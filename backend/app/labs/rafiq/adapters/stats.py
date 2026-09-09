"""`earlysignal.validation.stats` — can this sample's mean be believed?

Three tests, because each one kills a different way of being wrong.

BOOTSTRAP CONFIDENCE INTERVAL
    Resample the observations with replacement, take the mean each time, and
    read the 2.5th and 97.5th percentiles. No normality assumption, which
    matters: memecoin returns are a fat right tail with a hard -100% floor and
    nothing about them is Gaussian.

BENJAMINI-HOCHBERG, ACROSS THE CONFIGURATIONS ACTUALLY SEARCHED
    Sweep six loss caps, report the best one, and you have found the best of
    six noise draws. The caller passes `configurations_searched`; the p-value
    must clear the corrected threshold, not the raw 0.05.

    **The rank problem, stated rather than hidden.** BH compares the k-th
    smallest p-value against `k/N * alpha`. This function sees ONE p-value and
    cannot know its rank, so it uses `k=1` — `alpha/N`, BH's strictest rung.
    That is conservative by construction: it never passes something the full
    procedure would reject, and it may reject something full BH would pass.
    Being wrong in the direction of "we did not prove it" is the only
    acceptable direction for this project.

OUTLIER DEPENDENCE
    Drop the best 1, 3 and 5 observations and recompute. A positive mean that
    is negative without its five best trades is a claim about five trades, not
    about a strategy — and this project has been fooled by exactly that shape
    before.

Deterministic: `seed` fixes the resampling, so a verdict is reproducible.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

ALPHA = 0.05
RESAMPLES = 2000
DROP_TOP = (1, 3, 5)


@dataclass(frozen=True, slots=True)
class Interval:
    low: float
    high: float


@dataclass(frozen=True, slots=True)
class Outliers:
    mean_all: float
    #: Mean after dropping the best k, for each k in DROP_TOP.
    mean_without_top: dict[int, float]
    #: True when every trimmed mean keeps the sign of the full mean.
    survives: bool


@dataclass(frozen=True, slots=True)
class Verdict:
    label: str
    n: int
    mean: float
    ci: Interval
    p_value: float
    #: The BH threshold this p-value had to clear. See the module docstring.
    p_threshold: float
    p_corrected_survives: bool
    outliers: Outliers
    #: Every gate passed AND the interval excludes zero. Nothing is "passed"
    #: on the strength of a point estimate alone.
    passed: bool
    reasons: tuple[str, ...] = field(default=())


def _mean(values) -> float:
    return sum(values) / len(values)


def assess(label: str, sample, *, configurations_searched: int = 1,
           seed: int = 0, alpha: float = ALPHA,
           resamples: int = RESAMPLES) -> Verdict:
    """Bootstrap CI + BH correction + outlier dependence, in one verdict."""
    values = [float(v) for v in sample]
    n = len(values)
    if n < 2:
        zero = Interval(float("nan"), float("nan"))
        return Verdict(label, n, float("nan"), zero, 1.0, alpha, False,
                       Outliers(float("nan"), {}, False), False,
                       ("sample too small to assess",))

    observed = _mean(values)
    rng = random.Random(seed)  # noqa: S311 — resampling, not cryptography
    means = sorted(_mean(rng.choices(values, k=n)) for _ in range(resamples))
    lo = means[int(0.025 * resamples)]
    hi = means[min(int(0.975 * resamples), resamples - 1)]

    # Two-sided bootstrap p: how often the resampled mean lands on the far
    # side of zero from the observed one. Never zero — with `resamples` draws
    # the smallest honestly reportable p is 1/resamples.
    tail = sum(1 for m in means if (m <= 0) == (observed > 0))
    p_value = min(1.0, max(1.0 / resamples, 2.0 * tail / resamples))
    threshold = alpha / max(1, configurations_searched)
    survives = p_value <= threshold

    ordered = sorted(values, reverse=True)
    trimmed = {
        k: (_mean(ordered[k:]) if n - k >= 2 else float("nan"))
        for k in DROP_TOP
    }
    same_sign = [
        (m > 0) == (observed > 0) for m in trimmed.values() if m == m  # NaN-safe
    ]
    outliers = Outliers(observed, trimmed, bool(same_sign) and all(same_sign))

    excludes_zero = (lo > 0) == (hi > 0)
    reasons: list[str] = []
    if not survives:
        reasons.append(
            f"p={p_value:.4f} does not clear {threshold:.4f} "
            f"({configurations_searched} configurations searched)")
    if not excludes_zero:
        reasons.append(f"95% CI [{lo:+.2f}, {hi:+.2f}] contains zero")
    if not outliers.survives:
        reasons.append("mean changes sign once its best trades are removed")

    return Verdict(label, n, observed, Interval(lo, hi), p_value, threshold,
                   survives, outliers,
                   survives and excludes_zero and outliers.survives,
                   tuple(reasons))
