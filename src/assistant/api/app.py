"""FastAPI application factory.

All layer wiring lives in bootstrap.py; this module is intentionally thin.
"""

from __future__ import annotations

from fastapi import FastAPI

from assistant import __version__
from assistant.bootstrap import build_app_services
from assistant.config import Settings, get_settings
from assistant.web.routes import router as web_router


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app. Accepts optional settings for testability (DI)."""
    settings = settings or get_settings()

    app = FastAPI(
        title="AI Business Continuity Assistant",
        version=__version__,
    )
    app.state.settings = settings
    services = build_app_services(settings)
    app.state.services = services
    app.state.orchestrator = services.orchestrator  # keep alias for existing tests

    app.include_router(web_router)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "env": settings.app_env}

    return app


# Module-level app for `uvicorn assistant.api.app:app`
app = create_app()
