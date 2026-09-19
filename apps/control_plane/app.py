"""Control-plane ASGI factory.

Current slice (plan §32.3): the internal frame-ingest and browser-barrier HTTP
contract. The trusted store implementation arrives with Track B's
``services/frames/**``; the control-plane run/state slices extend this app.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, Response

from apps.control_plane.config import ControlSettings
from apps.control_plane.containment import ContainmentControl, HttpContainmentControl
from apps.control_plane.public_routes import router as public_router
from apps.control_plane.routes import DEFAULT_BARRIER_TIMEOUT_SECONDS, ReferenceSink, router
from services.control_store import ControlStore


def create_app(
    settings: ControlSettings | None = None,
    *,
    barrier_timeout_seconds: float = DEFAULT_BARRIER_TIMEOUT_SECONDS,
    db_path: str | None = None,
    containment: ContainmentControl | None = None,
    lifespan: Any = None,
) -> FastAPI:
    resolved = settings or ControlSettings()
    app = FastAPI(title="NightWatch control plane", version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved
    app.state.frames = ReferenceSink(timeout_seconds=barrier_timeout_seconds)
    path = db_path if db_path is not None else (resolved.control_db_path or ":memory:")
    app.state.control_store = ControlStore(path)
    app.state.containment = containment or HttpContainmentControl(
        resolved.live_store_base_url,
        resolved.live_internal_token,
    )

    @app.middleware("http")
    async def no_store_api(request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "control_plane",
            "environment": resolved.modal_environment,
        }

    app.include_router(router)
    app.include_router(public_router)
    return app


app = create_app()
