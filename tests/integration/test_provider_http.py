"""HTTP contract tests for the trusted provider (plan §9.3)."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from apps.trusted_provider.app import ProviderSettings, create_app

SECRET = "http-test-signing-secret"
EVALUATOR = "http-test-evaluator-token"
NAMESPACE = "ns_http"
OPERATION = "op_1"

EVAL_HEADERS = {"Authorization": f"Bearer {EVALUATOR}"}


def make_client() -> TestClient:
    app = create_app(
        ProviderSettings(provider_signing_secret=SECRET, evaluator_token=EVALUATOR),
        db_path=":memory:",
    )
    return TestClient(app)


def setup_namespace(client: TestClient) -> str:
    assert (
        client.post(
            "/internal/namespaces", json={"namespace": NAMESPACE}, headers=EVAL_HEADERS
        ).status_code
        == 201
    )
    registered = client.post(
        "/internal/operations",
        json={
            "namespace": NAMESPACE,
            "operation_id": OPERATION,
            "intent_id": "pi_http_001",
            "amount_minor": 7999,
            "currency": "GBP",
            "allowed_actions": ["capture", "refund", "inquiry"],
        },
        headers=EVAL_HEADERS,
    )
    assert registered.status_code == 201
    token_response = client.post(
        "/internal/scoped-tokens",
        json={
            "incident_id": "NW-001",
            "candidate_id": "B",
            "scenario_id": "S02",
            "namespace": NAMESPACE,
            "allowed_operation_ids": [OPERATION],
            "expires_in_seconds": 600,
        },
        headers=EVAL_HEADERS,
    )
    assert token_response.status_code == 200
    return token_response.json()["token"]


def capture_body(**overrides: Any) -> dict[str, Any]:
    payload = {
        "operation_id": OPERATION,
        "idempotency_key": "key_1",
        "amount_minor": 7999,
        "currency": "GBP",
    }
    payload.update(overrides)
    return payload


def test_evaluator_setup_and_scoped_capture() -> None:
    client = make_client()
    token = setup_namespace(client)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post("/capture", json=capture_body(), headers=headers)
    assert response.status_code == 200
    assert response.json()["replayed"] is False

    replay = client.post("/capture", json=capture_body(), headers=headers)
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True

    captures = client.get(f"/operations/{OPERATION}/captures", headers=headers)
    assert captures.status_code == 200
    assert len(captures.json()) == 1


def test_capture_requires_scoped_token_not_evaluator_token() -> None:
    client = make_client()
    setup_namespace(client)
    assert client.post("/capture", json=capture_body(), headers=EVAL_HEADERS).status_code == 401
    assert client.post("/capture", json=capture_body()).status_code == 401


def test_ledger_reads_are_evaluator_only() -> None:
    client = make_client()
    token = setup_namespace(client)
    assert (
        client.get(
            f"/internal/ledger/{NAMESPACE}", headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 401
    )
    ledger = client.get(f"/internal/ledger/{NAMESPACE}", headers=EVAL_HEADERS)
    assert ledger.status_code == 200
    assert ledger.json()["captures"] == []


def test_drop_after_capture_once_commits_then_loses_the_response() -> None:
    client = make_client()
    token = setup_namespace(client)
    headers = {"Authorization": f"Bearer {token}"}

    armed = client.post(
        "/internal/faults",
        json={"namespace": NAMESPACE, "fault": "DROP_AFTER_CAPTURE_ONCE"},
        headers=EVAL_HEADERS,
    )
    assert armed.status_code == 204

    dropped = client.post("/capture", json=capture_body(), headers=headers)
    assert dropped.status_code == 504

    captures = client.get(f"/operations/{OPERATION}/captures", headers=headers).json()
    assert len(captures) == 1

    # The one-shot fault is spent: the next attempt (new key) succeeds normally.
    second = client.post(
        "/capture", json=capture_body(idempotency_key="key_2"), headers=headers
    )
    assert second.status_code == 200
    assert len(client.get(f"/operations/{OPERATION}/captures", headers=headers).json()) == 2


def test_timeout_before_capture_once_appends_nothing() -> None:
    client = make_client()
    token = setup_namespace(client)
    headers = {"Authorization": f"Bearer {token}"}

    client.post(
        "/internal/faults",
        json={"namespace": NAMESPACE, "fault": "TIMEOUT_BEFORE_CAPTURE_ONCE"},
        headers=EVAL_HEADERS,
    )
    dropped = client.post("/capture", json=capture_body(), headers=headers)
    assert dropped.status_code == 504
    assert client.get(f"/operations/{OPERATION}/captures", headers=headers).json() == []


def test_scoped_token_cannot_touch_other_operations() -> None:
    client = make_client()
    token = setup_namespace(client)
    headers = {"Authorization": f"Bearer {token}"}
    response = client.post("/capture", json=capture_body(operation_id="op_other"), headers=headers)
    assert response.status_code == 403
