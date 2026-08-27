"""Which market tokens this platform is willing to trade, and why not the rest.

Solana only, end to end. The universe comes from Jupiter's verified list — the
same list the router quotes against — so every token here is an SPL mint with a
real Solana pool. Nothing from another chain can enter: the snapshot source is
Solana-native and the price provider now refuses non-Solana pairs outright.

Pure: no I/O, no clock. The caller supplies the row; this decides.

## Why anything is excluded at all

The wallet's exit is a 25% trailing stop. That rule is meaningless on an asset
that cannot move 25% — a stablecoin or a liquid-staking token would be bought,
never exit, and hold capital hostage forever. Excluding them is mechanical
(the exit cannot function), not predictive, and it is the only reason any of
these filters exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

#: A liquid-staking or wrapped token reports its whole float as pool depth, so
#: liquidity and market cap converge. Real tokens trade a fraction of supply:
#: measured on the live list, TRUMP sits at 0.07, PUMP 0.02, BOME 0.22 — while
#: JitoSOL, BNSOL, jlUSDC and LST all report exactly 1.00.
LST_LIQUIDITY_TO_MCAP = Decimal("0.90")

#: Peg detection. A stablecoin sits on its peg by construction; 2% is wide
#: enough for ordinary depeg noise and far below the 25% the exit needs.
PEG_TOLERANCE = Decimal("0.02")
PEG_LEVELS = (Decimal("1.00"),)

#: Depth floor. $50 against this is ~0.5% round trip on the measured Jupiter
#: cost curve for established tokens; below it the position pays more in
#: impact than the strategy can plausibly earn.
MIN_LIQUIDITY_USD = Decimal("250000")
#: Above this the token is effectively an index (SOL, USDC): deep, and not
#: what a 25% trailing stop is for.
MAX_LIQUIDITY_USD = Decimal("50000000")

#: Survivor filter, as requested: seven days of continuous existence.
MIN_AGE_DAYS = 7

#: How old a price reading may be and still authorise a buy. Fifteen minutes is
#: the same stale guard the execution research used, and it is a hard bound
#: rather than a preference: the wallet sizes a position from this price, so a
#: reading nobody has refreshed since is an estimate, and this platform does not
#: trade estimates.
MAX_SNAPSHOT_AGE_SECONDS = 900

#: How far the venue's implied market cap may exceed the universe provider's
#: before the token is refused an entry.
#:
#: This exists because a measured failure, not a hypothetical one. DexScreener
#: prices a token from its deepest pool, and when that pool is quoted in
#: another volatile token rather than SOL or a dollar stablecoin, the USD
#: figure is derived through that second token's price and can be wildly
#: wrong. Measured on 2026-08-25 against Jupiter's own market caps:
#:
#:     RAY/MET    $1.10T   vs      $203M   ~5,400x
#:     JUP/MET    $3.64T   vs      $676M   ~5,380x
#:     PUMP/MET  $23.96T   vs     $1.82B  ~13,160x
#:
#: All three are large, deep tokens — precisely what a depth-ranked universe
#: buys first — so this is the common case for this wallet rather than a tail.
#: Ten times is deliberately loose: it tolerates genuine divergence between two
#: providers and a stale daily snapshot, while a four-order-of-magnitude
#: disagreement cannot survive it. Two independent sources have to agree
#: roughly on what a token is worth before this wallet will buy it.
MAX_MARKET_CAP_RATIO = Decimal("10")


@dataclass(frozen=True, slots=True)
class UniverseRow:
    """One Jupiter verified token, as captured point-in-time."""

    mint_address: str
    symbol: str | None
    age_days: float | None
    liquidity_usd: Decimal | None
    market_cap: Decimal | None
    holder_count: int | None


@dataclass(frozen=True, slots=True)
class Verdict:
    admit: bool
    reason: str | None = None


def judge(row: UniverseRow) -> Verdict:
    """Whether this token may be enrolled for trading.

    Ordered so the answer is the first true reason rather than the most
    convenient one. Missing data never admits: a token whose age or depth we
    cannot establish is refused, not assumed.
    """
    if row.age_days is None:
        return Verdict(False, "unknown_age")
    if row.age_days < MIN_AGE_DAYS:
        return Verdict(False, "under_7_days")
    if row.liquidity_usd is None:
        return Verdict(False, "unknown_liquidity")
    if row.liquidity_usd < MIN_LIQUIDITY_USD:
        return Verdict(False, "liquidity_below_floor")
    if row.liquidity_usd > MAX_LIQUIDITY_USD:
        return Verdict(False, "liquidity_above_ceiling")
    if row.market_cap is not None and row.market_cap > 0:
        if row.liquidity_usd / row.market_cap >= LST_LIQUIDITY_TO_MCAP:
            # Pool == float: a staking derivative or wrapper, not a trade.
            return Verdict(False, "staking_or_wrapped")
    return Verdict(True)


def is_pegged(price_usd: Decimal | None) -> bool:
    """Whether an observed price sits on a peg the exit could never clear.

    Checked at entry rather than at enrolment because it needs a real observed
    price, and the universe snapshot carries none. A pegged asset is refused
    for the same mechanical reason as a staking token: a 25% trailing stop on
    something that moves 0.1% a month is a position that never closes.
    """
    if price_usd is None or price_usd <= 0:
        return False
    return any(
        abs(price_usd - level) / level <= PEG_TOLERANCE for level in PEG_LEVELS
    )
