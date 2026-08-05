"""What the same capital would have done in the Radar, over the same period.

Sprint 30 §2 and §13. The relaunched wallet starts with $1,000 at a recorded
instant, and **every benchmark starts with $1,000 at that same instant**. This
is the whole reason the module exists: the previous wallet compared itself
against `RadarRepository.benchmark`, which averages the return-since-detection
of every token the Radar has *ever* seen. That is a different period, a
different universe and a different starting capital, and comparing a wallet
launched today against it would credit or punish the strategy for months it
never traded.

Two comparisons are published, and they are genuinely two measurements:

* **Buy Every Radar Token** — the wallet's own cash constraint with no exit
  rule. $100 into each token as it becomes available, in the order it became
  available, until $1,000 is spent; then nothing, because nothing is ever sold.
  It isolates what the *exit rule* contributed, since the entries are the same
  shape as the wallet's.
* **Equal Weight Radar** — the index. $1,000 split evenly across every token
  that was on the Radar during the period, held to now. It isolates what the
  *entry ordering* contributed, since it takes everything and ranks nothing.

They coincide exactly when ten or fewer tokens qualify, and the API says so
rather than printing one number under two labels — Sprint 25 recorded that
duplication as a thing to refuse, and the answer is to make them different
measurements, not to hide one.

**Entry price is the price at the start of the period, not at detection.** A
token that entered the Radar weeks ago is bought by the benchmark at what it
cost when the wallet opened, because that is the only price the wallet could
have paid. Using the detection price would hand the benchmark a rise the wallet
was never present for.

**Nothing is excluded for being unpriced.** A token with no price at one end is
reported as unmeasurable and counted, not quietly dropped — dropping it would
make survivorship the benchmark's advantage.

Pure: no I/O, no clock, no randomness.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

_ZERO = Decimal(0)
_HUNDRED = Decimal(100)
_PCT = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class Constituent:
    """One token in the benchmark universe, priced at both ends.

    `available_at` is when the benchmark could first have bought it: the wallet's
    start for a token already on the Radar, its detection for one that arrived
    later. It decides the order the cash-constrained benchmark fills in.
    """

    mint_address: str
    available_at: datetime
    entry_price: Decimal | None
    current_price: Decimal | None

    @property
    def multiple(self) -> Decimal | None:
        if self.entry_price is None or self.entry_price <= 0:
            return None
        if self.current_price is None:
            return None
        return self.current_price / self.entry_price


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    """One comparison, measured or refused with a reason."""

    id: str
    label: str
    description: str
    return_pct: Decimal | None
    #: How many tokens the comparison actually held.
    positions: int
    #: How many were in the universe but could not be priced at both ends.
    unpriced: int
    unavailable_reason: str | None = None


def _mean_return_pct(multiples: Sequence[Decimal]) -> Decimal | None:
    """Equal-weight return over a set of multiples, as a percentage.

    Equal weight means the mean of the multiples: the same dollar amount into
    each, so each contributes its own multiple to the total in equal share.
    """
    if not multiples:
        return None
    total = sum(multiples, _ZERO) / Decimal(len(multiples))
    return ((total - 1) * _HUNDRED).quantize(_PCT)


def buy_every_radar_token(
    constituents: Sequence[Constituent],
    *,
    capital: Decimal,
    trade_size: Decimal,
) -> BenchmarkResult:
    """$100 into each token as it appeared, first come first served, never sold.

    Cash-constrained on purpose — it is the wallet's entry shape with the exit
    rule removed, which is the only way to read the difference between them as
    the exit rule's contribution.

    Fills in `available_at` order, tiebroken by mint so the same rows always
    produce the same portfolio. Ordering by return would be hindsight; ordering
    by whatever the database returned first would make the figure depend on a
    query plan.
    """
    slots = int(capital // trade_size) if trade_size > 0 else 0
    ordered = sorted(constituents, key=lambda item: (item.available_at, item.mint_address))

    taken: list[Constituent] = []
    for item in ordered:
        if len(taken) >= slots:
            break
        # A token the benchmark could not have priced could not have been
        # bought either, so it does not consume a slot. It is still counted
        # below — the universe is reported in full.
        if item.multiple is None:
            continue
        taken.append(item)

    multiples = [item.multiple for item in taken if item.multiple is not None]
    unpriced = sum(1 for item in ordered if item.multiple is None)

    return BenchmarkResult(
        id="buy_every_radar_token",
        label="Buy every Radar token",
        description=(
            f"${trade_size:,.0f} into each token as it reached the Radar, in the "
            f"order it arrived, until the ${capital:,.0f} was spent. Nothing is "
            "ever sold — the wallet's entry shape with no exit rule at all."
        ),
        return_pct=_mean_return_pct(multiples),
        positions=len(taken),
        unpriced=unpriced,
        unavailable_reason=(
            None
            if multiples
            else "No token in the period could be priced at both the start and now."
        ),
    )


def equal_weight_radar(
    constituents: Sequence[Constituent], *, capital: Decimal
) -> BenchmarkResult:
    """$1,000 split evenly across every token on the Radar in the period.

    Unconstrained by cash and indifferent to rank: it takes the whole universe.
    Where the cash-constrained benchmark measures the exit rule, this one
    measures whether ranking helped at all.
    """
    multiples = [item.multiple for item in constituents if item.multiple is not None]
    unpriced = sum(1 for item in constituents if item.multiple is None)

    return BenchmarkResult(
        id="equal_weight_radar",
        label="Equal weight Radar",
        description=(
            f"${capital:,.0f} split evenly across all {len(constituents)} tokens on "
            "the Radar during this period, held from the wallet's start to now. "
            "No ranking, no sizing, no exits."
        ),
        return_pct=_mean_return_pct(multiples),
        positions=len(multiples),
        unpriced=unpriced,
        unavailable_reason=(
            None
            if multiples
            else "No token in the period could be priced at both the start and now."
        ),
    )


#: Still unavailable, and still for the same reason. The platform records no SOL
#: price history, so the comparison would be fabricated rather than measured.
#: Sprint 30 §13 asked for the published reason to continue being shown instead.
HOLD_SOL_UNAVAILABLE = (
    "Not shown. The platform records no SOL price history of its own, so this "
    "comparison would be fabricated rather than measured. It stays unavailable "
    "until SOL is collected on the same footing as every other price here."
)

#: Printed above the table when both comparisons hold the same tokens. They are
#: distinct measurements that happen to coincide, and saying so is better than
#: either hiding one or letting a reader think two things were checked.
COINCIDENCE_NOTE = (
    "Both benchmarks currently hold the same tokens: fewer opportunities "
    "qualified during this period than the cash-constrained comparison could "
    "fund, so it bought all of them. The two figures separate as soon as more "
    "tokens qualify than $1,000 can hold."
)
