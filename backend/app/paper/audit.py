"""The permanent record of one completed trade.

Sprint 30 §11. Every closed position produces exactly one audit record, computed
here from facts that were observed and never from a figure recomputed later.

**Why this exists when the metrics already derive everything.** The wallet's
summary is derived from `paper_positions` and stays derived — cash, equity, ROI
and drawdown are all recomputed on every read, because a stored balance drifts
from the trades it claims to summarise. The audit record answers a different
question: *what did the market look like at each end of this trade, and what
would the venue have taken?* Those inputs live in `token_market_snapshots`,
which is pruned. A figure that is only derivable is only derivable while its
rows survive — and the oldest trades, the ones a track record is actually judged
on, would be the first to go dark.

So this module computes, once, from the rows that were there.

**Gross and net sit side by side, and neither is dropped.** Gross is what the
price did. Net is what would have been left after the published swap fee and the
constant-product price impact of the order against the depth observed at that
moment. When either end reports no depth, net is `None` **with its reason** —
never zero, and never a guess. Slippage from competing flow, priority fees and
MEV stay unmodelled here exactly as `costs.py` refuses them: this platform
stores snapshots, not fills.

Pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.paper import costs
from app.paper.models import ClosedTrade

_ZERO = Decimal(0)
_HUNDRED = Decimal(100)
_MONEY = Decimal("0.0001")
_PCT = Decimal("0.0001")

#: Written into `cost_unavailable_reason` when the venue reported no depth at
#: one end. Stored rather than rendered at read time so the record explains
#: itself even if this module is one day reworded.
NO_DEPTH_REASON = (
    "Net return not computed: the venue reported no pool depth at one end of "
    "this trade, and a cost charged against an invented depth would be a guess. "
    "Gross return is measured; the fee and impact are not."
)


@dataclass(frozen=True, slots=True)
class TradeAudit:
    """One completed trade, as it is written down and never rewritten.

    Every field is either an observation or arithmetic over observations. There
    is no judgement in here and no recommendation — the record says what the
    rule did and what it would have cost, and nothing about what to do next.
    """

    mint_address: str
    symbol: str | None

    entry_at: datetime
    entry_price: Decimal
    entry_market_cap: Decimal | None
    entry_liquidity_usd: Decimal | None
    size_usd: Decimal
    quantity: Decimal

    exit_at: datetime
    exit_price: Decimal
    exit_market_cap: Decimal | None
    exit_liquidity_usd: Decimal | None

    gross_return_usd: Decimal
    gross_return_pct: Decimal
    fee_usd: Decimal | None
    slippage_usd: Decimal | None
    net_return_usd: Decimal | None
    net_return_pct: Decimal | None
    cost_unavailable_reason: str | None

    exit_reason: str
    strategy_id: str
    strategy_version: str
    wallet_generation: int
    swap_fee_bps: Decimal | None

    def as_row(self) -> dict[str, object]:
        """The record as column values, ready for a single INSERT."""
        return {
            "mint_address": self.mint_address,
            "symbol": self.symbol,
            "entry_at": self.entry_at,
            "entry_price": self.entry_price,
            "entry_market_cap": self.entry_market_cap,
            "entry_liquidity_usd": self.entry_liquidity_usd,
            "size_usd": self.size_usd,
            "quantity": self.quantity,
            "exit_at": self.exit_at,
            "exit_price": self.exit_price,
            "exit_market_cap": self.exit_market_cap,
            "exit_liquidity_usd": self.exit_liquidity_usd,
            "gross_return_usd": self.gross_return_usd,
            "gross_return_pct": self.gross_return_pct,
            "fee_usd": self.fee_usd,
            "slippage_usd": self.slippage_usd,
            "net_return_usd": self.net_return_usd,
            "net_return_pct": self.net_return_pct,
            "cost_unavailable_reason": self.cost_unavailable_reason,
            "exit_reason": self.exit_reason,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "wallet_generation": self.wallet_generation,
            "swap_fee_bps": self.swap_fee_bps,
        }


def record(
    trade: ClosedTrade,
    *,
    symbol: str | None,
    entry_market_cap: Decimal | None,
    entry_liquidity_usd: Decimal | None,
    exit_market_cap: Decimal | None,
    exit_liquidity_usd: Decimal | None,
    strategy_id: str,
    strategy_version: str,
    wallet_generation: int,
    model: costs.CostModel = costs.DEFAULT,
) -> TradeAudit:
    """Compute the permanent record for one closed position.

    The exit is costed on what the position is **worth at exit**, not on what it
    cost to open. Selling a position that tripled is a three-times larger order,
    and charging it as though it were the entry size would understate the cost of
    precisely the winners — the finding Sprint 27 recorded as cost being
    progressive rather than flat.
    """
    proceeds = trade.proceeds
    gross_usd = proceeds - trade.size_usd
    gross_pct = _ZERO if trade.size_usd <= 0 else (gross_usd / trade.size_usd * _HUNDRED)

    round_trip = costs.round_trip(
        entry_notional=trade.size_usd,
        entry_liquidity=entry_liquidity_usd,
        exit_notional=proceeds,
        exit_liquidity=exit_liquidity_usd,
        model=model,
    )

    fee: Decimal | None = None
    slippage: Decimal | None = None
    net_usd: Decimal | None = None
    net_pct: Decimal | None = None
    unavailable: str | None = NO_DEPTH_REASON

    if round_trip is not None:
        unavailable = None
        fee = round_trip.entry.fee + round_trip.exit.fee
        # "Slippage" here is price impact — the move the order itself causes
        # against the pool. Slippage from *competing* flow is a different thing
        # and stays refused; `costs.DISCLOSURE` says so wherever net is shown.
        slippage = round_trip.entry.impact + round_trip.exit.impact
        net_usd = costs.net_proceeds(
            entry_notional=trade.size_usd, exit_notional=proceeds, costs=round_trip
        )
        net_pct = _ZERO if trade.size_usd <= 0 else (net_usd / trade.size_usd * _HUNDRED)

    return TradeAudit(
        mint_address=trade.mint_address,
        symbol=symbol,
        entry_at=trade.opened_at,
        entry_price=trade.entry_price,
        entry_market_cap=entry_market_cap,
        entry_liquidity_usd=entry_liquidity_usd,
        size_usd=trade.size_usd,
        quantity=trade.quantity,
        exit_at=trade.closed_at,
        exit_price=trade.exit_price,
        exit_market_cap=exit_market_cap,
        exit_liquidity_usd=exit_liquidity_usd,
        gross_return_usd=gross_usd.quantize(_MONEY),
        gross_return_pct=gross_pct.quantize(_PCT),
        fee_usd=None if fee is None else fee.quantize(_MONEY),
        slippage_usd=None if slippage is None else slippage.quantize(_MONEY),
        net_return_usd=None if net_usd is None else net_usd.quantize(_MONEY),
        net_return_pct=None if net_pct is None else net_pct.quantize(_PCT),
        cost_unavailable_reason=unavailable,
        exit_reason=trade.reason.value,
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        wallet_generation=wallet_generation,
        swap_fee_bps=model.swap_fee_bps,
    )


#: Printed at the head of the audit log. The three refusals are as much part of
#: the record as the two inclusions, and a reader deciding whether to trust a
#: net figure needs both halves.
DISCLOSURE = (
    "Every completed trade is recorded once, at the moment it closed, from the "
    "market data observed at each end. Nothing in this log is ever rewritten. "
    "Net figures charge the published swap fee on both sides plus the "
    "constant-product price impact of the order against the depth observed at "
    "that moment; they exclude slippage from competing transactions, priority "
    "fees and MEV, which this platform cannot measure from snapshots."
)
