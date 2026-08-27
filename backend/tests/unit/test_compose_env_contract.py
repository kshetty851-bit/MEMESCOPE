"""The `x-backend-env` anchor is a contract, and it has been broken three times.

Every occurrence had the same shape and the same symptom: a setting was placed
on one service instead of the shared anchor, the service that had it looked
healthy, and the services that did not silently fell back to a code default or
failed at runtime.

  1. `FEATURE_AI_SCORING_ENABLED` — scoring silently disabled (MASTER_CONTEXT §9).
  2. `ALLOWED_HOSTS` — all four workers restart-looped while the backend looked
     fine (MASTER_CONTEXT §18, defect 3).
  3. `REDIS_PASSWORD` — set on backend/worker/scheduler but not `scanner` or
     `enrichment`. Production starts Redis with `--requirepass`, so the scanner
     could not publish discoveries and the enrichment listener could not
     subscribe to them. Development, where Redis needs no password, worked
     perfectly.

Prose warnings did not prevent 2 or 3. This test does.

Parsed with a regex rather than PyYAML deliberately: the compose file is not in
the backend's build context, so adding a parser dependency to ship one test
would be a poor trade. The anchor is a flat block of `KEY: value` lines and
needs nothing cleverer.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


def _find_repo_root() -> Path | None:
    """Walk up looking for the compose file.

    Returns None inside the backend container, where the repository root is not
    mounted. CI runs pytest from `backend/` on the runner, where it resolves.
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "docker-compose.yml").is_file():
            return parent
    return None


REPO_ROOT = _find_repo_root()

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(
        REPO_ROOT is None,
        reason="docker-compose.yml not reachable (running inside the backend container)",
    ),
]


def _anchor_keys() -> set[str]:
    """Every key defined in the `x-backend-env` anchor block."""
    assert REPO_ROOT is not None
    text = (REPO_ROOT / "docker-compose.yml").read_text()

    block = re.search(r"^x-backend-env:\s*&backend-env\n(.*?)(?=^\S)", text, re.M | re.S)
    assert block is not None, "x-backend-env anchor not found in docker-compose.yml"

    return set(re.findall(r"^  ([A-Z][A-Z0-9_]*):", block.group(1), re.M))


#: Settings whose absence from the anchor breaks a service at runtime rather
#: than merely leaving it on a default. Each entry names why, so a future
#: reader can judge whether a removal is safe.
REQUIRED_IN_ANCHOR = {
    "ENVIRONMENT": "selects production validators; every service must agree",
    "SECRET_KEY": "token signing; a divergent value invalidates sessions",
    "ALLOWED_HOSTS": "production validator rejects boot without it",
    "CORS_ORIGINS": "production validator rejects boot without it",
    "REDIS_PASSWORD": "production Redis runs --requirepass; NOAUTH without it",
    "POSTGRES_HOST": "no database connection without it",
    "POSTGRES_PASSWORD": "no database connection without it",
    "POSTGRES_DB": "no database connection without it",
    "REDIS_HOST": "no Redis connection without it",
    "FEATURE_SCANNER_ENABLED": "read by the scanner and reported by the API",
    "FEATURE_ENRICHMENT_ENABLED": "read by enrichment and reported by the API",
    "FEATURE_AI_SCORING_ENABLED": "read by enrichment and the beat worker",
    "FEATURE_RADAR_ENABLED": "read by the API and the beat worker",
    "FEATURE_PUMPFUN_RADAR_ENABLED": "read by the Pump.fun Radar beat task",
    # The scanner writes its state and the API reads it; the scanner's own
    # container healthcheck and the API's endpoint must agree on what "down"
    # means, or Docker restarts a service the dashboard calls healthy.
    "SCANNER_RECONNECT_ERROR_ATTEMPTS": "scanner escalates, API reports it degraded",
    "SCANNER_STATE_TTL_SECONDS": "scanner writes the key, API expects it to still exist",
    "HEALTH_SCANNER_DOWN_MINUTES": "read by the API endpoint and the scanner healthcheck",
    # The enrichment worker runs detection and the API reads what it wrote, so
    # the two must agree on whether the engine is on and on what a graduation
    # is. A flag on one service is how this went wrong three times before.
    "FEATURE_OPPORTUNITY_ENGINE_ENABLED": "read by the enrichment worker's detection pass",
    "OPPORTUNITY_BONDING_CURVE_VENUES": "defines the transition; must not differ per service",
    "OPPORTUNITY_GRADUATED_VENUES": "defines the transition; must not differ per service",
    # The enrichment worker collects curve readings and the API reads them back.
    "FEATURE_CURVE_COLLECTION_ENABLED": "read by the enrichment worker's curve pass",
    # The scanner subscribes and the enrichment worker reads accounts. Split
    # across services, the two would talk to different nodes.
    "SOLANA_RPC_PROVIDER": "selects the RPC implementation for every service",
    "SOLANA_RPC_URL": "the endpoint when the provider is not vendor-specific",
    # The enrichment worker stamps a signal's expiry at detection; the beat
    # scheduler decides what has lapsed. Divergent TTLs mean one service opens
    # signals the other closes early, or never closes at all.
    "OPPORTUNITY_TTL_BREAKOUT_SECONDS": "detection stamps expiry, review enforces it",
    "OPPORTUNITY_TTL_PRE_BREAKOUT_SECONDS": "detection stamps expiry, review enforces it",
}

