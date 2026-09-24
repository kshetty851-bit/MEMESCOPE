"""Karthik's fresh books: an arm's trades from a start, funded as that book's
own wallet would fund them."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.labs.graduation import config
from app.labs.graduation.api import fresh_book, start_walks
from app.labs.graduation.tournament import ARMS, CONTROLS, accepts

# the quiet pair on one start, then the three band books
BQ, BQ4, *SWEEP = config.FRESH_BOOKS

#: The book the panel dropped on 2026-09-20, whose arm still runs as this
#: one's control: the wallet walk that fed it is what this file tests.
B75 = config.FreshBookSpec("BASE_75k_5m", BQ.start, Decimal(500), Decimal(100))


def test_the_page_shows_the_quiet_book_and_the_band_books() -> None:
    assert (BQ.book, BQ.capital_usd, BQ.ticket_usd) == (
        "BASE_75k_quiet_5m", Decimal(500), Decimal(100))
    # The four-minute twin is funded from the SAME minute with the same money:
    # its early trades are this book's own coins re-priced at four minutes
    # (`scripts/seed_quiet_4m.py`), so two walks from different starts would
    # not be comparable.
    assert (BQ4.book, BQ4.start, BQ4.capital_usd, BQ4.ticket_usd) == (
        "BASE_75k_quiet_4m", BQ.start, Decimal(500), Decimal(100))
    # Three books on one band, same money from the same minute: two clocks,
    # and the quiet filter tested against the five-minute one.
    assert [s.book for s in SWEEP] == [
        "BAND_55k_2m", "BAND_55k_5m", "BAND_55k_quiet_5m", "BAND_55k_pump_5m",
        # Karthik's decision book (2026-09-22), judged 30 Sep, on which he has
        # said he will stake real money. It starts FORWARD — a backdated start
        # would let a run that already happened decide that.
        "B3_198k_5m",
        # The deep arm the real wallet mirrors (2026-09-23). Also forward.
        "B5_500k_flow_5m",
        # The rug-money-blocked band (2026-09-23), beside its control.
        "BAND_55k_blk_5m",
        # Karthik's own book (2026-09-23), judged thirty days later.
        "KARTHIK_QUIET_5M"]
    by_book = {spec.book: spec for spec in SWEEP}
    karthik = by_book["KARTHIK_QUIET_5M"]
    assert karthik.start == datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
    # Thirty days, fixed BEFORE its first trade: a judge date chosen afterwards
    # is chosen by the result.
    assert datetime(2026, 10, 23, 12, 0, tzinfo=UTC) == config.KARTHIK_JUDGE_AT
    assert (config.KARTHIK_JUDGE_AT - karthik.start).days == 30
    # It copies BASE_75k_quiet_5m's RULE, not its record: same entry, hold and
    # filter, its own trades from its own start.
    mine = next(a for a in ARMS if a.name == "KARTHIK_QUIET_5M")
    theirs = next(a for a in ARMS if a.name == "BASE_75k_quiet_5m")
    assert ((mine.entry, mine.hold, mine.quiet, mine.locked)
            == (theirs.entry, theirs.hold, theirs.quiet, theirs.locked))
    # Named, not indexed: the last entry moves every time a book is added, and
    # this pair is pinned because both are decision books that start FORWARD.
    assert by_book["B5_500k_flow_5m"].start == datetime(2026, 9, 23, 5, 0, tzinfo=UTC)
    assert next(a for a in ARMS if a.name == "B5_500k_flow_5m").hold == 5
    b3 = by_book["B3_198k_5m"]
    assert b3.start == datetime(2026, 9, 22, 8, 0, tzinfo=UTC)
    assert (b3.capital_usd, b3.ticket_usd) == (Decimal(500), Decimal(100))
    # The four band books share one start; B3 has its own, because it is a
    # decision book opened later and not part of that comparison.
    assert {(s.capital_usd, s.ticket_usd, s.start) for s in SWEEP[:4]} == {
        (Decimal(500), Decimal(100), SWEEP[0].start)}
    assert all(s.capital_usd == Decimal(500) and s.ticket_usd == Decimal(100)
               for s in SWEEP)
    arms = [next(a for a in ARMS if a.name == s.book) for s in SWEEP]
    assert [a.hold for a in arms] == [2, 5, 5, 5, 5, 5, 5, 5]
    assert [a.quiet for a in arms] == [
        False, False, True, False, False, False, False, True]
    # The pump twin differs from BAND_55k_5m in the ENTRY, not the exit.
    assert [a.entry for a in arms] == [
        "band55", "band55", "band55", "band55_pump", "liq_B3", "deep500_flow",
        "band55", "floor75"]
    arm = next(a for a in ARMS if a.name == BQ.book)
    assert arm.quiet and arm.hold == 5 and not arm.is_control
    # The control it is judged against still trades, panel or no panel.
    assert [c.name for c in CONTROLS] == ["BASE_75k_5m"]


def trade(spec: config.FreshBookSpec, minute: int, ret: float, hold: int = 5) -> tuple:
    opened = spec.start + timedelta(minutes=minute)
    return (opened, opened + timedelta(minutes=hold), ret, 0.0, 0.0)


def test_it_starts_at_500_and_ignores_everything_before_the_start() -> None:
    book = fresh_book([trade(B75, -60, 5.0), trade(B75, 1, 0.10), trade(B75, 10, -0.90)],
                      None, B75)
    assert (book.book, book.hold_minutes, book.capital_usd) == ("BASE_75k_5m", 5, Decimal(500))
    assert (book.trades, book.wins, book.rugs, book.skipped) == (2, 1, 1, 0)
    # $100 at +10%, then $100 at -90%: 500 + 10 - 90
    assert book.balance_usd == Decimal("420.00")
    assert book.pnl_usd == Decimal("-80.00") and book.return_pct == Decimal("-16.00")


def test_a_sixth_trade_at_once_finds_no_money_and_is_skipped() -> None:
    book = fresh_book([trade(B75, 0, 0.01, hold=30) for _ in range(6)], None, B75)
    assert (book.trades, book.skipped) == (5, 1)

def test_the_band_arms_buy_between_55k_and_75k_and_nothing_else() -> None:
    """The one slice positive on all four days measured to 21 Sep: $55-75k at
    two minutes ran +6.4%, +2.5%, +1.7%, +1.7% a trade while $25-40k ran -4.1%,
    -5.0%, -18.3%, -21.0%. A band, not a floor: above $75k was mixed."""
    band = sorted((a for a in ARMS if a.name.startswith("BAND_55k")),
                  key=lambda a: (a.hold, a.quiet, a.entry))
    assert [a.name for a in band] == [
        "BAND_55k_2m", "BAND_55k_5m", "BAND_55k_blk_5m", "BAND_55k_pump_5m",
        "BAND_55k_quiet_5m"]
    assert [a.hold for a in band] == [2, 5, 5, 5, 5]
    assert [a.quiet for a in band] == [False, False, False, False, True]
    # Karthik's rug-money block (2026-09-23) is on exactly one of them.
    assert [a.rug_blocked for a in band] == [False, False, True, False, False]
    # Karthik's pump-only twin (2026-09-22) narrows the ENTRY and nothing else:
    # same band, same lock, same clock, so the launchpad is what it measures.
    assert [a.entry for a in band] == [
        "band55", "band55", "band55", "band55_pump", "band55"]
    assert all(a.locked and not a.is_control for a in band)
    assert all((a.tp, a.trail, a.stop, a.drain, a.clock) == (None, None, None, None, "entry")
               for a in band)
    kw = {"mint": "m", "open_at": BQ.start, "fdv": None, "sells": None, "reuse": None}
    assert not accepts(band[0], liquidity=Decimal(54_999), **kw)
    assert accepts(band[0], liquidity=Decimal(55_000), **kw)
    assert accepts(band[0], liquidity=Decimal(74_999), **kw)
    assert not accepts(band[0], liquidity=Decimal(75_000), **kw)   # the baseline's floor
    assert not accepts(band[0], liquidity=None, **kw)


def rolling(first: int, last: int) -> config.RollingStart:
    return config.RollingStart("B3_198k_5m", date(2026, 9, first), date(2026, 9, last),
                               Decimal(500), Decimal(100))


def day_trade(day: int, ret: float) -> tuple:
    opened = datetime(2026, 9, day, 9, 0, tzinfo=UTC)
    return (opened, opened + timedelta(minutes=5), ret, 0.0, 0.0)


def test_each_start_day_is_its_own_wallet_not_a_share_of_one() -> None:
    """Karthik's rolling start (2026-09-22). A wallet opened later meets fewer
    trades, so the rows must differ by WHICH trades they saw, not by dividing
    one result — the whole question is how much a result depends on the day."""
    trades = [day_trade(22, 0.10), day_trade(23, -0.90)]
    rows = start_walks(trades, Decimal("120"), rolling(22, 27), today=date(2026, 9, 23))
    assert [r.started_on for r in rows] == [date(2026, 9, 22), date(2026, 9, 23)]
    # The 22nd took both; the 23rd only met the loser.
    assert [r.trades for r in rows] == [2, 1]
    assert [r.balance_usd for r in rows] == [Decimal("420.00"), Decimal("410.00")]


def test_it_stops_adding_rows_after_the_last_day_but_keeps_the_old_ones() -> None:
    """The table ends on 31 Oct; the wallets already in it keep running, because
    a wallet that was never closed does not stop having a balance."""
    trades = [day_trade(22, 0.10), day_trade(25, 0.10)]
    rows = start_walks(trades, Decimal("120"), rolling(22, 23), today=date(2026, 9, 30))
    assert [r.started_on for r in rows] == [date(2026, 9, 22), date(2026, 9, 23)]
    # The 23rd's wallet still sees the trade from the 25th — it was not closed.
    assert rows[1].trades == 1


class _Rows:
    """What `db.scalars(...)` gives back."""

    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class _StubDb:
    """The two reads `karthik_book` makes: the book's closed positions, then
    the SOL rate. No engine, because the thing under test is arithmetic."""

    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    async def scalars(self, _statement: object) -> _Rows:
        return _Rows(self._rows)

    async def scalar(self, _statement: object) -> None:
        return None

    async def execute(self, _statement: object, _params: object = None) -> _Rows:
        # The later-exit comparison reads the price samples, which these
        # synthetic positions have none of: an empty result is the honest
        # answer and leaves the figures under test alone.
        return _Rows([])


class _Pos:
    """A closed paper position, with only the columns the endpoint reads."""

    def __init__(self, symbol: str, opened: datetime, ret: float) -> None:
        self.symbol = symbol
        self.opened_at = opened
        self.closed_at = opened + timedelta(minutes=5)
        self.net_return = ret
        self.pnl_usd = Decimal(str(100 * ret))
        self.impact_open = self.impact_close = Decimal(0)
        self.liq_open_usd = Decimal(100_000)


def _no_hold_cache() -> None:
    """The hold comparison caches at module level; a test must not inherit one
    run's answer or leave its own behind for the next."""
    from app.labs.graduation import api as _api
    _api._HOLDS = None


