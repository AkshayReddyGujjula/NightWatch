"""Cadence sampler for the concurrent visual evidence stream (plan §11.7).

The sampler drives ``get_browser_state(include_screenshot=true)`` captures at the
target cadence, assigns strictly increasing ``frame_seq`` values and drops stale
captures so an old screenshot can never satisfy the freshness requirement. The
action loop freezes sampling with :meth:`FrameSampler.pause_for_action` between
accepting a snapshot-bound decision and completing the matching CUA action.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from apps.contracts.browser import FramePhase

__all__ = ["CaptureResult", "FrameSampler", "SampledFrame"]


@dataclass(frozen=True)
class CaptureResult:
    """One CUA capture: image bytes plus the identity of the same call.

    ``captured_monotonic_ns`` is the freshness key: a capture that is not
    strictly newer than the last published one is dropped.
    """

    image: bytes
    captured_monotonic_ns: int
    snapshot_id: str
    capture_id: str | None
    mime: str


@dataclass(frozen=True)
class SampledFrame:
    """A freshly published sample handed to the ``publish`` callable."""

    frame_seq: int
    capture: CaptureResult
    phase: FramePhase = "SAMPLE"


CaptureFn = Callable[[], Awaitable[CaptureResult]]
PublishFn = Callable[[SampledFrame], Awaitable[None]]


class FrameSampler:
    """Publishes fresh captures at the target cadence until :meth:`stop`.

    ``capture`` and ``publish`` are async callables supplied by the runner; the
    sampler itself owns only cadence, freshness, sequence numbering, the
    measured FPS window and the shared action-pause lock. It is single-run:
    :meth:`run` is awaited by one task, and calling it again after ``stop``
    starts a fresh window (sequence numbering continues unless ``start_seq``
    was supplied).
    """

    def __init__(
        self,
        capture: CaptureFn,
        publish: PublishFn,
        *,
        min_fps: float = 1.0,
        target_fps: float = 2.0,
        clock: Callable[[], int] = time.monotonic_ns,
        start_seq: int = 0,
        fps_window: int = 32,
    ) -> None:
        if min_fps <= 0:
            raise ValueError("min_fps must be positive")
        if target_fps < min_fps:
            raise ValueError("target_fps must be at least min_fps")
        if start_seq < 0:
            raise ValueError("start_seq must be non-negative")
        if fps_window < 2:
            raise ValueError("fps_window must be at least 2")
        self.min_fps = min_fps
        self.target_fps = target_fps
        self.clock = clock
        self._capture = capture
        self._publish = publish
        self._next_seq = start_seq
        self._last_published_ns: int | None = None
        self._published_ns: deque[int] = deque(maxlen=fps_window)
        self._published_count = 0
        self._stale_dropped = 0
        self._running = False
        self._stop_event = asyncio.Event()
        self._pause_lock = asyncio.Lock()

    # -- observability -------------------------------------------------------

    @property
    def published_count(self) -> int:
        return self._published_count

    @property
    def stale_dropped(self) -> int:
        return self._stale_dropped

    @property
    def running(self) -> bool:
        return self._running

    def fps(self) -> float:
        """Measured rate from published capture timestamps (0.0 until two exist)."""
        samples = self._published_ns
        if len(samples) < 2:
            return 0.0
        span_ns = samples[-1] - samples[0]
        if span_ns <= 0:
            return 0.0
        return (len(samples) - 1) * 1_000_000_000 / span_ns

    # -- control -------------------------------------------------------------

    def pause_for_action(self) -> asyncio.Lock:
        """Lock the action loop holds while a snapshot-bound action is in flight."""
        return self._pause_lock

    def stop(self) -> None:
        """Request loop exit; the sleep between samples is interrupted promptly."""
        self._stop_event.set()

    async def run(self) -> None:
        """Sample until :meth:`stop`; capture/publish errors propagate honestly."""
        if self._running:
            raise RuntimeError("sampler is already running")
        self._running = True
        self._stop_event.clear()
        interval_s = 1.0 / self.target_fps
        try:
            while not self._stop_event.is_set():
                started_ns = self.clock()
                async with self._pause_lock:
                    if self._stop_event.is_set():
                        break
                    capture = await self._capture()
                frame = self._accept(capture)
                if frame is not None:
                    await self._publish(frame)
                remaining_s = interval_s - (self.clock() - started_ns) / 1_000_000_000
                if remaining_s > 0:
                    await self._sleep(remaining_s)
                else:
                    # A capture that outran the interval (or an instant capture
                    # callable) must still yield: never busy-spin the loop.
                    await asyncio.sleep(0)
        finally:
            self._running = False

    # -- internals -----------------------------------------------------------

    async def _sleep(self, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)

    def _accept(self, capture: CaptureResult) -> SampledFrame | None:
        if (
            self._last_published_ns is not None
            and capture.captured_monotonic_ns <= self._last_published_ns
        ):
            self._stale_dropped += 1
            return None
        self._last_published_ns = capture.captured_monotonic_ns
        self._published_ns.append(capture.captured_monotonic_ns)
        self._published_count += 1
        frame = SampledFrame(frame_seq=self._next_seq, capture=capture)
        self._next_seq += 1
        return frame
