"""Append-only provider ledger (plan §5.3).

The provider honours idempotency per key: same key and same parameters returns
the cached capture; same key with changed parameters is rejected. Unknown or
cross-namespace operations are rejected. Refunds never exceed the captured
total. Everything is namespace-scoped and append-only.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from typing import Literal

from apps.contracts.base import sha256_hex
from apps.contracts.payment import (
    CaptureRequest,
    CaptureResponse,
    CaptureRow,
    LedgerView,
    OperationRegisterRequest,
    RefundRequest,
    RefundResponse,
    RefundRow,
    RegistrationRow,
)

__all__ = ["LedgerStore", "ProviderError"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS namespaces (
  namespace TEXT PRIMARY KEY,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS registered_operations (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  namespace TEXT NOT NULL,
  operation_id TEXT NOT NULL,
  intent_id TEXT NOT NULL,
  amount_minor INTEGER NOT NULL,
  currency TEXT NOT NULL,
  allowed_actions TEXT NOT NULL,
  registered_at TEXT NOT NULL,
  UNIQUE (namespace, operation_id)
);
CREATE TABLE IF NOT EXISTS captures (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  capture_id TEXT NOT NULL,
  namespace TEXT NOT NULL,
  operation_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  amount_minor INTEGER NOT NULL,
  currency TEXT NOT NULL,
  captured_at TEXT NOT NULL,
  UNIQUE (namespace, idempotency_key)
);
CREATE TABLE IF NOT EXISTS refunds (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  refund_id TEXT NOT NULL,
  namespace TEXT NOT NULL,
  operation_id TEXT NOT NULL,
  refund_intent_id TEXT NOT NULL,
  amount_minor INTEGER NOT NULL,
  currency TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (namespace, operation_id, refund_intent_id)
);
-- One logical intent has at most one provider operation (plan §5.4 INV-01).
CREATE UNIQUE INDEX IF NOT EXISTS idx_registered_operations_intent
  ON registered_operations (namespace, intent_id);
"""


