"""Contract tests for the incident/payment/evaluation/lease models (plan §7.1, §13)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from apps.contracts.base import sha256_hex
from apps.contracts.evaluation import (
    CandidateEvaluation,
    InvariantResult,
    ScenarioRegistry,
    ScenarioResult,
)
from apps.contracts.incident import CandidateSpec, GeminiDiagnosis, PatchProposal
from apps.contracts.lease import RepairLease, RepairReceipt
from apps.contracts.payment import CheckoutResponse, IntentResponse, OrderResponse

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures"

HASH_A = "a" * 64
HASH_B = "b" * 64
SHA40 = "c" * 40


def utc(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 9, 19, hour, minute, second, tzinfo=UTC)

EXPECTED_INVARIANTS = {
    "S01": ["INV-01", "INV-02", "INV-04", "INV-05"],
    "S02": ["INV-01", "INV-02", "INV-05"],
    "S03": ["INV-01", "INV-02", "INV-05"],
    "S04": ["INV-01", "INV-02"],
    "S05": ["INV-01", "INV-02", "INV-04"],
    "S06": ["INV-01", "INV-02", "INV-03"],
    "S07": ["INV-01", "INV-02", "INV-03"],
    "S08": ["INV-01", "INV-02", "INV-05"],
}


def load_registry() -> ScenarioRegistry:
    payload = (FIXTURES / "scenarios.json").read_text()
    return ScenarioRegistry.model_validate_json(payload, strict=True)


def diagnosis_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "hypotheses": [
            {
                "hypothesis_id": "hyp-1",
                "summary": "The retry handler mints a fresh idempotency key after a lost response.",
                "evidence_ids": ["cap-1", "cap-2"],
                "contradicting_evidence_ids": [],
                "confidence": 0.8,
            }
        ],
        "requested_experiment": "CANDIDATE_WORLDS",
        "uncertainty": 0.2,
        "triage": {
            "category": "payment_correctness",
            "severity": "critical",
            "rationale": "Two captures for one intent (cap-1, cap-2).",
            "confidence": 0.9,
        },
        "model_name": "gemini-3.8-flash",
    }
    payload.update(overrides)
    return payload


def parse(model: type[Any], payload: dict[str, Any]) -> Any:
    return model.model_validate_json(json.dumps(payload), strict=True)


def test_scenario_registry_matches_plan_table() -> None:
    registry = load_registry()
    assert [scenario.scenario_id for scenario in registry.scenarios] == [
        "S01",
        "S02",
        "S03",
        "S04",
        "S05",
        "S06",
        "S07",
        "S08",
    ]
    assert {scenario.scenario_id: scenario.invariants for scenario in registry.scenarios} == (
        EXPECTED_INVARIANTS
    )
    assert {control.control_id: control.must_fail for control in registry.negative_controls} == {
        "NC-01": ["INV-02", "INV-05"],
        "NC-02": ["INV-01"],
    }
    surfaces = {scenario.surface for scenario in registry.scenarios}
    assert surfaces == {"UI_X", "UI_Y", "API"}


def test_pass_invariant_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        InvariantResult(
            invariant_id="INV-01",
            status="PASS",
            expected_summary="one capture",
            observed_summary="one capture",
            evidence_ids=[],
        )
    result = InvariantResult(
        invariant_id="INV-01",
        status="PASS",
        expected_summary="one capture",
        observed_summary="one capture",
        evidence_ids=["cap-1"],
    )
    assert result.status == "PASS"


def test_candidate_spec_rank_table_is_enforced() -> None:
    spec = CandidateSpec(
        candidate_id="B",
        kind="SAFE_HANDLER",
        rank=0,
        live_eligible=True,
        image_digest="sha256:abc",
        code_hash=HASH_A,
        base_commit_sha=SHA40,
        capsule_sha256=HASH_B,
        seed_hash=HASH_A,
        provider_namespace="ns-candidate-b",
    )
    assert spec.rank == 0
    with pytest.raises(ValidationError):
        CandidateSpec(
            candidate_id="A",
            kind="ROLLBACK",
            rank=0,
            live_eligible=False,
            image_digest="sha256:abc",
            code_hash=HASH_A,
            base_commit_sha=SHA40,
            capsule_sha256=HASH_B,
            seed_hash=HASH_A,
            provider_namespace="ns-candidate-a",
        )


def test_diagnosis_requires_triage_block() -> None:
    payload = diagnosis_payload()
    del payload["triage"]
    with pytest.raises(ValidationError):
        parse(GeminiDiagnosis, payload)


def test_triage_bounds_are_enforced() -> None:
    long_rationale = diagnosis_payload()
    long_rationale["triage"]["rationale"] = "x" * 201
    with pytest.raises(ValidationError):
        parse(GeminiDiagnosis, long_rationale)

    bad_confidence = diagnosis_payload()
    bad_confidence["triage"]["confidence"] = 1.2
    with pytest.raises(ValidationError):
        parse(GeminiDiagnosis, bad_confidence)


def test_diagnosis_allows_at_most_three_hypotheses() -> None:
    payload = diagnosis_payload()
    payload["hypotheses"] = payload["hypotheses"] * 4
    with pytest.raises(ValidationError):
        parse(GeminiDiagnosis, payload)


def test_patch_proposal_target_and_line_cap() -> None:
    valid = {
        "base_commit_sha": SHA40,
        "target_path": "apps/live_store/domain/payment_retry.py",
        "unified_diff": "--- a/x\n+++ b/x\n",
        "rationale": "reuse the persisted key",
        "expected_behavior": "one capture",
        "risks": [],
        "tests": [],
        "changed_lines": 12,
    }
    assert parse(PatchProposal, valid).changed_lines == 12

    foreign_target = valid | {"target_path": "apps/live_store/domain/checkout.py"}
    with pytest.raises(ValidationError):
        parse(PatchProposal, foreign_target)

    too_big = valid | {"changed_lines": 41}
    with pytest.raises(ValidationError):
        parse(PatchProposal, too_big)


def test_repair_lease_and_receipt_validate() -> None:
    lease = RepairLease(
        lease_id="lease-1",
        selected_candidate="B",
        evidence_set_sha256=HASH_A,
        handler_sha256=HASH_B,
        expected_router_generation=3,
        router_generation_at_issue=3,
        issued_at_utc=utc(14),
        expires_at_utc=utc(16),
        guardian_interval_seconds=15,
    )
    receipt = RepairReceipt(
        incident_id="NW-001",
        capsule_sha256=HASH_A,
        run_id="run-1",
        evidence_set_sha256=HASH_A,
        original_harm={
            "intent_id": "pi_live_001",
            "operation_id": "op_1",
            "capture_ids": ["cap-1", "cap-2"],
            "amount_minor": 7999,
            "currency": "GBP",
            "statement": "One logical intent produced two captures before containment.",
        },
        containment={
            "safe_hold_set_at_utc": utc(14, 1),
            "summary": "New captures were held; no further captures occurred.",
        },
        decision_basis="Candidate B passed every required gate.",
        demo_mode="CORE",
        created_at_utc=utc(14, 5),
    )
    assert receipt.lease is None
    assert lease.action == "ROUTE_SAFE_HANDLER"


def test_candidate_evaluation_builds() -> None:
    evaluation = CandidateEvaluation(
        candidate_id="B",
        scenario_ids=["S01", "S02"],
        invariant_ids=["INV-01", "INV-02"],
        verdict="RUNNING",
        started_at_utc=utc(14),
    )
    assert evaluation.verdict == "RUNNING"


def test_invariant_evidence_rejects_blank_ids() -> None:
    with pytest.raises(ValidationError):
        InvariantResult(
            invariant_id="INV-01",
            status="PASS",
            expected_summary="one capture",
            observed_summary="one capture",
            evidence_ids=["   "],
        )


def test_scenario_result_requires_registry_and_oracle_hashes() -> None:
    payload: dict[str, Any] = {
        "candidate_id": "B",
        "scenario_id": "S01",
        "status": "FAIL",
        "started_at_utc": utc(14),
        "finished_at_utc": utc(14, 1),
        "capsule_sha256": HASH_A,
        "seed_hash": HASH_A,
        "code_hash": HASH_A,
        "failure_reason": "no order",
    }
    with pytest.raises(ValidationError):
        ScenarioResult(**payload)
    result = ScenarioResult(
        **payload, scenario_registry_hash=HASH_A, oracle_code_hash=HASH_B
    )
    assert result.status == "FAIL"


def test_pass_scenario_requires_invariants() -> None:
    with pytest.raises(ValidationError):
        ScenarioResult(
            candidate_id="B",
            scenario_id="S01",
            status="PASS",
            started_at_utc=utc(14),
            finished_at_utc=utc(14, 1),
            capsule_sha256=HASH_A,
            seed_hash=HASH_A,
            code_hash=HASH_A,
            scenario_registry_hash=HASH_A,
            oracle_code_hash=HASH_A,
        )


def test_candidate_evaluation_rejects_duplicate_sets() -> None:
    with pytest.raises(ValidationError):
        CandidateEvaluation(
            candidate_id="B",
            scenario_ids=["S01", "S01"],
            invariant_ids=["INV-01"],
            verdict="RUNNING",
            started_at_utc=utc(14),
        )


def test_pass_scenario_rejects_non_pass_invariants() -> None:
    failing = InvariantResult(
        invariant_id="INV-01",
        status="FAIL",
        expected_summary="one capture",
        observed_summary="two captures",
    )
    with pytest.raises(ValidationError):
        ScenarioResult(
            candidate_id="B",
            scenario_id="S01",
            status="PASS",
            started_at_utc=utc(14),
            finished_at_utc=utc(14, 1),
            capsule_sha256=HASH_A,
            seed_hash=HASH_A,
            code_hash=HASH_A,
            scenario_registry_hash=HASH_A,
            oracle_code_hash=HASH_A,
            invariants=[failing],
        )


def test_frontend_field_readers_are_covered_by_store_contracts() -> None:
    # Track B promised the freeze reconciles its field names; the readers live in
    # api.js (request bodies) and storefront.js (response fields).
    frontend = "\n".join(
        (ROOT / "apps" / "storefront" / "assets" / name).read_text()
        for name in ("api.js", "storefront.js")
    )
    for name in (
        "customer_id",
        "items",
        "sku",
        "quantity",
        "intent_id",
        "amount_minor",
        "email",
        "address",
        "voucher_code",
        "order_id",
        "status",
    ):
        assert name in frontend

    assert {"intent_id", "items", "amount_minor", "currency"} <= set(IntentResponse.model_fields)
    checkout_fields = set(CheckoutResponse.model_fields)
    assert {"order_id", "intent_id", "status", "amount_minor", "currency"} <= checkout_fields
    order_fields = set(OrderResponse.model_fields)
    assert {"order_id", "intent_id", "status", "amount_minor", "currency"} <= order_fields
    assert sha256_hex(b"nightwatch").__len__() == 64
