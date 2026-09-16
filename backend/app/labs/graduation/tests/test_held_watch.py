"""The fast feed's decoding, and the measurements that justify it."""

from __future__ import annotations

import asyncio
import base64
import json
import struct
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.labs.graduation import config
from app.labs.graduation import held_watch as held_watch_module
from app.labs.graduation.held_watch import (
    EarlyWatch,
    Held,
    MarkWriter,
    account_bytes,
    mint_decimals,
    notification,
    pool_among,
    subscribe_frame,
    subscription_of,
    transaction_accounts,
    vault_amount,
    vault_mint,
    watch,
)
from app.labs.graduation.sources import HeldVaultStream
from app.security.liquidity import PoolState, b58encode

pytestmark = pytest.mark.unit

TOKEN, SOL = bytes([7]) * 32, bytes([9]) * 32
TOKEN_MINT, SOL_MINT = b58encode(TOKEN), b58encode(SOL)
T0 = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


def _account(amount: int, mint: bytes = TOKEN) -> bytes:
    """An SPL token account: 32-byte mint, 32-byte owner, then a u64 balance."""
    return mint + bytes(32) + struct.pack("<Q", amount) + bytes(93)


def _mint(decimals: int, *, initialized: bool = True) -> bytes:
    """An SPL mint: authority option and supply, then decimals at byte 44."""
    return bytes(44) + bytes([decimals, int(initialized)]) + bytes(36)


def _pool(base_mint: str = TOKEN_MINT) -> PoolState:
    return PoolState(creator="c", base_mint=base_mint, quote_mint=SOL_MINT,
                     lp_mint="lp", base_vault="BASEVAULT", quote_vault="QUOTEVAULT",
                     lp_supply_field=0, pool_bump=0, index=0)


def _held(mint: str = TOKEN_MINT, **kw) -> Held:
    return Held(mint=mint, pool=f"pool-{mint}", base_vault=f"{mint}-base",
                quote_vault=f"{mint}-quote", base_decimals=6, quote_decimals=9, **kw)


def test_a_vault_balance_is_a_u64_at_byte_sixty_four():
    """Standard across every SPL account, which is why the VAULTS are watched
    rather than the pool: a pool's layout is program-specific, a vault's is
    not."""
    assert vault_amount(_account(500_000)) == 500_000
    assert vault_mint(_account(1, SOL)) == SOL_MINT
    # Refused rather than guessed — a wrong balance becomes a wrong price and
    # then a wrong exit.
    for bad in (b"", bytes(60), None):
        assert vault_amount(bad) is None
        assert vault_mint(bad) is None


def test_the_units_error_that_shipped_is_gone():
    """2026-09-15, sVkL4MXW, calm trading: the socket wrote 0.011580703 while
    DexScreener said 0.00001161 — 997.5x, because a pump.fun token carries 6
    decimals and wrapped SOL 9. It put FLOOR_4m_SL at $17,517 in twenty
    minutes. The same reserves, scaled, land within 0.3% of DexScreener."""
    raw_ratio, dexscreener = Decimal("0.011580703455030981"), Decimal("0.00001161")
    base = 38_297_000_000_000
    held = _held(base=base, quote=int(base * raw_ratio))
    assert abs(held.price() / dexscreener - 1) < Decimal("0.003")
    assert round(Decimal(held.quote) / held.base / dexscreener) == 997
    # A half-seen pool has no price: both vaults must have reported.
    assert _held(base=4_000).price() is None
    assert _held(quote=1_000).price() is None
    assert _held(base=0, quote=1_000).price() is None


def test_depth_is_both_sides_at_spot():
    """What DexScreener calls liquidity. 443.5 SOL a side at $101.46 is the
    $90k it reported for sVkL4MXW; without depth an exit pays no impact."""
    held = _held(base=1, quote=443_500_000_000)
    assert held.depth_usd(Decimal("101.46")) == Decimal("89995.02")
    assert _held().depth_usd(Decimal(100)) is None
    assert held.depth_usd(Decimal(0)) is None


