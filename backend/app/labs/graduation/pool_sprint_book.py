"""Pool Sprint's pure paper ledger. Quotes only; no wallet or order imports."""

from __future__ import annotations

import gzip
import heapq
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

D = Decimal
DUBAI = timezone(timedelta(hours=4))
START = datetime(2026, 9, 30, 20, tzinfo=UTC)
CAPITAL = D(1500)
TICKET = D(50)
HOLD = timedelta(minutes=5)
DEADLINE = timedelta(minutes=7)
SEED = Path(__file__).with_name("data") / "pool_sprint_oct_2026.json.gz"
WSOL_MINT = "So11111111111111111111111111111111111111112"


def money(value: Decimal) -> str:
    return str(value.quantize(D("0.01")))


@dataclass(frozen=True)
class Observation:
    mint: str
    pair: str
    opened_at: datetime
    entry_price: Decimal
    liquidity: Decimal
    symbol: str | None = None
    name: str | None = None
    exited_at: datetime | None = None
    exit_price: Decimal | None = None
    source: str | None = None
    candle_start_at: datetime | None = None
    base_mint: str | None = None
    quote_mint: str | None = None
    pair_evidence: str | None = None
    graduated_at: datetime | None = None
    entry_buys: int | None = None
    entry_sells: int | None = None

    @property
    def fresh65(self) -> bool:
        """Use the original observation only; never later activity or prices."""
        if (
            self.graduated_at is None
            or self.entry_buys is None
            or self.entry_sells is None
            or self.entry_buys < 0
            or self.entry_sells < 0
        ):
            return False
        total = self.entry_buys + self.entry_sells
        return (
            timedelta(0) <= self.opened_at - self.graduated_at <= timedelta(seconds=30)
            and total > 0
            and 100 * self.entry_buys >= 65 * total
        )

    @property
    def sol_pair(self) -> bool:
        return bool(
            self.base_mint == self.mint and self.quote_mint == WSOL_MINT and self.pair_evidence
        )

    @property
    def priced(self) -> bool:
        return bool(
            self.exited_at is not None
            and self.exit_price is not None
            and self.exit_price > 0
            and self.opened_at + HOLD <= self.exited_at <= self.opened_at + DEADLINE
        )


@lru_cache(maxsize=1)
def snapshot() -> tuple[datetime, tuple[Observation, ...]]:
    """An audited, immutable export keeps a cold API off a 7m-row history scan."""
    data = json.loads(gzip.decompress(SEED.read_bytes()))
    if data["version"] != 3:
        raise ValueError("Unsupported Pool Sprint snapshot")
    records = tuple(
        Observation(
            mint=r[0],
            pair=r[1],
            opened_at=datetime.fromisoformat(r[2]),
            entry_price=D(r[3]),
            liquidity=D(r[4]),
            symbol=r[5],
            name=r[6],
            exited_at=datetime.fromisoformat(r[7]) if r[7] else None,
            exit_price=D(r[8]) if r[8] else None,
            source=r[9],
            candle_start_at=datetime.fromisoformat(r[10]) if r[10] else None,
            base_mint=r[11],
            quote_mint=r[12],
            pair_evidence=r[13],
            graduated_at=datetime.fromisoformat(r[14]) if r[14] else None,
            entry_buys=r[15],
            entry_sells=r[16],
        )
        for r in data["records"]
    )
    if len({r.mint for r in records}) != len(records):
        raise ValueError("Duplicate mint in Pool Sprint snapshot")
    return datetime.fromisoformat(data["snapshot_at"]), records


