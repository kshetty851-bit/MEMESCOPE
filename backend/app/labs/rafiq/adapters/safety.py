"""`earlysignal.risk.safety_policy` — the safety stream's three states.

MEMESCOPE's `token_security_evaluations.overall_status` is already exactly
this shape (`PASSED` / `UNKNOWN` / `FAILED`), and its own roll-up rule is the
one that matters here: UNKNOWN dominates PASS, because a check that could not
be performed is not a check that passed.
"""

from __future__ import annotations

import enum


class SafetyVerdict(enum.StrEnum):
    """PASSED confirms. FAILED vetoes. UNKNOWN is ABSENT, never either."""

    PASSED = "PASSED"
    UNKNOWN = "UNKNOWN"
    FAILED = "FAILED"
