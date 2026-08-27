"""The three ENTRY-SELECT-1 gates, and the property that they are off by default.

Each gate ships disabled, so the test that matters most is not what any of them
rejects — it is that a call which passes no threshold behaves exactly as it did
before the parameter existed. A flag that changes behaviour while nominally off
is the failure mode worth a test; the rest is arithmetic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.paper import eligibility
from app.paper.eligibility import Observation, Refusal
from app.radar import detector, scorer
from app.radar.models import Observation as RadarObservation
from app.radar.models import RadarSeries

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
NOTHING: frozenset[str] = frozenset()


def radar_series(*, liquidity: Decimal | None, count: int = 48) -> RadarSeries:
    return RadarSeries(
        mint_address="MintTest",
        observations=[
            RadarObservation(
                captured_at=NOW - timedelta(minutes=(count - i) * 30),
                price_usd=Decimal("0.001") + Decimal("0.00002") * Decimal(i),
                market_cap=Decimal(200_000),
                liquidity_usd=None
                if liquidity is None
                else liquidity + Decimal(300) * Decimal(i),
                volume_24h=Decimal(15_000) + Decimal(400) * Decimal(i),
                volume_1h=Decimal(500),
                buy_count_24h=100,
                sell_count_24h=100,
            )
            for i in range(count)
        ],
    )


def observation(**overrides: object) -> Observation:
    base: dict[str, object] = {
        "mint_address": "probe",
        "rank": 1,
        "has_snapshot": True,
        "observed_at": NOW,
        "price_usd": Decimal("0.01"),
        "liquidity_usd": Decimal(20_000),
        "market_cap": Decimal(150_000),
        "trading_status": "trading",
        "category": "early_momentum",
        "score": Decimal(60),
    }
    base.update(overrides)
    return Observation(**base)  # type: ignore[arg-type]


class TestRadarLiquidityFloor:
    def test_a_thin_pool_qualifies_when_the_floor_is_off(self) -> None:
        # The pre-flag behaviour, and the reason the flag exists: liquidity
        # reaches admission only through the risk dimension, where $9,000
        # already scores well above the floor of 30.
        result = scorer.evaluate(radar_series(liquidity=Decimal(9_000)), now=NOW)
        assert result is not None
        assert detector.qualifies(result) is True

    def test_the_same_pool_is_refused_once_the_floor_is_applied(self) -> None:
        result = scorer.evaluate(radar_series(liquidity=Decimal(9_000)), now=NOW)
        assert result is not None
        assert detector.qualifies(result, min_liquidity_usd=Decimal(25_000)) is False
        assert detector.classify(result, min_liquidity_usd=Decimal(25_000)) is None

    def test_a_deep_pool_still_qualifies_under_the_floor(self) -> None:
        result = scorer.evaluate(radar_series(liquidity=Decimal(40_000)), now=NOW)
        assert result is not None
        assert detector.qualifies(result, min_liquidity_usd=Decimal(25_000)) is True

    def test_unobserved_depth_fails_the_floor_rather_than_passing_it(self) -> None:
        # A bonding-curve pair reports no depth at all (ADR 0002). "Not
        # measured" must not read as "cleared the threshold".
        result = scorer.evaluate(radar_series(liquidity=None), now=NOW)
        if result is not None:
            assert detector.qualifies(result, min_liquidity_usd=Decimal(25_000)) is False


class TestCategoryGate:
    def test_category_is_inapplicable_when_no_set_is_passed(self) -> None:
        verdict = eligibility.judge(observation(), held_ever=NOTHING, open_now=NOTHING)
        assert verdict.eligible

    def test_an_excluded_category_is_refused_by_name(self) -> None:
        verdict = eligibility.judge(
            observation(category="early_momentum"),
            held_ever=NOTHING,
            open_now=NOTHING,
            eligible_categories=frozenset({"elite", "undervalued"}),
        )
        assert verdict.refused_for == Refusal.CATEGORY_NOT_ELIGIBLE.value

    @pytest.mark.parametrize("category", ["elite", "undervalued"])
    def test_an_included_category_still_qualifies(self, category: str) -> None:
        verdict = eligibility.judge(
            observation(category=category),
            held_ever=NOTHING,
            open_now=NOTHING,
            eligible_categories=frozenset({"elite", "undervalued"}),
        )
        assert verdict.eligible

    def test_an_untradeable_token_is_named_for_that_not_for_its_category(self) -> None:
        # Selectivity conditions run last on purpose: naming a preference
        # would hide a feed outage.
        verdict = eligibility.judge(
            observation(category="early_momentum", price_usd=None),
            held_ever=NOTHING,
            open_now=NOTHING,
            eligible_categories=frozenset({"elite"}),
        )
        assert verdict.refused_for == Refusal.NO_PRICE.value


class TestScorePercentile:
    def test_the_page_is_unchanged_when_no_percentile_is_passed(self) -> None:
        page = [
            observation(mint_address=f"m{i}", rank=i, score=Decimal(i)) for i in range(1, 11)
        ]
        verdicts = eligibility.screen(page, held_ever=NOTHING, open_now=NOTHING)
        assert all(verdict.eligible for verdict in verdicts)

    def test_only_the_top_of_the_page_survives_the_floor(self) -> None:
        page = [
            observation(mint_address=f"m{i}", rank=i, score=Decimal(i * 10))
            for i in range(1, 11)
        ]
        verdicts = eligibility.screen(
            page, held_ever=NOTHING, open_now=NOTHING, score_percentile=60.0
        )
        eligible = [verdict.mint_address for verdict in verdicts if verdict.eligible]
        # Nearest rank on ten scores: the cutoff is the sixth, so five survive.
        assert eligible == ["m6", "m7", "m8", "m9", "m10"]
        refused = {verdict.refused_for for verdict in verdicts if not verdict.eligible}
        assert refused == {Refusal.BELOW_SCORE_PERCENTILE.value}

    def test_a_lone_candidate_clears_its_own_percentile(self) -> None:
        # The floor must never empty a page it did not need to.
        verdicts = eligibility.screen(
            [observation(score=Decimal(1))],
            held_ever=NOTHING,
            open_now=NOTHING,
            score_percentile=99.0,
        )
        assert verdicts[0].eligible

    def test_tokens_refused_for_other_reasons_do_not_drag_the_cutoff_down(self) -> None:
        # An outage that leaves most of the page unpriced must not make a weak
        # token the best of what is left.
        page = [observation(mint_address="good", rank=1, score=Decimal(90))]
        page += [
            observation(mint_address=f"dead{i}", rank=i + 2, score=Decimal(1), price_usd=None)
            for i in range(9)
        ]
        verdicts = eligibility.screen(
            page, held_ever=NOTHING, open_now=NOTHING, score_percentile=60.0
        )
        eligible = [verdict.mint_address for verdict in verdicts if verdict.eligible]
        assert eligible == ["good"]

    def test_the_cutoff_is_a_score_some_token_actually_posted(self) -> None:
        scores = [Decimal(10), Decimal(20), Decimal(30), Decimal(40)]
        cutoff = eligibility.score_cutoff(scores, 60.0)
        assert cutoff in scores

    def test_an_empty_page_has_no_cutoff(self) -> None:
        assert eligibility.score_cutoff([], 60.0) is None
