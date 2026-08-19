"""Run the frozen V1.2 progressive-profit-lock research replay."""

# ruff: noqa: E501, ASYNC240
from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path
from statistics import median

from sqlalchemy import asc, select

from app.db.session import SessionFactory
from app.models.market import TokenMarketSnapshot
from app.models.paper import PaperPosition, PaperWallet
from app.paper.canonical_replay import Opportunity
from app.paper.canonical_replay import replay as replay_v1_1
from app.paper.models import Quote
from app.paper.progressive_profit_lock import LOCKS, replay


async def source() -> tuple[list[Opportunity], dict[str, list[Quote]]]:
    async with SessionFactory() as session:
        legacy = await session.scalar(
            select(PaperWallet)
            .where(PaperWallet.strategy_id == "trailing_stop_25_v1")
            .order_by(PaperWallet.generation)
        )
        if legacy is None:
            raise RuntimeError("Archived V1.0 wallet not found")
        rows = list(
            (
                await session.scalars(
                    select(PaperPosition)
                    .where(PaperPosition.wallet_id == legacy.id)
                    .order_by(asc(PaperPosition.opened_at))
                )
            ).all()
        )
        mints = sorted({row.mint_address for row in rows})
        snapshots = list(
            (
                await session.scalars(
                    select(TokenMarketSnapshot)
                    .where(TokenMarketSnapshot.mint_address.in_(mints))
                    .order_by(
                        TokenMarketSnapshot.mint_address, TokenMarketSnapshot.captured_at
                    )
                )
            ).all()
        )
    histories: dict[str, list[Quote]] = {}
    volumes: dict[tuple[str, object], Decimal | None] = {}
    for row in snapshots:
        volumes[(row.mint_address, row.captured_at)] = row.volume_24h
        if row.price_usd is not None and row.price_usd > 0:
            histories.setdefault(row.mint_address, []).append(
                Quote(row.captured_at, row.price_usd, row.liquidity_usd, row.market_cap)
            )
    opportunities = []
    for row in rows:
        entry = [
            quote
            for quote in histories.get(row.mint_address, ())
            if quote.captured_at <= row.opened_at
        ]
        if entry:
            quote = entry[-1]
            opportunities.append(
                Opportunity(
                    row.mint_address,
                    quote.captured_at,
                    row.entry_rank,
                    quote.price_usd,
                    quote.liquidity_usd,
                    volumes[(row.mint_address, quote.captured_at)],
                    quote.market_cap,
                )
            )
    return opportunities, histories


def numbers(result: object) -> dict[str, object]:
    trades = result.trades
    closed = [trade for trade in trades if trade.closed_at is not None]
    pnls = [trade.net_pnl for trade in closed if trade.net_pnl is not None]
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    return {
        "return": None if result.equity is None else (result.equity / Decimal(1000) - 1) * 100,
        "pf": None if not losses else sum(wins, Decimal(0)) / -sum(losses, Decimal(0)),
        "expectancy": None if not pnls else sum(pnls, Decimal(0)) / len(pnls),
        "max_drawdown": result.max_drawdown_pct,
        "wins": wins,
        "losses": losses,
        "closed": closed,
    }


