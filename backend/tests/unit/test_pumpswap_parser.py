"""Decoding PumpSwap pool creations, and recovering creations from blocks.

The `Program data:` fixture below is a real `CreatePoolEvent` captured from
mainnet on 2026-08-20 (transaction `i1ttRbEpVkZ…`, the creation of pool
`8A3DaQpw8CPz4t9zqDyHDwCmkqREkPYgBE6X4eYHKmJE`). Using observed bytes rather
than a hand-built payload is the point: the field offsets were unverified until
they were read off the chain and matched against the pool's known base mint,
WSOL quote, and the transaction's own blockTime.

The refusal cases matter most. A pool-creation transaction *does* contain an
`InitializeMint2` — for the pool's LP mint — so a parser that falls back to
generic mint extraction would confidently discover the wrong token.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime

import pytest

from app.services.scanner.parser import (
    PUMPSWAP_CREATE_POOL_DISCRIMINATOR,
    creation_events_from_block,
    is_token_creation_log,
    parse_pumpswap_pool_event,
)

pytestmark = pytest.mark.unit

#: Captured from mainnet, 2026-08-20. Base mint GPAVdWsS…empump, quote WSOL,
#: timestamp 1785435005 (== the transaction's blockTime), base decimals 6.
REAL_POOL_EVENT = (
    "Program data: sTEM0qB2p3R9k2tqAAAAAAAAb1lHjxrQJygJTFqP2FynymNf4w43fFwc6WfTxRtppCbk"
    "jNDvtXhbVWja26Ao0buo+1pJO3SRdk8EVqAKl5P4rwabiFf+q4GE+2h/Y0YYwDXaxDncGus7VZig8AAA"
    "AAABBgkACAGpLLwAAHmBAQYAAAAAAAgBqSy8AAB5gQEGAAAAAGQAAAAAAAAAM0YlniEAAADPRSWeIQAA"
    "APtqUorW7VGK/0w5TGxWUxEcz0V7X2scyiT1QAdp+u+nB/ZOVE3kSWeciuGN3vsnN8WgHI5P3uTxqwC4"
    "GsfR6XiD4xGr/VfyfxB4V6KhBjA/lnXObQAPRESiQlMjHqb2oRcV8yLNCDen9Qtk+Y/4EzcfTEsSq3bl"
    "2qdO/NkL5SvpdhI5W9EbTXr1u2K/qTuVPjcoJfr7QQ76/xjB5CCRXl2lAQ=="
)

EXPECTED_MINT = "GPAVdWsSJhoJhE7ZbcWc4ffNHAbBZRP58jujb1empump"
EXPECTED_BLOCK_TIME = datetime.fromtimestamp(1_785_435_005, tz=UTC)

PAMM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"

POOL_CREATION_LOGS = (
    f"Program {PAMM} invoke [1]",
    "Program log: Instruction: CreatePool",
    "Program log: Instruction: InitializeMint2",
    REAL_POOL_EVENT,
)


def test_discriminator_derivation_matches_the_pinned_bytes() -> None:
    assert hashlib.sha256(b"event:CreatePoolEvent").digest()[:8] == (
        PUMPSWAP_CREATE_POOL_DISCRIMINATOR
    )


class TestParsePumpswapPoolEvent:
    def test_decodes_the_real_mainnet_event(self) -> None:
        decoded = parse_pumpswap_pool_event(POOL_CREATION_LOGS)

        assert decoded is not None
        assert decoded.mint_address == EXPECTED_MINT
        assert decoded.block_time == EXPECTED_BLOCK_TIME
        assert decoded.decimals == 6
        # The pool carries no token metadata; the token stays PENDING.
        assert decoded.name is None
        assert decoded.symbol is None
        assert decoded.metadata_uri is None

    def test_absent_event_returns_none(self) -> None:
        assert parse_pumpswap_pool_event(("Program log: Instruction: Buy",)) is None

    def test_a_truncated_payload_is_refused(self) -> None:
        raw = base64.b64decode(REAL_POOL_EVENT[len("Program data: ") :])
        truncated = base64.b64encode(raw[:40]).decode()
        assert parse_pumpswap_pool_event((f"Program data: {truncated}",)) is None

    def test_an_implausible_timestamp_is_refused(self) -> None:
        """The timestamp validates the offsets; garbage there means every
        pubkey after it is garbage too."""
        raw = bytearray(base64.b64decode(REAL_POOL_EVENT[len("Program data: ") :]))
        raw[8:16] = (99_999_999_999).to_bytes(8, "little")
        mangled = base64.b64encode(bytes(raw)).decode()
        assert parse_pumpswap_pool_event((f"Program data: {mangled}",)) is None

    @staticmethod
    def _swapped_orientation() -> str:
        """The real event with base and quote sides exchanged — the WSOL-base
        orientation observed live on mainnet (e.g. tx `58yoMt9ifmf…`)."""
        raw = bytearray(base64.b64decode(REAL_POOL_EVENT[len("Program data: ") :]))
        raw[50:82], raw[82:114] = raw[82:114], raw[50:82]
        raw[114], raw[115] = raw[115], raw[114]
        return "Program data: " + base64.b64encode(bytes(raw)).decode()

    def test_a_wsol_base_pool_yields_the_quote_side_token(self) -> None:
        """Both pool orientations occur on mainnet; the launched token is the
        non-WSOL side, whichever side that is."""
        decoded = parse_pumpswap_pool_event((self._swapped_orientation(),))

        assert decoded is not None
        assert decoded.mint_address == EXPECTED_MINT
        assert decoded.decimals == 6

    def test_a_pool_with_wsol_on_neither_side_is_refused(self) -> None:
        """Without WSOL to anchor the orientation, which side launched cannot
        be attributed — and SOL itself must never be reported as a token."""
        raw = bytearray(base64.b64decode(REAL_POOL_EVENT[len("Program data: ") :]))
        raw[82:114] = raw[50:82]  # quote becomes a copy of the base token
        mangled = base64.b64encode(bytes(raw)).decode()
        assert parse_pumpswap_pool_event((f"Program data: {mangled}",)) is None

    def test_pool_creation_logs_pass_the_stream_prefilter(self) -> None:
        assert is_token_creation_log(POOL_CREATION_LOGS)
        assert is_token_creation_log(("Program log: Instruction: CreatePool",))
        assert not is_token_creation_log(("Program log: Instruction: Buy",))


class TestCreationEventsFromBlock:
    """Gap recovery reads `getBlock` results through the live pre-filter."""

    @staticmethod
    def _block(*transactions: dict) -> dict:
        return {"transactions": list(transactions)}

    @staticmethod
    def _tx(signature: str, logs: tuple[str, ...], *, err: object = None) -> dict:
        return {
            "meta": {"err": err, "logMessages": list(logs)},
            "transaction": {"signatures": [signature]},
        }

    def test_extracts_a_creation_attributed_to_the_watched_program(self) -> None:
        observed_at = datetime(2026, 8, 20, tzinfo=UTC)
        block = self._block(
            self._tx("sig-created", POOL_CREATION_LOGS),
            self._tx("sig-trade", ("Program log: Instruction: Buy",)),
        )

        events = creation_events_from_block(
            block, slot=123, programs=[PAMM], observed_at=observed_at
        )

        assert [event.signature for event in events] == ["sig-created"]
        assert events[0].slot == 123
        assert events[0].source_program == PAMM
        assert events[0].replayed is True
        assert events[0].observed_at == observed_at

    def test_a_failed_transaction_created_nothing(self) -> None:
        block = self._block(
            self._tx("sig-reverted", POOL_CREATION_LOGS, err={"InstructionError": []})
        )
        assert (
            creation_events_from_block(
                block, slot=1, programs=[PAMM], observed_at=datetime.now(UTC)
            )
            == []
        )

    def test_a_creation_by_an_unwatched_program_is_skipped(self) -> None:
        """Mirrors the live subscription: provenance must be attributable to a
        watched program, never guessed."""
        logs = (
            "Program SomeOtherProgram11111111111111111111111111 invoke [1]",
            "Program log: Instruction: InitializeMint2",
        )
        block = self._block(self._tx("sig-other", logs))
        assert (
            creation_events_from_block(
                block, slot=1, programs=[PAMM], observed_at=datetime.now(UTC)
            )
            == []
        )
