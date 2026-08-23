"""Which Radar tokens the wallet may buy, and why the rest were refused.

Sprint 30 §5 lists seven conditions. They are written here **once**, as a pure
function, because two callers need the same answer for different reasons:

* the evaluator, deciding what to open on this pass;
* the wallet read, deciding whether the page should say
  "Waiting for the next qualified Radar opportunity."

An empty book with cash in it is either "nothing qualified" or "the evaluator
is broken", and those are different facts. Duplicating the conditions across the
two paths would let them drift until the page said one and the trades said the
other.

Every refusal carries a **reason code**, and the reasons are counted rather than
discarded. A wallet that sits in cash has to be able to say what it looked at
and what stopped it — "no qualified token" with no denominator is a claim, not a
measurement.

Pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.paper.models import Candidate

#: What the provider's `trading_status` must read for a token to be tradeable.
#: `unknown` means the provider has not indexed a pool yet and `inactive` means
#: it indexed one with nothing left in it; neither is a market to buy into.
TRADEABLE_STATUS = "trading"


class Refusal(enum.StrEnum):
    """Why a Radar token was not bought.

    One member per published condition, so a count by reason maps back to §5
    line by line. There is deliberately no `OTHER`: a refusal nobody can name is
    a refusal nobody can check.
    """

    #: The wallet has held this mint before. One lifetime trade per token.
    ALREADY_TRADED = "already_traded"
    #: The position is open right now.
    ALREADY_HELD = "already_held"
    #: No market snapshot at all — the token has never been priced.
    NO_MARKET_DATA = "no_market_data"
    #: A snapshot exists but carries no usable price. Unpriced, not free.
    NO_PRICE = "no_price"
    #: The venue reports no pool depth. Bonding-curve pairs report none at all
    #: (ADR 0002), and a trade whose cost cannot be computed cannot be audited.
    NO_LIQUIDITY = "no_liquidity"
    #: The provider does not report the token as trading.
    NOT_TRADEABLE = "not_tradeable"
    #: A price exists but is too old to buy against. Distinct from
    #: `NO_MARKET_DATA` on purpose: a token nobody has priced and a token
    #: whose price stopped updating two hours ago are different failures, and
    #: on 2026-08-21 it was the second one that cost the wallet money.
    MARKET_DATA_STALE = "market_data_stale"
    #: Everything passed, but the cash left is below one position.
    INSUFFICIENT_CASH = "insufficient_paper_cash"


#: The wallet-level refusal recorded when the *operator*, not the candidate and
#: not the feed, stopped an entry. Shaped like `market_health.MARKET_HEALTH_REFUSAL`
#: so the dashboard's refusal counts stay one flat mapping.
ENTRIES_PAUSED_REFUSAL = "entries_paused"


#: The sentence each refusal renders as. Server-side, from a stable code — the
#: platform's rule for all prose, so a rewording is a deploy and not a migration.
REFUSAL_LABELS: dict[str, str] = {
    ENTRIES_PAUSED_REFUSAL: (
        "New entries are paused for capital protection. "
        "Open positions continue to be evaluated and exited normally."
    ),
    Refusal.ALREADY_TRADED: "Already traded by this wallet. One position per token, ever.",
    Refusal.ALREADY_HELD: "Already held.",
    Refusal.NO_MARKET_DATA: "No market data has been collected for this token.",
    Refusal.NO_PRICE: "No usable price in the latest reading.",
    Refusal.NO_LIQUIDITY: (
        "The venue reports no pool depth, so the trade could not be costed or audited."
    ),
    Refusal.NOT_TRADEABLE: "The market provider does not report this token as trading.",
    Refusal.MARKET_DATA_STALE: (
        "The latest price for this token is too old to buy against."
    ),
    Refusal.INSUFFICIENT_CASH: (
        "INSUFFICIENT_PAPER_CASH: not enough cash left for a full $10 position."
    ),
}


@dataclass(frozen=True, slots=True)
class Observation:
    """What is known about one Radar token at the moment of evaluation.

    A projection, so this module never sees an ORM row. `price_usd is None` and
    `has_snapshot is False` are different states and both are kept: a token
    nobody has priced and a token whose latest reading carries no price are
    refused for different reasons, and lumping them would hide which.
    """

    mint_address: str
    rank: int
    has_snapshot: bool
    observed_at: datetime | None = None
    price_usd: Decimal | None = None
    liquidity_usd: Decimal | None = None
    market_cap: Decimal | None = None
    volume_24h: Decimal | None = None
    trading_status: str | None = None


@dataclass(frozen=True, slots=True)
class Verdict:
    """One token, judged. Exactly one of `candidate` / `refused_for` is set."""

    mint_address: str
    rank: int
    candidate: Candidate | None = None
    refused_for: str | None = None

    @property
    def eligible(self) -> bool:
        return self.candidate is not None


def judge(
    observation: Observation,
    *,
    held_ever: frozenset[str] | set[str],
    open_now: frozenset[str] | set[str],
    now: datetime | None = None,
    max_snapshot_age: timedelta | None = None,
) -> Verdict:
    """Apply §5's conditions to one token, in published order.

    Order matters only for the *reason* reported, never for the outcome: a
    token that fails three conditions is refused once, and the first condition
    it fails is the one named. Ownership is checked first because it is the
    cheapest and the most permanent — a token already traded will never become
    eligible again however its market moves.

    `now` and `max_snapshot_age` add the staleness condition. Both are
    parameters rather than a clock read here, because this module is pure and
    the replay's reproducibility depends on it staying that way. Passing
    neither leaves behaviour exactly as it was — which is what lets the replay
    and the benchmark keep judging historical observations without a
    wall-clock notion of "stale" leaking into them.
    """
    if observation.mint_address in open_now:
        return _refuse(observation, Refusal.ALREADY_HELD)
    if observation.mint_address in held_ever:
        return _refuse(observation, Refusal.ALREADY_TRADED)
    # A reading with no timestamp is not a reading: the exit walk is ordered by
    # observation time, so a price the platform cannot date cannot be replayed.
    if not observation.has_snapshot or observation.observed_at is None:
        return _refuse(observation, Refusal.NO_MARKET_DATA)
    if observation.price_usd is None or observation.price_usd <= 0:
        return _refuse(observation, Refusal.NO_PRICE)
    # Checked after the price exists and before anything about the venue: an
    # old price is still a price, so this is not `NO_PRICE`, and refusing it
    # for the venue's sake would name the wrong cause.
    if (
        now is not None
        and max_snapshot_age is not None
        and now - observation.observed_at > max_snapshot_age
    ):
        return _refuse(observation, Refusal.MARKET_DATA_STALE)
    status = observation.trading_status
    if status is not None and status != TRADEABLE_STATUS:
        return _refuse(observation, Refusal.NOT_TRADEABLE)
    if observation.liquidity_usd is None or observation.liquidity_usd <= 0:
        return _refuse(observation, Refusal.NO_LIQUIDITY)

    return Verdict(
        mint_address=observation.mint_address,
        rank=observation.rank,
        candidate=Candidate(
            mint_address=observation.mint_address,
            rank=observation.rank,
            price_usd=observation.price_usd,
            observed_at=observation.observed_at,
            liquidity_usd=observation.liquidity_usd,
            market_cap=observation.market_cap,
            volume_24h=observation.volume_24h,
        ),
    )


def _refuse(observation: Observation, reason: Refusal) -> Verdict:
    return Verdict(
        mint_address=observation.mint_address,
        rank=observation.rank,
        refused_for=reason.value,
    )


def screen(
    observations: Sequence[Observation],
    *,
    held_ever: frozenset[str] | set[str],
    open_now: frozenset[str] | set[str],
    now: datetime | None = None,
    max_snapshot_age: timedelta | None = None,
) -> list[Verdict]:
    """Judge a whole ranked page, keeping the ranking.

    The order in is the Radar's order, and the order out is the same. "The
    highest-ranked eligible token" is then just the first eligible verdict —
    the rule reads as one line because the ranking was never resorted.
    """
    return [
        judge(
            item,
            held_ever=held_ever,
            open_now=open_now,
            now=now,
            max_snapshot_age=max_snapshot_age,
        )
        for item in observations
    ]


def first_eligible(verdicts: Iterable[Verdict]) -> Verdict | None:
    for verdict in verdicts:
        if verdict.eligible:
            return verdict
    return None


def refusal_counts(verdicts: Iterable[Verdict]) -> dict[str, int]:
    """How many tokens each condition turned away.

    Published beside the empty state. "No qualified Radar token" is only worth
    reading next to how many were considered and what stopped them; without
    that, an empty wallet and a broken evaluator look identical.
    """
    counts: dict[str, int] = {}
    for verdict in verdicts:
        if verdict.refused_for is None:
            continue
        counts[verdict.refused_for] = counts.get(verdict.refused_for, 0) + 1
    return counts


class Idle(enum.StrEnum):
    """Why the wallet is holding cash rather than deploying it.

    Two genuinely different states, and conflating them is what made the wallet
    look broken on 2026-08-05: it sat on $92.38 with nine positions open and
    said nothing for an hour, because the only published idle message was about
    the Radar having nothing to offer — which was not the reason.
    """

    #: Cash enough for a position, and nothing on the Radar qualifies. §9.
    #: Named for the condition rather than the subject: "token" in a
    #: constant name trips the hardcoded-secret lint, and the domain sense
    #: of the word is not worth a suppression.
    NOTHING_QUALIFIES = "nothing_qualifies"
    #: Something qualifies, but what is left will not fund a whole position.
    #: The strategy declines rather than part-filling, so this is a wait for a
    #: **close**, not for an opportunity.
    CASH_BELOW_TRADE_SIZE = "cash_below_trade_size"


#: Published wherever the wallet reports that it is holding cash. Sprint 30 §9:
#: the wallet never buys a lower-quality token to avoid an empty screen.
WAITING_MESSAGE = "Waiting for the next qualified Radar opportunity."

#: The other reason, added after the wallet spent an hour idle with no
#: explanation on the page. The strategy declines rather than part-filling — a
#: wallet that quietly halved its size would report a return the published rule
#: did not produce — so leftover cash below one position is an ordinary state
#: that resolves when a position closes, and it has to say so.
CASH_SHORT_MESSAGE = (
    "Holding cash until a position closes. What is left is less than one "
    "position, and the strategy never part-fills."
)

IDLE_MESSAGES: dict[str, str] = {
    Idle.NOTHING_QUALIFIES: WAITING_MESSAGE,
    Idle.CASH_BELOW_TRADE_SIZE: CASH_SHORT_MESSAGE,
}
