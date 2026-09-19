"""Live store handler router (plan §5.0, §8.3, §14.2).

Modes: ``BUGGY`` (pre-incident only), ``SAFE_HOLD`` (default containment),
``SAFE`` (leased repair), ``LEGACY`` (gated slice — not installed yet). On start
or restart the live store opens in ``SAFE_HOLD``. Generation changes are
compare-and-swap: exactly one writer wins per generation.
"""

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Callable
from datetime import datetime
from typing import Any

from apps.contracts.base import sha256_hex
from apps.contracts.payment import RouterMode, RouterState
from apps.live_store.domain.payment_retry import buggy_retry_checkout, safe_retry_checkout
from apps.live_store.store import Store, StoreError

__all__ = ["Router", "bucket_for", "handler_hash_for"]


def _source_hash(func: Callable[..., Any]) -> str:
    return sha256_hex(inspect.getsource(func).encode("utf-8"))


_HASHES: dict[str, str] = {
    "BUGGY": _source_hash(buggy_retry_checkout),
    "SAFE": _source_hash(safe_retry_checkout),
    "SAFE_HOLD": sha256_hex(b"safe_hold:no-capture"),
    "LEGACY": sha256_hex(b"legacy:not-installed"),
}


def handler_hash_for(mode: RouterMode) -> str:
    return _HASHES[mode]


def bucket_for(bucket_seed: str, intent_id: str) -> int:
    """Stable probe bucket 0-99 for staged smoke (plan §14.2)."""
    digest = hashlib.sha256(f"{bucket_seed}:{intent_id}".encode()).hexdigest()
    return int(digest[:8], 16) % 100


class Router:
    """Mode changes with a generation CAS; no transition ever re-enables the bug silently."""

    def __init__(self, store: Store) -> None:
        self._store = store

    def state(self) -> RouterState:
        return self._store.router_state()

    def set_mode(
        self,
        mode: RouterMode,
        *,
        expected_generation: int,
        lease_id: str | None = None,
        lease_expires_at: datetime | None = None,
    ) -> RouterState:
        current = self._store.router_state()
        if mode == "LEGACY":
            raise StoreError(409, "LEGACY handler is not installed in this build")
        if mode == "SAFE" and not lease_id:
            raise StoreError(422, "SAFE requires a lease id")
        if mode == "BUGGY" and current.mode == "SAFE":
            raise StoreError(409, "BUGGY is unreachable after the repair route is active")
        return self._store.set_router(
            mode=mode,
            expected_generation=expected_generation,
            handler_hash=handler_hash_for(mode),
            lease_id=lease_id if mode == "SAFE" else None,
            lease_expires_at=lease_expires_at if mode == "SAFE" else None,
        )
