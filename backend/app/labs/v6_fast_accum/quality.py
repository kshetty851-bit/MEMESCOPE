"""The data-quality report (§16), and the censoring measurement that matters.

Nothing is silently discarded. Every excluded token carries an explicit reason
and is counted in the report, so "how much of the universe did this experiment
actually see" has an answer rather than an inference.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal

from app.labs.v6_fast_accum.dataset import Dataset
from app.labs.v6_fast_accum.simulator import Trade


@dataclass
class QualityReport:
    tokens_total: int = 0
    tokens_pruned: int = 0
    tokens_no_samples: int = 0
    duplicate_mints: int = 0
    out_of_order_samples: int = 0
    impossible_progress: int = 0
    negative_reserves: int = 0
    impossible_price: int = 0
    exclusions: Counter = field(default_factory=Counter)
    censoring: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "tokens_total": self.tokens_total,
            "tokens_pruned": self.tokens_pruned,
            "tokens_no_samples": self.tokens_no_samples,
            "duplicate_mints": self.duplicate_mints,
            "out_of_order_samples": self.out_of_order_samples,
            "impossible_progress": self.impossible_progress,
            "negative_reserves": self.negative_reserves,
            "impossible_price": self.impossible_price,
            "exclusions": dict(self.exclusions),
            "censoring": self.censoring,
        }


def inspect(ds: Dataset) -> QualityReport:
    r = QualityReport(tokens_total=len(ds.tokens))
    seen: set[str] = set()
    for t in ds.tokens:
        if t.mint in seen:
            r.duplicate_mints += 1
        seen.add(t.mint)
        if t.pruned:
            r.tokens_pruned += 1
            r.exclusions["pruned_series_deleted"] += 1
            continue
        if not t.samples:
            r.tokens_no_samples += 1
            r.exclusions["no_curve_samples"] += 1
            continue
        prev = None
        for s in t.samples:
            if prev is not None and s.ts < prev:
                r.out_of_order_samples += 1
            prev = s.ts
            if s.progress_pct is not None and not (0 <= s.progress_pct <= 100):
                r.impossible_progress += 1
            if (s.v_quote is not None and s.v_quote < 0) or \
               (s.v_token is not None and s.v_token < 0):
                r.negative_reserves += 1
            if s.price is not None and s.price <= 0:
                r.impossible_price += 1
    return r


def censoring_report(ds: Dataset, trades: list[Trade]) -> dict:
    """Is the censoring correlated with the outcome?

    This is the measurement the whole experiment turns on. The collector stops
    polling for reasons — eviction takes the LEAST-PROGRESSED token when the
    watch set fills, silence takes one whose reserves stopped moving — and both
    describe a token that is dying. If the censored trades are drawn
    disproportionately from those reasons, then the resolved sample has had its
    losers removed and every profit figure computed on it is biased UPWARD.

    Reported as a share, per reason, censored versus resolved. A flat profile
    across reasons would mean censoring is roughly random and the resolved
    sample can be read at face value. A profile tilted toward `evicted` and
    `silent` means it cannot.
    """
    by_mint = ds.by_mint()
    cens: Counter = Counter()
    res: Counter = Counter()
    for t in trades:
        tok = by_mint.get(t.mint)
        reason = (tok.unsubscribe_reason if tok else None) or "(still watching)"
        (cens if t.censored else res)[reason] += 1
    total_c, total_r = sum(cens.values()), sum(res.values())
    reasons = sorted(set(cens) | set(res))
    return {
        "censored_total": total_c,
        "resolved_total": total_r,
        "censored_share": (float(total_c) / (total_c + total_r)) if (total_c + total_r) else 0.0,
        "by_reason": [
            {
                "reason": k,
                "censored": cens.get(k, 0),
                "resolved": res.get(k, 0),
                "censored_pct_of_censored": (100.0 * cens.get(k, 0) / total_c) if total_c else 0.0,
                "resolved_pct_of_resolved": (100.0 * res.get(k, 0) / total_r) if total_r else 0.0,
            }
            for k in reasons
        ],
    }
