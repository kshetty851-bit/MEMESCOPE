"""The shared market strip, tested where it is pure.

Sprint 23 made this one implementation behind two surfaces. The rules it
encodes — never estimate a missing reading, never zero an absent one — are now
asserted once, without a database, so a change to either surface cannot quietly
soften them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.market import TokenMarketSnapshot
from app.services.market_context import TokenContext, market_strip

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)


def _snapshot(price: str | None) -> TokenMarketSnapshot:
    return TokenMarketSnapshot(
        mint_address="probe",
        captured_at=NOW,
        price_usd=None if price is None else Decimal(price),
        market_cap=Decimal("124000"),
        liquidity_usd=Decimal("18000"),
        volume_24h=Decimal("89000"),
        dex_name="pumpswap",
    )


class TestMarketStrip:
    def test_an_unpriced_token_has_no_strip_at_all(self) -> None:
        assert market_strip(None, prior_price=Decimal("1")) is None

    def test_change_is_computed_when_both_ends_were_observed(self) -> None:
        strip = market_strip(_snapshot("0.000015"), prior_price=Decimal("0.000010"))
        assert strip is not None
        assert strip.change_24h_pct == Decimal("50.00")

    def test_change_is_absent_without_a_reading_from_far_enough_back(self) -> None:
        """A token four minutes old has not been flat for a day; it did not
        exist. Zero would be a claim nobody measured."""
        strip = market_strip(_snapshot("0.000015"), prior_price=None)
        assert strip is not None
        assert strip.change_24h_pct is None

    def test_a_zero_prior_price_yields_no_change_rather_than_infinity(self) -> None:
        """Division by a zero baseline is undefined, not infinite growth."""
        strip = market_strip(_snapshot("0.000015"), prior_price=Decimal("0"))
        assert strip is not None
        assert strip.change_24h_pct is None

    def test_a_priced_snapshot_carries_its_own_timestamp(self) -> None:
        """So a stale price is visibly stale rather than silently current."""
        strip = market_strip(_snapshot("0.000015"), prior_price=None)
        assert strip is not None
        assert strip.captured_at == NOW


class TestAge:
    def test_age_is_absent_when_the_origin_is_unknown(self) -> None:
        """`None`, never 0: "we do not know how old this is" and "this was
        created this instant" are different claims."""
        assert TokenContext.empty().age_seconds("probe", now=NOW) is None

    def test_age_never_goes_negative(self) -> None:
        """A block time fractionally ahead of our clock is a clock disagreement,
        not a token from the future."""
        context = TokenContext(
            names={},
            markets={},
            prior_prices={},
            ages={"probe": NOW + timedelta(minutes=5)},
        )
        assert context.age_seconds("probe", now=NOW) == 0
