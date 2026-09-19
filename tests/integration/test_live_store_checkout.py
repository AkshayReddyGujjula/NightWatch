"""Integration: checkout and refund paths against the real provider app (plan §13)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from apps.live_store.router import safe_handler_hash
from tests.helpers import (
    CHECKOUT_BODY,
    EVAL_HEADERS,
    LIVE_HEADERS,
    Stack,
    arm_fault,
    pre_register,
    read_facts,
    read_ledger,
    set_router_mode,
    start_checkout,
)


async def test_operator_can_arm_visible_double_charge_showcase(stack_factory) -> None:
    stack: Stack = await stack_factory(namespace="ns_demo_setup_control")
    armed = await stack.store_client.post(
        "/internal/demo/arm-double-charge", headers=LIVE_HEADERS
    )
    assert armed.status_code == 200, armed.text
    setup = armed.json()
    assert setup["router"]["mode"] == "BUGGY"
    assert setup["checkout_x_url"].endswith(f"?intent={setup['intent_id']}")

    checkout = await stack.store_client.post(
        f"/api/checkout/{setup['intent_id']}", json=CHECKOUT_BODY
    )
    assert checkout.status_code == 200, checkout.text
    result = checkout.json()
    assert result["status"] == "PAID"
    assert "You were charged twice" in result["message"]

    ledger = await stack.evaluator_client.get(
        f"/internal/ledger/{setup['namespace']}", headers=EVAL_HEADERS
    )
    assert ledger.status_code == 200, ledger.text
    assert len(ledger.json()["captures"]) == 2


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
    await pre_register(stack, intent_id=intent_id, amount_minor=created.json()["amount_minor"])

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


async def test_settled_order_is_never_overwritten(stack_factory) -> None:
    stack: Stack = await stack_factory(namespace="ns_settled")
    await set_router_mode(stack, "SAFE", lease_id="lease_test")
    intent_id, body = await start_checkout(stack)
    order_id = body["order_id"]

    replay = await stack.store_client.post(
        f"/api/checkout/{intent_id}",
        json={**CHECKOUT_BODY, "voucher_code": "NIGHT10"},
    )
    assert replay.status_code == 200
    assert replay.json()["status"] == "PAID"
    assert len((await read_ledger(stack))["captures"]) == 1

    refund = await stack.store_client.post(
        "/api/refunds",
        json={"order_id": order_id, "refund_intent_id": "ri_full", "amount_minor": 7999},
    )
    assert refund.json()["status"] == "REFUNDED_FULL"

    after_refund = await stack.store_client.post(f"/api/checkout/{intent_id}", json=CHECKOUT_BODY)
    assert after_refund.json()["status"] == "REFUNDED_FULL"
    assert len((await read_ledger(stack))["captures"]) == 1


async def test_buggy_cannot_be_rearmed_after_containment(stack_factory) -> None:
    stack: Stack = await stack_factory(namespace="ns_rearm")
    await set_router_mode(stack, "BUGGY")
    await set_router_mode(stack, "SAFE_HOLD")

    current = await stack.store_client.get("/internal/router", headers=LIVE_HEADERS)
    attempt = await stack.store_client.put(
        "/internal/router",
        json={"mode": "BUGGY", "expected_generation": current.json()["generation"]},
        headers=LIVE_HEADERS,
    )
    assert attempt.status_code == 409


async def test_safe_requires_handler_hash_and_expiry(stack_factory) -> None:
    stack: Stack = await stack_factory(namespace="ns_lease")
    generation = (
        await stack.store_client.get("/internal/router", headers=LIVE_HEADERS)
    ).json()["generation"]

    no_expiry = await stack.store_client.put(
        "/internal/router",
        json={"mode": "SAFE", "expected_generation": generation, "lease_id": "lease_x"},
        headers=LIVE_HEADERS,
    )
    assert no_expiry.status_code == 422

    wrong_hash = await stack.store_client.put(
        "/internal/router",
        json={
            "mode": "SAFE",
            "expected_generation": generation,
            "lease_id": "lease_x",
            "lease_expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
            "handler_sha256": "b" * 64,
        },
        headers=LIVE_HEADERS,
    )
    assert wrong_hash.status_code == 422


async def test_expired_lease_falls_back_to_safe_hold(stack_factory) -> None:
    stack: Stack = await stack_factory(namespace="ns_expiry")
    generation = (
        await stack.store_client.get("/internal/router", headers=LIVE_HEADERS)
    ).json()["generation"]
    response = await stack.store_client.put(
        "/internal/router",
        json={
            "mode": "SAFE",
            "expected_generation": generation,
            "lease_id": "lease_exp",
            "lease_expires_at": (datetime.now(UTC) + timedelta(seconds=1)).isoformat(),
            "handler_sha256": safe_handler_hash(),
        },
        headers=LIVE_HEADERS,
    )
    assert response.status_code == 200, response.text

    await asyncio.sleep(1.2)
    state = await stack.store_client.get("/internal/router", headers=LIVE_HEADERS)
    assert state.json()["mode"] == "SAFE_HOLD"