#: Real-wallet execution settings, kept as their own set because the failure
#: they guard against is not a broken feature — it is money moving under a
#: configuration nobody agreed to.
#:
#: The API serves the readiness dashboard, the Celery worker is where an
#: execution would actually run, and the beat scheduler decides when. If those
#: disagree, the dashboard can report `disabled` while the worker executes.
#: Every entry below was absent from the anchor before this sprint, which meant
#: setting it in `.env` changed nothing at all — services silently used code
#: defaults. Safe today only because those defaults are the disabled ones.
EXECUTION_REQUIRED_IN_ANCHOR = {
    "REAL_WALLET_EXECUTION_MODE": "the master control; drift means one service can execute",
    "REAL_WALLET_EXECUTION_ENABLED": "second of three controls that must all agree",
    "REAL_WALLET_AUTOTRADE_ENABLED": "third of three controls that must all agree",
    "REAL_WALLET_NETWORK": "wallet reads must not inherit scanner mainnet RPC",
    "REAL_WALLET_RPC_URL": "wallet RPC endpoint must match the declared network",
    "REAL_WALLET_ALLOWED_RPC_HOSTS": "the endpoint allowlist is a security boundary",
    "REAL_WALLET_ALLOWED_PROGRAM_IDS": (
        "one service must not sign a program another would refuse"
    ),
    "REAL_WALLET_ENTRY_SIZE_USD": "the size the worker spends and the API reports",
    "REAL_WALLET_MAX_DAILY_TRADES": "a count bound only works if every service shares it",
    "REAL_WALLET_MAX_BALANCE_SOL": "the ceiling that makes the blast radius a number",
    "REAL_WALLET_EXIT_MAX_QUOTE_AGE_SECONDS": "exit freshness must be one bound",
    "REAL_WALLET_EXIT_MAX_PRICE_IMPACT_PCT": "exit impact ceiling must be one number",
    "REAL_WALLET_EXIT_MAX_SLIPPAGE_BPS": "exit slippage ceiling must be one number",
    "REAL_WALLET_PUBLIC_KEY": "the pinned wallet; a divergent pin defeats key pinning",
    "REAL_WALLET_EXECUTION_SECRET_FILE": "must be rejected consistently during Phase 1",
    "REAL_WALLET_MAX_TRADE_USD": "a larger limit on the worker turns a $5 canary into more",
    "REAL_WALLET_MAX_OPEN_POSITIONS": "exposure limit the worker enforces and the API shows",
    "REAL_WALLET_MAX_TOTAL_EXPOSURE_USD": "same limit must bind the executor and the report",
    "REAL_WALLET_MAX_DAILY_NOTIONAL_USD": "same limit must bind the executor and the report",
    "REAL_WALLET_MAX_DAILY_LOSS_USD": "loss stop must not differ between decider and reporter",
    "REAL_WALLET_MIN_SOL_FEE_RESERVE": "a position that cannot fund its exit cannot be closed",
    "REAL_WALLET_MAX_CONSECUTIVE_EXECUTION_FAILURES": ("worker trips it, API reports it"),
    "FEATURE_REAL_WALLET_DRY_RUN_ENABLED": "beat enqueues it, worker runs it, API reports it",
    "REAL_WALLET_SAFETY_POLICY_VERSION": "audit rows must name one policy, not two",
    "REAL_WALLET_SAFETY_MAX_MARKET_AGE_SECONDS": (
        "a looser bound admits trades another refuses"
    ),
    "REAL_WALLET_SAFETY_MAX_QUOTE_AGE_SECONDS": (
        "a looser bound admits trades another refuses"
    ),
    "REAL_WALLET_SAFETY_MAX_BUY_PRICE_IMPACT_PCT": "impact ceiling must be one number",
    "REAL_WALLET_SAFETY_MAX_SELL_PRICE_IMPACT_PCT": "exit impact ceiling must be one number",
    "REAL_WALLET_SAFETY_MAX_ROUND_TRIP_LOSS_PCT": "round-trip ceiling must be one number",
    "REAL_WALLET_SAFETY_MAX_POSITION_LIQUIDITY_RATIO": "sizing bound must be one number",
    "REAL_WALLET_SAFETY_MAX_PRICE_DEVIATION_PCT": "deviation bound must be one number",
    "REAL_WALLET_SAFETY_SUPPORTED_VENUES": "the venue allowlist is a security boundary",
    "REAL_WALLET_SAFETY_SUPPORTED_TOKEN_2022_EXTENSIONS": "extension allowlist is a boundary",
    "JUPITER_V2_BASE_URL": "a divergent endpoint is an endpoint nobody reviewed",
    "JUPITER_V2_ORDER_TIMEOUT_SECONDS": "order freshness depends on it",
    "JUPITER_USDC_MINT": "settlement validates the USDC leg against this exact mint",
    "EXECUTION_SOL_PRICE_MAX_AGE_SECONDS": "fee-reserve freshness must be one bound",
    "EXECUTION_SOL_MINT": "the mint fees are priced in",
    "EXECUTION_PRIORITY_FEE_SOL": "reserve headroom must not differ between services",
    "EXECUTION_EXIT_FEE_RESERVE_MULTIPLIER": "exit affordability must be one policy",
}


