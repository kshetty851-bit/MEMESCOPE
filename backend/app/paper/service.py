"""Running the simulation, and reading it back.

Two responsibilities, deliberately in one place because they share a shape:

* `review` advances the wallet — **exits first, then entries**, so cash freed by
  a close is available to the same pass. The order is part of the published
  rule, not an implementation detail: the other order would decline entries the
  strategy could actually have funded, and Sprint 30 §4 states the loop as
  "exit, cash becomes available, immediately buy the next highest-ranked
  eligible token".
* `read` assembles everything the API serves, from positions and market history.

Neither invents anything. Prices come from `token_market_snapshots`, candidates
come from the Radar's own ranking, and the benchmarks are measured from the
wallet's own start instant over the same universe. Nothing here is a
recommendation, and nothing here touches a chain.

**Only the live wallet moves.** Every read filters on `archived_at IS NULL`;
archived generations are frozen where they were, including any positions that
were open at the moment of archival. Those never settle, and the archive view
says so rather than letting a reader assume they were closed at a fair price.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.market import TokenMarketSnapshot, TradingStatus
from app.models.paper import PaperPosition, PaperTradeAudit, PaperWallet
from app.models.radar import RadarToken
from app.paper import audit, benchmark, eligibility, execution, exits, metrics
from app.paper.execution import (
    ExecutionQuote,
    ExecutionQuoteUnavailableError,
)
from app.paper.exits import ExitRules
from app.paper.models import (
    Candidate,
    ClosedTrade,
    ExitReason,
    OpenPosition,
    PositionStatus,
    Quote,
)
from app.paper.repository import PaperRepository
from app.paper.strategy import AnyStrategy, TrackRecordBracketStrategy, registry
from app.radar.repository import RadarRepository
from app.repositories.market import MarketSnapshotRepository, EnrichmentStateRepository
from app.repositories.token import TokenRepository
from app.services.jupiter import JupiterExecutionClient

logger = get_logger(__name__)

_PCT = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class ReviewOutcome:
    """What one pass did. Reported so a stalled evaluator is visible.

    `refusals` is a count per published entry condition. Without it, "opened 0"
    is ambiguous between "nothing qualified" and "the evaluator is broken", and
    the wallet has to be able to tell those apart on its own log line.
    """

    evaluated: int
    closed: int
    opened: int
    audited: int
    candidates: int
    #: True when the scan hit its bound before running out of Radar. A capped
    #: search that says nothing looks exactly like an exhaustive one.
    candidates_truncated: bool
    refusals: dict[str, int]

    def as_dict(self) -> dict[str, object]:
        return {
            "evaluated": self.evaluated,
            "closed": self.closed,
            "opened": self.opened,
            "audited": self.audited,
            "candidates": self.candidates,
            "candidates_truncated": self.candidates_truncated,
            **{f"refused_{reason}": count for reason, count in sorted(self.refusals.items())},
        }


@dataclass(frozen=True, slots=True)
class ManualSellPreview:
    """The exact observed quote and cost model a manual close would use."""

    position: PaperPosition
    symbol: str | None
    name: str | None
    image_url: str | None
    quote: TokenMarketSnapshot
    quote_age_seconds: Decimal
    is_stale: bool
    warning: str | None
    audit: audit.TradeAudit
    exit_execution: ExecutionQuote | execution.LegacyExecution


@dataclass(frozen=True, slots=True)
class ManualSellOutcome:
    """What a confirmed manual paper close did."""

    preview: ManualSellPreview
    audited: bool
    opened: int
    candidates: int
    candidates_truncated: bool
    refusals: dict[str, int]


def _rules_for(position: PaperPosition) -> ExitRules:
    """The exit rules **this position was opened under**, read off its own row.

    Not from the configured strategy. That is the anti-hindsight guarantee made
    concrete: the bounds were fixed at entry and written once, so a position
    settles under the rules that were published when it was taken, even if the
    live strategy is later replaced. A wallet that re-read its exits from
    current configuration could re-read them favourably.

    One exactness note, stated because it is the kind of thing that quietly
    stops being true: `ExitRules` expresses a target and a stop as *multiples*
    of entry, while the row stores them as absolute prices, so a bracket
    position's rules are reconstructed by division and multiplied back. That
    round trip is exact to Decimal's working precision but not bit-identical.
    Generation 5 settles its stored barriers on the dedicated observed-bracket
    path; archived generations are frozen and never re-evaluated.
    """
    hold_for: timedelta | None = None
    if position.expires_at is not None:
        hold_for = position.expires_at - position.opened_at

    entry = position.entry_price
    priced = entry > 0
    target, stop = position.target_price, position.stop_price
    return ExitRules(
        take_profit_multiple=(None if target is None or not priced else target / entry),
        stop_loss_multiple=(None if stop is None or not priced else stop / entry),
        trailing_drawdown=position.trailing_drawdown,
        hold_for=hold_for,
    )


def _to_open(position: PaperPosition) -> OpenPosition:
    return OpenPosition(
        mint_address=position.mint_address,
        opened_at=position.opened_at,
        entry_price=position.entry_price,
        quantity=position.quantity,
        size_usd=position.size_usd,
        peak_price=position.peak_price,
        target_price=position.target_price,
        stop_price=position.stop_price,
        expires_at=position.expires_at,
        trailing_drawdown=position.trailing_drawdown,
    )


def _to_closed(position: PaperPosition) -> ClosedTrade | None:
    """A finished row as the metrics read it, or `None` if it is not finished.

    Defensive rather than asserted: a half-written close would otherwise crash
    the whole wallet read, and one unreadable row must not take the page down.
    """
    if position.closed_at is None or position.exit_price is None:
        return None
    try:
        reason = ExitReason(position.exit_reason or "")
    except ValueError:  # pragma: no cover - guarded by the writer
        return None
    return ClosedTrade(
        mint_address=position.mint_address,
        opened_at=position.opened_at,
        closed_at=position.closed_at,
        size_usd=position.size_usd,
        entry_price=position.entry_price,
        exit_price=position.exit_price,
        quantity=position.quantity,
        reason=reason,
    )


def _quote(row: TokenMarketSnapshot) -> Quote | None:
    if row.price_usd is None:
        return None
    return Quote(
        captured_at=row.captured_at,
        price_usd=row.price_usd,
        liquidity_usd=row.liquidity_usd,
        market_cap=row.market_cap,
    )


class PaperWalletService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = PaperRepository(session)
        self._market = MarketSnapshotRepository(session)
        self._radar = RadarRepository(session)
        self._execution = JupiterExecutionClient()

    @property
    def strategy(self) -> AnyStrategy:
        """The strategy that trades, falling back to the registry default.

        A configured id that is not registered falls back rather than crashing,
        and says so: a typo in an environment variable must not stop the wallet,
        and it must not silently trade rules nobody chose either. Since Sprint 30
        the registry holds exactly one operational strategy, so this is a
        validation of configuration rather than a choice between modes.
        """
        configured = registry.get(settings.PAPER_WALLET_STRATEGY_ID)
        if configured is None or not configured.operational:
            logger.warning(
                "paper_strategy_unknown",
                configured=settings.PAPER_WALLET_STRATEGY_ID,
                using=registry.default.id,
            )
            return registry.default
        return configured

    async def wallet(self, *, now: datetime) -> PaperWallet:
        """The live wallet, created once at the moment of the first pass.

        `started_at` is that moment, and every benchmark is measured from it —
        which is why it is written here rather than defaulted in the database:
        the wallet and its comparisons must begin at exactly the same instant.
        """
        existing = await self._repository.live_wallet()
        if existing is not None:
            return existing

        strategy = self.strategy
        return await self._repository.ensure_wallet(
            strategy_id=strategy.id,
            strategy_version=strategy.version,
            starting_balance=Decimal(str(settings.PAPER_WALLET_STARTING_BALANCE)),
            generation=await self._repository.next_generation(),
            started_at=now,
        )

    # --- Advancing the simulation -------------------------------------------

    async def review(self, *, now: datetime) -> ReviewOutcome:
        """One pass: settle exits, record them, then open what cash allows."""
        wallet = await self.wallet(now=now)
        evaluated, closed = await self._settle_exits(wallet, now=now)
        audited = await self._record_audits(wallet)
        opened, candidates, truncated, refusals = await self._open_entries(wallet, now=now)
        return ReviewOutcome(
            evaluated=evaluated,
            closed=closed,
            opened=opened,
            audited=audited,
            candidates=candidates,
            candidates_truncated=truncated,
            refusals=refusals,
        )

    async def manual_sell_preview(
        self, mint_address: str, *, now: datetime
    ) -> ManualSellPreview:
        """A paper-only close preview priced from the newest observable quote."""
        wallet = await self._repository.live_wallet()
        if wallet is None:
            raise NotFoundError(
                "The paper wallet has not been created yet.",
                code="paper_wallet_not_found",
            )

        position = await self._repository.position_for(wallet.id, mint_address)
        if position is None:
            raise NotFoundError(
                "This token is not in the live paper wallet.",
                code="paper_position_not_found",
                details={"mint_address": mint_address},
            )
        if position.status != PositionStatus.OPEN.value:
            raise ConflictError(
                "This paper position is already closed.",
                code="paper_position_already_closed",
                details={"mint_address": mint_address, "status": position.status},
            )

        quote = await self._market.latest_priced_for_mint_as_of(mint_address, as_of=now)
        if quote is None:
            raise ValidationError(
                "No usable observed quote exists for this paper position.",
                code="paper_quote_unavailable",
                details={"mint_address": mint_address},
            )

        token = (await TokenRepository(self._session).get_many_by_mints([mint_address])).get(
            mint_address
        )
        return await self._manual_preview_from(
            wallet=wallet,
            position=position,
            quote=quote,
            name=token.name if token is not None else None,
            symbol=token.symbol if token is not None else None,
            image_url=token.image_url if token is not None else None,
            now=now,
        )

    async def manual_sell(self, mint_address: str, *, now: datetime) -> ManualSellOutcome:
        """Close one open paper position at the newest observed quote.

        The close guard, audit uniqueness and replacement allocator are the same
        ones the automated evaluator uses. A duplicate request can therefore
        fail cleanly, but it cannot close, audit, release cash or replace twice.
        """
        wallet = await self._repository.live_wallet()
        if wallet is None:
            raise NotFoundError(
                "The paper wallet has not been created yet.",
                code="paper_wallet_not_found",
            )

        preview = await self.manual_sell_preview(mint_address, now=now)
        closed = await self._repository.close(
            preview.position.id,
            exit_price=preview.audit.exit_price,
            closed_at=preview.audit.exit_at,
            exit_reason=ExitReason.MANUAL.value,
            peak_price=max(preview.position.peak_price, preview.audit.exit_price),
            manual_action_at=now,
            exit_observed_price=preview.audit.exit_observed_price,
            exit_execution_model_version=preview.audit.exit_execution_model_version,
            exit_execution_quote=preview.audit.exit_execution_quote,
            exit_execution_quoted_at=preview.audit.exit_execution_quoted_at,
            exit_execution_context_slot=preview.audit.exit_execution_context_slot,
            exit_execution_price_impact_pct=preview.audit.exit_execution_price_impact_pct,
            exit_execution_fee_usd=preview.audit.exit_execution_fee_usd,
            exit_execution_route=preview.audit.exit_execution_route,
            exit_execution_confidence=preview.audit.execution_confidence,
            exit_execution_fallback_reason=preview.audit.execution_fallback_reason,
        )
        if not closed:
            raise ConflictError(
                "This paper position is already closed.",
                code="paper_position_already_closed",
                details={"mint_address": mint_address},
            )

        audited = await self._repository.record_audit(
            position_id=preview.position.id,
            wallet_id=wallet.id,
            **preview.audit.as_row(),
        )
        opened, candidates, truncated, refusals = await self._open_entries(wallet, now=now)
        return ManualSellOutcome(
            preview=preview,
            audited=audited,
            opened=opened,
            candidates=candidates,
            candidates_truncated=truncated,
            refusals=refusals,
        )

    async def _manual_preview_from(
        self,
        *,
        wallet: PaperWallet,
        position: PaperPosition,
        quote: TokenMarketSnapshot,
        name: str | None,
        symbol: str | None,
        image_url: str | None,
        now: datetime,
    ) -> ManualSellPreview:
        exit_price = quote.price_usd
        if exit_price is None or exit_price <= 0:  # pragma: no cover - query filters this
            raise ValidationError(
                "No usable observed quote exists for this paper position.",
                code="paper_quote_unavailable",
                details={"mint_address": position.mint_address},
            )
        exit_execution = await self._exit_execution_for(
            position=position,
            decision_price=exit_price,
            decision_liquidity=quote.liquidity_usd,
            now=now,
        )
        execution_price = (
            exit_execution.estimated_price_usd
            if isinstance(exit_execution, ExecutionQuote)
            else exit_price
        )
        exit_at = now if isinstance(exit_execution, ExecutionQuote) else quote.captured_at
        observed_trade = ClosedTrade(
            mint_address=position.mint_address,
            opened_at=position.opened_at,
            closed_at=exit_at,
            size_usd=position.size_usd,
            entry_price=position.entry_price,
            exit_price=execution_price,
            quantity=position.quantity,
            reason=ExitReason.MANUAL,
        )
        record = audit.record(
            observed_trade,
            symbol=symbol,
            entry_market_cap=position.entry_market_cap,
            entry_liquidity_usd=position.entry_liquidity_usd,
            exit_market_cap=audit.market_cap_at_price(
                observed_market_cap=quote.market_cap,
                observed_price=quote.price_usd,
                execution_price=execution_price,
            ),
            exit_liquidity_usd=quote.liquidity_usd,
            strategy_id=wallet.strategy_id,
            strategy_version=wallet.strategy_version,
            wallet_generation=wallet.generation,
            manual_action_at=now,
            entry_observed_price=position.entry_observed_price,
            exit_observed_price=exit_price,
            entry_execution=self._entry_execution_from(position),
            exit_execution=exit_execution
            if isinstance(exit_execution, ExecutionQuote)
            else None,
            execution_fallback_reason=(
                exit_execution.reason
                if isinstance(exit_execution, execution.LegacyExecution)
                else None
            ),
        )
        age = Decimal(max(0.0, (now - quote.captured_at).total_seconds())).quantize(_PCT)
        is_stale = age > Decimal(settings.HEALTH_TRACKED_STALE_SECONDS)
        return ManualSellPreview(
            position=position,
            symbol=symbol,
            name=name,
            image_url=image_url,
            quote=quote,
            quote_age_seconds=age,
            is_stale=is_stale,
            warning=(
                "This quote is stale. Confirming will still use this observed price; "
                "the system will not invent a fresher fill."
                if is_stale
                else None
            ),
            audit=record,
            exit_execution=exit_execution,
        )

    async def _entry_execution_for(
        self,
        *,
        candidate: Candidate,
        input_usd: Decimal,
        decimals: int | None,
        now: datetime,
    ) -> ExecutionQuote | execution.LegacyExecution:
        if settings.PAPER_EXECUTION_MODEL != "jupiter":
            return execution.LegacyExecution("PAPER_EXECUTION_MODEL=legacy")
        if decimals is None:
            return execution.LegacyExecution(
                "Token decimals unavailable for Jupiter entry quote."
            )
        try:
            return await self._execution.buy_quote(
                output_mint=candidate.mint_address,
                input_usd=input_usd,
                output_decimals=decimals,
                now=now,
            )
        except ExecutionQuoteUnavailableError as exc:
            logger.warning(
                "paper_jupiter_entry_quote_failed",
                mint_address=candidate.mint_address,
                reason=str(exc),
            )
            return execution.LegacyExecution(str(exc))

    async def _exit_execution_for(
        self,
        *,
        position: PaperPosition,
        decision_price: Decimal,
        decision_liquidity: Decimal | None,
        now: datetime,
    ) -> ExecutionQuote | execution.LegacyExecution:
        if settings.PAPER_EXECUTION_MODEL != "jupiter":
            return execution.LegacyExecution("PAPER_EXECUTION_MODEL=legacy")

        decimals = self._entry_output_decimals(position)
        if decimals is None:
            token = (
                await TokenRepository(self._session).get_many_by_mints([position.mint_address])
            ).get(position.mint_address)
            decimals = token.decimals if token is not None else None
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
                "paper_jupiter_exit_quote_failed",
                mint_address=position.mint_address,
                reason=str(exc),
            )
            notional = position.quantity * decision_price
            return execution.LegacyExecution(
                f"{exc}; fallback priced at observed notional {notional} "
                f"with liquidity {decision_liquidity}"
            )

    def _entry_output_decimals(self, position: PaperPosition) -> int | None:
        quote = position.entry_execution_quote
        if not isinstance(quote, dict):
            return None
        value = quote.get("output_decimals")
        return value if isinstance(value, int) else None

    def _quote_from_json(self, quote: dict[str, object] | None) -> ExecutionQuote | None:
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
                    None
                    if quote.get("context_slot") is None
                    else int(str(quote["context_slot"]))
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

    def _entry_execution_from(self, position: PaperPosition) -> ExecutionQuote | None:
        return self._quote_from_json(position.entry_execution_quote)

    def _exit_execution_from(self, position: PaperPosition) -> ExecutionQuote | None:
        return self._quote_from_json(position.exit_execution_quote)

    def _execution_open_values(
        self, found: ExecutionQuote | execution.LegacyExecution
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

    def _execution_close_values(
        self, found: ExecutionQuote | execution.LegacyExecution
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

    async def review_observed_mints(
        self, mint_addresses: Sequence[str], *, now: datetime
    ) -> ReviewOutcome | None:
        """Advance held positions touched by a newly committed observation.

        This is an acceleration path, not a different strategy evaluator. It
        reuses the normal replay-based exit resolver, and only opens a
        replacement after this focused pass actually closes a position. The
        scheduled full review remains responsible for missed events and quiet
        holdings.
        """
        mints = list(dict.fromkeys(mint_addresses))
        if not mints:
            return None

        wallet = await self._repository.live_wallet()
        if wallet is None:
            return None

        evaluated, closed = await self._settle_exits(wallet, now=now, mints=mints)
        if evaluated == 0:
            return None

        audited = await self._record_audits(wallet)
        if closed:
            opened, candidates, truncated, refusals = await self._open_entries(wallet, now=now)
        else:
            opened, candidates, truncated, refusals = 0, 0, False, {}
        return ReviewOutcome(
            evaluated=evaluated,
            closed=closed,
            opened=opened,
            audited=audited,
            candidates=candidates,
            candidates_truncated=truncated,
            refusals=refusals,
        )

    async def _settle_exits(
        self,
        wallet: PaperWallet,
        *,
        now: datetime,
        mints: Sequence[str] | None = None,
    ) -> tuple[int, int]:
        """Walk each open position's unseen observations and close the breaches.

        The whole reproducibility guarantee lives in these few lines. Each
        position is replayed over **every** reading since its own watermark, in
        order, and closes at the first breach — so a worker that missed six
        hours produces the same trades as one that missed none.

        One resolver runs every rule set. The trailing stop is not a second
        code path: `exits.resolve` takes the rules as data, and the rules come
        off the position's own row.
        """
        positions = await self._repository.open_positions(
            wallet.id, limit=settings.PAPER_WALLET_REVIEW_BATCH_LIMIT, mints=mints
        )
        if not positions:
            return 0, 0

        # One query for the batch, from the oldest watermark in it; each row is
        # then trimmed to its own. `window_for_mints` documents the same shape.
        # A resumed historical wallet must never replay its archived interval.
        # The resume watermark is independent of (and may be newer than) each
        # preserved position watermark, which remains an immutable historical
        # fact until a genuinely new quote advances it.
        resume_watermark = wallet.resume_watermark_at
        effective_watermarks = {
            position.id: max(
                position.last_evaluated_at,
                resume_watermark or position.last_evaluated_at,
            )
            for position in positions
        }
        oldest = min(effective_watermarks.values())
        series = await self._market.series_for_mints(
            [position.mint_address for position in positions], since=oldest
        )

        closed = 0
        for position in positions:
            rows = [
                row
                for row in series.get(position.mint_address, [])
                if row.captured_at > effective_watermarks[position.id]
            ]
            if position.trailing_activation_multiple is not None:
                closed += int(
                    await self._settle_activated_trail(position, rows=rows, now=now)
                )
                continue

            if wallet.strategy_id in {
                "paper_all_scanned_tp125_sl50_v1",
                "paper_track_record_tp125_sl50_v1",
            }:
                closed += int(await self._settle_observed_bracket(position, rows=rows, now=now))
                continue

            quotes = [quote for quote in (_quote(row) for row in rows) if quote is not None]
            found, running_peak = exits.resolve(
                _rules_for(position),
                entry_price=position.entry_price,
                opened_at=position.opened_at,
                quotes=quotes,
                peak=position.peak_price,
            )

            if found is None:
                # Nothing breached. Carry the peak and the watermark forward so
                # the same readings are never replayed — and so the peak
                # survives snapshot pruning.
                # A review without a quote is not an observation.  In
                # particular, it must not overwrite the archived watermark on
                # a resumed wallet merely because the scheduler ran.
                new_evaluated_at = position.last_evaluated_at
                if quotes:
                    new_evaluated_at = quotes[-1].captured_at
                elif rows:
                    new_evaluated_at = rows[-1].captured_at
                else:
                    new_evaluated_at = max(now, position.last_evaluated_at)
                
                await self._repository.advance(
                    position.id,
                    peak_price=running_peak,
                    last_evaluated_at=new_evaluated_at,
                )
                continue

            decision_quote = next(
                (quote for quote in quotes if quote.captured_at == found.at),
                None,
            )
            observed_exit_price = (
                decision_quote.price_usd if decision_quote is not None else found.price_usd
            )
            exit_execution = await self._exit_execution_for(
                position=position,
                decision_price=found.price_usd,
                decision_liquidity=(
                    decision_quote.liquidity_usd if decision_quote is not None else None
                ),
                now=now,
            )
            closed_now = await self._repository.close(
                position.id,
                exit_price=(
                    exit_execution.estimated_price_usd
                    if isinstance(exit_execution, ExecutionQuote)
                    else found.price_usd
                ),
                closed_at=now if isinstance(exit_execution, ExecutionQuote) else found.at,
                exit_reason=found.reason.value,
                # `resolve` returns the high *before* the breaching reading, so
                # this is already the peak that belongs to the trade rather than
                # to the token. A high printed after the exit is not this
                # position's — it sold before it.
                peak_price=running_peak,
                exit_observed_price=observed_exit_price,
                **self._execution_close_values(exit_execution),
            )
            closed += int(closed_now)

        return len(positions), closed

    async def _settle_observed_bracket(
        self, position: PaperPosition, *, rows: Sequence[TokenMarketSnapshot], now: datetime
    ) -> bool:
        """First observed TP/SL barrier wins; gap fills retain the observed quote."""
        for row in rows:
            price = row.price_usd
            if price is None or price <= 0:
                continue
            if position.stop_price is not None and price <= position.stop_price:
                return await self._close_observed_bracket(
                    position, row=row, reason=ExitReason.STOP
                )
            if position.target_price is not None and price >= position.target_price:
                return await self._close_observed_bracket(
                    position, row=row, reason=ExitReason.TARGET
                )
        
        prices = [row.price_usd for row in rows if row.price_usd is not None]
        await self._repository.advance(
            position.id,
            peak_price=max([position.peak_price, *prices]) if prices else position.peak_price,
            last_evaluated_at=rows[-1].captured_at if rows else max(now, position.last_evaluated_at),
        )
        return False

    async def _close_observed_bracket(
        self, position: PaperPosition, *, row: TokenMarketSnapshot, reason: ExitReason
    ) -> bool:
        assert row.price_usd is not None
        exit_execution = await self._exit_execution_for(
            position=position,
            decision_price=row.price_usd,
            decision_liquidity=row.liquidity_usd,
            now=row.captured_at,
        )
        return await self._repository.close(
            position.id,
            exit_price=(
                exit_execution.estimated_price_usd
                if isinstance(exit_execution, ExecutionQuote)
                else row.price_usd
            ),
            exit_observed_price=row.price_usd,
            closed_at=row.captured_at,
            exit_reason=reason.value,
            peak_price=max(position.peak_price, row.price_usd),
            **self._execution_close_values(exit_execution),
        )

    async def _settle_activated_trail(
        self,
        position: PaperPosition,
        *,
        rows: Sequence[TokenMarketSnapshot],
        now: datetime,
    ) -> bool:
        """Apply the 2x activation and observed-price 25% trailing exit.

        The source has point samples, not candles.  Therefore the sample that
        crosses 2x may arm a trail but cannot also trigger one, and a later gap
        through the trail settles at its observed price rather than the
        theoretical level.
        """
        activation_multiple = position.trailing_activation_multiple
        drawdown = position.trailing_drawdown
        if activation_multiple is None or drawdown is None:  # pragma: no cover
            return False

        activated_at = position.trailing_activated_at
        activation_price = position.trailing_activation_observed_price
        peak = position.peak_price
        theoretical_stop = position.trailing_stop_price
        last_at = position.last_evaluated_at
        for row in rows:
            last_at = row.captured_at
            price = row.price_usd
            if price is None or price <= 0:
                # No price means no executable terminal or trailing exit.
                continue
            if activated_at is None:
                if price >= position.entry_price * activation_multiple:
                    activated_at = row.captured_at
                    activation_price = price
                    peak = max(peak, price)
                    theoretical_stop = peak * (Decimal(1) - drawdown)
                continue

            # The stop is evaluated from the high before this point sample.  A
            # single sample cannot establish an unseen high-then-low sequence.
            if theoretical_stop is not None and price <= theoretical_stop:
                return await self._repository.close(
                    position.id,
                    exit_price=price,
                    exit_observed_price=price,
                    closed_at=row.captured_at,
                    exit_reason=ExitReason.TRAILING_STOP.value,
                    peak_price=peak,
                    trailing_trigger_price=theoretical_stop,
                    trailing_trigger_observed_price=price,
                    exit_execution_model_version="observed_trigger_v1",
                    exit_execution_confidence="observed_gap_conservative",
                    exit_execution_fallback_reason=(
                        "Settled at the observed triggering price; the theoretical "
                        "trailing stop was not assumed as a fill."
                    ),
                )
            if price > peak:
                peak = price
                theoretical_stop = peak * (Decimal(1) - drawdown)

        await self._repository.advance_activated_trail(
            position.id,
            peak_price=peak,
            trailing_stop_price=theoretical_stop,
            last_evaluated_at=last_at if rows else now,
            activated_at=activated_at,
            activation_observed_price=activation_price,
        )
        return False

    async def _close_terminal(
        self, position: PaperPosition, *, row: TokenMarketSnapshot, peak: Decimal
    ) -> bool:
        """Use only a provider's explicit inactive state plus an observed price."""
        assert row.price_usd is not None and row.price_usd > 0
        return await self._repository.close(
            position.id,
            exit_price=row.price_usd,
            exit_observed_price=row.price_usd,
            closed_at=row.captured_at,
            exit_reason=ExitReason.TERMINAL.value,
            peak_price=peak,
            exit_execution_model_version="observed_terminal_v1",
            exit_execution_confidence="provider_terminal_observation",
            exit_execution_fallback_reason=(
                "Provider reported inactive with a contemporaneous usable observed price."
            ),
        )

    async def _record_audits(self, wallet: PaperWallet) -> int:
        """Write the permanent record for any closed trade that lacks one.

        Separated from `_settle_exits` on purpose. A close and its audit row are
        written in the same transaction, but the audit is driven by *state* — "is
        there a closed position with no record?" — rather than by the event, so a
        trade closed before this sprint, or by a pass that crashed between the
        two writes, is picked up on the next run instead of being lost.

        The exit market cap and pool depth come from the reading nearest the exit
        timestamp. That is what the platform observed; it is not the fill, and
        the disclosure on every net figure says so.
        """
        closed_rows = await self._repository.closed_positions(wallet.id)
        if not closed_rows:
            return 0

        already = await self._repository.audited_position_ids(wallet.id)
        pending = [row for row in closed_rows if str(row.id) not in already]
        if not pending:
            return 0

        mints = [row.mint_address for row in pending]
        tokens = await TokenRepository(self._session).get_many_by_mints(mints)
        # From the earliest entry in the batch, so every exit reading is inside
        # the window. Trimmed per position below.
        oldest = min(row.opened_at for row in pending)
        series = await self._market.series_for_mints(mints, since=oldest)

        written = 0
        for row in pending:
            trade = _to_closed(row)
            if trade is None:  # pragma: no cover - guarded by the writer
                continue

            exit_reading = _reading_at(series.get(row.mint_address, []), trade.closed_at)
            token = tokens.get(row.mint_address)
            record = audit.record(
                trade,
                symbol=token.symbol if token is not None else None,
                entry_market_cap=row.entry_market_cap,
                entry_liquidity_usd=row.entry_liquidity_usd,
                exit_market_cap=audit.market_cap_at_price(
                    observed_market_cap=exit_reading.market_cap if exit_reading else None,
                    observed_price=exit_reading.price_usd if exit_reading else None,
                    execution_price=row.exit_price,
                ),
                exit_liquidity_usd=exit_reading.liquidity_usd if exit_reading else None,
                strategy_id=wallet.strategy_id,
                strategy_version=wallet.strategy_version,
                wallet_generation=wallet.generation,
                manual_action_at=row.manual_action_at,
                entry_observed_price=row.entry_observed_price,
                exit_observed_price=row.exit_observed_price,
                entry_execution=self._entry_execution_from(row),
                exit_execution=self._exit_execution_from(row),
                execution_fallback_reason=(
                    row.exit_execution_fallback_reason or row.entry_execution_fallback_reason
                ),
            )
            if await self._repository.record_audit(
                position_id=row.id, wallet_id=wallet.id, **record.as_row()
            ):
                written += 1

        return written

    async def _open_entries(
        self, wallet: PaperWallet, *, now: datetime
    ) -> tuple[int, int, bool, dict[str, int]]:
        """Offer the ranked Radar to the strategy, highest score first.

        Rank order is the rule, not an optimisation: §4 says the wallet buys the
        *highest-ranked eligible* token, so the scan takes the Radar's own
        ordering and stops at the first token that passes. Filling by whichever
        row the database returned first would make the result depend on a query
        plan.

        The scan is bounded by `PAPER_WALLET_CANDIDATE_LIMIT`, and when that
        bound is reached it is **reported**. A capped search that says nothing
        reads exactly like an exhaustive one that found nothing.
        """
        strategy = self.strategy
        if isinstance(strategy, TrackRecordBracketStrategy):
            return await self._open_track_record_entries(wallet, strategy=strategy, now=now)
        limit = strategy.top_n or settings.PAPER_WALLET_CANDIDATE_LIMIT
        entries = await self._radar.list_entries(
            category=None, active_only=True, sort="score", limit=limit, offset=0
        )
        if not entries:
            return 0, 0, False, {}

        verdicts = await self._screen(wallet, entries)

        mints = [verdict.mint_address for verdict in verdicts if verdict.eligible]
        tokens = await TokenRepository(self._session).get_many_by_mints(mints)
        token_ids = {mint: token.id for mint, token in tokens.items()}

        # Cash is derived from the rows as they stand, then decremented locally
        # as this pass commits capital — so two entries in one pass cannot both
        # spend the same dollar.
        cash = await self._cash_for(wallet)

        opened = 0
        refusals = eligibility.refusal_counts(verdicts)
        for verdict in verdicts:
            candidate = verdict.candidate
            if candidate is None:
                continue

            instruction = strategy.entry_for(candidate, cash_available=cash, now=now)
            if instruction is None:
                # Every eligibility condition already passed, so the only reason
                # left is cash. Counted, because idle capital with qualified
                # tokens in front of it is a fact the dashboard has to state.
                refusals[eligibility.Refusal.INSUFFICIENT_CASH] = (
                    refusals.get(eligibility.Refusal.INSUFFICIENT_CASH, 0) + 1
                )
                continue

            entry_execution = await self._entry_execution_for(
                candidate=candidate,
                input_usd=instruction.size_usd,
                decimals=(
                    tokens[candidate.mint_address].decimals
                    if candidate.mint_address in tokens
                    else None
                ),
                now=now,
            )
            execution_price = (
                entry_execution.estimated_price_usd
                if isinstance(entry_execution, ExecutionQuote)
                else instruction.price_usd
            )
            quantity = (
                entry_execution.output_amount
                if isinstance(entry_execution, ExecutionQuote)
                else instruction.quantity
            )

            created = await self._repository.open_position(
                wallet_id=wallet.id,
                mint_address=candidate.mint_address,
                token_id=token_ids.get(candidate.mint_address),
                opened_at=instruction.opened_at,
                entry_rank=candidate.rank,
                entry_price=execution_price,
                entry_observed_price=instruction.price_usd,
                size_usd=instruction.size_usd,
                quantity=quantity,
                **self._execution_open_values(entry_execution),
                target_price=instruction.target_price,
                stop_price=instruction.stop_price,
                expires_at=instruction.expires_at,
                trailing_drawdown=instruction.trailing_drawdown,
                trailing_activation_multiple=instruction.trailing_activation_multiple,
                entry_market_cap=audit.market_cap_at_price(
                    observed_market_cap=instruction.market_cap,
                    observed_price=instruction.price_usd,
                    execution_price=execution_price,
                ),
                entry_liquidity_usd=instruction.liquidity_usd,
                status=PositionStatus.OPEN.value,
                peak_price=execution_price,
                last_evaluated_at=instruction.opened_at,
            )
            if created is None:
                # Lost the race to another evaluator. Ordinary, not an error.
                refusals[eligibility.Refusal.ALREADY_HELD] = (
                    refusals.get(eligibility.Refusal.ALREADY_HELD, 0) + 1
                )
                continue

            cash -= instruction.size_usd
            opened += 1

        return opened, len(entries), len(entries) >= limit, dict(refusals)

    async def _open_track_record_entries(
        self,
        wallet: PaperWallet,
        *,
        strategy: TrackRecordBracketStrategy,
        now: datetime,
    ) -> tuple[int, int, bool, dict[str, int]]:
        """Open canonical Track Record admissions without re-scoring them."""
        await self._repository.lock_wallet(wallet.id)
        token_repository = TokenRepository(self._session)
        limit = settings.PAPER_WALLET_CANDIDATE_LIMIT
        admissions = await self._repository.track_record_admissions_after(
            watermark=wallet.started_at, limit=limit, as_of=now
        )
        if not admissions:
            return 0, 0, False, {}

        snapshots = await self._market.first_priced_for_mints_since(
            {
                admission.mint_address: admission.first_detected_at
                for admission in admissions
            },
            as_of=now,
        )
        tokens = await token_repository.get_many_by_mints(
            [admission.mint_address for admission in admissions]
        )
        cash = await self._cash_for(wallet)
        opened = 0
        refusals: dict[str, int] = {}
        for rank, admission in enumerate(admissions, start=1):
            snapshot = snapshots.get(admission.mint_address)
            if snapshot is None:
                continue
            token = tokens.get(admission.mint_address)
            candidate = Candidate(
                mint_address=admission.mint_address,
                rank=rank,
                price_usd=snapshot.price_usd,
                observed_at=snapshot.captured_at,
                liquidity_usd=snapshot.liquidity_usd,
                market_cap=snapshot.market_cap,
                volume_24h=snapshot.volume_24h,
            )
            if cash < strategy.trade_size_usd:
                claimed = await self._repository.claim_track_record_entry_decision(
                    wallet=wallet,
                    admission=admission,
                    decision="declined",
                    reason=eligibility.Refusal.INSUFFICIENT_CASH.value,
                )
                if claimed:
                    refusals[eligibility.Refusal.INSUFFICIENT_CASH] = (
                        refusals.get(eligibility.Refusal.INSUFFICIENT_CASH, 0) + 1
                    )
                continue

            claimed = await self._repository.claim_track_record_entry_decision(
                wallet=wallet,
                admission=admission,
                decision="entered",
            )
            if not claimed:
                continue
            instruction = strategy.entry_for(candidate, cash_available=cash, now=now)
            if instruction is None:  # guarded above
                continue
            entry_execution = await self._entry_execution_for(
                candidate=candidate,
                input_usd=instruction.size_usd,
                decimals=token.decimals if token is not None else None,
                now=now,
            )
            entry_price = (
                entry_execution.estimated_price_usd
                if isinstance(entry_execution, ExecutionQuote)
                else instruction.price_usd
            )
            quantity = (
                entry_execution.output_amount
                if isinstance(entry_execution, ExecutionQuote)
                else instruction.quantity
            )
            created = await self._repository.open_position(
                wallet_id=wallet.id,
                mint_address=admission.mint_address,
                token_id=admission.token_id,
                opened_at=instruction.opened_at,
                entry_rank=rank,
                entry_price=entry_price,
                entry_observed_price=instruction.price_usd,
                size_usd=instruction.size_usd,
                quantity=quantity,
                **self._execution_open_values(entry_execution),
                target_price=entry_price * strategy.take_profit_multiple,
                stop_price=entry_price * strategy.stop_loss_multiple,
                expires_at=None,
                trailing_drawdown=None,
                trailing_activation_multiple=None,
                entry_market_cap=audit.market_cap_at_price(
                    observed_market_cap=instruction.market_cap,
                    observed_price=instruction.price_usd,
                    execution_price=entry_price,
                ),
                entry_liquidity_usd=instruction.liquidity_usd,
                status=PositionStatus.OPEN.value,
                peak_price=entry_price,
                last_evaluated_at=instruction.opened_at,
            )
            if created is not None:
                cash -= instruction.size_usd
                opened += 1
        return opened, len(admissions), len(admissions) >= limit, refusals

    async def _screen(
        self, wallet: PaperWallet, entries: Sequence[RadarToken]
    ) -> list[eligibility.Verdict]:
        """Judge a ranked Radar page against §5's conditions.

        Shared by the evaluator and the read path so the page and the trades can
        never disagree about what qualified.
        """
        rows = list(entries)
        mints = [row.mint_address for row in rows]
        held = await self._repository.held_mints(wallet.id)
        open_now = await self._repository.open_mints(wallet.id)
        prices = await self._market.latest_for_mints(mints)

        observations = []
        for rank, row in enumerate(rows, start=1):
            snapshot = prices.get(row.mint_address)
            observations.append(
                eligibility.Observation(
                    mint_address=row.mint_address,
                    rank=rank,
                    has_snapshot=snapshot is not None,
                    observed_at=snapshot.captured_at if snapshot else None,
                    price_usd=snapshot.price_usd if snapshot else None,
                    liquidity_usd=snapshot.liquidity_usd if snapshot else None,
                    market_cap=snapshot.market_cap if snapshot else None,
                    volume_24h=snapshot.volume_24h if snapshot else None,
                    trading_status=(str(snapshot.trading_status.value) if snapshot else None),
                )
            )

        return eligibility.screen(observations, held_ever=held, open_now=open_now)

    async def _cash_for(self, wallet: PaperWallet) -> Decimal:
        open_rows = await self._repository.open_positions(wallet.id)
        closed_rows = await self._repository.closed_positions(wallet.id)
        closed = [trade for trade in (_to_closed(row) for row in closed_rows) if trade]
        return metrics.cash_for(
            wallet.starting_balance, [_to_open(row) for row in open_rows], closed
        )

    # --- Reading it back -----------------------------------------------------

    async def read(self, *, now: datetime) -> WalletRead:
        """Everything the API serves."""
        wallet = await self.wallet(now=now)
        positions = await self._repository.all_positions(wallet.id)

        open_rows = [row for row in positions if row.status == PositionStatus.OPEN.value]
        closed_rows = [row for row in positions if row.status == PositionStatus.CLOSED.value]
        closed = [trade for trade in (_to_closed(row) for row in closed_rows) if trade]

        snapshots = await self._market.latest_for_mints(
            [row.mint_address for row in open_rows], since=wallet.resume_watermark_at
        )
        prices: dict[str, Decimal | None] = {
            row.mint_address: (
                snapshots[row.mint_address].price_usd
                if row.mint_address in snapshots
                else None
            )
            for row in open_rows
        }
        price_times: dict[str, datetime | None] = {
            row.mint_address: (
                snapshots[row.mint_address].captured_at
                if row.mint_address in snapshots
                else None
            )
            for row in open_rows
        }

        all_mints = [row.mint_address for row in positions]
        
        enrichment_states = await EnrichmentStateRepository(self._session).get_many_by_mints(
            [row.mint_address for row in open_rows]
        )
        check_times: dict[str, datetime | None] = {
            row.mint_address: (
                enrichment_states[row.mint_address].last_attempt_at
                if row.mint_address in enrichment_states
                else None
            )
            for row in open_rows
        }

        names = await TokenRepository(self._session).get_many_by_mints(
            list(set(all_mints))
        )

        m = metrics.summarise(
            starting_balance=wallet.starting_balance,
            open_positions=[_to_open(row) for row in open_rows],
            prices=prices,
            closed=closed,
        )

        return WalletRead(
            wallet=wallet,
            strategy=self.strategy,
            metrics=m,
            positions=list(positions),
            prices=prices,
            price_times=price_times,
            check_times=check_times,
            names={mint: (token.name, token.symbol) for mint, token in names.items()},
            images={mint: token.image_url for mint, token in names.items()},
            benchmarks=await self.benchmarks(wallet),
            waiting_for=await self._waiting_for(wallet, cash=m.cash),
            audit_log=await self._repository.audit_log(wallet.id, limit=200),
            audit_count=await self._repository.audit_count(wallet.id),
            pnl_today=metrics.pnl_since(
                closed, since=now.replace(hour=0, minute=0, second=0, microsecond=0)
            ),
            observed_at=now,
        )

    async def benchmarks(self, wallet: PaperWallet) -> list[benchmark.BenchmarkResult]:
        """Both Radar comparisons, measured from the wallet's own start.

        Deliberately **not** `RadarRepository.benchmark`, which averages the
        return-since-detection of every token the Radar has ever seen. That
        covers a different period with different capital, and a wallet launched
        today has not lived through it. Sprint 30 §2 is explicit: the wallet and
        its benchmarks begin at exactly the same timestamp.
        """
        universe = await self._radar.entries_present_since(wallet.started_at)
        if not universe:
            return []

        mints = [row.mint_address for row in universe]
        # The price at the wallet's start, for tokens that were already on the
        # Radar then. A token detected later is bought at its detection price,
        # which is the first price the benchmark could have paid for it.
        at_start = await self._market.price_as_of_for_mints(mints, as_of=wallet.started_at)
        current = await self._market.latest_for_mints(mints)

        constituents = []
        for row in universe:
            available_at = max(row.first_detected_at, wallet.started_at)
            entry_price = (
                at_start.get(row.mint_address)
                if row.first_detected_at <= wallet.started_at
                else row.first_price
            )
            snapshot = current.get(row.mint_address)
            constituents.append(
                benchmark.Constituent(
                    mint_address=row.mint_address,
                    available_at=available_at,
                    entry_price=entry_price,
                    current_price=snapshot.price_usd if snapshot else None,
                )
            )

        capital = wallet.starting_balance
        trade_size = self.strategy.trade_size_usd
        return [
            benchmark.buy_every_radar_token(
                constituents, capital=capital, trade_size=trade_size
            ),
            benchmark.equal_weight_radar(constituents, capital=capital),
        ]

    async def _waiting_for(self, wallet: PaperWallet, *, cash: Decimal) -> WaitingState | None:
        """Why the wallet is holding cash, when it is.

        **Two different idle states, and the wallet must name which one.** The
        first version of this returned `None` when cash was below one position,
        on the reasoning that there was nothing to explain. That was wrong, and
        it showed: on 2026-08-05 the wallet sat on $92.38 with nine positions
        open for an hour, opening nothing and saying nothing, and the page gave
        a reader no way to tell that from a broken evaluator.

        So:

        * **Cash below one position** — something may well qualify, but the
          strategy declines rather than part-filling, so this is a wait for a
          *close*. Reported with the shortfall, and with how many tokens are
          queued behind it so the reader can see the opportunity is there and
          the capital is not.
        * **Cash available, nothing qualifies** — §9's state, with a count per
          refused condition.

        `None` in two cases, both of which have nothing to say. Fundable cash
        with a qualified token in front of it, which the next pass will take —
        a page that claimed to be waiting then would be worse than one that said
        nothing. And **no cash at all**, which is a fully invested wallet rather
        than an idle one; "holding cash until a position closes" printed over
        $0.00 would be nonsense.
        """
        trade_size = self.strategy.trade_size_usd
        if cash <= 0:
            return None
        limit = self.strategy.top_n or settings.PAPER_WALLET_CANDIDATE_LIMIT
        entries = await self._radar.list_entries(
            category=None, active_only=True, sort="score", limit=limit, offset=0
        )
        verdicts = await self._screen(wallet, entries)
        eligible = sum(1 for verdict in verdicts if verdict.eligible)

        if cash < trade_size:
            return WaitingState(
                reason=eligibility.Idle.CASH_BELOW_TRADE_SIZE.value,
                message=eligibility.CASH_SHORT_MESSAGE,
                idle_cash=cash,
                trade_size=trade_size,
                # What it is short by. Published because "$92.38 of cash" alone
                # reads as money the wallet is choosing not to use.
                shortfall=trade_size - cash,
                considered=len(verdicts),
                eligible=eligible,
                refusals=eligibility.refusal_counts(verdicts),
            )

        if eligible:
            return None

        return WaitingState(
            reason=eligibility.Idle.NOTHING_QUALIFIES.value,
            message=eligibility.WAITING_MESSAGE,
            idle_cash=cash,
            trade_size=trade_size,
            shortfall=Decimal(0),
            considered=len(verdicts),
            eligible=0,
            refusals=eligibility.refusal_counts(verdicts),
        )