async def main() -> None:
    opportunities, histories = await source()
    result = replay(opportunities, histories)
    baseline = replay_v1_1(opportunities, histories)
    stats = numbers(result)
    closed = stats["closed"]
    wins = stats["wins"]
    losses = stats["losses"]
    by_mint_v1 = {
        trade.mint: trade.net_pnl if trade.closed else trade.marked_pnl
        for trade in baseline.trades
    }
    comparisons = []
    for trade in result.trades:
        value = trade.net_pnl if trade.closed_at else trade.marked_pnl
        old = by_mint_v1.get(trade.mint)
        if value is not None and old is not None:
            comparisons.append((value - old, trade.mint, old, value))
    threshold_lines = []
    for threshold, _ in LOCKS:
        reached = [trade for trade in result.trades if threshold in trade.reached]
        retained = [
            trade.gross_return_pct for trade in reached if trade.gross_return_pct is not None
        ]
        threshold_lines.append(
            f"- +{threshold * 100:.0f}%: {len(reached)} trades; average eventual retained gross return: {'n/a' if not retained else f'{sum(retained, Decimal(0)) / len(retained):.2f}%'}"
        )
    sorted_opportunities = sorted(opportunities, key=lambda row: (row.observed_at, row.mint))
    splits = []
    for fraction in (Decimal("0.60"), Decimal("0.70")):
        cut = int(len(sorted_opportunities) * fraction)
        early, late = sorted_opportunities[:cut], sorted_opportunities[cut:]
        cutoff = early[-1].observed_at
        # The early cohort must not read future snapshots. It is marked at its
        # own chronological boundary; the later cohort remains independent.
        early_histories = {
            mint: [quote for quote in quotes if quote.captured_at <= cutoff]
            for mint, quotes in histories.items()
        }
        splits.append(
            (
                f"Early {int(fraction * 100)}% / Late {100 - int(fraction * 100)}%",
                numbers(replay(early, early_histories)),
                numbers(replay(late, histories)),
            )
        )
    lines = [
        "# V1.2 Progressive Profit-Lock — Frozen Research",
        "",
        "> Research only. No wallet, position, or strategy state was written.",
        "",
        "## Result",
        "",
        "- Starting equity: $1,000.00",
        f"- Ending equity: ${result.equity:.2f}",
        f"- Net P/L: ${result.equity - Decimal(1000):.2f}",
        f"- Return: {stats['return']:.2f}%",
        f"- Trades opened: {result.accepted}",
        f"- Trades rejected: {result.rejected_survival + result.rejected_cash + result.rejected_missing}",
        f"- Wins / losses: {len(wins)} / {len(losses)}",
        f"- Win rate: {len(wins) / len(closed) * 100:.2f}%",
        f"- Gross profit / loss: ${sum(wins, Decimal(0)):.2f} / ${sum(losses, Decimal(0)):.2f}",
        f"- Profit factor: {stats['pf']:.2f}",
        f"- Expectancy: ${stats['expectancy']:.2f}",
        f"- Execution costs: ${result.costs:.2f}",
        f"- Maximum drawdown: {result.max_drawdown_pct:.2f}%",
        f"- Exits: fixed TP 0, initial stop {sum(t.exit_kind == 'initial_stop' for t in closed)}, profit floor {sum(t.exit_kind == 'profit_floor' for t in closed)}, unresolved {sum(t.closed_at is None for t in result.trades)}",
        f"- Median winner / loser: ${median(wins):.2f} / ${median(losses):.2f}",
        f"- Largest winner / loss: ${max(wins):.2f} / ${min(losses):.2f}",
        f"- Average winner / loser: ${sum(wins, Decimal(0)) / len(wins):.2f} / ${sum(losses, Decimal(0)) / len(losses):.2f}",
        "",
        "## Threshold retention",
        "",
        *threshold_lines,
        "",
        "## Chronological validation",
        "",
    ]
    for label, train, test in splits:
        lines.extend(
            [
                f"### {label}",
                "",
                f"- Train: return {train['return']:.2f}%, PF {'n/a' if train['pf'] is None else f'{train["pf"]:.2f}'}, expectancy ${train['expectancy']:.2f}, max drawdown {train['max_drawdown']:.2f}%",
                f"- Test: return {test['return']:.2f}%, PF {'n/a' if test['pf'] is None else f'{test["pf"]:.2f}'}, expectancy ${test['expectancy']:.2f}, max drawdown {test['max_drawdown']:.2f}%",
                "",
            ]
        )
    lines.extend(
        [
            "## Versus canonical V1.1",
            "",
            "V1.1 ending equity: $556.65; P/L: -$443.35; PF: 0.61.",
            "",
            "### Top 15 improvements",
            "",
            "| Mint | V1.1 net/mark | V1.2 net/mark | Difference |",
            "|---|---:|---:|---:|",
        ]
    )
    for difference, mint, old, new in sorted(comparisons, reverse=True)[:15]:
        lines.append(f"| `{mint}` | ${old:.2f} | ${new:.2f} | ${difference:.2f} |")
    lines.extend(
        [
            "",
            "### Top 15 deteriorations",
            "",
            "| Mint | V1.1 net/mark | V1.2 net/mark | Difference |",
            "|---|---:|---:|---:|",
        ]
    )
    for difference, mint, old, new in sorted(comparisons)[:15]:
        lines.append(f"| `{mint}` | ${old:.2f} | ${new:.2f} | ${difference:.2f} |")
    path = (
        Path(__file__).resolve().parents[1]
        / "research_exports"
        / "v1_2_progressive_profit_lock.md"
    )
    path.write_text("\n".join(lines) + "\n")
    print(path)


if __name__ == "__main__":
    asyncio.run(main())