def walk(
    observations: list[Observation] | tuple[Observation, ...],
    *,
    as_of: datetime,
    start: datetime = START,
    capital: Decimal = CAPITAL,
    ticket: Decimal = TICKET,
    cost: Decimal = D(0),
    details: bool = False,
) -> dict[str, Any]:
    """Reinvest proceeds only WHEN received; an overdue unknown reserves its stake.

    Headline balance values an overdue unpriced holding at zero, without calling
    that reserve an observed rug. Quotes that have not arrived stay open at cost.
    """
    if ticket <= 0 or capital < 0 or cost < 0:
        raise ValueError("Invalid paper account size")
    rows = sorted(
        (
            r
            for r in observations
            if start <= r.opened_at <= as_of
            and r.entry_price > 0
            and D(10000) <= r.liquidity < D(40000)
            and r.sol_pair
            and r.fresh65
        ),
        key=lambda r: (r.opened_at, r.mint),
    )
    cash = balance = low = low_cash = capital
    priced_profit = D(0)
    pending: list[tuple[datetime, str, Observation]] = []
    taken = skipped = closed = reserved = wins = rugs = max_open = 0
    dex = candles = 0
    day_data: dict[str, dict[str, Any]] = {}
    trade_rows: dict[str, dict[str, Any]] = {}
    skipped_rows: list[dict[str, Any]] = []

    def day(at: datetime) -> dict[str, Any]:
        key = at.astimezone(DUBAI).date().isoformat()
        return day_data.setdefault(
            key,
            {
                "date": key,
                "opened": 0,
                "trades": 0,
                "priced": 0,
                "unpriced": 0,
                "rugs": 0,
                "skipped": 0,
                "pnl": D(0),
            },
        )

    def settle(until: datetime) -> None:
        nonlocal cash, balance, low, closed, reserved, wins, rugs, priced_profit, dex, candles
        while pending and pending[0][0] <= until:
            at, mint, r = heapq.heappop(pending)
            priced = r.priced
            proceeds = ticket * r.exit_price / r.entry_price if priced else D(0)
            pnl = proceeds - ticket
            cash += proceeds
            balance += pnl
            low = min(low, balance)
            d = day(at)
            d["trades"] += 1
            d["pnl"] += pnl
            if priced:
                closed += 1
                priced_profit += pnl
                wins += pnl > 0
                rugs += pnl <= -ticket / 2
                d["priced"] += 1
                d["rugs"] += pnl <= -ticket / 2
                dex += r.source == "dexscreener"
                candles += r.source == "geckoterminal_candle_close"
            else:
                reserved += 1
                d["unpriced"] += 1
            if details:
                trade_rows[mint].update(
                    closed_at=at.isoformat(),
                    status="priced" if priced else "unpriced",
                    pct=str(100 * (r.exit_price / r.entry_price - 1)) if priced else None,
                    pnl_usd=str(pnl),
                    rugged=bool(priced and pnl <= -ticket / 2),
                    source=r.source if priced else None,
                    exit_price=str(r.exit_price) if priced else None,
                )

    for r in rows:
        settle(r.opened_at)
        d = day(r.opened_at)
        if cash < ticket + cost:
            skipped += 1
            d["skipped"] += 1
            if details:
                skipped_rows.append(
                    {
                        "mint": r.mint,
                        "symbol": r.symbol,
                        "opened_at": r.opened_at.isoformat(),
                        "pool_usd": str(r.liquidity),
                        "status": "cash_skipped",
                    }
                )
            continue
        cash -= ticket + cost
        balance -= cost
        low = min(low, balance)
        low_cash = min(low_cash, cash)
        taken += 1
        d["opened"] += 1
        d["pnl"] -= cost
        close_at = r.exited_at if r.priced else r.opened_at + DEADLINE
        heapq.heappush(pending, (close_at, r.mint, r))
        max_open = max(max_open, len(pending))
        if details:
            trade_rows[r.mint] = {
                "mint": r.mint,
                "symbol": r.symbol,
                "name": r.name,
                "pair": r.pair,
                "base_mint": r.base_mint,
                "quote_mint": r.quote_mint,
                "quote_symbol": "SOL",
                "pair_evidence": r.pair_evidence,
                "graduated_at": r.graduated_at.isoformat() if r.graduated_at else None,
                "entry_buys": r.entry_buys,
                "entry_sells": r.entry_sells,
                "opened_at": r.opened_at.isoformat(),
                "closed_at": None,
                "pool_usd": str(r.liquidity),
                "entry_price": str(r.entry_price),
                "exit_price": None,
                "status": "open",
                "pct": None,
                "pnl_usd": None,
                "rugged": False,
                "source": None,
            }
    settle(as_of)
    days: list[dict[str, Any]] = []
    midnight = start.astimezone(DUBAI).replace(hour=0, minute=0, second=0, microsecond=0)
    day_end_balance = capital
    while midnight <= as_of.astimezone(DUBAI):
        d = day(midnight)
        before = day_end_balance
        day_end_balance += d["pnl"]
        days.append(
            {
                **{k: v for k, v in d.items() if k != "pnl"},
                "n": len(days) + 1,
                "from": midnight.isoformat(),
                "to": (midnight + timedelta(days=1)).isoformat(),
                "running": midnight.date() == as_of.astimezone(DUBAI).date(),
                "pnl_usd": money(d["pnl"]),
                "balance_usd": money(day_end_balance),
                "pct": str(100 * d["pnl"] / before) if before else "0",
            }
        )
        midnight += timedelta(days=1)
    result: dict[str, Any] = {
        "capital_usd": money(capital),
        "ticket_usd": money(ticket),
        "cost_usd": money(cost),
        "signals": len(rows),
        "trades": taken,
        "skipped": skipped,
        "closed": closed,
        "open": len(pending),
        "unpriced": reserved,
        "wins": wins,
        "rugs": rugs,
        "balance_usd": money(balance),
        "pnl_usd": money(balance - capital),
        "priced_pnl_usd": money(priced_profit),
        "free_cash_usd": money(cash),
        "open_stake_usd": money(ticket * len(pending)),
        "pricing_reserve_usd": money(ticket * reserved),
        "trading_costs_usd": money(cost * taken),
        "lowest_usd": money(low),
        "lowest_cash_usd": money(low_cash),
        "max_concurrent": max_open,
        "dex_exits": dex,
        "candle_exits": candles,
        "days": list(reversed(days)),
    }
    if details:
        result["trades_list"] = sorted(
            trade_rows.values(),
            key=lambda r: (r["opened_at"], r["mint"]),
            reverse=True,
        )
        result["skipped_list"] = list(reversed(skipped_rows))
    return result


