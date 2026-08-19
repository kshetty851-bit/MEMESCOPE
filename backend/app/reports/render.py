"""Rendering the daily report to HTML and plain text.

Email clients are not browsers. Gmail strips `<style>` blocks, Outlook renders
through Word, and neither runs JavaScript or honours flexbox. So this is
deliberately old-fashioned: tables for layout, every style inline, no external
asset, no class that has to survive a sanitiser.

The palette follows MEMESCOPE's terminal — graphite surfaces, one cyan accent,
green and red reserved for direction — but the layout does not chase the
product's look. This is an operational report; if a client falls back to the
text part, nothing of substance is lost, which is why the text part is a real
report rather than "view this in a browser".

## The rule about missing numbers

`None` renders as `N/A`, never as `0.00`, `—` or a blank cell. The audit that
started this work found the wallet's own figures distinguish "no rows behind
this" from "zero", and an email that flattens the two would report a fee of
nothing on a trade whose fee is unknown.

Pure: no I/O, no clock.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from html import escape

from app.reports.daily_paper import ClosedRow, DailyReport, OpenRow

# --- Palette. Inline everywhere; named here so the two renderers agree. -------
_BG = "#0b0e17"
_SURFACE = "#151925"
_LINE = "#252b3a"
_INK = "#e8eaf0"
_INK_2 = "#9aa3b8"
_INK_3 = "#6b7488"
_ACCENT = "#4fd1e0"
_UP = "#3fbf7f"
_DOWN = "#e0483c"

_NA = "N/A"


def _money(value: Decimal | None, *, signed: bool = False) -> str:
    if value is None:
        return _NA
    sign = "+" if signed and value > 0 else ""
    return f"{sign}${value:,.2f}"


def _pct(value: Decimal | None, *, signed: bool = True) -> str:
    if value is None:
        return _NA
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{value:.2f}%"


def _num(value: Decimal | None, places: int = 2) -> str:
    return _NA if value is None else f"{value:,.{places}f}"


def _price(value: Decimal | None) -> str:
    if value is None:
        return _NA
    # Sub-cent tokens are the norm here, so a fixed 2dp would print $0.00 for
    # most of the book.
    return f"${value:,.8f}".rstrip("0").rstrip(".") if value < 1 else f"${value:,.4f}"


def _colour(value: Decimal | None) -> str:
    if value is None:
        return _INK_2
    return _UP if value > 0 else _DOWN if value < 0 else _INK_2


def _when(moment: datetime | None, tz_name: str) -> str:
    if moment is None:
        return _NA
    from zoneinfo import ZoneInfo

    return moment.astimezone(ZoneInfo(tz_name)).strftime("%H:%M")


# --- HTML --------------------------------------------------------------------

_CELL = f"padding:8px 10px;border-bottom:1px solid {_LINE};font-size:12px;"
_HEAD = (
    f"padding:8px 10px;border-bottom:1px solid {_LINE};font-size:10px;"
    f"letter-spacing:0.08em;text-transform:uppercase;color:{_INK_3};text-align:left;"
)


def _stat(label: str, value: str, colour: str = _INK) -> str:
    return (
        f'<td style="{_CELL}width:25%;vertical-align:top;">'
        f'<div style="font-size:10px;letter-spacing:0.08em;text-transform:uppercase;'
        f'color:{_INK_3};padding-bottom:4px;">{escape(label)}</div>'
        f'<div style="font-size:16px;color:{colour};font-weight:600;">{escape(value)}</div>'
        f"</td>"
    )


def _section(title: str) -> str:
    return (
        f'<tr><td colspan="4" style="padding:22px 10px 8px;font-size:11px;'
        f"letter-spacing:0.14em;text-transform:uppercase;color:{_ACCENT};"
        f'border-bottom:1px solid {_LINE};">{escape(title)}</td></tr>'
    )


def _closed_table(rows: tuple[ClosedRow, ...], tz: str) -> str:
    if not rows:
        return (
            f'<tr><td colspan="4" style="{_CELL}color:{_INK_2};">'
            "No positions closed today.</td></tr>"
        )
    head = "".join(
        f'<th style="{_HEAD}">{h}</th>'
        for h in ("Token", "In", "Out", "Held", "Entry", "Exit", "Gross", "Net", "Rule")
    )
    body = ""
    for row in rows:
        body += (
            f"<tr>"
            f'<td style="{_CELL}color:{_INK};font-weight:600;">{escape(row.symbol)}</td>'
            f'<td style="{_CELL}color:{_INK_2};">{_when(row.opened_at, tz)}</td>'
            f'<td style="{_CELL}color:{_INK_2};">{_when(row.closed_at, tz)}</td>'
            f'<td style="{_CELL}color:{_INK_2};">{row.held_hours:.1f}h</td>'
            f'<td style="{_CELL}color:{_INK_2};">{_price(row.entry_price)}</td>'
            f'<td style="{_CELL}color:{_INK_2};">{_price(row.exit_price)}</td>'
            f'<td style="{_CELL}color:{_colour(row.gross_pct)};font-weight:600;">'
            f"{_pct(row.gross_pct)}</td>"
            f'<td style="{_CELL}color:{_colour(row.net_pct)};font-weight:600;">'
            f"{_pct(row.net_pct)}</td>"
            f'<td style="{_CELL}color:{_INK_3};">{escape(row.exit_reason)}</td>'
            f"</tr>"
        )
    return (
        f'<tr><td colspan="4" style="padding:0 10px;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse;"><tr>{head}</tr>{body}</table></td></tr>'
    )


def _open_table(rows: tuple[OpenRow, ...], tz: str) -> str:
    if not rows:
        return (
            f'<tr><td colspan="4" style="{_CELL}color:{_INK_2};">No open positions.</td></tr>'
        )
    head = "".join(
        f'<th style="{_HEAD}">{h}</th>'
        for h in ("Token", "Opened", "Held", "Entry", "Current", "Peak", "Gross", "Liquidity")
    )
    body = ""
    for row in rows:
        body += (
            f"<tr>"
            f'<td style="{_CELL}color:{_INK};font-weight:600;">{escape(row.symbol)}</td>'
            f'<td style="{_CELL}color:{_INK_2};">{_when(row.opened_at, tz)}</td>'
            f'<td style="{_CELL}color:{_INK_2};">{row.held_hours:.1f}h</td>'
            f'<td style="{_CELL}color:{_INK_2};">{_price(row.entry_price)}</td>'
            f'<td style="{_CELL}color:{_INK_2};">{_price(row.current_price)}</td>'
            f'<td style="{_CELL}color:{_INK_2};">{_price(row.peak_price)}</td>'
            f'<td style="{_CELL}color:{_colour(row.gross_pct)};font-weight:600;">'
            f"{_pct(row.gross_pct)}</td>"
            f'<td style="{_CELL}color:{_INK_2};">{_money(row.liquidity_usd)}</td>'
            f"</tr>"
        )
    return (
        f'<tr><td colspan="4" style="padding:0 10px;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse;"><tr>{head}</tr>{body}</table></td></tr>'
    )


def to_html(report: DailyReport, *, is_test: bool = False) -> str:
    """The report as an email-safe HTML document."""
    w = report.wallet
    t = report.today
    tz = report.timezone_name

    banner = ""
    if is_test:
        banner = (
            f'<tr><td colspan="4" style="padding:10px;background:{_ACCENT};'
            f"color:{_BG};font-size:12px;font-weight:700;text-align:center;"
            'letter-spacing:0.08em;">TEST EMAIL — NOT A SCHEDULED REPORT</td></tr>'
        )

    best = (
        f"{escape(report.best.symbol)} {_pct(report.best.gross_pct)} "
        f"({_money(report.best.pnl_usd, signed=True)}, {report.best.held_hours:.1f}h)"
        if report.best
        else "No positions closed today."
    )
    worst = (
        f"{escape(report.worst.symbol)} {_pct(report.worst.gross_pct)} "
        f"({_money(report.worst.pnl_usd, signed=True)}, {report.worst.held_hours:.1f}h)"
        if report.worst
        else "No positions closed today."
    )

    warnings_html = (
        "".join(
            f'<tr><td colspan="4" style="{_CELL}color:{_INK_2};">'
            f"{escape(note.label)}: <strong>{note.count}</strong></td></tr>"
            for note in report.warnings
        )
        if report.warnings
        else f'<tr><td colspan="4" style="{_CELL}color:{_INK_2};">'
        "No major data-quality warnings detected.</td></tr>"
    )

    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:{_BG};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
 style="background:{_BG};padding:24px 12px;">
<tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
 style="max-width:680px;background:{_SURFACE};border:1px solid {_LINE};
 border-radius:8px;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
 color:{_INK};">
{banner}
<tr><td colspan="4" style="padding:20px 10px 4px;">
  <div style="font-size:11px;letter-spacing:0.22em;color:{_ACCENT};">MEMESCOPE</div>
  <div style="font-size:20px;font-weight:600;padding-top:4px;">
    Daily Paper Wallet Report</div>
  <div style="font-size:12px;color:{_INK_3};padding-top:4px;">
    {report.report_date.isoformat()} · {_when(report.generated_at, tz)} · {escape(tz)}</div>
</td></tr>

{_section("Portfolio")}
<tr>{_stat("Starting", _money(w.starting_balance))}
    {_stat("Cash", _money(w.cash))}
    {
        _stat(
            "Equity",
            _money(w.equity),
            _colour(None if w.equity is None else w.equity - w.starting_balance),
        )
    }
    {_stat("Total return", _pct(w.roi_pct), _colour(w.roi_pct))}</tr>
<tr>{_stat("Realised P&L", _money(w.realised_pnl, signed=True), _colour(w.realised_pnl))}
    {_stat("Open value", _money(w.open_value))}
    {_stat("Invested", _money(w.invested_usd))}
    {_stat("Open positions", str(w.open_positions))}</tr>

{_section(f"Today · {report.report_date.isoformat()}")}
<tr>{_stat("Opened", str(t.opened))}
    {_stat("Closed", str(t.closed))}
    {_stat("Win rate", _pct(t.win_rate_pct, signed=False))}
    {
        _stat("Realised", _money(t.realised_pnl_usd, signed=True), _colour(t.realised_pnl_usd))
    }</tr>
<tr>{_stat("Gross P&L", _money(t.gross_pnl_usd, signed=True), _colour(t.gross_pnl_usd))}
    {_stat("Execution costs", _money(t.total_costs_usd))}
    {_stat("Net P&L", _money(t.net_pnl_usd, signed=True), _colour(t.net_pnl_usd))}
    {_stat("Return", _pct(t.return_pct), _colour(t.return_pct))}</tr>

{_section("Closed today")}
{_closed_table(report.closed_rows, tz)}

{_section("Best / worst")}
<tr><td colspan="4" style="{_CELL}color:{_INK_2};">Best: {best}</td></tr>
<tr><td colspan="4" style="{_CELL}color:{_INK_2};">Worst: {worst}</td></tr>

{_section("Open positions")}
{_open_table(report.open_rows, tz)}

{_section("Cumulative")}
<tr>{_stat("Closed trades", str(w.closed_positions))}
    {_stat("Win rate", _pct(w.win_rate_pct, signed=False))}
    {_stat("Profit factor", _num(w.profit_factor, 3))}
    {_stat("Max drawdown", _pct(w.max_drawdown_pct))}</tr>
<tr>{_stat("Avg win", _money(w.average_win))}
    {_stat("Avg loss", _money(w.average_loss))}
    {_stat("Largest win", _money(w.largest_winner))}
    {_stat("Largest loss", _money(w.largest_loser))}</tr>

{_section("Active strategy")}
<tr><td colspan="4" style="{_CELL}color:{_INK_2};">
  <strong style="color:{_INK};">{escape(report.strategy_name)}</strong>
  &nbsp;·&nbsp; {escape(report.strategy_id)} v{escape(report.strategy_version)}
  &nbsp;·&nbsp; execution: {escape(report.execution_model)}
</td></tr>

{_section("Data quality")}
{warnings_html}

<tr><td colspan="4" style="padding:16px 10px 20px;color:{_INK_3};font-size:11px;
 border-top:1px solid {_LINE};">
  Simulated trading only. No wallet is connected and no order is routed.
  Net figures charge the venue's published fee plus modelled price impact and
  exclude competing-flow slippage and MEV.
</td></tr>
</table></td></tr></table></body></html>"""


