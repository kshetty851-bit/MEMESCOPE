"""The four places a wrong answer would look like a finding: the decoder, the
fill, anything reading past the entry second, and the gate."""

from __future__ import annotations

import base64
import struct

from app.labs.tape import chain, store, study
from app.security.liquidity import migration_pool_address
from app.services.curve.pda import b58decode
from app.services.scanner.trade_events import (
    BUY_EVENT_DISCRIMINATOR,
    TRADE_EVENT_DISCRIMINATOR,
)

MINT = "Bjsxb2QErbB4rhpSRsUgtNBPPri24R3AK58tQwjvpump"
OTHER = "9Wm4XeBdnSTBWfvKaq2rGa6YDkFBJKBpXcbmVkZ9pump"
POOL = migration_pool_address(MINT, pumpfun_program=chain.PUMPFUN)[0]
OTHER_POOL = migration_pool_address(OTHER, pumpfun_program=chain.PUMPFUN)[0]
ALICE = "EABHq2ZXYCCBUw8LAJTgaMFYPifVm3sBcgicpt29pump"
BOB = "AaCBdbi8DiBvWiSjTG2xkkqeshDCSifsvYqZrkpDpump"
KEY = "an operator's funder"


def _log(payload: bytes) -> str:
    return "Program data: " + base64.b64encode(payload).decode()


def curve_event(user: str, sol: int, tokens: int, vsol: int, vtok: int) -> bytes:
    body = bytearray(TRADE_EVENT_DISCRIMINATOR + bytes(351))
    body[8:40] = b58decode(MINT)
    struct.pack_into("<QQ?", body, 40, sol, tokens, True)
    body[57:89] = b58decode(user)
    struct.pack_into("<QQ", body, 97, vsol, vtok)
    struct.pack_into("<Q", body, 161, 95)
    body[177:209] = b58decode(user)
    struct.pack_into("<Q", body, 209, 30)
    return bytes(body)


def swap_event(pool: str, user: str, base: int, quote: int) -> bytes:
    body = bytearray(BUY_EVENT_DISCRIMINATOR + bytes(473))
    struct.pack_into("<Q", body, 16, base)
    struct.pack_into("<QQQ", body, 64, quote, 20, 0)
    struct.pack_into("<Q", body, 88, 5)
    body[120:152] = b58decode(pool)
    body[152:184] = b58decode(user)
    struct.pack_into("<Q", body, 344, 5)
    return bytes(body)


def balance(owner: str, mint: str, amount: int, index: int) -> dict:
    return {"accountIndex": index, "mint": mint, "owner": owner,
            "uiTokenAmount": {"amount": str(amount)}}


def test_parse_reads_both_programs_and_ignores_other_pools() -> None:
    tx = {"slot": 7, "transactionIndex": 3, "blockTime": 1_000, "meta": {
        "logMessages": [_log(curve_event(ALICE, 85 * 10**9, 793 * 10**12,
                                         115 * 10**9, 280 * 10**12)),
                        _log(swap_event(POOL, BOB, 5 * 10**12, 10**9)),
                        _log(swap_event(OTHER_POOL, BOB, 1, 1))],
        "preTokenBalances": [balance(BOB, MINT, 0, 4)],
        "postTokenBalances": [balance(BOB, MINT, 5 * 10**12, 4),
                              balance(POOL, MINT, 200 * 10**12, 5),
                              balance(POOL, chain.WSOL, 68 * 10**9, 6)]}}
    trades, balances, creator = chain.parse(tx, mint=MINT, pool=POOL)
    assert creator == ALICE
    assert [r[5:8] for r in trades] == [("curve", "buy", ALICE), ("pool", "buy", BOB)]
    curve, swap = trades
    assert curve[8:] == (793 * 10**12, 85 * 10**9, 125, 280 * 10**12, 115 * 10**9)
    assert swap[8:] == (5 * 10**12, 10**9, 30, 200 * 10**12, 68 * 10**9)
    assert {(r[3], r[5]) for r in balances} == {(BOB, 5 * 10**12), (POOL, 200 * 10**12)}


def test_a_swap_with_truncated_logs_still_records_the_pool() -> None:
    tx = {"slot": 1, "transactionIndex": 0, "blockTime": 5, "meta": {
        "logMessages": ["Log truncated"],
        "postTokenBalances": [balance(POOL, MINT, 9, 1), balance(POOL, chain.WSOL, 8, 2)]}}
    trades, _, _ = chain.parse(tx, mint=MINT, pool=POOL)
    assert [(r[5], r[6], r[11], r[12]) for r in trades] == [("pool", "?", 9, 8)]


def test_fills_charge_every_toll_and_never_pay_the_virtual_quote() -> None:
    base, quote, vq = 10**13, 1_000 * 10**9, 17_584_505_288
    tokens = study.buy_tokens(base, quote, vq, 30, study.SIZE)
    back = study.sell_lamports(base, quote, vq, 30, tokens) / study.SIZE - 1
    # 2 x (30 pool + 10 router) bps + 2 x 0.00001 SOL on 0.2 SOL + ~0.02% impact
    assert -0.0088 < back < -0.0080
    assert study.sell_lamports(base, 0, vq, 30, tokens) == -study.NETWORK
    # the tier follows market cap: a $13M coin (130k SOL) pays 30, a fresh pool 125
    assert study.fee_bps((11_650_000 * 10**6, 1_495 * 10**9, None), vq) == 30
    assert study.fee_bps((206_900_000 * 10**6, 67 * 10**9, None), vq) == 125


