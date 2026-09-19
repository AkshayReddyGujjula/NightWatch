"""Control-plane ASGI factory.

Current slice (plan §32.3): the internal frame-ingest and browser-barrier HTTP
contract. The trusted store implementation arrives with Track B's
``services/frames/**``; the control-plane run/state slices extend this app.
"""

from __future__ import annotations

from fastapi import FastAPI

from apps.control_plane.config import ControlSettings
from apps.control_plane.routes import DEFAULT_BARRIER_TIMEOUT_SECONDS, ReferenceSink, router


def create_app(
    settings: ControlSettings | None = None,
    *,
    barrier_timeout_seconds: float = DEFAULT_BARRIER_TIMEOUT_SECONDS,
) -> FastAPI:
    resolved = settings or ControlSettings()
    app = FastAPI(title="NightWatch control plane", version="0.1.0")
    app.state.settings = resolved
    app.state.frames = ReferenceSink(timeout_seconds=barrier_timeout_seconds)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "control_plane",
            "environment": resolved.modal_environment,
        }

    app.include_router(router)
    return app


app = create_app()
