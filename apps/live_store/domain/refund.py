"""Refund orchestration (plan §13 S06/S07, §5.3).

Refund intents are idempotent: replaying one appends nothing at the provider
and never changes the recorded refund. The provider enforces the captured-total
cap; the store mirrors the resulting order status.
"""

from __future__ import annotations

from typing import Protocol

from apps.contracts.payment import OrderResponse, RefundResponse
from apps.live_store.store import Store

__all__ = ["perform_refund"]


class RefundProvider(Protocol):
    async def refund(
        self, operation_id: str, refund_intent_id: str, amount_minor: int
    ) -> RefundResponse: ...


async def perform_refund(
    store: Store,
    provider: RefundProvider,
    *,
    order_id: str,
    refund_intent_id: str,
    amount_minor: int,
) -> OrderResponse:
    order = store.get_order(order_id)
    operation = store.get_operation_for_intent(order.intent_id)
    store.record_refund_intent(operation.operation_id, refund_intent_id, amount_minor)
    result = await provider.refund(operation.operation_id, refund_intent_id, amount_minor)
    store.set_order_status(order_id, result.status)
    updated = store.get_order(order_id)
    return OrderResponse(
        order_id=updated.order_id,
        intent_id=updated.intent_id,
        status=updated.status,
        amount_minor=updated.amount_minor,
        currency=updated.currency,
        created_at=updated.created_at,
        updated_at=updated.updated_at,
    )
