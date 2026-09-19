"""Track B — one candidate world's run lifecycle (plan §12.2, §17).

Boots exactly one world, hands it to the scenario executor when one is wired, and
always tears it down — a world that crashes, times out or cannot be evaluated
becomes that candidate's own ERROR evaluation and never leaks into another
world's verdict.

Grading is injected, not implemented here: the executor collects
``ScenarioResult`` objects and the grader (Track A's ``services/oracle.py``)
turns them into a ``CandidateEvaluation``. Until both are wired, a world that
boots cleanly still returns ERROR — a candidate that cannot be evaluated can
never pass (plan §13.2).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from apps.contracts.base import ScenarioId
from apps.contracts.evaluation import CandidateEvaluation, InvariantId, ScenarioResult
from apps.contracts.incident import CandidateSpec
from services.scheduler import error_evaluation
from services.worlds.interface import WorldError, WorldLifecycle


class WorldLike(Protocol):
    """Structural type satisfied by :class:`services.worlds.modal_world.ModalWorld`."""

    @property
    def sandbox_id(self) -> str | None: ...

    @property
    def world_evidence(self) -> dict[str, Any]: ...

    def start(self, spec: CandidateSpec) -> WorldLifecycle: ...

    def stop(self) -> WorldLifecycle: ...


ScenarioExecutor = Callable[[CandidateSpec, WorldLike], list[ScenarioResult]]
Grader = Callable[[CandidateSpec, list[ScenarioResult]], CandidateEvaluation]


@dataclass(frozen=True)
class CandidateRun:
    """One world's outcome: the evaluation, its lifecycle, and failure reasons."""

    evaluation: CandidateEvaluation
    lifecycle: WorldLifecycle | None
    failures: list[str] = field(default_factory=list)


def run_candidate_world(
    spec: CandidateSpec,
    world: WorldLike,
    *,
    expected_scenario_ids: Sequence[ScenarioId],
    expected_invariant_ids: Sequence[InvariantId],
    scenario_executor: ScenarioExecutor | None = None,
    grader: Grader | None = None,
) -> CandidateRun:
    """Run one candidate world end-to-end; never raises for a single world."""
    failures: list[str] = []
    evaluation: CandidateEvaluation | None = None
    lifecycle: WorldLifecycle | None = None
    try:
        world.start(spec)
        if scenario_executor is None or grader is None:
            failures.append("scenario execution not wired (services/oracle.py pending)")
        else:
            results = scenario_executor(spec, world)
            evaluation = grader(spec, results)
    except WorldError as error:
        failures.append(f"world error: {error}")
    except Exception as error:  # noqa: BLE001 — every world failure stays local to it
        failures.append(f"{type(error).__name__}: {error}")
    finally:
        try:
            lifecycle = world.stop()
        except Exception as error:  # noqa: BLE001 — cleanup failure is recorded, not raised
            failures.append(f"cleanup failed: {type(error).__name__}: {error}")
    if evaluation is None:
        evaluation = error_evaluation(
            spec,
            expected_scenario_ids=expected_scenario_ids,
            expected_invariant_ids=expected_invariant_ids,
        )
    return CandidateRun(evaluation=evaluation, lifecycle=lifecycle, failures=failures)
