"""Orchestration. **Reads market data, writes only `strategy_lab_*`.**

Two entry points, and the difference between them is only *when* the same
resolver runs:

  * `run_backtest` — replay every matured canonical opportunity from scratch and
    persist the book. Idempotent by replacement: a new run supersedes the old
    one, and the old one is deleted rather than merged, because two runs over
    overlapping populations must never be summed.
  * `evaluate_forward` — one incremental tick. Settle open positions against
    observations that arrived since they were last seen, *then* offer new
    opportunities with whatever cash that freed.

`rules.resolve` is called by both. Forward research passes a `Resume`; the
backtest does not. There is no second implementation to keep in agreement.

── WHY EXITS SETTLE BEFORE ENTRIES ──────────────────────────────────────────

The same ordering the live Paper Wallet uses, for the same reason: cash
returned by a position that closed this tick must be available to the entries
considered in the same tick, or a strategy's capture rate would depend on how
often the scheduler happened to run.

── WHAT THIS MODULE CANNOT DO ───────────────────────────────────────────────

It imports no signer, no RPC client, no transaction builder, and nothing from
`app.real_wallet`. `LabState` has no live member, so no code path here can be
configured into one. The isolation test asserts both.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.strategy_lab import (
    StrategyLabFill,
    StrategyLabOpportunity,
    StrategyLabPosition,
    StrategyLabRefusal,
    StrategyLabWallet,
)
from app.strategy_lab import execution, metrics, opportunities, replay, repository, rules
from app.strategy_lab.state import LabState
from app.strategy_lab.strategies import ALL, StrategyDefinition

logger = logging.getLogger(__name__)

_ZERO = Decimal(0)

#: How many new opportunities one forward tick will offer a wallet. A bound, not
#: a policy: the anti-join means anything left over is picked up next tick, so a
#: burst of discoveries is spread across ticks rather than dropped.
FORWARD_BATCH = 400


def current_state() -> LabState:
    """The configured mode. Defaults to DISABLED — research opts in, never out."""
    raw = getattr(settings, "STRATEGY_LAB_MODE", None) or LabState.DISABLED.value
    try:
        return LabState(str(raw).upper())
    except ValueError:
        logger.warning("strategy_lab: unknown mode %r, treating as DISABLED", raw)
        return LabState.DISABLED


@dataclass(frozen=True, slots=True)
class BacktestSummary:
    run_id: uuid.UUID
    candidates: int
    usable: int
    exclusions: dict[str, int]
    rows: tuple[metrics.Row, ...]
    dataset_from: datetime | None
    dataset_to: datetime | None
    observation_count: int
    venues: dict[str, int]


async def run_backtest(
    session: AsyncSession,
    *,
    starting_capital: Decimal = replay.STARTING_CAPITAL,
    now: datetime | None = None,
    supersede: bool = True,
) -> BacktestSummary:
    """Replay every strategy over the canonical stream and store the result."""
    now = now or datetime.now(UTC)
    await repository.register_all(session, ALL)

    loaded = await opportunities.load(session, now=now)
    usable = [o for o in loaded if o.usable]
    exclusions: dict[str, int] = {}
    for o in loaded:
        if o.excluded_reason:
            exclusions[o.excluded_reason] = exclusions.get(o.excluded_reason, 0) + 1
    venues: dict[str, int] = {}
    for o in usable:
        key = o.venue or "unknown"
        venues[key] = venues.get(key, 0) + 1

    previous = await repository.latest_run(session, mode=LabState.BACKTEST.value)
    run = await repository.create_run(
        session,
        mode=LabState.BACKTEST.value,
        metrics_version=metrics.METRICS_VERSION,
        rules_version=rules.MULTI_TARGET_POLICY,
        dataset_from=min((o.eligible_at for o in usable), default=None),
        dataset_to=max((o.eligible_at for o in usable), default=None),
        candidates=len(loaded),
        usable=len(usable),
        exclusions=exclusions,
        venues=venues,
        observation_count=sum(len(o.quotes) for o in usable),
        notes=execution.DISCLOSURE,
    )

    opportunity_ids = await repository.upsert_opportunities(session, loaded)

    rows: list[metrics.Row] = []
    for definition in ALL:
        result = replay.run(definition, usable, starting_capital=starting_capital)
        wallet = await repository.get_or_create_wallet(
            session,
            definition=definition,
            mode=LabState.BACKTEST.value,
            starting_balance=starting_capital,
            run_id=run.id,
        )
        await repository.persist_positions(
            session,
            wallet=wallet,
            opportunity_ids=opportunity_ids,
            positions=result.positions,
            refusals=result.missed,
            final_cash=result.final_cash,
            equity_curve=result.equity_curve,
        )
        rows.append(metrics.row(result, name=definition.name, benchmark=definition.benchmark))

    run.finished_at = datetime.now(UTC)
    if supersede and previous is not None:
        # Deleted, never merged: two runs over overlapping populations are not
        # additive, and keeping both invites exactly that mistake.
        await repository.delete_run(session, previous.id)
    await session.commit()

    return BacktestSummary(
        run_id=run.id,
        candidates=len(loaded),
        usable=len(usable),
        exclusions=exclusions,
        rows=tuple(rows),
        dataset_from=run.dataset_from,
        dataset_to=run.dataset_to,
        observation_count=run.observation_count,
        venues=venues,
    )


@dataclass(frozen=True, slots=True)
class ForwardTick:
    state: str
    new_opportunities: int
    positions_opened: int
    positions_closed: int
    fills_booked: int
    refusals: int
    wallets: int
    skipped_reason: str | None = None


async def evaluate_forward(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    starting_capital: Decimal = replay.STARTING_CAPITAL,
) -> ForwardTick:
    """One incremental tick of continuous research. Safe to call repeatedly.

    Idempotent in both directions. An observation already folded into a
    position's stored state is never re-read, because `quotes_since` is
    exclusive on `evaluated_through`. An opportunity already taken or refused is
    never re-offered, because the candidate query anti-joins both tables. A
    crash between the two halves loses nothing: the next tick redoes exactly the
    work that did not commit.
    """
    state = current_state()
    if state is not LabState.FORWARD_RESEARCH:
        return ForwardTick(
            state=state.value,
            new_opportunities=0,
            positions_opened=0,
            positions_closed=0,
            fills_booked=0,
            refusals=0,
            wallets=0,
            skipped_reason=f"strategy lab mode is {state.value}",
        )

    now = now or datetime.now(UTC)
    await repository.register_all(session, ALL)

    new_opportunities = await _ingest(session, now=now)

    wallets: dict[str, StrategyLabWallet] = {}
    for definition in ALL:
        wallet = await repository.get_or_create_wallet(
            session,
            definition=definition,
            mode=LabState.FORWARD_RESEARCH.value,
            starting_balance=starting_capital,
        )
        wallets[definition.strategy_id] = wallet

    closed = fills = opened = refused = 0
    for definition in ALL:
        wallet = wallets[definition.strategy_id]
        # Exits first. Cash freed here funds the entries considered below.
        c, f = await _settle(session, wallet=wallet, definition=definition, now=now)
        closed += c
        fills += f
        o, r = await _offer(session, wallet=wallet, definition=definition, now=now)
        opened += o
        refused += r

    await session.commit()
    return ForwardTick(
        state=state.value,
        new_opportunities=new_opportunities,
        positions_opened=opened,
        positions_closed=closed,
        fills_booked=fills,
        refusals=refused,
        wallets=len(wallets),
    )


async def _ingest(session: AsyncSession, *, now: datetime) -> int:
    """Freeze canonical opportunities that became eligible since the last tick.

    Bounded by the newest opportunity already stored, less a small overlap. The
    overlap exists because a Radar decision can be written a moment after the
    instant it describes, and a strictly-greater cursor would step over it.
    `upsert_opportunities` is conflict-free, so re-reading is harmless.
    """
    latest = (
        await session.execute(select(func.max(StrategyLabOpportunity.eligible_at)))
    ).scalar_one_or_none()
    since = (latest - timedelta(minutes=30)) if latest is not None else None

    loaded = await opportunities.load(session, since=since, now=now)
    if not loaded:
        return 0
    before = (
        await session.execute(select(func.count()).select_from(StrategyLabOpportunity))
    ).scalar_one()
    await repository.upsert_opportunities(session, loaded)
    after = (
        await session.execute(select(func.count()).select_from(StrategyLabOpportunity))
    ).scalar_one()
    return int(after - before)


async def _settle(
    session: AsyncSession,
    *,
    wallet: StrategyLabWallet,
    definition: StrategyDefinition,
    now: datetime,
) -> tuple[int, int]:
    """Advance every open position by the observations it has not seen."""
    positions = await repository.open_positions(session, wallet.id)
    closed = booked = 0

    for position in positions:
        after = position.evaluated_through or position.opened_at
        expires_at = position.opened_at + definition.rules.hold_for
        quotes = await repository.quotes_since(
            session,
            mint=position.mint_address,
            pool=position.pool_address,
            after=after,
            until=min(now, expires_at + opportunities.TAIL),
        )

        resume = rules.Resume(
            remaining_quantity=position.remaining_quantity,
            filled_rungs=frozenset(position.filled_rungs or ()),
            fired_decay=frozenset(position.fired_decay or ()),
            armed=position.trail_armed,
            high=position.trail_high or _ZERO,
            observed_peak_multiple=position.observed_peak_multiple or _ZERO,
            executable_peak_multiple=position.executable_peak_multiple or _ZERO,
            batch_rung_fills=position.batch_rung_fills,
            last_executable_price=None,
        )
        outcome = rules.resolve(
            definition.rules,
            entry_price=position.entry_price,
            opened_at=position.opened_at,
            initial_quantity=position.initial_quantity,
            quotes=quotes,
            resume=resume,
        )

        fills = list(outcome.fills)
        unsettled = False
        if (
            not outcome.closed
            and outcome.remaining_quantity > 0
            and now >= expires_at + opportunities.TAIL
        ):
            # The clock and the grace window have both passed with nothing to
            # settle on. Mark it, label it, and stop carrying it as open.
            tail = rules.settle_unobserved(
                remaining_quantity=outcome.remaining_quantity,
                last_quote=quotes[-1] if quotes else None,
                at=expires_at,
                last_executable_price=outcome.last_executable_price,
            )
            if tail is not None:
                fills.append(tail)
                unsettled = True

        if fills:
            sequence = await repository.next_fill_sequence(session, position.id)
            for fill in fills:
                net, cost = execution.sell(fill.quantity, fill.price_usd, fill.liquidity_usd)
                session.add(
                    StrategyLabFill(
                        position_id=position.id,
                        sequence=sequence,
                        filled_at=fill.at,
                        reason=str(fill.reason),
                        price_usd=fill.price_usd,
                        quantity=fill.quantity,
                        liquidity_usd=fill.liquidity_usd,
                        rung_indexes=list(fill.rung_indexes),
                        trigger_price=fill.trigger_price,
                        gross_proceeds=fill.gross_proceeds,
                        execution_cost=cost,
                        net_proceeds=net,
                    )
                )
                sequence += 1
                booked += 1
                wallet.cash = wallet.cash + net
                position.remaining_quantity = position.remaining_quantity - fill.quantity

        position.filled_rungs = sorted(outcome.filled_rungs)
        position.trail_armed = _armed_after(definition, outcome, position)
        position.observed_peak_multiple = _cap(outcome.observed_peak_multiple)
        position.executable_peak_multiple = _cap(outcome.executable_peak_multiple)
        position.terminal_multiple = _cap(outcome.terminal_multiple)
        position.batch_rung_fills = outcome.batch_rung_fills
        if quotes:
            position.evaluated_through = quotes[-1].captured_at
        if outcome.remaining_quantity <= 0 or unsettled:
            position.remaining_quantity = _ZERO
            position.closed_at = fills[-1].at if fills else now
            position.close_reason = str(fills[-1].reason) if fills else "expiry"
            position.unsettled = unsettled
            closed += 1

    await session.flush()
    return closed, booked


def _armed_after(
    definition: StrategyDefinition, outcome: rules.Outcome, position: StrategyLabPosition
) -> bool:
    """Whether the trail is armed once this pass is folded in.

    Derived from the peak rather than returned by the resolver: arming is
    exactly "the executable path reached the activation multiple", and that is
    a fact the outcome already carries. A second channel for it would be a
    second thing to keep in agreement.
    """
    trailing = definition.rules.trailing
    if trailing is None:
        return False
    if trailing.activation_multiple is None:
        return True
    return (
        position.trail_armed
        or outcome.executable_peak_multiple >= trailing.activation_multiple
    )


def _cap(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return min(value, Decimal("999999999999"))


async def _offer(
    session: AsyncSession,
    *,
    wallet: StrategyLabWallet,
    definition: StrategyDefinition,
    now: datetime,
) -> tuple[int, int]:
    """Offer every unseen canonical opportunity, in the order it arrived."""
    candidates = await repository.unoffered_opportunities(
        session,
        wallet_id=wallet.id,
        # Never before the wallet existed. See `unoffered_opportunities`: a
        # forward record that swept up history would not be out of sample.
        since=wallet.created_at,
        limit=FORWARD_BATCH,
    )
    opened = refused = 0

    for candidate in candidates:
        refusal = _refusal_for(definition, candidate, wallet)
        if refusal is not None:
            session.add(
                StrategyLabRefusal(
                    wallet_id=wallet.id,
                    opportunity_id=candidate.id,
                    mint_address=candidate.mint_address,
                    refused_at=candidate.eligible_at,
                    reason=refusal,
                    cash_at_refusal=wallet.cash,
                    peak_multiple=None,
                )
            )
            refused += 1
            continue

        entry_cost = execution.buy(definition.entry_size_usd, candidate.liquidity_usd)
        quantity = (definition.entry_size_usd - entry_cost) / candidate.entry_price
        if quantity <= 0:
            session.add(
                StrategyLabRefusal(
                    wallet_id=wallet.id,
                    opportunity_id=candidate.id,
                    mint_address=candidate.mint_address,
                    refused_at=candidate.eligible_at,
                    reason=replay.Refusal.UNPRICEABLE,
                    cash_at_refusal=wallet.cash,
                    peak_multiple=None,
                )
            )
            refused += 1
            continue

        wallet.cash = wallet.cash - definition.entry_size_usd
        session.add(
            StrategyLabPosition(
                wallet_id=wallet.id,
                opportunity_id=candidate.id,
                mint_address=candidate.mint_address,
                opened_at=candidate.eligible_at,
                entry_price=candidate.entry_price,
                size_usd=definition.entry_size_usd,
                initial_quantity=quantity,
                remaining_quantity=quantity,
                entry_cost=entry_cost,
                entry_liquidity_usd=candidate.liquidity_usd,
                venue=candidate.venue,
                pool_address=candidate.pool_address,
                filled_rungs=[],
                fired_decay=[],
                trail_armed=(
                    definition.rules.trailing is not None
                    and definition.rules.trailing.activation_multiple is None
                ),
                trail_high=(
                    candidate.entry_price
                    if definition.rules.trailing is not None
                    and definition.rules.trailing.activation_multiple is None
                    else None
                ),
                evaluated_through=candidate.eligible_at,
            )
        )
        opened += 1

    await session.flush()
    return opened, refused


def _refusal_for(
    definition: StrategyDefinition,
    candidate: StrategyLabOpportunity,
    wallet: StrategyLabWallet,
) -> str | None:
    """The same decision `replay._refuse` makes, against a stored row.

    Checked in the same order for the same reason: an S9 refusal must be
    attributed to its gate rather than to whatever the wallet happened to hold,
    or the hypothesis under test would be hidden behind a cash figure.
    """
    if definition.min_discovery_age is not None:
        age = candidate.discovery_age_seconds
        if age is None or age < Decimal(definition.min_discovery_age.total_seconds()):
            return replay.Refusal.AGE_GATE
    if candidate.entry_price is None or candidate.entry_price <= 0:
        return replay.Refusal.UNPRICEABLE
    if wallet.cash < definition.entry_size_usd:
        return replay.Refusal.NO_CASH
    return None
