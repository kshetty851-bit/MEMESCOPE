"""A dying token must be watched at least as closely as a living one.

Two defects, found 2026-09-04 while trying to measure the market's own return
over a 6-8 hour hold. The estimate came out **+16.4%** when tokens with no
forward price were dropped and **-2.3%** when the deaths among them were
counted — the sign of the whole population, decided by whether the losers were
observed.

Both defects pushed in the same direction, which is why the bias was large:

  1. `scheduler.decide` eased off on `consecutive_empty`, so a token was polled
     LESS the longer its pool stayed missing. Self-reinforcing: each empty
     lengthened the interval, so the next empty arrived later, so the death was
     timestamped later still.

  2. Death was recorded only as one `INACTIVE` snapshot at a fixed empty count.
     One row is invisible to any window that does not contain it, and snapshots
     expire under retention while the fact stays true forever.

Neither made anything fail. Both made the losses quieter than the wins.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.backoff import BackoffPolicy
from app.services.market.scheduler import RefreshScheduler, SchedulePolicy

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
OLD_TOKEN = NOW - timedelta(days=30)      # past every age tier: 6h cadence
YOUNG_TOKEN = NOW - timedelta(hours=2)    # YOUNG tier: 5min cadence


POLICY = SchedulePolicy(
    fresh_max_minutes=30, fresh_interval_seconds=30,
    young_max_minutes=360, young_interval_seconds=300,
    mature_max_minutes=1440, mature_interval_seconds=1800,
    old_interval_seconds=21600, nursery_interval_seconds=60,
)
# Deterministic, so the failure path asserts a number rather than a range.
NO_JITTER = BackoffPolicy(
    initial_seconds=30.0, max_seconds=21600.0, multiplier=2.0, jitter=False
)


def _scheduler() -> RefreshScheduler:
    return RefreshScheduler(policy=POLICY, backoff=NO_JITTER)


def _interval(discovered_at=YOUNG_TOKEN, **kw) -> float:
    return _scheduler().decide(
        now=NOW, discovered_at=discovered_at, **kw
    ).interval_seconds


# --------------------------------------------------------------------------
# 1. the backoff that hid the deaths
# --------------------------------------------------------------------------


def test_a_token_that_never_listed_still_backs_off() -> None:
    """The original behaviour, kept. A new mint with no pool yet is waiting to
    be listed, and polling it hard forever would spend the budget on nothing."""
    base = _interval(consecutive_empty=0, ever_had_data=False)
    assert _interval(consecutive_empty=5, ever_had_data=False) > base


def test_a_token_that_LOST_its_pool_does_not_back_off() -> None:
    """The fix. Having had data makes an empty result a death, not a wait.

    This is the line that decided the sign of the population's return: a token
    watched less as it fails is a loss the platform does not see.
    """
    base = _interval(consecutive_empty=0, ever_had_data=True)
    for empties in (1, 5, 20):
        assert _interval(consecutive_empty=empties, ever_had_data=True) == base


def test_the_two_cases_are_scheduled_differently() -> None:
    """Same empty count, opposite meaning, so they must not share a cadence."""
    waiting = _interval(consecutive_empty=8, ever_had_data=False)
    dying = _interval(consecutive_empty=8, ever_had_data=True)
    assert dying < waiting


def test_provider_errors_still_back_off_for_a_dying_token() -> None:
    """A death is not a licence to hammer a broken endpoint. The failure path
    is about the PROVIDER, and it still applies."""
    steady = _interval(consecutive_failures=0, ever_had_data=True)
    assert _interval(consecutive_failures=6, ever_had_data=True) > steady


def test_an_old_token_keeps_the_faster_cadence_it_already_had() -> None:
    """The bug my own first fix introduced, pinned.

    An OLD token sits on a six-hour tier while the empty backoff capped at the
    mature interval of thirty minutes — so the old code accidentally polled
    dying old tokens TWELVE TIMES faster. Holding the tier would have undone
    that, making the fix worse than the defect for exactly the tokens most
    likely to be dead.
    """
    dying_old = _interval(OLD_TOKEN, consecutive_empty=4, ever_had_data=True)
    assert dying_old == POLICY.mature_interval_seconds
    assert dying_old < POLICY.old_interval_seconds


def test_the_reason_names_which_case_it_took() -> None:
    """Whoever reads a schedule log should not have to infer this."""
    dying = _scheduler().decide(
        now=NOW, discovered_at=OLD_TOKEN, consecutive_empty=3, ever_had_data=True
    )
    waiting = _scheduler().decide(
        now=NOW, discovered_at=OLD_TOKEN, consecutive_empty=3, ever_had_data=False
    )
    assert "confirming_death" in dying.reason
    assert "awaiting_listing" in waiting.reason


def test_the_default_preserves_the_old_behaviour() -> None:
    """`ever_had_data` defaults False, so a caller that has not been taught
    about this gets the pre-existing backoff rather than a silent change."""
    assert _interval(consecutive_empty=5) == _interval(
        consecutive_empty=5, ever_had_data=False
    )


# --------------------------------------------------------------------------
# 2. the death that left no durable record
# --------------------------------------------------------------------------


@pytest.mark.integration
class TestTheDeathIsRecordedDurably:
    """`delisted_at` on the enrichment state, written once and cleared on return.

    The `INACTIVE` snapshot that marks the same event is written once, at a
    fixed empty count, and then expires with retention — so it cannot answer
    "was this token alive at time T" for any T outside the window it happens to
    occupy. A query for a PRICE excludes dead tokens silently, which is how a
    population returning -2.3% measured as +16.4%.
    """

    async def _state(self, session, mint: str, *, snapshots: int):
        from datetime import timedelta as _td

        from app.models.market import EnrichmentStatus, TokenEnrichmentState
        from app.repositories.token import TokenRepository

        token = await TokenRepository(session).insert_if_absent({
            "mint_address": mint, "signature": f"sig-{mint}", "slot": 1,
            "discovered_at": NOW - _td(days=7), "block_time": NOW - _td(days=7),
            "symbol": mint[:6],
        })
        assert token is not None
        state = TokenEnrichmentState(
            token_id=token.id, mint_address=mint,
            status=EnrichmentStatus.ACTIVE, next_refresh_at=NOW,
            total_snapshots=snapshots,
        )
        session.add(state)
        await session.flush()
        return state

    async def _record(self, session, state, *, had_data: bool, at=NOW):
        from app.repositories.market import EnrichmentStateRepository

        return await EnrichmentStateRepository(session).record_result(
            state, now=at, next_refresh_at=at, tier="old",
            succeeded=True, had_data=had_data,
        )

    async def test_the_first_missing_pool_is_when_the_token_died(self, db_session):
        """Stamped at the FIRST absence, not when a threshold confirms it.

        The token had data at the previous poll and does not now; that is the
        earliest moment the platform can defensibly call it dead. Waiting for
        the tenth empty would date the death by the confirmation.
        """
        state = await self._state(db_session, "DeadMint1111111111111111111", snapshots=5)
        assert state.delisted_at is None
        await self._record(db_session, state, had_data=False)
        assert state.delisted_at == NOW

    async def test_later_empties_do_not_move_the_death_later(self, db_session):
        state = await self._state(db_session, "DeadMint2222222222222222222", snapshots=5)
        await self._record(db_session, state, had_data=False, at=NOW)
        later = NOW + timedelta(hours=6)
        await self._record(db_session, state, had_data=False, at=later)
        assert state.delisted_at == NOW, "the death time must not drift forward"

    async def test_a_token_that_comes_back_is_not_dead(self, db_session):
        """A provider gap must leave nothing behind."""
        state = await self._state(db_session, "BackMint3333333333333333333", snapshots=5)
        await self._record(db_session, state, had_data=False)
        assert state.delisted_at is not None
        await self._record(db_session, state, had_data=True, at=NOW + timedelta(minutes=30))
        assert state.delisted_at is None

    async def test_a_mint_that_never_listed_is_not_called_dead(self, db_session):
        """Awaiting listing is not delisting. Most of the table has never
        produced a snapshot, and calling those deaths would mark the market
        dead."""
        state = await self._state(db_session, "NewMint44444444444444444444", snapshots=0)
        await self._record(db_session, state, had_data=False)
        assert state.delisted_at is None
