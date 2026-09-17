"""G1 records top-10 holder concentration and LP lock at every decision.

On the trade row for an entry, on the candidate row for an entry or a
refusal, never blocking either, and never read from after the decision. The
forward 1h return of a refused candidate is filled by the outcomes pass.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.labs.rafiq import outcomes
from app.labs.rafiq.feed import _LP_CHECK, EntryFeatures
from app.labs.rafiq.models import RafiqCandidate, RafiqLabPosition
from app.labs.rafiq.service import RafiqLabService
from app.labs.rafiq.tests.test_g1_engine import DEEP, g1_book, path, seed_path
from app.models.research_data import HolderSnapshot
from app.models.token_security import TokenSecurityEvaluationRow

NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def holder(mint: str, at: datetime, pct: str) -> HolderSnapshot:
    return HolderSnapshot(mint_address=mint, captured_at=at, provider="test",
                          context="admission", supply_raw=Decimal(10**15), decimals=6,
                          top10_pct=Decimal(pct))


def verdict(mint: str, at: datetime, status: str,
            codes: list[str]) -> TokenSecurityEvaluationRow:
    return TokenSecurityEvaluationRow(
        mint_address=mint, evaluated_at=at, overall_status="VERIFIED",
        evaluator_version="test", reason_codes=[], evidence={},
        checks=[{"name": _LP_CHECK, "status": status, "reason_codes": codes}])


async def candidate(session, mint: str) -> RafiqCandidate:
    return (await session.execute(
        select(RafiqCandidate).where(RafiqCandidate.mint_address == mint)
    )).scalars().one()


@pytest.mark.integration
async def test_an_entry_and_a_refusal_both_carry_the_two_features(
    lab_session, monkeypatch
) -> None:
    """The phase-3 gate, as behaviour: one live entry and one candidate the
    gate refused, each with top-10 concentration and LP lock recorded from
    readings taken BEFORE the decision — and a later reading ignored."""
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    service = RafiqLabService(lab_session)
    await service.activate(now=NOW - timedelta(hours=1))
    entered = await seed_path(lab_session, "featin", NOW, path((0, 1), length=5))
    thin_rows = [(price, Decimal(150_000), status) for price, _, status in path(
        (0, 1), (20, "1.6"), (40, "1.3"), length=70)]
    refused = await seed_path(lab_session, "featout", NOW, thin_rows)
    before, after = NOW - timedelta(minutes=3), NOW + timedelta(seconds=30)
    lab_session.add_all([
        holder(entered, before, "34.5"), verdict(entered, before, "PASS", []),
        holder(refused, before, "61.2"),
        verdict(refused, before, "UNKNOWN", ["POOL_NOT_PROTOCOL_MIGRATED",
                                             "MIGRATION_DESTINATION_UNVERIFIED"]),
        # Written after the decision: must not be read into it.
        holder(entered, after, "99.0"), verdict(entered, after, "FAIL", ["LP_OUTSTANDING"]),
    ])
    await lab_session.flush()

    await service.tick(now=NOW)

    book = await g1_book(lab_session)
    trade = (await lab_session.execute(
        select(RafiqLabPosition).where(RafiqLabPosition.mint_address == entered)
    )).scalars().one()
    assert trade.strategy_id == book.id
    assert trade.entry_top10_holder_pct == Decimal("34.5000")
    assert trade.entry_top10_captured_at == before
    assert (trade.entry_lp_status, trade.entry_lp_locked) == ("PASS", True)
    assert trade.entry_features_error is None

    took = await candidate(lab_session, entered)
    assert (took.outcome, took.position_id) == ("entered", trade.id)
    assert (took.top10_holder_pct, took.lp_locked) == (Decimal("34.5000"), True)

    no = await candidate(lab_session, refused)
    assert (no.outcome, no.reject_reason) == ("rejected", "liquidity_too_low")
    assert no.top10_holder_pct == Decimal("61.2000")
    assert (no.lp_status, no.lp_locked) == ("UNKNOWN", None)
    assert no.max_return_1h is None

    await outcomes.record(lab_session, now=NOW + timedelta(hours=1))
    await lab_session.refresh(no)
    assert no.max_return_1h == Decimal("0.600000")     # 1.6 over the 1.0 it was refused at
    assert no.dead_1h is False


@pytest.mark.integration
async def test_a_silent_store_never_blocks_an_entry_and_names_itself(
    lab_session, monkeypatch
) -> None:
    monkeypatch.setenv("RAFIQ_LAB_ENABLED", "true")
    service = RafiqLabService(lab_session)
    await service.activate(now=NOW - timedelta(hours=1))
    mint = await seed_path(lab_session, "featnone", NOW, path((0, 1), length=5))

    await service.tick(now=NOW)

    trade = (await lab_session.execute(
        select(RafiqLabPosition).where(RafiqLabPosition.mint_address == mint)
    )).scalars().one()
    assert trade.entry_top10_holder_pct is None and trade.entry_lp_locked is None
    assert trade.entry_features_error == "no_holder_snapshot,no_security_evaluation"
    assert trade.cost_basis == Decimal("10.00") and trade.entry_liquidity_usd == DEEP


@pytest.mark.parametrize(("status", "codes", "locked"), [
    ("PASS", [], True),
    ("PASS", ["PUMPSWAP_MIGRATED_LP_BURNED"], True),
    ("FAIL", ["LP_OUTSTANDING"], False),
    ("UNKNOWN", ["LP_OUTSTANDING"], False),
    ("UNKNOWN", ["POOL_NOT_PROTOCOL_MIGRATED", "MIGRATION_DESTINATION_UNVERIFIED"], None),
    ("NOT_APPLICABLE", ["POOL_CUSTODY_OUT_OF_SCOPE"], None),
    (None, None, None),
])
def test_lp_locked_answers_only_what_the_check_established(status, codes, locked) -> None:
    features = EntryFeatures(top10_holder_pct=None, top10_captured_at=None,
                             lp_status=status, lp_reason_codes=codes,
                             lp_checked_at=None, error=None)
    assert features.lp_locked is locked
