"""The seven entry conditions, and the reasons they refuse with.

Sprint 30 §5 lists them; this file is where they are held to the list. The
property that matters most is not any single condition — it is that the
evaluator and the wallet page ask the *same* function, so "no qualified token"
on the screen and "opened 0" in the log can never come from different rules.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.paper import eligibility
from app.paper.eligibility import Observation, Refusal

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)
NOTHING: frozenset[str] = frozenset()


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
    }
    base.update(overrides)
    return Observation(**base)  # type: ignore[arg-type]


class TestTheConditions:
    def test_a_token_meeting_every_condition_becomes_a_candidate(self) -> None:
        verdict = eligibility.judge(observation(), held_ever=NOTHING, open_now=NOTHING)

        assert verdict.eligible
        assert verdict.candidate is not None
        assert verdict.candidate.liquidity_usd == Decimal(20_000)
        assert verdict.candidate.market_cap == Decimal(150_000)

    @pytest.mark.parametrize(
        ("overrides", "expected"),
        [
            ({"has_snapshot": False, "price_usd": None}, Refusal.NO_MARKET_DATA),
            ({"observed_at": None}, Refusal.NO_MARKET_DATA),
            ({"price_usd": None}, Refusal.NO_PRICE),
            ({"price_usd": Decimal(0)}, Refusal.NO_PRICE),
            ({"trading_status": "inactive"}, Refusal.NOT_TRADEABLE),
            ({"trading_status": "unknown"}, Refusal.NOT_TRADEABLE),
            ({"liquidity_usd": None}, Refusal.NO_LIQUIDITY),
            ({"liquidity_usd": Decimal(0)}, Refusal.NO_LIQUIDITY),
        ],
    )
    def test_each_condition_refuses_with_its_own_reason(
        self, overrides: dict[str, object], expected: Refusal
    ) -> None:
        verdict = eligibility.judge(
            observation(**overrides), held_ever=NOTHING, open_now=NOTHING
        )

        assert not verdict.eligible
        assert verdict.refused_for == expected

    def test_a_held_token_and_a_traded_token_are_different_refusals(self) -> None:
        """Both are "one lifetime trade per token", but a reader looking at an
        idle wallet needs to know whether it is holding or has moved on."""
        held = eligibility.judge(observation(), held_ever={"probe"}, open_now={"probe"})
        traded = eligibility.judge(observation(), held_ever={"probe"}, open_now=NOTHING)

        assert held.refused_for == Refusal.ALREADY_HELD
        assert traded.refused_for == Refusal.ALREADY_TRADED

    def test_ownership_is_checked_before_market_data(self) -> None:
        """A token already traded will never become eligible again however its
        market moves, so that is the reason worth reporting."""
        verdict = eligibility.judge(
            observation(has_snapshot=False, price_usd=None, liquidity_usd=None),
            held_ever={"probe"},
            open_now=NOTHING,
        )

        assert verdict.refused_for == Refusal.ALREADY_TRADED

    def test_every_refusal_code_has_a_published_sentence(self) -> None:
        """Prose is rendered server-side from a stable code — the platform's
        rule everywhere. A code with no label would reach a client as a slug."""
        for reason in Refusal:
            assert eligibility.REFUSAL_LABELS[reason]


class TestScreening:
    def test_the_radar_ordering_survives_the_screen(self) -> None:
        """ "The highest-ranked eligible token" is only one line of code because
        the ranking is never resorted."""
        rows = [
            observation(mint_address="a", rank=1, liquidity_usd=None),
            observation(mint_address="b", rank=2),
            observation(mint_address="c", rank=3),
        ]

        verdicts = eligibility.screen(rows, held_ever=NOTHING, open_now=NOTHING)

        assert [item.mint_address for item in verdicts] == ["a", "b", "c"]
        first = eligibility.first_eligible(verdicts)
        assert first is not None and first.mint_address == "b"

    def test_nothing_eligible_returns_none_rather_than_a_fallback(self) -> None:
        """The wallet never buys a lower-quality token to avoid an empty screen."""
        rows = [observation(mint_address="a", liquidity_usd=None)]

        assert (
            eligibility.first_eligible(
                eligibility.screen(rows, held_ever=NOTHING, open_now=NOTHING)
            )
            is None
        )

    def test_refusals_are_counted_so_an_empty_wallet_has_a_denominator(self) -> None:
        """ "No qualified token" with nothing behind it is a claim; with a count
        per condition it is a measurement."""
        rows = [
            observation(mint_address="a", liquidity_usd=None),
            observation(mint_address="b", liquidity_usd=None),
            observation(mint_address="c", price_usd=None),
            observation(mint_address="d"),
        ]

        counts = eligibility.refusal_counts(
            eligibility.screen(rows, held_ever=NOTHING, open_now=NOTHING)
        )

        assert counts == {Refusal.NO_LIQUIDITY: 2, Refusal.NO_PRICE: 1}
