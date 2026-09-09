"""Parsing a GeckoTerminal `new_pools` row into a launch stamp.

Pure, so the shape of the feed is pinned without a network call. The pieces
that have actually bitten: ids arrive network-prefixed, and the fields the
stamp depends on are the ones that must never be silently dropped.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.evmchain.gecko import parse_pool

NOW = datetime(2026, 9, 9, 6, 0, tzinfo=UTC)

ROW = {
    "id": "base_0x26b01abf1034aaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "attributes": {
        "address": "0x26b01abf1034aaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "name": "Arc PRESALE / WETH",
        "pool_created_at": "2026-09-09T05:53:55Z",
        "reserve_in_usd": "0.05036760977",
    },
    "relationships": {
        "base_token": {"data": {"id": "base_0xtoken0000000000000000000000000000000000"}},
        "dex": {"data": {"id": "uniswap-v2-base"}},
    },
}


class TestItKeepsWhatTheStampNeeds:
    def test_the_pool_address_is_stored_bare(self) -> None:
        """Ids come network-prefixed ("base_0x…") and the OHLCV endpoint wants
        the bare address, so a prefixed one would 404 every candle fetch."""
        out = parse_pool(ROW, "base", now=NOW)
        assert out["pool_address"] == "0x26b01abf1034aaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        assert not out["pool_address"].startswith("base_")

    def test_it_records_the_observation_not_a_derivation(self) -> None:
        out = parse_pool(ROW, "base", now=NOW)
        assert out["first_seen_at"] == NOW
        assert out["liquidity_usd_at_sighting"] == Decimal("0.05036760977")
        assert out["pool_created_at"] == datetime(2026, 9, 9, 5, 53, 55, tzinfo=UTC)

    def test_network_is_carried_not_assumed(self) -> None:
        assert parse_pool(ROW, "bsc", now=NOW)["network"] == "bsc"

    def test_base_token_is_unprefixed_too(self) -> None:
        out = parse_pool(ROW, "base", now=NOW)
        assert out["base_token_address"].startswith("0x")


class TestItRefusesWhatItCannotStamp:
    def test_no_address_is_no_row(self) -> None:
        assert parse_pool({"attributes": {}}, "base", now=NOW) is None

    def test_missing_optionals_do_not_raise(self) -> None:
        """A launch with no name, dex, timestamp or liquidity is still a
        launch: the address is the only thing the study cannot work without."""
        out = parse_pool({"id": "base_0xabc"}, "base", now=NOW)
        assert out is not None
        assert out["pool_address"] == "0xabc"
        assert out["name"] is None and out["dex_id"] is None
        assert out["pool_created_at"] is None
        assert out["liquidity_usd_at_sighting"] is None

    def test_a_junk_timestamp_is_dropped_not_guessed(self) -> None:
        row = {"id": "base_0xabc", "attributes": {"pool_created_at": "not-a-date",
                                                  "reserve_in_usd": "n/a"}}
        out = parse_pool(row, "base", now=NOW)
        assert out["pool_created_at"] is None
        assert out["liquidity_usd_at_sighting"] is None
