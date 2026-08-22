"""The Karthik wallet, advancing one pass at a time.

Every pass does the same two things in the same order:

    1. Look at every open position and settle the ones that can leave.
    2. Look at every new Track Record admission and decide it, once.

**Exits are settled before entries**, and the two halves are independent. If
cash is exhausted, step 2 has nothing to do and step 1 carries on exactly as
before — a wallet that stopped watching its open book because it could not buy
anything would be the worst possible failure of this experiment, so there is
deliberately no switch, flag or condition that can reach step 1.

## The two prices, and why they are not the same number

Karthik decides from a **stored observation** — the freshest reading the
enrichment pipeline has for the mint — and executes against a **live router
quote**. The observation says *whether* to act; the quote says *at what*. That
split is what keeps the book honest in both directions:

* An entry is never priced at the Track Record's own historical mark. If the
  worker sees the admission twenty minutes late, it buys at the price twenty
  minutes late, because that is the price Karthik could have paid.
* An exit at the target is never priced at the print that triggered it. A pool
  can print any number once its liquidity is gone; only a router willing to
  quote the whole position establishes that the position could be sold.

## Why the target may be missed, and never invented

The target is judged against the **latest** observation, not by replaying the
series since the last pass. A spike to 1.3x that has already reverted is not an
exit here — Karthik holds, and the spike stays visible in `peak_price`.

The alternative was worse. Replaying would find the historical breach, and then
either book it at a price that no longer exists (a fill Karthik never had) or
book it at today's collapsed price while calling it a target hit (a loss
recorded as a win). Missing an unexecutable spike is the honest failure, and it
is the one this module chooses.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.karthik import rules
from app.karthik.repository import KarthikRepository
from app.karthik.rules import Decision, ExitReason, Hold, Observation
from app.models.karthik import KarthikOpportunity, KarthikPosition, KarthikWallet
from app.models.market import TokenMarketSnapshot
from app.models.token import DiscoveredToken
from app.paper import execution
from app.paper.execution import ExecutionQuote, ExecutionQuoteUnavailableError
from app.radar.repository import RadarRepository
from app.repositories.market import MarketSnapshotRepository
from app.repositories.token import TokenRepository
from app.security.mint import decode_mint_account
from app.services.jupiter import JupiterExecutionClient
from app.services.rpc.registry import get_rpc

logger = get_logger(__name__)

_MONEY = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class ReviewOutcome:
    """What one pass did. Logged in full, including the reasons for nothing."""

    evaluated: int = 0
    closed: int = 0
    opened: int = 0
    admissions: int = 0
    decisions: dict[str, int] = field(default_factory=dict)
    holds: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "evaluated": self.evaluated,
            "closed": self.closed,
            "opened": self.opened,
            "admissions": self.admissions,
            **{f"decision_{key}": value for key, value in self.decisions.items()},
            **{f"hold_{key}": value for key, value in self.holds.items()},
        }


def _observation(row: TokenMarketSnapshot) -> Observation:
    return Observation(
        price_usd=row.price_usd,
        liquidity_usd=row.liquidity_usd,
        captured_at=row.captured_at,
        trading_status=str(row.trading_status),
    )


class KarthikService:
    """The Karthik paper wallet.

    Holds no state between passes. Everything it needs is in the three
    `karthik_*` tables and in the market history it reads but never writes.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = KarthikRepository(session)
        self._market = MarketSnapshotRepository(session)
        self._radar = RadarRepository(session)
        self._tokens = TokenRepository(session)
        self._execution = JupiterExecutionClient()

    # --- Activation ----------------------------------------------------------

    async def activate(self, *, now: datetime) -> KarthikWallet:
        """Create the wallet once. Re-running returns the existing one unchanged.

        There is no reset, no second generation and no way to move
        `activated_at`. Karthik is one experiment with one start instant; if a
        different one is ever wanted it is a different wallet, not this one
        rewound.
        """
        return await self._repository.activate(
            name="Karthik",
            starting_capital=rules.STARTING_CAPITAL,
            trade_size=rules.TRADE_SIZE,
            take_profit_multiple=rules.TAKE_PROFIT_MULTIPLE,
            activated_at=now,
        )

    async def wallet(self) -> KarthikWallet | None:
        return await self._repository.wallet()

    # --- One pass ------------------------------------------------------------

    async def review(self, *, now: datetime) -> ReviewOutcome | None:
        """Settle what can leave, then decide what has arrived.

        `None` before activation. Not an empty outcome: "Karthik has not been
        started" and "Karthik did nothing this pass" are different facts, and
        only the second is a result.
        """
        wallet = await self._repository.wallet()
        if wallet is None:
            return None

        evaluated, closed, holds = await self._settle_exits(wallet, now=now)
        opened, admissions, decisions = await self._open_entries(wallet, now=now)
        return ReviewOutcome(
            evaluated=evaluated,
            closed=closed,
            opened=opened,
            admissions=admissions,
            decisions=decisions,
            holds=holds,
        )

    # --- Exits ---------------------------------------------------------------

    async def _settle_exits(
        self, wallet: KarthikWallet, *, now: datetime
    ) -> tuple[int, int, dict[str, int]]:
        """Walk the open book. Close only what can genuinely be sold.

        Runs before entries and shares nothing with them. In particular it never
        consults cash: a wallet with $0 free still monitors, still hits targets
        and still books the proceeds, which is the only way $0 is a temporary
        state rather than the end of the experiment.
        """
        positions = await self._repository.open_positions(
            wallet.id, limit=settings.KARTHIK_REVIEW_BATCH_LIMIT
        )
        if not positions:
            return 0, 0, {}

        latest = await self._market.latest_for_mints(
            [position.mint_address for position in positions]
        )
        closed = 0
        holds: dict[str, int] = {}
        for position in positions:
            row = latest.get(position.mint_address)
            observation = None if row is None else _observation(row)
            hold = await self._settle_one(position, observation, now=now)
            if hold is None:
                closed += 1
            else:
                holds[hold.value] = holds.get(hold.value, 0) + 1
        return len(positions), closed, holds

    async def _settle_one(
        self,
        position: KarthikPosition,
        observation: Observation | None,
        *,
        now: datetime,
    ) -> Hold | None:
        """One position's whole exit policy. `None` means it closed."""
        peak = position.peak_price
        if observation is not None and observation.price_usd is not None:
            peak = max(peak, observation.price_usd)

        # Death first, and only on the provider's own word. A price that has
        # fallen 95% is a losing position and is held; a pool the provider
        # reports as having no meaningful liquidity left is one nothing can be
        # sold into, and $0 is not an estimate of its value, it is the fact.
        if (
            observation is not None
            and rules.is_dead(observation)
            and await self._repository.close(
                position.id,
                closed_at=now,
                exit_price=Decimal(0),
                exit_observed_price=observation.price_usd,
                exit_proceeds_usd=Decimal(0),
                exit_reason=ExitReason.DEAD_ZERO.value,
                peak_price=peak,
                last_evaluated_at=observation.captured_at,
                last_market_check_at=now,
                exit_execution_model_version="provider_inactive_v1",
                exit_execution_confidence="provider_terminal_observation",
                exit_evidence=(
                    "The market provider reported this pool inactive — indexed with no "
                    "meaningful liquidity left — at "
                    f"{observation.captured_at.isoformat()}. Nothing could be sold, so "
                    "the position returned $0.00 rather than its last printed price."
                ),
            )
        ):
            return None

        hold = rules.hold_reason(
            observation,
            target_price=position.target_price,
            now=now,
            max_age_seconds=settings.KARTHIK_MAX_MARKET_AGE_SECONDS,
        )
        if hold is None:
            assert observation is not None and observation.price_usd is not None
            quote = await self._sell_quote(position, now=now)
            if quote is None:
                # At or above the target with depth reported, but no route would
                # quote the position. The target is not met: it requires a sale,
                # and nothing here will assume one. Held, and counted.
                hold = Hold.NO_EXECUTABLE_QUOTE
            elif await self._repository.close(
                position.id,
                closed_at=now,
                exit_price=quote.estimated_price_usd,
                exit_observed_price=observation.price_usd,
                # The router's own output, never `1.25 x cost`. If the quote
                # comes back worse than the print — a thin pool, a wide route —
                # the worse number is the one that goes on the books.
                exit_proceeds_usd=(quote.output_amount_usd or Decimal(0)).quantize(_MONEY),
                exit_reason=ExitReason.TARGET_1_25X.value,
                peak_price=peak,
                last_evaluated_at=observation.captured_at,
                last_market_check_at=now,
                **self._execution_close_values(quote),
                exit_evidence=(
                    f"Observed {observation.price_usd} at "
                    f"{observation.captured_at.isoformat()} against a target of "
                    f"{position.target_price}, with {observation.liquidity_usd} of "
                    "reported pool depth. Sold 100% at the executable route quote."
                ),
            ):
                return None
            else:  # pragma: no cover - lost a race with another pass
                hold = Hold.NO_EXECUTABLE_QUOTE

        await self._repository.advance(
            position.id,
            peak_price=peak,
            last_evaluated_at=(
                observation.captured_at
                if observation is not None
                else position.last_evaluated_at
            ),
            last_market_check_at=now,
        )
        return hold

    async def _sell_quote(
        self, position: KarthikPosition, *, now: datetime
    ) -> ExecutionQuote | None:
        """A real route for the whole position, or `None`.

        **There is no legacy fallback on this path, deliberately.** The entry
        side may fall back to the deterministic cost model because the worst
        case there is a slightly wrong purchase price. The worst case here is a
        rug booked as a 25% win, so an unquotable position is simply not sold.
        """
        if settings.PAPER_EXECUTION_MODEL != "jupiter":
            return None
        try:
            quote = await self._execution.sell_quote(
                input_mint=position.mint_address,
                quantity=position.quantity,
                input_decimals=position.decimals,
                now=now,
            )
        except ExecutionQuoteUnavailableError as exc:
            logger.info(
                "karthik_exit_quote_unavailable",
                mint_address=position.mint_address,
                reason=str(exc),
            )
            return None
        if quote.output_amount_usd is None or quote.output_amount_usd <= 0:
            return None
        return quote

    # --- Entries -------------------------------------------------------------

    async def _open_entries(
        self, wallet: KarthikWallet, *, now: datetime
    ) -> tuple[int, int, dict[str, int]]:
        """Decide every undecided Track Record admission, once each.

        ── THE ORDER OF THE TWO WRITES ─────────────────────────────────────

        The entry is **priced first and claimed second**. Claiming first would
        be simpler and would lie: a claim recording `entered` for an admission
        the pricing then refused would leave a ledger row with no position
        behind it, and the capture rate would count a trade that never
        happened. So nothing is claimed until the outcome of the claim is
        already known.

        Pricing before the claim can mean two concurrent passes both request a
        quote for the same mint. That costs one wasted HTTP call and cannot
        cost a duplicate position: only one of them wins the claim, and the
        position insert refuses a second row regardless.
        """
        if settings.KARTHIK_ENTRIES_PAUSED:
            # Entries only. This cannot reach `_settle_exits`, which has already
            # run above and does not consult it — the same separation the paper
            # wallet's own pause has, and for the same reason: a switch that
            # stopped exit monitoring would strand an open book.
            logger.info("karthik_entries_paused")
            return 0, 0, {"refused_entries_paused": 1}

        await self._repository.lock_wallet(wallet.id)
        admissions = await self._repository.undecided_admissions(
            wallet=wallet, limit=settings.KARTHIK_CANDIDATE_LIMIT, as_of=now
        )
        if not admissions:
            return 0, 0, {}

        mints = [admission.mint_address for admission in admissions]
        latest = await self._market.latest_for_mints(mints)
        tokens = await self._tokens.get_many_by_mints(mints)
        detections = await self._radar.detection_times_for(mints)
        cash = await self._cash(wallet)

        opened = 0
        decisions: dict[str, int] = {}

        async def record(mint: str, at: datetime, decision: Decision) -> None:
            if await self._repository.claim(
                wallet=wallet,
                mint_address=mint,
                track_record_at=at,
                decision=decision.value,
                decided_at=now,
            ):
                decisions[decision.value] = decisions.get(decision.value, 0) + 1

        for admission in admissions:
            mint = admission.mint_address
            row = latest.get(mint)
            observation = None if row is None else _observation(row)
            if observation is not None and not rules.is_fresh(
                observation, now=now, max_age_seconds=settings.KARTHIK_MAX_MARKET_AGE_SECONDS
            ):
                # A stale reading is not a price Karthik could have paid.
                observation = None

            decision = rules.entry_decision(cash=cash, observation=observation)
            if decision is not Decision.ENTERED:
                await record(mint, admission.first_detected_at, decision)
                continue

            assert row is not None and observation is not None
            # Decimals are required at *entry*, not at exit, because a position
            # whose exit could never be quoted is a position that could never be
            # sold — a trap, not a trade.
            decimals = await self._decimals_for(mint, token=tokens.get(mint))
            priced = (
                None
                if decimals is None
                else await self._price_entry(
                    mint,
                    observation=observation,
                    size=wallet.trade_size,
                    decimals=decimals,
                    now=now,
                )
            )
            if decimals is None or priced is None:
                await record(mint, admission.first_detected_at, Decision.SKIPPED_NO_MARKET)
                continue

            if not await self._repository.claim(
                wallet=wallet,
                mint_address=mint,
                track_record_at=admission.first_detected_at,
                decision=Decision.ENTERED.value,
                decided_at=now,
            ):
                # Another pass already decided this mint. Nothing to do — and
                # nothing *may* be done, or the same admission would be bought
                # twice.
                continue

            entry_price, quantity, quote = priced
            created = await self._repository.open_position(
                wallet_id=wallet.id,
                mint_address=mint,
                token_id=admission.token_id,
                symbol=(tokens[mint].symbol if mint in tokens else None),
                token_name=(tokens[mint].name if mint in tokens else None),
                # Never substituted. A mint with no discovery row records `NULL`
                # here and the page says so, rather than borrowing the entry
                # time and reporting a delay of zero.
                detected_at=detections.get(mint),
                track_record_at=admission.first_detected_at,
                opened_at=now,
                entry_price=entry_price,
                entry_observed_price=observation.price_usd,
                entry_observed_at=observation.captured_at,
                cost_basis=wallet.trade_size,
                quantity=quantity,
                decimals=decimals,
                target_price=rules.target_price_for(entry_price),
                pool_address=row.pool_address,
                entry_liquidity_usd=observation.liquidity_usd,
                entry_market_cap=row.market_cap,
                status="open",
                peak_price=observation.price_usd,
                last_evaluated_at=observation.captured_at,
                last_market_check_at=now,
                **self._execution_open_values(quote),
            )
            if created is not None:
                cash -= wallet.trade_size
                opened += 1
                decisions[Decision.ENTERED.value] = (
                    decisions.get(Decision.ENTERED.value, 0) + 1
                )
        return opened, len(admissions), decisions

    async def _price_entry(
        self,
        mint: str,
        *,
        observation: Observation,
        size: Decimal,
        decimals: int,
        now: datetime,
    ) -> tuple[Decimal, Decimal, ExecutionQuote | execution.LegacyExecution] | None:
        """What one trade size actually buys, or `None` if it buys nothing.

        Cash always moves by exactly the trade size. Costs are taken out of the
        **tokens received**, never recorded beside a full-size fill — otherwise
        the wallet would charge a fee to the record and not to the balance,
        which is the one accounting lie this experiment cannot afford.
        """
        assert observation.price_usd is not None
        quote = await self._buy_quote(mint, size=size, decimals=decimals, now=now)
        if isinstance(quote, ExecutionQuote):
            if quote.output_amount <= 0:  # pragma: no cover - guarded in the client
                return None
            return quote.estimated_price_usd, quote.output_amount, quote

        # The deterministic model the paper wallet falls back to, charged
        # against the depth observed at this moment.
        from app.paper import costs

        side = costs.side_cost(size, observation.liquidity_usd)
        spendable = size if side is None else size - side.total
        if spendable <= 0:
            # A $10 order whose own fee and impact exceed $10. There is no
            # honest fill here, so there is no entry.
            return None
        quantity = spendable / observation.price_usd
        return size / quantity, quantity, quote

    async def _buy_quote(
        self, mint: str, *, size: Decimal, decimals: int, now: datetime
    ) -> ExecutionQuote | execution.LegacyExecution:
        if settings.PAPER_EXECUTION_MODEL != "jupiter":
            return execution.LegacyExecution("PAPER_EXECUTION_MODEL=legacy")
        try:
            return await self._execution.buy_quote(
                output_mint=mint, input_usd=size, output_decimals=decimals, now=now
            )
        except ExecutionQuoteUnavailableError as exc:
            logger.info("karthik_entry_quote_unavailable", mint_address=mint, reason=str(exc))
            return execution.LegacyExecution(str(exc))

    async def _decimals_for(self, mint: str, *, token: DiscoveredToken | None) -> int | None:
        """Decimals from the token row, else from the mint account itself.

        Read-only against the chain and best-effort. The write-back is to
        `discovered_tokens.decimals`, a property of the token rather than of any
        trade — no wallet, position or Track Record row is touched by it. This
        mirrors what the paper wallet already does at exit; the paper wallet's
        own copy is not called, so a change there cannot change Karthik.
        """
        if token is not None and token.decimals is not None:
            return token.decimals
        try:
            rpc = get_rpc()
            await rpc.start()
            try:
                result = await rpc.call(
                    "getAccountInfo", [mint, {"encoding": "base64", "commitment": "confirmed"}]
                )
            finally:
                await rpc.close()
            value = (result or {}).get("value") if isinstance(result, dict) else None
            if not isinstance(value, dict):
                return None
            decimals = decode_mint_account(value).decimals
        except Exception:
            logger.info("karthik_decimals_unavailable", mint_address=mint)
            return None

        if decimals is not None:
            try:
                await self._session.execute(
                    update(DiscoveredToken)
                    .where(
                        DiscoveredToken.mint_address == mint,
                        DiscoveredToken.decimals.is_(None),
                    )
                    .values(decimals=decimals)
                )
            except Exception:  # pragma: no cover - cache write is best-effort
                logger.info("karthik_decimals_cache_failed", mint_address=mint)
        return decimals

    # --- Execution payloads --------------------------------------------------

    def _execution_open_values(
        self, found: ExecutionQuote | execution.LegacyExecution
    ) -> dict[str, object]:
        if isinstance(found, ExecutionQuote):
            return {
                "entry_execution_model_version": found.model_version,
                "entry_execution_quote": found.as_json(),
                "entry_execution_price_impact_pct": found.price_impact_pct,
                "entry_execution_fee_usd": found.platform_fee_usd,
                "entry_execution_route": found.route,
                "entry_execution_confidence": found.confidence,
                "entry_execution_fallback_reason": None,
            }
        return {
            "entry_execution_model_version": found.model_version,
            "entry_execution_quote": None,
            "entry_execution_price_impact_pct": None,
            "entry_execution_fee_usd": None,
            "entry_execution_route": None,
            "entry_execution_confidence": found.confidence,
            "entry_execution_fallback_reason": found.reason,
        }

    def _execution_close_values(self, quote: ExecutionQuote) -> dict[str, object]:
        return {
            "exit_execution_model_version": quote.model_version,
            "exit_execution_quote": quote.as_json(),
            "exit_execution_price_impact_pct": quote.price_impact_pct,
            "exit_execution_fee_usd": quote.platform_fee_usd,
            "exit_execution_route": quote.route,
            "exit_execution_confidence": quote.confidence,
        }

    # --- Accounting ----------------------------------------------------------

    async def _cash(self, wallet: KarthikWallet) -> Decimal:
        committed, returned = await self._repository.committed_and_returned(wallet.id)
        return wallet.starting_capital - committed + returned

    async def read(self, *, now: datetime) -> WalletRead:
        """Everything the page shows, derived from the rows and the market."""
        wallet = await self._repository.wallet()
        if wallet is None:
            return WalletRead(wallet=None, now=now)

        open_positions = await self._repository.open_positions(wallet.id)
        closed_positions = await self._repository.closed_positions(wallet.id)
        marks = await self._market.latest_for_mints(
            [position.mint_address for position in open_positions]
        )
        cash = await self._cash(wallet)
        return WalletRead(
            wallet=wallet,
            now=now,
            cash=cash,
            open_positions=open_positions,
            closed_positions=closed_positions,
            marks=marks,
            skipped=await self._repository.skipped(wallet.id),
            decisions=await self._repository.decision_counts(wallet.id),
            admissions=await self._repository.opportunities_since_activation(wallet),
        )


