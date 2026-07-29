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
    # ⚠️ PROJECT_NAME is the JWT `iss` claim (core/security.py) and is validated
    # on every token decode. Renaming it — including to match the MEMESCOPE
    # branding used everywhere else — invalidates every issued token and signs
    # every user out. Change it only with a deliberate session-invalidation plan.
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

    # --- Reverse proxy -------------------------------------------------------
    # Peers whose `X-Forwarded-For` may be believed.
    #
    # Behind a proxy every request arrives from the proxy, so `request.client`
    # is the proxy for all of them. Left uncorrected the rate limiter keys every
    # user into a single bucket - which makes the limit both useless (one shared
    # allowance) and a self-inflicted denial of service (one abusive client
    # exhausts everyone's). Access logs lose the client address too.
    #
    # The header is only honoured when the immediate peer is listed here.
    # Trusting it unconditionally is worse than not trusting it at all: any
    # client could then set the header and pick its own rate-limit bucket.
    # Empty means "no proxy", which is correct for local development.
    TRUSTED_PROXY_IPS: CsvList = Field(default_factory=list)

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
    # Error reporting is off unless a DSN is supplied, so development never
    # ships noise to a shared project and CI never needs a secret to run.
    SENTRY_DSN: AnyHttpUrl | None = None
    # Fraction of requests traced. Full tracing on a service that evaluates
    # thousands of tokens an hour is expensive and tells you nothing the
    # sampled view does not; errors are always captured regardless.
    SENTRY_TRACES_SAMPLE_RATE: float = Field(default=0.1, ge=0.0, le=1.0)
    # Identifies the running build in Sentry so a regression can be tied to a
    # deploy. Set by `deploy.sh` from the git SHA.
    BUILD_SHA: str = "unknown"

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

    # --- Market data provider ------------------------------------------------
    # Which implementation of MarketDataProvider to construct. Swapping this is
    # the only change needed to move to a different vendor.
    MARKET_PROVIDER: str = "dexscreener"
    MARKET_PROVIDER_BASE_URL: str = "https://api.dexscreener.com"
    MARKET_PROVIDER_API_KEY: SecretStr = SecretStr("")
    MARKET_PROVIDER_TIMEOUT_SECONDS: float = 10.0
    # DexScreener accepts up to 30 addresses per request; batching is what makes
    # enriching thousands of tokens affordable inside the rate limit.
    MARKET_PROVIDER_BATCH_SIZE: int = 30
    MARKET_PROVIDER_MAX_ATTEMPTS: int = 3

    # --- Secondary provider (liquidity fill) ---------------------------------
    # Only consulted by MARKET_PROVIDER="composite", and only for rows the
    # primary returned with a pool but no liquidity — the pump.fun
    # bonding-curve gap that caps ~90% of the feed at 45% coverage. See
    # services/market/providers/geckoterminal.py for why this is keyed by pool
    # address and not by mint.
    MARKET_SECONDARY_BASE_URL: str = "https://api.geckoterminal.com/api/v2"
    MARKET_SECONDARY_NETWORK: str = "solana"
    MARKET_SECONDARY_TIMEOUT_SECONDS: float = 10.0
    # GeckoTerminal accepts up to 30 pool addresses per `pools/multi` call.
    MARKET_SECONDARY_BATCH_SIZE: int = 30
    MARKET_SECONDARY_MAX_ATTEMPTS: int = 2
    # The free tier allows ~30 calls/min. Held below it deliberately: exceeding
    # it trips the circuit breaker, which costs more coverage than the extra
    # calls buy. Raise this only alongside a paid plan.
    MARKET_SECONDARY_CALLS_PER_MINUTE: int = 25

    # --- Circuit breaker -----------------------------------------------------
    MARKET_BREAKER_FAILURE_THRESHOLD: int = 5
    MARKET_BREAKER_RESET_SECONDS: float = 60.0
    MARKET_BREAKER_HALF_OPEN_SUCCESSES: int = 2

    # --- Enrichment worker ---------------------------------------------------
    ENRICHMENT_POLL_INTERVAL_SECONDS: float = 5.0
    ENRICHMENT_BATCH_LIMIT: int = 60
    ENRICHMENT_CONCURRENCY: int = 4
    # Consecutive failures before a token is parked in the dead-letter state.
    ENRICHMENT_DEAD_LETTER_THRESHOLD: int = 10
    # How often to sweep for discovered tokens that have no scheduling row.
    # Runs at startup and then periodically: the Redis listener can miss events
    # (Redis restart, worker lag, state loss), and a startup-only sweep would
    # leave those tokens orphaned until someone restarted the worker.
    ENRICHMENT_BACKFILL_INTERVAL_SECONDS: float = 300.0

    # --- Adaptive refresh tiers ---------------------------------------------
    # "token age (minutes) -> refresh interval (seconds)". Young tokens move
    # fastest and matter most; old ones are polled rarely so their volume does
    # not crowd out fresh launches.
    ENRICHMENT_TIER_FRESH_MAX_MINUTES: int = 30
    ENRICHMENT_TIER_FRESH_INTERVAL_SECONDS: int = 30
    ENRICHMENT_TIER_YOUNG_MAX_MINUTES: int = 360  # 6 hours
    ENRICHMENT_TIER_YOUNG_INTERVAL_SECONDS: int = 300  # 5 minutes
    ENRICHMENT_TIER_MATURE_MAX_MINUTES: int = 1440  # 24 hours
    ENRICHMENT_TIER_MATURE_INTERVAL_SECONDS: int = 1800  # 30 minutes
    ENRICHMENT_TIER_OLD_INTERVAL_SECONDS: int = 21600  # 6 hours

    # --- AI scoring engine ---------------------------------------------------
    # Which weight vector to score with. Resolved through the model registry,
    # which raises on an unknown name rather than falling back to a default —
    # a typo must not silently ship scores from a model nobody chose.
    # --- Opportunity Radar ---------------------------------------------------
    # Off by default like every other pipeline flag, so enabling it is a
    # deliberate act. Independent of the scanner: the Radar re-evaluates
    # existing projects and does not need discovery to be running.
    FEATURE_RADAR_ENABLED: bool = False
    RADAR_SWEEP_BATCH_LIMIT: int = 500
    RADAR_SWEEP_INTERVAL_SECONDS: int = 900

    SCORING_MODEL_VERSION: str = "v1"
    # Snapshots per feature window. The window itself is tier-relative
    # (K x tier interval, clamped), because a fixed window starves the slow
    # tiers: at a 6-hour refresh interval a one-hour window holds one
    # observation, permanently capping evidence for every healthy old token.
    SCORING_FEATURE_WINDOW: int = 12
    SCORING_WINDOW_MIN_SECONDS: int = 3600  # 1 hour
    SCORING_WINDOW_MAX_SECONDS: int = 604800  # 7 days
    # Liquidity drawdown inside this window is a rug in progress and vetoes the
    # score; the same decline spread over days is decay and only penalises.
    SCORING_RUG_WINDOW_SECONDS: int = 3600
    # Observations needed before window-based signals count as fully evidenced.
    SCORING_MIN_OBSERVATIONS: int = 3
    # Consecutive qualifying evaluations before Elite is granted.
    SCORING_ELITE_SUSTAIN_EVALUATIONS: int = 3

    # --- Score materiality ---------------------------------------------------
    # `token_scores` is upserted every evaluation; history is written only when
    # something actually changed. Without these, a 30-second tier writes ~2,880
    # near-identical history rows per token per day and the Observatory Log
    # becomes noise rather than a record of genuine events.
    SCORING_HISTORY_MIN_DELTA: float = 2.0
    # A grade change alone is not enough: this deadband stops a score
    # oscillating across a band edge from writing a row per evaluation.
    SCORING_GRADE_DEADBAND: float = 0.5
    # Heartbeat, so a flat token still leaves a sampled trace.
    SCORING_HISTORY_MIN_INTERVAL_SECONDS: int = 300

    # --- Score sweep ---------------------------------------------------------
    # A score is stale once this many of its own tier's refresh intervals have
    # passed without re-evaluation. Tier-relative, because two minutes of
    # silence is nothing for a six-hourly token and a missed beat for one
    # refreshing every thirty seconds.
    SCORING_STALE_AFTER_TIER_MULTIPLE: int = 4
    SCORING_SWEEP_BATCH_LIMIT: int = 200
    SCORING_RESCORE_BATCH_LIMIT: int = 200
    # Full-fidelity retention for score history before thinning.
    SCORING_HISTORY_RETENTION_DAYS: int = 30

    # Separate from the discovery channel: a score event is not a discovery, and
    # conflating them would force every consumer to discriminate on payload shape.
    SCORE_EVENT_CHANNEL: str = "memescope:scores:changed"

    # --- Development conveniences --------------------------------------------
    # Treat every request as an authenticated developer, skipping token checks
    # entirely. For local development only: it is rejected outright in
    # production by `_enforce_production_hardening`, and every consumer must go
    # through `auth_bypass_active` rather than reading this flag directly, so
    # the environment check cannot be forgotten at a call site.
    DEVELOPMENT_BYPASS_AUTH: bool = False
    # Identity handed to requests while the bypass is active. Never persisted.
    # A real TLD, because the response schema validates it as an email address -
    # `.local` and `.example` are reserved names that fail validation.
    DEVELOPMENT_USER_EMAIL: str = "developer@memescope.dev"

    # --- Feature flags -------------------------------------------------------
    FEATURE_SCANNER_ENABLED: bool = False
    FEATURE_ENRICHMENT_ENABLED: bool = False
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

    # Every `CsvList` field must be named here or it will only accept a JSON
    # array, and a plain `A,B` in an env file fails validation at boot. The list
    # is explicit rather than inferred from the annotation because the failure
    # is loud and immediate either way, and an explicit list is greppable.
    @field_validator("SENTRY_DSN", mode="before")
    @classmethod
    def _empty_is_unset(cls, value: Any) -> Any:
        """Treat an empty environment variable as "not configured".

        `SENTRY_DSN: ${SENTRY_DSN:-}` in a compose file sets the variable to an
        empty string rather than leaving it absent, and an empty string is not a
        valid URL — so a deployment that simply had no Sentry project failed to
        boot at all, with a validation error about a field the operator never
        set. The default path must be the one that works.
        """
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @field_validator(
        "CORS_ORIGINS",
        "ALLOWED_HOSTS",
        "TRUSTED_PROXY_IPS",
        "SCANNER_WATCH_PROGRAMS",
        mode="before",
    )
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
    def auth_bypass_active(self) -> bool:
        """Whether requests should be treated as an authenticated developer.

        The single source of truth for the bypass. It ands the flag with the
        environment so that enabling it cannot, by construction, take effect
        anywhere but local development - a call site that read
        `DEVELOPMENT_BYPASS_AUTH` directly could forget that check, so nothing
        does.

        `test` is deliberately excluded. Allowing it would mean a developer with
        the flag exported silently ran the whole suite with authentication
        disabled, and every auth test would pass for the wrong reason. Tests
        that need to exercise the bypass patch this property explicitly.
        """
        return self.DEVELOPMENT_BYPASS_AUTH and self.ENVIRONMENT == "local"

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
            # Refuse to boot rather than quietly ignoring it. A process that
            # started "successfully" with an auth bypass requested is the worst
            # outcome available: silently ignoring the flag would leave whoever
            # set it believing something about the deployment that is not true.
            if self.DEVELOPMENT_BYPASS_AUTH:
                raise ValueError("DEVELOPMENT_BYPASS_AUTH must not be set in production")
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
