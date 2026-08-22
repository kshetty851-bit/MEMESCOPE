"""The trading rules HQ is not allowed to change, and a way to prove it didn't.

§26 of the HQ brief names a list of things no autonomous action may modify:
strategy, position sizing, entry and exit policy, the security gate, the 6-hour
hold, Real Wallet permissions, wallet signing. This module turns that list from
a promise into a measurement.

── WHAT THIS IS AND IS NOT ──────────────────────────────────────────────

It is a fingerprint. `capture()` reads the live values of the protected
settings and strategy definitions and returns a hash plus the individual
values. `compare()` says whether two fingerprints differ and which field moved.

It is **not** a permission system. Nothing here prevents a write; the code that
could change these values is the deployment, not HQ. What it provides is the
guarantee the brief actually asks for — that if a protected value ever changes
across an autonomous action, the action fails, rolls back, and raises an
incident, rather than succeeding quietly.

── WHY IT READS SETTINGS RATHER THAN THE DATABASE ───────────────────────

Because that is where these rules live. Strategy definitions are frozen
dataclasses in `app.paper.strategy` and the thresholds are `Settings` fields;
both are fixed at process start by the image and the environment. A fingerprint
over the database would be measuring outcomes, not policy, and would change
every time a position opened.

The consequence worth stating plainly: this detects a *deployment* that changed
a protected rule. It cannot detect a change made and reverted between two
captures, and it says nothing about code paths that ignore these values. It is
a tripwire on the values themselves, which is what was asked for.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.core.config import settings


def _strategy_fingerprint() -> dict[str, Any]:
    """The operational strategies, reduced to the fields that decide trades."""
    from app.paper.strategy import SECURITY_GATED_STRATEGY_IDS, registry

    # Read defensively across strategy *types*, not defensively across bugs.
    # The registry holds several shapes — trailing-stop, bracket, fixed-size —
    # and they do not share every field. Asking each for the fields it has is
    # correct; a fingerprint that assumed one shape recorded the whole set as
    # unreadable the first time a bracket strategy was registered, which is a
    # guard that quietly stops guarding.
    out: dict[str, Any] = {}
    for strategy in registry.all():
        entry: dict[str, Any] = {
            "version": strategy.version,
            "operational": bool(strategy.operational),
        }
        for field in (
            "trade_size_usd",
            "trailing_drawdown",
            "take_profit",
            "stop_loss",
            "max_positions",
        ):
            value = getattr(strategy, field, None)
            if value is not None:
                entry[field] = str(value)
        hold_for = getattr(strategy, "hold_for", None)
        entry["hold_for_seconds"] = hold_for.total_seconds() if hold_for else None
        out[strategy.id] = entry
    out["_security_gated"] = sorted(SECURITY_GATED_STRATEGY_IDS)
    return out


#: Settings fields that are protected trading policy.
#:
#: Listed explicitly rather than pattern-matched on a prefix. A prefix rule
#: would silently stop covering a field somebody renames, and the failure mode
#: of this list is the one to prefer: a missing field is a gap somebody can see
#: in a diff, where a broken glob is invisible.
PROTECTED_SETTINGS: tuple[str, ...] = (
    # Real Wallet permissions and execution safety.
    "REAL_WALLET_AUTOTRADE_ENABLED",
    "REAL_WALLET_AUTOTRADE_COOLDOWN_SECONDS",
    "REAL_WALLET_SAFETY_POLICY_VERSION",
    "REAL_WALLET_SAFETY_MAX_MARKET_AGE_SECONDS",
    "REAL_WALLET_SAFETY_MAX_QUOTE_AGE_SECONDS",
    "REAL_WALLET_SAFETY_MAX_BUY_PRICE_IMPACT_PCT",
    "REAL_WALLET_SAFETY_MAX_SELL_PRICE_IMPACT_PCT",
    "REAL_WALLET_SAFETY_MAX_ROUND_TRIP_LOSS_PCT",
    "REAL_WALLET_SAFETY_MAX_POSITION_LIQUIDITY_RATIO",
    "REAL_WALLET_SAFETY_MAX_PRICE_DEVIATION_PCT",
    # The security entry gate.
    "TOKEN_SECURITY_EVALUATION_ENABLED",
    # Paper entry policy.
    "PAPER_ENTRY_MAX_SNAPSHOT_AGE_SECONDS",
)


def capture() -> dict[str, Any]:
    """Read every protected value and fingerprint it.

    Never raises. A fingerprint that can throw is a guard that disables itself
    exactly when something unusual is happening — instead, a field that cannot
    be read is recorded as unreadable, which makes the comparison fail closed
    because "unreadable" differs from whatever it was before.
    """
    values: dict[str, Any] = {}
    for name in PROTECTED_SETTINGS:
        try:
            values[name] = str(getattr(settings, name))
        except Exception as exc:
            values[name] = f"<unreadable: {exc}>"
    try:
        values["_strategies"] = _strategy_fingerprint()
    except Exception as exc:
        values["_strategies"] = f"<unreadable: {exc}>"

    blob = json.dumps(values, sort_keys=True, default=str)
    return {
        "digest": hashlib.sha256(blob.encode()).hexdigest(),
        "values": values,
    }


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Did any protected rule move between two captures?

    Returns the verdict and, when it changed, exactly which fields and from
    what to what — because "an invariant broke" is not an actionable sentence
    and "REAL_WALLET_AUTOTRADE_ENABLED went False → True" is.
    """
    if before.get("digest") == after.get("digest"):
        return {"held": True, "changed": {}}

    before_values = before.get("values", {}) or {}
    after_values = after.get("values", {}) or {}
    changed: dict[str, Any] = {}
    for key in sorted(set(before_values) | set(after_values)):
        old = before_values.get(key)
        new = after_values.get(key)
        if old != new:
            changed[key] = {"before": old, "after": new}
    return {"held": False, "changed": changed}
