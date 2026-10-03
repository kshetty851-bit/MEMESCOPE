"""Karthik's fresh books: an arm's trades from a start, funded as that book's
own wallet would fund them."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.labs.graduation import config
from app.labs.graduation.api import fresh_book, start_walks
from app.labs.graduation.tournament import ARMS, CONTROLS, accepts

# the quiet pair on one start, then the other books
BQ, BQ4, *SWEEP = config.FRESH_BOOKS

#: The book the panel dropped on 2026-09-20, whose arm still runs as this
#: one's control: the wallet walk that fed it is what this file tests.
B75 = config.FreshBookSpec("BASE_75k_5m", BQ.start, Decimal(500), Decimal(100))


def test_the_page_shows_the_quiet_book_and_the_other_books() -> None:
    assert (BQ.book, BQ.capital_usd, BQ.ticket_usd) == (
        "BASE_75k_quiet_5m", Decimal(500), Decimal(100))
    # The four-minute twin is funded from the SAME minute with the same money:
    # its early trades are this book's own coins re-priced at four minutes
    # (`scripts/seed_quiet_4m.py`), so two walks from different starts would
    # not be comparable.
    assert (BQ4.book, BQ4.start, BQ4.capital_usd, BQ4.ticket_usd) == (
        "BASE_75k_quiet_4m", BQ.start, Decimal(500), Decimal(100))
    # The pump band book is the one band book left: the others lost and went
    # on 2026-10-01.
    assert [s.book for s in SWEEP] == [
        "BAND_55k_pump_5m",
        # Karthik's decision book (2026-09-22), judged 30 Sep, on which he has
        # said he will stake real money. It starts FORWARD — a backdated start
        # would let a run that already happened decide that.
        "B3_198k_5m",
        # The deep arm the real wallet mirrors (2026-09-23). Also forward.
        "B5_500k_flow_5m",
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
    assert all(s.capital_usd == Decimal(500) and s.ticket_usd == Decimal(100)
               for s in SWEEP if s.book != "KARTHIK_QUIET_5M")
    # Karthik's own book was resized at his request on 2026-09-24, 2026-09-25
    # and 2026-09-27 ($100 at $50, what he means to start the real wallet on),
    # and says so: the size and the moment it changed are both recorded, so
    # the page can mark what came before as in sample.
    assert (by_book["KARTHIK_QUIET_5M"].capital_usd,
            by_book["KARTHIK_QUIET_5M"].ticket_usd) == (Decimal(500), Decimal(50))
    # ...and on 2026-10-03 to $500 at $50, when it moved to $50k+ pools.
    assert (Decimal(100), Decimal(50)) == config.KARTHIK_PREVIOUS_SIZE
    assert (by_book["KARTHIK_QUIET_5M"].start < config.KARTHIK_RESIZED_AT
            < config.KARTHIK_JUDGE_AT)
    arms = [next(a for a in ARMS if a.name == s.book) for s in SWEEP]
    assert [a.hold for a in arms] == [5, 5, 5, 5]
    assert [a.quiet for a in arms] == [False, False, False, True]
    assert [a.entry for a in arms] == ["band55_pump", "liq_B3", "deep500_flow", "floor75"]
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

def test_the_band_arm_buys_between_55k_and_75k_and_nothing_else() -> None:
    """$55-75k, a band, not a floor. Only the pump.fun-only band arm is left
    (the others lost and went on 2026-10-01); the plain rule stays checkable
    on a stand-in."""
    from app.labs.graduation.tournament import Arm

    band = [a for a in ARMS if a.name.startswith("BAND_55k")]
    assert [a.name for a in band] == ["BAND_55k_pump_5m"]
    (pump,) = band
    assert (pump.entry, pump.hold, pump.quiet, pump.rug_blocked) == ("band55_pump", 5, False, False)
    assert pump.locked and not pump.is_control
    assert (pump.tp, pump.trail, pump.stop, pump.drain, pump.clock) == (None, None, None, None, "entry")
    plain = Arm("band", "band55", 5)
    kw = {"mint": "m", "open_at": BQ.start, "fdv": None, "sells": None, "reuse": None}
    assert not accepts(plain, liquidity=Decimal(54_999), **kw)
    assert accepts(plain, liquidity=Decimal(55_000), **kw)
    assert accepts(plain, liquidity=Decimal(74_999), **kw)
    assert not accepts(plain, liquidity=Decimal(75_000), **kw)   # the baseline's floor
    assert not accepts(plain, liquidity=None, **kw)


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
    """The reads `karthik_book` makes: the book's closed positions, the SOL
    rate, then his $50-75k arm's positions (none here). No engine, because the
    thing under test is arithmetic."""

    def __init__(self, rows: list[object]) -> None:
        self._rows = rows
        self._read = False

    async def scalars(self, _statement: object) -> _Rows:
        # Only the first read is the book's: the rest (the $50-75k arm) get
        # nothing, or every row would be counted twice.
        first, self._read = not self._read, True
        return _Rows(self._rows if first else [])

    async def scalar(self, _statement: object) -> None:
        return None

    async def execute(self, _statement: object, _params: object = None) -> _Empty:
        return _Empty()


class _Empty:
    """What the book's other reads get from the stub: nothing."""

    def all(self) -> list[object]:
        return []

    def one(self) -> tuple[int, int]:
        return (0, 0)

    def scalars(self) -> _Empty:
        return self

    def __iter__(self):
        return iter(())


