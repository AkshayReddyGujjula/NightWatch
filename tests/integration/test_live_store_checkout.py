"""Integration: checkout and refund paths against the real provider app (plan §13)."""

from __future__ import annotations

import asyncio

from tests.helpers import (
    CHECKOUT_BODY,
    LIVE_HEADERS,
    Stack,
    arm_fault,
    read_facts,
    read_ledger,
    set_router_mode,
    start_checkout,
)


async def test_safe_checkout_pays_exactly_once(stack_factory) -> None:
    stack: Stack = await stack_factory(namespace="ns_s01")
    await set_router_mode(stack, "SAFE", lease_id="lease_test")
    intent_id, body = await start_checkout(stack)
    assert body["status"] == "PAID"
    assert body["amount_minor"] == 7999

    ledger = await read_ledger(stack)
    assert len(ledger["captures"]) == 1
    assert ledger["captures"][0]["amount_minor"] == 7999

    facts = await read_facts(stack, intent_id)
    assert facts["order_status"] == "PAID"
    assert facts["order_count"] == 1
    assert facts["operation_count"] == 1
    assert facts["confirmation_count"] == 1
    assert facts["fulfillment_count"] == 1
    assert facts["stock_remaining"] == 99


async def test_s02_drop_after_capture_recovers_via_inquiry(stack_factory) -> None:
    stack: Stack = await stack_factory(namespace="ns_s02")
    await set_router_mode(stack, "SAFE", lease_id="lease_test")
    await arm_fault(stack, "DROP_AFTER_CAPTURE_ONCE")
    intent_id, body = await start_checkout(stack)
    assert body["status"] == "PAID"

    ledger = await read_ledger(stack)
    assert len(ledger["captures"]) == 1
    facts = await read_facts(stack, intent_id)
    assert facts["confirmation_count"] == 1
    assert facts["stock_remaining"] == 99


async def test_s08_timeout_before_capture_stays_pending(stack_factory) -> None:
    stack: Stack = await stack_factory(namespace="ns_s08")
    await set_router_mode(stack, "SAFE", lease_id="lease_test")
    await arm_fault(stack, "TIMEOUT_BEFORE_CAPTURE_ONCE")
    intent_id, body = await start_checkout(stack)
    assert body["status"] == "PENDING_CONFIRMATION"

    ledger = await read_ledger(stack)
    assert ledger["captures"] == []
    facts = await read_facts(stack, intent_id)
    assert facts["order_status"] == "PENDING_CONFIRMATION"
    assert facts["confirmation_count"] == 0
    assert facts["stock_remaining"] == 100


async def test_s03_concurrent_submits_are_idempotent(stack_factory) -> None:
    stack: Stack = await stack_factory(namespace="ns_s03")
    await set_router_mode(stack, "SAFE", lease_id="lease_test")
    created = await stack.store_client.post(
        "/api/intents",
        json={"customer_id": "cust_test", "items": [{"sku": "SKU-A", "quantity": 1}]},
    )
    intent_id = created.json()["intent_id"]

    responses = await asyncio.gather(
        *(
            stack.store_client.post(f"/api/checkout/{intent_id}", json=CHECKOUT_BODY)
            for _ in range(2)
        )
    )
    assert all(response.status_code == 200 for response in responses)
    assert all(response.json()["status"] == "PAID" for response in responses)

    ledger = await read_ledger(stack)
    assert len(ledger["captures"]) == 1
    facts = await read_facts(stack, intent_id)
    assert facts["order_count"] == 1
    assert facts["operation_count"] == 1
    assert facts["confirmation_count"] == 1
    assert facts["fulfillment_count"] == 1
    assert facts["stock_remaining"] == 99


async def test_s06_full_refund_and_replay(stack_factory) -> None:
    stack: Stack = await stack_factory(namespace="ns_s06")
    await set_router_mode(stack, "SAFE", lease_id="lease_test")
    _intent_id, body = await start_checkout(stack)
    order_id = body["order_id"]

    refund = {
        "order_id": order_id,
        "refund_intent_id": "ri_full",
        "amount_minor": 7999,
    }
    first = await stack.store_client.post("/api/refunds", json=refund)
    assert first.status_code == 200
    assert first.json()["status"] == "REFUNDED_FULL"

    replay = await stack.store_client.post("/api/refunds", json=refund)
    assert replay.status_code == 200
    assert replay.json()["status"] == "REFUNDED_FULL"

    ledger = await read_ledger(stack)
    assert len(ledger["refunds"]) == 1
    assert ledger["refunds"][0]["amount_minor"] == 7999


async def test_s07_partial_refunds_and_replay(stack_factory) -> None:
    stack: Stack = await stack_factory(namespace="ns_s07")
    await set_router_mode(stack, "SAFE", lease_id="lease_test")
    _intent_id, body = await start_checkout(stack)
    order_id = body["order_id"]

    first = await stack.store_client.post(
        "/api/refunds",
        json={"order_id": order_id, "refund_intent_id": "ri_1", "amount_minor": 2000},
    )
    second = await stack.store_client.post(
        "/api/refunds",
        json={"order_id": order_id, "refund_intent_id": "ri_2", "amount_minor": 1000},
    )
    assert first.json()["status"] == "REFUNDED_PARTIAL"
    assert second.json()["status"] == "REFUNDED_PARTIAL"

    replay = await stack.store_client.post(
        "/api/refunds",
        json={"order_id": order_id, "refund_intent_id": "ri_2", "amount_minor": 1000},
    )
    assert replay.json()["status"] == "REFUNDED_PARTIAL"

    ledger = await read_ledger(stack)
    assert len(ledger["refunds"]) == 2
    assert sum(row["amount_minor"] for row in ledger["refunds"]) == 3000


async def test_safe_hold_blocks_new_captures(stack_factory) -> None:
    stack: Stack = await stack_factory(namespace="ns_hold")
    _intent_id, body = await start_checkout(stack)
    assert body["status"] == "SAFE_HOLD"
    assert body["order_id"] is None
    ledger = await read_ledger(stack)
    assert ledger["captures"] == []


async def test_router_generation_cas_rejects_stale_writers(stack_factory) -> None:
    stack: Stack = await stack_factory(namespace="ns_cas")
    current = await stack.store_client.get("/internal/router", headers=LIVE_HEADERS)
    generation = current.json()["generation"]

    first = await stack.store_client.put(
        "/internal/router",
        json={"mode": "BUGGY", "expected_generation": generation},
        headers=LIVE_HEADERS,
    )
    assert first.status_code == 200
    assert first.json()["generation"] == generation + 1

    stale = await stack.store_client.put(
        "/internal/router",
        json={"mode": "SAFE_HOLD", "expected_generation": generation},
        headers=LIVE_HEADERS,
    )
    assert stale.status_code == 409

    legacy = await stack.store_client.put(
        "/internal/router",
        json={"mode": "LEGACY", "expected_generation": generation + 1},
        headers=LIVE_HEADERS,
    )
    assert legacy.status_code == 409
