"""Trade-flow features derived from two market snapshots.

One implementation, because two systems now read the same number and a second
copy would be a second definition the moment either was edited. The Strategy
Lab computes `sell_share_15m` for its twenty portfolios; the paper wallet needs
the identical figure to test a rule derived from the Lab's own trades, and a
rule tested against a differently-computed feature would not be the same rule.

## Why sell share

Measured on V6.1's first 26 closed V6-07 trades, every loss was a `dead_zero` —
the token going to zero — and the entry rule was blind to it: liquidity at entry
was $698k for winners against $684k for the deaths. Sell share separated them
where liquidity did not, at 0.023 against 0.244.

That is four losing trades, so it is a hypothesis rather than a finding, and it
is the reason this module exists rather than a reason to trust it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


class _CountedSnapshot(Protocol):
    """The two counters this needs, from any snapshot-shaped row."""

    buy_count_24h: int | None
    sell_count_24h: int | None


def counter_delta(now: int | None, then: int | None) -> int | None:
    """Counter difference, clamped at zero.

    The 24h counters tick backwards on a small fraction of rows — the window
    slides, so an old trade can leave it — and a negative trade count is not
    information. Clamping is what the Lab has always done; it is restated here
    rather than reimplemented so the two cannot drift apart.
    """
    if now is None or then is None:
        return None
    return max(0, int(now) - int(then))


@dataclass(frozen=True, slots=True)
class TradeFlow:
    """Buy/sell mix across a window. `None` anywhere means unmeasured."""

    #: Sell trades as a fraction of all trades in the window.
    sell_share: Decimal | None
    #: Total trades in the window — the denominator, exposed because a share
    #: computed over three trades is not the same evidence as one over three
    #: hundred, and a caller that cannot see the count cannot tell.
    trade_count: int | None

    @property
    def measured(self) -> bool:
        return self.sell_share is not None


def trade_flow(
    last: _CountedSnapshot | None, earlier: _CountedSnapshot | None
) -> TradeFlow:
    """Buy/sell mix between two snapshots, or unmeasured.

    Unmeasured — not zero, and not "no selling". A missing counter, a missing
    earlier snapshot or a window with no trades in it all mean nobody observed
    the mix, and a caller filtering on "sell share is low" must not be handed a
    zero it can pass. Callers decide what to do with `None`; this refuses to
    invent it.
    """
    if last is None or earlier is None:
        return TradeFlow(sell_share=None, trade_count=None)
    buys = counter_delta(last.buy_count_24h, earlier.buy_count_24h)
    sells = counter_delta(last.sell_count_24h, earlier.sell_count_24h)
    if buys is None or sells is None:
        return TradeFlow(sell_share=None, trade_count=None)
    total = buys + sells
    if total <= 0:
        # No trades in the window. A share is undefined rather than zero: an
        # untraded token is not a token nobody is selling.
        return TradeFlow(sell_share=None, trade_count=0)
    return TradeFlow(sell_share=Decimal(sells) / Decimal(total), trade_count=total)


__all__ = ["TradeFlow", "counter_delta", "trade_flow"]
