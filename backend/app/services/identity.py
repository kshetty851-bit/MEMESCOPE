"""Clone risk — is this token trading on someone else's name?

Memecoin launchpads make a name free to reuse, and reuse is the norm rather
than the exception: measured on the live database, **16,188 of ~23,300 named
tokens (69%) share a name with at least one other token**, across 333 clusters
of ten or more. The largest cluster is 149 tokens called *Puffins*.

A user searching for a project they heard about is therefore choosing from a
list of near-identical candidates, most of which are impersonations. That is a
direct, avoidable way to lose money, and — unlike holder counts or wallet
history — the platform already holds every field needed to warn about it.

Pure, in the same discipline as `services/scoring` and `app/radar`: no I/O, no
clock, no randomness. The caller supplies the counts; this module decides what
they mean and renders the sentence.

**What this cannot tell you.** MEMESCOPE only sees tokens its own scanner
discovered. "Earliest known" means earliest *observed*, not earliest in
existence — a genuine original that predates the scanner would look like a
clone. The wording below says "known to MEMESCOPE" for that reason, and
`identity_confidence` is never reported as certain.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class CloneRisk(enum.StrEnum):
    """How likely this token is trading on a name it did not establish."""

    NONE = "none"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class IdentityConfidence(enum.StrEnum):
    """How sure we can be that the name identifies *this* project."""

    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"


#: A name shared this widely is contested rather than coincidental. Two tokens
#: called "Moon" is a collision; ten is a pattern of deliberate reuse.
CONTESTED_CLUSTER = 10


@dataclass(frozen=True, slots=True)
class IdentityAssessment:
    """What the platform can say about a token's claim to its own name."""

    #: Tokens sharing this exact name, including this one. 1 means unique.
    sharing_name: int
    #: How many of those MEMESCOPE discovered before this one.
    discovered_before: int
    clone_risk: CloneRisk
    identity_confidence: IdentityConfidence
    #: Rendered here, never composed on the client — the same rule the scoring
    #: engine and the Radar follow for their own reasons.
    explanation: str

    @property
    def is_earliest_known(self) -> bool:
        return self.discovered_before == 0


def assess(*, sharing_name: int, discovered_before: int) -> IdentityAssessment:
    """Band a name collision. Pure.

    `sharing_name` counts this token, so 1 means the name is unique in
    everything MEMESCOPE has seen.
    """
    if sharing_name < 1:
        raise ValueError("sharing_name counts this token, so it is at least 1")
    if discovered_before < 0:
        raise ValueError("discovered_before cannot be negative")
    if discovered_before >= sharing_name:
        raise ValueError("discovered_before must be less than sharing_name")

    others = sharing_name - 1

    if others == 0:
        return IdentityAssessment(
            sharing_name=sharing_name,
            discovered_before=discovered_before,
            clone_risk=CloneRisk.NONE,
            identity_confidence=IdentityConfidence.HIGH,
            explanation="No other token known to MEMESCOPE uses this name.",
        )

    if discovered_before == 0:
        # First to the name, among what we saw. Being copied is not the same as
        # copying, so the risk is on the *other* tokens, not this one — but the
        # name is still ambiguous to anyone searching for it.
        return IdentityAssessment(
            sharing_name=sharing_name,
            discovered_before=discovered_before,
            clone_risk=CloneRisk.LOW,
            identity_confidence=IdentityConfidence.MODERATE,
            explanation=(
                f"This is the earliest token known to MEMESCOPE using this name, "
                f"and {others} later {_tokens(others)} reuse it. It may be the "
                f"project the others are imitating, though MEMESCOPE cannot see "
                f"tokens launched before it started scanning."
            ),
        )

    if sharing_name >= CONTESTED_CLUSTER:
        return IdentityAssessment(
            sharing_name=sharing_name,
            discovered_before=discovered_before,
            clone_risk=CloneRisk.HIGH,
            identity_confidence=IdentityConfidence.LOW,
            explanation=(
                f"{sharing_name} tokens share this name and {discovered_before} of "
                f"them were discovered first. A name reused this many times is "
                f"usually deliberate, and this token is not the original."
            ),
        )

    return IdentityAssessment(
        sharing_name=sharing_name,
        discovered_before=discovered_before,
        clone_risk=CloneRisk.MODERATE,
        identity_confidence=IdentityConfidence.LOW,
        explanation=(
            f"{discovered_before} earlier {_tokens(discovered_before)} already "
            f"used this name before this one appeared."
        ),
    )


def unnamed() -> IdentityAssessment:
    """The assessment for a token with no name.

    Reported rather than omitted: "we checked and there is no name to compare"
    and "we did not check" are different facts, and only the first is true here.
    """
    return IdentityAssessment(
        sharing_name=1,
        discovered_before=0,
        clone_risk=CloneRisk.NONE,
        identity_confidence=IdentityConfidence.LOW,
        explanation=(
            "This token has no name recorded, so it cannot be compared against others by name."
        ),
    )


def _tokens(count: int) -> str:
    return "token" if count == 1 else "tokens"
