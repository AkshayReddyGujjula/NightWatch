"""Control-plane HTTP contracts.

These models freeze the public incident/run read surface used by the operator
dashboard.  Events are append-only and are the source of truth; snapshots and
evaluation payloads are committed read models derived from that evidence.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from apps.contracts.base import CandidateId, IdStr, NonEmptyStr, StrictModel, UtcDatetime
from apps.contracts.evaluation import InvariantId, ScenarioResult

__all__ = [
    "EvaluationResults",
    "IncidentSnapshot",
    "IncidentState",
    "NegativeControlResult",
    "SafeStopRequest",
    "WorldHealth",
]


IncidentState = Literal[
    "RUN_REQUESTED",
    "SAFE_HOLD",
    "RUNNING",
    "COMPLETED",
    "ESCALATED",
]


class SafeStopRequest(StrictModel):
    reason: Annotated[str, StringConstraints(min_length=1, max_length=200)] = (
        "operator_requested"
    )


class IncidentSnapshot(StrictModel):
    incident_id: IdStr
    run_id: IdStr
    state: IncidentState
    state_version: Annotated[int, Field(ge=0)]
    containment_verified: bool
    event_count: Annotated[int, Field(ge=0)]
    receipt_available: bool
    degraded_reasons: list[NonEmptyStr] = Field(default_factory=list)
    created_at_utc: UtcDatetime
    updated_at_utc: UtcDatetime


class NegativeControlResult(StrictModel):
    control_id: Literal["NC-01", "NC-02"]
    status: Literal["PASS", "FAIL", "ERROR"]
    failed_invariants: list[InvariantId] = Field(default_factory=list)
    evidence_ids: list[NonEmptyStr] = Field(default_factory=list)


class EvaluationResults(StrictModel):
    """Committed matrix source; no provisional world output is returned."""

    run_id: IdStr
    scenarios: list[ScenarioResult] = Field(default_factory=list)
    negative_controls: list[NegativeControlResult] = Field(default_factory=list)
    committed_at_utc: UtcDatetime


class WorldHealth(StrictModel):
    world_id: IdStr
    status: Literal["STARTING", "READY", "RUNNING", "COMPLETED", "ERROR", "TERMINATED"]
    candidate_id: CandidateId | None = None
    sandbox_id: IdStr | None = None
    detail: str | None = None
    checked_at_utc: UtcDatetime
