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
from datetime import datetime
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
    #: Everything passed, but the cash left is below one position.
    INSUFFICIENT_CASH = "insufficient_paper_cash"
    #: The strategy's own entry rules declined a candidate that passed every
    #: eligibility condition — its liquidity floor, its flow ceiling, whatever
    #: it publishes. Distinct from INSUFFICIENT_CASH because the two say
    #: opposite things about the wallet: one is idle capital with qualified
    #: tokens in front of it, the other is the strategy working as designed.
    STRATEGY_DECLINED = "strategy_declined"
    #: Entries are administratively paused (V4 containment). Not a judgement
    #: about any token — the whole pass was refused before ranking.
    ENTRIES_PAUSED = "entries_paused"


#: The sentence each refusal renders as. Server-side, from a stable code — the
#: platform's rule for all prose, so a rewording is a deploy and not a migration.
REFUSAL_LABELS: dict[str, str] = {
    Refusal.ALREADY_TRADED: "Already traded by this wallet. One position per token, ever.",
    Refusal.ALREADY_HELD: "Already held.",
    Refusal.NO_MARKET_DATA: "No market data has been collected for this token.",
    Refusal.NO_PRICE: "No usable price in the latest reading.",
    Refusal.NO_LIQUIDITY: (
        "The venue reports no pool depth, so the trade could not be costed or audited."
    ),
    Refusal.NOT_TRADEABLE: "The market provider does not report this token as trading.",
    Refusal.INSUFFICIENT_CASH: (
        "INSUFFICIENT_PAPER_CASH: not enough cash left for a full $10 position."
    ),
    Refusal.STRATEGY_DECLINED: (
        "STRATEGY_DECLINED: the token qualified and the wallet could afford it, "
        "but the strategy's own entry rules refused it — its liquidity floor or "
        "its flow ceiling. This is the strategy working, not capital sitting idle."
    ),
    Refusal.ENTRIES_PAUSED: (
        "Entries are paused: no validated edge on the current admission stream. "
        "Open positions are still reviewed and exits still settle."
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
    #: Sell fraction of trades over the last ~15 minutes. `None` is UNMEASURED.
    sell_share_15m: Decimal | None = None


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
) -> Verdict:
    """Apply §5's conditions to one token, in published order.

    Order matters only for the *reason* reported, never for the outcome: a
    token that fails three conditions is refused once, and the first condition
    it fails is the one named. Ownership is checked first because it is the
    cheapest and the most permanent — a token already traded will never become
    eligible again however its market moves.
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
            sell_share_15m=observation.sell_share_15m,
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
) -> list[Verdict]:
    """Judge a whole ranked page, keeping the ranking.

    The order in is the Radar's order, and the order out is the same. "The
    highest-ranked eligible token" is then just the first eligible verdict —
    the rule reads as one line because the ranking was never resorted.
    """
    return [judge(item, held_ever=held_ever, open_now=open_now) for item in observations]


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
