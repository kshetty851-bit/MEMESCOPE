"""Aggregation over finished episodes. Pure; takes rows, returns JSON.

The only question this module exists to answer is whether the score was worth
computing: does a higher decile actually break out more often, and does it
return more when it does? It reports that without deciding it — every number
here is an average of what happened, and nothing in the detection path can see
any of it.

`None` is preserved throughout. An episode whose window has not closed has no
return, and counting it as zero would be the easiest way to make a flat result
look like a positive one.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from typing import Any

from app.labs.nse_breakout import config, states

#: Kept out of the mean: a return that does not exist yet is not a zero one.
DECILES = 10


def _floats(values: Iterable[Any]) -> list[float]:
    return [float(v) for v in values if v is not None]


def _mean(values: Sequence[float]) -> float | None:
    return round(statistics.fmean(values), 4) if values else None


def _median(values: Sequence[float]) -> float | None:
    return round(statistics.median(values), 4) if values else None


def _win_rate(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return round(sum(1 for v in values if v > 0) / len(values) * 100, 2)


def _profit_factor(values: Sequence[float]) -> float | None:
    """Gross gains over gross losses.

    None rather than infinity when nothing lost: a profit factor with no
    denominator is not a very good one, it is an unmeasured one, and infinity
    in a JSON payload is a rendering bug waiting to happen.
    """
    gains = sum(v for v in values if v > 0)
    losses = -sum(v for v in values if v < 0)
    if losses <= 0:
        return None
    return round(gains / losses, 4)


def _side(rows: Sequence[Any], prefix: str) -> dict[str, Any]:
    twenty = _floats(getattr(r, f"ret_{prefix}_20") for r in rows)
    return {
        "n": len(twenty),
        "mean_ret_20": _mean(twenty),
        "median_ret_20": _median(twenty),
        "win_rate_20": _win_rate(twenty),
        "mean_mfe": _mean(_floats(
            getattr(r, "mfe_20" if prefix == "ref" else "mfe_bo_20") for r in rows)),
        "mean_mae": _mean(_floats(
            getattr(r, "mae_20" if prefix == "ref" else "mae_bo_20") for r in rows)),
    }


def _decile_of(score: int) -> int:
    """Score 0-100 into deciles 1-10. 100 belongs in the top one, not an
    eleventh."""
    return min(DECILES, max(1, score // DECILES + 1))


def summarise(rows: Sequence[Any]) -> dict[str, Any]:
    """The `/stats` payload for one source's episodes."""
    total = len(rows)
    if not total:
        return {"episodes": 0, "reached_breakout_pct": None,
                "false_breakout_pct": None, "from_ref": _side((), "ref"),
                "from_breakout": _side((), "bo"), "trail10": {},
                "rel_nifty_20_mean": None, "by_score_decile": [], "by_year": []}

    broke = [r for r in rows if r.breakout_date is not None]
    false_breaks = [r for r in rows if r.close_reason == states.FALSE_BREAKOUT]
    trail = _floats(r.trail10_pct for r in rows)
    return {
        "episodes": total,
        "reached_breakout_pct": round(len(broke) / total * 100, 2),
        # Of the ones that BROKE OUT, not of all episodes: an episode that
        # never broke out cannot have broken out falsely, and putting it in
        # the denominator would make the rate look better the more setups
        # fizzled before the level.
        "false_breakout_pct": (round(len(false_breaks) / len(broke) * 100, 2)
                               if broke else None),
        "from_ref": _side(rows, "ref"),
        "from_breakout": _side(broke, "bo"),
        "trail10": {"n": len(trail), "mean": _mean(trail),
                    "win_rate": _win_rate(trail),
                    "profit_factor": _profit_factor(trail),
                    "stopped_pct": (round(sum(1 for r in rows
                                              if r.trail10_stopped) / len(trail)
                                          * 100, 2) if trail else None)},
        "rel_nifty_20_mean": _mean(_floats(r.rel_nifty_20 for r in rows)),
        "by_score_decile": _by_decile(rows),
        "by_year": _by_year(rows),
        "days_to_breakout_median": _median(
            _floats(r.days_to_breakout for r in broke)),
    }


def _by_decile(rows: Sequence[Any]) -> list[dict[str, Any]]:
    """Does a higher score actually break out more, and return more?

    Bucketed on `max_score` — the highest the setup ever scored — rather than
    the score on the day it opened. The opening score is whatever crossed the
    threshold first and is the same number for almost every episode by
    construction; the peak is the one that varies.
    """
    buckets: dict[int, list[Any]] = {}
    for row in rows:
        buckets.setdefault(_decile_of(row.max_score), []).append(row)
    out = []
    for decile in sorted(buckets):
        group = buckets[decile]
        broke = [r for r in group if r.breakout_date is not None]
        returns = _floats(r.ret_bo_20 for r in broke)
        out.append({
            "decile": decile,
            "score_range": f"{(decile - 1) * DECILES}-{decile * DECILES - 1}",
            "n": len(group),
            "reached_breakout_pct": round(len(broke) / len(group) * 100, 2),
            "mean_ret_bo_20": _mean(returns),
            "mean_ret_ref_20": _mean(_floats(r.ret_ref_20 for r in group)),
            "win_rate": _win_rate(returns),
        })
    return out


def _by_year(rows: Sequence[Any]) -> list[dict[str, Any]]:
    """The same numbers per calendar year. A result that only exists in one
    year is a fact about that year."""
    buckets: dict[int, list[Any]] = {}
    for row in rows:
        buckets.setdefault(row.opened.year, []).append(row)
    out = []
    for year in sorted(buckets):
        group = buckets[year]
        broke = [r for r in group if r.breakout_date is not None]
        out.append({
            "year": year,
            "episodes": len(group),
            "reached_breakout_pct": round(len(broke) / len(group) * 100, 2),
            "mean_ret_bo_20": _mean(_floats(r.ret_bo_20 for r in broke)),
            "mean_ret_ref_20": _mean(_floats(r.ret_ref_20 for r in group)),
            "rel_nifty_20_mean": _mean(_floats(r.rel_nifty_20 for r in group)),
        })
    return out


def config_snapshot() -> dict[str, Any]:
    """The thresholds these numbers were produced under.

    Pasted into the payload so a statistic can never be read against the wrong
    rules: the README's replay table and a later run are only comparable if
    this block matches.
    """
    return {"watch_score": config.WATCH_SCORE, "watch_pct": config.WATCH_PCT,
            "near_score": config.NEAR_SCORE, "near_pct": config.NEAR_PCT,
            "break_confirm_pct": config.BREAK_CONFIRM_PCT,
            "break_vol_mult": config.BREAK_VOL_MULT,
            "false_window_days": config.FALSE_WINDOW_DAYS,
            "fail_pct": config.FAIL_PCT,
            "max_episode_days": config.MAX_EPISODE_DAYS,
            "trail_pct": config.TRAIL_PCT}
