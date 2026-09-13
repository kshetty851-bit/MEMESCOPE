"""The automated leakage checker (§15). Pure.

Fails a run rather than annotating it. A leaked feature does not make a result
slightly optimistic, it makes the result meaningless, and a warning at the
bottom of a report is something a reader skips.

## What this can and cannot see

It checks that every feature a decision used carries a `source_timestamp` at or
before its `decision_timestamp`, that no trade exits before it enters, and that
no position is carried through a migration.

It cannot see the two leaks that actually threaten this experiment, because
both act BEFORE a feature is computed:

* **Retention.** The 24-hour pruner deletes the curve series of non-graduates,
  so an archive older than a day is survivorship-shaped no matter how clean
  each surviving feature is.
* **Sampling.** The collector stops polling on eviction and on silence, both of
  which correlate with the token dying.

`quality.censoring_report` measures those. This module is deliberately narrow,
and says so, so that a green result here is not mistaken for a clean dataset.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.labs.v6_fast_accum.simulator import Trade


@dataclass(frozen=True, slots=True)
class LeakageFinding:
    mint: str
    strategy: str
    rule: str
    detail: str


def audit(trades: list[Trade]) -> tuple[bool, list[LeakageFinding]]:
    """`(passed, findings)`. Passed means no finding, not "no leakage"."""
    findings: list[LeakageFinding] = []
    for t in trades:
        for f in t.features:
            if f.derived_from_future_data:
                findings.append(LeakageFinding(
                    t.mint, t.strategy, "feature_after_decision",
                    f"{f.feature_name}: source {f.source_timestamp.isoformat()} "
                    f"> decision {f.decision_timestamp.isoformat()}"))
        if t.exit_ts is not None and t.exit_ts < t.entry_ts:
            findings.append(LeakageFinding(
                t.mint, t.strategy, "exit_before_entry",
                f"exit {t.exit_ts.isoformat()} < entry {t.entry_ts.isoformat()}"))
        if t.exit_reason == "graduation" and t.censored:
            findings.append(LeakageFinding(
                t.mint, t.strategy, "graduation_exit_censored",
                "a graduation exit cannot also be censored"))
        if t.elapsed_s < 0:
            findings.append(LeakageFinding(
                t.mint, t.strategy, "entry_before_first_seen",
                f"elapsed {t.elapsed_s}s is negative"))
    return (not findings), findings
