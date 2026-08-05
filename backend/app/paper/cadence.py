"""When the wallet next looks at the Radar.

Sprint 30 §12 asks the dashboard to show the next Radar evaluation. That is a
fact about the schedule, not about the data, so it is computed rather than
stored — and computed from a constant that a test pins to the Celery beat, so
the number on the page cannot drift away from the job that actually runs.

The wallet also reviews on its own five-minute beat and immediately after every
Radar refresh, so this is the next moment the *ranking* can change, which is the
one that decides new entries. Exits do not wait for it: they are resolved from
the stored observation series, so a price that breached a rule at noon closes the
position at noon whenever the pass happens to run.

Pure: no I/O, no clock, no randomness. `now` is a parameter.
"""

from __future__ import annotations

from datetime import datetime, timedelta

#: The Radar sweep's cadence, in minutes. `test_paper_cadence.py` asserts this
#: equals the `radar-sweep` crontab in `app/workers/celery_app.py` — a page that
#: predicts the next evaluation from a number nobody checks is a page that
#: eventually predicts the wrong one.
RADAR_SWEEP_MINUTES = 15


def next_evaluation(now: datetime, *, every_minutes: int = RADAR_SWEEP_MINUTES) -> datetime:
    """The next wall-clock boundary the Radar sweep fires on.

    Crontab minutes are absolute (`*/15` fires at :00, :15, :30, :45), not
    relative to the last run, so this is the boundary after `now` rather than
    `now` plus an interval. A tick landing exactly on a boundary returns the
    *next* one: the moment has arrived, and the answer to "when next" is never
    "now".
    """
    floor = now.replace(second=0, microsecond=0)
    passed = (floor.minute // every_minutes) * every_minutes
    boundary = floor.replace(minute=passed)
    return boundary + timedelta(minutes=every_minutes)
