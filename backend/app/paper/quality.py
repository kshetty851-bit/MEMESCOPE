"""Whether a historical trade can be trusted for research.

V1.1 research. The audit that opened this phase found the trade table is not
uniformly usable: one position closed before it opened, seven carry no
liquidity depth at all, and roughly a third report a market cap that collapsed
below $5,000 while the price barely moved. Optimising a strategy over rows like
those fits the strategy to a data bug.

So this module answers one question per trade — **is this row usable, and if
not, why** — and answers it as data rather than by deleting the row.

## The rule that governs everything here

**Nothing is silently corrected and nothing is silently dropped.** A flagged
trade keeps its values; the flag travels beside it. Every caller that excludes
records must be able to say how many it excluded and for which reason, which is
why `summarise` exists and why `Assessment` carries every code it found rather
than only the worst one.

## Three statuses, and what each licenses

* `VALID` — no defect detected. Usable everywhere.
* `SUSPECT` — a specific field is unreliable, named by its reason code. Usable
  for experiments that do not read that field. A trade whose market cap is
  nonsense still has a perfectly good price path, and refusing it from a
  trailing-stop study would discard evidence for no reason.
* `INVALID` — the row cannot be reasoned about at all. Excluded from every
  optimisation metric.

The distinction matters because the market-cap defect is widespread. Treating
it as `INVALID` would throw away a third of an already small dataset over a
field most experiments never touch.

Pure: no I/O, no clock, no randomness. `now` is not needed and is not taken.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

#: Divergence between price return and market-cap return, in percentage points,
#: beyond which the market cap is not believable for a token whose supply is
#: effectively fixed. Generous on purpose: supply genuinely does change on some
#: tokens, and this is a screen for "these two numbers cannot both be right",
#: not a precision instrument.
MCAP_DIVERGENCE_PP = Decimal(25)

#: Divergence beyond which the disagreement is not a supply event under any
#: reading. Separated from the softer threshold so the two can be counted apart.
EXTREME_MCAP_DIVERGENCE_PP = Decimal(100)

#: A market cap at or below this, reached while the price held up, is the
#: signature the audit found: capitalisation collapsing to near nothing while
#: the token still trades within half its entry price.
IMPLAUSIBLE_MCAP_USD = Decimal(5_000)

#: Price retention above which an accompanying market-cap collapse is
#: contradictory rather than merely a bad token.
IMPLAUSIBLE_COLLAPSE_PRICE_RETURN_PCT = Decimal(-50)

#: Fewest observations inside the holding window that still describe a path.
#: Below this, excursion metrics and replay have nothing to walk.
MIN_PATH_OBSERVATIONS = 5


class Quality(enum.StrEnum):
    """How far a trade can be trusted.

    Ordered worst-last so `max` over a set of findings yields the governing
    status without a lookup table.
    """

    VALID = "valid"
    SUSPECT = "suspect"
    INVALID = "invalid"


#: Rank for escalation. `StrEnum` compares lexically, which would make
#: "invalid" < "suspect" < "valid" — the reverse of what severity means.
_SEVERITY: dict[Quality, int] = {
    Quality.VALID: 0,
    Quality.SUSPECT: 1,
    Quality.INVALID: 2,
}


class Reason(enum.StrEnum):
    """Machine-readable defect codes.

    Stable strings: they are counted, filtered on and displayed, so renaming one
    silently rewrites the meaning of a stored report.
    """

    #: The position closed before it opened. Nothing about it can be sequenced.
    EXIT_BEFORE_ENTRY = "exit_before_entry"
    #: No entry or no exit timestamp on a closed position.
    MISSING_TIMESTAMPS = "missing_timestamps"
    #: No depth was recorded, so no execution cost can be computed. The trade is
    #: real and its gross outcome stands; only net is unavailable.
    MISSING_ENTRY_LIQUIDITY = "missing_entry_liquidity"
    #: Price return and market-cap return disagree beyond the soft threshold.
    MCAP_PRICE_RETURN_DIVERGENCE = "mcap_price_return_divergence"
    #: The same disagreement, past the point any supply event explains it.
    EXTREME_MCAP_PRICE_DIVERGENCE = "extreme_mcap_price_divergence"
    #: Market cap collapsed to near zero while the price held up.
    IMPLAUSIBLE_MCAP_COLLAPSE = "implausible_mcap_collapse"
    #: Too few observations in the holding window to describe a path.
    INSUFFICIENT_PATH_DATA = "insufficient_path_data"
    #: No execution model version recorded, so the trade cannot be attributed to
    #: the legacy or the Jupiter regime.
    EXECUTION_MODEL_UNKNOWN = "execution_model_unknown"
    #: A closed position with no exit price.
    MISSING_EXIT_PRICE = "missing_exit_price"
    #: Entry price absent or non-positive; returns are undefined.
    NON_POSITIVE_ENTRY_PRICE = "non_positive_entry_price"


#: Which fields each reason makes untrustworthy. A caller asks "is this trade
#: usable for an experiment that reads liquidity?" rather than hard-coding a set
#: of reason codes at every call site.
TAINTS: dict[Reason, frozenset[str]] = {
    Reason.EXIT_BEFORE_ENTRY: frozenset({"timing", "duration", "path", "return"}),
    Reason.MISSING_TIMESTAMPS: frozenset({"timing", "duration", "path"}),
    Reason.MISSING_ENTRY_LIQUIDITY: frozenset({"liquidity", "cost", "net"}),
    Reason.MCAP_PRICE_RETURN_DIVERGENCE: frozenset({"market_cap"}),
    Reason.EXTREME_MCAP_PRICE_DIVERGENCE: frozenset({"market_cap"}),
    Reason.IMPLAUSIBLE_MCAP_COLLAPSE: frozenset({"market_cap"}),
    Reason.INSUFFICIENT_PATH_DATA: frozenset({"path", "excursion", "replay"}),
    Reason.EXECUTION_MODEL_UNKNOWN: frozenset({"execution_regime"}),
    Reason.MISSING_EXIT_PRICE: frozenset({"return", "net"}),
    Reason.NON_POSITIVE_ENTRY_PRICE: frozenset({"return", "net", "path"}),
}

#: Defects that make the row unusable outright rather than unusable in one
#: dimension. Deliberately short: only contradictions that break sequencing or
#: make every return undefined.
_FATAL: frozenset[Reason] = frozenset(
    {
        Reason.EXIT_BEFORE_ENTRY,
        Reason.MISSING_TIMESTAMPS,
        Reason.NON_POSITIVE_ENTRY_PRICE,
        Reason.MISSING_EXIT_PRICE,
    }
)


@dataclass(frozen=True, slots=True)
class TradeRecord:
    """The fields quality assessment reads, projected off the ORM row.

    A projection rather than the model for the reason the rest of this package
    projects: the assessment is a pure function of these values, and taking the
    ORM object would drag a session into a module that must not have one.
    """

    trade_id: str
    opened_at: datetime | None
    closed_at: datetime | None
    entry_price: Decimal | None
    exit_price: Decimal | None
    entry_market_cap: Decimal | None
    exit_market_cap: Decimal | None
    entry_liquidity_usd: Decimal | None
    execution_model_version: str | None
    #: Observations recorded inside the holding window.
    path_observations: int
    #: Whether the position is finished. Open positions are assessed on what
    #: exists so far rather than failed for lacking an exit.
    is_closed: bool = True


@dataclass(frozen=True, slots=True)
class Assessment:
    """What is wrong with one trade, if anything."""

    trade_id: str
    status: Quality
    reasons: tuple[Reason, ...]
    #: Divergence actually measured, when it could be measured at all. Carried
    #: so a report can show the magnitude rather than only the verdict.
    mcap_divergence_pp: Decimal | None = None

    def taints(self, field: str) -> bool:
        """Whether any finding makes `field` untrustworthy."""
        return any(field in TAINTS[reason] for reason in self.reasons)

    def usable_for(self, field: str) -> bool:
        """Whether this trade may be used by an experiment reading `field`.

        `INVALID` is unusable for everything. `SUSPECT` is unusable only for the
        dimensions its reasons actually taint — which is what keeps a
        market-cap defect from disqualifying a price-path study.
        """
        if self.status is Quality.INVALID:
            return False
        return not self.taints(field)


def _return_pct(start: Decimal | None, end: Decimal | None) -> Decimal | None:
    if start is None or end is None or start <= 0:
        return None
    return (end / start - Decimal(1)) * Decimal(100)


def assess(record: TradeRecord) -> Assessment:
    """Grade one trade.

    Collects every defect rather than returning at the first: a row can be both
    uncostable and have a broken market cap, and a caller filtering on liquidity
    needs to know about the first even though the second is louder.
    """
    reasons: list[Reason] = []

    # --- Sequencing ---------------------------------------------------------
    if record.opened_at is None or (record.is_closed and record.closed_at is None):
        reasons.append(Reason.MISSING_TIMESTAMPS)
    elif record.closed_at is not None and record.closed_at < record.opened_at:
        reasons.append(Reason.EXIT_BEFORE_ENTRY)

    # --- Returns ------------------------------------------------------------
    if record.entry_price is None or record.entry_price <= 0:
        reasons.append(Reason.NON_POSITIVE_ENTRY_PRICE)
    if record.is_closed and record.exit_price is None:
        reasons.append(Reason.MISSING_EXIT_PRICE)

    # --- Cost -------------------------------------------------------------—
    if record.entry_liquidity_usd is None or record.entry_liquidity_usd <= 0:
        reasons.append(Reason.MISSING_ENTRY_LIQUIDITY)

    # --- Market cap ---------------------------------------------------------
    #
    # The comparison only means anything when both returns exist. Supply is not
    # stored per snapshot, so this cannot separate "supply changed" from "the
    # market cap is wrong" — it reports that the two disagree and leaves the
    # cause to the root-cause diagnostic.
    price_ret = _return_pct(record.entry_price, record.exit_price)
    mcap_ret = _return_pct(record.entry_market_cap, record.exit_market_cap)
    divergence: Decimal | None = None
    if price_ret is not None and mcap_ret is not None:
        divergence = abs(price_ret - mcap_ret)
        if divergence > EXTREME_MCAP_DIVERGENCE_PP:
            reasons.append(Reason.EXTREME_MCAP_PRICE_DIVERGENCE)
        elif divergence > MCAP_DIVERGENCE_PP:
            reasons.append(Reason.MCAP_PRICE_RETURN_DIVERGENCE)

    if (
        record.exit_market_cap is not None
        and record.exit_market_cap <= IMPLAUSIBLE_MCAP_USD
        and price_ret is not None
        and price_ret > IMPLAUSIBLE_COLLAPSE_PRICE_RETURN_PCT
    ):
        reasons.append(Reason.IMPLAUSIBLE_MCAP_COLLAPSE)

    # --- Path ---------------------------------------------------------------
    if record.path_observations < MIN_PATH_OBSERVATIONS:
        reasons.append(Reason.INSUFFICIENT_PATH_DATA)

    # --- Execution regime ---------------------------------------------------
    if not record.execution_model_version:
        reasons.append(Reason.EXECUTION_MODEL_UNKNOWN)

    if not reasons:
        status = Quality.VALID
    elif any(reason in _FATAL for reason in reasons):
        status = Quality.INVALID
    else:
        status = Quality.SUSPECT

    return Assessment(
        trade_id=record.trade_id,
        status=status,
        reasons=tuple(reasons),
        mcap_divergence_pp=divergence,
    )


@dataclass(frozen=True, slots=True)
class QualitySummary:
    """Counts for a set of assessments.

    Exists so that "we excluded some rows" is never a sentence anyone has to
    take on trust. Every exclusion appears here with its reason and its count.
    """

    total: int
    valid: int
    suspect: int
    invalid: int
    by_reason: dict[str, int]

    @property
    def usable(self) -> int:
        """Rows not excluded outright. Suspect rows still count."""
        return self.valid + self.suspect


def summarise(assessments: list[Assessment]) -> QualitySummary:
    """Aggregate assessments into a reportable summary."""
    by_reason: dict[str, int] = {}
    for assessment in assessments:
        for reason in assessment.reasons:
            by_reason[reason.value] = by_reason.get(reason.value, 0) + 1

    return QualitySummary(
        total=len(assessments),
        valid=sum(1 for a in assessments if a.status is Quality.VALID),
        suspect=sum(1 for a in assessments if a.status is Quality.SUSPECT),
        invalid=sum(1 for a in assessments if a.status is Quality.INVALID),
        by_reason=by_reason,
    )


def worst(statuses: list[Quality]) -> Quality:
    """The governing status of a set. Empty means nothing was wrong."""
    if not statuses:
        return Quality.VALID
    return max(statuses, key=lambda status: _SEVERITY[status])
