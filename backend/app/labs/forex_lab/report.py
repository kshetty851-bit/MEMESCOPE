"""Turn a sweep's JSON into REPORT.md.

Pure formatting over a dict. Its one piece of judgement is the gate, and the
gate is a constant: four conditions stated before the sweep ran, checked
verbatim, never adjusted to fit what came back.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.labs.forex_lab import config

HERE = Path(__file__).parent
OUTPUT = HERE / "output"

#: Stated in PLAN.md before a single candle was replayed. Not to be moved.
GATE = {
    "profit_factor_min": 1.3,
    "years_positive_min": 4,
    "years_positive_of": 6,
    "must_include_year": 2022,
    "max_drawdown_pct_max": 25.0,
    "best_month_share_max": 0.30,
}


def gate_verdict(r: dict[str, Any]) -> dict[str, Any]:
    """PASS only if all four hold. A None profit factor means no losing trade
    at all, which over six years is a bug or an empty run, not a pass."""
    pf = r.get("profit_factor")
    per_year = {int(k): v for k, v in (r.get("per_year") or {}).items()}
    share = r.get("best_month_share")
    checks = {
        "pf>=1.3": pf is not None and pf >= GATE["profit_factor_min"],
        "positive in >=4 of 6 years": r.get("years_positive", 0) >= GATE["years_positive_min"],
        "2022 positive": per_year.get(GATE["must_include_year"], 0) > 0,
        "max DD < 25%": r.get("max_drawdown_pct", 1e9) < GATE["max_drawdown_pct_max"],
        "no month > 30% of profit": (
            r.get("total_return_pct", 0) > 0
            and share is not None
            and share <= GATE["best_month_share_max"]
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


def _fmt(v, nd=2, dash="—"):
    if v is None:
        return dash
    if isinstance(v, float):
        return f"{v:,.{nd}f}"
    return f"{v:,}" if isinstance(v, int) else str(v)


def _config_table(results: list[dict]) -> str:
    head = ("| Config | PF | Return % | Max DD % | Low water | Trades | "
            "Re-centres | Stop-outs | Rejected | Years + (of 6) | "
            "Best month share |")
    sep = "|" + "---|" * 11
    rows = []
    for r in sorted(results, key=lambda x: -(x["profit_factor"] or -1)):
        share = r["best_month_share"]
        low = _fmt(r.get("min_equity"))
        if r.get("blown"):
            low += " **BLOWN**"
        rows.append(
            f"| `{r['config']['name']}` | {_fmt(r['profit_factor'], 3)} | "
            f"{_fmt(r['total_return_pct'])} | {_fmt(r['max_drawdown_pct'])} | "
            f"{low} | {_fmt(r['trades'])} | {_fmt(r['recenters'])} | "
            f"{_fmt(r['stopouts'])} | {_fmt(r['rejected_fills'])} | "
            f"{r['years_positive']} of {GATE['years_positive_of']} | "
            f"{'—' if share is None else f'{share:.1%}'} |"
        )
    return "\n".join([head, sep, *rows])


def _year_table(results: list[dict]) -> str:
    years = sorted({int(y) for r in results for y in r["per_year"]})
    head = "| Config | " + " | ".join(str(y) for y in years) + " |"
    sep = "|" + "---|" * (len(years) + 1)
    rows = []
    for r in sorted(results, key=lambda x: -(x["profit_factor"] or -1)):
        per = {int(k): v for k, v in r["per_year"].items()}
        cells = " | ".join(f"{per.get(y, 0):+,.0f}" for y in years)
        rows.append(f"| `{r['config']['name']}` | {cells} |")
    return "\n".join([head, sep, *rows])


_DEVIATIONS = """## Deviations from the brief, and what they cost

Every one of these is argued in full in DECISIONS.md; this is the list.

1. **Triple swap on Wednesday — an ADDITION, not a relaxation.** The brief says
   swap is applied daily at 17:00 New York. Charged on five weekday rollovers
   that is five nights of carry for seven nights held, and the weekend is never
   billed. Brokers book three nights at the Wednesday rollover, whose value
   date settles on Monday. It makes the backtest more expensive, not less.

2. **Swap rates are derived, not quoted.** OANDA publishes no retrievable
   historical swap archive. The table is built from what a swap is made of —
   the ECB deposit facility rate against Fed funds effective, time-weighted per
   year, less 0.5%/yr of markup each side — and the inputs and outputs are
   printed in `config.py` so the arithmetic can be checked.

3. **The spread is charged half on each fill.** "Applied on every fill", with
   grid levels at the mid, means a buy pays half above and a sell half below:
   one full 0.8-pip spread per round trip, which is what a broker takes.
   Charging the full spread on both legs would bill 1.6 pips for one round trip.

