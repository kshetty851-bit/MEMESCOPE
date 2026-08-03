"""The signal provider contract.

One interface, so the engine can combine providers without knowing what any of
them measures, and a new one can be added without touching the engine
(ARCHITECTURE_DECISIONS.md AD-04). This generalises `analysts/base.py`, which
proved the shape across six specialists.

## The contract

A provider is a **pure function from an observation window to zero or more
signal candidates**. It receives an `ObservationWindow` and an explicit `now`,
and returns a `ProviderResult`. No database, no network, no clock, no
randomness.

Purity is not stylistic. It is what makes a signal replayable over stored
history, which is how thresholds get tuned rather than guessed, and it is why
the scoring engine and the analyst ensemble are testable without fixtures.

## What a provider may not do

- No I/O of any kind.
- No recommendation. A candidate describes an observed transition; it never
  says buy, sell, hold, or "consider".
- No estimation. A provider that lacks its inputs returns
  `ProviderResult.unavailable` with a reason. Reported, never omitted — the
  same contract `/smart-money/{mint}` already honours in production.
- No knowledge of opportunities. Merging candidates into opportunities,
  deduplication and lifecycle all belong to the engine. A provider that reached
  into them would have to be rewritten every time the lifecycle changed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.opportunities.models import ObservationWindow, ProviderMeta, ProviderResult


class SignalProvider(ABC):
    """One source of signal candidates.

    Instances are stateless and shared across evaluations, so an implementation
    must not accumulate anything between calls.
    """

    @property
    @abstractmethod
    def meta(self) -> ProviderMeta:
        """What this provider is. Published, so its role is checkable."""

    @abstractmethod
    def evaluate(self, window: ObservationWindow, *, now: datetime) -> ProviderResult:
        """Zero or more candidates from one token's window.

        Must be total: every window, including an empty one, has an answer.
        Returning no candidates is the overwhelmingly common case and is not an
        error — `ProviderResult.nothing` says so explicitly.
        """

    # --- Conveniences, so implementations do not repeat the ceremony --------

    @property
    def provider_id(self) -> str:
        return self.meta.provider_id

    def _nothing(self) -> ProviderResult:
        return ProviderResult.nothing(self.provider_id)

    def _unavailable(self, reason: str) -> ProviderResult:
        return ProviderResult.unavailable(self.provider_id, reason=reason)
