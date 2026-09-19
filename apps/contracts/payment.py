"""Payment and checkout domain contracts.

Covers the NightMart store tables, the trusted mock-provider ledger rows, the
public store API (field names mirror ``apps/storefront/assets/api.js``, Track B's
single field-name holder) and the router state (plan §5.3, §9.2, §9.3).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from apps.contracts.base import (
    CandidateId,
    Hash256,
    IdStr,
    IsoUtcDatetime,
    NonEmptyStr,
    ScenarioId,
    StrictModel,
    UtcDatetime,
)

__all__ = [
    "CaptureRequest",
    "CaptureResponse",
    "CaptureRow",
    "CheckoutIntent",
    "CheckoutRequest",
    "CheckoutResponse",
    "Confirmation",
    "CreateIntentRequest",
    "Currency",
    "FaultKind",
    "Fulfillment",
    "IntentItem",
    "IntentResponse",
    "LedgerView",
    "MinorAmount",
    "OperationRegisterRequest",
    "Order",
    "OrderResponse",
    "OrderStatus",
    "PaymentOperation",
    "PaymentOperationState",
    "ProviderAction",
    "ProviderTokenClaims",
    "Quantity",
    "RefundIntent",
    "RefundRequest",
    "RefundResponse",
    "RefundRow",
    "RegistrationRow",
    "RouterMode",
    "RouterState",
    "ScopedTokenRequest",
    "ScopedTokenResponse",
]

Currency = Literal["GBP"]

# Status vocabulary must stay consistent with apps/storefront/assets/api.js.
OrderStatus = Literal[
    "PENDING",
    "PROCESSING",
    "PENDING_CONFIRMATION",
    "PAID",
    "DECLINED",
    "QUARANTINED",
    "SAFE_HOLD",
    "REFUNDED_PARTIAL",
    "REFUNDED_FULL",
]

RouterMode = Literal["BUGGY", "SAFE_HOLD", "SAFE", "LEGACY"]

PaymentOperationState = Literal["PENDING", "CONFIRMED", "PENDING_CONFIRMATION", "QUARANTINED"]

ProviderAction = Literal["capture", "refund", "inquiry"]

FaultKind = Literal["DROP_AFTER_CAPTURE_ONCE", "TIMEOUT_BEFORE_CAPTURE_ONCE"]

# NightMart catalogue bound (apps/storefront/assets/catalog.js: maxQuantity = 5).
Quantity = Annotated[int, Field(ge=1, le=5)]

MinorAmount = Annotated[int, Field(gt=0)]

EmailAddress = Annotated[
    str,
    StringConstraints(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
]

VoucherCode = Annotated[str, StringConstraints(min_length=1, max_length=40)]


# ------------------------------------------------------------------ public API


class IntentItem(StrictModel):
    sku: NonEmptyStr
    quantity: Quantity


class CreateIntentRequest(StrictModel):
    customer_id: NonEmptyStr
    items: Annotated[list[IntentItem], Field(min_length=1)]


class IntentResponse(StrictModel):
    intent_id: IdStr
    items: list[IntentItem]
    amount_minor: MinorAmount
    currency: Currency
    created_at: UtcDatetime


class CheckoutRequest(StrictModel):
    email: EmailAddress
    address: NonEmptyStr
    voucher_code: VoucherCode | None = None


class CheckoutResponse(StrictModel):
    """No ``order_id`` means the checkout did not complete: read ``status``."""

    order_id: IdStr | None = None
    intent_id: IdStr
    status: OrderStatus
    amount_minor: int | None = None
    captured_total_minor: int | None = None
    currency: Currency = "GBP"
    message: str | None = None


class OrderResponse(StrictModel):
    order_id: IdStr
    intent_id: IdStr
    status: OrderStatus
    amount_minor: MinorAmount
    currency: Currency
    created_at: UtcDatetime
    updated_at: UtcDatetime


# ------------------------------------------------------------------ store rows


class CheckoutIntent(StrictModel):
    intent_id: IdStr
    customer_id: NonEmptyStr
    cart_hash: Hash256
    amount_minor: MinorAmount
    currency: Currency
    created_at: UtcDatetime


class Order(StrictModel):
    order_id: IdStr
    intent_id: IdStr
    status: OrderStatus
    amount_minor: MinorAmount
    currency: Currency
    created_at: UtcDatetime
    updated_at: UtcDatetime


class PaymentOperation(StrictModel):
    operation_id: IdStr
    intent_id: IdStr
    idempotency_key: NonEmptyStr
    amount_minor: MinorAmount
    currency: Currency
    state: PaymentOperationState


class Confirmation(StrictModel):
    confirmation_id: IdStr
    order_id: IdStr
    created_at: UtcDatetime


class Fulfillment(StrictModel):
    fulfillment_id: IdStr
    order_id: IdStr
    sku: NonEmptyStr
    quantity: Quantity
    created_at: UtcDatetime


class RefundIntent(StrictModel):
    refund_intent_id: IdStr
    operation_id: IdStr
    amount_minor: MinorAmount
    created_at: UtcDatetime


class RouterState(StrictModel):
    mode: RouterMode
    generation: Annotated[int, Field(ge=0)]
    handler_hash: Hash256
    rollout_pct: Annotated[int, Field(ge=0, le=100)] = 0
    bucket_seed: NonEmptyStr
    lease_id: IdStr | None = None
    lease_expires_at: UtcDatetime | None = None
    updated_at: UtcDatetime


# ------------------------------------------------------------ provider ledger


class RegistrationRow(StrictModel):
    namespace: NonEmptyStr
    operation_id: IdStr
    intent_id: IdStr
    amount_minor: MinorAmount
    currency: Currency
    allowed_actions: Annotated[list[ProviderAction], Field(min_length=1)]
    registered_at: UtcDatetime


class CaptureRow(StrictModel):
    capture_id: IdStr
    namespace: NonEmptyStr
    operation_id: IdStr
    idempotency_key: NonEmptyStr
    amount_minor: MinorAmount
    currency: Currency
    captured_at: UtcDatetime


class RefundRow(StrictModel):
    refund_id: IdStr
    namespace: NonEmptyStr
    operation_id: IdStr
    refund_intent_id: IdStr
    amount_minor: MinorAmount
    currency: Currency
    created_at: UtcDatetime


class LedgerView(StrictModel):
    """Evaluator-only read of one namespace; ``digest`` covers the ordered rows."""

    namespace: NonEmptyStr
    registrations: list[RegistrationRow]
    captures: list[CaptureRow]
    refunds: list[RefundRow]
    digest: Hash256


class ProviderTokenClaims(StrictModel):
    """Decoded scoped provider token bound to one run/candidate/scenario (plan §9.3)."""

    incident_id: IdStr
    candidate_id: CandidateId
    scenario_id: ScenarioId
    namespace: NonEmptyStr
    allowed_operation_ids: Annotated[list[IdStr], Field(min_length=1)]
    expires_at_utc: UtcDatetime


# ------------------------------------------------------------ provider wire API


class CaptureRequest(StrictModel):
    operation_id: IdStr
    idempotency_key: NonEmptyStr
    amount_minor: MinorAmount
    currency: Currency
    # Required only when the operation is not pre-registered: the provider
    # auto-registers it within the token's namespace (evaluator registration
    # remains the way to freeze amounts for deterministic fixtures).
    intent_id: IdStr | None = None


class CaptureResponse(StrictModel):
    capture_id: IdStr
    operation_id: IdStr
    amount_minor: MinorAmount
    currency: Currency
    replayed: bool


class RefundRequest(StrictModel):
    operation_id: IdStr
    refund_intent_id: IdStr
    amount_minor: MinorAmount


class RefundResponse(StrictModel):
    refund_id: IdStr
    operation_id: IdStr
    refund_intent_id: IdStr
    amount_minor: MinorAmount
    total_refunded_minor: Annotated[int, Field(ge=0)]
    status: Literal["REFUNDED_PARTIAL", "REFUNDED_FULL"]


class OperationRegisterRequest(StrictModel):
    namespace: NonEmptyStr
    operation_id: IdStr
    intent_id: IdStr
    amount_minor: MinorAmount
    currency: Currency
    allowed_actions: Annotated[list[ProviderAction], Field(min_length=1)]


class ScopedTokenRequest(StrictModel):
    incident_id: IdStr
    candidate_id: CandidateId
    scenario_id: ScenarioId
    namespace: NonEmptyStr
    allowed_operation_ids: Annotated[list[IdStr], Field(min_length=1)]
    expires_in_seconds: Annotated[int, Field(gt=0, le=86400)] = 7200


class ScopedTokenResponse(StrictModel):
    token: NonEmptyStr
    expires_at_utc: UtcDatetime


class RefundApiRequest(StrictModel):
    """Public ``POST /api/refunds`` body (plan §9.2)."""

    order_id: IdStr
    refund_intent_id: IdStr
    amount_minor: MinorAmount


class RouterUpdateRequest(StrictModel):
    """Internal ``PUT /internal/router`` body (plan §9.2, §14.2)."""

    mode: Literal["BUGGY", "SAFE_HOLD", "SAFE", "LEGACY"]
    expected_generation: Annotated[int, Field(ge=0)]
    lease_id: IdStr | None = None
    lease_expires_at: IsoUtcDatetime | None = None
    handler_sha256: Hash256 | None = None


class StoreFacts(StrictModel):
    """Evaluator-only app truth for one intent (``GET /internal/state/{intent_id}``)."""

    intent_id: IdStr
    order_status: OrderStatus | None = None
    order_count: Annotated[int, Field(ge=0)]
    operation_count: Annotated[int, Field(ge=0)]
    operation_id: IdStr | None = None
    idempotency_key: str | None = None
    confirmation_count: Annotated[int, Field(ge=0)]
    fulfillment_count: Annotated[int, Field(ge=0)]
    # May go negative if a run oversells; the oracle reports it rather than 500-ing.
    stock_remaining: int
