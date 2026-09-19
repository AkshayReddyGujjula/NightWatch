"""Frozen-example and strictness tests for the browser contracts (plan §7)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from apps.contracts.browser import (
    MAX_FRAME_BYTES,
    BrowserBarrierState,
    BrowserFrame,
    BrowserReadyRequest,
    JevDecision,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "expected"


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def frame_payload() -> dict[str, Any]:
    return load("internal_frames_metadata.json")


def parse_frame(payload: dict[str, Any]) -> BrowserFrame:
    return BrowserFrame.model_validate_json(json.dumps(payload), strict=True)


def test_frozen_frame_example_validates() -> None:
    frame = parse_frame(frame_payload())
    assert frame.candidate_id == "B"
    assert frame.phase == "AFTER_ACTION"
    assert frame.image_size_bytes <= MAX_FRAME_BYTES


def test_frame_rejects_extra_field() -> None:
    with pytest.raises(ValidationError):
        parse_frame(frame_payload() | {"surprise": 1})


def test_frame_rejects_strict_type_coercion() -> None:
    with pytest.raises(ValidationError):
        parse_frame(frame_payload() | {"frame_seq": "7"})


def test_frame_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError):
        parse_frame(frame_payload() | {"captured_at_utc": "2026-09-19T13:05:00"})


def test_frame_normalises_aware_datetime_to_utc() -> None:
    frame = parse_frame(frame_payload() | {"captured_at_utc": "2026-09-19T14:05:00+01:00"})
    assert frame.captured_at_utc.isoformat() == "2026-09-19T13:05:00+00:00"


def test_frame_rejects_oversize_declared_size() -> None:
    with pytest.raises(ValidationError):
        parse_frame(frame_payload() | {"image_size_bytes": MAX_FRAME_BYTES + 1})


def test_frame_is_frozen() -> None:
    frame = parse_frame(frame_payload())
    with pytest.raises(ValidationError):
        frame.frame_seq = 8  # type: ignore[misc]


def test_jev_decision_accepts_pilot_shaped_response() -> None:
    payload = {
        "decision_id": "dec-0001",
        "chosen_action_id": "click__a17",
        "operation": "click",
        "model_name": "jev-1.13.0",
        "confidence": 0.27,
        "probabilities": {"abstain": 0.45, "click__a17": 0.52, "reobserve": 0.03},
        "observation_hash": "a" * 64,
    }
    decision = JevDecision.model_validate_json(json.dumps(payload), strict=True)
    assert decision.probabilities["abstain"] == 0.45


def test_jev_decision_rejects_out_of_bounds_confidence() -> None:
    payload = {
        "decision_id": "dec-0001",
        "chosen_action_id": "click__a17",
        "operation": "click",
        "model_name": "jev-1.13.0",
        "confidence": 1.5,
        "probabilities": {"click__a17": 0.52},
        "observation_hash": "a" * 64,
    }
    with pytest.raises(ValidationError):
        JevDecision.model_validate_json(json.dumps(payload), strict=True)


def test_jev_decision_rejects_unknown_operation() -> None:
    payload = {
        "decision_id": "dec-0001",
        "chosen_action_id": "click__a17",
        "operation": "deploy_everything",
        "model_name": "jev-1.13.0",
        "confidence": 0.5,
        "probabilities": {"click__a17": 0.52},
        "observation_hash": "a" * 64,
    }
    with pytest.raises(ValidationError):
        JevDecision.model_validate_json(json.dumps(payload), strict=True)


def test_ready_request_example_validates() -> None:
    body = BrowserReadyRequest.model_validate_json(
        json.dumps(load("browser_ready_request.json")), strict=True
    )
    assert body.run_id == "run_20260919_1330"


def test_barrier_state_example_validates() -> None:
    state = BrowserBarrierState.model_validate_json(
        json.dumps(load("browser_barrier_state.json")), strict=True
    )
    assert state.status == "RELEASED"
    assert len(state.ready) == 3
