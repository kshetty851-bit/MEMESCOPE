"""The study: the hypotheses in README.md, run once against the harvested tapes.

Every trade is priced the way the chain would have filled it: the pool's own
vaults plus its virtual quote at the entry second and at the exit second, the
pool's own fee tier read off its swaps, Jupiter's router fee and the network
fee on both legs. No DexScreener anywhere — its stale first print is what made
the BASE book's +$187 paper profit (on-chain: -$3).

Everything a filter reads is knowable at the entry second: the tape stops
there, and an operator's reputation counts only rugs that had already
happened. Thresholds for the exploratory features are chosen on the TRAIN days
and applied once to the TEST days.
"""

from __future__ import annotations

import random
import sqlite3
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.labs.graduation.config import PUMPSWAP_FEE_TIERS
from app.labs.tape.chain import ENTRY_LAGS, HOLDS, PUMPFUN
from app.services.curve.pda import bonding_curve_address

SUPPLY = 10**15                 # every pump.fun coin: 1B tokens, 6 decimals
SIZE = 2 * 10**8                # 0.2 SOL (~$20): the live wallet's ticket
ROUTER_BPS = 10                 # Jupiter's platform fee, each leg
NETWORK = 10_000                # lamports a leg: base + priority fee (real wallet: ~7-8k)
#: Vault SOL at the entry second. At ~$100 SOL (Aug-Sep 2026) these are the
#: live books' floors: BASE_75k ($75k of depth) and B3_198k.
FLOORS = {"BASE": 375 * 10**9, "B3": 990 * 10**9}
BAND = (580 * 10**9, 990 * 10**9)   # $116k-$198k: the "liquidity band" (F51)
RUG = -0.5                      # a trade that lost half is a rug
BIG = SUPPLY // 100             # 1% of supply: an operator's bag, not a bot's
BUNDLE_MIN = SUPPLY // 200      # 0.5%: bundle bags ran ~1.2% each
DUST = 10**7                    # 0.01 SOL: smaller buys are volume bots
REPUTATION_WINDOW = 3 * 3600    # the live block's window
LABEL = (15, 300)               # a coin's own rug label: bought at 15s, held 5 min
BASE_ARM = (15, "BASE", 240)    # lag, floor, hold of every filter test
GATE_MIN_N = 150
SEED = 20260918
DRAWS = 2000


@dataclass
class Coin:
    mint: str
    pool: str
    t0: int
    vq: int
    creator: str | None
    migrator: str
    pts: dict[int, tuple[int, int, int | None]]
    feats: dict[int, dict[str, Any]] = field(default_factory=dict)
    #: (first move time or None, capped) per watched wallet; None = not watched
    moves: list[tuple[int | None, int]] | None = None

    @property
    def day(self) -> str:
        return datetime.fromtimestamp(self.t0, UTC).date().isoformat()

    def state(self, at: int) -> tuple[int, int, int | None] | None:
        s = self.pts.get(at)
        return s if s and s[0] else None


# --- fills --------------------------------------------------------------------

def buy_tokens(base: int, quote: int, vq: int, fee_bps: int, spend: int) -> float:
    """Tokens `spend` lamports buy: network fee and router fee off the top,
    the pool's fee charged on top of its quote, constant product over
    (vault quote + virtual quote, vault base)."""
    q = (spend - NETWORK) * (10_000 - ROUTER_BPS) / 10_000
    q_in = q * 10_000 / (10_000 + fee_bps)
    return base * q_in / (quote + vq + q_in)


def sell_lamports(base: int, quote: int, vq: int, fee_bps: int, tokens: float) -> float:
    """Lamports selling `tokens` returns. The virtual quote prices the swap but
    pays no one: a drained pool pays at most what its vault holds."""
    out = min((quote + vq) * tokens / (base + tokens), quote)
    return out * (10_000 - fee_bps) / 10_000 * (10_000 - ROUTER_BPS) / 10_000 - NETWORK