class _Pos:
    """A closed paper position, with only the columns the endpoint reads."""

    def __init__(self, symbol: str, opened: datetime, ret: float) -> None:
        self.symbol = symbol
        self.mint = f"{symbol}pump"
        self.opened_at = opened
        self.graduated_at = opened - timedelta(seconds=30)   # a normal entry
        self.closed_at = opened + timedelta(minutes=5)
        self.net_return = ret
        self.pnl_usd = Decimal(str(100 * ret))
        self.impact_open = self.impact_close = Decimal(0)
        self.liq_open_usd = Decimal(200_000)   # inside the book's $150k+ range


async def test_karthik_book_buys_as_many_as_the_balance_allows() -> None:
    """Every figure describes the SAME trades: the ones the book bought.

    Since 2026-10-03 (replayed from day 1) the book buys every signal while a
    $50 ticket of its $500 is free: twelve signals inside one five-minute hold
    fund ten, the rug among them included, and the last two find no money.
    One more after the first ten have closed is free again, so it is bought.
    """
    from app.labs.graduation.api import karthik_book

    start = next(s for s in config.FRESH_BOOKS
                 if s.book == "KARTHIK_QUIET_5M").start
    rows = [_Pos(f"C{i:02d}", start + timedelta(seconds=10 * i), 0.02)
            for i in range(12)]
    rows[3].net_return = -0.99
    rows[3].pnl_usd = Decimal("-99")
    rows.append(_Pos("LATER", rows[-1].closed_at, 0.02))

    book = await karthik_book(db=_StubDb(rows))  # type: ignore[arg-type]

    assert (book["trades"], book["skipped"], book["busy_skipped"]) == (11, 2, 0)
    assert book["trades_list"][0]["symbol"] == "LATER"
    assert (book["wins"], book["rugs"]) == (10, 1)
    assert book["one_at_a_time_since"] is None and book["many_at_once_since"]


async def test_karthik_days_are_24h_from_the_open_not_calendar_days() -> None:
    """The book opened at noon, so calendar days would make its first and last
    half-length and every comparison between days a lie.

    The percentage is of the balance each day OPENED with, so the days
    multiply out to the book's own total instead of each being measured off a
    different number.
    """
    from app.labs.graduation.api import karthik_book

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
    # Day 1: two $50 tickets at +10% on a $500 book.
    assert days[1]["pnl_usd"] == Decimal("10.00")
    assert days[1]["pct"] == Decimal("2.00")           # 10 of the 500 it opened with
    assert days[1]["balance_usd"] == Decimal("510.00")
    # Day 2 is measured off 510, the balance it inherited -- not off 500.
    assert days[2]["pnl_usd"] == Decimal("-20.00")     # +5 then -25
    assert days[2]["pct"] == Decimal("-3.92")
    # The days reconcile to the book: last day's balance is the book's balance.
    assert days[max(days)]["balance_usd"] == book["balance_usd"]


async def test_the_public_summary_gives_headline_figures_and_nothing_else() -> None:
    """The homepage is public, so this is everything anyone without the site
    code can learn about Karthik's Lab: no trades, no coins, no timings."""
    from app.labs.graduation import api as _api
    from app.middleware.alpha_access import AlphaAccessMiddleware

    _api._KARTHIK_PUBLIC = None
    start = next(s for s in config.FRESH_BOOKS if s.book == "KARTHIK_QUIET_5M").start
    rows = [_Pos("C0", start + timedelta(hours=1), 0.10)]
    out = await _api.karthik_summary(db=_StubDb(rows))  # type: ignore[arg-type]
    assert set(out) == {"started_at", "judge_at", "capital_usd", "ticket_usd", "balance_usd",
                        "pnl_usd", "pnl_pct", "trades", "wins", "rugs"}
    assert out["pnl_usd"] == Decimal("5.00")           # one $50 ticket at +10%
    assert out["pnl_pct"] == Decimal("1.00")           # of the $500 it started with
    # Only that one path opens; the full book and anything beside it stay shut.
    exempt = AlphaAccessMiddleware._is_exempt
    assert exempt("/api/v1/labs/graduation/karthik/summary")
    assert not exempt("/api/v1/labs/graduation/karthik")
    assert not exempt("/api/v1/labs/graduation/karthik/summary/x")
    assert not exempt("/api/v1/real-wallet/status")
    _api._KARTHIK_PUBLIC = None



