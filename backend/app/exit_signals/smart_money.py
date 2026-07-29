"""Smart money — declared, weighted, and not currently computable.

Wallet quality, accumulation, distribution and cluster detection are genuine
signals and the platform declares them. It cannot compute any of them, and this
module exists so that absence is **visible in coverage** rather than silently
missing — the same mechanism `radar/community.py` uses.

## Why this is not a matter of effort

The platform stores market aggregates: price, market cap, liquidity, volume and
buy/sell *counts*. It stores no wallet addresses, no transactions and no holder
lists. Nothing here can be derived from what exists.

Worse, the headline signals cannot be derived even from a complete wallet feed
starting today. "Historical profitability", "win rate" and "average ROI" are
claims about trades a wallet made **before MEMESCOPE existed**, priced at the
moment each trade happened, across tokens the platform never observed. Computing
them requires historical price series for arbitrary tokens at arbitrary past
timestamps — a dataset the platform does not have and cannot reconstruct from
its own records.

A wallet score built without that would be a number with the shape of evidence
and none of the substance, on the screen where users are most likely to trust
it. That is the exact failure `lib/intelligence.ts` was deleted for in Phase
4.1, and it is why this module returns nothing rather than something plausible.

## What implementing it actually requires

1. **Transaction ingestion.** A Helius worker persisting swap-level events per
   mint: wallet, direction, amount, slot. New tables, and a volume far larger
   than `token_market_snapshots`.
2. **Historical pricing.** Price-at-slot for every token a profiled wallet has
   traded, to value entries and exits. This is the hard part and needs a
   provider the platform does not currently integrate.
3. **Wallet profiling.** Realised and unrealised P&L, hold duration, entry
   timing relative to each token's discovery, bot heuristics.
4. **Only then** the scoring in this package's docstrings becomes meaningful.

Steps 1 and 2 are a data-engineering project, not a scoring module. Until they
exist, `available` is `False` everywhere and the API says so.
"""

from __future__ import annotations

from decimal import Decimal

from app.exit_signals.models import ExitSignal, SignalResult

#: Signals that would exist with wallet data, and currently cannot.
DECLARED_SIGNALS: tuple[ExitSignal, ...] = (
    ExitSignal.SMART_MONEY_DISTRIBUTING,
    ExitSignal.HOLDER_GROWTH_STALLING,
)

#: What the API reports for a token's smart-money block. Every field is `None`
#: rather than zero: "no smart wallets detected" and "we cannot see wallets" are
#: different claims, and zero would read as the first.
UNAVAILABLE_REASON = (
    "Wallet-level data is not collected. Smart money requires transaction "
    "ingestion and historical pricing that the platform does not yet have — see "
    "app/exit_signals/smart_money.py for what implementing it involves."
)


def evaluate() -> tuple[SignalResult, ...]:
    """Always unavailable. See the module docstring."""
    return tuple(SignalResult.unavailable(signal) for signal in DECLARED_SIGNALS)


def token_intelligence() -> dict[str, str | None]:
    """The per-token smart-money block, as the API serves it.

    Deliberately all-`None` with a reason attached, so the frontend renders
    "not collected" rather than a confident zero.
    """
    return {
        "smart_wallet_count": None,
        "average_wallet_quality": None,
        "net_accumulation": None,
        "accumulation_trend": None,
        "distribution_trend": None,
        "largest_recent_buyer": None,
        "largest_recent_seller": None,
        "unavailable_reason": UNAVAILABLE_REASON,
    }


#: Weight the smart-money block *would* carry once it exists, published so the
#: coverage figure is explainable rather than arbitrary.
DECLARED_WEIGHT = Decimal("0.20")
