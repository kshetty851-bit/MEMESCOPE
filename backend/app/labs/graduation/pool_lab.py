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

import re

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
#: And more than this many buys in DexScreener's 5-minute count before the buy
#: (Karthik, 2026-10-12): the early pump has mostly happened. Chosen on 5-9 Oct
#: (+$20) and held on 10-12 Oct (+$40); one of 4 rules out of 146 that did.
MAX_BUYS_BEFORE = 39
#: Buys only this many seconds after graduation (Karthik, 2026-10-14: "apply
#: rule 1 to 10k pool since day 1"). Buys in the first ~19 s rugged 14-19% of
#: the time; after 46 s they lost a little. Chosen on 5-10 Oct (+$41) and held
#: on 11-14 Oct (+$114), better on 8 of 10 days: +$702 -> +$857, rugs 49 -> 35.
#: The edges were fitted on 10 days. Unknown graduation time is kept.
ENTRY_AGE_S = (19, 46)


def in_entry_window(position: Any) -> bool:
    """Was this coin bought inside `ENTRY_AGE_S` of its graduation?"""
    graduated = getattr(position, "graduated_at", None)
    if graduated is None:
        return True
    age = (position.opened_at - graduated).total_seconds()
    return ENTRY_AGE_S[0] <= age <= ENTRY_AGE_S[1]
#: Famous names the $10k book skips (Karthik, 2026-10-11: "skip tokens with
#: famous names, they just come to rug"; "yes build and deploy it for 10k
#: pool"). On its 555 trades 5-11 Oct the 40 famous names rugged 17.5% vs 2.1%
#: and lost -14% a trade; skipping them from day 1 took $610 -> ~$827, better on
#: every day. NOT the $50k books: there they still made +1.7% a trade. A
#: symbol is famous if it contains a word below, or IS a short one; the list
#: was written after seeing these coins, so it needs new names as they come.
FAMOUS_WORDS = (
    "openai", "deepseek", "claude", "anthropic", "gemini", "grok", "chatgpt", "gpt", "llama",
    "nvidia", "tesla", "musk", "elon", "trump", "barron", "melania", "putin", "biden", "obama",
    "kanye", "drake", "taylor", "soulja", "instagram", "tiktok", "youtube", "google", "apple",
    "microsoft", "amazon", "netflix", "facebook", "metamask", "spacex", "starlink", "twitter",
    "telegram", "disney", "nike", "pepsi", "cocacola", "mcdonald", "samsung", "nintendo", "gta",
    "fortnite", "minecraft", "roblox", "pokemon", "binance", "coinbase", "robinhood", "blackrock",
    "bitcoin", "ethereum", "solana", "doge", "shiba", "pepe", "vitalik", "saylor", "zuck", "bezos",
    "jensen", "altman", "mrbeast", "ronaldo", "messi", "lebron", "kardashian",
)
FAMOUS_EXACT = frozenset({
    "x", "ai", "meta", "agi", "btc", "eth", "sol", "bnb", "xrp", "usa", "nba", "nfl", "fifa",
    "tsla", "aapl", "nvda", "goog", "amzn", "msft", "sony", "nasa", "cia", "fbi", "pope", "cz",
})


#: AI names (Karthik, 2026-10-12: "apply skip AI names in 50-60k pools since day
#: 1"): fakes of trending AI products, a rug wave from 9 Oct in small $50k pools
#: (DeepSeek, OpenAI, Doubao AI). Lower-case substrings of the symbol.
AI_WORDS = ("ai", "gpt", "openai", "deepseek", "claude", "grok", "gemini", "anthropic",
            "llama", "豆包", "doubao", "qwen", "kimi", "mistral", "agi")


def ai_name(symbol: str | None) -> bool:
    s = (symbol or "").lower()
    return any(w in s for w in AI_WORDS)


def name_key(symbol: str | None) -> str:
    """A coin's name for matching: letters and digits, lower case, so
    "Mr Beast", "MrBeast" and "MRBEAST" are one name."""
    return re.sub(r"[^a-z0-9]", "", (symbol or "").lower())


def famous_name(symbol: str | None) -> bool:
    s = re.sub(r"[^a-z0-9]", "", (symbol or "").lower())
    return bool(s) and (s in FAMOUS_EXACT or any(w in s for w in FAMOUS_WORDS))


SIZES = (10, 20, 25, 50, 100, 200)
WALLETS = 10
WALLET_TICKET = 50.0
WALLET_START = 500.0
#: The $10k book's balance as a multiple of its ticket (Karthik, 2026-10-10:
#: "yes change to 5x in 10k pool"; 10x before). Its 3-minute trades never had
#: more than two open at once, so $250 bought every trade $500 did: same
#: dollars, double the return. 5x, not 2-3x: a -$200 day (7 Oct, before the
#: few-sellers rule) would have emptied $100-$150. Applied from day 1.
#: Back to 10x on 2026-10-11 (Karthik: "in pool lab change the table to 10x
#: instead of 5x"): same trades and dollars, half the percentage return.
TEN_K_RATIO = 10
TEN_K_START = WALLET_TICKET * TEN_K_RATIO
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
