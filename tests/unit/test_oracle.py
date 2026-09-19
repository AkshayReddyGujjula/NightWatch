"""Deterministic oracle exact-set and negative-control guards."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.contracts.base import canonical_sha256
from apps.contracts.evaluation import Scenario
from apps.contracts.incident import CandidateSpec
from apps.contracts.payment import LedgerView, StoreFacts
from services.oracle import Oracle, ScenarioEvidence, ScenarioSuite


def _spec(suite: ScenarioSuite) -> CandidateSpec:
    return CandidateSpec(
        candidate_id="B",
        kind="SAFE_HANDLER",
        rank=0,
        live_eligible=True,
        image_digest="local-test-image",
        code_hash=suite.code_hash,
        base_commit_sha="a" * 40,
        capsule_sha256="b" * 64,
        seed_hash=suite.seed_hash,
        provider_namespace="test-b",
    )


def test_empty_results_never_vacuously_pass() -> None:
    suite = ScenarioSuite()
    try:
        spec = _spec(suite)
        errors = suite.oracle.validate_evidence_set(spec, [])
        assert errors
        assert "missing=" in errors[0]
        assert suite.oracle.grade_candidate(spec, []).verdict == "ERROR"
    finally:
        suite.close()


def test_negative_controls_fail_exact_intended_invariants() -> None:
    controls = Oracle().run_negative_controls()
    assert [(item.control_id, item.status, item.failed_invariants) for item in controls] == [
        ("NC-01", "FAIL", ["INV-02", "INV-05"]),
        ("NC-02", "FAIL", ["INV-01"]),
    ]
    assert all(item.evidence_ids for item in controls)


def test_inv_06_requires_separation_and_immutable_original_digest() -> None:
    digest = canonical_sha256({"original": "ledger"})
    evidence = ScenarioEvidence(
        candidate_id="B",
        scenario=Scenario(
            scenario_id="S08",
            surface="API",
            case="immutability check",
            required_outcome="unchanged",
            invariants=["INV-06"],
        ),
        namespace="candidate-b-s08",
        store_facts=StoreFacts(
            intent_id="pi-1",
            order_status=None,
            order_count=0,
            operation_count=0,
            confirmation_count=0,
            fulfillment_count=0,
            stock_remaining=100,
        ),
        ledger=LedgerView(
            namespace="candidate-b-s08",
            registrations=[],
            captures=[],
            refunds=[],
            digest=canonical_sha256({"candidate": "ledger"}),
        ),
        http_statuses=(200,),
        reported_status=None,
        expected_stock=100,
        original_namespace="original-incident",
        original_digest_before=digest,
        original_digest_after=digest,
        trace_facts={"test": "inv-06"},
    )
    assert Oracle().evaluate(evidence, "INV-06").status == "PASS"
    changed = ScenarioEvidence(
        **{
            **evidence.__dict__,
            "original_digest_after": canonical_sha256({"original": "mutated"}),
        }
    )
    assert Oracle().evaluate(changed, "INV-06").status == "FAIL"


def test_oracle_result_evidence_ids_are_never_empty() -> None:
    with pytest.raises(ValueError, match="trusted evidence IDs"):
        Oracle._result("INV-01", "FAIL", "expected", "observed", [])
    assert datetime.now(UTC).tzinfo is not None
