"""SOL/USD, and the two dishonest figures it removes.

Before this, `realised_net_pnl_usd` was assigned the gross figure — a column
named `net` holding gross reads as measured and is not — and the SOL fee
reserve could only be compared against itself, so a wallet could open a
position it could not afford to close.

The tests that matter most here are the refusals. A price source that guesses
when it does not know is worse than no price source, because every figure
downstream inherits the guess without saying so.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.paper.execution import ExecutionQuoteUnavailableError
from app.real_wallet.sol_price import (
    JupiterSolUsdPriceSource,
    SolUsdPrice,
    UnavailableSolUsdPriceSource,
    evaluate_fee_reserve,
    fee_usd,
    lamports_to_sol,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)


def price(usd: str = "180", *, age_seconds: int = 0) -> SolUsdPrice:
    return SolUsdPrice(
        usd=Decimal(usd),
        observed_at=NOW - timedelta(seconds=age_seconds),
        source="jupiter_quote_v1",
    )


class TestFreshness:
    def test_a_recent_reading_is_fresh(self) -> None:
        assert price(age_seconds=30).is_fresh(NOW, max_age_seconds=120)

    def test_a_reading_past_the_bound_is_stale(self) -> None:
        assert not price(age_seconds=300).is_fresh(NOW, max_age_seconds=120)

    def test_a_reading_from_the_future_is_not_fresh(self) -> None:
        """Clock skew must not read as freshness — it is the one direction that
        would make a stale figure look newer than it is."""
        assert not price(age_seconds=-60).is_fresh(NOW, max_age_seconds=120)

    def test_the_age_is_reported_so_a_reader_can_judge_it(self) -> None:
        assert price(age_seconds=45).age_seconds(NOW) == Decimal(45)


class TestFeeConversion:
    def test_a_fee_converts_at_the_recorded_price(self) -> None:
        """5,000 lamports is the standard Solana base fee: 0.000005 SOL."""
        assert lamports_to_sol(5_000) == Decimal("0.000005")
        assert fee_usd(lamports=5_000, price=price("180")) == Decimal("0.000900")

    def test_a_priority_fee_sized_transaction_converts(self) -> None:
        assert fee_usd(lamports=505_000, price=price("180")) == Decimal("0.090900")

    def test_no_price_means_no_fee_figure_rather_than_zero(self) -> None:
        """The whole defect in one assertion: absent must not become 0.00."""
        assert fee_usd(lamports=5_000, price=None) is None

    def test_no_fee_means_no_fee_figure_rather_than_zero(self) -> None:
        """A missing fee and a fee of zero are different facts."""
        assert fee_usd(lamports=None, price=price()) is None

    def test_a_negative_fee_is_refused(self) -> None:
        assert fee_usd(lamports=-1, price=price()) is None


class TestFeeReserve:
    def test_a_funded_wallet_passes(self) -> None:
        decision = evaluate_fee_reserve(
            balance_sol=Decimal("0.05"),
            minimum_reserve_sol=Decimal("0.01"),
            priority_fee_sol=Decimal("0.0005"),
        )

        assert decision.sufficient
        assert decision.reasons == ()

    def test_the_requirement_covers_the_exit_as_well_as_the_entry(self) -> None:
        """A position that cannot fund its own close is worse than one never
        opened. Two transactions plus the standing reserve."""
        decision = evaluate_fee_reserve(
            balance_sol=Decimal("1"),
            minimum_reserve_sol=Decimal("0.01"),
            priority_fee_sol=Decimal("0.0005"),
        )

        # (0.000005 + 0.0005) x 2 + 0.01
        assert decision.required_sol == Decimal("0.011010")

    def test_enough_for_the_entry_but_not_the_exit_is_refused(self) -> None:
        decision = evaluate_fee_reserve(
            balance_sol=Decimal("0.0006"),
            minimum_reserve_sol=Decimal("0.01"),
            priority_fee_sol=Decimal("0.0005"),
        )

        assert not decision.sufficient
        assert "SOL_FEE_RESERVE_INSUFFICIENT" in decision.reasons

    def test_an_unknown_balance_fails_closed(self) -> None:
        """Not knowing what the wallet holds is not evidence that it holds
        enough."""
        decision = evaluate_fee_reserve(
            balance_sol=None,
            minimum_reserve_sol=Decimal("0.01"),
            priority_fee_sol=Decimal("0.0005"),
        )

        assert not decision.sufficient
        assert decision.reasons == ("SOL_BALANCE_UNKNOWN",)
        assert decision.available_sol is None

    def test_a_larger_multiplier_demands_more(self) -> None:
        conservative = evaluate_fee_reserve(
            balance_sol=Decimal("1"),
            minimum_reserve_sol=Decimal("0"),
            priority_fee_sol=Decimal("0.001"),
            exit_multiplier=4,
        )

        assert conservative.required_sol == Decimal("0.004020")


class _Quote:
    def __init__(self, usd: Decimal | None) -> None:
        self.output_amount_usd = usd


class _Client:
    def __init__(self, *, usd: Decimal | None = None, raises: Exception | None = None) -> None:
        self._usd = usd
        self._raises = raises
        self.calls: list[dict[str, object]] = []

    async def sell_quote(self, **kwargs: object) -> _Quote:
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return _Quote(self._usd)


class TestTheJupiterSource:
    async def test_it_prices_one_sol_in_usdc(self) -> None:
        client = _Client(usd=Decimal("182.50"))

        result = await JupiterSolUsdPriceSource(client=client).current(now=NOW)  # type: ignore[arg-type]

        assert result is not None
        assert result.usd == Decimal("182.50")
        assert result.source == "jupiter_quote_v1"
        assert client.calls[0]["quantity"] == Decimal(1)

    async def test_the_reading_is_stamped_when_it_was_fetched(self) -> None:
        """Not with a provider timestamp: the quote describes the market at the
        moment it was asked, and claiming a more precise instant would overstate
        its freshness."""
        result = await JupiterSolUsdPriceSource(client=_Client(usd=Decimal(180))).current(  # type: ignore[arg-type]
            now=NOW
        )

        assert result is not None
        assert result.observed_at == NOW

    async def test_an_unavailable_route_yields_no_price(self) -> None:
        source = JupiterSolUsdPriceSource(
            client=_Client(raises=ExecutionQuoteUnavailableError("down"))  # type: ignore[arg-type]
        )

        assert await source.current(now=NOW) is None

    async def test_an_unexpected_provider_error_yields_no_price(self) -> None:
        """Execution accounting must never inherit a half-parsed number from a
        provider error path."""
        source = JupiterSolUsdPriceSource(client=_Client(raises=RuntimeError("boom")))  # type: ignore[arg-type]

        assert await source.current(now=NOW) is None

    @pytest.mark.parametrize("usd", [None, Decimal(0), Decimal("-1")])
    async def test_a_non_positive_price_is_no_price(self, usd: Decimal | None) -> None:
        source = JupiterSolUsdPriceSource(client=_Client(usd=usd))  # type: ignore[arg-type]

        assert await source.current(now=NOW) is None

    async def test_the_explicit_empty_source_never_invents_one(self) -> None:
        assert await UnavailableSolUsdPriceSource().current(now=NOW) is None
