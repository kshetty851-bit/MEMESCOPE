"""Buys and sells counted from a pool's own transactions, by window."""
from datetime import UTC, datetime

from app.labs.graduation import fresh_catch_helius as fh

M = "MINT"


def _tx(bt, sol_delta, tok_before, tok_after, err=None):
    bal = lambda amt: [{"mint": M, "owner": "P", "uiTokenAmount": {"uiAmount": amt}}]
    return {"blockTime": bt, "transaction": {"message": {"accountKeys": ["P"]}},
            "meta": {"err": err, "preBalances": [10_000_000_000, 0], "postBalances": [10_000_000_000 - sol_delta, 0],
                     "preTokenBalances": bal(tok_before), "postTokenBalances": bal(tok_after)}}


def test_swaps_and_windows():
    g = datetime.fromtimestamp(1_000, UTC)
    txs = [_tx(1_005, 2_000_000_000, 0, 100),        # buy 2 SOL at 5 s
           _tx(1_015, -500_000_000, 100, 50),        # sell 0.5 SOL at 15 s
           _tx(1_025, 1_000_000_000, 0, 10),         # buy 1 SOL at 25 s
           _tx(1_008, 1_000_000_000, 0, 10, err={"x": 1})]   # failed: ignored
    c = fh.counts(fh.swaps(txs, M), g)
    assert c["10"] == [1, 0, 2.0, 0.0]
    assert c["20"] == [1, 1, 2.0, 0.5]
    assert c["30"] == [2, 1, 3.0, 0.5]
