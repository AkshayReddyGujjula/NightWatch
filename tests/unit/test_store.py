"""Store-level CAS guards: settled orders are never overwritten (plan INV-02)."""

from __future__ import annotations

from apps.contracts.payment import IntentItem
from apps.live_store.router import Router
from apps.live_store.store import Store


def make_store_with_order() -> tuple[Store, str, str, str]:
    store = Store()
    intent = store.create_intent("cust_unit", [IntentItem(sku="SKU-A", quantity=1)])
    order, operation = store.get_or_create_order_and_operation(intent.intent_id, 7999)
    return store, intent.intent_id, order.order_id, operation.operation_id


def test_late_outcome_cannot_overwrite_paid_order() -> None:
    store, _intent_id, order_id, operation_id = make_store_with_order()
    assert store.mark_paid(order_id, operation_id, "SKU-A", 1) is True
    assert store.set_order_status_if_unsettled(order_id, "PENDING_CONFIRMATION") is False
    assert store.get_order(order_id).status == "PAID"


def test_mark_paid_cannot_resurrect_quarantined_or_refunded_order() -> None:
    store, intent_id, order_id, operation_id = make_store_with_order()
    store.set_order_status(order_id, "QUARANTINED")
    assert store.mark_paid(order_id, operation_id, "SKU-A", 1) is False
    facts = store.store_facts(intent_id)
    assert facts.order_status == "QUARANTINED"
    assert facts.confirmation_count == 0
    assert facts.fulfillment_count == 0

    store2, _intent2, order2, operation2 = make_store_with_order()
    assert store2.mark_paid(order2, operation2, "SKU-A", 1) is True
    store2.set_order_status(order2, "REFUNDED_FULL")
    assert store2.mark_paid(order2, operation2, "SKU-A", 1) is False
    assert store2.get_order(order2).status == "REFUNDED_FULL"


def test_reset_live_clears_the_buggy_latch_for_the_next_rehearsal() -> None:
    store = Store()
    router = Router(store)
    router.set_mode("BUGGY", expected_generation=store.router_state().generation)
    router.set_mode("SAFE_HOLD", expected_generation=store.router_state().generation)
    assert store.buggy_locked() is True

    store.reset_live()
    assert store.buggy_locked() is False
    assert store.router_state().mode == "SAFE_HOLD"

    router.set_mode("BUGGY", expected_generation=store.router_state().generation)
    assert store.router_state().mode == "BUGGY"
