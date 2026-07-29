"""Clone-risk API contracts.

`explanation` is rendered server-side and shipped as a finished sentence, the
same convention `ScoreReason.message` and the Radar's reasons follow. A client
that composed this string would own a verdict the platform did not issue, and
the two could then disagree about the same token.
"""

from __future__ import annotations

from typing import Literal

from app.schemas.common import BaseSchema


class IdentityOut(BaseSchema):
    """Whether a token's name is contested, and where it sits in the queue."""

    mint_address: str

    #: Tokens sharing this exact name, counting this one. 1 means unique.
    sharing_name: int
    #: How many of those MEMESCOPE discovered before this token.
    discovered_before: int
    #: Earliest *observed*, which is not the same as earliest in existence —
    #: the scanner cannot see launches that predate it.
    is_earliest_known: bool

    clone_risk: Literal["none", "low", "moderate", "high"]
    identity_confidence: Literal["high", "moderate", "low"]

    #: A finished sentence. Display it; do not parse it.
    explanation: str


class IdentityPage(BaseSchema):
    items: list[IdentityOut]
