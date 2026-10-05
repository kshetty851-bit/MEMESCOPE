"""Pool Lab (Karthik, 2026-10-05: "build Pool LAB - lets start 10k pool WITH
this 10x splits. and another table build 50k pool - 50$ on 500$ each with 10
user wallets backtest, keep the trade price real way, start the timer too").

Two books, each shown twice — a BACKTEST from 1 Oct 00:00 Dubai and a LIVE
record from the lab's own start (`START`, the timer):

* $10k+ pools, the quiet rule, every size on ten times its balance. Live from
  its own paper arm (`TEN_K_BOOK`). The backtest has no arm to read before
  `START`, so it REPLAYS every graduation from the post-graduation samples,
  exactly as `scripts/seed_karthik_bands.py` does, with one extra guard: the
  exit reading must be confirmed by the next one (within `CONFIRM`). Tiny
  pools print single readings 5-7x off; an exit nobody could repeat is not a
  price.
* $50k+ pools, ten user wallets at $50 on $500 each, on the real-time
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

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

#: The timer: the live columns count from here.
START = datetime(2026, 10, 5, 17, 0, tzinfo=UTC)
#: The backtests count from 1 Oct, 00:00 Dubai.
FROM = datetime(2026, 9, 30, 20, 0, tzinfo=UTC)
TEN_K_BOOK = "POOL_10K_QUIET_5M"
SIZES = (10, 20, 25, 50, 100, 200)
WALLETS = 10
WALLET_TICKET = 50.0
WALLET_START = 500.0
#: The real wallets' per-coin cap across user wallets (REAL_WALLET_MAX_COIN_USD).
COIN_CAP = 250.0
#: An exit reading must sit within this fraction of the next reading.
CONFIRM = 0.30
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


def confirmed_exit(
    rows: list[Any], at: datetime, entry_price: Decimal, entry_depth: Decimal
) -> Any | None:
    """The first sample at or after `at` that the pool's depth can support
    (the seed script's guard) AND the next reading confirms."""
    later = [r for r in rows if r.ts >= at]
    for i, r in enumerate(later):
        price = Decimal(r.price_native)
        if price > entry_price * (Decimal(r.liquidity_usd) / entry_depth) ** 2 * Decimal(
            "1.5"
        ):
            continue
        nxt = later[i + 1] if i + 1 < len(later) else None
        if nxt is None:
            return None
        ratio = float(Decimal(nxt.price_native) / price) if price else 0.0
        if abs(ratio - 1) <= CONFIRM:
            return r
    return None


def group_samples(rows: Any) -> dict[str, list[Any]]:
    by: dict[str, list[Any]] = defaultdict(list)
    for r in rows:
        by[r.mint].append(r)
    return by


def replay(
    samples: list[Any], hold: timedelta
) -> tuple[Any, Decimal, Decimal, datetime] | None:
    """One coin as the quiet rule would have bought it, rebuilt from its
    samples: `seed_karthik_bands.replay` with the confirmed exit."""
    from app.labs.graduation import config
    from app.labs.graduation.backtest import amm_buy, amm_impact
    from app.labs.graduation.models import GradPaperPosition
    from app.labs.graduation.paper import _rate, costs
    from app.labs.graduation.tournament import graduation_pool

    notional = config.PAPER_NOTIONAL_USD
    pool = graduation_pool(samples[0].mint)
    rows = [
        r
        for r in samples
        if r.pair_address == pool
        and r.price_native
        and r.price_native > 0
        and r.liquidity_usd
        and r.price_usd
    ]
    if not rows:
        return None
    e = rows[0]
    depth, price = Decimal(e.liquidity_usd), Decimal(e.price_native)
    if e.txs >= config.QUIET_MAX_POOL_TXS:
        return None
    impact = amm_impact(notional, depth)
    rate = _rate(Decimal(e.price_usd), price)
    if impact is None or impact > config.PAPER_MAX_IMPACT or rate is None:
        return None
    quote_amount = (notional / rate).quantize(Decimal("0.000000001"))
    fee_bps = config.pool_fee_bps(price)
    fill = amm_buy(
        price,
        order_usd=notional,
        liquidity_usd=depth,
        fee_fraction=costs(quote_amount, pool_fee_bps=fee_bps).fee_fraction,
    )
    if fill is None or fill <= 0:
        return None
    x = confirmed_exit(rows, e.ts + hold, price, depth)
    if x is None:
        return None
    position = GradPaperPosition(
        mint=e.mint,
        symbol=(e.symbol or None),
        opened_at=e.ts,
        open_quote=price,
        open_fill=fill,
        notional_usd=notional,
        sol_usd_at_open=rate,
        notional_quote=quote_amount,
        tokens=(quote_amount / fill),
        peak_quote=price,
        last_quote=Decimal(x.price_native),
        liq_open_usd=depth,
        impact_open=impact,
        pool_fee_bps=fee_bps,
        graduated_at=e.grad,
        marked_at=x.ts,
    )
    return position, Decimal(x.price_native), Decimal(x.liquidity_usd), x.ts
