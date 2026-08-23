"""Reads and writes for Strategy Lab's own tables. **Touches nothing else.**

Every statement in this module names a `strategy_lab_*` table, with two
read-only exceptions that are not writes at all: the canonical opportunity
loader reads Radar's decision audit, and the quote loader reads market
snapshots. Neither is owned by a wallet.

`tests/unit/test_strategy_lab_isolation.py` reads this file's source and fails
the build if an `INSERT`, `UPDATE` or `DELETE` ever names a table outside the
namespace. Isolation asserted by a test rather than by a convention, because a
convention is one careless commit away from not holding.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.strategy_lab import (
    StrategyLabFill,
    StrategyLabOpportunity,
    StrategyLabPosition,
    StrategyLabRefusal,
    StrategyLabRun,
    StrategyLabStrategy,
    StrategyLabWallet,
)
from app.strategy_lab.opportunities import CANONICAL_VERSION, Opportunity
from app.strategy_lab.rules import EXECUTABLE_FLOOR_USD, Quote
from app.strategy_lab.strategies import StrategyDefinition

#: How much of the equity curve is kept for the chart. Six weeks of 15-minute
#: samples; the exact drawdown lives in `max_drawdown_pct` and is never trimmed.
EQUITY_CURVE_POINTS = 4000


class DefinitionChangedError(RuntimeError):
    """A registered strategy's parameters differ from the code's. §17's guard.

    Raised rather than reconciled. Silently accepting the new definition would
    restate every result already published under that version number, which is
    exactly the failure the version rule exists to prevent. The fix is a new
    version, never an overwrite.
    """


async def register(session: AsyncSession, definition: StrategyDefinition) -> None:
    """Record a definition, or verify the stored one still matches the code."""
    stored = (
        await session.execute(
            select(StrategyLabStrategy).where(
                StrategyLabStrategy.strategy_id == definition.strategy_id,
                StrategyLabStrategy.version == definition.version,
            )
        )
    ).scalar_one_or_none()

    if stored is not None:
        if stored.definition_hash != definition.definition_hash:
            raise DefinitionChangedError(
                f"{definition.key} is registered with hash {stored.definition_hash} "
                f"but the code now hashes to {definition.definition_hash}. "
                f"A changed parameter is a NEW VERSION, never an edit — results "
                f"already published under {definition.key} would otherwise "
                f"silently come to mean something else."
            )
        return

    session.add(
        StrategyLabStrategy(
            strategy_id=definition.strategy_id,
            version=definition.version,
            name=definition.name,
            purpose=definition.purpose,
            entry_size_usd=definition.entry_size_usd,
            definition_hash=definition.definition_hash,
            definition=definition._canonical(),
            benchmark=definition.benchmark,
        )
    )
    await session.flush()


async def register_all(
    session: AsyncSession, definitions: Sequence[StrategyDefinition]
) -> None:
    for definition in definitions:
        await register(session, definition)


async def upsert_opportunities(
    session: AsyncSession, opportunities: Sequence[Opportunity]
) -> dict[str, uuid.UUID]:
    """Freeze each canonical opportunity once. Returns mint -> row id.

    `ON CONFLICT DO NOTHING`, never `DO UPDATE`: a frozen opportunity that could
    be rewritten is not frozen, and the whole point of §1 is that the evidence
    is the evidence available at that instant.
    """
    if not opportunities:
        return {}

    rows = [
        {
            "source_decision_id": uuid.UUID(o.source_decision_id),
            "mint_address": o.mint_address,
            "eligible_at": o.eligible_at,
            "entry_price": o.entry_price,
            "liquidity_usd": o.liquidity_usd,
            "market_cap": o.market_cap,
            "liq_to_mcap": o.liq_to_mcap,
            "volume_24h": o.volume_24h,
            "volume_1h": o.volume_1h,
            "buys_24h": o.buys_24h,
            "sells_24h": o.sells_24h,
            "buy_sell_ratio_24h": o.buy_sell_ratio_24h,
            "pool_address": o.pool_address,
            "venue": o.venue,
            "trading_pair": o.trading_pair,
            "discovery_age_seconds": o.discovery_age_seconds,
            "first_discovered_at": o.first_discovered_at,
            "radar_rank": o.radar_rank,
            "radar_score": o.radar_score,
            "confidence_score": o.confidence_score,
            "risk_score": o.risk_score,
            "risk_band": o.risk_band,
            "security_status": o.security_status,
            "security_evaluated_at": o.security_evaluated_at,
            "observation_cadence_seconds": o.observation_cadence_seconds,
            "radar_input_snapshot_count": o.radar_input_snapshot_count,
            "evidence_coverage_pct": o.evidence_coverage_pct,
            "canonical_version": CANONICAL_VERSION,
            "excluded_reason": o.excluded_reason,
        }
        for o in opportunities
    ]
    statement = insert(StrategyLabOpportunity).values(rows)
    await session.execute(
        statement.on_conflict_do_nothing(constraint="uq_strategy_lab_opportunity_mint")
    )
    await session.flush()

    found = (
        await session.execute(
            select(StrategyLabOpportunity.mint_address, StrategyLabOpportunity.id).where(
                StrategyLabOpportunity.mint_address.in_(
                    [o.mint_address for o in opportunities]
                )
            )
        )
    ).all()
    return dict(found)


async def create_run(
    session: AsyncSession,
    *,
    mode: str,
    metrics_version: str,
    rules_version: str,
    dataset_from: datetime | None,
    dataset_to: datetime | None,
    candidates: int,
    usable: int,
    exclusions: dict[str, int],
    venues: dict[str, int],
    observation_count: int,
    notes: str | None = None,
) -> StrategyLabRun:
    run = StrategyLabRun(
        mode=mode,
        canonical_version=CANONICAL_VERSION,
        metrics_version=metrics_version,
        rules_version=rules_version,
        dataset_from=dataset_from,
        dataset_to=dataset_to,
        candidates=candidates,
        usable=usable,
        excluded=candidates - usable,
        exclusions=exclusions,
        venues=venues,
        observation_count=observation_count,
        notes=notes,
    )
    session.add(run)
    await session.flush()
    return run


async def get_or_create_wallet(
    session: AsyncSession,
    *,
    definition: StrategyDefinition,
    mode: str,
    starting_balance: Decimal,
    run_id: uuid.UUID | None = None,
) -> StrategyLabWallet:
    """One wallet per (strategy, version, mode, run). Simulated money, always."""
    existing = (
        await session.execute(
            select(StrategyLabWallet).where(
                StrategyLabWallet.strategy_id == definition.strategy_id,
                StrategyLabWallet.version == definition.version,
                StrategyLabWallet.mode == mode,
                StrategyLabWallet.run_id.is_(run_id)
                if run_id is None
                else StrategyLabWallet.run_id == run_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    wallet = StrategyLabWallet(
        run_id=run_id,
        strategy_id=definition.strategy_id,
        version=definition.version,
        definition_hash=definition.definition_hash,
        mode=mode,
        starting_balance=starting_balance,
        entry_size_usd=definition.entry_size_usd,
        cash=starting_balance,
    )
    session.add(wallet)
    await session.flush()
    return wallet


async def latest_run(session: AsyncSession, *, mode: str) -> StrategyLabRun | None:
    return (
        await session.execute(
            select(StrategyLabRun)
            .where(StrategyLabRun.mode == mode, StrategyLabRun.finished_at.is_not(None))
            .order_by(StrategyLabRun.finished_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def wallets_for_run(session: AsyncSession, run_id: uuid.UUID) -> list[StrategyLabWallet]:
    return list(
        (
            await session.execute(
                select(StrategyLabWallet).where(StrategyLabWallet.run_id == run_id)
            )
        )
        .scalars()
        .all()
    )


async def forward_wallets(session: AsyncSession) -> list[StrategyLabWallet]:
    return list(
        (
            await session.execute(
                select(StrategyLabWallet).where(StrategyLabWallet.mode == "FORWARD_RESEARCH")
            )
        )
        .scalars()
        .all()
    )


async def delete_run(session: AsyncSession, run_id: uuid.UUID) -> None:
    """Discard a superseded backtest. Cascades to its wallets and their rows.

    Only ever called on a `BACKTEST` run being replaced by a fresher one over
    the same definitions — the service refuses any other target, so a forward
    record can never be removed this way.
    """
    await session.execute(delete(StrategyLabRun).where(StrategyLabRun.id == run_id))


async def persist_positions(
    session: AsyncSession,
    *,
    wallet: StrategyLabWallet,
    opportunity_ids: dict[str, uuid.UUID],
    positions: Sequence,
    refusals: Sequence,
    final_cash: Decimal,
    equity_curve: Sequence[tuple[datetime, Decimal]] = (),
) -> None:
    """Write one replay's book. Bulk, because a run writes thousands of rows."""
    position_rows = []
    for position in positions:
        opportunity_id = opportunity_ids.get(position.mint_address)
        if opportunity_id is None:
            continue
        last = position.fills[-1][0] if position.fills else None
        position_rows.append(
            {
                "id": uuid.uuid4(),
                "wallet_id": wallet.id,
                "opportunity_id": opportunity_id,
                "mint_address": position.mint_address,
                "opened_at": position.opened_at,
                "entry_price": position.entry_price,
                "size_usd": position.size_usd,
                "initial_quantity": position.initial_quantity,
                "remaining_quantity": Decimal(0),
                "entry_cost": position.entry_cost,
                "entry_liquidity_usd": position.entry_liquidity_usd,
                "venue": position.venue,
                "pool_address": position.pool_address,
                "filled_rungs": sorted(
                    {i for f, _, _ in position.fills for i in f.rung_indexes}
                ),
                "fired_decay": [],
                "trail_armed": False,
                "trail_high": None,
                "observed_peak_multiple": _q(position.observed_peak_multiple),
                "executable_peak_multiple": _q(position.executable_peak_multiple),
                "terminal_multiple": _q(position.terminal_multiple),
                "batch_rung_fills": position.batch_rung_fills,
                "evaluated_through": last.at if last else None,
                "closed_at": position.closed_at,
                "close_reason": position.final_reason,
                "unsettled": position.unsettled,
            }
        )
    if position_rows:
        await session.execute(insert(StrategyLabPosition), position_rows)

    fill_rows = []
    for row, position in zip(position_rows, positions, strict=False):
        for sequence, (fill, net, cost) in enumerate(position.fills):
            fill_rows.append(
                {
                    "position_id": row["id"],
                    "sequence": sequence,
                    "filled_at": fill.at,
                    "reason": str(fill.reason),
                    "price_usd": fill.price_usd,
                    "quantity": fill.quantity,
                    "liquidity_usd": fill.liquidity_usd,
                    "rung_indexes": list(fill.rung_indexes),
                    "trigger_price": fill.trigger_price,
                    "gross_proceeds": fill.gross_proceeds,
                    "execution_cost": cost,
                    "net_proceeds": net,
                }
            )
    if fill_rows:
        await session.execute(insert(StrategyLabFill), fill_rows)

    refusal_rows = []
    seen: set[uuid.UUID] = set()
    for refusal in refusals:
        opportunity_id = opportunity_ids.get(refusal.mint_address)
        if opportunity_id is None or opportunity_id in seen:
            continue
        seen.add(opportunity_id)
        refusal_rows.append(
            {
                "wallet_id": wallet.id,
                "opportunity_id": opportunity_id,
                "mint_address": refusal.mint_address,
                "refused_at": refusal.at,
                "reason": refusal.reason,
                "cash_at_refusal": refusal.cash_at_refusal,
                "peak_multiple": _q(refusal.peak_multiple),
            }
        )
    if refusal_rows:
        await session.execute(
            insert(StrategyLabRefusal)
            .values(refusal_rows)
            .on_conflict_do_nothing(constraint="uq_strategy_lab_refusal")
        )

    wallet.cash = final_cash
    peak = wallet.starting_balance
    worst = Decimal(0)
    for _, equity in equity_curve:
        peak, worst = _advance(peak=peak, worst=worst, equity=equity)
    wallet.peak_equity = peak
    wallet.max_drawdown_pct = worst
    wallet.equity_curve = [
        [at.isoformat(), str(value)] for at, value in list(equity_curve)[-EQUITY_CURVE_POINTS:]
    ]
    await session.flush()