4. **A gapped order fills at its level, not at the reopen.** The conventional
   choice, and the one whose two errors cancel — see the limitation below.

5. **Margin is held at the open price and summed over hedged positions.** The
   brief gives a per-micro-lot formula without saying which price or how the
   two sides combine. Many brokers charge only the larger side in hedging mode;
   summing is the stricter reading, and the brief says positions are never
   netted.

6. **Market closes pay slippage as well as spread.** A re-centre or a stop-out
   is the one moment a grid dumps many positions into a fast move.

7. **"4 of 6 years" is measured over 2020–2025.** The window spans seven
   calendar years because 2026 is January to June. Folding a half year in as a
   seventh would loosen the gate; it is reported separately and counted in
   nothing.

8. **The migration was applied directly rather than through `alembic upgrade
   head`.** That command was already broken on this branch before this lab
   existed — `0063_breakout_lab` parents to a revision not present here — and
   the brief forbids touching files outside the lab. `0069` parents to `0068`,
   the branch head, and its DDL was executed against a clean database to prove
   it runs.

## Limitations worth stating plainly

**The gap model does not charge the worst of a weekend.** An order the market
gapped over fills at its own level, so a stop crossed by a 40-pip Sunday gap is
flattered by exactly the amount a limit crossed by the same gap is penalised.
The grid holds equal numbers of both, so the errors cancel in aggregate — and
for the neutral baseline, which has no stops, the convention is purely
conservative. But a grid is short volatility across a weekend, and this is the
one cost it is not made to pay in full.

**Six and a half years of one pair is one sample of one regime.** A grid's
headline number is famously a function of the window it ran over. The gate was
written down before the sweep ran and has not been adjusted since, which is the
only thing separating this from a search for a flattering window.

