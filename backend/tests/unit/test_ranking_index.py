"""The ranking index must match the query `/scores/top` actually issues.

`ix_token_scores_ranking` led with `model_version`, but the endpoint sends an
equality on that column only when a caller passes `?model_version=` — which
nothing does by default. Postgres could not use it for ordering, so a 20-row
page seq-scanned `token_scores`, hash-joined `discovered_tokens` and top-N
sorted 20,225 rows: 1,804 buffers to return 20 (MEMESCOPE_AUDIT.md §6).

An `EXPLAIN` assertion would be the direct test, but Postgres correctly prefers
a sequential scan on a table with a handful of test rows, so it would assert the
opposite of production behaviour. These pin the index *shape* instead — which is
what was wrong — and the ordering contract is covered behaviourally in
`tests/integration/test_scores_api.py`.
"""

from __future__ import annotations

import pytest

from app.models.score import TokenScore
from app.repositories.score import ScoreRepository

pytestmark = pytest.mark.unit


def _index(name: str):
    for index in TokenScore.__table__.indexes:
        if index.name == name:
            return index
    return None


class TestDefaultRankingIndex:
    def test_it_exists(self) -> None:
        assert _index("ix_token_scores_ranking_default") is not None

    def test_it_leads_with_the_sort_key(self) -> None:
        """The whole defect: a leading column the query does not constrain.

        Postgres can only walk a btree in index order if every column before
        the sort key is pinned by an equality. `model_version` was not, so the
        index was unusable for ordering no matter how well it matched
        otherwise.
        """
        index = _index("ix_token_scores_ranking_default")
        assert index is not None
        leading = str(next(iter(index.expressions)))

        assert "score" in leading, f"leading expression is {leading!r}, expected score"
        assert "model_version" not in leading

    def test_it_sorts_descending(self) -> None:
        """`/scores/top` means highest first; an ascending index cannot serve it
        without a backward scan the planner will not choose here."""
        index = _index("ix_token_scores_ranking_default")
        assert index is not None
        assert "DESC" in str(next(iter(index.expressions))).upper()

    def test_it_carries_the_tiebreak_column(self) -> None:
        """`mint_address` breaks ties in the query's ORDER BY.

        Without it in the index the planner still has to sort, which is the
        cost this index exists to remove.
        """
        index = _index("ix_token_scores_ranking_default")
        assert index is not None
        assert any("mint_address" in str(expr) for expr in index.expressions)

    def test_its_partial_predicate_is_one_the_default_query_carries(self) -> None:
        """A partial index is only usable when the query implies its predicate.

        `has_veto = false` is applied on every request that does not pass
        `include_vetoed`, so it always holds. The replaced index also required
        `evidence >= 25`, which no request implies — `min_confidence` is
        optional and unset by default — making it unusable by construction.
        """
        index = _index("ix_token_scores_ranking_default")
        assert index is not None
        predicate = str(index.dialect_options["postgresql"]["where"])

        assert "has_veto" in predicate
        assert "evidence" not in predicate, (
            "An evidence floor in the predicate is what made the previous index "
            "unusable: no default request constrains evidence."
        )


class TestReplacedIndexIsGone:
    def test_the_unusable_partial_index_is_not_redeclared(self) -> None:
        assert _index("ix_token_scores_ranking_hot") is None


class TestModelVersionIndexIsRetained:
    def test_it_still_exists(self) -> None:
        """Zero recorded scans, deliberately kept.

        It serves `?model_version=`, a supported filter, and the drain a model
        promotion runs. "Nobody has passed the parameter" is not the same claim
        as "no query can use this", which is what justified the two drops.
        """
        assert _index("ix_token_scores_ranking") is not None


class TestPredicateFormMatchesTheEmittedSql:
    def test_the_index_predicate_uses_the_same_operator_the_orm_emits(self) -> None:
        """`IS false` and `= false` are not interchangeable to the planner.

        SQLAlchemy compiles `has_veto.is_(False)` to `has_veto IS false`.
        Postgres will not prove that implies `has_veto = false`, so an index
        written with `=` is never used — the query plan silently stays a
        sequential scan and nothing anywhere reports a problem.

        This was measured, not assumed: the first version of this index used
        `= false`, and `EXPLAIN` on the ORM's own SQL still showed a seq scan
        while a hand-written equivalent used the index. Testing the hand-written
        form would have passed and shipped the bug.
        """
        from sqlalchemy.dialects import postgresql

        index = _index("ix_token_scores_ranking_default")
        assert index is not None
        predicate = str(index.dialect_options["postgresql"]["where"])

        emitted = str(
            ScoreRepository(None)  # type: ignore[arg-type]
            ._ranking_filters(
                min_score=None,
                min_evidence=None,
                max_risk=None,
                grade=None,
                model_version=None,
                trigger=None,
                elite_only=False,
                include_vetoed=False,
            )[0]
            .compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
        )

        # "token_scores.has_veto IS false" must contain the index's predicate
        # verbatim, operator included.
        assert predicate in emitted, (
            f"index predicate {predicate!r} does not appear in the emitted SQL "
            f"{emitted!r}; the planner will not use the index"
        )


class TestDefaultFiltersMatchTheIndex:
    def test_the_default_ranking_filters_are_exactly_the_partial_predicate(
        self,
    ) -> None:
        """Guards the pairing from either side drifting.

        If a future default adds a filter, or `include_vetoed` flips, this
        catches it — otherwise the index silently stops being used and the only
        symptom is a slow endpoint nobody attributes to a default change.
        """
        conditions = ScoreRepository(None)._ranking_filters(  # type: ignore[arg-type]
            min_score=None,
            min_evidence=None,
            max_risk=None,
            grade=None,
            model_version=None,
            trigger=None,
            elite_only=False,
            include_vetoed=False,
        )

        assert len(conditions) == 1
        assert "has_veto" in str(conditions[0])
