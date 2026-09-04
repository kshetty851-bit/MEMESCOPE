"""Celery application.

Scaffold only. Day 1 ships the plumbing plus one maintenance task; scanner and
scoring jobs land here later as their own modules under `app/workers/`.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
from celery.signals import task_postrun

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
        "app.paper.scheduler",
        "app.karthik.scheduler",
        "app.real_wallet.scheduler",
        "app.reports.scheduler",
        "app.workers.priority_tasks",
        "app.workers.enrichment_tasks",
        "app.workers.retention_tasks",
        "app.workers.research_tasks",
        "app.arena.scheduler",
        "app.lab.scheduler",
        "app.compound.scheduler",
        "app.pumpfun.scheduler",
        "app.hq_ops.tasks",
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
    # Lets `control.broadcast("pool_restart")` actually restart the prefork
    # pool. Off by default in Celery, which is why the one real remediation
    # for a wedged worker was unavailable to anything but a human with a
    # shell. The control channel is reachable only from inside the compose
    # network; this does not widen who can reach it, only what they can ask.
    worker_pool_restarts=True,
)

@task_postrun.connect
def _record_task_outcome(sender=None, state=None, retval=None, **_: object) -> None:
    """Record what every task RETURNED, so HQ can see a task that runs and fails.

    A signal rather than a decorator on each task: nothing has to be added to a
    task for it to be covered, and a task written next year is covered the day
    it is written. An opt-in registry would be a list somebody forgets, which is
    the exact failure this is here to catch.

    Wrapped completely. A monitoring write must never be able to fail the thing
    it monitors, and this runs inside the worker's task lifecycle.
    """
    name = getattr(sender, "name", None) or ""
    # Celery's own bookkeeping tasks are not the platform's work.
    if not name or name.startswith("celery."):
        return
    try:
        from app.hq_ops.task_outcomes import record
        from app.workers.runtime import run_async

        run_async(record(name, state=str(state or ""), result=retval))
    except Exception:  # noqa: BLE001
        pass


celery_app.conf.beat_schedule = {
    # Beat's proof of life, for HQ's production watch. Beat has no control
    # channel and runs where the API cannot see it, so the only way to know it
    # is still turning is for it to write that down. Every minute: the point is
    # to notice a stopped scheduler quickly, and the write is one SET.
    "hq-beat-heartbeat": {
        "task": "app.hq_ops.tasks.publish_beat_heartbeat",
        "schedule": crontab(minute="*"),
    },
    # HQ's autonomous pass. Every two minutes: fast enough that a wedged worker
    # is noticed and restarted inside a paper-review cycle, slow enough that a
    # component which flaps does not get a restart every sixty seconds. It is
    # the only scheduled task in MEMESCOPE that is permitted to change the
    # running system, and what it may change is the allowlist in
    # `app.hq_ops.remediation` and nothing else.
    "hq-ops-tick": {
        "task": "app.hq_ops.tasks.hq_ops_tick",
        "schedule": crontab(minute="*/2"),
    },
    # Karthik's observation pass. Five minutes rather than two: it watches one
    # wallet's data quality, not the platform's liveness, and nothing it can
    # find becomes more urgent for being noticed ninety seconds sooner. Under
    # OBSERVE_ONLY it opens findings and writes audit rows; it executes no
    # repair, and there is no code path from here to one.
    "karthik-ops-tick": {
        "task": "app.hq_ops.tasks.karthik_ops_tick",
        "schedule": crontab(minute="*/5"),
    },
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
    # The paper wallet advances on its own beat because nothing else can move
    # it: a position whose token stopped being enriched is exactly the one most
    # likely to be sitting through its stop. Exits are resolved from the stored
    # observation series, so a missed pass changes when a close is *recorded*,
    # never which close it was or at what price.
    #
    # Every minute, not every five. The cadence used to match the opportunity
    # review, which was defensible while an open position's quote was itself
    # minutes old — the pass had nothing new to read. Open positions now sit in
    # the priority lane at fifteen seconds, so this beat became the slowest link
    # in the chain, and `last_evaluated_at` is a timestamp the wallet *shows*:
    # a five-minute-old evaluation reads as a stalled wallet whatever the price
    # behind it says. Measured at 2.5s per pass against 13 open positions on
    # 2026-08-19, and a shorter window means each pass replays less, not more.
    "paper-review": {
        "task": "app.paper.scheduler.paper_review",
        "schedule": crontab(minute="*"),
    },
    # The Karthik wallet's own beat, beside the paper wallet's rather than
    # inside it. Every minute for the same reason: Karthik prices both its
    # entries and its exits from the freshest observation it can see, so the
    # gap between admission and entry — the number the experiment is measured
    # on — is bounded by this cadence. Its task takes a different advisory lock
    # and its own session, so neither wallet can delay or roll back the other.
    "karthik-review": {
        "task": "app.karthik.scheduler.karthik_review",
        "schedule": crontab(minute="*"),
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
    # Raw telemetry expiry. This beat did not exist until 2026-08-21, and its
    # absence is why production reached 100% disk: `retention_tasks` could not
    # even be imported, so `token_market_snapshots` was never pruned once and
    # `radar_decision_snapshots` had no policy at all. In the quiet hour beside
    # the other maintenance, and deliberately delete-only — reclaiming pages to
    # the filesystem needs VACUUM FULL, which takes an exclusive lock and is an
    # operator action, not something a beat should do behind your back.
    "nursery-sweep": {
        "task": "app.workers.research_tasks.nursery_sweep",
        "schedule": crontab(minute="*/15"),
    },
    "research-quotes-sample": {
        "task": "app.workers.research_tasks.research_quotes_sample",
        "schedule": crontab(minute="*/5"),
    },
    "holder-snapshots-collect": {
        "task": "app.workers.research_tasks.holder_snapshots_collect",
        "schedule": crontab(minute="*/10"),
    },
    "universe-snapshot-daily": {
        "task": "app.workers.research_tasks.universe_snapshot_daily",
        "schedule": crontab(hour="2", minute="10"),
    },
    # Enrolment follows the snapshot by twenty minutes, then repeats hourly so
    # a token crossing the liquidity floor mid-day is observed the same day.
    "universe-enrol": {
        "task": "app.workers.research_tasks.universe_enrol",
        "schedule": crontab(minute="30"),
    },
    # Research simulation: judges due checkpoints and advances virtual
    # positions. Cannot touch paper, karthik or real-wallet accounting.
    "arena-tick": {
        "task": "app.arena.scheduler.arena_tick",
        "schedule": crontab(minute="*"),
    },
    # V6 Strategy Lab: twenty virtual portfolios. Every minute, like the Arena,
    # so a 30-minute checkpoint is judged within a minute of coming due and the
    # 24-hour snapshot lands on its frozen boundary rather than drifting.
    "lab-tick": {
        "task": "app.lab.scheduler.lab_tick",
        "schedule": crontab(minute="*"),
    },
    # The Compound Lab: one wallet, one rule, and a target on the WALLET rather
    # than on a position. Same cadence as the Lab it shares an engine with — the
    # cycle target has to be tested on the same marks the Lab settles against,
    # and a slower beat would bank a cycle at a price that had already moved.
    "compound-tick": {
        "task": "app.compound.scheduler.compound_tick",
        "schedule": crontab(minute="*"),
    },
    # The PumpFun Lab mirrors one on-chain wallet. Every minute, because the
    # leader's median hold is 8.5 minutes — a slower poll would copy trades he
    # had already closed.
    "pumpfun-tick": {
        "task": "app.pumpfun.scheduler.pumpfun_tick",
        "schedule": crontab(minute="*"),
    },
    # Re-quotes what the Lab holds open so `settle` marks it at what a seller
    # would actually be offered, rather than at a CPMM model over a reported
    # liquidity figure that stops describing a market once the pool collapses.
    # Every three minutes, not every minute: Jupiter rate-limits hard and the
    # sweep paces itself, and a mark that is three minutes behind is still
    # incomparably better than one that trusts a dead pool.
    "lab-sellability-refresh": {
        "task": "app.lab.scheduler.lab_sellability_refresh",
        "schedule": crontab(minute="*/3"),
    },
    # The real wallet's heartbeat. Beside the Lab's and at the same cadence,
    # because it acts on Lab decisions and those are actionable for ten minutes.
    # It creates at most one BUY intent per tick and only while the operator's
    # switch is on; with the switch off — its default — it refuses immediately.
    "real-wallet-driver-tick": {
        "task": "app.real_wallet.scheduler.real_wallet_driver_tick",
        "schedule": crontab(minute="*"),
    },
    # The other half of the driver. Without it the wallet buys and never sells,
    # so no profit is realised and nothing compounds. Every minute, because a
    # take-profit is measured against a mark and a mark an hour old is not one.
    "real-wallet-executor-tick": {
        "task": "app.real_wallet.scheduler.real_wallet_executor_tick",
        "schedule": crontab(minute="*"),
    },
    # The chain balance against what the rail says it did. Every two minutes,
    # matching HQ's own pass: this is the only real-wallet signal that is
    # security rather than operations, and the window a movement can hide in
    # should be the shortest one that is not wasteful.
    "real-wallet-balance-watch": {
        "task": "app.real_wallet.scheduler.real_wallet_balance_watch",
        "schedule": crontab(minute="*/2"),
    },
    "real-wallet-exit-tick": {
        "task": "app.real_wallet.scheduler.real_wallet_exit_tick",
        "schedule": crontab(minute="*"),
    },
    "regime-snapshot-hourly": {
        "task": "app.workers.research_tasks.regime_snapshot_hourly",
        "schedule": crontab(minute="7"),
    },
    "executable-outcomes-compute": {
        "task": "app.workers.research_tasks.executable_outcomes_compute",
        "schedule": crontab(minute="37"),
    },
    "prune-telemetry": {
        "task": "app.workers.retention_tasks.prune_telemetry",
        "schedule": crontab(hour="3", minute="45"),
    },
    # The guard that would have caught it. Every fifteen minutes, because the
    # measured fill rate at the time was ~1.4 GB/day against 2.6 GB free — the
    # window between "fine" and "Redis cannot persist" was under two days.
    "check-disk-space": {
        "task": "app.workers.retention_tasks.check_disk_space",
        "schedule": crontab(minute="*/15"),
    },
    # The daily paper-wallet email. Every fifteen minutes rather than once at
    # 09:00, and the beat here is UTC while the report time is local — the task
    # itself decides whether the wall clock in `DAILY_REPORT_TIMEZONE` has
    # reached the configured hour.
    #
    # That indirection buys three things a `crontab(hour=...)` cannot: it
    # survives a worker being down at the exact minute, it retries a failed
    # send without waiting a day, and it does not silently shift when the
    # report timezone observes DST while Celery does not. Sending twice is
    # prevented by a partial unique index, not by the schedule.
    "daily-paper-report": {
        "task": "app.reports.scheduler.daily_paper_report",
        "schedule": crontab(minute="*/15"),
    },
}
