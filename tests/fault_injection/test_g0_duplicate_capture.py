"""Gate G0 (plan §18): one intent -> exactly two captures while health is 200,
and the original namespace cannot be reset or changed by reproduction runs.
"""

from __future__ import annotations

import json

from apps.contracts.payment import LedgerView
from services.detector import detect_duplicate_capture
from tests.helpers import (
    EVAL_HEADERS,
    Stack,
    arm_fault,
    read_ledger,
    set_router_mode,
    start_checkout,
)


async def test_g0_duplicate_capture_with_immutable_original(stack_factory) -> None:
    original: Stack = await stack_factory(namespace="ns_original")
    await set_router_mode(original, "BUGGY")
    await arm_fault(original, "DROP_AFTER_CAPTURE_ONCE")

    intent_id, body = await start_checkout(original)
    assert body["status"] == "PAID"

    health = await original.store_client.get("/health")
    assert health.status_code == 200
    assert health.json()["mode"] == "BUGGY"

    before = await read_ledger(original)
    captures = before["captures"]
    assert len(captures) == 2, "the buggy handler must produce exactly two captures"
    assert len({row["idempotency_key"] for row in captures}) == 2
    assert {row["amount_minor"] for row in captures} == {7999}
    assert {row["currency"] for row in captures} == {"GBP"}
    assert len({row["operation_id"] for row in captures}) == 1

    detection = detect_duplicate_capture(
        LedgerView.model_validate_json(json.dumps(before)), intent_id=intent_id
    )
    assert detection is not None
    assert detection.invariant_id == "INV-01"
    assert len(detection.capture_ids) == 2

    # Reproduction runs in a fresh namespace and must not touch the original.
    repro: Stack = await stack_factory(namespace="ns_repro")
    await set_router_mode(repro, "SAFE", lease_id="lease_repro")
    await start_checkout(repro)

    after_repro = await read_ledger(original)
    assert after_repro["digest"] == before["digest"]

    # A reset creates a NEW namespace; the original can never be overwritten.
    duplicate = await original.evaluator_client.post(
        "/internal/namespaces", json={"namespace": "ns_original"}, headers=EVAL_HEADERS
    )
    assert duplicate.status_code == 409
    fresh = await original.evaluator_client.post(
        "/internal/namespaces", json={"namespace": "ns_reset_fresh"}, headers=EVAL_HEADERS
    )
    assert fresh.status_code == 201

    after_reset = await read_ledger(original)
    assert after_reset["digest"] == before["digest"]
    assert len(after_reset["captures"]) == 2