#: Kept here rather than imported from `reporting` so persistence does not
#: depend on the read layer. Both use the same two lines; the duplication is
#: cheaper than the cycle.
def _advance(*, peak: Decimal, worst: Decimal, equity: Decimal) -> tuple[Decimal, Decimal]:
    new_peak = max(peak, equity)
    if new_peak <= 0:
        return new_peak, worst
    return new_peak, max(worst, (new_peak - equity) / new_peak * 100)


def _q(value: Decimal | None) -> Decimal | None:
    """Clamp a multiple into the stored NUMERIC(20,8) so a 1e12 tick cannot
    abort a whole run on overflow. Clamped rather than dropped: the fact that a
    token printed an absurd multiple is itself evidence, and losing the row
    would lose it."""
    if value is None:
        return None
    return min(value, Decimal("999999999999"))


# ── Forward research: incremental reads ─────────────────────────────────────

_NEW_QUOTES = text(
    """
    SELECT captured_at, price_usd, liquidity_usd
      FROM token_market_snapshots
     WHERE mint_address = :mint
       AND price_usd IS NOT NULL AND price_usd > 0
       AND (CAST(:pool AS text) IS NULL OR pool_address = CAST(:pool AS text))
       AND captured_at > :after
       AND captured_at <= :until
     ORDER BY captured_at
    """
)


