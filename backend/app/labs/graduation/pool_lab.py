"""Pool Lab (Karthik, 2026-10-05: "build Pool LAB - lets start 10k pool WITH
this 10x splits. and another table build 50k pool - 50$ on 500$ each with 10
user wallets backtest, keep the trade price real way, start the timer too").

Two books:

* $10k+ pools, the quiet rule, every size on ten times its balance: LIVE ONLY,
  from its own paper arm (`TEN_K_BOOK`) since `START` (the timer). Its replayed
  backtest went on 2026-10-05 at Karthik's request ("reset their profit");
  the tiny-pool replays rested on a few 5-7x prints anyway.
* $50k+ pools, ten user wallets at $50 on $500 each — a BACKTEST from 1 Oct
  00:00 Dubai and LIVE from `START` — on the real-time
  trades of Karthik's book (never replayed rows), the coins the real wallets
  refuse taken out. "The real way": wallets that buy the same coin buy ONE
  AFTER ANOTHER, so each pays the price the ones before it pushed up, and they
  sell the same way. With the real per-coin cap ($250 across user wallets)
  only five wallets fit in a coin; the longest-waiting go first, as the driver
  does. The uncapped total — all ten in every coin — is shown beside it.

Pricing is the lab's own: `api._multiple`'s linear pool impact, generalised to
a different order size on each leg, and `api._size_penalty` for the flat fee.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

#: The timer: the live columns count from here.
# Reset 2026-10-05 (Karthik: "i want to see 10k pool starting now so reset
# their profit"): the $10k book is live-only from here, no backtest.
# Then from the book's FIRST trade (15:59:14), when it moved to a 3-minute
# sell the same evening ("revise 10k pool selling at 3m, change the profit
# assuming we started since 1st trade"): its trades before the change are its
# 5-minute twin's, re-priced at three minutes (`scripts/seed_quiet_4m.py`).
START = datetime(2026, 10, 5, 15, 59, tzinfo=UTC)
#: The backtests count from 1 Oct, 00:00 Dubai.
FROM = datetime(2026, 9, 30, 20, 0, tzinfo=UTC)
TEN_K_BOOK = "POOL_10K_QUIET_3M"
#: Pools the $10k book skips (Karthik, 2026-10-06: "apply skip 25k-50k pools
#: to 10k book and assume we had this rule since start"). The arm stops buying
#: them (`floor10k_no25_50`); the page leaves out the ones it bought before.
SKIP_POOL_USD = (25_000, 50_000)
#: Skip a coin whose pool had more than this many sells (DexScreener's 5-minute
#: count, last read before the buy) when it was bought (Karthik, 2026-10-10:
#: "yes apply it and revise profit since day 1"). On the book's 615 trades
#: 5-10 Oct, the 152 with more than 5 lost money on every day (-$741 at $50),
#: book -$188 -> +$473; chosen on the first half, held on the second. The page
#: leaves them out from the first trade; the arm still buys them.
MAX_SELLS_BEFORE = 5
SIZES = (10, 20, 25, 50, 100, 200)
WALLETS = 10
WALLET_TICKET = 50.0
WALLET_START = 500.0
#: The real wallets' per-coin cap across user wallets (REAL_WALLET_MAX_COIN_USD).
COIN_CAP = 250.0
RUG = -0.5
NEVER = datetime.min.replace(tzinfo=UTC)


def legs_multiple(
    ret: float, impact: tuple[float, float] | None, k_buy: float, k_sell: float
) -> float:
    """`api._multiple` with a different order size on each leg: a trade
    measured at $100 (k=1) as `ret`, at `k_buy` times that size on the way in
    and `k_sell` on the way out."""
    gross = 1.0 + ret
    if impact:
        i_open, i_close = impact
        gross *= (1 + i_open) / (1 + k_buy * i_open) * (1 + i_close) / (1 + k_sell * i_close)
    return gross


def queue_k(position: int, ticket: float, measured: float = 100.0) -> float:
    """The impact multiple for the `position`-th order (0 = first) of `ticket`
    dollars in a queue of equal orders. Impact is linear in the dollars already
    moved, so the order after `y` dollars pays as if it were `2y + x`."""
    return (2 * position * ticket + ticket) / measured


@dataclass
class Wallet:
    name: str
    cash: float = WALLET_START
    low: float = WALLET_START
    held: list[tuple[datetime, float, float]] = field(default_factory=list)
    trades: int = 0
    rugs: int = 0
    last_buy: datetime = NEVER

    def settle_until(self, at: datetime) -> None:
        due = sorted((h for h in self.held if h[0] <= at), key=lambda h: h[0])
        self.held = [h for h in self.held if h[0] > at]
        equity = self.cash + sum(h[2] for h in self.held) + sum(h[2] for h in due)
        for _, multiple, stake in due:
            self.cash += stake * multiple
            equity += stake * (multiple - 1)
            self.low = min(self.low, equity)

    def worth(self) -> float:
        return self.cash + sum(h[2] * h[1] for h in self.held)


def ten_wallets(
    trades: list[tuple[datetime, datetime, float, tuple[float, float] | None]],
    penalty: float,
    *,
    cap: float | None,
) -> list[Wallet]:
    """Ten wallets on the same coins, one after another. `trades` are
    (opened, closed, return measured at $100, (impact_open, impact_close))."""
    wallets = [Wallet(f"USER {i}") for i in range(1, WALLETS + 1)]
    per_coin = WALLETS if cap is None else int(cap // WALLET_TICKET)
    for opened, closed, ret, impact in sorted(trades, key=lambda t: t[0]):
        for w in wallets:
            w.settle_until(opened)
        ready = sorted(
            (w for w in wallets if w.cash >= WALLET_TICKET),
            key=lambda w: (w.last_buy, int(w.name.split()[-1])),
        )[:per_coin]
        for place, w in enumerate(ready):
            k = queue_k(place, WALLET_TICKET)
            multiple = legs_multiple(ret, impact, k, k) - penalty
            w.cash -= WALLET_TICKET
            w.held.append((closed, multiple, WALLET_TICKET))
            w.trades += 1
            w.rugs += ret <= RUG
            w.last_buy = opened
    for w in wallets:
        w.settle_until(datetime.max.replace(tzinfo=UTC))
    return wallets


def wallets_payload(wallets: list[Wallet]) -> dict[str, Any]:
    rows = [
        {
            "name": w.name,
            "balance_usd": round(w.worth(), 2),
            "pnl_usd": round(w.worth() - WALLET_START, 2),
            "trades": w.trades,
            "rugs": w.rugs,
            "lowest_usd": round(w.low, 2),
        }
        for w in wallets
    ]
    total = sum(r["balance_usd"] for r in rows)
    return {
        "wallets": rows,
        "total_usd": round(total, 2),
        "pnl_usd": round(total - WALLET_START * len(rows), 2),
        "trades": sum(r["trades"] for r in rows),
    }
