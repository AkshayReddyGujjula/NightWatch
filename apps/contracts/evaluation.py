"""Evaluation contracts: the scenario registry, invariant results and verdicts.

Plan §13, §13.1, §13.2, §14.2. The scenario registry in
``fixtures/scenarios.json`` validates against these models, and no candidate
verdict depends on a browser frame stream.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from apps.contracts.base import (
    CandidateId,
    Hash256,
    IdStr,
    NonEmptyStr,
    ScenarioId,
    StrictModel,
    UtcDatetime,
)
from apps.contracts.payment import FaultKind, Quantity

__all__ = [
    "CandidateEvaluation",
    "InvariantId",
    "InvariantResult",
    "InvariantStatus",
    "NegativeControl",
    "Scenario",
    "ScenarioRegistry",
    "ScenarioResult",
    "StageEvent",
    "Surface",
    "VerdictStatus",
]

Surface = Literal["UI_X", "UI_Y", "API"]

InvariantId = Literal["INV-01", "INV-02", "INV-03", "INV-04", "INV-05", "INV-06"]

InvariantStatus = Literal["PASS", "FAIL", "ERROR"]

VerdictStatus = Literal["PENDING", "RUNNING", "PASS", "FAIL", "ERROR", "SKIPPED_INVALID"]


class Scenario(StrictModel):
    """One registry entry; the exact case text mirrors plan §13."""

    scenario_id: ScenarioId
    surface: Surface
    case: NonEmptyStr
    required_outcome: NonEmptyStr
    invariants: Annotated[list[InvariantId], Field(min_length=1)]
    fault: FaultKind | None = None
    sku: NonEmptyStr = "SKU-A"
    quantity: Quantity = 1
    voucher_minor: Annotated[int, Field(ge=0)] | None = None
    expected_stock: Annotated[int, Field(ge=0)] | None = None


class NegativeControl(StrictModel):
    control_id: Literal["NC-01", "NC-02"]
    description: NonEmptyStr
    must_fail: Annotated[list[InvariantId], Field(min_length=1)]


class ScenarioRegistry(StrictModel):
    version: Annotated[int, Field(ge=1)]
    scenarios: Annotated[list[Scenario], Field(min_length=1)]
    negative_controls: Annotated[list[NegativeControl], Field(min_length=1)]

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        scenario_ids = [scenario.scenario_id for scenario in self.scenarios]
        if len(set(scenario_ids)) != len(scenario_ids):
            raise ValueError("scenario_id values must be unique")
        control_ids = [control.control_id for control in self.negative_controls]
        if len(set(control_ids)) != len(control_ids):
            raise ValueError("negative control IDs must be unique")
        return self


class InvariantResult(StrictModel):
    invariant_id: InvariantId
    status: InvariantStatus
    expected_summary: NonEmptyStr
    observed_summary: NonEmptyStr
    evidence_ids: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def _pass_requires_evidence(self) -> Self:
        if self.status == "PASS" and not self.evidence_ids:
            raise ValueError("a PASS requires non-empty trusted evidence IDs")
        return self


class ScenarioResult(StrictModel):
    candidate_id: CandidateId
    scenario_id: ScenarioId
    status: InvariantStatus
    started_at_utc: UtcDatetime
    finished_at_utc: UtcDatetime
    app_facts: dict[str, str] = Field(default_factory=dict)
    ledger_evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    browser_trace_hash: Hash256 | None = None
    invariants: list[InvariantResult] = Field(default_factory=list)
    capsule_sha256: Hash256
    seed_hash: Hash256
    code_hash: Hash256
    failure_reason: str | None = None


class CandidateEvaluation(StrictModel):
    candidate_id: CandidateId
    scenario_ids: Annotated[list[ScenarioId], Field(min_length=1)]
    invariant_ids: Annotated[list[InvariantId], Field(min_length=1)]
    verdict: VerdictStatus
    sandbox_id: IdStr | None = None
    function_call_id: IdStr | None = None
    started_at_utc: UtcDatetime
    finished_at_utc: UtcDatetime | None = None
    evidence_set_sha256: Hash256 | None = None


class StageEvent(StrictModel):
    """One staged-smoke stage; counts come from actual bucket IDs (plan §14.2)."""

    requested_pct: Literal[5, 25, 100]
    routed_count: Annotated[int, Field(ge=0)]
    held_count: Annotated[int, Field(ge=0)]
    routed_bucket_ids: list[NonEmptyStr] = Field(default_factory=list)
    normal_probe_count: Annotated[int, Field(ge=0)]
    loss_probe_count: Annotated[int, Field(ge=0)]
    failed_probe_ids: list[NonEmptyStr] = Field(default_factory=list)
    passed: bool
