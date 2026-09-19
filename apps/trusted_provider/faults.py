"""One-shot namespace-scoped fault schedules (plan §5.3).

``DROP_AFTER_CAPTURE_ONCE`` appends the capture and then drops the response;
``TIMEOUT_BEFORE_CAPTURE_ONCE`` simulates a timeout without any capture. Both
are consumed exactly once per namespace.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime

from apps.contracts.payment import FaultKind

__all__ = ["FaultSchedules"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS fault_schedules (
  namespace TEXT NOT NULL,
  fault TEXT NOT NULL,
  generation INTEGER NOT NULL,
  consumed_at TEXT,
  PRIMARY KEY (namespace, fault)
);
"""


class FaultSchedules:
    """Shared-connection fault table; one-shot per (namespace, fault)."""

    def __init__(self, connection: sqlite3.Connection, lock: threading.Lock) -> None:
        self._conn = connection
        self._lock = lock
        with self._lock, self._conn:
            self._conn.executescript(SCHEMA)

    def arm(self, namespace: str, fault: FaultKind, *, generation: int = 1) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO fault_schedules (namespace, fault, generation, consumed_at)
                VALUES (?, ?, ?, NULL)
                ON CONFLICT(namespace, fault) DO UPDATE SET
                  generation = fault_schedules.generation + 1,
                  consumed_at = NULL
                """,
                (namespace, fault, generation),
            )

    def consume(self, namespace: str, fault: FaultKind) -> bool:
        """Return True if an unconsumed fault fires now; it is consumed atomically."""
        now = datetime.now(UTC).isoformat()
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                UPDATE fault_schedules
                SET consumed_at = ?
                WHERE namespace = ? AND fault = ? AND consumed_at IS NULL
                """,
                (now, namespace, fault),
            )
        return cursor.rowcount == 1
