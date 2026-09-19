"""Real S03–S08 execution through provider/store HTTP code paths."""

from __future__ import annotations

import pytest

from apps.contracts.incident import CandidateSpec
from services.oracle import ScenarioSuite


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


@pytest.mark.asyncio
async def test_api_scenarios_pass_with_isolated_evidence_and_ui_is_labelled() -> None:
    suite = ScenarioSuite()
    try:
        spec = _spec(suite)
        results = await suite.execute_async(spec)
        by_id = {result.scenario_id: result for result in results}

        assert [
            result.status
            for result in results
            if result.scenario_id in {"S03", "S04", "S05", "S06", "S07", "S08"}
        ] == ["PASS"] * 6
        for scenario_id in ("S01", "S02"):
            assert by_id[scenario_id].status == "ERROR"
            assert by_id[scenario_id].failure_reason == "ERROR_BROWSER_STACK"

        namespaces = [result.app_facts["provider_namespace"] for result in results]
        assert len(namespaces) == len(set(namespaces)) == 8
        assert all(result.seed_hash == suite.seed_hash for result in results)
        assert all(result.code_hash == suite.code_hash for result in results)
        assert all(
            result.app_facts["db_generation_sha256"] == suite.seed_hash
            for result in results
        )
        assert all(
            invariant.evidence_ids
            for result in results
            for invariant in result.invariants
        )
        assert suite.oracle.validate_evidence_set(spec, results) == []
        # Overall ERROR is honest: the two required UI scenarios are unavailable.
        assert suite.oracle.grade_candidate(spec, results).verdict == "ERROR"
    finally:
        suite.close()


@pytest.mark.asyncio
async def test_api_scenario_outcomes_match_real_ledger_counts() -> None:
    suite = ScenarioSuite()
    try:
        results = {result.scenario_id: result for result in await suite.execute_async(_spec(suite))}
        assert results["S03"].app_facts["capture_count"] == "1"
        assert results["S03"].app_facts["same_order"] == "true"
        assert results["S04"].app_facts["capture_count"] == "1"
        assert results["S04"].app_facts["same_order"] == "true"
        assert results["S05"].app_facts["capture_count"] == "1"
        assert results["S06"].app_facts["refund_count"] == "1"
        assert results["S07"].app_facts["refund_count"] == "2"
        assert results["S08"].app_facts["capture_count"] == "0"
        assert all(
            result.app_facts["original_digest_before"]
            == result.app_facts["original_digest_after"]
            for result in results.values()
            if "original_digest_after" in result.app_facts
        )
    finally:
        suite.close()


@pytest.mark.asyncio
async def test_frozen_hash_mismatch_fails_before_scenario_execution() -> None:
    suite = ScenarioSuite()
    try:
        spec = _spec(suite).model_copy(update={"seed_hash": "f" * 64})
        with pytest.raises(ValueError, match="seed_hash"):
            await suite.execute_async(spec)
    finally:
        suite.close()
