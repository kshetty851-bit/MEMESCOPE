"""The hour after graduation: price, volume and buy/sell counts from the AMM.

The curve is gone once a token migrates — the account zeroes every reserve — so
everything in this module comes from market APIs instead of the chain.

## Two sources, and the order they are tried

* **DexScreener**, once every `POSTGRAD_INTERVAL_S`, batched thirty mints to a
  call. This is the live path and it carries what the brief asked for: price,
  5-minute and 1-hour volume, and buy/sell transaction counts.
* **GeckoTerminal minute OHLCV**, only to fill a gap a missed poll left.

A backfilled row is marked `source='geckoterminal'` and carries a price and one
minute's volume, and nothing else. It is NOT the same measurement as a live
poll and the column it does not fill is left null rather than approximated —
`volume_m5_usd` is a rolling five-minute window DexScreener computes, and a
one-minute candle cannot produce it.

## The fallback has a precondition worth knowing

GeckoTerminal addresses a POOL, not a mint. The pool address is learned from a
DexScreener response. So a token whose **first** DexScreener poll fails has no
pool address and can never be backfilled — the gap in its series is permanent.
This is reported rather than hidden: `backfill_impossible` counts it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.logging import get_logger
from app.labs.graduation import config
from app.labs.graduation.models import SOURCE_DEXSCREENER, SOURCE_GECKOTERMINAL
from app.labs.graduation.sources import MarketSource, chunked

logger = get_logger(__name__)

_USD_DP = Decimal("0.01")
_PRICE_DP = Decimal("0.00000001")
_USD_MAX = Decimal(10) ** 22
_PRICE_MAX = Decimal(10) ** 16


@dataclass(slots=True)
class PostGradState:
    """One graduated token, for as long as its window is open."""

    mint: str
    migrated_at: datetime
    pair_address: str | None = None
    dex_id: str | None = None
    #: The POOL OPEN: the first price this token ever answered with. The
    #: outcome window runs from here, not from the migration — they are about
    #: nine minutes apart and measuring from the migration loses that off the
    #: end of every window.
    opened_at: datetime | None = None
    last_sample_at: datetime | None = None
    samples: int = 0
    #: Timestamps already written, so a backfill cannot duplicate a live poll.
    seen_ts: set[datetime] = field(default_factory=set)

    def window_open(self, now: datetime) -> bool:
        """Open for a full hour from the POOL OPEN once there is one.

        Before the first price there is nothing to measure from, so the token
        waits `POSTGRAD_OPEN_GRACE_SECONDS` for a pair to be indexed and is
        then given up on — otherwise a graduate whose pair never appears would
        be polled for ever.
        """
        if self.opened_at is None:
            return (now - self.migrated_at).total_seconds() < (
                config.POSTGRAD_OPEN_GRACE_SECONDS)
        return (now - self.opened_at).total_seconds() < config.POST_MIGRATION_SECONDS

    def due(self, now: datetime) -> bool:
        if self.last_sample_at is None:
            return True
        return (now - self.last_sample_at).total_seconds() >= config.POSTGRAD_INTERVAL_S

    def gap_seconds(self, now: datetime) -> float:
        since = self.last_sample_at or self.migrated_at
        return (now - since).total_seconds()


def _decimal(value: object, places: Decimal, ceiling: Decimal) -> Decimal | None:
    """A finite, in-range Decimal, or None. `str()` first: these APIs send
    JSON floats and strings, and `Decimal(0.1)` is not `Decimal("0.1")`."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not out.is_finite() or out.copy_abs() >= ceiling:
        return None
    return out.quantize(places)


def _int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_pair(pair: dict[str, Any], *, ts: datetime) -> dict[str, Any] | None:
    """One `/tokens/v1/{chain}/{mints}` row -> a sample row.

    The field names are the ones this repo's Breakout lab already reads off
    this endpoint, so they are not guesses.
    """
    base = pair.get("baseToken") or {}
    mint = base.get("address")
    if not mint or pair.get("chainId") != config.NETWORK:
        return None
    volume = pair.get("volume") or {}
    txns = pair.get("txns") or {}
    m5 = txns.get("m5") or {}
    h1 = txns.get("h1") or {}
    return {
        "ts": ts,
        "mint": str(mint),
        "source": SOURCE_DEXSCREENER,
        "pair_address": str(pair["pairAddress"]) if pair.get("pairAddress") else None,
        "dex_id": str(pair["dexId"])[:32] if pair.get("dexId") else None,
        "price_usd": _decimal(pair.get("priceUsd"), _PRICE_DP, _PRICE_MAX),
        "price_native": _decimal(pair.get("priceNative"), _PRICE_DP, _PRICE_MAX),
        "liquidity_usd": _decimal((pair.get("liquidity") or {}).get("usd"),
                                  _USD_DP, _USD_MAX),
        "fdv": _decimal(pair.get("fdv"), _USD_DP, _USD_MAX),
        "volume_m5_usd": _decimal(volume.get("m5"), _USD_DP, _USD_MAX),
        "volume_h1_usd": _decimal(volume.get("h1"), _USD_DP, _USD_MAX),
        "volume_m1_usd": None,
        "txns_m5_buys": _int(m5.get("buys")),
        "txns_m5_sells": _int(m5.get("sells")),
        "txns_h1_buys": _int(h1.get("buys")),
        "txns_h1_sells": _int(h1.get("sells")),
    }


