"""FastAPI application factory.

M0 provides only a health check and app wiring. Query/action/connections/admin routes
and the web app (Jinja2 + HTMX) arrive in later milestones — all as thin clients over
the Permission Engine, never bypassing it.
"""

from __future__ import annotations

from fastapi import FastAPI

from assistant import __version__
from assistant.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI app. Accepts optional settings for testability (DI)."""
    settings = settings or get_settings()

    app = FastAPI(
        title="AI Business Continuity Assistant",
        version=__version__,
    )
    app.state.settings = settings

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "env": settings.app_env}

    return app


# Module-level app for `uvicorn assistant.api.app:app`
app = create_app()
