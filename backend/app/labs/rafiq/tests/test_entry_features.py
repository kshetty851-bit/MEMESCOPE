"""The entry decision's two instrumented features.

`FINDINGS.md` ranks holder concentration and LP-lock status at entry as the
most likely movers of the total-loss rate and records that no book checks
either. These tests hold the three properties that make the instrument worth
trusting later, when somebody reads a column of nulls and has to decide what
it means:

* a silent store never changes whether a trade is taken,
* a reading taken after the decision is never read back into it, and
* a reading is never written to a row that already exists.

Without the third, a null becomes evidence the strategy never had; without the
second, every statistic computed from these columns is look-ahead.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.labs.rafiq import config
from app.labs.rafiq.feed import _LP_CHECK, RafiqFeed
from app.labs.rafiq.models import RafiqLabPosition
from app.labs.rafiq.service import RafiqLabService
from app.labs.rafiq.tests.test_full_cycle import seed_candidate
from app.models.research_data import HolderSnapshot
from app.models.token_security import TokenSecurityEvaluationRow

pytestmark = pytest.mark.integration


def _holder(mint: str, at: datetime, pct: Decimal | None) -> HolderSnapshot:
    return HolderSnapshot(
        mint_address=mint, captured_at=at, provider="test", context="admission",
        supply_raw=Decimal(1_000_000), decimals=6, top10_pct=pct)


def _evaluation(mint: str, at: datetime, checks: list[dict]) -> TokenSecurityEvaluationRow:
    return TokenSecurityEvaluationRow(
        mint_address=mint, evaluated_at=at, overall_status="VERIFIED",
        evaluator_version="test", reason_codes=[], checks=checks, evidence={})


def _lp(status: str, codes: list[str]) -> dict:
    return {"name": _LP_CHECK, "status": status, "reason_codes": codes}


async def _enter_one(session, now, *, tag: str) -> RafiqLabPosition:
    """One F2 entry, and the row it wrote."""
    mint = await seed_candidate(session, now, tag=tag)
    service = RafiqLabService(session)
    await service.activate(now=now - timedelta(hours=1))
    await service.tick(now=now)
    row = (await session.execute(
        select(RafiqLabPosition).where(RafiqLabPosition.mint_address == mint)
    )).scalars().first()
    assert row is not None, "no book entered the seeded candidate"
    return row


async def test_a_silent_store_never_stops_the_trade(lab_session, monkeypatch) -> None:
    """The fetch-failure policy, as behaviour. Neither store has anything to
    say about this mint, and the entry happens anyway with both readings null
    and both silences named."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    now = datetime.now(UTC)
    row = await _enter_one(lab_session, now, tag="silent")

    assert row.entry_top10_holder_pct is None
    assert row.entry_lp_status is None
    assert row.entry_lp_checked_at is None
    assert row.entry_features_error == "no_holder_snapshot,no_security_evaluation"


async def test_both_readings_are_captured_at_entry(lab_session, monkeypatch) -> None:
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    now = datetime.now(UTC)
    mint = await seed_candidate(lab_session, now, tag="captured")
    taken = now - timedelta(minutes=3)
    lab_session.add(_holder(mint, taken, Decimal("41.2500")))
    lab_session.add(_evaluation(mint, taken, [_lp("UNKNOWN", ["LP_OUTSTANDING"])]))
    await lab_session.flush()

    service = RafiqLabService(lab_session)
    await service.activate(now=now - timedelta(hours=1))
    await service.tick(now=now)
    row = (await lab_session.execute(
        select(RafiqLabPosition).where(RafiqLabPosition.mint_address == mint)
    )).scalars().first()

    assert row.entry_top10_holder_pct == Decimal("41.2500")
    assert row.entry_top10_captured_at == taken
    assert row.entry_lp_status == "UNKNOWN"
    assert row.entry_lp_reason_codes == ["LP_OUTSTANDING"]
    assert row.entry_lp_checked_at == taken
    assert row.entry_features_error is None
    # The age at the decision is derivable, and is the three minutes that
    # actually elapsed rather than an age frozen at write time.
    assert row.opened_at - row.entry_top10_captured_at == timedelta(minutes=3)


