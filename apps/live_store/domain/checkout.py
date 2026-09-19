"""Checkout orchestration for the live store (plan §5.1, §5.2).

BUGGY and SAFE route to their handlers in ``domain/payment_retry.py``; the
outcome is applied to the store under uniqueness constraints so one intent can
never produce two orders, confirmations or fulfillments.
"""

from __future__ import annotations

from apps.contracts.payment import (
    CheckoutRequest,
    CheckoutResponse,
    Order,
    OrderStatus,
    PaymentOperation,
)
from apps.live_store.domain.payment_retry import (
    PaymentOutcome,
    PaymentProvider,
    buggy_retry_checkout,
    safe_retry_checkout,
)
from apps.live_store.router import Router
from apps.live_store.store import CURRENCY, VOUCHERS, Store, StoreError

__all__ = ["perform_checkout"]

_SETTLED_ORDER_STATUSES = {"PAID", "REFUNDED_PARTIAL", "REFUNDED_FULL", "QUARANTINED"}

_OUTCOME_ORDER_STATUS: dict[str, OrderStatus] = {
    "PENDING_CONFIRMATION": "PENDING_CONFIRMATION",
    "QUARANTINED": "QUARANTINED",
    "FAILED": "DECLINED",
}

_OUTCOME_OPERATION_STATE: dict[str, str] = {
    "PENDING_CONFIRMATION": "PENDING_CONFIRMATION",
    "QUARANTINED": "QUARANTINED",
    "FAILED": "PENDING",
}


async def perform_checkout(
    store: Store,
    router: Router,
    provider: PaymentProvider,
    *,
    intent_id: str,
    request: CheckoutRequest,
) -> CheckoutResponse:
    intent = store.get_intent(intent_id)

    discount = 0
    if request.voucher_code is not None:
        discount = VOUCHERS.get(request.voucher_code, 0)
        if discount == 0:
            raise StoreError(422, f"unknown voucher code {request.voucher_code!r}")
    total = intent.amount_minor - discount
    if total <= 0:
        raise StoreError(422, "amount due must be positive after the discount")

    mode = router.state().mode
    if mode == "SAFE_HOLD":
        return CheckoutResponse(
            order_id=None,
            intent_id=intent_id,
            status="SAFE_HOLD",
            amount_minor=total,
            currency=CURRENCY,
            message="New payments are held for review; nothing was captured for this attempt.",
        )

    order, operation = store.get_or_create_order_and_operation(intent_id, total)

    # A settled order is never mutated by a later checkout; replayed checkouts
    # return the stored truth (plan INV-02: PAID/DECLINED/refunded states are
    # authoritative, and a second attempt must not "downgrade" them).
    if order.status in _SETTLED_ORDER_STATUSES:
        return CheckoutResponse(
            order_id=order.order_id,
            intent_id=order.intent_id,
            status=order.status,
            amount_minor=order.amount_minor,
            currency=CURRENCY,
            message="Already settled; no new payment attempt was made.",
        )

    # Re-check containment immediately before any capture can fire: a Safe Stop
    # that won the race must stop this attempt (plan §8.4). The remaining window
    # narrows to the provider call itself; full operation-stamping arrives with
    # the lease slice.
    mode = router.state().mode
    if mode == "SAFE_HOLD":
        return CheckoutResponse(
            order_id=None,
            intent_id=intent_id,
            status="SAFE_HOLD",
            amount_minor=total,
            currency=CURRENCY,
            message="New payments are held for review; nothing was captured for this attempt.",
        )

    items = store.get_intent_items(intent_id)
    sku = items[0].sku if items else "SKU-A"
    quantity = sum(item.quantity for item in items) or 1

    def persist_key(key: str) -> None:
        store.set_operation_key(operation.operation_id, key)

    if mode == "BUGGY":
        outcome = await buggy_retry_checkout(
            provider,
            operation_id=operation.operation_id,
            amount_minor=total,
            currency=CURRENCY,
            intent_id=intent_id,
            attempt_keys=[
                f"key_{operation.operation_id}_a1",
                f"key_{operation.operation_id}_a2",
            ],
            persist_key=persist_key,
        )
    elif mode == "SAFE":
        outcome = await safe_retry_checkout(
            provider,
            operation_id=operation.operation_id,
            amount_minor=total,
            currency=CURRENCY,
            intent_id=intent_id,
            stable_key=f"key_{operation.operation_id}",
            persist_key=persist_key,
        )
    else:  # pragma: no cover - LEGACY is rejected by the router today
        raise StoreError(409, f"router mode {mode} cannot perform a checkout")

    return _apply_outcome(store, order, operation, outcome, total, sku, quantity)


def _apply_outcome(
    store: Store,
    order: Order,
    operation: PaymentOperation,
    outcome: PaymentOutcome,
    total: int,
    sku: str,
    quantity: int,
) -> CheckoutResponse:
    if outcome.status == "PAID":
        if store.mark_paid(order.order_id, operation.operation_id, sku, quantity):
            return CheckoutResponse(
                order_id=order.order_id,
                intent_id=order.intent_id,
                status="PAID",
                amount_minor=total,
                currency=CURRENCY,
                message=outcome.reason,
            )
        settled = store.get_order(order.order_id)
        return CheckoutResponse(
            order_id=settled.order_id,
            intent_id=settled.intent_id,
            status=settled.status,
            amount_minor=settled.amount_minor,
            currency=CURRENCY,
            message="Settled by a concurrent outcome; no new payment state was applied.",
        )
    status = _OUTCOME_ORDER_STATUS[outcome.status]
    if store.set_order_status_if_unsettled(order.order_id, status):
        store.set_operation_state(
            operation.operation_id, _OUTCOME_OPERATION_STATE[outcome.status]
        )
        return CheckoutResponse(
            order_id=order.order_id,
            intent_id=order.intent_id,
            status=status,
            amount_minor=total,
            currency=CURRENCY,
            message=outcome.reason,
        )
    settled = store.get_order(order.order_id)
    return CheckoutResponse(
        order_id=settled.order_id,
        intent_id=settled.intent_id,
        status=settled.status,
        amount_minor=settled.amount_minor,
        currency=CURRENCY,
        message="Settled by a concurrent outcome; no new payment state was applied.",
    )
