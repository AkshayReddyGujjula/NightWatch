"""Modal app for the trusted services (plan §4.2, §16).

Exactly one App owns the deployment; Track B's ``modal/services_b.py`` imports
``app`` from here and binds ``run_candidate`` to the same object
(CONTRACT_CHANGE 2026-09-19, accepted). Track A is the only deployer (§17).

Persistence: each stateful service owns one Volume mounted at ``/data`` with
direct single-writer SQLite. A small lifespan task commits the volume every two
seconds and once on shutdown; a cold start reloads before SQLite opens. The
snapshot-backup path in §4.2 is deferred and no durable-HA claim is made.

Deploy:

    MODAL_ENVIRONMENT=nightwatch-demo uv run modal deploy modal/services_a.py
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI

import modal

app = modal.App("nightwatch")

PROVIDER_VOLUME = modal.Volume.from_name("nightwatch-provider-data", create_if_missing=True)
STORE_VOLUME = modal.Volume.from_name("nightwatch-live-store-data", create_if_missing=True)

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
            "PROVIDER_DB_PATH": "/data/nightwatch_provider.db",
            "STORE_DB_PATH": "/data/nightwatch_live_store.db",
        }
    )
    .add_local_python_source("apps", "services")
    .add_local_dir("fixtures", remote_path="/root/fixtures")
)


def _volume_lifespan(volume: modal.Volume) -> Any:
    """Commit the volume periodically while serving, and once on shutdown."""

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        async def commit_loop() -> None:
            while True:
                await asyncio.sleep(2.0)
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(volume.commit)

        task = asyncio.create_task(commit_loop())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(Exception):
                await asyncio.to_thread(volume.commit)

    return lifespan


@app.function(
    image=TRUSTED_IMAGE,
    secrets=[modal.Secret.from_name("nightwatch-provider")],
    volumes={"/data": PROVIDER_VOLUME},
    min_containers=1,
    max_containers=1,
    timeout=3600,
)
@modal.asgi_app()
def provider_asgi() -> FastAPI:
    from apps.trusted_provider.app import ProviderSettings, create_app

    PROVIDER_VOLUME.reload()
    return create_app(ProviderSettings(), lifespan=_volume_lifespan(PROVIDER_VOLUME))


@app.function(
    image=TRUSTED_IMAGE,
    secrets=[modal.Secret.from_name("nightwatch-live-internal")],
    volumes={"/data": STORE_VOLUME},
    min_containers=1,
    max_containers=1,
    timeout=3600,
)
@modal.concurrent(max_inputs=32)
@modal.asgi_app()
def live_store_asgi() -> FastAPI:
    from apps.live_store.app import StoreSettings, create_app

    STORE_VOLUME.reload()
    return create_app(StoreSettings(), lifespan=_volume_lifespan(STORE_VOLUME))


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
@modal.concurrent(max_inputs=64)
@modal.asgi_app()
def control_asgi() -> FastAPI:
    from apps.control_plane.app import ControlSettings, create_app

    return create_app(ControlSettings())
