"""Bounded, non-mutating entry-edge screen over the canonical V1.1 universe."""
# ruff: noqa: E501, ASYNC240
from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path

from app.paper.canonical_replay import replay
from app.paper.models import Quote
from scripts.run_v1_2_progressive_profit_lock import source


def metrics(result: object) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    closed = [trade for trade in result.trades if trade.closed]
    pnls = [trade.net_pnl for trade in closed if trade.net_pnl is not None]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    return (
        None if result.marked_equity is None else (result.marked_equity / 1000 - 1) * 100,
        None if not losses else sum(wins, Decimal(0)) / -sum(losses, Decimal(0)),
        None if not pnls else sum(pnls, Decimal(0)) / len(pnls),
    )


async def main() -> None:
    opportunities, histories = await source()
    ordered = sorted(opportunities, key=lambda x: (x.observed_at, x.mint))
    # Fixed, interpretable gates. Values are declared before results are read.
    gates = {
        "baseline survival >= 1.25": lambda x: True,
        "liquidity >= $5k": lambda x: x.liquidity is not None and x.liquidity >= 5000,
        "liquidity >= $10k": lambda x: x.liquidity is not None and x.liquidity >= 10000,
        "turnover >= 2.0": lambda x: x.volume_24h is not None and x.liquidity is not None and x.volume_24h / x.liquidity >= 2,
        "turnover >= 5.0": lambda x: x.volume_24h is not None and x.liquidity is not None and x.volume_24h / x.liquidity >= 5,
        "liquidity >= $5k AND turnover >= 2.0": lambda x: x.liquidity is not None and x.volume_24h is not None and x.liquidity >= 5000 and x.volume_24h / x.liquidity >= 2,
    }
    lines = ["# Entry Edge Research — Bounded Initial Screen", "", "> Research only; immutable snapshots read, no wallet rows written.", "", "## Historically available at the reconstructed entry snapshot", "", "- price, liquidity, market cap, volume 5m/1h/24h, buy/sell 24h counts, DEX/pair/pool, provider latency, trading status and verification.", "- Candidate ledger also contains entry rank. Historical Radar component/evidence, holders, concentration, token age, confidence/risk and 6h fields were not joined into this first audit because no immutable entry-timestamp record was established for all opportunities.", "- Market cap is explicitly excluded from gates pending independent quality validation.", "", "## Fixed-gate replay results", "", "| Gate | opportunities | return | PF | expectancy |", "|---|---:|---:|---:|", ]
    for name, gate in gates.items():
        selected = [row for row in ordered if gate(row)]
        result = replay(selected, histories)
        ret, pf, exp = metrics(result)
        lines.append(f"| {name} | {len(selected)} | {'n/a' if ret is None else f'{ret:.2f}%'} | {'n/a' if pf is None else f'{pf:.2f}'} | {'n/a' if exp is None else f'${exp:.2f}'} |")
    lines.extend(["", "## Chronological holdouts", "", "The same frozen gates were evaluated on early-60/late-40 and early-70/late-30 opportunity cohorts. No gate was selected from full-history performance.", "", "| Gate | 60/40 late return / PF / expectancy | 70/30 late return / PF / expectancy |", "|---|---:|---:|"])
    for name, gate in gates.items():
        results=[]
        for fraction in (Decimal('.60'), Decimal('.70')):
            late=ordered[int(len(ordered)*fraction):]
            r=replay([x for x in late if gate(x)], histories); ret,pf,exp=metrics(r)
            results.append(f"{'n/a' if ret is None else f'{ret:.2f}%'} / {'n/a' if pf is None else f'{pf:.2f}'} / {'n/a' if exp is None else f'${exp:.2f}'}")
        lines.append(f"| {name} | {results[0]} | {results[1]} |")
    lines.extend(["", "## Finding", "", "No gate is considered validated unless its later cohort has positive expectancy and PF > 1. This bounded screen is deliberately not a parameter search.", "", "## Limitations", "", "- This report does not claim Radar inversion causes: immutable historical Radar component rows were not established for every entry timestamp.", "- The canonical historical Jupiter-quote limitation remains: the production legacy fallback cost model is used, not fabricated historical Jupiter quotes."])
    path=Path(__file__).resolve().parents[1]/'research_exports'/'entry_edge_initial_screen.md'
    path.write_text('\n'.join(lines)+'\n'); print(path)

if __name__=='__main__': asyncio.run(main())
