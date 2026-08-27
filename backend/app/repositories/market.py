"""Market snapshot and enrichment-state persistence.

Database access only — no provider calls, no scheduling decisions. The worker
and service pass in already-computed values.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import (
    ARRAY,
    CursorResult,
    Select,
    String,
    and_,
    func,
    literal,
    select,
    true,
    update,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import cast as sa_cast
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import aliased

from app.models.market import (
    LANE_NORMAL,
    LANE_TRACK_RECORD,
    EnrichmentStatus,
    TokenEnrichmentState,
    TokenMarketSnapshot,
)
from app.models.paper import PaperWallet
from app.models.radar import RadarToken
from app.models.token import DiscoveredToken
from app.repositories.base import BaseRepository


class MarketSnapshotRepository(BaseRepository[TokenMarketSnapshot]):
    """Append-only history. Nothing here ever updates a snapshot."""

    model = TokenMarketSnapshot

    async def add_snapshot(self, values: dict[str, Any]) -> TokenMarketSnapshot:
        snapshot = TokenMarketSnapshot(**values)
        self.session.add(snapshot)
        await self.session.flush()
        await self.session.refresh(snapshot)
        return snapshot

    async def add_many(self, rows: Sequence[dict[str, Any]]) -> int:
        """Bulk insert. Used by the worker to write a whole batch in one round trip."""
        if not rows:
            return 0
        await self.session.execute(pg_insert(TokenMarketSnapshot).values(list(rows)))
        return len(rows)

    async def recent_context(
        self, token_ids: Sequence[Any], *, window_seconds: int, per_token: int = 12
    ) -> dict[Any, list[TokenMarketSnapshot]]:
        """The comparison window the ingest firewall judges new prints against.

        Oldest-first per token, flagged rows included (the classifier needs
        them for its persistence rule). One LATERAL seek per token, same shape
        as `_newest_per_mint` and for the same reason.
        """
        unique = list(dict.fromkeys(token_ids))
        if not unique:
            return {}
        cutoff = datetime.now(UTC) - timedelta(seconds=window_seconds)
        wanted = select(
            func.unnest(literal([str(t) for t in unique], ARRAY(String))).label("tid")
        ).subquery("wanted")
        recent = (
            select(TokenMarketSnapshot)
            .where(
                TokenMarketSnapshot.token_id == sa_cast(wanted.c.tid, PgUUID(as_uuid=True)),
                TokenMarketSnapshot.captured_at >= cutoff,
            )
            .order_by(TokenMarketSnapshot.captured_at.desc())
            .limit(per_token)
            .lateral("recent")
        )
        entity = aliased(TokenMarketSnapshot, recent)
        stmt = select(entity).select_from(wanted).join(recent, true())
        out: dict[Any, list[TokenMarketSnapshot]] = {}
        for row in (await self.session.execute(stmt)).scalars():
            out.setdefault(row.token_id, []).append(row)
        for rows in out.values():
            rows.sort(key=lambda r: r.captured_at)
        return out

    async def latest_for_mint(self, mint_address: str) -> TokenMarketSnapshot | None:
        stmt = (
            select(TokenMarketSnapshot)
            .where(
                TokenMarketSnapshot.mint_address == mint_address,
                # Ingest firewall: a flagged print stays stored and auditable,
                # but it is never "the market right now".
                TokenMarketSnapshot.suspect.is_not(True),
            )
            .order_by(TokenMarketSnapshot.captured_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def latest_priced_for_mint_as_of(
        self, mint_address: str, *, as_of: datetime
    ) -> TokenMarketSnapshot | None:
        """Newest usable price at or before `as_of`.

        Manual paper exits use this instead of the unconstrained latest row so a
        future-dated observation cannot become a fill.
        """
        stmt = (
            select(TokenMarketSnapshot)
            .where(
                TokenMarketSnapshot.mint_address == mint_address,
                TokenMarketSnapshot.captured_at <= as_of,
                TokenMarketSnapshot.price_usd.is_not(None),
                TokenMarketSnapshot.price_usd > 0,
                TokenMarketSnapshot.suspect.is_not(True),
            )
            .order_by(TokenMarketSnapshot.captured_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def first_priced_for_mints_since(
        self, discovered_at: dict[str, datetime], *, as_of: datetime | None = None
    ) -> dict[str, TokenMarketSnapshot]:
        """First usable observation at or after each scanner discovery.

        It makes an all-scanned entry reproducible: a later review cannot use a
        newer quote merely because the evaluator was delayed.
        """
        if not discovered_at:
            return {}
        predicates = [
            TokenMarketSnapshot.mint_address.in_(list(discovered_at)),
            TokenMarketSnapshot.price_usd.is_not(None),
            TokenMarketSnapshot.price_usd > 0,
        ]
        if as_of is not None:
            predicates.append(TokenMarketSnapshot.captured_at <= as_of)
        rows = (
            await self.session.execute(
                select(TokenMarketSnapshot)
                .where(*predicates)
                .order_by(
                    TokenMarketSnapshot.mint_address.asc(),
                    TokenMarketSnapshot.captured_at.asc(),
                )
            )
        ).scalars().all()
        first: dict[str, TokenMarketSnapshot] = {}
        for row in rows:
            if row.mint_address in first:
                continue
            detected = discovered_at[row.mint_address]
            if row.captured_at >= detected:
                first[row.mint_address] = row
        return first

    async def _newest_per_mint(
        self,
        mints: Sequence[str],
        predicates: Sequence[Any],
    ) -> Sequence[TokenMarketSnapshot]:
        """The newest snapshot per mint, one index seek each.

        `DISTINCT ON (mint_address) ... WHERE mint_address IN (...)` reads
        *every* snapshot for every mint and sorts the lot to keep one row per
        group. On 2026-08-19 that was 223,851 rows and a 54 MB external merge
        for 100 mints — 4.5 s a chunk, 52 s of the paper wallet's 75 s
        response, and it grows with history rather than with the answer.

        A LATERAL with `LIMIT 1` asks the question the
        `(mint_address, captured_at DESC)` index already answers: seek, take the
        first row, stop. Same plan measured at 40 ms for the same 100 mints, and
        the cost no longer depends on how much history a mint has.

        Chunked because the mint list rides in as one array parameter, and a
        single statement over tens of thousands of mints is its own problem.
        """
        unique = list(dict.fromkeys(mints))
        if not unique:
            return []

        results: list[TokenMarketSnapshot] = []
        batch_size = 500
        for i in range(0, len(unique), batch_size):
            chunk = unique[i : i + batch_size]
            wanted = select(
                func.unnest(literal(chunk, ARRAY(String))).label("mint_address")
            ).subquery("wanted")
            newest = (
                select(TokenMarketSnapshot)
                .where(
                    TokenMarketSnapshot.mint_address == wanted.c.mint_address,
                    # Ingest firewall: flagged prints never answer "latest".
                    TokenMarketSnapshot.suspect.is_not(True),
                    *predicates,
                )
                .order_by(TokenMarketSnapshot.captured_at.desc())
                .limit(1)
                .lateral("newest")
            )
            entity = aliased(TokenMarketSnapshot, newest)
            stmt = select(entity).select_from(wanted).join(newest, true())
            results.extend((await self.session.execute(stmt)).scalars().all())
        return results

    async def latest_for_mints(
        self, mints: Sequence[str], *, since: datetime | None = None
    ) -> dict[str, TokenMarketSnapshot]:
        """Newest snapshot per mint, for a batch, in one query.

        The board renders market data for a whole page of cards, and a query per
        card is what turns one page load into twenty-five round trips. `DISTINCT
        ON` rides the `(mint_address, captured_at DESC)` index for the same
        reason `latest_per_token` uses it.

        A mint with no snapshot is simply absent from the result. That is the
        honest shape: the caller must render "no market data" rather than a
        zero, because a token nobody has priced yet is not a token worth $0.
        """
        unique = list(dict.fromkeys(mints))
        if not unique:
            return {}

        predicates = []
        if since is not None:
            predicates.append(TokenMarketSnapshot.captured_at >= since)
        rows = await self._newest_per_mint(unique, predicates)
        return {row.mint_address: row for row in rows}

    async def price_as_of_for_mints(
        self, mints: Sequence[str], *, as_of: datetime
    ) -> dict[str, Decimal]:
        """Each mint's last observed price at or before `as_of`, batched.

        The platform stores no `price_change_24h` column, and it should not
        start: a stored delta is a second copy of what the history already says
        and drifts the moment a snapshot is corrected or pruned. The change is
        derived at read time from the two readings that actually exist.

        A mint absent from the result had no observation that far back — it is
        newer than the window. The caller must render no change rather than
        0%, because "unchanged" and "we were not watching yet" are different
        claims and only one of them is true.
        """
        unique = list(dict.fromkeys(mints))
        if not unique:
            return {}

        rows = await self._newest_per_mint(
            unique,
            [
                TokenMarketSnapshot.captured_at <= as_of,
                TokenMarketSnapshot.price_usd.is_not(None),
            ],
        )
        return {
            row.mint_address: row.price_usd
            for row in rows
            if row.price_usd is not None and row.price_usd > 0
        }

    async def snapshots_as_of_for_mints(
        self, mints: Sequence[str], *, as_of: datetime
    ) -> dict[str, TokenMarketSnapshot]:
        """Each mint's newest FULL snapshot at or before `as_of`, batched.

        `price_as_of_for_mints` returns prices; this returns the rows, because
        trade-flow features need the buy/sell counters rather than the price.

        A mint absent from the result had no observation that far back. The
        caller must treat that as unmeasured rather than as a zero — the two
        are different claims and only one of them is true.
        """
        unique = list(dict.fromkeys(mints))
        if not unique:
            return {}
        rows = await self._newest_per_mint(
            unique, [TokenMarketSnapshot.captured_at <= as_of]
        )
        return {row.mint_address: row for row in rows}

    async def series_for_mints(
        self, mints: Sequence[str], *, since: datetime
    ) -> dict[str, list[TokenMarketSnapshot]]:
        """Every priced observation after `since`, per mint, **oldest first**.

        Ascending, unlike `window_for_mints`, because the paper wallet replays
        this series in the order it happened: an exit is decided by the *first*
        reading that breached a rule, so reversing it would book the last breach
        instead of the first and quietly improve every result.

        Unbounded per mint by design. A `LIMIT` here would silently drop the
        oldest readings — exactly the ones that decide an exit — and turn a
        missed evaluation window into a better-looking track record.

        `since` is the widest window in the batch; a caller holding a different
        watermark per row trims in memory, as `window_for_mints` documents.
        Rows with no price are excluded: an unpriced observation cannot breach a
        price rule, and treating it as zero would stop out every position.

        **Flagged prints are excluded too**, for the same reason and with more
        force. This is the series a position is EXITED on, so a bad print here
        does not merely mislead a reader — it closes a trade. On 2026-08-25
        ANTFUN printed $0.00000025 against a $0.0418 running high while its
        reported pool depth fell from $38.7M to $7.7M in the same reading: a
        pair switch, not a 166,000x collapse. The ingest firewall caught it and
        marked the row `price_band_low`, `_newest_per_mint` already refused to
        let such a row answer "latest" — and this series handed it straight to
        the exit rule, which stopped the position out. Only the fill-drift cap
        kept the booked result honest.
        """
        unique = list(dict.fromkeys(mints))
        if not unique:
            return {}

        series: dict[str, list[TokenMarketSnapshot]] = {}
        batch_size = 100
        for i in range(0, len(unique), batch_size):
            chunk = unique[i : i + batch_size]
            stmt = (
                select(TokenMarketSnapshot)
                .where(
                    TokenMarketSnapshot.mint_address.in_(chunk),
                    TokenMarketSnapshot.captured_at > since,
                    TokenMarketSnapshot.price_usd.is_not(None),
                    # Ingest firewall: a print the platform distrusts must
                    # never be the reading that closes a position.
                    TokenMarketSnapshot.suspect.is_not(True),
                )
                .order_by(
                    TokenMarketSnapshot.mint_address,
                    TokenMarketSnapshot.captured_at.asc(),
                )
            )
            for snapshot in (await self.session.execute(stmt)).scalars().all():
                series.setdefault(snapshot.mint_address, []).append(snapshot)
                
        return series

    async def history_for_mint(
        self,
        mint_address: str,
        *,
        offset: int = 0,
        limit: int = 50,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[Sequence[TokenMarketSnapshot], int]:
        def _filtered(stmt: Select[Any]) -> Select[Any]:
            stmt = stmt.where(TokenMarketSnapshot.mint_address == mint_address)
            if since is not None:
                stmt = stmt.where(TokenMarketSnapshot.captured_at >= since)
            if until is not None:
                stmt = stmt.where(TokenMarketSnapshot.captured_at <= until)
            return stmt

        rows_stmt = (
            _filtered(select(TokenMarketSnapshot))
            .order_by(TokenMarketSnapshot.captured_at.desc())
            .offset(offset)
            .limit(limit)
        )
        count_stmt = _filtered(select(func.count()).select_from(TokenMarketSnapshot))

        rows = (await self.session.execute(rows_stmt)).scalars().all()
        total = int((await self.session.execute(count_stmt)).scalar_one())
        return rows, total

    async def window_for_mints(
        self,
        mint_addresses: Sequence[str],
        *,
        since: datetime,
        limit_per_mint: int,
    ) -> dict[str, list[TokenMarketSnapshot]]:
        """Up to N recent snapshots for each of several mints, newest first.

        One round trip for a whole scoring batch. `ROW_NUMBER() OVER (PARTITION
        BY mint_address ORDER BY captured_at DESC)` takes the head of each
        token's history in a single pass over
        `ix_snapshots_mint_captured_desc`, where the obvious alternative - a
        query per mint - would be one round trip per token per cycle.

        `since` is the widest window in the batch. Tokens whose own tier implies
        a narrower window are trimmed in memory by the caller, because the
        window is a per-token property and this is a single statement.
        """
        if not mint_addresses:
            return {}

        ranked = (
            select(
                TokenMarketSnapshot,
                func.row_number()
                .over(
                    partition_by=TokenMarketSnapshot.mint_address,
                    order_by=TokenMarketSnapshot.captured_at.desc(),
                )
                .label("rn"),
            )
            .where(
                TokenMarketSnapshot.mint_address.in_(mint_addresses),
                TokenMarketSnapshot.captured_at >= since,
            )
            .subquery("ranked")
        )
        Ranked = aliased(TokenMarketSnapshot, ranked)  # noqa: N806 - an ORM alias is a class

        stmt = (
            select(Ranked)
            .where(ranked.c.rn <= limit_per_mint)
            .order_by(Ranked.mint_address, Ranked.captured_at.desc())
        )

        window: dict[str, list[TokenMarketSnapshot]] = {}
        for snapshot in (await self.session.execute(stmt)).scalars().all():
            window.setdefault(snapshot.mint_address, []).append(snapshot)
        return window

    async def latest_per_token(
        self,
        *,
        offset: int = 0,
        limit: int = 20,
        order_by: str = "volume_24h",
        min_liquidity: float | None = None,
        since: datetime | None = None,
    ) -> tuple[Sequence[tuple[TokenMarketSnapshot, DiscoveredToken]], int]:
        """Latest snapshot per token, joined to the token, ranked for trending.

        `DISTINCT ON (mint_address) ... ORDER BY mint_address, captured_at DESC`
        is the Postgres-native way to take one row per group; it rides the
        `(mint_address, captured_at DESC)` index instead of sorting the whole
        table like a window-function or correlated-subquery formulation would.
        """
        newest = (
            select(TokenMarketSnapshot)
            .distinct(TokenMarketSnapshot.mint_address)
            .where(TokenMarketSnapshot.suspect.is_not(True))
            .order_by(
                TokenMarketSnapshot.mint_address,
                TokenMarketSnapshot.captured_at.desc(),
            )
        )
        if since is not None:
            newest = newest.where(TokenMarketSnapshot.captured_at >= since)

        latest = newest.subquery("latest")
        # Map the subquery back onto the ORM class so callers get real
        # TokenMarketSnapshot instances rather than raw rows.
        Latest = aliased(TokenMarketSnapshot, latest)  # noqa: N806 — an ORM alias is a class

        sortable = {
            "volume_24h": Latest.volume_24h,
            "volume_1h": Latest.volume_1h,
            "volume_5m": Latest.volume_5m,
            "liquidity_usd": Latest.liquidity_usd,
            "market_cap": Latest.market_cap,
            "price_usd": Latest.price_usd,
            "captured_at": Latest.captured_at,
        }
        sort_column = sortable.get(order_by, Latest.volume_24h)

        conditions = []
        if min_liquidity is not None:
            conditions.append(Latest.liquidity_usd >= min_liquidity)
        where = and_(*conditions) if conditions else true()

        rows_stmt = (
            select(Latest, DiscoveredToken)
            .join(DiscoveredToken, DiscoveredToken.id == Latest.token_id)
            .where(where)
            # NULLS LAST: a token with no recorded volume must not outrank one
            # that has volume, and NULL sorts first in Postgres DESC ordering.
            .order_by(sort_column.desc().nullslast(), Latest.mint_address)
            .offset(offset)
            .limit(limit)
        )
        count_stmt = select(func.count()).select_from(latest).where(where)

        rows = (await self.session.execute(rows_stmt)).all()
        total = int((await self.session.execute(count_stmt)).scalar_one())
        return [(row[0], row[1]) for row in rows], total

    async def count_for_mint(self, mint_address: str) -> int:
        stmt = (
            select(func.count())
            .select_from(TokenMarketSnapshot)
            .where(TokenMarketSnapshot.mint_address == mint_address)
        )
        return int((await self.session.execute(stmt)).scalar_one())


class EnrichmentStateRepository(BaseRepository[TokenEnrichmentState]):
    model = TokenEnrichmentState

    async def get_by_mint(self, mint_address: str) -> TokenEnrichmentState | None:
        stmt = select(TokenEnrichmentState).where(
            TokenEnrichmentState.mint_address == mint_address
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def get_many_by_mints(self, mints: Sequence[str]) -> dict[str, TokenEnrichmentState]:
        if not mints:
            return {}
        unique = list(set(mints))
        results: dict[str, TokenEnrichmentState] = {}
        batch_size = 500
        for i in range(0, len(unique), batch_size):
            chunk = unique[i : i + batch_size]
            stmt = select(TokenEnrichmentState).where(TokenEnrichmentState.mint_address.in_(chunk))
            for row in (await self.session.execute(stmt)).scalars().all():
                results[row.mint_address] = row
        return results

    async def ensure_state(
        self,
        *,
        token_id: uuid.UUID,
        mint_address: str,
        next_refresh_at: datetime,
        priority: int = 0,
    ) -> TokenEnrichmentState | None:
        """Create the scheduling row for a token if it has none.

        `ON CONFLICT DO NOTHING` so the discovery listener and the backfill
        sweep can both call it without racing.
        """
        stmt = (
            pg_insert(TokenEnrichmentState)
            .values(
                token_id=token_id,
                mint_address=mint_address,
                next_refresh_at=next_refresh_at,
                status=EnrichmentStatus.ACTIVE,
                priority=priority,
            )
            .on_conflict_do_nothing()  # any arbiter: the row exists under EITHER
            # unique constraint (mint_address OR token_id). Naming only the
            # mint index let the token_id constraint fire first in production
            # — 2,073 spurious enrichment_discovery_failed warnings by V4.
            .returning(TokenEnrichmentState)
        )
        row = (await self.session.execute(stmt)).scalars().first()
        if row is not None:
            await self.session.flush()
        return row

    async def backfill_missing(self, *, limit: int = 500) -> int:
        """Create state rows for tokens discovered before enrichment existed."""
        missing = (
            select(DiscoveredToken.id, DiscoveredToken.mint_address)
            .outerjoin(
                TokenEnrichmentState,
                TokenEnrichmentState.token_id == DiscoveredToken.id,
            )
            .where(TokenEnrichmentState.id.is_(None))
            .limit(limit)
        )
        rows = (await self.session.execute(missing)).all()
        if not rows:
            return 0

        await self.session.execute(
            pg_insert(TokenEnrichmentState)
            .values(
                [
                    {
                        "token_id": token_id,
                        "mint_address": mint_address,
                        "status": EnrichmentStatus.ACTIVE,
                    }
                    for token_id, mint_address in rows
                ]
            )
            .on_conflict_do_nothing()  # any arbiter: the row exists under EITHER
            # unique constraint (mint_address OR token_id). Naming only the
            # mint index let the token_id constraint fire first in production
            # — 2,073 spurious enrichment_discovery_failed warnings by V4.
        )
        return len(rows)

    async def prioritize_unquoted_track_record_candidates(self, *, now: datetime) -> int:
        """Promptly seek the first quote after a Generation 6 Track Record admission.

        `LANE_TRACK_RECORD` is above the derived Radar/display lane, but only
        applies to a canonical admission with no usable post-admission quote.
        It is cleared after each provider attempt.  Raw scanner rows are
        deliberately absent from this query.
        """
        wallet = await self.session.scalar(
            select(PaperWallet).where(PaperWallet.archived_at.is_(None))
        )
        if wallet is None or wallet.strategy_id != "paper_track_record_tp125_sl50_v1":
            return 0
        post_admission_quote = (
            select(TokenMarketSnapshot.id)
            .where(
                TokenMarketSnapshot.token_id == TokenEnrichmentState.token_id,
                TokenMarketSnapshot.price_usd.is_not(None),
                TokenMarketSnapshot.price_usd > 0,
                TokenMarketSnapshot.captured_at >= RadarToken.first_detected_at,
            )
            .exists()
        )
        result = await self.session.execute(
            update(TokenEnrichmentState)
            .where(
                TokenEnrichmentState.token_id == RadarToken.token_id,
                RadarToken.first_detected_at > wallet.started_at,
                TokenEnrichmentState.status == EnrichmentStatus.ACTIVE,
                TokenEnrichmentState.priority < LANE_TRACK_RECORD,
                ~post_admission_quote,
            )
            .values(
                priority=LANE_TRACK_RECORD,
                next_refresh_at=func.least(TokenEnrichmentState.next_refresh_at, now),
            )
        )
        return int(result.rowcount or 0)

    async def claim_due(
        self,
        *,
        now: datetime,
        limit: int,
        lease_seconds: int = 120,
        min_priority: int | None = None,
    ) -> Sequence[TokenEnrichmentState]:
        """Atomically claim tokens that are due for refresh.

        `FOR UPDATE SKIP LOCKED` inside a CTE is what makes this safe to run
        from multiple worker replicas: each claims a disjoint set instead of
        every worker fetching the same head of the queue. Claimed rows are
        pushed forward by `lease_seconds` so a worker that dies mid-batch
        releases its tokens automatically rather than stranding them.

        **Ordered by lane, then by due time.** Sprint 28: the backlog reached
        36,154 active tokens, so a Radar token asking for a 15-second refresh
        sorted behind 36,000 rows that were hours overdue and waited a measured
        p95 of 106 minutes. One lane column and one ORDER BY term fix that
        without a second queue, a second worker or a second scheduler.

        Within a lane the order is unchanged — oldest due first — so the
        ordinary population still cannot starve its own tail.
        """
        lane_filter = (
            [TokenEnrichmentState.priority >= min_priority]
            if min_priority is not None
            else []
        )
        due = (
            select(TokenEnrichmentState.id)
            .where(
                TokenEnrichmentState.status == EnrichmentStatus.ACTIVE,
                TokenEnrichmentState.next_refresh_at <= now,
                *lane_filter,
            )
            .order_by(
                TokenEnrichmentState.priority.desc(),
                TokenEnrichmentState.next_refresh_at.asc(),
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )

        claimed = (
            update(TokenEnrichmentState)
            .where(TokenEnrichmentState.id.in_(due))
            .values(
                last_attempt_at=now,
                next_refresh_at=now + timedelta(seconds=lease_seconds),
            )
            .returning(TokenEnrichmentState)
        )
        return (await self.session.execute(claimed)).scalars().all()

    async def record_result(
        self,
        state: TokenEnrichmentState,
        *,
        now: datetime,
        next_refresh_at: datetime,
        tier: str,
        succeeded: bool,
        had_data: bool,
        error: str | None = None,
        dead_letter: bool = False,
    ) -> TokenEnrichmentState:
        state.total_refreshes += 1
        # Track Record quote priority is for acquisition only.  A real quote,
        # an empty response, or a provider failure has now been observed, so
        # leave the bounded lane for ordinary scheduling.
        if state.priority >= LANE_TRACK_RECORD:
            state.priority = LANE_NORMAL
        state.next_refresh_at = next_refresh_at
        state.tier = tier
        state.last_attempt_at = now

        if succeeded:
            state.last_success_at = now
            state.consecutive_failures = 0
            state.last_error = None
            if had_data:
                state.total_snapshots += 1
                state.consecutive_empty = 0
            else:
                state.consecutive_empty += 1
        else:
            state.consecutive_failures += 1
            state.last_error = (error or "")[:500] or None

        if dead_letter:
            state.status = EnrichmentStatus.DEAD_LETTER

        await self.session.flush()
        return state

    async def defer_batch(
        self, state_ids: Sequence[uuid.UUID], *, next_refresh_at: datetime
    ) -> int:
        """Move a batch's next refresh out, and touch nothing else.

        Used when the provider was unavailable and **no call was made on any
        token's behalf**. The deliberate omissions are the point: no
        `consecutive_failures`, no `last_attempt_at`, no `total_refreshes`, no
        dead-letter. A token cannot be judged by a request that never left the
        process — that conflation dead-lettered 163 tokens on 2026-08-05.

        One statement for the batch rather than a row at a time: this runs on
        the failure path, which is exactly when the database is least likely to
        want N round trips.
        """
        if not state_ids:
            return 0
        result = cast(
            "CursorResult[Any]",
            await self.session.execute(
                update(TokenEnrichmentState)
                .where(TokenEnrichmentState.id.in_(list(state_ids)))
                .values(next_refresh_at=next_refresh_at)
            ),
        )
        return int(result.rowcount or 0)

    async def counts_by_status(self) -> dict[str, int]:
        stmt = select(TokenEnrichmentState.status, func.count()).group_by(
            TokenEnrichmentState.status
        )
        return {
            str(status): int(count) for status, count in (await self.session.execute(stmt))
        }

    async def requeue_dead_letters(
        self, *, now: datetime, limit: int = 100, idle_for: timedelta | None = None
    ) -> int:
        """Return dead-lettered tokens to the active queue.

        Was an operator action with no caller, which meant dead-lettering was
        terminal in practice: a token removed by one bad minute never came back.
        `app.workers.enrichment_tasks.requeue_dead_letters` now runs it on a
        beat, so the state is a **quarantine rather than a grave**.

        `idle_for` keeps that from becoming a retry loop. A token is only
        readmitted once it has sat dead-lettered for that long, so a genuinely
        broken mint costs one wasted call per interval instead of one per pass.
        Ordered oldest-attempt-first so the queue drains fairly under `limit`.
        """
        conditions = [TokenEnrichmentState.status == EnrichmentStatus.DEAD_LETTER]
        if idle_for is not None:
            conditions.append(TokenEnrichmentState.last_attempt_at <= now - idle_for)

        ids = (
            select(TokenEnrichmentState.id)
            .where(*conditions)
            .order_by(TokenEnrichmentState.last_attempt_at.asc())
            .limit(limit)
            .scalar_subquery()
        )
        result = cast(
            "CursorResult[Any]",
            await self.session.execute(
                update(TokenEnrichmentState)
                .where(TokenEnrichmentState.id.in_(ids))
                .values(
                    status=EnrichmentStatus.ACTIVE,
                    consecutive_failures=0,
                    next_refresh_at=now,
                    last_error=None,
                )
            ),
        )
        return int(result.rowcount or 0)
