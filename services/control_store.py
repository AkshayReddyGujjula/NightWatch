"""SQLite-backed, append-only control-plane evidence store."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apps.contracts.base import canonical_sha256
from apps.contracts.control import EvaluationResults, IncidentSnapshot, WorldHealth
from apps.contracts.incident import EventKind, IncidentEvent
from apps.contracts.lease import RepairReceipt


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _json(model: Any) -> str:
    return model.model_dump_json()


class ControlStore:
    """Committed incident/event read models with hash-chained events.

    The connection is guarded because FastAPI may execute callers on different
    threads. Every event insert and its incident snapshot update share one
    ``BEGIN IMMEDIATE`` transaction, so SSE polling cannot observe half a state
    transition.
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(db_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS incidents (
                    incident_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL UNIQUE,
                    state TEXT NOT NULL,
                    state_version INTEGER NOT NULL,
                    containment_verified INTEGER NOT NULL,
                    event_count INTEGER NOT NULL,
                    receipt_json TEXT,
                    degraded_reasons_json TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS incident_events (
                    ordinal INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    incident_id TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    FOREIGN KEY (incident_id) REFERENCES incidents(incident_id)
                );
                CREATE INDEX IF NOT EXISTS incident_events_incident_ordinal
                    ON incident_events(incident_id, ordinal);
                CREATE TABLE IF NOT EXISTS evaluations (
                    run_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS worlds (
                    world_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );
                """
            )
            self.connection.commit()

    def begin_run(self, incident_id: str) -> tuple[IncidentSnapshot, bool]:
        """Create one run for an incident, or return the existing run."""
        with self.lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                row = self.connection.execute(
                    "SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)
                ).fetchone()
                if row is not None:
                    self.connection.commit()
                    return self._snapshot_from_row(row), False

                now = _utcnow()
                run_id = f"run_{uuid.uuid4().hex}"
                self.connection.execute(
                    """
                    INSERT INTO incidents (
                        incident_id, run_id, state, state_version,
                        containment_verified, event_count, receipt_json,
                        degraded_reasons_json, created_at_utc, updated_at_utc
                    ) VALUES (?, ?, 'RUN_REQUESTED', 0, 0, 0, NULL, '[]', ?, ?)
                    """,
                    (incident_id, run_id, now.isoformat(), now.isoformat()),
                )
                self._append_event_locked(
                    incident_id,
                    "RUN_REQUESTED",
                    {"run_id": run_id},
                    state="RUN_REQUESTED",
                )
                self.connection.commit()
                return self._get_snapshot_locked(incident_id), True
            except Exception:
                self.connection.rollback()
                raise

    def append_event(
        self,
        incident_id: str,
        kind: EventKind,
        payload: dict[str, str],
        *,
        state: str | None = None,
        containment_verified: bool | None = None,
        degraded_reason: str | None = None,
    ) -> IncidentEvent:
        with self.lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                event = self._append_event_locked(
                    incident_id,
                    kind,
                    payload,
                    state=state,
                    containment_verified=containment_verified,
                    degraded_reason=degraded_reason,
                )
                self.connection.commit()
                return event
            except Exception:
                self.connection.rollback()
                raise

    def _append_event_locked(
        self,
        incident_id: str,
        kind: EventKind,
        payload: dict[str, str],
        *,
        state: str | None = None,
        containment_verified: bool | None = None,
        degraded_reason: str | None = None,
    ) -> IncidentEvent:
        row = self.connection.execute(
            "SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)
        ).fetchone()
        if row is None:
            raise KeyError(incident_id)
        prior = self.connection.execute(
            """
            SELECT event_hash FROM incident_events
            WHERE incident_id = ? ORDER BY ordinal DESC LIMIT 1
            """,
            (incident_id,),
        ).fetchone()
        next_version = int(row["state_version"]) + 1
        material: dict[str, Any] = {
            "event_id": f"evt_{uuid.uuid4().hex}",
            "incident_id": incident_id,
            "run_id": row["run_id"],
            "kind": kind,
            "occurred_at_utc": _utcnow(),
            "monotonic_ns": time.monotonic_ns(),
            "state_version": next_version,
            "payload": payload,
            "prior_event_hash": prior["event_hash"] if prior is not None else None,
        }
        hash_material = {
            **material,
            "occurred_at_utc": material["occurred_at_utc"].isoformat(),
        }
        event = IncidentEvent(**material, event_hash=canonical_sha256(hash_material))
        reasons = json.loads(row["degraded_reasons_json"])
        if degraded_reason and degraded_reason not in reasons:
            reasons.append(degraded_reason)
        self.connection.execute(
            """
            INSERT INTO incident_events (event_id, incident_id, event_json, event_hash)
            VALUES (?, ?, ?, ?)
            """,
            (event.event_id, incident_id, _json(event), event.event_hash),
        )
        self.connection.execute(
            """
            UPDATE incidents
            SET state = ?, state_version = ?, containment_verified = ?,
                event_count = event_count + 1, degraded_reasons_json = ?,
                updated_at_utc = ?
            WHERE incident_id = ?
            """,
            (
                state or row["state"],
                next_version,
                int(
                    bool(row["containment_verified"])
                    if containment_verified is None
                    else containment_verified
                ),
                json.dumps(reasons),
                event.occurred_at_utc.isoformat(),
                incident_id,
            ),
        )
        return event

    def get_snapshot(self, incident_id: str) -> IncidentSnapshot:
        with self.lock:
            return self._get_snapshot_locked(incident_id)

    def _get_snapshot_locked(self, incident_id: str) -> IncidentSnapshot:
        row = self.connection.execute(
            "SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)
        ).fetchone()
        if row is None:
            raise KeyError(incident_id)
        return self._snapshot_from_row(row)

    @staticmethod
    def _snapshot_from_row(row: sqlite3.Row) -> IncidentSnapshot:
        return IncidentSnapshot(
            incident_id=row["incident_id"],
            run_id=row["run_id"],
            state=row["state"],
            state_version=row["state_version"],
            containment_verified=bool(row["containment_verified"]),
            event_count=row["event_count"],
            receipt_available=row["receipt_json"] is not None,
            degraded_reasons=json.loads(row["degraded_reasons_json"]),
            created_at_utc=datetime.fromisoformat(row["created_at_utc"]),
            updated_at_utc=datetime.fromisoformat(row["updated_at_utc"]),
        )

    def list_events_after(
        self, incident_id: str, last_event_id: str | None = None
    ) -> list[IncidentEvent]:
        with self.lock:
            self._get_snapshot_locked(incident_id)
            after_ordinal = 0
            if last_event_id:
                cursor = self.connection.execute(
                    """
                    SELECT ordinal FROM incident_events
                    WHERE incident_id = ? AND event_id = ?
                    """,
                    (incident_id, last_event_id),
                ).fetchone()
                if cursor is None:
                    raise ValueError("Last-Event-ID is not in this incident stream")
                after_ordinal = int(cursor["ordinal"])
            rows = self.connection.execute(
                """
                SELECT event_json FROM incident_events
                WHERE incident_id = ? AND ordinal > ? ORDER BY ordinal
                """,
                (incident_id, after_ordinal),
            ).fetchall()
        return [IncidentEvent.model_validate_json(row["event_json"], strict=True) for row in rows]

    def save_receipt(self, receipt: RepairReceipt) -> None:
        with self.lock:
            cursor = self.connection.execute(
                """
                UPDATE incidents SET receipt_json = ?, updated_at_utc = ?
                WHERE incident_id = ? AND run_id = ?
                """,
                (_json(receipt), _utcnow().isoformat(), receipt.incident_id, receipt.run_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(receipt.incident_id)
            self.connection.commit()

    def get_receipt(self, incident_id: str) -> RepairReceipt:
        with self.lock:
            row = self.connection.execute(
                "SELECT receipt_json FROM incidents WHERE incident_id = ?", (incident_id,)
            ).fetchone()
        if row is None or row["receipt_json"] is None:
            raise KeyError(incident_id)
        return RepairReceipt.model_validate_json(row["receipt_json"], strict=True)

    def save_evaluations(self, results: EvaluationResults) -> None:
        with self.lock:
            self.connection.execute(
                """
                INSERT INTO evaluations (run_id, payload_json) VALUES (?, ?)
                ON CONFLICT(run_id) DO UPDATE SET payload_json = excluded.payload_json
                """,
                (results.run_id, _json(results)),
            )
            self.connection.commit()

    def get_evaluations(self, run_id: str) -> EvaluationResults:
        with self.lock:
            row = self.connection.execute(
                "SELECT payload_json FROM evaluations WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return EvaluationResults.model_validate_json(row["payload_json"], strict=True)

    def save_world_health(self, health: WorldHealth) -> None:
        with self.lock:
            self.connection.execute(
                """
                INSERT INTO worlds (world_id, payload_json) VALUES (?, ?)
                ON CONFLICT(world_id) DO UPDATE SET payload_json = excluded.payload_json
                """,
                (health.world_id, _json(health)),
            )
            self.connection.commit()

    def get_world_health(self, world_id: str) -> WorldHealth:
        with self.lock:
            row = self.connection.execute(
                "SELECT payload_json FROM worlds WHERE world_id = ?", (world_id,)
            ).fetchone()
        if row is None:
            raise KeyError(world_id)
        return WorldHealth.model_validate_json(row["payload_json"], strict=True)
