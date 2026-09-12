"""`/labs/rafiq` — read-only.

There is no POST, PUT, PATCH or DELETE on this router. The lab trades on its
own tick and nothing else; there is no manual entry, no manual exit and no
activation endpoint, so there is nothing here that a request could ask it to do.

Every figure arrives already computed. A threshold or a rate applied in the
browser would be a second, unpublished rule competing with the one the lab
actually followed, and the two would disagree the first time either changed.

With the flag off every route answers `running: false` rather than an empty
book: "the lab is not running" and "the lab ran and found nothing" are
different facts and must not render identically.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.labs.rafiq import analyst, config, entry_gate, registry
from app.labs.rafiq.adapters import costs
from app.labs.rafiq.feed import RafiqFeed
from app.labs.rafiq.models import (
    RafiqLabGateRejection,
    RafiqLabDailyState,
    RafiqLabPosition,
    RafiqLabStrategy,
)
from app.labs.rafiq.service import RafiqLabService

router = APIRouter(prefix="/labs/rafiq", tags=["rafiq-lab"])


class StrategyOut(BaseModel):
    code: str
    name: str
    lane: str
    #: The one-line question this book exists to answer.
    question: str
    #: Rafiq's frozen constants, published so the page never restates them.
    #: Null for a book with no take profit at all — D2, and C2's second leg.
    take_profit_mult: str | None
    stop_mult: str
    trailing_frac: str | None
    max_hold_hours: str
    entry_threshold: str
    liquidity_derived_risk: bool
    daily_breaker: bool
    consensus_gate: bool
    #: The v2 entry gate this book runs, as published thresholds. Identical
    #: across A2-D2; E2's is stricter.
    gate: dict[str, str]

    starting_equity: str
    #: What execution has cost this book so far: the gap between what its
    #: trades would have been worth filled at the observed mid price, and what
    #: they actually returned after fee and price impact. Published because
    #: "would a real wallet see this number?" is the first question anyone
    #: asks of a paper book, and the honest answer is "yes, minus this".
    execution_cost_usd: str
    cash: str
    #: Cash plus the CURRENT mark of every open position. Never a cost basis.
    equity: str
    realised_pnl: str
    unrealised_pnl: str
    open_positions: int
    closed_trades: int
    wins: int
    losses: int
    #: Realised P&L BEFORE fee and price impact. v1 could not answer "why did
    #: this lose" without hand arithmetic; this is the number that separated
    #: "everything loses" from "B is nearly breakeven and dying to friction".
    gross_pnl_ex_fees: str
    mean_pnl_per_trade_net: str | None
    mean_pnl_per_trade_gross: str | None
    #: How often the gate refused this book an entry, and for which condition.
    #: Cumulative since activation; a reason that never fired shows zero.
    entries_rejected_by_gate: int
    rejection_reason_counts: dict[str, int]
    #: Realised equity after each close, oldest first, seeded at the starting
    #: balance. The curve is derived from the trades rather than stored, so it
    #: can never disagree with them.
    equity_curve: list[str]
    activated_at: datetime


class PositionOut(BaseModel):
    strategy_code: str
    mint_address: str
    symbol: str | None
    opened_at: datetime
    age_seconds: int
    entry_price: str
    quantity: str
    #: 1 for every book but C2, which opens two legs per token.
    leg: int
    cost_basis: str
    stop_price: str
    stop_pct: str
    #: Null when this leg has no take profit.
    target_price: str | None
    trailing_frac: str | None
    max_hold_hours: str
    peak_price: str
    #: Null when nothing has priced this mint yet — never zero.
    last_mark_price: str | None
    current_value: str | None
    unrealised_pnl: str | None
    status: str


class TradeOut(BaseModel):
    strategy_code: str
    mint_address: str
    symbol: str | None
    opened_at: datetime
    closed_at: datetime
    hold_seconds: int
    entry_price: str
    exit_price: str
    exit_observed_price: str
    cost_basis: str
    proceeds_usd: str
    realised_pnl: str
    return_pct: str
    exit_reason: str
    exit_evidence: str | None
    leg: int
    #: What the gate saw, and what execution actually cost on each side.
    entry_liquidity_usd: str | None
    entry_market_cap_usd: str | None
    entry_price_impact_pct: str | None
    exit_price_impact_pct: str | None
    #: Gross is before fee and impact; net is what the book actually booked.
    gross_pnl_usd: str
    fees_usd: str
    net_pnl_usd: str
    #: What the position would fetch now had it never been closed — sold
    #: through the same fee-and-impact model as the exit above, so the two are
    #: comparable. Null when nothing prices the mint any more, which is not
    #: the same claim as zero.
    if_held_value: str | None
    if_held_pct: str | None


class BreakerOut(BaseModel):
    strategy_code: str
    #: True only for E2. The others are reported for comparison and are not
    #: gated by it.
    gates_entries: bool
    day: str
    day_open_equity: str
    realised_today: str
    halted: bool
    halted_reason: str | None
    halted_at: datetime | None


class FigureOut(BaseModel):
    label: str
    value: str
    #: The columns the figure was computed from. Published so a reader can
    #: check the arithmetic rather than take it.
    source: str


class FindingOut(BaseModel):
    key: str
    headline: str
    evidence: str
    #: A quantity that would have to move, never an outcome that would follow.
    #: Empty when the record does not point anywhere yet, which is a finding.
    lever: str
    source: str


class AnalysisOut(BaseModel):
    #: Which HQ desk answers for this strategy, resolved server-side.
    #:
    #: Published so the browser never has to map a code to a person. That map
    #: used to live in TypeScript AND in Python, and when the lab shipped v2
    #: with new codes the two agreed with each other and disagreed with the
    #: database — five desks went dark and no test could see it, because both
    #: copies were still consistent. One source, sent over the wire.
    analyst: str | None
    code: str
    lane: str
    #: False when the strategy has no trades to read. The reason is in
    #: `detail`, and there is nothing behind it to render as a zero.
    measured: bool
    detail: str
    observed_at: datetime
    verdict: str
    open_positions: int
    closed_positions: int
    figures: list[FigureOut]
    findings: list[FindingOut]


class StatusOut(BaseModel):
    running: bool
    starting_equity: str
    strategies: list[StrategyOut]


def _q(v: Decimal | None) -> str | None:
    return None if v is None else str(v)


def _execution_cost(positions) -> Decimal:
    """Fee and price impact already deducted from this book.

    Entry drag is what the fill cost above the observed price; exit drag is
    what the sale returned below it. Both are computed from columns written at
    the time, so this is a measurement rather than an assumed slippage figure.
    """
    total = Decimal(0)
    for p in positions:
        if p.entry_observed_price and p.entry_observed_price > 0:
            ideal = p.cost_basis / p.entry_observed_price
            total += (ideal - p.quantity) * p.entry_observed_price
        if p.status == "closed" and p.exit_observed_price is not None:
            gross = p.quantity * p.exit_observed_price
            total += gross - (p.exit_proceeds_usd or Decimal(0))
    return total


async def _rows(session: AsyncSession):
    strategies = list((await session.execute(
        select(RafiqLabStrategy).order_by(RafiqLabStrategy.code)
    )).scalars())
    positions = list((await session.execute(
        select(RafiqLabPosition).order_by(RafiqLabPosition.opened_at)
    )).scalars())
    rejected: dict = {}
    for r in (await session.execute(select(RafiqLabGateRejection))).scalars():
        rejected.setdefault(r.strategy_id, {})[r.reason] = r.rejections
    return strategies, positions, rejected


@router.get("/status", response_model=StatusOut)
async def status(session: AsyncSession = Depends(get_db)) -> StatusOut:
    """Five books, each from its own $1,000. Nothing is recomputed downstream."""
    if not config.enabled():
        return StatusOut(running=False, starting_equity=str(config.STARTING_EQUITY),
                         strategies=[])
    rows, all_positions, rejected = await _rows(session)
    out: list[StrategyOut] = []
    for row in rows:
        spec = registry.BY_CODE[row.code]
        mine = [p for p in all_positions if p.strategy_id == row.id]
        closed = [p for p in mine if p.status == "closed"]
        openp = [p for p in mine if p.status == "open"]
        cash = RafiqLabService.cash(row, mine)
        marked = sum((RafiqLabService._value(p) for p in openp), Decimal(0))
        pnl = [(p.exit_proceeds_usd or Decimal(0)) - p.cost_basis for p in closed]
        curve, running_equity = [str(row.starting_equity)], row.starting_equity
        for delta in pnl:
            running_equity += delta
            curve.append(str(running_equity))
        x = spec.profile.exits
        out.append(StrategyOut(
            code=row.code, name=spec.name, lane=row.lane, question=spec.question,
            take_profit_mult=_q(x.take_profit_mult), stop_mult=str(x.stop_mult),
            trailing_frac=_q(x.trailing_frac),
            max_hold_hours=str(Decimal(x.max_hold.total_seconds()) / 3600),
            entry_threshold=str(spec.profile.entry_threshold),
            liquidity_derived_risk=spec.liquidity_derived_risk,
            daily_breaker=spec.daily_breaker, consensus_gate=spec.consensus_gate,
            gate={k: str(v) for k, v in spec.gate.canonical.items()},
            starting_equity=str(row.starting_equity),
            execution_cost_usd=str(_execution_cost(mine)), cash=str(cash),
            equity=str(cash + marked), realised_pnl=str(sum(pnl, Decimal(0))),
            unrealised_pnl=str(marked - sum((p.cost_basis for p in openp), Decimal(0))),
            open_positions=len(openp), closed_trades=len(closed),
            wins=sum(1 for d in pnl if d > 0), losses=sum(1 for d in pnl if d <= 0),
            gross_pnl_ex_fees=str(sum(pnl, Decimal(0)) + _execution_cost(closed)),
            mean_pnl_per_trade_net=(
                None if not pnl else str(sum(pnl, Decimal(0)) / len(pnl))),
            mean_pnl_per_trade_gross=(
                None if not pnl else
                str((sum(pnl, Decimal(0)) + _execution_cost(closed)) / len(pnl))),
            entries_rejected_by_gate=sum(rejected.get(row.id, {}).values()),
            rejection_reason_counts={
                reason: rejected.get(row.id, {}).get(reason, 0)
                for reason in entry_gate.REASONS},
            equity_curve=curve, activated_at=row.activated_at))
    return StatusOut(running=True, starting_equity=str(config.STARTING_EQUITY),
                     strategies=out)


@router.get("/positions", response_model=list[PositionOut])
async def positions(session: AsyncSession = Depends(get_db)) -> list[PositionOut]:
    """Everything still open, with its age and what it is worth right now."""
    if not config.enabled():
        return []
    rows, all_positions, rejected = await _rows(session)
    codes = {r.id: r.code for r in rows}
    now = datetime.now(UTC)
    out = []
    for p in [x for x in all_positions if x.status == "open"]:
        value = RafiqLabService._value(p)
        out.append(PositionOut(
            strategy_code=codes[p.strategy_id], mint_address=p.mint_address,
            symbol=p.symbol, opened_at=p.opened_at,
            age_seconds=int((now - p.opened_at).total_seconds()),
            entry_price=str(p.entry_price), quantity=str(p.quantity), leg=p.leg,
            cost_basis=str(p.cost_basis), stop_price=str(p.stop_price),
            stop_pct=str(p.stop_pct), target_price=_q(p.target_price),
            trailing_frac=_q(p.trailing_frac),
            max_hold_hours=str(Decimal(p.max_hold_seconds) / 3600),
            peak_price=str(p.peak_price), last_mark_price=_q(p.last_mark_price),
            current_value=str(value), unrealised_pnl=str(value - p.cost_basis),
            status=p.status))
    return out


@router.get("/trades", response_model=list[TradeOut])
async def trades(session: AsyncSession = Depends(get_db)) -> list[TradeOut]:
    """Every closed trade, newest first, with the evidence for its exit."""
    if not config.enabled():
        return []
    rows, all_positions, rejected = await _rows(session)
    codes = {r.id: r.code for r in rows}
    closed = sorted([p for p in all_positions if p.status == "closed"],
                    key=lambda p: p.closed_at, reverse=True)
    # One query for every mint, not one per trade: the freshest price each
    # still has. A mint nothing has priced recently is simply absent, and the
    # rows built from it report null rather than zero.
    marks = await RafiqFeed(session).latest_marks({p.mint_address for p in closed})
    out = []
    for p in closed:
        mark = marks.get(p.mint_address)
        # Priced through the SAME execution model as the exit it sits beside:
        # fee and price impact against the pool as it stands now. A naive
        # `quantity x price` here would flatter every row, and worst exactly
        # where it misleads most — a pool whose liquidity has collapsed shows a
        # handsome paper mark and cannot absorb a sale at all.
        held_value = (None if mark is None
                      else costs.sell_proceeds(p.quantity, mark[0], mark[1]))
        proceeds = p.exit_proceeds_usd or Decimal(0)
        out.append(TradeOut(
            strategy_code=codes[p.strategy_id], mint_address=p.mint_address,
            symbol=p.symbol, opened_at=p.opened_at, closed_at=p.closed_at,
            hold_seconds=int((p.closed_at - p.opened_at).total_seconds()),
            entry_price=str(p.entry_price), exit_price=str(p.exit_price),
            exit_observed_price=str(p.exit_observed_price),
            cost_basis=str(p.cost_basis), proceeds_usd=str(proceeds),
            realised_pnl=str(proceeds - p.cost_basis),
            return_pct=str((proceeds / p.cost_basis - 1) * 100),
            exit_reason=p.exit_reason or "", exit_evidence=p.exit_evidence,
            leg=p.leg,
            entry_liquidity_usd=_q(p.entry_liquidity_usd),
            entry_market_cap_usd=_q(p.entry_market_cap_usd),
            entry_price_impact_pct=_q(p.entry_price_impact_pct),
            exit_price_impact_pct=_q(p.exit_price_impact_pct),
            gross_pnl_usd=str(proceeds - p.cost_basis + _execution_cost([p])),
            fees_usd=str(_execution_cost([p])),
            net_pnl_usd=str(proceeds - p.cost_basis),
            if_held_value=_q(held_value),
            if_held_pct=(None if held_value is None
                         else str((held_value / p.cost_basis - 1) * 100))))
    return out


@router.get("/breaker", response_model=list[BreakerOut])
async def breaker(session: AsyncSession = Depends(get_db)) -> list[BreakerOut]:
    """Today's daily state per strategy. D and E are gated by it; the rest are
    shown so a reader can see what the breaker would have done to them."""
    if not config.enabled():
        return []
    rows, _, _ = await _rows(session)
    codes = {r.id: r.code for r in rows}
    states = list((await session.execute(
        select(RafiqLabDailyState).order_by(RafiqLabDailyState.day.desc())
    )).scalars())
    latest: dict[str, RafiqLabDailyState] = {}
    for s in states:
        latest.setdefault(codes[s.strategy_id], s)
    return [BreakerOut(
        strategy_code=code, gates_entries=registry.BY_CODE[code].daily_breaker,
        day=s.day.isoformat(), day_open_equity=str(s.day_open_equity),
        realised_today=str(s.realised_today), halted=s.halted,
        halted_reason=s.halted_reason, halted_at=s.halted_at,
    ) for code, s in sorted(latest.items())]


@router.get("/analysis", response_model=list[AnalysisOut])
async def analysis(session: AsyncSession = Depends(get_db)) -> list[AnalysisOut]:
    """One reading per strategy, computed from that strategy's own trades.

    The desk that a person would ask "why is this losing money?". It answers
    with arithmetic over rows and stops there: nothing here projects a return,
    ranks the strategies against each other, or proposes a rule. Those are the
    claims eight recorded no-edge findings on this platform were unable to
    support, and a page that made them anyway would be the least trustworthy
    thing in the product.

    Answers for every registered strategy including ones that have never
    traded, because "no trades yet" and "trades that found nothing" must not
    render identically.
    """
    if not config.enabled():
        return []
    from app.hq_ops.desk import ANALYST_ORDER

    codes = [s.code for s in registry.STRATEGIES]
    rows = []
    for seat, code in enumerate(codes):
        who = ANALYST_ORDER[seat] if seat < len(ANALYST_ORDER) else None
        rows.append(
            AnalysisOut(analyst=who, **analyst.as_dict(await analyst.analyse(session, code)))
        )
    return rows
