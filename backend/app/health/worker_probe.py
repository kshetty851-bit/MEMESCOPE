"""Container healthchecks for the Celery worker and beat.

`python -m app.health.worker_probe worker` / `... beat`.

Both services inherited the image's `HEALTHCHECK`, which curls
`http://localhost:8000/live` — an endpoint that exists only in the API
container. In the worker and the scheduler it can never succeed, so both
reported `unhealthy` permanently and the signal meant nothing.

That is not cosmetic. On 2026-08-21 the worker wedged on a Redis transaction
and consumed **nothing for fifty minutes** — no paper review, no priority lane,
no retention — while beat happily queued tasks nobody ran. Its container status
during the outage was `unhealthy`, exactly as it had been for weeks while
perfectly fine. A check that is always failing cannot report a failure.

Each probe asks the question that distinguishes alive from dead **for that
process**:

  * The **worker** answers a Celery ping. It is the one signal that proves the
    consumer loop is actually turning rather than blocked, which is precisely
    what a wedged worker is not.
  * **Beat** has no such control channel — it only sends. So it is judged by
    its shelve: beat writes the schedule file every time it fires, and a file
    that has stopped advancing is a beat that has stopped scheduling.
"""

from __future__ import annotations

import socket
import sys
import time
from pathlib import Path

from app.core.logging import configure_logging, get_logger

logger = get_logger(__name__)

#: Where beat is told to keep its schedule (`--schedule=` in compose).
BEAT_SCHEDULE_PATHS = (
    Path("/var/lib/celery/celerybeat-schedule"),
    Path("/tmp/celerybeat-schedule"),  # noqa: S108 - the development path
)

#: Beat's shelve must have been touched inside this window. Generous on
#: purpose: the busiest beat here fires every minute, and the point is to catch
#: a stopped scheduler, not to police jitter.
BEAT_MAX_AGE_SECONDS = 600.0


def check_worker() -> bool:
    """True when **this container's** worker answers a ping.

    Scoped by destination, not broadcast. `control.ping()` with no destination
    asks every worker on the broker, so a container whose own worker was dead
    would still see a reply from a healthy sibling and report itself fine —
    verified: the API container, which runs no worker at all, gets a reply.
    A healthcheck that any other host can satisfy is not a healthcheck.

    The node name is `celery@<hostname>`, which inside a container is its own
    id — so this asks exactly one worker: the one this healthcheck speaks for.
    """
    from app.workers.celery_app import celery_app

    node = f"celery@{socket.gethostname()}"
    replies = celery_app.control.ping(destination=[node], timeout=10.0) or []
    healthy = any(node in reply for reply in replies)
    logger.info("worker_probe", healthy=healthy, node=node, replies=len(replies))
    return healthy


def check_beat() -> bool:
    """True when beat's schedule file exists and is still advancing."""
    for path in BEAT_SCHEDULE_PATHS:
        # The shelve may be `<name>` or `<name>.db` depending on the backend.
        for candidate in (path, path.with_suffix(".db")):
            if not candidate.exists():
                continue
            age = time.time() - candidate.stat().st_mtime
            healthy = age <= BEAT_MAX_AGE_SECONDS
            logger.info(
                "beat_probe", healthy=healthy, path=str(candidate), age_seconds=round(age, 1)
            )
            return healthy

    # No schedule file at all. Beat writes one on its first tick, so this is
    # either a beat that has never started or one pointed somewhere else.
    logger.error("beat_probe", healthy=False, reason="no schedule file found")
    return False


def main(argv: list[str]) -> int:
    configure_logging()
    role = argv[1] if len(argv) > 1 else "worker"
    try:
        ok = check_worker() if role == "worker" else check_beat()
    except Exception as exc:
        logger.error(
            "worker_probe_failed", role=role, error=str(exc), error_type=type(exc).__name__
        )
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
