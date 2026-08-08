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
    # Redis channel the scanner publishes to and the API fans out from. This is
    # the *base* name; `token_channel` below is what is actually used.
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

    # --- Opportunity Engine ---------------------------------------------------
    # Off by default like every other pipeline flag, so enabling it is a
    # deliberate act. While off, detection never runs and no existing behaviour
    # changes — the Radar, scoring and enrichment are untouched either way.
    FEATURE_OPPORTUNITY_ENGINE_ENABLED: bool = False
    #: Which venues count as a bonding curve, and which as a graduated pool.
    #: Configurable because a launchpad renaming its venue must be a config
    #: change, not a code change — pump.fun has already renamed an instruction
    #: once (see the scanner's `InitializeMint` reasoning).
    OPPORTUNITY_BONDING_CURVE_VENUES: CsvList = Field(default_factory=lambda: ["pumpfun"])
    OPPORTUNITY_GRADUATED_VENUES: CsvList = Field(default_factory=lambda: ["pumpswap"])
    #: Observations a signal needs before it may become ACTIVE. Below this the
    #: opportunity sits in PENDING_CONFIRMATION and reaches no board: one
    #: snapshot is noise.
    OPPORTUNITY_REQUIRED_CONFIRMATIONS: int = Field(default=2, ge=1)
    #: How many observations to load per token for provider evaluation.
    OPPORTUNITY_WINDOW_SIZE: int = Field(default=12, ge=2, le=200)
    #: Per-signal-type TTL. Fresh graduation is a bounded factual window; a
    #: token that graduated three days ago did not graduate *now*.
    OPPORTUNITY_TTL_FRESH_GRADUATION_SECONDS: int = Field(default=172_800, ge=60)
    #: Fallback for any signal type without its own TTL, so a provider added in
    #: a future sprint cannot produce an immortal signal by omission.
    OPPORTUNITY_TTL_DEFAULT_SECONDS: int = Field(default=21_600, ge=60)
    #: How long an opportunity stays EXPIRING before closing. A re-detection
    #: inside this window revives it in place rather than minting a generation.
    OPPORTUNITY_GRACE_SECONDS: int = Field(default=3_600, ge=0)
    #: How long a CLOSED opportunity settles before archival frees its token to
    #: open a new generation.
    OPPORTUNITY_ARCHIVE_AFTER_SECONDS: int = Field(default=86_400, ge=0)
    #: Per-signal TTL for the breakout family. Hours, not days: ADR §11 puts
    #: breakout at "confirmed or invalidated fast", and a stale breakout is the
    #: most misleading card the board can show — it claims a move is happening.
    OPPORTUNITY_TTL_BREAKOUT_SECONDS: int = Field(default=21_600, ge=60)
    #: Pre-breakout resolves more slowly by nature: it is a claim about pressure
    #: building, which either realises into a breakout or quietly does not.
    OPPORTUNITY_TTL_PRE_BREAKOUT_SECONDS: int = Field(default=86_400, ge=60)

    # --- Priority enrichment lane ---------------------------------------------
    # Sprint 28. A lane inside the existing queue, not a second queue: the claim
    # query sorts on `priority` before `next_refresh_at`, so a displayed token
    # jumps a backlog that reached 36,154 rows. Measured before this, a tracked
    # token's p95 refresh gap was 106 minutes.
    FEATURE_PRIORITY_ENRICHMENT_ENABLED: bool = False
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

    # --- Paper wallet ---------------------------------------------------------
    # A deterministic simulation over stored market history. No wallet is
    # connected, no order is routed and no chain is touched: a position is a row
    # recording what a published rule would have done.
    #
    # Off by default like every other pipeline flag. While off, nothing opens,
    # nothing closes, and the API reports the wallet as not running rather than
    # serving an empty one that looks like a strategy which never traded.
    FEATURE_PAPER_WALLET_ENABLED: bool = False
    #: Starting capital. Configurable, but written onto the wallet row at
    #: creation and read from there afterwards — every return is measured
    #: against the balance the wallet *started* with, so changing this setting
    #: later must not restate results that were already published.
    PAPER_WALLET_STARTING_BALANCE: float = Field(default=1_000.0, gt=0)
    #: Which published strategy trades. Sprint 30 made this one value rather
    #: than a choice: the registry holds exactly one operational strategy, so a
    #: different id here does not switch modes, it falls back with a warning.
    PAPER_WALLET_STRATEGY_ID: str = "trailing_stop_25_v1"
    #: How many positions the evaluator advances per pass. Bounded and ordered
    #: oldest-watermark-first, which is what keeps a growing book from starving
    #: its own tail — the failure that livelocked the score sweep.
    PAPER_WALLET_REVIEW_BATCH_LIMIT: int = Field(default=200, ge=1, le=2000)
    #: How far down the ranked Radar the evaluator looks for the next entry.
    #: Not a rule — the rule is "the highest-ranked eligible token" — but a scan
    #: has to stop somewhere, and a bound that is hit is *reported* rather than
    #: silently truncating the search (`candidates_truncated` on every pass).
    PAPER_WALLET_CANDIDATE_LIMIT: int = Field(default=250, ge=1, le=2000)

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
    #: Tokens per collection pass. `getMultipleAccounts` accepts 100 addresses,
    #: so this is a multiple of that or a fraction of one call.
    CURVE_COLLECTION_BATCH_LIMIT: int = Field(default=100, ge=1, le=1000)
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
    SCORING_HISTORY_RETENTION_DAYS: int = 30

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
        "OPPORTUNITY_BONDING_CURVE_VENUES",
        "OPPORTUNITY_GRADUATED_VENUES",
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
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor so settings are parsed exactly once per process."""
    return Settings()


settings = get_settings()