class ProviderError(Exception):
    """Typed provider rejection carrying the HTTP status to surface."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _dt(value: str) -> datetime:
    """Strict models require real datetimes; SQLite stores ISO strings."""
    return datetime.fromisoformat(value)


class LedgerStore:
    """Single-writer SQLite ledger; the oracle's source of truth."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock, self._conn:
            self._conn.executescript(SCHEMA)

    @property
    def connection(self) -> sqlite3.Connection:
        """Raw connection shared with the fault-schedule table (same DB file)."""
        return self._conn

    @property
    def lock(self) -> threading.Lock:
        """Single-writer lock guarding the shared connection."""
        return self._lock

    # -- namespaces ----------------------------------------------------------

    def create_namespace(self, namespace: str) -> None:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "INSERT OR IGNORE INTO namespaces (namespace, created_at) VALUES (?, ?)",
                (namespace, _now()),
            )
        if cursor.rowcount == 0:
            raise ProviderError(409, f"namespace {namespace!r} already exists")

    def namespace_digest(self, namespace: str) -> str:
        return self.ledger_view(namespace).digest

    def require_namespace(self, namespace: str) -> None:
        """Public namespace-existence check for routes that write other tables."""
        with self._lock:
            self._require_namespace(namespace)

    def capture_exists(self, namespace: str, idempotency_key: str) -> bool:
        """True when this key already has a capture (a replay, not a fresh append)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM captures WHERE namespace = ? AND idempotency_key = ?",
                (namespace, idempotency_key),
            ).fetchone()
        return row is not None

    # -- registration --------------------------------------------------------

    def register_operation(self, request: OperationRegisterRequest) -> RegistrationRow:
        with self._lock, self._conn:
            self._require_namespace(request.namespace)
            try:
                self._conn.execute(
                    """
                    INSERT INTO registered_operations
                      (namespace, operation_id, intent_id, amount_minor, currency,
                       allowed_actions, registered_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        request.namespace,
                        request.operation_id,
                        request.intent_id,
                        request.amount_minor,
                        request.currency,
                        json.dumps(sorted(request.allowed_actions)),
                        _now(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ProviderError(
                    409,
                    f"operation {request.operation_id!r} is already registered, "
                    "or the intent already has an operation",
                ) from exc
        return self._registration(request.namespace, request.operation_id)

    # -- capture -------------------------------------------------------------

    def capture(
        self,
        namespace: str,
        request: CaptureRequest,
        *,
        allowed_operation_ids: list[str],
    ) -> CaptureResponse:
        operation_allowed = self._operation_allowed(allowed_operation_ids, request.operation_id)
        explicit_operation = request.operation_id in allowed_operation_ids
        with self._lock, self._conn:
            self._require_namespace(namespace)
            registration = self._registration_or_none(namespace, request.operation_id)
            if registration is None:
                # The provider rejects unknown operations. Auto-registration is
                # reserved for tokens that name this exact operation id; a
                # wildcard token may only touch pre-registered operations.
                if not explicit_operation:
                    raise ProviderError(404, f"unknown operation {request.operation_id!r}")
                if request.intent_id is None:
                    raise ProviderError(
                        422, "intent_id is required to register a new operation on first capture"
                    )
                registration = self._auto_register(namespace, request)
            elif not operation_allowed:
                raise ProviderError(403, "operation is not permitted by this token")
            if "capture" not in registration.allowed_actions:
                raise ProviderError(403, "captures are not allowed for this operation")
            if request.intent_id is not None and request.intent_id != registration.intent_id:
                raise ProviderError(409, "intent_id does not match the registered operation")
            if (
                registration.amount_minor != request.amount_minor
                or registration.currency != request.currency
            ):
                raise ProviderError(409, "operation amount/currency mismatch")

            existing = self._capture_for_key(namespace, request.idempotency_key)
            if existing is not None:
                if (
                    existing.operation_id == request.operation_id
                    and existing.amount_minor == request.amount_minor
                    and existing.currency == request.currency
                ):
                    return CaptureResponse(
                        capture_id=existing.capture_id,
                        operation_id=existing.operation_id,
                        amount_minor=existing.amount_minor,
                        currency=existing.currency,
                        replayed=True,
                    )
                raise ProviderError(409, "idempotency key reused with changed parameters")

            capture_id = _new_id("cap")
            self._conn.execute(
                """
                INSERT INTO captures
                  (capture_id, namespace, operation_id, idempotency_key,
                   amount_minor, currency, captured_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    capture_id,
                    namespace,
                    request.operation_id,
                    request.idempotency_key,
                    request.amount_minor,
                    request.currency,
                    _now(),
                ),
            )
        return CaptureResponse(
            capture_id=capture_id,
            operation_id=request.operation_id,
            amount_minor=request.amount_minor,
            currency=request.currency,
            replayed=False,
        )

    def captures_for(self, namespace: str, operation_id: str) -> list[CaptureRow]:
        with self._lock:
            self._require_namespace(namespace)
            rows = self._conn.execute(
                """
                SELECT capture_id, namespace, operation_id, idempotency_key,
                       amount_minor, currency, captured_at
                FROM captures WHERE namespace = ? AND operation_id = ?
                ORDER BY seq
                """,
                (namespace, operation_id),
            ).fetchall()
        return [
            CaptureRow(
                capture_id=row["capture_id"],
                namespace=row["namespace"],
                operation_id=row["operation_id"],
                idempotency_key=row["idempotency_key"],
                amount_minor=row["amount_minor"],
                currency=row["currency"],
                captured_at=_dt(row["captured_at"]),
            )
            for row in rows
        ]

    # -- refund --------------------------------------------------------------

    def refund(
        self,
        namespace: str,
        request: RefundRequest,
        *,
        allowed_operation_ids: list[str],
    ) -> RefundResponse:
        if not self._operation_allowed(allowed_operation_ids, request.operation_id):
            raise ProviderError(403, "operation is not permitted by this token")
        with self._lock, self._conn:
            self._require_namespace(namespace)
            registration = self._registration_or_none(namespace, request.operation_id)
            if registration is None:
                raise ProviderError(404, f"unknown operation {request.operation_id!r}")
            if "refund" not in registration.allowed_actions:
                raise ProviderError(403, "refunds are not allowed for this operation")

            existing = self._conn.execute(
                """
                SELECT refund_id, amount_minor FROM refunds
                WHERE namespace = ? AND operation_id = ? AND refund_intent_id = ?
                """,
                (namespace, request.operation_id, request.refund_intent_id),
            ).fetchone()

            captured_total = self._captured_total(namespace, request.operation_id)
            refunded_total = self._refunded_total(namespace, request.operation_id)

            if existing is not None:
                if existing["amount_minor"] != request.amount_minor:
                    raise ProviderError(
                        409, "refund intent replayed with a different amount"
                    )
                total = refunded_total
                return RefundResponse(
                    refund_id=existing["refund_id"],
                    operation_id=request.operation_id,
                    refund_intent_id=request.refund_intent_id,
                    amount_minor=existing["amount_minor"],
                    total_refunded_minor=total,
                    status=self._refund_status(total, captured_total),
                )

            if refunded_total + request.amount_minor > captured_total:
                raise ProviderError(409, "refund exceeds the captured total")

            refund_id = _new_id("ref")
            self._conn.execute(
                """
                INSERT INTO refunds
                  (refund_id, namespace, operation_id, refund_intent_id,
                   amount_minor, currency, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    refund_id,
                    namespace,
                    request.operation_id,
                    request.refund_intent_id,
                    request.amount_minor,
                    registration.currency,
                    _now(),
                ),
            )
            total = refunded_total + request.amount_minor
        return RefundResponse(
            refund_id=refund_id,
            operation_id=request.operation_id,
            refund_intent_id=request.refund_intent_id,
            amount_minor=request.amount_minor,
            total_refunded_minor=total,
            status=self._refund_status(total, captured_total),
        )

    # -- ledger --------------------------------------------------------------

    def ledger_view(self, namespace: str) -> LedgerView:
        with self._lock:
            self._require_namespace(namespace)
            registrations = [
                RegistrationRow(
                    namespace=row["namespace"],
                    operation_id=row["operation_id"],
                    intent_id=row["intent_id"],
                    amount_minor=row["amount_minor"],
                    currency=row["currency"],
                    allowed_actions=json.loads(row["allowed_actions"]),
                    registered_at=_dt(row["registered_at"]),
                )
                for row in self._conn.execute(
                    "SELECT * FROM registered_operations WHERE namespace = ? ORDER BY seq",
                    (namespace,),
                ).fetchall()
            ]
            captures = [
                CaptureRow(
                    capture_id=row["capture_id"],
                    namespace=row["namespace"],
                    operation_id=row["operation_id"],
                    idempotency_key=row["idempotency_key"],
                    amount_minor=row["amount_minor"],
                    currency=row["currency"],
                    captured_at=_dt(row["captured_at"]),
                )
                for row in self._conn.execute(
                    "SELECT * FROM captures WHERE namespace = ? ORDER BY seq",
                    (namespace,),
                ).fetchall()
            ]
            refunds = [
                RefundRow(
                    refund_id=row["refund_id"],
                    namespace=row["namespace"],
                    operation_id=row["operation_id"],
                    refund_intent_id=row["refund_intent_id"],
                    amount_minor=row["amount_minor"],
                    currency=row["currency"],
                    created_at=_dt(row["created_at"]),
                )
                for row in self._conn.execute(
                    "SELECT * FROM refunds WHERE namespace = ? ORDER BY seq",
                    (namespace,),
                ).fetchall()
            ]
        canonical = json.dumps(
            {
                "registrations": [row.model_dump(mode="json") for row in registrations],
                "captures": [row.model_dump(mode="json") for row in captures],
                "refunds": [row.model_dump(mode="json") for row in refunds],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return LedgerView(
            namespace=namespace,
            registrations=registrations,
            captures=captures,
            refunds=refunds,
            digest=sha256_hex(canonical.encode("utf-8")),
        )

    # -- internals -----------------------------------------------------------

    def _require_namespace(self, namespace: str) -> None:
        row = self._conn.execute(
            "SELECT 1 FROM namespaces WHERE namespace = ?", (namespace,)
        ).fetchone()
        if row is None:
            raise ProviderError(404, f"unknown namespace {namespace!r}")

    def _registration_or_none(self, namespace: str, operation_id: str) -> RegistrationRow | None:
        row = self._conn.execute(
            "SELECT * FROM registered_operations WHERE namespace = ? AND operation_id = ?",
            (namespace, operation_id),
        ).fetchone()
        if row is None:
            return None
        return RegistrationRow(
            namespace=row["namespace"],
            operation_id=row["operation_id"],
            intent_id=row["intent_id"],
            amount_minor=row["amount_minor"],
            currency=row["currency"],
            allowed_actions=json.loads(row["allowed_actions"]),
            registered_at=_dt(row["registered_at"]),
        )

    def _registration(self, namespace: str, operation_id: str) -> RegistrationRow:
        registration = self._registration_or_none(namespace, operation_id)
        if registration is None:  # pragma: no cover - callers just inserted it
            raise ProviderError(404, f"unknown operation {operation_id!r}")
        return registration

    def _auto_register(self, namespace: str, request: CaptureRequest) -> RegistrationRow:
        assert request.intent_id is not None  # checked by the caller
        try:
            self._conn.execute(
                """
                INSERT INTO registered_operations
                  (namespace, operation_id, intent_id, amount_minor, currency,
                   allowed_actions, registered_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    namespace,
                    request.operation_id,
                    request.intent_id,
                    request.amount_minor,
                    request.currency,
                    json.dumps(["capture", "inquiry", "refund"]),
                    _now(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ProviderError(
                409, "intent already has a registered operation under another id"
            ) from exc
        return self._registration(namespace, request.operation_id)

    def _capture_for_key(self, namespace: str, idempotency_key: str) -> CaptureRow | None:
        row = self._conn.execute(
            "SELECT * FROM captures WHERE namespace = ? AND idempotency_key = ?",
            (namespace, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        return CaptureRow(
            capture_id=row["capture_id"],
            namespace=row["namespace"],
            operation_id=row["operation_id"],
            idempotency_key=row["idempotency_key"],
            amount_minor=row["amount_minor"],
            currency=row["currency"],
            captured_at=_dt(row["captured_at"]),
        )

    def _captured_total(self, namespace: str, operation_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(amount_minor), 0) AS total FROM captures "
            "WHERE namespace = ? AND operation_id = ?",
            (namespace, operation_id),
        ).fetchone()
        return int(row["total"])

    def _refunded_total(self, namespace: str, operation_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(amount_minor), 0) AS total FROM refunds "
            "WHERE namespace = ? AND operation_id = ?",
            (namespace, operation_id),
        ).fetchone()
        return int(row["total"])

    @staticmethod
    def _refund_status(
        total: int, captured_total: int
    ) -> Literal["REFUNDED_PARTIAL", "REFUNDED_FULL"]:
        return "REFUNDED_FULL" if total >= captured_total else "REFUNDED_PARTIAL"

    @staticmethod
    def _operation_allowed(allowed_operation_ids: list[str], operation_id: str) -> bool:
        return "*" in allowed_operation_ids or operation_id in allowed_operation_ids
