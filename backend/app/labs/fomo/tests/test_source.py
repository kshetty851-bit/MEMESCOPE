"""The leaderboard must be a point-in-time 24h roster, and swaps must belong to its wallet."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import httpx
import pytest

from app.labs.fomo import source
from app.labs.fomo.source import WSOL, fetch_swaps, parse_roster, parse_transaction

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


def rawtx(*, token: int, mint: str = MINT, sol: int = 0, wsol: int = 0, err=None,
          owner: str = WALLET, fee: int = 5000, t: int = 1_700_000_000, extra=()) -> dict:
    """A jsonParsed getTransaction where WALLET (fee payer) moves these amounts."""
    def bal(m: str, amount: int) -> dict:
        return {"owner": owner, "mint": m, "uiTokenAmount": {"amount": str(amount)}}

    pre = [bal(mint, 1_000_000), bal(WSOL, 5_000_000_000)]
    post = [bal(mint, 1_000_000 + token), bal(WSOL, 5_000_000_000 + wsol)]
    for m, a in extra:
        pre.append(bal(m, 500))
        post.append(bal(m, 500 + a))
    return {"blockTime": t, "slot": 9, "transaction": {"message": {"accountKeys": [
                {"pubkey": WALLET}, {"pubkey": "pool"}]}},
            "meta": {"err": err, "fee": fee, "preBalances": [10_000_000_000, 1],
                     "postBalances": [10_000_000_000 + sol - fee, 1],
                     "preTokenBalances": pre, "postTokenBalances": post}}


def test_a_swap_is_the_wallets_own_balance_change_paid_for_the_other_way() -> None:
    buy = parse_transaction(rawtx(token=400, sol=-2_000_000_000), WALLET, "b")
    assert (buy.side, buy.mint, buy.sol_amount, buy.signature) == ("buy", MINT, 2.0, "b")
    sell = parse_transaction(rawtx(token=-400, wsol=1_500_000_000), WALLET, "s")
    assert (sell.side, sell.sol_amount) == ("sell", 1.5)          # paid in wrapped SOL
    routed = parse_transaction(rawtx(token=400, extra=[("USDC", -300)]), WALLET, "u")
    assert routed.side == "buy" and routed.sol_amount is None     # paid in another token


def test_transfers_failures_and_other_wallets_are_not_swaps() -> None:
    assert parse_transaction(rawtx(token=400), WALLET, "airdrop") is None        # fee only
    assert parse_transaction(rawtx(token=400, sol=-50_000), WALLET, "dust") is None
    assert parse_transaction(rawtx(token=400, sol=-2_000_000_000, err={"x": 1}),
                             WALLET, "failed") is None
    assert parse_transaction(rawtx(token=400, sol=-2_000_000_000, owner="someone"),
                             WALLET, "theirs") is None
    assert parse_transaction(None, WALLET, "missing") is None


def node(sigs: list[dict], txs: dict[str, object], calls: list) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append((body["method"], body["params"]))
        if body["method"] == "getSignaturesForAddress":
            return httpx.Response(200, json={"result": sigs})
        got = txs.get(body["params"][0])
        if got == 429:
            return httpx.Response(429)
        return httpx.Response(200, json={"result": got})
    return httpx.MockTransport(handle)


def poll(sigs, txs, cursors, calls=None):
    source.READ_PAUSE_S = 0
    calls = [] if calls is None else calls
    client = httpx.AsyncClient(transport=node(sigs, txs, calls))
    return asyncio.run(fetch_swaps(client, "http://node", [WALLET], cursors, now=NOW))


def test_the_bookmark_reads_only_new_transactions_oldest_first(monkeypatch) -> None:
    t = int(NOW.timestamp())
    sigs = [{"signature": "new", "blockTime": t - 10, "err": None},
            {"signature": "old", "blockTime": t - 20, "err": None},
            {"signature": "bad", "blockTime": t - 30, "err": {"x": 1}}]
    txs = {"new": rawtx(token=-400, sol=2_000_000_000, t=t - 10),
           "old": rawtx(token=400, sol=-2_000_000_000, t=t - 20)}
    calls: list = []
    trades, errors, marks = poll(sigs, txs, {WALLET: "prev"}, calls)
    assert [(tr.signature, tr.side) for _, tr in trades] == [("old", "buy"), ("new", "sell")]
    assert errors == {} and marks == {WALLET: "new"}
    assert calls[0] == ("getSignaturesForAddress", [WALLET, {"limit": 100, "until": "prev"}])
    assert [c[1][0] for c in calls[1:]] == ["old", "new"]          # failed tx never fetched
    # Newer wallets sign version-1 transactions; asking for 0 gets -32015.
    assert all(c[1][1]["maxSupportedTransactionVersion"] == 1 for c in calls[1:])


def test_a_failed_read_keeps_what_was_read_and_resumes_there(monkeypatch) -> None:
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    t = int(NOW.timestamp())
    sigs = [{"signature": "b", "blockTime": t - 30, "err": None},
            {"signature": "a", "blockTime": t - 60, "err": None}]
    txs = {"a": rawtx(token=400, sol=-10**9, t=t - 60), "b": 429}
    trades, errors, marks = poll(sigs, txs, {WALLET: "prev"})
    assert [tr.signature for _, tr in trades] == ["a"]
    assert errors == {WALLET: "LookupError"} and marks == {WALLET: "a"}   # b next pass


def test_a_new_wallet_looks_back_ten_minutes_only() -> None:
    t = int(NOW.timestamp())
    sigs = [{"signature": "a", "blockTime": t - 60, "err": None},
            {"signature": "ancient", "blockTime": t - 3600, "err": None}]
    calls: list = []
    trades, _, marks = poll(sigs, {"a": rawtx(token=400, sol=-10**9, t=t - 60)}, {}, calls)
    assert [tr.signature for _, tr in trades] == ["a"] and marks == {WALLET: "a"}
    assert "until" not in calls[0][1][1]
    assert [c[1][0] for c in calls[1:]] == ["a"]                   # an hour old: never read


def test_a_busy_wallet_is_read_a_few_at_a_time() -> None:
    t = int(NOW.timestamp())
    sigs = [{"signature": f"s{i}", "blockTime": t - i, "err": None} for i in range(40)]
    calls: list = []
    _, errors, marks = poll(sigs, {}, {WALLET: "prev"}, calls)
    reads = [c[1][0] for c in calls[1:]]
    assert reads == [f"s{i}" for i in range(39, 39 - source.MAX_READS, -1)]   # oldest first
    assert marks == {WALLET: reads[-1]} and errors == {}


def test_a_full_page_is_flagged_but_still_moves_on() -> None:
    t = int(NOW.timestamp())
    sigs = [{"signature": f"s{i}", "blockTime": t - i, "err": {"x": 1}} for i in range(100)]
    _, errors, marks = poll(sigs, {}, {WALLET: "prev"})
    assert errors == {WALLET: "history_capped"} and marks == {WALLET: "s0"}


async def _no_sleep(*_a, **_k) -> None:
    return None