async def test_karthik_book_counts_only_the_trades_it_could_fund() -> None:
    """Every figure describes the SAME trades: the ones the book bought.

    A $500 book at $100 a ticket funds five positions at once, so when six
    signals overlap the sixth is skipped. Counting wins and rugs over all the
    arm's trades while the balance counted only the funded ones is what made
    the page read "0 rugs of 11 trades, 12 wins" on its first afternoon: it
    would credit the book with dodging a rug it merely had no money for.
    """
    from app.labs.graduation.api import karthik_book

    _no_hold_cache()
    start = next(s for s in config.FRESH_BOOKS
                 if s.book == "KARTHIK_QUIET_5M").start
    # Eight signals inside one five-minute hold: the book can fund five.
    rows = [_Pos(f"C{i}", start + timedelta(seconds=30 * i), 0.02)
            for i in range(8)]
    # The last one is a rug, and it is one the book cannot afford.
    rows[-1].net_return = -0.99
    rows[-1].pnl_usd = Decimal("-99")

    book = await karthik_book(db=_StubDb(rows))  # type: ignore[arg-type]

    assert book["trades"] + book["skipped"] == len(rows)
    assert book["trades"] == 5 and book["skipped"] == 3
    # The three it could not buy are absent from every count, including the
    # rug -- which it did not dodge, it just had no money left.
    assert book["wins"] == 5
    assert book["rugs"] == 0
    assert len(book["trades_list"]) == 5
    assert {t["symbol"] for t in book["trades_list"]} == {f"C{i}" for i in range(5)}
    # The invariant the defect broke: no figure may exceed the trade count.
    assert book["wins"] <= book["trades"] and book["rugs"] <= book["trades"]


