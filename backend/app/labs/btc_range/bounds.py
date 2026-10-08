"""Limits and wording for every tunable in `StrategyConfig`.

One table serves two readers: `/config` publishes it so the page can validate a
field before it sends it, and `ConfigIn` enforces it so the server never trusts
that the page did. A value outside it is a 422, never a clamp - silently
changing what the reader asked to test would make the result a lie about the
config it reports.

The wording is read aloud by a page that must never advise. Labels and help say
what a setting MEASURES or LIMITS, in neutral terms; the page's banned-word test
renders every one of them.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from decimal import Decimal
from typing import Literal

from app.labs.btc_range.types import StrategyConfig

Kind = Literal["int", "decimal", "bool"]
Group = Literal["range", "entries", "account"]


@dataclass(frozen=True, slots=True)
class FieldBound:
    min: Decimal
    max: Decimal
    step: Decimal
    label: str
    help: str
    kind: Kind
    group: Group


def _int(lo: int, hi: int, label: str, help_: str, group: Group, step: int = 1) -> FieldBound:
    return FieldBound(Decimal(lo), Decimal(hi), Decimal(step), label, help_, "int", group)


def _dec(lo: str, hi: str, step: str, label: str, help_: str, group: Group) -> FieldBound:
    return FieldBound(Decimal(lo), Decimal(hi), Decimal(step), label, help_, "decimal", group)


def _flag(label: str, help_: str) -> FieldBound:
    return FieldBound(Decimal(0), Decimal(1), Decimal(1), label, help_, "bool", "entries")


#: Keyed by `StrategyConfig` field name. Order is the order the page lists them.
BOUNDS: dict[str, FieldBound] = {
    # --- range detection -----------------------------------------------------
    "lookback": _int(
        24,
        672,
        "Range window (candles)",
        "How many 15-minute candles define the range. 96 candles is one day.",
        "range",
    ),
    "touch_tolerance": _dec(
        "0.01",
        "0.20",
        "0.01",
        "Touch tolerance",
        "How close to an edge, as a fraction of the range width, "
        "a wick must reach to count as a touch.",
        "range",
    ),
    "min_touches": _int(
        1,
        5,
        "Touches per edge",
        "Touches of each edge needed for full credit in the range confidence score.",
        "range",
    ),
    "min_width_pct": _dec(
        "0.1",
        "5",
        "0.1",
        "Narrowest range (%)",
        "Ranges narrower than this, as a percent of the mid price, "
        "are reported as too narrow.",
        "range",
    ),
    "max_width_pct": _dec(
        "1",
        "20",
        "0.5",
        "Widest range (%)",
        "Ranges wider than this, as a percent of the mid price, are reported as too wide.",
        "range",
    ),
    "max_trend_efficiency": _dec(
        "0.1",
        "0.8",
        "0.05",
        "Trend limit",
        "Kaufman efficiency ratio of the closes, 0 to 1. "
        "Above this the window reads as a trend, not a range.",
        "range",
    ),
    "min_confidence": _int(
        0,
        100,
        "Minimum confidence",
        "Range confidence score, 0 to 100, needed before an edge is acted on.",
        "range",
    ),
    # --- entries and exits ---------------------------------------------------
    "entry_zone": _dec(
        "0.05",
        "0.45",
        "0.01",
        "Entry zone",
        "Fraction of the range width, measured from an edge, "
        "in which price counts as at that edge.",
        "entries",
    ),
    "tp_target": _dec(
        "0.2",
        "1.0",
        "0.05",
        "Target position",
        "Where the target sits inside the range, "
        "as a fraction of its width from the entry edge.",
        "entries",
    ),
    "sl_buffer": _dec(
        "0.02",
        "1.0",
        "0.01",
        "Stop distance",
        "How far beyond the entry edge the stop sits, as a fraction of the range width.",
        "entries",
    ),
    "min_reward_risk": _dec(
        "0.5",
        "5",
        "0.1",
        "Minimum reward to risk",
        "Calls whose target distance is smaller than this multiple of the stop distance "
        "are reported as poor reward to risk.",
        "entries",
    ),
    "max_hold_candles": _int(
        0,
        672,
        "Max candles in a trade",
        "A trade ends at the close after this many candles. 0 turns the time limit off.",
        "entries",
    ),
    "cooldown_candles": _int(
        0,
        96,
        "Pause after an exit (candles)",
        "Candles with no new trade after any exit.",
        "entries",
    ),
    "allow_long": _flag("Trade long", "Include long trades, taken near support."),
    "allow_short": _flag("Trade short", "Include short trades, taken near resistance."),
    # --- paper account -------------------------------------------------------
    "starting_balance": _dec(
        "100",
        "1000000",
        "100",
        "Starting balance (USD)",
        "Paper account size at the start of the run.",
        "account",
    ),
    "risk_per_trade_pct": _dec(
        "0.1",
        "5",
        "0.1",
        "Risk per trade (%)",
        "Percent of account equity lost if the stop is reached, before costs. "
        "Sets the position size.",
        "account",
    ),
    "max_leverage": _dec(
        "1",
        "5",
        "0.5",
        "Max leverage",
        "Position value is capped at account equity times this figure.",
        "account",
    ),
    "fee_bps": _dec(
        "0",
        "50",
        "0.5",
        "Fee (bps per side)",
        "Exchange fee on position value, in basis points, charged at entry and again at exit.",
        "account",
    ),
    "slippage_bps": _dec(
        "0",
        "50",
        "0.5",
        "Slippage (bps per fill)",
        "Adverse price movement applied to every fill, in basis points.",
        "account",
    ),
}


def config_field_names() -> tuple[str, ...]:
    """Every `StrategyConfig` field, in declaration order."""
    return tuple(f.name for f in fields(StrategyConfig))
