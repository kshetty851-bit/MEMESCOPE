"""Who gets polled and who stops. Pure rules, so no fakes and no I/O.

Every poll of every watched token costs an RPC call, so these rules are the
lab's whole cost model. They are also the rules most likely to be quietly wrong
in a way that shows up months later as a missing token.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.labs.graduation import config
from app.labs.graduation.watchset import TokenState, WatchSet, fingerprint
from app.services.curve.state import CurveState

D = Decimal
NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


def reading(real_token: int = 793100000000000, complete: bool = False,
            real_sol: int = 6) -> CurveState:
    return CurveState(
        virtual_token_reserves=279900000000000 + real_token,
        virtual_sol_reserves=30000000000 + real_sol,
        real_token_reserves=real_token, real_sol_reserves=real_sol,
        token_total_supply=1000000000000000, complete=complete,
    )


def token(mint: str = "m1", seen: datetime = NOW, pool: str = "pump") -> TokenState:
    return TokenState(mint=mint, first_seen_at=seen, launch_pool=pool)


def watch(max_size: int = 500) -> WatchSet:
    return WatchSet(max_size=max_size)


# --- admission ----------------------------------------------------------------

def test_a_launch_is_admitted() -> None:
    w = watch()
    assert w.admit(token()) is None
    assert "m1" in w and len(w) == 1


def test_a_bonk_launch_is_refused() -> None:
    """A bonk curve has no PDA under the pump.fun program at all, so polling it
    would read an account that does not exist, every fifteen seconds, for ever."""
    w = watch()
    w.admit(token(pool="bonk"))
    assert len(w) == 0 and w.rejected_foreign == 1


def test_admitting_the_same_mint_twice_is_a_no_op() -> None:
    w = watch()
    w.admit(token())
    w.admit(token())
    assert len(w) == 1 and w.admitted == 1


# --- eviction -----------------------------------------------------------------

def test_a_full_set_evicts_the_lowest_progress_token() -> None:
    w = watch(max_size=2)
    low, high = token("low"), token("high")
    low.last_progress, high.last_progress = D("5"), D("40")
    w.admit(low)
    w.admit(high)

    evicted = w.admit(token("new"))
    assert evicted is not None and evicted.mint == "low"
    assert sorted(w.mints()) == ["high", "new"]


def test_the_evicted_token_is_handed_back_so_it_can_be_written() -> None:
    """A token that vanished from memory without being returned would be a
    token the tables never mention — the lab would have watched it and left no
    trace that it did."""
    w = watch(max_size=1)
    w.admit(token("first"))
    evicted = w.admit(token("second"))
    assert evicted is not None and evicted.mint == "first"


def test_a_tracked_token_is_never_evicted_for_room() -> None:
    """Tracked tokens are the entire point of the watch set."""
    w = watch(max_size=1)
    tracked = token("tracked")
    tracked.tracked_at, tracked.last_progress = NOW, D("85")
    w.admit(tracked)

    assert w.admit(token("newcomer")) is None
    assert w.mints() == ["tracked"]
    assert w.rejected_full == 1


def test_oldest_wins_the_tie_among_equally_unprogressed_tokens() -> None:
    w = watch(max_size=2)
    w.admit(token("older", seen=NOW - timedelta(minutes=10)))
    w.admit(token("newer", seen=NOW))
    evicted = w.admit(token("newest"))
    assert evicted is not None and evicted.mint == "older"


# --- silence ------------------------------------------------------------------

def test_silence_is_measured_on_the_reserves_not_the_clock() -> None:
    """A poll happens whether or not anybody traded. If silence were measured
    from the last POLL, every dead token would look permanently alive and the
    set would fill with curves nobody has ever bought — two thirds of them."""
    w = watch()
    state = token()
    w.admit(state)
    still = reading()

    # The FIRST read is movement — it is the first time anything is known about
    # this curve — so it starts the clock. Every identical read after it is not.
    first = NOW + timedelta(seconds=15)
    assert state.observe(still, D("0"), first) is True
    assert state.last_progress_change_at == first

    at = first
    for _ in range(239):
        at += timedelta(seconds=15)
        assert state.observe(still, D("0"), at) is False

    assert state.last_sample_at == at                 # it WAS looked at, 240 times
    assert state.last_progress_change_at == first     # and nothing ever happened
    assert w.expiry_reason(state, at) == "silent"


def test_a_token_never_read_at_all_still_ages_out() -> None:
    """An RPC that answers for nobody must not pin a token in the set for ever.
    With no successful read there is no change timestamp, so silence falls back
    to when the token was first seen."""
    w = watch()
    state = token()
    w.admit(state)
    assert state.last_progress_change_at is None
    assert w.expiry_reason(state, NOW + timedelta(minutes=config.SILENT_MIN)) == "silent"


def test_a_moving_curve_resets_the_silence_timer() -> None:
    w = watch()
    state = token()
    w.admit(state)

    late = NOW + timedelta(minutes=config.SILENT_MIN - 1)
    assert state.observe(reading(real_token=700000000000000), D("11.8"), late) is True
    assert state.last_progress_change_at == late
    assert w.expiry_reason(state, late) is None

    later = late + timedelta(minutes=config.SILENT_MIN + 1)
    assert w.expiry_reason(state, later) == "silent"


def test_a_tracked_token_is_never_evicted_for_silence() -> None:
    """A curve parked at 94% for three hours is not a mistake to clean up. It
    is the observation."""
    w = watch()
    state = token()
    w.admit(state)
    state.observe(reading(real_token=79310000000000), D("90"), NOW)
    assert state.tracked

    hours_later = NOW + timedelta(hours=3)
    assert w.expiry_reason(state, hours_later) is None


# --- the other two ways out ---------------------------------------------------

def test_a_migrated_token_leaves_after_the_window() -> None:
    w = watch()
    state = token()
    state.migrated_at = NOW
    w.admit(state)

    inside = NOW + timedelta(seconds=config.POST_MIGRATION_SECONDS - 60)
    assert w.expiry_reason(state, inside) is None
    outside = NOW + timedelta(seconds=config.POST_MIGRATION_SECONDS + 60)
    assert w.expiry_reason(state, outside) == "post_migration"


def test_stale_is_the_one_rule_a_tracked_token_can_trip() -> None:
    """The backstop, so the set cannot silt up with tokens that will never
    resolve either way."""
    w = watch()
    state = token()
    state.tracked_at = NOW
    w.admit(state)
    state.observe(reading(real_token=79310000000000), D("90"),
                  NOW + timedelta(hours=config.STALE_HOURS - 1))

    assert w.expiry_reason(state, NOW + timedelta(hours=config.STALE_HOURS - 1)) is None
    assert w.expiry_reason(state, NOW + timedelta(hours=config.STALE_HOURS)) == "stale"


def test_sweep_removes_and_returns_everything_expired() -> None:
    w = watch()
    quiet, busy = token("quiet"), token("busy")
    w.admit(quiet)
    w.admit(busy)
    later = NOW + timedelta(minutes=config.SILENT_MIN + 1)
    busy.observe(reading(real_token=700000000000000), D("11.8"), later)

    swept = w.sweep(later)
    assert [(s.mint, r) for s, r in swept] == [("quiet", "silent")]
    assert w.mints() == ["busy"]


# --- observing ----------------------------------------------------------------

def test_observe_reports_whether_anything_moved() -> None:
    """One comparison drives two decisions — whether a sample is worth writing
    and whether the silence timer resets — so they cannot disagree."""
    state = token()
    assert state.observe(reading(), D("0"), NOW) is True          # first ever
    assert state.observe(reading(), D("0"), NOW) is False         # identical
    assert state.observe(reading(real_sol=7), D("0"), NOW) is True  # a lamport


def test_completing_counts_as_movement_even_with_still_reserves() -> None:
    state = token()
    state.observe(reading(real_token=0), D("100"), NOW)
    assert state.observe(reading(real_token=0, complete=True), D("100"), NOW) is True
    assert state.seen_complete_on_chain is True
    assert state.graduated is True


def test_max_progress_survives_a_sell() -> None:
    state = token()
    state.observe(reading(real_token=79310000000000), D("90"), NOW)
    state.observe(reading(real_token=150000000000000), D("81.1"), NOW)
    assert state.max_progress == D("90")
    assert state.last_progress == D("81.1")
    assert state.tracked is True  # crossing once is enough


def test_crossing_the_threshold_marks_the_token_tracked() -> None:
    state = token()
    state.observe(reading(real_token=300000000000000), D("62.2"), NOW)
    assert state.tracked is False
    at = NOW + timedelta(seconds=15)
    state.observe(reading(real_token=237930000000000), D("70.000"), at)
    assert state.tracked_at == at
    assert state.status == "tracking"


def test_fingerprint_covers_every_reserve() -> None:
    """A change in any one of them is a change. Comparing only the token side
    would miss a buy that moved SOL and rounded to the same token reserve."""
    base = fingerprint(reading())
    assert base != fingerprint(reading(real_sol=7))
    assert base != fingerprint(reading(real_token=1))
    assert base != fingerprint(reading(complete=True))
