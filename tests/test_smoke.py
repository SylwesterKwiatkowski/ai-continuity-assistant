"""M0 smoke tests: the app builds, config loads, and the health check responds."""

from __future__ import annotations

from fastapi.testclient import TestClient

from assistant import __version__
from assistant.api.app import create_app
from assistant.config import Settings


def test_settings_defaults() -> None:
    settings = Settings()
    assert settings.app_env in {"local", "dev", "prod"}
    assert settings.is_prod is (settings.app_env == "prod")


def test_health_endpoint() -> None:
    client = TestClient(create_app(Settings(app_env="local")))
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"status": "ok", "version": __version__, "env": "local"}
