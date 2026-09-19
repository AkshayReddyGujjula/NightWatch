"""Wired provider+store stack used by Track A tests.

One provider app and one live-store app joined over in-process ASGI transports —
the same code paths a Modal deployment uses, with no network.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from fastapi import FastAPI

from apps.live_store.app import StoreSettings as LiveStoreSettings
from apps.live_store.app import create_app as create_live_store_app
from apps.live_store.provider import HttpPaymentProvider
from apps.trusted_provider.app import ProviderSettings
from apps.trusted_provider.app import create_app as create_provider_app

EVALUATOR_TOKEN = "test-evaluator-token"
LIVE_INTERNAL_TOKEN = "test-live-internal-token"
SIGNING_SECRET = "test-signing-secret"

EVAL_HEADERS = {"Authorization": f"Bearer {EVALUATOR_TOKEN}"}
LIVE_HEADERS = {"Authorization": f"Bearer {LIVE_INTERNAL_TOKEN}"}

CHECKOUT_BODY: dict[str, str] = {
    "email": "fixture@example.com",
    "address": "1 Test Street, London",
}


@dataclass
class Stack:
    namespace: str
    provider_token: str
    provider_app: FastAPI
    live_app: FastAPI
    evaluator_client: httpx.AsyncClient
    provider_client: httpx.AsyncClient
    store_client: httpx.AsyncClient

    async def aclose(self) -> None:
        await self.store_client.aclose()
        await self.provider_client.aclose()
        await self.evaluator_client.aclose()


async def build_stack(*, namespace: str) -> Stack:
    provider_app = create_provider_app(
        ProviderSettings(provider_signing_secret=SIGNING_SECRET, evaluator_token=EVALUATOR_TOKEN),
        db_path=":memory:",
    )
    evaluator_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=provider_app), base_url="http://provider"
    )
    created = await evaluator_client.post(
        "/internal/namespaces", json={"namespace": namespace}, headers=EVAL_HEADERS
    )
    if created.status_code != 201:
        raise RuntimeError(f"namespace setup failed: {created.status_code} {created.text}")
    token_response = await evaluator_client.post(
        "/internal/scoped-tokens",
        json={
            "incident_id": "NW-TEST",
            "candidate_id": "B",
            "scenario_id": "S02",
            "namespace": namespace,
            "allowed_operation_ids": ["*"],
            "expires_in_seconds": 3600,
        },
        headers=EVAL_HEADERS,
    )
    provider_token = token_response.json()["token"]

    provider_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=provider_app), base_url="http://provider"
    )
    live_app = create_live_store_app(
        LiveStoreSettings(
            live_internal_token=LIVE_INTERNAL_TOKEN, evaluator_token=EVALUATOR_TOKEN
        ),
        db_path=":memory:",
        provider=HttpPaymentProvider("http://provider", provider_token, client=provider_client),
    )
    store_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=live_app), base_url="http://store"
    )
    return Stack(
        namespace=namespace,
        provider_token=provider_token,
        provider_app=provider_app,
        live_app=live_app,
        evaluator_client=evaluator_client,
        provider_client=provider_client,
        store_client=store_client,
    )


async def arm_fault(stack: Stack, fault: str) -> None:
    response = await stack.evaluator_client.post(
        "/internal/faults",
        json={"namespace": stack.namespace, "fault": fault},
        headers=EVAL_HEADERS,
    )
    assert response.status_code == 204, response.text


async def set_router_mode(stack: Stack, mode: str, *, lease_id: str | None = None) -> None:
    current = await stack.store_client.get("/internal/router", headers=LIVE_HEADERS)
    assert current.status_code == 200, current.text
    body: dict[str, object] = {
        "mode": mode,
        "expected_generation": current.json()["generation"],
    }
    if lease_id is not None:
        body["lease_id"] = lease_id
    response = await stack.store_client.put(
        "/internal/router", json=body, headers=LIVE_HEADERS
    )
    assert response.status_code == 200, response.text


async def read_ledger(stack: Stack) -> dict:
    response = await stack.evaluator_client.get(
        f"/internal/ledger/{stack.namespace}", headers=EVAL_HEADERS
    )
    assert response.status_code == 200, response.text
    return response.json()


async def read_facts(stack: Stack, intent_id: str) -> dict:
    response = await stack.store_client.get(
        f"/internal/state/{intent_id}", headers=EVAL_HEADERS
    )
    assert response.status_code == 200, response.text
    return response.json()


async def start_checkout(
    stack: Stack, *, quantity: int = 1, voucher_code: str | None = None
) -> tuple[str, dict]:
    created = await stack.store_client.post(
        "/api/intents",
        json={"customer_id": "cust_test", "items": [{"sku": "SKU-A", "quantity": quantity}]},
    )
    assert created.status_code == 201, created.text
    intent_id = created.json()["intent_id"]
    body = dict(CHECKOUT_BODY)
    if voucher_code is not None:
        body["voucher_code"] = voucher_code
    response = await stack.store_client.post(f"/api/checkout/{intent_id}", json=body)
    assert response.status_code == 200, response.text
    return intent_id, response.json()
