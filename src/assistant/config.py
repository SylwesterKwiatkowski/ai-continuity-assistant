"""Application configuration.

All secrets and environment-specific values come from the environment (or a `.env`
file locally) — never hardcoded. See `.env.example` for the authoritative list.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo layout: src/assistant/config.py -> parents[2] is the project root.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SEEDS_DIR = PROJECT_ROOT / "seeds"


class Settings(BaseSettings):
    """Typed application settings, loaded from environment / `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Environment
    app_env: Literal["local", "dev", "prod"] = "local"

    # Storage (MVP: SQLite path; swappable to a Postgres URL later)
    database_url: str = "sqlite:///./assistant.sqlite"

    # Per-user token store (encryption key). Stub/no-op in MVP; must be set in prod.
    token_store_key: str = "dev-only-not-secret"

    # Auth mode: "dev" enables the demo user picker; "oauth" shows OAuth placeholder.
    # SESSION_SECRET must be a real secret in prod.
    auth_mode: Literal["dev", "oauth"] = "dev"
    session_secret: str = "dev-only-session-secret"
    session_ttl_hours: int = 8

    # Summarizer (LLM). Unused while the deterministic stub is active.
    llm_api_key: str = ""
    llm_model: str = "claude-opus-4-8"

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (safe to call from anywhere / as a FastAPI dep)."""
    return Settings()