# --- Plain text --------------------------------------------------------------


def to_text(report: DailyReport, *, is_test: bool = False) -> str:
    """The same report as text. A real fallback, not a pointer to the HTML."""
    w = report.wallet
    t = report.today
    tz = report.timezone_name
    lines: list[str] = []

    if is_test:
        lines += ["*** TEST EMAIL - NOT A SCHEDULED REPORT ***", ""]

    lines += [
        "MEMESCOPE - DAILY PAPER WALLET REPORT",
        f"{report.report_date.isoformat()} · {_when(report.generated_at, tz)} · {tz}",
        "",
        "PORTFOLIO",
        f"  Starting        {_money(w.starting_balance)}",
        f"  Cash            {_money(w.cash)}",
        f"  Equity          {_money(w.equity)}",
        f"  Total return    {_pct(w.roi_pct)}",
        f"  Realised P&L    {_money(w.realised_pnl, signed=True)}",
        f"  Open positions  {w.open_positions}",
        "",
        f"TODAY ({report.report_date.isoformat()})",
        f"  Opened          {t.opened}",
        f"  Closed          {t.closed}  (W {t.winners} / L {t.losers})",
        f"  Win rate        {_pct(t.win_rate_pct, signed=False)}",
        f"  Gross P&L       {_money(t.gross_pnl_usd, signed=True)}",
        f"  Costs           {_money(t.total_costs_usd)}",
        f"  Net P&L         {_money(t.net_pnl_usd, signed=True)}",
        f"  Realised        {_money(t.realised_pnl_usd, signed=True)}",
        "",
        "CLOSED TODAY",
    ]

    if report.closed_rows:
        for row in report.closed_rows:
            lines.append(
                f"  {row.symbol:<10} {_when(row.opened_at, tz)}->{_when(row.closed_at, tz)}"
                f"  {row.held_hours:>5.1f}h  gross {_pct(row.gross_pct):>9}"
                f"  net {_pct(row.net_pct):>9}  {row.exit_reason}"
            )
    else:
        lines.append("  No positions closed today.")

    lines += ["", "BEST / WORST"]
    if report.best:
        lines.append(
            f"  Best   {report.best.symbol} {_pct(report.best.gross_pct)} "
            f"({_money(report.best.pnl_usd, signed=True)}, {report.best.held_hours:.1f}h)"
        )
        lines.append(
            f"  Worst  {report.worst.symbol} {_pct(report.worst.gross_pct)} "
            f"({_money(report.worst.pnl_usd, signed=True)}, {report.worst.held_hours:.1f}h)"
        )
    else:
        lines.append("  No positions closed today.")

    lines += ["", "OPEN POSITIONS"]
    if report.open_rows:
        for row in report.open_rows:
            lines.append(
                f"  {row.symbol:<10} held {row.held_hours:>5.1f}h  "
                f"entry {_price(row.entry_price):>14}  now {_price(row.current_price):>14}  "
                f"gross {_pct(row.gross_pct):>9}"
            )
    else:
        lines.append("  No open positions.")

    lines += [
        "",
        "CUMULATIVE",
        f"  Closed trades   {w.closed_positions}",
        f"  Win rate        {_pct(w.win_rate_pct, signed=False)}",
        f"  Profit factor   {_num(w.profit_factor, 3)}",
        f"  Max drawdown    {_pct(w.max_drawdown_pct)}",
        "",
        "ACTIVE STRATEGY",
        f"  {report.strategy_name} · {report.strategy_id} v{report.strategy_version}",
        f"  Execution model: {report.execution_model}",
        "",
    ]
    lines += [
        "DATA QUALITY",
    ]
    if report.warnings:
        lines += [f"  {note.label}: {note.count}" for note in report.warnings]
    else:
        lines.append("  No major data-quality warnings detected.")

    lines += [
        "",
        "Simulated trading only. No wallet is connected and no order is routed.",
    ]
    return "\n".join(lines)


def subject_for(report: DailyReport, *, is_test: bool = False) -> str:
    if is_test:
        return "MEMESCOPE — Test Paper Wallet Report"
    return f"MEMESCOPE — Daily Paper Wallet Report — {report.report_date.isoformat()}"
