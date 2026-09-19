"""Track B frame pipeline: trusted store, uploader and cadence sampler (plan §11.7)."""

from __future__ import annotations

from services.frames.sampler import CaptureResult, FrameSampler, SampledFrame
from services.frames.store import FrameStore
from services.frames.uploader import (
    FrameBudgetExceeded,
    FrameEncodingError,
    FrameEncodingUnavailable,
    FrameUploader,
    FrameUploadError,
    FrameUploadRejected,
    encode_frame_image,
)

__all__ = [
    "CaptureResult",
    "FrameBudgetExceeded",
    "FrameEncodingError",
    "FrameEncodingUnavailable",
    "FrameSampler",
    "FrameStore",
    "FrameUploadError",
    "FrameUploadRejected",
    "FrameUploader",
    "SampledFrame",
    "encode_frame_image",
]
