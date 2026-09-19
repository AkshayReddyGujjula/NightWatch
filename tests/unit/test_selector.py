"""Code-owned candidate policy; model confidence is never an input."""

from __future__ import annotations

from datetime import UTC, datetime

from apps.contracts.evaluation import CandidateEvaluation
from apps.contracts.incident import CandidateSpec
from services.selector import select_candidate


def _spec(candidate_id: str) -> CandidateSpec:
    table = {
        "A": ("ROLLBACK", 1),
        "B": ("SAFE_HANDLER", 0),
        "C": ("GEMINI_PATCH", 2),
    }
    kind, rank = table[candidate_id]
    return CandidateSpec(
        candidate_id=candidate_id,  # type: ignore[arg-type]
        kind=kind,  # type: ignore[arg-type]
        rank=rank,
        live_eligible=True,
        image_digest="image",
        code_hash="a" * 64,
        base_commit_sha="b" * 40,
        capsule_sha256="c" * 64,
        seed_hash="d" * 64,
        provider_namespace=f"candidate-{candidate_id.lower()}",
    )


def _evaluation(candidate_id: str, verdict: str) -> CandidateEvaluation:
    now = datetime.now(UTC)
    return CandidateEvaluation(
        candidate_id=candidate_id,  # type: ignore[arg-type]
        scenario_ids=["S03"],
        invariant_ids=["INV-01"],
        verdict=verdict,  # type: ignore[arg-type]
        started_at_utc=now,
        finished_at_utc=now,
        evidence_set_sha256="e" * 64 if verdict == "PASS" else None,
    )


def test_lowest_fixed_risk_rank_wins_among_complete_passes() -> None:
    decision = select_candidate(
        [_spec("A"), _spec("B"), _spec("C")],
        [_evaluation("A", "PASS"), _evaluation("B", "PASS"), _evaluation("C", "PASS")],
    )
    assert decision.winner is not None
    assert decision.winner.candidate_id == "B"
    assert decision.eligible_candidate_ids == ("B", "A", "C")
    assert "model confidence was not considered" in decision.reason


def test_error_fail_and_missing_evaluations_never_win() -> None:
    no_pass = select_candidate(
        [_spec("A"), _spec("B")],
        [_evaluation("A", "ERROR"), _evaluation("B", "FAIL")],
    )
    assert no_pass.winner is None
    missing = select_candidate([_spec("A"), _spec("B")], [_evaluation("A", "PASS")])
    assert missing.winner is None
    assert "missing evaluations" in missing.reason


def test_pass_without_bound_evidence_hash_never_wins() -> None:
    malformed = _evaluation("B", "PASS").model_copy(
        update={"evidence_set_sha256": None}
    )
    decision = select_candidate([_spec("B")], [malformed])
    assert decision.winner is None