def fee_bps(state: tuple[int, int, int | None], vq: int) -> int:
    """PumpSwap's fee tier at this market cap (SOL): 125 bps on a small coin
    down to 30 on a big one. The graduation lab's table, read off pump.fun's
    fee config account; the harvested swaps paid the same tiers."""
    mcap = price(state, vq) * SUPPLY / 10**9
    return next(bps for floor, bps in reversed(PUMPSWAP_FEE_TIERS) if mcap >= floor)


def trade(c: Coin, lag: int, hold: int, size: int = SIZE) -> float | None:
    """Net return of buying `size` at t0+lag and selling at t0+lag+hold."""
    e, x = c.state(c.t0 + lag), c.state(c.t0 + lag + hold)
    if e is None or x is None:
        return None
    tokens = buy_tokens(e[0], e[1], c.vq, fee_bps(e, c.vq), size)
    return sell_lamports(x[0], x[1], c.vq, fee_bps(x, c.vq), tokens) / size - 1


def watched(c: Coin, reaction: int = 2, lag: int = 15, hold: int = 240) -> float | None:
    """H12: the base trade, sold `reaction` seconds after the first time an
    operator wallet (>= 1% at entry) let go of >= 1% of its bag — if that came
    before the planned exit. An unwatched coin has no answer. A watch that ran
    out of pages saw no move, so the coin keeps the base exit (the
    conservative reading: it can only shrink H12's advantage)."""
    if c.moves is None:
        return None
    due = c.t0 + lag + hold
    first = min((t for t, _ in c.moves if t is not None and t + reaction < due),
                default=None)
    if first is None:
        return trade(c, lag, hold)
    e, x = c.state(c.t0 + lag), c.state(first + reaction)
    if e is None or x is None:
        return None
    tokens = buy_tokens(e[0], e[1], c.vq, fee_bps(e, c.vq), SIZE)
    return sell_lamports(x[0], x[1], c.vq, fee_bps(x, c.vq), tokens) / SIZE - 1


def operator_watch(coins: list[Coin]) -> dict[str, Any]:
    """H12 against the base trade on the SAME coins (paired)."""
    lag, floor, hold = BASE_ARM
    rows = [(c, trade(c, lag, hold), watched(c, 2), watched(c, 5))
            for c in members(coins, lag, floor) if c.moves is not None]
    rows = [r for r in rows if None not in r[1:]]
    out: dict[str, Any] = {
        "coins": len(rows),
        "triggered": sum(1 for c, *_ in rows if any(
            t is not None and t + 2 < c.t0 + lag + hold for t, _ in c.moves or ())),
        "capped_watches": sum(sum(cap for _, cap in c.moves) for c, *_ in rows),
        "base": summary([(c.day, c.mint, b) for c, b, _, _ in rows]),
        "watch_2s": summary([(c.day, c.mint, w) for c, _, w, _ in rows]),
        "watch_5s": summary([(c.day, c.mint, w) for c, _, _, w in rows]),
    }
    diffs = [w - b for _, b, w, _ in rows]
    if len(diffs) > 2 and (sd := statistics.stdev(diffs)):
        out["paired_gain_pct"] = round(100 * statistics.fmean(diffs), 3)
        out["paired_t"] = round(statistics.fmean(diffs) / (sd / len(diffs) ** 0.5), 2)
    r = out["watch_2s"]
    if r.get("n", 0) >= GATE_MIN_N:
        won, days = (int(x) for x in r["days_positive"].split("/"))
        out["passes_gate"] = bool(
            r["mean_pct"] > 0 and r["usd_minus_best_trade"] > 0 and r["usd_minus_best_day"] > 0
            and won >= 0.6 * days and out.get("paired_t", 0) > 3)
    else:
        out["passes_gate"] = False
    return out


def price(state: tuple[int, int, int | None], vq: int) -> float:
    return (state[1] + vq) / state[0]


def raw_move(c: Coin, lag: int, hold: int) -> float | None:
    e, x = c.state(c.t0 + lag), c.state(c.t0 + lag + hold)
    return None if e is None or x is None else price(x, c.vq) / price(e, c.vq) - 1


# --- loading and features -----------------------------------------------------

