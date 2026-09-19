"""NightMart live store ASGI app (plan §5.0, §9.2).

Public storefront API plus the internal router/state endpoints. The store's
only outbound credential is its scoped provider token; internal endpoints use
``LIVE_INTERNAL_TOKEN`` (router) and ``EVALUATOR_TOKEN`` (app truth).
"""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from pydantic_settings import BaseSettings, SettingsConfigDict

from apps.contracts.payment import (
    CheckoutRequest,
    CheckoutResponse,
    CreateIntentRequest,
    IntentResponse,
    OrderResponse,
    RefundApiRequest,
    RouterState,
    RouterUpdateRequest,
    StoreFacts,
)
from apps.live_store.domain.checkout import perform_checkout
from apps.live_store.domain.payment_retry import ProviderRejected, ProviderUncertain
from apps.live_store.domain.refund import perform_refund
from apps.live_store.provider import HttpPaymentProvider, UnavailableProvider
from apps.live_store.router import Router
from apps.live_store.store import Store, StoreError

router = APIRouter()


class StoreSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    modal_environment: str = "nightwatch-a"
    live_internal_token: str = ""
    evaluator_token: str = ""
    provider_base_url: str = ""
    provider_token: str = ""
    store_db_path: str = ""


def _bearer_token(authorization: str | None) -> str | None:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def _require_token(configured: str, supplied: str | None, label: str) -> None:
    if not configured:
        raise HTTPException(status_code=503, detail=f"{label} token is not configured")
    if supplied is None or not hmac.compare_digest(supplied, configured):
        raise HTTPException(status_code=401, detail=f"invalid {label} token")


async def require_live_internal(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    _require_token(
        request.app.state.settings.live_internal_token,
        _bearer_token(authorization),
        "live internal",
    )


async def require_evaluator(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    _require_token(
        request.app.state.settings.evaluator_token, _bearer_token(authorization), "evaluator"
    )


def _http_from_store_error(exc: StoreError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


# ------------------------------------------------------------------ public API


@router.post("/api/intents", response_model=IntentResponse, status_code=201)
async def create_intent(body: CreateIntentRequest, request: Request) -> IntentResponse:
    store: Store = request.app.state.store
    try:
        intent = store.create_intent(body.customer_id, body.items)
    except StoreError as exc:
        raise _http_from_store_error(exc) from exc
    return store.intent_response(intent, body.items)


@router.get("/api/intents/{intent_id}", response_model=IntentResponse)
async def get_intent(intent_id: str, request: Request) -> IntentResponse:
    store: Store = request.app.state.store
    try:
        intent = store.get_intent(intent_id)
        items = store.get_intent_items(intent_id)
    except StoreError as exc:
        raise _http_from_store_error(exc) from exc
    return store.intent_response(intent, items)


@router.post("/api/checkout/{intent_id}", response_model=CheckoutResponse)
async def checkout(
    intent_id: str, body: CheckoutRequest, request: Request
) -> CheckoutResponse:
    try:
        return await perform_checkout(
            request.app.state.store,
            request.app.state.router,
            request.app.state.provider,
            intent_id=intent_id,
            request=body,
        )
    except StoreError as exc:
        raise _http_from_store_error(exc) from exc


@router.get("/api/orders/{order_id}", response_model=OrderResponse)
async def get_order(order_id: str, request: Request) -> OrderResponse:
    store: Store = request.app.state.store
    try:
        order = store.get_order(order_id)
    except StoreError as exc:
        raise _http_from_store_error(exc) from exc
    return OrderResponse(
        order_id=order.order_id,
        intent_id=order.intent_id,
        status=order.status,
        amount_minor=order.amount_minor,
        currency=order.currency,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


@router.post("/api/refunds", response_model=OrderResponse)
async def create_refund(body: RefundApiRequest, request: Request) -> OrderResponse:
    try:
        return await perform_refund(
            request.app.state.store,
            request.app.state.provider,
            order_id=body.order_id,
            refund_intent_id=body.refund_intent_id,
            amount_minor=body.amount_minor,
        )
    except StoreError as exc:
        raise _http_from_store_error(exc) from exc
    except ProviderRejected as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ProviderUncertain as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# ----------------------------------------------------------------- internal API


@router.get("/internal/router", response_model=RouterState)
async def read_router(
    request: Request,
    _: Annotated[None, Depends(require_live_internal)],
) -> RouterState:
    return request.app.state.router.state()


@router.put("/internal/router", response_model=RouterState)
async def update_router(
    body: RouterUpdateRequest,
    request: Request,
    _: Annotated[None, Depends(require_live_internal)],
) -> RouterState:
    try:
        return request.app.state.router.set_mode(
            body.mode,
            expected_generation=body.expected_generation,
            lease_id=body.lease_id,
            lease_expires_at=body.lease_expires_at,
        )
    except StoreError as exc:
        raise _http_from_store_error(exc) from exc


@router.get("/internal/state/{intent_id}", response_model=StoreFacts)
async def read_state(
    intent_id: str,
    request: Request,
    _: Annotated[None, Depends(require_evaluator)],
) -> StoreFacts:
    try:
        return request.app.state.store.store_facts(intent_id)
    except StoreError as exc:
        raise _http_from_store_error(exc) from exc


def create_app(
    settings: StoreSettings | None = None,
    *,
    db_path: str | None = None,
    provider: object | None = None,
) -> FastAPI:
    resolved = settings or StoreSettings()
    path = db_path if db_path is not None else (resolved.store_db_path or ":memory:")
    app = FastAPI(title="NightWatch live store", version="0.1.0")
    app.state.settings = resolved
    store = Store(path)
    app.state.store = store
    app.state.router = Router(store)
    if provider is not None:
        app.state.provider = provider
    elif resolved.provider_base_url:
        app.state.provider = HttpPaymentProvider(
            resolved.provider_base_url, resolved.provider_token
        )
    else:
        app.state.provider = UnavailableProvider()

    @app.get("/health")
    async def health_root() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "live_store",
            "mode": store.router_state().mode,
        }

    app.include_router(router)
    return app


app = create_app()
