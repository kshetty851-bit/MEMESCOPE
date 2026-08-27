"""Bounded rolling wallet-flow aggregation.

Answers the question the aggregate market fields cannot: **10,000 transactions
from 5,000 wallets is not the same as 10,000 from 80**, and DATA-1B showed that
liquidity/market-cap can tell us what dies but is blind to what runs. Breadth
and concentration are the missing measurements.

## Why a ring buffer rather than per-wallet counters

Every metric here is a *share within one mint* over a *time window*. A sliding
window over per-wallet counters needs either per-wallet timestamp lists (which
is the unbounded wallet map this must not build) or approximate decay. A small
fixed ring of recent events per mint gives exact answers over any window it
still covers, in memory that is bounded by construction: `capacity` events per
mint, nothing per wallet.

The ceiling is stated rather than hidden. When a window's oldest event is newer
than the window itself, the ring has overflowed and the count is a floor, not a
total — reported as `quality="capped"` so a reader never mistakes a truncated
count for a complete one.

## What is bounded

* events per mint — `capacity`, oldest evicted first
* tracked mints — `max_mints`, least-recently-traded evicted first
* idle mints — dropped after `ttl_seconds` with no trade

Nothing grows with the number of distinct wallets, which is the only quantity
here that has no natural limit.
"""

from __future__ import annotations

from collections import Counter, OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.services.scanner.trade_events import Side, TradeEvent

#: Windows every snapshot reports. Ordered so the ring only has to cover the
#: longest one to answer all three.
WINDOWS: tuple[tuple[str, timedelta], ...] = (
    ("5m", timedelta(minutes=5)),
    ("15m", timedelta(minutes=15)),
    ("1h", timedelta(hours=1)),
)


@dataclass(slots=True)
class _MintState:
    events: deque[tuple[datetime, str, Side, int]]
    last_seen: datetime
    #: Signatures already folded in, so a reconnect replay cannot double-count.
    #: Bounded with the ring: a signature older than the ring cannot be
    #: re-applied to it anyway.
    seen: deque[str] = field(default_factory=deque)
    seen_set: set[str] = field(default_factory=set)
    overflowed: bool = False


@dataclass(frozen=True, slots=True)
class FlowStats:
    """One window of one mint. `quality` states what the numbers are worth."""

    window: str
    unique_buyers: int
    unique_sellers: int
    unique_wallets: int
    buy_count: int
    sell_count: int
    buy_volume: int
    sell_volume: int
    tx_per_wallet: float | None
    repeat_wallet_ratio: float | None
    top5_tx_share: float | None
    top10_tx_share: float | None
    top5_volume_share: float | None
    top10_volume_share: float | None
    largest_buyer_share: float | None
    largest_seller_share: float | None
    quality: str

    def as_dict(self) -> dict[str, Any]:
        return {f: getattr(self, f) for f in self.__slots__}


def _share(counter: Counter[str], top: int, total: int) -> float | None:
    if total <= 0 or not counter:
        return None
    return sum(c for _, c in counter.most_common(top)) / total