def load(db: sqlite3.Connection) -> list[Coin]:
    pts: dict[str, dict[int, tuple[int, int, int | None]]] = defaultdict(dict)
    for mint, at, base, quote, fee in db.execute(
            "SELECT mint, at, res_base, res_quote, fee_bps FROM points"):
        pts[mint][at] = (base, quote, fee)
    coins = [Coin(m, p, t0, vq or 0, cr, mg, pts[m]) for m, p, t0, vq, cr, mg in db.execute(
        "SELECT mint, pool, t0, vq, creator, migrator FROM grads "
        "WHERE points='ok' AND tape='ok' AND funders='ok' ORDER BY t0")]
    funders = dict(db.execute("SELECT wallet, funder FROM funders WHERE funder IS NOT NULL"))
    moves: dict[str, list[tuple[int | None, int]]] = defaultdict(list)
    for mint, t, capped in db.execute("SELECT mint, t, capped FROM moves"):
        moves[mint].append((t, capped))
    for c in coins:
        c.feats = tape_features(db, c, funders)
        c.moves = moves.get(c.mint)
    return coins


def _bundle(bags: list[int]) -> int:
    """Size of the biggest group of near-identical bags (within 2%)."""
    best = 0
    for a in bags:
        best = max(best, sum(1 for b in bags if abs(b - a) <= 0.02 * a))
    return best if best >= 2 else 0


def tape_features(db: sqlite3.Connection, c: Coin, funders: dict[str, str]
                  ) -> dict[int, dict[str, Any]]:
    """What the tape says at each entry second. Nothing after it is read."""
    trades = db.execute(
        "SELECT t, venue, side, user, quote FROM trades WHERE mint=? ORDER BY slot, idx, ev",
        (c.mint,)).fetchall()
    bals = db.execute("SELECT t, owner, amount FROM balances WHERE mint=? ORDER BY slot, idx",
                      (c.mint,)).fetchall()
    skip = {c.pool, bonding_curve_address(c.mint, program_id=PUMPFUN)}
    curve_ts = [t for t, venue, *_ in trades if venue == "curve"]
    curve_buyers = {u for t, venue, side, u, _ in trades if venue == "curve" and side == "buy"}
    out: dict[int, dict[str, Any]] = {}
    for lag in ENTRY_LAGS:
        te = c.t0 + lag
        entry = c.state(te)
        if entry is None:
            continue
        # peak: the most a wallet held from the pool's opening on, counting
        # the bag it carried in. `moved` is how much of that it had let go.
        latest: dict[str, int] = {}
        peak: dict[str, int] = {}
        for t, owner, amount in bals:
            if t > te:
                break
            if t >= c.t0:
                peak[owner] = max(peak.get(owner, latest.get(owner, 0)), amount)
            latest[owner] = amount
        holders = sorted((a for o, a in latest.items() if a > 0 and o not in skip),
                         reverse=True)
        ops = {o for o in latest.keys() | peak.keys()
               if max(peak.get(o, 0), latest.get(o, 0)) >= BIG and o not in skip}
        moved = max((1 - latest.get(o, 0) / peak[o] for o in ops if peak.get(o)), default=0.0)
        flows = [(side, u, q) for t, venue, side, u, q in trades
                 if venue == "pool" and c.t0 <= t <= te and u and u not in ops
                 and (q or 0) >= DUST]
        ids = ops | ({c.creator} if c.creator else set())
        ids |= {funders[w] for w in ids if w in funders}
        out[lag] = {
            "quote": entry[1],
            "fee_bps": fee_bps(entry, c.vq),
            "top1": holders[0] / SUPPLY if holders else 0.0,
            "gun": holders[0] / entry[0] if holders else 0.0,
            "bundle": _bundle([a for a in holders if a >= BUNDLE_MIN]),
            "ops_moved": moved,
            "buyers": len({u for s, u, _ in flows if s == "buy"}),
            "buy_sol": sum(q for s, _, q in flows if s == "buy") / 1e9,
            "sellers": len({u for s, u, _ in flows if s == "sell"}),
            "sell_sol": sum(q for s, _, q in flows if s == "sell") / 1e9,
            "curve_buyers": len(curve_buyers),
            "curve_secs": c.t0 - min(curve_ts) if curve_ts else 0,
            "self_migrated": c.migrator in ops or c.migrator == c.creator,
            "hour": datetime.fromtimestamp(te, UTC).hour,
            "ids": ids,
        }
    return out


