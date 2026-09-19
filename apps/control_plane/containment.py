"""Trusted live-store containment client."""

from __future__ import annotations

from typing import Protocol

import httpx

from apps.contracts.payment import RouterState


class ContainmentControl(Protocol):
    async def ensure_safe_hold(self) -> RouterState: ...


class HttpContainmentControl:
    def __init__(self, base_url: str, token: str, *, timeout_seconds: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds

    async def ensure_safe_hold(self) -> RouterState:
        if not self.base_url or not self.token:
            raise RuntimeError("live-store containment endpoint is not configured")
        headers = {"Authorization": f"Bearer {self.token}"}
        async with httpx.AsyncClient(
            base_url=self.base_url, headers=headers, timeout=self.timeout_seconds
        ) as client:
            before_response = await client.get("/internal/router")
            before_response.raise_for_status()
            before = RouterState.model_validate_json(before_response.content, strict=True)
            if before.mode != "SAFE_HOLD":
                write_response = await client.put(
                    "/internal/router",
                    json={"mode": "SAFE_HOLD", "expected_generation": before.generation},
                )
                write_response.raise_for_status()

            # The independent readback is mandatory; a successful PUT body is
            # not accepted as containment evidence.
            readback_response = await client.get("/internal/router")
            readback_response.raise_for_status()
            readback = RouterState.model_validate_json(readback_response.content, strict=True)
            if readback.mode != "SAFE_HOLD":
                raise RuntimeError(f"SAFE_HOLD readback failed: observed {readback.mode}")
            return readback
