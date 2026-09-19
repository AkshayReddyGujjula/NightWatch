"""Track B — candidate-runner tests: one world never contaminates another's verdict."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from apps.contracts.evaluation import (
    CandidateEvaluation,
    InvariantResult,
    ScenarioResult,
)
from apps.contracts.incident import CandidateSpec
from services.worlds.interface import WorldError, WorldLifecycle
from services.worlds.runner import CandidateRun, run_candidate_world

_HASH = "a" * 64
_GIT_SHA = "b" * 40
_SCENARIOS = ["S01"]
_INVARIANTS = ["INV-01"]


def make_spec(candidate_id: str) -> CandidateSpec:
    kind_rank = {"A": ("ROLLBACK", 1), "B": ("SAFE_HANDLER", 0), "C": ("GEMINI_PATCH", 2)}
    kind, rank = kind_rank[candidate_id]
    return CandidateSpec(
        candidate_id=candidate_id,
        kind=kind,
        rank=rank,
        live_eligible=candidate_id == "B",
        image_digest="im-test",
        code_hash=_HASH,
        base_commit_sha=_GIT_SHA,
        capsule_sha256=_HASH,
        seed_hash=_HASH,
        provider_namespace=f"ns-{candidate_id}",
    )


class FakeWorld:
    """Minimal ``WorldLike`` with injectable start/stop behaviour."""

    def __init__(self, *, fail_start: bool = False, fail_stop: bool = False) -> None:
        self.started = False
        self.stopped = False
        self._fail_start = fail_start
        self._fail_stop = fail_stop

    @property
    def sandbox_id(self) -> str | None:
        return "sb-fake"

    @property
    def world_evidence(self) -> dict[str, Any]:
        return {"fake": True}

    def start(self, spec: CandidateSpec) -> WorldLifecycle:
        if self._fail_start:
            raise WorldError("boom")
        self.started = True
        return WorldLifecycle(
            candidate_id=spec.candidate_id,
            sandbox_id="sb-fake",
            created_monotonic_ns=1_000,
            ready_monotonic_ns=2_000,
        )

    def stop(self) -> WorldLifecycle:
        if self._fail_stop:
            raise RuntimeError("stop exploded")
        self.stopped = True
        return WorldLifecycle(
            candidate_id="",
            sandbox_id="sb-fake",
            finished_monotonic_ns=3_000,
            terminated=True,
        )


def fake_executor(spec: CandidateSpec, world: Any) -> list[ScenarioResult]:
    now = datetime.now(UTC)
    return [
        ScenarioResult(
            candidate_id=spec.candidate_id,
            scenario_id="S01",
            status="PASS",
            started_at_utc=now,
            finished_at_utc=now,
            invariants=[
                InvariantResult(
                    invariant_id="INV-01",
                    status="PASS",
                    expected_summary="one order, one capture, one confirmation",
                    observed_summary="one order, one capture, one confirmation",
                    evidence_ids=["ledger:capture-1"],
                )
            ],
            capsule_sha256=_HASH,
            seed_hash=_HASH,
            code_hash=_HASH,
            scenario_registry_hash=_HASH,
            oracle_code_hash=_HASH,
        )
    ]


def fake_grader(spec: CandidateSpec, results: list[ScenarioResult]) -> CandidateEvaluation:
    assert results
    now = datetime.now(UTC)
    return CandidateEvaluation(
        candidate_id=spec.candidate_id,
        scenario_ids=list(_SCENARIOS),
        invariant_ids=list(_INVARIANTS),
        verdict="PASS",
        started_at_utc=now,
        finished_at_utc=now,
    )


def test_unwired_scenarios_return_error_and_world_is_stopped() -> None:
    world = FakeWorld()
    run: CandidateRun = run_candidate_world(
        make_spec("B"),
        world,
        expected_scenario_ids=_SCENARIOS,
        expected_invariant_ids=_INVARIANTS,
    )
    assert run.evaluation.verdict == "ERROR"
    assert run.failures == ["scenario execution not wired (services/oracle.py pending)"]
    assert run.evaluation.scenario_ids == _SCENARIOS
    assert world.started and world.stopped
    assert run.lifecycle is not None and run.lifecycle.terminated


def test_start_failure_is_localised_and_cleanup_still_runs() -> None:
    world = FakeWorld(fail_start=True)
    run = run_candidate_world(
        make_spec("A"),
        world,
        expected_scenario_ids=_SCENARIOS,
        expected_invariant_ids=_INVARIANTS,
    )
    assert run.evaluation.verdict == "ERROR"
    assert run.failures and run.failures[0].startswith("world error: boom")
    assert world.stopped
    assert run.lifecycle is not None and run.lifecycle.terminated


def test_cleanup_failure_is_recorded_not_raised() -> None:
    world = FakeWorld(fail_stop=True)
    run = run_candidate_world(
        make_spec("C"),
        world,
        expected_scenario_ids=_SCENARIOS,
        expected_invariant_ids=_INVARIANTS,
    )
    assert run.evaluation.verdict == "ERROR"
    assert run.lifecycle is None
    assert any("cleanup failed" in reason for reason in run.failures)


def test_wired_executor_and_grader_produce_evaluation_without_failures() -> None:
    world = FakeWorld()
    run = run_candidate_world(
        make_spec("B"),
        world,
        expected_scenario_ids=_SCENARIOS,
        expected_invariant_ids=_INVARIANTS,
        scenario_executor=fake_executor,
        grader=fake_grader,
    )
    assert run.evaluation.verdict == "PASS"
    assert run.failures == []
    assert world.stopped
    assert run.lifecycle is not None and run.lifecycle.terminated
