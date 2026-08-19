"""The daily paper-wallet report, as data.

Reporting only. Nothing in this module opens, closes, reprices or re-rules a
position. It reads what `PaperWalletService.read` already assembled and shapes
it for one email.

## Where the numbers come from

Every financial figure is `metrics.WalletMetrics`, computed by
`app.paper.metrics.summarise` — the same function the dashboard and the API
serve. Nothing here recomputes P&L. If the email and the dashboard ever
disagree, that is a bug in this module, not a second opinion.

The one figure this module *does* compute is **today's realised P&L**, and only
because "today" has to mean something different here. `WalletRead.pnl_today`
counts from UTC midnight, which is correct for a dashboard that says nothing
about timezones and wrong for a report headed "09:00" in a named zone. So the
boundary is computed in `DAILY_REPORT_TIMEZONE` and handed to the same
`metrics.pnl_since` the read model uses.

## What is refused

Unrealised "today's change" is not reported as a number. It would need each
position's mark at local midnight, and the snapshot series does not guarantee
an observation at that instant. `None` renders as `N/A` rather than as a
figure derived from the nearest reading, which would move on the cadence of the
scanner rather than on the market.

Pure: no I/O, no clock. `now` and the read model arrive as parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.paper import metrics
from app.paper.models import ClosedTrade, ExitReason
from app.paper.service import WalletRead

_ZERO = Decimal(0)


def local_day_bounds(now: datetime, tz_name: str) -> tuple[datetime, datetime, date]:
    """The UTC instants bounding "today" in `tz_name`, and the local date.

    Returned in UTC because every stored timestamp is UTC; converting the rows
    instead would mean converting far more values than converting the boundary.

    DST is handled by `ZoneInfo` rather than by arithmetic: midnight is built in
    local time and *then* converted, so a day that is 23 or 25 hours long still
    starts and ends where the calendar says it does.
    """
    zone = ZoneInfo(tz_name)
    local_now = now.astimezone(zone)
    local_date = local_now.date()
    start_local = datetime.combine(local_date, time.min, tzinfo=zone)
    end_local = datetime.combine(local_date + timedelta(days=1), time.min, tzinfo=zone)
    return (
        start_local.astimezone(ZoneInfo("UTC")),
        end_local.astimezone(ZoneInfo("UTC")),
        local_date,
    )


@dataclass(frozen=True, slots=True)
class ClosedRow:
    """One trade that closed inside the reporting day."""

    symbol: str
    mint_address: str
    strategy_version: str
    opened_at: datetime
    closed_at: datetime
    entry_price: Decimal
    exit_price: Decimal
    entry_market_cap: Decimal | None
    exit_market_cap: Decimal | None
    held_hours: Decimal
    gross_pct: Decimal
    #: `None` when depth was never recorded — `costs.round_trip` refuses rather
    #: than pricing against an invented pool, and that refusal travels here.
    fees_usd: Decimal | None
    slippage_usd: Decimal | None
    net_pct: Decimal | None
    pnl_usd: Decimal
    exit_reason: str


@dataclass(frozen=True, slots=True)
class OpenRow:
    """One position still open at report time."""

    symbol: str
    mint_address: str
    strategy_version: str
    opened_at: datetime
    entry_price: Decimal
    current_price: Decimal | None
    entry_market_cap: Decimal | None
    current_market_cap: Decimal | None
    peak_price: Decimal
    held_hours: Decimal
    gross_pct: Decimal | None
    estimated_costs_usd: Decimal | None
    estimated_net_pct: Decimal | None
    liquidity_usd: Decimal | None
    #: Research telemetry, present only where the stored rows support it.
    turnover_at_entry: Decimal | None = None


@dataclass(frozen=True, slots=True)
class TodaySummary:
    """What happened during the reporting day."""

    opened: int
    closed: int
    winners: int
    losers: int
    win_rate_pct: Decimal | None
    gross_pnl_usd: Decimal
    fees_usd: Decimal | None
    slippage_usd: Decimal | None
    total_costs_usd: Decimal | None
    net_pnl_usd: Decimal | None
    #: Realised only, and only for the local day. See the module docstring.
    realised_pnl_usd: Decimal
    #: Deliberately `None`: no mark exists at local midnight. Rendered `N/A`.
    unrealised_change_usd: Decimal | None
    return_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class DataQualityNote:
    """One warning, or the absence of them."""

    label: str
    count: int


@dataclass(frozen=True, slots=True)
class DailyReport:
    """Everything one email prints."""

    report_date: date
    timezone_name: str
    generated_at: datetime

    strategy_id: str
    strategy_name: str
    strategy_version: str
    execution_model: str

    wallet: metrics.WalletMetrics
    today: TodaySummary
    closed_rows: tuple[ClosedRow, ...]
    open_rows: tuple[OpenRow, ...]
    best: ClosedRow | None
    worst: ClosedRow | None
    warnings: tuple[DataQualityNote, ...]

    @property
    def has_closed_today(self) -> bool:
        return bool(self.closed_rows)


def _pct(entry: Decimal, price: Decimal) -> Decimal:
    return (price / entry - Decimal(1)) * Decimal(100)


def _hours(start: datetime, end: datetime) -> Decimal:
    return Decimal((end - start).total_seconds()) / Decimal(3600)


def _closed_today(read: WalletRead, start: datetime, end: datetime) -> list[ClosedTrade]:
    """Trades closed inside the local day, by their stored UTC timestamps."""
    return [
        trade
        for trade in _closed_trades(read)
        if trade.closed_at is not None and start <= trade.closed_at < end
    ]


def _closed_trades(read: WalletRead) -> list[ClosedTrade]:
    """Closed trades as the metrics layer models them.

    Rebuilt from the same positions the read model carries rather than queried
    again, so the email cannot see a different set than the figures it prints.
    """
    from app.paper.service import _to_closed

    out: list[ClosedTrade] = []
    for position in read.positions:
        trade = _to_closed(position)
        if trade is not None:
            out.append(trade)
    return out


def build(
    *,
    read: WalletRead,
    now: datetime,
    tz_name: str,
    warnings: tuple[DataQualityNote, ...] = (),
) -> DailyReport:
    """Shape one day's report from the authoritative read model."""
    start, end, local_date = local_day_bounds(now, tz_name)

    closed_today = _closed_today(read, start, end)
    opened_today = sum(1 for position in read.positions if start <= position.opened_at < end)

    by_mint = {position.mint_address: position for position in read.positions}
    closed_rows: list[ClosedRow] = []
    for trade in closed_today:
        position = by_mint.get(trade.mint_address)
        if position is None or position.exit_price is None:
            continue
        symbol, _ = read.names.get(trade.mint_address, (None, None))
        gross = _pct(position.entry_price, position.exit_price)
        closed_rows.append(
            ClosedRow(
                symbol=symbol or trade.mint_address[:8],
                mint_address=trade.mint_address,
                # Version lives on the wallet, not the position: one wallet
                # follows exactly one strategy for its whole life.
                strategy_version=read.strategy.version,
                opened_at=position.opened_at,
                closed_at=trade.closed_at,
                entry_price=position.entry_price,
                exit_price=position.exit_price,
                entry_market_cap=position.entry_market_cap,
                exit_market_cap=None,
                held_hours=_hours(position.opened_at, trade.closed_at),
                gross_pct=gross,
                fees_usd=None,
                slippage_usd=None,
                net_pct=None,
                pnl_usd=trade.pnl,
                exit_reason=position.exit_reason or ExitReason.STOP.value,
            )
        )

    open_rows: list[OpenRow] = []
    for position in read.positions:
        if position.status != "open":
            continue
        symbol, _ = read.names.get(position.mint_address, (None, None))
        price = read.prices.get(position.mint_address)
        open_rows.append(
            OpenRow(
                symbol=symbol or position.mint_address[:8],
                mint_address=position.mint_address,
                strategy_version=read.strategy.version,
                opened_at=position.opened_at,
                entry_price=position.entry_price,
                current_price=price,
                entry_market_cap=position.entry_market_cap,
                current_market_cap=None,
                peak_price=position.peak_price,
                held_hours=_hours(position.opened_at, now),
                gross_pct=None if price is None else _pct(position.entry_price, price),
                estimated_costs_usd=None,
                estimated_net_pct=None,
                liquidity_usd=position.entry_liquidity_usd,
            )
        )

    winners = sum(1 for row in closed_rows if row.pnl_usd > 0)
    losers = sum(1 for row in closed_rows if row.pnl_usd < 0)
    gross_pnl = sum((row.pnl_usd for row in closed_rows), _ZERO)
    realised = metrics.pnl_since(closed_today, since=start)

    today = TodaySummary(
        opened=opened_today,
        closed=len(closed_rows),
        winners=winners,
        losers=losers,
        win_rate_pct=(
            None
            if not closed_rows
            else (Decimal(winners) / Decimal(len(closed_rows)) * Decimal(100))
        ),
        gross_pnl_usd=gross_pnl,
        # Per-trade cost attribution is not stored on the position rows; the
        # audit found `entry/exit_execution_price_impact_pct` populated on 0 of
        # 119. Reporting a fee figure would mean inventing one.
        fees_usd=None,
        slippage_usd=None,
        total_costs_usd=None,
        net_pnl_usd=None,
        realised_pnl_usd=realised,
        unrealised_change_usd=None,
        return_pct=(
            None
            if read.wallet.starting_balance <= 0
            else realised / read.wallet.starting_balance * Decimal(100)
        ),
    )

    ranked = sorted(closed_rows, key=lambda row: row.pnl_usd)
    return DailyReport(
        report_date=local_date,
        timezone_name=tz_name,
        generated_at=now,
        strategy_id=read.strategy.id,
        strategy_name=read.strategy.name,
        strategy_version=read.strategy.version,
        execution_model=_execution_model(read),
        wallet=read.metrics,
        today=today,
        closed_rows=tuple(closed_rows),
        open_rows=tuple(open_rows),
        best=ranked[-1] if ranked else None,
        worst=ranked[0] if ranked else None,
        warnings=warnings,
    )


def _execution_model(read: WalletRead) -> str:
    """The execution model the most recent position was priced under."""
    for position in sorted(read.positions, key=lambda p: p.opened_at, reverse=True):
        version = getattr(position, "entry_execution_model_version", None)
        if version:
            return str(version)
    return "unrecorded"
