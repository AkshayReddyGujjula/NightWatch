"""Live store handler router (plan §5.0, §8.1, §8.3, §14.2).

Modes: ``BUGGY`` (pre-incident only), ``SAFE_HOLD`` (default containment),
``SAFE`` (leased repair), ``LEGACY`` (gated slice — not installed yet).

Safety properties enforced here:

- a process start opens in ``SAFE_HOLD`` (the store performs the reset);
- once a deliberate containment transition happened, ``BUGGY`` is latched
  unreachable — plan §8.1: "no transition returns to BUGGY";
- ``SAFE`` requires a lease id, an unexpired ``lease_expires_at`` and the exact
  installed SAFE handler hash; the signed-lease/evidence binding arrives with
  the lease slice;
- an expired ``SAFE`` lease falls back to ``SAFE_HOLD`` on the next state read.
"""

from __future__ import annotations

import contextlib
import hashlib
import inspect
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from apps.contracts.base import sha256_hex
from apps.contracts.payment import RouterMode, RouterState
from apps.live_store.domain.payment_retry import buggy_retry_checkout, safe_retry_checkout
from apps.live_store.store import SAFE_HOLD_HANDLER_HASH, Store, StoreError

__all__ = ["Router", "bucket_for", "handler_hash_for"]


def _source_hash(func: Callable[..., Any]) -> str:
    return sha256_hex(inspect.getsource(func).encode("utf-8"))


_HASHES: dict[str, str] = {
    "BUGGY": _source_hash(buggy_retry_checkout),
    "SAFE": _source_hash(safe_retry_checkout),
    "SAFE_HOLD": SAFE_HOLD_HANDLER_HASH,
    "LEGACY": sha256_hex(b"legacy:not-installed"),
}


def handler_hash_for(mode: RouterMode) -> str:
    return _HASHES[mode]


def safe_handler_hash() -> str:
    return _HASHES["SAFE"]


def bucket_for(bucket_seed: str, intent_id: str) -> int:
    """Stable probe bucket 0-99 for staged smoke (plan §14.2)."""
    digest = hashlib.sha256(f"{bucket_seed}:{intent_id}".encode()).hexdigest()
    return int(digest[:8], 16) % 100


class Router:
    """Mode changes with a generation CAS and a one-way BUGGY latch."""

    def __init__(self, store: Store) -> None:
        self._store = store

    def state(self) -> RouterState:
        current = self._store.router_state()
        if (
            current.mode == "SAFE"
            and current.lease_expires_at is not None
            and current.lease_expires_at <= datetime.now(UTC)
        ):
            with contextlib.suppress(StoreError):
                self._store.set_router(
                    mode="SAFE_HOLD",
                    expected_generation=current.generation,
                    handler_hash=handler_hash_for("SAFE_HOLD"),
                )
            return self._store.router_state()
        return current

    def set_mode(
        self,
        mode: RouterMode,
        *,
        expected_generation: int,
        lease_id: str | None = None,
        lease_expires_at: datetime | None = None,
        handler_sha256: str | None = None,
    ) -> RouterState:
        current = self._store.router_state()
        if mode == "LEGACY":
            raise StoreError(409, "LEGACY handler is not installed in this build")
        if mode == "BUGGY":
            if self._store.buggy_locked():
                raise StoreError(409, "BUGGY is unreachable after containment")
            if current.mode == "SAFE":
                raise StoreError(409, "BUGGY is unreachable after the repair route is active")
        if mode == "SAFE":
            if current.mode != "SAFE_HOLD":
                raise StoreError(409, "SAFE may only be activated from SAFE_HOLD")
            if not lease_id:
                raise StoreError(422, "SAFE requires a lease id")
            if lease_expires_at is None or lease_expires_at <= datetime.now(UTC):
                raise StoreError(422, "SAFE requires an unexpired lease_expires_at")
            if handler_sha256 != _HASHES["SAFE"]:
                raise StoreError(422, "handler_sha256 does not match the installed SAFE handler")
        return self._store.set_router(
            mode=mode,
            expected_generation=expected_generation,
            handler_hash=handler_hash_for(mode),
            lease_id=lease_id if mode == "SAFE" else None,
            lease_expires_at=lease_expires_at if mode == "SAFE" else None,
        )
