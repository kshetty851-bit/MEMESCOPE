"""The market-data entry gate: what it blocks, and what it must never block.

Pure logic only — `assess` and `census_from` take measured facts and a clock,
so every boundary here is exercised without a database. The queries behind them
are covered in `tests/integration/test_market_data_gate.py`.

The whole point of the module is one asymmetry, so it is asserted first and
repeatedly: **bad evidence stops new entries and never stops exits.**
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.paper.market_health import (
    EntryBlockReason,
    FeedEvidence,
    FeedState,
    MarketDataHealth,
    OpenBookCensus,
    PositionFreshness,
    Thresholds,
    assess,
    census_from,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 21, 15, 0, 0, tzinfo=UTC)

#: A feed doing exactly what it promises: a fresh reading and real throughput.
HEALTHY_FEED = FeedEvidence(
    newest_priced_at=NOW - timedelta(seconds=5),
    recent_priced_snapshots=6_000,
    recent_priced_mints=1_500,
)


def position(mint: str, *, age: float | None, generation: int = 9) -> PositionFreshness:
    return PositionFreshness(
        mint_address=mint,
        generation=generation,
        observed_at=None if age is None else NOW - timedelta(seconds=age),
        age_seconds=age,
    )


def health(evidence: FeedEvidence, census: OpenBookCensus) -> MarketDataHealth:
    return assess(evidence, census, now=NOW)


class TestFeedStopped:
    """1. The 2026-08-21 outage: the feed stops, and entries must stop with it."""

    def test_a_stopped_feed_blocks_new_entries(self) -> None:
        stopped = FeedEvidence(
            newest_priced_at=NOW - timedelta(minutes=125),
            recent_priced_snapshots=0,
            recent_priced_mints=0,
        )
        verdict = health(stopped, OpenBookCensus())
        assert verdict.state is FeedState.STALE
        assert verdict.entries_allowed is False
        assert verdict.primary_reason is EntryBlockReason.MARKET_DATA_STALE

    def test_a_feed_that_never_produced_anything_is_stale_not_healthy(self) -> None:
        """Fail closed on absence of evidence.

        The opposite reading — "nothing measured, so nothing wrong" — is
        exactly what let a 125-minute outage run unremarked.
        """
        verdict = health(FeedEvidence(), OpenBookCensus())
        assert verdict.state is FeedState.STALE
        assert verdict.entries_allowed is False

    def test_a_fresh_reading_on_almost_no_mints_is_a_wedged_worker(self) -> None:
        """Recency alone is not health.

        One hot token with a current row proves nothing about a feed serving
        1,700 mints, and a worker stuck on it would otherwise report healthy
        forever.
        """
        wedged = FeedEvidence(
            newest_priced_at=NOW - timedelta(seconds=2),
            recent_priced_snapshots=400,
            recent_priced_mints=3,
        )
        verdict = health(wedged, OpenBookCensus())
        assert verdict.state is FeedState.STALE
        assert verdict.primary_reason is EntryBlockReason.FEED_UNHEALTHY

    def test_exit_management_is_reported_active_in_every_blocked_state(self) -> None:
        """The asymmetry, stated on the record rather than assumed.

        Nothing in this module is reachable from an exit path — asserted
        structurally in `test_paper_purity` — and the reading the operator sees
        has to say so even while entries are refused.
        """
        for evidence in (
            FeedEvidence(),
            FeedEvidence(newest_priced_at=NOW - timedelta(minutes=125)),
            FeedEvidence(newest_priced_at=NOW, recent_priced_mints=1),
        ):
            verdict = health(evidence, OpenBookCensus())
            assert verdict.entries_allowed is False
            assert verdict.as_dict()["exit_management"] == "ACTIVE"


class TestHealthyFeed:
    """2. The ordinary path is untouched. A gate that blocks normal trading is a bug."""

    def test_a_healthy_feed_with_a_fresh_book_allows_entries(self) -> None:
        census = census_from([position("a", age=12), position("b", age=20)])
        verdict = health(HEALTHY_FEED, census)
        assert verdict.state is FeedState.HEALTHY
        assert verdict.entries_allowed is True
        assert verdict.block_reasons == ()

    def test_an_empty_book_on_a_healthy_feed_allows_entries(self) -> None:
        """A wallet with nothing open is the first entry's starting state."""
        verdict = health(HEALTHY_FEED, OpenBookCensus())
        assert verdict.entries_allowed is True

    def test_measured_production_cadence_does_not_trip_the_gate(self) -> None:
        """The calibration claim, pinned.

        Production measured p50 17.3s and p95 41.9s for priced observations on
        open positions. If those ages blocked entries the gate would be
        unusable, so the thresholds are asserted against the real numbers
        rather than against round ones.
        """
        census = census_from(
            [position(f"m{i}", age=age) for i, age in enumerate((17.3, 41.9))]
        )
        assert census.critical == 0
        assert health(HEALTHY_FEED, census).entries_allowed is True

    def test_a_slow_feed_is_degraded_but_still_trades(self) -> None:
        """DEGRADED earns its place: slower than promised is still evidence."""
        slow = FeedEvidence(
            newest_priced_at=NOW - timedelta(seconds=150),
            recent_priced_snapshots=2_000,
            recent_priced_mints=600,
        )
        verdict = health(slow, census_from([position("a", age=20)]))
        assert verdict.state is FeedState.DEGRADED
        assert verdict.entries_allowed is True


