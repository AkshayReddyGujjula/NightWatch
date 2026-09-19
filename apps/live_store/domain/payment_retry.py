"""Checkout payment retry handlers.

``payment_retry.py`` is the ONLY file Candidate C may patch (plan §10.3), so it
stays small and self-contained. Two handlers exist:

- :func:`buggy_retry_checkout` — the incident (plan §5.1): a lost response is
  treated as failure and the handler charges again with a FRESH idempotency key.
- :func:`safe_retry_checkout` — the prepared repair (Candidate B, plan §5.2):
  one persisted key, and on uncertainty it inquires by operation ID instead of
  capturing again. Zero captures or an unavailable lookup stays
  PENDING_CONFIRMATION; anything else unexpected is QUARANTINED.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from apps.contracts.payment import CaptureResponse, CaptureRow

__all__ = [
    "PaymentOutcome",
    "PaymentProvider",
    "PaymentStatus",
    "ProviderRejected",
    "ProviderUncertain",
    "buggy_retry_checkout",
    "safe_retry_checkout",
]


class ProviderUncertain(Exception):
    """Transport failure, timeout or a lost response: the capture state is unknown."""


class ProviderRejected(Exception):
    """The provider answered with a business rejection (4xx)."""


class PaymentProvider(Protocol):
    async def capture(
        self,
        operation_id: str,
        idempotency_key: str,
        amount_minor: int,
        currency: str,
        intent_id: str,
    ) -> CaptureResponse: ...

    async def captures(self, operation_id: str) -> list[CaptureRow]: ...


PaymentStatus = Literal["PAID", "PENDING_CONFIRMATION", "QUARANTINED", "FAILED"]


@dataclass(frozen=True)
class PaymentOutcome:
    status: PaymentStatus
    capture_id: str | None = None
    idempotency_key: str | None = None
    reason: str | None = None


async def buggy_retry_checkout(
    provider: PaymentProvider,
    *,
    operation_id: str,
    amount_minor: int,
    currency: str,
    intent_id: str,
    attempt_keys: list[str],
    persist_key: Callable[[str], None],
) -> PaymentOutcome:
    """BUGGY handler: fresh idempotency key on every attempt after uncertainty."""
    first_key, retry_key = attempt_keys[0], attempt_keys[1]
    persist_key(first_key)
    used_key = first_key
    try:
        capture = await provider.capture(operation_id, first_key, amount_minor, currency, intent_id)
    except ProviderUncertain:
        used_key = retry_key
        persist_key(retry_key)
        try:
            capture = await provider.capture(
                operation_id, retry_key, amount_minor, currency, intent_id
            )
        except ProviderUncertain as exc:
            return PaymentOutcome(
                "PENDING_CONFIRMATION", idempotency_key=used_key, reason=f"uncertain: {exc}"
            )
        except ProviderRejected as exc:
            return PaymentOutcome("FAILED", idempotency_key=used_key, reason=str(exc))
    except ProviderRejected as exc:
        return PaymentOutcome("FAILED", idempotency_key=used_key, reason=str(exc))
    return PaymentOutcome("PAID", capture_id=capture.capture_id, idempotency_key=used_key)


async def safe_retry_checkout(
    provider: PaymentProvider,
    *,
    operation_id: str,
    amount_minor: int,
    currency: str,
    intent_id: str,
    stable_key: str,
    persist_key: Callable[[str], None],
) -> PaymentOutcome:
    """SAFE handler (plan §5.2): never capture again while uncertain."""
    persist_key(stable_key)
    try:
        capture = await provider.capture(
            operation_id, stable_key, amount_minor, currency, intent_id
        )
    except ProviderUncertain:
        try:
            captures = await provider.captures(operation_id)
        except (ProviderUncertain, ProviderRejected) as exc:
            return PaymentOutcome(
                "PENDING_CONFIRMATION",
                idempotency_key=stable_key,
                reason=f"provider lookup unavailable: {exc}",
            )
        matching = [
            row for row in captures if row.amount_minor == amount_minor and row.currency == currency
        ]
        if not captures:
            return PaymentOutcome(
                "PENDING_CONFIRMATION",
                idempotency_key=stable_key,
                reason="no capture found for the operation",
            )
        if len(captures) == 1 and matching:
            return PaymentOutcome(
                "PAID", capture_id=captures[0].capture_id, idempotency_key=stable_key
            )
        return PaymentOutcome(
            "QUARANTINED",
            idempotency_key=stable_key,
            reason=f"unexpected capture set ({len(captures)} captures)",
        )
    except ProviderRejected as exc:
        return PaymentOutcome("FAILED", idempotency_key=stable_key, reason=str(exc))
    return PaymentOutcome("PAID", capture_id=capture.capture_id, idempotency_key=stable_key)