async def test_karthik_days_are_24h_from_the_open_not_calendar_days() -> None:
    """The book opened at noon, so calendar days would make its first and last
    half-length and every comparison between days a lie.

    The percentage is of the balance each day OPENED with, so the days
    multiply out to the book's own total instead of each being measured off a
    different number.
    """
    from app.labs.graduation.api import karthik_book

    _no_hold_cache()
    start = next(s for s in config.FRESH_BOOKS
                 if s.book == "KARTHIK_QUIET_5M").start
    rows = [
        _Pos("A", start + timedelta(hours=1), 0.10),        # day 1
        _Pos("B", start + timedelta(hours=20), 0.10),       # day 1
        # Opened on day 1, sold on day 2: it counts where the money landed.
        _Pos("C", start + timedelta(hours=23, minutes=58), 0.10),
        _Pos("D", start + timedelta(hours=30), -0.50),      # day 2
    ]
    book = await karthik_book(db=_StubDb(rows))  # type: ignore[arg-type]
    days = {d["n"]: d for d in book["days"]}

    assert [d["n"] for d in book["days"]] == sorted(days, reverse=True)
    assert days[1]["trades"] == 2                      # not 3: C closed on day 2
    assert days[2]["trades"] == 2
    # Day 1: two $100 tickets at +10% on a $500 book.
    assert days[1]["pnl_usd"] == Decimal("20.00")
    assert days[1]["pct"] == Decimal("4.00")           # 20 of the 500 it opened with
    assert days[1]["balance_usd"] == Decimal("520.00")
    # Day 2 is measured off 520, the balance it inherited -- not off 500.
    assert days[2]["pnl_usd"] == Decimal("-40.00")     # +10 then -50
    assert days[2]["pct"] == Decimal("-7.69")
    # The days reconcile to the book: last day's balance is the book's balance.
    assert days[max(days)]["balance_usd"] == book["balance_usd"]
