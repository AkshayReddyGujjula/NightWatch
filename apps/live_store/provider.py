"""HTTP client for the trusted provider, used from inside a live/candidate world.

The store's only credential is its scoped provider token; transport failures,
timeouts and the deliberate ``504`` dropped-response faults all surface as
:class:`ProviderUncertain` so handlers can implement inquiry-first recovery.
"""

from __future__ import annotations

import json

import httpx

from apps.contracts.payment import CaptureResponse, CaptureRow, RefundResponse
from apps.live_store.domain.payment_retry import ProviderRejected, ProviderUncertain

__all__ = ["HttpPaymentProvider", "UnavailableProvider"]


class HttpPaymentProvider:
    """Small typed wrapper over the provider's store-facing endpoints."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 5.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._client = client
        self._timeout = timeout

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def _request(
        self, method: str, path: str, *, json: dict[str, object] | None = None
    ) -> httpx.Response:
        client = self._get_client()
        try:
            response = await client.request(
                method,
                f"{self._base_url}{path}",
                json=json,
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise ProviderUncertain(f"provider transport error: {exc}") from exc
        if response.status_code >= 500:
            raise ProviderUncertain(f"provider returned {response.status_code}")
        if response.status_code >= 400:
            body = response.text[:200]
            raise ProviderRejected(f"provider rejected the call ({response.status_code}): {body}")
        return response

    async def prepare_double_charge_demo(
        self,
        *,
        live_internal_token: str,
        operation_id: str,
        intent_id: str,
        amount_minor: int,
    ) -> dict[str, object]:
        """Ask the trusted provider to freeze and arm one demo operation."""
        client = self._get_client()
        try:
            response = await client.post(
                f"{self._base_url}/internal/demo/double-charge",
                json={
                    "operation_id": operation_id,
                    "intent_id": intent_id,
                    "amount_minor": amount_minor,
                    "currency": "GBP",
                },
                headers={"Authorization": f"Bearer {live_internal_token}"},
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise ProviderUncertain(f"provider demo setup transport error: {exc}") from exc
        if response.status_code >= 500:
            raise ProviderUncertain(f"provider demo setup returned {response.status_code}")
        if response.status_code >= 400:
            raise ProviderRejected(
                f"provider demo setup rejected ({response.status_code}): {response.text[:200]}"
            )
        payload: dict[str, object] = response.json()
        token = payload.get("token")
        if not isinstance(token, str) or not token:
            raise ProviderUncertain("provider demo setup omitted its scoped token")
        self._token = token
        return payload

    async def capture(
        self,
        operation_id: str,
        idempotency_key: str,
        amount_minor: int,
        currency: str,
        intent_id: str,
    ) -> CaptureResponse:
        response = await self._request(
            "POST",
            "/capture",
            json={
                "operation_id": operation_id,
                "idempotency_key": idempotency_key,
                "amount_minor": amount_minor,
                "currency": currency,
                "intent_id": intent_id,
            },
        )
        return CaptureResponse.model_validate_json(response.text)

    async def captures(self, operation_id: str) -> list[CaptureRow]:
        response = await self._request("GET", f"/operations/{operation_id}/captures")
        return [
            CaptureRow.model_validate_json(json.dumps(row)) for row in response.json()
        ]

    async def refund(
        self, operation_id: str, refund_intent_id: str, amount_minor: int
    ) -> RefundResponse:
        response = await self._request(
            "POST",
            "/refund",
            json={
                "operation_id": operation_id,
                "refund_intent_id": refund_intent_id,
                "amount_minor": amount_minor,
            },
        )
        return RefundResponse.model_validate_json(response.text)


class UnavailableProvider:
    """Fail-safe stand-in when no provider credentials are configured."""

    async def capture(
        self,
        operation_id: str,
        idempotency_key: str,
        amount_minor: int,
        currency: str,
        intent_id: str,
    ) -> CaptureResponse:
        raise ProviderUncertain("provider is not configured")

    async def captures(self, operation_id: str) -> list[CaptureRow]:
        raise ProviderUncertain("provider is not configured")

    async def refund(
        self, operation_id: str, refund_intent_id: str, amount_minor: int
    ) -> RefundResponse:
        raise ProviderUncertain("provider is not configured")
