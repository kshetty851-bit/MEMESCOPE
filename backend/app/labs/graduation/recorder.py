"""The three loops, the buffers, and the only place this package writes.

    subscribeNewToken ─▶ watch set ─▶ getMultipleAccounts every POLL_INTERVAL_S
                                              │
                                     decode ─▶ progress ─▶ checkpoints
                                              │
    subscribeMigration ────────────────▶ post-graduation sampler (DexScreener)

Three loops in one process, sharing one watch set and one flush:

* **discovery** consumes the websocket. It never writes a sample — it only
  admits candidates and opens post-graduation windows.
* **polling** reads every watched curve from the chain on a fixed interval.
  This is where progress, checkpoints and graduation-by-`complete` come from.
* **post-graduation** samples the AMM pair for an hour after a migration.

They are separate loops because they fail separately: a rate-limited market API
must not stop the curve poll, and a websocket reconnect must not pause either.

## Nothing here is metered

The previous version of this lab bought per-trade data from PumpPortal's
`subscribeTokenTrade` at 0.01 SOL per 10,000 events. The chain reports the same
curve state for the price of an RPC call, so that stream is gone. What is lost
with it is per-trade detail — who bought, how many buyers, holder
concentration — because the account reports reserves and not who moved them.
That is a real loss and it is recorded as null, never as zero.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.db.session import SessionFactory
from app.labs.graduation import config, curve, parse
from app.labs.graduation.models import (
    STATUS_DONE,
    GradCheckpoint,
    GradCurveSample,
    GradMigration,
    GradPostgradSample,
    GradToken,
)
from app.labs.graduation.postgrad import PostGradSampler
from app.labs.graduation.sources import CurveRPC, MarketSource, PumpPortalStream
from app.labs.graduation.watchset import TokenState, WatchSet

logger = get_logger(__name__)


class GraduationRecorder:
    """Holds the sources, the watch set and the write buffers."""

    def __init__(
        self,
        *,
        stream: PumpPortalStream | None = None,
        rpc: CurveRPC | None = None,
        market: MarketSource | None = None,
        watch: WatchSet | None = None,
        session_factory: async_sessionmaker[AsyncSession] = SessionFactory,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._stream = stream or PumpPortalStream()
        self._rpc = rpc or CurveRPC()
        self._market = market or MarketSource()
        self._sessions = session_factory
        self._now = now

        self.watch = watch or WatchSet()
        self.postgrad = PostGradSampler(market=self._market, now=now)

        self._dirty: set[str] = set()
        self._retired: dict[str, tuple[TokenState, str]] = {}
        self._samples: list[dict[str, Any]] = []
        self._checkpoints: list[dict[str, Any]] = []
        self._migrations: list[dict[str, Any]] = []
        self._postgrad_rows: list[dict[str, Any]] = []

        self.dropped_rows = 0
        self.polls = 0
        self.samples_written = 0
        self.checkpoints_written = 0
        self.migrations_written = 0
        self.unexpected_fields: set[str] = set()

    @property
    def stream(self) -> PumpPortalStream:
        return self._stream

    @property
    def rpc(self) -> CurveRPC:
        return self._rpc

    # --- the loops ----------------------------------------------------------

    async def run(self) -> None:
        """Discovery, polling and post-graduation, until the stream stops."""
        if not config.enabled():
            logger.info("graduation_recorder_disabled")
            return
        async with self._rpc, self._market:
            tasks = [
                asyncio.create_task(self._poll_loop(), name="graduation-poll"),
                asyncio.create_task(self._postgrad_loop(), name="graduation-postgrad"),
            ]
            try:
                await self._discovery()
            finally:
                for task in tasks:
                    task.cancel()
                for task in tasks:
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                await self.shutdown()

    async def _discovery(self) -> None:
        async for message in self._stream.messages():
            try:
                self.handle(message, self._now())
            except Exception:  # one bad message must not end the run
                logger.exception("graduation_handle_failed")

    async def _poll_loop(self) -> None:
        while True:
            await asyncio.sleep(config.POLL_INTERVAL_S)
            try:
                await self.poll_once(self._now())
                await self.flush()
            except asyncio.CancelledError:
                raise
            except Exception:  # a failed pass retries on the next tick
                logger.exception("graduation_poll_failed")

    async def _postgrad_loop(self) -> None:
        while True:
            await asyncio.sleep(config.POSTGRAD_INTERVAL_S)
            try:
                for row in await self.postgrad.poll(self._now()):
                    self._buffer(self._postgrad_rows, row)
                await self.flush()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("graduation_postgrad_failed")

    async def shutdown(self) -> None:
        """Last flush. Every live state is closed, so a restart does not think
        it is still polling something this process no longer holds."""
        now = self._now()
        for state in self.watch.states.values():
            self._retired.setdefault(state.mint, (state, "shutdown"))
        self.watch.states.clear()
        self._dirty.clear()
        await self.flush(now=now)

    # --- discovery ----------------------------------------------------------

    def handle(self, message: dict, now: datetime) -> None:
        """One websocket message. Admits candidates and records graduations."""
        if parse.is_subscription_ack(message):
            return
        unexpected = parse.unexpected_fields(message)
        if unexpected - self.unexpected_fields:
            self.unexpected_fields |= unexpected
            logger.warning("graduation_unexpected_fields",
                           fields=sorted(self.unexpected_fields))

        if (migration := parse.parse_migration(message, received_at=now)):
            self._on_migration(migration)
            return
        if (token := parse.parse_token(message, received_at=now)):
            self._on_launch(token)

    def _on_launch(self, row: parse.TokenRow) -> None:
        """A new token joins the watch set. The only door in."""
        if row.mint in self.watch:
            return
        state = TokenState(
            mint=row.mint,
            first_seen_at=row.first_seen_at,
            name=row.name,
            symbol=row.symbol,
            creator=row.creator,
            launch_pool=row.launch_pool,
            bonding_curve_key=row.bonding_curve_key,
            quote_currency=row.quote_currency,
            curve_address=self._rpc.address_for(row.mint),
        )
        evicted = self.watch.admit(state)
        if evicted is not None:
            self._retired.setdefault(evicted.mint, (evicted, "evicted"))
            self._dirty.discard(evicted.mint)
        if row.mint in self.watch:
            self._dirty.add(row.mint)

    def _on_migration(self, row: parse.MigrationRow) -> None:
        """The graduation. The feed is GLOBAL: it reports migrations of tokens
        this lab never watched, and those are recorded too — a graduation
        nobody watched is still a graduation that happened."""
        state = self.watch.get(row.mint)
        self._buffer(self._migrations, {
            "mint": row.mint,
            "ts": row.ts,
            "pool": row.pool,
            "signature": row.signature,
            "progress_pct_before": state.max_progress if state else None,
            "seen_complete_on_chain": bool(state and state.seen_complete_on_chain),
            "raw": row.raw,
        })
        self.postgrad.start(row.mint, row.ts)
        if state is None:
            return
        state.migrated_at = row.ts
        state.max_progress = Decimal(100)
        self._dirty.add(row.mint)
        self._owe_checkpoints(state, None, ts=row.ts)
        logger.info("graduation_migrated", mint=row.mint, tracked=state.tracked)

    # --- polling ------------------------------------------------------------

    async def poll_once(self, now: datetime) -> dict[str, int]:
        """Read every watched curve, fold it in, then sweep what has expired."""
        mints = self.watch.mints()
        if not mints:
            return {"polled": 0}
        readings = await self._rpc.fetch(mints)
        self.polls += 1

        moved = 0
        for mint, state in list(self.watch.states.items()):
            if mint not in readings:
                continue  # the read did not happen; not a statement about the curve
            reading = readings[mint]
            if reading is None:
                # No account, or it did not decode. A launch is visible on the
                # websocket before its curve account is queryable, so this is
                # ordinary for the first poll or two and is not an error.
                continue
            progress = curve.progress_of(reading)
            previous_max = state.max_progress
            if state.observe(reading, progress, now):
                moved += 1
                self._buffer_sample(state, reading, progress, now)
            elif not config.SAMPLE_ON_CHANGE_ONLY:
                self._buffer_sample(state, reading, progress, now)
            cap = curve.market_cap_quote(reading)
            if cap is not None:
                state.peak_market_cap_quote = max(
                    state.peak_market_cap_quote or cap, cap)
            self._owe_checkpoints(state, reading, previous_max=previous_max, ts=now)
            if reading.complete and state.migrated_at is None:
                # The chain said so before the websocket did. Open the
                # post-graduation window now rather than waiting for a feed
                # that may never mention it.
                self.postgrad.start(mint, now)
            self._dirty.add(mint)

        for state, reason in self.watch.sweep(now):
            self._retired.setdefault(state.mint, (state, reason))
            self._dirty.discard(state.mint)
        self._rpc.forget(m for m in self._retired if m not in self.watch)
        return {"polled": len(readings), "moved": moved, "live": len(self.watch)}

    def _owe_checkpoints(self, state: TokenState, reading: Any, *,
                         previous_max: Decimal | None = None,
                         ts: datetime | None = None) -> None:
        """Write every level this token has crossed and not yet recorded.

        A token can cross three levels between two polls — fifteen seconds is
        long enough to go from 68% to 94% — and owes all three at once, each
        carrying the one reading that revealed them.
        """
        for level in config.CHECKPOINT_LEVELS:
            if level in state.levels_done:
                continue
            if not curve.crossed(previous_max, state.max_progress, level):
                continue
            state.levels_done.add(level)
            v_token, real_token = (
                curve.whole_tokens(reading.virtual_token_reserves) if reading else None,
                curve.whole_tokens(reading.real_token_reserves) if reading else None,
            )
            v_quote, real_quote = curve.quote_reserves(reading)
            self._buffer(self._checkpoints, {
                "mint": state.mint,
                "level_pct": level,
                "ts": ts or state.last_sample_at or self._now(),
                "progress_pct": state.max_progress or level,
                "v_token_reserves": v_token,
                "real_token_reserves": real_token,
                "v_quote_reserves": v_quote,
                "real_quote_reserves": real_quote,
                "quote_currency": state.quote_currency,
                "market_cap_quote": (curve.market_cap_quote(reading) if reading
                                     else state.peak_market_cap_quote),
            })

    def _buffer_sample(self, state: TokenState, reading: Any,
                       progress: Decimal | None, now: datetime) -> None:
        v_quote, real_quote = curve.quote_reserves(reading)
        self._buffer(self._samples, {
            "ts": now,
            "mint": state.mint,
            "v_token_reserves": curve.whole_tokens(reading.virtual_token_reserves),
            "real_token_reserves": curve.whole_tokens(reading.real_token_reserves),
            "v_quote_reserves": v_quote,
            "real_quote_reserves": real_quote,
            "quote_currency": state.quote_currency,
            "token_total_supply": curve.whole_tokens(reading.token_total_supply),
            "progress_pct": progress,
            "complete": reading.complete,
            "market_cap_quote": curve.market_cap_quote(reading),
        })

    # --- buffers ------------------------------------------------------------

    def _buffer(self, target: list[dict[str, Any]], row: dict[str, Any]) -> None:
        """Append, unless the buffer is at its ceiling.

        A database outage must cost memory, not the process. Dropping the
        NEWEST row keeps the buffer a contiguous record of one window rather
        than a sample with a hole in it.
        """
        total = (len(self._samples) + len(self._checkpoints)
                 + len(self._migrations) + len(self._postgrad_rows))
        if total >= config.BUFFER_MAX_ROWS:
            self.dropped_rows += 1
            return
        target.append(row)

    # --- writing ------------------------------------------------------------

    async def flush(self, *, now: datetime | None = None) -> dict[str, int]:
        """Drain every buffer in one transaction.

        Tokens first: the sample rows name them, and a reader that saw a sample
        for a mint with no token row would be reading a half-written flush. The
        buffers are swapped out BEFORE the await so a poll landing mid-write
        goes into the next batch rather than this one.
        """
        if not (self._dirty or self._retired or self._samples
                or self._checkpoints or self._migrations or self._postgrad_rows):
            return {}
        live = [self.watch.states[m] for m in self._dirty if m in self.watch]
        retired, self._retired = self._retired, {}
        samples, self._samples = self._samples, []
        checkpoints, self._checkpoints = self._checkpoints, []
        migrations, self._migrations = self._migrations, []
        postgrad, self._postgrad_rows = self._postgrad_rows, []
        self._dirty = set()
        closed_at = now or self._now()

        try:
            async with self._sessions() as session:
                await self._upsert_tokens(session, live)
                for reason in {r for _, r in retired.values()}:
                    await self._upsert_tokens(
                        session, [s for s, r in retired.values() if r == reason],
                        unsubscribed_at=closed_at, reason=reason)
                await self._insert(session, GradMigration, migrations, "mint")
                await self._insert(session, GradCurveSample, samples,
                                   constraint="uq_grad_curve_samples_mint_ts")
                await self._insert(session, GradCheckpoint, checkpoints,
                                   constraint="uq_grad_checkpoints_mint")
                await self._insert(session, GradPostgradSample, postgrad,
                                   constraint="uq_grad_postgrad_samples_mint_ts")
                await session.commit()
        except Exception:
            # The rows are gone from the buffer either way: re-queueing a batch
            # a constraint rejected would retry it for ever. The token
            # aggregates are re-derived from state on the next flush; only one
            # window of samples is lost, and the count says how many.
            self.dropped_rows += (len(samples) + len(checkpoints)
                                  + len(migrations) + len(postgrad))
            logger.exception("graduation_flush_failed", samples=len(samples),
                             checkpoints=len(checkpoints))
            return {"error": 1}

        self.samples_written += len(samples)
        self.checkpoints_written += len(checkpoints)
        self.migrations_written += len(migrations)
        return {"tokens": len(live) + len(retired), "samples": len(samples),
                "checkpoints": len(checkpoints), "migrations": len(migrations),
                "postgrad": len(postgrad)}

    async def _insert(self, session: AsyncSession, model: Any,
                      rows: list[dict[str, Any]], index: str | None = None, *,
                      constraint: str | None = None) -> None:
        """Append-only, conflicts ignored. Every one of these tables is a
        record of an observation, so a row that is already there is the same
        observation and not a newer one."""
        if not rows:
            return
        statement = insert(model).values(rows)
        if constraint is not None:
            statement = statement.on_conflict_do_nothing(constraint=constraint)
        elif index is not None:
            statement = statement.on_conflict_do_nothing(index_elements=[index])
        await session.execute(statement)

    async def _upsert_tokens(self, session: AsyncSession, states: list[TokenState],
                             *, unsubscribed_at: datetime | None = None,
                             reason: str | None = None) -> None:
        """One statement for the batch. `_dirty` is a set and `_retired` is a
        dict, so no mint appears twice — which matters, because `ON CONFLICT DO
        UPDATE` refuses a batch that touches the same row a second time."""
        if not states:
            return
        rows = [self._token_values(s, unsubscribed_at, reason) for s in states]
        statement = insert(GradToken).values(rows)
        # `pruned_at` and the empty trade aggregates are deliberately absent:
        # the pruner owns one, and a Phase 2 backfill owns the others. A live
        # flush must not reset either.
        updates = {k: getattr(statement.excluded, k) for k in rows[0]
                   if k not in ("mint", "first_seen_at")}
        if unsubscribed_at is None:
            updates.pop("unsubscribed_at")
            updates.pop("unsubscribe_reason")
        await session.execute(
            statement.on_conflict_do_update(index_elements=["mint"], set_=updates))

    def _token_values(self, state: TokenState, unsubscribed_at: datetime | None,
                      reason: str | None) -> dict[str, Any]:
        return {
            "mint": state.mint,
            "symbol": state.symbol,
            "name": state.name,
            "creator": state.creator,
            "launch_pool": state.launch_pool,
            "bonding_curve_key": state.bonding_curve_key,
            "curve_address": state.curve_address,
            "quote_currency": state.quote_currency,
            "first_seen_at": state.first_seen_at,
            "tracked_at": state.tracked_at,
            "migrated_at": state.migrated_at,
            "unsubscribed_at": unsubscribed_at,
            "unsubscribe_reason": reason,
            "status": STATUS_DONE if unsubscribed_at else state.status,
            "max_progress_pct": state.max_progress,
            "last_progress_pct": state.last_progress,
            "last_progress_change_at": state.last_progress_change_at,
            "first_sample_at": state.first_sample_at,
            "last_sample_at": state.last_sample_at,
            "sample_count": state.sample_count,
            "peak_market_cap_quote": state.peak_market_cap_quote,
        }


async def recorder_health(session: AsyncSession, *,
                          recorder: GraduationRecorder | None = None,
                          now: datetime | None = None) -> dict[str, Any]:
    """What the lab is doing, countable from the tables plus live counters."""
    now = now or datetime.now(UTC)
    since = now - timedelta(seconds=config.HEALTH_WINDOW_SECONDS)
    samples = await session.scalar(
        select(func.count()).select_from(GradCurveSample)
        .where(GradCurveSample.ts >= since))
    postgrad = await session.scalar(
        select(func.count()).select_from(GradPostgradSample)
        .where(GradPostgradSample.ts >= since))
    tracked = await session.scalar(
        select(func.count()).select_from(GradToken)
        .where(GradToken.tracked_at.is_not(None)))
    migrated = await session.scalar(
        select(func.count()).select_from(GradMigration)
        .where(GradMigration.ts >= since))
    health: dict[str, Any] = {
        "enabled": config.enabled(),
        "window_seconds": config.HEALTH_WINDOW_SECONDS,
        "curve_samples_in_window": samples or 0,
        "postgrad_samples_in_window": postgrad or 0,
        "migrations_in_window": migrated or 0,
        "tokens_ever_tracked": tracked or 0,
    }
    if recorder is not None:
        health |= {
            "connected": recorder.stream.connected,
            "reconnects": recorder.stream.reconnects,
            "messages_received": recorder.stream.messages_received,
            "watch_set": len(recorder.watch),
            "watch_set_max": config.MAX_WATCH_SET,
            "postgrad_windows": len(recorder.postgrad),
            "polls": recorder.polls,
            # Redacted: the endpoint carries the API key in its query string.
            "rpc_url": config.safe_rpc_url(),
            "rpc_calls": recorder.rpc.calls,
            "rpc_failures": recorder.rpc.failures,
            "rpc_budget_exhausted": recorder.rpc.rate_limited,
            "rpc_last_failure": recorder.rpc.last_failure,
            "dropped_rows": recorder.dropped_rows,
            "backfills": recorder.postgrad.backfilled,
            "backfill_impossible": recorder.postgrad.backfill_impossible,
            "unexpected_fields": sorted(recorder.unexpected_fields),
        }
    return health