def _coin(mint: str, t0: int, *, crash: bool, ids: set[str]) -> study.Coin:
    start = (10**13, 1_000 * 10**9, 30)
    end = (10**13 * 3 if crash else 10**13, 300 * 10**9 if crash else 1_000 * 10**9, 30)
    c = study.Coin(mint, POOL, t0, 0, None, "", {t0 + 15: start, t0 + 315: end})
    c.feats = {15: {"ids": ids}}
    return c


def test_reputation_counts_a_rug_only_once_it_has_happened() -> None:
    rug = _coin("A", 1_000, crash=True, ids={KEY})
    early = _coin("B", 1_100, crash=False, ids={KEY})     # enters before A's rug shows
    late = _coin("C", 1_400, crash=False, ids={KEY})
    stranger = _coin("D", 1_400, crash=False, ids={"someone else"})
    study.reputation([rug, early, late, stranger])
    assert (early.feats[15]["rep_n"], early.feats[15]["rep_rugs"]) == (0, 0)
    assert (late.feats[15]["rep_n"], late.feats[15]["rep_rugs"]) == (2, 1)
    assert late.feats[15]["rep_recent_rug"] is True
    assert stranger.feats[15]["rep_n"] == 0


def test_features_never_read_past_the_entry_second() -> None:
    db = store.connect(":memory:")
    t0 = 10_000
    db.execute("INSERT INTO grads (mint,pool,t0,slot,idx,sig,migrator) VALUES (?,?,?,?,?,?,?)",
               (MINT, POOL, t0, 1, 0, "s", ALICE))
    db.executemany("INSERT INTO balances VALUES (?,?,?,?,?,?)", [
        (MINT, 1, 1, ALICE, t0, 793 * 10**12),
        (MINT, 2, 1, BOB, t0 + 1, 190 * 10**12),
        (MINT, 9, 1, ALICE, t0 + 16, 10**12),              # dumps a second after lag 15
    ])
    state = (12 * 10**12, 1_500 * 10**9, 30)
    coin = study.Coin(MINT, POOL, t0, 0, ALICE, ALICE,
                      {t0 + lag: state for lag in chain.ENTRY_LAGS})
    feats = study.tape_features(db, coin, {})
    assert feats[15]["ops_moved"] == 0 and feats[15]["top1"] == 0.793
    assert feats[45]["ops_moved"] > 0.99                 # by 45s the dump is history


def test_gate_needs_every_term() -> None:
    good = {"n": 200, "mean_pct": 1.0, "usd_minus_best_trade": 5.0, "usd_minus_best_day": 3.0,
            "days_positive": "5/7", "control_p": 0.001}
    assert study.gate(good, alpha=0.005)
    for key, bad in (("n", 100), ("mean_pct", -0.1), ("usd_minus_best_trade", -1.0),
                     ("usd_minus_best_day", -1.0), ("days_positive", "3/7"),
                     ("control_p", 0.01)):
        assert not study.gate({**good, key: bad}, alpha=0.005), key


class _Replay:
    """A stand-in for Helius that answers `history` from a fixed list."""

    def __init__(self, txs: list[dict]) -> None:
        self.txs = txs

    async def history(self, *_: object, **__: object):  # type: ignore[no-untyped-def]
        for tx in self.txs:
            yield tx


async def test_a_move_is_the_wallets_own_bag_shrinking() -> None:
    held = 100 * 10**12

    def tx(t: int, pre: int | None, post: int | None) -> dict:
        own = lambda a: [balance(ALICE, MINT, a, 1)] if a is not None else []  # noqa: E731
        return {"blockTime": t, "meta": {"preTokenBalances": own(pre),
                                         "postTokenBalances": own(post)}}

    replay = _Replay([tx(20, None, None),            # a swap that only names the wallet
                      tx(21, held, held),            # its bag untouched
                      tx(22, held, int(held * 0.995)),   # under 1%: not a move
                      tx(23, int(held * 0.995), int(held * 0.98))])
    assert await chain.first_move(replay, MINT, ALICE, held, 16, 255) == (  # type: ignore[arg-type]
        23, int(held * 0.98), False)


def test_the_watch_sells_two_seconds_after_the_first_move() -> None:
    t0 = 1_000
    calm, drained = (10**13, 1_000 * 10**9, None), (10**15, 10 * 10**9, None)
    coin = study.Coin("M", POOL, t0, 0, None, "", {t0 + 15: calm, t0 + 102: calm,
                                                   t0 + 105: drained, t0 + 255: drained})
    coin.moves = [(t0 + 100, 0), (None, 0)]
    assert study.watched(coin, 2) > -0.02          # out at +102s, before the drain
    assert study.watched(coin, 5) < -0.9           # 5s late is too late
    assert study.trade(coin, 15, 240) < -0.9       # holding the full 4 minutes
    coin.moves = [(None, 1)]                       # the watch ran out of pages
    assert study.watched(coin, 2) == study.trade(coin, 15, 240)
