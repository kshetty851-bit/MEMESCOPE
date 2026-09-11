"""The forward paper book: its rules, its arithmetic, and what it may not touch."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.labs.graduation import config
from app.labs.graduation.backtest import Costs, ExitState, Tick, TrailingStop
from app.labs.graduation.paper import Account, costs

D = Decimal
NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


def state(price: str, *, entry: str = "1.0", peak: str = "1.0") -> ExitState:
    return ExitState(clock_at=NOW, entry_price=D(entry),
                     tick=Tick(ts=NOW, price=D(price), source="paper"),
                     peak=D(peak))


# --- the frozen rules ---------------------------------------------------------

def test_the_book_ships_with_the_rules_that_were_asked_for() -> None:
    """$1,000 over ten $100 slots with a 30% trailing stop, in quote terms at
    roughly $200/SOL. Pinned so a later edit to the defaults is a visible
    change to a stated rule rather than a quiet one."""
    assert D("5.0") == config.PAPER_CAPITAL_QUOTE      # ~$1,000
    assert D("0.5") == config.PAPER_NOTIONAL_QUOTE     # ~$100
    assert config.PAPER_MAX_SLOTS == 10
    assert D("0.30") == config.PAPER_TRAILING_PCT


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
    assert costs().notional_quote == config.PAPER_NOTIONAL_QUOTE


def test_a_flat_round_trip_still_loses_the_spread() -> None:
    c = costs()
    entry, exit_ = c.buy_price(D(1)), c.sell_price(D(1))
    assert round(exit_ / entry - 1, 4) == D("-0.0564")


# --- the account --------------------------------------------------------------

def test_equity_is_derived_never_stored() -> None:
    """Storing equity would be a second source of truth for something the
    positions already say, and the two would disagree the first time either
    changed."""
    a = Account(starting=D("5.0"), realised=D("-0.4"), unrealised=D("0.1"),
                open_positions=3, closed_positions=7, wins=2)
    assert a.equity == D("4.7")
    assert a.free_slots == config.PAPER_MAX_SLOTS - 3


def test_a_full_book_has_no_free_slots() -> None:
    a = Account(starting=D("5.0"), realised=D(0), unrealised=D(0),
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
