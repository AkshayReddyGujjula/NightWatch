"""Committed public control API: idempotency, containment, replay and reads."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from apps.contracts.base import sha256_hex
from apps.contracts.browser import BrowserFrame
from apps.contracts.control import EvaluationResults, IncidentSnapshot, WorldHealth
from apps.contracts.payment import RouterState
from apps.control_plane.app import create_app
from apps.control_plane.config import ControlSettings

TOKEN = "operator-test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
HASH = "a" * 64


class FakeContainment:
    def __init__(self) -> None:
        self.calls = 0

    async def ensure_safe_hold(self) -> RouterState:
        self.calls += 1
        return RouterState(
            mode="SAFE_HOLD",
            generation=self.calls + 10,
            handler_hash=HASH,
            rollout_pct=0,
            bucket_seed="test-bucket-seed",
            updated_at=datetime.now(UTC),
        )


class FailingContainment:
    async def ensure_safe_hold(self) -> RouterState:
        raise RuntimeError("router unavailable")


class ContainmentOnlyOrchestrator:
    """Keep foundation route tests focused on containment and replay."""

    async def orchestrate(self, snapshot: IncidentSnapshot) -> IncidentSnapshot:
        return snapshot


def make_client(tmp_path: Path, containment: object) -> tuple[TestClient, object]:
    app = create_app(
        ControlSettings(nightwatch_operator_token=TOKEN),
        db_path=str(tmp_path / "control.db"),
        containment=containment,  # type: ignore[arg-type]
        orchestrator=ContainmentOnlyOrchestrator(),
    )
    return TestClient(app), app


def test_run_is_idempotent_and_safe_hold_is_read_back(tmp_path: Path) -> None:
    containment = FakeContainment()
    client, app = make_client(tmp_path, containment)

    first = client.post("/api/incidents/NW-001/run", headers=AUTH)
    assert first.status_code == 200
    snapshot = first.json()
    assert snapshot["state"] == "SAFE_HOLD"
    assert snapshot["containment_verified"] is True
    assert snapshot["event_count"] == 2

    second = client.post("/api/incidents/NW-001/run", headers=AUTH)
    assert second.status_code == 200
    assert second.json() == snapshot
    assert containment.calls == 1

    events = app.state.control_store.list_events_after("NW-001")
    assert [event.kind for event in events] == ["RUN_REQUESTED", "SAFE_HOLD_SET"]
    assert events[0].prior_event_hash is None
    assert events[1].prior_event_hash == events[0].event_hash
    assert events[1].payload["readback"] == "verified"


def test_safe_stop_is_audited_then_recontains(tmp_path: Path) -> None:
    containment = FakeContainment()
    client, app = make_client(tmp_path, containment)
    client.post("/api/incidents/NW-002/run", headers=AUTH)

    response = client.post(
        "/api/incidents/NW-002/safe-stop",
        json={"reason": "judge demonstration"},
        headers=AUTH,
    )
    assert response.status_code == 200
    assert response.json()["state"] == "SAFE_HOLD"
    events = app.state.control_store.list_events_after("NW-002")
    assert [event.kind for event in events[-2:]] == [
        "SAFE_STOP_REQUESTED",
        "SAFE_HOLD_SET",
    ]
    assert events[-2].payload["reason"] == "judge demonstration"
    assert containment.calls == 2


def test_failed_containment_is_explicit_and_no_run_is_started(tmp_path: Path) -> None:
    client, app = make_client(tmp_path, FailingContainment())
    response = client.post("/api/incidents/NW-003/run", headers=AUTH)
    assert response.status_code == 200
    snapshot = response.json()
    assert snapshot["state"] == "ESCALATED"
    assert snapshot["containment_verified"] is False
    assert snapshot["degraded_reasons"][0].startswith("CONTAINMENT_FAILED:")
    assert app.state.control_store.list_events_after("NW-003")[-1].kind == "ESCALATED"


def test_operator_auth_and_committed_read_models(tmp_path: Path) -> None:
    client, app = make_client(tmp_path, FakeContainment())
    assert client.get("/api/incidents/missing").status_code == 401
    assert client.get("/api/incidents/missing", headers=AUTH).status_code == 404

    snapshot = client.post("/api/incidents/NW-004/run", headers=AUTH).json()
    now = datetime.now(UTC)
    app.state.control_store.save_evaluations(
        EvaluationResults(run_id=snapshot["run_id"], committed_at_utc=now)
    )
    app.state.control_store.save_world_health(
        WorldHealth(world_id="world-1", status="READY", checked_at_utc=now)
    )

    evaluations = client.get(
        f"/api/runs/{snapshot['run_id']}/evaluations", headers=AUTH
    )
    assert evaluations.status_code == 200
    assert evaluations.json()["scenarios"] == []
    assert client.get("/api/worlds/world-1/health", headers=AUTH).json()["status"] == "READY"
    assert client.get("/api/incidents/NW-004/receipt", headers=AUTH).status_code == 404


def test_last_event_cursor_replays_only_newer_committed_events(tmp_path: Path) -> None:
    client, app = make_client(tmp_path, FakeContainment())
    client.post("/api/incidents/NW-005/run", headers=AUTH)
    events = app.state.control_store.list_events_after("NW-005")
    replay = app.state.control_store.list_events_after("NW-005", events[0].event_id)
    assert [event.event_id for event in replay] == [events[1].event_id]

    response = client.get(
        "/api/incidents/NW-005/events",
        headers={**AUTH, "Last-Event-ID": "evt_not_in_this_stream"},
    )
    assert response.status_code == 409


def test_openapi_contains_complete_control_route_inventory(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path, FakeContainment())
    paths = set(client.get("/openapi.json").json()["paths"])
    assert {
        "/api/incidents/{incident_id}/run",
        "/api/incidents/{incident_id}/safe-stop",
        "/api/incidents/{incident_id}",
        "/api/incidents/{incident_id}/events",
        "/api/incidents/{incident_id}/receipt",
        "/api/runs/{run_id}/evaluations",
        "/api/runs/{run_id}/frames/{candidate_id}/latest",
        "/api/worlds/{world_id}/health",
    } <= paths


def test_latest_frame_is_authenticated_run_bound_and_conditional(tmp_path: Path) -> None:
    client, app = make_client(tmp_path, FakeContainment())
    snapshot = client.post("/api/incidents/NW-FRAME/run", headers=AUTH).json()
    run_id = snapshot["run_id"]
    image = b"\xff\xd8\xff\xe0nightwatch-live-frame"
    frame = BrowserFrame(
        run_id=run_id,
        candidate_id="C1",
        scenario_id="S02",
        frame_seq=7,
        sandbox_id="sb-frame-1",
        cua_session_id="cua-frame-1",
        snapshot_id="snapshot-frame-1",
        phase="SAMPLE",
        captured_monotonic_ns=7_000_000_000,
        captured_at_utc=datetime.now(UTC),
        image_sha256=sha256_hex(image),
        image_size_bytes=len(image),
        image_mime="image/jpeg",
    )
    app.state.frames.accept_frame(frame, image=image)
    path = f"/api/runs/{run_id}/frames/C1/latest"

    assert client.get(path).status_code == 401
    assert client.get(f"/api/runs/{run_id}/frames/C2/latest", headers=AUTH).status_code == 404

    response = client.get(path, headers=AUTH)
    assert response.status_code == 200
    assert response.content == image
    assert response.headers["etag"] == frame.image_sha256
    assert response.headers["x-frame-seq"] == "7"
    assert response.headers["cache-control"] == "no-store"

    unchanged = client.get(f"{path}?after=7", headers=AUTH)
    assert unchanged.status_code == 304
    by_etag = client.get(path, headers={**AUTH, "If-None-Match": frame.image_sha256})
    assert by_etag.status_code == 304
