"""The operator-invoked maintenance command.

Its most important property is negative: nothing schedules it. `VACUUM` on
`token_score_history` rewrites 1.8 GB, and a background job that decides on its
own to do that during a launch burst is a worse outage than the drift it fixes.
"""

from __future__ import annotations

import pytest

from app.db import maintenance

pytestmark = pytest.mark.integration


class TestNeverAutomatic:
    def test_no_celery_task_calls_maintenance(self) -> None:
        """The requirement, asserted rather than promised in prose.

        Catches a future 'this should really run nightly' commit, which is
        exactly how a 2.5 GB rewrite ends up in a beat schedule.
        """
        from app.workers.celery_app import celery_app

        scheduled = {entry["task"] for entry in celery_app.conf.beat_schedule.values()}

        assert not any("maintenance" in task for task in scheduled)

    def test_the_module_registers_no_celery_task(self) -> None:
        source = maintenance.__file__ or ""
        assert source.endswith("maintenance.py")
        with open(source) as handle:
            text = handle.read()
        assert "celery_app.task" not in text
        assert "@shared_task" not in text


async def _seed_token_scores(rows: int = 5) -> None:
    """The maintenance contract is about an ANALYZEd table with rows in it —
    an empty scratch database was exercising a different (vacuous) question,
    which is why this file flickered between rigs. Seed deterministically."""
    import uuid as _uuid

    from sqlalchemy import text as _text

    from app.db.session import SessionFactory as _SF

    async with _SF() as session:
        for i in range(rows):
            tid = _uuid.uuid4()
            await session.execute(_text(
                "INSERT INTO discovered_tokens (id, mint_address, signature, slot,"
                " discovered_at, source_program, metadata_status, metadata_attempts)"
                " VALUES (:id, :mint, :sig, 1, now(), 'pumpfun', 'pending', 0)"
                " ON CONFLICT DO NOTHING"
            ), {"id": tid, "mint": f"MAINTSEED{i}x{tid.hex[:8]}", "sig": f"maintsig-{tid}"})
            await session.execute(_text(
                "INSERT INTO token_scores (id, token_id, mint_address, model_version,"
                " score, evidence, coverage, market_risk, opportunity_raw, observations,"
                " is_elite, has_veto, evaluated_at, grade, created_at, updated_at)"
                " VALUES (:id, :tid, :mint, 'v1', 50, 50, 50, 50, 50, 3,"
                " false, false, now(), 'watch', now(), now())"
                " ON CONFLICT DO NOTHING"
            ), {"id": _uuid.uuid4(), "tid": tid, "mint": f"MAINTSEED{i}x{tid.hex[:8]}"})
        await session.commit()


async def _unseed_token_scores() -> None:
    """Leave the shared database exactly as found — the seed is per-test
    evidence, not a fixture other files should ever be able to observe."""
    from sqlalchemy import text as _text

    from app.db.session import SessionFactory as _SF

    async with _SF() as session:
        await session.execute(_text("DELETE FROM token_scores WHERE mint_address LIKE 'MAINTSEED%'"))
        await session.execute(_text("DELETE FROM discovered_tokens WHERE mint_address LIKE 'MAINTSEED%'"))
        await session.commit()


class TestReport:
    async def test_it_reports_drift_without_changing_anything(self) -> None:
        """Read-only: what an operator runs to decide whether to maintain."""
        report = await maintenance.statistics_drift(("token_scores",))

        assert len(report) == 1
        row = report[0]
        assert row["table"] == "token_scores"
        assert isinstance(row["planner_estimate"], int)
        assert isinstance(row["actual"], int)

    async def test_drift_is_reported_against_pg_class_not_pg_stat(self) -> None:
        """`pg_class.reltuples` is what the planner reads.

        `pg_stat_user_tables.n_live_tup` is a different counter, lost on an
        unclean shutdown — reading it reported a 97x 'drift' during the audit
        that the planner never actually saw. The estimate here must track the
        real count closely on a freshly analyzed table, which `n_live_tup`
        would not.
        """
        await _seed_token_scores()
        try:
            await maintenance.maintain(tables=("token_scores",))
            row = (await maintenance.statistics_drift(("token_scores",)))[0]

            assert row["drift_factor"] == pytest.approx(1.0, abs=0.05)
        finally:
            await _unseed_token_scores()


class TestAnalyze:
    async def test_analyze_runs_and_reports_progress(self) -> None:
        """ANALYZE is cheap and safe: no rewrite, no blocking lock."""
        maintained = await maintenance.maintain(tables=("token_scores",))
        assert maintained == 1

    async def test_analyze_leaves_the_estimate_accurate(self) -> None:
        await maintenance.maintain(tables=("token_scores",))
        row = (await maintenance.statistics_drift(("token_scores",)))[0]

        actual = int(row["actual"])  # type: ignore[call-overload]
        estimate = int(row["planner_estimate"])  # type: ignore[call-overload]
        if actual == 0:
            pytest.skip("no rows in this database to estimate")
        assert abs(estimate - actual) <= max(1, actual * 0.1)


class TestCli:
    def test_report_is_the_only_mode_that_touches_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called: list[str] = []

        async def _maintain(**kwargs: object) -> int:
            called.append("maintain")
            return 0

        async def _drift(tables: object = ()) -> list[dict[str, object]]:
            called.append("report")
            return [{"table": "token_scores", "planner_estimate": 1, "actual": 1}]

        monkeypatch.setattr(maintenance, "maintain", _maintain)
        # Stubbed as well: `main` opens its own event loop, and the module-level
        # engine's pool is already bound to the test loop.
        monkeypatch.setattr(maintenance, "statistics_drift", _drift)

        assert maintenance.main(["--report", "--table", "token_scores"]) == 0
        assert called == ["report"]

    def test_vacuum_is_opt_in(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The expensive form must never be the default."""
        seen: list[bool] = []

        async def _maintain(*, vacuum: bool = False, tables: object = ()) -> int:
            seen.append(vacuum)
            return 1

        monkeypatch.setattr(maintenance, "maintain", _maintain)

        maintenance.main(["--table", "token_scores"])
        maintenance.main(["--vacuum", "--table", "token_scores"])

        assert seen == [False, True]

    def test_an_unknown_table_is_rejected(self) -> None:
        """Table names are interpolated into SQL, so the allowlist is the
        boundary that makes that safe."""
        with pytest.raises(SystemExit):
            maintenance.main(["--table", "'; DROP TABLE users; --"])

    def test_a_failure_exits_non_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _boom(**kwargs: object) -> int:
            raise RuntimeError("connection refused")

        monkeypatch.setattr(maintenance, "maintain", _boom)
        assert maintenance.main(["--table", "token_scores"]) == 1
