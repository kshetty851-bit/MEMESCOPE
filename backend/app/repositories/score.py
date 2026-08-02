"""Score persistence.

Database access only - no scoring logic, no weighting, no materiality decisions.
The caller computes values and passes them in, exactly as the enrichment worker
does for snapshots.

Two rules are enforced *here* rather than in the service, because they are
correctness properties of the storage layer and no caller should be able to
opt out of them:

  * A stale evaluation can never overwrite a fresher one (`upsert_many`).
  * History is append-only; nothing in this module updates a history row.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import (
    CursorResult,
    Row,
    Select,
    and_,
    delete,
    func,
    or_,
    select,
    true,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased

from app.models.market import TokenMarketSnapshot
from app.models.score import TokenScore, TokenScoreHistory
from app.models.token import DiscoveredToken
from app.repositories.base import BaseRepository

# Everything except the identity columns and `created_at`. Listed explicitly
# rather than derived from the mapper so that adding a column is a deliberate
# decision about whether a re-evaluation should overwrite it.
_UPSERT_UPDATABLE: tuple[str, ...] = (
    "model_version",
    "score",
    "evidence",
    "coverage",
    "market_risk",
    "opportunity_raw",
    "observations",
    "grade",
    "is_elite",
    "has_veto",
    "latest_snapshot_at",
    "evaluated_at",
    "source_snapshot_captured_at",
)


class ScoreRepository(BaseRepository[TokenScore]):
    """Current-score state. One row per token, upserted on every evaluation."""

    model = TokenScore

    async def get_by_mint(self, mint_address: str) -> TokenScore | None:
        stmt = select(TokenScore).where(TokenScore.mint_address == mint_address)
        return (await self.session.execute(stmt)).scalars().first()

    async def get_many_by_mints(self, mint_addresses: Sequence[str]) -> dict[str, TokenScore]:
        """Batch lookup keyed by mint. One query for a whole scoring batch."""
        if not mint_addresses:
            return {}
        stmt = select(TokenScore).where(TokenScore.mint_address.in_(mint_addresses))
        rows = (await self.session.execute(stmt)).scalars().all()
        return {row.mint_address: row for row in rows}

    async def upsert_many(self, rows: Sequence[dict[str, Any]]) -> list[str]:
        """Insert or update current scores, newest evaluation wins.

        Three writers touch this table - inline scoring in the enrichment cycle,
        the staleness sweep, and rescore jobs - and only the first is serialised
        by the enrichment claim. Without a guard, a rescore reading at T1 could
        land after a live evaluation at T2 and silently reinstate the older
        score. The `WHERE` on the conflict target makes that impossible in SQL,
        so no caller has to remember it:

            ON CONFLICT (token_id) DO UPDATE SET ...
            WHERE EXCLUDED.evaluated_at > token_scores.evaluated_at
               OR EXCLUDED.model_version <> token_scores.model_version

        The `model_version` arm is the one case where an "older" write is
        intended: promoting a new model deliberately replaces rows regardless of
        timestamp ordering.

        Returns the mints actually written. Rows rejected by the guard are
        absent - that is a normal outcome, not an error.
        """
        deduped = self._latest_per_token(rows)
        if not deduped:
            return []

        stmt = pg_insert(TokenScore).values(deduped)
        assignments: dict[str, Any] = {
            column: stmt.excluded[column] for column in _UPSERT_UPDATABLE
        }
        # `onupdate=func.now()` only fires for ORM/Core UPDATE constructs, not
        # for the SET clause of an ON CONFLICT, so it is applied by hand.
        assignments["updated_at"] = func.now()

        guarded = stmt.on_conflict_do_update(
            index_elements=[TokenScore.token_id],
            set_=assignments,
            where=or_(
                stmt.excluded.evaluated_at > TokenScore.evaluated_at,
                stmt.excluded.model_version != TokenScore.model_version,
            ),
        ).returning(TokenScore.mint_address)

        return list((await self.session.execute(guarded)).scalars().all())

    @staticmethod
    def _latest_per_token(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        """Collapse a batch to one row per token, keeping the newest evaluation.

        Postgres raises `ON CONFLICT DO UPDATE command cannot affect row a
        second time` when a single statement carries the same conflict key
        twice. A batch can legitimately contain a duplicate - a token claimed by
        the sweep and re-enqueued mid-cycle, say - so the collapse happens here
        rather than being a landmine every caller must step around.
        """
        newest: dict[uuid.UUID, dict[str, Any]] = {}
        for row in rows:
            token_id = row["token_id"]
            existing = newest.get(token_id)
            if existing is None or row["evaluated_at"] >= existing["evaluated_at"]:
                newest[token_id] = row
        return list(newest.values())

    async def mints_without_scores(
        self, *, since: datetime, limit: int = 500
    ) -> Sequence[str]:
        """Tokens with a *scorable* snapshot window but no score row yet.

        The sweep's first arm: it closes the window between the enrichment
        commit and the scoring commit, plus anything missed across a restart.

        `since` is the oldest snapshot the engine could still build a window
        from. The caller supplies it because the window is tier-relative and
        tiers are a scheduling concern, not a persistence one - the same
        division of labour as `stale_before`.

        **Why the cutoff exists.** This asked only for *any* snapshot, which is
        not the condition the engine actually scores on: it needs an
        observation inside the token's history window. A token last enriched a
        week ago satisfied the old predicate, was selected, produced an empty
        window, and was skipped as unscorable - then selected again on the next
        pass, forever. With `LIMIT` and no `ORDER BY`, Postgres returned the
        same rows from the same heap positions every time, so 2,880 permanently
        unscorable tokens held the head of the queue and consumed the entire
        200-row budget on every cycle. The sweep ran every 15 minutes for days
        and scored nothing (MEMESCOPE_AUDIT.md §3.5).

        **Why the ordering is by latest snapshot.** Any total order would make
        the query deterministic, but a *static* one would re-select the same
        head whenever that head is unscorable for some reason this predicate
        does not capture - the same starvation with a different cause. Ordering
        by the freshest observation makes the head rotate on its own: every
        enrichment write reorders the queue, so a token that cannot be scored
        drifts down it as others are refreshed. `mint_address` breaks ties, so
        the order is total and two identical calls return identical pages.

        Newest-first is also the right priority on its own terms - the token
        whose data just landed is the one a score is most useful for.
        """
        latest = (
            select(func.max(TokenMarketSnapshot.captured_at).label("latest"))
            .where(
                TokenMarketSnapshot.token_id == DiscoveredToken.id,
                TokenMarketSnapshot.captured_at >= since,
            )
            .lateral("latest_snapshot")
        )
        stmt = (
            select(DiscoveredToken.mint_address)
            .outerjoin(TokenScore, TokenScore.token_id == DiscoveredToken.id)
            # An inner lateral join: a token with no snapshot inside the window
            # produces a NULL aggregate and is dropped, which is exactly the
            # `EXISTS` this replaces - but it also yields the sort key, so the
            # ordering costs no second pass over the snapshot table.
            .join(latest, latest.c.latest.is_not(None))
            .where(TokenScore.id.is_(None))
            .order_by(latest.c.latest.desc(), DiscoveredToken.mint_address.asc())
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def stale_before(
        self, *, cutoff: datetime, limit: int = 500
    ) -> Sequence[TokenScore]:
        """Scores not re-evaluated since `cutoff`.

        The caller supplies the cutoff because staleness is tier-relative and
        tiers are a scheduling concern, not a persistence one - the same
        division of labour as `EnrichmentStateRepository.claim_due`, which takes
        `now` rather than reading the clock itself.
        """
        stmt = (
            select(TokenScore)
            .where(TokenScore.evaluated_at < cutoff)
            .order_by(TokenScore.evaluated_at.asc())
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def with_token(self, mint_address: str) -> Row[Any] | None:
        """Current score joined to the token identity a response needs.

        One query rather than two: the read path needs the token's name and its
        age (for read-time freshness) alongside the score, and fetching them
        separately would be a round trip per request for data on the same row's
        foreign key.
        """
        stmt = (
            select(
                TokenScore,
                DiscoveredToken.name,
                DiscoveredToken.symbol,
                DiscoveredToken.block_time,
                DiscoveredToken.discovered_at,
            )
            .join(DiscoveredToken, DiscoveredToken.id == TokenScore.token_id)
            .where(TokenScore.mint_address == mint_address)
        )
        return (await self.session.execute(stmt)).first()

    def _ranking_filters(
        self,
        *,
        min_score: Decimal | None,
        min_evidence: Decimal | None,
        max_risk: Decimal | None,
        grade: str | None,
        model_version: str | None,
        trigger: str | None,
        elite_only: bool,
        include_vetoed: bool,
    ) -> list[Any]:
        """Every filter as a SQL predicate. Nothing is filtered in Python.

        Applied identically to the page query and its count, so `total` always
        describes the same set the page was drawn from.
        """
        conditions: list[Any] = []
        if min_score is not None:
            conditions.append(TokenScore.score >= min_score)
        if min_evidence is not None:
            conditions.append(TokenScore.evidence >= min_evidence)
        if max_risk is not None:
            conditions.append(TokenScore.market_risk <= max_risk)
        if grade is not None:
            conditions.append(TokenScore.grade == grade)
        if model_version is not None:
            conditions.append(TokenScore.model_version == model_version)
        if elite_only:
            conditions.append(TokenScore.is_elite.is_(True))
        if not include_vetoed:
            conditions.append(TokenScore.has_veto.is_(False))
        if trigger is not None:
            # `trigger` lives on history, not on the current score, so this asks
            # "what earned this token its most recent history row?". A
            # correlated scalar subquery rides
            # `ix_score_history_mint_evaluated` and is only ever built when the
            # filter is supplied, so the common ranking stays a plain scan.
            latest_trigger = (
                select(TokenScoreHistory.trigger)
                .where(TokenScoreHistory.mint_address == TokenScore.mint_address)
                .order_by(TokenScoreHistory.evaluated_at.desc())
                .limit(1)
                .scalar_subquery()
            )
            conditions.append(latest_trigger == trigger)
        return conditions

    async def ranked_page(
        self,
        *,
        offset: int = 0,
        limit: int = 20,
        sort_by: str = "score",
        order: str = "desc",
        min_score: Decimal | None = None,
        min_evidence: Decimal | None = None,
        max_risk: Decimal | None = None,
        grade: str | None = None,
        model_version: str | None = None,
        trigger: str | None = None,
        elite_only: bool = False,
        include_vetoed: bool = False,
    ) -> tuple[Sequence[Row[Any]], int, int]:
        """A ranked page of scores, filtered and sorted in the database.

        Returns `(rows, matched_total, candidate_total)`. The candidate count is
        the unfiltered population, so a caller can tell an empty page caused by
        a strict filter from one caused by an empty table.
        """
        sortable = {
            "score": TokenScore.score,
            "evidence": TokenScore.evidence,
            "market_risk": TokenScore.market_risk,
            "opportunity_raw": TokenScore.opportunity_raw,
            "evaluated_at": TokenScore.evaluated_at,
        }
        column = sortable.get(sort_by, TokenScore.score)
        direction = column.asc() if order == "asc" else column.desc()

        conditions = self._ranking_filters(
            min_score=min_score,
            min_evidence=min_evidence,
            max_risk=max_risk,
            grade=grade,
            model_version=model_version,
            trigger=trigger,
            elite_only=elite_only,
            include_vetoed=include_vetoed,
        )
        where = and_(*conditions) if conditions else true()

        rows_stmt = (
            select(
                TokenScore,
                DiscoveredToken.name,
                DiscoveredToken.symbol,
                DiscoveredToken.block_time,
                DiscoveredToken.discovered_at,
            )
            .join(DiscoveredToken, DiscoveredToken.id == TokenScore.token_id)
            .where(where)
            # `mint_address` breaks ties so the ordering is total. Without it two
            # tokens on the same score could swap places between page requests
            # and appear twice, or not at all.
            .order_by(direction, TokenScore.mint_address.asc())
            .offset(offset)
            .limit(limit)
        )
        matched_stmt = select(func.count()).select_from(TokenScore).where(where)
        candidate_stmt = select(func.count()).select_from(TokenScore)

        rows = (await self.session.execute(rows_stmt)).all()
        matched = int((await self.session.execute(matched_stmt)).scalar_one())
        candidates = int((await self.session.execute(candidate_stmt)).scalar_one())
        return rows, matched, candidates

    async def outdated_model_mints(
        self, *, model_version: str, limit: int = 500
    ) -> Sequence[str]:
        """Scores computed by a model version other than the active one.

        Scores from different versions are not comparable, so a mixed table
        makes every ranking meaningless. This is what lets a promotion drain the
        backlog incrementally instead of needing one enormous migration.
        """
        stmt = (
            select(TokenScore.mint_address)
            .where(TokenScore.model_version != model_version)
            .order_by(TokenScore.evaluated_at.asc())
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def scored_mints_page(
        self, *, after_mint: str | None = None, limit: int = 500
    ) -> Sequence[str]:
        """A stable page of scored mints, for resumable full rescores.

        Keyset on `mint_address` rather than offset: a rescore walks the whole
        table while the table is being written to, and offsets shift under
        exactly that condition.
        """
        stmt = select(TokenScore.mint_address).order_by(TokenScore.mint_address.asc())
        if after_mint is not None:
            stmt = stmt.where(TokenScore.mint_address > after_mint)
        return (await self.session.execute(stmt.limit(limit))).scalars().all()

    async def counts_by_grade(self) -> dict[str, int]:
        """Grade distribution. Operational visibility on score calibration."""
        stmt = select(TokenScore.grade, func.count()).group_by(TokenScore.grade)
        return {str(grade): int(count) for grade, count in (await self.session.execute(stmt))}


class ScoreHistoryRepository(BaseRepository[TokenScoreHistory]):
    """Append-only score history. Nothing here ever updates a row."""

    model = TokenScoreHistory

    async def add_many(self, rows: Sequence[dict[str, Any]]) -> int:
        """Bulk insert. One round trip for a whole batch's material changes."""
        if not rows:
            return 0
        await self.session.execute(pg_insert(TokenScoreHistory).values(list(rows)))
        return len(rows)

    async def latest_for_mint(self, mint_address: str) -> TokenScoreHistory | None:
        stmt = (
            select(TokenScoreHistory)
            .where(TokenScoreHistory.mint_address == mint_address)
            .order_by(TokenScoreHistory.evaluated_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def latest_for_mints(
        self, mint_addresses: Sequence[str]
    ) -> dict[str, TokenScoreHistory]:
        """Most recent history row per mint, in one query.

        Materiality is decided against the previous history row, so a scoring
        batch needs this for every token it is about to evaluate. `DISTINCT ON`
        rides the `(mint_address, evaluated_at DESC)` index instead of sorting
        the whole table, matching how the latest market snapshot is resolved.
        """
        if not mint_addresses:
            return {}
        stmt = (
            select(TokenScoreHistory)
            .where(TokenScoreHistory.mint_address.in_(mint_addresses))
            .distinct(TokenScoreHistory.mint_address)
            .order_by(
                TokenScoreHistory.mint_address,
                TokenScoreHistory.evaluated_at.desc(),
            )
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return {row.mint_address: row for row in rows}

    async def recent_for_mints(
        self, mint_addresses: Sequence[str], *, limit_per_mint: int = 5
    ) -> dict[str, list[TokenScoreHistory]]:
        """The last N history rows for each of several mints, newest first.

        Serves two callers at once, which is why it is batched rather than N
        calls to `recent_for_mint`: materiality compares against the newest row,
        and the Elite streak is replayed from the run of rows below it.
        """
        if not mint_addresses:
            return {}

        ranked = (
            select(
                TokenScoreHistory,
                func.row_number()
                .over(
                    partition_by=TokenScoreHistory.mint_address,
                    order_by=TokenScoreHistory.evaluated_at.desc(),
                )
                .label("rn"),
            )
            .where(TokenScoreHistory.mint_address.in_(mint_addresses))
            .subquery("ranked_history")
        )
        Ranked = aliased(TokenScoreHistory, ranked)  # noqa: N806 - an ORM alias is a class

        stmt = (
            select(Ranked)
            .where(ranked.c.rn <= limit_per_mint)
            .order_by(Ranked.mint_address, Ranked.evaluated_at.desc())
        )

        rows: dict[str, list[TokenScoreHistory]] = {}
        for row in (await self.session.execute(stmt)).scalars().all():
            rows.setdefault(row.mint_address, []).append(row)
        return rows

    async def prune_before(self, *, cutoff: datetime, keep_per_hour: int = 1) -> int:
        """Thin history older than `cutoff` down to `keep_per_hour` rows an hour.

        Deletes rather than aggregates, and the retained row is the newest in
        each hour bucket. Irreversible by nature, which is why the retention
        window is configuration rather than a constant.
        """
        bucket = func.date_trunc("hour", TokenScoreHistory.evaluated_at)
        ranked = (
            select(
                TokenScoreHistory.id,
                func.row_number()
                .over(
                    partition_by=(TokenScoreHistory.mint_address, bucket),
                    order_by=TokenScoreHistory.evaluated_at.desc(),
                )
                .label("rn"),
            )
            .where(TokenScoreHistory.evaluated_at < cutoff)
            .subquery("prunable")
        )
        doomed = select(ranked.c.id).where(ranked.c.rn > keep_per_hour).scalar_subquery()

        result = cast(
            "CursorResult[Any]",
            await self.session.execute(
                delete(TokenScoreHistory).where(TokenScoreHistory.id.in_(doomed))
            ),
        )
        return int(result.rowcount or 0)

    async def recent_for_mint(
        self, mint_address: str, *, limit: int = 5
    ) -> Sequence[TokenScoreHistory]:
        """The last N rows, newest first.

        Backs the Elite streak, which is derived by replaying rows rather than
        read from a mutable counter.
        """
        stmt = (
            select(TokenScoreHistory)
            .where(TokenScoreHistory.mint_address == mint_address)
            .order_by(TokenScoreHistory.evaluated_at.desc())
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def history_for_mint(
        self,
        mint_address: str,
        *,
        offset: int = 0,
        limit: int = 50,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[Sequence[TokenScoreHistory], int]:
        """Paginated history, newest first.

        Offset pagination is correct here and nowhere else in the scoring API:
        this table is append-only, so a page boundary cannot shift under a
        reader the way a live ranking can.
        """

        def _filtered(stmt: Select[Any]) -> Select[Any]:
            stmt = stmt.where(TokenScoreHistory.mint_address == mint_address)
            if since is not None:
                stmt = stmt.where(TokenScoreHistory.evaluated_at >= since)
            if until is not None:
                stmt = stmt.where(TokenScoreHistory.evaluated_at <= until)
            return stmt

        rows_stmt = (
            _filtered(select(TokenScoreHistory))
            .order_by(TokenScoreHistory.evaluated_at.desc())
            .offset(offset)
            .limit(limit)
        )
        count_stmt = _filtered(select(func.count()).select_from(TokenScoreHistory))

        rows = (await self.session.execute(rows_stmt)).scalars().all()
        total = int((await self.session.execute(count_stmt)).scalar_one())
        return rows, total

    async def count_for_mint(self, mint_address: str) -> int:
        stmt = (
            select(func.count())
            .select_from(TokenScoreHistory)
            .where(TokenScoreHistory.mint_address == mint_address)
        )
        return int((await self.session.execute(stmt)).scalar_one())
