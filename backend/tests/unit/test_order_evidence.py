"""What the signer cannot check, checked here instead.

`sign_jupiter_transaction` verifies that a transaction has one required signer
and that our pinned wallet is the fee payer. It cannot read which mints or
amounts the compiled instructions move. That means structural validation proves
"only my wallet pays for this" and never "this is the swap I authorised" — and
only the second protects the balance.

Each test below is one way an order can be wrong. They are separate rather than
table-driven where the reason differs, because the point of the reason codes is
that the audit row says which failure happened.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.real_wallet.order_evidence import (
    AuthorizedOrder,
    OrderEvidenceRejectedError,
    OrderRejection,
    to_raw_amount,
    verify,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
WALLET = "8vHhLrEXECUTIONWALLETPUBLICKEYxxxxxxxxxxxxxx"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
TOKEN = "3dPRz3igaqxkrFMWwARmAwdMTqV8WbQDVn2mkgTgpump"


def buy_authorisation(**overrides: Any) -> AuthorizedOrder:
    base: dict[str, Any] = {
        "side": "BUY",
        "wallet_public_key": WALLET,
        "input_mint": USDC,
        "output_mint": TOKEN,
        "input_amount_raw": 5_000_000,  # $5 at 6 decimals
        "request_id": "req-1",
        "ordered_at": NOW - timedelta(seconds=3),
        "max_slippage_bps": 100,
        "max_price_impact_pct": Decimal(5),
        "max_order_age_seconds": 15,
    }
    base.update(overrides)
    return AuthorizedOrder(**base)


def sell_authorisation(**overrides: Any) -> AuthorizedOrder:
    base: dict[str, Any] = {
        "side": "SELL",
        "input_mint": TOKEN,
        "output_mint": USDC,
        "input_amount_raw": 2_500_000,
        "position_id": "position-1",
        "position_quantity_confirmed": True,
    }
    base.update(overrides)
    return buy_authorisation(**base)


def order(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "taker": WALLET,
        "inputMint": USDC,
        "outputMint": TOKEN,
        "inAmount": "5000000",
        "outAmount": "2500000",
        "otherAmountThreshold": "2450000",
        "slippageBps": 50,
        "requestId": "req-1",
        "priceImpactPct": "0.012",
        "routePlan": [{"swapInfo": {"label": "pumpswap"}}],
    }
    base.update(overrides)
    return base


def sell_order(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "inputMint": TOKEN,
        "outputMint": USDC,
        "inAmount": "2500000",
        "outAmount": "5100000",
        "otherAmountThreshold": "5000000",
    }
    base.update(overrides)
    return order(**base)


class TestBuy:
    def test_a_matching_order_is_approved(self) -> None:
        verdict = verify(authorized=buy_authorisation(), order=order(), now=NOW)

        assert verdict.approved
        assert verdict.reason_codes == ()

    def test_the_observed_figures_are_recorded_even_on_approval(self) -> None:
        """The audit row should show what was offered, not only the verdict."""
        verdict = verify(authorized=buy_authorisation(), order=order(), now=NOW)

        assert verdict.observed["in_amount"] == "5000000"
        assert verdict.observed["request_id"] == "req-1"
        assert verdict.observed["route_hops"] == "1"

    def test_a_different_taker_blocks(self) -> None:
        """The most dangerous single field: a swap paid for by us, delivered
        elsewhere."""
        verdict = verify(
            authorized=buy_authorisation(), order=order(taker="someone-else"), now=NOW
        )

        assert not verdict.approved
        assert OrderRejection.TAKER_MISMATCH in verdict.reason_codes

    def test_a_wrong_input_mint_blocks(self) -> None:
        verdict = verify(authorized=buy_authorisation(), order=order(inputMint=TOKEN), now=NOW)

        assert OrderRejection.INPUT_MINT_MISMATCH in verdict.reason_codes

    def test_a_wrong_output_mint_blocks(self) -> None:
        """Buying a different token than the one the safety gate cleared."""
        verdict = verify(
            authorized=buy_authorisation(), order=order(outputMint="OtherMint"), now=NOW
        )

        assert OrderRejection.OUTPUT_MINT_MISMATCH in verdict.reason_codes

    @pytest.mark.parametrize("amount", ["5000001", "50000000", "0", "abc", None])
    def test_any_input_amount_but_the_authorised_one_blocks(self, amount: Any) -> None:
        """Exact, not approximate. A 10x `inAmount` is the difference between a
        $5 canary and a $50 one."""
        verdict = verify(authorized=buy_authorisation(), order=order(inAmount=amount), now=NOW)

        assert OrderRejection.INPUT_AMOUNT_MISMATCH in verdict.reason_codes

    def test_a_missing_minimum_output_blocks(self) -> None:
        """Without a floor there is no slippage protection at all."""
        verdict = verify(
            authorized=buy_authorisation(),
            order=order(otherAmountThreshold=None),
            now=NOW,
        )

        assert OrderRejection.MINIMUM_OUTPUT_MISSING in verdict.reason_codes

    def test_a_minimum_above_the_quote_blocks(self) -> None:
        verdict = verify(
            authorized=buy_authorisation(),
            order=order(otherAmountThreshold="9999999"),
            now=NOW,
        )

        assert OrderRejection.MINIMUM_OUTPUT_ABOVE_EXPECTED in verdict.reason_codes

    def test_slippage_above_policy_blocks(self) -> None:
        verdict = verify(authorized=buy_authorisation(), order=order(slippageBps=900), now=NOW)

        assert OrderRejection.SLIPPAGE_ABOVE_POLICY in verdict.reason_codes

    def test_a_mismatched_request_id_blocks(self) -> None:
        """The id binds this order to the `/execute` that will carry it."""
        verdict = verify(
            authorized=buy_authorisation(), order=order(requestId="req-2"), now=NOW
        )

        assert OrderRejection.REQUEST_ID_MISMATCH in verdict.reason_codes

    def test_a_missing_request_id_blocks(self) -> None:
        verdict = verify(authorized=buy_authorisation(), order=order(requestId=None), now=NOW)

        assert OrderRejection.REQUEST_ID_MISSING in verdict.reason_codes

    def test_a_stale_order_blocks(self) -> None:
        """Prices move. An order older than the policy window describes a market
        that no longer exists."""
        verdict = verify(
            authorized=buy_authorisation(ordered_at=NOW - timedelta(minutes=5)),
            order=order(),
            now=NOW,
        )

        assert OrderRejection.ORDER_STALE in verdict.reason_codes

    def test_an_order_dated_in_the_future_blocks(self) -> None:
        """Clock skew must not read as freshness."""
        verdict = verify(
            authorized=buy_authorisation(ordered_at=NOW + timedelta(minutes=5)),
            order=order(),
            now=NOW,
        )

        assert OrderRejection.ORDER_STALE in verdict.reason_codes

    def test_price_impact_above_policy_blocks(self) -> None:
        """Jupiter reports a fraction; the policy is written in percent."""
        verdict = verify(
            authorized=buy_authorisation(), order=order(priceImpactPct="0.40"), now=NOW
        )

        assert OrderRejection.PRICE_IMPACT_ABOVE_POLICY in verdict.reason_codes

    def test_an_order_with_no_route_blocks(self) -> None:
        verdict = verify(authorized=buy_authorisation(), order=order(routePlan=[]), now=NOW)

        assert OrderRejection.ROUTE_EVIDENCE_MISSING in verdict.reason_codes

    def test_every_mismatch_is_reported_not_just_the_first(self) -> None:
        """An order wrong in four ways is a different event from a stale one."""
        verdict = verify(
            authorized=buy_authorisation(),
            order=order(
                taker="other", inputMint="x", outputMint="y", inAmount="1", routePlan=[]
            ),
            now=NOW,
        )

        assert len(verdict.reason_codes) >= 5


class TestSell:
    def test_a_matching_sell_is_approved(self) -> None:
        verdict = verify(authorized=sell_authorisation(), order=sell_order(), now=NOW)

        assert verdict.approved

    def test_the_pair_must_be_the_token_into_usdc(self) -> None:
        verdict = verify(
            authorized=sell_authorisation(),
            order=sell_order(inputMint=USDC, outputMint=TOKEN),
            now=NOW,
        )

        assert OrderRejection.INPUT_MINT_MISMATCH in verdict.reason_codes
        assert OrderRejection.OUTPUT_MINT_MISMATCH in verdict.reason_codes

    def test_selling_a_quantity_other_than_the_confirmed_one_blocks(self) -> None:
        """Selling more than the wallet holds fails on chain after paying a fee;
        selling less silently strands the remainder."""
        verdict = verify(
            authorized=sell_authorisation(), order=sell_order(inAmount="2400000"), now=NOW
        )

        assert OrderRejection.INPUT_AMOUNT_MISMATCH in verdict.reason_codes

    def test_an_unbound_sell_blocks(self) -> None:
        verdict = verify(
            authorized=sell_authorisation(position_id=None), order=sell_order(), now=NOW
        )

        assert OrderRejection.POSITION_BINDING_INVALID in verdict.reason_codes

    def test_a_sell_sized_from_an_unconfirmed_quantity_blocks(self) -> None:
        """An exit computed from an assumed balance rather than chain evidence."""
        verdict = verify(
            authorized=sell_authorisation(position_quantity_confirmed=False),
            order=sell_order(),
            now=NOW,
        )

        assert OrderRejection.SELL_QUANTITY_NOT_CONFIRMED in verdict.reason_codes


class TestRefusalIsLoud:
    def test_require_raises_so_a_caller_cannot_ignore_the_verdict(self) -> None:
        verdict = verify(authorized=buy_authorisation(), order=order(taker="other"), now=NOW)

        with pytest.raises(OrderEvidenceRejectedError, match="TAKER_MISMATCH"):
            verdict.require()

    def test_an_unsupported_side_is_refused_before_anything_else(self) -> None:
        verdict = verify(authorized=buy_authorisation(side="TRANSFER"), order=order(), now=NOW)

        assert verdict.reason_codes == (OrderRejection.SIDE_UNSUPPORTED,)


class TestExactBaseUnits:
    def test_a_representable_quantity_converts(self) -> None:
        assert to_raw_amount(Decimal("2.5"), 6) == 2_500_000

    def test_an_unrepresentable_quantity_refuses_rather_than_rounding(self) -> None:
        """Rounding an exit quantity leaves dust or oversells; both cost money."""
        with pytest.raises(ValueError, match="not_representable"):
            to_raw_amount(Decimal("2.5000001"), 6)
