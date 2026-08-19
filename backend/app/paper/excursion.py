"""How far a trade went the right way, and the wrong way, before it closed.

V1.1 research. The V1.0 record says where each position exited; it does not say
what was available to exit into. Without that, every exit-rule experiment is
guesswork — "a tighter trail would have kept more" is a claim about the path,
and the path is exactly what was never measured.

Maximum favourable and adverse excursion answer it:

* **MFE** — the best unrealised return reached while the position was open.
* **MAE** — the worst.
* **Exit capture** — how much of the MFE the exit actually took.

A strategy with a good MFE and poor capture is losing money to its exit rule. A
strategy with poor MFE is losing it to its entry rule. The two failures need
opposite fixes, which is why they have to be told apart before anything is
tuned.

## The fidelity limit, stated once and carried on every result

`token_market_snapshots` stores **one price per observation and no OHLC**. So an
excursion is the extreme of the *observed* series, never the true intra-period
extreme. Between two snapshots the price may have gone anywhere, and nothing
here pretends otherwise:

* no interpolation between observations,
* no synthesised high or low,
* no assumed touch of a level that no snapshot recorded.

Every result carries `FIDELITY_NOTE`, and callers are expected to display it.
The consequence is directional and must be repeated wherever it matters: real
MFE is **at least** what is reported and real MAE is **at most** it, so any rule
tuned against these numbers is tuned against a conservative shadow of the path.

Pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.paper.models import Quote

#: Stamped on every computed excursion. Not a footnote — the number is only
#: interpretable beside it.
FIDELITY_NOTE = "SNAPSHOT_RESOLUTION_ONLY"

#: Fewest observations that describe an excursion at all. One point is a
#: reading, not a path: its MFE and MAE would both be that single point and the
#: pair would look like a flat trade rather than an unmeasured one.
MIN_OBSERVATIONS = 2


class Availability(enum.StrEnum):
    """Whether the metrics could be computed, and if not, why."""

    #: Computed from a usable series.
    AVAILABLE = "available"
    #: Fewer than `MIN_OBSERVATIONS` inside the window.
    INSUFFICIENT_OBSERVATIONS = "insufficient_observations"
    #: No entry price, or a non-positive one. Returns are undefined.
    NO_ENTRY_PRICE = "no_entry_price"
    #: No observations at all fell inside the holding window.
    NO_PATH = "no_path"


@dataclass(frozen=True, slots=True)
class Excursion:
    """The path of one position, reduced to its extremes.

    Percentages are returns against the entry price, so `mfe_pct` of 40 means
    the position was up 40% at its best observed moment. `None` throughout when
    `availability` is anything but `AVAILABLE` — an unmeasured excursion is
    never reported as zero, because zero is a real and different outcome.
    """

    availability: Availability
    observations: int
    fidelity: str = FIDELITY_NOTE

    mfe_pct: Decimal | None = None
    mae_pct: Decimal | None = None
    price_at_mfe: Decimal | None = None
    price_at_mae: Decimal | None = None
    time_to_mfe: datetime | None = None
    time_to_mae: datetime | None = None
    #: Seconds from entry to each extreme. Derived here rather than by callers
    #: so "how long until it peaked" is one definition everywhere.
    seconds_to_mfe: int | None = None
    seconds_to_mae: int | None = None

    realized_exit_return_pct: Decimal | None = None
    #: Realised return divided by MFE. Only defined when the position actually
    #: went favourable — see `_capture` for why the guard is strict.
    exit_capture_ratio: Decimal | None = None

    @property
    def available(self) -> bool:
        return self.availability is Availability.AVAILABLE


def _pct(entry: Decimal, price: Decimal) -> Decimal:
    return (price / entry - Decimal(1)) * Decimal(100)


def _capture(realized_pct: Decimal | None, mfe_pct: Decimal | None) -> Decimal | None:
    """Fraction of the favourable excursion the exit realised.

    Defined only when the trade actually offered something to capture. Three
    refusals, each for a reason a ratio would misreport:

    * **MFE at or below zero** — the position was never up. Dividing a loss by a
      non-positive best gives a number whose sign says nothing about the exit.
    * **No realised return** — the position is open, or its exit is unrecorded.

    A negative capture is legal and meaningful: the position was up, and the
    exit still booked a loss.
    """
    if realized_pct is None or mfe_pct is None:
        return None
    if mfe_pct <= 0:
        return None
    return realized_pct / mfe_pct


def compute(
    *,
    entry_price: Decimal | None,
    opened_at: datetime,
    quotes: list[Quote],
    exit_price: Decimal | None = None,
) -> Excursion:
    """Excursion metrics for one position from its observed path.

    `quotes` must already be restricted to the holding window and sorted
    chronologically; this walks them once in the order given and does not sort,
    because a caller that supplied them out of order has a bug the metric should
    not paper over.

    The entry price itself is **not** treated as an observation. MFE and MAE
    describe what happened *after* the position opened; seeding the series with
    the entry would floor MAE at zero and make every trade look as though it was
    never underwater at the moment it opened.
    """
    if entry_price is None or entry_price <= 0:
        return Excursion(availability=Availability.NO_ENTRY_PRICE, observations=len(quotes))
    if not quotes:
        return Excursion(availability=Availability.NO_PATH, observations=0)
    if len(quotes) < MIN_OBSERVATIONS:
        return Excursion(
            availability=Availability.INSUFFICIENT_OBSERVATIONS,
            observations=len(quotes),
        )

    best = quotes[0]
    worst = quotes[0]
    for quote in quotes[1:]:
        # Strict comparisons keep the *earliest* extreme when a level is matched
        # again later. "When did it first reach its best" is the question a
        # timing metric is asked; a later tie is the same price, not new news.
        if quote.price_usd > best.price_usd:
            best = quote
        if quote.price_usd < worst.price_usd:
            worst = quote

    realized = None if exit_price is None else _pct(entry_price, exit_price)
    mfe = _pct(entry_price, best.price_usd)
    mae = _pct(entry_price, worst.price_usd)

    return Excursion(
        availability=Availability.AVAILABLE,
        observations=len(quotes),
        mfe_pct=mfe,
        mae_pct=mae,
        price_at_mfe=best.price_usd,
        price_at_mae=worst.price_usd,
        time_to_mfe=best.captured_at,
        time_to_mae=worst.captured_at,
        seconds_to_mfe=int((best.captured_at - opened_at).total_seconds()),
        seconds_to_mae=int((worst.captured_at - opened_at).total_seconds()),
        realized_exit_return_pct=realized,
        exit_capture_ratio=_capture(realized, mfe),
    )


@dataclass(frozen=True, slots=True)
class ExcursionSummary:
    """Aggregate excursion behaviour across a set of trades.

    Medians rather than means for the excursions themselves: on this dataset a
    single token that ran several hundred percent drags a mean far away from
    anything typical, and the question these answer is "what does a trade here
    usually offer", not "what did the best one offer".
    """

    trades: int
    available: int
    unavailable: int
    median_mfe_pct: Decimal | None
    median_mae_pct: Decimal | None
    median_capture: Decimal | None
    #: Positions whose best observed level never exceeded the entry. These can
    #: never be improved by an exit rule — only by not entering.
    never_favourable: int
    #: Positions that were up by at least this much at some point and still
    #: closed at a loss. The clearest measure of exit-rule damage.
    gave_back_winners: int
    gave_back_threshold_pct: Decimal


def _median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def summarise(
    excursions: list[Excursion], *, gave_back_threshold_pct: Decimal = Decimal(20)
) -> ExcursionSummary:
    """Aggregate a set of excursions for reporting."""
    usable = [e for e in excursions if e.available]

    return ExcursionSummary(
        trades=len(excursions),
        available=len(usable),
        unavailable=len(excursions) - len(usable),
        median_mfe_pct=_median([e.mfe_pct for e in usable if e.mfe_pct is not None]),
        median_mae_pct=_median([e.mae_pct for e in usable if e.mae_pct is not None]),
        median_capture=_median(
            [e.exit_capture_ratio for e in usable if e.exit_capture_ratio is not None]
        ),
        never_favourable=sum(1 for e in usable if e.mfe_pct is not None and e.mfe_pct <= 0),
        gave_back_winners=sum(
            1
            for e in usable
            if e.mfe_pct is not None
            and e.mfe_pct >= gave_back_threshold_pct
            and e.realized_exit_return_pct is not None
            and e.realized_exit_return_pct <= 0
        ),
        gave_back_threshold_pct=gave_back_threshold_pct,
    )
