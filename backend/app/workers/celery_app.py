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
    include=["app.workers.tasks"],
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
}
