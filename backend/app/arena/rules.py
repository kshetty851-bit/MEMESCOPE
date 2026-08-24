"""The Arena's frozen rules, stated once, as pure functions.

Protocol v1.0.0 (`V5_FORWARD_ARENA_PROTOCOL.md`, blob a83892df). Every
threshold here is an economic or operational constraint declared BEFORE any
Arena outcome existed. **Editing a number here is not a tweak — it is a new
candidate version whose record starts at zero** (protocol §7), and the version
constant below must move with it.

Pure: no I/O, no clock, no randomness, no settings. `now` never appears; the
caller supplies the observation. That is what makes a decision replayable, and
a decision that cannot be replayed cannot be checked.

Missing data is never imputed. A condition whose input is UNKNOWN evaluates
FALSE and names itself in the skip reason — the platform's standing rule that
absence is charged to evidence rather than hidden.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

#: Bumping this is a new candidate whose record starts at zero.
RULES_VERSION = "1.0.0"

#: The one predeclared decision checkpoint (protocol §1).
CHECKPOINT_MINUTES = 30

#: Frozen exit policy, identical for every trading candidate (protocol §3).
TAKE_PROFIT_MULTIPLE = Decimal("1.5")
TIME_EXIT_HOURS = 6
#: Below this the position is treated as having lost its exit, not as cheap.
MIN_EXIT_LIQUIDITY_USD = Decimal("1000")

#: Sizing (protocol §4).
STARTING_EQUITY = Decimal("1000.00")
POSITION_SIZE_USD = Decimal("10.00")
MAX_CONCURRENT = 5
MAX_DEPLOYED_USD = Decimal("50.00")

#: Circuit breaker (protocol §6).
FAILURE_EQUITY_FLOOR = Decimal("800.00")

#: Operational floors shared by several candidates.
MIN_LIQUIDITY_USD = Decimal("10000")
MAX_ENTRY_IMPACT_PCT = Decimal("3.0")


@dataclass(frozen=True, slots=True)
class Observation:
    """Everything the rules may read, as of the checkpoint instant.

    A field that is `None` is UNKNOWN — never zero. The distinction decides
    whether a candidate skips for a measured reason or for an absent one, and
    the ledger records which.
    """

    # --- execution (B) ---
    buy_route_ok: bool | None = None
    sell_route_ok: bool | None = None
    quoted_impact_pct: Decimal | None = None
    liquidity_usd: Decimal | None = None

    # --- wallet flow (C) ---
    unique_wallets_1h: int | None = None
    unique_buyers_1h: int | None = None
    unique_sellers_1h: int | None = None
    top10_tx_share: Decimal | None = None
    flow_quality: str | None = None

    # --- nursery / liquidity (D) ---
    liquidity_at_10m: Decimal | None = None
    max_liquidity_drop_frac: Decimal | None = None
    observation_count: int | None = None
    drawdown_from_peak: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Verdict:
    eligible: bool
    #: The FIRST failing condition, named. Ordered so the answer is the first
    #: reason rather than the most convenient one.
    skip_reason: str | None = None


def _missing(name: str) -> Verdict:
    return Verdict(False, f"unknown_{name}")


def evaluate_b(o: Observation) -> Verdict:
    """B — TRADEABILITY. Can this realistically be bought AND sold?"""
    if o.buy_route_ok is None:
        return _missing("buy_route")
    if not o.buy_route_ok:
        return Verdict(False, "buy_route_failed")
    if o.sell_route_ok is None:
        return _missing("sell_route")
    if not o.sell_route_ok:
        return Verdict(False, "sell_route_failed")
    if o.quoted_impact_pct is None:
        return _missing("impact")
    if o.quoted_impact_pct > MAX_ENTRY_IMPACT_PCT:
        return Verdict(False, "impact_above_3pct")
    if o.liquidity_usd is None:
        return _missing("liquidity")
    if o.liquidity_usd < MIN_LIQUIDITY_USD:
        return Verdict(False, "liquidity_below_10k")
    return Verdict(True)


def evaluate_c(o: Observation) -> Verdict:
    """C — WALLET FLOW. Is participation broad, or ten wallets in a trenchcoat?"""
    if o.unique_wallets_1h is None:
        return _missing("unique_wallets")
    if o.unique_wallets_1h < 20:
        return Verdict(False, "wallets_below_20")
    if o.unique_buyers_1h is None or o.unique_sellers_1h is None:
        return _missing("buyers_sellers")
    if o.unique_buyers_1h <= o.unique_sellers_1h:
        return Verdict(False, "buyers_not_above_sellers")
    if o.top10_tx_share is None:
        return _missing("top10_share")
    if o.top10_tx_share > Decimal("0.80"):
        return Verdict(False, "top10_share_above_80pct")
    if o.flow_quality is None:
        return _missing("flow_quality")
    if o.flow_quality != "exact":
        return Verdict(False, "flow_window_capped")
    return Verdict(True)


def evaluate_d(o: Observation) -> Verdict:
    """D — NURSERY / LIQUIDITY. What happened while the platform watched?"""
    if o.liquidity_usd is None or o.liquidity_at_10m is None:
        return _missing("liquidity_trajectory")
    if o.liquidity_usd < o.liquidity_at_10m:
        return Verdict(False, "liquidity_decaying")
    if o.max_liquidity_drop_frac is None:
        return _missing("liquidity_drop")
    if o.max_liquidity_drop_frac > Decimal("0.50"):
        return Verdict(False, "liquidity_withdrawal_over_50pct")
    if o.observation_count is None:
        return _missing("observations")
    if o.observation_count < 15:
        return Verdict(False, "under_15_observations")
    if o.drawdown_from_peak is None:
        return _missing("drawdown")
    if o.drawdown_from_peak > Decimal("0.50"):
        return Verdict(False, "drawdown_over_50pct")
    return Verdict(True)


def evaluate_e(o: Observation) -> Verdict:
    """E — COMBINED QUALITY. One condition per family, plus the safety floor."""
    if o.buy_route_ok is None or o.sell_route_ok is None:
        return _missing("route")
    if not (o.buy_route_ok and o.sell_route_ok):
        return Verdict(False, "not_two_sided")
    if o.unique_wallets_1h is None:
        return _missing("unique_wallets")
    if o.unique_wallets_1h < 20:
        return Verdict(False, "wallets_below_20")
    if o.liquidity_usd is None or o.liquidity_at_10m is None:
        return _missing("liquidity_trajectory")
    if o.liquidity_usd < o.liquidity_at_10m:
        return Verdict(False, "liquidity_decaying")
    if o.liquidity_usd < MIN_LIQUIDITY_USD:
        return Verdict(False, "liquidity_below_10k")
    return Verdict(True)


#: Code -> (display name, rule function). "A" is absent on purpose: the cash
#: control has no rule to evaluate, which is the whole point of it.
EVALUATORS = {
    "B": ("Tradeability", evaluate_b),
    "C": ("Wallet Flow", evaluate_c),
    "D": ("Nursery / Liquidity", evaluate_d),
    "E": ("Combined Quality", evaluate_e),
}
CASH_CODE = "A"
CASH_NAME = "Cash Control"


def exit_decision(
    *,
    multiple: Decimal,
    liquidity_usd: Decimal | None,
    sell_route_ok: bool | None,
    held_hours: float,
    is_dead: bool,
) -> str | None:
    """Which frozen exit fires, or None to keep holding.

    Ordered by severity: a dead pool is settled before a target is honoured,
    because a price print from a pool nobody can sell into is not a fill.
    """
    if is_dead:
        return "dead_zero"
    if sell_route_ok is False:
        return "sell_route_lost"
    if liquidity_usd is not None and liquidity_usd < MIN_EXIT_LIQUIDITY_USD:
        return "sell_route_lost"
    if multiple >= TAKE_PROFIT_MULTIPLE:
        return "target_1_5x"
    if held_hours >= TIME_EXIT_HOURS:
        return "time_6h"
    return None
