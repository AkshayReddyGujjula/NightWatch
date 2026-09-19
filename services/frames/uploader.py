"""Frame uploader: bounded JPEG/WebP encoding plus a local rate budget (plan §11.7).

The uploader posts the strict multipart contract (``metadata`` part = strict
``BrowserFrame`` JSON, ``image`` part = binary with the declared MIME) to
``POST /internal/frames`` with the scoped runner bearer token. A monotonic-clock
token bucket enforces the 2.5 fps / 800 KB/s per-world budget locally and fails
fast with a typed error instead of sleeping: the caller drops the frame.
"""

from __future__ import annotations

import io
import time
from collections.abc import Callable

import httpx

from apps.contracts.base import sha256_hex
from apps.contracts.browser import MAX_FRAME_BYTES, BrowserFrame, FrameIngestAck

__all__ = [
    "FrameBudgetExceeded",
    "FrameEncodingError",
    "FrameEncodingUnavailable",
    "FrameUploadError",
    "FrameUploadRejected",
    "FrameUploader",
    "encode_frame_image",
]


class FrameEncodingError(RuntimeError):
    """A captured image could not be decoded or reduced under the byte cap."""


class FrameEncodingUnavailable(FrameEncodingError):
    """Pillow is not importable, so frame encoding cannot run at all."""


class FrameUploadError(RuntimeError):
    """A frame upload failed locally or was rejected by the control plane."""


class FrameBudgetExceeded(FrameUploadError):
    """The local fps/byte budget was already spent for this instant."""

    def __init__(self, message: str, *, retry_after_s: float) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


class FrameUploadRejected(FrameUploadError):
    """The control plane answered with a non-success status."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"frame ingest rejected with status {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


def encode_frame_image(png_bytes: bytes, *, max_bytes: int = MAX_FRAME_BYTES) -> tuple[bytes, str]:
    """Encode a capture as JPEG no larger than ``max_bytes`` (plan §11.7).

    Quality is reduced first, then the image is scaled down, until the encoded
    JPEG fits. Raises :class:`FrameEncodingUnavailable` when Pillow is missing
    and :class:`FrameEncodingError` when the input is not decodable or no
    bounded JPEG can be produced.
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - exercised only without Pillow
        raise FrameEncodingUnavailable("Pillow is required to encode frame images") from exc

    try:
        with Image.open(io.BytesIO(png_bytes)) as opened:
            opened.load()
            base = opened.convert("RGB")
    except (OSError, ValueError) as exc:
        raise FrameEncodingError("could not decode the capture image") from exc

    scale = 1.0
    for _ in range(6):
        if scale >= 1.0:
            working = base
        else:
            size = (max(1, int(base.width * scale)), max(1, int(base.height * scale)))
            working = base.resize(size, Image.Resampling.LANCZOS)
        for quality in (85, 70, 55, 40):
            buffer = io.BytesIO()
            working.save(buffer, format="JPEG", quality=quality, optimize=True)
            data = buffer.getvalue()
            if len(data) <= max_bytes:
                return data, "image/jpeg"
        scale *= 0.7
    raise FrameEncodingError(f"could not encode the capture under {max_bytes} bytes")


class _TokenBucket:
    """Continuous-refill bucket; ``available`` reports the wait needed, if any."""

    def __init__(self, *, rate: float, capacity: float, clock: Callable[[], float]) -> None:
        if rate <= 0 or capacity <= 0:
            raise ValueError("rate and capacity must be positive")
        self._rate = rate
        self._capacity = capacity
        self._clock = clock
        self._tokens = capacity
        self._updated = clock()

    def _refill(self, now: float) -> None:
        elapsed = now - self._updated
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._updated = now

    def available(self, amount: float, now: float) -> float:
        """Seconds until ``amount`` tokens exist; ``0.0`` when already available."""
        self._refill(now)
        if self._tokens >= amount:
            return 0.0
        return (amount - self._tokens) / self._rate

    def take(self, amount: float, now: float) -> None:
        self._refill(now)
        self._tokens -= amount


class FrameUploader:
    """Posts frames to ``POST /internal/frames`` under a local rate budget."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout_s: float = 2.0,
        max_fps: float = 2.5,
        max_bytes_per_s: float = 800 * 1024,
        clock: Callable[[], float] = time.monotonic,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url must not be empty")
        if not token:
            raise ValueError("token must not be empty")
        if timeout_s <= 0 or max_fps <= 0 or max_bytes_per_s <= 0:
            raise ValueError("timeout_s, max_fps and max_bytes_per_s must be positive")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_s = timeout_s
        self.max_fps = max_fps
        self.max_bytes_per_s = max_bytes_per_s
        self._clock = clock
        self._transport = transport
        self._fps_bucket = _TokenBucket(rate=max_fps, capacity=max_fps, clock=clock)
        self._byte_bucket = _TokenBucket(
            rate=max_bytes_per_s, capacity=max_bytes_per_s, clock=clock
        )

    async def post(self, frame: BrowserFrame, image: bytes) -> FrameIngestAck:
        """Upload one frame; raises typed errors and never sleeps for budget."""
        if len(image) != frame.image_size_bytes:
            raise FrameUploadError(
                f"image is {len(image)} bytes, metadata declares {frame.image_size_bytes}"
            )
        if sha256_hex(image) != frame.image_sha256:
            raise FrameUploadError("image_sha256 does not match the uploaded bytes")

        now = self._clock()
        retry_after = max(
            self._fps_bucket.available(1.0, now),
            self._byte_bucket.available(float(len(image)), now),
        )
        if retry_after > 0:
            raise FrameBudgetExceeded(
                f"local frame budget exceeded (max_fps={self.max_fps}, "
                f"max_bytes_per_s={self.max_bytes_per_s}); drop the frame",
                retry_after_s=retry_after,
            )
        self._fps_bucket.take(1.0, now)
        self._byte_bucket.take(float(len(image)), now)

        extension = "jpg" if frame.image_mime == "image/jpeg" else "webp"
        url = f"{self.base_url}/internal/frames"
        files = {"image": (f"frame.{extension}", image, frame.image_mime)}
        headers = {"Authorization": f"Bearer {self.token}"}
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_s, transport=self._transport
            ) as client:
                response = await client.post(
                    url, data={"metadata": frame.model_dump_json()}, files=files, headers=headers
                )
        except httpx.HTTPError as exc:
            raise FrameUploadError(f"frame upload failed: {exc}") from exc

        if not 200 <= response.status_code < 300:
            raise FrameUploadRejected(response.status_code, response.text[:300])
        try:
            return FrameIngestAck.model_validate_json(response.text, strict=True)
        except ValueError as exc:
            raise FrameUploadError("frame ingest returned an invalid ack body") from exc
