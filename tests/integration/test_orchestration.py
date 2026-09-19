"""Contained incident orchestration through the public POST /run seam."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from apps.contracts.base import ScenarioId
from apps.contracts.control import IncidentSnapshot
from apps.contracts.evaluation import CandidateEvaluation, InvariantId
from apps.contracts.incident import CandidateSpec, CapsuleRowSet, IncidentCapsule
from apps.contracts.payment import (
    CaptureRow,
    CheckoutIntent,
    Order,
    PaymentOperation,
    RouterState,
)
from apps.control_plane.app import create_app
from apps.control_plane.config import ControlSettings
from apps.control_plane.orchestration import OrchestrationEngine, RaceOutcome
from apps.control_plane.orchestration_store import OrchestrationControlStore
from services.capsule import build_capsule
from services.gemini_agent import GeminiOutcome

TOKEN = "orchestration-test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
HASH = "a" * 64
GIT_SHA = "b" * 40


class FakeContainment:
    async def ensure_safe_hold(self) -> RouterState:
        return RouterState(
            mode="SAFE_HOLD",
            generation=7,
            handler_hash=HASH,
            rollout_pct=0,
            bucket_seed="orchestration-test",
            updated_at=datetime.now(UTC),
        )


def _capsule(snapshot: IncidentSnapshot) -> IncidentCapsule:
    now = datetime.now(UTC)
    intent = CheckoutIntent(
        intent_id="intent-1",
        customer_id="customer-1",
        cart_hash="c" * 64,
        amount_minor=7999,
        currency="GBP",
        created_at=now,
    )
    order = Order(
        order_id="order-1",
        intent_id=intent.intent_id,
        status="PAID",
        amount_minor=7999,
        currency="GBP",
        created_at=now,
        updated_at=now,
    )
    operation = PaymentOperation(
        operation_id="operation-1",
        intent_id=intent.intent_id,
        idempotency_key="idem-1",
        amount_minor=7999,
        currency="GBP",
        state="CONFIRMED",
    )
    capture = CaptureRow(
        capture_id="capture-1",
        namespace="incident-original",
        operation_id=operation.operation_id,
        idempotency_key=operation.idempotency_key,
        amount_minor=7999,
        currency="GBP",
        captured_at=now,
    )
    return build_capsule(
        incident_id=snapshot.incident_id,
        run_id=snapshot.run_id,
        namespace="incident-original",
        harmed_intent_id=intent.intent_id,
        harmed_order_id=order.order_id,
        harmed_operation_id=operation.operation_id,
        ledger_captures=[capture],
        ledger_refunds=[],
        store_rows=CapsuleRowSet(intent=intent, order=order, operation=operation),
        recent_logs=[],
        current_release_hash="d" * 64,
        previous_release_hash="e" * 64,
        safe_handler_hash="f" * 64,
        buggy_module_path="apps/live_store/domain/payment_retry.py",
        buggy_module_source="def retry(): pass\n",
        bounded_diff="known incident diff",
        seed_bytes=b"seed",
        scenario_registry_bytes=b"registry",
        oracle_source="oracle",
        image_digest="sha256:test-image",
        fault="DROP_AFTER_CAPTURE_ONCE",
        expected_symptom="two captures for one logical intent",
        started_at_utc=now,
    )


class FakeCapsuleSource:
    async def freeze(self, snapshot: IncidentSnapshot) -> IncidentCapsule:
        return _capsule(snapshot)


class UnavailableGemini:
    async def propose(self, capsule: IncidentCapsule) -> GeminiOutcome:
        assert capsule.capsule_sha256
        return GeminiOutcome(None, failure_reason="GEMINI_UNAVAILABLE:NO_API_KEY")


class PassingRace:
    def __init__(self, *, malformed_pass: bool = False) -> None:
        self.malformed_pass = malformed_pass
        self.calls = 0

    async def run(
        self,
        specs: list[CandidateSpec],
        *,
        expected_scenario_ids: list[ScenarioId],
        expected_invariant_ids: list[InvariantId],
    ) -> RaceOutcome:
        self.calls += 1
        assert [spec.candidate_id for spec in specs] == ["A", "B"]
        now = datetime.now(UTC)
        b_scenarios = expected_scenario_ids[:-1] if self.malformed_pass else expected_scenario_ids
        return RaceOutcome(
            (
                CandidateEvaluation(
                    candidate_id="A",
                    scenario_ids=expected_scenario_ids,
                    invariant_ids=expected_invariant_ids,
                    verdict="FAIL",
                    started_at_utc=now,
                    finished_at_utc=now,
                    evidence_set_sha256="1" * 64,
                ),
                CandidateEvaluation(
                    candidate_id="B",
                    scenario_ids=b_scenarios,
                    invariant_ids=expected_invariant_ids,
                    verdict="PASS",
                    started_at_utc=now,
                    finished_at_utc=now,
                    evidence_set_sha256="2" * 64,
                ),
            )
        )


def _client(tmp_path: Path, *, malformed_pass: bool = False) -> tuple[TestClient, object]:
    store = OrchestrationControlStore()
    race = PassingRace(malformed_pass=malformed_pass)
    engine = OrchestrationEngine(
        store=store,
        capsule_source=FakeCapsuleSource(),
        gemini=UnavailableGemini(),
        candidate_race=race,
        base_commit_sha=GIT_SHA,
        demo_mode="CORE",
    )
    app = create_app(
        ControlSettings(nightwatch_operator_token=TOKEN),
        db_path=str(tmp_path / "orchestration.db"),
        containment=FakeContainment(),
        orchestrator=engine,
    )
    # The app owns its ControlStore. Point the injected engine at the exact same
    # committed store instance to model the production factory wiring.
    engine.store = app.state.control_store
    return TestClient(app), app


def test_run_freezes_capsule_races_and_selects_deterministically(tmp_path: Path) -> None:
    client, app = _client(tmp_path)
    response = client.post("/api/incidents/NW-ORCH-1/run", headers=AUTH)
    assert response.status_code == 200
    snapshot = response.json()
    assert snapshot["state"] == "RUNNING"
    assert snapshot["containment_verified"] is True
    assert any("ERROR_BROWSER_STACK:S01,S02" in item for item in snapshot["degraded_reasons"])
    assert any("GEMINI_UNAVAILABLE:NO_API_KEY" in item for item in snapshot["degraded_reasons"])

    events = app.state.control_store.list_events_after("NW-ORCH-1")
    assert [event.kind for event in events] == [
        "RUN_REQUESTED",
        "SAFE_HOLD_SET",
        "CAPSULE_FROZEN",
        "REPRODUCING",
        "VALIDATING",
        "SELECTING",
    ]
    assert events[-1].payload["winner"] == "B"
    assert "model confidence was not considered" in events[-1].payload["reason"]
    assert app.state.control_store.get_capsule("NW-ORCH-1").run_id == snapshot["run_id"]
    evaluations = app.state.control_store.get_candidate_evaluations(snapshot["run_id"])
    assert [(item.candidate_id, item.verdict) for item in evaluations] == [
        ("A", "FAIL"),
        ("B", "PASS"),
        ("C", "SKIPPED_INVALID"),
    ]


def test_malformed_runner_pass_is_downgraded_to_error(tmp_path: Path) -> None:
    client, app = _client(tmp_path, malformed_pass=True)
    response = client.post("/api/incidents/NW-ORCH-2/run", headers=AUTH)
    assert response.status_code == 200
    snapshot = response.json()
    assert snapshot["state"] == "ESCALATED"
    assert any("RUNNER_FAILURES:B: malformed PASS" in item for item in snapshot["degraded_reasons"])
    evaluations = app.state.control_store.get_candidate_evaluations(snapshot["run_id"])
    assert next(item for item in evaluations if item.candidate_id == "B").verdict == "ERROR"
    assert app.state.control_store.list_events_after("NW-ORCH-2")[-1].kind == "ESCALATED"


def test_default_orchestrator_labels_missing_trusted_capsule_source(tmp_path: Path) -> None:
    app = create_app(
        ControlSettings(
            nightwatch_operator_token=TOKEN,
            current_commit_sha=GIT_SHA,
        ),
        db_path=str(tmp_path / "default.db"),
        containment=FakeContainment(),
    )
    response = TestClient(app).post("/api/incidents/NW-ORCH-3/run", headers=AUTH)
    assert response.status_code == 200
    snapshot = response.json()
    assert snapshot["state"] == "ESCALATED"
    assert snapshot["degraded_reasons"] == [
        "CAPSULE_UNAVAILABLE: no trusted incident evidence source is configured"
    ]
    assert [
        event.kind for event in app.state.control_store.list_events_after("NW-ORCH-3")
    ] == ["RUN_REQUESTED", "SAFE_HOLD_SET", "ESCALATED"]
