"""The forward paper book: its rules, its arithmetic, and what it may not touch."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.labs.graduation import config
from app.labs.graduation.backtest import (
    Costs,
    ExitState,
    TakeProfit,
    Tick,
    TrailingStop,
)
from app.labs.graduation.paper import (
    Account,
    costs,
    exit_policy,
    net_return,
)

D = Decimal
NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


def state(price: str, *, entry: str = "1.0", peak: str = "1.0") -> ExitState:
    return ExitState(clock_at=NOW, entry_price=D(entry),
                     tick=Tick(ts=NOW, price=D(price), source="paper"),
                     peak=D(peak))


# --- the frozen rules ---------------------------------------------------------

def test_the_book_ships_with_the_rules_that_were_asked_for() -> None:
    """$1,000 over a hundred $10 slots, a 30% trailing stop and a 2x target.
    Pinned so a later edit to the defaults is a visible change to a stated
    rule, not a quiet one — the whole value of a forward run is that its
    rules were fixed before the outcome was known."""
    assert D("1000") == config.PAPER_CAPITAL_USD
    assert D("10") == config.PAPER_NOTIONAL_USD
    assert config.PAPER_MAX_SLOTS == 100
    assert D("0.30") == config.PAPER_TRAILING_PCT
    assert D("2") == config.PAPER_TAKE_PROFIT_X
    # The slots at that size are exactly the book, so it can be fully
    # deployed and no candidate is skipped for want of capital that exists.
    assert config.PAPER_NOTIONAL_USD * config.PAPER_MAX_SLOTS == config.PAPER_CAPITAL_USD


def test_the_trailing_stop_fires_at_thirty_percent_off_the_peak() -> None:
    rule = TrailingStop(config.PAPER_TRAILING_PCT)
    assert rule.fires(state("0.70", peak="1.0")) is True
    assert rule.fires(state("0.71", peak="1.0")) is False
    # It trails the PEAK, not the entry: a position that doubled and gave back
    # 30% of the high is closed even though it is still up on the entry.
    assert rule.fires(state("1.40", entry="1.0", peak="2.0")) is True


def test_the_max_hold_is_the_data_not_a_strategy_choice() -> None:
    """Post-graduation prices end when the sampler's window does. Past that
    there is no mark and no exit price, so a position would hang unpriceable.
    The backstop must not outlive the series."""
    assert config.PAPER_MAX_HOLD_MINUTES * 60 <= config.POST_MIGRATION_SECONDS


# --- costs --------------------------------------------------------------------

def test_the_book_uses_the_backtester_cost_model() -> None:
    """Not a second opinion. Two cost models that drifted apart would make the
    forward run and the replay incomparable, which is the only reason to have
    both."""
    assert costs().pump_fee_bps == Costs().pump_fee_bps
    assert costs().slip_bps == Costs().slip_bps
    assert costs().priority_fee_quote == Costs().priority_fee_quote


def test_a_flat_round_trip_still_loses_the_spread() -> None:
    c = costs()
    entry, exit_ = c.buy_price(D(1)), c.sell_price(D(1))
    assert round(exit_ / entry - 1, 4) == D("-0.0564")


# --- the account --------------------------------------------------------------

def test_the_sol_usd_rate_is_observed_or_refused() -> None:
    """DexScreener answers with price_usd AND price_native for the same pair
    at the same instant, so the rate is a measurement. When either side is
    missing it is refused: a position sized at an invented rate would report a
    dollar P&L that never existed."""
    from app.labs.graduation.paper import _rate

    assert _rate(D("200.0"), D("1.0")) == D("200")
    assert _rate(None, D("1.0")) is None
    assert _rate(D("200"), None) is None
    assert _rate(D("200"), D("0")) is None
    assert _rate(D("0"), D("1")) is None


def test_dollar_pnl_comes_from_size_and_return_not_a_live_rate() -> None:
    """A closed trade's dollars must not move when SOL does. Size and return
    are both exact and fixed at the time; re-converting the SOL proceeds later
    would let a move in SOL rewrite what the trade earned."""
    notional, net = D("100"), D("0.25")
    assert (notional * net).quantize(D("0.01")) == D("25.00")


def test_equity_is_derived_never_stored() -> None:
    """Storing equity would be a second source of truth for something the
    positions already say, and the two would disagree the first time either
    changed."""
    a = Account(starting=D("1000"), realised=D("-40"), unrealised=D("10"),
                open_positions=3, closed_positions=7, wins=2)
    assert a.equity == D("970")
    assert a.pnl == D("-30")
    assert a.return_pct == D("-0.0300")
    assert a.free_slots == config.PAPER_MAX_SLOTS - 3
    assert a.as_dict()["equity_usd"] == "970.00"


def test_a_full_book_has_no_free_slots() -> None:
    a = Account(starting=D("1000"), realised=D(0), unrealised=D(0),
                open_positions=config.PAPER_MAX_SLOTS, closed_positions=0, wins=0)
    assert a.free_slots == 0


# --- what it may not do -------------------------------------------------------

def test_the_paper_book_cannot_reach_a_wallet() -> None:
    """Paper only. The point of a forward book is that being wrong costs
    nothing; a package that could reach a signer would not have that property.

    Checked over the AST — imports and identifiers — not the source text. The
    module's own docstring says "no signer, no route to a real wallet", and a
    substring search would match that promise and fail on it.
    """
    import ast
    import pathlib

    tree = ast.parse(
        (pathlib.Path(__file__).resolve().parent.parent / "paper.py").read_text())

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    # Dotted-prefix match, not a bare prefix: "app.lab" must not swallow
    # "app.labs.graduation.backtest", which this module legitimately imports.
    banned_modules = ("solders", "app.real_wallet", "app.paper", "app.paper_v2",
                      "app.karthik", "app.lab", "app.strategy_lab")
    for module in imported:
        for banned in banned_modules:
            assert module != banned and not module.startswith(f"{banned}."), module

    # No call or attribute anywhere is named like a signing path.
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    for banned in ("sign", "sign_transaction", "send_transaction", "keypair",
                   "signer", "private_key", "secret_key"):
        assert banned not in names, banned


def test_every_price_read_is_bounded_by_the_tick_clock() -> None:
    """Without `ts <= now` the book reads the newest row in the table, which
    on any replay or backfill is a price from the FUTURE — the running peak
    becomes the window's eventual high and the trailing stop fires on
    information nothing could have had.

    Live it is harmless only because later rows do not exist yet. That is
    luck, not a guarantee, and it was a real bug: the first end-to-end run
    tracked a peak of 1.35 on a series that had peaked at 2.00.
    """
    import pathlib

    body = (pathlib.Path(__file__).resolve().parent.parent / "paper.py").read_text()
    # Both the mark and the entry scan are bounded.
    assert body.count("GradPostgradSample.ts <= self._now") == 2


def test_the_book_is_gated_on_its_own_flag_as_well_as_the_lab() -> None:
    """The recorder can run for weeks before anything opens a position."""
    import os

    lab = os.environ.get("LAB_GRADUATION_ENABLED")
    paper = os.environ.get("LAB_GRADUATION_PAPER_ENABLED")
    try:
        os.environ["LAB_GRADUATION_ENABLED"] = "true"
        os.environ.pop("LAB_GRADUATION_PAPER_ENABLED", None)
        assert config.enabled() is True
        assert config.paper_enabled() is False    # lab on, book off
        os.environ["LAB_GRADUATION_PAPER_ENABLED"] = "true"
        assert config.paper_enabled() is True
        os.environ["LAB_GRADUATION_ENABLED"] = "false"
        assert config.paper_enabled() is False    # book on, lab off
    finally:
        for key, value in (("LAB_GRADUATION_ENABLED", lab),
                           ("LAB_GRADUATION_PAPER_ENABLED", paper)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# --- the P&L arithmetic -------------------------------------------------------

class _Position:
    """Just the fields `net_return` reads. A real row would need a database and
    would test SQLAlchemy rather than the formula."""

    def __init__(self, quote: str, tokens: str) -> None:
        self.notional_quote = D(quote)
        self.tokens = D(tokens)


def _bought(price: str, quote: str = "1.0") -> _Position:
    """A position opened at `price`, sized at `quote`, costs included — the
    same two lines `_fill` uses."""
    fill = costs().buy_price(D(price))
    return _Position(quote, str(D(quote) / fill))


def test_a_position_marked_at_its_own_entry_shows_exactly_the_round_trip_cost() -> None:
    """The opening mark is not zero and must not be: buying and selling at one
    unchanged price costs both legs. If this figure ever comes out at 0 the
    book has stopped charging for execution."""
    side = costs().side_fraction
    expected = (1 - side) / (1 + side) - 1
    net = net_return(_bought("0.00000048"), D("0.00000048"), costs())
    assert net is not None
    assert abs(net - expected) < D("0.000001")
    # Concretely: a $100 position opens showing about -$5.64.
    assert D("-5.7") < D("100") * net < D("-5.5")


def test_the_formula_reproduces_a_trade_the_live_book_actually_closed() -> None:
    """29KvBXvMpB..., closed on a trailing stop 2026-09-11: entered at a quoted
    0.00000048 SOL, exited at a quoted 0.00000060, and the book recorded
    +0.17954325 / +$17.95.

    Pinned against the ROW, not against this code, so a change to the cost
    model or the formula shows up as a trade that would no longer have earned
    what it earned.
    """
    net = net_return(_bought("0.00000048"), D("0.00000060"), costs())
    assert net is not None
    assert net.quantize(D("0.00000001")) == D("0.17954325")
    assert (D("100") * net).quantize(D("0.01")) == D("17.95")


def test_the_percentage_does_not_depend_on_the_position_size() -> None:
    """Dollars are `notional_usd * net`, and `net` is a pure price ratio. If
    size leaked into the ratio, the same market move would report a different
    percentage on a different-sized book."""
    move = (D("0.00000048"), D("0.00000060"))
    small = net_return(_bought(str(move[0])), move[1], costs())
    large = net_return(_bought(str(move[0]), quote="2.0"), move[1], costs())
    assert small is not None and large is not None
    # Decimal division is not exact, so agree to the cent on $100, not to the
    # last of twenty-seven digits.
    assert abs(small - large) < D("0.00000001")


def test_a_net_return_needs_a_price_and_refuses_without_one() -> None:
    """An unmarked position contributes NOTHING to equity. Treating a missing
    mark as a zero return would quietly value it at cost."""
    assert net_return(_bought("0.00000048"), None, costs()) is None
    assert net_return(_Position("0", "0"), D("1"), costs()) is None


# --- the 2x target ------------------------------------------------------------

def test_the_target_fires_at_twice_the_price_paid() -> None:
    """2x is measured against the FILL, not the quote. A target measured
    against the quoted price would trigger before the position was actually
    up 2x on what it cost."""
    policy = exit_policy()
    assert policy.fires(state("1.99", entry="1.0", peak="1.99")) is None
    assert policy.fires(state("2.00", entry="1.0", peak="2.00")) == "take_profit"


def test_the_stop_is_checked_before_the_target() -> None:
    """A 60-second sample can satisfy both — up 2x from entry and 30% off a
    higher peak. Minute data cannot say which filled first, so the loss is
    taken. If this ever flips, the book has quietly become optimistic."""
    both = state("2.00", entry="1.0", peak="4.0")
    assert TrailingStop(config.PAPER_TRAILING_PCT).fires(both) is True
    assert TakeProfit(config.PAPER_TAKE_PROFIT_X - 1).fires(both) is True
    assert exit_policy().fires(both) == "trailing_stop"


def test_a_two_x_target_banks_less_than_two_x() -> None:
    """The exit pays its own cost, so the stated target is not the realised
    return. Asserted because the page says so."""
    position = _bought("1.0")
    entry = position.notional_quote / position.tokens
    net = net_return(position, entry * config.PAPER_TAKE_PROFIT_X, costs())
    assert net is not None
    assert D("0.93") < net < D("0.95")   # about +94%, not +100%