def report(observations: list[Observation], as_of: datetime) -> dict[str, Any]:
    base = walk(observations, as_of=as_of, details=True)
    starts = []
    at = START
    while at <= as_of:
        w = walk(observations, as_of=as_of, start=at)
        starts.append(
            {
                "start": at.isoformat(),
                "days": (as_of - at).total_seconds() / 86400,
                **{
                    key: w[key]
                    for key in [
                        "balance_usd",
                        "pnl_usd",
                        "lowest_usd",
                        "trades",
                        "rugs",
                        "skipped",
                    ]
                },
            }
        )
        at += timedelta(days=1)
    sizes = []
    for ticket in [D(10), D(25), D(50), D(75), D(100)]:
        cells = []
        for floor in [10000, 20000, 30000]:
            w = walk(
                [r for r in observations if r.liquidity >= floor], as_of=as_of, ticket=ticket
            )
            cells.append(
                {
                    key: w[key]
                    for key in [
                        "balance_usd",
                        "pnl_usd",
                        "lowest_usd",
                        "trades",
                        "rugs",
                        "skipped",
                    ]
                }
            )
        sizes.append({"ticket_usd": str(ticket), "cells": cells})
    costs = []
    for cost in [D(0), D("0.50"), D(1), D(2)]:
        w = walk(observations, as_of=as_of, cost=cost)
        costs.append(
            {
                key: w[key]
                for key in [
                    "cost_usd",
                    "balance_usd",
                    "pnl_usd",
                    "trades",
                    "skipped",
                    "rugs",
                    "lowest_usd",
                ]
            }
        )
    bands = []
    for lo, hi in [(10000, 20000), (20000, 30000), (30000, 40000)]:
        trades = [t for t in base["trades_list"] if lo <= D(t["pool_usd"]) < hi]
        bands.append(
            {
                "low": lo,
                "high": hi,
                "trades": len(trades),
                "rugs": sum(t["rugged"] for t in trades),
                "pnl_usd": money(
                    sum((D(t["pnl_usd"]) for t in trades if t["pnl_usd"] is not None), D(0))
                ),
            }
        )
    return {
        **base,
        "pool_candidates": len(observations),
        "excluded_non_sol": sum(
            bool(r.pair_evidence) and not r.sol_pair for r in observations
        ),
        "unverified_pools": sum(not r.pair_evidence for r in observations),
        "excluded_entry_rule": sum(r.sol_pair and not r.fresh65 for r in observations),
        "entry_rule": "FRESH_30S_BUYS_65PCT",
        "name": "Pool Sprint Lab",
        "book": "POOL_SPRINT_5M",
        "rule": (
            "Verified token/SOL only; $10k-$40k at first recorded liquidity; "
            "first seen within 30s of graduation; at least 65% buy transactions; "
            "$50 per trade; sell after five minutes"
        ),
        "started_at": START.isoformat(),
        "as_of": as_of.isoformat(),
        "hold_minutes": 5,
        "pools_usd": [10000, 40000],
        "start_dates": list(reversed(starts)),
        "sizes": sizes,
        "costs": costs,
        "bands": bands,
        "paper_only": True,
    }
