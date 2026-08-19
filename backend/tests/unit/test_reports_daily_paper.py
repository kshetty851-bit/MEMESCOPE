"""The daily report: date boundaries, rendering, and the refusal to invent.

Two things here are worth more than the rest.

`TestLocalDayBounds` pins the timezone contract. The wallet's own `pnl_today`
counts from **UTC** midnight, which is correct for a dashboard that names no
timezone and wrong for an email headed "09:00 Asia/Dubai". If these tests stop
holding, the report silently attributes four hours of trades to the wrong day.

`TestMissingDataRendersNA` pins the other. `None` means "no rows behind this",
not zero, and an email that prints $0.00 for an unknown fee is stating a number
nobody computed.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from app.paper import metrics
from app.reports import render
from app.reports.daily_paper import (
    ClosedRow,
    DailyReport,
    DataQualityNote,
    TodaySummary,
    local_day_bounds,
)

DUBAI = "Asia/Dubai"  # UTC+4, no DST
LONDON = "Europe/London"  # DST, so the offset is not a constant


class TestLocalDayBounds:
    def test_dubai_day_starts_four_hours_before_utc_midnight(self) -> None:
        # 2026-08-12 06:00 UTC is 10:00 in Dubai — the same calendar day.
        start, end, local = local_day_bounds(
            datetime(2026, 8, 12, 6, 0, tzinfo=UTC), DUBAI
        )
        assert local == date(2026, 8, 12)
        assert start == datetime(2026, 8, 11, 20, 0, tzinfo=UTC)
        assert end == datetime(2026, 8, 12, 20, 0, tzinfo=UTC)

    def test_late_utc_evening_is_already_tomorrow_in_dubai(self) -> None:
        """The boundary case the UTC-midnight version gets wrong."""
        _, _, local = local_day_bounds(datetime(2026, 8, 12, 21, 0, tzinfo=UTC), DUBAI)
        assert local == date(2026, 8, 13)

    def test_early_utc_morning_is_still_yesterday_in_new_york(self) -> None:
        _, _, local = local_day_bounds(
            datetime(2026, 8, 12, 2, 0, tzinfo=UTC), "America/New_York"
        )
        assert local == date(2026, 8, 11)

    def test_dst_is_handled_by_the_zone_not_by_arithmetic(self) -> None:
        """London is UTC+1 in August and UTC+0 in January."""
        summer_start, _, _ = local_day_bounds(
            datetime(2026, 8, 12, 12, 0, tzinfo=UTC), LONDON
        )
        winter_start, _, _ = local_day_bounds(
            datetime(2026, 1, 12, 12, 0, tzinfo=UTC), LONDON
        )
        assert summer_start == datetime(2026, 8, 11, 23, 0, tzinfo=UTC)
        assert winter_start == datetime(2026, 1, 12, 0, 0, tzinfo=UTC)

    def test_the_day_is_exactly_24_hours_outside_a_dst_change(self) -> None:
        start, end, _ = local_day_bounds(datetime(2026, 8, 12, 6, 0, tzinfo=UTC), DUBAI)
        assert (end - start).total_seconds() == 86_400


def wallet_metrics(**overrides: object) -> metrics.WalletMetrics:
    base: dict[str, object] = {
        "starting_balance": Decimal(1000),
        "cash": Decimal(800),
        "equity": Decimal(1050),
        "roi_pct": Decimal(5),
        "open_value": Decimal(250),
        "known_partial_equity": Decimal(1050),
        "invested_usd": Decimal(200),
        "unpriced_positions": 0,
        "priced_positions": 2,
        "open_positions": 2,
        "closed_positions": 10,
        "realised_pnl": Decimal(50),
        "win_rate_pct": Decimal(40),
        "average_win": Decimal(30),
        "average_loss": Decimal(-15),
        "profit_factor": Decimal("1.2"),
        "largest_winner": Decimal(80),
        "largest_loser": Decimal(-40),
        "max_drawdown_pct": Decimal(-12),
        "average_hold_hours": Decimal(6),
        "exits_by_reason": {"stop": 10},
    }
    base.update(overrides)
    return metrics.WalletMetrics(**base)  # type: ignore[arg-type]


def closed_row(symbol: str, gross: Decimal, pnl: Decimal) -> ClosedRow:
    return ClosedRow(
        symbol=symbol,
        mint_address=f"{symbol}mint",
        strategy_version="1.0.0",
        opened_at=datetime(2026, 8, 12, 4, 0, tzinfo=UTC),
        closed_at=datetime(2026, 8, 12, 8, 0, tzinfo=UTC),
        entry_price=Decimal("0.001"),
        exit_price=Decimal("0.0012"),
        entry_market_cap=Decimal(100_000),
        exit_market_cap=None,
        held_hours=Decimal(4),
        gross_pct=gross,
        fees_usd=None,
        slippage_usd=None,
        net_pct=None,
        pnl_usd=pnl,
        exit_reason="stop",
    )


def report(**overrides: object) -> DailyReport:
    rows = overrides.pop("closed_rows", ())
    base: dict[str, object] = {
        "report_date": date(2026, 8, 12),
        "timezone_name": DUBAI,
        "generated_at": datetime(2026, 8, 12, 5, 0, tzinfo=UTC),
        "strategy_id": "trailing_stop_25_v1",
        "strategy_name": "Trailing Stop 25%",
        "strategy_version": "1.0.0",
        "execution_model": "legacy_constant_product_v1",
        "wallet": wallet_metrics(),
        "today": TodaySummary(
            opened=1,
            closed=len(rows),
            winners=sum(1 for r in rows if r.pnl_usd > 0),
            losers=sum(1 for r in rows if r.pnl_usd < 0),
            win_rate_pct=Decimal(50) if rows else None,
            gross_pnl_usd=sum((r.pnl_usd for r in rows), Decimal(0)),
            fees_usd=None,
            slippage_usd=None,
            total_costs_usd=None,
            net_pnl_usd=None,
            realised_pnl_usd=Decimal(25),
            unrealised_change_usd=None,
            return_pct=Decimal("2.5"),
        ),
        "closed_rows": rows,
        "open_rows": (),
        "best": max(rows, key=lambda r: r.pnl_usd) if rows else None,
        "worst": min(rows, key=lambda r: r.pnl_usd) if rows else None,
        "warnings": (),
    }
    base.update(overrides)
    return DailyReport(**base)  # type: ignore[arg-type]


class TestHtmlRendering:
    def test_renders_a_complete_document(self) -> None:
        html = render.to_html(report())
        assert html.startswith("<!doctype html>")
        assert "Daily Paper Wallet Report" in html
        assert "2026-08-12" in html

    def test_uses_no_javascript_or_external_assets(self) -> None:
        """Email clients strip both, and Gmail strips <style> blocks too."""
        html = render.to_html(report())
        for forbidden in ("<script", "javascript:", "<link", "@import", "<style"):
            assert forbidden not in html.lower()

    def test_escapes_token_symbols(self) -> None:
        rows = (closed_row("<img src=x>", Decimal(10), Decimal(5)),)
        html = render.to_html(report(closed_rows=rows))
        assert "<img src=x>" not in html
        assert "&lt;img" in html

    def test_no_trades_says_so(self) -> None:
        html = render.to_html(report())
        assert "No positions closed today." in html

    def test_test_email_carries_a_banner(self) -> None:
        assert "TEST EMAIL" in render.to_html(report(), is_test=True)
        assert "TEST EMAIL" not in render.to_html(report(), is_test=False)


class TestTextRendering:
    def test_is_a_real_report_not_a_pointer(self) -> None:
        text = render.to_text(report())
        assert "MEMESCOPE - DAILY PAPER WALLET REPORT" in text
        assert "PORTFOLIO" in text
        assert "CUMULATIVE" in text
        # Never a "view in browser" stub.
        assert "browser" not in text.lower()

    def test_no_trades_says_so(self) -> None:
        assert "No positions closed today." in render.to_text(report())

    def test_lists_closed_trades(self) -> None:
        rows = (closed_row("WIF", Decimal(20), Decimal(20)),)
        text = render.to_text(report(closed_rows=rows))
        assert "WIF" in text

    def test_test_email_is_marked(self) -> None:
        assert "TEST EMAIL" in render.to_text(report(), is_test=True)


class TestMissingDataRendersNA:
    """`None` is not zero, on any surface."""

    def test_unavailable_costs_are_na_not_zero(self) -> None:
        rows = (closed_row("WIF", Decimal(20), Decimal(20)),)
        for body in (
            render.to_html(report(closed_rows=rows)),
            render.to_text(report(closed_rows=rows)),
        ):
            assert "N/A" in body

    def test_unpriced_equity_is_na(self) -> None:
        html = render.to_html(report(wallet=wallet_metrics(equity=None, roi_pct=None)))
        assert "N/A" in html

    def test_zero_is_still_printed_as_zero(self) -> None:
        """A real zero must not be disguised as missing."""
        text = render.to_text(report(wallet=wallet_metrics(realised_pnl=Decimal(0))))
        assert "$0.00" in text


class TestWinnersAndLosers:
    def test_best_and_worst_are_reported(self) -> None:
        rows = (
            closed_row("WIN", Decimal(50), Decimal(50)),
            closed_row("LOSS", Decimal(-30), Decimal(-30)),
        )
        text = render.to_text(report(closed_rows=rows))
        assert "Best   WIN" in text
        assert "Worst  LOSS" in text

    def test_direction_colours_are_applied(self) -> None:
        """Green for a gain, red for a loss, on the same page."""
        rows = (
            closed_row("WIN", Decimal(50), Decimal(50)),
            closed_row("LOSS", Decimal(-30), Decimal(-30)),
        )
        html = render.to_html(report(closed_rows=rows))
        assert "#3fbf7f" in html  # up
        assert "#e0483c" in html  # down


class TestDataQuality:
    def test_healthy_says_so(self) -> None:
        assert "No major data-quality warnings detected." in render.to_text(report())

    def test_warnings_are_listed_with_counts(self) -> None:
        warned = report(warnings=(DataQualityNote("Uncostable positions", 7),))
        text = render.to_text(warned)
        assert "Uncostable positions: 7" in text


class TestSubject:
    def test_daily_subject_carries_the_date(self) -> None:
        assert (
            render.subject_for(report())
            == "MEMESCOPE — Daily Paper Wallet Report — 2026-08-12"
        )

    def test_test_subject_is_distinct(self) -> None:
        assert (
            render.subject_for(report(), is_test=True)
            == "MEMESCOPE — Test Paper Wallet Report"
        )


class TestProductionAndResearchAreSeparated:
    def test_the_email_identifies_the_active_paper_strategy(self) -> None:
        assert "trailing_stop_25_v1" in render.to_html(report())
