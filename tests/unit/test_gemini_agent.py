"""Gemini failures are labelled skips and never fabricated diagnoses."""

from __future__ import annotations

import pytest

from services.gemini_agent import TypedGeminiAdvisor


@pytest.mark.asyncio
async def test_missing_model_is_a_labelled_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    advisor = TypedGeminiAdvisor(model="")
    outcome = await advisor.propose(None)  # type: ignore[arg-type]
    assert outcome.diagnosis is None
    assert outcome.patches == ()
    assert outcome.failure_reason == "GEMINI_UNAVAILABLE:NO_MODEL"


@pytest.mark.asyncio
async def test_missing_api_key_is_a_labelled_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    advisor = TypedGeminiAdvisor(model="google:gemini-test")
    outcome = await advisor.propose(None)  # type: ignore[arg-type]
    assert outcome.diagnosis is None
    assert outcome.failure_reason == "GEMINI_UNAVAILABLE:NO_API_KEY"
