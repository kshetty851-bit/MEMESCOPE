"""The Karthik rule, tested as a rule rather than as a code path.

Every case here is one sentence from the published strategy:

    $1,000 of capital. $10 per new Track Record token. Sell all of it at 1.25x.
    No stop loss. No time exit. Otherwise hold until the token is genuinely
    dead.

The negative cases matter more than the positive ones. It is easy to build a
wallet that exits at 1.25x; the hard part is a wallet that does *not* exit at
0.2x, does not exit after six hours, and does not exit into a print that no
buyer stands behind.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.karthik import rules
from app.karthik.rules import Decision, Hold, Observation

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
ENTRY = Decimal("0.001")
TARGET = rules.target_price_for(ENTRY)


def _obs(
    price: str | None,
    *,
    liquidity: str | None = "18000",
    age_seconds: int = 0,
    status: str = "trading",
) -> Observation:
    return Observation(
        price_usd=None if price is None else Decimal(price),
        liquidity_usd=None if liquidity is None else Decimal(liquidity),
        captured_at=NOW - timedelta(seconds=age_seconds),
        trading_status=status,
    )


def _hold(observation: Observation | None) -> Hold | None:
    return rules.hold_reason(
        observation, target_price=TARGET, now=NOW, max_age_seconds=900
    )


# --- The published numbers ---------------------------------------------------


def test_the_published_numbers_are_the_ones_in_the_code() -> None:
    """The strategy line on the page and the constants must be one thing.

    Asserted rather than trusted because these three numbers are the entire
    experiment; a drift between the page and the rule would invalidate every
    figure without breaking anything.
    """
    assert rules.STARTING_CAPITAL == Decimal("1000.00")
    assert rules.TRADE_SIZE == Decimal("10.00")
    assert rules.TAKE_PROFIT_MULTIPLE == Decimal("1.25")


def test_the_target_is_exactly_one_and_a_quarter_times_entry() -> None:
    assert rules.target_price_for(Decimal("0.001")) == Decimal("0.00125")


# --- Entry -------------------------------------------------------------------


def test_a_priced_tradeable_token_with_cash_is_entered() -> None:
    assert (
        rules.entry_decision(cash=Decimal("1000"), observation=_obs("0.001"))
        is Decision.ENTERED
    )


def test_exactly_one_trade_size_of_cash_is_enough() -> None:
    """$10.00 available buys a $10.00 position. The boundary is inclusive."""
    assert (
        rules.entry_decision(cash=Decimal("10.00"), observation=_obs("0.001"))
        is Decision.ENTERED
    )


def test_less_than_one_trade_size_skips_permanently() -> None:
    """A cent short is short.

    The decision is `SKIPPED_INSUFFICIENT_CASH` rather than a deferral, and the
    service records it in a ledger row that is never revisited. A missed
    opportunity remains missed — buying it later would price the entry hours
    after the signal and report a capture rate the wallet did not earn.
    """
    assert (
        rules.entry_decision(cash=Decimal("9.99"), observation=_obs("0.001"))
        is Decision.SKIPPED_INSUFFICIENT_CASH
    )


def test_no_cash_skips_even_when_the_market_is_perfect() -> None:
    assert (
        rules.entry_decision(cash=Decimal("0"), observation=_obs("0.001"))
        is Decision.SKIPPED_INSUFFICIENT_CASH
    )


@pytest.mark.parametrize(
    ("observation", "why"),
    [
        (None, "nothing has priced this mint"),
        (_obs(None), "a snapshot with no price is unpriced, not free"),
        (_obs("0"), "a zero price is not a price"),
        (_obs("0.001", liquidity=None), "no reported depth means no computable cost"),
        (_obs("0.001", liquidity="0"), "an empty pool cannot be bought into"),
        (_obs("0.001", status="inactive"), "the provider says the pool is gone"),
    ],
)
def test_an_unpriceable_opportunity_is_skipped_not_guessed(
    observation: Observation | None, why: str
) -> None:
    assert (
        rules.entry_decision(cash=Decimal("1000"), observation=observation)
        is Decision.SKIPPED_NO_MARKET
    ), why


# --- Exit: the target --------------------------------------------------------


def test_one_and_a_quarter_times_entry_is_the_target() -> None:
    """`None` means "the rule is satisfied, now go and get a real quote"."""
    assert _hold(_obs("0.00125")) is None


def test_one_and_a_quarter_times_entry_exactly_counts() -> None:
    assert rules.target_reached(_obs("0.00125"), target_price=TARGET) is True


def test_one_and_twenty_four_hundredths_holds() -> None:
    """1.24x is not 1.25x. There is no rounding in either direction."""
    assert _hold(_obs("0.00124")) is Hold.BELOW_TARGET


# --- Exit: the absent stop loss ---------------------------------------------


@pytest.mark.parametrize("multiple", ["1.10", "1.00", "0.80", "0.50", "0.20", "0.05"])
def test_every_price_below_the_target_holds(multiple: str) -> None:
    """There is no stop loss, so falling is not an exit at any depth.

    Parametrised over the exact ladder in the strategy: a wallet that closed at
    0.5x would be running a stop nobody published, and the experiment would be
    measuring a different rule than the one it claims.
    """
    price = ENTRY * Decimal(multiple)
    assert _hold(_obs(str(price))) is Hold.BELOW_TARGET


def test_time_is_not_an_exit() -> None:
    """Six hours, six days: the rule has no clock in it.

    `hold_reason` takes `now` only to judge whether a *reading* is fresh. There
    is no branch anywhere that consults how long a position has been open, and
    this asserts it by holding the price constant and moving time.
    """
    stale_but_falling = _obs("0.0009", age_seconds=0)
    assert _hold(stale_but_falling) is Hold.BELOW_TARGET
    later = rules.hold_reason(
        Observation(
            price_usd=Decimal("0.0009"),
            liquidity_usd=Decimal("18000"),
            captured_at=NOW + timedelta(hours=6),
            trading_status="trading",
        ),
        target_price=TARGET,
        now=NOW + timedelta(hours=6),
        max_age_seconds=900,
    )
    assert later is Hold.BELOW_TARGET


# --- Exit: executability, the rule that stops a rug becoming a win -----------


def test_a_two_x_print_into_a_drained_pool_is_not_an_exit() -> None:
    """The single most important negative in this module.

    A pool that has been drained can print any number. If the target were a
    price test alone, the rug would be recorded as a 25% win — the exact
    outcome that would make every published figure worthless.
    """
    assert _hold(_obs(str(ENTRY * 2), liquidity="0")) is Hold.TARGET_NOT_EXECUTABLE


def test_a_two_x_print_with_no_depth_reported_at_all_is_not_an_exit() -> None:
    assert _hold(_obs(str(ENTRY * 2), liquidity=None)) is Hold.TARGET_NOT_EXECUTABLE


def test_a_two_x_print_on_a_pool_the_provider_calls_inactive_is_not_an_exit() -> None:
    assert (
        _hold(_obs(str(ENTRY * 2), liquidity="18000", status="inactive"))
        is Hold.TARGET_NOT_EXECUTABLE
    )


# --- Death -------------------------------------------------------------------


def test_death_is_the_providers_word_and_not_a_price() -> None:
    assert rules.is_dead(_obs("0.0000001")) is False
    assert rules.is_dead(_obs("0.001", status="inactive")) is True


# --- Freshness ---------------------------------------------------------------


def test_a_stale_reading_holds_rather_than_deciding_anything() -> None:
    """Not fresh enough to buy or sell against, so the position simply waits.

    Note what this is *not*: a stale reading never closes a position. The only
    two closes are a target with a route behind it and a provider calling the
    pool dead.
    """
    assert _hold(_obs("0.00125", age_seconds=901)) is Hold.NO_FRESH_MARKET
    assert _hold(None) is Hold.NO_FRESH_MARKET


def test_a_reading_from_a_container_whose_clock_runs_ahead_is_fresh() -> None:
    """Clock skew between the enrichment worker and the reviewer is not staleness."""
    assert rules.is_fresh(_obs("0.001", age_seconds=-30), now=NOW, max_age_seconds=900)