@pytest.mark.parametrize(("key", "why"), sorted(REQUIRED_IN_ANCHOR.items()))
def test_runtime_critical_setting_is_in_the_shared_anchor(key: str, why: str) -> None:
    assert key in _anchor_keys(), (
        f"{key} must be in the x-backend-env anchor, not on individual services.\n"
        f"Reason: {why}.\n"
        "A setting on one service reaches only that service; the others fall back "
        "to a code default or fail at runtime while the one that has it looks healthy."
    )


@pytest.mark.parametrize(("key", "why"), sorted(EXECUTION_REQUIRED_IN_ANCHOR.items()))
def test_execution_setting_is_in_the_shared_anchor(key: str, why: str) -> None:
    """Every execution control reaches every backend-side service, or none.

    Stricter in consequence than the general contract above: a missing feature
    flag disables a feature, and a missing execution control lets one service
    believe trading is off while another acts as though it is on.
    """
    assert key in _anchor_keys(), (
        f"{key} must be in the x-backend-env anchor.\n"
        f"Reason: {why}.\n"
        "Backend-side services take environment only through `<<: *backend-env`, "
        "so a key outside the anchor silently uses the code default everywhere — "
        "including in the Celery worker, which is where an execution would run."
    )


def _services_using_anchor() -> set[str]:
    """Backend-side services that inherit the shared environment."""
    assert REPO_ROOT is not None
    text = (REPO_ROOT / "docker-compose.yml").read_text()
    services = re.search(r"^services:\n(.*)", text, re.M | re.S)
    assert services is not None
    found: set[str] = set()
    pattern = r"^  ([a-z][a-z0-9_-]*):\n(.*?)(?=^  \S|\Z)"
    for block in re.finditer(pattern, services.group(1), re.M | re.S):
        body = block.group(2)
        if "*backend-env" in body:
            found.add(block.group(1))
    return found


def test_every_backend_side_service_inherits_the_anchor() -> None:
    """The consistency proof: identical values because there is one source.

    Rather than compare four copies of each setting, this asserts there is only
    ever one copy. `<<: *backend-env` is a YAML merge of the same mapping, so a
    service that inherits it cannot hold a different value for an execution
    control unless it also overrides that key — which the next test forbids.
    """
    services = _services_using_anchor()

    assert {"backend", "worker", "scheduler", "scanner", "enrichment"} <= services, (
        "A backend-side service stopped inheriting `<<: *backend-env`: "
        f"found {sorted(services)}. Every service that reads execution settings "
        "must take them from the one shared mapping."
    )


def test_no_service_overrides_an_execution_setting() -> None:
    """Inheritance is only a guarantee while nothing shadows it.

    A YAML merge key lets a service re-declare an inherited key, and the
    re-declaration wins. That is precisely how `REDIS_PASSWORD` drifted, and on
    an execution control it would let one service run with limits or a mode
    that no other service reports.
    """
    assert REPO_ROOT is not None
    guarded = set(EXECUTION_REQUIRED_IN_ANCHOR)
    offenders: list[str] = []

    for name in ("docker-compose.yml", "docker-compose.prod.yml"):
        path = REPO_ROOT / name
        if not path.is_file():
            continue
        text = path.read_text()
        services = re.search(r"^services:\n(.*)", text, re.M | re.S)
        if services is None:
            continue
        for block in re.finditer(
            r"^  ([a-z][a-z0-9_-]*):\n(.*?)(?=^  \S|\Z)", services.group(1), re.M | re.S
        ):
            for key in re.findall(r"^\s+([A-Z][A-Z0-9_]*):", block.group(2), re.M):
                if key in guarded:
                    offenders.append(f"{name}:{block.group(1)}:{key}")

    assert not offenders, (
        "Execution settings are overridden per service: "
        f"{sorted(offenders)}. They belong in the x-backend-env anchor only, so "
        "that the API, the worker and the beat scheduler cannot disagree about "
        "whether trading is enabled or how large a trade may be."
    )


