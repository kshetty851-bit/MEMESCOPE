"""Meme Lifecycle Lab — the paper ledger's rules.

The ledger is where "a strategy fired" becomes "a strategy could have done
this with $1,000". Every refusal must leave a record, fees must reach cash,
and an unpriced holding must leave equity unknown rather than zero.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.lifecycle_lab.config import PortfolioConfig
from app.lifecycle_lab.domain import (
    REAL_TRADING,
    AgeBucket,
    Arm,
    DivergenceCase,
    ExitReason,
    LifecycleState,
)
from app.lifecycle_lab.exits import ExitSignal
from app.lifecycle_lab.portfolio import (
    REJECT_ALREADY_HOLDING_MINT,
    REJECT_INSUFFICIENT_CASH,
    REJECT_MAX_DEPLOYED,
    REJECT_MAX_OPEN,
    REJECT_NO_PRICE,
    EntryRequest,
    PaperTrade,
    Portfolio,
    Rejection,
    trade_key,
)

pytestmark = pytest.mark.unit

T0 = datetime(2026, 9, 1, tzinfo=UTC)


def req(
    mint: str,
    *,
    price: Decimal | None = Decimal("1"),
    at: datetime = T0,
    liquidity: Decimal | None = None,
) -> EntryRequest:
    return EntryRequest(
        at=at,
        arm=Arm.BASELINE,
        meme_id="m1",
        mint_address=mint,
        price=price,
        liquidity_usd=liquidity,
        market_cap=None,
        token_age_seconds=None,
        age_bucket=AgeBucket.UNKNOWN,
        lifecycle_state=LifecycleState.UNKNOWN,
        divergence_case=DivergenceCase.NONE,
        entry_reason="conditions_met",
    )


def signal(price: Decimal, at: datetime, liquidity: Decimal | None = None) -> ExitSignal:
    return ExitSignal(
        reason=ExitReason.TAKE_PROFIT,
        at=at,
        fill_price=price,
        observed_price=price,
        trigger_price=price,
        liquidity_usd=liquidity,
    )


def test_defaults_are_the_published_book() -> None:
    """$1,000 / $10 / 5 open / $50 deployed — the design's numbers, so a
    result is comparable to the spec it was registered under."""
    cfg = PortfolioConfig()
    assert cfg.starting_capital == Decimal("1000")
    assert cfg.position_size == Decimal("10")
    assert cfg.max_open_positions == 5
    assert cfg.max_deployed == Decimal("50")
    assert REAL_TRADING is False


def test_entry_charges_fees_to_cash_and_sizes_at_ten_dollars() -> None:
    """Fees are cash, not a footnote: cash falls by size + entry costs."""
    book = Portfolio(PortfolioConfig())
    trade = book.try_open(req("A", price=Decimal("0.5")))
    assert isinstance(trade, PaperTrade)
    assert trade.size_usd == Decimal("10")
    assert trade.quantity == Decimal("20")
    # Unknown depth → flat model: 0.3% fee + 3% flat slippage on $10.
    assert trade.cost_model == "flat"
    assert trade.entry_fees_usd == Decimal("0.33")
    assert book.cash == Decimal("1000") - Decimal("10.33")
    assert book.deployed == Decimal("10")


def test_known_liquidity_uses_constant_product_model() -> None:
    book = Portfolio(PortfolioConfig())
    trade = book.try_open(req("A", liquidity=Decimal("20000")))
    assert isinstance(trade, PaperTrade)
    assert trade.cost_model == "constant_product"
    # fee 0.03 + slippage 0.10 + impact 10 * 10/10000 = 0.01
    assert trade.entry_fees_usd == Decimal("0.03") + Decimal("0.10") + Decimal("0.01")


def test_max_open_is_five_and_rejections_are_recorded() -> None:
    """A sixth entry is refused with a reason — never silently dropped."""
    book = Portfolio(PortfolioConfig(max_deployed=Decimal("1000")))
    for i in range(5):
        assert isinstance(book.try_open(req(f"M{i}")), PaperTrade)
    sixth = book.try_open(req("M5"))
    assert isinstance(sixth, Rejection)
    assert sixth.reason == REJECT_MAX_OPEN
    assert book.rejections == [sixth]


def test_max_deployed_caps_capital_at_risk() -> None:
    book = Portfolio(PortfolioConfig(max_open_positions=10, max_deployed=Decimal("30")))
    for i in range(3):
        assert isinstance(book.try_open(req(f"M{i}")), PaperTrade)
    fourth = book.try_open(req("M3"))
    assert isinstance(fourth, Rejection) and fourth.reason == REJECT_MAX_DEPLOYED


def test_default_book_never_deploys_more_than_fifty() -> None:
    book = Portfolio(PortfolioConfig())
    for i in range(20):
        book.try_open(req(f"M{i}"))
    assert book.deployed == Decimal("50")
    assert len(book.open_trades) == 5
    assert len(book.rejections) == 15


def test_insufficient_cash_includes_entry_costs() -> None:
    """$10 of cash cannot buy a $10 position plus its fees."""
    book = Portfolio(PortfolioConfig(starting_capital=Decimal("10")))
    result = book.try_open(req("A"))
    assert isinstance(result, Rejection) and result.reason == REJECT_INSUFFICIENT_CASH
    assert book.cash == Decimal("10")


def test_one_open_position_per_mint() -> None:
    book = Portfolio(PortfolioConfig())
    assert isinstance(book.try_open(req("A")), PaperTrade)
    again = book.try_open(req("A", at=T0 + timedelta(minutes=5)))
    assert isinstance(again, Rejection) and again.reason == REJECT_ALREADY_HOLDING_MINT


def test_no_price_is_a_rejection_not_a_fill() -> None:
    book = Portfolio(PortfolioConfig())
    for price in (None, Decimal(0)):
        r = book.try_open(req("A", price=price))
        assert isinstance(r, Rejection) and r.reason == REJECT_NO_PRICE
    assert book.cash == Decimal("1000")


def test_close_books_pnl_net_of_both_sides() -> None:
    """pnl = proceeds - exit costs - size - entry costs, and cash agrees."""
    book = Portfolio(PortfolioConfig())
    trade = book.try_open(req("A", price=Decimal("1")))
    assert isinstance(trade, PaperTrade)
    closed = book.close(trade.trade_key, signal(Decimal("2"), T0 + timedelta(hours=1)))
    gross = Decimal("20")
    exit_cost = gross * Decimal("0.033")
    assert closed.exit_fees_usd == exit_cost
    assert closed.pnl_usd == gross - exit_cost - Decimal("10.33")
    assert closed.status == "closed"
    assert book.cash == Decimal("1000") + closed.pnl_usd
    assert book.realized_pnl == closed.pnl_usd
    assert closed.evidence_timeline[-1]["kind"] == "exit:take_profit"


def test_equity_is_none_when_any_open_position_is_unpriced() -> None:
    """An unpriced holding is unmeasured, not worthless (paper/metrics.py)."""
    book = Portfolio(PortfolioConfig())
    a = book.try_open(req("A"))
    b = book.try_open(req("B"))
    assert isinstance(a, PaperTrade) and isinstance(b, PaperTrade)
    snap = book.snapshot(T0, {"A": Decimal("1"), "B": None})
    assert snap.equity is None
    assert snap.unrealized_pnl is None
    assert snap.drawdown is None
    assert snap.cash == book.cash
    priced = book.snapshot(T0, {"A": Decimal("1"), "B": Decimal("1")})
    assert priced.equity == book.cash + Decimal("20")


def test_drawdown_tracks_running_peak_of_known_equity() -> None:
    book = Portfolio(PortfolioConfig())
    trade = book.try_open(req("A"))
    assert isinstance(trade, PaperTrade)
    up = book.snapshot(T0, {"A": Decimal("3")})
    assert up.equity is not None and up.peak_equity == up.equity
    unknown = book.snapshot(T0 + timedelta(minutes=5), {"A": None})
    assert unknown.peak_equity == up.peak_equity  # unknown never moves the peak
    down = book.snapshot(T0 + timedelta(minutes=10), {"A": Decimal("1")})
    assert down.equity is not None
    assert down.drawdown == (up.equity - down.equity) / up.equity


def test_end_of_data_marks_without_filling() -> None:
    book = Portfolio(PortfolioConfig())
    book.try_open(req("A"))
    (marked,) = book.mark_end_of_data()
    assert marked.exit_reason is ExitReason.END_OF_DATA
    assert marked.status == "open"
    assert marked.exit_price is None and marked.pnl_usd is None


def test_trade_key_is_deterministic() -> None:
    assert trade_key(Arm.BASELINE, "A", T0) == trade_key(Arm.BASELINE, "A", T0)
    assert trade_key(Arm.BASELINE, "A", T0) != trade_key(Arm.CONTROL_D_COMBINED, "A", T0)


def test_trade_to_dict_is_json_safe() -> None:
    import json

    book = Portfolio(PortfolioConfig())
    trade = book.try_open(replace(req("A"), entry_features={"x": "1"}))
    assert isinstance(trade, PaperTrade)
    json.dumps(trade.to_dict())
    json.dumps(book.snapshot(T0, {"A": None}).to_dict())
