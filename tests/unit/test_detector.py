"""Detector unit tests: INV-01 across operations and capture sets (plan §5.4)."""

from __future__ import annotations

from datetime import UTC, datetime

from apps.contracts.payment import CaptureRow, LedgerView, RegistrationRow
from services.detector import detect_duplicate_capture

NS = "ns_detector"


def registration(operation_id: str, intent_id: str) -> RegistrationRow:
    return RegistrationRow(
        namespace=NS,
        operation_id=operation_id,
        intent_id=intent_id,
        amount_minor=7999,
        currency="GBP",
        allowed_actions=["capture", "refund", "inquiry"],
        registered_at=datetime.now(UTC),
    )


def capture(operation_id: str, capture_id: str, key: str, amount_minor: int = 7999) -> CaptureRow:
    return CaptureRow(
        capture_id=capture_id,
        namespace=NS,
        operation_id=operation_id,
        idempotency_key=key,
        amount_minor=amount_minor,
        currency="GBP",
        captured_at=datetime.now(UTC),
    )


def ledger(
    registrations: list[RegistrationRow], captures: list[CaptureRow]
) -> LedgerView:
    return LedgerView(
        namespace=NS,
        registrations=registrations,
        captures=captures,
        refunds=[],
        digest="a" * 64,
    )


def test_single_capture_is_clean() -> None:
    view = ledger([registration("op_1", "pi_1")], [capture("op_1", "cap_1", "k1")])
    assert detect_duplicate_capture(view, intent_id="pi_1") is None


def test_same_operation_duplicate_is_detected() -> None:
    view = ledger(
        [registration("op_1", "pi_1")],
        [capture("op_1", "cap_1", "k1"), capture("op_1", "cap_2", "k2")],
    )
    detection = detect_duplicate_capture(view, intent_id="pi_1")
    assert detection is not None
    assert detection.invariant_id == "INV-01"
    assert detection.capture_ids == ("cap_1", "cap_2")


def test_split_captures_across_operations_are_detected() -> None:
    """A duplicate may not hide by splitting operations (NC-02 shape)."""
    view = ledger(
        [registration("op_a", "pi_1"), registration("op_b", "pi_1")],
        [capture("op_a", "cap_1", "k1"), capture("op_b", "cap_2", "k2")],
    )
    detection = detect_duplicate_capture(view, intent_id="pi_1")
    assert detection is not None
    assert len(detection.capture_ids) == 2


def test_unknown_intent_is_clean() -> None:
    view = ledger([registration("op_1", "pi_1")], [capture("op_1", "cap_1", "k1")])
    assert detect_duplicate_capture(view, intent_id="pi_never") is None
