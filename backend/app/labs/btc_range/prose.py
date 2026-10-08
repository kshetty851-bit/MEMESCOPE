"""One sentence per reason code, rendered at response time.

Prose is never stored and never composed on the client (CLAUDE.md): a stored
sentence would freeze today's wording into history, and a client-side one would
let two surfaces drift apart. Rewording here is a deploy, not a migration.

Every sentence describes what was OBSERVED. None says what to do - the page this
feeds is paper only and must read the same to someone who is not allowed to
trade. `test_btc_range_prose` holds every sentence to that.
"""

from __future__ import annotations

from app.labs.btc_range.types import Reason

REASON_TEXT: dict[Reason, str] = {
    Reason.NEAR_SUPPORT: (
        "Price is in the lower part of the range, within the entry zone of support."
    ),
    Reason.NEAR_RESISTANCE: (
        "Price is in the upper part of the range, within the entry zone of resistance."
    ),
    Reason.MID_RANGE: (
        "Price is between the two entry zones, away from both edges of the range."
    ),
    Reason.TRENDING: (
        "Closes across the window moved mostly in one direction, "
        "so the window reads as a trend rather than a range."
    ),
    Reason.BREAKOUT_UP: "Price closed above the top of the range.",
    Reason.BREAKOUT_DOWN: "Price closed below the bottom of the range.",
    Reason.LOW_CONFIDENCE: (
        "The range is not well established: its edge touches, flatness and width "
        "score below the minimum confidence."
    ),
    Reason.RANGE_TOO_NARROW: "The range is narrower than the minimum width.",
    Reason.RANGE_TOO_WIDE: "The range is wider than the maximum width.",
    Reason.POOR_REWARD_RISK: (
        "The distance to the target is small next to the distance to the stop, "
        "below the minimum reward to risk."
    ),
    Reason.COSTS_EXCEED_TARGET: (
        "Round-trip fees and slippage are at least as large as the distance to the target."
    ),
    Reason.SIDE_DISABLED: "Price is at an edge on a side the configuration has turned off.",
    Reason.INSUFFICIENT_DATA: "There are not enough closed candles to measure a range yet.",
}


def reason_text(reason: Reason | str) -> str:
    """The sentence for a code.

    An unknown code returns the code itself rather than raising: a reason added
    to the engine before its prose should show up as a visible raw code on the
    page, not as a 500 on the whole status board.
    """
    try:
        return REASON_TEXT[Reason(reason)]
    except (KeyError, ValueError):
        return str(reason)
