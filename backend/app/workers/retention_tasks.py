"""Retention: keeping raw telemetry from filling the disk.

**This file used to be dead code, and the disk paid for it.** It imported
`app.core.celery_app` and `app.core.utils.async_celery` — neither of which has
ever existed — so it could not be imported at all. It was absent from Celery's
`include` list, absent from `beat_schedule`, and its task defaulted to
`dry_run=True`. `token_market_snapshots` was therefore never pruned once, and
`radar_decision_snapshots` had no policy in any form. On 2026-08-21 production
reached 100% disk: Redis could no longer write its RDB, returned `MISCONF` on
every write, Celery beat could not enqueue, and **every scheduled job silently
stopped** — including paper review. A retention worker that cannot fail loudly
is worse than none, because its silence is indistinguishable from success.

So this module is built around three rules learned from that incident.

**Deleting is not reclaiming.** `DELETE` marks tuples dead; plain `VACUUM`
returns the space to the table's own free space map, not to the filesystem.
Only `VACUUM FULL` (or a partition drop) gives pages back to the OS, and it
needs free space equal to the *retained* size. These jobs therefore keep tables
from growing further; they do not shrink a table that has already exploded.
That is a deliberate split: the recurring job is safe and lock-free, and the
one-off compaction is an operator action taken with the free space measured.

**Evidence outlives telemetry.** A row that explains a trade is not telemetry.
`token_market_snapshots` is pruned with a permanent carve-out for every mint in
`radar_tokens` or `paper_positions`, so an admitted or traded token keeps its
whole observed history regardless of age. The previous implementation protected
only *open* positions, which would have deleted the entry and exit evidence of
every closed trade.

**Retention must never be able to stop trading.** Each table is pruned in its
own transaction and its own try block, and the task returns a report instead of
raising. A failure here costs disk, not exits.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from typing import Any
from typing import cast as _cast

from sqlalchemy import CursorResult, text

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.workers.celery_app import celery_app
from app.workers.runtime import run_async

logger = get_logger(__name__)

#: Deleted in bounded batches. One 5-million-row `DELETE` holds a transaction
#: and its locks for minutes and bloats WAL; a loop of 50k leaves gaps for
#: autovacuum and for everything else using the table.
_BATCH = 50_000
_MAX_BATCHES = 400


async def _delete_in_batches(sql: str, params: dict[str, Any]) -> int:
    """Run a bounded delete loop. Returns rows removed."""
    removed = 0
    for _ in range(_MAX_BATCHES):
        async with SessionFactory() as session:
            result = await session.execute(text(sql), params)
            await session.commit()
        count = _cast("CursorResult[Any]", result).rowcount or 0
        removed += count
        if count < _BATCH:
            break
    return removed


async def _prune_score_history(days: int) -> int:
    return await _delete_in_batches(
        """
        DELETE FROM token_score_history
        WHERE ctid IN (
            SELECT ctid FROM token_score_history
            WHERE evaluated_at < :cutoff
            LIMIT :batch
        )
        """,
        {"cutoff": datetime.now(UTC) - timedelta(days=days), "batch": _BATCH},
    )


async def _prune_market_snapshots(days: int) -> int:
    """Prune ordinary tokens only. Admitted and traded mints are kept forever.

    The carve-out is the whole point: these rows are how an entry price, an
    exit price and every trailing-stop decision in between are explained. A
    token that reached the Radar or the wallet keeps its complete series, and
    so does any snapshot a paper or radar decision referenced — those foreign
    keys are ON DELETE SET NULL, so pruning one would not fail, it would
    silently blank the link from a decision to the observation it acted on.

    **Both protected sets are inline CTEs, not temp tables.** A temp table
    belongs to one connection, and committing between batches hands the
    connection back to the pool — so the next batch can land on a different
    one and fail with `relation "_protected_mints" does not exist`. That is
    invisible while the pool happens to hand back the same connection, which
    is exactly how it passed in isolation and failed in a full suite run. The
    sets are small (~700 mints, ~900 ids), so hashing them per batch is
    cheaper than the bug.

    The scan is driven off `ix_snapshots_captured_at` by `ORDER BY
    captured_at`, so each batch walks the oldest rows in index order and stops
    at the limit rather than scanning the table.
    """
    return await _delete_in_batches(
        """
        WITH prot_mints AS (
            SELECT mint_address FROM radar_tokens
            UNION
            SELECT mint_address FROM paper_positions
        ),
        prot_snaps AS (
            SELECT market_snapshot_id AS id FROM paper_decision_snapshots
             WHERE market_snapshot_id IS NOT NULL
            UNION
            SELECT market_snapshot_id FROM paper_decision_outcomes
             WHERE market_snapshot_id IS NOT NULL
            UNION
            SELECT market_snapshot_id FROM radar_decision_outcomes
             WHERE market_snapshot_id IS NOT NULL
        ),
        doomed AS (
            SELECT s.id FROM token_market_snapshots s
            WHERE s.captured_at < :cutoff
              AND NOT EXISTS (
                  SELECT 1 FROM prot_mints p WHERE p.mint_address = s.mint_address
              )
              AND NOT EXISTS (SELECT 1 FROM prot_snaps x WHERE x.id = s.id)
            ORDER BY s.captured_at
            LIMIT :batch
        )
        DELETE FROM token_market_snapshots t USING doomed d WHERE t.id = d.id
        """,
        {"cutoff": datetime.now(UTC) - timedelta(days=days), "batch": _BATCH},
    )


async def _prune_radar_decision_snapshots(days: int) -> int:
    """Raw forward-research input. `radar_decision_outcomes` — the distilled
    result, and the only part any analysis reads — is never touched.

    A decision that already has an outcome is **excluded, not deleted**: that
    foreign key is `ON DELETE RESTRICT`, so removing such a row does not prune
    it, it raises and aborts the batch. The exclusion is also the correct
    semantics — an outcome without the decision it scored explains nothing.
    """
    return await _delete_in_batches(
        """
        DELETE FROM radar_decision_snapshots
        WHERE id IN (
            SELECT s.id FROM radar_decision_snapshots s
            WHERE s.evaluated_at < :cutoff
              AND NOT EXISTS (
                  SELECT 1 FROM radar_decision_outcomes o WHERE o.decision_id = s.id
              )
            ORDER BY s.evaluated_at
            LIMIT :batch
        )
        """,
        {"cutoff": datetime.now(UTC) - timedelta(days=days), "batch": _BATCH},
    )


def disk_usage_percent(path: str = "/") -> float:
    total, used, _free = shutil.disk_usage(path)
    return round(100.0 * used / total, 1) if total else 0.0


@celery_app.task(name="app.workers.retention_tasks.prune_telemetry")
def prune_telemetry() -> dict[str, Any]:
    """Expire raw telemetry. Never raises; a failure costs disk, not exits."""
    return run_async(_prune_telemetry())


async def _prune_telemetry() -> dict[str, Any]:
    report: dict[str, Any] = {
        "disk_percent_before": disk_usage_percent(),
        "score_history": 0,
        "market_snapshots": 0,
        "radar_decision_snapshots": 0,
        "wallet_flow_snapshots": 0,
        "radar_rank_events": 0,
        "failures": [],
    }

    jobs = (
        ("score_history", _prune_score_history, settings.SCORING_HISTORY_RETENTION_DAYS),
        ("market_snapshots", _prune_market_snapshots, settings.MARKET_SNAPSHOT_RETENTION_DAYS),
        (
            "radar_decision_snapshots",
            _prune_radar_decision_snapshots,
            settings.RADAR_DECISION_SNAPSHOT_RETENTION_DAYS,
        ),
        (
            "wallet_flow_snapshots",
            _prune_wallet_flow_snapshots,
            settings.WALLET_FLOW_RETENTION_DAYS,
        ),
        (
            "radar_rank_events",
            _prune_radar_rank_events,
            settings.RADAR_RANK_EVENT_RETENTION_DAYS,
        ),
    )
    for name, prune, days in jobs:
        try:
            report[name] = await prune(days)
        except Exception as exc:
            # Contained per table: one bad prune must not cost the others, and
            # must not raise into the beat.
            report["failures"].append(name)
            logger.exception("retention_prune_failed", table=name, error=str(exc))

    report["disk_percent_after"] = disk_usage_percent()

    # Logged at every level the operator cares about, and *always* logged even
    # at zero. A retention job that only speaks when it acts is
    # indistinguishable from one that has stopped running — which is precisely
    # how this went unnoticed until the disk was full.
    if report["failures"]:
        logger.error("retention_completed_with_failures", **report)
    else:
        logger.info("retention_completed", **report)
    return report


async def _prune_wallet_flow_snapshots(days: int) -> int:
    """Wallet-flow rows are research primitives with a bounded shelf life —
    decision-time reads happen within hours; the window covers any replay."""
    return await _delete_in_batches(
        """
        DELETE FROM wallet_flow_snapshots
        WHERE ctid IN (
            SELECT ctid FROM wallet_flow_snapshots
            WHERE captured_at < :cutoff
            LIMIT :batch
        )
        """,
        {"cutoff": datetime.now(UTC) - timedelta(days=days), "batch": _BATCH},
    )


async def _prune_radar_rank_events(days: int) -> int:
    """Rank telemetry: one row per mint per rank observation.

    Added 2026-08-26. This table had NO retention and was the only unbounded
    telemetry left — 1.27M rows and 865MB when it was found, while every
    neighbouring table was being pruned on schedule. It stopped being written
    on 2026-08-22 when the flag that produced it was paused, so today it is a
    frozen 865MB rather than a growing one; the policy exists so that turning
    that flag back on does not quietly restart the growth.

    Pruned on `observed_at` rather than `created_at`: the former is when the
    rank was true, which is the only timestamp a replay would filter on.
    """
    return await _delete_in_batches(
        """
        DELETE FROM radar_rank_events
        WHERE ctid IN (
            SELECT ctid FROM radar_rank_events
            WHERE observed_at < :cutoff
            LIMIT :batch
        )
        """,
        {"cutoff": datetime.now(UTC) - timedelta(days=days), "batch": _BATCH},
    )


@celery_app.task(name="app.workers.retention_tasks.check_disk_space")
def check_disk_space() -> dict[str, Any]:
    """Watch the disk, and act before Postgres and Redis are endangered.

    The threshold is not cosmetic. At 100% Redis cannot persist and rejects
    every write with `MISCONF`, which takes Celery beat down with it; Postgres
    stops accepting writes shortly after. 85% leaves room for a backup plus a
    table rewrite, so the emergency pass has somewhere to work.
    """
    percent = disk_usage_percent()
    report: dict[str, Any] = {"disk_percent": percent, "action": "none"}

    if percent >= settings.DISK_CRITICAL_PERCENT:
        # Tighter windows, applied immediately. Evidence keeps its carve-out.
        report["action"] = "emergency_prune"
        logger.error(
            "disk_critical",
            disk_percent=percent,
            threshold=settings.DISK_CRITICAL_PERCENT,
            detail=(
                "Emergency retention pass. At 100% Redis loses persistence and "
                "every scheduled job stops."
            ),
        )
        report["emergency"] = run_async(_emergency_prune())
    elif percent >= settings.DISK_WARNING_PERCENT:
        report["action"] = "warn"
        logger.warning(
            "disk_warning", disk_percent=percent, threshold=settings.DISK_WARNING_PERCENT
        )
    else:
        logger.info("disk_ok", disk_percent=percent)
    return report


async def _emergency_prune() -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        out["score_history"] = await _prune_score_history(
            settings.SCORING_HISTORY_EMERGENCY_DAYS
        )
        out["radar_decision_snapshots"] = await _prune_radar_decision_snapshots(
            settings.RADAR_DECISION_SNAPSHOT_EMERGENCY_DAYS
        )
    except Exception as exc:
        logger.exception("emergency_prune_failed", error=str(exc))
        out["failed"] = True
    return out
