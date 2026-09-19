"""Gate G0 evidence runner (plan §18).

Runs the complete duplicate-capture flow locally over in-process ASGI
transports — provider, live store, scoped tokens, the one-shot fault and the
detector — then prints JSON evidence with real values. No Modal, no network.

    uv run python scripts/g0_gate.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from apps.contracts.payment import LedgerView  # noqa: E402
from apps.live_store.app import StoreSettings as LiveStoreSettings  # noqa: E402
from apps.live_store.app import create_app as create_live_store_app  # noqa: E402
from apps.live_store.provider import HttpPaymentProvider  # noqa: E402
from apps.live_store.router import safe_handler_hash  # noqa: E402
from apps.trusted_provider.app import ProviderSettings  # noqa: E402
from apps.trusted_provider.app import create_app as create_provider_app  # noqa: E402
from services.detector import detect_duplicate_capture  # noqa: E402

EVALUATOR_TOKEN = "g0-evaluator-token"
LIVE_INTERNAL_TOKEN = "g0-live-internal-token"
SIGNING_SECRET = "g0-signing-secret"
EVAL_HEADERS = {"Authorization": f"Bearer {EVALUATOR_TOKEN}"}
LIVE_HEADERS = {"Authorization": f"Bearer {LIVE_INTERNAL_TOKEN}"}
CHECKOUT_BODY = {"email": "fixture@example.com", "address": "1 Test Street, London"}


async def main() -> int:
    if not __debug__:  # pragma: no cover - fail closed when run with python -O
        raise RuntimeError("gate assertions are disabled (python -O); refusing to run")
    provider_app = create_provider_app(
        ProviderSettings(provider_signing_secret=SIGNING_SECRET, evaluator_token=EVALUATOR_TOKEN),
        db_path=":memory:",
    )
    evaluator = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=provider_app), base_url="http://provider"
    )

    async def make_store(namespace: str) -> httpx.AsyncClient:
        created = await evaluator.post(
            "/internal/namespaces", json={"namespace": namespace}, headers=EVAL_HEADERS
        )
        assert created.status_code == 201, created.text
        token = (
            await evaluator.post(
                "/internal/scoped-tokens",
                json={
                    "incident_id": "NW-001",
                    "candidate_id": "B",
                    "scenario_id": "S02",
                    "namespace": namespace,
                    "allowed_operation_ids": ["*"],
                    "expires_in_seconds": 3600,
                },
                headers=EVAL_HEADERS,
            )
        ).json()["token"]
        provider_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=provider_app), base_url="http://provider"
        )
        live_app = create_live_store_app(
            LiveStoreSettings(
                live_internal_token=LIVE_INTERNAL_TOKEN, evaluator_token=EVALUATOR_TOKEN
            ),
            db_path=":memory:",
            provider=HttpPaymentProvider("http://provider", token, client=provider_client),
        )
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=live_app), base_url="http://store"
        )

    async def set_mode(store: httpx.AsyncClient, mode: str, *, lease_id: str | None = None) -> None:
        current = await store.get("/internal/router", headers=LIVE_HEADERS)
        body: dict[str, object] = {
            "mode": mode,
            "expected_generation": current.json()["generation"],
        }
        if mode == "SAFE":
            body["lease_id"] = lease_id or "lease_g0"
            body["lease_expires_at"] = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
            body["handler_sha256"] = safe_handler_hash()
        response = await store.put("/internal/router", json=body, headers=LIVE_HEADERS)
        assert response.status_code == 200, response.text

    async def pre_register(namespace: str, intent_id: str, amount_minor: int) -> None:
        response = await evaluator.post(
            "/internal/operations",
            json={
                "namespace": namespace,
                "operation_id": f"op_{intent_id}",
                "intent_id": intent_id,
                "amount_minor": amount_minor,
                "currency": "GBP",
                "allowed_actions": ["capture", "refund", "inquiry"],
            },
            headers=EVAL_HEADERS,
        )
        assert response.status_code == 201, response.text

    async def read_ledger(namespace: str) -> dict:
        response = await evaluator.get(f"/internal/ledger/{namespace}", headers=EVAL_HEADERS)
        assert response.status_code == 200, response.text
        return response.json()

    # -- incident in the original namespace ---------------------------------
    original = await make_store("ns_original")
    await set_mode(original, "BUGGY")
    armed = await evaluator.post(
        "/internal/faults",
        json={"namespace": "ns_original", "fault": "DROP_AFTER_CAPTURE_ONCE"},
        headers=EVAL_HEADERS,
    )
    assert armed.status_code == 204

    created = await original.post(
        "/api/intents",
        json={"customer_id": "cust_g0", "items": [{"sku": "SKU-A", "quantity": 1}]},
    )
    assert created.status_code == 201, created.text
    intent_id = created.json()["intent_id"]
    await pre_register("ns_original", intent_id, created.json()["amount_minor"])

    checkout = await original.post(f"/api/checkout/{intent_id}", json=CHECKOUT_BODY)
    assert checkout.status_code == 200, checkout.text
    assert checkout.json()["status"] == "PAID"

    health = await original.get("/health")
    assert health.status_code == 200
    assert health.json()["mode"] == "BUGGY"

    before = await read_ledger("ns_original")
    detection = detect_duplicate_capture(
        LedgerView.model_validate_json(json.dumps(before)), intent_id=intent_id
    )
    assert detection is not None, "the detector must qualify the INV-01 violation"
    assert len(before["captures"]) == 2

    # -- reproduction in a fresh namespace; original must not change --------
    repro = await make_store("ns_repro")
    await set_mode(repro, "SAFE", lease_id="lease_repro")
    repro_intent = (
        await repro.post(
            "/api/intents",
            json={"customer_id": "cust_g0_repro", "items": [{"sku": "SKU-A", "quantity": 1}]},
        )
    ).json()["intent_id"]
    await pre_register("ns_repro", repro_intent, 7999)
    repro_checkout = await repro.post(f"/api/checkout/{repro_intent}", json=CHECKOUT_BODY)
    assert repro_checkout.json()["status"] == "PAID"
    repro_ledger = await read_ledger("ns_repro")
    assert len(repro_ledger["captures"]) == 1, "the repaired path must capture exactly once"

    after_repro = await read_ledger("ns_original")

    # -- reset proof ---------------------------------------------------------
    duplicate = await evaluator.post(
        "/internal/namespaces", json={"namespace": "ns_original"}, headers=EVAL_HEADERS
    )
    fresh = await evaluator.post(
        "/internal/namespaces", json={"namespace": "ns_reset_fresh"}, headers=EVAL_HEADERS
    )
    after_reset = await read_ledger("ns_original")

    evidence = {
        "gate": "G0",
        "intent_id": intent_id,
        "checkout_status": checkout.json()["status"],
        "captures": [
            {
                "capture_id": row["capture_id"],
                "idempotency_key": row["idempotency_key"],
                "amount_minor": row["amount_minor"],
                "currency": row["currency"],
                "operation_id": row["operation_id"],
            }
            for row in before["captures"]
        ],
        "health_at_incident": {"status_code": health.status_code, "body": health.json()},
        "detection": {
            "invariant_id": detection.invariant_id,
            "detail": detection.detail,
            "capture_ids": list(detection.capture_ids),
        },
        "original_digest_before_repro": before["digest"],
        "original_digest_after_repro": after_repro["digest"],
        "repro_namespace": "ns_repro",
        "repro_capture_count": len(repro_ledger["captures"]),
        "reset_proof": {
            "duplicate_create_status": duplicate.status_code,
            "fresh_namespace_status": fresh.status_code,
            "original_digest_after_reset": after_reset["digest"],
            "original_capture_count_after_reset": len(after_reset["captures"]),
        },
    }

    assert after_repro["digest"] == before["digest"], "original digest changed!"
    assert after_reset["digest"] == before["digest"], "reset touched the original!"
    assert duplicate.status_code == 409
    assert fresh.status_code == 201

    print(json.dumps(evidence, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