**This is a backtest.** Nothing here has traded. Fill assumptions that hold in
a replay — that a limit at a level always fills when price touches it, that
rejections are the only thing a broker ever refuses — are assumptions, not
observations.
"""


def _baseline_row(label: str, r: dict | None) -> str:
    if r is None:
        return f"| {label} | — | — |"
    return (f"| {label}, `{r['config']['name']}` | {_fmt(r['final_equity'])} | "
            f"{_fmt(r['total_return_pct'])}% |")


def _verdict_sentence(hedged: dict | None, neutral: dict | None, bh: dict) -> str:
    """The plain statement the brief asks for. Says so explicitly when a
    baseline is missing rather than quietly comparing against nothing."""
    if hedged is None:
        return "No hedged configuration was run, so there is nothing to compare."
    parts = []
    if neutral is None:
        parts.append("no neutral grid was run to compare against")
    else:
        parts.append(
            f"**{'beat' if hedged['final_equity'] > neutral['final_equity'] else 'did not beat'}** "
            "the neutral-grid baseline")
    parts.append(
        f"**{'beat' if hedged['final_equity'] > bh['final_equity'] else 'did not beat'}** "
        "buy-and-hold")
    return "The hedged grid " + " and ".join(parts) + "."


def _pct(v) -> str:
    return "—" if v is None else f"{v:.1%}"


def _tick(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def write_report(sweep_path: str = "sweep.json", dest: Path | None = None) -> str:
    """Render REPORT.md from a sweep file and write it. Returns the path."""
    p = Path(sweep_path)
    if not p.is_absolute():
        p = OUTPUT / sweep_path
    data = json.loads(p.read_text())
    results = data["results"]
    dest = dest or (HERE / "REPORT.md")

    ranked = sorted(results, key=lambda x: -(x["profit_factor"] or -1))
    best = ranked[0]
    v = gate_verdict(best)
    c = v["checks"]
    y2022 = {int(k): val for k, val in best["per_year"].items()}.get(2022, 0.0)

    def best_of(rs):
        return max(rs, key=lambda x: (x["profit_factor"] or -1)) if rs else None

    best_neutral = best_of([r for r in results
                            if r["config"]["stop_multiplier"] == 0.0])
    best_hedged = best_of([r for r in results
                           if r["config"]["stop_multiplier"] > 0])
    bh = data["buy_and_hold"]

    cfg = best["config"]
    first, last = data["first_minute"][:10], data["last_minute"][:10]
    # The window the brief asked for, against the window that was actually
    # replayed. A report headed 2020–2026 over eighteen months of data is a
    # report that lies in its title.
    want_first = config.START.isoformat()
    want_last = config.END.isoformat()
    short = first > want_first or last < want_last
    banner = []
    if short:
        banner = [
            f"> **Partial coverage.** The brief's window is {want_first} to "
            f"{want_last}; this replay covers {first} to {last}. Every number "
            "below is about the window that was loaded, and the gate's "
            "\"4 of 6 years\" cannot be satisfied by a window that does not "
            "contain six years.",
            "",
        ]

    lines = [
        f"# forex_lab — a hedged grid on EUR/USD, {first} to {last}",
        "",
        *banner,
        f"{data['candles']:,} one-minute bid/ask candles aggregated from Dukascopy "
        f"ticks, {first} to {last}. "
        "$1,000 paper wallet at 10x leverage, 1 micro lot an order, 0.8-pip spread, "
        "0.2-pip slippage on stop fills, swap charged at every 17:00 New York "
        "rollover with three nights booked on Wednesday. No live trading and no "
        "paper feed: this is a replay and nothing else.",
        "",
        "## Verdict",
        "",
        f"**{_tick(v['passed'])}** — the best configuration by profit factor is "
        f"`{cfg['name']}`: step {cfg['step_pips']:g} pips, {cfg['levels']} levels "
        f"each side, stop orders at x{cfg['stop_multiplier']:g} of the base size.",
        "",
        "Against the gate stated in PLAN.md before the sweep ran, unadjusted:",
        "",
        "| Gate condition | Required | Actual | |",
        "|---|---|---|---|",
        f"| Profit factor | >= 1.3 | {_fmt(best['profit_factor'], 3)} | "
        f"{_tick(c['pf>=1.3'])} |",
        f"| Years positive | >= 4 of 6 | {best['years_positive']} of "
        f"{GATE['years_positive_of']} | {_tick(c['positive in >=4 of 6 years'])} |",
        f"| 2022 positive | yes | ${y2022:+,.0f} | {_tick(c['2022 positive'])} |",
        f"| Max drawdown | < 25% | {_fmt(best['max_drawdown_pct'])}% | "
        f"{_tick(c['max DD < 25%'])} |",
        f"| Largest month | <= 30% of total profit | "
        f"{_pct(best['best_month_share'])} | "
        f"{_tick(c['no month > 30% of profit'])} |",
        "",
        "## Every configuration",
        "",
        _config_table(results),
        "",
        "### Profit and loss by year, in dollars on a $1,000 wallet",
        "",
        _year_table(results),
        "",
        "2026 is January to June, half a year, and is counted in nothing: the "
        "gate's denominator is the six full years 2020–2025.",
        "",
        "\"Low water\" is the lowest equity the account ever showed, measured at "
        "the worse extreme of every candle rather than at a daily close. A "
        "configuration marked BLOWN passed through zero: its profit factor and "
        "its return are arithmetic about an account that had stopped existing, "
        "and no gate result for it means anything.",
        "",
        "\"Best month share\" is the most profitable month as a fraction of the "
        "run's TOTAL profit, so it exceeds 100% whenever the other months lost "
        "money between them — a configuration whose whole result is one good "
        "month and a slow bleed. It is blank where there was no profit to "
        "concentrate, and the gate fails in that case too.",
        "",
        f"## Cost breakdown — `{cfg['name']}`",
        "",
        "| Component | USD |",
        "|---|---|",
        f"| Banked by take-profits | {_fmt(best['tp_pnl'])} |",
        f"| Realised on re-centres | {_fmt(best['recenter_loss'])} |",
        f"| Realised on stop-outs | {_fmt(best['stopout_loss'])} |",
        f"| Swap | {_fmt(best['swap_paid'])} |",
        f"| **Final equity** | **{_fmt(best['final_equity'])}** |",
        "",
        f"Spread and slippage inside those figures: **{_fmt(best['spread_paid'])}** "
        "paid across every fill, entries and exits both. It is not a separate line "
        "above because it is already inside each of them — every fill price in this "
        "engine is the price after the spread, so subtracting it again would bill "
        "it twice.",
        "",
        f"{best['fills']:,} fills, {best['trades']:,} closed positions, "
        f"{best['rejected_fills']:,} fills rejected by the 90% margin cap, "
        f"{best['recenters']:,} re-centres, {best['stopouts']:,} stop-outs.",
        "",
        "## Against the baselines",
        "",
        "| | Final equity | Return |",
        "|---|---|---|",
        _baseline_row("Best hedged grid", best_hedged),
        _baseline_row("Best neutral grid (no stop orders)", best_neutral),
        f"| Buy and hold, 1 micro lot | {_fmt(bh['final_equity'])} | "
        f"{_fmt(bh['total_return_pct'])}% |",
        "",
        _verdict_sentence(best_hedged, best_neutral, bh),
        "",
        _DEVIATIONS,
    ]
    text = "\n".join(lines)
    dest.write_text(text)
    return str(dest)


def render(sweep_path: str = "sweep.json") -> str:
    return write_report(sweep_path)
