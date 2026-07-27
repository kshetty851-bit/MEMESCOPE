"""Application configuration.

All settings are loaded from environment variables (or a local `.env` file) and
validated at import time. Fail fast: a misconfigured process should never boot.
"""

from __future__ import annotations

import json
import secrets
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import (
    AnyHttpUrl,
    Field,
    PostgresDsn,
    RedisDsn,
    SecretStr,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# `NoDecode` stops pydantic-settings from JSON-parsing these before validation,
# so `CORS_ORIGINS=http://a,http://b` works as well as a JSON array would.
CsvList = Annotated[list[str], NoDecode]

Environment = Literal["local", "test", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---------------------------------------------------------
    PROJECT_NAME: str = "MemeScope AI"
    VERSION: str = "0.1.0"
    ENVIRONMENT: Environment = "local"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # --- Security ------------------------------------------------------------
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_urlsafe(48))
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    JWT_ALGORITHM: str = "HS256"
    PASSWORD_MIN_LENGTH: int = 12

    # Cookie used to carry the refresh token.
    REFRESH_COOKIE_NAME: str = "memescope_refresh"
    REFRESH_COOKIE_PATH: str = "/api/v1/auth"
    REFRESH_COOKIE_DOMAIN: str | None = None
    REFRESH_COOKIE_SECURE: bool = True
    REFRESH_COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"

    # --- CORS ----------------------------------------------------------------
    CORS_ORIGINS: CsvList = Field(default_factory=lambda: ["http://localhost:3000"])
    ALLOWED_HOSTS: CsvList = Field(default_factory=lambda: ["*"])

    # --- Database ------------------------------------------------------------
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "memescope"
    POSTGRES_PASSWORD: str = "memescope"
    POSTGRES_DB: str = "memescope"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE_SECONDS: int = 1800
    DB_ECHO: bool = False

    # --- Redis ---------------------------------------------------------------
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None

    # --- Rate limiting -------------------------------------------------------
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS: int = 120
    RATE_LIMIT_WINDOW_SECONDS: int = 60

    # --- Observability -------------------------------------------------------
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    LOG_FORMAT: Literal["json", "console"] = "json"
    SENTRY_DSN: AnyHttpUrl | None = None

    # --- Frontend ------------------------------------------------------------
    FRONTEND_URL: str = "http://localhost:3000"

    # --- Solana / Helius -----------------------------------------------------
    # Never hardcoded: SecretStr keeps the key out of logs and repr output.
    HELIUS_API_KEY: SecretStr = SecretStr("")
    HELIUS_RPC_BASE: str = "https://mainnet.helius-rpc.com"
    HELIUS_WS_BASE: str = "wss://mainnet.helius-rpc.com"
    HELIUS_HTTP_TIMEOUT_SECONDS: float = 20.0

    # --- Token discovery scanner --------------------------------------------
    # Programs whose logs are watched for token-creation instructions. pump.fun
    # is where the overwhelming majority of Solana meme coins launch; adding a
    # launchpad is a config change, not a code change.
    SCANNER_WATCH_PROGRAMS: CsvList = Field(
        default_factory=lambda: ["6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"]
    )
    SCANNER_COMMITMENT: Literal["processed", "confirmed", "finalized"] = "confirmed"
    # Bounded queue: under a launch burst we shed load rather than exhaust memory.
    SCANNER_QUEUE_SIZE: int = 2000
    SCANNER_WORKER_CONCURRENCY: int = 4
    # Reconnect/retry backoff (seconds), exponential with full jitter.
    SCANNER_BACKOFF_INITIAL_SECONDS: float = 1.0
    SCANNER_BACKOFF_MAX_SECONDS: float = 60.0
    SCANNER_BACKOFF_MULTIPLIER: float = 2.0
    # A confirmed transaction is not instantly queryable, nor instantly indexed
    # by DAS; both are retried rather than dropped.
    SCANNER_TX_FETCH_ATTEMPTS: int = 6
    SCANNER_METADATA_ATTEMPTS: int = 5
    SCANNER_WS_PING_INTERVAL_SECONDS: float = 20.0
    # TTL of the Redis dedupe key that suppresses repeated events for a mint.
    SCANNER_DEDUPE_TTL_SECONDS: int = 3600
    # Redis channel the scanner publishes to and the API fans out from.
    TOKEN_EVENT_CHANNEL: str = "memescope:tokens:discovered"

    # --- Feature flags -------------------------------------------------------
    FEATURE_SCANNER_ENABLED: bool = False
    FEATURE_AI_SCORING_ENABLED: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def HELIUS_RPC_URL(self) -> str:
        return f"{self.HELIUS_RPC_BASE}/?api-key={self.HELIUS_API_KEY.get_secret_value()}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def HELIUS_WS_URL(self) -> str:
        return f"{self.HELIUS_WS_BASE}/?api-key={self.HELIUS_API_KEY.get_secret_value()}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def helius_configured(self) -> bool:
        return bool(self.HELIUS_API_KEY.get_secret_value())

    @field_validator("CORS_ORIGINS", "ALLOWED_HOSTS", "SCANNER_WATCH_PROGRAMS", mode="before")
    @classmethod
    def _split_csv(cls, value: Any) -> Any:
        """Accept a comma-separated string or a JSON array."""
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                return json.loads(text)
            return [item.strip() for item in text.split(",") if item.strip()]
        return value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def DATABASE_URI(self) -> str:
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD,
                host=self.POSTGRES_HOST,
                port=self.POSTGRES_PORT,
                path=self.POSTGRES_DB,
            )
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SYNC_DATABASE_URI(self) -> str:
        """Sync DSN — used by Alembic and by tooling that cannot await."""
        return self.DATABASE_URI.replace("postgresql+asyncpg", "postgresql+psycopg")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def REDIS_URI(self) -> str:
        return str(
            RedisDsn.build(
                scheme="redis",
                host=self.REDIS_HOST,
                port=self.REDIS_PORT,
                password=self.REDIS_PASSWORD,
                path=str(self.REDIS_DB),
            )
        )

    @model_validator(mode="after")
    def _enforce_production_hardening(self) -> Settings:
        if self.ENVIRONMENT == "production":
            if self.DEBUG:
                raise ValueError("DEBUG must be disabled in production")
            if len(self.SECRET_KEY) < 32:
                raise ValueError("SECRET_KEY must be at least 32 characters in production")
            if "*" in self.ALLOWED_HOSTS:
                raise ValueError("ALLOWED_HOSTS must be explicit in production")
            if not self.REFRESH_COOKIE_SECURE:
                raise ValueError("REFRESH_COOKIE_SECURE must be true in production")
        if self.FEATURE_SCANNER_ENABLED and not self.HELIUS_API_KEY.get_secret_value():
            raise ValueError("HELIUS_API_KEY is required when FEATURE_SCANNER_ENABLED is true")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor so settings are parsed exactly once per process."""
    return Settings()


settings = get_settings()
