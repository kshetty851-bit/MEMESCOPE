"""Read-only token-security evidence.

Every route here reads stored rows. None of them can trigger an evaluation,
open a position, request a wallet, build a transaction, clear a kill switch,
or change a strategy — the service that *writes* evidence is reachable only
from the paper review pass and the offline analysis script, never from HTTP.

That is deliberate: an endpoint that evaluated on demand would be an
unauthenticated way to make the platform issue arbitrary RPC calls.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.core.config import settings
from app.security.contract import (
    EVALUATION_FRESHNESS,
    EVALUATOR_VERSION,
    TokenSecurityEvaluation,
)
from app.security.repository import TokenSecurityRepository

router = APIRouter(prefix="/token-security", tags=["token-security"])


def _render(evaluation: TokenSecurityEvaluation, *, now: datetime) -> dict[str, object]:
    """One evaluation, with its own staleness computed server-side.

    `stale` and `stale_checks` are answered here rather than left to the
    client, for the platform's usual reason: a second implementation of a
    freshness rule is a second freshness rule.
    """
    payload = evaluation.as_json()
    payload["stale"] = not evaluation.is_fresh(now=now)
    payload["stale_checks"] = [str(name) for name in evaluation.stale_checks(now=now)]
    return payload


@router.get("/summary", summary="Aggregate token-security activity")
async def summary(
    session: DbSession,
    window_hours: int = Query(default=24, ge=1, le=168),
) -> dict[str, object]:
    """What the shared evaluator has actually done, over a window.

    Returns real zeros when nothing has been evaluated. An empty platform
    reports `source_state: "no_evaluations"` and zero counts — never a
    fabricated healthy status, because "we have checked nothing" and "we
    checked everything and it was fine" are the two readings a security
    panel must never confuse.
    """
    now = datetime.now(UTC)
    since = now - timedelta(hours=window_hours)
    data = await TokenSecurityRepository(session).summary_since(since)

    last = data["last_evaluation_at"]
    if data["total_evaluations"] == 0:
        source_state = "no_evaluations"
    elif last is None or (now - last) > EVALUATION_FRESHNESS:
        source_state = "stale"
    else:
        source_state = "live"

    return {
        "window_hours": window_hours,
        "evaluator_version": EVALUATOR_VERSION,
        "evaluated_recently": data["evaluated_recently"],
        "verified_count": data["verified_count"],
        "failed_count": data["failed_count"],
        "unknown_count": data["unknown_count"],
        "failures_by_reason": data["failures_by_reason"],
        "last_evaluation_at": last,
        "total_evaluations": data["total_evaluations"],
        "source_state": source_state,
        "observed_at": now,
    }


@router.get("/evaluations", summary="Latest security evidence for a batch of mints")
async def batch(
    session: DbSession,
    mints: str = Query(description="Comma-separated mint addresses."),
) -> dict[str, object]:
    """A bounded batch, so a page of Radar rows costs one request.

    The cap is enforced by truncation rather than by rejecting the request,
    and what was dropped is reported: a silently shortened answer reads
    exactly like a complete one.
    """
    now = datetime.now(UTC)
    requested = [value.strip() for value in mints.split(",") if value.strip()]
    unique = list(dict.fromkeys(requested))
    capped = unique[: settings.TOKEN_SECURITY_MAX_BATCH]

    found = await TokenSecurityRepository(session).latest_for_mints(capped)
    return {
        "requested": len(unique),
        "returned": len(found),
        "truncated": len(unique) > len(capped),
        "limit": settings.TOKEN_SECURITY_MAX_BATCH,
        # A requested mint with no evidence is absent from `items` and named
        # here instead. UNKNOWN-by-absence is a real state and the client
        # must be able to tell it apart from a mint it never asked about.
        "without_evidence": [mint for mint in capped if mint not in found],
        "items": {
            mint: _render(evaluation, now=now) for mint, evaluation in found.items()
        },
    }


@router.get("/evaluations/{mint_address}", summary="Security evidence for one mint")
async def for_mint(
    mint_address: str,
    session: DbSession,
    history: int = Query(default=1, ge=1, le=50),
) -> dict[str, object]:
    now = datetime.now(UTC)
    rows = await TokenSecurityRepository(session).history_for_mint(
        mint_address, limit=history
    )
    return {
        "mint_address": mint_address,
        "evaluator_version": EVALUATOR_VERSION,
        "items": [_render(evaluation, now=now) for evaluation in rows],
    }
