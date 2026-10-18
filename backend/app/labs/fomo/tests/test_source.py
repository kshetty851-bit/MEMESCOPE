"""The leaderboard must be a point-in-time 24h roster, and swaps must belong to its wallet."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.labs.fomo.source import parse_roster, parse_swaps

WALLET = "J23qr98GjGJJqKq9CBEnyRhHbmkaVxtTJNNxKu597wsA"
MINT = "So11111111111111111111111111111111111111113"


NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)


def roster() -> dict:
    return {
        "window": "24h",
        "capturedAt": NOW.isoformat(),
        "traders": [
            {
                "rank": n,
                "userId": f"user-{n}",
                "handle": f"trader{n}",
                "wallets": {"solana": WALLET},
                "pnlUsd": 1000 - n,
            }
            for n in range(1, 23)
        ],
    }


def test_roster_does_not_follow_rank_21_or_accept_another_window() -> None:
    leaders = parse_roster(roster(), now=NOW)
    assert len(leaders) == 20
    assert [leader.rank for leader in leaders] == list(range(1, 21))
    wrong = roster()
    wrong["window"] = "7d"
    with pytest.raises(ValueError, match="window"):
        parse_roster(wrong, now=NOW)


def test_missing_solana_wallet_is_not_invented() -> None:
    payload = roster()
    payload["traders"][0]["wallets"] = {"evm": "0xabc"}
    leaders = parse_roster(payload, now=NOW)
    assert len(leaders) == 19
    assert leaders[0].rank == 2


def test_stale_cached_roster_cannot_activate_a_new_book() -> None:
    payload = roster()
    payload["capturedAt"] = "2026-10-18T09:00:00Z"
    with pytest.raises(ValueError, match="stale"):
        parse_roster(payload, now=NOW)


def test_swaps_use_the_traders_own_token_balance_delta() -> None:
    payload = [
        {
            "type": "SWAP",
            "signature": "sig",
            "timestamp": 1_700_000_000,
            "accountData": [
                {
                    "account": WALLET,
                    "tokenBalanceChanges": [
                        {
                            "userAccount": "someone-else",
                            "mint": MINT,
                            "rawTokenAmount": {"tokenAmount": "500"},
                        },
                        {
                            "userAccount": WALLET,
                            "mint": MINT,
                            "rawTokenAmount": {"tokenAmount": "-400"},
                        },
                    ],
                }
            ],
        }
    ]
    trades = parse_swaps(payload, WALLET)
    assert len(trades) == 1
    assert trades[0].side == "sell"
    assert trades[0].mint == MINT


def test_one_signature_is_one_swap_and_a_full_page_is_flagged() -> None:
    import asyncio

    import httpx

    from app.labs.fomo.source import fetch_swaps

    swap = {
        "type": "SWAP",
        "signature": "dup",
        "timestamp": 1_700_000_000,
        "accountData": [{"account": WALLET, "tokenBalanceChanges": [
            {"userAccount": WALLET, "mint": MINT, "rawTokenAmount": {"tokenAmount": "400"}}]}],
    }
    page = [swap] + [{"type": "TRANSFER", "signature": f"t{i}"} for i in range(99)]
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json=page)))
    trades, errors = asyncio.run(fetch_swaps(client, "k", [WALLET]))
    assert [(w, t.signature, t.side) for w, t in trades] == [(WALLET, "dup", "buy")]
    assert errors == {WALLET: "history_capped"}      # 100 rows: older swaps may be hidden
    with pytest.raises(ValueError, match="HELIUS_API_KEY"):
        asyncio.run(fetch_swaps(client, "", [WALLET]))
