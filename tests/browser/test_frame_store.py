"""FrameStore unit tests + drop-in HTTP test (plan §9.1, §11.7).

Unit coverage: strict ordering, unknown-run rejection, the bounded latest-frame
slot with ``after_seq``, barrier release/timeout/idempotency/session-hash and
bounded subscriber coalescing. The final test proves the drop-in swap: the real
app is built by ``create_app``, ``app.state.frames`` is replaced with the store,
and real multipart frames flow through the frozen route with a real TestClient.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from apps.contracts.base import sha256_hex
from apps.control_plane.app import create_app
from apps.control_plane.config import ControlSettings
from apps.control_plane.routes import (
    ReadySetMismatchError,
    SequenceRegressionError,
    SessionHashMismatchError,
    UnknownRunError,
)
from services.frames import FrameStore
from tests.browser.helpers import IMAGE, RUN_ID, make_frame, ready_body

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "expected"
HTTP_TOKEN = "browser-store-token"
HTTP_IMAGE = b"browser-store-http-frame-bytes"
HTTP_AUTH = {"Authorization": f"Bearer {HTTP_TOKEN}"}


# ------------------------------------------------------------------ frames


def test_frame_sequence_must_strictly_increase_per_candidate() -> None:
    store = FrameStore()
    store.register_run(RUN_ID)
    assert store.accept_frame(make_frame(0)).latest_seq == 0
    # Gaps are allowed: stale SAMPLE frames may be coalesced (plan §11.7).
    assert store.accept_frame(make_frame(5)).latest_seq == 5
    with pytest.raises(SequenceRegressionError):
        store.accept_frame(make_frame(5))
    with pytest.raises(SequenceRegressionError):
        store.accept_frame(make_frame(3))
    # Sequences are independent per candidate.
    assert store.accept_frame(make_frame(0, candidate_id="A")).latest_seq == 0
    assert store.latest_seq(RUN_ID, "A") == 0
    assert store.latest_seq(RUN_ID, "B") == 5


def test_frame_for_unknown_run_is_rejected() -> None:
    store = FrameStore()
    with pytest.raises(UnknownRunError):
        store.accept_frame(make_frame(0, run_id="run_never_registered"))
    with pytest.raises(UnknownRunError):
        store.subscribe("run_never_registered")
    assert store.latest("run_never_registered", "B") is None
    assert store.latest_seq("run_never_registered", "B") is None


def test_latest_slot_keeps_one_frame_and_honours_after_seq() -> None:
    store = FrameStore()
    store.register_run(RUN_ID)
    assert store.latest(RUN_ID, "B") is None
    store.accept_frame(make_frame(2), image=IMAGE)
    frame, image = store.latest(RUN_ID, "B")
    assert frame.frame_seq == 2
    assert image == IMAGE
    assert store.latest(RUN_ID, "B", after_seq=2) is None
    assert store.latest(RUN_ID, "B", after_seq=1) == (frame, IMAGE)
    store.accept_frame(make_frame(3), image=IMAGE)
    newer = store.latest(RUN_ID, "B", after_seq=2)
    assert newer is not None and newer[0].frame_seq == 3
    assert store.latest_seq(RUN_ID, "B") == 3
    # Metadata-only ingest records the frame but keeps no image bytes.
    store.accept_frame(make_frame(4))
    slot = store.latest(RUN_ID, "B")
    assert slot is not None and slot[0].frame_seq == 4 and slot[1] == b""


# ----------------------------------------------------------------- barrier


def test_barrier_releases_one_generation_when_all_expected_are_ready() -> None:
    store = FrameStore()
    store.register_run(RUN_ID)
    assert store.state(RUN_ID).status == "PENDING"
    assert store.mark_ready("A", ready_body("A")).status == "PENDING"
    assert store.mark_ready("B", ready_body("B")).status == "PENDING"
    released = store.mark_ready("C", ready_body("C"))
    assert released.status == "RELEASED"
    assert released.generation == 1
    assert released.released_at_utc is not None
    assert released.deadline_at_utc is not None
    assert sorted(world.candidate_id for world in released.ready) == ["A", "B", "C"]


def test_barrier_ready_is_idempotent_per_candidate() -> None:
    store = FrameStore()
    store.register_run(RUN_ID)
    store.mark_ready("A", ready_body("A"))
    store.mark_ready("B", ready_body("B"))
    again = store.mark_ready("A", ready_body("A"))
    assert again.status == "PENDING"
    assert sorted(world.candidate_id for world in again.ready) == ["A", "B"]
    store.mark_ready("C", ready_body("C"))
    replayed = store.mark_ready("A", ready_body("A"))
    assert replayed.status == "RELEASED"
    assert replayed.generation == 1


def test_barrier_rejects_session_hash_mismatch() -> None:
    store = FrameStore()
    store.register_run(RUN_ID)
    body = ready_body("A").model_copy(update={"session_hash": "b" * 64})
    with pytest.raises(SessionHashMismatchError):
        store.mark_ready("A", body)


def test_barrier_rejects_unexpected_candidate() -> None:
    store = FrameStore()
    store.register_run(RUN_ID)
    store.expect(RUN_ID, ["A", "B"])
    with pytest.raises(ReadySetMismatchError):
        store.mark_ready("C", ready_body("C"))


def test_barrier_timeout_is_typed_and_terminal() -> None:
    store = FrameStore(timeout_seconds=0.02)
    store.register_run(RUN_ID)
    time.sleep(0.04)
    timed_out = store.state(RUN_ID)
    assert timed_out.status == "TIMEOUT"
    assert timed_out.timed_out_at_utc is not None
    # A late readiness post does not resurrect a timed-out barrier.
    late = store.mark_ready("A", ready_body("A"))
    assert late.status == "TIMEOUT"


# ---------------------------------------------------------------- fan-out


async def test_fan_out_coalesces_unread_samples() -> None:
    store = FrameStore()
    store.register_run(RUN_ID)
    stream = store.subscribe(RUN_ID)
    store.accept_frame(make_frame(0))
    store.accept_frame(make_frame(1))
    first = await asyncio.wait_for(anext(stream), 1.0)
    assert first.frame_seq == 1  # the unread older SAMPLE was replaced
    store.accept_frame(make_frame(2))
    second = await asyncio.wait_for(anext(stream), 1.0)
    assert second.frame_seq == 2
    await stream.aclose()


async def test_fan_out_never_displaces_keyframes_with_samples() -> None:
    store = FrameStore()
    store.register_run(RUN_ID)
    stream = store.subscribe(RUN_ID)
    store.accept_frame(make_frame(0, phase="BEFORE_ACTION"))
    store.accept_frame(make_frame(1, phase="SAMPLE"))
    first = await asyncio.wait_for(anext(stream), 1.0)
    assert (first.frame_seq, first.phase) == (0, "BEFORE_ACTION")
    store.accept_frame(make_frame(2, phase="AFTER_ACTION"))
    second = await asyncio.wait_for(anext(stream), 1.0)
    assert (second.frame_seq, second.phase) == (2, "AFTER_ACTION")
    await stream.aclose()


async def test_close_ends_every_subscriber_and_rejects_new_ones() -> None:
    store = FrameStore()
    store.register_run(RUN_ID)
    first = store.subscribe(RUN_ID)
    second = store.subscribe(RUN_ID)
    store.close()
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(first), 1.0)
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(second), 1.0)
    with pytest.raises(RuntimeError):
        store.subscribe(RUN_ID)


# ------------------------------------------------------------ HTTP swap


def http_metadata(seq: int, **overrides: Any) -> dict[str, Any]:
    payload = json.loads((FIXTURES / "internal_frames_metadata.json").read_text())
    payload.update(
        {
            "run_id": RUN_ID,
            "candidate_id": "B",
            "frame_seq": seq,
            "image_size_bytes": len(HTTP_IMAGE),
            "image_sha256": sha256_hex(HTTP_IMAGE),
            "image_mime": "image/jpeg",
        }
    )
    payload.update(overrides)
    return payload


def post_http_frame(
    client: TestClient, metadata: dict[str, Any], *, auth: dict[str, str] = HTTP_AUTH
) -> Any:
    return client.post(
        "/internal/frames",
        data={"metadata": json.dumps(metadata)},
        files={"image": ("frame.jpg", HTTP_IMAGE, "image/jpeg")},
        headers=auth,
    )


def test_store_is_a_drop_in_replacement_for_the_reference_sink() -> None:
    app = create_app(ControlSettings(frame_ingest_token=HTTP_TOKEN), barrier_timeout_seconds=5.0)
    store = FrameStore(timeout_seconds=5.0)
    app.state.frames = store
    store.register_run(RUN_ID)

    with TestClient(app) as client:
        accepted = post_http_frame(client, http_metadata(0))
        assert accepted.status_code == 200
        assert accepted.json() == {
            "run_id": RUN_ID,
            "candidate_id": "B",
            "frame_seq": 0,
            "latest_seq": 0,
        }
        assert post_http_frame(client, http_metadata(0)).status_code == 409
        unknown = http_metadata(1, run_id="run_never_registered")
        assert post_http_frame(client, unknown).status_code == 404

        pending = client.get(f"/internal/runs/{RUN_ID}/browser-barrier", headers=HTTP_AUTH)
        assert pending.status_code == 200
        assert pending.json()["status"] == "PENDING"

        released = None
        for candidate in ("A", "B", "C"):
            released = client.post(
                f"/internal/worlds/{candidate}/browser-ready",
                json=ready_body(candidate).model_dump(mode="json"),
                headers=HTTP_AUTH,
            )
            assert released.status_code == 200
        assert released is not None and released.json()["status"] == "RELEASED"

        readback = client.get(f"/internal/runs/{RUN_ID}/browser-barrier", headers=HTTP_AUTH)
        assert readback.status_code == 200
        body = readback.json()
        assert body["status"] == "RELEASED"
        assert body["generation"] == 1
        assert sorted(world["candidate_id"] for world in body["ready"]) == ["A", "B", "C"]

    assert store.latest_seq(RUN_ID, "B") == 0
    # HTTP ingest forwards the validated image into the bounded byte slot.
    slot = store.latest(RUN_ID, "B")
    assert slot is not None
    assert slot[0].image_sha256 == sha256_hex(HTTP_IMAGE)
    assert slot[1] == HTTP_IMAGE
