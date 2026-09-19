"""Track B — candidate race scheduler (plan §12.1, §14.4).

Runs the A/B/C candidate specs concurrently through the trusted `run_candidate`
map and returns exactly one :class:`CandidateEvaluation` per spec, in spec
order. A world that dies, times out or returns an unparseable payload becomes an
ERROR evaluation for **that** candidate only — never a swallowed item, never a
pass, and never a failure that leaks into another world's verdict.

Implementation note (deliberate, recorded): §12.1 sketches
``order_outputs=False``. We pass ``order_outputs=True`` so every map item is
attributed positionally to the spec that produced it. With unordered outputs a
container crash loses its candidate identity, and attributing it by guess could
mark the wrong world ERROR — and ERROR can change deterministic selection.

Deterministic selection (§14.1) happens outside this module and only over
complete evidence sets. The map runner is injected so tests can race fake
worlds without Modal; in production it is ``run_candidate.map.aio``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import ValidationError

from apps.contracts.base import ScenarioId
from apps.contracts.evaluation import CandidateEvaluation, InvariantId
from apps.contracts.incident import CandidateSpec


class MapRunner(Protocol):
    """Shaped like ``run_candidate.map.aio`` (plan §12.1)."""

    def __call__(
        self,
        inputs: Sequence[str],
        *,
        order_outputs: bool = ...,
        return_exceptions: bool = ...,
    ) -> AsyncIterator[Any]: ...


def error_evaluation(
    spec: CandidateSpec,
    *,
    expected_scenario_ids: Sequence[ScenarioId],
    expected_invariant_ids: Sequence[InvariantId],
    sandbox_id: str | None = None,
    started_at_utc: datetime | None = None,
    finished_at_utc: datetime | None = None,
) -> CandidateEvaluation:
    """One candidate's ERROR shell when its world produced no usable result.

    The expected evidence sets are recorded as the candidate's matrix, so the
    central evidence-set validator fails closed on the missing
    ``(candidate_id, scenario_id, invariant_id)`` tuples instead of on an empty
    list. The failure reason belongs in the control-plane event log — the
    frozen evaluation contract has no field for it.

    ``started_at_utc``/``finished_at_utc`` carry the world's measured UTC
    lifecycle window when one exists (plan §12.3), so the race script can
    compute real concurrency overlap from committed timestamps instead of the
    requested container count.
    """
    now = datetime.now(UTC)
    # One instant when only one side of the window is known, so the recorded
    # window can never invert (started > finished).
    if started_at_utc is None and finished_at_utc is not None:
        started_at_utc = finished_at_utc
    if finished_at_utc is None:
        finished_at_utc = started_at_utc or now
    return CandidateEvaluation(
        candidate_id=spec.candidate_id,
        scenario_ids=list(expected_scenario_ids),
        invariant_ids=list(expected_invariant_ids),
        sandbox_id=sandbox_id,
        verdict="ERROR",
        started_at_utc=started_at_utc or now,
        finished_at_utc=finished_at_utc,
    )


async def race(
    specs: Sequence[CandidateSpec],
    map_runner: MapRunner,
    *,
    expected_scenario_ids: Sequence[ScenarioId],
    expected_invariant_ids: Sequence[InvariantId],
    failures: list[str] | None = None,
) -> list[CandidateEvaluation]:
    """Run every spec concurrently; return one evaluation per spec, spec order.

    ``failures``, when supplied, collects ``"{candidate_id}: {reason}"`` strings
    for the orchestrator to persist as control-plane events (the frozen
    evaluation contract carries no free-text failure field).
    """
    inputs = [spec.model_dump_json() for spec in specs]
    by_candidate: dict[str, CandidateEvaluation] = {}
    reasoned: set[str] = set()
    overflow = 0
    index = 0

    def _record(candidate_id: str, reason: str) -> None:
        reasoned.add(candidate_id)
        if failures is not None:
            failures.append(f"{candidate_id}: {reason}")

    async for item in map_runner(inputs, order_outputs=True, return_exceptions=True):
        spec = specs[index] if index < len(specs) else None
        index += 1
        if spec is None:
            overflow += 1
            continue
        if isinstance(item, BaseException):
            _record(spec.candidate_id, f"{type(item).__name__}: {item}")
            continue
        if not isinstance(item, str | bytes):
            _record(spec.candidate_id, f"map item had type {type(item).__name__}")
            continue
        try:
            evaluation = CandidateEvaluation.model_validate_json(item, strict=True)
        except ValidationError as error:
            _record(
                spec.candidate_id,
                f"invalid CandidateEvaluation ({error.error_count()} validation error(s))",
            )
            continue
        if evaluation.candidate_id != spec.candidate_id:
            _record(
                spec.candidate_id,
                f"map item carried candidate_id {evaluation.candidate_id!r}",
            )
            continue
        by_candidate[evaluation.candidate_id] = evaluation

    evaluations: list[CandidateEvaluation] = []
    for spec in specs:
        found = by_candidate.get(spec.candidate_id)
        if found is None:
            if spec.candidate_id not in reasoned:
                _record(spec.candidate_id, "no result returned for this candidate")
            evaluations.append(
                error_evaluation(
                    spec,
                    expected_scenario_ids=expected_scenario_ids,
                    expected_invariant_ids=expected_invariant_ids,
                )
            )
        else:
            evaluations.append(found)

    if overflow:
        reasoned.add("race")
        if failures is not None:
            failures.append(f"race: {overflow} extra map item(s) ignored")
    return evaluations