def test_decimals_come_off_the_mint_account():
    assert mint_decimals(_mint(6)) == 6
    assert mint_decimals(_mint(9) + bytes(200)) == 9   # Token-2022 extensions
    assert mint_decimals(_mint(6, initialized=False)) is None
    assert mint_decimals(bytes(81)) is None
    assert mint_decimals(None) is None


def test_a_pool_is_watched_only_once_every_fact_is_proven():
    accounts = [_mint(6), _mint(9), _account(1, TOKEN), _account(1, SOL)]
    held = watch(TOKEN_MINT, "POOL", _pool(), accounts)
    assert held is not None
    assert (held.base_decimals, held.quote_decimals) == (6, 9)
    assert (held.pool, held.base_vault, held.quote_vault) == (
        "POOL", "BASEVAULT", "QUOTEVAULT")
    # The token on the QUOTE side would invert every price.
    assert watch(TOKEN_MINT, "POOL", _pool(base_mint=SOL_MINT), accounts) is None
    # A vault holding some other mint is not this pool's vault.
    swapped = [_mint(6), _mint(9), _account(1, SOL), _account(1, TOKEN)]
    assert watch(TOKEN_MINT, "POOL", _pool(), swapped) is None
    # Decimals that could not be read are never guessed.
    unreadable = [None, _mint(9), _account(1, TOKEN), _account(1, SOL)]
    assert watch(TOKEN_MINT, "POOL", _pool(), unreadable) is None
    assert watch(TOKEN_MINT, "POOL", None, accounts) is None
    assert watch(TOKEN_MINT, "POOL", _pool(), accounts[:3]) is None


def test_an_older_slot_never_rewinds_the_price():
    """The socket and a direct read both deliver balances, not always in
    order."""
    held = _held(base=100, quote=100)
    assert held.apply("base", 200, slot=50)
    assert not held.apply("base", 999, slot=49)
    assert held.base == 200
    assert held.apply("quote", 300, slot=50)     # the other side, same slot
    assert held.quote == 300


def test_a_first_price_is_checked_before_anything_is_written():
    writer = MarkWriter()
    dex = Decimal("0.000000613")
    # Nothing to check against: nothing written.
    assert writer.decide("m", dex, None, T0) == "unchecked"
    # 1,000x ABOVE is the error that shipped: profits that did not exist.
    assert writer.decide("m", dex * 1000, dex, T0) == "wrong_scale"
    assert writer.decide("m", dex * Decimal("2.01"), dex, T0) == "wrong_scale"
    assert "m" not in writer.trusted
    # 17% below DexScreener is HONEST: measured 2026-09-16 on a fresh
    # graduate, with depth 9.4% below — and 0.906² = 0.821.
    assert writer.decide("m", Decimal("0.0000005081198"), dex, T0) == "write"
    # Once proven, the scale is not re-litigated: a rug is supposed to put
    # the socket far below a lagging DexScreener.
    assert writer.decide("m", dex / 50, dex, T0 + timedelta(seconds=1)) == "write"


def test_a_rug_is_never_refused_as_a_scale_error():
    """D9W99Lzd, 2026-09-16: the pool drained to 0.2382 SOL ($46 of depth)
    while DexScreener sat frozen at 1.79e-8 with $1,756 for minutes. The node's
    own parser agreed with the socket to four places. Refusing that price —
    which a two-sided check did, three times, live — would have marked a dead
    position 75x above what it could sell for."""
    writer = MarkWriter()
    socket, dexscreener = Decimal("2.394612E-10"), Decimal("1.79E-8")
    assert writer.decide("D9W99Lzd", socket, dexscreener, T0) == "write"


