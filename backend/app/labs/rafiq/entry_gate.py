"""The v2 entry gate. Refuses a candidate before it ever becomes a position.

WHAT THIS IS, AND WHAT THE EVIDENCE FOR IT ACTUALLY SAYS
--------------------------------------------------------
v1 ran five books for a day. Every book cleared a 50% win rate and every book
still lost. The proposal this module implements reads that as a cost problem —
$50 into a thin pump.fun pool pays ~10% round trip on the way in and out, and a
stop cannot fill at all on a token whose pool has gone — and gates entry on
liquidity, market cap and price impact to stop it happening.

**That reading was tested before this was written, and it did not survive.**
Replayed over 290 closed v1 trades, the gate left expectancy flat (-10.1% for
the trades it admits against -10.2% for the trades it rejects) and moved the
total losses onto the side it admits: a 20.5% wipeout rate among admitted
tokens against 1.0% among rejected ones. Both terms point that way on their
own — tokens over $200k market cap wiped out 19.3% of the time against 0.0%
below it. Entry liquidity measures how much there is to drain, not how likely
a token is to be drained.

It is implemented anyway, deliberately, because a replay over one day of one
market regime is weaker evidence than a forward run, and the forward run is the
thing that settles it. Nothing here should be read as a claim that it works.

WHERE PRICE IMPACT COMES FROM
-----------------------------
The proposal assumed the token stream carries a venue's quoted slippage. It
does not — `feed.Observation` has no such field, and this platform takes no
quotes. It carries something better attested instead: `adapters/costs.py`'s
`side_cost`, MEMESCOPE's own fit to 320 live Jupiter quotes, which computes the
impact this exact notional would pay at this exact depth.

That substitution has a consequence worth stating, because it changes which
threshold binds. Under that model a position sitting at the proposed
`max_position_pct_of_liquidity` of 0.5% carries 10.7% impact — seven times the
1.5% cap printed beside it. So the impact rule reaches every candidate first,
`max_position_pct_of_liquidity` never fires, and the effective liquidity floor
is not $50,000 but about $78,900 at a $50 position and $39,400 at $25. The
0.5% rule is kept because it was specified, not because it can ever bind.

THRESHOLDS ARE NOT TUNED AND MUST NOT BE
----------------------------------------
Every number below is the proposal's own starting value, transcribed. Fitting
them to this platform's data is the exact error that produced v1, and a gate
tuned on the trades it is meant to be evaluated against measures nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.labs.rafiq.adapters.costs import CostModel, side_cost

#: The cost model the gate prices impact against. The same 30 bps the
#: strategies carry — a gate that priced impact differently from the runner
#: would reject candidates the runner would have filled cheaply, and vice versa.
MODEL = CostModel(swap_fee_bps=Decimal(30))


@dataclass(frozen=True, slots=True)
class GateThresholds:
    """One book's entry conditions. Starting values, never fitted ones."""

    min_liquidity_usd: Decimal = Decimal(50_000)
    min_market_cap_usd: Decimal = Decimal(200_000)
    #: Reject when the modelled impact for THIS notional at THIS depth is worse
    #: than this. In practice the binding condition — see the module docstring.
    max_entry_price_impact_pct: Decimal = Decimal("1.5")
    #: Reject when the position would itself be a large share of the pool. Kept
    #: because it was specified; it cannot fire before the impact rule does.
    max_position_pct_of_liquidity: Decimal = Decimal("0.5")
    #: A missing reading is a rejection, not a pass. An unmeasured token cannot
    #: be shown to clear a floor, and v1's worst fills were on tokens with no
    #: symbol and no reported cap.
    reject_if_liquidity_unknown: bool = True
    reject_if_market_cap_unknown: bool = True

    @property
    def canonical(self) -> dict:
        """Every threshold as strings, for the profile digest.

        A gate threshold changes what a book trades, so it belongs in the hash
        that stops a changed rule being traded into an existing record.
        """
        return {
            "min_liquidity_usd": str(self.min_liquidity_usd),
            "min_market_cap_usd": str(self.min_market_cap_usd),
            "max_entry_price_impact_pct": str(self.max_entry_price_impact_pct),
            "max_position_pct_of_liquidity": str(self.max_position_pct_of_liquidity),
            "reject_if_liquidity_unknown": self.reject_if_liquidity_unknown,
            "reject_if_market_cap_unknown": self.reject_if_market_cap_unknown,
        }


#: Applied identically to A2, B2, C2 and D2, so its effect is readable by
#: comparing A2 against v1's A rather than against another gated book.
DEFAULT = GateThresholds()

