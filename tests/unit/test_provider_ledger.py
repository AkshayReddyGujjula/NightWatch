"""Append-only ledger semantics: replay, rejections, refunds, digest (plan §5.3)."""

from __future__ import annotations

import pytest

from apps.contracts.payment import CaptureRequest, OperationRegisterRequest, RefundRequest
from apps.trusted_provider.ledger import LedgerStore, ProviderError

NS = "ns_unit"
OTHER_NS = "ns_unit_other"
OP = "op_1"
ALLOWED = ["op_1"]
WILDCARD = ["*"]


def make_store() -> LedgerStore:
    store = LedgerStore()
    store.create_namespace(NS)
    store.register_operation(
        OperationRegisterRequest(
            namespace=NS,
            operation_id=OP,
            intent_id="pi_unit_001",
            amount_minor=7999,
            currency="GBP",
            allowed_actions=["capture", "refund", "inquiry"],
        )
    )
    return store


def capture_request(**overrides: object) -> CaptureRequest:
    payload: dict[str, object] = {
        "operation_id": OP,
        "idempotency_key": "key_1",
        "amount_minor": 7999,
        "currency": "GBP",
    }
    payload.update(overrides)
    return CaptureRequest(**payload)


def test_same_key_replay_returns_cached_capture() -> None:
    store = make_store()
    first = store.capture(NS, capture_request(), allowed_operation_ids=ALLOWED)
    replay = store.capture(NS, capture_request(), allowed_operation_ids=ALLOWED)
    assert replay.replayed is True
    assert replay.capture_id == first.capture_id
    assert len(store.captures_for(NS, OP)) == 1


def test_same_key_changed_parameters_is_rejected() -> None:
    store = make_store()
    store.capture(NS, capture_request(), allowed_operation_ids=ALLOWED)
    with pytest.raises(ProviderError) as excinfo:
        store.capture(NS, capture_request(amount_minor=8000), allowed_operation_ids=ALLOWED)
    assert excinfo.value.status_code == 409
    assert len(store.captures_for(NS, OP)) == 1


def test_fresh_key_appends_a_second_capture() -> None:
    store = make_store()
    first = store.capture(NS, capture_request(), allowed_operation_ids=ALLOWED)
    second = store.capture(
        NS, capture_request(idempotency_key="key_2"), allowed_operation_ids=ALLOWED
    )
    captures = store.captures_for(NS, OP)
    assert len(captures) == 2
    assert {captures[0].capture_id, captures[1].capture_id} == {first.capture_id, second.capture_id}
    assert captures[0].idempotency_key != captures[1].idempotency_key


def test_unknown_operation_is_rejected() -> None:
    store = make_store()
    with pytest.raises(ProviderError) as excinfo:
        store.capture(
            NS, capture_request(operation_id="op_unknown"), allowed_operation_ids=ALLOWED
        )
    assert excinfo.value.status_code == 404


def test_registration_amount_mismatch_is_rejected() -> None:
    store = make_store()
    with pytest.raises(ProviderError) as excinfo:
        store.capture(NS, capture_request(amount_minor=8000), allowed_operation_ids=ALLOWED)
    assert excinfo.value.status_code == 409


def test_wildcard_token_cannot_auto_register_operations() -> None:
    store = make_store()
    with pytest.raises(ProviderError) as excinfo:
        store.capture(
            NS,
            capture_request(operation_id="op_dynamic", intent_id="pi_dynamic"),
            allowed_operation_ids=WILDCARD,
        )
    assert excinfo.value.status_code == 404


def test_explicit_token_can_auto_register_once() -> None:
    store = make_store()
    request = capture_request(operation_id="op_dynamic")
    with pytest.raises(ProviderError) as excinfo:
        store.capture(NS, request, allowed_operation_ids=["op_dynamic"])
    assert excinfo.value.status_code == 422  # intent_id required on auto-registration

    registered = store.capture(
        NS,
        capture_request(operation_id="op_dynamic", intent_id="pi_dynamic"),
        allowed_operation_ids=["op_dynamic"],
    )
    assert registered.replayed is False


