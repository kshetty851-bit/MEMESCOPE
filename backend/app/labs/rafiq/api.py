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

Every route reads ONE run: the current one by default (G1), or any archived
run by `?run=<lab_run_id>` — `F2-and-earlier` for A2-F2.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.labs.rafiq import analyst, config, entry_gate, registry
from app.labs.rafiq.adapters import costs
from app.labs.rafiq.feed import RafiqFeed
from app.labs.rafiq.models import (
    RafiqLabDailyState,
    RafiqLabGateRejection,
    RafiqLabPosition,
    RafiqLabRunState,
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
    lab_run_id: str
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
    #: False for a retired book: it still settles its open positions under the
    #: geometry frozen on each row, but opens nothing new. Published because a
    #: page showing six books without it reads as six books competing, and
    #: five of them stopped taking entries when F2 started.
    enters: bool
    #: A retired book's numbers are its last, not its current. Only F2's move.
    equity_floor: str | None
    max_trades_per_day: int | None
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
    #: Realised P&L BEFORE fee and price impact — including an open G1 row's
    #: scale-out, like `realised_pnl`. v1 could not answer "why did
    #: this lose" without hand arithmetic; this is the number that separated
    #: "everything loses" from "B is nearly breakeven and dying to friction".
    gross_pnl_ex_fees: str
    #: Per CLOSED trade: a G1 trade counts once, when its last quarter sells.
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
    #: G1 only: the ratchet's floor and the high-water mark it follows. Null
    #: for a book without one.
    ratchet_floor: str | None = None
    ratchet_high_water: str | None = None
    #: G1 only: `Learning.current_parameters()` as the next entry will read it.
    learning: dict | None = None


class PositionOut(BaseModel):
    strategy_code: str
    lab_run_id: str
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
    #: What the part still held would fetch from the pool as last read.
    current_value: str | None
    unrealised_pnl: str | None
    status: str
    #: G1: the share still held (0.25 after the scale-out) and what the
    #: scale-out already returned.
    fraction_open: str
    scaled_out: bool
    realised_usd: str


class TradeOut(BaseModel):
    strategy_code: str
    lab_run_id: str
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
    #: G1: whether 75% was sold at +30% first, and what that sale returned.
    #: `proceeds_usd` above is the whole position's, that sale included.
    scaled_out: bool
    scale_out_proceeds_usd: str
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
    #: The run these books belong to.
    run: str
    starting_equity: str
    strategies: list[StrategyOut]


def _q(v: Decimal | None) -> str | None:
    return None if v is None else str(v)


def _realised_pnl(positions) -> Decimal:
    """P&L already taken: every closed trade, and the scale-out of a G1
    position whose remaining quarter is still open. With `unrealised_pnl`
    over what is still held, the two add up to equity less the start."""
    return sum(
        (((p.exit_proceeds_usd or Decimal(0)) - p.cost_basis) if p.status == "closed"
         else (p.realised_usd - p.cost_basis * (1 - p.fraction_open))
         for p in positions if p.status == "closed" or p.scaled_out),
        Decimal(0),
    )


def _scale_out_cost(p) -> Decimal:
    """Fee and impact behind an open G1 row's scale-out: the sold share of
    the entry's drag, and the partial sale's own."""
    sold = 1 - p.fraction_open
    entry = (p.cost_basis - p.quantity * p.entry_observed_price
             if p.entry_observed_price else Decimal(0))
    return entry * sold + p.quantity * sold * p.scale_out_price - p.realised_usd


def _execution_cost(positions) -> Decimal:
    """Fee and price impact already deducted from this book.

    Entry drag is what the fill cost above the observed price; exit drag is
    what the sale returned below its FILL price. Both are computed from columns
    written at the time, so this is a measurement rather than an assumed
    slippage figure.

    Exit drag is measured from the fill, not the observed print, so it is fee
    and impact and nothing else. Measured from the print it also counted the
    take-profit fill cap and, worst, a dead pool's leftover price — a print
    nobody could sell into, booked as "execution cost". That is how the
    published friction ran at several times the cost model (4.08% of notional
    across A2-F2, of which 1.57% was dead pools and 1.12% the cap).
    """
    total = Decimal(0)
    for p in positions:
        if p.entry_observed_price and p.entry_observed_price > 0:
            ideal = p.cost_basis / p.entry_observed_price
            total += (ideal - p.quantity) * p.entry_observed_price
        if p.scaled_out:
            # The scale-out's drag counts when it sells, open row or not.
            sold = p.quantity * (1 - p.fraction_open)
            total += sold * p.scale_out_price - p.realised_usd
        if p.status == "closed" and p.exit_price is not None:
            final = p.quantity * p.fraction_open
            total += final * p.exit_price - ((p.exit_proceeds_usd or Decimal(0))
                                             - p.realised_usd)
    return total


def _run(run: str | None) -> str:
    return run or registry.CURRENT_RUN


#: `?run=` on every route. Omitted, it is the run the beat trades.
RunParam = Annotated[str | None, Query(max_length=32,
                                       description="lab_run_id; defaults to the current run")]


async def _rows(session: AsyncSession, run: str):
    strategies = list((await session.execute(
        select(RafiqLabStrategy).where(RafiqLabStrategy.lab_run_id == run)
        .order_by(RafiqLabStrategy.code)
    )).scalars())
    ids = [s.id for s in strategies]
    positions = list((await session.execute(
        select(RafiqLabPosition).where(RafiqLabPosition.strategy_id.in_(ids))
        .order_by(RafiqLabPosition.opened_at)
    )).scalars())
    rejected: dict = {}
    for r in (await session.execute(
        select(RafiqLabGateRejection).where(RafiqLabGateRejection.strategy_id.in_(ids))
    )).scalars():
        rejected.setdefault(r.strategy_id, {})[r.reason] = r.rejections
    return strategies, positions, rejected


@router.get("/status", response_model=StatusOut)
async def status(session: AsyncSession = Depends(get_db),
                 run: RunParam = None) -> StatusOut:
    """One run's books, each from its own $1,000. Nothing is recomputed
    downstream."""
    run = _run(run)
    if not config.enabled():
        return StatusOut(running=False, run=run,
                         starting_equity=str(config.STARTING_EQUITY), strategies=[])
    rows, all_positions, rejected = await _rows(session, run)
    state = (await session.execute(
        select(RafiqLabRunState).where(RafiqLabRunState.lab_run_id == run)
    )).scalars().first()
    out: list[StrategyOut] = []
    reader = RafiqLabService(session)
    for row in rows:
        spec = registry.BY_CODE[row.code]
        learned = None
        if spec.g1:
            # Read-only: loaded without creating state, asked, never saved.
            lrn, _ = await reader._learner(row, create=False)
            learned = lrn.current_parameters()
        mine = [p for p in all_positions if p.strategy_id == row.id]
        closed = [p for p in mine if p.status == "closed"]
        openp = [p for p in mine if p.status == "open"]
        cash = RafiqLabService.cash(row, mine)
        marked = sum((RafiqLabService._value(p) for p in openp), Decimal(0))
        pnl = [(p.exit_proceeds_usd or Decimal(0)) - p.cost_basis for p in closed]
        still_at_risk = sum((p.cost_basis * p.fraction_open for p in openp), Decimal(0))
        realised = _realised_pnl(mine)
        # What execution cost the realised part: closed trades whole, and an
        # open G1 row's scale-out.
        realised_cost = _execution_cost(closed) + sum(
            (_scale_out_cost(p) for p in openp if p.scaled_out), Decimal(0))
        curve, running_equity = [str(row.starting_equity)], row.starting_equity
        for delta in pnl:
            running_equity += delta
            curve.append(str(running_equity))
        x = spec.profile.exits
        out.append(StrategyOut(
            code=row.code, lab_run_id=row.lab_run_id, name=spec.name, lane=row.lane,
            question=spec.question,
            take_profit_mult=_q(x.take_profit_mult), stop_mult=str(x.stop_mult),
            trailing_frac=_q(x.trailing_frac),
            max_hold_hours=str(Decimal(x.max_hold.total_seconds()) / 3600),
            entry_threshold=str(spec.profile.entry_threshold),
            liquidity_derived_risk=spec.liquidity_derived_risk,
            daily_breaker=spec.daily_breaker, consensus_gate=spec.consensus_gate,
            # An archived row opens nothing, whatever its code does now.
            enters=spec.enters and row.lab_run_id == registry.CURRENT_RUN,
            equity_floor=_q(spec.equity_floor),
            max_trades_per_day=spec.max_trades_per_day,
            gate={k: str(v) for k, v in spec.gate.canonical.items()},
            starting_equity=str(row.starting_equity),
            execution_cost_usd=str(_execution_cost(mine)), cash=str(cash),
            equity=str(cash + marked), realised_pnl=str(realised),
            unrealised_pnl=str(marked - still_at_risk),
            open_positions=len(openp), closed_trades=len(closed),
            wins=sum(1 for d in pnl if d > 0), losses=sum(1 for d in pnl if d <= 0),
            gross_pnl_ex_fees=str(realised + realised_cost),
            mean_pnl_per_trade_net=(
                None if not pnl else str(sum(pnl, Decimal(0)) / len(pnl))),
            mean_pnl_per_trade_gross=(
                None if not pnl else
                str((sum(pnl, Decimal(0)) + _execution_cost(closed)) / len(pnl))),
            entries_rejected_by_gate=sum(rejected.get(row.id, {}).values()),
            rejection_reason_counts={
                reason: rejected.get(row.id, {}).get(reason, 0)
                for reason in entry_gate.REASONS},
            equity_curve=curve, activated_at=row.activated_at,
            ratchet_floor=_q(state.ratchet_floor) if spec.g1 and state else None,
            ratchet_high_water=(_q(state.ratchet_high_water)
                                if spec.g1 and state else None),
            learning=learned))
    return StatusOut(running=True, run=run, starting_equity=str(config.STARTING_EQUITY),
                     strategies=out)


@router.get("/positions", response_model=list[PositionOut])
async def positions(session: AsyncSession = Depends(get_db),
                    run: RunParam = None) -> list[PositionOut]:
    """Everything still open, with its age and what it is worth right now."""
    if not config.enabled():
        return []
    rows, all_positions, _ = await _rows(session, _run(run))
    codes = {r.id: r.code for r in rows}
    now = datetime.now(UTC)
    out = []
    for p in [x for x in all_positions if x.status == "open"]:
        value = RafiqLabService._value(p)
        out.append(PositionOut(
            strategy_code=codes[p.strategy_id], lab_run_id=p.lab_run_id,
            mint_address=p.mint_address,
            symbol=p.symbol, opened_at=p.opened_at,
            age_seconds=int((now - p.opened_at).total_seconds()),
            entry_price=str(p.entry_price), quantity=str(p.quantity), leg=p.leg,
            cost_basis=str(p.cost_basis), stop_price=str(p.stop_price),
            stop_pct=str(p.stop_pct), target_price=_q(p.target_price),
            trailing_frac=_q(p.trailing_frac),
            max_hold_hours=str(Decimal(p.max_hold_seconds) / 3600),
            peak_price=str(p.peak_price), last_mark_price=_q(p.last_mark_price),
            current_value=str(value),
            unrealised_pnl=str(value - p.cost_basis * p.fraction_open),
            status=p.status, fraction_open=str(p.fraction_open),
            scaled_out=p.scaled_out, realised_usd=str(p.realised_usd)))
    return out


@router.get("/trades", response_model=list[TradeOut])
async def trades(session: AsyncSession = Depends(get_db),
                 run: RunParam = None) -> list[TradeOut]:
    """Every closed trade, newest first, with the evidence for its exit."""
    if not config.enabled():
        return []
    rows, all_positions, _ = await _rows(session, _run(run))
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
            strategy_code=codes[p.strategy_id], lab_run_id=p.lab_run_id,
            mint_address=p.mint_address,
            symbol=p.symbol, opened_at=p.opened_at, closed_at=p.closed_at,
            hold_seconds=int((p.closed_at - p.opened_at).total_seconds()),
            entry_price=str(p.entry_price), exit_price=str(p.exit_price),
            exit_observed_price=str(p.exit_observed_price),
            cost_basis=str(p.cost_basis), proceeds_usd=str(proceeds),
            realised_pnl=str(proceeds - p.cost_basis),
            return_pct=str((proceeds / p.cost_basis - 1) * 100),
            exit_reason=p.exit_reason or "", exit_evidence=p.exit_evidence,
            leg=p.leg, scaled_out=p.scaled_out,
            scale_out_proceeds_usd=str(p.realised_usd),
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
async def breaker(session: AsyncSession = Depends(get_db),
                  run: RunParam = None) -> list[BreakerOut]:
    """Today's daily state per book in the run. Books with `daily_breaker` are
    gated by it; the rest are shown so a reader can see what it would have
    done to them."""
    if not config.enabled():
        return []
    rows, _, _ = await _rows(session, _run(run))
    codes = {r.id: r.code for r in rows}
    states = list((await session.execute(
        select(RafiqLabDailyState).where(RafiqLabDailyState.strategy_id.in_(list(codes)))
        .order_by(RafiqLabDailyState.day.desc())
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
async def analysis(session: AsyncSession = Depends(get_db),
                   run: RunParam = None) -> list[AnalysisOut]:
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

    run = _run(run)
    codes = [s.code for s in registry.RUNS.get(run, ())]
    rows = []
    for seat, code in enumerate(codes):
        who = ANALYST_ORDER[seat] if seat < len(ANALYST_ORDER) else None
        reading = await analyst.analyse(session, code, run=run)
        rows.append(AnalysisOut(analyst=who, **analyst.as_dict(reading)))
    return rows