@dataclass(frozen=True, slots=True)
class WalletRead:
    """One consistent reading of the wallet. Derived, never stored."""

    wallet: KarthikWallet | None
    now: datetime
    cash: Decimal = Decimal(0)
    open_positions: Sequence[KarthikPosition] = ()
    closed_positions: Sequence[KarthikPosition] = ()
    marks: dict[str, TokenMarketSnapshot] = field(default_factory=dict)
    skipped: Sequence[KarthikOpportunity] = ()
    decisions: dict[str, int] = field(default_factory=dict)
    admissions: int = 0

    def mark_for(self, position: KarthikPosition) -> Decimal | None:
        """The current executable-ish mark, or `None` when nothing is priced.

        `None` renders as "no market data", never as zero. A token nobody has
        priced is not a token worth $0 — the only thing that books a zero here
        is a provider reporting the pool inactive, and that closes the position.
        """
        row = self.marks.get(position.mint_address)
        if row is None or row.price_usd is None or row.price_usd <= 0:
            return None
        return row.price_usd

    @property
    def allocated(self) -> Decimal:
        return sum((position.cost_basis for position in self.open_positions), start=Decimal(0))

    @property
    def open_value(self) -> Decimal:
        """Market value of the open book, counting an unpriced position at cost.

        Counting it at zero would report a loss nobody observed; counting it at
        cost says "we have not re-measured this", which is the truth. The page
        shows the unpriced count beside the figure so the reader can weigh it.
        """
        total = Decimal(0)
        for position in self.open_positions:
            mark = self.mark_for(position)
            total += position.cost_basis if mark is None else position.quantity * mark
        return total

    @property
    def realized_pnl(self) -> Decimal:
        total = Decimal(0)
        for position in self.closed_positions:
            proceeds = position.exit_proceeds_usd or Decimal(0)
            total += proceeds - position.cost_basis
        return total

    @property
    def unrealized_pnl(self) -> Decimal:
        return self.open_value - self.allocated

    @property
    def equity(self) -> Decimal:
        return self.cash + self.open_value


def utcnow() -> datetime:
    return datetime.now(UTC)
