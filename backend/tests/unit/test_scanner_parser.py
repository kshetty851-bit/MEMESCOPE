"""Unit tests for log/transaction parsing.

These cover the shapes that actually break in production: unparsed
instructions, failed transactions, partial DAS responses, and hostile strings
in on-chain metadata.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.services.scanner.parser import (
    extract_fee_payer,
    extract_mint_and_decimals,
    is_token_creation_log,
    parse_asset_metadata,
    parse_log_notification,
    parse_transaction,
)

pytestmark = pytest.mark.unit

MINT = "HHbRJ9Fw2tPxETGSsaeQhpgdizfVafLvXK7eo5mwpump"
CREATOR = "5r1Q8ehbFi4SaF8XLjcNMCdJCEov95wttcmjgk3ncXTr"
SIG = (
    "5APdFocxZdDUbHAU5vyEtSR9gWm21ftvRMh1WHr4ZUNxN38ZGiF3fBAMfLBcThTtkgQVH5NeGQxXxZ9LpXMJDG7g"
)


def _notification(*, logs: list[str], err: object = None, slot: int = 435484419) -> dict:
    return {
        "jsonrpc": "2.0",
        "method": "logsNotification",
        "params": {
            "result": {
                "context": {"slot": slot},
                "value": {"signature": SIG, "err": err, "logs": logs},
            }
        },
    }


def _transaction(*, parsed_mint: bool = True, err: object = None) -> dict:
    inner: list[dict] = []
    if parsed_mint:
        inner = [
            {
                "instructions": [
                    {
                        "parsed": {
                            "type": "initializeMint2",
                            "info": {"decimals": 6, "mint": MINT, "mintAuthority": CREATOR},
                        }
                    }
                ]
            }
        ]
    return {
        "slot": 435484419,
        "blockTime": 1785132741,
        "meta": {
            "err": err,
            "innerInstructions": inner,
            "preTokenBalances": [],
            "postTokenBalances": [{"mint": MINT}],
        },
        "transaction": {
            "message": {
                "accountKeys": [
                    {"pubkey": CREATOR},
                    {"pubkey": "So11111111111111111111111111111111111111112"},
                ],
                "instructions": [],
            }
        },
    }


# --- Log filtering -----------------------------------------------------------


def test_creation_log_is_detected() -> None:
    assert is_token_creation_log(["Program log: Instruction: InitializeMint2"])


def test_ordinary_transfer_log_is_ignored() -> None:
    assert not is_token_creation_log(
        ["Program log: Instruction: TransferChecked", "Program log: Instruction: Buy"]
    )


def test_empty_logs_are_ignored() -> None:
    assert not is_token_creation_log([])


# --- Notification parsing ----------------------------------------------------


def test_parse_notification_extracts_signature_and_slot() -> None:
    event = parse_log_notification(_notification(logs=["Instruction: InitializeMint2"]))
    assert event is not None
    assert event.signature == SIG
    assert event.slot == 435484419


def test_failed_transactions_are_skipped() -> None:
    """A reverted mint never existed, so it must not enter the pipeline."""
    assert (
        parse_log_notification(_notification(logs=["x"], err={"InstructionError": []})) is None
    )


@pytest.mark.parametrize(
    "message",
    [
        {},
        {"params": None},
        {"params": {"result": None}},
        {"params": {"result": {"value": None}}},
        {"params": {"result": {"value": {"logs": []}}}},  # no signature
    ],
)
def test_malformed_notifications_return_none(message: dict) -> None:
    assert parse_log_notification(message) is None


# --- Transaction parsing -----------------------------------------------------


def test_mint_and_decimals_from_parsed_instruction() -> None:
    mint, decimals = extract_mint_and_decimals(_transaction())
    assert mint == MINT
    assert decimals == 6


def test_mint_falls_back_to_balance_diff_when_unparsed() -> None:
    """Some RPC nodes return unparsed instructions; the mint is still derivable."""
    mint, decimals = extract_mint_and_decimals(_transaction(parsed_mint=False))
    assert mint == MINT
    assert decimals is None


def test_balance_diff_is_ambiguous_with_multiple_new_mints() -> None:
    tx = _transaction(parsed_mint=False)
    tx["meta"]["postTokenBalances"] = [
        {"mint": MINT},
        {"mint": "OtherMint1111111111111111111"},
    ]
    assert extract_mint_and_decimals(tx) == (None, None)


def test_fee_payer_is_the_creator() -> None:
    assert extract_fee_payer(_transaction()) == CREATOR


def test_fee_payer_handles_plain_string_keys() -> None:
    tx = _transaction()
    tx["transaction"]["message"]["accountKeys"] = [CREATOR]
    assert extract_fee_payer(tx) == CREATOR


def test_parse_transaction_builds_full_creation() -> None:
    creation = parse_transaction(_transaction(), signature=SIG, source_program="pump")
    assert creation is not None
    assert creation.mint_address == MINT
    assert creation.creator_address == CREATOR
    assert creation.decimals == 6
    assert creation.slot == 435484419
    # Derived from the fixture's blockTime rather than hardcoded, so the
    # assertion cannot drift from the input.
    assert creation.block_time == datetime.fromtimestamp(1785132741, tz=UTC)
    assert creation.source_program == "pump"


def test_parse_transaction_rejects_failed_transaction() -> None:
    assert parse_transaction(_transaction(err={"e": 1}), signature=SIG) is None


def test_parse_transaction_returns_none_without_a_mint() -> None:
    tx = _transaction(parsed_mint=False)
    tx["meta"]["postTokenBalances"] = []
    assert parse_transaction(tx, signature=SIG) is None


# --- Metadata parsing --------------------------------------------------------


def test_parse_asset_metadata_reads_all_fields() -> None:
    metadata = parse_asset_metadata(
        {
            "content": {
                "json_uri": "https://ipfs.io/ipfs/abc",
                "metadata": {"name": "Indian Batman", "symbol": "JEETMAN"},
            },
            "token_info": {"decimals": 6},
        }
    )
    assert metadata.name == "Indian Batman"
    assert metadata.symbol == "JEETMAN"
    assert metadata.metadata_uri == "https://ipfs.io/ipfs/abc"
    assert metadata.decimals == 6


@pytest.mark.parametrize("asset", [{}, {"content": {}}, {"content": {"metadata": {}}}])
def test_partial_metadata_never_raises(asset: dict) -> None:
    """Partial DAS responses are normal seconds after launch."""
    metadata = parse_asset_metadata(asset)
    assert metadata.name is None
    assert metadata.symbol is None


def test_metadata_strips_nul_padding_and_truncates() -> None:
    """On-chain strings are attacker-controlled and NUL-padded."""
    metadata = parse_asset_metadata(
        {"content": {"metadata": {"name": "Evil\x00\x00  ", "symbol": "S" * 500}}}
    )
    assert metadata.name == "Evil"
    assert metadata.symbol is not None
    assert len(metadata.symbol) == 64


def test_blank_metadata_becomes_none() -> None:
    metadata = parse_asset_metadata({"content": {"metadata": {"name": "   ", "symbol": ""}}})
    assert metadata.name is None
    assert metadata.symbol is None
