"""Modal app for the trusted services (plan §4.2, §16).

Exactly one App owns the deployment; Track B's ``modal/services_b.py`` imports
``app`` from here and binds ``run_candidate`` to the same object
(CONTRACT_CHANGE 2026-09-19, accepted). Track A is the only deployer (§17).

Persistence (plan §4.2): SQLite runs on **local container disk**, never directly
on the Volume. After every critical transaction the service writes a closed
snapshot (SQLite backup API) plus a SHA-256 sidecar into its Volume and commits
it; a cold start reloads the Volume, verifies the sidecar and restores the
snapshot before SQLite opens. The trigger is request-driven, not a timer: Modal
only advances the user-code event loop while a function call is in flight, so a
sleeping background task would not fire between requests. ``Volume.reload``
fails while any container holds a file open on the Volume, so startup retries
with backoff and **fails closed** rather than serving stale or empty ledger
state. This is a hackathon topology, not durable HA: a restart restores
``SAFE_HOLD`` and requires operator revalidation before a new lease.

Deploy (trusted services only; ``modal_app.py`` additionally composes Track B's
``run_candidate``):

    MODAL_ENVIRONMENT=nightwatch-demo uv run modal deploy modal/services_a.py
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import os
import sqlite3
import threading
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response

import modal

logger = logging.getLogger("nightwatch.services_a")

app = modal.App("nightwatch")

PROVIDER_VOLUME = modal.Volume.from_name("nightwatch-provider-data", create_if_missing=True)
STORE_VOLUME = modal.Volume.from_name("nightwatch-live-store-data", create_if_missing=True)

VOLUME_MOUNT = "/data"
#: ``Volume.reload`` fails while another container holds a file open; retry with
#: backoff instead of crash-looping the service.
RELOAD_ATTEMPTS = 6
RELOAD_BACKOFF_SECONDS = 0.5

#: Trusted-service image. Local source is mounted, so a deploy always ships the
#: current working tree.
TRUSTED_IMAGE = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install(
        "fastapi",
        "uvicorn[standard]",
        "pydantic",
        "pydantic-settings",
        "httpx",
        "python-multipart",
    )
    .env(
        {
            "NIGHTWATCH_FIXTURES": "/root/fixtures",
            # Local container disk only (plan §4.2). The legacy on-Volume database
            # files are left in place, unmodified: the original incident namespace
            # is immutable and must never be reset or rewritten.
            "PROVIDER_DB_PATH": "/tmp/nightwatch_provider.db",
            "STORE_DB_PATH": "/tmp/nightwatch_live_store.db",
        }
    )
    .add_local_python_source("apps", "services")
    .add_local_dir("fixtures", remote_path="/root/fixtures")
)


def _atomic_write(path: Path, payload: bytes) -> None:
    """Write ``payload`` to ``path`` atomically inside the Volume mount."""
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "wb") as handle:
        handle.write(payload)
        handle.flush()
        with contextlib.suppress(OSError):
            # FUSE mounts do not always implement fsync; the atomic rename below
            # is what makes the file visible, so a missing fsync is not fatal.
            os.fsync(handle.fileno())
    os.replace(temporary, path)


class SqliteVolumeSnapshot:
    """Local-disk SQLite persisted as a closed snapshot in a Modal Volume.

    The live database file never lives on the Volume (plan §4.2): the service
    opens SQLite at :attr:`local_path` on container disk and periodically writes
    a consistent copy through the SQLite backup API, then commits the Volume.
    ``restore`` runs *before* SQLite opens and is the only place the Volume is
    read, so no open file handle ever blocks a reload.
    """

    def __init__(
        self,
        volume: modal.Volume,
        *,
        local_path: str,
        snapshot_name: str,
        volume_mount: str = VOLUME_MOUNT,
    ) -> None:
        self._volume = volume
        self.local_path = Path(local_path)
        self.snapshot_path = Path(volume_mount) / snapshot_name
        self.sidecar_path = Path(volume_mount) / f"{snapshot_name}.sha256"
        self._connection: sqlite3.Connection | None = None
        self._lock: threading.Lock | None = None
        self._last_total_changes: int | None = None

    # -- startup -------------------------------------------------------------

    def restore(self) -> None:
        """Reload the Volume, verify the sidecar and stage the snapshot locally.

        Fails closed: a reload that cannot complete, or a snapshot whose SHA-256
        does not match its sidecar, raises instead of silently starting from an
        empty database.
        """
        self.local_path.unlink(missing_ok=True)
        if not self._reload():
            raise RuntimeError(
                f"could not reload the Modal Volume for {self.snapshot_path.name}; "
                "refusing to start with unverified ledger state"
            )
        self.snapshot_path.with_name(self.snapshot_path.name + ".tmp").unlink(missing_ok=True)
        if not self.snapshot_path.exists():
            return  # first ever start: an empty database is the correct state
        payload = self.snapshot_path.read_bytes()
        expected = self.sidecar_path.read_text(encoding="utf-8").strip()
        actual = hashlib.sha256(payload).hexdigest()
        if actual != expected:
            raise RuntimeError(
                f"snapshot {self.snapshot_path.name} failed its SHA-256 check; "
                "refusing to serve unverified ledger state"
            )
        self.local_path.write_bytes(payload)

    def _reload(self) -> bool:
        for attempt in range(RELOAD_ATTEMPTS):
            try:
                self._volume.reload()
                return True
            except RuntimeError:
                if attempt == RELOAD_ATTEMPTS - 1:
                    return False
                time.sleep(RELOAD_BACKOFF_SECONDS * (2**attempt))
        return False  # pragma: no cover - the loop always returns

    def attach(self, connection: sqlite3.Connection, lock: threading.Lock) -> None:
        """Bind the open SQLite connection this snapshot mirrors."""
        self._connection = connection
        self._lock = lock
        self._last_total_changes = connection.total_changes

    # -- while serving -------------------------------------------------------

    def _backup_if_changed(self, *, force: bool) -> tuple[bytes, str] | None:
        """Closed SQLite backup staged on local disk, or None when unchanged.

        ``sqlite3.Connection.total_changes`` is the change detector, so an idle
        service never rewrites or re-commits the Volume. The staging file lives
        on container disk: only closed files are ever written into the Volume
        mount, and each lands through an atomic rename.

        Runs on the event-loop thread deliberately. The backup is cheap for a
        demo-sized database and the store lock is already held, so this keeps
        the snapshot independent of the connection's ``check_same_thread`` flag
        instead of depending on how the store happened to open SQLite.
        """
        connection = self._connection
        if connection is None or self._lock is None:
            return None
        if not force and connection.total_changes == self._last_total_changes:
            return None
        staging = self.local_path.with_name(self.local_path.name + ".snapshot-staging")
        staging.unlink(missing_ok=True)
        with self._lock:
            destination = sqlite3.connect(staging)
            try:
                connection.backup(destination)
            finally:
                destination.close()
            self._last_total_changes = connection.total_changes
        payload = staging.read_bytes()
        staging.unlink(missing_ok=True)
        return payload, hashlib.sha256(payload).hexdigest()

    async def snapshot_async(self, *, force: bool = False) -> bool:
        """Persist a closed snapshot + sidecar and commit; True when it wrote.

        Called after a request that may have mutated state (plan §4.2: "after
        every critical transaction"). This must be the *request-driven* trigger,
        not a timer: Modal's user-code event loop only advances while a function
        call is in flight, so a sleeping background task does not fire between
        requests. ``volume.commit`` is awaited through its async API so the
        network round-trip never blocks the event loop.
        """
        result = self._backup_if_changed(force=force)
        if result is None:
            return False
        payload, digest = result
        await asyncio.to_thread(_atomic_write, self.snapshot_path, payload)
        await asyncio.to_thread(_atomic_write, self.sidecar_path, (digest + "\n").encode())
        await self._volume.commit.aio()
        return True


def _install_snapshot_middleware(application: FastAPI, snapshot: SqliteVolumeSnapshot) -> None:
    """Persist after every request; the change gate makes idle requests free.

    Every request is considered because reads are not guaranteed to be pure:
    the router falls back to ``SAFE_HOLD`` on lease expiry while serving a GET.
    """

    @application.middleware("http")
    async def _persist_after_request(request: Request, call_next: Callable[..., Any]) -> Response:
        response = await call_next(request)
        try:
            await snapshot.snapshot_async()
        except Exception:
            # The transaction is already durable on local disk; a failed commit
            # must be loud and retried on the next request, never silent and
            # never a reason to drop an already-completed money operation.
            logger.exception(
                "volume snapshot failed after %s %s", request.method, request.url.path
            )
        return response


def _shutdown_lifespan(snapshot: SqliteVolumeSnapshot) -> Callable[[FastAPI], Any]:
    """Final forced snapshot on shutdown (plan §4.2)."""

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            try:
                await snapshot.snapshot_async(force=True)
            except Exception:
                logger.exception("final volume snapshot failed")

    return lifespan


@app.function(
    image=TRUSTED_IMAGE,
    secrets=[modal.Secret.from_name("nightwatch-provider")],
    volumes={VOLUME_MOUNT: PROVIDER_VOLUME},
    min_containers=1,
    max_containers=1,
    timeout=3600,
)
@modal.asgi_app()
def provider_asgi() -> FastAPI:
    from apps.trusted_provider.app import ProviderSettings, create_app

    snapshot = SqliteVolumeSnapshot(
        PROVIDER_VOLUME,
        local_path="/tmp/nightwatch_provider.db",
        snapshot_name="nightwatch_provider.snapshot.db",
    )
    snapshot.restore()
    application = create_app(
        ProviderSettings(provider_db_path=str(snapshot.local_path)),
        lifespan=_shutdown_lifespan(snapshot),
    )
    snapshot.attach(application.state.ledger.connection, application.state.ledger.lock)
    _install_snapshot_middleware(application, snapshot)
    return application


@app.function(
    image=TRUSTED_IMAGE,
    secrets=[modal.Secret.from_name("nightwatch-live-internal")],
    volumes={VOLUME_MOUNT: STORE_VOLUME},
    min_containers=1,
    max_containers=1,
    timeout=3600,
)
@modal.asgi_app()
def live_store_asgi() -> FastAPI:
    from apps.live_store.app import StoreSettings, create_app

    snapshot = SqliteVolumeSnapshot(
        STORE_VOLUME,
        local_path="/tmp/nightwatch_live_store.db",
        snapshot_name="nightwatch_live_store.snapshot.db",
    )
    snapshot.restore()
    application = create_app(
        StoreSettings(store_db_path=str(snapshot.local_path)),
        lifespan=_shutdown_lifespan(snapshot),
    )
    snapshot.attach(application.state.store.connection, application.state.store.lock)
    _install_snapshot_middleware(application, snapshot)
    return application


@app.function(
    image=TRUSTED_IMAGE,
    secrets=[
        modal.Secret.from_name("nightwatch-control"),
        modal.Secret.from_name("nightwatch-evidence-ingest"),
    ],
    min_containers=1,
    max_containers=1,
    timeout=3600,
)
@modal.asgi_app()
def control_asgi() -> FastAPI:
    from apps.control_plane.app import ControlSettings, create_app

    return create_app(ControlSettings())
