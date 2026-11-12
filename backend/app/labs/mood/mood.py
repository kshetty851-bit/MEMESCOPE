"""Mood Lab (Karthik, 2026-11-12: "start the backtest with wateva free, build separate lab").

Reads the crowd on 25 big meme-coin futures (Binance USD-M, free data) and paper
trades two mood rules, each beside a random-entry control. Paper only: nothing
here can reach a wallet.

The rules are the ones pre-registered and backtested on 12 Nov 2026 (Nov 2024 -
Nov 2026, picked on 2024-25, tested on 2026), unchanged:

* Shadow (PASSED, +0.55%/trade on 789 unseen 2026 trades): top traders' position
  long/short ratio vs retail's account ratio, each as a percentile of the coin's
  own last 90 days. Gap >= 0.5 -> LONG, <= -0.5 -> SHORT. Held 3 days.
* Contra (watch only, ~0 in 2026): funding pct >= 0.9 and retail long/short pct
  >= 0.8 -> SHORT. Held 1 day.

A day's signal is computed once Binance publishes that UTC day's positioning file
(the next morning); the trade opens at the futures mark price THEN, not at the
day's close as the backtest did, and closes at the first mark price after the
hold. Costs: 0.20% round trip plus the real funding paid or received.
"""

from __future__ import annotations

import bisect
import csv
import hashlib
import io
import json
import random
import zipfile
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

ENABLED = True                     # the lab's on/off switch: False opens nothing
KEY = "mood:v1"
METRICS = "mood:metrics:v1"        # hash: "SYM:YYYY-MM-DD" -> daily averages (or "none")
START_DAY = "2026-11-12"           # first signal day traded (UTC)
CAPITAL, TICKET, COST = 1000.0, 50.0, 0.002
HISTORY_DAYS = 100
FILES_PER_RUN = 300
FAPI = "https://fapi.binance.com"
VISION = "https://data.binance.vision/data/futures/um/daily/metrics"
FNG = "https://api.alternative.me/fng/?limit=120&format=json"
COINS = ("DOGEUSDT", "1000SHIBUSDT", "PEOPLEUSDT", "1000PEPEUSDT", "1000FLOKIUSDT", "MEMEUSDT",
         "1000BONKUSDT", "WIFUSDT", "BOMEUSDT", "TURBOUSDT", "MEWUSDT", "BRETTUSDT", "POPCATUSDT",
         "DOGSUSDT", "NEIROUSDT", "GOATUSDT", "MOODENGUSDT", "1000000MOGUSDT", "ACTUSDT", "PNUTUSDT",
         "1000CHEEMSUSDT", "SPXUSDT", "PENGUUSDT", "FARTCOINUSDT", "TRUMPUSDT")
BOOKS = {"shadow": 3, "contra": 1}          # book -> hold in days
CONTROL = {"ref_shadow": "shadow", "ref_contra": "contra"}

#: The 12 Nov 2026 backtest, as run (scratchpad mood/bt.py). Shown, never recomputed.
BACKTEST = [
    {"name": "Shadow", "hold": 3, "select": "+1.09%", "test": "+0.55%", "test_trades": 789, "test_usd": 216, "verdict": "pass"},
    {"name": "Shadow", "hold": 7, "select": "+1.83%", "test": "+0.37%", "test_trades": 499, "test_usd": 91, "verdict": "pass"},
    {"name": "Contra", "hold": 1, "select": "+2.44%", "test": "+0.06%", "test_trades": 175, "test_usd": 5, "verdict": "about zero"},
    {"name": "Contra", "hold": 3, "select": "+2.98%", "test": "-0.85%", "test_trades": 135, "test_usd": -57, "verdict": "fail"},
    {"name": "Phoenix", "hold": 1, "select": "+4.34%", "test": "-0.58%", "test_trades": 31, "test_usd": -9, "verdict": "fail"},
    {"name": "Spring", "hold": 3, "select": "+3.51%", "test": "-1.54%", "test_trades": 170, "test_usd": -131, "verdict": "fail"},
    {"name": "Spring", "hold": 7, "select": "+5.70%", "test": "-0.77%", "test_trades": 152, "test_usd": -59, "verdict": "fail"},
]


def pct(hist: list[float], v: float | None) -> float | None:
    """Where `v` sits in the coin's own past (0..1); None with under 60 days."""
    if v is None or len(hist) < 60:
        return None
    s = sorted(hist)
    return bisect.bisect_left(s, v) / len(s)


def reading(days: list[dict], i: int) -> dict[str, float | None]:
    """Percentiles for day i from the 90 days before it (nothing from after)."""
    t, past = days[i], days[max(0, i - 90):i]
    col = lambda k: [x[k] for x in past if x.get(k) is not None]
    return {"fund": pct(col("fund"), t.get("fund")), "retail": pct(col("ret_ls"), t.get("ret_ls")),
            "top": pct(col("top"), t.get("top"))}


