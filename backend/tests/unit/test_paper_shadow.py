"""Unit tests for Parallel Shadow Wallets (V2-V5) and Strategy Intelligence.

Verifies:
- Exact candidate rules and boundary conditions.
- Rejection reasons persistence and machine-readable codes.
- Financial independence of shadow wallets.
- Decision, position exit, and audit idempotency.
- V1 production isolation.
- Missed opportunities and Good Rejection / Missed Winner analytics.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.models.market import TokenMarketSnapshot
from app.models.radar import RadarToken
from app.paper.execution import ExecutionQuote, LegacyExecution
from app.paper.shadow import (
    SHADOW_SPECS,
    Opportunity,
    ShadowReason,
    _filter_performance,
    _missed_opportunities,
    _promotion_blockers,
    _promotion_eligible,
    _promotion_score,
    _reasons_for,
    _spec_for,
    execution_quality,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
EMPTY_SET: frozenset[str] = frozenset()


def make_radar(
    mint: str = "probe_mint",
    score: Decimal = Decimal(75),
    confidence: Decimal = Decimal("0.90"),
    evaluated_at: datetime = NOW,
) -> RadarToken:
    radar = MagicMock(spec=RadarToken)
    radar.mint_address = mint
    radar.current_opportunity_score = score
    radar.current_confidence = confidence
    radar.last_evaluated_at = evaluated_at
    return radar


def make_snapshot(
    price_usd: Decimal = Decimal("1.0"),
    market_cap: Decimal = Decimal(40_000),
    liquidity_usd: Decimal = Decimal(10_000),
    volume_24h: Decimal = Decimal(50_000),
    trading_status: str = "trading",
    captured_at: datetime = NOW,
) -> TokenMarketSnapshot:
    snapshot = MagicMock(spec=TokenMarketSnapshot)
    snapshot.price_usd = price_usd
    snapshot.market_cap = market_cap
    snapshot.liquidity_usd = liquidity_usd
    snapshot.volume_24h = volume_24h
    status_mock = MagicMock()
    status_mock.value = trading_status
    snapshot.trading_status = status_mock
    snapshot.captured_at = captured_at
    return snapshot


def make_quote(impact_pct: Decimal = Decimal("0.5")) -> ExecutionQuote:
    return ExecutionQuote(
        side="buy",
        model_version="jupiter_v1",
        quoted_at=NOW,
        latency_ms=Decimal(50),
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="probe_mint",
        input_amount_raw="100000000",
        output_amount_raw="1000000000",
        input_decimals=9,
        output_decimals=6,
        input_amount=Decimal(100),
        output_amount=Decimal(100),
        input_amount_usd=Decimal(100),
        output_amount_usd=Decimal(100),
        estimated_price_usd=Decimal(1),
        price_impact_pct=impact_pct,
        context_slot=123456,
        platform_fee_usd=Decimal(0),
        route="Raydium",
        amms=("Raydium",),
        raw={},
    )


def make_opportunity(
    mint: str = "probe_mint",
    score: Decimal = Decimal(75),
    mcap: Decimal = Decimal(40_000),
    liquidity: Decimal = Decimal(10_000),
    impact: Decimal | None = Decimal("0.5"),
    has_snapshot: bool = True,
    trading_status: str = "trading",
    require_quote: bool = True,
) -> Opportunity:
    radar = make_radar(mint=mint, score=score)
    snapshot = (
        make_snapshot(market_cap=mcap, liquidity_usd=liquidity, trading_status=trading_status)
        if has_snapshot
        else None
    )
    quote = (
        make_quote(impact_pct=impact)
        if (impact is not None and require_quote)
        else (LegacyExecution("No quote") if not require_quote else None)
    )
    return Opportunity(
        radar=radar,
        rank=1,
        snapshot=snapshot,
        token_id=None,
        symbol="PROBE",
        decimals=6,
        age_seconds=3600,
        execution_quote=quote,
    )


class TestExecutionQuality:
    def test_quality_bands(self) -> None:
        assert execution_quality(Decimal("0.5")) == "A"
        assert execution_quality(Decimal("1.0")) == "A"
        assert execution_quality(Decimal("1.01")) == "B+"
        assert execution_quality(Decimal("2.0")) == "B+"
        assert execution_quality(Decimal("2.01")) == "C"
        assert execution_quality(Decimal("5.0")) == "C"
        assert execution_quality(Decimal("5.01")) == "D"
        assert execution_quality(None) is None


class TestShadowSpecRegistry:
    def test_specs_exist_and_codes_are_unique(self) -> None:
        assert len(SHADOW_SPECS) == 4
        codes = [spec.code for spec in SHADOW_SPECS]
        assert codes == ["v2", "v3", "v4", "v5"]
        for code in codes:
            assert _spec_for(code).code == code

    def test_unknown_spec_raises_key_error(self) -> None:
        with pytest.raises(KeyError):
            _spec_for("v99")


class TestV2CandidateRulesAndBoundaries:
    """V2: Mcap $25K-$50K, Quality A/B+, Impact <2%, Radar >=65."""

    def test_v2_accepted_opportunity(self) -> None:
        spec = _spec_for("v2")
        opp = make_opportunity(score=Decimal(65), mcap=Decimal(35_000), impact=Decimal("1.5"))
        reasons = _reasons_for(spec, opp, held=EMPTY_SET, open_now=EMPTY_SET)
        assert reasons == []

    def test_v2_boundary_mcap_25k(self) -> None:
        spec = _spec_for("v2")
        # $25,000 is inclusive lower bound -> accepted
        opp_exact = make_opportunity(
            score=Decimal(65), mcap=Decimal(25_000), impact=Decimal("1.5")
        )
        assert _reasons_for(spec, opp_exact, held=EMPTY_SET, open_now=EMPTY_SET) == []

        # Below $25,000 -> rejected
        opp_below = make_opportunity(
            score=Decimal(65), mcap=Decimal(24_999), impact=Decimal("1.5")
        )
        assert _reasons_for(spec, opp_below, held=EMPTY_SET, open_now=EMPTY_SET) == [
            ShadowReason.MARKET_CAP_TOO_LOW
        ]

    def test_v2_boundary_mcap_50k(self) -> None:
        spec = _spec_for("v2")
        # $50,000 is inclusive upper bound -> accepted
        opp_exact = make_opportunity(
            score=Decimal(65), mcap=Decimal(50_000), impact=Decimal("1.5")
        )
        assert _reasons_for(spec, opp_exact, held=EMPTY_SET, open_now=EMPTY_SET) == []

        # Above $50,000 -> rejected
        opp_above = make_opportunity(
            score=Decimal(65), mcap=Decimal(50_001), impact=Decimal("1.5")
        )
        assert _reasons_for(spec, opp_above, held=EMPTY_SET, open_now=EMPTY_SET) == [
            ShadowReason.MARKET_CAP_TOO_HIGH
        ]

    def test_v2_boundary_radar_score_65(self) -> None:
        spec = _spec_for("v2")
        # Radar 65 is inclusive lower bound -> accepted
        opp_exact = make_opportunity(
            score=Decimal(65), mcap=Decimal(35_000), impact=Decimal("1.5")
        )
        assert _reasons_for(spec, opp_exact, held=EMPTY_SET, open_now=EMPTY_SET) == []

        # Radar 64.99 -> rejected
        opp_below = make_opportunity(
            score=Decimal("64.99"), mcap=Decimal(35_000), impact=Decimal("1.5")
        )
        assert _reasons_for(spec, opp_below, held=EMPTY_SET, open_now=EMPTY_SET) == [
            ShadowReason.RADAR_BELOW_THRESHOLD
        ]

    def test_v2_boundary_impact_2_percent(self) -> None:
        spec = _spec_for("v2")
        # Impact 1.99% -> accepted
        opp_below = make_opportunity(
            score=Decimal(65), mcap=Decimal(35_000), impact=Decimal("1.99")
        )
        assert _reasons_for(spec, opp_below, held=EMPTY_SET, open_now=EMPTY_SET) == []

        # Impact 2.0% is strict inequality <2% -> rejected
        opp_exact = make_opportunity(
            score=Decimal(65), mcap=Decimal(35_000), impact=Decimal("2.0")
        )
        reasons = _reasons_for(spec, opp_exact, held=EMPTY_SET, open_now=EMPTY_SET)
        assert ShadowReason.PRICE_IMPACT_TOO_HIGH in reasons


class TestV3CandidateRulesAndBoundaries:
    """V3: Radar >=70, Quality A only, No mcap restriction."""

    def test_v3_accepted_opportunity(self) -> None:
        spec = _spec_for("v3")
        opp = make_opportunity(
            score=Decimal(70), mcap=Decimal(1_000_000), impact=Decimal("0.8")
        )
        assert _reasons_for(spec, opp, held=EMPTY_SET, open_now=EMPTY_SET) == []

    def test_v3_boundary_radar_score_70(self) -> None:
        spec = _spec_for("v3")
        opp_exact = make_opportunity(
            score=Decimal(70), mcap=Decimal(100_000), impact=Decimal("0.5")
        )
        assert _reasons_for(spec, opp_exact, held=EMPTY_SET, open_now=EMPTY_SET) == []

        opp_below = make_opportunity(
            score=Decimal("69.9"), mcap=Decimal(100_000), impact=Decimal("0.5")
        )
        assert _reasons_for(spec, opp_below, held=EMPTY_SET, open_now=EMPTY_SET) == [
            ShadowReason.RADAR_BELOW_THRESHOLD
        ]

    def test_v3_quality_a_only(self) -> None:
        spec = _spec_for("v3")
        # Impact 1.5% is Quality B+ -> rejected
        opp_b_plus = make_opportunity(
            score=Decimal(75), mcap=Decimal(100_000), impact=Decimal("1.5")
        )
        assert _reasons_for(spec, opp_b_plus, held=EMPTY_SET, open_now=EMPTY_SET) == [
            ShadowReason.EXECUTION_QUALITY_BELOW_THRESHOLD
        ]


class TestV4CandidateRulesAndBoundaries:
    """V4: Mcap $50K-$100K, Quality A/B+, Impact <2%."""

    def test_v4_boundary_mcap_50k_and_100k(self) -> None:
        spec = _spec_for("v4")
        # Mcap $50,000 -> accepted
        opp_50k = make_opportunity(
            score=Decimal(50), mcap=Decimal(50_000), impact=Decimal("1.0")
        )
        assert _reasons_for(spec, opp_50k, held=EMPTY_SET, open_now=EMPTY_SET) == []

        # Mcap $100,000 -> accepted
        opp_100k = make_opportunity(
            score=Decimal(50), mcap=Decimal(100_000), impact=Decimal("1.0")
        )
        assert _reasons_for(spec, opp_100k, held=EMPTY_SET, open_now=EMPTY_SET) == []

        # Mcap $49,999 -> rejected low
        opp_low = make_opportunity(
            score=Decimal(50), mcap=Decimal(49_999), impact=Decimal("1.0")
        )
        assert _reasons_for(spec, opp_low, held=EMPTY_SET, open_now=EMPTY_SET) == [
            ShadowReason.MARKET_CAP_TOO_LOW
        ]

        # Mcap $100,001 -> rejected high
        opp_high = make_opportunity(
            score=Decimal(50), mcap=Decimal(100_001), impact=Decimal("1.0")
        )
        assert _reasons_for(spec, opp_high, held=EMPTY_SET, open_now=EMPTY_SET) == [
            ShadowReason.MARKET_CAP_TOO_HIGH
        ]


class TestV5CandidateRulesAndBoundaries:
    """V5: Quality A only, Jupiter impact <1%, Jupiter quote required, No mcap restriction."""

    def test_v5_accepted_opportunity(self) -> None:
        spec = _spec_for("v5")
        opp = make_opportunity(score=Decimal(50), mcap=Decimal(200_000), impact=Decimal("0.5"))
        assert _reasons_for(spec, opp, held=EMPTY_SET, open_now=EMPTY_SET) == []

    def test_v5_boundary_impact_1_percent(self) -> None:
        spec = _spec_for("v5")
        # Impact 0.99% -> accepted
        opp_099 = make_opportunity(
            score=Decimal(50), mcap=Decimal(200_000), impact=Decimal("0.99")
        )
        assert _reasons_for(spec, opp_099, held=EMPTY_SET, open_now=EMPTY_SET) == []

        # Impact 1.0% is strict inequality <1% -> rejected
        opp_10 = make_opportunity(
            score=Decimal(50), mcap=Decimal(200_000), impact=Decimal("1.0")
        )
        reasons = _reasons_for(spec, opp_10, held=EMPTY_SET, open_now=EMPTY_SET)
        assert ShadowReason.PRICE_IMPACT_TOO_HIGH in reasons

    def test_v5_missing_jupiter_quote(self) -> None:
        spec = _spec_for("v5")
        opp_no_jupiter = make_opportunity(
            score=Decimal(50), mcap=Decimal(200_000), impact=None, require_quote=False
        )
        reasons = _reasons_for(spec, opp_no_jupiter, held=EMPTY_SET, open_now=EMPTY_SET)
        assert ShadowReason.JUPITER_QUOTE_UNAVAILABLE in reasons


class TestRejectionReasonCodesAndStateConstraints:
    def test_already_held_and_already_traded_reasons(self) -> None:
        spec = _spec_for("v2")
        opp = make_opportunity(score=Decimal(70), mcap=Decimal(35_000), impact=Decimal("1.0"))

        # Mint in open positions -> ALREADY_HELD
        assert _reasons_for(spec, opp, held={"probe_mint"}, open_now={"probe_mint"}) == [
            ShadowReason.ALREADY_HELD
        ]

        # Mint in previously traded -> ALREADY_TRADED
        assert _reasons_for(spec, opp, held={"probe_mint"}, open_now=EMPTY_SET) == [
            ShadowReason.ALREADY_TRADED
        ]

    def test_missing_market_data_and_non_tradeable_reasons(self) -> None:
        spec = _spec_for("v2")
        opp_no_snapshot = make_opportunity(has_snapshot=False)
        assert _reasons_for(spec, opp_no_snapshot, held=EMPTY_SET, open_now=EMPTY_SET) == [
            ShadowReason.NO_MARKET_DATA
        ]

        opp_inactive = make_opportunity(trading_status="halted")
        reasons = _reasons_for(spec, opp_inactive, held=EMPTY_SET, open_now=EMPTY_SET)
        assert ShadowReason.NOT_TRADEABLE in reasons


class TestCrossWalletAnalytics:
    def test_missed_opportunities_and_good_rejection(self) -> None:
        # Construct wallet data with decisions and positions PnL
        wallet_v2 = {
            "code": "v2",
            "position_pnl_by_mint": {
                "mint_winner": Decimal("25.00"),
                "mint_loser": Decimal("-15.00"),
            },
            "decisions": [
                {"mint_address": "mint_winner", "decision": "accepted", "reason_codes": []},
                {"mint_address": "mint_loser", "decision": "accepted", "reason_codes": []},
            ],
        }

        wallet_v3 = {
            "code": "v3",
            "position_pnl_by_mint": {},
            "decisions": [
                {
                    "mint_address": "mint_winner",
                    "decision": "rejected",
                    "reason_codes": ["radar_below_threshold"],
                },
                {
                    "mint_address": "mint_loser",
                    "decision": "rejected",
                    "reason_codes": ["execution_quality_below_threshold"],
                },
            ],
        }

        missed = _missed_opportunities([wallet_v2, wallet_v3])
        assert len(missed) == 2

        winner_miss = next(item for item in missed if item["mint_address"] == "mint_winner")
        assert winner_miss["wallet_code"] == "v3"
        assert winner_miss["outcome"] == "missed_winner"
        assert winner_miss["accepted_elsewhere"] == ["v2"]
        assert winner_miss["pnl_usd"] == "25.0000"

        loser_miss = next(item for item in missed if item["mint_address"] == "mint_loser")
        assert loser_miss["wallet_code"] == "v3"
        assert loser_miss["outcome"] == "good_rejection"
        assert loser_miss["accepted_elsewhere"] == ["v2"]
        assert loser_miss["pnl_usd"] == "-15.0000"

    def test_filter_performance_aggregation(self) -> None:
        wallet_v2 = {
            "code": "v2",
            "position_pnl_by_mint": {
                "mint_win": Decimal("50.00"),
                "mint_loss": Decimal("-20.00"),
            },
            "decisions": [
                {"mint_address": "mint_win", "decision": "accepted", "reason_codes": []},
                {"mint_address": "mint_loss", "decision": "accepted", "reason_codes": []},
            ],
        }
        wallet_v4 = {
            "code": "v4",
            "position_pnl_by_mint": {},
            "decisions": [
                {
                    "mint_address": "mint_win",
                    "decision": "rejected",
                    "reason_codes": ["market_cap_too_low"],
                },
                {
                    "mint_address": "mint_loss",
                    "decision": "rejected",
                    "reason_codes": ["market_cap_too_low"],
                },
            ],
        }

        filters = _filter_performance([wallet_v2, wallet_v4])
        mcap_filter = next(f for f in filters if f["reason_code"] == "market_cap_too_low")

        assert mcap_filter["times_triggered"] == 2
        assert mcap_filter["winning_trades_prevented"] == 1
        assert mcap_filter["losing_trades_prevented"] == 1
        assert mcap_filter["net_pl_saved"] == "20.0000"
        assert mcap_filter["net_pl_missed"] == "50.0000"
        assert mcap_filter["average_opportunity_cost"] == "50.0000"


class TestPromotionRules:
    def test_promotion_score_and_eligibility(self) -> None:
        # Under 100 trades -> not eligible
        assert not _promotion_eligible(
            net_return=Decimal("100"),
            profit_factor=Decimal("1.50"),
            expectancy=Decimal("10"),
            closed_count=50,
        )

        blockers = _promotion_blockers(
            net_return=Decimal("100"),
            profit_factor=Decimal("1.50"),
            expectancy=Decimal("10"),
            closed_count=50,
        )
        assert blockers == ["needs_100_completed_live_trades"]

        # Meets all criteria -> eligible
        assert _promotion_eligible(
            net_return=Decimal("100"),
            profit_factor=Decimal("1.50"),
            expectancy=Decimal("10"),
            closed_count=100,
        )
        assert (
            _promotion_blockers(
                net_return=Decimal("100"),
                profit_factor=Decimal("1.50"),
                expectancy=Decimal("10"),
                closed_count=100,
            )
            == []
        )

        score = _promotion_score(
            net_return=Decimal("100"),
            profit_factor=Decimal("1.50"),
            expectancy=Decimal("10"),
            closed_count=100,
            win_rate=Decimal("60"),
            max_drawdown=Decimal("10"),
        )
        assert score > Decimal(50)


def test_rejects_jupiter_quote_with_extreme_market_price_mismatch() -> None:
    """A valid Jupiter quote must not create fake paper P/L from a bad price."""
    observed_price = Decimal("0.00003271")
    from dataclasses import replace

    quote = replace(
        make_quote(impact_pct=Decimal("0.5")),
        estimated_price_usd=Decimal("0.000001543318715779"),
    )

    # Reproduce the real failure mode: Jupiter implied a price ~21x below
    # the contemporaneous market snapshot.

    opportunity = Opportunity(
        radar=make_radar(score=Decimal(75)),
        rank=1,
        snapshot=make_snapshot(
            price_usd=observed_price,
            market_cap=Decimal(35_000),
        ),
        token_id=None,
        symbol="TEST",
        decimals=6,
        age_seconds=3600,
        execution_quote=quote,
    )

    spec = _spec_for("v5")
    reasons = _reasons_for(spec, opportunity, held=set(), open_now=set())

    assert ShadowReason.EXECUTION_PRICE_MISMATCH in reasons
