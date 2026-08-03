"""Reason codes rendered into English, on the backend.

The frontend never composes these sentences, for the reason `radar/explain.py`
records: a second opinion about the same token, rendered client-side, can
disagree with the engine that produced it.

Nothing here is stored. `opportunity_signals.reason_codes` holds stable
identifiers and the prose lives in this module, so rewording an explanation is
a deploy rather than a migration (ARCHITECTURE_DECISIONS.md AD-07).

Templates are indicative, never predictive: "has left its bonding curve", never
"will run". And never a recommendation — the same boundary every explanation
surface on this platform holds.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.opportunities.models import SignalType

#: One sentence per reason code. Unknown codes render as themselves rather than
#: raising: a provider added in a future sprint should produce a plain-looking
#: explanation, not a 500 on the board.
REASON_MESSAGE: dict[str, str] = {
    "graduated_from_bonding_curve": (
        "This token has left its bonding curve and now trades on an open pool."
    ),
    "trading_venue_changed": (
        "The venue reporting this token's market changed between observations."
    ),
    "approaching_graduation": (
        "This token has filled enough of its bonding curve to be approaching "
        "graduation."
    ),
    "curve_progress_rising": "Curve progress has increased across the window.",
    "curve_progress_stalled": "Curve progress has not moved across the window.",
    "volume_expanding_into_graduation": (
        "Trading volume is running above this token's own earlier baseline."
    ),
    "buy_pressure_dominant": "Buys outnumbered sells across the window.",
    "trade_rate_rising": "Trades are arriving faster than one a minute.",
    "price_broke_trailing_high": (
        "The price has moved above the highest level of this token's own recent "
        "observations."
    ),
    "approaching_trailing_high": (
        "The price is trading close to the highest level of this token's own "
        "recent observations, without having passed it."
    ),
    "volume_expanded_over_baseline": (
        "Hourly volume is running above the median of this token's own recent "
        "observations."
    ),
    "pre_breakout_became_breakout": (
        "The price cleared the range it had been pressing against, so this "
        "reading resolved into a breakout."
    ),
    "pre_breakout_pressure_faded": (
        "The price fell back out of the band it was holding, so it is no longer "
        "pressing against its range."
    ),
    "near_graduation_became_graduation": (
        "The token graduated to an open pool, resolving this reading."
    ),
    "curve_progress_retreated": (
        "Bonding-curve progress fell back below the level this reading was "
        "made at."
    ),
    "graduation_venue_reverted": (
        "The token was observed back on a bonding curve, which contradicts the "
        "venue change this reading reported."
    ),
    "thin_observation_window": (
        "Few observations stand behind this reading, so it is held with less "
        "confidence."
    ),
}

#: What each signal type is asking. Shown as the card's headline.
SIGNAL_HEADLINE: dict[SignalType, str] = {
    SignalType.FRESH_GRADUATION: "Freshly graduated",
    SignalType.NEAR_GRADUATION: "Approaching graduation",
    SignalType.LIQUIDITY_EXPANSION: "Liquidity expanding",
    SignalType.VOLUME_EXPANSION: "Volume expanding",
    SignalType.PRE_BREAKOUT: "Approaching breakout",
    SignalType.BREAKOUT: "Breaking out",
    SignalType.ACCUMULATION: "Entering accumulation",
    SignalType.HOLDER_GROWTH: "Holders growing",
    SignalType.COMMUNITY_SURGE: "Community growing",
    SignalType.BUILDER_ACTIVITY: "Builder activity",
    SignalType.WHALE_ACCUMULATION: "Whale accumulation",
    SignalType.SMART_MONEY_ENTRY: "Smart money entry",
    SignalType.NARRATIVE_ACCELERATION: "Narrative accelerating",
}

#: Which limits apply to which signal type — what the platform could *not*
#: check while forming this claim. Not decoration: the limits clause is where
#: the coverage gap stays visible instead of the card quietly looking complete.
#: See ARCHITECTURE_DECISIONS.md §14 for why each is absent.
SIGNAL_LIMITS: dict[SignalType, tuple[str, ...]] = {
    SignalType.FRESH_GRADUATION: (
        "Liquidity could not be verified before graduation — bonding-curve pools "
        "report none.",
        "Holder distribution is not collected, so concentration was not checked.",
    ),
    SignalType.BREAKOUT: (
        "The range is this token's own recent observations, not a fixed period "
        "— snapshot cadence varies by token age.",
        "Holder distribution is not collected, so concentration was not checked.",
        "Liquidity is not reported for bonding-curve pools, so depth was not "
        "checked.",
    ),
    SignalType.PRE_BREAKOUT: (
        "The range is this token's own recent observations, not a fixed period "
        "— snapshot cadence varies by token age.",
        "Whether the range actually breaks is not claimed; only that price is "
        "near it on expanded volume.",
        "Holder distribution is not collected, so concentration was not checked.",
    ),
    SignalType.NEAR_GRADUATION: (
        "Curve progress is inferred from reported market cap, which is not a "
        "direct read of the bonding curve.",
        "Liquidity is not reported for bonding-curve pools, so depth was not "
        "checked.",
        "Holder distribution is not collected, so concentration was not checked.",
    ),
}


def headline(signal_type: SignalType) -> str:
    return SIGNAL_HEADLINE.get(
        signal_type, signal_type.value.replace("_", " ").capitalize()
    )


def message(code: str) -> str:
    return REASON_MESSAGE.get(code, code.replace("_", " ").capitalize())


@dataclass(frozen=True, slots=True)
class Explanation:
    """Why this appeared *now*, in the five parts of AD-07.

    `trigger` — what crossed. `boundary` — the threshold, named. `delta` — from
    what, to what, over which window. `corroboration` — which other providers
    agree. `limits` — what could not be checked, and why.
    """

    headline: str
    trigger: str
    boundary: str | None
    delta: tuple[str, ...]
    corroboration: tuple[str, ...]
    limits: tuple[str, ...]


def explain(
    *,
    signal_type: SignalType,
    reason_codes: tuple[str, ...],
    evidence: tuple[dict[str, str | None], ...],
    corroborating_providers: tuple[str, ...] = (),
) -> Explanation:
    """Render one signal's explanation from stored codes and evidence.

    Pure, and derived entirely from what was persisted — so the same signal
    explains the same way whenever it is read, and a board reconstructed from a
    past moment reads as it did then.
    """
    codes = tuple(reason_codes)
    trigger = message(codes[0]) if codes else headline(signal_type)
    supporting = tuple(message(code) for code in codes[1:])

    delta = tuple(
        f"{item.get('label')}: {item.get('value')}"
        + (f" ({item['detail']})" if item.get("detail") else "")
        for item in evidence
        if item.get("label") and item.get("value")
    )

    return Explanation(
        headline=headline(signal_type),
        trigger=trigger,
        boundary=supporting[0] if supporting else None,
        delta=delta,
        corroboration=(
            tuple(f"Also reported by {provider}." for provider in corroborating_providers)
            if corroborating_providers
            else ()
        ),
        limits=SIGNAL_LIMITS.get(signal_type, ()),
    )
