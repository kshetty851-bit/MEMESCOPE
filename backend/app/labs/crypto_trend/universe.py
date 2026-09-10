"""Top-30 by market cap -> the tradeable top-20. Pure; no I/O."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.core.logging import get_logger
from app.labs.crypto_trend import config

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Coin:
    coingecko_id: str
    ticker: str
    name: str
    binance_symbol: str
    rank: int
    market_cap_rank: int | None
    market_cap_usd: Decimal | None


def is_excluded(market: dict[str, Any]) -> bool:
    return (str(market["id"]).lower() in config.EXCLUDED
            or str(market["symbol"]).lower() in config.EXCLUDED)


def map_symbol(coingecko_id: str, ticker: str) -> str:
    """The Binance perp for a coin: the override if there is one, else
    `<TICKER>USDT`. Whether that contract exists is the caller's check."""
    return config.SYMBOL_OVERRIDES.get(coingecko_id) or f"{ticker.upper()}USDT"


def select_universe(
    markets: Iterable[dict[str, Any]],
    perps: set[str],
    *,
    size: int = config.UNIVERSE_SIZE,
) -> tuple[list[Coin], list[dict[str, str]]]:
    """Walk the ranking in order: drop exclusions, drop anything without a
    Binance perp (logged and returned as `skipped`), stop at `size`.

    A coin with no perp does not consume one of the 20 slots — it cannot be
    traded, so it cannot be one of the 20 that are. The universe can still be
    short of `size` when the top-30 is thin on tradeable coins; the health
    report shows the count.
    """
    chosen: list[Coin] = []
    skipped: list[dict[str, str]] = []
    for m in markets:
        if is_excluded(m):
            continue
        ticker = str(m["symbol"]).upper()
        symbol = map_symbol(str(m["id"]), ticker)
        if symbol not in perps:
            skipped.append({"coingecko_id": str(m["id"]), "ticker": ticker, "tried": symbol})
            logger.info("crypto_trend_no_perp", coingecko_id=m["id"], ticker=ticker,
                        tried=symbol)
            continue
        cap = m.get("market_cap")
        chosen.append(Coin(
            coingecko_id=str(m["id"]), ticker=ticker, name=str(m.get("name") or ticker),
            binance_symbol=symbol, rank=len(chosen) + 1,
            market_cap_rank=m.get("market_cap_rank"),
            market_cap_usd=None if cap is None else Decimal(str(cap)),
        ))
        if len(chosen) >= size:
            break
    return chosen, skipped