def test_writes_are_throttled_but_never_starved():
    writer = MarkWriter(trusted={"m"})
    p = Decimal("0.000001")
    assert writer.decide("m", p, None, T0) == "write"
    # A small move inside the interval waits; a big one does not.
    assert writer.decide("m", p * Decimal("1.001"), None, T0 + timedelta(seconds=1)) == "hold"
    assert writer.decide("m", p * Decimal("1.01"), None, T0 + timedelta(seconds=1)) == "write"
    later = T0 + timedelta(seconds=1)
    # Any change is written once the interval has passed.
    small = p * Decimal("1.011")
    assert writer.decide("m", small, None, later + timedelta(
        seconds=config.HELD_INTERVAL_S)) == "write"
    # An unchanged price is re-written only on the heartbeat, which is what
    # keeps a quiet pool's mark inside the book's trust window.
    at = later + timedelta(seconds=config.HELD_INTERVAL_S)
    assert writer.decide("m", small, None, at + timedelta(seconds=5)) == "hold"
    assert writer.decide("m", small, None, at + timedelta(
        seconds=config.HELD_HEARTBEAT_S)) == "write"
    assert config.HELD_HEARTBEAT_S * 3 <= config.HELD_TRUST_S
    writer.keep([])
    assert not writer.trusted and not writer.last


def test_notifications_are_told_apart_from_acknowledgements():
    ack = {"id": 1, "result": 111}
    note = {"method": "accountNotification", "params": {"subscription": 111}}
    assert subscription_of(ack) is None
    assert subscription_of(note) == 111
    assert notification(note) is None           # no balance, no slot
    assert notification(_note(111, 42, slot=7)) == (111, 42, 7)


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
    assert config.HELD_WRITE_ENABLED


# --- the socket ---------------------------------------------------------------

def _note(sub: int, amount: int, *, slot: int) -> dict:
    return {"jsonrpc": "2.0", "method": "accountNotification", "params": {
        "subscription": sub, "result": {
            "context": {"slot": slot},
            "value": {"data": [base64.b64encode(_account(amount)).decode(), "base64"]}}}}


class FakeSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.inbox: asyncio.Queue[str] = asyncio.Queue()
        self.options: dict = {}

    def connect(self, url: str, **options) -> FakeSocket:
        self.options = options
        return self

    async def __aenter__(self) -> FakeSocket:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def send(self, frame: str) -> None:
        self.sent.append(json.loads(frame))

    async def recv(self) -> str:
        return await self.inbox.get()

    def methods(self, name: str) -> list[dict]:
        return [f for f in self.sent if f["method"] == name]

    async def reply(self, frame: dict, result: object) -> None:
        await self.inbox.put(json.dumps({"jsonrpc": "2.0", "id": frame["id"],
                                         "result": result}))


async def _until(check, seconds: float = 4.0) -> None:
    for _ in range(int(seconds / 0.02)):
        if check():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition never held")


