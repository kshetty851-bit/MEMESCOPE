"""Market-wide regime from the universe's 4h directions. Pure.

    RISK_ON   breadth_up   >= BREADTH_RISK_ON  and BTC is not DOWN
    RISK_OFF  breadth_down >= BREADTH_RISK_OFF and BTC is not UP
    CHOP      otherwise

Breadth is the fraction of coins WITH a 4h state; a coin too new to have one
is not in the denominator. A missing BTC state is neither UP nor DOWN, so it
vetoes nothing — the brief's rule is "BTC not DOWN", and absent is not DOWN.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from app.labs.crypto_trend import config

RISK_ON, RISK_OFF, CHOP = "RISK_ON", "RISK_OFF", "CHOP"


@dataclass(frozen=True, slots=True)
class Regime:
    bar_close_time: datetime
    computed_at: datetime
    #: Coins with a 4h state — the breadth denominator.
    coins: int
    breadth_up: float
    breadth_down: float
    btc_direction: str | None
    eth_direction: str | None
    regime: str


def compute_regime(
    directions_4h: Mapping[str, str], *, bar_close_time: datetime, computed_at: datetime,
) -> Regime:
    n = len(directions_4h)
    up = sum(1 for d in directions_4h.values() if d == "UP") / n if n else 0.0
    down = sum(1 for d in directions_4h.values() if d == "DOWN") / n if n else 0.0
    btc = directions_4h.get(config.REGIME_BTC_SYMBOL)
    eth = directions_4h.get(config.REGIME_ETH_SYMBOL)
    if n and up >= config.BREADTH_RISK_ON and btc != "DOWN":
        regime = RISK_ON
    elif n and down >= config.BREADTH_RISK_OFF and btc != "UP":
        regime = RISK_OFF
    else:
        regime = CHOP
    return Regime(bar_close_time=bar_close_time, computed_at=computed_at, coins=n,
                  breadth_up=up, breadth_down=down, btc_direction=btc, eth_direction=eth,
                  regime=regime)
