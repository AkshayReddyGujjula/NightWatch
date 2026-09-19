"""NightMart store database (plan §5.3).

Single-writer SQLite with the exact tables the plan freezes. Every mutation is
serialized by one lock and uses explicit transactions; uniqueness constraints
(``orders.intent_id``, ``payment_operations.intent_id``, ``confirmations.order_id``,
``fulfillments.order_id``) are what make "one intent -> one order -> one
operation -> one confirmation -> one fulfillment" true even under concurrency.

There is no stock table on purpose (plan §5.3): stock is derived as
``INITIAL_STOCK - SUM(fulfillments.quantity)`` so fulfillment can only ever
decrement once per order.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime

from apps.contracts.base import canonical_sha256, sha256_hex
from apps.contracts.payment import (
    CheckoutIntent,
    Currency,
    IntentItem,
    IntentResponse,
    Order,
    OrderStatus,
    PaymentOperation,
    RouterMode,
    RouterState,
    StoreFacts,
)

CATALOG: dict[str, int] = {"SKU-A": 7999}
CURRENCY: Currency = "GBP"
INITIAL_STOCK = 100
# Fixture voucher allowlist; the UI field is free text and unknown codes are rejected.
VOUCHERS: dict[str, int] = {"NIGHT10": 1000}

SCHEMA = """
CREATE TABLE IF NOT EXISTS checkout_intents (
  intent_id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL,
  cart_hash TEXT NOT NULL,
  amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
  currency TEXT NOT NULL,
  created_at TEXT NOT NULL,
  items_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
  order_id TEXT PRIMARY KEY,
  intent_id TEXT NOT NULL UNIQUE REFERENCES checkout_intents(intent_id),
  status TEXT NOT NULL,
  amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
  currency TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payment_operations (
  operation_id TEXT PRIMARY KEY,
  intent_id TEXT NOT NULL UNIQUE REFERENCES checkout_intents(intent_id),
  idempotency_key TEXT NOT NULL UNIQUE,
  amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
  currency TEXT NOT NULL,
  state TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS confirmations (
  confirmation_id TEXT PRIMARY KEY,
  order_id TEXT NOT NULL UNIQUE REFERENCES orders(order_id),
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fulfillments (
  fulfillment_id TEXT PRIMARY KEY,
  order_id TEXT NOT NULL UNIQUE REFERENCES orders(order_id),
  sku TEXT NOT NULL,
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS refund_intents (
  refund_intent_id TEXT NOT NULL,
  operation_id TEXT NOT NULL,
  amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
  created_at TEXT NOT NULL,
  PRIMARY KEY (operation_id, refund_intent_id)
);
CREATE TABLE IF NOT EXISTS router_state (
  singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
  mode TEXT NOT NULL,
  generation INTEGER NOT NULL,
  handler_hash TEXT NOT NULL,
  rollout_pct INTEGER NOT NULL,
  bucket_seed TEXT NOT NULL,
  lease_id TEXT,
  lease_expires_at TEXT,
  updated_at TEXT NOT NULL,
  buggy_locked INTEGER NOT NULL DEFAULT 0
);
"""

#: Stable handler hash for the containment mode; the router imports this too.
SAFE_HOLD_HANDLER_HASH = sha256_hex(b"safe_hold:no-capture")


class StoreError(Exception):
    """Typed store rejection carrying the HTTP status to surface."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class Store:
    """Single-writer store database."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.isolation_level = None  # explicit transactions only
        self._conn.row_factory = sqlite3.Row
        with self._lock, self._conn:
            self._conn.executescript(SCHEMA)
            columns = {
                row["name"] for row in self._conn.execute("PRAGMA table_info(router_state)")
            }
            if "buggy_locked" not in columns:
                self._conn.execute(
                    "ALTER TABLE router_state ADD COLUMN buggy_locked INTEGER NOT NULL DEFAULT 0"
                )
            self._conn.execute(
                """
                INSERT OR IGNORE INTO router_state
                  (singleton, mode, generation, handler_hash, rollout_pct, bucket_seed,
                   lease_id, lease_expires_at, updated_at, buggy_locked)
                VALUES (1, 'SAFE_HOLD', 1, ?, 0, ?, NULL, NULL, ?, 0)
                """,
                (SAFE_HOLD_HANDLER_HASH, uuid.uuid4().hex, _now()),
            )
            # A process start is a restart: fail closed to SAFE_HOLD (plan §8.3).
            # The buggy-lock ratchet survives restarts; only mode/lease reset.
            self._conn.execute(
                """
                UPDATE router_state
                SET mode = 'SAFE_HOLD', generation = generation + 1, handler_hash = ?,
                    lease_id = NULL, lease_expires_at = NULL, updated_at = ?
                WHERE singleton = 1
                """,
                (SAFE_HOLD_HANDLER_HASH, _now()),
            )

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    @property
    def lock(self) -> threading.Lock:
        return self._lock

    # -- intents -------------------------------------------------------------

    def create_intent(self, customer_id: str, items: list[IntentItem]) -> CheckoutIntent:
        amount = 0
        for item in items:
            price = CATALOG.get(item.sku)
            if price is None:
                raise StoreError(422, f"unknown sku {item.sku!r}")
            amount += price * item.quantity
        if amount <= 0:  # pragma: no cover - Quantity is ge=1 and the catalog is non-empty
            raise StoreError(422, "cart amount must be positive")
        intent = CheckoutIntent(
            intent_id=_new_id("pi"),
            customer_id=customer_id,
            cart_hash=canonical_sha256([item.model_dump(mode="json") for item in items]),
            amount_minor=amount,
            currency=CURRENCY,
            created_at=datetime.now(UTC),
        )
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO checkout_intents
                  (intent_id, customer_id, cart_hash, amount_minor, currency,
                   created_at, items_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intent.intent_id,
                    intent.customer_id,
                    intent.cart_hash,
                    intent.amount_minor,
                    intent.currency,
                    intent.created_at.isoformat(),
                    json.dumps([item.model_dump(mode="json") for item in items]),
                ),
            )
        return intent

    def get_intent_items(self, intent_id: str) -> list[IntentItem]:
        row = self._conn.execute(
            "SELECT items_json FROM checkout_intents WHERE intent_id = ?", (intent_id,)
        ).fetchone()
        if row is None:
            raise StoreError(404, f"unknown intent {intent_id!r}")
        return [IntentItem.model_validate(item) for item in json.loads(row["items_json"])]

    def get_intent(self, intent_id: str) -> CheckoutIntent:
        row = self._conn.execute(
            "SELECT * FROM checkout_intents WHERE intent_id = ?", (intent_id,)
        ).fetchone()
        if row is None:
            raise StoreError(404, f"unknown intent {intent_id!r}")
        return CheckoutIntent(
            intent_id=row["intent_id"],
            customer_id=row["customer_id"],
            cart_hash=row["cart_hash"],
            amount_minor=row["amount_minor"],
            currency=row["currency"],
            created_at=_dt(row["created_at"]),
        )

    def intent_response(self, intent: CheckoutIntent, items: list[IntentItem]) -> IntentResponse:
        return IntentResponse(
            intent_id=intent.intent_id,
            items=items,
            amount_minor=intent.amount_minor,
            currency=intent.currency,
            created_at=intent.created_at,
        )

    # -- orders and operations ----------------------------------------------

    def get_or_create_order_and_operation(
        self, intent_id: str, amount_minor: int
    ) -> tuple[Order, PaymentOperation]:
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._require_intent(intent_id)
                order_row = self._conn.execute(
                    "SELECT * FROM orders WHERE intent_id = ?", (intent_id,)
                ).fetchone()
                if order_row is None:
                    order_id = _new_id("ord")
                    now = _now()
                    self._conn.execute(
                        """
                        INSERT INTO orders
                          (order_id, intent_id, status, amount_minor, currency,
                           created_at, updated_at)
                        VALUES (?, ?, 'PENDING', ?, ?, ?, ?)
                        """,
                        (order_id, intent_id, amount_minor, CURRENCY, now, now),
                    )
                    order_row = self._conn.execute(
                        "SELECT * FROM orders WHERE order_id = ?", (order_id,)
                    ).fetchone()
                operation_row = self._conn.execute(
                    "SELECT * FROM payment_operations WHERE intent_id = ?", (intent_id,)
                ).fetchone()
                if operation_row is None:
                    operation_id = f"op_{intent_id}"
                    self._conn.execute(
                        """
                        INSERT INTO payment_operations
                          (operation_id, intent_id, idempotency_key, amount_minor, currency, state)
                        VALUES (?, ?, ?, ?, ?, 'PENDING')
                        """,
                        (operation_id, intent_id, f"key_{operation_id}", amount_minor, CURRENCY),
                    )
                    operation_row = self._conn.execute(
                        "SELECT * FROM payment_operations WHERE operation_id = ?", (operation_id,)
                    ).fetchone()
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")
        return self._order(order_row), self._operation(operation_row)

    def get_order(self, order_id: str) -> Order:
        row = self._conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        if row is None:
            raise StoreError(404, f"unknown order {order_id!r}")
        return self._order(row)

    def get_operation_for_intent(self, intent_id: str) -> PaymentOperation:
        row = self._conn.execute(
            "SELECT * FROM payment_operations WHERE intent_id = ?", (intent_id,)
        ).fetchone()
        if row is None:
            raise StoreError(404, f"no payment operation for intent {intent_id!r}")
        return self._operation(row)

    def set_order_status(self, order_id: str, status: OrderStatus) -> None:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "UPDATE orders SET status = ?, updated_at = ? WHERE order_id = ?",
                (status, _now(), order_id),
            )
        if cursor.rowcount != 1:
            raise StoreError(404, f"unknown order {order_id!r}")

    def mark_paid(self, order_id: str, operation_id: str, sku: str, quantity: int) -> None:
        """PAID + one confirmation + exactly one fulfillment, atomically."""
        with self._lock, self._conn:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                now = _now()
                cursor = self._conn.execute(
                    "UPDATE orders SET status = 'PAID', updated_at = ? WHERE order_id = ?",
                    (now, order_id),
                )
                if cursor.rowcount != 1:
                    raise StoreError(404, f"unknown order {order_id!r}")
                self._conn.execute(
                    "INSERT OR IGNORE INTO confirmations (confirmation_id, order_id, created_at)"
                    " VALUES (?, ?, ?)",
                    (_new_id("conf"), order_id, now),
                )
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO fulfillments
                      (fulfillment_id, order_id, sku, quantity, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (_new_id("ful"), order_id, sku, quantity, now),
                )
                self._conn.execute(
                    "UPDATE payment_operations SET state = 'CONFIRMED' WHERE operation_id = ?",
                    (operation_id,),
                )
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def set_operation_key(self, operation_id: str, idempotency_key: str) -> None:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "UPDATE payment_operations SET idempotency_key = ? WHERE operation_id = ?",
                (idempotency_key, operation_id),
            )
        if cursor.rowcount != 1:
            raise StoreError(404, f"unknown operation {operation_id!r}")

    def set_operation_state(self, operation_id: str, state: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE payment_operations SET state = ? WHERE operation_id = ?",
                (state, operation_id),
            )

    # -- refunds -------------------------------------------------------------

    def record_refund_intent(
        self, operation_id: str, refund_intent_id: str, amount_minor: int
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO refund_intents
                  (refund_intent_id, operation_id, amount_minor, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (refund_intent_id, operation_id, amount_minor, _now()),
            )

    # -- facts ---------------------------------------------------------------

    def store_facts(self, intent_id: str) -> StoreFacts:
        order = self._conn.execute(
            "SELECT * FROM orders WHERE intent_id = ?", (intent_id,)
        ).fetchone()
        operation = self._conn.execute(
            "SELECT * FROM payment_operations WHERE intent_id = ?", (intent_id,)
        ).fetchone()
        order_count = 1 if order else 0
        confirmation_count = 0
        fulfillment_count = 0
        if order:
            confirmation_count = int(
                self._conn.execute(
                    "SELECT COUNT(*) AS n FROM confirmations WHERE order_id = ?",
                    (order["order_id"],),
                ).fetchone()["n"]
            )
            fulfillment_count = int(
                self._conn.execute(
                    "SELECT COUNT(*) AS n FROM fulfillments WHERE order_id = ?",
                    (order["order_id"],),
                ).fetchone()["n"]
            )
        return StoreFacts(
            intent_id=intent_id,
            order_status=order["status"] if order else None,
            order_count=order_count,
            operation_count=1 if operation else 0,
            operation_id=operation["operation_id"] if operation else None,
            idempotency_key=operation["idempotency_key"] if operation else None,
            confirmation_count=confirmation_count,
            fulfillment_count=fulfillment_count,
            stock_remaining=self.stock_remaining(),
        )

    def stock_remaining(self) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS sold FROM fulfillments"
        ).fetchone()
        return INITIAL_STOCK - int(row["sold"])

    # -- router --------------------------------------------------------------

    def router_state(self) -> RouterState:
        row = self._conn.execute("SELECT * FROM router_state WHERE singleton = 1").fetchone()
        return RouterState(
            mode=row["mode"],
            generation=row["generation"],
            handler_hash=row["handler_hash"],
            rollout_pct=row["rollout_pct"],
            bucket_seed=row["bucket_seed"],
            lease_id=row["lease_id"],
            lease_expires_at=_dt(row["lease_expires_at"]) if row["lease_expires_at"] else None,
            updated_at=_dt(row["updated_at"]),
        )

    def buggy_locked(self) -> bool:
        """One-way ratchet: once containment happened, BUGGY can never be re-armed."""
        row = self._conn.execute(
            "SELECT buggy_locked FROM router_state WHERE singleton = 1"
        ).fetchone()
        return bool(row["buggy_locked"])

    def set_router(
        self,
        *,
        mode: RouterMode,
        expected_generation: int,
        handler_hash: str,
        lease_id: str | None = None,
        lease_expires_at: datetime | None = None,
    ) -> RouterState:
        """Compare-and-swap the router row; exactly one generation wins.

        Any deliberate transition into SAFE_HOLD or SAFE latches ``buggy_locked``
        permanently (plan §8.1: no transition returns to BUGGY).
        """
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                UPDATE router_state
                SET mode = ?, generation = generation + 1, handler_hash = ?,
                    lease_id = ?, lease_expires_at = ?,
                    buggy_locked = CASE WHEN ? IN ('SAFE', 'SAFE_HOLD') THEN 1
                                        ELSE buggy_locked END,
                    updated_at = ?
                WHERE singleton = 1 AND generation = ?
                """,
                (
                    mode,
                    handler_hash,
                    lease_id,
                    lease_expires_at.isoformat() if lease_expires_at else None,
                    mode,
                    _now(),
                    expected_generation,
                ),
            )
            if cursor.rowcount != 1:
                raise StoreError(409, "router generation mismatch")
        return self.router_state()

    # -- internals -----------------------------------------------------------

    def _require_intent(self, intent_id: str) -> None:
        row = self._conn.execute(
            "SELECT 1 FROM checkout_intents WHERE intent_id = ?", (intent_id,)
        ).fetchone()
        if row is None:
            raise StoreError(404, f"unknown intent {intent_id!r}")

    @staticmethod
    def _order(row: sqlite3.Row) -> Order:
        return Order(
            order_id=row["order_id"],
            intent_id=row["intent_id"],
            status=row["status"],
            amount_minor=row["amount_minor"],
            currency=row["currency"],
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
        )

    @staticmethod
    def _operation(row: sqlite3.Row) -> PaymentOperation:
        return PaymentOperation(
            operation_id=row["operation_id"],
            intent_id=row["intent_id"],
            idempotency_key=row["idempotency_key"],
            amount_minor=row["amount_minor"],
            currency=row["currency"],
            state=row["state"],
        )
