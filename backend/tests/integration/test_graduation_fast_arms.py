"""The fast arms E75_4m / E75T_4m against a real database: who gets read,
who gets recorded, who gets bought, and that an operator's record only ever
holds what was known at the tick."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.labs.graduation.held_watch import Held
from app.labs.graduation.models import (
    GradMigration,
    GradOperator,
    GradPaperPosition,
    GradPostgradSample,
)
from app.labs.graduation.tournament import Tournament
from app.services.curve.pda import b58encode

pytestmark = pytest.mark.integration

NOW = datetime(2026, 9, 19, 12, 0, 0, tzinfo=UTC)
MINT = {name: b58encode(bytes([i + 1]) * 32) for i, name in enumerate("ABCSZOUL")}
#: Pool SOL for each candidate: 1,000 SOL is $200k of depth at $100 SOL,
#: 300 is $60k (recorded, too shallow to buy), 100 is $20k (not recorded).
QUOTE_SOL = {"A": 1000, "B": 1000, "C": 1000, "S": 300, "Z": 100, "O": 1000, "U": 1000}
IDS = {"A": {"WalletA", "FunderT"}, "B": {"WalletB", "FunderD"},
       "C": {"WalletC", "FunderF"}, "S": {"WalletS", "FunderT"}, "U": None}


def held(mint: str, quote_sol: float) -> Held:
    return Held(mint=mint, pool="pool", base_vault="bv", quote_vault="qv", base_decimals=6,
                quote_decimals=9, base=11_600_000 * 10**6, quote=int(quote_sol * 10**9),
                quote_mint="So11111111111111111111111111111111111111112")


def history(mint: str, ids: set[str], rugged: bool, labelled_at: datetime) -> GradOperator:
    return GradOperator(mint=mint, pool="p", entry_at=labelled_at - timedelta(minutes=5),
                        price_native=Decimal("0.0001"), ids=sorted(ids),
                        label_due_at=labelled_at, rugged=rugged, labelled_at=labelled_at,
                        source="tape")


async def _setup(session) -> None:
    session.add(GradPostgradSample(ts=NOW - timedelta(seconds=30), mint="rate",
                                   source="dexscreener", price_native=Decimal("0.0001"),
                                   price_usd=Decimal("0.01")))
    for key, mint in MINT.items():
        if key == "L":
            continue
        age = 40 if key == "O" else 10
        session.add(GradMigration(mint=mint, ts=NOW - timedelta(seconds=age), pool="pump-amm",
                                  signature=f"sig{key}"))
    hour_ago = NOW - timedelta(hours=1)
    session.add_all([
        history("P1", {"FunderT"}, False, hour_ago),
        history("P2", {"FunderT"}, False, hour_ago),
        history("P3", {"FunderD"}, True, hour_ago),
        history("P4", {"FunderD"}, False, hour_ago),
        history("P5", {"FunderF"}, False, hour_ago),
        history("P6", {"FunderF"}, False, hour_ago),
        # rugged, but its label lands a minute AFTER this tick: not evidence yet
        history("P7", {"FunderF"}, True, NOW + timedelta(minutes=1)),
        # due for its own label now; its pool is down 60%
        GradOperator(mint=MINT["L"], pool="p", entry_at=NOW - timedelta(minutes=5),
                     price_native=Decimal("0.0001"), ids=["WalletL"],
                     label_due_at=NOW - timedelta(seconds=1), source="live"),
    ])
    await session.flush()


def readers():
    by_mint = {MINT[k]: k for k in MINT}
    reads: list[str] = []

    async def pool_reader(mint: str, pool: str) -> Held:
        key = by_mint[mint]
        reads.append(key)
        if key == "L":   # 0.00004 SOL a token: 60% under its 0.0001 entry
            return Held(mint=mint, pool=pool, base_vault="bv", quote_vault="qv",
                        base_decimals=6, quote_decimals=9, base=10**13, quote=400 * 10**9,
                        quote_mint="So11111111111111111111111111111111111111112")
        return held(mint, QUOTE_SOL[key])

    async def operator_reader(mint: str, pool: str) -> frozenset[str] | None:
        ids = IDS[by_mint[mint]]
        return None if ids is None else frozenset(ids)

    return pool_reader, operator_reader, reads


async def test_fast_arms_buy_deep_pools_and_trust_only_clean_operators(db_session) -> None:
    await _setup(db_session)
    pool_reader, operator_reader, reads = readers()
    tournament = Tournament(db_session, now=NOW, pool_reader=pool_reader,
                            operator_reader=operator_reader)
    opened = await tournament._fill_fast()
    await db_session.flush()

    positions = (await db_session.scalars(select(GradPaperPosition))).all()
    books = {(p.book, p.mint) for p in positions}
    key = {v: k for k, v in MINT.items()}
    assert {(b, key[m]) for b, m in books} == {
        ("E75_4m", "A"), ("E75_4m", "B"), ("E75_4m", "C"), ("E75_4m", "U"),
        ("E75T_4m", "A"),   # FunderT: two earlier coins, both clean
        ("E75T_4m", "C"),   # FunderF's rug is not known until a minute from now
    }                        # B: FunderD rugged before; U: unreadable = a stranger
    assert opened == 6
    recorded = {key[m] for m in (await db_session.scalars(
        select(GradOperator.mint).where(GradOperator.source == "live",
                                        GradOperator.mint != MINT["L"]))).all()}
    assert recorded == {"A", "B", "C", "S", "U"}   # S recorded, too shallow to buy
    assert "O" not in reads                           # too old to be an entry
    unread = await db_session.get(GradOperator, MINT["U"])
    assert unread is not None and unread.ids is None


async def test_a_coin_is_labelled_five_minutes_after_entry(db_session) -> None:
    await _setup(db_session)
    pool_reader, operator_reader, _ = readers()
    await Tournament(db_session, now=NOW, pool_reader=pool_reader,
                     operator_reader=operator_reader)._label_operators()
    labelled = await db_session.get(GradOperator, MINT["L"])
    assert labelled.rugged is True and labelled.labelled_at == NOW
    assert labelled.exit_price_native == Decimal("0.000040000000000000")