async def test_a_reading_taken_after_the_decision_is_not_read(
    lab_session, monkeypatch
) -> None:
    """Point-in-time, enforced in SQL. A snapshot one second past the decision
    is in the table by the time the position row is written, and must not
    reach it — otherwise every statistic from these columns is look-ahead."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    now = datetime.now(UTC)
    mint = await seed_candidate(lab_session, now, tag="future")
    lab_session.add(_holder(mint, now + timedelta(seconds=1), Decimal("99.0000")))
    lab_session.add(_evaluation(mint, now + timedelta(seconds=1),
                                [_lp("PASS", [])]))
    await lab_session.flush()

    service = RafiqLabService(lab_session)
    await service.activate(now=now - timedelta(hours=1))
    await service.tick(now=now)
    row = (await lab_session.execute(
        select(RafiqLabPosition).where(RafiqLabPosition.mint_address == mint)
    )).scalars().first()

    assert row.entry_top10_holder_pct is None
    assert row.entry_lp_status is None
    assert row.entry_features_error == "no_holder_snapshot,no_security_evaluation"


async def test_entry_features_are_never_backfilled(lab_session, monkeypatch) -> None:
    """The reading that arrives after the entry stays out of the entry's row.

    This is the test that stops a well-meaning later change from "filling in
    the gaps": the null is the record of what the decision could see, and a
    value written into it afterwards is evidence the strategy never had."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    now = datetime.now(UTC)
    row = await _enter_one(lab_session, now, tag="nobackfill")
    assert row.entry_top10_holder_pct is None

    # Both stores now answer, and the position is still open.
    lab_session.add(_holder(row.mint_address, now + timedelta(minutes=1),
                            Decimal("12.0000")))
    lab_session.add(_evaluation(row.mint_address, now + timedelta(minutes=1),
                                [_lp("PASS", [])]))
    await lab_session.flush()

    service = RafiqLabService(lab_session)
    for minute in (2, 3, 4):
        await service.tick(now=now + timedelta(minutes=minute))
    await lab_session.refresh(row)

    assert row.status == "open", "the position closed; this proves nothing"
    assert row.entry_top10_holder_pct is None
    assert row.entry_lp_status is None
    assert row.entry_features_error == "no_holder_snapshot,no_security_evaluation"


async def test_an_evaluation_without_the_lp_check_keeps_its_timestamp(
    lab_session
) -> None:
    """"The evaluator ran and did not perform this check" and "the evaluator
    never ran" are different facts, and the column has to carry both."""
    now = datetime.now(UTC)
    mint = ("NoLpChk" + uuid.uuid4().hex).ljust(44, "5")[:44]
    at = now - timedelta(minutes=2)
    lab_session.add(_evaluation(mint, at, [{"name": "MINT_AUTHORITY",
                                            "status": "PASS",
                                            "reason_codes": []}]))
    await lab_session.flush()

    features = await RafiqFeed(lab_session).entry_features(mint=mint, at=now)
    assert features.lp_status is None
    assert features.lp_reason_codes is None
    assert features.lp_checked_at == at
    assert features.error == "no_holder_snapshot,no_lp_check"


async def test_a_snapshot_that_measured_nothing_is_not_a_reading(
    lab_session
) -> None:
    """A failed collection writes a row with `top10_pct` null. Reading it as a
    measurement would report holder concentration of zero for a token nobody
    could resolve."""
    now = datetime.now(UTC)
    mint = ("NullPct" + uuid.uuid4().hex).ljust(44, "6")[:44]
    lab_session.add(_holder(mint, now - timedelta(minutes=1), None))
    await lab_session.flush()

    features = await RafiqFeed(lab_session).entry_features(mint=mint, at=now)
    assert features.top10_holder_pct is None
    assert "no_holder_snapshot" in features.error


async def test_the_freshest_reading_at_or_before_the_decision_wins(
    lab_session
) -> None:
    now = datetime.now(UTC)
    mint = ("Freshest" + uuid.uuid4().hex).ljust(44, "7")[:44]
    for minutes, pct in ((30, Decimal("10.0000")), (5, Decimal("20.0000"))):
        lab_session.add(_holder(mint, now - timedelta(minutes=minutes), pct))
    lab_session.add(_holder(mint, now + timedelta(minutes=5), Decimal("30.0000")))
    await lab_session.flush()

    features = await RafiqFeed(lab_session).entry_features(mint=mint, at=now)
    assert features.top10_holder_pct == Decimal("20.0000")


def test_lp_check_name_matches_the_platform() -> None:
    """Pinned against the shared contract's own enum, not against a string
    this lab wrote down. A rename upstream then breaks here instead of
    silently turning every LP reading into `no_lp_check` for ever."""
    from app.security.contract import CheckName

    assert CheckName.LIQUIDITY_SECURITY.value == _LP_CHECK


def test_the_lab_does_not_fetch_to_decide() -> None:
    """No HTTP client reaches the entry path. The fetch-failure policy is
    satisfied by construction, not by a timeout that might be raised later."""
    import ast
    import pathlib

    for name in ("feed.py", "service.py"):
        tree = ast.parse((pathlib.Path(config.__file__).parent / name).read_text())
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree) if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        }
        assert not imported & {"httpx", "requests", "aiohttp", "urllib"}, name
