"""Deterministic candidate selection; models never choose the winner."""

from __future__ import annotations

from dataclasses import dataclass

from apps.contracts.evaluation import CandidateEvaluation
from apps.contracts.incident import CandidateSpec


@dataclass(frozen=True)
class SelectionDecision:
    winner: CandidateSpec | None
    reason: str
    eligible_candidate_ids: tuple[str, ...]


def select_candidate(
    specs: list[CandidateSpec], evaluations: list[CandidateEvaluation]
) -> SelectionDecision:
    """Select only a complete PASS, tie-breaking with the code-owned risk rank."""
    spec_ids = [spec.candidate_id for spec in specs]
    evaluation_ids = [evaluation.candidate_id for evaluation in evaluations]
    if len(set(spec_ids)) != len(spec_ids):
        return SelectionDecision(None, "duplicate candidate specs", ())
    if len(set(evaluation_ids)) != len(evaluation_ids):
        return SelectionDecision(None, "duplicate candidate evaluations", ())

    by_candidate = {evaluation.candidate_id: evaluation for evaluation in evaluations}
    missing = [candidate_id for candidate_id in spec_ids if candidate_id not in by_candidate]
    if missing:
        return SelectionDecision(None, f"missing evaluations for {missing}", ())

    eligible = [
        spec
        for spec in specs
        if spec.live_eligible
        and by_candidate[spec.candidate_id].verdict == "PASS"
        and by_candidate[spec.candidate_id].evidence_set_sha256 is not None
    ]
    eligible.sort(key=lambda spec: (spec.rank, spec.candidate_id))
    if not eligible:
        return SelectionDecision(
            None,
            "no live-eligible candidate passed every required gate",
            (),
        )
    winner = eligible[0]
    return SelectionDecision(
        winner,
        (
            f"{winner.candidate_id} selected from complete PASS candidates by "
            "lowest fixed risk rank; model confidence was not considered"
        ),
        tuple(spec.candidate_id for spec in eligible),
    )
