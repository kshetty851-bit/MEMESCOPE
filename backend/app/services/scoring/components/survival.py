"""Survival age - Scout. "Has it lived long enough to mean anything?"

The only deliberately non-monotone curve in the model, and the only component
that is always available - age is always known.

Both ends are bad for different reasons. A token four minutes old is not
promising, it is *unknown*: almost nothing has happened yet, and the vast
majority of launches are dead within the hour. A token ten days old is a
different kind of uninteresting - whatever move it had, it has had.

The peak sits between two hours and a day: long enough that survival is
evidence, early enough that the opportunity is not already spent.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.scoring.components.base import (
    ComponentId,
    ComponentResult,
    ScoreComponent,
)
from app.services.scoring.explain import AgentId, ReasonCode
from app.services.scoring.features import FeatureSet
from app.services.scoring.normalisers import anchors, interpolate

# Age in minutes.
SURVIVAL = anchors(
    ("0", "15"),
    ("5", "25"),
    ("30", "55"),
    ("120", "85"),
    ("1440", "85"),
    ("4320", "60"),
    ("10080", "40"),
)

TOO_NEW_MINUTES = Decimal(30)
ESTABLISHED_MINUTES = Decimal(120)
STALE_MINUTES = Decimal(10080)


class SurvivalAge(ScoreComponent):
    id = ComponentId.SURVIVAL_AGE
    agent = AgentId.SCOUT

    def evaluate(self, features: FeatureSet) -> ComponentResult:
        age = features.age_minutes
        score = interpolate(age, SURVIVAL)

        if age < TOO_NEW_MINUTES:
            reason = ReasonCode.TOKEN_TOO_NEW
        elif age >= STALE_MINUTES:
            reason = ReasonCode.TOKEN_STALE
        elif age >= ESTABLISHED_MINUTES:
            reason = ReasonCode.SURVIVAL_ESTABLISHED
        else:
            reason = ReasonCode.TOKEN_TOO_NEW

        return ComponentResult(
            id=self.id,
            agent=self.agent,
            available=True,
            score=score,
            raw={"age_minutes": age},
            reasons=(reason,),
        )
