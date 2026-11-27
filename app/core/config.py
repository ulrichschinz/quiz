"""app.core.config — central configuration (pydantic-settings).

Single home for every environment variable. Field name (case-insensitively)
== the env var name. `get_settings()` returns a *fresh* instance on each call
(deliberately not cached) so tests can `monkeypatch.setenv` per test and the
process re-reads `os.environ` — these are cold paths (startup, submit), so the
re-instantiation cost is irrelevant.

`.env` loading is NOT configured here: `app/main.py` calls `load_dotenv()`
before any `Settings()` is constructed.

Security-relevant fields fail closed (SEC-001 / SEC-007):

* a missing, short or placeholder `SECRET_KEY` raises a `ValidationError` at
  construction — `app/main.py` constructs Settings at import time, so the
  process refuses to start (a forgeable session cookie is never acceptable);
* a too-short / placeholder `ADMIN_PASSWORD` fails closed for the *admin area
  only*: it is logged as an error and treated as unset, so the admin login is
  disabled while the public quiz, landing and result pages keep serving. A weak
  admin password must not take the lead funnel offline.

`hide_input_in_errors` keeps the secret values out of error text / logs.
"""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.logging import get_logger

log = get_logger("core.config")
# get_settings() runs per request: report a rejected ADMIN_PASSWORD only once.
_weak_admin_password_reported = False

SECRET_KEY_MIN_LENGTH = 32
ADMIN_PASSWORD_MIN_LENGTH = 12
_SECRET_KEY_HINT = 'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(48))"'
# Publicly known values (old code default, .env.example placeholder). Anything
# starting with "change-me" is rejected as well.
KNOWN_PLACEHOLDER_SECRETS = frozenset(
    {
        "dev-secret-change-me",
        "change-me-generate-a-random-64-char-hex",
    }
)


class Settings(BaseSettings):
    """Process configuration, sourced from the environment."""

    model_config = SettingsConfigDict(
        case_sensitive=False, extra="ignore", hide_input_in_errors=True
    )

    # --- Core ---
    database_url: str = "sqlite:///./quiz.db"
    # Session-cookie signing key. No usable default: must be set (see validator).
    secret_key: str = Field(default="", validate_default=True)
    app_host: str = ""
    # FastAPI /docs, /redoc, /openapi.json — off unless explicitly enabled (local dev).
    enable_api_docs: bool = False
    # Strict-Transport-Security max-age (seconds), sent only on https requests
    # (directly or X-Forwarded-Proto: https). 0 disables the header (SEC-014).
    hsts_max_age: int = Field(default=365 * 24 * 60 * 60, ge=0)

    # --- Admin (single-password admin area) ---
    # Unset/empty => admin login disabled. If set: >= ADMIN_PASSWORD_MIN_LENGTH chars,
    # otherwise it is treated as unset (login disabled, error logged).
    admin_password: str | None = None
    # Session cookie: Secure flag (disable only for plain-http local dev/tests)
    # and lifetime in seconds (also enforced server-side per login).
    session_https_only: bool = True
    session_max_age: int = Field(default=8 * 60 * 60, ge=60)
    # Login brute-force throttle: per client IP, sliding window.
    login_max_failures: int = Field(default=10, ge=1)
    login_window_seconds: int = Field(default=15 * 60, ge=1)

    # --- Public submit API abuse limits (SEC-003) ---
    # Per client IP, sliding windows; exceeding either => HTTP 429. 0 disables.
    submit_max_per_minute: int = Field(default=10, ge=0)
    submit_max_per_hour: int = Field(default=50, ge=0)
    # Same email + quiz again within this many seconds => result is stored and
    # shown, but CRM/email are NOT triggered again. 0 disables.
    submit_dedup_window_seconds: int = Field(default=600, ge=0)
    # Max request body for /api/* (bytes) => HTTP 413 above it.
    api_max_body_bytes: int = Field(default=64 * 1024, ge=1024)

    # --- Lead pipeline: vibe CRM push (empty url => leg skipped) ---
    crm_ingest_url: str = ""
    crm_api_key: str = ""

    # --- Score levels: traffic-light thresholds (applied to any 0–100 score) ---
    # score < mid => "low" (red), < high => "mid" (orange), else "high" (green).
    score_threshold_mid: int = 40
    score_threshold_high: int = 70

    # --- Lead pipeline: SMTP email (empty host => leg skipped) ---
    smtp_host: str = ""
    # 465 => implicit TLS (SMTPS); otherwise SMTP + STARTTLS (if SMTP_STARTTLS).
    # Both verify the relay's certificate + hostname against the system CAs.
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True

    @field_validator("secret_key")
    @classmethod
    def _secret_key_strong(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError(f"SECRET_KEY is not set. {_SECRET_KEY_HINT}")
        if v in KNOWN_PLACEHOLDER_SECRETS or v.lower().startswith("change-me"):
            raise ValueError(f"SECRET_KEY is a known placeholder value. {_SECRET_KEY_HINT}")
        if len(v) < SECRET_KEY_MIN_LENGTH:
            raise ValueError(
                f"SECRET_KEY is too short (minimum {SECRET_KEY_MIN_LENGTH} characters). "
                f"{_SECRET_KEY_HINT}"
            )
        return v

    @field_validator("admin_password")
    @classmethod
    def _admin_password_strong(cls, v: str | None) -> str | None:
        global _weak_admin_password_reported
        if not v:
            return v  # unset/empty => admin login disabled (fail-closed)
        if len(v) < ADMIN_PASSWORD_MIN_LENGTH or v.lower().startswith("change-me"):
            if not _weak_admin_password_reported:
                _weak_admin_password_reported = True
                log.error(
                    "ADMIN_PASSWORD rejected: it must be at least %d characters and not a "
                    "placeholder. The admin login is DISABLED until it is fixed.",
                    ADMIN_PASSWORD_MIN_LENGTH,
                )
            return None  # fail closed for the admin area only
        return v


def get_settings() -> Settings:
    """Return a fresh Settings instance (NOT cached — see module docstring)."""
    return Settings()
