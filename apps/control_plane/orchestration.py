"""Incident orchestration after containment has been independently read back."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast

from apps.contracts.base import ScenarioId
from apps.contracts.control import IncidentSnapshot
from apps.contracts.evaluation import CandidateEvaluation, InvariantId
from apps.contracts.incident import CandidateSpec, IncidentCapsule
from apps.control_plane.orchestration_store import OrchestrationControlStore
from services.gemini_agent import GeminiAdvisor, GeminiOutcome, TypedGeminiAdvisor
from services.oracle import CORE_SCENARIO_IDS, DemoMode, Oracle
from services.selector import select_candidate


class OrchestrationBlocked(RuntimeError):
    """A required trusted input or integration seam is unavailable."""


class CapsuleSource(Protocol):
    async def freeze(self, snapshot: IncidentSnapshot) -> IncidentCapsule: ...


class IncidentOrchestrator(Protocol):
    async def orchestrate(self, snapshot: IncidentSnapshot) -> IncidentSnapshot: ...


@dataclass(frozen=True)
class RaceOutcome:
    evaluations: tuple[CandidateEvaluation, ...]
    failures: tuple[str, ...] = ()


class CandidateRace(Protocol):
    async def run(
        self,
        specs: list[CandidateSpec],
        *,
        expected_scenario_ids: list[ScenarioId],
        expected_invariant_ids: list[InvariantId],
    ) -> RaceOutcome: ...


class UnavailableCapsuleSource:
    async def freeze(self, snapshot: IncidentSnapshot) -> IncidentCapsule:
        raise OrchestrationBlocked(
            "CAPSULE_UNAVAILABLE: no trusted incident evidence source is configured"
        )


class ModalCandidateRace:
    """Call the deployed trusted runner; never create an ephemeral Modal app."""

    def __init__(self, *, environment: str) -> None:
        self.environment = environment

    async def run(
        self,
        specs: list[CandidateSpec],
        *,
        expected_scenario_ids: list[ScenarioId],
        expected_invariant_ids: list[InvariantId],
    ) -> RaceOutcome:
        import modal
        from services.scheduler import MapRunner, race

        function = modal.Function.from_name(
            "nightwatch",
            "run_candidate",
            environment_name=self.environment,
        )
        failures: list[str] = []
        evaluations = await race(
            specs,
            cast(MapRunner, function.map.aio),
            expected_scenario_ids=expected_scenario_ids,
            expected_invariant_ids=expected_invariant_ids,
            failures=failures,
        )
        return RaceOutcome(tuple(evaluations), tuple(failures))


class OrchestrationEngine:
    def __init__(
        self,
        *,
        store: OrchestrationControlStore,
        capsule_source: CapsuleSource,
        gemini: GeminiAdvisor,
        candidate_race: CandidateRace,
        base_commit_sha: str,
        demo_mode: DemoMode = "CORE",
        oracle: Oracle | None = None,
    ) -> None:
        self.store = store
        self.capsule_source = capsule_source
        self.gemini = gemini
        self.candidate_race = candidate_race
        self.base_commit_sha = base_commit_sha
        self.demo_mode = demo_mode
        self.oracle = oracle or Oracle()

    async def orchestrate(self, snapshot: IncidentSnapshot) -> IncidentSnapshot:
        if not snapshot.containment_verified or snapshot.state != "SAFE_HOLD":
            return self._escalate(
                snapshot.incident_id,
                "ORCHESTRATION_BLOCKED: SAFE_HOLD readback is not verified",
            )
        try:
            capsule = await self.capsule_source.freeze(snapshot)
            if capsule.incident_id != snapshot.incident_id or capsule.run_id != snapshot.run_id:
                raise OrchestrationBlocked("CAPSULE_IDENTITY_MISMATCH")
            self.store.save_capsule(capsule)
            self.store.append_event(
                snapshot.incident_id,
                "CAPSULE_FROZEN",
                {"capsule_sha256": capsule.capsule_sha256},
                state="SAFE_HOLD",
            )

            gemini_outcome = await self.gemini.propose(capsule)
            if gemini_outcome.diagnosis is not None:
                self.store.save_diagnosis(snapshot.run_id, gemini_outcome.diagnosis)

            specs = self._candidate_specs(capsule, gemini_outcome)
            required_scenarios, required_invariants = self._required_matrix()
            degradation = self._initial_degradation(gemini_outcome)
            self.store.append_event(
                snapshot.incident_id,
                "REPRODUCING",
                {
                    "candidate_ids": ",".join(spec.candidate_id for spec in specs),
                    "demo_mode": self.demo_mode,
                    "gemini": (
                        "typed" if gemini_outcome.diagnosis is not None else "unavailable"
                    ),
                },
                state="RUNNING",
                degraded_reason=degradation,
            )

            race = await self.candidate_race.run(
                specs,
                expected_scenario_ids=required_scenarios,
                expected_invariant_ids=required_invariants,
            )
            evaluations, validation_failures = self._validate_runner_results(
                specs,
                list(race.evaluations),
                required_scenarios,
                required_invariants,
            )
            if not any(spec.candidate_id == "C" for spec in specs):
                evaluations.append(
                    self._skipped_c_evaluation(
                        required_scenarios,
                        required_invariants,
                    )
                )
            self.store.save_candidate_evaluations(snapshot.run_id, evaluations)
            runner_failures = [*race.failures, *validation_failures]
            self.store.append_event(
                snapshot.incident_id,
                "VALIDATING",
                {
                    "outcomes": json.dumps(
                        {
                            evaluation.candidate_id: evaluation.verdict
                            for evaluation in evaluations
                        },
                        sort_keys=True,
                    ),
                    "runner_failures": str(len(runner_failures)),
                },
                state="RUNNING",
                degraded_reason=(
                    "RUNNER_FAILURES:" + " | ".join(runner_failures)[:450]
                    if runner_failures
                    else None
                ),
            )

            decision = select_candidate(specs, evaluations)
            if decision.winner is None:
                return self._escalate(snapshot.incident_id, decision.reason)
            self.store.append_event(
                snapshot.incident_id,
                "SELECTING",
                {
                    "winner": decision.winner.candidate_id,
                    "reason": decision.reason,
                    "eligible": ",".join(decision.eligible_candidate_ids),
                },
                state="RUNNING",
            )
            # Task 3 owns smoke/lease/receipt. RUNNING is deliberate: selection
            # is not activation and cannot be reported as completed yet.
            return self.store.get_snapshot(snapshot.incident_id)
        except OrchestrationBlocked as exc:
            return self._escalate(snapshot.incident_id, str(exc))
        except Exception as exc:  # noqa: BLE001 - every integration failure fails closed
            return self._escalate(
                snapshot.incident_id,
                f"ORCHESTRATION_ERROR:{type(exc).__name__}:{exc}",
            )

    def _candidate_specs(
        self, capsule: IncidentCapsule, gemini: GeminiOutcome
    ) -> list[CandidateSpec]:
        if len(self.base_commit_sha) != 40:
            raise OrchestrationBlocked("BASE_COMMIT_SHA_UNAVAILABLE")
        specs = [
            CandidateSpec(
                candidate_id="A",
                kind="ROLLBACK",
                rank=1,
                live_eligible=True,
                image_digest=capsule.image_digest,
                code_hash=capsule.previous_release_hash,
                base_commit_sha=self.base_commit_sha,
                capsule_sha256=capsule.capsule_sha256,
                seed_hash=capsule.seed_hash,
                provider_namespace=f"{capsule.run_id}-a",
            ),
            CandidateSpec(
                candidate_id="B",
                kind="SAFE_HANDLER",
                rank=0,
                live_eligible=True,
                image_digest=capsule.image_digest,
                code_hash=capsule.safe_handler_hash,
                base_commit_sha=self.base_commit_sha,
                capsule_sha256=capsule.capsule_sha256,
                seed_hash=capsule.seed_hash,
                provider_namespace=f"{capsule.run_id}-b",
            ),
        ]
        # Candidate C is added only after Task 4's patch guard accepts one.
        # Merely receiving model output never authorizes unguarded code to race.
        _ = gemini
        return specs

    def _required_matrix(self) -> tuple[list[ScenarioId], list[InvariantId]]:
        scenarios = [
            scenario
            for scenario in self.oracle.registry.scenarios
            if self.demo_mode == "FULL" or scenario.scenario_id in CORE_SCENARIO_IDS
        ]
        if not scenarios:
            raise OrchestrationBlocked("EMPTY_REQUIRED_SCENARIO_SET")
        scenario_ids: list[ScenarioId] = [
            scenario.scenario_id for scenario in scenarios
        ]
        invariant_ids: list[InvariantId] = sorted(
            {invariant for scenario in scenarios for invariant in scenario.invariants}
        )
        return scenario_ids, invariant_ids

    def _initial_degradation(self, outcome: GeminiOutcome) -> str | None:
        reasons = []
        if self.demo_mode == "CORE":
            reasons.append("ERROR_BROWSER_STACK:S01,S02")
        if outcome.failure_reason:
            reasons.append(outcome.failure_reason)
        return ";".join(reasons) or None

    @staticmethod
    def _skipped_c_evaluation(
        scenario_ids: list[ScenarioId], invariant_ids: list[InvariantId]
    ) -> CandidateEvaluation:
        now = datetime.now(UTC)
        return CandidateEvaluation(
            candidate_id="C",
            scenario_ids=scenario_ids,
            invariant_ids=invariant_ids,
            verdict="SKIPPED_INVALID",
            started_at_utc=now,
            finished_at_utc=now,
        )

    @staticmethod
    def _validate_runner_results(
        specs: list[CandidateSpec],
        evaluations: list[CandidateEvaluation],
        required_scenarios: list[ScenarioId],
        required_invariants: list[InvariantId],
    ) -> tuple[list[CandidateEvaluation], list[str]]:
        by_candidate: dict[str, CandidateEvaluation] = {}
        failures: list[str] = []
        duplicate_ids: set[str] = set()
        expected_ids = {spec.candidate_id for spec in specs}
        for result in evaluations:
            if result.candidate_id not in expected_ids:
                failures.append(
                    f"unexpected candidate evaluation {result.candidate_id} ignored"
                )
                continue
            if result.candidate_id in by_candidate:
                duplicate_ids.add(result.candidate_id)
                continue
            by_candidate[result.candidate_id] = result
        validated: list[CandidateEvaluation] = []
        for spec in specs:
            evaluation = by_candidate.get(spec.candidate_id)
            if evaluation is None or spec.candidate_id in duplicate_ids:
                reason = (
                    "duplicate results"
                    if spec.candidate_id in duplicate_ids
                    else "missing result"
                )
                failures.append(f"{spec.candidate_id}: {reason}")
                validated.append(
                    OrchestrationEngine._error_evaluation(
                        spec, required_scenarios, required_invariants
                    )
                )
                continue
            pass_shape_valid = (
                evaluation.scenario_ids == required_scenarios
                and evaluation.invariant_ids == required_invariants
                and evaluation.evidence_set_sha256 is not None
            )
            if evaluation.verdict == "PASS" and not pass_shape_valid:
                failures.append(f"{spec.candidate_id}: malformed PASS evidence shape")
                validated.append(
                    OrchestrationEngine._error_evaluation(
                        spec, required_scenarios, required_invariants
                    )
                )
            else:
                validated.append(evaluation)
        return validated, failures

    @staticmethod
    def _error_evaluation(
        spec: CandidateSpec,
        scenario_ids: list[ScenarioId],
        invariant_ids: list[InvariantId],
    ) -> CandidateEvaluation:
        now = datetime.now(UTC)
        return CandidateEvaluation(
            candidate_id=spec.candidate_id,
            scenario_ids=scenario_ids,
            invariant_ids=invariant_ids,
            verdict="ERROR",
            started_at_utc=now,
            finished_at_utc=now,
        )

    def _escalate(self, incident_id: str, reason: str) -> IncidentSnapshot:
        self.store.append_event(
            incident_id,
            "ESCALATED",
            {"reason": reason[:500]},
            state="ESCALATED",
            degraded_reason=reason[:512],
        )
        return self.store.get_snapshot(incident_id)


async def orchestrate_incident(
    orchestrator: IncidentOrchestrator, snapshot: IncidentSnapshot
) -> IncidentSnapshot:
    """Named control-plane seam used by ``POST /run`` and injected tests."""
    return await orchestrator.orchestrate(snapshot)


def build_default_orchestrator(
    *,
    store: OrchestrationControlStore,
    environment: str,
    base_commit_sha: str,
    gemini_model: str,
) -> OrchestrationEngine:
    return OrchestrationEngine(
        store=store,
        capsule_source=UnavailableCapsuleSource(),
        gemini=TypedGeminiAdvisor(model=gemini_model),
        candidate_race=ModalCandidateRace(environment=environment),
        base_commit_sha=base_commit_sha,
        demo_mode="CORE",
    )
