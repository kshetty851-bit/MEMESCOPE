"""Celery application.

Scaffold only. Day 1 ships the plumbing plus one maintenance task; scanner and
scoring jobs land here later as their own modules under `app/workers/`.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "memescope",
    broker=settings.REDIS_URI,
    backend=settings.REDIS_URI,
    include=[
        "app.workers.tasks",
        "app.workers.scoring_tasks",
        "app.radar.scheduler",
        "app.events.scheduler",
        "app.opportunities.scheduler",
        "app.paper.scheduler",
        "app.real_wallet.scheduler",
        "app.workers.priority_tasks",
        "app.workers.enrichment_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=600,
    task_soft_time_limit=540,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=200,
    broker_connection_retry_on_startup=True,
    result_expires=3600,
)

celery_app.conf.beat_schedule = {
    "purge-expired-refresh-tokens": {
        "task": "app.workers.tasks.purge_expired_refresh_tokens",
        "schedule": crontab(hour="3", minute="0"),
    },
    # The reconciliation pass behind the enrichment worker's fast path. Not
    # optional: the fast path cannot cover the crash window between the
    # enrichment commit and the scoring commit, nor deploys and restarts.
    "score-sweep": {
        "task": "app.workers.scoring_tasks.score_sweep",
        "schedule": crontab(minute="*/15"),
    },
    # Runs beside the refresh-token purge, in the same quiet hour.
    "prune-score-history": {
        "task": "app.workers.scoring_tasks.prune_score_history",
        "schedule": crontab(hour="3", minute="30"),
    },
    # The Radar re-evaluates existing projects on its own cadence, independent
    # of discovery. Every 15 minutes: often enough that a breakout is caught the
    # same hour, rare enough that the sweep never overruns itself.
    "radar-sweep": {
        "task": "app.radar.scheduler.radar_sweep",
        "schedule": crontab(minute="*/15"),
    },
    # Admission only: reuses persisted discovery and market data without
    # invoking the existing opportunity-scoring sweep above.
    "pumpfun-radar-scan": {
        "task": "app.radar.scheduler.pumpfun_radar_scan",
        "schedule": crontab(minute="*/15"),
    },
    # Event detection runs a few minutes *after* the Radar sweep, deliberately.
    # It compares fresh analyst readings against the cached previous ones, so
    # running it before the sweep would diff a stale reading against itself and
    # report nothing — losing the change until the next cycle.
    "event-cycle": {
        "task": "app.events.scheduler.event_cycle",
        "schedule": crontab(minute="3,18,33,48"),
    },
    # Closing an opportunity needs no new data, only elapsed time, and the
    # enrichment fast path cannot do it: a token whose signal has gone quiet is
    # exactly the one detection stops visiting. Every five minutes, not fifteen,
    # because the grace window is an hour — a board that shows a lapsed
    # opportunity as ACTIVE is making a claim about now from data about then.
    "opportunity-review": {
        "task": "app.opportunities.scheduler.opportunity_review",
        "schedule": crontab(minute="*/5"),
    },
    # The paper wallet advances on its own beat because nothing else can move
    # it: a position whose token stopped being enriched is exactly the one most
    # likely to be sitting through its stop. Every five minutes, matching the
    # opportunity review — exits are resolved from the stored observation
    # series, so a missed pass changes when a close is *recorded*, never which
    # close it was or at what price.
    "paper-review": {
        "task": "app.paper.scheduler.paper_review",
        "schedule": crontab(minute="*/5"),
    },
    "real-wallet-dry-run-reconciliation": {
        "task": "app.real_wallet.scheduler.real_wallet_dry_run",
        "schedule": crontab(minute="*/5"),
    },
    # Membership of the priority enrichment lane is derived from what the
    # product currently displays, so it has to be recomputed rather than
    # accumulated. Every minute: the lane refreshes its members every fifteen
    # seconds, so a minute of membership lag costs at most four refreshes on a
    # token that just entered the visible ranks.
    "priority-lane": {
        "task": "app.workers.priority_tasks.refresh_priority_lane",
        "schedule": crontab(minute="*"),
    },
    # Dead-lettering is a quarantine, not a grave. Every five minutes the
    # readmission pass returns tokens that have served their idle period — the
    # beat that did not exist when a 60-second provider outage parked 163 of the
    # 200 priority-lane tokens on 2026-08-05 and nothing brought them back.
    # Cheap by construction: one predicated UPDATE, bounded per pass.
    "enrichment-requeue-dead-letters": {
        "task": "app.workers.enrichment_tasks.requeue_dead_letters",
        "schedule": crontab(minute="*/5"),
    },
}
