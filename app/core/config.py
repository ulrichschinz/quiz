"""app.core.config — central configuration (pydantic-settings).

Single home for every environment variable. Field name (case-insensitively)
== the env var name. `get_settings()` returns a *fresh* instance on each call
(deliberately not cached) so tests can `monkeypatch.setenv` per test and the
process re-reads `os.environ` — these are cold paths (startup, submit), so the
re-instantiation cost is irrelevant.

`.env` loading is NOT configured here: `app/main.py` calls `load_dotenv()`
before any `Settings()` is constructed.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process configuration, sourced from the environment."""

    model_config = SettingsConfigDict(case_sensitive=False, extra="ignore")

    # --- Core ---
    database_url: str = "sqlite:///./quiz.db"
    secret_key: str = "dev-secret-change-me"
    app_host: str = ""

    # --- Admin (single-password admin area) ---
    admin_password: str | None = None

    # --- Lead pipeline: vibe CRM push (empty url => leg skipped) ---
    crm_ingest_url: str = ""
    crm_api_key: str = ""

    # --- Lead pipeline: SMTP email (empty host => leg skipped) ---
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True


def get_settings() -> Settings:
    """Return a fresh Settings instance (NOT cached — see module docstring)."""
    return Settings()