def _reading_at(
    series: Sequence[TokenMarketSnapshot], at: datetime
) -> TokenMarketSnapshot | None:
    """The observation that dated an exit, or the closest one at or before it.

    Exits are dated to an observation, so the exact reading is normally present.
    The `<=` fallback covers a trailing stop, whose exit *price* is the trigger
    level rather than the observed price — the reading that breached it is still
    the one whose market cap and depth belong to the trade.
    """
    best: TokenMarketSnapshot | None = None
    for row in series:
        if row.captured_at > at:
            break
        best = row
    return best


@dataclass(frozen=True, slots=True)
class WaitingState:
    """Why the wallet is idle, whenever it is.

    `reason` is a stable code (`eligibility.Idle`); `message` is the sentence
    rendered from it server-side, the same rule as every other piece of prose
    here. A surface never composes one from the other.
    """

    reason: str
    message: str
    idle_cash: Decimal
    trade_size: Decimal
    #: How far the cash is short of one position. Zero when it is not short.
    shortfall: Decimal
    considered: int
    #: How many Radar tokens *would* be bought if the cash were there. The
    #: figure that separates "no opportunity" from "no capital".
    eligible: int
    refusals: dict[str, int]


@dataclass(frozen=True, slots=True)
class WalletRead:
    """The assembled read model. Rendering happens in `api.py`."""

    wallet: PaperWallet
    strategy: AnyStrategy
    metrics: metrics.WalletMetrics
    positions: list[PaperPosition]
    prices: dict[str, Decimal | None]
    #: When each mark was observed, so a surface can say how old it is.
    price_times: dict[str, datetime | None]
    #: The most recent market check attempt for each open position.
    check_times: dict[str, datetime | None]
    names: dict[str, tuple[str | None, str | None]]
    images: dict[str, str | None]
    benchmarks: list[benchmark.BenchmarkResult]
    #: `None` unless the wallet is holding fundable cash with nothing eligible.
    waiting_for: WaitingState | None
    audit_log: Sequence[PaperTradeAudit]
    audit_count: int
    pnl_today: Decimal
    observed_at: datetime


def utcnow() -> datetime:
    """The clock, in one place, so the pure modules never reach for it."""
    return datetime.now(UTC)


__all__ = [
    "PaperWalletService",
    "ReviewOutcome",
    "WaitingState",
    "WalletRead",
    "utcnow",
]
