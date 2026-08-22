"""Karthik's authority boundary, and the honesty of every surface behind it.

The tests that would fail if the operator ever became something other than what
it was built to be: one wallet, seven reversible repairs, nothing armed by
default, and no figure invented for a wallet that does not exist.

── WHY SO MANY OF THESE ARE ABOUT *NOT* DOING THINGS ────────────────────

Because that is what the feature is. The reading half is ordinary code and its
failure mode is a wrong number on a screen. The authority half's failure mode
is an autonomous process quietly repairing a trading record, and the only way
to be sure that cannot happen is to assert the refusals rather than the
successes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.karthik_ops import detect, integrity, monitor, reports, service, tables
from app.karthik_ops.authority import (
    AUTONOMY_ENV_VAR,
    FORBIDDEN_STRATEGY_IDS,
    SAFE_REPAIRS,
    WALLET_ENV_VAR,
    autonomy,
    permit,
)
from app.karthik_ops.wallet import UNBOUND, resolve
from app.models.hq_ops import HqAction, HqIncident

# ── the allowlist ───────────────────────────────────────────────────────


class TestAllowlist:
    def test_every_repair_is_reversible_and_operational(self) -> None:
        """No entry may touch the record the experiment is measuring.

        The property that makes the list safe is not that it is short — it is
        that every action on it changes a cache, a subscription, a heartbeat or
        an idempotent job, and none of them changes a trade, a fill, a price or
        a cash balance. A key naming a write to any of those would be a repair
        that can alter the result.
        """
        # Checked on the *verb*, not on the nouns. "position" appears in
        # `position_subscriptions_reprime`, which re-primes a market feed and
        # writes nothing — a substring rule cannot tell that from a write, and
        # would either pass everything or fail the wrong entry. What an action
        # does is its last segment, and these six are all recoverable
        # operations on derived or transient state.
        recoverable = {
            "restart",
            "refresh",
            "reprime",
            "retry",
            "repair",
            "rerun",
        }
        for key, repair in SAFE_REPAIRS.items():
            assert repair.reversible, f"{key} is not reversible"
            assert key.startswith("karthik."), f"{key} is not namespaced to Karthik"
            verb = key.rsplit("_", 1)[-1]
            assert verb in recoverable, (
                f"{key} ends in {verb!r}, which is not a recoverable action"
            )

    def test_an_unknown_action_is_refused_without_evaluation(self) -> None:
        verdict = permit("karthik.rewrite_history", mode="SAFE_AUTOREPAIR")
        assert verdict.allowed is False
        assert verdict.verdict == "not_allowlisted"

    def test_a_real_action_is_refused_in_observe_only(self) -> None:
        verdict = permit("karthik.quote_retry", mode="OBSERVE_ONLY")
        assert verdict.allowed is False
        # The two refusals are different facts about a deployment and must not
        # collapse: one is a bug or an attack, the other is the intended state.
        assert verdict.verdict == "observe_only"

    def test_a_real_action_is_allowed_only_when_armed(self) -> None:
        assert permit("karthik.quote_retry", mode="SAFE_AUTOREPAIR").allowed is True

    def test_observe_only_is_the_default_and_survives_a_typo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(AUTONOMY_ENV_VAR, raising=False)
        assert autonomy() == "OBSERVE_ONLY"
        for typo in ("SAFE_AUTO_REPAIR", "safe-autorepair", "true", "1", "yes", ""):
            monkeypatch.setenv(AUTONOMY_ENV_VAR, typo)
            assert autonomy() == "OBSERVE_ONLY", f"{typo!r} armed production"
        monkeypatch.setenv(AUTONOMY_ENV_VAR, "SAFE_AUTOREPAIR")
        assert autonomy() == "SAFE_AUTOREPAIR"


# ── isolation ───────────────────────────────────────────────────────────


class TestIsolation:
    async def test_unbound_when_the_wallet_is_not_on_this_deployment(
        self, db_session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The state this whole module was written in.

        The wallet's tables are created by the wallet's own migration. Without
        it the operator must run correctly and report nothing, rather than
        raising on the first query.
        """
        monkeypatch.delenv(WALLET_ENV_VAR, raising=False)
        binding = await resolve(db_session)
        assert binding.readable is False
        assert binding.wallet_id is None
        # Either the tables are absent (unbound) or present and empty
        # (designated_but_missing). Both are honest; neither is a crash.
        assert binding.state in ("unbound", "designated_but_missing")

    @pytest.mark.parametrize("strategy_id", sorted(FORBIDDEN_STRATEGY_IDS))
    async def test_refuses_to_be_bound_to_another_wallet(
        self, db_session, monkeypatch: pytest.MonkeyPatch, strategy_id: str
    ) -> None:
        """The one place §7's boundary can actually be crossed: configuration.

        Somebody sets the variable to the live Original Paper Wallet's strategy
        and Karthik silently becomes a second operator on the platform's
        published track record. He refuses, reads nothing, and says why.
        """
        monkeypatch.setenv(WALLET_ENV_VAR, strategy_id)
        binding = await resolve(db_session)
        assert binding.state == "forbidden"
        assert binding.readable is False
        assert binding.needs_owner is True

    async def test_never_raises_on_a_deployment_without_the_wallet(
        self, db_session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(WALLET_ENV_VAR, "karthik")
        binding = await resolve(db_session)
        assert binding.readable is False
        assert binding.detail

    def test_the_forbidden_list_covers_every_registered_paper_strategy(self) -> None:
        """A new Original Paper generation must not be nameable by omission.

        The list is explicit rather than derived so a rename is visible in a
        diff — but it still has to *cover* the registry, and this is what says
        so when somebody adds a strategy and forgets.
        """
        from app.paper.strategy import registry

        for strategy in registry.all():
            assert strategy.id in FORBIDDEN_STRATEGY_IDS, (
                f"{strategy.id} is a paper wallet strategy Karthik could be pointed at"
            )

    def test_reaches_exactly_three_tables_and_they_are_all_karthiks(self) -> None:
        """The isolation, at its strongest point.

        Three tables, no relationships, no writes. That list is the complete
        set of rows Karthik can reach, and the isolation claim is checkable
        against it rather than against a sentence.
        """
        assert set(tables.declared_tables()) == {
            "karthik_wallets",
            "karthik_opportunities",
            "karthik_positions",
        }

    def test_reads_no_other_subsystem(self) -> None:
        """Structural, not aspirational: the module cannot import what it must
        not touch. An import is the cheapest possible thing to assert and the
        only one that survives a refactor nobody reviewed."""
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[2] / "app" / "karthik_ops"
        forbidden = ("app.paper_v2", "app.strategy_lab", "app.real_wallet", "app.paper.")
        for path in root.glob("*.py"):
            source = path.read_text()
            for module in forbidden:
                assert module not in source, f"{path.name} imports {module}"

    def test_touches_track_record_read_only(self) -> None:
        """`radar_tokens` is the Track Record. Karthik selects from it and does
        nothing else to it — §24's requirement, expressed as the absence of any
        other statement rather than as a promise."""
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[2] / "app" / "karthik_ops"
        for path in root.glob("*.py"):
            source = path.read_text()
            for write in ("session.add(RadarToken", "update(RadarToken", "delete(RadarToken"):
                assert write not in source, f"{path.name} writes to the Track Record"


# ── the integrity score ─────────────────────────────────────────────────


class TestIntegrity:
    def test_factors_sum_to_exactly_one_hundred(self) -> None:
        assert sum(factor.max_penalty for factor in integrity.FACTORS) == 100

    def test_nothing_measured_scores_none_rather_than_a_number(self) -> None:
        """The single most important assertion about this number.

        100 would claim the experiment is trustworthy; 0 would accuse it of
        being broken. Neither is known, and `None` is the only honest answer.
        """
        result = integrity.unmeasured("No wallet.")
        assert result.score is None
        assert result.band == "NOT MEASURED"
        assert result.unmeasured == len(integrity.FACTORS)
        assert all(d.measured is False for d in result.deductions)

    def test_a_clean_measured_experiment_scores_one_hundred(self) -> None:
        clean = [
            integrity.Deduction(
                factor=f.key, label=f.label, penalty=0, measured=True, detail="clean"
            )
            for f in integrity.FACTORS
        ]
        result = integrity.score(clean)
        assert result.score == 100
        assert result.band == "HEALTHY"

    def test_an_unmeasured_factor_deducts_nothing_and_is_counted(self) -> None:
        """`hq_ops`'s rule, applied to a score: "we could not look" must not
        drag the number down *or* be rounded up to clean. It contributes zero
        and is published in `unmeasured` where a reader can see it."""
        mixed = [
            integrity.Deduction(
                factor=f.key,
                label=f.label,
                penalty=0,
                measured=f.key != "quote_freshness",
                detail="",
            )
            for f in integrity.FACTORS
        ]
        result = integrity.score(mixed)
        assert result.score == 100
        assert result.unmeasured == 1

    def test_a_totally_broken_experiment_bottoms_out_at_zero(self) -> None:
        worst = [
            integrity.Deduction(
                factor=f.key, label=f.label, penalty=f.max_penalty, measured=True, detail=""
            )
            for f in integrity.FACTORS
        ]
        result = integrity.score(worst)
        assert result.score == 0
        assert result.band == "UNRELIABLE"

    def test_a_factor_cannot_deduct_more_than_it_declared(self) -> None:
        with pytest.raises(ValueError, match="of a permitted"):
            integrity.score(
                [
                    integrity.Deduction(
                        factor="target_provenance",
                        label="x",
                        penalty=99,
                        measured=True,
                        detail="",
                    )
                ]
            )

    def test_it_is_not_a_profitability_score(self) -> None:
        """No factor may be about money. A data-quality instrument that quietly
        rewarded a winning wallet would be a second P&L display, and a losing
        experiment run properly must be able to score 100."""
        for factor in integrity.FACTORS:
            blob = f"{factor.key} {factor.label} {factor.meaning}".lower()
            for word in ("profit", "pnl", "p&l", "return", "win rate", "roi"):
                assert word not in blob, f"{factor.key} scores profitability"


# ── the defect catalogue ────────────────────────────────────────────────


class TestDefects:
    def test_only_auto_fix_defects_name_a_repair(self) -> None:
        for defect in detect.DEFECTS:
            if defect.rectification == "AUTO_FIX":
                assert defect.repair in SAFE_REPAIRS, f"{defect.key} names an unknown repair"
            else:
                assert defect.repair is None, f"{defect.key} is one refactor from auto-repair"

    def test_everything_touching_the_record_needs_the_owner(self) -> None:
        """§17: never rewrite historical P&L to repair a result. Every defect
        that is *about* the record is therefore OWNER_REQUIRED, and this is the
        list that would fail if one were quietly reclassified."""
        record_defects = {
            "duplicate_position",
            "entry_size_wrong",
            "pre_activation_entry",
            "negative_proceeds",
            "forbidden_exit",
            "target_below_multiple",
            "accounting_mismatch",
        }
        for key in record_defects:
            assert detect.DEFECT_BY_KEY[key].rectification == "OWNER_REQUIRED"

    def test_undetectable_conditions_say_why_rather_than_passing_silently(self) -> None:
        gaps = [d for d in detect.DEFECTS if not d.detectable]
        assert gaps, "the catalogue claims to check everything, which is not credible"
        for defect in gaps:
            assert defect.gap and len(defect.gap) > 40

    def test_coverage_is_published_with_the_gaps_in_it(self) -> None:
        published = detect.coverage()
        assert published["not_detectable"] == len(
            [d for d in detect.DEFECTS if not d.detectable]
        )
        assert len(published["checks"]) == len(detect.DEFECTS)

    async def test_detects_nothing_when_there_is_nothing_to_detect(self, db_session) -> None:
        assert await detect.run(db_session, UNBOUND) == []


# ── the incident lifecycle and the audit trail ──────────────────────────


def _finding(
    defect: str = "stale_quote",
    rectification: str = "AUTO_FIX",
    signature: str = "karthik.stale_quote",
) -> detect.Finding:
    return detect.Finding(
        defect=defect,
        label=detect.DEFECT_BY_KEY[defect].label,
        rectification=rectification,  # type: ignore[arg-type]
        severity="degraded",
        signature=signature,
        summary="Two open positions have no price newer than ten minutes.",
        evidence={"positions": 2},
    )


class TestLifecycle:
    async def test_opens_one_incident_per_condition_not_one_per_tick(self, db_session) -> None:
        first, created_first = await service.open_finding(db_session, _finding())
        second, created_second = await service.open_finding(db_session, _finding())
        assert created_first is True
        assert created_second is False
        assert first.id == second.id

    async def test_codes_are_karthiks_own(self, db_session) -> None:
        incident, _ = await service.open_finding(db_session, _finding())
        assert incident.code.startswith("INC-KAR-")
        assert incident.agent == service.AGENT
        assert incident.component.startswith("karthik.")

    async def test_an_owner_finding_lands_in_the_owner_queue(self, db_session) -> None:
        incident, _ = await service.open_finding(
            db_session,
            _finding(
                defect="accounting_mismatch",
                rectification="OWNER_REQUIRED",
                signature="karthik.accounting_mismatch",
            ),
        )
        assert incident.kind == "karthik_approval"
        assert incident.code.startswith("REQ-KAR-")
        assert incident.status == "awaiting_owner"
        # `red` is the existing vocabulary for "no autonomous action may touch
        # this", so the refusal and the styling both apply without a second one.
        assert incident.autonomy == "red"
        assert incident.owner_rationale

        ledger = await service.ledger(db_session)
        assert incident.id in {row.id for row in ledger.owner_attention}

    async def test_observe_only_records_the_decision_and_executes_nothing(
        self, db_session
    ) -> None:
        """The headline behaviour of a first production deployment.

        Karthik detects, diagnoses, records and recommends. The audit row
        exists — that is the point of observe-only, it exercises the whole
        decision path — and its outcome is `skipped`.
        """
        incident, permission = await service.consider(
            db_session, _finding(), mode="OBSERVE_ONLY"
        )
        assert permission.allowed is False
        assert permission.verdict == "observe_only"

        actions = (
            (
                await db_session.execute(
                    select(HqAction).where(HqAction.incident_id == incident.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(actions) == 1
        assert actions[0].outcome == "skipped"
        assert actions[0].agent == service.AGENT
        # Never hide a failed or refused repair.
        assert actions[0].reason

    async def test_an_owner_finding_can_never_be_auto_repaired_even_when_armed(
        self, db_session
    ) -> None:
        """The strongest single assertion in this file.

        Autonomy fully armed, a critical accounting mismatch on the table, and
        the answer is still no — because the defect names no repair and no
        repair exists that could be named.
        """
        _incident, permission = await service.consider(
            db_session,
            _finding(
                defect="accounting_mismatch",
                rectification="OWNER_REQUIRED",
                signature="karthik.accounting_mismatch_armed",
            ),
            mode="SAFE_AUTOREPAIR",
        )
        assert permission.allowed is False
        assert permission.verdict == "not_allowlisted"

    async def test_the_ledger_returns_only_karthiks_rows(self, db_session) -> None:
        await service.open_finding(db_session, _finding())
        # Somebody else's incident, in the same table.
        db_session.add(
            HqIncident(
                code="INC-999",
                sequence=999,
                kind="incident",
                component="redis",
                severity="critical",
                status="open",
                autonomy="green",
                agent="sentinel",
                signature="redis.down",
                symptoms={},
            )
        )
        await db_session.flush()

        ledger = await service.ledger(db_session)
        assert ledger.open_rows
        for row in ledger.open_rows:
            assert row.kind in service.KARTHIK_KINDS
            assert row.agent == service.AGENT

    async def test_the_hq_panel_does_not_show_karthiks_rows(self, db_session) -> None:
        """The other half of the isolation: Sentinel's room must not fill with
        wallet findings. Both surfaces filter on the same frozenset, so
        inclusion here and exclusion there cannot drift."""
        from app.hq_ops.api import operations_state
        from app.hq_ops.service import OPEN_STATUSES

        await service.open_finding(db_session, _finding())
        state = await operations_state(db_session)
        for incident in [*state.incidents, *state.recent]:
            assert incident.kind not in service.KARTHIK_KINDS
        for action in state.activity:
            assert action.agent != service.AGENT
        assert OPEN_STATUSES  # the import is the contract, not decoration


# ── the screens and the reports ─────────────────────────────────────────


class TestUnboundSurfaces:
    """Every read, against no wallet. All six must say the same thing."""

    async def test_every_screen_reports_unmeasured_with_a_reason(self, db_session) -> None:
        for reader in (
            monitor.wallet_screen,
            monitor.feed_screen,
            monitor.positions_screen,
            monitor.target_screen,
            monitor.accounting,
        ):
            reading = await reader(db_session, UNBOUND)
            assert reading.measured is False, reader.__name__
            assert reading.values == {}, f"{reader.__name__} invented a value"
            assert reading.rows == [], f"{reader.__name__} invented a row"
            assert "designated" in reading.detail.lower()

    @pytest.mark.parametrize("window", ["daily", "weekly", "lifetime"])
    async def test_every_report_reports_unmeasured(self, db_session, window: str) -> None:
        report = await reports.build(db_session, UNBOUND, window=window)
        assert report.measured is False
        assert report.pnl_usd is None
        assert report.targets_hit is None
        # Not zero. A quiet day and an absent wallet are different facts.
        assert report.entered is None

    async def test_a_first_visit_is_not_a_quiet_one(self, db_session) -> None:
        away = await reports.while_away(db_session, UNBOUND, since=None)
        assert away.measured is False
        assert away.new_trades is None

    async def test_integrity_is_unscored_rather_than_perfect(self, db_session) -> None:
        result = service.evaluate_integrity(
            UNBOUND,
            findings=[],
            positions=monitor.Reading(measured=False, detail="x"),
            books=monitor.Reading(measured=False, detail="x"),
            open_rows=[],
        )
        assert result.score is None
        assert result.band == "NOT MEASURED"


class TestBoundSurfaces:
    """The bound path, exercised against the wallet's real table shapes.

    Worth having even though this branch's deployments are unbound: the whole
    module is written to be correct the moment the wallet's migration lands,
    and code that has only ever run in its empty state is code nobody has run.

    Since the merge these run against the wallet's real model, so a renamed
    column now fails here rather than passing against the operator's stale idea
    of the schema. That was the one gap in this class before, and closing it is
    what importing the model bought.
    """

    @pytest.fixture
    async def wallet(self, db_session):
        # The wallet's tables are part of `Base.metadata` now that the branches
        # have merged, so conftest's `create_all` has already made them. Before
        # the merge this fixture created them from the operator's own Core
        # declarations; that scaffolding is gone with the thing it stood in for.
        wallet_id = uuid.uuid4()
        activated = datetime.now(UTC) - timedelta(days=2)
        await db_session.execute(
            tables.karthik_wallets.insert().values(
                id=wallet_id,
                name="karthik",
                starting_capital=Decimal(1000),
                trade_size=Decimal(10),
                take_profit_multiple=Decimal("1.25"),
                activated_at=activated,
            )
        )
        await db_session.flush()
        return await resolve(db_session)

    async def _position(self, db_session, wallet, *, n: int = 1, **over):
        opened = over.pop("opened_at", datetime.now(UTC) - timedelta(hours=1))
        # Every NOT NULL column on the real table, so a fixture row is a row
        # the wallet itself could have written. The operator reads a subset of
        # these, but inserting a partial row would be testing against a schema
        # that does not exist.
        values = {
            "id": uuid.uuid4(),
            "wallet_id": wallet.wallet_id,
            "mint_address": f"Mint{n}",
            "detected_at": opened,
            "track_record_at": opened,
            "opened_at": opened,
            "entry_price": Decimal(1),
            "entry_observed_price": Decimal(1),
            "entry_observed_at": opened,
            "cost_basis": Decimal(10),
            "quantity": Decimal(10),
            "decimals": 6,
            "target_price": Decimal("1.25"),
            "peak_price": Decimal(1),
            "last_evaluated_at": opened,
            "status": "open",
        }
        values.update(over)
        await db_session.execute(tables.karthik_positions.insert().values(**values))
        await db_session.flush()

    async def _opportunity(self, db_session, wallet, *, mint: str, decision: str, delay=0):
        at = datetime.now(UTC) - timedelta(hours=1)
        await db_session.execute(
            tables.karthik_opportunities.insert().values(
                id=uuid.uuid4(),
                wallet_id=wallet.wallet_id,
                mint_address=mint,
                track_record_at=at,
                decision=decision,
                decided_at=at + timedelta(seconds=delay),
            )
        )
        await db_session.flush()

    async def test_binds_to_the_singleton_wallet_and_reads_its_published_rules(
        self, db_session, wallet
    ) -> None:
        assert wallet.readable is True
        assert wallet.starting_balance == Decimal(1000)
        assert wallet.trade_size == Decimal(10)
        assert wallet.take_profit_multiple == Decimal("1.25")
        # The rules are read to check fills against, never to instruct.
        assert "no stop" in wallet.detail

    async def test_the_schema_forbids_a_second_wallet_and_the_resolver_agrees(
        self, db_session, wallet
    ) -> None:
        """The guard in `resolve()` is a second line, and this says which line.

        `uq_karthik_wallets_singleton` is a unique index on a constant
        expression — the database saying "at most one of these" — so a second
        wallet cannot be inserted at all. The resolver still counts, because a
        `limit(1)` that silently picked one of two would publish half an
        experiment as the whole of it, and a constraint is a thing a future
        migration can drop.
        """
        from sqlalchemy.exc import IntegrityError

        from app.models.karthik import KarthikWallet

        assert any(
            index.name == "uq_karthik_wallets_singleton" and index.unique
            for index in KarthikWallet.__table__.indexes
        )

        with pytest.raises(IntegrityError):
            await db_session.execute(
                tables.karthik_wallets.insert().values(
                    id=uuid.uuid4(),
                    name="karthik-2",
                    starting_capital=Decimal(1000),
                    trade_size=Decimal(10),
                    take_profit_multiple=Decimal("1.25"),
                    activated_at=datetime.now(UTC),
                )
            )
        await db_session.rollback()

    async def test_derives_the_book_from_position_rows(self, db_session, wallet) -> None:
        await self._position(db_session, wallet, n=1)
        await self._position(db_session, wallet, n=2)
        reading = await monitor.wallet_screen(db_session, wallet)
        assert reading.measured is True
        assert reading.values["open_positions"] == 2
        assert Decimal(str(reading.values["allocated_usd"])) == Decimal(20)
        # An unpriced book is not a flat book.
        assert reading.values["unrealised_pnl_usd"] is None

    async def test_a_closed_trade_with_no_proceeds_is_excluded_and_counted(
        self, db_session, wallet
    ) -> None:
        """Unknown proceeds are not zero proceeds. Excluding the row *and*
        saying so is the only reading that does not overstate the record."""
        await self._position(
            db_session,
            wallet,
            n=3,
            status="closed",
            closed_at=datetime.now(UTC),
            exit_proceeds_usd=None,
        )
        reading = await monitor.wallet_screen(db_session, wallet)
        assert reading.values["closed_without_proceeds"] == 1
        assert Decimal(str(reading.values["realised_pnl_usd"])) == Decimal(0)
        assert "proceeds" in reading.detail

    async def test_the_schema_forbids_a_duplicate_position(self, db_session, wallet) -> None:
        """`uq_karthik_positions_wallet_mint` makes one-position-per-token a
        database fact rather than a rule somebody follows.

        The operator's `duplicate_position` check therefore cannot fire today,
        and that is the correct outcome — it is kept as the second line for the
        same reason as the wallet singleton above: one indexed GROUP BY per
        tick is nothing, and a constraint is a thing a migration can drop. What
        this test pins is *which* mechanism is actually doing the work, so
        nobody later reads a permanently-empty check as coverage.
        """
        from sqlalchemy.exc import IntegrityError

        from app.models.karthik import KarthikPosition

        assert any(
            constraint.name == "uq_karthik_positions_wallet_mint"
            for constraint in KarthikPosition.__table__.constraints
        )

        await self._position(db_session, wallet, n=9)
        with pytest.raises(IntegrityError):
            await self._position(db_session, wallet, n=9)
        await db_session.rollback()

    async def test_a_duplicate_would_be_owner_work_if_one_ever_appeared(self) -> None:
        # Classification, asserted without needing a row the database refuses
        # to create. A duplicate is about the experiment's record, so §17 puts
        # it out of reach of any repair.
        assert detect.DEFECT_BY_KEY["duplicate_position"].rectification == "OWNER_REQUIRED"
        assert detect.DEFECT_BY_KEY["duplicate_position"].repair is None

    async def test_finds_a_wrong_entry_size_against_the_published_rule(
        self, db_session, wallet
    ) -> None:
        # Checked against the wallet's own `trade_size`, not a constant here.
        await self._position(db_session, wallet, n=4, cost_basis=Decimal(25))
        findings = await detect.run(db_session, wallet)
        assert any(f.defect == "entry_size_wrong" for f in findings)

    async def test_finds_a_backdated_entry(self, db_session, wallet) -> None:
        await self._position(
            db_session, wallet, n=5, opened_at=datetime.now(UTC) - timedelta(days=30)
        )
        findings = await detect.run(db_session, wallet)
        assert any(f.defect == "pre_activation_entry" for f in findings)

    async def test_finds_a_target_filled_below_the_published_multiple(
        self, db_session, wallet
    ) -> None:
        await self._position(
            db_session,
            wallet,
            n=6,
            status="closed",
            closed_at=datetime.now(UTC),
            exit_price=Decimal("1.10"),
            exit_proceeds_usd=Decimal(11),
            exit_reason="target_1_25x",
        )
        findings = await detect.run(db_session, wallet)
        assert any(f.defect == "target_below_multiple" for f in findings)

    async def test_finds_an_exit_the_wallet_has_no_rule_for(self, db_session, wallet) -> None:
        """The wallet has a target and no stop. Anything else closing a
        position is a rule it does not have."""
        await self._position(
            db_session,
            wallet,
            n=7,
            status="closed",
            closed_at=datetime.now(UTC),
            exit_price=Decimal("0.5"),
            exit_proceeds_usd=Decimal(5),
            exit_reason="stop_loss",
        )
        findings = await detect.run(db_session, wallet)
        assert any(f.defect == "forbidden_exit" for f in findings)

    async def test_finds_a_decision_recorded_far_too_late(self, db_session, wallet) -> None:
        await self._opportunity(
            db_session, wallet, mint="MintLate", decision="entered", delay=3600
        )
        findings = await detect.run(db_session, wallet)
        late = [f for f in findings if f.defect == "late_decision"]
        assert late and late[0].rectification == "OBSERVE_ONLY"

    async def test_finds_a_decision_it_does_not_recognise(self, db_session, wallet) -> None:
        """A decision string outside the published set means the wallet grew a
        rule the operator has not been told about — which is worth an owner's
        attention whichever way it turns out."""
        await self._opportunity(
            db_session, wallet, mint="MintOdd", decision="deferred_pending_review"
        )
        findings = await detect.run(db_session, wallet)
        assert any(f.defect == "unknown_decision" for f in findings)

    async def test_a_report_counts_the_window_it_says_it_counts(
        self, db_session, wallet
    ) -> None:
        await self._position(
            db_session,
            wallet,
            n=8,
            status="closed",
            closed_at=datetime.now(UTC),
            exit_price=Decimal("1.30"),
            exit_proceeds_usd=Decimal(13),
            exit_reason="target_1_25x",
        )
        daily = await reports.build(db_session, wallet, window="daily")
        assert daily.measured is True
        assert daily.targets_hit == 1
        assert daily.closed_positions == 1
        # Proceeds minus cost, from the wallet's own recorded figures.
        assert Decimal(str(daily.pnl_usd)) == Decimal(3)

    async def test_a_weekly_report_carries_a_day_series_with_no_holes(
        self, db_session, wallet
    ) -> None:
        weekly = await reports.build(db_session, wallet, window="weekly")
        assert len(weekly.daily_series) >= 7
        dates = [row["date"] for row in weekly.daily_series]
        assert dates == sorted(dates)

    async def test_the_while_away_summary_uses_the_readers_own_window(
        self, db_session, wallet
    ) -> None:
        await self._opportunity(db_session, wallet, mint="MintW", decision="entered")
        recent = await reports.while_away(
            db_session, wallet, since=datetime.now(UTC) - timedelta(minutes=30)
        )
        assert recent.measured is True
        # Decided an hour ago, so it is outside a thirty-minute window.
        assert recent.new_trades == 0

    async def test_the_integrity_score_becomes_a_number_once_there_is_evidence(
        self, db_session, wallet
    ) -> None:
        await self._position(db_session, wallet, n=11)
        await self._opportunity(db_session, wallet, mint="Mint11", decision="entered")
        findings = await detect.run(db_session, wallet)
        result = service.evaluate_integrity(
            wallet,
            findings=findings,
            positions=await monitor.positions_screen(db_session, wallet),
            books=await monitor.accounting(db_session, wallet),
            open_rows=[],
        )
        assert result.score is not None
        assert 0 <= result.score <= 100
        assert result.band in ("HEALTHY", "DEGRADED", "UNRELIABLE")
