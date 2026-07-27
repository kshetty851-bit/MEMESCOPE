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
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

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

    async def mints_without_scores(self, *, limit: int = 500) -> Sequence[str]:
        """Tokens that have market snapshots but no score row yet.

        The sweep's first arm: it closes the window between the enrichment
        commit and the scoring commit, plus anything missed across a restart.

        Tokens with no snapshot are excluded - there is nothing to score yet,
        and returning them would make the sweep re-examine every unindexed mint
        on every pass.
        """
        has_snapshot = (
            select(TokenMarketSnapshot.id)
            .where(TokenMarketSnapshot.token_id == DiscoveredToken.id)
            .exists()
        )
        stmt = (
            select(DiscoveredToken.mint_address)
            .outerjoin(TokenScore, TokenScore.token_id == DiscoveredToken.id)
            .where(TokenScore.id.is_(None), has_snapshot)
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