class TestOpenPositionWatchdog:
    """6, 7. A position that goes dark is detected, and holds the gate shut."""

    def test_a_stale_open_position_blocks_new_entries(self) -> None:
        census = census_from([position("fresh", age=15), position("dark", age=600)])
        assert census.critical == 1
        assert census.critical_mints == ("dark",)
        verdict = health(HEALTHY_FEED, census)
        assert verdict.entries_allowed is False
        assert verdict.state is FeedState.RECOVERING

    def test_the_census_buckets_by_measured_age(self) -> None:
        census = census_from(
            [
                position("a", age=10),
                position("b", age=30),
                position("c", age=90),
                position("d", age=400),
            ]
        )
        assert (census.total, census.fresh, census.warning, census.critical) == (4, 2, 1, 1)

    def test_warning_is_visible_and_does_not_block(self) -> None:
        """The middle state has to exist and has to be harmless.

        A watchdog whose only two states are fine and blocked gives no notice
        before it stops the wallet trading.
        """
        census = census_from([position("a", age=90)])
        assert census.warning == 1
        assert census.critical == 0
        assert health(HEALTHY_FEED, census).entries_allowed is True

    def test_metrics_report_oldest_and_percentiles(self) -> None:
        """Nearest-rank, so every percentile is an age some position really had.

        Ages 1..20: p50 is the 11th value and p95 the 19th. `oldest` is the
        maximum and is reported separately, because a p95 that quietly became
        the worst case would hide the tail it exists to expose.
        """
        census = census_from([position(f"m{i}", age=float(i)) for i in range(1, 21)])
        assert census.oldest_age_seconds == 20.0
        assert census.refresh_p50_seconds == 11.0
        assert census.refresh_p95_seconds == 19.0

    def test_percentiles_are_none_for_an_empty_book(self) -> None:
        census = census_from([])
        assert census.refresh_p50_seconds is None
        assert census.oldest_age_seconds is None


