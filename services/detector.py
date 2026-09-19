"""Incident detection from the trusted ledger (plan §5.1, §5.4, §4.1 rule 5).

The store's HTTP 200, a UI success message and Jev's observations are never
evidence; only the append-only provider ledger can qualify an incident.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from apps.contracts.evaluation import InvariantId
from apps.contracts.payment import LedgerView

__all__ = ["IncidentDetection", "detect_duplicate_capture"]


@dataclass(frozen=True)
class IncidentDetection:
    namespace: str
    intent_id: str
    operation_id: str
    capture_ids: tuple[str, ...]
    idempotency_keys: tuple[str, ...]
    amount_minor: int
    currency: str
    invariant_id: InvariantId
    detail: str
    detected_at_utc: datetime


def detect_duplicate_capture(ledger: LedgerView, *, intent_id: str) -> IncidentDetection | None:
    """INV-01 violation for one logical intent.

    Counts every positive capture across **all** operations registered to the
    intent, so a duplicate cannot hide by splitting operations, and also flags
    more than one operation for one intent (plan §5.4: one provider operation
    per logical intent).
    """
    operations = sorted(
        {row.operation_id for row in ledger.registrations if row.intent_id == intent_id}
    )
    if not operations:
        return None
    capture_rows = [
        row
        for row in ledger.captures
        if row.operation_id in set(operations) and row.amount_minor > 0
    ]
    if len(capture_rows) <= 1 and len(operations) == 1:
        return None
    first = capture_rows[0] if capture_rows else None
    return IncidentDetection(
        namespace=ledger.namespace,
        intent_id=intent_id,
        operation_id=first.operation_id if first else operations[0],
        capture_ids=tuple(row.capture_id for row in capture_rows),
        idempotency_keys=tuple(row.idempotency_key for row in capture_rows),
        amount_minor=first.amount_minor if first else 0,
        currency=first.currency if first else "GBP",
        invariant_id="INV-01",
        detail=(
            f"{len(capture_rows)} captures across {len(operations)} operation(s) "
            f"for one logical intent"
        ),
        detected_at_utc=datetime.now(UTC),
    )