def signal(book: str, r: dict[str, float | None]) -> int:
    """+1 long, -1 short, 0 nothing. Exactly the backtested thresholds."""
    if book == "shadow" and r["top"] is not None and r["retail"] is not None:
        gap = r["top"] - r["retail"]
        return 1 if gap >= .5 else -1 if gap <= -.5 else 0
    if book == "contra" and r["fund"] is not None and r["retail"] is not None:
        return -1 if r["fund"] >= .9 and r["retail"] >= .8 else 0
    return 0


def net(side: int, entry: float, exit_: float, funding: float) -> float:
    """Return on the stake: price move for the side, less costs, less funding paid."""
    return side * (exit_ / entry - 1) - COST - side * funding


def mood_score(r: dict[str, float | None]) -> int | None:
    """-100 (panic) .. +100 (greed): funding and retail positioning vs their own past."""
    if r["fund"] is None or r["retail"] is None:
        return None
    return round(100 * (r["fund"] + r["retail"] - 1))


async def _json(c: httpx.AsyncClient, url: str) -> Any:
    r = await c.get(url, timeout=20)
    r.raise_for_status()
    return r.json()


async def _metrics(c: httpx.AsyncClient, sym: str, d: str) -> dict | None | str:
    """Daily averages from Binance's archive; None = not published yet; 'none' = never."""
    r = await c.get(f"{VISION}/{sym}/{sym}-metrics-{d}.zip", timeout=20)
    if r.status_code == 404:
        return "none" if date.fromisoformat(d) < date.today() - timedelta(days=3) else None
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    rows = list(csv.DictReader(io.StringIO(z.read(z.namelist()[0]).decode())))

    def avg(k: str) -> float | None:
        v = [float(x[k]) for x in rows if x.get(k) not in (None, "")]
        return sum(v) / len(v) if v else None
    return {"oi": avg("sum_open_interest_value"), "top": avg("sum_toptrader_long_short_ratio"),
            "ret_ls": avg("count_long_short_ratio")}


def _day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).date().isoformat()


async def refresh(redis: Any, now: datetime | None = None) -> dict[str, Any]:
    """Every 10 minutes: fill data, open the new days' trades, close the due ones."""
    now = now or datetime.now(UTC)
    state = json.loads(await redis.get(KEY) or "{}")
    state.setdefault("positions", [])
    state.setdefault("processed", {})                # sym -> last signal day handled
    state.setdefault("skipped_cash", {})
    days: dict[str, list[dict]] = {}
    marks: dict[str, float] = {}
    funding: dict[str, list[tuple[int, float]]] = {}
    fetched = 0
    async with httpx.AsyncClient(headers={"User-Agent": "memescope-mood-lab"}) as c:
        for p in await _json(c, f"{FAPI}/fapi/v1/premiumIndex"):
            if p["symbol"] in COINS:
                marks[p["symbol"]] = float(p["markPrice"])
        try:
            state["fng"] = [{"d": _day(int(x["timestamp"]) * 1000), "v": int(x["value"]),
                             "label": x["value_classification"]} for x in (await _json(c, FNG))["data"][:30]]
        except Exception:
            pass
        for sym in COINS:
            k = await _json(c, f"{FAPI}/fapi/v1/klines?symbol={sym}&interval=1d&limit={HISTORY_DAYS + 30}")
            f = await _json(c, f"{FAPI}/fapi/v1/fundingRate?symbol={sym}&limit=1000")
            funding[sym] = [(x["fundingTime"], float(x["fundingRate"])) for x in f]
            fund_day: dict[str, float] = {}
            for t, v in funding[sym]:
                fund_day[_day(t)] = fund_day.get(_day(t), 0.0) + v
            rows = []
            for x in k:
                if x[6] >= now.timestamp() * 1000:       # the day is not over
                    continue
                d = _day(x[0])
                rows.append({"d": d, "c": float(x[4]), "fund": fund_day.get(d)})
            for r in rows:
                key = f"{sym}:{r['d']}"
                m = await redis.hget(METRICS, key)
                if m is None and fetched < FILES_PER_RUN:
                    got = await _metrics(c, sym, r["d"])
                    fetched += 1
                    if got is not None:
                        m = json.dumps(got)
                        await redis.hset(METRICS, key, m)
                if m and m != '"none"':
                    r.update(json.loads(m))
                r["ready"] = m is not None
            days[sym] = rows
    if not ENABLED:
        return {"enabled": False, "fetched": fetched}

    opened = closed = 0
    pos = state["positions"]
    # close what is due, at the first mark after the hold
    for p in pos:
        if p.get("closed_at") or p["sym"] not in marks:
            continue
        if now >= datetime.fromisoformat(p["due_at"]):
            t0 = datetime.fromisoformat(p["opened_at"]).timestamp() * 1000
            fsum = sum(v for t, v in funding.get(p["sym"], []) if t0 < t <= now.timestamp() * 1000)
            p.update(closed_at=now.isoformat(), exit=marks[p["sym"]], funding=fsum,
                     ret=net(p["side"], p["entry"], marks[p["sym"]], fsum))
            p["pnl_usd"] = TICKET * p["ret"]
            closed += 1

    def cash(book: str) -> float:
        b = [p for p in pos if p["book"] == book]
        return CAPITAL + sum(p.get("pnl_usd", 0) for p in b if p.get("closed_at")) \
            - TICKET * sum(1 for p in b if not p.get("closed_at"))

    def open_(book: str, sym: str, side: int, d: str, extra: dict | None = None) -> bool:
        if sym not in marks:
            return False
        if cash(book) < TICKET:
            state["skipped_cash"][book] = state["skipped_cash"].get(book, 0) + 1
            return False
        hold = BOOKS[CONTROL.get(book, book)]
        pos.append({"book": book, "sym": sym, "side": side, "day": d, "opened_at": now.isoformat(),
                    "due_at": (now + timedelta(days=hold)).isoformat(), "entry": marks[sym], **(extra or {})})
        return True

    busy = {(p["book"], p["sym"]) for p in pos if not p.get("closed_at")}
    for sym, rows in days.items():
        for i, r in enumerate(rows):
            if not r["ready"]:
                break                       # history still filling (or not published): wait
            if r["d"] < START_DAY or r["d"] <= state["processed"].get(sym, ""):
                continue
            rd = reading(rows, i)
            for book in BOOKS:
                side = signal(book, rd)
                if not side or (book, sym) in busy:
                    continue
                if open_(book, sym, side, r["d"], {k: (round(v, 3) if v is not None else None) for k, v in rd.items()}):
                    opened += 1
                    busy.add((book, sym))
                    # Ref: the same side and hold on a coin drawn at random
                    rng = random.Random(int(hashlib.sha256(f"{book}{sym}{r['d']}".encode()).hexdigest()[:12], 16))
                    open_("ref_" + book, rng.choice([s for s in COINS if s in marks]), side, r["d"])
            state["processed"][sym] = r["d"]

    pulse = []
    for sym, rows in days.items():
        ready = [i for i, r in enumerate(rows) if r["ready"] and r.get("ret_ls") is not None]
        if not ready:
            continue
        i = ready[-1]
        rd = reading(rows, i)
        pulse.append({"sym": sym, "day": rows[i]["d"], "mood": mood_score(rd),
                      "gap": None if rd["top"] is None or rd["retail"] is None else round(rd["top"] - rd["retail"], 2),
                      "shadow": signal("shadow", rd), "contra": signal("contra", rd),
                      "price": marks.get(sym), "history_days": i})
    state.update(pulse=pulse, updated_at=now.isoformat(), marks=marks)
    await redis.set(KEY, json.dumps(state))
    return {"fetched": fetched, "opened": opened, "closed": closed, "open": sum(1 for p in pos if not p.get("closed_at"))}


