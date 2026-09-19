"""FrameSampler cadence, freshness and action-pause tests (plan §11.7)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import pytest

from services.frames import CaptureResult, FrameSampler, SampledFrame
from tests.browser.helpers import FakeNsClock


class FakeCapture:
    """Async capture callable whose timestamps advance a fake nanosecond clock."""

    def __init__(self, clock: FakeNsClock, *, step_ns: int = 600_000_000) -> None:
        self.clock = clock
        self.step_ns = step_ns
        self.calls = 0

    async def __call__(self) -> CaptureResult:
        self.calls += 1
        captured_ns = self.clock()
        self.clock.advance_ns(self.step_ns)
        return CaptureResult(
            image=f"frame-{self.calls}".encode(),
            captured_monotonic_ns=captured_ns,
            snapshot_id=f"snap-{self.calls}",
            capture_id=None,
            mime="image/jpeg",
        )


def collector() -> tuple[list[SampledFrame], Callable[[SampledFrame], Awaitable[None]]]:
    published: list[SampledFrame] = []

    async def publish(frame: SampledFrame) -> None:
        published.append(frame)

    return published, publish


async def _wait_for(predicate: Callable[[], bool], *, timeout_s: float = 3.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition was not met in time")
        await asyncio.sleep(0.001)


async def test_sampler_assigns_increasing_sequences_and_measures_fps() -> None:
    clock = FakeNsClock()
    capture = FakeCapture(clock)
    published, publish = collector()
    sampler = FrameSampler(capture, publish, clock=clock, min_fps=1.0, target_fps=2.0)

    task = asyncio.create_task(sampler.run())
    await _wait_for(lambda: len(published) >= 3)
    sampler.stop()
    await asyncio.wait_for(task, 1.0)

    assert [frame.frame_seq for frame in published[:3]] == [0, 1, 2]
    assert all(frame.phase == "SAMPLE" for frame in published)
    assert sampler.published_count == len(published)
    # Captures are 0.6 s apart on the capture clock, so the measured rate must
    # come from captured_monotonic_ns, not the loop's sleep cadence.
    assert sampler.fps() == pytest.approx(1_000_000_000 / 600_000_000)
    assert not sampler.running


async def test_stale_capture_is_dropped_and_never_satisfies_cadence() -> None:
    clock = FakeNsClock()
    stamps = iter([2_000_000_000, 2_000_000_000, 2_500_000_000])
    calls = 0

    async def capture() -> CaptureResult:
        nonlocal calls
        calls += 1
        return CaptureResult(
            image=b"x",
            captured_monotonic_ns=next(stamps, 2_500_000_000),
            snapshot_id=f"snap-{calls}",
            capture_id=None,
            mime="image/jpeg",
        )

    published, publish = collector()
    sampler = FrameSampler(capture, publish, clock=clock, min_fps=1.0, target_fps=50.0)

    task = asyncio.create_task(sampler.run())
    await _wait_for(lambda: len(published) >= 2)
    sampler.stop()
    await asyncio.wait_for(task, 1.0)

    assert [frame.frame_seq for frame in published] == [0, 1]
    assert [frame.capture.captured_monotonic_ns for frame in published] == [
        2_000_000_000,
        2_500_000_000,
    ]
    assert sampler.stale_dropped >= 1
    assert sampler.fps() == pytest.approx(2.0)


async def test_pause_for_action_freezes_sampling_until_released() -> None:
    clock = FakeNsClock()
    capture = FakeCapture(clock)
    published, publish = collector()
    sampler = FrameSampler(capture, publish, clock=clock, min_fps=1.0, target_fps=50.0)

    async with sampler.pause_for_action():
        task = asyncio.create_task(sampler.run())
        await asyncio.sleep(0.05)
        assert capture.calls == 0
        assert published == []

    await _wait_for(lambda: len(published) >= 1)
    sampler.stop()
    await asyncio.wait_for(task, 1.0)
    assert capture.calls >= 1


async def test_stop_interrupts_the_idle_sleep_promptly() -> None:
    clock = FakeNsClock()
    capture = FakeCapture(clock, step_ns=100_000_000)
    published, publish = collector()
    sampler = FrameSampler(capture, publish, clock=clock, min_fps=1.0, target_fps=1.0)

    task = asyncio.create_task(sampler.run())
    await _wait_for(lambda: len(published) >= 1)
    started = asyncio.get_running_loop().time()
    sampler.stop()
    await asyncio.wait_for(task, 0.5)
    # Without the stop-event wakeup the loop would sleep the remaining ~0.9 s.
    assert asyncio.get_running_loop().time() - started < 0.4


def test_sampler_rejects_rates_outside_the_frozen_envelope() -> None:
    clock = FakeNsClock()

    async def capture() -> CaptureResult:  # pragma: no cover - construction only
        raise AssertionError("not called")

    async def publish(frame: SampledFrame) -> None:  # pragma: no cover - construction only
        raise AssertionError("not called")

    with pytest.raises(ValueError):
        FrameSampler(capture, publish, clock=clock, min_fps=1.0, target_fps=0.5)
    with pytest.raises(ValueError):
        FrameSampler(capture, publish, clock=clock, min_fps=0.0, target_fps=2.0)
    with pytest.raises(ValueError):
        FrameSampler(capture, publish, clock=clock, start_seq=-1)
