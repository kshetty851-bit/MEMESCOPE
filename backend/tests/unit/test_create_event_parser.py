"""Decoding a launchpad creation event straight from the log stream.

The fixture below is a real `Program data:` line captured from mainnet on
2026-08-03. Using observed bytes rather than a hand-built payload is the point:
the layout was unverified until it was read off the chain, and a fixture written
from the same assumptions the parser makes would prove nothing.

The refusals matter most. This parser runs on attacker-controlled bytes and
decides whether a token exists, so a wrong reading is worse than no reading —
the same contract `curve/state.py` holds at its own boundary.
"""

from __future__ import annotations

import base64
import hashlib
import struct
from datetime import UTC, datetime

import pytest

from app.services.scanner.parser import (
    CREATE_EVENT_DISCRIMINATOR,
    parse_create_event,
)

pytestmark = pytest.mark.unit

#: Captured live from `logsSubscribe` on mainnet, 2026-08-03.
REAL_EVENT = (
    "Program data: G3KpTd7rY3YFAAAAc2VhbHkFAAAAc2VhbHlDAAAAaHR0cHM6Ly9pcGZzLmlvL2lwZnMv"
    "UW1YUk5TRDJmc3FncTFGdGZLSHhKSmdvWXZiNVBSeURoS3NqTlFGNFZvTFFFUEDWXWT6DfE70ocWan1n"
    "rbUMoU8ME79LnAoD0j4+7lEZ5xUTUm01m0qqkuwnqleIXH//r+1i72hHe0dsFbt4pEXS8/oqVRM/opM2"
    "XoQYgyk8FrKL8y8OlLoQOlt2GbTLuNLz+ipVEz+ikzZehBiDKTwWsovzLw6UuhA6W3YZtMu4d+BwagAA"
    "AAAAENhH488DAACsI/wGAAAAAHjF+1HRAgAAgMakfo0DAAbd9uHudY/eGEJdvORszdq2GvxNg7kNJ/69"
    "+SjYoYv8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACsI/wGAAAA"
)

OTHER_LOGS = (
    "Program 6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P invoke [1]",
    "Program log: Instruction: Create",
    "Program log: Instruction: InitializeMint2",
)


def _event(
    *,
    name: str = "sealy",
    symbol: str = "SEAL",
    uri: str = "https://ipfs.io/ipfs/Qm123",
    pubkeys: int = 4,
    timestamp: int | None = 1_785_782_603,
    discriminator: bytes = CREATE_EVENT_DISCRIMINATOR,
) -> str:
    """Build a synthetic `Program data:` line, for cases mainnet will not hand us."""
    body = bytearray(discriminator)
    for text in (name, symbol, uri):
        raw = text.encode("utf-8")
        body += struct.pack("<I", len(raw)) + raw
    body += bytes(range(32)) * pubkeys
    if timestamp is not None:
        body += struct.pack("<q", timestamp)
    return "Program data: " + base64.b64encode(bytes(body)).decode()


class TestRealPayload:
    def test_it_decodes_a_real_mainnet_event(self) -> None:
        """Everything `TokenCreation` needs, plus the metadata that would
        otherwise cost a DAS call — from bytes already in hand."""
        decoded = parse_create_event([*OTHER_LOGS, REAL_EVENT])

        assert decoded is not None
        assert decoded.name == "sealy"
        assert decoded.symbol == "sealy"
        assert decoded.metadata_uri == (
            "https://ipfs.io/ipfs/QmXRNSD2fsqgq1FtfKHxJJgoYvb5PRyDhKsjNQF4VoLQEP"
        )
        assert decoded.mint_address
        assert decoded.creator_address
        assert decoded.block_time is not None
        assert decoded.block_time.tzinfo is not None

    def test_the_discriminator_is_the_anchor_derivation(self) -> None:
        """Pinned as literal bytes for greppability, but it is not a magic
        number — Anchor derives it, and a future event type can be added the
        same way rather than by guessing."""
        assert hashlib.sha256(b"event:CreateEvent").digest()[:8] == CREATE_EVENT_DISCRIMINATOR


class TestExtraction:
    def test_it_reads_past_unrelated_log_lines(self) -> None:
        assert parse_create_event([*OTHER_LOGS, _event()]) is not None

    def test_timestamp_becomes_an_aware_datetime(self) -> None:
        decoded = parse_create_event([_event(timestamp=1_785_782_603)])

        assert decoded is not None
        assert decoded.block_time == datetime(2026, 8, 3, 18, 43, 23, tzinfo=UTC)

    def test_a_missing_timestamp_still_yields_the_mint(self) -> None:
        """The mint is the fact that matters. An older event layout that stops
        short must not cost the token."""
        decoded = parse_create_event([_event(timestamp=None)])

        assert decoded is not None
        assert decoded.mint_address
        assert decoded.block_time is None

    def test_decimals_are_never_invented(self) -> None:
        """These mints are conventionally six decimals. The event does not say
        so, and asserting it would be estimating missing data."""
        decoded = parse_create_event([REAL_EVENT])

        assert decoded is not None
        assert not hasattr(decoded, "decimals")


class TestRefusals:
    def test_no_program_data_line_is_not_an_event(self) -> None:
        assert parse_create_event(OTHER_LOGS) is None

    def test_empty_logs_decode_to_nothing(self) -> None:
        assert parse_create_event([]) is None

    def test_a_different_event_is_skipped_not_misread(self) -> None:
        """A trade event rides the same transaction. Decoding one as the other
        is exactly how a confident, wrong reading gets produced."""
        other = _event(discriminator=bytes.fromhex("aabbccddeeff0011"))

        assert parse_create_event([other]) is None

    def test_an_implausible_string_length_is_refused(self) -> None:
        """A length prefix beyond the bound does not mean a long name — it
        means the offsets moved, and every field after it is garbage."""
        body = bytearray(CREATE_EVENT_DISCRIMINATOR)
        body += struct.pack("<I", 100_000)  # absurd name length
        body += b"x" * 64
        line = "Program data: " + base64.b64encode(bytes(body)).decode()

        assert parse_create_event([line]) is None

    def test_non_utf8_bytes_are_refused_not_replaced(self) -> None:
        """Replacing undecodable bytes would manufacture a readable name out of
        a misread and hide the fault."""
        body = bytearray(CREATE_EVENT_DISCRIMINATOR)
        body += struct.pack("<I", 4) + b"\xff\xfe\xfd\xfc"
        body += bytes(range(32)) * 4
        line = "Program data: " + base64.b64encode(bytes(body)).decode()

        assert parse_create_event([line]) is None

    def test_a_truncated_payload_is_refused(self) -> None:
        """Not enough bytes for the mint means there is no mint to report."""
        assert parse_create_event([_event(pubkeys=1, timestamp=None)]) is None

    def test_an_implausible_timestamp_refuses_the_whole_reading(self) -> None:
        """The strongest single invariant: it is read after three variable
        strings and four keys, so it validates every offset before it."""
        assert parse_create_event([_event(timestamp=1)]) is None
        assert parse_create_event([_event(timestamp=99_999_999_999)]) is None

    def test_malformed_base64_is_skipped(self) -> None:
        assert parse_create_event(["Program data: not!valid!base64!"]) is None


class TestDeterminism:
    def test_the_same_payload_decodes_identically_every_time(self) -> None:
        """Pure by construction — no clock, no network, no randomness — so a
        replay over stored logs reproduces discovery exactly."""
        runs = [parse_create_event([REAL_EVENT]) for _ in range(5)]

        assert all(run == runs[0] for run in runs)
