"""X (Twitter) - interface only.

No network call is ever made from this module. ``collect`` returns DISABLED.

To enable it, all of the following must exist; none is scraped or worked around:
  * a paid X API plan that includes the **recent search counts** endpoint
    (``GET /2/tweets/counts/recent``, 7-day window, hourly/daily granularity);
  * an app-only bearer token in ``MLL_X_BEARER_TOKEN``;
  * ``MLL_X_ENABLED=true``;
  * an implementation of ``collect`` that maps each count bucket to a
    ``MENTIONS`` / ``WINDOW_COUNT`` observation, with 429 -> ``ERROR
    rate_limited`` like every other adapter.

Until then ``enabled()`` reports why, and the run log shows DISABLED - never a
zero count.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from app.lifecycle_lab.adapters.base import AdapterResult, Subject, disabled_result
from app.lifecycle_lab.domain import DataClass, Source


class XAdapter:
    source: Source = Source.X
    data_class: DataClass = DataClass.FORWARD

    def __init__(self, settings: Any) -> None:
        self._settings = settings

    def enabled(self) -> tuple[bool, str | None]:
        if not self._settings.FEATURE_LIFECYCLE_LAB_ENABLED:
            return False, "lab_disabled"
        if (
            not self._settings.MLL_X_ENABLED
            or not self._settings.MLL_X_BEARER_TOKEN.get_secret_value()
        ):
            return False, "disabled_by_config"
        # Configured, but there is no implementation to run.
        return False, "not_implemented_no_api_plan"

    async def collect(self, subjects: Sequence[Subject], *, now: datetime) -> AdapterResult:
        _, reason = self.enabled()
        return disabled_result(self.source, reason or "not_implemented_no_api_plan")
