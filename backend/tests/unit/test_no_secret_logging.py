"""Credentials must never reach a log line.

The failure this guards was real: httpx logs `HTTP Request: POST <url>` at
INFO, RPC endpoints carry their credential IN the URL (Helius in the query
string, Chainstack in the path), and 91 production log lines held live
provider secrets before this was closed.
"""

from __future__ import annotations

import logging

import pytest

from app.core.logging import configure_logging
from app.services.rpc.standard import _redact

pytestmark = pytest.mark.unit


def test_httpx_request_logging_is_silenced():
    configure_logging()
    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("httpcore").level >= logging.WARNING


@pytest.mark.parametrize(
    "url, secret",
    [
        ("https://mainnet.helius-rpc.com/?api-key=SECRET123", "SECRET123"),
        ("https://solana-mainnet.core.chainstack.com/PATHTOKEN456", "PATHTOKEN456"),
        ("https://node.example.com/v1/KEY789/rpc", "KEY789"),
    ],
)
def test_redact_removes_credentials_from_any_position(url, secret):
    redacted = _redact(url)
    assert secret not in redacted
    assert redacted.startswith("https://")


def test_redact_keeps_the_host_so_the_line_stays_useful():
    assert _redact("https://solana-mainnet.core.chainstack.com/tok") == (
        "https://solana-mainnet.core.chainstack.com/***"
    )
