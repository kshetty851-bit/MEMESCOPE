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
    # The enrichment worker stamps a signal's expiry at detection; the beat
    # scheduler decides what has lapsed. Divergent TTLs mean one service opens
    # signals the other closes early, or never closes at all.
    "OPPORTUNITY_TTL_BREAKOUT_SECONDS": "detection stamps expiry, review enforces it",
    "OPPORTUNITY_TTL_PRE_BREAKOUT_SECONDS": "detection stamps expiry, review enforces it",
}


@pytest.mark.parametrize(("key", "why"), sorted(REQUIRED_IN_ANCHOR.items()))
def test_runtime_critical_setting_is_in_the_shared_anchor(key: str, why: str) -> None:
    assert key in _anchor_keys(), (
        f"{key} must be in the x-backend-env anchor, not on individual services.\n"
        f"Reason: {why}.\n"
        "A setting on one service reaches only that service; the others fall back "
        "to a code default or fail at runtime while the one that has it looks healthy."
    )


def test_redis_password_is_not_also_set_per_service() -> None:
    """The anchor must be the single source, or the two can drift apart.

    This is what disguised occurrence 3: `REDIS_PASSWORD` appeared three times
    in the production overlay, which read as deliberate and complete.
    """
    assert REPO_ROOT is not None
    overlay = (REPO_ROOT / "docker-compose.prod.yml").read_text()

    # The `redis` service's own --requirepass is a command argument, not an
    # environment key, and is the correct place to demand the value.
    env_assignments = re.findall(r"^\s+REDIS_PASSWORD:", overlay, re.M)

    assert not env_assignments, (
        f"REDIS_PASSWORD is set on {len(env_assignments)} service(s) in "
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
