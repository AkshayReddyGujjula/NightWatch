"""Incident-domain contracts: events, the frozen capsule, Gemini's typed outputs.

Plan §6, §7.1, §10.4. The capsule is the only evidence Gemini and candidate
creation may consume; the triage block is advisory and never gates anything.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from apps.contracts.base import (
    CandidateId,
    GitSha40,
    Hash256,
    IdStr,
    MonotonicNs,
    NonEmptyStr,
    StrictModel,
    UtcDatetime,
)
from apps.contracts.payment import (
    CaptureRow,
    CheckoutIntent,
    FaultKind,
    Order,
    PaymentOperation,
    RefundRow,
)

__all__ = [
    "CandidateSpec",
    "CapsuleRowSet",
    "EventKind",
    "GeminiDiagnosis",
    "Hypothesis",
    "IncidentCapsule",
    "IncidentEvent",
    "LogLine",
    "PatchProposal",
    "RequestedExperiment",
    "TriageAdvisory",
    "TriageCategory",
    "TriageSeverity",
]

EventKind = Literal[
    "RUN_REQUESTED",
    "DETECTED",
    "SAFE_HOLD_SET",
    "CAPSULE_FROZEN",
    "REPRODUCING",
    "VALIDATING",
    "SELECTING",
    "STAGED_SMOKE",
    "LEASED",
    "ESCALATED",
    "SAFE_STOP_REQUESTED",
    "LEASE_EXPIRED",
    "LEASE_REVOKED",
]

TriageCategory = Literal[
    "payment_correctness",
    "deploy_regression",
    "infrastructure",
    "security",
    "unknown",
]

TriageSeverity = Literal["low", "medium", "high", "critical"]

RequestedExperiment = Literal["NONE", "BASELINE_REPLAY", "CANDIDATE_WORLDS"]


class IncidentEvent(StrictModel):
    event_id: IdStr
    incident_id: IdStr
    run_id: IdStr | None = None
    kind: EventKind
    occurred_at_utc: UtcDatetime
    monotonic_ns: MonotonicNs
    state_version: Annotated[int, Field(ge=0)]
    payload: dict[str, str] = Field(default_factory=dict)
    prior_event_hash: Hash256 | None = None
    event_hash: Hash256


class LogLine(StrictModel):
    at_utc: UtcDatetime
    level: Literal["INFO", "WARN", "ERROR"]
    message: Annotated[str, StringConstraints(max_length=500)]


class CapsuleRowSet(StrictModel):
    """Store rows relevant to the harmed intent (plan §6)."""

    intent: CheckoutIntent
    order: Order | None = None
    operation: PaymentOperation | None = None


class IncidentCapsule(StrictModel):
    incident_id: IdStr
    run_id: IdStr
    started_at_utc: UtcDatetime
    started_monotonic_ns: MonotonicNs
    original_namespace: NonEmptyStr
    harmed_intent_id: IdStr
    harmed_order_id: IdStr
    harmed_operation_id: IdStr
    ledger_captures: list[CaptureRow]
    ledger_refunds: list[RefundRow] = Field(default_factory=list)
    store_rows: CapsuleRowSet
    recent_logs: list[LogLine] = Field(default_factory=list)
    current_release_hash: Hash256
    previous_release_hash: Hash256
    safe_handler_hash: Hash256
    buggy_module_path: NonEmptyStr
    buggy_module_sha256: Hash256
    bounded_diff: str
    seed_hash: Hash256
    scenario_registry_hash: Hash256
    oracle_code_hash: Hash256
    image_digest: NonEmptyStr
    fault: FaultKind | None = None
    expected_symptom: str
    fixture_knowledge: Literal[True] = True
    capsule_sha256: Hash256
    exclusions: list[str] = Field(default_factory=list)
    unavailable_evidence: list[str] = Field(default_factory=list)


class TriageAdvisory(StrictModel):
    """Advisory only (plan §10.4): never qualifies an incident, gates a candidate,

    influences selection or touches the lease. Renders as MODEL_PROPOSED.
    """

    category: TriageCategory
    severity: TriageSeverity
    rationale: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]


class Hypothesis(StrictModel):
    hypothesis_id: IdStr
    summary: Annotated[str, StringConstraints(min_length=1, max_length=400)]
    evidence_ids: Annotated[list[NonEmptyStr], Field(min_length=1)]
    contradicting_evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]


class GeminiDiagnosis(StrictModel):
    hypotheses: Annotated[list[Hypothesis], Field(min_length=1, max_length=3)]
    requested_experiment: RequestedExperiment
    uncertainty: Annotated[float, Field(ge=0.0, le=1.0)]
    triage: TriageAdvisory
    model_name: NonEmptyStr
    model_version: NonEmptyStr | None = None


class PatchProposal(StrictModel):
    """Candidate C's bounded proposal; validated by the patch guard, never deployed."""

    base_commit_sha: GitSha40
    target_path: Literal["apps/live_store/domain/payment_retry.py"]
    unified_diff: Annotated[str, StringConstraints(min_length=1)]
    rationale: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    expected_behavior: Annotated[str, StringConstraints(min_length=1, max_length=1000)]
    risks: list[str] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    changed_lines: Annotated[int, Field(ge=0, le=40)]


class CandidateSpec(StrictModel):
    candidate_id: CandidateId
    kind: Literal["ROLLBACK", "SAFE_HANDLER", "GEMINI_PATCH"]
    rank: Annotated[int, Field(ge=0, le=2)]
    live_eligible: bool
    image_digest: NonEmptyStr
    code_hash: Hash256
    base_commit_sha: GitSha40
    capsule_sha256: Hash256
    seed_hash: Hash256
    provider_namespace: NonEmptyStr

    @model_validator(mode="after")
    def _rank_matches_fixed_table(self) -> Self:
        """Rank/kind are fixed by plan §14.1 and never chosen by a model."""
        table: dict[str, tuple[str, int]] = {
            "A": ("ROLLBACK", 1),
            "B": ("SAFE_HANDLER", 0),
        }
        if self.candidate_id.startswith("C"):
            expected_kind, expected_rank = "GEMINI_PATCH", 2
        else:
            try:
                expected_kind, expected_rank = table[self.candidate_id]
            except KeyError as exc:
                raise ValueError(
                    f"candidate {self.candidate_id} is not a supported rollback, safe, or patch id"
                ) from exc
        if self.kind != expected_kind or self.rank != expected_rank:
            raise ValueError(
                f"candidate {self.candidate_id} must be {expected_kind} at rank {expected_rank}"
            )
        return self
