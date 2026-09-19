"""Trusted mock payment provider ASGI app (plan §9.3).

Evaluator endpoints (namespace management, operation registration, scoped-token
minting, faults, ledger reads) require ``EVALUATOR_TOKEN``. Store-facing
endpoints (``/capture``, ``/refund``, captures inquiry) require a scoped signed
token bound to one namespace, operation IDs and expiry.
"""

from __future__ import annotations

import hmac
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic_settings import BaseSettings, SettingsConfigDict

from apps.contracts.base import IdStr, NonEmptyStr, StrictModel, UtcDatetime
from apps.contracts.payment import (
    CaptureRequest,
    CaptureResponse,
    CaptureRow,
    FaultKind,
    LedgerView,
    MinorAmount,
    OperationRegisterRequest,
    ProviderTokenClaims,
    RefundRequest,
    RefundResponse,
    RegistrationRow,
    ScopedTokenRequest,
    ScopedTokenResponse,
)
from apps.trusted_provider.auth import TokenError, mint_token, verify_token
from apps.trusted_provider.faults import FaultSchedules
from apps.trusted_provider.ledger import LedgerStore, ProviderError

router = APIRouter()

DROPPED_RESPONSE_STATUS = 504


class ProviderSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    provider_signing_secret: str = ""
    evaluator_token: str = ""
    live_internal_token: str = ""
    provider_db_path: str = ""


class NamespaceRequest(StrictModel):
    namespace: NonEmptyStr


class NamespaceResponse(StrictModel):
    namespace: NonEmptyStr
    created_at: UtcDatetime


class FaultArmRequest(StrictModel):
    namespace: NonEmptyStr
    fault: FaultKind


class DemoDoubleChargeRequest(StrictModel):
    """Exact operation frozen by the trusted operator before the demo checkout."""

    operation_id: IdStr
    intent_id: IdStr
    amount_minor: MinorAmount
    currency: str = "GBP"


class DemoDoubleChargeSetup(StrictModel):
    namespace: NonEmptyStr
    token: NonEmptyStr
    expires_at_utc: UtcDatetime


def _bearer_token(authorization: str | None) -> str | None:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


def _operation_allowed(allowed_operation_ids: list[str], operation_id: str) -> bool:
    return "*" in allowed_operation_ids or operation_id in allowed_operation_ids


