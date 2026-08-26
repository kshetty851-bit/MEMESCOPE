"""Application configuration.

All settings are loaded from environment variables (or a local `.env` file) and
validated at import time. Fail fast: a misconfigured process should never boot.
"""

from __future__ import annotations

import json
import secrets
from decimal import Decimal
from functools import lru_cache
from typing import Annotated, Any, Literal
from urllib.parse import urlparse

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
    VERSION: str = "0.8.0-rc1"
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

    # --- Temporary private-alpha access gate --------------------------------
    # This is not user authentication. It is a server-side deployment gate used
    # while the product is private: a shared code creates an httpOnly cookie,
    # and the frontend/dashboard checks that cookie through the API.
    ALPHA_ACCESS_CODE: SecretStr = SecretStr("619554")
    ALPHA_ACCESS_REQUIRED: bool = False
    ALPHA_ACCESS_COOKIE_NAME: str = "memescope_alpha"
    ALPHA_ACCESS_COOKIE_PATH: str = "/"
    ALPHA_ACCESS_COOKIE_DOMAIN: str | None = None
    ALPHA_ACCESS_COOKIE_SECURE: bool = False
    ALPHA_ACCESS_COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"
    ALPHA_ACCESS_SESSION_DAYS: int = 30
    ALPHA_ACTIVITY_HEARTBEAT_SECONDS: int = 25

    # --- Daily paper-wallet report ------------------------------------------
    #
    # Reporting only. Nothing here can open, close or reprice a position; the
    # report reads `PaperWalletService.read` and renders it.
    #
    # Off by default and it stays off without SMTP credentials, so a deploy that
    # has not been configured sends nothing rather than failing on a schedule.
    DAILY_REPORT_ENABLED: bool = False
    #: Comma-separated. `CsvList` is the same coercion `CORS_ORIGINS` uses.
    DAILY_REPORT_RECIPIENTS: CsvList = Field(
        default_factory=lambda: ["Kshetty851@gmail.com"]
    )
    #: Local hour the report is for, in `DAILY_REPORT_TIMEZONE`.
    DAILY_REPORT_HOUR: int = Field(default=9, ge=0, le=23)
    DAILY_REPORT_MINUTE: int = Field(default=0, ge=0, le=59)
    #: An IANA name, never a fixed offset. The whole application stores and
    #: schedules in UTC (`celery_app.conf.timezone`), so "09:00" is meaningless
    #: without saying 09:00 *where* — and a fixed offset would silently drift
    #: through a DST change.
    DAILY_REPORT_TIMEZONE: str = "Asia/Dubai"

    # --- Outbound email -----------------------------------------------------
    #
    # There was no email infrastructure before this feature. Credentials are
    # environment-only and never defaulted to anything that could send.
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: SecretStr = SecretStr("")
    SMTP_USE_TLS: bool = True
    SMTP_TIMEOUT_SECONDS: float = 20.0
    #: Envelope sender. Falls back to `SMTP_USERNAME`, which is what most
    #: providers require the From address to match anyway.
    SMTP_FROM_EMAIL: str = ""
    SMTP_FROM_NAME: str = "MEMESCOPE"

    @property
    def email_configured(self) -> bool:
        """Whether a real send is possible.

        Checked before every scheduled attempt so an unconfigured deploy logs a
        skip rather than a failure — a report nobody set up is not an incident.
        """
        return bool(self.SMTP_HOST and self.SMTP_USERNAME)

    @property
    def email_sender(self) -> str:
        return self.SMTP_FROM_EMAIL or self.SMTP_USERNAME
    ALPHA_ACTIVITY_ACTIVE_SECONDS: int = 60
    ALPHA_ACTIVITY_IDLE_SECONDS: int = 600
    ALPHA_ACTIVITY_RETENTION_DAYS: int = 60

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

    # --- Solana RPC ----------------------------------------------------------
    # Which implementation the scanner and curve collection talk to. `solana`
    # is plain JSON-RPC against any compliant node; `helius` adds the DAS
    # metadata read on top of the same standard calls. Default stays `helius`
    # so an existing deployment's behaviour is unchanged by this setting
    # appearing — switching is a deliberate act, not a silent migration.
    SOLANA_RPC_PROVIDER: str = "helius"
    #: The endpoint used when the provider is not vendor-specific. Any public
    #: endpoint, self-hosted validator, or paid provider's standard URL.
    SOLANA_RPC_URL: str = "https://api.mainnet-beta.solana.com"
    #: Subscription endpoint for the scanner. `logsSubscribe` is standard, so
    #: any node exposing a WebSocket serves it.
    SOLANA_WS_URL: str = "wss://api.mainnet-beta.solana.com"
    SOLANA_RPC_TIMEOUT_SECONDS: float = 20.0

    # --- Helius (one RPC implementation) -------------------------------------
    # Never hardcoded: SecretStr keeps the key out of logs and repr output.
    HELIUS_API_KEY: SecretStr = SecretStr("")
    HELIUS_RPC_BASE: str = "https://mainnet.helius-rpc.com"
    HELIUS_WS_BASE: str = "wss://mainnet.helius-rpc.com"
    HELIUS_HTTP_TIMEOUT_SECONDS: float = 20.0

    # --- Token discovery scanner --------------------------------------------
    # Programs whose logs are watched for token-creation instructions. pump.fun
    # is where the overwhelming majority of Solana meme coins launch; the
    # PumpSwap AMM (`pAMM…`) covers direct pool launches that never touch the
    # bonding curve — its `create_pool` emits a `CreatePoolEvent` (discriminator
    # b1310cd2a076a774, verified against mainnet) naming the base mint.
    SCANNER_WATCH_PROGRAMS: CsvList = Field(
        default_factory=lambda: [
            "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
            "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",
        ]
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
    # Reconnect escalation. The backoff ladder above is correct and must not
    # change — full jitter is what stops every client retrying in lockstep when
    # Helius recovers. What was missing is escalation: the scanner spent four
    # days on attempt 959 against an exhausted Helius quota, logging `warning`
    # every time, while the container reported healthy. Past this many
    # consecutive failures the condition is no longer transient and is logged at
    # ERROR.
    SCANNER_RECONNECT_ERROR_ATTEMPTS: int = Field(default=5, ge=1)
    # ...but not on every attempt after that, or a week-long outage writes a
    # million identical ERROR lines. One in N once escalated.
    SCANNER_RECONNECT_ERROR_EVERY: int = Field(default=20, ge=1)
    # How long the scanner's published state stays valid in Redis. Longer than
    # the maximum backoff delay, so a scanner that is merely between retries
    # does not read as absent; short enough that a killed process disappears.
    SCANNER_STATE_TTL_SECONDS: int = Field(default=300, ge=30)
    # Gap recovery on (re)connect: how far back, in slots, the scanner will
    # walk `getBlock` to recover creations it missed while disconnected. One
    # block is one RPC call, so this is also the per-outage request budget;
    # 900 slots is roughly six minutes of chain. A longer outage recovers only
    # the newest window — the older tokens' information value has already
    # decayed — and logs the slots it abandoned rather than hiding them.
    # Zero disables recovery.
    SCANNER_RECOVERY_MAX_SLOTS: int = Field(default=900, ge=0, le=20_000)
    # Pause between block fetches. Recovery shares one RPC allowance with live
    # transaction resolution AND the enrichment worker's curve collection, so
    # it must trickle: on 2026-08-20 a 4-blocks/second walk against the public
    # endpoint helped 429-storm the shared IP for hours and slowed every
    # enrichment cycle. One block per second walks the full default window
    # inside the walk's 15-minute wall-clock deadline. Tighten on a paid
    # endpoint via env.
    SCANNER_RECOVERY_BLOCK_DELAY_SECONDS: float = Field(default=1.0, ge=0.0, le=10.0)
    # Redis channel the scanner publishes to and the API fans out from. This is
    # the *base* name; `token_channel` below is what is actually used.
    TOKEN_EVENT_CHANNEL: str = "memescope:tokens:discovered"

    # --- Yellowstone gRPC shadow discovery ----------------------------------
    # It is deliberately off by default and cannot become canonical in Phase 1.
    YELLOWSTONE_ENABLED: bool = False
    YELLOWSTONE_SHADOW_MODE: bool = True
    YELLOWSTONE_GRPC_URL: str = ""
    YELLOWSTONE_X_TOKEN: SecretStr = SecretStr("")
    YELLOWSTONE_PROGRAM_IDS: CsvList = Field(
        default_factory=lambda: ["6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"]
    )
    YELLOWSTONE_REPLAY_OVERLAP_SLOTS: int = Field(default=2, ge=0, le=100)
    YELLOWSTONE_MAX_RECEIVE_BYTES: int = Field(default=16 * 1024 * 1024, ge=1_048_576)

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
    ENRICHMENT_BATCH_LIMIT: int = 120
    ENRICHMENT_CONCURRENCY: int = 4
    # Consecutive failures before a token is parked in the dead-letter state.
    # **Both conditions must hold** — see `RefreshScheduler.should_dead_letter`.
    # A count alone is cadence-dependent: ten failures is 2.5 minutes on the
    # 15-second priority lane and 20 on the normal one, which made the tokens
    # the product most wants fresh the easiest to park. On 2026-08-05 a
    # 60-second provider outage dead-lettered 163 of the 200 lane members.
    ENRICHMENT_DEAD_LETTER_THRESHOLD: int = 10
    #: ...and it must have been failing at least this long. The time condition
    #: is what makes the threshold mean the same thing in every lane.
    ENRICHMENT_DEAD_LETTER_MIN_MINUTES: int = Field(default=30, ge=1, le=1440)
    #: How long a dead-lettered token waits before the requeue beat readmits it.
    #: Dead-lettering is a quarantine, not a grave — but a token that is
    #: genuinely broken should cost one wasted call per interval, not one per
    #: pass, which is what this interval buys.
    ENRICHMENT_DEAD_LETTER_RETRY_MINUTES: int = Field(default=60, ge=5, le=10_080)
    #: How many to readmit per pass, so a large backlog drains gradually rather
    #: than arriving as one spike on a provider that may still be unwell.
    ENRICHMENT_DEAD_LETTER_REQUEUE_LIMIT: int = Field(default=250, ge=1, le=5000)
    #: Floor on how long a batch is pushed back when the provider is
    #: unavailable. The breaker's own remaining cooldown is used when it is
    #: longer; this is the guard for when it reports nearly zero, which would
    #: otherwise let the worker spin on a rejection that costs nothing to make.
    ENRICHMENT_DEFER_MIN_SECONDS: float = Field(default=15.0, ge=1.0, le=600.0)
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

    # --- Retention and disk protection --------------------------------------
    # Raw telemetry is expired; evidence is not. `token_market_snapshots` keeps
    # a permanent carve-out for every mint in `radar_tokens` or
    # `paper_positions`, so an admitted or traded token keeps its whole series
    # regardless of these windows.
    #
    # Sized from the 2026-08-21 audit of production: score history was 11 GB
    # (79% older than 7 days), radar decision snapshots 4.2 GB growing at
    # ~1 GB/day with no policy at all, and market snapshots 3.7 GB (78% older
    # than 7 days). At these windows the three settle near 14 GB combined with
    # the nursery running, against a 38 GB disk.
    SCORING_HISTORY_RETENTION_DAYS: int = 7
    MARKET_SNAPSHOT_RETENTION_DAYS: int = Field(default=7, ge=1, le=365)
    #: The heaviest table per row (~8 KB, mostly JSONB) and the fastest grower.
    #: The distilled `radar_decision_outcomes` is permanent; this is only its
    #: raw input, and a decision that already has an outcome is excluded from
    #: pruning entirely.
    #:
    #: 3 -> 2 days: measured on production after the 2026-08-21 cleanup, three
    #: days of this table is ~4.3 GB, and it projects to ~8.4 GB with the
    #: nursery running — half the steady-state database on a 38 GB disk. Two
    #: days returns ~2.8 GB of that and lifts projected free space from ~12 GB
    #: to ~15 GB.
    RADAR_DECISION_SNAPSHOT_RETENTION_DAYS: int = Field(default=2, ge=1, le=365)
    #: Windows used only by the emergency pass above the critical threshold.
    SCORING_HISTORY_EMERGENCY_DAYS: int = Field(default=3, ge=1, le=365)
    RADAR_DECISION_SNAPSHOT_EMERGENCY_DAYS: int = Field(default=1, ge=1, le=365)
    #: Warn here; act there. At 100% Redis loses RDB persistence, returns
    #: MISCONF on every write, and Celery beat stops enqueuing — which is how
    #: a full disk silently stopped every scheduled job on 2026-08-21. 85%
    #: leaves room for a backup plus a table rewrite.
    DISK_WARNING_PERCENT: float = Field(default=75.0, ge=1.0, le=99.0)
    DISK_CRITICAL_PERCENT: float = Field(default=85.0, ge=1.0, le=99.0)

    # --- Fresh-token nursery lane -------------------------------------------
    # Every newly discovered token's first FRESH-window minutes of prioritised
    # observation, claimed ahead of the backlog but always behind the display
    # lane (open paper positions included). Exists because the FRESH tier's
    # interval was a promise the queue could not keep: with 238k overdue rows,
    # a fresh token's median wait for its *first* snapshot was 4.3 hours.
    #
    # Capacity bound. Worst-case claim demand is `cap * 60 / interval` per
    # minute, which must leave room inside the enrichment worker's measured
    # throughput for the display lane and the backlog. Zero disables the lane
    # entirely. Trimming is oldest-first, so a launch storm costs tail
    # observation minutes, never the first look at the newest token.
    #
    # **Sized from the replay, not guessed.** At 600 the lane held a token for
    # only 18 minutes during the afternoon launch regime measured on
    # 2026-08-20 (~1,900 launches/hour), yielding ~12 observations — exactly
    # the Radar's `MIN_OBSERVATIONS` floor, with no margin. 1,000 covers that
    # regime for the whole 30-minute window (~20 observations). The cost is
    # ~400 extra claims/minute, or ~13 extra provider requests/minute at 30
    # mints per request: measured live at 116 requests/minute with zero rate
    # limiting and zero breaker trips, against a 300/minute allowance.
    ENRICHMENT_NURSERY_MAX_TOKENS: int = Field(default=1000, ge=0, le=5000)
    # 60s yields ~25 observations across the 30-minute window — comfortably
    # past the Radar's 12-observation floor and scoring's depth requirement of
    # 3, without the display lane's 15s cost per token.
    ENRICHMENT_NURSERY_INTERVAL_SECONDS: int = Field(default=60, ge=15, le=600)

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
    #: How many slices the eligible universe is divided into. Every project is
    #: evaluated once per full rotation, so at a 900s sweep this is 12 hours.
    #: Raise it to spread load, lower it to shorten the guaranteed interval.
    RADAR_ROTATION_BUCKETS: int = 48

    # --- Forward Radar-quality research ------------------------------------
    # This observes the committed Radar after the fact.  It never changes a
    # score, rank, candidate universe, or selection decision; a persistence
    # failure is logged and discarded rather than entering the Radar path.
    FEATURE_RADAR_QUALITY_DATASET: bool = True
    RADAR_QUALITY_CONTROL_SAMPLE_MODULUS: int = Field(default=20, ge=2, le=1_000)
    RADAR_QUALITY_OUTCOME_BATCH_LIMIT: int = Field(default=100, ge=1, le=2_000)

    # --- Pump.fun Radar discovery ------------------------------------------
    # This is an admission stage, deliberately separate from the Opportunity
    # Radar. It identifies a bounded-age Pump.fun universe from data already
    # discovered and enriched; it neither scores nor re-fetches a token.
    FEATURE_PUMPFUN_RADAR_ENABLED: bool = False
    PUMPFUN_PROGRAM_ID: str = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
    PUMPFUN_RADAR_MIN_AGE_DAYS: int = Field(default=6, ge=0)
    PUMPFUN_RADAR_MAX_AGE_DAYS: int = Field(default=8, ge=0)
    # Zero is an intentional safe default: it requires the market fields to
    # exist without silently imposing a product threshold that has not been
    # chosen yet. Operators can tighten both values through configuration.
    PUMPFUN_RADAR_MIN_MARKET_CAP: float = Field(default=0, ge=0)
    PUMPFUN_RADAR_MIN_LIQUIDITY: float = Field(default=0, ge=0)
    PUMPFUN_RADAR_BATCH_LIMIT: int = Field(default=500, ge=1, le=5000)

    # --- Opportunity Engine: retired (V4 Phase 2 follow-up) -------------------
    # The engine ran flag-off for its whole production life; the near-graduation
    # provider was closed as unanswerable (ARCHITECTURE_DECISIONS.md §14a) and
    # V4 found the concept duplicated Radar admission. Its tables and history
    # remain (app/models/opportunity.py); its settings are gone — Settings uses
    # extra="ignore", so stale FEATURE_OPPORTUNITY_* env vars are harmless.

    # --- Priority enrichment lane ---------------------------------------------
    # Sprint 28. A lane inside the existing queue, not a second queue: the claim
    # query sorts on `priority` before `next_refresh_at`, so a displayed token
    # jumps a backlog that reached 36,154 rows. Measured before this, a tracked
    # token's p95 refresh gap was 106 minutes.
    FEATURE_PRIORITY_ENRICHMENT_ENABLED: bool = True
    #: What a displayed token gets regardless of age. Published because the
    #: freshness indicator on every surface is measured against it.
    ENRICHMENT_PRIORITY_INTERVAL_SECONDS: int = Field(default=15, ge=5, le=600)
    #: How many Radar ranks are treated as displayed. The homepage shows 10; the
    #: extra ranks cover the churn just below the fold so a token entering the
    #: visible set is already fresh rather than starting stale.
    ENRICHMENT_PRIORITY_RADAR_RANKS: int = Field(default=25, ge=1, le=200)
    #: Ceiling on the lane. Without it a bug that marks everything priority
    #: turns the lane back into the backlog it was built to escape.
    ENRICHMENT_PRIORITY_MAX_TOKENS: int = Field(default=200, ge=1, le=2000)

    # --- Ingest data-quality firewall (V4 Phase 2) -------------------------
    # Annotates incoming snapshots against their own 10-minute history; a
    # flagged row is stored untouched but excluded from peaks, features,
    # outcomes and wallet reads. V4 measured 8 prints >100x (worst 304,776x)
    # reaching peak_multiple unchallenged in one fresh day.
    FEATURE_SNAPSHOT_SANITY_ENABLED: bool = True
    #: A print outside baseline*band / baseline/band is suspect — unless the
    #: last MIN_PRIOR prints already agree with it (a persistent real move).
    SNAPSHOT_SANITY_BAND: float = Field(default=3.0, ge=1.5, le=100.0)
    SNAPSHOT_SANITY_LIQUIDITY_JUMP: float = Field(default=10.0, ge=2.0, le=1000.0)
    SNAPSHOT_SANITY_MIN_PRIOR: int = Field(default=3, ge=2, le=10)
    SNAPSHOT_SANITY_WINDOW_SECONDS: int = Field(default=600, ge=60, le=3600)

    # --- Chainstack RPC (primary production Solana RPC once configured) -----
    #: Full endpoint URL INCLUDING the access token (Chainstack embeds it in
    #: the path). Secret-bearing: reaches logs only through describe(), which
    #: redacts. Empty = provider unavailable; the router then runs
    #: Helius-only, and with neither configured it refuses rather than
    #: falling back to the public node.
    CHAINSTACK_RPC_URL: str = ""

    # --- Nursery: eligibility is not discovery (V4 Phase 2) -----------------
    #: Minimum minutes of observability before a qualifying token can become a
    #: Track Record admission. 0 disables the gate (previous behaviour). An
    #: OPERATIONAL CONTAINMENT default, recorded on every nursery row — not a
    #: researched trading threshold, and research must treat it as censoring.
    RADAR_MIN_OBSERVATION_MINUTES: int = Field(default=0, ge=0, le=1440)
    #: An OBSERVING row never re-judged for this long is closed as EXPIRED.
    RADAR_NURSERY_EXPIRE_HOURS: int = Field(default=24, ge=1, le=168)

    # --- Wallet-flow instrumentation (V4 Phase 2) ---------------------------
    # Decodes the Buy/Sell events already arriving on the scanner's socket into
    # bounded rolling per-mint aggregates. DATA COLLECTION ONLY: read by no
    # trading rule; ships dark and is switched on deliberately.
    FEATURE_WALLET_FLOW_ENABLED: bool = False
    #: Recent trades held per mint. Every metric is a share within one mint
    #: over a window, so a small ring answers all of them exactly while the
    #: memory stays bounded by construction.
    WALLET_FLOW_EVENT_CAPACITY: int = Field(default=256, ge=16, le=4096)
    #: Tracked mints, least-recently-traded evicted first.
    WALLET_FLOW_MAX_MINTS: int = Field(default=4000, ge=100, le=100_000)
    #: A mint with no trade for this long is dropped.
    WALLET_FLOW_TTL_SECONDS: float = Field(default=3600.0, ge=60.0, le=86_400.0)
    #: How often the scanner persists snapshots for research-relevant mints
    #: (nursery members + recent admissions). 0 disables persistence.
    WALLET_FLOW_FLUSH_SECONDS: int = Field(default=300, ge=0, le=3600)
    #: Wallet-flow snapshot retention (research primitives; see scanner flush).
    WALLET_FLOW_RETENTION_DAYS: int = Field(default=14, ge=1, le=90)

    # --- V5 Forward Strategy Arena (research simulation only) ---------------
    # Five $1,000 virtual portfolios scoring frozen entry hypotheses against a
    # cash control. It never creates a paper/karthik/real position and never
    # writes outside arena_*. Ships dark; production turns it on deliberately.
    FEATURE_ARENA_ENABLED: bool = False
    #: The contamination boundary (protocol §0): tokens whose 30-minute
    #: checkpoint precedes this instant are never scored. ISO-8601 UTC. Empty
    #: means "stamp at first activation", which is then immutable in the row.
    ARENA_VALID_FROM: str = ""

    # --- Isolated mainnet signer ------------------------------------------
    # The socket the API may talk to. The signer FILE path is deliberately not
    # a setting any application container reads: only the signer service reads
    # MAINNET_SIGNER_FILE, from its own environment, and it is the one process
    # that mounts key material.
    MAINNET_SIGNER_SOCKET: str = ""

    # --- V6 Forward Strategy Lab (research simulation only) -----------------
    # Twenty $1,000 virtual portfolios scoring the frozen V6_FINAL_20_STRATEGIES
    # registry against a cash control, all fed by the one MEMESCOPE scanner. It
    # never creates a paper/karthik/real position and never writes outside
    # lab_*. Ships dark; production turns it on deliberately.
    FEATURE_LAB_ENABLED: bool = False
    #: The contamination boundary (mission §15): tokens whose checkpoint
    #: precedes this instant are never scored, because the historical dataset
    #: has already been inspected seven times. ISO-8601 UTC. Empty means "stamp
    #: at first activation", after which the row makes it immutable — including
    #: the 24-hour snapshot instant derived from it.
    LAB_VALID_FROM: str = ""

    #: First-hour observation SLA: the median matured admission/nursery token
    #: must have at least this many stored observations in its first hour.
    #: V4 measured 7; the fast lane targets 30+ (nursery asks for 60s refresh).
    RESEARCH_SLA_FIRST_HOUR_MIN_OBS: int = Field(default=30, ge=1, le=3600)

    # --- Research collectors (V4 Phase 2) -----------------------------------
    # One flag for the four instrumentation beats (skipped quotes, holder
    # snapshots, universe snapshot, regime telemetry). They collect; they are
    # read by no trading path. Ships dark; production turns it on deliberately.
    FEATURE_RESEARCH_COLLECTORS_ENABLED: bool = False
    #: Round-trip quote samples per 5-minute run (2 API calls each).
    #: Round-trip quote samples per 5-minute run (2 API calls each). Sized for
    #: the V5 protocol's six checkpoints across a live nursery: at ~40 members
    #: a checkpoint falls due roughly every 90s, and the sampler must clear
    #: them before their grace window closes.
    RESEARCH_QUOTE_BATCH: int = Field(default=16, ge=1, le=50)
    RESEARCH_QUOTE_SIZE_USD: float = Field(default=10.0, gt=0, le=100.0)
    #: Holder snapshots per 10-minute run (2 RPC calls each).
    HOLDER_SNAPSHOT_BATCH: int = Field(default=10, ge=1, le=100)
    #: The operational containment thresholds the regime telemetry RECORDS.
    #: Explicitly not a validated alpha model — see V4 REPORT §7.
    REGIME_HOSTILE_ADMISSIONS_PER_DAY: int = Field(default=100, ge=1)
    REGIME_HOSTILE_MEDIAN_AGE_MINUTES: int = Field(default=60, ge=1)

    # --- Fast-lane enrichment replica (V4 Phase 2) --------------------------
    # V4 measured first-hour cadence at median 7 observations: the full cycle
    # spends most of its wall clock on scoring/radar/curves AFTER snapshots
    # commit, throttling collection to ~30 tokens/min/replica. A replica with
    # this flag claims only nursery/display/track-record lanes and runs the
    # snapshot stages alone — collection first, judgement elsewhere.
    ENRICHMENT_FAST_LANE_ONLY: bool = False

    # --- Paper wallet ---------------------------------------------------------
    # A deterministic simulation over stored market history. No wallet is
    # connected, no order is routed and no chain is touched: a position is a row
    # recording what a published rule would have done.
    #
    # Off by default like every other pipeline flag. While off, nothing opens,
    # nothing closes, and the API reports the wallet as not running rather than
    # serving an empty one that looks like a strategy which never traded.
    FEATURE_PAPER_WALLET_ENABLED: bool = False
    #: Entry-only pause for the Original Paper Wallet — the V4 research
    #: containment (2026-08-24): no validated edge exists and the admission
    #: stream is hostile, so new positions stop while the open book keeps
    #: being reviewed, exits keep settling and the record keeps being kept.
    #: Deliberately NOT `FEATURE_PAPER_WALLET_ENABLED`: that flag is checked
    #: before the review runs at all, so it stops exits too. This one is read
    #: at the single function every new position is born in, after exits have
    #: already settled.
    PAPER_WALLET_ENTRIES_PAUSED: bool = False
    #: The operational reason both wallet APIs and HQ print while entries are
    #: paused. A statement about the platform's evidence, never a market
    #: prediction — e.g. "NO_VALIDATED_EDGE/HOSTILE_POPULATION".
    WALLET_ENTRIES_PAUSE_REASON: str = ""
    #: Starting capital. Configurable, but written onto the wallet row at
    #: creation and read from there afterwards — every return is measured
    #: against the balance the wallet *started* with, so changing this setting
    #: later must not restate results that were already published.
    PAPER_WALLET_STARTING_BALANCE: float = Field(default=1_000.0, gt=0)
    #: Which published strategy trades. Sprint 30 made this one value rather
    #: than a choice: the registry holds exactly one operational strategy, so a
    #: different id here does not switch modes, it falls back with a warning.
    # One forward-only paper experiment.  Replacing this id does not reset a
    # wallet implicitly: the explicit paper-wallet reset migration archives the
    # old generation before this strategy is allowed to run.
    PAPER_WALLET_STRATEGY_ID: str = "universe_trailing_stop_25_v1"
    #: How many positions the evaluator advances per pass. Bounded and ordered
    #: oldest-watermark-first, which is what keeps a growing book from starving
    #: its own tail — the failure that livelocked the score sweep.
    PAPER_WALLET_REVIEW_BATCH_LIMIT: int = Field(default=2000, ge=1, le=2000)
    #: How far down the ranked Radar the evaluator looks for the next entry.
    #: Not a rule — the rule is "the highest-ranked eligible token" — but a scan
    #: has to stop somewhere, and a bound that is hit is *reported* rather than
    #: silently truncating the search (`candidates_truncated` on every pass).
    PAPER_WALLET_CANDIDATE_LIMIT: int = Field(default=250, ge=1, le=2000)
    #: Future paper trades use Jupiter quotes captured at decision time. When a
    #: quote cannot be obtained, the writer records the fallback reason and uses
    #: the legacy deterministic estimate rather than pretending a route existed.
    PAPER_EXECUTION_MODEL: Literal["legacy", "jupiter"] = "jupiter"
    JUPITER_QUOTE_BASE_URL: str = "https://lite-api.jup.ag/swap/v1"
    JUPITER_QUOTE_TIMEOUT_SECONDS: float = Field(default=6.0, gt=0, le=30)
    JUPITER_QUOTE_SLIPPAGE_BPS: int = Field(default=50, ge=0, le=10_000)
    JUPITER_USDC_MINT: str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

    # --- The Karthik paper wallet ------------------------------------------
    # A second, deliberately simpler paper experiment in its own tables. There
    # is no enable flag: Karthik exists once a wallet row exists, and that row
    # is created by one deliberate activation. A flag would be a second, weaker
    # copy of a fact the database already holds — and the flag most people would
    # reach for to "stop Karthik" would stop its exit monitoring too.
    #
    #: Entries only, and never anything else. Read at the single entry gate,
    #: which runs *after* exits have already been settled, so pausing purchases
    #: cannot strand an open position. The paper wallet's own pause is separated
    #: the same way, for the same reason.
    KARTHIK_ENTRIES_PAUSED: bool = False
    #: How many undecided Track Record admissions one pass may judge. Bounded,
    #: and taken oldest-admission-first so the tail cannot starve.
    KARTHIK_CANDIDATE_LIMIT: int = Field(default=250, ge=1, le=2000)
    #: How many open positions one pass advances, oldest watermark first.
    KARTHIK_REVIEW_BATCH_LIMIT: int = Field(default=2000, ge=1, le=2000)
    #: How old an observation may be and still stand in for the market *now*.
    #: Karthik buys and sells against readings, so a stale one is not a price it
    #: could have transacted at — it is refused rather than used.
    KARTHIK_MAX_MARKET_AGE_SECONDS: int = Field(default=900, ge=30, le=86_400)

    # --- Future real-wallet safety gate ------------------------------------
    # This policy only produces an auditable ALLOW/REJECT decision. It is not
    # connected to a signer, transaction builder, or execution engine.
    REAL_WALLET_SAFETY_POLICY_VERSION: str = "real_wallet_safety_v1"
    REAL_WALLET_SAFETY_MAX_MARKET_AGE_SECONDS: int = Field(default=90, ge=1, le=3600)
    REAL_WALLET_SAFETY_MAX_QUOTE_AGE_SECONDS: int = Field(default=15, ge=1, le=300)
    REAL_WALLET_SAFETY_MAX_BUY_PRICE_IMPACT_PCT: Decimal = Field(
        default=Decimal("5"), ge=Decimal("0"), le=Decimal("100")
    )
    REAL_WALLET_SAFETY_MAX_SELL_PRICE_IMPACT_PCT: Decimal = Field(
        default=Decimal("5"), ge=Decimal("0"), le=Decimal("100")
    )
    REAL_WALLET_SAFETY_MAX_ROUND_TRIP_LOSS_PCT: Decimal = Field(
        default=Decimal("10"), ge=Decimal("0"), le=Decimal("100")
    )
    REAL_WALLET_SAFETY_MAX_POSITION_LIQUIDITY_RATIO: Decimal = Field(
        default=Decimal("0.01"), gt=Decimal("0"), le=Decimal("1")
    )
    REAL_WALLET_SAFETY_MAX_PRICE_DEVIATION_PCT: Decimal = Field(
        default=Decimal("5"), ge=Decimal("0"), le=Decimal("100")
    )
    REAL_WALLET_SAFETY_SUPPORTED_VENUES: CsvList = Field(
        default_factory=lambda: ["pumpfun", "pumpswap"]
    )
    #: Venues the SECURITY EVALUATOR recognises. Deliberately a separate
    #: setting from the real wallet's list above, which it used to share.
    #:
    #: They answer different questions. The real wallet's list is "where may
    #: this platform SEND MONEY", and stays as narrow as it has always been.
    #: This one is "is this a market we recognise at all" — and Raydium,
    #: Meteora and Orca are the three largest AMMs on Solana, which the
    #: platform already prices from on every snapshot. Calling them
    #: unrecognised was a statement about pump.fun's dominance in the scanner's
    #: population, not about the venues.
    #:
    #: Sharing one list meant the market-universe wallet could not be admitted
    #: without also widening what the real wallet would be permitted to trade.
    #: Splitting them keeps that surface untouched.
    SECURITY_RECOGNISED_VENUES: CsvList = Field(
        default_factory=lambda: ["pumpfun", "pumpswap", "raydium", "meteora", "orca"]
    )
    # Token-2022 extension discriminants, deliberately an explicit allowlist.
    # 18=MetadataPointer and 19=TokenMetadata are the two observed in the
    # audit; an unknown extension is not presumed safe.
    REAL_WALLET_SAFETY_SUPPORTED_TOKEN_2022_EXTENSIONS: CsvList = Field(
        default_factory=lambda: ["18", "19"]
    )

    # --- Multi-generation position management (PW-LIFECYCLE-1) ------------
    # Whether the review pass settles exits for wallets that have been
    # archived. The architecture requires this — a retired *policy* still owes
    # an exit on every trade it opened — but turning it on has a one-off
    # consequence that must be a decision rather than a side effect.
    #
    # 105 positions across generations 1, 5 and 6 were abandoned when their
    # wallets were archived, and several passed a barrier or expiry while
    # nobody was evaluating them. Enabling this replays each position over its
    # own stored observations and closes it at the **historically observed**
    # price of the first breach — it never closes at today's price and never
    # invents an exit. That is a correction rather than a rewrite, but it does
    # change 105 recorded outcomes, so it ships off and is turned on
    # deliberately after the frozen-position audit has been reviewed.
    #
    # It must be ON before any generation cutover, or the outgoing
    # generation's open book is abandoned exactly as generations 1, 5 and 6
    # were.
    PAPER_WALLET_MANAGE_ARCHIVED_GENERATIONS: bool = False

    # --- Shared token security evaluation (read-only, HQ-6) ---------------
    # Deliberately NOT gated on REAL_WALLET_EXECUTION_MODE. Token security is
    # a property of the token; tying it to whether a wallet is enabled is the
    # exact observability hole HQ-5 found, where a disabled wallet meant the
    # platform could say nothing about any mint.
    #
    # This flag governs *evidence capture only*. Nothing in the paper entry
    # path reads the verdict, so turning it off loses observability and
    # changes no trading decision.
    TOKEN_SECURITY_EVALUATION_ENABLED: bool = True
    #: Hard fan-out cap for one review pass. The evaluator shares a worker
    #: with market enrichment and the paper review; an unbounded sweep would
    #: starve both, so the bound is a number rather than a hope.
    TOKEN_SECURITY_MAX_PER_PASS: int = Field(default=25, ge=0, le=200)
    #: Largest batch the per-token read model will answer in one request, so
    #: HQ can fill a Radar page without N+1 and without an unbounded query.
    TOKEN_SECURITY_MAX_BATCH: int = Field(default=50, ge=1, le=200)

    # --- Dedicated execution wallet (disabled by default) -----------------
    # This is deliberately separate from the safety gate.  It is only the
    # public-address, signer-boundary and limit configuration for a future,
    # low-balance execution wallet.  There is no transaction submission path
    # in this release. `armed` can prepare and audit an order but still has no
    # submission transport. `live` exists only so the central guard can reject
    # incomplete production configuration; this codebase does not install a
    # live submission transport.
    REAL_WALLET_EXECUTION_MODE: Literal["disabled", "dry_run", "armed", "live"] = "disabled"
    REAL_WALLET_EXECUTION_ENABLED: bool = False
    REAL_WALLET_AUTOTRADE_ENABLED: bool = False
    # This is deliberately separate from the scanner's mainnet RPC settings.
    # Wallet observation starts on devnet, and a wallet RPC can never silently
    # inherit the scanner's production endpoint.
    REAL_WALLET_NETWORK: Literal["devnet", "mainnet"] = "devnet"
    REAL_WALLET_RPC_URL: str = "https://api.devnet.solana.com"
    #: Public only. The paired secret is never loaded by an application process
    #: during Phase 1; a later isolated signer service needs separate review.
    REAL_WALLET_PUBLIC_KEY: str = ""
    REAL_WALLET_EXECUTION_SECRET_FILE: str = ""
    #: The ONLY address SOL may ever be withdrawn to. Deposits are open — the
    #: execution address is public and anyone may send to it — but the way out is
    #: a single destination the operator nominated, so a compromised caller,
    #: signer or API cannot choose where the money goes; it can at worst return
    #: it to the owner. Empty permits NOTHING: a withdrawal path with no
    #: nominated destination refuses rather than accepting any address, which is
    #: the same fail-closed direction as the RPC host list.
    REAL_WALLET_WITHDRAWAL_ADDRESS: str = ""
    # Phase 2 is a separate, deliberately tiny manual-devnet workflow. These
    # values are used by the API and signer to enforce the same small envelope;
    # the signer-file *path* is intentionally not a Settings field because the
    # API, worker, and web processes must never receive it.
    PHASE2_DEVNET_SIGNER_SOCKET: str = ""
    PHASE2_DEVNET_QUOTE_TTL_SECONDS: int = Field(default=60, ge=10, le=600)
    PHASE2_DEVNET_APPROVAL_TTL_SECONDS: int = Field(default=120, ge=10, le=900)
    PHASE2_DEVNET_MAX_TRANSFER_LAMPORTS: int = Field(default=1_000_000, ge=1, le=10_000_000)
    PHASE2_DEVNET_CONFIRM_RETRIES: int = Field(default=6, ge=1, le=20)
    PHASE2_DEVNET_CONFIRM_RETRY_SECONDS: float = Field(default=1.0, ge=0.1, le=10)
    #: Hosts a wallet RPC may be pointed at. `REAL_WALLET_RPC_URL` is editable
    #: by anyone with environment access; a genesis check proves which chain an
    #: endpoint *claims*, not that we agreed to ask that endpoint. Empty
    #: permits nothing, which is the safe direction for a narrowing list.
    REAL_WALLET_ALLOWED_RPC_HOSTS: CsvList = Field(
        default_factory=lambda: ["api.devnet.solana.com"]
    )
    #: Programs a real swap transaction may invoke at the top level. Defaults
    #: live in `real_wallet.tx_inspect`; this widens them only by deliberate
    #: configuration after an operator has decoded a real order.
    REAL_WALLET_ALLOWED_PROGRAM_IDS: CsvList = Field(default_factory=list)
    #: What one real entry spends. **Zero means unconfigured, and unconfigured
    #: refuses.** The final $100/$50/$25 ladder is the Paper position-size
    #: evidence work's decision and has not been made; a default here would
    #: quietly pre-empt it. Must not exceed `REAL_WALLET_MAX_TRADE_USD`.
    REAL_WALLET_ENTRY_SIZE_USD: Decimal = Field(default=Decimal("0"), ge=0)
    REAL_WALLET_MAX_TRADE_USD: Decimal = Field(default=Decimal("5"), gt=0)
    REAL_WALLET_MAX_OPEN_POSITIONS: int = Field(default=1, ge=1)
    REAL_WALLET_MAX_TOTAL_EXPOSURE_USD: Decimal = Field(default=Decimal("10"), gt=0)
    REAL_WALLET_MAX_DAILY_NOTIONAL_USD: Decimal = Field(default=Decimal("20"), gt=0)
    REAL_WALLET_MAX_DAILY_LOSS_USD: Decimal = Field(default=Decimal("10"), gt=0)
    #: How many real submissions may happen in one day, both sides counted. A
    #: notional cap bounds how much a bug can spend; only a count bounds how
    #: many times it can fire, and fee-only churn is invisible to the former.
    REAL_WALLET_MAX_DAILY_TRADES: int = Field(default=4, ge=1, le=100)
    #: The most SOL the canary wallet may ever hold. Compared in integer
    #: lamports. This is the bound that makes the blast radius a number rather
    #: than a promise: over-funding is refused instead of traded.
    REAL_WALLET_MAX_BALANCE_SOL: Decimal = Field(
        default=Decimal("0.25"), gt=0, le=Decimal("5")
    )
    #: Freshness and impact bounds for a real *exit* quote. An exit that cannot
    #: be priced is reported as an explicit failure state, never retried away.
    REAL_WALLET_EXIT_MAX_QUOTE_AGE_SECONDS: int = Field(default=15, ge=1, le=300)
    REAL_WALLET_EXIT_MAX_PRICE_IMPACT_PCT: Decimal = Field(
        default=Decimal("5"), gt=0, le=Decimal("50")
    )
    REAL_WALLET_EXIT_MAX_SLIPPAGE_BPS: int = Field(default=300, ge=1, le=5000)
    REAL_WALLET_MIN_SOL_FEE_RESERVE: Decimal = Field(default=Decimal("0.01"), ge=0)
    REAL_WALLET_AUTOTRADE_COOLDOWN_SECONDS: int = Field(default=300, ge=0)
    REAL_WALLET_MAX_CONSECUTIVE_EXECUTION_FAILURES: int = Field(default=2, ge=1)
    REAL_WALLET_DRY_RUN_CANDIDATE_LIMIT: int = Field(default=10, ge=1, le=100)
    FEATURE_REAL_WALLET_DRY_RUN_ENABLED: bool = False
    JUPITER_V2_BASE_URL: str = "https://api.jup.ag/swap/v2"
    JUPITER_API_KEY: SecretStr = SecretStr("")
    JUPITER_V2_ORDER_TIMEOUT_SECONDS: float = Field(default=8.0, gt=0, le=30)

    # --- Execution fee accounting (SOL/USD) --------------------------------
    # Network fees are paid in SOL and every limit in this system is written in
    # USD. Without a dated SOL/USD reading the two cannot be reconciled, so
    # `realised_net_pnl_usd` used to be set to the gross figure — a field that
    # said "net" and held gross. These settings exist so that stops.
    #: Which read-only provider supplies SOL/USD. `jupiter` reuses the quote
    #: API the paper wallet already depends on rather than adding a vendor.
    EXECUTION_SOL_PRICE_PROVIDER: Literal["jupiter"] = "jupiter"
    #: A price older than this cannot gate an entry. Fees are still converted
    #: from an older reading when settling history, but the reading's age and
    #: source are stored with the figure so nobody has to assume.
    EXECUTION_SOL_PRICE_MAX_AGE_SECONDS: int = Field(default=120, ge=1, le=3600)
    #: Wrapped SOL. The unit the network charges its fees in.
    EXECUTION_SOL_MINT: str = "So11111111111111111111111111111111111111112"
    #: Assumed priority fee per transaction, in SOL. Configuration, not a
    #: measurement — it is used only to make the reserve conservative, never to
    #: report a cost that was actually paid.
    EXECUTION_PRIORITY_FEE_SOL: Decimal = Field(
        default=Decimal("0.0005"), ge=Decimal("0"), le=Decimal("1")
    )
    #: How many transaction-costs of headroom the wallet must retain beyond the
    #: entry. At least 2: a position that cannot afford its own exit is a
    #: position that cannot be closed, which is worse than never opening it.
    EXECUTION_EXIT_FEE_RESERVE_MULTIPLIER: int = Field(default=2, ge=2, le=10)

    # --- Breakout provider ----------------------------------------------------
    # Every threshold measured against the stored history on 2026-08-03 (1.37 M
    # evaluable observations). At these values the provider fires on 0.03 % of
    # observations for breakout and 0.31 % for pre-breakout; a board is not a
    # feed, and a signal that fires on everything ranks nothing.
    #: Observations required before a range exists at all. Below this the
    #: provider reports unavailable rather than reading two points as a trend.
    OPPORTUNITY_BREAKOUT_MIN_OBSERVATIONS: int = Field(default=8, ge=3, le=200)
    #: How far above its own trailing high the price must be. 0.15 keeps 0.12 %
    #: of observations; 0 would keep 0.71 %, most of which is noise inside the
    #: normal spread of a thin pair.
    OPPORTUNITY_BREAKOUT_PRICE_MARGIN: float = Field(default=0.15, ge=0, le=10)
    #: Hourly volume against the window's median. Required by both claims — a
    #: price drifting up on no extra trading is the range being re-read, not
    #: broken.
    OPPORTUNITY_BREAKOUT_VOLUME_MULTIPLE: float = Field(default=2.0, ge=1, le=100)
    #: How close to the trailing high still counts as approaching it. 0.90 is
    #: the pre-breakout band's lower edge.
    OPPORTUNITY_BREAKOUT_PROXIMITY: float = Field(default=0.90, ge=0, le=1)

    #: Upper bound on opportunities examined by one expiry pass. Bounded so the
    #: sweep cannot grow unbounded with the table.
    OPPORTUNITY_EXPIRY_BATCH_LIMIT: int = Field(default=500, ge=1, le=5000)

    # --- Bonding curve collection ---------------------------------------------
    # Reads pump.fun curve accounts directly from the chain, which is the input
    # §14a names as the unblock for Near Graduation. Off by default like every
    # other pipeline stage, and additionally blocked today by the Helius plan
    # quota — every RPC method returns `429 max usage reached`.
    FEATURE_CURVE_COLLECTION_ENABLED: bool = False
    #: Tokens per collection pass. The collector chunks to whatever
    #: `getMultipleAccounts` accepts (100 addresses) on its own, so this is a
    #: work limit rather than an RPC one — and it must not sit *below*
    #: `ENRICHMENT_BATCH_LIMIT`, or the tail of every full enrichment batch is
    #: silently truncated away and those tokens get a market snapshot with no
    #: curve reading beside it. Raised from 100 with the batch limit.
    CURVE_COLLECTION_BATCH_LIMIT: int = Field(default=120, ge=1, le=1000)
    #: How many curve observations the near-graduation window reads.
    CURVE_WINDOW_SIZE: int = Field(default=12, ge=2, le=200)

    # --- Near Graduation provider --------------------------------------------
    # Off by default because the data does not support it, not because the
    # feature is unfinished. Measured against the live database on 2026-08-03:
    # of 386 tokens observed graduating, only 5 ever showed a pump.fun market
    # cap at or above 50k, and of 48 that did reach 50k only those same 5
    # graduated. `market_cap` on a bonding-curve pair is not bonding-curve
    # progress — the same class of gap that leaves `liquidity_usd` 100% null
    # for these pairs (ADR 0002).
    #
    # The provider and its model are complete and tested. Enable this once a
    # source of genuine curve progress exists — on-chain reserves via Helius is
    # the route ADR 0002 names — and the signal reaches the board with no code
    # change.
    OPPORTUNITY_NEAR_GRADUATION_ENABLED: bool = False
    #: Market cap at which a pump.fun token graduates, in USD. Configurable
    #: because it is a protocol constant that has changed before; deriving it
    #: from observed transitions is the better long-term answer.
    OPPORTUNITY_GRADUATION_MARKET_CAP: float = Field(default=69_000, gt=0)
    #: Progress at or above which a token counts as approaching graduation.
    #: Below it there is nothing to report — most of the universe sits there.
    OPPORTUNITY_NEAR_GRADUATION_MIN_PROGRESS: float = Field(default=0.55, gt=0, le=1)
    #: Observations needed before the trend components may contribute. Below
    #: this they report unavailable rather than reading a trend from two points.
    OPPORTUNITY_NEAR_GRADUATION_MIN_OBSERVATIONS: int = Field(default=4, ge=2)

    # --- Pipeline health -----------------------------------------------------
    # Staleness thresholds, per stage, in minutes. A stage is `healthy` below
    # the degraded bound, `degraded` between the two, and `down` at or past the
    # down bound. Every stage gets its own pair because their cadences differ by
    # two orders of magnitude — discovery is continuous, the Radar sweeps every
    # 15 minutes — so one shared threshold would either cry wolf on the Radar or
    # stay silent for an hour of dead discovery.
    #
    # Health is *derived from persisted state*: the last row each stage wrote.
    # Nothing here reports a stage as healthy because its process is running;
    # the scanner was running throughout the four days it discovered nothing.
    HEALTH_SCANNER_DEGRADED_MINUTES: int = Field(default=15, ge=1)
    HEALTH_SCANNER_DOWN_MINUTES: int = Field(default=60, ge=1)
    HEALTH_ENRICHMENT_DEGRADED_MINUTES: int = Field(default=10, ge=1)
    HEALTH_ENRICHMENT_DOWN_MINUTES: int = Field(default=30, ge=1)
    # Scoring and the Radar both run on a 15-minute beat, so one missed cycle is
    # degraded and several in a row is down.
    HEALTH_SCORING_DEGRADED_MINUTES: int = Field(default=30, ge=1)
    HEALTH_SCORING_DOWN_MINUTES: int = Field(default=120, ge=1)
    #: How old a *tracked* token's newest snapshot may be before it counts as
    #: stale. 300s = five minutes, matching the "normal" band the freshness
    #: indicator uses on every surface, so the API and the screen agree about
    #: what stale means.
    HEALTH_TRACKED_STALE_SECONDS: int = Field(default=300, ge=30, le=86_400)
    HEALTH_RADAR_DEGRADED_MINUTES: int = Field(default=30, ge=1)
    HEALTH_RADAR_DOWN_MINUTES: int = Field(default=120, ge=1)

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

    # Separate from the discovery channel: a score event is not a discovery, and
    # conflating them would force every consumer to discriminate on payload shape.
    SCORE_EVENT_CHANNEL: str = "memescope:scores:changed"
    # A narrow invalidation topic for committed market, Radar and paper-wallet
    # changes. This is another Redis Pub/Sub topic on the existing event bus,
    # not a second transport or queue.
    LIVE_EVENT_CHANNEL: str = "memescope:live:changed"

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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def uses_helius(self) -> bool:
        """Whether the configured RPC is the vendor-specific one.

        One place answers this. Before the abstraction, "are we on Helius" was
        implied by a key being present, which is why the key was required even
        where nothing vendor-specific was called.
        """
        return self.SOLANA_RPC_PROVIDER.strip().lower() == "helius"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def rpc_ws_url(self) -> str:
        """The subscription endpoint for the configured provider.

        The scanner's only vendor coupling was this URL. `logsSubscribe` is
        standard Solana WebSocket RPC, so the scanner itself needed no change
        beyond asking here instead of asking for Helius by name.
        """
        return self.HELIUS_WS_URL if self.uses_helius else self.SOLANA_WS_URL

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
        "YELLOWSTONE_PROGRAM_IDS",
        # Both were `CsvList` from the day the safety gate landed but were never
        # registered here, because neither had ever appeared in a compose file —
        # so the omission was invisible. Putting the execution contract in the
        # shared anchor made the backend refuse to boot on `pumpfun,pumpswap`.
        # These two are the venue and Token-2022 extension allowlists, i.e. the
        # settings an operator is most likely to want to narrow by hand.
        "REAL_WALLET_SAFETY_SUPPORTED_VENUES",
        "SECURITY_RECOGNISED_VENUES",
        "REAL_WALLET_SAFETY_SUPPORTED_TOKEN_2022_EXTENSIONS",
        # Fourth and fifth occurrence of the same trap, registered here from the
        # start rather than after a failed boot. Both are allowlists an operator
        # will set as `a.example.com,b.example.com` in a compose file.
        "REAL_WALLET_ALLOWED_RPC_HOSTS",
        "REAL_WALLET_ALLOWED_PROGRAM_IDS",
        # Third occurrence of the trap above, and caught the same way: the
        # recipient list was `CsvList` from the day the report landed but was
        # invisible until it reached a compose file, at which point
        # `DAILY_REPORT_RECIPIENTS=one@example.com` stopped the backend booting.
        "DAILY_REPORT_RECIPIENTS",
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

    @property
    def lab_valid_from(self) -> "datetime | None":
        """The frozen V6 contamination boundary, parsed. None = stamp at activation."""
        from datetime import datetime as _dt

        raw = (self.LAB_VALID_FROM or "").strip()
        if not raw:
            return None
        try:
            return _dt.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None

    @property
    def arena_valid_from(self) -> "datetime | None":
        """The frozen contamination boundary, parsed. None = stamp at activation."""
        from datetime import datetime as _dt

        raw = (self.ARENA_VALID_FROM or "").strip()
        if not raw:
            return None
        try:
            return _dt.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None


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
    def alpha_gate_open(self) -> bool:
        """Whether every visitor already has alpha access.

        Modelled on `auth_bypass_active` above and for the same reason: it ands
        the flag with the environment, so switching the gate off cannot take
        effect in production by construction. A call site reading
        `ALPHA_ACCESS_REQUIRED` directly could forget that check, so nothing
        does.

        This is belt and braces. Production already refuses to *boot* with
        `ALPHA_ACCESS_REQUIRED` false — see the validator that raises
        "ALPHA_ACCESS_REQUIRED must be true in production" — so this property
        is a second, independent reason the gate cannot open there.

        `test` is excluded deliberately, exactly as the auth bypass excludes
        it: a developer with the flag exported would otherwise run the whole
        suite with the gate open and every gate test would pass for the wrong
        reason. The tests that exercise this patch the property explicitly.

        ── WHY THIS EXISTS ──────────────────────────────────────────────────

        Turning the gate off used to open the API while leaving the dashboard
        unusable: every endpoint answered without a cookie, but
        `GET /alpha/session` still reported `authenticated: false`, so the
        dashboard layout bounced every visitor back to the landing page. The
        two halves disagreed about the same setting. This makes the session
        read agree with the behaviour the rest of the API already had.
        """
        return not self.ALPHA_ACCESS_REQUIRED and self.ENVIRONMENT == "local"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_namespace(self) -> str:
        """Prefix isolating every Redis channel by environment.

        The test suite already isolates Postgres — it creates and drops its own
        `*_test` database — but it shared Redis with whatever stack happened to
        be running. So `pytest` published discoveries onto the same channel the
        development enrichment worker was subscribed to, naming tokens that
        exist only in the test database. The worker read them, failed the
        foreign key, and tore down its subscription. A green test run left the
        development pipeline in a crash loop.

        Derived from `ENVIRONMENT` rather than configured separately: a
        namespace an operator can set independently is a namespace an operator
        can set to the same value twice, which is the bug this prevents.
        """
        return self.ENVIRONMENT

    @computed_field  # type: ignore[prop-decorator]
    @property
    def token_channel(self) -> str:
        """The discovery channel actually published to and subscribed from."""
        return f"{self.redis_namespace}:{self.TOKEN_EVENT_CHANNEL}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def score_channel(self) -> str:
        """The score-change channel actually published to and subscribed from."""
        return f"{self.redis_namespace}:{self.SCORE_EVENT_CHANNEL}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def live_channel(self) -> str:
        """The committed UI-invalidation channel, namespaced by environment."""
        return f"{self.redis_namespace}:{self.LIVE_EVENT_CHANNEL}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def scanner_state_key(self) -> str:
        """Where the scanner process publishes its own connection state.

        The scanner runs in its own container, so the API cannot read its
        in-memory counters. It writes them here instead, with a TTL, and the
        pipeline health endpoint reads them.
        """
        return f"{self.redis_namespace}:memescope:scanner:state"

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
            if not self.ALPHA_ACCESS_REQUIRED:
                raise ValueError("ALPHA_ACCESS_REQUIRED must be true in production")
            if len(self.ALPHA_ACCESS_CODE.get_secret_value()) < 1:
                raise ValueError("ALPHA_ACCESS_CODE is required in production")
            if not self.ALPHA_ACCESS_COOKIE_SECURE:
                raise ValueError("ALPHA_ACCESS_COOKIE_SECURE must be true in production")
        # Required only when Helius is the configured provider. Demanding a
        # vendor key to run the scanner against a public endpoint was the
        # hard dependency this sprint removed.
        if (
            self.FEATURE_SCANNER_ENABLED
            and self.uses_helius
            and not self.HELIUS_API_KEY.get_secret_value()
        ):
            raise ValueError(
                "HELIUS_API_KEY is required when FEATURE_SCANNER_ENABLED is true "
                "and SOLANA_RPC_PROVIDER is 'helius'. Set SOLANA_RPC_PROVIDER=solana "
                "to run against a standard endpoint instead."
            )
        if self.PUMPFUN_RADAR_MIN_AGE_DAYS > self.PUMPFUN_RADAR_MAX_AGE_DAYS:
            raise ValueError(
                "PUMPFUN_RADAR_MIN_AGE_DAYS must not exceed PUMPFUN_RADAR_MAX_AGE_DAYS"
            )
        # An inverted pair would report a stage as `down` before it was ever
        # `degraded`, so the middle state could never be observed and the
        # warning that precedes an outage would never fire.
        for stage in ("SCANNER", "ENRICHMENT", "SCORING", "RADAR"):
            degraded = getattr(self, f"HEALTH_{stage}_DEGRADED_MINUTES")
            down = getattr(self, f"HEALTH_{stage}_DOWN_MINUTES")
            if degraded > down:
                raise ValueError(
                    f"HEALTH_{stage}_DEGRADED_MINUTES must not exceed "
                    f"HEALTH_{stage}_DOWN_MINUTES"
                )
        if self.SCANNER_RECONNECT_ERROR_ATTEMPTS < 1:
            raise ValueError("SCANNER_RECONNECT_ERROR_ATTEMPTS must be at least 1")
        if self.YELLOWSTONE_ENABLED and not self.YELLOWSTONE_SHADOW_MODE:
            raise ValueError("Phase 1 Yellowstone may run only with YELLOWSTONE_SHADOW_MODE=true")
        if self.YELLOWSTONE_ENABLED and (
            not self.YELLOWSTONE_GRPC_URL or not self.YELLOWSTONE_X_TOKEN.get_secret_value()
        ):
            raise ValueError("YELLOWSTONE_GRPC_URL and YELLOWSTONE_X_TOKEN are required when enabled")
        # Phase 1 has no isolated signing service. Accepting a key-file path in
        # an API, worker, scanner, or scheduler process would recreate the
        # audit's custody weakness even though no execution is currently wired.
        # The only supported use of FileExecutionSigner is the explicit local
        # operator CLI; deployment-side signing is a later reviewed boundary.
        if self.REAL_WALLET_EXECUTION_SECRET_FILE:
            raise ValueError(
                "REAL_WALLET_EXECUTION_SECRET_FILE is not permitted in application "
                "processes during the read-only wallet phase"
            )
        # A configured entry size above the per-trade cap would be silently
        # clamped somewhere downstream, and a limit that clamps is a limit
        # nobody can read off the configuration. Refuse the contradiction
        # instead of resolving it.
        if self.REAL_WALLET_ENTRY_SIZE_USD > self.REAL_WALLET_MAX_TRADE_USD:
            raise ValueError(
                "REAL_WALLET_ENTRY_SIZE_USD must not exceed REAL_WALLET_MAX_TRADE_USD"
            )
        # The wallet RPC must be on its own allowlist. Shipping an endpoint the
        # execution path will refuse is a deployment that looks configured and
        # fails at the first signature, which is the worst moment to find out.
        # Inlined rather than imported from `real_wallet.network`: settings are
        # constructed at import time and that module reaches back here.
        wallet_rpc_host = (
            urlparse(self.REAL_WALLET_RPC_URL).hostname or ""
        ).lower()
        allowed_rpc_hosts = {
            host.strip().lower()
            for host in self.REAL_WALLET_ALLOWED_RPC_HOSTS
            if host.strip()
        }
        if not wallet_rpc_host or wallet_rpc_host not in allowed_rpc_hosts:
            raise ValueError(
                "REAL_WALLET_RPC_URL host must appear in REAL_WALLET_ALLOWED_RPC_HOSTS"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor so settings are parsed exactly once per process."""
    return Settings()


settings = get_settings()
