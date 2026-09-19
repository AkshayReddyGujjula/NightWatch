"""FrameUploader encoding, budget and frozen-route tests (plan §11.7)."""

from __future__ import annotations

import builtins
import io
import os

import httpx
import pytest

from apps.contracts.base import sha256_hex
from apps.control_plane.app import create_app
from apps.control_plane.config import ControlSettings
from services.frames import (
    FrameBudgetExceeded,
    FrameEncodingError,
    FrameEncodingUnavailable,
    FrameStore,
    FrameUploader,
    FrameUploadError,
    FrameUploadRejected,
    encode_frame_image,
)
from tests.browser.helpers import IMAGE, RUN_ID, FakeSecondsClock, make_frame

TOKEN = "browser-uploader-token"


def _ack_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={"run_id": RUN_ID, "candidate_id": "B", "frame_seq": 0, "latest_seq": 0},
    )


def _uploader(
    clock: FakeSecondsClock,
    *,
    max_fps: float = 2.5,
    max_bytes_per_s: float = 800 * 1024,
) -> FrameUploader:
    return FrameUploader(
        "http://control.test",
        TOKEN,
        clock=clock,
        max_fps=max_fps,
        max_bytes_per_s=max_bytes_per_s,
        transport=httpx.MockTransport(_ack_handler),
    )


# ------------------------------------------------------------------ budget


async def test_fps_budget_fails_fast_with_typed_error() -> None:
    clock = FakeSecondsClock()
    uploader = _uploader(clock, max_fps=2.5, max_bytes_per_s=800 * 1024)
    frame = make_frame(0)
    assert (await uploader.post(frame, IMAGE)).run_id == RUN_ID
    await uploader.post(frame, IMAGE)
    with pytest.raises(FrameBudgetExceeded) as excinfo:
        await uploader.post(frame, IMAGE)
    assert excinfo.value.retry_after_s > 0
    # The bucket refills with the monotonic clock; no sleeping happens inside.
    clock.advance(1.0)
    await uploader.post(frame, IMAGE)


async def test_byte_budget_fails_fast_with_typed_error() -> None:
    clock = FakeSecondsClock()
    image = b"x" * 600
    frame = make_frame(0, image=image)
    uploader = _uploader(clock, max_fps=1000.0, max_bytes_per_s=1000.0)
    await uploader.post(frame, image)
    with pytest.raises(FrameBudgetExceeded):
        await uploader.post(frame, image)
    clock.advance(1.0)
    await uploader.post(frame, image)


async def test_mismatched_image_is_rejected_before_the_budget_is_spent() -> None:
    clock = FakeSecondsClock()
    uploader = _uploader(clock, max_fps=1.0)
    frame = make_frame(0)
    with pytest.raises(FrameUploadError):
        await uploader.post(frame, IMAGE + b"!")
    with pytest.raises(FrameUploadError):
        await uploader.post(frame, b"completely-different-bytes")
    # Nothing was uploaded, so the first real frame still fits the bucket.
    assert (await uploader.post(frame, IMAGE)).latest_seq == 0


# ------------------------------------------------------------- frozen route


async def test_uploader_posts_multipart_through_the_real_app_and_store() -> None:
    app = create_app(ControlSettings(frame_ingest_token=TOKEN), barrier_timeout_seconds=5.0)
    store = FrameStore(timeout_seconds=5.0)
    app.state.frames = store
    store.register_run(RUN_ID)
    transport = httpx.ASGITransport(app=app)

    uploader = FrameUploader("http://control.test", TOKEN, transport=transport)
    ack = await uploader.post(make_frame(7), IMAGE)
    assert (ack.run_id, ack.candidate_id, ack.frame_seq, ack.latest_seq) == (RUN_ID, "B", 7, 7)
    assert store.latest_seq(RUN_ID, "B") == 7
    assert store.latest(RUN_ID, "B") is not None

    rejected = FrameUploader("http://control.test", "wrong-token", transport=transport)
    with pytest.raises(FrameUploadRejected) as excinfo:
        await rejected.post(make_frame(7), IMAGE)
    assert excinfo.value.status_code == 401


# ----------------------------------------------------------------- encoding


def _noise_png(size: tuple[int, int] = (640, 480)) -> bytes:
    pytest.importorskip("PIL")
    from PIL import Image

    image = Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_encode_frame_image_reduces_under_the_cap() -> None:
    png = _noise_png()
    data, mime = encode_frame_image(png, max_bytes=20_000)
    assert mime == "image/jpeg"
    assert 0 < len(data) <= 20_000
    assert data[:2] == b"\xff\xd8"  # JPEG SOI marker


def test_encode_frame_image_raises_when_no_bounded_jpeg_exists() -> None:
    with pytest.raises(FrameEncodingError):
        encode_frame_image(_noise_png(), max_bytes=10)


def test_missing_pillow_raises_the_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("Pillow is not installed in this environment")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(FrameEncodingUnavailable):
        encode_frame_image(b"not-an-image")


async def test_uploader_round_trips_a_real_encoded_capture() -> None:
    png = _noise_png((320, 240))
    image, mime = encode_frame_image(png, max_bytes=50_000)
    frame = make_frame(0, image=image, image_mime=mime)
    assert frame.image_sha256 == sha256_hex(image)
    uploader = _uploader(FakeSecondsClock())
    ack = await uploader.post(frame, image)
    assert ack.frame_seq == 0
