"""`earlysignal.manipulation` — the on-chain veto.

Three cheap sanity checks over quantities MEMESCOPE already records. Each one
answers a different question, and any one of them tripping is enough:

  BUYER/SELLER RATIO   A pool with many more sellers than buyers is
                       distributing, not accumulating, whatever the price says.
  BUYS/SELLS RATIO     Trade counts far out of line with the wallet counts mean
                       a few wallets are trading with themselves — the shape of
                       wash volume.
  VOLUME / MARKET CAP  Five-minute volume that is a large fraction of the whole
                       market cap is not organic turnover at these sizes.

**A check with no data does not trip and does not pass.** It is skipped and
named in `skipped`, so a candidate that looks clean because nothing could be
measured is distinguishable from one that looks clean because it was measured.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class ManipulationPolicy:
    """Provisional. Every constant is a hypothesis, not a validated fit."""

    #: Sellers may outnumber buyers by at most this much.
    max_seller_buyer_ratio: Decimal = Decimal(3)
    #: Trades per unique wallet above this is wash-shaped.
    max_trades_per_wallet: Decimal = Decimal(8)
    #: Five-minute volume above this fraction of market cap is not organic.
    max_volume_to_mcap_5m: Decimal = Decimal("0.50")
    #: Below this liquidity nothing above is measurable in a useful way.
    min_liquidity_usd: Decimal = Decimal(1_000)


@dataclass(frozen=True, slots=True)
class Signal:
    name: str
    detail: str


@dataclass(frozen=True, slots=True)
class Assessment:
    manipulated: bool
    suspicious: tuple[Signal, ...]
    #: Checks that had no data. Named so "clean" and "unmeasured" stay apart.
    skipped: tuple[str, ...]


def assess(*, buyers=None, sellers=None, buys=None, sells=None,
           volume_m5=None, market_cap=None, liquidity=None,
           policy: ManipulationPolicy = ManipulationPolicy()) -> Assessment:
    """`manipulated=True` on any breach. Missing inputs skip their own check."""
    suspicious: list[Signal] = []
    skipped: list[str] = []

    if buyers is None or sellers is None:
        skipped.append("buyer_seller_ratio")
    elif buyers <= 0 and sellers > 0:
        suspicious.append(Signal("buyer_seller_ratio",
                                 f"{sellers} sellers and no buyers"))
    elif buyers > 0:
        ratio = Decimal(sellers) / Decimal(buyers)
        if ratio > policy.max_seller_buyer_ratio:
            suspicious.append(Signal(
                "buyer_seller_ratio",
                f"sellers outnumber buyers {ratio:.1f}:1 "
                f"(limit {policy.max_seller_buyer_ratio}:1)"))

    wallets = None if (buyers is None or sellers is None) else buyers + sellers
    trades = None if (buys is None or sells is None) else buys + sells
    if wallets is None or trades is None:
        skipped.append("trades_per_wallet")
    elif wallets > 0:
        per_wallet = Decimal(trades) / Decimal(wallets)
        if per_wallet > policy.max_trades_per_wallet:
            suspicious.append(Signal(
                "trades_per_wallet",
                f"{per_wallet:.1f} trades per unique wallet "
                f"(limit {policy.max_trades_per_wallet}) — wash-shaped"))

    if volume_m5 is None or market_cap is None or market_cap <= 0:
        skipped.append("volume_to_mcap")
    else:
        share = Decimal(volume_m5) / Decimal(market_cap)
        if share > policy.max_volume_to_mcap_5m:
            suspicious.append(Signal(
                "volume_to_mcap",
                f"5-minute volume is {share:.0%} of market cap "
                f"(limit {policy.max_volume_to_mcap_5m:.0%})"))

    if liquidity is None:
        skipped.append("liquidity_floor")
    elif Decimal(liquidity) < policy.min_liquidity_usd:
        suspicious.append(Signal(
            "liquidity_floor",
            f"liquidity ${Decimal(liquidity):,.0f} below "
            f"${policy.min_liquidity_usd:,.0f} — nothing here is measurable"))

    return Assessment(bool(suspicious), tuple(suspicious), tuple(skipped))