def parse_candle(candle: list[Any], *, mint: str, state: PostGradState
                 ) -> dict[str, Any] | None:
    """One GeckoTerminal `[ts, open, high, low, close, volume]` -> a sample.

    Everything DexScreener would have given and this cannot is left NULL. A
    backfilled row that carried zeros where it has no reading would be
    indistinguishable from a minute in which nothing traded.
    """
    seconds = _int(candle[0])
    close = _decimal(candle[4], _PRICE_DP, _PRICE_MAX)
    if seconds is None or close is None:
        return None
    return {
        "ts": datetime.fromtimestamp(seconds, tz=UTC),
        "mint": mint,
        "source": SOURCE_GECKOTERMINAL,
        "pair_address": state.pair_address,
        "dex_id": state.dex_id,
        "price_usd": close,
        "price_native": None,
        "liquidity_usd": None,
        "fdv": None,
        "volume_m5_usd": None,
        "volume_h1_usd": None,
        "volume_m1_usd": _decimal(candle[5], _USD_DP, _USD_MAX),
        "txns_m5_buys": None,
        "txns_m5_sells": None,
        "txns_h1_buys": None,
        "txns_h1_sells": None,
    }


class PostGradSampler:
    """Holds the open windows and produces sample rows for them."""

    def __init__(
        self,
        *,
        market: MarketSource,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._market = market
        self._now = now
        self.states: dict[str, PostGradState] = {}
        self.samples_written = 0
        self.backfilled = 0
        self.backfill_impossible = 0
        #: Samples refused because they came from a pool the position was not
        #: opened against. A non-zero count here is the sampler working.
        self.pair_rejected = 0

    def __len__(self) -> int:
        return len(self.states)

    def start(self, mint: str, migrated_at: datetime) -> None:
        """Open a window. Idempotent: the migration feed and the chain's own
        `complete` flag can both report the same graduation."""
        self.states.setdefault(mint, PostGradState(mint=mint, migrated_at=migrated_at))

    def close(self, mint: str) -> None:
        self.states.pop(mint, None)

    def expire(self, now: datetime) -> list[str]:
        """Drop windows that have run their hour, and name them."""
        done = [m for m, s in self.states.items() if not s.window_open(now)]
        for mint in done:
            self.states.pop(mint, None)
        return done

    async def poll(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """One pass: sample everything due, then backfill what was missed."""
        now = now or self._now()
        self.expire(now)
        due = [m for m, s in self.states.items() if s.due(now)]
        rows: list[dict[str, Any]] = []
        for batch in chunked(due, config.DEXSCREENER_BATCH):
            for pair in await self._market.dex_pairs(batch):
                if (row := parse_pair(pair, ts=now)) is not None:
                    rows.append(row)
        # Deepest pool first, so a mint's FIRST sample pins the pair a real
        # order would actually have hit rather than whichever row DexScreener
        # happened to list first.
        rows.sort(key=lambda r: r.get("liquidity_usd") or 0, reverse=True)
        rows = [r for r in rows if self._accept(r)]
        rows.extend(await self._backfill(now))
        self.samples_written += len(rows)
        return rows

    def _accept(self, row: dict[str, Any]) -> bool:
        """Record what a live sample taught us, and refuse a duplicate ts.

        The PAIR IS PINNED on the first sample and every later row from a
        different pair is refused. `/tokens/v1` answers with every pool a mint
        trades in, and the order is not stable, so without this the series
        silently hops between pools: observed 2026-09-11, ORE's marks moved
        from its SOL pair to a USD-quoted one and "rose" 100x in a minute
        without trading, and a pump.fun token jumped 162x the same way. 45 of
        349 paper trades were affected and they accounted for +$2,414 of a
        +$1,712 book.

        A position is opened against one pool. Marking it against another is
        not a price change, it is a change of instrument.
        """
        state = self.states.get(row["mint"])
        if state is None:
            return False
        pair = row.get("pair_address")
        if state.pair_address is None:
            state.pair_address = pair
        elif pair != state.pair_address:
            self.pair_rejected += 1
            return False
        if row["ts"] in state.seen_ts:
            return False
        state.seen_ts.add(row["ts"])
        state.opened_at = state.opened_at or row["ts"]
        state.last_sample_at = row["ts"]
        state.samples += 1
        state.dex_id = row.get("dex_id") or state.dex_id
        return True

    async def _backfill(self, now: datetime) -> list[dict[str, Any]]:
        """Fill gaps left by polls that did not happen or did not answer."""
        rows: list[dict[str, Any]] = []
        for state in list(self.states.values()):
            if state.gap_seconds(now) < config.BACKFILL_GAP_SECONDS:
                continue
            if state.pair_address is None:
                # Never had a successful poll, so there is no pool to ask
                # about. Counted, because a silent permanent gap is worse
                # than a loud one.
                self.backfill_impossible += 1
                continue
            minutes = min(config.BACKFILL_MINUTES,
                          max(1, int(state.gap_seconds(now) // 60) + 1))
            candles = await self._market.gecko_minute_ohlcv(
                state.pair_address, limit=minutes)
            for candle in candles:
                row = parse_candle(candle, mint=state.mint, state=state)
                if row is None or row["ts"] in state.seen_ts:
                    continue
                if row["ts"] < state.migrated_at - timedelta(minutes=1):
                    # Candles predating the graduation belong to a different
                    # question; this table is the hour AFTER.
                    continue
                state.seen_ts.add(row["ts"])
                rows.append(row)
            if rows:
                state.last_sample_at = max(r["ts"] for r in rows)
                self.backfilled += 1
        return rows
