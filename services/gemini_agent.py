"""Typed Gemini diagnosis from the frozen incident capsule only."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Protocol

from pydantic import Field

from apps.contracts.base import StrictModel
from apps.contracts.incident import (
    GeminiDiagnosis,
    Hypothesis,
    IncidentCapsule,
    PatchProposal,
    RequestedExperiment,
    TriageAdvisory,
)


class DiagnosisDraft(StrictModel):
    hypotheses: list[Hypothesis] = Field(min_length=1, max_length=3)
    requested_experiment: RequestedExperiment
    uncertainty: float = Field(ge=0.0, le=1.0)
    triage: TriageAdvisory


@dataclass(frozen=True)
class GeminiOutcome:
    diagnosis: GeminiDiagnosis | None
    patches: tuple[PatchProposal, ...] = ()
    failure_reason: str | None = None


class GeminiAdvisor(Protocol):
    async def propose(self, capsule: IncidentCapsule) -> GeminiOutcome: ...


class TypedGeminiAdvisor:
    """Pydantic-AI structured output; absence/failure is a labelled skip."""

    def __init__(
        self,
        *,
        model: str,
        timeout_seconds: float = 25.0,
    ) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def propose(self, capsule: IncidentCapsule) -> GeminiOutcome:
        if not self.model:
            return GeminiOutcome(None, failure_reason="GEMINI_UNAVAILABLE:NO_MODEL")
        if not (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")):
            return GeminiOutcome(None, failure_reason="GEMINI_UNAVAILABLE:NO_API_KEY")
        try:
            from pydantic_ai import Agent

            agent = Agent(
                self.model,
                output_type=DiagnosisDraft,
                system_prompt=(
                    "You are NightWatch's advisory incident diagnostician. Use only the "
                    "frozen capsule JSON. Cite capsule evidence identifiers in hypotheses. "
                    "Do not grade candidates, select repairs, issue leases, or claim facts "
                    "outside the capsule. Return only the requested structured output."
                ),
                retries=1,
            )
            result = await asyncio.wait_for(
                agent.run(capsule.model_dump_json()), timeout=self.timeout_seconds
            )
            draft = result.output
            diagnosis = GeminiDiagnosis(
                hypotheses=draft.hypotheses,
                requested_experiment=draft.requested_experiment,
                uncertainty=draft.uncertainty,
                triage=draft.triage,
                model_name=self.model,
                model_version=None,
            )
            # Multi-patch generation is Task 4. Until its guard lands, C is
            # explicitly skipped rather than accepting unguarded generated code.
            return GeminiOutcome(
                diagnosis,
                failure_reason="C_SKIPPED_PATCH_GUARD_NOT_WIRED",
            )
        except Exception as exc:  # noqa: BLE001 - model failures are typed degradation
            return GeminiOutcome(
                None,
                failure_reason=f"GEMINI_INVALID:{type(exc).__name__}",
            )