def reputation(coins: list[Coin]) -> None:
    """Add each coin's point-in-time operator record to its features.

    A coin's operator is its big wallets, its creator, and whoever funded
    them. Another coin counts against it only once that coin's own label was
    known — five minutes after its 15s entry — and before this coin's entry."""
    lag0, hold0 = LABEL
    labels = []
    for c in coins:
        move = raw_move(c, lag0, hold0)
        if move is not None and lag0 in c.feats:
            labels.append((c.t0 + lag0 + hold0, c.mint, move <= RUG, c.feats[lag0]["ids"]))
    by_id: dict[str, list[tuple[int, str, bool]]] = defaultdict(list)
    for known, mint, rugged, ids in labels:
        for i in ids:
            by_id[i].append((known, mint, rugged))
    for c in coins:
        for lag, f in c.feats.items():
            te = c.t0 + lag
            prior = {mint: (known, rugged)
                     for i in f["ids"] for known, mint, rugged in by_id[i]
                     if known <= te and mint != c.mint}
            f["rep_n"] = len(prior)
            f["rep_rugs"] = sum(1 for _, r in prior.values() if r)
            f["rep_recent_rug"] = any(r and known >= te - REPUTATION_WINDOW
                                      for known, r in prior.values())


# --- evaluation ---------------------------------------------------------------

@dataclass(frozen=True)
class Arm:
    name: str
    lag: int
    floor: str
    hold: int
    keep: Callable[[dict[str, Any]], bool] | None = None
    note: str = ""


def members(coins: Iterable[Coin], lag: int, floor: str) -> list[Coin]:
    lo = FLOORS[floor]
    return [c for c in coins if lag in c.feats and c.feats[lag]["quote"] >= lo]


def summary(rows: list[tuple[str, str, float]]) -> dict[str, Any]:
    """rows = (day, mint, net return). Money is at the live $20 ticket."""
    if not rows:
        return {"n": 0}
    rets = [r for _, _, r in rows]
    by_day: dict[str, float] = defaultdict(float)
    for d, _, r in rows:
        by_day[d] += 20 * r
    best_day = max(by_day, key=lambda d: by_day[d])
    usd = 20 * sum(rets)
    return {
        "n": len(rets),
        "mean_pct": round(100 * statistics.fmean(rets), 3),
        "median_pct": round(100 * statistics.median(rets), 3),
        "win_pct": round(100 * sum(r > 0 for r in rets) / len(rets), 1),
        "rug_pct": round(100 * sum(r <= RUG for r in rets) / len(rets), 2),
        "usd_at_20": round(usd, 2),
        "usd_minus_best_trade": round(usd - 20 * max(rets), 2),
        "usd_minus_best_day": round(usd - by_day[best_day], 2),
        "days_positive": f"{sum(v > 0 for v in by_day.values())}/{len(by_day)}",
    }


def control_p(kept: list[float], pool: list[float], seed: int = SEED) -> float:
    """Share of random subsets of the arm's own population, the same size as
    what the filter kept, whose mean is at least the filter's. A filter that
    only sheds trades at random scores ~0.5; one that picks winners, ~0."""
    if not kept or len(kept) >= len(pool):
        return 1.0
    rng = random.Random(seed)  # noqa: S311 - a reproducible control, not a secret
    target = statistics.fmean(kept)
    hits = sum(statistics.fmean(rng.sample(pool, len(kept))) >= target for _ in range(DRAWS))
    return round((hits + 1) / (DRAWS + 1), 4)


def priced(arm: Arm, coins: list[Coin]) -> list[tuple[Coin, float]]:
    pop = [(c, trade(c, arm.lag, arm.hold)) for c in members(coins, arm.lag, arm.floor)]
    return [(c, r) for c, r in pop if r is not None]