async def test_the_book_counts_only_its_pool_range_but_the_checks_see_every_size() -> None:
    """The book counts $50k-and-up pools (2026-10-03). Anything under that is
    never the book's, even if a row for it reaches this read; the checks
    beside the book still see every size."""
    from app.labs.graduation.api import karthik_book

    start = next(s for s in config.FRESH_BOOKS if s.book == "KARTHIK_QUIET_5M").start
    shallow = _Pos("SHALLOW", start + timedelta(hours=1), -0.99)  # $40k rug, not the book's
    shallow.liq_open_usd = Decimal(40_000)
    deep = _Pos("DEEP", start + timedelta(hours=2), 0.10)            # $400k: the book's
    deep.liq_open_usd = Decimal(400_000)
    book = await karthik_book(db=_StubDb([shallow, deep]))  # type: ignore[arg-type]

    assert book["pools_usd"] == [50_000, None]
    assert "$50k and up" in book["rule"]
    assert (book["trades"], book["rugs"]) == (1, 0)
    assert [(t["symbol"], t["mint"]) for t in book["trades_list"]] == [("DEEP", "DEEPpump")]
    _, now = _grid(book)
    # The grid starts at $25k (2026-10-03): the $40k rug is in that column only,
    # bought first and sold before the $400k pool came.
    assert (now[25_000]["trades"], now[25_000]["rugs"]) == (2, 1)
    # The $400k pool is in every other floor's column, not the $100k-$150k band's.
    assert all((c["trades"], c["rugs"]) == (1, 0) for k, c in now.items()
               if not isinstance(k, tuple) and k >= 50_000)
    assert (now[(100_000, 150_000)]["trades"], now[(100_000, 150_000)]["rugs"]) == (0, 0)


async def test_every_closed_trade_is_listed_not_just_the_latest_sixty() -> None:
    """Karthik, 2026-09-27: 'show all closed trades, not only 60'. Newest first,
    each with its mint so the page can link it to the exchange."""
    from app.labs.graduation.api import karthik_book

    start = next(s for s in config.FRESH_BOOKS if s.book == "KARTHIK_QUIET_5M").start
    rows = [_Pos(f"C{i}", start + timedelta(minutes=10 * i), 0.01) for i in range(75)]
    book = await karthik_book(db=_StubDb(rows))  # type: ignore[arg-type]
    assert len(book["trades_list"]) == book["trades"] == 75
    assert book["trades_list"][0]["symbol"] == "C74"
    assert all(t["mint"].endswith("pump") for t in book["trades_list"])


def _grid(book: dict) -> tuple[list, dict]:
    """(columns, the current size's cells by column): a floor's key is its
    floor, a band's is (floor, cap)."""
    floors = [f["floor_usd"] if f.get("cap_usd") is None else (f["floor_usd"], f["cap_usd"])
              for f in book["whatif"]["floors"]]
    now = next(r for r in book["whatif"]["sizes"] if r["current"])
    return floors, dict(zip(floors, now["cells"], strict=True))


async def test_the_grid_is_every_size_by_every_pool_floor() -> None:
    """Karthik, 2026-09-27: one table, sizes down, pool floors across, the
    book's own column marked ($50k+ since 2026-10-03). Each size on ten
    times its size (2026-10-03)."""
    from app.labs.graduation.api import karthik_book

    start = next(s for s in config.FRESH_BOOKS if s.book == "KARTHIK_QUIET_5M").start
    book = await karthik_book(db=_StubDb([_Pos("A", start + timedelta(hours=1), 0.10)]))  # type: ignore[arg-type]
    w = book["whatif"]
    assert [(f["floor_usd"], f["cap_usd"]) for f in w["floors"]] == [
        (25_000, None), (50_000, None), (75_000, None), (100_000, 150_000),
        (100_000, None), (150_000, None), (200_000, None)]
    assert [f["floor_usd"] for f in w["floors"] if f["book"]] == [50_000]
    assert [(r["ticket_usd"], r["capital_usd"]) for r in w["sizes"]] == [
        (10, 100), (20, 200), (25, 250), (50, 500), (100, 1000), (200, 2000)]
    assert [r["current"] for r in w["sizes"]] == [False, False, False, True, False, False]
    assert all(len(r["cells"]) == 7 for r in w["sizes"])
    # A $200k pool at +10%: every floor up to $200k took it.
    floors, now = _grid(book)
    # A $200k pool: every floor up to $200k took it; the $100k-$150k band did not.
    assert [now[f]["trades"] for f in floors] == [1, 1, 1, 0, 1, 1, 1]
    assert now[50_000]["pnl_usd"] == Decimal("5.00")                 # $50 at +10%
    assert w["sizes"][-1]["cells"][0]["pnl_usd"] == Decimal("20.00")  # $200 at +10%
    # $25k+ and $50k+ include the arms' replayed rows, and say so.
    assert [f["replayed_below"] for f in w["floors"]][:3] == [True, True, False]
    # The second table (2026-10-03): the same sizes on ten times their size.
    assert [(r["ticket_usd"], r["capital_usd"]) for r in w["sizes_wide"]] == [
        (10, 100), (20, 200), (25, 250), (50, 500), (100, 1000), (200, 2000)]
    # Counted from 1 Oct (2026-10-03): a trade on the book's first day is not in it.
    wide = w["sizes_wide"][-1]["cells"][0]
    assert (wide["trades"], wide["balance_usd"]) == (0, Decimal("2000.00"))
    assert w["wide_from"] == "2026-09-30T20:00:00+00:00"