def test_capture_requires_the_capture_action() -> None:
    store = LedgerStore()
    store.create_namespace(NS)
    store.register_operation(
        OperationRegisterRequest(
            namespace=NS,
            operation_id=OP,
            intent_id="pi_unit_003",
            amount_minor=7999,
            currency="GBP",
            allowed_actions=["refund", "inquiry"],
        )
    )
    with pytest.raises(ProviderError) as excinfo:
        store.capture(NS, capture_request(), allowed_operation_ids=ALLOWED)
    assert excinfo.value.status_code == 403


def test_intent_mismatch_is_rejected() -> None:
    store = make_store()
    with pytest.raises(ProviderError) as excinfo:
        store.capture(
            NS, capture_request(intent_id="pi_other"), allowed_operation_ids=ALLOWED
        )
    assert excinfo.value.status_code == 409


def test_two_operations_for_one_intent_are_rejected() -> None:
    store = make_store()
    with pytest.raises(ProviderError) as excinfo:
        store.register_operation(
            OperationRegisterRequest(
                namespace=NS,
                operation_id="op_second",
                intent_id="pi_unit_001",
                amount_minor=7999,
                currency="GBP",
                allowed_actions=["capture"],
            )
        )
    assert excinfo.value.status_code == 409


def test_namespaces_are_isolated() -> None:
    store = make_store()
    store.create_namespace(OTHER_NS)
    store.capture(NS, capture_request(), allowed_operation_ids=ALLOWED)
    assert store.captures_for(OTHER_NS, OP) == []
    assert store.ledger_view(NS).digest != store.ledger_view(OTHER_NS).digest


def test_refund_replay_appends_nothing() -> None:
    store = make_store()
    store.capture(NS, capture_request(), allowed_operation_ids=ALLOWED)
    request = RefundRequest(operation_id=OP, refund_intent_id="ri_1", amount_minor=1000)
    first = store.refund(NS, request, allowed_operation_ids=ALLOWED)
    replay = store.refund(NS, request, allowed_operation_ids=ALLOWED)
    assert replay.refund_id == first.refund_id
    assert replay.total_refunded_minor == 1000
    assert replay.status == "REFUNDED_PARTIAL"
    assert len(store.ledger_view(NS).refunds) == 1


def test_refund_cannot_exceed_captured_total() -> None:
    store = make_store()
    store.capture(NS, capture_request(), allowed_operation_ids=ALLOWED)
    with pytest.raises(ProviderError) as excinfo:
        store.refund(
            NS,
            RefundRequest(operation_id=OP, refund_intent_id="ri_big", amount_minor=8000),
            allowed_operation_ids=ALLOWED,
        )
    assert excinfo.value.status_code == 409


def test_full_refund_status() -> None:
    store = make_store()
    store.capture(NS, capture_request(), allowed_operation_ids=ALLOWED)
    result = store.refund(
        NS,
        RefundRequest(operation_id=OP, refund_intent_id="ri_full", amount_minor=7999),
        allowed_operation_ids=ALLOWED,
    )
    assert result.status == "REFUNDED_FULL"
    assert result.total_refunded_minor == 7999


def test_refund_requires_allowed_action() -> None:
    store = LedgerStore()
    store.create_namespace(NS)
    store.register_operation(
        OperationRegisterRequest(
            namespace=NS,
            operation_id=OP,
            intent_id="pi_unit_002",
            amount_minor=7999,
            currency="GBP",
            allowed_actions=["capture"],
        )
    )
    store.capture(NS, capture_request(), allowed_operation_ids=ALLOWED)
    with pytest.raises(ProviderError) as excinfo:
        store.refund(
            NS,
            RefundRequest(operation_id=OP, refund_intent_id="ri_1", amount_minor=100),
            allowed_operation_ids=ALLOWED,
        )
    assert excinfo.value.status_code == 403


def test_digest_is_stable_and_changes_on_append() -> None:
    store = make_store()
    before = store.namespace_digest(NS)
    assert store.namespace_digest(NS) == before
    store.capture(NS, capture_request(), allowed_operation_ids=ALLOWED)
    assert store.namespace_digest(NS) != before


def test_duplicate_namespace_rejected() -> None:
    store = make_store()
    with pytest.raises(ProviderError) as excinfo:
        store.create_namespace(NS)
    assert excinfo.value.status_code == 409
