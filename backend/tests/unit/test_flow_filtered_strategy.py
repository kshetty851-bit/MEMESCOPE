"""The flow filter, and the arithmetic behind it.

The whole experiment is one entry condition, so the condition is what these
pin. If the filter admits a token it should refuse, the wallet is not testing
the hypothesis it claims to test — it is running V6-07 with extra steps.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app import flow_features
from app.paper.models import Candidate
from app.paper.strategy import FLOW_FILTERED_LIQ500K_TP150_V1 as S
from app.paper.strategy import registry

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


class _Snap:
    """Only the two counters `trade_flow` reads."""

    def __init__(self, buys, sells):
        self.buy_count_24h = buys
        self.sell_count_24h = sells


def _candidate(**over) -> Candidate:
    values = dict(
        mint_address="Mint111111111111111111111111111111111111111",
        rank=1,
        price_usd=Decimal("0.10"),
        observed_at=NOW,
        liquidity_usd=Decimal("700000"),
        market_cap=Decimal("60000000"),
        volume_24h=Decimal("50000"),
        sell_share_15m=Decimal("0.02"),
    )
    values.update(over)
    return Candidate(**values)


def _entry(c: Candidate):
    return S.entry_for(c, cash_available=Decimal("100"), now=NOW)


# --------------------------------------------------------------------------
# trade_flow: the number itself
# --------------------------------------------------------------------------


def test_sell_share_is_sells_over_all_trades() -> None:
    f = flow_features.trade_flow(_Snap(100, 25), _Snap(80, 20))
    assert f.sell_share == Decimal(5) / Decimal(25)   # 5 sells of 25 trades
    assert f.trade_count == 25


def test_counters_that_tick_backwards_clamp_at_zero() -> None:
    """The 24h counters slide, so an old trade can leave the window. A negative
    trade count is not information."""
    assert flow_features.counter_delta(90, 100) == 0


@pytest.mark.parametrize(
    ("last", "earlier"),
    [
        (None, _Snap(1, 1)),          # no current reading
        (_Snap(1, 1), None),          # nothing 15 minutes back
        (_Snap(None, 1), _Snap(1, 1)),  # a counter missing
    ],
)
def test_unmeasurable_flow_is_none_never_zero(last, earlier) -> None:
    """Zero would read as "nobody is selling", which is a claim nobody made."""
    assert flow_features.trade_flow(last, earlier).sell_share is None


def test_a_window_with_no_trades_is_undefined_not_calm() -> None:
    """An untraded token is not a token nobody is selling."""
    f = flow_features.trade_flow(_Snap(10, 5), _Snap(10, 5))
    assert f.sell_share is None
    assert f.trade_count == 0


# --------------------------------------------------------------------------
# the entry gate
# --------------------------------------------------------------------------


def test_it_admits_a_deep_pool_with_quiet_flow() -> None:
    e = _entry(_candidate())
    assert e is not None
    assert e.size_usd == Decimal(5)
    assert e.target_price == Decimal("0.10") * Decimal("1.50")
    assert e.expires_at == NOW + timedelta(hours=6)


def test_it_refuses_flow_above_the_ceiling() -> None:
    """0.244 was the dead_zero median. It must not get in."""
    assert _entry(_candidate(sell_share_15m=Decimal("0.244"))) is None


def test_the_ceiling_is_inclusive_at_its_stated_value() -> None:
    assert _entry(_candidate(sell_share_15m=Decimal("0.20"))) is not None
    assert _entry(_candidate(sell_share_15m=Decimal("0.201"))) is None


def test_unmeasured_flow_refuses_rather_than_admits() -> None:
    """The single most important line in the strategy.

    `None` means nobody observed the buy/sell mix. Admitting on it would turn
    every thin-data token into a pass, and thin data is exactly what the
    tokens this filter targets tend to have — so the failure would be
    concentrated on the cases the filter exists for.
    """
    assert _entry(_candidate(sell_share_15m=None)) is None


def test_it_still_enforces_v607s_own_liquidity_floor() -> None:
    assert _entry(_candidate(liquidity_usd=Decimal("499999"))) is None
    assert _entry(_candidate(liquidity_usd=None)) is None


def test_it_publishes_no_stop_loss() -> None:
    """Stops on these tokens filled near zero. An absent stop is the rule, not
    an oversight, so it must be absent on the position too."""
    assert S.exit_rules.stop_loss_multiple is None
    assert _entry(_candidate()).stop_price is None


def test_an_unpriced_token_is_not_a_free_one() -> None:
    assert _entry(_candidate(price_usd=Decimal(0))) is None


def test_it_declines_rather_than_part_filling_on_short_cash() -> None:
    assert S.entry_for(_candidate(), cash_available=Decimal("4.99"), now=NOW) is None


# --------------------------------------------------------------------------
# the registry
# --------------------------------------------------------------------------


def test_it_is_the_one_operational_strategy() -> None:
    """Asserted against what PRODUCTION constructs, not what pytest sees.

    An autouse fixture in `tests/conftest.py` forces the archived Track Record
    strategy operational for the whole suite — its own docstring notes this
    makes the "exactly one operational" invariant untestable from inside
    pytest, where it reads as two. So the fixture is undone here and restored
    afterwards, and the assertion is about the real registry.
    """
    from app.paper.strategy import PAPER_TRACK_RECORD_TP125_SL50_V1 as archived

    forced = archived.operational
    object.__setattr__(archived, "operational", False)
    try:
        assert registry.default.id == S.id
        assert [s.id for s in registry.all() if s.operational] == [S.id]
    finally:
        object.__setattr__(archived, "operational", forced)


def test_the_retired_strategy_is_declared_with_a_reason() -> None:
    """Retired, not deleted: a slot that changed hands should say so."""
    old = registry.get("universe_trailing_stop_25_v1")
    assert old is not None
    assert old.operational is False
    assert old.unavailable_reason


def test_it_is_behind_the_security_gate() -> None:
    """Membership in `SECURITY_GATED_STRATEGY_IDS` is what makes the repository
    refuse a position without fresh VERIFIED security evidence — a live mint
    authority or a live freeze authority.

    Leaving it out would drop the strongest anti-rug check from the one
    strategy built specifically to avoid rugs. The set names it as a literal
    string because it is declared above the strategy, so this asserts the two
    have not drifted apart.
    """
    from app.paper.strategy import SECURITY_GATED_STRATEGY_IDS

    assert S.id in SECURITY_GATED_STRATEGY_IDS


def test_karthik_can_never_be_bound_to_it() -> None:
    """§7 isolation: every paper strategy is forbidden to the Karthik wallet."""
    from app.karthik_ops.authority import FORBIDDEN_STRATEGY_IDS

    assert S.id in FORBIDDEN_STRATEGY_IDS