def _as_http_error(exc: ProviderError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


async def require_evaluator(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    expected = request.app.state.settings.evaluator_token
    if not expected:
        raise HTTPException(status_code=503, detail="evaluator token is not configured")
    supplied = _bearer_token(authorization)
    if supplied is None or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid evaluator token")


async def require_demo_operator(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    expected = request.app.state.settings.live_internal_token
    if not expected:
        raise HTTPException(status_code=503, detail="demo operator token is not configured")
    supplied = _bearer_token(authorization)
    if supplied is None or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid demo operator token")


async def require_scoped_token(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> ProviderTokenClaims:
    supplied = _bearer_token(authorization)
    if supplied is None:
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        return verify_token(supplied, request.app.state.settings.provider_signing_secret)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


# ------------------------------------------------------------ evaluator-only


@router.post("/internal/namespaces", response_model=NamespaceResponse, status_code=201)
async def create_namespace(
    body: NamespaceRequest,
    request: Request,
    _: Annotated[None, Depends(require_evaluator)],
) -> NamespaceResponse:
    try:
        request.app.state.ledger.create_namespace(body.namespace)
    except ProviderError as exc:
        raise _as_http_error(exc) from exc
    return NamespaceResponse(namespace=body.namespace, created_at=datetime.now(UTC))


@router.post("/internal/operations", response_model=RegistrationRow, status_code=201)
async def register_operation(
    body: OperationRegisterRequest,
    request: Request,
    _: Annotated[None, Depends(require_evaluator)],
) -> RegistrationRow:
    try:
        return request.app.state.ledger.register_operation(body)
    except ProviderError as exc:
        raise _as_http_error(exc) from exc


@router.post("/internal/scoped-tokens", response_model=ScopedTokenResponse)
async def create_scoped_token(
    body: ScopedTokenRequest,
    request: Request,
    _: Annotated[None, Depends(require_evaluator)],
) -> ScopedTokenResponse:
    settings: ProviderSettings = request.app.state.settings
    expires_at = datetime.now(UTC) + timedelta(seconds=body.expires_in_seconds)
    claims = ProviderTokenClaims(
        incident_id=body.incident_id,
        candidate_id=body.candidate_id,
        scenario_id=body.scenario_id,
        namespace=body.namespace,
        allowed_operation_ids=body.allowed_operation_ids,
        expires_at_utc=expires_at,
    )
    try:
        token = mint_token(claims, settings.provider_signing_secret)
    except TokenError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ScopedTokenResponse(token=token, expires_at_utc=expires_at)


@router.post("/internal/faults", status_code=204)
async def arm_fault(
    body: FaultArmRequest,
    request: Request,
    _: Annotated[None, Depends(require_evaluator)],
) -> Response:
    try:
        request.app.state.ledger.require_namespace(body.namespace)
    except ProviderError as exc:
        raise _as_http_error(exc) from exc
    request.app.state.faults.arm(body.namespace, body.fault)
    return Response(status_code=204)


@router.get("/internal/ledger/{namespace}", response_model=LedgerView)
async def read_ledger(
    namespace: str,
    request: Request,
    _: Annotated[None, Depends(require_evaluator)],
) -> LedgerView:
    try:
        return request.app.state.ledger.ledger_view(namespace)
    except ProviderError as exc:
        raise _as_http_error(exc) from exc


# ----------------------------------------------------------------- store-facing


@router.post(
    "/internal/demo/double-charge",
    response_model=DemoDoubleChargeSetup,
)
async def prepare_double_charge_demo(
    body: DemoDoubleChargeRequest,
    request: Request,
    _: Annotated[None, Depends(require_demo_operator)],
) -> DemoDoubleChargeSetup:
    """Create a fresh immutable ledger namespace and arm the real incident.

    This is operator-only rehearsal setup.  The returned token is scoped to the
    one pre-registered operation; the live store never receives evaluator
    authority and cannot inspect or rewrite the append-only ledger.
    """
    namespace = f"demo_double_charge_{uuid.uuid4().hex}"
    ledger: LedgerStore = request.app.state.ledger
    try:
        ledger.create_namespace(namespace)
        ledger.register_operation(
            OperationRegisterRequest(
                namespace=namespace,
                operation_id=body.operation_id,
                intent_id=body.intent_id,
                amount_minor=body.amount_minor,
                currency="GBP",
                allowed_actions=["capture", "refund", "inquiry"],
            )
        )
    except ProviderError as exc:
        raise _as_http_error(exc) from exc
    request.app.state.faults.arm(namespace, "DROP_AFTER_CAPTURE_ONCE")
    expires_at = datetime.now(UTC) + timedelta(hours=2)
    claims = ProviderTokenClaims(
        incident_id=f"NW-DEMO-{uuid.uuid4().hex[:12]}",
        candidate_id="A",
        scenario_id="S01",
        namespace=namespace,
        allowed_operation_ids=[body.operation_id],
        expires_at_utc=expires_at,
    )
    try:
        token = mint_token(claims, request.app.state.settings.provider_signing_secret)
    except TokenError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return DemoDoubleChargeSetup(
        namespace=namespace,
        token=token,
        expires_at_utc=expires_at,
    )


@router.post("/capture", response_model=CaptureResponse)
async def capture(
    body: CaptureRequest,
    request: Request,
    claims: Annotated[ProviderTokenClaims, Depends(require_scoped_token)],
) -> CaptureResponse | Response:
    if not _operation_allowed(claims.allowed_operation_ids, body.operation_id):
        raise HTTPException(status_code=403, detail="operation is not permitted by this token")
    faults: FaultSchedules = request.app.state.faults
    ledger: LedgerStore = request.app.state.ledger
    # Faults fire only for fresh appends: an idempotent replay neither consumes
    # the one-shot fault nor loses a response that would have been returned.
    fresh_append = not ledger.capture_exists(claims.namespace, body.idempotency_key)
    if fresh_append and faults.consume(claims.namespace, "TIMEOUT_BEFORE_CAPTURE_ONCE"):
        # Simulated timeout; the caller must inquire, never blind-retry.
        return Response(status_code=DROPPED_RESPONSE_STATUS)
    try:
        response = ledger.capture(
            claims.namespace, body, allowed_operation_ids=claims.allowed_operation_ids
        )
    except ProviderError as exc:
        raise _as_http_error(exc) from exc
    if not response.replayed and faults.consume(claims.namespace, "DROP_AFTER_CAPTURE_ONCE"):
        # The capture is committed; the response is deliberately lost.
        return Response(status_code=DROPPED_RESPONSE_STATUS)
    return response


@router.get("/operations/{operation_id}/captures", response_model=list[CaptureRow])
async def list_captures(
    operation_id: str,
    request: Request,
    claims: Annotated[ProviderTokenClaims, Depends(require_scoped_token)],
) -> list[CaptureRow]:
    if not _operation_allowed(claims.allowed_operation_ids, operation_id):
        raise HTTPException(status_code=403, detail="operation is not permitted by this token")
    try:
        return request.app.state.ledger.captures_for(claims.namespace, operation_id)
    except ProviderError as exc:
        raise _as_http_error(exc) from exc


@router.post("/refund", response_model=RefundResponse)
async def refund(
    body: RefundRequest,
    request: Request,
    claims: Annotated[ProviderTokenClaims, Depends(require_scoped_token)],
) -> RefundResponse:
    try:
        return request.app.state.ledger.refund(
            claims.namespace, body, allowed_operation_ids=claims.allowed_operation_ids
        )
    except ProviderError as exc:
        raise _as_http_error(exc) from exc


@router.get("/health/alive")
async def health_alive() -> dict[str, str]:
    return {"status": "ok", "service": "trusted_provider"}


def create_app(
    settings: ProviderSettings | None = None,
    *,
    db_path: str | None = None,
    lifespan: Any = None,
) -> FastAPI:
    resolved = settings or ProviderSettings()
    path = db_path if db_path is not None else (resolved.provider_db_path or ":memory:")
    app = FastAPI(title="NightWatch trusted provider", version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved
    ledger = LedgerStore(path)
    app.state.ledger = ledger
    app.state.faults = FaultSchedules(ledger.connection, ledger.lock)

    @app.get("/health")
    async def health_root() -> dict[str, str]:
        return {"status": "ok", "service": "trusted_provider"}

    app.include_router(router)
    return app


app = create_app()