def board(state: dict[str, Any]) -> dict[str, Any]:
    """The page: each book against its control, open and closed trades, Pulse, the backtest."""
    pos = state.get("positions", [])
    marks = state.get("marks", {})
    books = {}
    for book in list(BOOKS) + list(CONTROL):
        b = [p for p in pos if p["book"] == book]
        done = [p for p in b if p.get("closed_at")]
        live = [p for p in b if not p.get("closed_at")]
        unreal = sum(TICKET * net(p["side"], p["entry"], marks.get(p["sym"], p["entry"]), 0) for p in live)
        books[book] = {"trades": len(done), "open": len(live), "wins": sum(p["ret"] > 0 for p in done),
                       "pnl_usd": round(sum(p["pnl_usd"] for p in done), 2), "open_pnl_usd": round(unreal, 2),
                       "balance_usd": round(CAPITAL + sum(p["pnl_usd"] for p in done), 2),
                       "skipped_cash": state.get("skipped_cash", {}).get(book, 0)}
    show = lambda p: {**{k: p.get(k) for k in ("book", "sym", "side", "day", "opened_at", "due_at", "closed_at",
                                                 "entry", "exit", "funding", "top", "retail", "fund")},
                      "ret": p.get("ret"), "pnl_usd": p.get("pnl_usd"),
                      "now": marks.get(p["sym"]) if not p.get("closed_at") else None}
    real = [p for p in pos if p["book"] in BOOKS]
    return {"enabled": ENABLED, "start_day": START_DAY, "capital_usd": CAPITAL, "ticket_usd": TICKET,
            "holds": BOOKS, "updated_at": state.get("updated_at"), "books": books,
            "open": [show(p) for p in real if not p.get("closed_at")],
            "closed": [show(p) for p in sorted((p for p in real if p.get("closed_at")),
                                               key=lambda p: p["closed_at"], reverse=True)[:100]],
            "pulse": sorted(state.get("pulse", []), key=lambda x: -(x["mood"] or 0)),
            "fng": state.get("fng", [])[:14], "backtest": BACKTEST}
