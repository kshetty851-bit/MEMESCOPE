"""The Radar row as a trader reads it.

Sprint 24. Everything the Radar knew was already true; it was written in the
engine's vocabulary. `fresh_graduation`, `severity: major`, `provider_id`,
`strength: 85.33` are all accurate and none of them belong on a screen someone
reads in three seconds.

This module is the translation layer, and it is **pure** — no I/O, no clock, no
randomness, `now` always a parameter. That is what makes it replayable: the
sentence beside a token today is the sentence that would be rendered for the
same stored facts a year from now, which is the only way an explanation can be
part of a permanent record.

Three rules, each of which the tests assert:

  - **Never invent.** Every sentence describes a fact already stored. Where no
    fact supports a sentence, the fallback states the detection itself, which
    is always true.
  - **Never predict.** "Volume is expanding", never "volume will expand".
    Templates are indicative, matching `explain.py`.
  - **Never grade on an invented curve.** The risk bands below are cuts on the
    existing risk dimension, published here rather than buried in a component,
    for the same reason `MIN_BASE_RATE_SAMPLE` is published: the threshold is
    part of the claim.

Signal types arrive as plain strings rather than `SignalType`, so this module
imports nothing from `app.opportunities` — the Radar's purity boundary allows
`app.radar` only, and a code is a stable contract without the enum.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.radar.models import RadarReason

# --- Signals, in trader language ---------------------------------------------

#: What each signal type is, said the way a trader would say it. The engine
#: keeps its own names; only this mapping is read aloud.
SIGNAL_LABEL: dict[str, str] = {
    "fresh_graduation": "Recently graduated from Pump.fun",
    "near_graduation": "Approaching graduation",
    "liquidity_expansion": "Liquidity is being added",
    "volume_expansion": "Volume is surging",
    "pre_breakout": "Pressing against its recent high",
    "breakout": "Strong buying pressure",
    "accumulation": "Steady accumulation",
    "holder_growth": "Holder count is climbing",
    "community_surge": "Community activity is climbing",
    "builder_activity": "The team is shipping",
    "whale_accumulation": "Large wallets are buying",
    "smart_money_entry": "Historically profitable wallets have entered",
    "narrative_acceleration": "Its narrative is gaining attention",
}

#: How each signal reads when it is the reason the row is interesting *now*.
#: Written to end mid-sentence so the elapsed time can complete it.
SIGNAL_WHY: dict[str, str] = {
    "fresh_graduation": "Graduated from Pump.fun",
    "near_graduation": "Moved close to graduating",
    "liquidity_expansion": "Liquidity was added",
    "volume_expansion": "Volume surged",
    "pre_breakout": "Moved up against its recent high",
    "breakout": "Broke above its recent high on rising volume",
    "accumulation": "Began accumulating",
    "holder_growth": "Holder count climbed",
    "community_surge": "Community activity climbed",
    "builder_activity": "Development activity picked up",
    "whale_accumulation": "Large wallets bought in",
    "smart_money_entry": "Historically profitable wallets entered",
    "narrative_acceleration": "Its narrative picked up attention",
}


def signal_label(signal_type: str | None) -> str | None:
    """The signal, named for a reader rather than for the engine.

    An unrecognised type returns `None` rather than its raw code: printing
    `pre_breakout` on screen is worse than printing nothing, and a new provider
    shipping before its label is a deploy away from correct.
    """
    if signal_type is None:
        return None
    return SIGNAL_LABEL.get(signal_type)


# --- Risk, in four words -----------------------------------------------------

#: Cuts on the existing risk dimension, which is scored like every other
#: dimension — **high is safe**. Published rather than buried in a component so
#: the band is checkable against the number that produced it.
RISK_BANDS: tuple[tuple[Decimal, str], ...] = (
    (Decimal(70), "low"),
    (Decimal(45), "medium"),
    (Decimal(25), "high"),
)
LOWEST_RISK_BAND = "extreme"


def risk_band(risk_score: Decimal | None) -> str | None:
    """`low` | `medium` | `high` | `extreme`, or `None` when unassessed.

    `None` is not a fifth band and must not render as one. A dimension the
    sweep had no source for is unmeasured, and on this scale an invented zero
    would read as the most dangerous token on the page.
    """
    if risk_score is None:
        return None
    for floor, band in RISK_BANDS:
        if risk_score >= floor:
            return band
    return LOWEST_RISK_BAND


# --- Why now -----------------------------------------------------------------

#: Detection reasons in trader language. Present tense, indicative, one clause.
REASON_WHY: dict[RadarReason, str] = {
    RadarReason.RESISTANCE_BROKEN: "Price has pushed above its recent high",
    RadarReason.VOLUME_EXPANDING: "Trading volume is expanding against its own baseline",
    RadarReason.BUY_PRESSURE_DOMINANT: "Buyers are outnumbering sellers over the last day",
    RadarReason.HIGHER_HIGHS_AND_LOWS: "Highs and lows are both stepping up",
    RadarReason.PRICE_TRENDING_UP: "Price has been trending up",
    RadarReason.LIQUIDITY_GROWING: "Liquidity has been added over the window",
    RadarReason.VOLATILITY_COMPRESSED: "The trading range has narrowed",
    RadarReason.LIQUIDITY_DEEP_FOR_SIZE: "Liquidity is deep for the valuation",
    RadarReason.TURNOVER_HEALTHY: "Daily volume is proportionate to pool depth",
    RadarReason.TREND_ALIGNED: "The short-term trend is holding above the longer one",
    RadarReason.VOLUME_WITHOUT_LIQUIDITY: "Volume far exceeds the liquidity behind it",
    RadarReason.LIQUIDITY_THIN_FOR_SIZE: "Liquidity is thin for the valuation",
    RadarReason.LIQUIDITY_CRITICALLY_THIN: "Liquidity is too thin to support an exit",
    RadarReason.STRUCTURE_BREAKING_DOWN: "Highs and lows are both stepping down",
    RadarReason.PRICE_TRENDING_DOWN: "Price has been trending down",
    RadarReason.VOLUME_FADING: "Trading volume is fading against its own baseline",
    RadarReason.SELL_PRESSURE_DOMINANT: "Sellers are outnumbering buyers over the last day",
    RadarReason.LIQUIDITY_SHRINKING: "Liquidity has been withdrawn over the window",
}

#: Which reason is worth saying first when several are true at once. Ordered by
#: how much it distinguishes this token from the rest of the page: measured on
#: the live board, `trend_aligned` held for 10 of the top 10 and says almost
#: nothing, while `resistance_broken` held for 8 and `volume_expanding` for 4.
#:
#: Reasons absent from this order are never chosen as a headline — they are
#: statements of *missing data* (`community_data_unavailable`,
#: `insufficient_history`, `signal_not_available`), which belong in the
#: evidence figure, not in a sentence about why a token is interesting.
REASON_PRIORITY: tuple[RadarReason, ...] = (
    RadarReason.RESISTANCE_BROKEN,
    RadarReason.VOLUME_EXPANDING,
    RadarReason.BUY_PRESSURE_DOMINANT,
    RadarReason.HIGHER_HIGHS_AND_LOWS,
    RadarReason.PRICE_TRENDING_UP,
    RadarReason.LIQUIDITY_GROWING,
    RadarReason.VOLUME_WITHOUT_LIQUIDITY,
    RadarReason.LIQUIDITY_CRITICALLY_THIN,
    RadarReason.LIQUIDITY_THIN_FOR_SIZE,
    RadarReason.STRUCTURE_BREAKING_DOWN,
    RadarReason.PRICE_TRENDING_DOWN,
    RadarReason.VOLUME_FADING,
    RadarReason.SELL_PRESSURE_DOMINANT,
    RadarReason.LIQUIDITY_SHRINKING,
    RadarReason.VOLATILITY_COMPRESSED,
    RadarReason.LIQUIDITY_DEEP_FOR_SIZE,
    RadarReason.TURNOVER_HEALTHY,
    RadarReason.TREND_ALIGNED,
)

#: How far a token must have moved from detection before the move is the most
#: interesting thing about it. Below these it is noise, and saying "up 1.1x
#: since detection" would dress a rounding error as news.
MOVE_UP_THRESHOLD = Decimal("1.5")
MOVE_DOWN_THRESHOLD = Decimal("0.6")

_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 3_600
_SECONDS_PER_DAY = 86_400


@dataclass(frozen=True, slots=True)
class WhyNow:
    """One sentence, and the stable code that produced it.

    The code is what a client keys on; the sentence is what it displays. Both
    are rendered here so rewording is a deploy rather than a migration, and so
    the client cannot compose a second opinion about the same token.
    """

    code: str
    sentence: str


def elapsed(seconds: int) -> str:
    """A duration as a phrase that completes a sentence: "4 minutes ago"."""
    value = max(0, seconds)
    if value < _SECONDS_PER_MINUTE:
        return "moments ago"
    if value < _SECONDS_PER_HOUR:
        minutes = value // _SECONDS_PER_MINUTE
        return f"{minutes} minute{'' if minutes == 1 else 's'} ago"
    if value < _SECONDS_PER_DAY:
        hours = value // _SECONDS_PER_HOUR
        return f"{hours} hour{'' if hours == 1 else 's'} ago"
    days = value // _SECONDS_PER_DAY
    return f"{days} day{'' if days == 1 else 's'} ago"


def _multiple(value: Decimal) -> str:
    """A multiple as it reads mid-sentence: 2.4x, 17x."""
    return f"{value:.0f}x" if value >= 10 else f"{value:.1f}x"


def why_now(
    *,
    now: datetime,
    signal_type: str | None = None,
    signal_detected_at: datetime | None = None,
    current_multiple: Decimal | None = None,
    detection_reasons: tuple[str, ...] = (),
    first_detected_at: datetime | None = None,
) -> WhyNow:
    """The one sentence that answers "why is this here, now?".

    Priority is by how time-sensitive the fact is, not by how flattering it is:

      1. **A live signal.** Something changed, and it has a timestamp. This is
         the only input that is genuinely about *now* rather than about the
         token's state, so it outranks everything.
      2. **A large move since detection.** The Radar's own claim, marked to
         market. Stated in both directions — a token down 70% from detection
         gets that sentence, because a track record that only narrates winners
         is not a track record.
      3. **The strongest detection reason**, in priority order.
      4. **The detection itself**, which is always true and therefore always
         available as a floor. There is no case where this function returns
         nothing to say.

    Every branch describes a stored fact. None estimates, and none forecasts.
    """
    if signal_type is not None and signal_detected_at is not None:
        opener = SIGNAL_WHY.get(signal_type)
        if opener is not None:
            ago = elapsed(int((now - signal_detected_at).total_seconds()))
            return WhyNow(code=f"signal:{signal_type}", sentence=f"{opener} {ago}.")

    if current_multiple is not None and current_multiple > 0:
        if current_multiple >= MOVE_UP_THRESHOLD:
            return WhyNow(
                code="move_up",
                sentence=f"Trading {_multiple(current_multiple)} above where it was detected.",
            )
        if current_multiple <= MOVE_DOWN_THRESHOLD:
            drop = (Decimal(1) - current_multiple) * 100
            return WhyNow(
                code="move_down",
                sentence=f"Down {drop:.0f}% from where it was detected.",
            )

    chosen = _strongest_reason(detection_reasons)
    if chosen is not None:
        return WhyNow(code=f"reason:{chosen.value}", sentence=f"{REASON_WHY[chosen]}.")

    if first_detected_at is not None:
        ago = elapsed(int((now - first_detected_at).total_seconds()))
        return WhyNow(code="detected", sentence=f"Picked up by the Radar {ago}.")

    # Reachable only for a row with no detection timestamp, which the schema
    # does not permit. Stated rather than raised: a row that renders is better
    # than a page that 500s over a sentence.
    return WhyNow(code="unavailable", sentence="On the Radar; no change recorded yet.")


def _strongest_reason(codes: tuple[str, ...]) -> RadarReason | None:
    """The highest-priority reason present, or `None` if none is sayable.

    Unknown codes are skipped rather than rendered. A reason the engine added
    and this module has not learned yet must not reach a screen as a raw
    identifier.
    """
    present: set[RadarReason] = set()
    for code in codes:
        try:
            present.add(RadarReason(code))
        except ValueError:
            continue
    for reason in REASON_PRIORITY:
        if reason in present:
            return reason
    return None
