"""Track B — scheduler race tests: one failed world must not affect another."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Any

from apps.contracts.evaluation import CandidateEvaluation
from apps.contracts.incident import CandidateSpec
from services.scheduler import race

_HASH = "a" * 64
_GIT_SHA = "b" * 40
_SCENARIOS = ["S01", "S02"]
_INVARIANTS = ["INV-01", "INV-02"]

_KIND_RANK = {
    "A": ("ROLLBACK", 1),
    "B": ("SAFE_HANDLER", 0),
    "C": ("GEMINI_PATCH", 2),
}


def make_spec(candidate_id: str) -> CandidateSpec:
    kind, rank = _KIND_RANK[candidate_id]
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


def evaluation_json(candidate_id: str, verdict: str = "PASS") -> str:
    now = datetime.now(UTC)
    return CandidateEvaluation(
        candidate_id=candidate_id,
        scenario_ids=list(_SCENARIOS),
        invariant_ids=list(_INVARIANTS),
        verdict=verdict,
        started_at_utc=now,
        finished_at_utc=now,
    ).model_dump_json()


class FakeMap:
    """One async item per input, in input order, like ``map.aio(order_outputs=True)``."""

    def __init__(self, items: Sequence[Any]) -> None:
        self._items = list(items)

    def __call__(
        self,
        inputs: Sequence[str],
        *,
        order_outputs: bool = True,
        return_exceptions: bool = True,
    ) -> AsyncIterator[Any]:
        self.last_inputs = list(inputs)
        self.last_order_outputs = order_outputs
        self.last_return_exceptions = return_exceptions
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[Any]:
        for item in self._items:
            yield item


async def test_race_returns_one_evaluation_per_spec_in_spec_order() -> None:
    specs = [make_spec("A"), make_spec("B"), make_spec("C")]
    # With order_outputs=True the real map yields one item per input, in input
    # order; the race must then return them in spec order with verdicts intact.
    runner = FakeMap([evaluation_json("A"), evaluation_json("B"), evaluation_json("C", "FAIL")])
    failures: list[str] = []

    results = await race(
        specs,
        runner,
        expected_scenario_ids=_SCENARIOS,
        expected_invariant_ids=_INVARIANTS,
        failures=failures,
    )

    assert [item.candidate_id for item in results] == ["A", "B", "C"]
    assert [item.verdict for item in results] == ["PASS", "PASS", "FAIL"]
    assert failures == []
    assert runner.last_order_outputs is True
    assert runner.last_inputs == [spec.model_dump_json() for spec in specs]


async def test_crashed_world_becomes_error_for_that_candidate_only() -> None:
    specs = [make_spec("A"), make_spec("B")]
    runner = FakeMap([evaluation_json("A"), RuntimeError("container died")])
    failures: list[str] = []

    results = await race(
        specs,
        runner,
        expected_scenario_ids=_SCENARIOS,
        expected_invariant_ids=_INVARIANTS,
        failures=failures,
    )

    assert results[0].verdict == "PASS"
    assert results[1].verdict == "ERROR"
    # The ERROR shell still carries the expected evidence matrix, so a central
    # validator fails closed on missing tuples rather than on an empty list.
    assert results[1].scenario_ids == _SCENARIOS
    assert results[1].invariant_ids == _INVARIANTS
    assert failures == ["B: RuntimeError: container died"]


async def test_missing_result_becomes_error_with_reason() -> None:
    specs = [make_spec("A"), make_spec("B"), make_spec("C")]
    runner = FakeMap([evaluation_json("A")])
    failures: list[str] = []

    results = await race(
        specs,
        runner,
        expected_scenario_ids=_SCENARIOS,
        expected_invariant_ids=_INVARIANTS,
        failures=failures,
    )

    assert [item.verdict for item in results] == ["PASS", "ERROR", "ERROR"]
    assert failures == [
        "B: no result returned for this candidate",
        "C: no result returned for this candidate",
    ]


async def test_malformed_payload_becomes_error_not_a_crash() -> None:
    specs = [make_spec("A"), make_spec("B")]
    runner = FakeMap(["{not json", evaluation_json("B")])
    failures: list[str] = []

    results = await race(
        specs,
        runner,
        expected_scenario_ids=_SCENARIOS,
        expected_invariant_ids=_INVARIANTS,
        failures=failures,
    )

    assert results[0].verdict == "ERROR"
    assert results[1].verdict == "PASS"
    assert failures and failures[0].startswith("A: invalid CandidateEvaluation")


async def test_mismatched_candidate_id_is_rejected_for_that_slot() -> None:
    specs = [make_spec("A"), make_spec("B")]
    runner = FakeMap([evaluation_json("B"), evaluation_json("B")])
    failures: list[str] = []

    results = await race(
        specs,
        runner,
        expected_scenario_ids=_SCENARIOS,
        expected_invariant_ids=_INVARIANTS,
        failures=failures,
    )

    assert results[0].verdict == "ERROR"
    assert results[1].verdict == "PASS"
    assert failures == ["A: map item carried candidate_id 'B'"]


async def test_extra_items_are_ignored_and_recorded() -> None:
    specs = [make_spec("A")]
    runner = FakeMap([evaluation_json("A"), evaluation_json("B")])
    failures: list[str] = []

    results = await race(
        specs,
        runner,
        expected_scenario_ids=_SCENARIOS,
        expected_invariant_ids=_INVARIANTS,
        failures=failures,
    )

    assert [item.candidate_id for item in results] == ["A"]
    assert results[0].verdict == "PASS"
    assert failures == ["race: 1 extra map item(s) ignored"]