class WalletFlowTracker:
    """In-process, bounded, and safe to run inside the scanner loop.

    Deliberately holds no lock and does no I/O: it is updated from the single
    task that already reads the socket, and read at decision time through a
    snapshot. Adding a lock would put contention on the hot path that feeds
    discovery.
    """

    def __init__(
        self,
        *,
        capacity: int = 256,
        max_mints: int = 4000,
        ttl_seconds: float = 3600.0,
    ) -> None:
        self._capacity = capacity
        self._max_mints = max_mints
        self._ttl = timedelta(seconds=ttl_seconds)
        # OrderedDict, not dict: eviction is O(1) via popitem(last=False).
        # A full sort over the tracked set on every insertion past the cap
        # collapsed ingest from 52,000 to 562 events/sec under load — below
        # the arrival rate, which would back up the scanner's queue.
        self._mints: OrderedDict[str, _MintState] = OrderedDict()
        self.events_applied = 0
        self.duplicates = 0
        self.evicted_mints = 0
        self.evicted_events = 0

    # --- ingest -------------------------------------------------------------

    def apply(self, key: str, event: TradeEvent, *, signature: str | None = None) -> bool:
        """Fold one trade in. `key` is the mint, or the pool when that is all
        the chain gave us. Returns False for a duplicate."""
        state = self._mints.get(key)
        if state is None:
            state = _MintState(events=deque(), last_seen=event.observed_at)
            self._mints[key] = state
            self._enforce_mint_cap(event.observed_at)
        else:
            # Touch: keeps the cold end of the mapping genuinely cold.
            self._mints.move_to_end(key)

        if signature is not None:
            if signature in state.seen_set:
                self.duplicates += 1
                return False
            state.seen.append(signature)
            state.seen_set.add(signature)
            while len(state.seen) > self._capacity:
                state.seen_set.discard(state.seen.popleft())

        state.events.append((event.observed_at, event.user, event.side, max(0, event.amount)))
        # Out-of-order arrivals are normal on a log stream; keeping the ring
        # ordered is what makes window filtering correct rather than merely
        # cheap.
        if len(state.events) > 1 and state.events[-2][0] > event.observed_at:
            ordered = sorted(state.events, key=lambda e: e[0])
            state.events.clear()
            state.events.extend(ordered)
        while len(state.events) > self._capacity:
            state.events.popleft()
            state.overflowed = True
            self.evicted_events += 1
        state.last_seen = max(state.last_seen, event.observed_at)
        self.events_applied += 1
        return True

    def _enforce_mint_cap(self, now: datetime) -> None:
        """Drop the least-recently-traded mints, one cheap pop at a time.

        A dead launch stops trading, so recency is relevance here. `apply`
        moves a mint to the end on every trade, which makes the front of the
        mapping the coldest entry and eviction O(1).
        """
        while len(self._mints) > self._max_mints:
            self._mints.popitem(last=False)
            self.evicted_mints += 1

    def expire(self, now: datetime) -> int:
        """Drop mints that have not traded within the TTL."""
        dead = [k for k, s in self._mints.items() if now - s.last_seen > self._ttl]
        for k in dead:
            del self._mints[k]
            self.evicted_mints += 1
        return len(dead)

    # --- read ---------------------------------------------------------------

    def stats(self, key: str, *, now: datetime) -> list[FlowStats]:
        """Every window for one mint. Empty when the mint is not tracked."""
        state = self._mints.get(key)
        if state is None:
            return []
        out: list[FlowStats] = []
        for label, span in WINDOWS:
            cutoff = now - span
            # Bounded at BOTH ends. The upper bound is the point-in-time
            # guarantee: a snapshot stamped `now` must contain only what was
            # observed before `now`, and log timestamps can run ahead of the
            # reader through ordinary clock skew. Without it a decision-time
            # snapshot silently includes the future.
            rows = [e for e in state.events if cutoff <= e[0] <= now]
            out.append(self._window_stats(label, rows, state, span))
        return out

    def _window_stats(
        self, label: str, rows: list[tuple[datetime, str, Side, int]],
        state: _MintState, span: timedelta,
    ) -> FlowStats:
        buyers = {w for _, w, s, _ in rows if s is Side.BUY}
        sellers = {w for _, w, s, _ in rows if s is Side.SELL}
        wallets = buyers | sellers
        tx = Counter(w for _, w, _, _ in rows)
        vol: Counter[str] = Counter()
        for _, w, _, a in rows:
            vol[w] += a
        buy_c = sum(1 for _, _, s, _ in rows if s is Side.BUY)
        sell_c = len(rows) - buy_c
        buy_v = sum(a for _, _, s, a in rows if s is Side.BUY)
        sell_v = sum(a for _, _, s, a in rows if s is Side.SELL)
        total_tx = len(rows)
        total_vol = buy_v + sell_v
        buyer_vol: Counter[str] = Counter()
        seller_vol: Counter[str] = Counter()
        for _, w, s, a in rows:
            (buyer_vol if s is Side.BUY else seller_vol)[w] += a
        # Coverage rule, stated once and simply: the ring can only be missing
        # events inside this window if it has overflowed AND its oldest
        # retained event is newer than the window start. Anything else means
        # every event in the window is still held, so the counts are exact.
        window_start = (rows[0][0] if rows else None)
        oldest_held = state.events[0][0] if state.events else None
        truncated = (
            state.overflowed
            and oldest_held is not None
            and window_start is not None
            and oldest_held > window_start - span
        )
        quality = "capped" if truncated else "exact"
        return FlowStats(
            window=label,
            unique_buyers=len(buyers),
            unique_sellers=len(sellers),
            unique_wallets=len(wallets),
            buy_count=buy_c,
            sell_count=sell_c,
            buy_volume=buy_v,
            sell_volume=sell_v,
            tx_per_wallet=(total_tx / len(wallets)) if wallets else None,
            repeat_wallet_ratio=(
                sum(1 for c in tx.values() if c > 1) / len(wallets) if wallets else None
            ),
            top5_tx_share=_share(tx, 5, total_tx),
            top10_tx_share=_share(tx, 10, total_tx),
            top5_volume_share=_share(vol, 5, total_vol),
            top10_volume_share=_share(vol, 10, total_vol),
            largest_buyer_share=_share(buyer_vol, 1, buy_v),
            largest_seller_share=_share(seller_vol, 1, sell_v),
            quality=quality,
        )

    # --- observability ------------------------------------------------------

    @property
    def tracked_mints(self) -> int:
        return len(self._mints)

    @property
    def active_wallet_entries(self) -> int:
        """Total buffered events — the memory this holds, in one number."""
        return sum(len(s.events) for s in self._mints.values())

    def metrics(self) -> dict[str, int]:
        return {
            "tracked_mints": self.tracked_mints,
            "active_wallet_entries": self.active_wallet_entries,
            "events_applied": self.events_applied,
            "duplicates": self.duplicates,
            "evicted_mints": self.evicted_mints,
            "evicted_events": self.evicted_events,
        }