class TestUnrecoverablePositions:
    """11. One dead mint must not stop the wallet for ever."""

    def test_an_unpriceable_position_is_counted_but_does_not_block(self) -> None:
        """94 open Generation 5 positions are in exactly this state.

        Their pools are gone and their last price is four days old. Blocking
        entries on them would fail closed on a condition that can never clear,
        and a safety mechanism that makes the system permanently useless is not
        a safety mechanism.
        """
        census = census_from([position("dead", age=4 * 24 * 3600), position("live", age=12)])
        assert census.unpriceable == 1
        assert census.unpriceable_mints == ("dead",)
        assert census.critical == 0
        verdict = health(HEALTHY_FEED, census)
        assert verdict.entries_allowed is True

    def test_an_unpriceable_position_is_never_silently_dropped(self) -> None:
        """Excluded from the gate, never from the report.

        A number nobody can see is the failure this whole module answers.
        """
        census = census_from([position("dead", age=4 * 24 * 3600)])
        verdict = health(HEALTHY_FEED, census)
        assert "no priceable market" in verdict.detail
        assert verdict.as_dict()["unpriceable_positions"] == ["dead"]
        assert verdict.as_dict()["open_positions_unpriceable"] == 1

    def test_a_position_never_priced_is_unpriceable_not_critical(self) -> None:
        """No evidence a refresh would produce anything, so it cannot be waited on."""
        census = census_from([position("never", age=None)])
        assert census.unpriceable == 1
        assert census.critical == 0

    def test_an_outage_length_gap_is_still_recoverable(self) -> None:
        """The boundary that matters.

        The real outage ran 2h49m. A position dark for that long must count as
        stale-and-recoverable — it blocks entries and gets re-primed — rather
        than being written off as a dead pool.
        """
        census = census_from([position("outage", age=169 * 60)])
        assert census.critical == 1
        assert census.unpriceable == 0


class TestRecoveryOrder:
    """10. Recovery is complete when the book is fresh, not when a timer expires."""

    def test_recovery_is_incomplete_while_a_managed_position_is_dark(self) -> None:
        """The feed being back is not the same as the book being back.

        This is the USMS case exactly: at 13:41 the feed was producing again,
        and this position had no priced observation until 14:25.
        """
        census = census_from([position("usms", age=45 * 60)])
        verdict = health(HEALTHY_FEED, census)
        assert verdict.state is FeedState.RECOVERING
        assert verdict.primary_reason is EntryBlockReason.RECOVERY_INCOMPLETE
        assert verdict.as_dict()["recovery"] == "INCOMPLETE"

    def test_recovery_completes_only_once_every_position_has_priced(self) -> None:
        blocked = health(HEALTHY_FEED, census_from([position("a", age=600)]))
        assert blocked.entries_allowed is False
        recovered = health(HEALTHY_FEED, census_from([position("a", age=8)]))
        assert recovered.entries_allowed is True
        assert recovered.as_dict()["recovery"] == "COMPLETE"

    def test_a_stale_book_under_a_slow_feed_names_the_feed_not_the_recovery(self) -> None:
        """Cause over symptom.

        When the feed itself is lagging, the positions are stale *because* of
        it; reporting RECOVERY_INCOMPLETE would send the reader to fix the
        wrong thing.
        """
        slow = FeedEvidence(
            newest_priced_at=NOW - timedelta(seconds=200),
            recent_priced_snapshots=1_000,
            recent_priced_mints=300,
        )
        verdict = assess(slow, census_from([position("a", age=600)]), now=NOW)
        assert verdict.primary_reason is EntryBlockReason.OPEN_POSITION_STALE


class TestThresholdOverrides:
    """Boundaries are inclusive at the worse side, matching `health.classify`."""

    @pytest.mark.parametrize(
        ("age", "blocked"), [(299.0, False), (300.0, True), (301.0, True)]
    )
    def test_the_feed_stale_boundary_is_inclusive(self, age: float, blocked: bool) -> None:
        evidence = FeedEvidence(
            newest_priced_at=NOW - timedelta(seconds=age),
            recent_priced_snapshots=5_000,
            recent_priced_mints=1_200,
        )
        verdict = assess(
            evidence,
            census_from([]),
            now=NOW,
            thresholds=Thresholds(feed_stale_seconds=300.0),
        )
        assert (not verdict.entries_allowed) is blocked

    def test_a_clock_skewed_future_reading_is_not_infinitely_healthy(self) -> None:
        """A row dated slightly ahead reads as age zero, never as negative."""
        skewed = FeedEvidence(
            newest_priced_at=NOW + timedelta(seconds=30),
            recent_priced_snapshots=5_000,
            recent_priced_mints=1_200,
        )
        assert assess(skewed, census_from([]), now=NOW).feed_age_seconds == 0.0
