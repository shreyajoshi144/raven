"""Validated application settings. Secrets are never echoed in error messages."""
from __future__ import annotations

import logging
import sys
from functools import lru_cache
from typing import Literal

from pydantic import ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

OFFICIAL_GITHUB_API = "https://api.github.com"
_DEV_SECRET_PREFIX = "dev-insecure-"


class SettingsError(RuntimeError):
    """Raised for invalid configuration. Messages never contain secret values."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    app_env: Literal["development", "test", "production"] = "development"
    app_secret_key: str = ""
    database_url: str = ""
    log_level: str = "INFO"

    # LLM provider (single provider initially: anthropic)
    llm_provider: str = "anthropic"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_base_url: str = "https://api.anthropic.com"
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2
    llm_max_output_tokens: int = 2000
    llm_max_concurrency: int = 4  # simultaneous in-flight provider calls per process
    llm_max_retry_after_seconds: float = 20.0  # a longer Retry-After is not waited out; fail fast to retrieval-only/fallback
    llm_price_input_per_mtok: float | None = None  # optional USD list prices; cost is reported only when both are set
    llm_price_output_per_mtok: float | None = None
    llm_max_tokens_per_request: int = 60000  # input+output budget for one Q&A/analysis request
    # Optional fallback model, tried when the primary fails with an availability error (provider: anthropic | openai_compat, e.g. a local vLLM/Ollama endpoint)
    llm_fallback_provider: str = ""
    llm_fallback_model: str = ""
    llm_fallback_api_key: str = ""
    llm_fallback_base_url: str = ""
    # Optional semantic retrieval: any OpenAI-compatible /v1/embeddings endpoint. Unset = lexical retrieval only.
    embeddings_base_url: str = ""
    embeddings_model: str = ""
    embeddings_api_key: str = ""

    # GitHub
    github_api_base_url: str = OFFICIAL_GITHUB_API
    github_token: str = ""  # optional; raises the unauthenticated rate limit
    github_connect_timeout: float = 5.0
    github_read_timeout: float = 20.0
    max_archive_bytes: int = 60 * 1024 * 1024  # compressed bytes streamed per analysis
    max_archive_uncompressed_bytes: int = 400 * 1024 * 1024

    # Orchestration
    n8n_base_url: str = ""
    n8n_encryption_key: str = ""  # consumed by the n8n container; validated here for prod
    n8n_webhook_secret: str = ""  # app -> n8n
    internal_service_secret: str = ""  # n8n -> app
    n8n_trigger_timeout_seconds: float = 10.0
    qa_workflow_timeout_seconds: float = 120.0
    trigger_max_attempts: int = 5

    # Resource limits (spec section 7 defaults)
    max_repository_files: int = 2000
    max_source_file_bytes: int = 1024 * 1024
    max_total_source_bytes: int = 20 * 1024 * 1024
    max_python_files: int = 1000
    max_web_files: int = 300
    max_web_file_bytes: int = 256 * 1024
    max_web_total_bytes: int = 5 * 1024 * 1024
    max_llm_lines_per_request: int = 1200
    max_llm_calls_per_analysis: int = 80
    max_analysis_seconds: int = 600
    max_docs_seconds: int = 600
    impact_per_hour: int = 10
    max_concurrent_analyses: int = 2

    # Retry policy
    max_stage_attempts: int = 3
    retry_base_seconds: float = 5.0
    retry_max_seconds: float = 120.0

    # Auth / sessions / rate limits
    web_dist_dir: str | None = None  # built React app (web/dist); when set, it is served at / and the legacy UI moves to /legacy
    allow_registration: bool = True
    require_email_verification: bool = False  # recommended for public sign-ups; needs SMTP_HOST in production
    app_base_url: str = "http://localhost:8000"  # used in emailed links
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "Raven <no-reply@localhost>"
    smtp_starttls: bool = True
    email_token_ttl_minutes: int = 60
    session_ttl_hours: int = 24
    cookie_secure: bool | None = None  # default: True in production
    login_max_attempts: int = 10
    login_window_seconds: int = 900
    analyses_per_hour: int = 20
    chat_per_minute: int = 20
    max_request_bytes: int = 64 * 1024
    answer_cache_enabled: bool = True
    answer_cache_ttl_hours: int = 24 * 14  # entries are exact for their commit; the TTL only bounds table growth
    # Per-user daily quotas (UTC day) and per-endpoint rate limits; a per-user override on the users row wins
    daily_analyses: int = 30
    daily_questions: int = 100
    daily_llm_tokens: int = 300_000
    daily_spend_usd: float | None = None  # also enforced when set and both LLM prices are configured
    rl_read_per_minute: int = 240   # GET endpoints, per user and route
    rl_write_per_minute: int = 30   # POST/PUT/PATCH/DELETE endpoints, per user and route

    # Database pool
    db_pool_size: int = 5
    db_max_overflow: int = 5

    # Worker / static frontend
    worker_poll_seconds: float = 1.0
    worker_lease_seconds: int = 60
    worker_shutdown_grace_seconds: int = 30
    frontend_dir: str = ""

    # Testing hook: allow non-official GitHub host outside production only
    allow_custom_upstreams: bool = False

    @field_validator("llm_price_input_per_mtok", "llm_price_output_per_mtok", mode="before")
    @classmethod
    def _blank_price_is_unset(cls, v):  # Compose passes unset variables as ""
        return None if isinstance(v, str) and not v.strip() else v

    @model_validator(mode="after")
    def _validate(self) -> "Settings":
        prod = self.app_env == "production"
        problems: list[str] = []

        if not self.database_url:
            problems.append("DATABASE_URL is required")
        elif self.database_url.startswith("postgresql://"):
            self.database_url = self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        elif self.database_url.startswith("postgres://"):
            self.database_url = self.database_url.replace("postgres://", "postgresql+psycopg://", 1)

        if not prod:
            # Development/test fallbacks are explicit, prefixed, and rejected in production.
            if not self.app_secret_key:
                self.app_secret_key = _DEV_SECRET_PREFIX + "app-secret-key-0000000000000000"
            if not self.internal_service_secret:
                self.internal_service_secret = _DEV_SECRET_PREFIX + "internal-service-secret-00000"
            if not self.n8n_webhook_secret:
                self.n8n_webhook_secret = _DEV_SECRET_PREFIX + "n8n-webhook-secret-00000000"
            if not self.n8n_base_url:
                self.n8n_base_url = "http://localhost:5678"
        else:
            secrets = {
                "APP_SECRET_KEY": self.app_secret_key,
                "INTERNAL_SERVICE_SECRET": self.internal_service_secret,
                "N8N_WEBHOOK_SECRET": self.n8n_webhook_secret,
                "N8N_ENCRYPTION_KEY": self.n8n_encryption_key,
            }
            for name, value in secrets.items():
                if not value:
                    problems.append(f"{name} is required in production")
                elif len(value) < 32:
                    problems.append(f"{name} must be at least 32 characters in production")
                elif value.startswith(_DEV_SECRET_PREFIX) or "change-me" in value.lower() or "changeme" in value.lower():
                    problems.append(f"{name} must not be a development/placeholder value in production")
            non_empty = [v for v in secrets.values() if v]
            if len(set(non_empty)) != len(non_empty):
                problems.append("APP_SECRET_KEY, INTERNAL_SERVICE_SECRET, N8N_WEBHOOK_SECRET and N8N_ENCRYPTION_KEY must all differ")
            if not self.n8n_base_url:
                problems.append("N8N_BASE_URL is required in production")
            if self.require_email_verification and not self.smtp_host:
                problems.append("SMTP_HOST is required in production when REQUIRE_EMAIL_VERIFICATION is true")
            if self.cookie_secure is False:
                problems.append("COOKIE_SECURE cannot be false in production")
            if self.allow_custom_upstreams:
                problems.append("ALLOW_CUSTOM_UPSTREAMS cannot be enabled in production")

        if self.github_api_base_url.rstrip("/") != OFFICIAL_GITHUB_API and not (
            not prod and self.allow_custom_upstreams
        ):
            problems.append("GITHUB_API_BASE_URL must be the official GitHub API")
        self.github_api_base_url = self.github_api_base_url.rstrip("/")

        if self.llm_provider not in {"anthropic", "openai_compat"}:
            problems.append("LLM_PROVIDER must be one of: anthropic, openai_compat")
        if self.max_concurrent_analyses < 1:
            problems.append("MAX_CONCURRENT_ANALYSES must be >= 1")
        if self.max_stage_attempts < 1:
            problems.append("MAX_STAGE_ATTEMPTS must be >= 1")

        if problems:
            raise SettingsError("Invalid configuration: " + "; ".join(problems))

        if self.cookie_secure is None:
            self.cookie_secure = prod
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key and self.llm_model)

    @property
    def llm_fallback_configured(self) -> bool:
        return bool(self.llm_fallback_model and (self.llm_fallback_api_key or self.llm_fallback_base_url))

    @property
    def embeddings_configured(self) -> bool:
        return bool(self.embeddings_base_url and self.embeddings_model)

    def uses_dev_secrets(self) -> bool:
        return any(
            v.startswith(_DEV_SECRET_PREFIX)
            for v in (self.app_secret_key, self.internal_service_secret, self.n8n_webhook_secret)
        )


def _load() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]
    except ValidationError as exc:  # pydantic type errors, e.g. non-numeric limits
        fields = ", ".join(str(e["loc"][0]).upper() for e in exc.errors() if e.get("loc"))
        raise SettingsError(f"Invalid configuration values for: {fields}") from None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return _load()


def reset_settings_cache() -> None:
    get_settings.cache_clear()


def load_settings_or_exit() -> Settings:
    """Entry-point helper: print a safe message and exit non-zero on bad config."""
    try:
        return get_settings()
    except SettingsError as exc:
        print(f"raven: {exc}", file=sys.stderr)
        logging.getLogger("raven").error("configuration_error")
        raise SystemExit(2) from None
