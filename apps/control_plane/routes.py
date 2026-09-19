"""Internal control-plane routes for the frozen frame/barrier HTTP contract.

Plan §9.1, §11.7, §32.3. Track A owns these routes; Track B owns the trusted
implementation in ``services/frames/**``. The in-memory :class:`ReferenceSink`
below is a development stand-in for that implementation: it preserves the
observable contract (validation, ordering, barrier semantics) and must be
swapped for Track B's store at integration without changing the wire shapes.
"""

from __future__ import annotations

import hmac
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from pydantic import ValidationError

from apps.contracts.base import CandidateId, sha256_hex
from apps.contracts.browser import (
    MAX_FRAME_BYTES,
    BarrierStatus,
    BrowserBarrierState,
    BrowserFrame,
    BrowserReadyRequest,
    FrameIngestAck,
    ReadyWorld,
)

router = APIRouter()

DEFAULT_EXPECTED_CANDIDATES: tuple[CandidateId, ...] = ("A", "B", "C")
DEFAULT_BARRIER_TIMEOUT_SECONDS = 120.0

_FRAME_READ_CHUNK = 64 * 1024


def _utcnow() -> datetime:
    return datetime.now(UTC)


class UnknownRunError(LookupError):
    """Frame ingest for a run the control plane does not know about."""


class SequenceRegressionError(ValueError):
    """A frame arrived that is not strictly newer than the last recorded one."""


class ReadySetMismatchError(ValueError):
    """A readiness post that does not match the expected barrier membership."""


class SessionHashMismatchError(ValueError):
    """A readiness post whose session_hash does not bind its own identifiers."""


def world_session_hash(run_id: str, candidate_id: str, sandbox_id: str, cua_session_id: str) -> str:
    """Canonical session binding hash for :class:`BrowserReadyRequest` (plan §9.1)."""
    material = f"{run_id}|{candidate_id}|{sandbox_id}|{cua_session_id}".encode()
    return sha256_hex(material)


@dataclass
class _RunState:
    """Per-run reference state: latest frame sequence, readiness, barrier status."""

    expected: list[CandidateId]
    latest_frame_seq: dict[CandidateId, int] = field(default_factory=dict)
    ready: dict[CandidateId, ReadyWorld] = field(default_factory=dict)
    status: BarrierStatus = "PENDING"
    generation: int = 0
    timeout_seconds: float = DEFAULT_BARRIER_TIMEOUT_SECONDS
    deadline_monotonic: float | None = None
    deadline_at_utc: datetime | None = None
    released_at_utc: datetime | None = None
    timed_out_at_utc: datetime | None = None


class ReferenceSink:
    """In-memory frame slot + browser barrier (development reference only).

    Behaviour that is part of the frozen contract:

    - frame sequences are strictly increasing per ``(run_id, candidate_id)``;
    - a frame for an unregistered run is rejected (never falls through to a
      prior run);
    - the barrier releases one generation when every expected candidate is
      ready, or reports a typed ``TIMEOUT`` after ``timeout_seconds``;
    - readiness is idempotent per candidate and bound to its session hash.
    """

    def __init__(self, *, timeout_seconds: float = DEFAULT_BARRIER_TIMEOUT_SECONDS) -> None:
        self.timeout_seconds = timeout_seconds
        self.runs: dict[str, _RunState] = {}

    # -- run registration ---------------------------------------------------

    def register_run(self, run_id: str, candidates: Sequence[CandidateId] | None = None) -> None:
        """Create (or reset) the barrier state for a run.

        The control-plane run slice calls this when a run is created; until it
        lands, tests and dev callers seed runs explicitly.
        """
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
        state = self.runs.get(frame.run_id)
        if state is None:
            raise UnknownRunError(frame.run_id)
        latest = state.latest_frame_seq.get(frame.candidate_id, -1)
        if frame.frame_seq <= latest:
            raise SequenceRegressionError(
                f"frame_seq {frame.frame_seq} is not newer than recorded {latest}"
            )
        state.latest_frame_seq[frame.candidate_id] = frame.frame_seq
        return FrameIngestAck(
            run_id=frame.run_id,
            candidate_id=frame.candidate_id,
            frame_seq=frame.frame_seq,
            latest_seq=frame.frame_seq,
        )

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


async def require_frame_ingest_token(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Scoped runner auth for the internal frame/barrier endpoints (plan §9.1)."""
    expected = request.app.state.settings.frame_ingest_token
    if not expected:
        raise HTTPException(status_code=503, detail="frame ingest token is not configured")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="missing bearer token")
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="invalid bearer token")


def _validation_detail(exc: ValidationError) -> list[dict[str, object]]:
    return json.loads(exc.json(include_url=False, include_input=False))


@router.post("/internal/frames", response_model=FrameIngestAck)
async def ingest_frame(
    request: Request,
    metadata: Annotated[str, Form()],
    image: Annotated[UploadFile, File()],
    _: Annotated[None, Depends(require_frame_ingest_token)],
) -> FrameIngestAck:
    """Strict ``BrowserFrame`` metadata + binary image (plan §9.1, §11.7)."""
    try:
        frame = BrowserFrame.model_validate_json(metadata, strict=True)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc

    payload = bytearray()
    while True:
        chunk = await image.read(_FRAME_READ_CHUNK)
        if not chunk:
            break
        payload.extend(chunk)
        if len(payload) > MAX_FRAME_BYTES:
            raise HTTPException(
                status_code=413, detail=f"image exceeds the {MAX_FRAME_BYTES} byte cap"
            )

    if len(payload) != frame.image_size_bytes:
        raise HTTPException(
            status_code=422, detail="declared image_size_bytes does not match the uploaded bytes"
        )
    if sha256_hex(bytes(payload)) != frame.image_sha256:
        raise HTTPException(
            status_code=422, detail="image_sha256 does not match the uploaded bytes"
        )
    if image.content_type is not None and image.content_type != frame.image_mime:
        raise HTTPException(
            status_code=422, detail="multipart image content-type does not match image_mime"
        )

    sink: ReferenceSink = request.app.state.frames
    try:
        return sink.accept_frame(frame, image=bytes(payload))
    except UnknownRunError as exc:
        raise HTTPException(status_code=404, detail="unknown run") from exc
    except SequenceRegressionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/internal/worlds/{candidate_id}/browser-ready", response_model=BrowserBarrierState)
async def browser_ready(
    candidate_id: CandidateId,
    body: BrowserReadyRequest,
    request: Request,
    _: Annotated[None, Depends(require_frame_ingest_token)],
) -> BrowserBarrierState:
    """Register one world as ready for the current barrier generation (plan §12.2)."""
    sink: ReferenceSink = request.app.state.frames
    try:
        return sink.mark_ready(candidate_id, body)
    except SessionHashMismatchError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ReadySetMismatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/internal/runs/{run_id}/browser-barrier", response_model=BrowserBarrierState)
async def browser_barrier(
    run_id: str,
    request: Request,
    _: Annotated[None, Depends(require_frame_ingest_token)],
) -> BrowserBarrierState:
    """Release a generation when all expected worlds are ready, or type a timeout."""
    sink: ReferenceSink = request.app.state.frames
    return sink.state(run_id)
