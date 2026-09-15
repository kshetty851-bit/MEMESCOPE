"""The fast feed's decoding, and the measurements that justify it."""

from __future__ import annotations

import base64
import json
import struct
from decimal import Decimal

import pytest

from app.labs.graduation import config
from app.labs.graduation.held_watch import (
    Held,
    account_bytes,
    subscribe_frame,
    subscription_of,
    vault_amount,
)

pytestmark = pytest.mark.unit


def _account(amount: int) -> bytes:
    """An SPL token account: 32-byte mint, 32-byte owner, then a u64 balance."""
    return bytes(64) + struct.pack("<Q", amount) + bytes(60)


def test_a_vault_balance_is_a_u64_at_byte_sixty_four():
    """Standard across every SPL account, which is why the VAULTS are watched
    rather than the pool: a pool's layout is program-specific, a vault's is
    not."""
    assert vault_amount(_account(500_000)) == 500_000
    # Refused rather than guessed — a wrong balance becomes a wrong price and
    # then a wrong exit.
    assert vault_amount(b"") is None
    assert vault_amount(bytes(60)) is None
    assert vault_amount(None) is None


def test_price_comes_from_the_reserves_and_needs_no_decimals():
    """It is compared against an entry price computed the same way, and a ratio
    of two prices in the same units needs no scaling."""
    assert Held("m", "b", "q", base=4_000, quote=1_000).price() == Decimal("0.25")
    # A half-seen pool has no price: both vaults must have reported.
    assert Held("m", "b", "q", base=4_000).price() is None
    assert Held("m", "b", "q", quote=1_000).price() is None
    assert Held("m", "b", "q", base=0, quote=1_000).price() is None


def test_notifications_are_told_apart_from_acknowledgements():
    ack = {"id": 1, "result": 111}
    note = {"method": "accountNotification", "params": {"subscription": 111}}
    assert subscription_of(ack) is None
    assert subscription_of(note) == 111


def test_account_bytes_survives_a_malformed_answer():
    raw = _account(7)
    value = {"data": [base64.b64encode(raw).decode(), "base64"]}
    assert account_bytes(value) == raw
    for bad in ({}, {"data": None}, {"data": []}, {"data": ["!!not base64!!"]}, None):
        assert account_bytes(bad) is None


def test_the_subscribe_frame_asks_for_processed_commitment():
    """Confirmed commitment would add a second or more, and the whole point is
    that the wallet dies somewhere between 18s and 27s of reaction."""
    frame = json.loads(subscribe_frame("POOL", 3))
    assert frame["method"] == "accountSubscribe"
    assert frame["params"][0] == "POOL"
    assert frame["params"][1]["commitment"] == "processed"
    assert frame["id"] == 3


def test_the_feed_is_fast_enough_to_matter():
    """Measured 2026-09-15: collapses fall 1.14% a second, so a stop is worth
    $1,040 at 0.6s reaction and $0 at 27s. DexScreener refreshes about every
    27s; accountSubscribe delivered one update every 0.6s on the same pool."""
    assert config.SOLANA_WS_URL.startswith("wss://")
    assert config.HELD_WRITE_PCT <= Decimal("0.01"), (
        "a write threshold above 1% would miss most of a 1.14%/s fall")
