"""Trusted frame store: latest-frame slots, browser barrier and SSE fan-out.

Track B implementation behind the frozen ``POST /internal/frames`` and browser
barrier routes (plan §9.1, §11.7, §12.2). It is a drop-in replacement for the
development :class:`apps.control_plane.routes.ReferenceSink`: the same public
surface, the same error classes imported from the control plane, and the same
observable semantics. On top of that it keeps the newest ``BrowserFrame``
metadata plus its image bytes in one in-memory slot per ``(run, candidate)`` —
bytes never reach SQLite — and fans frame metadata out to bounded subscribers.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from apps.contracts.base import CandidateId
from apps.contracts.browser import (
    BarrierStatus,
    BrowserBarrierState,
    BrowserFrame,
    BrowserReadyRequest,
    FrameIngestAck,
    ReadyWorld,
)
from apps.control_plane.routes import (
    DEFAULT_BARRIER_TIMEOUT_SECONDS,
    DEFAULT_EXPECTED_CANDIDATES,
    ReadySetMismatchError,
    SequenceRegressionError,
    SessionHashMismatchError,
    UnknownRunError,
    world_session_hash,
)

__all__ = ["FrameStore"]


class _CloseSentinel:
    """Queue marker that ends one subscriber (the type keeps the queue typed)."""


_CLOSED = _CloseSentinel()


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class _LatestFrame:
    """The bounded per ``(run, candidate)`` slot: metadata plus image bytes."""

    frame: BrowserFrame
    image: bytes


@dataclass
class _RunState:
    """Per-run state mirroring the reference sink, plus the frame slot/fan-out."""

    expected: list[CandidateId]
    latest_frame_seq: dict[CandidateId, int] = field(default_factory=dict)
    latest: dict[CandidateId, _LatestFrame] = field(default_factory=dict)
    ready: dict[CandidateId, ReadyWorld] = field(default_factory=dict)
    subscribers: set[asyncio.Queue[BrowserFrame | _CloseSentinel]] = field(default_factory=set)
    status: BarrierStatus = "PENDING"
    generation: int = 0
    timeout_seconds: float = DEFAULT_BARRIER_TIMEOUT_SECONDS
    deadline_monotonic: float | None = None
    deadline_at_utc: datetime | None = None
    released_at_utc: datetime | None = None
    timed_out_at_utc: datetime | None = None


class FrameStore:
    """In-memory latest-frame store + browser barrier for one control plane.

    Behaviour that is part of the frozen contract (identical to
    :class:`~apps.control_plane.routes.ReferenceSink`):

    - frame sequences are strictly increasing per ``(run_id, candidate_id)``;
    - a frame for an unregistered run is rejected (never falls through to a
      prior run);
    - the barrier releases one generation when every expected candidate is
      ready, or reports a typed ``TIMEOUT`` after ``timeout_seconds``;
    - readiness is idempotent per candidate and bound to its session hash.

    Additional Track B behaviour:

    - ``accept_frame(..., image=...)`` keeps the newest frame metadata and its
      image bytes in one bounded slot per ``(run, candidate)``. The frozen HTTP
      route currently ingests metadata only, so an HTTP-ingested frame stores
      empty bytes; in-process callers can pass ``image=`` to keep the bytes.
    - :meth:`subscribe` yields frame metadata to bounded subscribers; the queue
      holds one frame and an unread ``SAMPLE`` is coalesced, never blocking the
      ingest path. ``BEFORE_ACTION``/``AFTER_ACTION``/``TERMINAL`` keyframes are
      never displaced by a droppable ``SAMPLE``.
    """

    def __init__(self, *, timeout_seconds: float = DEFAULT_BARRIER_TIMEOUT_SECONDS) -> None:
        self.timeout_seconds = timeout_seconds
        self.runs: dict[str, _RunState] = {}
        self._closed = False

    # -- run registration ---------------------------------------------------

    def register_run(self, run_id: str, candidates: Sequence[CandidateId] | None = None) -> None:
        """Create (or reset) the barrier state and frame slots for a run."""
        self.runs[run_id] = _RunState(
            expected=list(candidates or DEFAULT_EXPECTED_CANDIDATES),
            timeout_seconds=self.timeout_seconds,
            deadline_monotonic=time.monotonic() + self.timeout_seconds,
            deadline_at_utc=_utcnow() + timedelta(seconds=self.timeout_seconds),
        )

    def expect(self, run_id: str, candidates: Sequence[CandidateId]) -> None:
        """Set the expected candidate set without touching recorded state."""
        state = self._get_or_create(run_id)
        state.expected = list(candidates)

    # -- frames --------------------------------------------------------------

    def accept_frame(self, frame: BrowserFrame, image: bytes | None = None) -> FrameIngestAck:
        """Record one frame; strict sequence order, gaps allowed (plan §11.7)."""
        state = self.runs.get(frame.run_id)
        if state is None:
            raise UnknownRunError(frame.run_id)
        latest = state.latest_frame_seq.get(frame.candidate_id, -1)
        if frame.frame_seq <= latest:
            raise SequenceRegressionError(
                f"frame_seq {frame.frame_seq} is not newer than recorded {latest}"
            )
        state.latest_frame_seq[frame.candidate_id] = frame.frame_seq
        state.latest[frame.candidate_id] = _LatestFrame(
            frame=frame, image=image if image is not None else b""
        )
        self._publish(state, frame)
        return FrameIngestAck(
            run_id=frame.run_id,
            candidate_id=frame.candidate_id,
            frame_seq=frame.frame_seq,
            latest_seq=frame.frame_seq,
        )

    def latest(
        self, run_id: str, candidate_id: CandidateId, after_seq: int | None = None
    ) -> tuple[BrowserFrame, bytes] | None:
        """Newest frame slot, or ``None`` when missing/not newer than ``after_seq``.

        The bytes are empty when the slot was filled through the metadata-only
        HTTP ingest path (the frozen route validates but does not forward the
        image part to the sink).
        """
        state = self.runs.get(run_id)
        if state is None:
            return None
        slot = state.latest.get(candidate_id)
        if slot is None:
            return None
        if after_seq is not None and slot.frame.frame_seq <= after_seq:
            return None
        return slot.frame, slot.image

    def latest_seq(self, run_id: str, candidate_id: CandidateId) -> int | None:
        """Newest recorded ``frame_seq`` for one slot, or ``None`` when absent."""
        state = self.runs.get(run_id)
        if state is None:
            return None
        return state.latest_frame_seq.get(candidate_id)

    # -- SSE fan-out ---------------------------------------------------------

    def subscribe(self, run_id: str) -> AsyncIterator[BrowserFrame]:
        """Yield frame metadata for one run over a bounded one-frame queue.

        Raises :class:`UnknownRunError` for an unregistered run and
        :class:`RuntimeError` after :meth:`close`. Subscribers that do not read
        fast enough lose older ``SAMPLE`` frames; keyframes are never displaced
        by a droppable ``SAMPLE``.
        """
        if self._closed:
            raise RuntimeError("frame store is closed")
        state = self.runs.get(run_id)
        if state is None:
            raise UnknownRunError(run_id)
        # Register the bounded queue eagerly so frames accepted between
        # ``subscribe`` and the first ``anext`` are not lost.
        queue: asyncio.Queue[BrowserFrame | _CloseSentinel] = asyncio.Queue(maxsize=1)
        state.subscribers.add(queue)
        return self._drain(state, queue)

    async def _drain(
        self, state: _RunState, queue: asyncio.Queue[BrowserFrame | _CloseSentinel]
    ) -> AsyncIterator[BrowserFrame]:
        try:
            while True:
                item = await queue.get()
                if isinstance(item, _CloseSentinel):
                    return
                yield item
        finally:
            state.subscribers.discard(queue)

    def close(self) -> None:
        """End every subscriber and reject new subscriptions."""
        if self._closed:
            return
        self._closed = True
        for state in self.runs.values():
            for queue in list(state.subscribers):
                _force_put(queue, _CLOSED)

    def _publish(self, state: _RunState, frame: BrowserFrame) -> None:
        for queue in list(state.subscribers):
            if queue.full():
                dropped = queue.get_nowait()
                if isinstance(dropped, _CloseSentinel):
                    # A closed subscriber never resurrects.
                    queue.put_nowait(dropped)
                    continue
                if dropped.phase != "SAMPLE" and frame.phase == "SAMPLE":
                    # Never displace an unread keyframe with a droppable SAMPLE.
                    queue.put_nowait(dropped)
                    continue
            queue.put_nowait(frame)

    # -- barrier -------------------------------------------------------------

    def mark_ready(
        self, candidate_id: CandidateId, body: BrowserReadyRequest
    ) -> BrowserBarrierState:
        expected_hash = world_session_hash(
            body.run_id, candidate_id, body.sandbox_id, body.cua_session_id
        )
        if body.session_hash != expected_hash:
            raise SessionHashMismatchError("session_hash does not bind this world session")
        state = self._get_or_create(body.run_id)
        if candidate_id not in state.expected:
            raise ReadySetMismatchError(
                f"candidate {candidate_id} is not part of the expected barrier set"
            )
        state.ready[candidate_id] = ReadyWorld(
            candidate_id=candidate_id,
            sandbox_id=body.sandbox_id,
            session_hash=body.session_hash,
        )
        if state.status == "PENDING" and set(state.expected) <= set(state.ready):
            state.status = "RELEASED"
            state.generation += 1
            state.released_at_utc = _utcnow()
        return self.state(body.run_id)

    def state(self, run_id: str) -> BrowserBarrierState:
        state = self._get_or_create(run_id)
        self._refresh_timeout(state)
        return BrowserBarrierState(
            run_id=run_id,
            generation=state.generation,
            expected_candidates=list(state.expected),
            ready=list(state.ready.values()),
            status=state.status,
            timeout_seconds=state.timeout_seconds,
            deadline_at_utc=state.deadline_at_utc,
            released_at_utc=state.released_at_utc,
            timed_out_at_utc=state.timed_out_at_utc,
        )

    # -- internals -----------------------------------------------------------

    def _get_or_create(self, run_id: str) -> _RunState:
        state = self.runs.get(run_id)
        if state is None:
            self.register_run(run_id)
            state = self.runs[run_id]
        return state

    def _refresh_timeout(self, state: _RunState) -> None:
        if (
            state.status == "PENDING"
            and state.deadline_monotonic is not None
            and time.monotonic() > state.deadline_monotonic
        ):
            state.status = "TIMEOUT"
            state.timed_out_at_utc = _utcnow()


def _force_put(
    queue: asyncio.Queue[BrowserFrame | _CloseSentinel], item: BrowserFrame | _CloseSentinel
) -> None:
    """Replace whatever a subscriber has not read yet with ``item``."""
    while True:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            break
    queue.put_nowait(item)