#: E2 only. The question E2 asks is whether a much harder gate works at a much
#: lower trade count, so these are deliberately far stricter — and E2 already
#: carries the consensus and manipulation vetoes on top.
STRICT = GateThresholds(
    min_liquidity_usd=Decimal(150_000),
    min_market_cap_usd=Decimal(500_000),
    max_entry_price_impact_pct=Decimal("0.75"),
    max_position_pct_of_liquidity=Decimal("0.25"),
)


@dataclass(frozen=True, slots=True)
class GateVerdict:
    """Allowed or not, and if not, the first condition that failed."""

    allowed: bool
    #: Stable code, suitable for a rejection counter. `None` when allowed.
    reason: str | None = None
    detail: str | None = None
    #: The modelled entry impact, when it could be computed at all. Recorded on
    #: the position for admitted candidates so a later read-out never has to
    #: re-derive it against a cost model that may have moved since.
    entry_impact_pct: Decimal | None = None


def impact_pct(notional: Decimal, liquidity_usd: Decimal | None) -> Decimal | None:
    """Impact ALONE for one leg, either side — no swap fee, or the cap is misread.

    `side_cost.total_pct` folds the 30 bps fee in with impact. The proposal's
    `max_entry_price_impact_pct` is a slippage cap, not a round-trip cost cap,
    so comparing the total against it would reject a further 0.3% of depth for
    a reason the threshold was never written about.

    The model is symmetric, so the same function prices an exit: what a sale of
    `notional` gives up at this depth. `_settle` records that on the way out.

    """
    cost = side_cost(notional, liquidity_usd, model=MODEL)
    return None if cost is None else cost.impact_pct


def check_entry(*, liquidity_usd: Decimal | None, market_cap_usd: Decimal | None,
                notional_usd: Decimal,
                thresholds: GateThresholds = DEFAULT) -> GateVerdict:
    """Allow or refuse one entry, naming the first condition it fails.

    Order affects only which reason is reported, never the outcome. Liquidity
    is checked first because it is the condition behind both of v1's failure
    modes: it drives impact on the way in, and its absence is what turns a
    designed -12% stop into a -100% fill on the way out.
    """
    if liquidity_usd is None or liquidity_usd <= 0:
        if thresholds.reject_if_liquidity_unknown:
            return GateVerdict(False, "liquidity_unknown")
    elif liquidity_usd < thresholds.min_liquidity_usd:
        return GateVerdict(False, "liquidity_too_low",
                           f"${liquidity_usd:,.0f} < "
                           f"${thresholds.min_liquidity_usd:,.0f}")
    else:
        share_pct = notional_usd / liquidity_usd * 100
        if share_pct > thresholds.max_position_pct_of_liquidity:
            return GateVerdict(False, "position_too_large_for_pool",
                               f"{share_pct:.3f}% of pool > "
                               f"{thresholds.max_position_pct_of_liquidity}%")

    if market_cap_usd is None or market_cap_usd <= 0:
        if thresholds.reject_if_market_cap_unknown:
            return GateVerdict(False, "market_cap_unknown")
    elif market_cap_usd < thresholds.min_market_cap_usd:
        return GateVerdict(False, "market_cap_too_low",
                           f"${market_cap_usd:,.0f} < "
                           f"${thresholds.min_market_cap_usd:,.0f}")

    impact = impact_pct(notional_usd, liquidity_usd)
    if impact is None:
        # Only reachable when liquidity is unpriceable AND the operator turned
        # `reject_if_liquidity_unknown` off. An unmeasurable cost is not a
        # zero cost, so it refuses rather than defaulting.
        return GateVerdict(False, "price_impact_unknown")
    if impact > thresholds.max_entry_price_impact_pct:
        return GateVerdict(False, "price_impact_too_high",
                           f"{impact:.2f}% > "
                           f"{thresholds.max_entry_price_impact_pct}%",
                           entry_impact_pct=impact)

    return GateVerdict(True, entry_impact_pct=impact)


#: Every reason `check_entry` can return, so a read-out can show a zero for a
#: condition that never fired rather than omitting it. Two of these are
#: expected to stay at zero for the default thresholds — see the docstring.
REASONS: tuple[str, ...] = (
    "liquidity_unknown",
    "liquidity_too_low",
    "position_too_large_for_pool",
    "market_cap_unknown",
    "market_cap_too_low",
    "price_impact_unknown",
    "price_impact_too_high",
)
