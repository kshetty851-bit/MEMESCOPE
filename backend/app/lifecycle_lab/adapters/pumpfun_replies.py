"""pump.fun replies — a health probe, not a fetcher.

Replies are already polled into ``pumpfun_social_snapshots`` by
``app/pumpfun/social.py``; the repository reads that table in place, so this
adapter writes no observations. It answers one question for the run log: is the
poller alive and fresh enough that "no replies row" means "none yet" rather than
"nobody was looking"?

The collector reads the newest ``observed_at`` from the repository and hands it
over with ``set_latest_observed_at``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from app.lifecycle_lab.adapters.base import AdapterResult, Subject, disabled_result
from app.lifecycle_lab.domain import DataClass, Source, SourceStatus

#: The poller runs every ~10 minutes; two missed polls is stale.
FRESH_WITHIN = timedelta(minutes=20)


class PumpfunRepliesAdapter:
    source: Source = Source.PUMPFUN_REPLIES
    data_class: DataClass = DataClass.FORWARD

    def __init__(self, settings: Any) -> None:
        self._settings = settings
        self._latest: datetime | None = None

    def enabled(self) -> tuple[bool, str | None]:
        if not self._settings.FEATURE_LIFECYCLE_LAB_ENABLED:
            return False, "lab_disabled"
        if not self._settings.FEATURE_PUMPFUN_SOCIAL_ENABLED:
            return False, "pumpfun_social_disabled"
        if not self._settings.MLL_PUMPFUN_REPLIES_ENABLED:
            return False, "disabled_by_config"
        return True, None

    def set_latest_observed_at(self, latest: datetime | None) -> None:
        self._latest = latest

    def probe(self, latest_observed_at: datetime | None, *, now: datetime) -> AdapterResult:
        if latest_observed_at is None:
            return AdapterResult(self.source, SourceStatus.UNAVAILABLE, "poller_never_ran")
        if now - latest_observed_at <= FRESH_WITHIN:
            return AdapterResult(self.source, SourceStatus.AVAILABLE, None)
        return AdapterResult(self.source, SourceStatus.STALE, "poller_stale")

    async def collect(self, subjects: Sequence[Subject], *, now: datetime) -> AdapterResult:
        ok, reason = self.enabled()
        if not ok:
            return disabled_result(self.source, reason or "disabled_by_config")
        return self.probe(self._latest, now=now)
