"""Lease and receipt contracts (plan §7.1, §14.1, §14.3).

Only deterministic code may issue a ``ROUTE_SAFE_HANDLER`` lease, and only the
selected live-eligible candidate (B, or LEGACY when built and tested) may be
named. The receipt distinguishes prior harm, containment, tested evidence and
unresolved work.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from apps.contracts.base import Hash256, IdStr, NonEmptyStr, StrictModel, UtcDatetime
from apps.contracts.evaluation import CandidateEvaluation, StageEvent
from apps.contracts.payment import Currency

__all__ = [
    "ContainmentSummary",
    "LeaseScope",
    "OriginalHarm",
    "RepairAction",
    "RepairLease",
    "RepairReceipt",
]

RepairAction = Literal["ROUTE_SAFE_HANDLER"]

LeaseScope = Literal["synthetic_checkout_router"]

SelectedRoute = Literal["B", "LEGACY"]


class RepairLease(StrictModel):
    lease_id: IdStr
    action: RepairAction = "ROUTE_SAFE_HANDLER"
    selected_candidate: SelectedRoute
    evidence_set_sha256: Hash256
    handler_sha256: Hash256
    scope: LeaseScope = "synthetic_checkout_router"
    expected_router_generation: Annotated[int, Field(ge=0)]
    router_generation_at_issue: Annotated[int, Field(ge=0)]
    issued_at_utc: UtcDatetime
    expires_at_utc: UtcDatetime
    guardian_interval_seconds: Annotated[int, Field(gt=0)]


class OriginalHarm(StrictModel):
    """The already-harmed intent; NightWatch never claims to reverse it."""

    intent_id: IdStr
    operation_id: IdStr
    capture_ids: Annotated[list[IdStr], Field(min_length=1)]
    amount_minor: Annotated[int, Field(ge=0)]
    currency: Currency
    statement: NonEmptyStr


class ContainmentSummary(StrictModel):
    safe_hold_set_at_utc: UtcDatetime
    summary: NonEmptyStr


class RepairReceipt(StrictModel):
    incident_id: IdStr
    capsule_sha256: Hash256
    run_id: IdStr
    evidence_set_sha256: Hash256
    original_harm: OriginalHarm
    containment: ContainmentSummary
    candidate_matrix: list[CandidateEvaluation] = Field(default_factory=list)
    decision_basis: NonEmptyStr
    stage_events: list[StageEvent] = Field(default_factory=list)
    lease: RepairLease | None = None
    lease_readback_summary: str | None = None
    lease_readback_sha256: Hash256 | None = None
    model_ids: list[NonEmptyStr] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    demo_mode: Literal["FULL", "CORE"]
    degraded_reasons: list[str] = Field(default_factory=list)
    created_at_utc: UtcDatetime