async def quotes_since(
    session: AsyncSession,
    *,
    mint: str,
    pool: str | None,
    after: datetime,
    until: datetime,
) -> list[Quote]:
    """Only observations this position has not been shown before.

    `after` is exclusive. That is what makes a restart idempotent: an
    observation already folded into `filled_rungs` and `trail_high` is never
    replayed, so no rung fires twice and no proceeds are booked twice.
    """
    rows = (
        await session.execute(
            _NEW_QUOTES, {"mint": mint, "pool": pool, "after": after, "until": until}
        )
    ).all()
    out = []
    for row in rows:
        liquidity = Decimal(row.liquidity_usd) if row.liquidity_usd is not None else None
        out.append(
            Quote(
                price_usd=Decimal(row.price_usd),
                captured_at=row.captured_at,
                liquidity_usd=liquidity,
                executable=liquidity is not None and liquidity >= EXECUTABLE_FLOOR_USD,
            )
        )
    return out


async def open_positions(
    session: AsyncSession, wallet_id: uuid.UUID
) -> list[StrategyLabPosition]:
    return list(
        (
            await session.execute(
                select(StrategyLabPosition).where(
                    StrategyLabPosition.wallet_id == wallet_id,
                    StrategyLabPosition.closed_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )


async def unoffered_opportunities(
    session: AsyncSession,
    *,
    wallet_id: uuid.UUID,
    since: datetime | None = None,
    limit: int = 500,
) -> list[StrategyLabOpportunity]:
    """Canonical opportunities this wallet has neither taken nor refused.

    Anti-joined rather than tracked with a cursor: a cursor would silently skip
    an opportunity inserted out of order after a backfill, and skipping is the
    one failure mode that breaks §1's identical-opportunities requirement.

    `since` is the wallet's own start. **A forward wallet must never be offered
    an opportunity that predates it.** Without this the first tick after
    activation sweeps up the entire historical backlog, and the forward record
    becomes a backtest wearing a forward label — which would destroy the only
    thing that makes it worth having, that it is out of sample.
    """
    taken = select(StrategyLabPosition.opportunity_id).where(
        StrategyLabPosition.wallet_id == wallet_id
    )
    refused = select(StrategyLabRefusal.opportunity_id).where(
        StrategyLabRefusal.wallet_id == wallet_id
    )
    query = select(StrategyLabOpportunity).where(
        StrategyLabOpportunity.excluded_reason.is_(None),
        StrategyLabOpportunity.id.not_in(taken),
        StrategyLabOpportunity.id.not_in(refused),
    )
    if since is not None:
        query = query.where(StrategyLabOpportunity.eligible_at >= since)
    return list(
        (
            await session.execute(
                query.order_by(StrategyLabOpportunity.eligible_at).limit(limit)
            )
        )
        .scalars()
        .all()
    )


async def next_fill_sequence(session: AsyncSession, position_id: uuid.UUID) -> int:
    value = (
        await session.execute(
            select(StrategyLabFill.sequence)
            .where(StrategyLabFill.position_id == position_id)
            .order_by(StrategyLabFill.sequence.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return 0 if value is None else value + 1


async def prune_forward_horizon(session: AsyncSession, *, older_than: timedelta) -> None:
    """No-op placeholder kept honest: nothing is pruned yet.

    Written as an explicit no-op rather than omitted so the retention question
    is visibly unanswered rather than invisibly forgotten. §26 sizes the growth;
    at that rate this does not need answering for a long time.
    """
    return None
