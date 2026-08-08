"""I/O for the Generation-2 Strategy Lab.

Loads one scoped, immutable research dataset. The live paper-wallet evaluator is
not imported here and no write path exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.paper import PaperPosition, PaperTradeAudit, PaperWallet
from app.models.radar import RadarToken
from app.paper import execution, lab
from app.paper.models import PositionStatus
from app.repositories.market import MarketSnapshotRepository


@dataclass(frozen=True, slots=True)
class LabDataset:
    entries: tuple[lab.TradeInput, ...]
    integrity: lab.DataIntegrity
    execution_models: tuple[lab.ExecutionModelPerformance, ...]
    loaded_at: datetime


_ZERO = Decimal(0)
_HUNDRED = Decimal(100)


def _model_label(model: str) -> str:
    if model == execution.JUPITER_MODEL_VERSION:
        return "Jupiter Execution Model V2"
    if model == execution.LEGACY_MODEL_VERSION:
        return "Legacy Execution Model V1"
    return "Unknown execution model"


def _execution_model_performance(
    audits: list[PaperTradeAudit],
) -> tuple[lab.ExecutionModelPerformance, ...]:
    groups: dict[str, list[PaperTradeAudit]] = {}
    for row in audits:
        model = row.execution_model_version or execution.LEGACY_MODEL_VERSION
        groups.setdefault(model, []).append(row)

    results: list[lab.ExecutionModelPerformance] = []
    for model, rows in sorted(groups.items()):
        net_returns = [row.net_return_usd for row in rows if row.net_return_usd is not None]
        wins = [value for value in net_returns if value > 0]
        losses = [abs(value) for value in net_returns if value < 0]
        gross_profit = sum(wins, _ZERO)
        gross_loss = sum(losses, _ZERO)
        results.append(
            lab.ExecutionModelPerformance(
                model_version=model,
                label=_model_label(model),
                trades=len(rows),
                gross_return_usd=sum(
                    ((row.gross_return_usd or _ZERO) for row in rows), _ZERO
                ).quantize(Decimal("0.0001")),
                net_return_usd=sum(net_returns, _ZERO).quantize(Decimal("0.0001")),
                win_rate_pct=(
                    None
                    if not net_returns
                    else (Decimal(len(wins)) / Decimal(len(net_returns)) * _HUNDRED).quantize(
                        Decimal("0.01")
                    )
                ),
                profit_factor=(
                    None
                    if gross_loss <= 0
                    else (gross_profit / gross_loss).quantize(Decimal("0.01"))
                ),
                fees_usd=sum(((row.fee_usd or _ZERO) for row in rows), _ZERO).quantize(
                    Decimal("0.0001")
                ),
                slippage_usd=sum(
                    ((row.slippage_usd or _ZERO) for row in rows), _ZERO
                ).quantize(Decimal("0.0001")),
            )
        )
    return tuple(results)


async def load_dataset(session: AsyncSession, *, now: datetime) -> LabDataset:
    """Load Generation 2 (`trailing_stop_25_v1`) only."""
    wallets = list(
        (
            await session.scalars(
                select(PaperWallet).where(
                    PaperWallet.generation == lab.GENERATION,
                    PaperWallet.strategy_id == lab.STRATEGY_ID,
                )
            )
        ).all()
    )
    if not wallets:
        return LabDataset(
            entries=(),
            integrity=lab.DataIntegrity(
                scoped_generation=lab.GENERATION,
                scoped_strategy_id=lab.STRATEGY_ID,
                positions=0,
                open_positions=0,
                closed_positions=0,
                audited_closed_positions=0,
                missing_audit_rows=0,
                manual_overrides=0,
                legacy_execution_model_rows=0,
                jupiter_execution_model_rows=0,
                unknown_execution_model_rows=0,
                archived_generation_positions=0,
                archived_missing_audit_rows=0,
                verdict="No Generation 2 wallet exists in this database.",
            ),
            execution_models=(),
            loaded_at=now,
        )

    wallet_ids = [wallet.id for wallet in wallets]
    positions = list(
        (
            await session.scalars(
                select(PaperPosition)
                .where(PaperPosition.wallet_id.in_(wallet_ids))
                .order_by(PaperPosition.opened_at.asc(), PaperPosition.mint_address.asc())
            )
        ).all()
    )
    audits = list(
        (
            await session.scalars(
                select(PaperTradeAudit).where(PaperTradeAudit.wallet_id.in_(wallet_ids))
            )
        ).all()
    )
    audits_by_position = {row.position_id: row for row in audits}
    mints = [row.mint_address for row in positions]
    radar = {
        row.mint_address: row
        for row in (
            await session.scalars(select(RadarToken).where(RadarToken.mint_address.in_(mints)))
        ).all()
    }
    oldest = min((row.opened_at for row in positions), default=now)
    series = await MarketSnapshotRepository(session).series_for_mints(mints, since=oldest)

    entries: list[lab.TradeInput] = []
    for row in positions:
        score = radar.get(row.mint_address)
        quotes = tuple(
            lab.QuotePoint(
                at=snapshot.captured_at,
                price=snapshot.price_usd,
                market_cap=snapshot.market_cap,
                liquidity_usd=snapshot.liquidity_usd,
                volume_24h=snapshot.volume_24h,
            )
            for snapshot in series.get(row.mint_address, [])
            if snapshot.price_usd is not None and snapshot.price_usd > 0
        )
        entry_volume = next(
            (quote.volume_24h for quote in quotes if quote.at >= row.opened_at), None
        )
        entries.append(
            lab.TradeInput(
                position_id=row.id,
                mint_address=row.mint_address,
                symbol=None
                if audits_by_position.get(row.id) is None
                else audits_by_position[row.id].symbol,
                opened_at=row.opened_at,
                entry_price=row.entry_price,
                size_usd=row.size_usd,
                quantity=row.quantity,
                entry_market_cap=row.entry_market_cap,
                entry_liquidity_usd=row.entry_liquidity_usd,
                entry_rank=row.entry_rank,
                status=row.status,
                actual_closed_at=row.closed_at,
                actual_exit_reason=row.exit_reason,
                manual=row.exit_reason == "manual",
                peak_price=row.peak_price,
                first_detected_at=None if score is None else score.first_detected_at,
                radar_score=None if score is None else score.first_opportunity_score,
                confidence=None if score is None else score.first_confidence,
                category=None if score is None else score.category,
                entry_volume_24h=entry_volume,
                quotes=quotes,
            )
        )

    closed = [row for row in positions if row.status == PositionStatus.CLOSED.value]
    missing = [row for row in closed if row.id not in audits_by_position]
    legacy_execution = sum(
        1
        for row in audits
        if row.execution_model_version in (None, "legacy_constant_product_v1")
    )
    jupiter_execution = sum(
        1 for row in audits if row.execution_model_version == "jupiter_quote_v2"
    )
    unknown_execution = len(audits) - legacy_execution - jupiter_execution
    archived_positions = int(
        await session.scalar(
            select(func.count())
            .select_from(PaperPosition)
            .join(PaperWallet, PaperWallet.id == PaperPosition.wallet_id)
            .where(PaperWallet.generation != lab.GENERATION)
        )
        or 0
    )
    archived_missing = int(
        await session.scalar(
            select(func.count())
            .select_from(PaperPosition)
            .join(PaperWallet, PaperWallet.id == PaperPosition.wallet_id)
            .outerjoin(PaperTradeAudit, PaperTradeAudit.position_id == PaperPosition.id)
            .where(
                PaperWallet.generation != lab.GENERATION,
                PaperPosition.status == PositionStatus.CLOSED.value,
                PaperTradeAudit.id.is_(None),
            )
        )
        or 0
    )
    return LabDataset(
        entries=tuple(entries),
        integrity=lab.DataIntegrity(
            scoped_generation=lab.GENERATION,
            scoped_strategy_id=lab.STRATEGY_ID,
            positions=len(positions),
            open_positions=sum(
                1 for row in positions if row.status == PositionStatus.OPEN.value
            ),
            closed_positions=len(closed),
            audited_closed_positions=len(closed) - len(missing),
            missing_audit_rows=len(missing),
            manual_overrides=sum(1 for row in positions if row.exit_reason == "manual"),
            legacy_execution_model_rows=legacy_execution,
            jupiter_execution_model_rows=jupiter_execution,
            unknown_execution_model_rows=unknown_execution,
            archived_generation_positions=archived_positions,
            archived_missing_audit_rows=archived_missing,
            verdict=(
                "Generation 2 is complete enough for scoped research."
                if not missing
                else "Generation 2 has missing audit rows; optimisation should stop."
            ),
        ),
        execution_models=_execution_model_performance(audits),
        loaded_at=now,
    )


def replay_all(dataset: LabDataset) -> tuple[lab.StrategyResult, ...]:
    return lab.replay_all(dataset.entries)
