"""Browser-domain boundary models: Jev observation/decision and CUA frames.

Frozen contract for plan §7.1 and §11. The multipart ``POST /internal/frames``
metadata part is exactly :class:`BrowserFrame`; the binary image is the second
part (field name ``image``). Track B owns the implementations in
``services/jev/**`` and ``services/frames/**``; the HTTP contract is Track A's.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from apps.contracts.base import (
    CandidateId,
    Hash256,
    IdStr,
    MonotonicNs,
    NonEmptyStr,
    ScenarioId,
    StrictModel,
    UtcDatetime,
)

__all__ = [
    "MAX_FRAME_BYTES",
    "ActionId",
    "ActionOperation",
    "BarrierStatus",
    "BrowserBarrierState",
    "BrowserFrame",
    "BrowserObservation",
    "BrowserReadyRequest",
    "ControlPurpose",
    "FrameIngestAck",
    "FrameMime",
    "FramePhase",
    "JevDecision",
    "ObservedControl",
    "ReadyWorld",
]

# One frame image may not exceed 350 KB (plan §11.7). Binary kilobytes.
MAX_FRAME_BYTES = 350 * 1024

# Opaque action ID minted by the CUA adapter, e.g. ``click__a17``. The reserved
# control actions ``reobserve``, ``abstain`` and ``done_unverified`` share the
# same shape (plan §11.3).
ActionId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]

ActionOperation = Literal["click", "type", "select", "reobserve", "abstain", "done_unverified"]

ControlPurpose = Literal["submit", "email", "address", "voucher", "quantity", "sku", "other"]

FramePhase = Literal["SAMPLE", "BEFORE_ACTION", "AFTER_ACTION", "TERMINAL"]

FrameMime = Literal["image/jpeg", "image/webp"]

BarrierStatus = Literal["PENDING", "RELEASED", "TIMEOUT"]


class ObservedControl(StrictModel):
    """One visible, enabled control offered to Jev (plan §11.2)."""

    action_id: ActionId
    role: NonEmptyStr
    name: NonEmptyStr
    purpose: ControlPurpose = "other"
    enabled: bool


class BrowserObservation(StrictModel):
    """Compact semantic snapshot; page text is untrusted data (plan §11.2)."""

    goal: NonEmptyStr
    origin: NonEmptyStr
    url: NonEmptyStr
    page_generation: Annotated[int, Field(ge=0)]
    heading: str
    status_text: str
    controls: list[ObservedControl] = Field(default_factory=list)
    completed_postconditions: list[str] = Field(default_factory=list)
    observation_hash: Hash256


class JevDecision(StrictModel):
    """One typed action choice returned by TypeSafe and validated by code (plan §11.3)."""

    decision_id: IdStr
    chosen_action_id: ActionId
    operation: ActionOperation
    model_name: NonEmptyStr
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    probabilities: dict[ActionId, Annotated[float, Field(ge=0.0, le=1.0)]]
    provider_request_id: str | None = None
    observation_hash: Hash256


class BrowserFrame(StrictModel):
    """Frame metadata for ``POST /internal/frames`` (plan §7.1, §11.7).

    ``image_sha256`` is the frame's canonical identity; the binary image travels
    as the separately hashed multipart part and never enters SQLite.
    """

    run_id: IdStr
    candidate_id: CandidateId
    scenario_id: ScenarioId
    frame_seq: Annotated[int, Field(ge=0)]
    sandbox_id: IdStr
    cua_session_id: IdStr
    snapshot_id: IdStr
    capture_id: IdStr | None = None
    phase: FramePhase
    captured_monotonic_ns: MonotonicNs
    captured_at_utc: UtcDatetime
    image_sha256: Hash256
    image_size_bytes: Annotated[int, Field(gt=0, le=MAX_FRAME_BYTES)]
    image_mime: FrameMime
    jev_decision_id: IdStr | None = None
    selected_action_label: Annotated[str, StringConstraints(max_length=160)] | None = None
    confidence: Annotated[float, Field(ge=0.0, le=1.0)] | None = None


class FrameIngestAck(StrictModel):
    """Response body of ``POST /internal/frames``."""

    run_id: IdStr
    candidate_id: CandidateId
    frame_seq: Annotated[int, Field(ge=0)]
    latest_seq: Annotated[int, Field(ge=0)]


class BrowserReadyRequest(StrictModel):
    """Body of ``POST /internal/worlds/{candidate_id}/browser-ready`` (plan §9.1).

    ``session_hash`` binds the readiness to one world session:
    ``sha256("{run_id}|{candidate_id}|{sandbox_id}|{cua_session_id}")``.
    """

    run_id: IdStr
    sandbox_id: IdStr
    cua_session_id: IdStr
    session_hash: Hash256


class ReadyWorld(StrictModel):
    """One candidate world that has registered readiness for a generation."""

    candidate_id: CandidateId
    sandbox_id: IdStr
    session_hash: Hash256


class BrowserBarrierState(StrictModel):
    """Barrier state returned by ready posts and ``GET .../browser-barrier`` (plan §12.2)."""

    run_id: IdStr
    generation: Annotated[int, Field(ge=0)]
    expected_candidates: list[CandidateId]
    ready: list[ReadyWorld] = Field(default_factory=list)
    status: BarrierStatus
    timeout_seconds: Annotated[float, Field(gt=0)] = 120.0
    deadline_at_utc: UtcDatetime | None = None
    released_at_utc: UtcDatetime | None = None
    timed_out_at_utc: UtcDatetime | None = None
