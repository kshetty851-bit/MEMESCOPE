"""Every transition, on hand-built numbers."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.labs.nse_breakout import config, states
from app.labs.nse_breakout.levels import Cluster, Levels

D0 = date(2024, 1, 1)
LEVEL = 100.0


def reading(close: float, *, volume_mult: float = 1.0,
            resistance: float | None = LEVEL, touches: int = 3) -> Levels:
    """A `Levels` with exactly the fields the machine reads."""
    mean = 1000.0
    return Levels(
        clusters=(Cluster(resistance or 0.0, touches, D0, D0, False),),
        nearest_resistance=resistance, is_52w_high=False, week52_high=resistance,
        atr=2.0, volume_mean=mean, volume_slow_mean=mean,
        range_high=close * 1.05, range_low=close * 0.95, close=close,
        volume=mean * volume_mult, bars=300)


def step(episode: states.EpisodeState, close: float, score: int, when: date,
         **kw) -> tuple[states.Evaluation, states.EpisodeState]:
    level_read = reading(close, **kw)
    evaluation = states.evaluate(level_read, score, episode)
    return evaluation, states.advance(episode, evaluation, when, close)


# --- entry ----------------------------------------------------------------------

def test_watch_needs_the_score_and_the_distance() -> None:
    far, near = 88.0, 97.0                      # -12% and -3% from the level
    assert step(states.EpisodeState(), near, 61, D0)[0].state == states.WATCH
    assert step(states.EpisodeState(), near, 59, D0)[0].state == states.NONE
    assert step(states.EpisodeState(), far, 99, D0)[0].state == states.NONE


def test_near_is_the_tighter_pair_of_thresholds() -> None:
    assert step(states.EpisodeState(), 97.0, 70, D0)[0].state == states.NEAR
    assert step(states.EpisodeState(), 97.0, 69, D0)[0].state == states.WATCH
    assert step(states.EpisodeState(), 93.0, 99, D0)[0].state == states.WATCH


def test_a_close_already_above_the_level_is_not_a_setup() -> None:
    """Nothing to break. NEAR means "about to", and a stock through the level
    on no volume is past it, not approaching it."""
    assert step(states.EpisodeState(), 100.5, 99, D0)[0].state == states.NONE


def test_an_episode_records_the_close_on_the_day_it_first_went_near() -> None:
    """`ref_price` is what buying the setup would have paid; it is fixed on the
    first WATCH/NEAR bar and never revisited."""
    _, episode = step(states.EpisodeState(), 97.0, 75, D0)
    assert episode.first_near_date == D0 and episode.ref_price == 97.0
    _, episode = step(episode, 98.5, 80, D0 + timedelta(days=1))
    assert episode.ref_price == 97.0, "not re-marked on a better day"


# --- the breakout ---------------------------------------------------------------

def test_a_breakout_needs_the_margin_and_the_volume() -> None:
    _, watching = step(states.EpisodeState(), 97.0, 75, D0)
    tomorrow = D0 + timedelta(days=1)
    assert step(watching, 100.5, 75, tomorrow, volume_mult=3.0)[0].state != \
        states.BREAKOUT, "inside the confirm margin"
    assert step(watching, 101.5, 75, tomorrow, volume_mult=1.2)[0].state != \
        states.BREAKOUT, "no volume"
    evaluation, _ = step(watching, 101.5, 75, tomorrow, volume_mult=1.6)
    assert evaluation.state == states.BREAKOUT
    assert evaluation.breakout_price == 101.5
    assert evaluation.volume_mult == pytest.approx(1.6)


def test_through_the_level_without_volume_ends_the_setup() -> None:
    """Not a breakout — and not a setup any more either, because the level it
    was waiting on is behind it. Holding it as WATCH would keep an episode open
    against a level that no longer stands in the way."""
    _, watching = step(states.EpisodeState(), 97.0, 75, D0)
    evaluation, _ = step(watching, 101.5, 75, D0 + timedelta(days=1),
                         volume_mult=1.1)
    assert evaluation.state == states.FAILED
    assert evaluation.reason == "no_volume"


def test_the_first_confirmed_breakout_is_the_breakout() -> None:
    """Pre-decided. Later closes through the level are events, not a second
    breakout, so `breakout_price` cannot drift upward with the stock."""
    _, episode = step(states.EpisodeState(), 97.0, 75, D0)
    _, episode = step(episode, 101.5, 75, D0 + timedelta(days=1), volume_mult=2.0)
    assert episode.breakout_price == 101.5
    _, episode = step(episode, 130.0, 75, D0 + timedelta(days=2), volume_mult=5.0)
    assert episode.breakout_price == 101.5
    assert episode.breakout_date == D0 + timedelta(days=1)


def test_the_level_is_fixed_once_the_episode_opens() -> None:
    """Without this a stock drifting up has its target quietly raised every
    bar and can never break out — and a breakout would immediately re-target
    the next level, so the episode would never record what it opened for."""
    _, episode = step(states.EpisodeState(), 97.0, 75, D0)
    assert episode.resistance == LEVEL
    evaluation, episode = step(episode, 98.0, 75, D0 + timedelta(days=1),
                               resistance=140.0)
    assert episode.resistance == LEVEL, "today's nearest level is irrelevant now"
    assert evaluation.state == states.NEAR


# --- the ways out ---------------------------------------------------------------

def test_a_close_back_under_the_level_inside_the_window_is_a_false_breakout() -> None:
    _, episode = step(states.EpisodeState(), 97.0, 75, D0)
    _, episode = step(episode, 101.5, 75, D0 + timedelta(days=1), volume_mult=2.0)
    evaluation, episode = step(episode, 99.0, 75, D0 + timedelta(days=2))
    assert evaluation.state == states.FALSE_BREAKOUT
    assert episode.state == states.FALSE_BREAKOUT


def test_the_same_close_after_the_window_is_not() -> None:
    """Five bars is the window. A stock that holds the level for a week and
    then falls back has broken out and then gone down, which is a different
    fact from never having broken out at all."""
    _, episode = step(states.EpisodeState(), 97.0, 75, D0)
    _, episode = step(episode, 101.5, 75, D0 + timedelta(days=1), volume_mult=2.0)
    for i in range(config.FALSE_WINDOW_DAYS + 1):
        _, episode = step(episode, 103.0, 75, D0 + timedelta(days=2 + i))
    evaluation, _ = step(episode, 99.0, 75, D0 + timedelta(days=20))
    assert evaluation.state == states.BREAKOUT


def test_falling_away_from_the_level_fails_the_setup() -> None:
    _, episode = step(states.EpisodeState(), 97.0, 75, D0)
    evaluation, _ = step(episode, 91.0, 75, D0 + timedelta(days=1))
    assert evaluation.state == states.FAILED and evaluation.reason == "fell_away"


def test_a_score_that_fades_for_five_bars_fails_the_setup() -> None:
    _, episode = step(states.EpisodeState(), 97.0, 75, D0)
    for i in range(config.FAIL_SCORE_BARS - 1):
        evaluation, episode = step(episode, 96.0, 40, D0 + timedelta(days=1 + i))
        assert evaluation.state != states.FAILED, f"gave up after {i + 1} bars"
    evaluation, _ = step(episode, 96.0, 40, D0 + timedelta(days=10))
    assert evaluation.state == states.FAILED
    assert evaluation.reason == "score_faded"


def test_one_good_bar_resets_the_fade_count() -> None:
    _, episode = step(states.EpisodeState(), 97.0, 75, D0)
    for i in range(4):
        _, episode = step(episode, 96.0, 40, D0 + timedelta(days=1 + i))
    _, episode = step(episode, 96.0, 75, D0 + timedelta(days=6))
    assert episode.weak_bars == 0
    evaluation, _ = step(episode, 96.0, 40, D0 + timedelta(days=7))
    assert evaluation.state != states.FAILED


def test_an_episode_expires_after_the_maximum_bars() -> None:
    _, episode = step(states.EpisodeState(), 97.0, 75, D0)
    for i in range(config.MAX_EPISODE_DAYS - 1):
        evaluation, episode = step(episode, 97.0, 75, D0 + timedelta(days=1 + i))
        assert evaluation.state != states.EXPIRED
    evaluation, episode = step(episode, 97.0, 75, D0 + timedelta(days=200))
    assert evaluation.state == states.EXPIRED
    assert episode.state == states.EXPIRED


def test_the_expiry_window_is_counted_in_bars_not_calendar_days() -> None:
    """A long weekend must not age an episode, and a stock that stops trading
    must not expire faster than one that trades every day. Every window in the
    machine is one unit: bars."""
    _, episode = step(states.EpisodeState(), 97.0, 75, D0)
    evaluation, _ = step(episode, 97.0, 75, D0 + timedelta(days=365))
    assert evaluation.state == states.NEAR, "one bar later is one bar later"


# --- episodes stay open ----------------------------------------------------------

def test_one_dull_bar_does_not_abandon_an_open_episode() -> None:
    """NONE is "no new state this bar", not a way out. Closing on it would
    split one setup into two half-episodes with a ref_price from the wrong
    day — and leave the first one open for ever."""
    _, episode = step(states.EpisodeState(), 97.0, 75, D0)
    evaluation, episode = step(episode, 96.0, 20, D0 + timedelta(days=1))
    assert evaluation.state == states.NONE
    assert episode.is_open and episode.state == states.NEAR
    assert episode.first_near_date == D0 and episode.ref_price == 97.0


def test_a_breakout_with_no_prior_watch_records_no_episode() -> None:
    """Pre-decided: episodes open on the first WATCH/NEAR. A stock that gaps
    through a level nobody was watching has no ref_price, and inventing one
    would be inventing an entry."""
    evaluation, episode = step(states.EpisodeState(), 101.5, 75, D0,
                               volume_mult=3.0)
    assert evaluation.state == states.BREAKOUT
    assert not episode.is_open and episode.opened is None
