"""Paper Wallet V2: its own wallet, its own capital, its own review loop.

── ISOLATION, AND WHERE IT IS ENFORCED ──────────────────────────────────────

V2 shares the *market* with V1 — the same Radar, the same snapshots, the same
SEC-2 gate — and shares no *money* with it at all. That split is enforced in
three places rather than promised in one:

  * **Schema.** V2 reads and writes `paper_v2_*` only. It never opens a session
    against `paper_positions`, so a V1 row cannot reach a V2 figure by mistake.
  * **Lineage.** V2 is absent from `paper.strategy.CAPITAL_LINEAGES` and must
    stay absent. Its starting balance is new simulated capital.
  * **Controls.** `PAPER_V2_MODE` and `PAPER_V2_ENTRIES_PAUSED` are V2's alone.
    Pausing V1 does not pause V2; disabling V2 does not touch V1.

── THE ENTRY UNIVERSE IS DELIBERATELY UNCHANGED ─────────────────────────────

V2 screens candidates with `paper.eligibility.screen` — the *same* function V1
uses, including the SEC-2 precondition. No age filter, no sell/buy filter, no
liquidity ratio. This experiment is about money management, and an entry rule
smuggled in beside it would make the comparison meaningless. The upstream
verdict is copied onto every position as `decision_provenance` so a later
comparison can prove the two wallets saw the same opportunities.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.paper_v2 import PaperV2Fill, PaperV2Position, PaperV2Wallet
from app.paper import costs
from app.paper_v2 import ladder, metrics

#: What V2 runs. Not read from configuration — see `ladder.PRIMARY`.
STRATEGY_ID = "paper_v2_ladder_25"
STRATEGY_VERSION = "1.0.0-experimental"
STRATEGY_NAME = "Paper Wallet V2"
STRATEGY_SUMMARY = (
    "$25 Fixed · No Stop Loss · 25% @ 1.25x · 25% @ 1.50x · 25% @ 1.75x · "
    "25% Runner · 6H Max Hold"
)
EXECUTION_MODEL_VERSION = "v2_ladder_constant_product_v1"

#: The refusal recorded when V2 cannot fund an entry. Never borrows.
INSUFFICIENT_CASH = "insufficient_v2_cash"
ENTRIES_PAUSED = "v2_entries_paused"
NOT_ACTIVE = "v2_not_paper_active"

_ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class ReviewOutcome:
    evaluated: int
    filled: int
    closed: int
    opened: int
    refusals: dict[str, int]

    def as_dict(self) -> dict[str, object]:
        return {
            "evaluated": self.evaluated,
            "filled": self.filled,
            "closed": self.closed,
            "opened": self.opened,
            **{f"refused_{k}": v for k, v in self.refusals.items()},
        }


class PaperV2Service:
    """V2's engine. Constructed per request; holds no state between calls."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- lifecycle -------------------------------------------------------

    @property
    def mode(self) -> str:
        return settings.PAPER_V2_MODE

    @property
    def enabled(self) -> bool:
        return self.mode != "disabled"

    async def live_wallet(self) -> PaperV2Wallet | None:
        return await self._session.scalar(
            select(PaperV2Wallet).where(PaperV2Wallet.archived_at.is_(None))
        )

    async def ensure_wallet(self, *, now: datetime) -> PaperV2Wallet | None:
        """The V2 wallet, created once on first non-disabled review.

        Returns `None` while disabled: an experiment that has not been switched
        on should hold no capital and show no balance, so a deployed-but-off V2
        is visibly *not started* rather than sitting at a fake $1,000.

        Concurrency-safe the same way V1's is — insert-then-read against the
        live index, so two workers starting together resolve to one wallet.
        """
        if not self.enabled:
            return None
        existing = await self.live_wallet()
        if existing is not None:
            return existing
        await self._session.execute(
            insert(PaperV2Wallet)
            .values(
                name=STRATEGY_NAME,
                strategy_id=STRATEGY_ID,
                strategy_version=STRATEGY_VERSION,
                # New simulated capital. Never read from a V1 row.
                starting_balance=Decimal(str(settings.PAPER_V2_STARTING_BALANCE)),
                trade_size_usd=Decimal(str(settings.PAPER_V2_TRADE_SIZE_USD)),
                started_at=now,
            )
            .on_conflict_do_nothing()
        )
        await self._session.flush()
        return await self.live_wallet()

    # --- reading ---------------------------------------------------------

    async def open_positions(self, wallet_id: uuid.UUID) -> Sequence[PaperV2Position]:
        return (
            await self._session.scalars(
                select(PaperV2Position)
                .where(
                    PaperV2Position.wallet_id == wallet_id,
                    PaperV2Position.status == "open",
                )
                .order_by(PaperV2Position.last_evaluated_at.asc())
            )
        ).all()

    async def closed_positions(self, wallet_id: uuid.UUID) -> Sequence[PaperV2Position]:
        return (
            await self._session.scalars(
                select(PaperV2Position)
                .where(
                    PaperV2Position.wallet_id == wallet_id,
                    PaperV2Position.status == "closed",
                )
                .order_by(PaperV2Position.closed_at.desc())
            )
        ).all()

    async def fills_for(
        self, position_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, list[PaperV2Fill]]:
        if not position_ids:
            return {}
        rows = (
            await self._session.scalars(
                select(PaperV2Fill)
                .where(PaperV2Fill.position_id.in_(list(position_ids)))
                .order_by(PaperV2Fill.filled_at.asc())
            )
        ).all()
        out: dict[uuid.UUID, list[PaperV2Fill]] = {}
        for row in rows:
            out.setdefault(row.position_id, []).append(row)
        return out

    async def summarise(
        self, wallet: PaperV2Wallet, *, prices: dict[str, Decimal | None]
    ) -> metrics.V2Metrics:
        """Every figure V2 reports, derived from V2 rows only."""
        open_rows = await self.open_positions(wallet.id)
        closed_rows = await self.closed_positions(wallet.id)
        by_position = await self.fills_for(
            [row.id for row in (*open_rows, *closed_rows)]
        )

        open_legs = [
            metrics.OpenLeg(
                mint_address=row.mint_address,
                initial_notional=row.initial_notional,
                initial_quantity=row.initial_quantity,
                remaining_quantity=row.remaining_quantity,
            )
            for row in open_rows
        ]
        closed_legs = [
            metrics.ClosedLeg(
                mint_address=row.mint_address,
                initial_notional=row.initial_notional,
                net_proceeds=sum(
                    (f.net_proceeds for f in by_position.get(row.id, [])), _ZERO
                ),
                closed_at=row.closed_at,
            )
            for row in closed_rows
        ]
        # Cash already returned by partial fills on positions still running.
        partial = sum(
            (
                f.net_proceeds
                for row in open_rows
                for f in by_position.get(row.id, [])
            ),
            _ZERO,
        )
        # In close order: a drawdown is a path, not a set.
        curve: list[Decimal] = []
        running = wallet.starting_balance
        for leg in sorted(
            closed_legs,
            key=lambda leg: (leg.closed_at is None, leg.closed_at, leg.mint_address),
        ):
            running += leg.pnl
            curve.append(running)

        return metrics.summarise(
            starting_balance=wallet.starting_balance,
            open_legs=open_legs,
            closed_legs=closed_legs,
            partial_proceeds=partial,
            prices=prices,
            realised_curve=curve,
        )

    async def cash(self, wallet: PaperV2Wallet) -> Decimal:
        """Spendable cash. Derived, never stored — the V1 rule, kept."""
        summary = await self.summarise(wallet, prices={})
        return summary.cash

    # --- settlement ------------------------------------------------------

    async def settle(
        self,
        position: PaperV2Position,
        *,
        quotes: Sequence[ladder.Quote],
        rules: ladder.LadderRules,
        now: datetime,
    ) -> tuple[int, bool]:
        """Apply the ladder to one position. Returns (fills written, closed).

        `filled_rungs` is read from the row and written back, so a restart
        cannot re-fire a rung that already sold. The database enforces the same
        thing independently via `uq_paper_v2_fills_rung`.
        """
        already = frozenset(int(i) for i in (position.filled_rungs or []))
        outcome = ladder.resolve(
            rules,
            entry_price=position.entry_price,
            opened_at=position.opened_at,
            initial_quantity=position.initial_quantity,
            remaining_quantity=position.remaining_quantity,
            quotes=quotes,
            already_filled=already,
        )

        for fill in outcome.fills:
            gross = fill.quantity * fill.price_usd
            cost = costs.side_cost(gross, fill.liquidity_usd)
            fee = cost.fee if cost else None
            impact = cost.impact if cost else None
            charge = cost.total if cost else _ZERO
            self._session.add(
                PaperV2Fill(
                    position_id=position.id,
                    rung_index=fill.rung_index,
                    reason=str(fill.reason),
                    filled_at=fill.at,
                    quantity=fill.quantity,
                    execution_price=fill.price_usd,
                    observed_price=fill.observed_price,
                    gross_proceeds=gross,
                    fee_usd=fee,
                    impact_usd=impact,
                    net_proceeds=gross - charge,
                    liquidity_usd=fill.liquidity_usd,
                    execution_model_version=EXECUTION_MODEL_VERSION,
                )
            )

        position.remaining_quantity = outcome.remaining_quantity
        position.filled_rungs = sorted(outcome.filled_rungs)
        position.last_evaluated_at = now
        if outcome.closed:
            position.status = "closed"
            position.closed_at = outcome.fills[-1].at if outcome.fills else now
            position.final_exit_reason = (
                str(outcome.fills[-1].reason) if outcome.fills else None
            )
        return len(outcome.fills), outcome.closed

    # --- entries ---------------------------------------------------------

    def entry_refusal(self) -> str | None:
        """Why V2 will not open, or `None` when it may.

        Read before any candidate is examined. V2's controls are its own: this
        function never consults `PAPER_WALLET_ENTRIES_PAUSED`.
        """
        if self.mode != "paper_active":
            return NOT_ACTIVE
        if settings.PAPER_V2_ENTRIES_PAUSED:
            return ENTRIES_PAUSED
        return None

    async def open_entry(
        self,
        wallet: PaperV2Wallet,
        *,
        mint_address: str,
        entry_price: Decimal,
        liquidity_usd: Decimal | None,
        market_cap: Decimal | None,
        provenance: dict,
        now: datetime,
        token_id: uuid.UUID | None = None,
        entry_rank: int | None = None,
    ) -> PaperV2Position | None:
        """Open one $25 position, or `None` when the wallet cannot fund it.

        Fixed notional, always. No liquidity-aware sizing, no compounding, no
        scaling with equity — the size is the experiment's control variable.
        """
        size = wallet.trade_size_usd
        if await self.cash(wallet) < size:
            return None
        if entry_price <= 0:
            return None

        cost = costs.side_cost(size, liquidity_usd)
        charge = cost.total if cost else _ZERO
        quantity = (size - charge) / entry_price
        if quantity <= 0:
            return None

        position = PaperV2Position(
            wallet_id=wallet.id,
            mint_address=mint_address,
            token_id=token_id,
            opened_at=now,
            expires_at=now + ladder.PRIMARY.hold_for,
            entry_price=entry_price,
            initial_notional=size,
            initial_quantity=quantity,
            remaining_quantity=quantity,
            filled_rungs=[],
            status="open",
            entry_liquidity_usd=liquidity_usd,
            entry_market_cap=market_cap,
            entry_cost_usd=charge,
            entry_rank=entry_rank,
            decision_provenance=provenance,
            last_evaluated_at=now,
        )
        self._session.add(position)
        await self._session.flush()
        return position
