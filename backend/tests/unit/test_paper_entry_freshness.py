"""The per-candidate freshness condition, and what it must not disturb.

Sits beside `test_paper_eligibility.py`, which owns the other seven conditions.
This file covers only the one added after 2026-08-21: a price can exist, carry
depth, and still be too old to buy against.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.paper import eligibility
from app.paper.eligibility import Observation, Refusal

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 21, 15, 0, 0, tzinfo=UTC)
MAX_AGE = timedelta(seconds=120)


def observation(*, age_seconds: float | None = 10.0, **overrides: object) -> Observation:
    fields: dict[str, object] = {
        "mint_address": "mint",
        "rank": 1,
        "has_snapshot": True,
        "observed_at": None if age_seconds is None else NOW - timedelta(seconds=age_seconds),
        "price_usd": Decimal("0.01"),
        "liquidity_usd": Decimal("50000"),
        "market_cap": Decimal("1000000"),
        "volume_24h": Decimal("20000"),
        "trading_status": "trading",
    }
    fields.update(overrides)
    return Observation(**fields)  # type: ignore[arg-type]


def judge(
    obs: Observation,
    *,
    now: datetime | None = NOW,
    max_age: timedelta | None = MAX_AGE,
):
    return eligibility.judge(
        obs, held_ever=set(), open_now=set(), now=now, max_snapshot_age=max_age
    )


class TestStaleCandidate:
    """3. A candidate priced too long ago is refused, and says why."""

    def test_a_stale_candidate_is_refused(self) -> None:
        verdict = judge(observation(age_seconds=3_600))
        assert verdict.eligible is False
        assert verdict.refused_for == Refusal.MARKET_DATA_STALE.value

    def test_a_fresh_candidate_still_qualifies(self) -> None:
        assert judge(observation(age_seconds=10)).eligible is True

    @pytest.mark.parametrize(
        ("age", "eligible"), [(119.0, True), (120.0, True), (121.0, False)]
    )
    def test_the_boundary_admits_exactly_the_limit(self, age: float, eligible: bool) -> None:
        """`>` rather than `>=`: a reading exactly at the limit is inside it.

        The opposite choice would refuse a candidate whose age equalled the
        published number, which reads as an off-by-one to anyone checking the
        gate against its own documentation.
        """
        assert judge(observation(age_seconds=age)).eligible is eligible

    def test_staleness_is_named_separately_from_no_price(self) -> None:
        """4, and the distinction the incident turned on.

        A token nobody has priced and a token whose price stopped updating two
        hours ago fail for different reasons and need different fixes. Folding
        them together would have reported the outage as "no market data",
        which is what the platform already said about tokens it had simply
        never seen.
        """
        assert judge(observation(has_snapshot=False, age_seconds=None)).refused_for == (
            Refusal.NO_MARKET_DATA.value
        )
        assert judge(observation(price_usd=None)).refused_for == Refusal.NO_PRICE.value
        assert judge(observation(age_seconds=9_000)).refused_for == (
            Refusal.MARKET_DATA_STALE.value
        )

    def test_an_old_price_is_refused_for_age_not_for_its_venue(self) -> None:
        """Order within `judge` decides which cause is reported.

        A stale reading of a token whose pool has since gone quiet would fail
        both conditions; naming the venue would send the reader after the
        token instead of after the feed.
        """
        verdict = judge(observation(age_seconds=9_000, liquidity_usd=Decimal(0)))
        assert verdict.refused_for == Refusal.MARKET_DATA_STALE.value


class TestUnchangedWithoutAClock:
    """The replay and the benchmark must keep judging history by its own terms."""

    def test_no_clock_means_no_staleness_condition(self) -> None:
        """A four-day-old observation is eligible when no `now` is supplied.

        This is what lets `replay` and `benchmark` walk historical readings
        without a wall-clock notion of stale leaking into a result that is
        supposed to be reproducible.
        """
        ancient = observation(age_seconds=4 * 24 * 3600)
        assert eligibility.judge(ancient, held_ever=set(), open_now=set()).eligible is True

    def test_a_max_age_without_a_clock_is_inert(self) -> None:
        assert judge(observation(age_seconds=9_000), now=None).eligible is True

    def test_a_clock_without_a_max_age_is_inert(self) -> None:
        assert judge(observation(age_seconds=9_000), max_age=None).eligible is True


class TestScreenKeepsItsContract:
    def test_screening_preserves_rank_order_and_counts_the_new_reason(self) -> None:
        rows = [
            observation(mint_address="fresh", rank=1, age_seconds=5),
            observation(mint_address="stale", rank=2, age_seconds=6_000),
            observation(mint_address="alsofresh", rank=3, age_seconds=30),
        ]
        verdicts = eligibility.screen(
            rows, held_ever=set(), open_now=set(), now=NOW, max_snapshot_age=MAX_AGE
        )
        assert [v.mint_address for v in verdicts] == ["fresh", "stale", "alsofresh"]
        assert eligibility.first_eligible(verdicts).mint_address == "fresh"
        assert eligibility.refusal_counts(verdicts) == {Refusal.MARKET_DATA_STALE.value: 1}

    def test_every_refusal_has_a_published_sentence(self) -> None:
        """A reason code with no label renders as a blank on the page."""
        for reason in Refusal:
            assert eligibility.REFUSAL_LABELS[reason]

    def test_the_refusal_vocabulary_is_pinned_exactly(self) -> None:
        """Every condition the wallet can refuse on, in one list.

        Moved here from `test_hq6_paper_isolation.py`, which pinned the same
        set as a side effect of guarding against *security* leaking into
        eligibility. This is the right home: adding a reason is a deliberate
        change to what the wallet will and will not buy, and it should fail a
        test that is about the vocabulary rather than one about HQ-6.
        """
        assert {member.value for member in Refusal} == {
            "already_traded",
            "already_held",
            "no_market_data",
            "no_price",
            "no_liquidity",
            "not_tradeable",
            "market_data_stale",
            "insufficient_paper_cash",
        }