def run_arm(arm: Arm, coins: list[Coin], *, control: bool = True) -> dict[str, Any]:
    pop = priced(arm, coins)
    kept = [(c, r) for c, r in pop if arm.keep is None or arm.keep(c.feats[arm.lag])]
    out = summary([(c.day, c.mint, r) for c, r in kept])
    moves = [m for c, _ in kept if (m := raw_move(c, arm.lag, arm.hold)) is not None]
    if moves:
        out["gross_mean_pct"] = round(100 * statistics.fmean(moves), 3)
    if arm.keep is not None and control:
        out["population_n"] = len(pop)
        out["control_p"] = control_p([r for _, r in kept], [r for _, r in pop])
        refused = [r for c, r in pop if not arm.keep(c.feats[arm.lag])]
        out["refused_mean_pct"] = (round(100 * statistics.fmean(refused), 3)
                                   if refused else None)
    return out


def gate(r: dict[str, Any], alpha: float) -> bool:
    """README's gate, on the TEST days only. Every term has to hold."""
    if r.get("n", 0) < GATE_MIN_N:
        return False
    won, days = (int(x) for x in r["days_positive"].split("/"))
    return (r["mean_pct"] > 0 and r["usd_minus_best_trade"] > 0 and r["usd_minus_best_day"] > 0
            and won >= 0.6 * days and r.get("control_p", 1.0) < alpha)


def split_days(coins: list[Coin], split: str | None) -> tuple[list[Coin], list[Coin]]:
    days = sorted({c.day for c in coins})
    first_test = split or days[int(len(days) * 0.6)]
    return ([c for c in coins if c.day < first_test],
            [c for c in coins if c.day >= first_test])