async def test_each_floor_buys_only_its_own_pools() -> None:
    """Each cell is its own walk over the pools at or above its floor, so a
    floor that never spent on the shallow coin still buys the deep one."""
    from app.labs.graduation.api import karthik_book

    start = next(s for s in config.FRESH_BOOKS if s.book == "KARTHIK_QUIET_5M").start
    shallow = _Pos("SHALLOW", start + timedelta(hours=1), 0.01)
    shallow.liq_open_usd = Decimal(100_000)
    deep = _Pos("DEEP", start + timedelta(hours=1, minutes=2), -0.99)  # SHALLOW still held
    deep.liq_open_usd = Decimal(600_000)
    book = await karthik_book(db=_StubDb([shallow, deep]))  # type: ignore[arg-type]

    assert (book["trades"], book["rugs"], book["busy_skipped"]) == (2, 1, 0)
    _, now = _grid(book)
    assert (now[50_000]["trades"], now[50_000]["rugs"]) == (2, 1)   # the book's column
    assert (now[75_000]["trades"], now[75_000]["rugs"]) == (2, 1)
    assert (now[150_000]["trades"], now[150_000]["rugs"]) == (1, 1)
    assert (now[200_000]["trades"], now[200_000]["rugs"]) == (1, 1)


async def test_a_coin_bought_more_than_two_minutes_after_graduating_never_happened() -> None:
    """The entry guard (2026-09-27), replayed from day 1: EVO was bought 186s
    after graduating and its creator dumped inside the late hold."""
    from app.labs.graduation.api import karthik_book

    start = next(s for s in config.FRESH_BOOKS if s.book == "KARTHIK_QUIET_5M").start
    evo = _Pos("EVO", start + timedelta(hours=1), -1.0)
    evo.graduated_at = evo.opened_at - timedelta(seconds=186)
    edge = _Pos("EDGE", start + timedelta(hours=2), 0.02)          # exactly 120s: kept
    edge.graduated_at = edge.opened_at - timedelta(seconds=120)
    unknown = _Pos("UNKNOWN", start + timedelta(hours=3), 0.02)    # no graduation time
    unknown.graduated_at = None
    book = await karthik_book(db=_StubDb([evo, edge, unknown]))  # type: ignore[arg-type]

    assert [t["symbol"] for t in book["trades_list"]] == ["EDGE"]
    assert (book["trades"], book["rugs"]) == (1, 0)
    assert book["max_entry_age_s"] == 120 and book["quiet_max_txs"] == 100
    _, now = _grid(book)
    assert now[75_000]["trades"] == 1


async def test_coins_opened_in_the_same_instant_are_always_taken_in_one_order() -> None:
    """Replayed rows share a timestamp; when the cash runs out among them, the
    coin left over must not depend on the order the database returns them in
    (2026-10-03: the book's figures moved between two reads of the same data)."""
    from app.labs.graduation.api import karthik_book

    start = next(s for s in config.FRESH_BOOKS if s.book == "KARTHIK_QUIET_5M").start
    at = start + timedelta(hours=1)
    coins = [_Pos(f"C{i:02d}", at, 0.01 * i) for i in range(11)]   # 11 tickets, room for 10
    one = await karthik_book(db=_StubDb(coins))  # type: ignore[arg-type]
    two = await karthik_book(db=_StubDb(list(reversed(coins))))  # type: ignore[arg-type]
    taken = sorted(t["symbol"] for t in one["trades_list"])
    assert taken == [f"C{i:02d}" for i in range(10)]
    assert taken == sorted(t["symbol"] for t in two["trades_list"])
    assert one["balance_usd"] == two["balance_usd"]
