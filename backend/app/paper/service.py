"""Running the simulation, and reading it back.

Two responsibilities, deliberately in one place because they share a shape:

* `review` advances the wallet — **exits first, then entries**, so cash freed by
  a close is available to the same pass. The order is part of the published
  rule, not an implementation detail: the other order would decline entries the
  strategy could actually have funded.
* `read` assembles everything the API serves, from positions and market history.

Neither invents anything. Prices come from `token_market_snapshots`, candidates
come from the Radar's own ranking, and the benchmark comes from
`RadarRepository.benchmark` — the equal-weight figure that already existed.
Nothing here is a recommendation, and nothing here touches a chain.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.paper import PaperPosition, PaperWallet
from app.paper import engine, metrics
from app.paper.models import (
    Candidate,
    ClosedTrade,
    ExitReason,
    OpenPosition,
    PositionStatus,
    Quote,
)
from app.paper.repository import PaperRepository
from app.paper.strategy import FixedSizeStrategy, registry
from app.radar.repository import RadarRepository
from app.repositories.market import MarketSnapshotRepository
from app.repositories.token import TokenRepository

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ReviewOutcome:
    """What one pass did. Reported so a stalled evaluator is visible."""

    evaluated: int
    closed: int
    opened: int
    skipped_held: int
    skipped_unfunded: int

    def as_dict(self) -> dict[str, int]:
        return {
            "evaluated": self.evaluated,
            "closed": self.closed,
            "opened": self.opened,
            "skipped_held": self.skipped_held,
            "skipped_unfunded": self.skipped_unfunded,
        }


def _to_open(position: PaperPosition) -> OpenPosition:
    return OpenPosition(
        mint_address=position.mint_address,
        opened_at=position.opened_at,
        entry_price=position.entry_price,
        quantity=position.quantity,
        size_usd=position.size_usd,
        target_price=position.target_price,
        stop_price=position.stop_price,
        expires_at=position.expires_at,
        peak_price=position.peak_price,
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


class PaperWalletService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = PaperRepository(session)
        self._market = MarketSnapshotRepository(session)
        self._radar = RadarRepository(session)

    @property
    def strategy(self) -> FixedSizeStrategy:
        """The strategy that trades, falling back to the registry default.

        A configured id that is not registered falls back rather than crashing,
        and says so: a typo in an environment variable must not stop the wallet,
        and it must not silently trade rules nobody chose either.
        """
        configured = registry.get(settings.PAPER_WALLET_STRATEGY_ID)
        if configured is None:
            logger.warning(
                "paper_strategy_unknown",
                configured=settings.PAPER_WALLET_STRATEGY_ID,
                using=registry.default.id,
            )
            return registry.default
        return configured

    async def wallet(self) -> PaperWallet:
        strategy = self.strategy
        return await self._repository.ensure_wallet(
            strategy_id=strategy.id,
            strategy_version=strategy.version,
            starting_balance=Decimal(str(settings.PAPER_WALLET_STARTING_BALANCE)),
        )

    # --- Advancing the simulation -------------------------------------------

    async def review(self, *, now: datetime) -> ReviewOutcome:
        """One pass: settle exits, then open what the strategy can fund."""
        wallet = await self.wallet()
        evaluated, closed = await self._settle_exits(wallet, now=now)
        opened, held, unfunded = await self._open_entries(wallet, now=now)
        return ReviewOutcome(
            evaluated=evaluated,
            closed=closed,
            opened=opened,
            skipped_held=held,
            skipped_unfunded=unfunded,
        )

    async def _settle_exits(self, wallet: PaperWallet, *, now: datetime) -> tuple[int, int]:
        """Walk each open position's unseen observations and close the breaches.

        The whole reproducibility guarantee lives in these few lines. Each
        position is replayed over **every** reading since its own watermark, in
        order, and closes at the first breach — so a worker that missed six
        hours produces the same trades as one that missed none.
        """
        positions = await self._repository.open_positions(
            wallet.id, limit=settings.PAPER_WALLET_REVIEW_BATCH_LIMIT
        )
        if not positions:
            return 0, 0

        # One query for the batch, from the oldest watermark in it; each row is
        # then trimmed to its own. `window_for_mints` documents the same shape.
        oldest = min(position.last_evaluated_at for position in positions)
        series = await self._market.series_for_mints(
            [position.mint_address for position in positions], since=oldest
        )

        closed = 0
        for position in positions:
            quotes = [
                Quote(captured_at=row.captured_at, price_usd=row.price_usd)
                for row in series.get(position.mint_address, [])
                if row.price_usd is not None and row.captured_at > position.last_evaluated_at
            ]
            domain = _to_open(position)
            found = engine.resolve_exit(domain, quotes)

            if found is None:
                # Nothing breached. Carry the peak and the watermark forward so
                # the same readings are never replayed — and so the peak
                # survives snapshot pruning.
                await self._repository.advance(
                    position.id,
                    peak_price=engine.peak_through(domain, quotes),
                    last_evaluated_at=quotes[-1].captured_at if quotes else now,
                )
                continue

            await self._repository.close(
                position.id,
                exit_price=found.price_usd,
                closed_at=found.at,
                exit_reason=found.reason.value,
                # Only the peak up to the exit belongs to the trade. A high
                # printed after the position closed belongs to the token.
                peak_price=engine.peak_before(domain, quotes, found.at),
            )
            closed += 1

        return len(positions), closed

    async def _open_entries(
        self, wallet: PaperWallet, *, now: datetime
    ) -> tuple[int, int, int]:
        """Offer every Top-N Radar token to the strategy, in rank order.

        Rank order matters when cash is short: the wallet fills from the top of
        the Radar down, which is the only ordering consistent with a ranking
        the platform publishes. Filling by whichever row the database returned
        first would make the result depend on a query plan.
        """
        strategy = self.strategy
        entries = await self._radar.list_entries(
            category=None, active_only=True, sort="score", limit=strategy.top_n, offset=0
        )
        if not entries:
            return 0, 0, 0

        mints = [entry.mint_address for entry in entries]
        held = await self._repository.held_mints(wallet.id)
        prices = await self._market.latest_for_mints(mints)
        tokens = await TokenRepository(self._session).get_many_by_mints(mints)
        token_ids = {mint: token.id for mint, token in tokens.items()}

        # Cash is derived from the rows as they stand, then decremented locally
        # as this pass commits capital — so two entries in one pass cannot both
        # spend the same dollar.
        cash = await self._cash_for(wallet)

        opened = skipped_held = skipped_unfunded = 0
        for rank, entry in enumerate(entries, start=1):
            mint = entry.mint_address
            if mint in held:
                skipped_held += 1
                continue

            snapshot = prices.get(mint)
            price = snapshot.price_usd if snapshot is not None else None
            if price is None or price <= 0:
                # Unpriced, not free. A position cannot be sized against a price
                # nobody observed, and inventing one would be the estimate this
                # platform refuses to make.
                continue

            candidate = Candidate(
                mint_address=mint,
                rank=rank,
                price_usd=price,
                observed_at=snapshot.captured_at if snapshot is not None else now,
            )
            instruction = strategy.entry_for(candidate, cash_available=cash, now=now)
            if instruction is None:
                skipped_unfunded += 1
                continue

            created = await self._repository.open_position(
                wallet_id=wallet.id,
                mint_address=mint,
                token_id=token_ids.get(mint),
                opened_at=instruction.opened_at,
                entry_rank=rank,
                entry_price=instruction.price_usd,
                size_usd=instruction.size_usd,
                quantity=instruction.quantity,
                target_price=instruction.target_price,
                stop_price=instruction.stop_price,
                expires_at=instruction.expires_at,
                status=PositionStatus.OPEN.value,
                peak_price=instruction.price_usd,
                last_evaluated_at=instruction.opened_at,
            )
            if created is None:
                # Lost the race to another evaluator. Ordinary, not an error.
                skipped_held += 1
                continue

            cash -= instruction.size_usd
            opened += 1

        return opened, skipped_held, skipped_unfunded

    async def _cash_for(self, wallet: PaperWallet) -> Decimal:
        open_rows = await self._repository.open_positions(wallet.id)
        closed_rows = await self._repository.closed_positions(wallet.id)
        closed = [trade for trade in (_to_closed(row) for row in closed_rows) if trade]
        return metrics.cash_for(
            wallet.starting_balance, [_to_open(row) for row in open_rows], closed
        )

    # --- Reading it back -----------------------------------------------------

    async def read(self, *, now: datetime) -> WalletRead:
        """Everything the API serves, in five queries."""
        wallet = await self.wallet()
        positions = await self._repository.all_positions(wallet.id)

        open_rows = [row for row in positions if row.status == PositionStatus.OPEN.value]
        closed_rows = [row for row in positions if row.status == PositionStatus.CLOSED.value]
        closed = [trade for trade in (_to_closed(row) for row in closed_rows) if trade]

        snapshots = await self._market.latest_for_mints(
            [row.mint_address for row in open_rows]
        )
        prices: dict[str, Decimal | None] = {
            row.mint_address: (
                snapshots[row.mint_address].price_usd
                if row.mint_address in snapshots
                else None
            )
            for row in open_rows
        }
        names = await TokenRepository(self._session).get_many_by_mints(
            [row.mint_address for row in positions]
        )

        summary = metrics.summarise(
            starting_balance=wallet.starting_balance,
            open_positions=[_to_open(row) for row in open_rows],
            prices=prices,
            closed=closed,
        )
        benchmark = await self._radar.benchmark()

        return WalletRead(
            wallet=wallet,
            strategy=self.strategy,
            metrics=summary,
            positions=list(positions),
            prices=prices,
            names={mint: (token.name, token.symbol) for mint, token in names.items()},
            benchmark=benchmark,
            pnl_today=metrics.pnl_since(
                closed, since=now.replace(hour=0, minute=0, second=0, microsecond=0)
            ),
            observed_at=now,
        )


@dataclass(frozen=True, slots=True)
class WalletRead:
    """The assembled read model. Rendering happens in `api.py`."""

    wallet: PaperWallet
    strategy: FixedSizeStrategy
    metrics: metrics.WalletMetrics
    positions: list[PaperPosition]
    prices: dict[str, Decimal | None]
    names: dict[str, tuple[str | None, str | None]]
    benchmark: dict[str, Decimal | int | None]
    pnl_today: Decimal
    observed_at: datetime


def utcnow() -> datetime:
    """The clock, in one place, so the pure modules never reach for it."""
    return datetime.now(UTC)


__all__ = ["PaperWalletService", "ReviewOutcome", "WalletRead", "utcnow"]