def pick_threshold(train: list[Coin], name: str, feature: str) -> Arm:
    """The one exploratory rule a feature gets: keep coins at or above (or at
    or below) a TRAIN tercile, whichever did best on TRAIN. Nothing about the
    test days is read to choose it."""
    lag, floor, hold = BASE_ARM
    values = sorted(c.feats[lag][feature] for c in members(train, lag, floor))
    if len(values) < 30:
        return Arm(name, lag, floor, hold, lambda f: True, note="too few TRAIN coins")
    cuts = sorted({values[len(values) // 3], values[2 * len(values) // 3]})
    best: tuple[float, Arm] | None = None
    for cut in cuts:
        for above in (True, False):
            keep = ((lambda f, c=cut: f[feature] >= c) if above
                    else (lambda f, c=cut: f[feature] <= c))
            arm = Arm(name, lag, floor, hold, keep,
                      note=f"{feature} {'>=' if above else '<='} {cut:g} (chosen on TRAIN)")
            kept = [r for c, r in priced(arm, train) if keep(c.feats[lag])]
            if len(kept) >= 30 and (best is None or statistics.fmean(kept) > best[0]):
                best = (statistics.fmean(kept), arm)
    return best[1] if best else Arm(name, lag, floor, hold, lambda f: True, note="no rule")


def hypotheses(train: list[Coin]) -> list[Arm]:
    lag, floor, hold = BASE_ARM
    fixed = [
        Arm("H1a reputation: no rug by the same operator in 3h", lag, floor, hold,
            lambda f: not f["rep_recent_rug"], "the live money-source block"),
        Arm("H1b reputation: operator never rugged before", lag, floor, hold,
            lambda f: f["rep_rugs"] == 0),
        Arm("H1c reputation: operator's past coins rugged < 50% (or unknown)",
            lag, floor, hold, lambda f: f["rep_n"] < 2 or f["rep_rugs"] / f["rep_n"] < 0.5),
        Arm("H1d reputation: proven operator (2+ past coins, none rugged)", lag, floor, hold,
            lambda f: f["rep_n"] >= 2 and f["rep_rugs"] == 0),
        Arm("H3 operators have not moved their bags before entry", lag, floor, hold,
            lambda f: f["ops_moved"] < 0.01),
        Arm("H5 natural graduation (curve lived > 60s)", lag, floor, hold,
            lambda f: f["curve_secs"] > 60),
        Arm("H7 no bundle of identical bags", lag, floor, hold, lambda f: f["bundle"] == 0),
        Arm("H8 pool opened 18:00-05:59 UTC", lag, floor, hold,
            lambda f: f["hour"] >= 18 or f["hour"] < 6),
        Arm("H9 depth band $116k-$198k", lag, floor, hold,
            lambda f: BAND[0] <= f["quote"] < BAND[1]),
        Arm("H10 fee tier at entry <= 50 bps", lag, floor, hold, lambda f: f["fee_bps"] <= 50),
        Arm("H11 B3 floor (>= 990 SOL, ~$198k)", lag, floor, hold,
            lambda f: f["quote"] >= FLOORS["B3"]),
    ]
    explored = [pick_threshold(train, "H4 retail buyers before entry", "buyers"),
                pick_threshold(train, "H4b retail SOL in before entry", "buy_sol"),
                pick_threshold(train, "H6 loaded gun (top bag / pool tokens)", "gun")]
    return fixed + explored


def latency(coins: list[Coin]) -> dict[str, Any]:
    """H2, the scanner's own question: the SAME coins bought at 5s, 15s and
    45s after the pool opened, each held 4 minutes. Paired by coin, so the
    only thing that differs is how fast the entry was."""
    both = [c for c in members(coins, 45, "BASE")
            if all(trade(c, lag, 240) is not None for lag in ENTRY_LAGS)]
    out: dict[str, Any] = {"coins": len(both)}
    for lag in ENTRY_LAGS:
        out[f"lag_{lag}s"] = summary([(c.day, c.mint, trade(c, lag, 240)) for c in both])  # type: ignore[misc]
    diffs = [trade(c, 15, 240) - trade(c, 45, 240) for c in both]  # type: ignore[operator]
    if len(diffs) > 2:
        m, s = statistics.fmean(diffs), statistics.stdev(diffs)
        out["15s_minus_45s_pct"] = round(100 * m, 3)
        out["t"] = round(m / (s / len(diffs) ** 0.5), 2) if s else None
    return out


def export_operators(db: sqlite3.Connection, out: str) -> dict[str, int]:
    """Every harvested coin's operator and rug label, in the form the
    graduation lab's `seed-operators` loads: its fast arm E75T_4m trusts only
    operators with a clean record, and this is the record up to the harvest.
    Same definitions as `reputation`: bought at 15s, rug = -50% at 5 min."""
    import csv

    coins = load(db)
    lag, hold = LABEL
    n = 0
    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["mint", "pool", "migrated_at", "entry_at", "price_native", "depth_usd",
                    "ids", "rugged", "labelled_at"])
        for c in coins:
            e = c.state(c.t0 + lag)
            if e is None or lag not in c.feats:
                continue
            move = raw_move(c, lag, hold)
            w.writerow([c.mint, c.pool, c.t0, c.t0 + lag,
                        f"{price(e, c.vq) / 1000:.18f}",  # SOL per whole token
                        "", " ".join(sorted(c.feats[lag]["ids"])),
                        "" if move is None else int(move <= RUG), c.t0 + lag + hold])
            n += 1
    return {"exported": n}


def run(db: sqlite3.Connection, split: str | None = None) -> dict[str, Any]:
    coins = load(db)
    reputation(coins)
    train, test = split_days(coins, split)
    grid = {f"{floor} lag{lag}s hold{hold}s": run_arm(Arm("", lag, floor, hold), coins)
            for floor in FLOORS for lag in ENTRY_LAGS for hold in HOLDS}
    arms = hypotheses(train)
    base = Arm("BASE (no filter)", *BASE_ARM)
    alpha = 0.05 / len(arms)
    tests = {}
    for arm in [base, *arms]:
        result = {"rule": arm.note, "train": run_arm(arm, train), "test": run_arm(arm, test)}
        result["passes_gate"] = gate(result["test"], alpha) if arm.keep else None
        tests[arm.name] = result
    return {
        "coins": len(coins),
        "days": [coins[0].day, coins[-1].day] if coins else None,
        "train_days": sorted({c.day for c in train}),
        "test_days": sorted({c.day for c in test}),
        "bonferroni_alpha": round(alpha, 4),
        "grid_all_days": grid,
        "latency": {"train": latency(train), "test": latency(test)},
        "operator_watch": {"train": operator_watch(train), "test": operator_watch(test)},
        "hypotheses": tests,
    }
