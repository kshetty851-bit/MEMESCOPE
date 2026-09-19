"""Rafiqv2's flag, and its six books read from `books/strategy_*.json`.

The JSON files are the rules, as delivered. Everything a book does comes from
its file; the six differ only in their entry gate, score threshold, stop, hold
and scale-out. A setting this engine does not implement is refused at load
rather than silently ignored — a config that says "disabled" and runs anyway
is a second, unpublished rule.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from app.labs.rafiq.entry_gate import GateThresholds
from app.labs.rafiq.strategies.strategy_d_daily_breaker import DailyBreakerPolicy


def enabled() -> bool:
    """Read at call time: a worker that cached it would outlive a switch-off."""
    return os.getenv("RAFIQV2_LAB_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}


#: Every setting whose other values this engine has no code for.
_IMPLEMENTED = {
    ("learning", "enabled"): True,
    ("learning", "per_book_state"): True,
    ("fast_rug_gates", "enabled"): True,
    ("profit_lock", "enabled"): True,
    ("death_rate_breaker", "enabled"): True,
    ("death_rate_breaker", "clear_evidence_after_halt"): True,
    ("equity_ratchet", "enabled"): True,
    ("equity_ratchet", "floor_never_falls"): True,
    ("equity_ratchet", "on_breach"): "halt_all_new_entries",
    ("equity_ratchet", "force_close_open_positions"): False,
    ("daily_breaker", "enabled"): True,
    ("daily_breaker", "basis"): "mark_to_market_including_open_positions",
    ("sizing", "scale_with_book"): True,
    ("exits", "runner_take_profit"): None,
}


@dataclass(frozen=True)
class Book:
    code: str
    name: str
    identity: str
    starting_equity: Decimal
    gate: GateThresholds
    score_min: Decimal
    stop: Decimal
    max_hold: timedelta
    #: None for D2, which never scales out: its whole position is the runner.
    scale_out_at: Decimal | None
    scale_out_fraction: Decimal | None
    runner_trail: Decimal
    rug_ladder: tuple
    lock_ladder: tuple
    death_window: int
    death_rate: Decimal
    death_min_sample: int
    death_halt_for: timedelta
    ratchet_give_back: Decimal
    ratchet_floor: Decimal
    size_pct: Decimal
    size_min: Decimal
    size_max: Decimal
    daily: DailyBreakerPolicy
    #: The file without its `_` commentary: what is published and hashed.
    rules: dict
    #: SHA-256 of `rules`. A book row opened under another digest refuses to
    #: run, so an edited rule is a new record, never a silent restatement.
    digest: str


def _rules(node):
    if isinstance(node, dict):
        return {k: _rules(v) for k, v in node.items() if not k.startswith("_")}
    if isinstance(node, list):
        return [_rules(v) for v in node]
    return node


def _d(value) -> Decimal:
    return Decimal(str(value))


def load(path: Path) -> Book:
    raw = json.loads(path.read_text())
    for (section, key), want in _IMPLEMENTED.items():
        if raw[section][key] != want:
            raise ValueError(f"{path.name}: {section}.{key} = {raw[section][key]!r}; "
                             f"this engine implements only {want!r}")
    rules = _rules(raw)
    ex, scale = raw["exits"], raw["exits"]["scale_out"]
    death, ratchet, size = raw["death_rate_breaker"], raw["equity_ratchet"], raw["sizing"]
    return Book(
        code=raw["book"], name=raw["name"], identity=raw["_identity"],
        starting_equity=_d(raw["starting_capital_usd"]),
        gate=GateThresholds(
            min_liquidity_usd=_d(raw["entry_gate"]["min_liquidity_usd"]),
            min_market_cap_usd=_d(raw["entry_gate"]["min_market_cap_usd"]),
            max_entry_price_impact_pct=_d(raw["entry_gate"]["max_impact_pct"])),
        score_min=_d(raw["entry_score_min"]),
        stop=_d(ex["stop"]),
        max_hold=timedelta(minutes=ex["max_hold_minutes"]),
        scale_out_at=_d(scale["at_multiple"]) if scale else None,
        scale_out_fraction=_d(scale["sell_fraction"]) if scale else None,
        runner_trail=_d(ex["runner_trail_frac"]),
        rug_ladder=tuple((r["after_seconds"], _d(r["min_multiple"]), r["label"])
                         for r in raw["fast_rug_gates"]["ladder"]),
        lock_ladder=tuple((_d(r["once_peak_reaches_pct"]) / 100,
                           _d(r["never_sell_below_pct"]) / 100)
                          for r in raw["profit_lock"]["ladder"]),
        death_window=death["window"],
        death_rate=_d(death["halt_at_death_rate_pct"]) / 100,
        death_min_sample=death["min_sample"],
        death_halt_for=timedelta(hours=death["halt_for_hours"]),
        ratchet_give_back=_d(ratchet["give_back_pct"]) / 100,
        ratchet_floor=_d(ratchet["initial_floor_usd"]),
        size_pct=_d(size["position_pct_of_book"]) / 100,
        size_min=_d(size["min_position_usd"]),
        size_max=_d(size["max_position_usd"]),
        daily=DailyBreakerPolicy(
            max_daily_drawdown=_d(raw["daily_breaker"]["max_daily_drawdown_pct"]) / 100,
            max_daily_realised_loss=_d(raw["daily_breaker"]["max_daily_realised_loss_pct"])
            / 100),
        rules=rules,
        digest=hashlib.sha256(json.dumps(rules, sort_keys=True).encode()).hexdigest(),
    )


BOOKS: tuple[Book, ...] = tuple(
    load(p) for p in sorted((Path(__file__).parent / "books").glob("strategy_*.json")))
BY_CODE: dict[str, Book] = {b.code: b for b in BOOKS}
