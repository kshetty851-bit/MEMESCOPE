"""One desk's day, and the rule that stops it inventing one.

The feature is "click a character, see what they did". The hard part is not
building a timeline — it is refusing to build one for the ten desks that have
no log, because a plausible empty timeline and a real quiet day look identical
and only one of them is true.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.hq_ops import desk
from app.models.hq_ops import HqAction, HqIncident

pytest_plugins: list[str] = []


class TestUnloggedDesks:
    async def test_every_logless_desk_says_why(self, db_session) -> None:
        """The headline rule.

        A desk without an event stream returns `measured: false` and a sentence
        naming what is missing. That is a different answer from "nothing
        happened", and the difference is the whole point.
        """
        for employee in desk.NO_LOG:
            result = await desk.build(db_session, employee)
            assert result.measured is False, employee
            assert result.timeline == [], f"{employee} invented a timeline"
            assert result.counts == [], f"{employee} invented figures"
            assert len(result.detail) > 40, f"{employee} does not explain itself"

    async def test_an_unknown_desk_is_refused_rather_than_guessed(self, db_session) -> None:
        result = await desk.build(db_session, "someone-else")
        assert result.measured is False
        assert "log" in result.detail

    async def test_the_logless_list_names_real_employees(self) -> None:
        # A stale entry here would silently give a desk that HAS gained a log
        # the "no log" answer for ever.
        from app.hq_ops.desk import NO_LOG

        logged = {"karthik", "patch", "sentinel", "radar"}
        assert not (logged & set(NO_LOG)), "a desk is both logged and logless"


class TestActionDesks:
    async def _action(self, db_session, agent: str, outcome: str, action: str, ago_min: int):
        db_session.add(
            HqAction(
                agent=agent,
                action=action,
                autonomy="green",
                reason="because",
                outcome=outcome,
                at=datetime.now(UTC) - timedelta(minutes=ago_min),
            )
        )
        await db_session.flush()

    async def test_counts_every_outcome_not_just_the_successes(self, db_session) -> None:
        """A day of `skipped` is observe-only working as designed; a day of
        `failed` needs a person. A bare action count cannot tell them apart."""
        for i in range(5):
            await self._action(db_session, "karthik", "skipped", "karthik.quote_retry", i)
        await self._action(db_session, "karthik", "failed", "karthik.read_model_refresh", 6)

        result = await desk.build(db_session, "karthik")
        assert result.measured is True
        by_label = {c.label.strip(): c.value for c in result.counts}
        assert by_label["Actions attempted"] == 6
        assert by_label["skipped"] == 5
        assert by_label["failed"] == 1

    async def test_ignores_another_agent_and_anything_older_than_the_window(
        self, db_session
    ) -> None:
        await self._action(db_session, "karthik", "skipped", "a", 10)
        await self._action(db_session, "patch", "skipped", "a", 10)
        await self._action(db_session, "karthik", "skipped", "a", 60 * 30)  # 30h ago

        result = await desk.build(db_session, "karthik")
        assert {c.label.strip(): c.value for c in result.counts}["Actions attempted"] == 1

    async def test_caps_the_timeline_without_capping_the_counts(self, db_session) -> None:
        # 566 actions in a day is real. The timeline is a readable summary of a
        # log, and the counts are the log.
        for i in range(desk.TIMELINE_LIMIT + 15):
            await self._action(db_session, "patch", "succeeded", "worker.pool_restart", i)

        result = await desk.build(db_session, "patch")
        assert len(result.timeline) == desk.TIMELINE_LIMIT
        assert {c.label.strip(): c.value for c in result.counts}["Actions attempted"] == (
            desk.TIMELINE_LIMIT + 15
        )

    async def test_a_quiet_logged_desk_says_so_and_stays_measured(self, db_session) -> None:
        # The distinction the whole module exists for: measured AND empty.
        result = await desk.build(db_session, "karthik")
        assert result.measured is True
        assert result.timeline == []
        assert "Nothing recorded" in result.headline

    async def test_orders_the_timeline_newest_first(self, db_session) -> None:
        await self._action(db_session, "patch", "succeeded", "older", 200)
        await self._action(db_session, "patch", "succeeded", "newer", 5)
        result = await desk.build(db_session, "patch")
        assert [e.label for e in result.timeline] == ["newer", "older"]


class TestIncidentDesk:
    async def test_reports_what_it_raised_and_what_closed(self, db_session) -> None:
        now = datetime.now(UTC)
        for i, resolved in enumerate([True, False, False]):
            db_session.add(
                HqIncident(
                    code=f"INC-{900 + i}",
                    sequence=900 + i,
                    kind="incident",
                    component="redis" if i else "disk",
                    severity="critical" if i == 0 else "degraded",
                    status="resolved" if resolved else "open",
                    autonomy="green",
                    agent="sentinel",
                    signature=f"sig-{i}-{uuid.uuid4()}",
                    symptoms={"summary": "something was observed"},
                    detected_at=now - timedelta(minutes=10 + i),
                    resolved_at=now if resolved else None,
                )
            )
        await db_session.flush()

        result = await desk.build(db_session, "sentinel")
        by_label = {c.label.strip(): c.value for c in result.counts}
        assert result.measured is True
        assert by_label["Findings raised"] == 3
        assert by_label["Resolved"] == 1
        assert by_label["Critical"] == 1
        assert "3 findings" in result.headline


class TestEveryFigureNamesItsSource:
    async def test_no_count_is_published_without_a_field(self, db_session) -> None:
        # The same rule every metric in HQ lives under.
        db_session.add(
            HqAction(
                agent="patch", action="a", autonomy="green", reason="r", outcome="succeeded"
            )
        )
        await db_session.flush()
        for employee in ("patch", "sentinel", "radar"):
            result = await desk.build(db_session, employee)
            for count in result.counts:
                assert count.source, f"{employee}: {count.label} names no source"

    def test_the_module_only_reads(self) -> None:
        """Structural: a dossier must not be able to alter the record it
        reports on. No writer, no flush, no commit anywhere in the module.

        Sync on purpose — reading a file inside an async test blocks the loop,
        and this needs no session anyway."""
        import pathlib

        source = (
            pathlib.Path(__file__).resolve().parents[2] / "app" / "hq_ops" / "desk.py"
        ).read_text()
        for writer in ("session.add", "session.commit", "session.flush", "update(", "delete("):
            assert writer not in source, f"desk.py contains {writer}"
