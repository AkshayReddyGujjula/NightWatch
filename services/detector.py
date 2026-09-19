"""Incident detection from the trusted ledger (plan §5.1, §4.1 rule 5).

The store's HTTP 200, a UI success message and Jev's observations are never
evidence; only the append-only provider ledger can qualify an incident.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

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
    invariant_id: str
    detail: str
    detected_at_utc: str


def detect_duplicate_capture(ledger: LedgerView, *, intent_id: str) -> IncidentDetection | None:
    """INV-01 violation: more than one positive capture for one logical intent."""
    operations = {row.operation_id for row in ledger.registrations if row.intent_id == intent_id}
    for operation_id in sorted(operations):
        captures = [
            row
            for row in ledger.captures
            if row.operation_id == operation_id and row.amount_minor > 0
        ]
        if len(captures) > 1:
            first = captures[0]
            return IncidentDetection(
                namespace=ledger.namespace,
                intent_id=intent_id,
                operation_id=operation_id,
                capture_ids=tuple(row.capture_id for row in captures),
                idempotency_keys=tuple(row.idempotency_key for row in captures),
                amount_minor=first.amount_minor,
                currency=first.currency,
                invariant_id="INV-01",
                detail=(
                    f"{len(captures)} captures for one logical intent "
                    f"(operation {operation_id})"
                ),
                detected_at_utc=datetime.now(UTC).isoformat(),
            )
    return None
