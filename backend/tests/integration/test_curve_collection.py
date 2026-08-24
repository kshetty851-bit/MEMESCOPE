"""Curve collection end to end: derive, fetch, parse, append, replay.

The RPC is stubbed. That is not a shortcut — the Helius plan is quota
exhausted, so a test that reached the network would fail for a reason unrelated
to the code under test. What is exercised here is everything between the
address and the row.
"""

from __future__ import annotations

import base64
import struct
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.curve import TokenCurveSnapshot
from app.models.market import TradingStatus
from app.repositories.curve import CurveSnapshotRepository
from app.repositories.market import MarketSnapshotRepository
from app.repositories.token import TokenRepository
from app.services.curve.collector import BondingCurveCollector
from app.services.curve.pda import bonding_curve_address
from app.services.helius.client import HeliusError

pytestmark = pytest.mark.integration

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
MINT = "HHbRJ9Fw2tPxETGSsaeQhpgdizfVafLvXK7eo5mwpump"
OTHER = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"

INITIAL_REAL_TOKENS = 793_100_000_000_000
TOTAL_SUPPLY = 1_000_000_000_000_000


def account_bytes(*, real_token: int = INITIAL_REAL_TOKENS, complete: int = 0) -> str:
    """Base64 account data, as `getMultipleAccounts` returns it."""
    raw = (
        b"\x01" * 8
        + struct.pack(
            "<QQQQQ",
            1_073_000_000_000_000,
            30_000_000_000,
            real_token,
            0,
            TOTAL_SUPPLY,
        )
        + bytes([complete])
    )
    return base64.b64encode(raw).decode()


class StubRpc:
    """Records reads and replays canned account values.

    Stands in for a `SolanaRPC`, not for Helius: since Sprint 13 the collector
    asks the interface for a batched account read and never names a vendor, so
    the stub is written against the same surface any node implements.
    """

    def __init__(self, values: list[dict[str, Any] | None] | Exception) -> None:
        self._values = values
        self.calls: list[tuple[str, Any]] = []


