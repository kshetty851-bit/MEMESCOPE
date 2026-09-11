"""The state machine, as pure functions over one symbol's bars.

`WATCH -> NEAR -> BREAKOUT`, with `FALSE_BREAKOUT`, `FAILED` and `EXPIRED` as
the ways out. No session, no clock: `evaluate()` is given the levels, the score
and the episode so far, and returns the state that bar implies. The engine that
walks the database and writes rows lives in `episodes.py`; keeping the decision
here means a transition can be tested with hand-built numbers instead of a
database, and the replay and the live pass are provably the same rule folded
over different bars.

**Every window here is counted in BARS, not calendar days.** The outcome
horizons are trading days, a stock that does not trade produces no bar, and a
long weekend must not age an episode. One unit throughout.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

from app.labs.nse_breakout import config
from app.labs.nse_breakout.levels import Levels

NONE = "NONE"
WATCH = "WATCH"
NEAR = "NEAR"
BREAKOUT = "BREAKOUT"
FALSE_BREAKOUT = "FALSE_BREAKOUT"
FAILED = "FAILED"
EXPIRED = "EXPIRED"

#: States an episode stays open in.
OPEN_STATES = (WATCH, NEAR, BREAKOUT)
#: States an episode may be OPENED by. Pre-decided: an episode opens on the
#: first WATCH or NEAR, so a stock that gaps straight through a level it was
#: never watched into is reported as BREAKOUT and records no episode — there
#: is no ref_price for it, and inventing one would be inventing an entry.
OPENING_STATES = (WATCH, NEAR)
#: States that close an episode.
CLOSING_STATES = (FALSE_BREAKOUT, FAILED, EXPIRED)


@dataclass(frozen=True, slots=True)
class EpisodeState:
    """What the machine needs to know about the episode so far.

    Deliberately a value rather than the ORM row: `evaluate` has to be callable
    from a replay that has no rows yet.
    """

    opened: date | None = None
    state: str = NONE
    first_near_date: date | None = None
    #: Close on `first_near_date` — what buying at NEAR would have paid.
    ref_price: float | None = None
    #: The level this episode is about. FIXED once the episode opens.
    resistance: float | None = None
    breakout_date: date | None = None
    breakout_price: float | None = None
    #: Bars since the episode opened, and since the breakout.
    bars_open: int = 0
    bars_since_breakout: int = 0
    #: Consecutive bars scoring under `WATCH_SCORE`.
    weak_bars: int = 0

    @property
    def is_open(self) -> bool:
        return self.state in OPEN_STATES


@dataclass(frozen=True, slots=True)
class Evaluation:
    state: str
    resistance: float | None
    #: Set on the bar that confirms a breakout.
    breakout_price: float | None = None
    volume_mult: float | None = None
    #: Why the episode closed, when it did.
    reason: str | None = None
    weak_bars: int = 0

    @property
    def closes_episode(self) -> bool:
        return self.state in CLOSING_STATES


def evaluate(levels: Levels, score: int, episode: EpisodeState) -> Evaluation:
    """The state this bar implies for this symbol.

    **The level is fixed when the episode opens.** After that the episode is
    about THAT price, not whatever is nearest today. Without this a stock
    drifting upward would have its target quietly raised every bar and could
    never break out — and a breakout would immediately re-target the next level
    up, so the episode would never record the thing it was opened to record.

    First rule wins, in this order:

    1. an open episode past `MAX_EPISODE_DAYS` bars has expired, however it
       looks today;
    2. an episode already in BREAKOUT can only turn false or stay;
    3. a close through the fixed level by the confirm margin, on volume, is
       the breakout;
    4. falling `FAIL_PCT` below the level, or `FAIL_SCORE_BARS` weak bars in a
       row, is failure — against the fixed level, for the same reason;
    5. otherwise NEAR, WATCH or nothing, by score and distance.
    """
    close = levels.close
    weak = episode.weak_bars + 1 if score < config.WATCH_SCORE else 0
    level = episode.resistance if episode.is_open else levels.nearest_resistance

    if episode.is_open and episode.bars_open >= config.MAX_EPISODE_DAYS:
        return Evaluation(EXPIRED, level, reason=EXPIRED, weak_bars=weak)

    if episode.state == BREAKOUT:
        if (level is not None and close < level
                and episode.bars_since_breakout <= config.FALSE_WINDOW_DAYS):
            return Evaluation(FALSE_BREAKOUT, level, reason=FALSE_BREAKOUT,
                              weak_bars=weak)
        return Evaluation(BREAKOUT, level, breakout_price=episode.breakout_price,
                          weak_bars=weak)

    if level is None:
        return Evaluation(NONE, None, weak_bars=weak)

    mult = levels.volume_mult
    if close > level * (1 + config.BREAK_CONFIRM_PCT / 100):
        if mult is not None and mult >= config.BREAK_VOL_MULT:
            return Evaluation(BREAKOUT, level, breakout_price=close,
                              volume_mult=mult, weak_bars=weak)
        # Through the level without volume. Not a breakout — and not a setup
        # any more either, because the level it was waiting on is behind it.
        if episode.state in OPENING_STATES:
            return Evaluation(FAILED, level, reason="no_volume", weak_bars=weak)
        return Evaluation(NONE, level, volume_mult=mult, weak_bars=weak)

    if episode.state in OPENING_STATES:
        if close < level * (1 - config.FAIL_PCT / 100):
            return Evaluation(FAILED, level, reason="fell_away", weak_bars=weak)
        if weak >= config.FAIL_SCORE_BARS:
            return Evaluation(FAILED, level, reason="score_faded", weak_bars=weak)

    if close <= 0:
        return Evaluation(NONE, level, weak_bars=weak)
    distance = (level - close) / close * 100
    if distance < 0:
        return Evaluation(NONE, level, weak_bars=weak)
    if score >= config.NEAR_SCORE and distance <= config.NEAR_PCT:
        return Evaluation(NEAR, level, weak_bars=weak)
    if score >= config.WATCH_SCORE and distance <= config.WATCH_PCT:
        return Evaluation(WATCH, level, weak_bars=weak)
    return Evaluation(NONE, level, weak_bars=weak)


def advance(episode: EpisodeState, evaluation: Evaluation, when: date,
            close: float) -> EpisodeState:
    """The episode after this bar. Pure, so the replay and the live pass are
    the same fold over the same function."""
    if evaluation.closes_episode:
        return replace(episode, state=evaluation.state,
                       weak_bars=evaluation.weak_bars)

    if episode.is_open and evaluation.state == NONE:
        # An open episode does NOT close because one bar scored badly or drifted
        # out of range. NONE is "no new state this bar"; the ways out are
        # FAILED, FALSE_BREAKOUT and EXPIRED, and the weak-bar count is what
        # turns a run of NONE bars into FAILED. Without this the episode would
        # be silently abandoned mid-flight and a new one opened when it
        # recovered — two half-episodes where there was one setup, and a
        # ref_price from the wrong day.
        return replace(episode, bars_open=episode.bars_open + 1,
                       bars_since_breakout=episode.bars_since_breakout,
                       weak_bars=evaluation.weak_bars)

    if not episode.is_open and evaluation.state not in OPENING_STATES:
        # Nothing open, and a BREAKOUT or NONE cannot open one. Only the
        # weak-bar count carries across.
        return EpisodeState(weak_bars=evaluation.weak_bars)

    opened = episode.opened if episode.is_open else when
    first_near = episode.first_near_date
    ref_price = episode.ref_price
    if first_near is None and evaluation.state in OPENING_STATES:
        first_near, ref_price = when, close
    breakout_date = episode.breakout_date
    breakout_price = episode.breakout_price
    bars_since_breakout = episode.bars_since_breakout
    if evaluation.state == BREAKOUT:
        if breakout_date is None:
            # Pre-decided: the FIRST confirmed breakout is the breakout. Later
            # closes through the level are events, not a second breakout.
            breakout_date, breakout_price = when, evaluation.breakout_price
            bars_since_breakout = 0
        else:
            bars_since_breakout += 1
    return EpisodeState(
        opened=opened, state=evaluation.state, first_near_date=first_near,
        ref_price=ref_price, resistance=evaluation.resistance,
        breakout_date=breakout_date, breakout_price=breakout_price,
        bars_open=episode.bars_open + 1 if episode.is_open else 1,
        bars_since_breakout=bars_since_breakout,
        weak_bars=evaluation.weak_bars)
