"""Universe tokens get their `decimals` from the mint account itself.

Without decimals a token cannot be sell-quoted, and a token that cannot be
quoted has no independent price source: ORE printed $974,720 against a real
$58 on 2026-09-09 and nothing contradicted it. 147 of 185 universe tokens
were in that state.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.token import DiscoveredToken
from app.repositories.token import TokenRepository
from app.universe.enrolment import SOURCE_PROGRAM, backfill_decimals

pytestmark = pytest.mark.integration

NOW = datetime.now(UTC)
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"


def _mint_account(decimals: int) -> dict[str, Any]:
    """An 82-byte SPL Mint: no authorities, zero supply, `decimals` at byte 44."""
    raw = bytearray(82)
    raw[44] = decimals
    raw[45] = 1  # is_initialized
    return {"owner": TOKEN_PROGRAM, "data": [base64.b64encode(bytes(raw)).decode(), "base64"]}


class FakeRPC:
    def __init__(self, by_mint: dict[str, dict[str, Any] | None], *, fail: bool = False):
        self.by_mint = by_mint
        self.fail = fail
        self.asked: list[str] = []

    async def start(self) -> None: ...
    async def close(self) -> None: ...

    async def get_multiple_accounts(self, addresses, *, encoding="base64"):
        self.asked = list(addresses)
        if self.fail:
            raise RuntimeError("node down")
        return [self.by_mint.get(a) for a in addresses]


async def _token(session: AsyncSession, mint: str, *, source: str = SOURCE_PROGRAM,
                 decimals: int | None = None) -> None:
    await TokenRepository(session).insert_if_absent({
        "mint_address": mint, "signature": f"universe:{mint}", "slot": 0,
        "discovered_at": NOW - timedelta(days=1), "block_time": NOW - timedelta(days=30),
        "symbol": mint[:6], "source_program": source, "decimals": decimals,
    })


async def _decimals(session: AsyncSession, mint: str) -> int | None:
    return await session.scalar(
        select(DiscoveredToken.decimals).where(DiscoveredToken.mint_address == mint))


class TestDecimalsBackfill:
    async def test_a_universe_token_gets_its_decimals_from_the_mint(
        self, db_session: AsyncSession
    ) -> None:
        mint = "UniverseNoDecimals" + "1" * 26
        await _token(db_session, mint)

        filled = await backfill_decimals(db_session, rpc=FakeRPC({mint: _mint_account(11)}))

        assert filled == 1
        assert await _decimals(db_session, mint) == 11

    async def test_only_universe_tokens_without_decimals_are_asked_for(
        self, db_session: AsyncSession
    ) -> None:
        known = "UniverseKnown" + "1" * 31
        scanner = "ScannerToken" + "1" * 32
        await _token(db_session, known, decimals=6)
        await _token(db_session, scanner, source="pump", decimals=None)
        rpc = FakeRPC({})

        await backfill_decimals(db_session, rpc=rpc)

        assert known not in rpc.asked
        assert scanner not in rpc.asked, "launchpad tokens are sized as 6 already"

    async def test_a_missing_account_or_a_dead_node_leaves_null(
        self, db_session: AsyncSession
    ) -> None:
        """NULL keeps quoting skipped — the safe direction — and enrolment
        must never fail because a read did not happen."""
        gone = "UniverseGone" + "1" * 32
        await _token(db_session, gone)

        assert await backfill_decimals(db_session, rpc=FakeRPC({gone: None})) == 0
        assert await _decimals(db_session, gone) is None
        assert await backfill_decimals(db_session, rpc=FakeRPC({}, fail=True)) == 0
        assert await _decimals(db_session, gone) is None