def _stream(sock: FakeSocket, reads: list) -> HeldVaultStream:
    stream = HeldVaultStream(url="wss://node", connect=sock.connect, now=lambda: T0)

    async def accounts(addresses):
        reads.append(list(addresses))
        # 2 SOL against 4M tokens, for every pool asked about.
        return 100, [_account(4_000_000_000_000), _account(2_000_000_000, SOL)] * (
            len(addresses) // 2)

    stream.accounts = accounts
    return stream


async def test_the_socket_follows_the_held_set_without_reconnecting():
    """The first version subscribed once and re-read the held set only when
    the socket dropped, so in its twenty live minutes it watched ONE token
    while the book traded dozens. The set changes about once a minute."""
    sock, reads, prices = FakeSocket(), [], []
    stream = _stream(sock, reads)
    first, second = _held("A"), _held("B")
    wanted = {"A": first}

    async def on_price(held, ts):
        prices.append((held.mint, held.price()))

    task = asyncio.create_task(stream.stream(lambda: wanted, on_price))
    try:
        await _until(lambda: len(sock.methods("accountSubscribe")) == 2)
        assert sock.options["ping_interval"] == config.HELD_PING_S
        # Read at once, so the first price does not wait for a trade.
        await _until(lambda: prices)
        assert reads[0] == ["A-base", "A-quote"]
        assert prices == [("A", Decimal("0.0000005"))]
        for frame, sub in zip(sock.methods("accountSubscribe"), (11, 12), strict=True):
            await sock.reply(frame, sub)
        # A trade: the token side shrinks at a newer slot, price rises.
        await sock.inbox.put(json.dumps(_note(11, 2_000_000_000_000, slot=101)))
        await _until(lambda: len(prices) == 2)
        assert prices[-1] == ("A", Decimal("0.000001"))
        # A stale notification is ignored rather than rewinding the price.
        await sock.inbox.put(json.dumps(_note(11, 4_000_000_000_000, slot=99)))
        # The position closes and another opens — on the SAME socket.
        wanted.clear()
        wanted["B"] = second
        await _until(lambda: len(sock.methods("accountUnsubscribe")) == 2)
        assert sorted(f["params"][0] for f in sock.methods("accountUnsubscribe")) == [11, 12]
        assert {f["params"][0] for f in sock.methods("accountSubscribe")[2:]} == {
            "B-base", "B-quote"}
        await _until(lambda: prices[-1][0] == "B")
        assert [m for m, _ in prices].count("A") == 2
        # A notification for the dropped pool moves nothing.
        await sock.inbox.put(json.dumps(_note(12, 1, slot=500)))
        await asyncio.sleep(0.1)
        assert [m for m, _ in prices].count("A") == 2
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_a_quiet_pool_is_read_not_assumed(monkeypatch):
    """A pool cannot change price without its vaults changing, so silence on a
    healthy subscription is an unchanged price. "Healthy" is proven by a read
    every heartbeat — a dead subscription must not assert a frozen price."""
    monkeypatch.setattr(config, "HELD_HEARTBEAT_S", 1)
    sock, reads, prices = FakeSocket(), [], []
    stream = _stream(sock, reads)

    async def on_price(held, ts):
        prices.append(held.mint)

    task = asyncio.create_task(stream.stream(lambda: {"A": _held("A")}, on_price))
    try:
        await _until(lambda: len(reads) >= 3, seconds=6)
        assert all(r == ["A-base", "A-quote"] for r in reads)
        assert len(prices) >= 3
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


async def test_a_refused_subscription_drops_the_socket():
    """A pool that never subscribed would sit on its seed price for ever, so a
    refusal ends the socket and the caller reconnects."""
    sock = FakeSocket()
    stream = _stream(sock, [])

    async def on_price(held, ts):
        return None

    task = asyncio.create_task(stream.stream(lambda: {"A": _held("A")}, on_price))
    await _until(lambda: sock.methods("accountSubscribe"))
    frame = sock.methods("accountSubscribe")[0]
    await sock.inbox.put(json.dumps({"jsonrpc": "2.0", "id": frame["id"],
                                     "error": {"code": -32602, "message": "no"}}))
    with pytest.raises(RuntimeError, match="refused"):
        await asyncio.wait_for(task, 3)


async def test_an_unanswered_read_is_retried_not_cached_as_unwatchable():
    """A None is cached for the life of the position. One dropped request must
    not leave a position on minute-old marks until it closes."""
    stream = HeldVaultStream(url="wss://node")

    async def silent(addresses):
        return 0, [None] * len(addresses)

    async def empty(addresses):
        return 42, [None] * len(addresses)    # answered: no such account

    stream.accounts = silent
    with pytest.raises(ConnectionError):
        await stream.resolve(TOKEN_MINT, "POOL")
    stream.accounts = empty
    assert await stream.resolve(TOKEN_MINT, "POOL") is None


# --- the early arm's watch ----------------------------------------------------

def _early() -> EarlyWatch:
    return EarlyWatch(floor_usd=Decimal("198000"), window_s=90)


def _sol_quoted(**kw) -> Held:
    return _held(quote_mint=config.WSOL_MINT, **kw)


def test_the_early_watch_records_the_first_reading_deep_enough():
    """A pump.fun pool opens around 85 SOL a side — $17,000 of depth at $100 —
    so B3's $198k is a pool that has since filled. The first reading that
    shows it is the entry, and it is taken once."""
    watch = _early()
    watch.add(TOKEN_MINT, T0, "sig")
    shallow = _sol_quoted(base=206_900_000_000_000, quote=85_000_000_000)
    assert watch.observe(shallow, Decimal(100), T0 + timedelta(seconds=3)) is None
    deep = _sol_quoted(base=17_000_000_000_000, quote=1_000_000_000_000)
    row = watch.observe(deep, Decimal(100), T0 + timedelta(seconds=40))
    assert row is not None
    assert (row["migrated_at"], row["crossed_at"]) == (T0, T0 + timedelta(seconds=40))
    assert row["depth_usd"] == Decimal("200000")
    assert row["price_native"] == deep.price()
    assert (row["first_seen_at"], row["first_depth_usd"]) == (
        T0 + timedelta(seconds=3), Decimal("17000"))
    assert watch.observe(deep, Decimal(100), T0 + timedelta(seconds=41)) is None
    assert TOKEN_MINT not in watch.due and TOKEN_MINT not in watch.first


def test_the_early_watch_refuses_what_it_cannot_price_or_is_too_late_for():
    watch = _early()
    watch.add(TOKEN_MINT, T0, "sig")
    deep = _sol_quoted(base=1, quote=1_000_000_000_000)
    usdc = _held(base=1, quote=1_000_000_000_000, quote_mint="USDC")
    assert watch.observe(usdc, Decimal(100), T0) is None        # not SOL-quoted
    assert watch.observe(deep, None, T0) is None                # no SOL rate yet
    assert watch.observe(deep, Decimal(100), T0 + timedelta(seconds=91)) is None
    assert watch.expire(T0 + timedelta(seconds=91)) == [TOKEN_MINT]
    assert not watch.due
    assert _early().observe(deep, Decimal(100), T0) is None     # never registered


def test_a_transaction_names_its_static_and_loaded_accounts():
    tx = {"transaction": {"message": {"accountKeys": ["A", "B"]}},
          "meta": {"loadedAddresses": {"writable": ["C"], "readonly": ["D"]}}}
    assert transaction_accounts(tx) == ["A", "B", "C", "D"]
    for bad in (None, {}, {"transaction": {}}, "x"):
        assert transaction_accounts(bad) == []


def test_the_pool_is_the_one_account_whose_base_is_this_mint(monkeypatch):
    from types import SimpleNamespace

    decoded = {b"pool": SimpleNamespace(base_mint=TOKEN_MINT),
               b"other": SimpleNamespace(base_mint=SOL_MINT)}
    monkeypatch.setattr(held_watch_module, "parse_pool", decoded.get)
    assert pool_among(TOKEN_MINT, ["K1", "K2", "K3"], [b"x", b"pool", b"other"]) == "K2"
    assert pool_among(TOKEN_MINT, ["K1"], [b"other"]) is None
    # Two pools for one mint is a guess, and a guess is refused.
    assert pool_among(TOKEN_MINT, ["K1", "K2"], [b"pool", b"pool"]) is None


async def test_the_pool_comes_from_the_migrations_own_transaction(monkeypatch):
    """Deriving the address matched DexScreener's pool for 0 of 146 recent
    graduations; the migration transaction's accounts matched 10 of 10."""
    from types import SimpleNamespace

    stream = HeldVaultStream(url="wss://node")
    keys = [f"K{i}" for i in range(150)]
    txs = {"sig": {"transaction": {"message": {"accountKeys": keys}}}}
    reads: list[int] = []

    async def call(method, params):
        assert method == "getTransaction"
        assert params[1]["maxSupportedTransactionVersion"] == 0
        return txs.get(params[0])

    async def accounts(batch):
        reads.append(len(batch))
        return 7, [b"pool" if k == "K120" else b"x" for k in batch]

    decoded = {b"pool": SimpleNamespace(base_mint=TOKEN_MINT)}
    monkeypatch.setattr(held_watch_module, "parse_pool", decoded.get)
    stream._call = call
    stream.accounts = accounts
    assert await stream.pool_from_migration(TOKEN_MINT, "sig") == "K120"
    assert reads == [100, 50]                   # the node's 100-account limit
    decoded.clear()
    assert await stream.pool_from_migration(TOKEN_MINT, "sig") is None
    with pytest.raises(ConnectionError):        # too new to read: ask again
        await stream.pool_from_migration(TOKEN_MINT, "not-yet")