def test_the_committed_defaults_are_the_disabled_ones() -> None:
    """A checkout must never be one `docker compose up` from live trading.

    Asserted against the compose default rather than the Pydantic default: the
    file is what actually reaches a container, and it is what an operator edits.
    """
    assert REPO_ROOT is not None
    text = (REPO_ROOT / "docker-compose.yml").read_text()

    for key, expected in (
        ("REAL_WALLET_EXECUTION_MODE", "disabled"),
        ("REAL_WALLET_EXECUTION_ENABLED", "false"),
        ("REAL_WALLET_AUTOTRADE_ENABLED", "false"),
        ("FEATURE_REAL_WALLET_DRY_RUN_ENABLED", "false"),
    ):
        match = re.search(rf"^  {key}: \$\{{{key}:-([^}}]*)\}}", text, re.M)
        assert match is not None, f"{key} is not declared with a default in the anchor"
        assert match.group(1) == expected, (
            f"{key} defaults to {match.group(1)!r} in docker-compose.yml; it must "
            f"default to {expected!r}. Enabling execution is a deliberate act, "
            "never the state of a fresh checkout."
        )


def test_redis_password_is_not_also_set_per_consumer_service() -> None:
    """The anchor must be the single source, or the two can drift apart.

    This is what disguised occurrence 3: `REDIS_PASSWORD` appeared three times
    in the production overlay, which read as deliberate and complete.

    **`redis` itself is exempt, and only `redis`.** It is the server rather than
    a consumer: it does not inherit the anchor, and its own healthcheck shells
    out to `redis-cli -a "$REDIS_PASSWORD"`, so the variable has to be in its
    environment. Excluding it was missed when this test was written, which made
    the check fail for a legitimate declaration — and because the whole module
    skips inside the backend container, that failure was only ever visible on
    CI. A test that cannot pass gets muted, and a muted test protects nothing.
    """
    assert REPO_ROOT is not None
    overlay = (REPO_ROOT / "docker-compose.prod.yml").read_text()
    services = re.search(r"^services:\n(.*)", overlay, re.M | re.S)
    assert services is not None, "no services block in docker-compose.prod.yml"

    offenders = [
        block.group(1)
        for block in re.finditer(
            r"^  ([a-z][a-z0-9_-]*):\n(.*?)(?=^  \S|\Z)", services.group(1), re.M | re.S
        )
        if block.group(1) != "redis"
        and re.search(r"^\s+REDIS_PASSWORD:", block.group(2), re.M)
    ]

    assert not offenders, (
        f"REDIS_PASSWORD is set on {sorted(offenders)} in "
        "docker-compose.prod.yml. It belongs in the x-backend-env anchor only — "
        "per-service copies are how the scanner and enrichment workers were "
        "missed."
    )


def test_the_scanner_declares_a_healthcheck() -> None:
    """Its absence is why four days of dead discovery went unnoticed.

    `restart: unless-stopped` only sees a live process, and the scanner process
    stayed perfectly alive throughout — reconnecting to a Helius that had run
    out of quota. Without a healthcheck nothing ever asked whether it was still
    finding tokens.
    """
    assert REPO_ROOT is not None
    text = (REPO_ROOT / "docker-compose.yml").read_text()

    scanner = re.search(r"^  scanner:\n(.*?)(?=^  \S)", text, re.M | re.S)
    assert scanner is not None, "scanner service not found in docker-compose.yml"

    assert "healthcheck:" in scanner.group(1), (
        "The scanner service has no healthcheck. A dead scanner reports `Up` "
        "forever without one — see MEMESCOPE_AUDIT.md R1."
    )
    assert "app.health.probe" in scanner.group(1), (
        "The scanner healthcheck must run the discovery probe, not a generic "
        "liveness command: the process being alive is exactly what lied."
    )


def test_every_anchor_key_is_a_real_setting() -> None:
    """Catches the opposite drift: configuration that no longer does anything."""
    from app.core.config import Settings

    known = set(Settings.model_fields)
    # Not Settings fields, but legitimately consumed elsewhere.
    infrastructure = {"RUN_MIGRATIONS", "BUILD_SHA"}

    unknown = _anchor_keys() - known - infrastructure
    assert not unknown, (
        f"Anchor defines settings the application does not read: {sorted(unknown)}. "
        "Either they were renamed in config.py or they are dead configuration."
    )
