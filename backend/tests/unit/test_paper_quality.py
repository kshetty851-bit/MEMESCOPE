"""Trade quality grading.

The V1.1 audit found three real defects in the historical table: a position that
closed before it opened, seven with no depth recorded, and roughly a third whose
market cap collapsed to near nothing while the price held. This module decides
which of those make a row unusable and which merely make one *field* unusable.

The distinction is the whole point, and the test that matters most is
`TestSuspectIsNotInvalid`: a broken market cap must not disqualify a trade from
a price-path study, or a third of an already small dataset disappears over a
column that study never reads.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.paper.quality import (
    Quality,
    Reason,
    TradeRecord,
    assess,
    summarise,
    worst,
)

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def record(**overrides: object) -> TradeRecord:
    """A clean trade, with defects applied by keyword."""
    base: dict[str, object] = {
        "trade_id": "t1",
        "opened_at": NOW,
        "closed_at": NOW + timedelta(hours=4),
        "entry_price": Decimal("0.001"),
        "exit_price": Decimal("0.0012"),
        "entry_market_cap": Decimal(100_000),
        "exit_market_cap": Decimal(120_000),
        "entry_liquidity_usd": Decimal(50_000),
        "execution_model_version": "jupiter_quote_v2",
        "path_observations": 400,
    }
    base.update(overrides)
    return TradeRecord(**base)  # type: ignore[arg-type]


class TestCleanTrade:
    def test_a_consistent_trade_is_valid(self) -> None:
        result = assess(record())
        assert result.status is Quality.VALID
        assert result.reasons == ()

    def test_price_and_mcap_moving_together_is_not_flagged(self) -> None:
        # +20% price, +20% market cap: supply unchanged, both agree.
        result = assess(record())
        assert Reason.MCAP_PRICE_RETURN_DIVERGENCE not in result.reasons
        assert result.mcap_divergence_pp is not None
        assert result.mcap_divergence_pp < Decimal(1)


class TestFatalDefects:
    def test_exit_before_entry_is_invalid(self) -> None:
        result = assess(record(closed_at=NOW - timedelta(hours=1)))
        assert result.status is Quality.INVALID
        assert Reason.EXIT_BEFORE_ENTRY in result.reasons

    def test_missing_timestamps_is_invalid(self) -> None:
        assert assess(record(closed_at=None)).status is Quality.INVALID
        assert assess(record(opened_at=None)).status is Quality.INVALID

    def test_non_positive_entry_price_is_invalid(self) -> None:
        result = assess(record(entry_price=Decimal(0)))
        assert result.status is Quality.INVALID
        assert Reason.NON_POSITIVE_ENTRY_PRICE in result.reasons

    def test_closed_without_exit_price_is_invalid(self) -> None:
        result = assess(record(exit_price=None))
        assert result.status is Quality.INVALID
        assert Reason.MISSING_EXIT_PRICE in result.reasons


class TestMarketCapDefects:
    def test_divergence_beyond_soft_threshold_is_suspect(self) -> None:
        # Price +20%, market cap -40%: 60pp apart.
        result = assess(record(exit_market_cap=Decimal(60_000)))
        assert result.status is Quality.SUSPECT
        assert Reason.MCAP_PRICE_RETURN_DIVERGENCE in result.reasons

    def test_extreme_divergence_gets_its_own_code(self) -> None:
        # Price +20%, market cap -95%: 115pp apart.
        result = assess(record(exit_market_cap=Decimal(5_001)))
        assert Reason.EXTREME_MCAP_PRICE_DIVERGENCE in result.reasons
        assert Reason.MCAP_PRICE_RETURN_DIVERGENCE not in result.reasons

    def test_the_audit_signature_is_caught(self) -> None:
        """Market cap collapsing under $5k while the price holds up."""
        result = assess(
            record(entry_market_cap=Decimal(2_000_000), exit_market_cap=Decimal(900))
        )
        assert Reason.IMPLAUSIBLE_MCAP_COLLAPSE in result.reasons
        assert result.status is Quality.SUSPECT

    def test_a_genuine_collapse_with_price_collapse_is_not_flagged(self) -> None:
        """A token that actually died is not a data defect."""
        result = assess(
            record(
                entry_price=Decimal("0.001"),
                exit_price=Decimal("0.00002"),  # -98%
                entry_market_cap=Decimal(1_000_000),
                exit_market_cap=Decimal(900),  # also -99.9%
            )
        )
        assert Reason.IMPLAUSIBLE_MCAP_COLLAPSE not in result.reasons

    def test_divergence_needs_both_returns(self) -> None:
        result = assess(record(entry_market_cap=None))
        assert result.mcap_divergence_pp is None
        assert Reason.MCAP_PRICE_RETURN_DIVERGENCE not in result.reasons


class TestNonFatalDefects:
    def test_missing_liquidity_is_suspect_not_invalid(self) -> None:
        result = assess(record(entry_liquidity_usd=None))
        assert result.status is Quality.SUSPECT
        assert Reason.MISSING_ENTRY_LIQUIDITY in result.reasons

    def test_thin_path_is_suspect(self) -> None:
        result = assess(record(path_observations=2))
        assert result.status is Quality.SUSPECT
        assert Reason.INSUFFICIENT_PATH_DATA in result.reasons

    def test_unknown_execution_model_is_suspect(self) -> None:
        for value in (None, ""):
            result = assess(record(execution_model_version=value))
            assert Reason.EXECUTION_MODEL_UNKNOWN in result.reasons


class TestSuspectIsNotInvalid:
    """The rule that keeps the dataset usable.

    A market-cap defect taints market cap and nothing else. If this stops
    holding, a third of the trades vanish from every price-path experiment for
    no reason.
    """

    def test_mcap_defect_does_not_block_a_path_study(self) -> None:
        result = assess(
            record(entry_market_cap=Decimal(2_000_000), exit_market_cap=Decimal(900))
        )
        assert result.usable_for("path") is True
        assert result.usable_for("return") is True
        assert result.usable_for("market_cap") is False

    def test_missing_liquidity_blocks_cost_but_not_return(self) -> None:
        result = assess(record(entry_liquidity_usd=None))
        assert result.usable_for("net") is False
        assert result.usable_for("cost") is False
        assert result.usable_for("return") is True

    def test_invalid_is_unusable_for_everything(self) -> None:
        result = assess(record(closed_at=NOW - timedelta(hours=1)))
        for field in ("path", "return", "market_cap", "cost", "net"):
            assert result.usable_for(field) is False


class TestMultipleDefects:
    def test_every_defect_is_collected_not_just_the_first(self) -> None:
        result = assess(
            record(
                entry_liquidity_usd=None,
                path_observations=1,
                execution_model_version=None,
                exit_market_cap=Decimal(700),
            )
        )
        assert Reason.MISSING_ENTRY_LIQUIDITY in result.reasons
        assert Reason.INSUFFICIENT_PATH_DATA in result.reasons
        assert Reason.EXECUTION_MODEL_UNKNOWN in result.reasons
        assert Reason.IMPLAUSIBLE_MCAP_COLLAPSE in result.reasons

    def test_one_fatal_defect_governs_the_status(self) -> None:
        result = assess(record(entry_liquidity_usd=None, closed_at=None))
        assert result.status is Quality.INVALID


class TestOpenPositions:
    def test_an_open_position_is_not_failed_for_lacking_an_exit(self) -> None:
        result = assess(record(is_closed=False, closed_at=None, exit_price=None))
        assert result.status is Quality.VALID


class TestSummary:
    def test_counts_every_exclusion_by_reason(self) -> None:
        assessments = [
            assess(record(trade_id="a")),
            assess(record(trade_id="b", entry_liquidity_usd=None)),
            assess(record(trade_id="c", entry_liquidity_usd=None)),
            assess(record(trade_id="d", closed_at=NOW - timedelta(hours=1))),
        ]
        summary = summarise(assessments)

        assert summary.total == 4
        assert summary.valid == 1
        assert summary.suspect == 2
        assert summary.invalid == 1
        assert summary.usable == 3
        assert summary.by_reason[Reason.MISSING_ENTRY_LIQUIDITY.value] == 2

    def test_empty_set_summarises_cleanly(self) -> None:
        summary = summarise([])
        assert summary.total == 0
        assert summary.by_reason == {}


class TestWorst:
    def test_severity_order_is_not_lexical(self) -> None:
        """`StrEnum` would sort invalid < suspect < valid. Severity must not."""
        assert worst([Quality.VALID, Quality.INVALID, Quality.SUSPECT]) is Quality.INVALID
        assert worst([Quality.VALID, Quality.SUSPECT]) is Quality.SUSPECT
        assert worst([]) is Quality.VALID
