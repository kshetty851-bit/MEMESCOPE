"""`GET /api/v1/arena/*` — the Arena scoreboard. Read-only, no write verb.

Every response is labelled RESEARCH SIMULATION. Arena equity is not Paper
Wallet equity and the two must never be presented as the same number.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.arena import rules
from app.arena.schemas import ArenaBoard, ArenaCandidateOut, ArenaDecisionOut
from app.models.arena import ArenaCandidate, ArenaDecision, ArenaPosition

router = APIRouter(prefix="/arena", tags=["arena"])

DISCLOSURE = (
    "RESEARCH SIMULATION — NOT THE OFFICIAL PAPER WALLET. Five virtual $1,000 "
    "portfolios scoring frozen entry hypotheses against a cash control. No real "
    "or paper position is ever created by this experiment."
)


def _wilson(k: int, n: int) -> tuple[float, float] | None:
    if n == 0:
        return None
    z, p = 1.96, k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (max(0.0, c - h), min(1.0, c + h))


@router.get("", response_model=ArenaBoard, summary="Arena standings (research simulation)")
async def board(session: DbSession) -> ArenaBoard:
    cands = list((await session.execute(select(ArenaCandidate).order_by(ArenaCandidate.code))).scalars())
    out: list[ArenaCandidateOut] = []
    for c in cands:
        closed = list(
            (
                await session.execute(
                    select(ArenaPosition).where(
                        ArenaPosition.candidate_id == c.id, ArenaPosition.status == "closed"
                    )
                )
            ).scalars()
        )
        opens = list(
            (
                await session.execute(
                    select(ArenaPosition).where(
                        ArenaPosition.candidate_id == c.id, ArenaPosition.status == "open"
                    )
                )
            ).scalars()
        )
        pnls = [
            (p.exit_proceeds_usd or Decimal(0)) - p.size_usd for p in closed
        ]
        wins = [x for x in pnls if x > 0]
        losses = [x for x in pnls if x <= 0]
        gross_w = sum(wins) or Decimal(0)
        gross_l = -sum(losses) if losses else Decimal(0)
        deployed = sum((p.size_usd for p in opens), Decimal(0))
        equity = c.cash + deployed
        skipped = int(
            await session.scalar(
                select(func.count()).select_from(ArenaDecision).where(
                    ArenaDecision.candidate_id == c.id, ArenaDecision.eligible.is_(False)
                )
            ) or 0
        )
        routes = dict(
            (
                await session.execute(
                    select(ArenaDecision.route_state, func.count())
                    .where(ArenaDecision.candidate_id == c.id)
                    .group_by(ArenaDecision.route_state)
                )
            ).all()
        )
        ci = _wilson(len(wins), len(closed))
        out.append(
            ArenaCandidateOut(
                code=c.code, name=c.name, version=c.version, status=c.status,
                failed_reason=c.failed_reason,
                starting_equity=c.starting_equity, equity=equity, cash=c.cash,
                deployed=deployed,
                realized_pnl=sum(pnls, Decimal(0)),
                total_return=((equity - c.starting_equity) / c.starting_equity)
                if c.starting_equity else Decimal(0),
                trades=len(closed), wins=len(wins), losses=len(losses),
                win_rate=(Decimal(len(wins)) / len(closed)) if closed else None,
                win_rate_ci_low=(Decimal(str(round(ci[0], 4))) if ci else None),
                win_rate_ci_high=(Decimal(str(round(ci[1], 4))) if ci else None),
                expectancy=(sum(pnls, Decimal(0)) / len(closed)) if closed else None,
                profit_factor=(gross_w / gross_l) if gross_l > 0 else None,
                avg_win=(gross_w / len(wins)) if wins else None,
                avg_loss=(-gross_l / len(losses)) if losses else None,
                max_drawdown=((c.peak_equity - equity) / c.peak_equity)
                if c.peak_equity else Decimal(0),
                open_positions=len(opens), skipped=skipped,
                buy_failures=int(routes.get("BUY_FAILED", 0)),
                sell_failures=int(routes.get("BUY_OK_SELL_FAILED", 0)),
                route_unknown=int(routes.get("ROUTE_UNKNOWN", 0)),
                reached_125=sum(1 for p in closed if p.reached_125),
                reached_150=sum(1 for p in closed if p.reached_150),
                reached_200=sum(1 for p in closed if p.reached_200),
            )
        )
    return ArenaBoard(
        candidates=out, checkpoint_minutes=rules.CHECKPOINT_MINUTES,
        rules_version=rules.RULES_VERSION,
        valid_from=(cands[0].valid_from if cands else None),
        disclosure=DISCLOSURE, observed_at=datetime.now(UTC),
    )


@router.get("/decisions", response_model=list[ArenaDecisionOut], summary="Decision ledger")
async def decisions(
    session: DbSession,
    code: Annotated[str | None, Query(max_length=2)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ArenaDecisionOut]:
    """What each candidate decided — including what it refused, and why."""
    stmt = (
        select(ArenaDecision, ArenaCandidate.code)
        .join(ArenaCandidate, ArenaCandidate.id == ArenaDecision.candidate_id)
        .order_by(ArenaDecision.checkpoint_at.desc())
        .limit(limit)
    )
    if code:
        stmt = stmt.where(ArenaCandidate.code == code.upper())
    return [
        ArenaDecisionOut(
            code=c, mint_address=d.mint_address, checkpoint_at=d.checkpoint_at,
            eligible=d.eligible, skip_reason=d.skip_reason, route_state=d.route_state,
            features=d.features,
        )
        for d, c in (await session.execute(stmt)).all()
    ]
