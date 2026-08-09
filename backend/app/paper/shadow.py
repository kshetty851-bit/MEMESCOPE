"""Shadow paper wallets for future live strategy evidence.

V1 remains the published paper wallet. This module runs V2-V5 candidates beside
it: same Radar opportunities, separate cash, separate positions, separate audit
rows and immutable decision records. The goal is live evidence, not hindsight.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, cast

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.market import TokenMarketSnapshot
from app.models.paper import (
    PaperShadowDecision,
    PaperShadowPosition,
    PaperShadowTradeAudit,
    PaperShadowWallet,
)
from app.models.radar import RadarToken
from app.paper import audit, eligibility, execution, exits, metrics
from app.paper.execution import ExecutionQuote, ExecutionQuoteUnavailableError
from app.paper.models import ClosedTrade, ExitReason, OpenPosition, PositionStatus, Quote
from app.radar.repository import RadarRepository
from app.repositories.market import MarketSnapshotRepository
from app.repositories.token import TokenRepository
from app.services.jupiter import JupiterExecutionClient

logger = get_logger(__name__)

_ZERO = Decimal(0)
_ONE = Decimal(1)
_MONEY = Decimal("0.0001")
_PCT = Decimal("0.0001")
_TRADE_SIZE = Decimal(100)
_TRAILING = Decimal("0.25")
_STARTING_BALANCE = Decimal(1000)
_MIN_PROMOTION_TRADES = 100
_PROMOTION_PROFIT_FACTOR = Decimal("1.20")


class ShadowReason:
    ALREADY_TRADED = "already_traded"
    ALREADY_HELD = "already_held"
    NO_MARKET_DATA = "no_market_data"
    NO_PRICE = "no_price"
    NO_LIQUIDITY = "no_liquidity"
    NOT_TRADEABLE = "not_tradeable"
    INSUFFICIENT_CASH = "portfolio_allocation_limit"
    MARKET_CAP_TOO_LOW = "market_cap_too_low"
    MARKET_CAP_TOO_HIGH = "market_cap_too_high"
    RADAR_BELOW_THRESHOLD = "radar_below_threshold"
    EXECUTION_QUALITY_BELOW_THRESHOLD = "execution_quality_below_threshold"
    PRICE_IMPACT_TOO_HIGH = "price_impact_too_high"
    JUPITER_QUOTE_UNAVAILABLE = "jupiter_quote_unavailable"
    EXECUTION_PRICE_MISMATCH = "execution_price_mismatch"


@dataclass(frozen=True, slots=True)
class ShadowSpec:
    code: str
    name: str
    version: str
    summary: str
    min_score: Decimal | None = None
    min_market_cap: Decimal | None = None
    max_market_cap: Decimal | None = None
    allowed_qualities: frozenset[str] | None = None
    max_entry_impact_pct: Decimal | None = None
    require_jupiter: bool = False


SHADOW_SPECS: tuple[ShadowSpec, ...] = (
    ShadowSpec(
        code="v2",
        name="V2 Focused Early Liquidity",
        version="1.0.0",
        summary="Market cap $25K-$50K, execution quality A/B+, impact <2%, Radar >=65.",
        min_score=Decimal(65),
        min_market_cap=Decimal("25000"),
        max_market_cap=Decimal("50000"),
        allowed_qualities=frozenset({"A", "B+"}),
        max_entry_impact_pct=Decimal("2"),
    ),
    ShadowSpec(
        code="v3",
        name="V3 Quality Only",
        version="1.0.0",
        summary="Radar >=70 and execution quality A only; no market-cap restriction.",
        min_score=Decimal(70),
        allowed_qualities=frozenset({"A"}),
    ),
    ShadowSpec(
        code="v4",
        name="V4 Mid-Cap Quality",
        version="1.0.0",
        summary="Market cap $50K-$100K, execution quality A/B+, impact <2%.",
        min_market_cap=Decimal("50000"),
        max_market_cap=Decimal("100000"),
        allowed_qualities=frozenset({"A", "B+"}),
        max_entry_impact_pct=Decimal("2"),
    ),
    ShadowSpec(
        code="v5",
        name="V5 Jupiter Impact",
        version="1.0.0",
        summary="Execution quality A only with Jupiter estimated impact <1%; no cap filter.",
        allowed_qualities=frozenset({"A"}),
        max_entry_impact_pct=Decimal("1"),
        require_jupiter=True,
    ),
)


@dataclass(frozen=True, slots=True)
class Opportunity:
    radar: RadarToken
    rank: int
    snapshot: TokenMarketSnapshot | None
    token_id: object | None
    symbol: str | None
    decimals: int | None
    age_seconds: int | None
    execution_quote: ExecutionQuote | execution.LegacyExecution | None

    @property
    def mint_address(self) -> str:
        return self.radar.mint_address

    @property
    def price_usd(self) -> Decimal | None:
        return None if self.snapshot is None else self.snapshot.price_usd

    @property
    def market_cap(self) -> Decimal | None:
        return None if self.snapshot is None else self.snapshot.market_cap

    @property
    def liquidity_usd(self) -> Decimal | None:
        return None if self.snapshot is None else self.snapshot.liquidity_usd

    @property
    def volume_24h(self) -> Decimal | None:
        return None if self.snapshot is None else self.snapshot.volume_24h

    @property
    def observed_at(self) -> datetime | None:
        return None if self.snapshot is None else self.snapshot.captured_at

    @property
    def impact_pct(self) -> Decimal | None:
        if isinstance(self.execution_quote, ExecutionQuote):
            return self.execution_quote.price_impact_pct
        return None

    @property
    def execution_quality(self) -> str | None:
        return execution_quality(self.impact_pct)


@dataclass(frozen=True, slots=True)
class ShadowOutcome:
    evaluated: int
    decisions: int
    opened: int
    closed: int
    audited: int
    candidates: int
    candidates_truncated: bool
    refusals: dict[str, int]

    def as_dict(self) -> dict[str, object]:
        return {
            "evaluated": self.evaluated,
            "decisions": self.decisions,
            "opened": self.opened,
            "closed": self.closed,
            "audited": self.audited,
            "candidates": self.candidates,
            "candidates_truncated": self.candidates_truncated,
            **{f"refused_{key}": value for key, value in sorted(self.refusals.items())},
        }


def execution_quality(impact_pct: Decimal | None) -> str | None:
    """Stable execution bands for entry filters."""
    if impact_pct is None:
        return None
    if impact_pct <= Decimal("1"):
        return "A"
    if impact_pct <= Decimal("2"):
        return "B+"
    if impact_pct <= Decimal("5"):
        return "C"
    return "D"


def _to_quote(row: TokenMarketSnapshot) -> Quote | None:
    if row.price_usd is None:
        return None
    return Quote(
        captured_at=row.captured_at,
        price_usd=row.price_usd,
        liquidity_usd=row.liquidity_usd,
        market_cap=row.market_cap,
    )


def _to_open(row: PaperShadowPosition) -> OpenPosition:
    return OpenPosition(
        mint_address=row.mint_address,
        opened_at=row.opened_at,
        entry_price=row.entry_price,
        quantity=row.quantity,
        size_usd=row.size_usd,
        peak_price=row.peak_price,
        trailing_drawdown=row.trailing_drawdown,
    )


def _to_closed(row: PaperShadowPosition) -> ClosedTrade | None:
    if row.closed_at is None or row.exit_price is None:
        return None
    return ClosedTrade(
        mint_address=row.mint_address,
        opened_at=row.opened_at,
        closed_at=row.closed_at,
        size_usd=row.size_usd,
        entry_price=row.entry_price,
        exit_price=row.exit_price,
        quantity=row.quantity,
        reason=ExitReason(row.exit_reason or ExitReason.STOP.value),
    )


def _quote_from_json(quote: dict[str, object] | None) -> ExecutionQuote | None:
    if (
        not isinstance(quote, dict)
        or quote.get("model_version") != execution.JUPITER_MODEL_VERSION
    ):
        return None
    try:
        amms = quote.get("amms")
        raw = quote.get("raw")
        return ExecutionQuote(
            side=str(quote["side"]),
            model_version=str(quote["model_version"]),
            quoted_at=datetime.fromisoformat(str(quote["quoted_at"])),
            latency_ms=Decimal(str(quote["latency_ms"])),
            input_mint=str(quote["input_mint"]),
            output_mint=str(quote["output_mint"]),
            input_amount_raw=str(quote["input_amount_raw"]),
            output_amount_raw=str(quote["output_amount_raw"]),
            input_decimals=int(str(quote["input_decimals"])),
            output_decimals=int(str(quote["output_decimals"])),
            input_amount=Decimal(str(quote["input_amount"])),
            output_amount=Decimal(str(quote["output_amount"])),
            input_amount_usd=(
                None
                if quote.get("input_amount_usd") is None
                else Decimal(str(quote["input_amount_usd"]))
            ),
            output_amount_usd=(
                None
                if quote.get("output_amount_usd") is None
                else Decimal(str(quote["output_amount_usd"]))
            ),
            estimated_price_usd=Decimal(str(quote["estimated_price_usd"])),
            price_impact_pct=(
                None
                if quote.get("price_impact_pct") is None
                else Decimal(str(quote["price_impact_pct"]))
            ),
            context_slot=(
                None if quote.get("context_slot") is None else int(str(quote["context_slot"]))
            ),
            platform_fee_usd=(
                None
                if quote.get("platform_fee_usd") is None
                else Decimal(str(quote["platform_fee_usd"]))
            ),
            route=str(quote.get("route") or ""),
            amms=(
                tuple(str(item) for item in amms if isinstance(item, str))
                if isinstance(amms, list)
                else ()
            ),
            raw=cast(dict[str, object], raw) if isinstance(raw, dict) else {},
        )
    except (KeyError, ValueError):
        return None


class ShadowPaperService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._market = MarketSnapshotRepository(session)
        self._radar = RadarRepository(session)
        self._execution = JupiterExecutionClient()

    async def review(self, *, now: datetime) -> ShadowOutcome:
        wallets = await self._ensure_wallets(now=now)
        closed = 0
        audited = 0
        for wallet in wallets:
            closed += await self._settle_exits(wallet, now=now)
            audited += await self._record_audits(wallet)

        opportunities, truncated = await self._opportunities(now=now)
        opened = 0
        decisions = 0
        refusals: Counter[str] = Counter()
        for wallet in wallets:
            spec = _spec_for(wallet.wallet_code)
            opened_now, decisions_now, refused_now = await self._evaluate_wallet(
                wallet, spec, opportunities, now=now
            )
            opened += opened_now
            decisions += decisions_now
            refusals.update(refused_now)

        return ShadowOutcome(
            evaluated=len(wallets),
            decisions=decisions,
            opened=opened,
            closed=closed,
            audited=audited,
            candidates=len(opportunities),
            candidates_truncated=truncated,
            refusals=dict(refusals),
        )

    async def intelligence(self, *, now: datetime) -> dict[str, object]:
        wallets = await self._ensure_wallets(now=now)
        rows = []
        for wallet in wallets:
            positions = await self._positions(wallet.id)
            decisions = await self._decisions(wallet.wallet_code)
            open_mints = [
                row.mint_address
                for row in positions
                if row.status == PositionStatus.OPEN.value
            ]
            latest = await self._market.latest_for_mints(open_mints)
            rows.append(_wallet_report(wallet, positions, decisions, latest, now=now))

        return {
            "enabled": settings.FEATURE_PAPER_WALLET_ENABLED,
            "observed_at": now,
            "promotion_rules": {
                "minimum_completed_trades": _MIN_PROMOTION_TRADES,
                "minimum_profit_factor": str(_PROMOTION_PROFIT_FACTOR),
                "requires_positive_net_return": True,
                "requires_positive_expectancy": True,
            },
            "wallets": rows,
            "missed_opportunities": _missed_opportunities(rows),
            "filter_performance": _filter_performance(rows),
        }

    async def _ensure_wallets(self, *, now: datetime) -> list[PaperShadowWallet]:
        for spec in SHADOW_SPECS:
            await self._session.execute(
                insert(PaperShadowWallet)
                .values(
                    wallet_code=spec.code,
                    strategy_id="trailing_stop_25_v1_shadow",
                    strategy_version=spec.version,
                    display_name=spec.name,
                    starting_balance=_STARTING_BALANCE,
                    started_at=now,
                )
                .on_conflict_do_nothing(index_elements=[PaperShadowWallet.wallet_code])
            )
        await self._session.flush()
        return list(
            (
                await self._session.scalars(
                    select(PaperShadowWallet).order_by(PaperShadowWallet.wallet_code)
                )
            ).all()
        )

    async def _opportunities(self, *, now: datetime) -> tuple[list[Opportunity], bool]:
        limit = settings.PAPER_WALLET_CANDIDATE_LIMIT
        radar_rows = await self._radar.list_entries(
            category=None, active_only=True, sort="score", limit=limit, offset=0
        )
        mints = [row.mint_address for row in radar_rows]
        snapshots = await self._market.latest_for_mints(mints)
        tokens = await TokenRepository(self._session).get_many_by_mints(mints)

        output: list[Opportunity] = []
        quote_cache: dict[str, ExecutionQuote | execution.LegacyExecution | None] = {}
        for rank, row in enumerate(radar_rows, start=1):
            token = tokens.get(row.mint_address)
            snapshot = snapshots.get(row.mint_address)
            age_seconds = (
                None
                if token is None or token.block_time is None
                else max(0, int((now - token.block_time).total_seconds()))
            )
            quote: ExecutionQuote | execution.LegacyExecution | None = None
            if (
                snapshot is not None
                and snapshot.price_usd is not None
                and snapshot.price_usd > 0
            ):
                quote = await self._entry_execution(
                    mint=row.mint_address,
                    decimals=token.decimals if token is not None else None,
                    now=now,
                )
            quote_cache[row.mint_address] = quote
            output.append(
                Opportunity(
                    radar=row,
                    rank=rank,
                    snapshot=snapshot,
                    token_id=token.id if token is not None else None,
                    symbol=token.symbol if token is not None else None,
                    decimals=token.decimals if token is not None else None,
                    age_seconds=age_seconds,
                    execution_quote=quote_cache[row.mint_address],
                )
            )
        return output, len(radar_rows) >= limit

    async def _entry_execution(
        self, *, mint: str, decimals: int | None, now: datetime
    ) -> ExecutionQuote | execution.LegacyExecution:
        if settings.PAPER_EXECUTION_MODEL != "jupiter":
            return execution.LegacyExecution("PAPER_EXECUTION_MODEL=legacy")
        if decimals is None:
            return execution.LegacyExecution("Token decimals unavailable for Jupiter quote.")
        try:
            return await self._execution.buy_quote(
                output_mint=mint,
                input_usd=_TRADE_SIZE,
                output_decimals=decimals,
                now=now,
            )
        except ExecutionQuoteUnavailableError as exc:
            logger.warning("paper_shadow_jupiter_entry_quote_failed", mint_address=mint)
            return execution.LegacyExecution(str(exc))

    async def _exit_execution(
        self, position: PaperShadowPosition, *, now: datetime
    ) -> ExecutionQuote | execution.LegacyExecution:
        if settings.PAPER_EXECUTION_MODEL != "jupiter":
            return execution.LegacyExecution("PAPER_EXECUTION_MODEL=legacy")
        quote = _quote_from_json(position.entry_execution_quote)
        decimals = quote.output_decimals if quote is not None else None
        if decimals is None:
            return execution.LegacyExecution(
                "Token decimals unavailable for Jupiter exit quote."
            )
        try:
            return await self._execution.sell_quote(
                input_mint=position.mint_address,
                quantity=position.quantity,
                input_decimals=decimals,
                now=now,
            )
        except ExecutionQuoteUnavailableError as exc:
            logger.warning(
                "paper_shadow_jupiter_exit_quote_failed",
                mint_address=position.mint_address,
            )
            return execution.LegacyExecution(str(exc))

    async def _evaluate_wallet(
        self,
        wallet: PaperShadowWallet,
        spec: ShadowSpec,
        opportunities: Sequence[Opportunity],
        *,
        now: datetime,
    ) -> tuple[int, int, Counter[str]]:
        held = await self._held_mints(wallet.id)
        open_now = await self._open_mints(wallet.id)
        cash = await self._cash_for(wallet)
        opened = 0
        decisions = 0
        refusals: Counter[str] = Counter()

        for opportunity in opportunities:
            if await self._decision_exists(wallet, opportunity):
                continue

            reasons = _reasons_for(spec, opportunity, held=held, open_now=open_now)
            if not reasons and cash < _TRADE_SIZE:
                reasons = [ShadowReason.INSUFFICIENT_CASH]

            position_id = None
            decision: Literal["accepted", "rejected"] = "rejected" if reasons else "accepted"
            if not reasons:
                created = await self._open_position(wallet, opportunity, now=now)
                if created is not None:
                    opened += 1
                    cash -= _TRADE_SIZE
                    held.add(opportunity.mint_address)
                    open_now.add(opportunity.mint_address)
                    position_id = created.id
                else:
                    decision = "rejected"
                    reasons = [ShadowReason.ALREADY_TRADED]

            inserted = await self._record_decision(
                wallet=wallet,
                spec=spec,
                opportunity=opportunity,
                decision=decision,
                reasons=reasons,
                position_id=position_id,
                now=now,
            )
            if decision == "accepted" and not inserted:
                raise RuntimeError("shadow paper position opened without an accepted decision")
            decisions += int(inserted)
            refusals.update(reasons)

        return opened, decisions, refusals

    async def _open_position(
        self, wallet: PaperShadowWallet, opportunity: Opportunity, *, now: datetime
    ) -> PaperShadowPosition | None:
        if opportunity.price_usd is None:
            return None
        entry_execution = opportunity.execution_quote
        execution_price = (
            entry_execution.estimated_price_usd
            if isinstance(entry_execution, ExecutionQuote)
            else opportunity.price_usd
        )
        quantity = (
            entry_execution.output_amount
            if isinstance(entry_execution, ExecutionQuote)
            else _TRADE_SIZE / opportunity.price_usd
        )
        values = _entry_execution_values(entry_execution)
        result = await self._session.execute(
            insert(PaperShadowPosition)
            .values(
                shadow_wallet_id=wallet.id,
                mint_address=opportunity.mint_address,
                token_id=opportunity.token_id,
                opened_at=now,
                entry_rank=opportunity.rank,
                entry_price=execution_price,
                entry_observed_price=opportunity.price_usd,
                size_usd=_TRADE_SIZE,
                quantity=quantity,
                trailing_drawdown=_TRAILING,
                entry_market_cap=audit.market_cap_at_price(
                    observed_market_cap=opportunity.market_cap,
                    observed_price=opportunity.price_usd,
                    execution_price=execution_price,
                ),
                entry_liquidity_usd=opportunity.liquidity_usd,
                entry_radar_score=opportunity.radar.current_opportunity_score,
                entry_confidence=opportunity.radar.current_confidence,
                entry_token_age_seconds=opportunity.age_seconds,
                entry_volume_24h=opportunity.volume_24h,
                entry_execution_quality=opportunity.execution_quality,
                status=PositionStatus.OPEN.value,
                peak_price=execution_price,
                last_evaluated_at=now,
                **values,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    PaperShadowPosition.shadow_wallet_id,
                    PaperShadowPosition.mint_address,
                ]
            )
            .returning(PaperShadowPosition)
        )
        return result.scalar_one_or_none()

    async def _record_decision(
        self,
        *,
        wallet: PaperShadowWallet,
        spec: ShadowSpec,
        opportunity: Opportunity,
        decision: Literal["accepted", "rejected"],
        reasons: Sequence[str],
        position_id: object | None,
        now: datetime,
    ) -> bool:
        found = opportunity.execution_quote
        result = await self._session.execute(
            insert(PaperShadowDecision)
            .values(
                shadow_wallet_id=wallet.id,
                wallet_code=wallet.wallet_code,
                strategy_id=wallet.strategy_id,
                strategy_version=spec.version,
                mint_address=opportunity.mint_address,
                token_id=opportunity.token_id,
                radar_rank=opportunity.rank,
                radar_evaluated_at=opportunity.radar.last_evaluated_at,
                decided_at=now,
                decision=decision,
                reason_codes=list(reasons),
                radar_score=opportunity.radar.current_opportunity_score,
                radar_confidence=opportunity.radar.current_confidence,
                market_cap=opportunity.market_cap,
                liquidity_usd=opportunity.liquidity_usd,
                volume_24h=opportunity.volume_24h,
                token_age_seconds=opportunity.age_seconds,
                entry_impact_pct=opportunity.impact_pct,
                execution_quality=opportunity.execution_quality,
                execution_model_version=(
                    found.model_version
                    if isinstance(found, (ExecutionQuote, execution.LegacyExecution))
                    else None
                ),
                execution_confidence=(
                    found.confidence
                    if isinstance(found, (ExecutionQuote, execution.LegacyExecution))
                    else None
                ),
                execution_fallback_reason=(
                    found.reason if isinstance(found, execution.LegacyExecution) else None
                ),
                position_id=position_id,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    PaperShadowDecision.wallet_code,
                    PaperShadowDecision.mint_address,
                    PaperShadowDecision.radar_evaluated_at,
                ]
            )
            .returning(PaperShadowDecision.id)
        )
        return result.scalar_one_or_none() is not None

    async def _decision_exists(
        self, wallet: PaperShadowWallet, opportunity: Opportunity
    ) -> bool:
        found = await self._session.scalar(
            select(PaperShadowDecision.id)
            .where(
                PaperShadowDecision.wallet_code == wallet.wallet_code,
                PaperShadowDecision.mint_address == opportunity.mint_address,
                PaperShadowDecision.radar_evaluated_at == opportunity.radar.last_evaluated_at,
            )
            .limit(1)
        )
        return found is not None

    async def _settle_exits(self, wallet: PaperShadowWallet, *, now: datetime) -> int:
        positions = await self._open_positions(wallet.id)
        if not positions:
            return 0
        oldest = min(row.last_evaluated_at for row in positions)
        series = await self._market.series_for_mints(
            [row.mint_address for row in positions], since=oldest
        )
        closed = 0
        for position in positions:
            quotes = [
                quote
                for quote in (_to_quote(row) for row in series.get(position.mint_address, []))
                if quote is not None and quote.captured_at > position.last_evaluated_at
            ]
            found, peak = exits.resolve(
                exits.ExitRules(trailing_drawdown=position.trailing_drawdown),
                entry_price=position.entry_price,
                opened_at=position.opened_at,
                quotes=quotes,
                peak=position.peak_price,
            )
            if found is None:
                await self._advance(
                    position.id,
                    peak_price=peak,
                    last_evaluated_at=quotes[-1].captured_at if quotes else now,
                )
                continue
            decision_quote = next(
                (quote for quote in quotes if quote.captured_at == found.at),
                None,
            )
            observed_exit_price = (
                decision_quote.price_usd if decision_quote is not None else found.price_usd
            )
            exit_execution = await self._exit_execution(position, now=now)
            exit_price = (
                exit_execution.estimated_price_usd
                if isinstance(exit_execution, ExecutionQuote)
                else found.price_usd
            )
            if await self._close(
                position.id,
                exit_price=exit_price,
                closed_at=now if isinstance(exit_execution, ExecutionQuote) else found.at,
                exit_reason=found.reason.value,
                peak_price=peak,
                exit_observed_price=observed_exit_price,
                exit_execution=exit_execution,
            ):
                closed += 1
        return closed

    async def _record_audits(self, wallet: PaperShadowWallet) -> int:
        closed_rows = [
            row
            for row in await self._positions(wallet.id)
            if row.status == PositionStatus.CLOSED.value
        ]
        if not closed_rows:
            return 0
        already = await self._audited_position_ids(wallet.id)
        pending = [row for row in closed_rows if str(row.id) not in already]
        if not pending:
            return 0

        mints = [row.mint_address for row in pending]
        tokens = await TokenRepository(self._session).get_many_by_mints(mints)
        oldest = min(row.opened_at for row in pending)
        series = await self._market.series_for_mints(mints, since=oldest)
        written = 0
        for row in pending:
            trade = _to_closed(row)
            if trade is None:
                continue
            exit_reading = _reading_at(series.get(row.mint_address, []), trade.closed_at)
            token = tokens.get(row.mint_address)
            record = audit.record(
                trade,
                symbol=token.symbol if token is not None else None,
                entry_market_cap=row.entry_market_cap,
                entry_liquidity_usd=row.entry_liquidity_usd,
                exit_market_cap=audit.market_cap_at_price(
                    observed_market_cap=(
                        exit_reading.market_cap if exit_reading is not None else None
                    ),
                    observed_price=(
                        exit_reading.price_usd if exit_reading is not None else None
                    ),
                    execution_price=row.exit_price,
                ),
                exit_liquidity_usd=(
                    exit_reading.liquidity_usd if exit_reading is not None else None
                ),
                strategy_id=wallet.strategy_id,
                strategy_version=wallet.strategy_version,
                wallet_generation=1,
                entry_observed_price=row.entry_observed_price,
                exit_observed_price=row.exit_observed_price,
                entry_execution=_quote_from_json(row.entry_execution_quote),
                exit_execution=_quote_from_json(row.exit_execution_quote),
                execution_fallback_reason=(
                    row.exit_execution_fallback_reason or row.entry_execution_fallback_reason
                ),
            )
            result = await self._session.execute(
                insert(PaperShadowTradeAudit)
                .values(
                    position_id=row.id,
                    shadow_wallet_id=wallet.id,
                    wallet_code=wallet.wallet_code,
                    **_shadow_audit_row(record),
                )
                .on_conflict_do_nothing(index_elements=[PaperShadowTradeAudit.position_id])
                .returning(PaperShadowTradeAudit.id)
            )
            written += int(result.scalar_one_or_none() is not None)
        return written

    async def _positions(self, wallet_id: object) -> Sequence[PaperShadowPosition]:
        return (
            await self._session.scalars(
                select(PaperShadowPosition)
                .where(PaperShadowPosition.shadow_wallet_id == wallet_id)
                .order_by(PaperShadowPosition.opened_at.desc())
            )
        ).all()

    async def _open_positions(self, wallet_id: object) -> Sequence[PaperShadowPosition]:
        return (
            await self._session.scalars(
                select(PaperShadowPosition)
                .where(
                    PaperShadowPosition.shadow_wallet_id == wallet_id,
                    PaperShadowPosition.status == PositionStatus.OPEN.value,
                )
                .order_by(PaperShadowPosition.last_evaluated_at.asc())
                .limit(settings.PAPER_WALLET_REVIEW_BATCH_LIMIT)
            )
        ).all()

    async def _held_mints(self, wallet_id: object) -> set[str]:
        rows = await self._session.scalars(
            select(PaperShadowPosition.mint_address).where(
                PaperShadowPosition.shadow_wallet_id == wallet_id
            )
        )
        return set(rows.all())

    async def _open_mints(self, wallet_id: object) -> set[str]:
        rows = await self._session.scalars(
            select(PaperShadowPosition.mint_address).where(
                PaperShadowPosition.shadow_wallet_id == wallet_id,
                PaperShadowPosition.status == PositionStatus.OPEN.value,
            )
        )
        return set(rows.all())

    async def _decisions(self, wallet_code: str) -> Sequence[PaperShadowDecision]:
        return (
            await self._session.scalars(
                select(PaperShadowDecision)
                .where(PaperShadowDecision.wallet_code == wallet_code)
                .order_by(PaperShadowDecision.decided_at.desc())
            )
        ).all()

    async def _cash_for(self, wallet: PaperShadowWallet) -> Decimal:
        rows = await self._positions(wallet.id)
        open_rows = [row for row in rows if row.status == PositionStatus.OPEN.value]
        closed_rows = [row for row in rows if row.status == PositionStatus.CLOSED.value]
        closed = [trade for trade in (_to_closed(row) for row in closed_rows) if trade]
        return metrics.cash_for(
            wallet.starting_balance, [_to_open(row) for row in open_rows], closed
        )

    async def _audited_position_ids(self, wallet_id: object) -> set[str]:
        rows = await self._session.scalars(
            select(PaperShadowTradeAudit.position_id).where(
                PaperShadowTradeAudit.shadow_wallet_id == wallet_id
            )
        )
        return {str(row) for row in rows.all()}

    async def _advance(
        self, position_id: object, *, peak_price: Decimal, last_evaluated_at: datetime
    ) -> None:
        await self._session.execute(
            update(PaperShadowPosition)
            .where(
                PaperShadowPosition.id == position_id,
                PaperShadowPosition.status == PositionStatus.OPEN.value,
                PaperShadowPosition.last_evaluated_at <= last_evaluated_at,
            )
            .values(
                peak_price=func.greatest(PaperShadowPosition.peak_price, peak_price),
                last_evaluated_at=last_evaluated_at,
            )
        )

    async def _close(
        self,
        position_id: object,
        *,
        exit_price: Decimal,
        closed_at: datetime,
        exit_reason: str,
        peak_price: Decimal,
        exit_observed_price: Decimal,
        exit_execution: ExecutionQuote | execution.LegacyExecution,
    ) -> bool:
        result = await self._session.execute(
            update(PaperShadowPosition)
            .where(
                PaperShadowPosition.id == position_id,
                PaperShadowPosition.status == PositionStatus.OPEN.value,
            )
            .values(
                status=PositionStatus.CLOSED.value,
                exit_price=exit_price,
                exit_observed_price=exit_observed_price,
                closed_at=closed_at,
                exit_reason=exit_reason,
                peak_price=peak_price,
                last_evaluated_at=closed_at,
                **_exit_execution_values(exit_execution),
            )
            .returning(PaperShadowPosition.id)
        )
        return result.scalar_one_or_none() is not None


def _spec_for(code: str) -> ShadowSpec:
    for spec in SHADOW_SPECS:
        if spec.code == code:
            return spec
    raise KeyError(code)


def _reasons_for(
    spec: ShadowSpec,
    opportunity: Opportunity,
    *,
    held: set[str],
    open_now: set[str],
) -> list[str]:
    reasons: list[str] = []
    mint = opportunity.mint_address
    snapshot = opportunity.snapshot
    if mint in open_now:
        return [ShadowReason.ALREADY_HELD]
    if mint in held:
        return [ShadowReason.ALREADY_TRADED]
    if snapshot is None or opportunity.observed_at is None:
        return [ShadowReason.NO_MARKET_DATA]
    if opportunity.price_usd is None or opportunity.price_usd <= 0:
        return [ShadowReason.NO_PRICE]
    status = snapshot.trading_status
    if status is not None and str(status.value) != eligibility.TRADEABLE_STATUS:
        reasons.append(ShadowReason.NOT_TRADEABLE)
    if opportunity.liquidity_usd is None or opportunity.liquidity_usd <= 0:
        reasons.append(ShadowReason.NO_LIQUIDITY)
    if (
        spec.min_score is not None
        and opportunity.radar.current_opportunity_score < spec.min_score
    ):
        reasons.append(ShadowReason.RADAR_BELOW_THRESHOLD)
    if spec.min_market_cap is not None and (
        opportunity.market_cap is None or opportunity.market_cap < spec.min_market_cap
    ):
        reasons.append(ShadowReason.MARKET_CAP_TOO_LOW)
    if spec.max_market_cap is not None and (
        opportunity.market_cap is None or opportunity.market_cap > spec.max_market_cap
    ):
        reasons.append(ShadowReason.MARKET_CAP_TOO_HIGH)
    found = opportunity.execution_quote
    if spec.require_jupiter and not isinstance(found, ExecutionQuote):
        reasons.append(ShadowReason.JUPITER_QUOTE_UNAVAILABLE)

    # A Jupiter quote can be structurally valid while being economically
    # inconsistent with the market snapshot (for example because token
    # decimals or the quoted route are stale/bad). Never allow such a quote
    # to manufacture an instant paper gain or loss.
    if (
        isinstance(found, ExecutionQuote)
        and opportunity.price_usd is not None
        and opportunity.price_usd > 0
    ):
        execution_price_deviation = (
            abs(found.estimated_price_usd - opportunity.price_usd) / opportunity.price_usd
        )
        if execution_price_deviation > Decimal("0.50"):
            reasons.append(ShadowReason.EXECUTION_PRICE_MISMATCH)

    quality = opportunity.execution_quality
    if spec.allowed_qualities is not None and quality not in spec.allowed_qualities:
        reasons.append(ShadowReason.EXECUTION_QUALITY_BELOW_THRESHOLD)
    if spec.max_entry_impact_pct is not None and (
        opportunity.impact_pct is None or opportunity.impact_pct >= spec.max_entry_impact_pct
    ):
        reasons.append(ShadowReason.PRICE_IMPACT_TOO_HIGH)
    return reasons


def _entry_execution_values(
    found: ExecutionQuote | execution.LegacyExecution | None,
) -> dict[str, Any]:
    if isinstance(found, ExecutionQuote):
        return {
            "entry_execution_model_version": found.model_version,
            "entry_execution_quote": found.as_json(),
            "entry_execution_quoted_at": found.quoted_at,
            "entry_execution_context_slot": found.context_slot,
            "entry_execution_price_impact_pct": found.price_impact_pct,
            "entry_execution_fee_usd": found.platform_fee_usd,
            "entry_execution_route": found.route,
            "entry_execution_confidence": found.confidence,
            "entry_execution_fallback_reason": None,
        }
    if isinstance(found, execution.LegacyExecution):
        return {
            "entry_execution_model_version": found.model_version,
            "entry_execution_quote": None,
            "entry_execution_quoted_at": None,
            "entry_execution_context_slot": None,
            "entry_execution_price_impact_pct": None,
            "entry_execution_fee_usd": None,
            "entry_execution_route": None,
            "entry_execution_confidence": found.confidence,
            "entry_execution_fallback_reason": found.reason,
        }
    return {
        "entry_execution_model_version": None,
        "entry_execution_quote": None,
        "entry_execution_quoted_at": None,
        "entry_execution_context_slot": None,
        "entry_execution_price_impact_pct": None,
        "entry_execution_fee_usd": None,
        "entry_execution_route": None,
        "entry_execution_confidence": None,
        "entry_execution_fallback_reason": None,
    }


def _exit_execution_values(
    found: ExecutionQuote | execution.LegacyExecution,
) -> dict[str, Any]:
    if isinstance(found, ExecutionQuote):
        return {
            "exit_execution_model_version": found.model_version,
            "exit_execution_quote": found.as_json(),
            "exit_execution_quoted_at": found.quoted_at,
            "exit_execution_context_slot": found.context_slot,
            "exit_execution_price_impact_pct": found.price_impact_pct,
            "exit_execution_fee_usd": found.platform_fee_usd,
            "exit_execution_route": found.route,
            "exit_execution_confidence": found.confidence,
            "exit_execution_fallback_reason": None,
        }
    return {
        "exit_execution_model_version": found.model_version,
        "exit_execution_quote": None,
        "exit_execution_quoted_at": None,
        "exit_execution_context_slot": None,
        "exit_execution_price_impact_pct": None,
        "exit_execution_fee_usd": None,
        "exit_execution_route": None,
        "exit_execution_confidence": found.confidence,
        "exit_execution_fallback_reason": found.reason,
    }


def _reading_at(
    rows: Sequence[TokenMarketSnapshot], at: datetime
) -> TokenMarketSnapshot | None:
    eligible = [row for row in rows if row.captured_at <= at]
    if not eligible:
        return None
    return max(eligible, key=lambda row: row.captured_at)


def _wallet_report(
    wallet: PaperShadowWallet,
    positions: Sequence[PaperShadowPosition],
    decisions: Sequence[PaperShadowDecision],
    latest: dict[str, TokenMarketSnapshot],
    *,
    now: datetime,
) -> dict[str, object]:
    open_rows = [row for row in positions if row.status == PositionStatus.OPEN.value]
    closed_rows = [row for row in positions if row.status == PositionStatus.CLOSED.value]
    closed = [trade for trade in (_to_closed(row) for row in closed_rows) if trade]
    price_map = {
        row.mint_address: (
            latest[row.mint_address].price_usd if row.mint_address in latest else None
        )
        for row in open_rows
    }
    summary = metrics.summarise(
        starting_balance=wallet.starting_balance,
        open_positions=[_to_open(row) for row in open_rows],
        prices=price_map,
        closed=closed,
    )
    accepted = [row for row in decisions if row.decision == "accepted"]
    rejected = [row for row in decisions if row.decision == "rejected"]
    reason_counts: Counter[str] = Counter()
    for row in rejected:
        reason_counts.update(_reasons(row.reason_codes))

    net_returns = [_net_or_gross(row) for row in closed_rows]
    winners = [value for value in net_returns if value > 0]
    losers = [value for value in net_returns if value < 0]
    gross_profit = sum((value for value in winners), _ZERO)
    gross_loss = sum((-value for value in losers), _ZERO)
    expectancy = (
        None if not net_returns else (sum(net_returns, _ZERO) / Decimal(len(net_returns)))
    )
    best = max(closed_rows, key=_net_or_gross, default=None)
    worst = min(closed_rows, key=_net_or_gross, default=None)

    position_pnl_by_mint: dict[str, Decimal | None] = {}
    for pos_closed in closed_rows:
        if pos_closed.exit_price is not None:
            position_pnl_by_mint[pos_closed.mint_address] = (
                pos_closed.quantity * pos_closed.exit_price
            ) - pos_closed.size_usd
    for pos_open in open_rows:
        mark = price_map.get(pos_open.mint_address)
        if mark is not None:
            position_pnl_by_mint[pos_open.mint_address] = (
                pos_open.quantity * mark
            ) - pos_open.size_usd

    return {
        "code": wallet.wallet_code,
        "name": wallet.display_name,
        "strategy_id": wallet.strategy_id,
        "strategy_version": wallet.strategy_version,
        "summary": _spec_for(wallet.wallet_code).summary,
        "started_at": wallet.started_at,
        "current_equity": summary.equity,
        "cash": summary.cash,
        "gross_return": summary.realised_pnl,
        "net_return": sum(net_returns, _ZERO).quantize(_MONEY),
        "profit_factor": (
            None if gross_loss <= 0 else (gross_profit / gross_loss).quantize(Decimal("0.01"))
        ),
        "expectancy": None if expectancy is None else expectancy.quantize(_MONEY),
        "win_rate_pct": summary.win_rate_pct,
        "max_drawdown_pct": summary.max_drawdown_pct,
        "capital_utilization_pct": _capital_utilization(summary.invested_usd, summary.equity),
        "accepted_opportunities": len(accepted),
        "rejected_opportunities": len(rejected),
        "acceptance_rate_pct": _pct(len(accepted), len(decisions)),
        "top_rejection_reasons": dict(reason_counts.most_common(8)),
        "average_radar_score": _avg([row.radar_score for row in decisions]),
        "average_market_cap": _avg([row.market_cap for row in decisions]),
        "average_liquidity_usd": _avg([row.liquidity_usd for row in decisions]),
        "average_entry_impact_pct": _avg([row.entry_impact_pct for row in decisions]),
        "average_token_age_hours": _age_hours(
            _avg_int([row.token_age_seconds for row in decisions])
        ),
        "average_hold_hours": summary.average_hold_hours,
        "average_winner": None if not winners else (sum(winners, _ZERO) / len(winners)),
        "average_loser": None if not losers else (sum(losers, _ZERO) / len(losers)),
        "best_trade": _trade_card(best),
        "worst_trade": _trade_card(worst),
        "open_positions": len(open_rows),
        "closed_positions": len(closed_rows),
        "position_pnl_by_mint": position_pnl_by_mint,
        "promotion_score": _promotion_score(
            net_return=sum(net_returns, _ZERO),
            profit_factor=None
            if gross_loss <= 0
            else (gross_profit / gross_loss).quantize(Decimal("0.01")),
            expectancy=expectancy,
            closed_count=len(closed_rows),
            win_rate=summary.win_rate_pct,
            max_drawdown=summary.max_drawdown_pct,
        ),
        "promotion_eligible": _promotion_eligible(
            net_return=sum(net_returns, _ZERO),
            profit_factor=None if gross_loss <= 0 else gross_profit / gross_loss,
            expectancy=expectancy,
            closed_count=len(closed_rows),
        ),
        "promotion_blockers": _promotion_blockers(
            net_return=sum(net_returns, _ZERO),
            profit_factor=None if gross_loss <= 0 else gross_profit / gross_loss,
            expectancy=expectancy,
            closed_count=len(closed_rows),
        ),
        "decisions": [
            {
                "mint_address": row.mint_address,
                "wallet_code": row.wallet_code,
                "decision": row.decision,
                "reason_codes": _reasons(row.reason_codes),
                "radar_rank": row.radar_rank,
                "radar_score": row.radar_score,
                "market_cap": row.market_cap,
                "liquidity_usd": row.liquidity_usd,
                "entry_impact_pct": row.entry_impact_pct,
                "execution_quality": row.execution_quality,
                "decided_at": row.decided_at,
            }
            for row in decisions[:200]
        ],
        "observed_at": now,
    }


def _reasons(raw: object) -> list[str]:
    if isinstance(raw, list):
        return [str(item) for item in raw]
    return []


def _net_or_gross(row: PaperShadowPosition) -> Decimal:
    if row.exit_price is None:
        return _ZERO
    return (row.quantity * row.exit_price) - row.size_usd


def _shadow_audit_row(record: audit.TradeAudit) -> dict[str, object]:
    """Project the shared audit record onto the shadow audit table.

    Manual exits are V1-only today. `audit.record()` includes
    `manual_action_at` because it writes V1 manual-sell audits, but shadow
    wallets have no manual close path and their audit table intentionally has no
    such column. SQLAlchemy treats unknown INSERT keys as a compile-time error,
    so the projection has to happen before the shadow audit insert.
    """

    allowed = set(PaperShadowTradeAudit.__table__.columns.keys())
    return {key: value for key, value in record.as_row().items() if key in allowed}


def _pct(part: int, total: int) -> Decimal | None:
    if total <= 0:
        return None
    return (Decimal(part) / Decimal(total) * Decimal(100)).quantize(Decimal("0.01"))


def _avg(values: Sequence[Decimal | None]) -> Decimal | None:
    actual = [value for value in values if value is not None]
    if not actual:
        return None
    return (sum(actual, _ZERO) / Decimal(len(actual))).quantize(_PCT)


def _avg_int(values: Sequence[int | None]) -> Decimal | None:
    actual = [Decimal(value) for value in values if value is not None]
    if not actual:
        return None
    return sum(actual, _ZERO) / Decimal(len(actual))


def _age_hours(seconds: Decimal | None) -> Decimal | None:
    if seconds is None:
        return None
    return (seconds / Decimal(3600)).quantize(Decimal("0.01"))


def _capital_utilization(invested: Decimal, equity: Decimal | None) -> Decimal | None:
    if equity is None or equity <= 0:
        return None
    return (invested / equity * Decimal(100)).quantize(Decimal("0.01"))


def _trade_card(row: PaperShadowPosition | None) -> dict[str, object] | None:
    if row is None or row.exit_price is None or row.closed_at is None:
        return None
    pnl = _net_or_gross(row)
    return {
        "mint_address": row.mint_address,
        "opened_at": row.opened_at,
        "closed_at": row.closed_at,
        "pnl_usd": pnl.quantize(_MONEY),
        "return_pct": (pnl / row.size_usd * Decimal(100)).quantize(_PCT)
        if row.size_usd > 0
        else None,
        "exit_reason": row.exit_reason,
    }


def _promotion_score(
    *,
    net_return: Decimal,
    profit_factor: Decimal | None,
    expectancy: Decimal | None,
    closed_count: int,
    win_rate: Decimal | None,
    max_drawdown: Decimal | None,
) -> Decimal:
    score = Decimal(0)
    if net_return > 0:
        score += Decimal(25)
    if profit_factor is not None and profit_factor > Decimal(1):
        score += min(Decimal(25), (profit_factor - _ONE) * Decimal(25))
    if expectancy is not None and expectancy > 0:
        score += Decimal(20)
    score += min(Decimal(15), Decimal(closed_count) / Decimal(_MIN_PROMOTION_TRADES) * 15)
    if win_rate is not None:
        score += min(Decimal(10), win_rate / Decimal(10))
    if max_drawdown is not None:
        score += max(_ZERO, Decimal(5) - min(Decimal(5), max_drawdown / Decimal(10)))
    return score.quantize(Decimal("0.01"))


def _promotion_eligible(
    *,
    net_return: Decimal,
    profit_factor: Decimal | None,
    expectancy: Decimal | None,
    closed_count: int,
) -> bool:
    return (
        closed_count >= _MIN_PROMOTION_TRADES
        and net_return > 0
        and profit_factor is not None
        and profit_factor > _PROMOTION_PROFIT_FACTOR
        and expectancy is not None
        and expectancy > 0
    )


def _promotion_blockers(
    *,
    net_return: Decimal,
    profit_factor: Decimal | None,
    expectancy: Decimal | None,
    closed_count: int,
) -> list[str]:
    blockers: list[str] = []
    if closed_count < _MIN_PROMOTION_TRADES:
        blockers.append("needs_100_completed_live_trades")
    if net_return <= 0:
        blockers.append("net_return_not_positive")
    if profit_factor is None or profit_factor <= _PROMOTION_PROFIT_FACTOR:
        blockers.append("profit_factor_not_above_1_20")
    if expectancy is None or expectancy <= 0:
        blockers.append("expectancy_not_positive")
    return blockers


def _missed_opportunities(rows: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    accepted_by_mint: dict[str, list[tuple[str, Decimal | None]]] = defaultdict(list)
    for wallet in rows:
        w_code = str(wallet["code"])
        pnl_map = cast(dict[str, Decimal | None], wallet.get("position_pnl_by_mint", {}))
        for item in cast(list[dict[str, object]], wallet["decisions"]):
            if item["decision"] == "accepted":
                mint = str(item["mint_address"])
                pnl = pnl_map.get(mint)
                accepted_by_mint[mint].append((w_code, pnl))

    missed: list[dict[str, object]] = []
    for wallet in rows:
        w_code = str(wallet["code"])
        for item in cast(list[dict[str, object]], wallet["decisions"]):
            mint = str(item["mint_address"])
            if item["decision"] != "rejected" or mint not in accepted_by_mint:
                continue
            others = [entry for entry in accepted_by_mint[mint] if entry[0] != w_code]
            if not others:
                continue

            accepted_wallets = [entry[0] for entry in others]
            pnls = [entry[1] for entry in others if entry[1] is not None]
            avg_pnl = sum(pnls, _ZERO) / Decimal(len(pnls)) if pnls else None

            outcome = "pending"
            if avg_pnl is not None:
                if avg_pnl > 0:
                    outcome = "missed_winner"
                elif avg_pnl < 0:
                    outcome = "good_rejection"

            missed.append(
                {
                    "wallet_code": w_code,
                    "mint_address": mint,
                    "reason_codes": item["reason_codes"],
                    "accepted_elsewhere": accepted_wallets,
                    "outcome": outcome,
                    "pnl_usd": str(avg_pnl.quantize(_MONEY)) if avg_pnl is not None else None,
                }
            )
    return missed[:100]


def _filter_performance(rows: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    counts: Counter[str] = Counter()
    winning_prevented: Counter[str] = Counter()
    losing_prevented: Counter[str] = Counter()
    pl_saved: defaultdict[str, Decimal] = defaultdict(lambda: _ZERO)
    pl_missed: defaultdict[str, Decimal] = defaultdict(lambda: _ZERO)

    accepted_pnls_by_mint: dict[str, list[Decimal]] = defaultdict(list)
    for wallet in rows:
        pnl_map = cast(dict[str, Decimal | None], wallet.get("position_pnl_by_mint", {}))
        for item in cast(list[dict[str, object]], wallet["decisions"]):
            if item["decision"] == "accepted":
                mint = str(item["mint_address"])
                pnl = pnl_map.get(mint)
                if pnl is not None:
                    accepted_pnls_by_mint[mint].append(pnl)

    for wallet in rows:
        for item in cast(list[dict[str, object]], wallet["decisions"]):
            if item["decision"] == "rejected":
                reasons = cast(list[str], item["reason_codes"])
                counts.update(reasons)
                mint = str(item["mint_address"])
                other_pnls = accepted_pnls_by_mint.get(mint, [])
                if other_pnls:
                    avg_pnl = sum(other_pnls, _ZERO) / Decimal(len(other_pnls))
                    for reason in reasons:
                        if avg_pnl > 0:
                            winning_prevented[reason] += 1
                            pl_missed[reason] += avg_pnl
                        elif avg_pnl < 0:
                            losing_prevented[reason] += 1
                            pl_saved[reason] += abs(avg_pnl)

    results = []
    for reason, count in counts.most_common():
        win_prev = winning_prevented[reason]
        lose_prev = losing_prevented[reason]
        saved = pl_saved[reason] if lose_prev > 0 else None
        missed = pl_missed[reason] if win_prev > 0 else None
        avg_cost = (
            (missed / Decimal(win_prev)).quantize(_MONEY)
            if (win_prev > 0 and missed is not None)
            else None
        )

        results.append(
            {
                "reason_code": reason,
                "times_triggered": count,
                "winning_trades_prevented": win_prev,
                "losing_trades_prevented": lose_prev,
                "net_pl_saved": str(saved.quantize(_MONEY)) if saved is not None else None,
                "net_pl_missed": str(missed.quantize(_MONEY)) if missed is not None else None,
                "average_opportunity_cost": str(avg_cost) if avg_cost is not None else None,
            }
        )
    return results
