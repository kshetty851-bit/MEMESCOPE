"""`earlysignal.evidence` — independent-stream consensus.

THE RULE A STREAM MUST OBEY
---------------------------
A stream is in exactly one of three states, and the third is the one that
matters:

  CONFIRMING  the feed supplied the evidence and it agrees
  DISSENTING  the feed supplied the evidence and it disagrees
  ABSENT      the feed could not supply the evidence at all

**Absent is never confirming.** MEMESCOPE has no social data source at all, and
its wallet-flow table is behind a flag that is off by default, so a naive
mapping would quietly turn "we cannot see this" into "this looks fine" for
half the streams Strategy E asks about. `from_feed` below can only ever
construct a verdict from a value that is actually present; everything else is
omitted, and an omitted stream cannot count toward `min_confirming_streams`.

Staleness is the same problem in the time dimension: a confirming reading from
two hours ago is evidence about two hours ago. `max_age` demotes it to absent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.labs.rafiq.adapters.safety import SafetyVerdict

#: The four streams Strategy E names. `social` is declared here and never
#: produced by `from_feed`, because the platform has no social data — see the
#: README's gap list. Declaring it keeps the absence visible instead of
#: making the requirement quietly disappear.
STREAMS = ("onchain", "dex", "social", "safety")


@dataclass(frozen=True, slots=True)
class StreamVerdict:
    """One stream's reading. Only constructed when evidence actually exists."""

    stream: str
    confirming: bool
    observed_at: datetime
    detail: str = ""

    def is_fresh(self, *, now: datetime, max_age: timedelta) -> bool:
        return now - self.observed_at <= max_age


@dataclass(frozen=True, slots=True)
class ConsensusPolicy:
    min_confirming_streams: int = 2
    #: Safety must be one of the confirming streams, not merely one of many.
    require_safety: bool = True
    #: Older than this and a verdict is evidence about the past, so it is
    #: treated as absent rather than as agreement.
    max_age: timedelta = timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class Consensus:
    agreed: bool
    reasons: tuple[str, ...]
    confirming: tuple[str, ...]
    dissenting: tuple[str, ...]
    absent: tuple[str, ...]


def consensus(streams, *, now: datetime, policy: ConsensusPolicy) -> Consensus:
    """Do enough independent streams agree, with safety among them?

    `streams` is any iterable of `StreamVerdict`. A stream that appears twice
    is counted once — the freshest reading wins — so a caller cannot
    manufacture breadth by supplying the same evidence under two names.
    """
    freshest: dict[str, StreamVerdict] = {}
    for verdict in streams:
        if not verdict.is_fresh(now=now, max_age=policy.max_age):
            continue
        held = freshest.get(verdict.stream)
        if held is None or verdict.observed_at > held.observed_at:
            freshest[verdict.stream] = verdict

    confirming = tuple(sorted(k for k, v in freshest.items() if v.confirming))
    dissenting = tuple(sorted(k for k, v in freshest.items() if not v.confirming))
    absent = tuple(sorted(set(STREAMS) - set(freshest)))

    reasons: list[str] = []
    if len(confirming) < policy.min_confirming_streams:
        reasons.append(
            f"only {len(confirming)} of {policy.min_confirming_streams} required "
            f"streams confirm (absent: {', '.join(absent) or 'none'})"
        )
    if policy.require_safety and "safety" not in confirming:
        reasons.append(
            "safety stream did not confirm — "
            + ("absent" if "safety" in absent else "dissenting")
        )
    for name in dissenting:
        reasons.append(f"{name} dissents: {freshest[name].detail or 'no detail'}")

    agreed = (
        len(confirming) >= policy.min_confirming_streams
        and (not policy.require_safety or "safety" in confirming)
    )
    return Consensus(agreed, tuple(reasons), confirming, dissenting, absent)


def from_feed(observation, *, safety: SafetyVerdict | None,
              safety_observed_at: datetime | None) -> tuple[StreamVerdict, ...]:
    """Map a MEMESCOPE observation onto stream verdicts.

    Builds a verdict ONLY from a value the feed actually supplied. There is no
    `else` branch producing a default: an unreadable stream is left out, and
    `consensus` then reports it as absent.

    * `onchain` — wallet flow. Confirms when unique buyers outnumber unique
      sellers over the hour AND the top-10 wallets are not most of the trades.
      Absent whenever the wallet-flow snapshot is missing (its collector is
      behind a flag that ships off).
    * `dex`     — market data. Confirms when the pool is liquid enough to
      price and 15-minute liquidity is not draining.
    * `social`  — never produced. The platform stores no social data.
    * `safety`  — the security evaluation. UNKNOWN produces nothing.
    """
    out: list[StreamVerdict] = []
    at = observation.observed_at

    buyers, sellers = observation.buyers, observation.sellers
    top10 = observation.top10_tx_share
    if buyers is not None and sellers is not None:
        ok = buyers > sellers and (top10 is None or top10 <= Decimal("0.60"))
        out.append(StreamVerdict(
            "onchain", ok, at,
            f"{buyers} buyers vs {sellers} sellers"
            + (f", top-10 hold {top10:.0%} of trades" if top10 is not None else ""),
        ))

    liq, liqchg = observation.liquidity_usd, observation.liquidity_change_15m
    if liq is not None:
        ok = liq > 0 and (liqchg is None or liqchg > Decimal("-0.20"))
        out.append(StreamVerdict(
            "dex", ok, at,
            f"liquidity ${liq:,.0f}"
            + (f", {liqchg:+.1%} over 15m" if liqchg is not None else ""),
        ))

    if safety is not None and safety is not SafetyVerdict.UNKNOWN:
        out.append(StreamVerdict(
            "safety", safety is SafetyVerdict.PASSED,
            safety_observed_at or at, f"security evaluation {safety}",
        ))

    return tuple(out)
