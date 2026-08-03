"""Attaching curve position to a market window.

The two series come from different sources on different clocks. This is the
join that decides which curve reading an observation is allowed to see, and
getting it wrong is not visible in the output — a signal justified by a reading
taken after the observation still looks like a signal. So the property under
test is the *direction* of the join, not the values it produces.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.curve import TokenCurveSnapshot
from app.opportunities.repository import as_of_progress

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
INITIAL_REAL_TOKENS = 793_100_000_000_000
TOTAL_SUPPLY = 1_000_000_000_000_000


def snapshot(
    *,
    at: datetime,
    real_token: int = INITIAL_REAL_TOKENS,
    complete: bool = False,
    virtual_sol: int = 30_000_000_000,
) -> TokenCurveSnapshot:
    return TokenCurveSnapshot(
        mint_address="mint",
        captured_at=at,
        virtual_token_reserves=Decimal(1_073_000_000_000_000),
        virtual_sol_reserves=Decimal(virtual_sol),
        real_token_reserves=Decimal(real_token),
        real_sol_reserves=Decimal(0),
        token_total_supply=Decimal(TOTAL_SUPPLY),
        complete=complete,
    )


def minutes(offset: int) -> datetime:
    return NOW + timedelta(minutes=offset)


class TestAsOfProgress:
    def test_no_curve_data_leaves_every_observation_unknown(self) -> None:
        """Absent is `None`, never zero. Zero would claim nobody has bought."""
        assert as_of_progress([minutes(0), minutes(1)], []) == [None, None]

    def test_an_observation_reads_the_newest_curve_at_or_before_it(self) -> None:
        half = INITIAL_REAL_TOKENS // 2
        series = [
            snapshot(at=minutes(0), real_token=INITIAL_REAL_TOKENS),
            snapshot(at=minutes(5), real_token=half),
        ]

        values = as_of_progress([minutes(1), minutes(5), minutes(9)], series)

        assert values[0] == Decimal(0)  # sees the first reading only
        assert values[1] and values[1] > Decimal("0.4")  # the exact-tie reading
        assert values[2] == values[1]  # carried forward until a newer one lands

    def test_a_later_curve_reading_never_reaches_an_earlier_observation(self) -> None:
        """The leak that would make a replay disagree with production.

        An observation must be explainable by data that existed when it was
        taken. Carrying a reading backwards would let a signal be justified by
        the future, and the disagreement would only ever surface in backtests.
        """
        series = [snapshot(at=minutes(10), real_token=0, complete=True)]

        values = as_of_progress([minutes(0), minutes(9), minutes(10)], series)

        assert values == [None, None, Decimal(1)]

    def test_each_observation_takes_the_reading_that_was_current_for_it(self) -> None:
        """A newer reading displaces the carried one rather than merging with it.

        The provider reads this series as movement, so a value that outlives
        the reading it came from is the difference between a filling curve and
        a stalled one.
        """
        quarter = INITIAL_REAL_TOKENS // 4
        series = [
            snapshot(at=minutes(0), real_token=INITIAL_REAL_TOKENS),
            snapshot(at=minutes(5), real_token=quarter),
            snapshot(at=minutes(10), real_token=0),
        ]

        values = as_of_progress([minutes(1), minutes(6), minutes(11)], series)

        assert values == [Decimal(0), Decimal("0.75"), Decimal(1)]

    def test_a_completed_curve_reads_as_full(self) -> None:
        series = [snapshot(at=minutes(0), real_token=0, complete=True)]

        assert as_of_progress([minutes(1)], series) == [Decimal(1)]

    def test_the_window_length_is_preserved(self) -> None:
        """One value per observation, always — the caller zips them strictly."""
        moments = [minutes(index) for index in range(7)]

        assert len(as_of_progress(moments, [snapshot(at=minutes(3))])) == len(moments)
