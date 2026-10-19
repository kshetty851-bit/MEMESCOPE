"""The Pool Lab's maths (2026-10-05): ten wallets on one coin pay one after
another, and the per-coin cap admits five."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.labs.graduation import pool_lab as pl

T0 = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


def test_a_later_order_in_the_queue_pays_more():
    first, fifth = pl.queue_k(0, 50), pl.queue_k(4, 50)
    assert (first, fifth) == (0.5, 4.5)
    impact = (0.01, 0.01)
    assert pl.legs_multiple(0.05, impact, 1, 1) == 1.05  # as measured at $100
    assert pl.legs_multiple(0.05, impact, first, first) > pl.legs_multiple(
        0.05, impact, fifth, fifth
    )
    assert pl.legs_multiple(0.05, None, 9, 9) == 1.05  # no recorded impact, no change


def test_the_cap_lets_five_wallets_in_and_they_take_turns():
    coins = [
        (
            T0 + timedelta(minutes=10 * i),
            T0 + timedelta(minutes=10 * i + 5),
            0.10,
            (0.01, 0.01),
        )
        for i in range(2)
    ]
    capped = pl.ten_wallets(coins, 0.0, cap=pl.COIN_CAP)
    assert [w.trades for w in capped] == [1] * 10  # five, then the other five
    uncapped = pl.ten_wallets(coins, 0.0, cap=None)
    assert [w.trades for w in uncapped] == [2] * 10
    # First in line does best on the same coin.
    assert uncapped[0].worth() > uncapped[9].worth()


def test_a_wallet_never_spends_money_it_does_not_have():
    # Eleven overlapping coins on $500 at $50: ten tickets, the eleventh waits.
    coins = [
        (T0 + timedelta(seconds=i), T0 + timedelta(minutes=5), 0.0, None) for i in range(11)
    ]
    wallets = pl.ten_wallets(coins, 0.0, cap=None)
    assert all(w.trades == 10 for w in wallets)
    assert all(abs(w.worth() - pl.WALLET_START) < 1e-9 for w in wallets)


def test_famous_names_are_skipped_and_ordinary_names_are_not():
    for sym in ("OpenAI", "DeepSeek", "GTA 6 Coin", "Elonhotdog", "BARRON", "$TRUMP", "X", "ZuckAI", "MetaMask"):
        assert pl.famous_name(sym), sym
    for sym in ("QE", "CRAWLMASK", "DINK", "HOTJ", "Samurai", "metal", "", None):
        assert not pl.famous_name(sym), sym


def test_ai_names_are_spotted():
    for sym in ("DeepSeek", "OpenAI", "豆包AI", "GrokCoin", "ChatGPT"):
        assert pl.ai_name(sym), sym
    for sym in ("SOULJA", "Tesla", "", None):
        assert not pl.ai_name(sym), sym


def test_entry_window_keeps_19_to_46_seconds():
    from types import SimpleNamespace as N
    g = datetime(2026, 10, 14, tzinfo=UTC)
    at = lambda s: N(opened_at=g + timedelta(seconds=s), graduated_at=g)
    assert not pl.in_entry_window(at(10)) and not pl.in_entry_window(at(47))
    assert pl.in_entry_window(at(19)) and pl.in_entry_window(at(30)) and pl.in_entry_window(at(46))
    assert pl.in_entry_window(N(opened_at=g, graduated_at=None))  # unknown is kept


def test_name_key_matches_spacing_and_case():
    assert pl.name_key("Mr Beast") == pl.name_key("MRBEAST") == pl.name_key("MrBeast") == "mrbeast"
    assert pl.name_key(None) == ""


def test_karthik_stake_by_pool_and_quietness():
    from app.labs.graduation import config

    assert config.karthik_ticket(60_000) == 100.0           # small pool, buys unknown (19 Oct)
    assert config.karthik_ticket(60_000, 13) == 100.0       # small pool, quiet
    assert config.karthik_ticket(60_000, 14) == 100.0       # small pool, busier (19 Oct)
    # The real wallets keep the 16 Oct table.
    assert config.karthik_ticket(60_000, 14, config.WALLET_TICKETS_BY_POOL) == 75.0
    assert config.karthik_ticket(400_000, 3) == 25.0        # large pool, quiet or not


def test_unnamed_evening_is_dubai_17_to_midnight() -> None:
    from types import SimpleNamespace

    from app.labs.graduation import api as gapi
    at = lambda h, m=0: datetime(2026, 10, 16, h, m, tzinfo=UTC)  # noqa: E731 - UTC hour
    row = lambda sym, t: SimpleNamespace(symbol=sym, opened_at=t)  # noqa: E731
    assert gapi._unnamed_evening(row("", at(13)))         # 17:00 Dubai
    assert gapi._unnamed_evening(row(None, at(19, 59)))   # 23:59 Dubai
    assert gapi._unnamed_evening(row("  ", at(15)))
    assert not gapi._unnamed_evening(row("", at(12, 59)))  # 16:59 Dubai
    assert not gapi._unnamed_evening(row("", at(20)))      # 00:00 Dubai
    assert not gapi._unnamed_evening(row("PEPE", at(15)))


def test_karthik_lab_rebuys_a_rugged_name_when_the_ban_is_off(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.labs.graduation import api as gapi
    from app.labs.graduation import config
    t = datetime(2026, 10, 10, 12, tzinfo=UTC)
    rug = SimpleNamespace(symbol="PEPE", mint="a", opened_at=t,
                          closed_at=t + timedelta(minutes=5),
                          net_return=-0.95)
    again = SimpleNamespace(symbol="PEPE", mint="b", opened_at=t + timedelta(hours=1),
                            closed_at=t + timedelta(hours=1, minutes=5), net_return=0.1)
    monkeypatch.setattr(config, "KARTHIK_LAB_RUGGED_NAME_BAN", False)
    assert gapi._without_bad_names([rug, again])[0] == [rug, again]
    monkeypatch.setattr(config, "KARTHIK_LAB_RUGGED_NAME_BAN", True)
    assert gapi._without_bad_names([rug, again])[0] == [rug]


def test_real_wallets_size_like_karthik_lab() -> None:
    from decimal import Decimal

    from app.real_wallet.driver import lab_sized
    d = Decimal
    assert lab_sized("G-Q50", d("50"), 60_000, 13) == d("66.66")      # quiet small coin
    assert lab_sized("G-Q50", d("50"), 60_000, 14) == d("50.00")      # busier small coin
    assert lab_sized("G-Q50", d("50"), 400_000, 3) == d("16.66")      # $150k+ pool
    assert lab_sized("G-Q50", d("50"), None, 3) == d("50")            # pool unread: plain
    assert lab_sized("G-Q150", d("50"), 60_000, 3) == d("50")         # other strategies: plain


def test_lab_name_rules_shared_with_real_wallets() -> None:
    from app.labs.graduation import config
    eve = datetime(2026, 10, 16, 14, tzinfo=UTC)                     # 18:00 Dubai
    assert config.spaced_name("GTA 6 Coin") and not config.spaced_name(" PEPE ")
    assert config.unnamed_evening(None, eve) and config.unnamed_evening("", eve)
    assert not config.unnamed_evening("PEPE", eve)
    assert not config.unnamed_evening(None, eve - timedelta(hours=2))  # 16:00 Dubai


def test_size_grid_stakes_like_the_book() -> None:
    from decimal import Decimal
    from types import SimpleNamespace

    from app.labs.graduation import api as gapi
    t = datetime(2026, 10, 10, 12, tzinfo=UTC)
    rows = [SimpleNamespace(mint=str(i), symbol="X", opened_at=t + timedelta(hours=i),
                            closed_at=t + timedelta(hours=i, minutes=5), net_return=0.10,
                            impact_open=0, impact_close=0, liq_open_usd=80_000)
            for i in range(3)]
    plain = gapi._karthik_whatif(rows, Decimal("200"), capital=600.0, ticket=100.0,
                                 cents=Decimal("0.01"))
    staked = gapi._karthik_whatif(rows, Decimal("200"), capital=600.0, ticket=100.0,
                                  cents=Decimal("0.01"), stake=lambda r: 1.5)
    book = [f["book"] for f in plain["floors"]].index(True)
    row = next(s for s in plain["sizes"] if s["ticket_usd"] == 100)
    row2 = next(s for s in staked["sizes"] if s["ticket_usd"] == 100)
    assert row2["cells"][book]["pnl_usd"] > row["cells"][book]["pnl_usd"] * Decimal("1.4")


def test_open_buy_reads_the_first_minute_only() -> None:
    from decimal import Decimal

    from app.labs.graduation.models import GradOpenBuy
    from app.labs.graduation.open_buys import biggest_open_spend, no_buy_at_open
    tx = lambda t, pre, post: {"blockTime": t, "meta": {"preBalances": [pre], "postBalances": [post]}}  # noqa: E731
    assert biggest_open_spend([tx(100, 70_000_000_000, 5_000_000_000)], 100) == Decimal(65)
    assert biggest_open_spend([tx(100, 1_000_000_000, 900_000_000)], 100) == 0   # 0.1 SOL: no buy
    assert biggest_open_spend([tx(161, 70_000_000_000, 0), None], 100) == 0      # after the minute
    assert no_buy_at_open(GradOpenBuy(mint="a", read=True, open_buy_sol=Decimal(0)))
    assert not no_buy_at_open(GradOpenBuy(mint="a", read=True, open_buy_sol=Decimal(60)))
    assert not no_buy_at_open(GradOpenBuy(mint="a", read=False, open_buy_sol=None))
    assert not no_buy_at_open(None)


def test_real_wallet_reads_the_open_buy_once(monkeypatch) -> None:
    import asyncio
    from decimal import Decimal

    from app.labs.graduation import open_buys
    from app.real_wallet.driver import RealWalletDriver
    calls = []

    async def fake(client, pool):
        calls.append(pool)
        return {"NOBUY": Decimal(0), "BUY": Decimal(60)}.get(pool)
    monkeypatch.setattr(open_buys, "read_pool", fake)
    monkeypatch.setattr("app.labs.graduation.tournament.graduation_pool", lambda m: m)
    open_buys._AT_BUY.clear()
    run = asyncio.run
    assert run(RealWalletDriver._no_open_buy("NOBUY")) is True
    assert run(RealWalletDriver._no_open_buy("BUY")) is False
    assert run(RealWalletDriver._no_open_buy("UNREAD")) is False      # unknown is bought
    assert run(RealWalletDriver._no_open_buy("NOBUY")) is True
    assert calls == ["NOBUY", "BUY", "UNREAD"]                        # answers cached, unread re-asked later


def test_open_buy_needs_every_transaction_read(monkeypatch) -> None:
    import asyncio
    from decimal import Decimal

    from app.labs.graduation import open_buys
    sigs = [{"signature": s, "err": None, "blockTime": 100} for s in ("c", "b", "a")]
    def fake(txs):
        async def rpc(client, method, params):
            if method == "getSignaturesForAddress":
                return sigs
            got = txs[params[0]]
            if got is None:
                raise LookupError(method)
            return {"meta": {"preBalances": [got], "postBalances": [0]}}
        return rpc
    async def no_helius(client, pool):
        return None
    monkeypatch.setattr(open_buys, "_read_helius", no_helius)
    monkeypatch.setattr(open_buys, "_rpc", fake({"a": 1000, "b": None, "c": 70_000_000_000}))
    assert asyncio.run(open_buys.read_pool(None, "p")) == Decimal(70)      # skips the unread one, finds the buy
    monkeypatch.setattr(open_buys, "_rpc", fake({"a": 1000, "b": None, "c": 1000}))
    assert asyncio.run(open_buys.read_pool(None, "p")) is None             # a gap means unknown, not "no buy"
    monkeypatch.setattr(open_buys, "_rpc", fake({"a": 1000, "b": 1000, "c": 1000}))
    assert asyncio.run(open_buys.read_pool(None, "p")) == 0                # all read, none over the floor


def test_open_buy_reads_helius_first(monkeypatch) -> None:
    import asyncio
    from decimal import Decimal

    import httpx

    from app.labs.graduation import open_buys
    tx = lambda t, pre, err=None: {"blockTime": t, "meta": {"err": err, "preBalances": [pre], "postBalances": [0]}}  # noqa: E731
    def client(body):
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=body)))
    monkeypatch.setattr(open_buys.settings, "HELIUS_API_KEY", open_buys.settings.HELIUS_API_KEY.__class__("k"))
    read = lambda body: asyncio.run(open_buys._read_helius(client(body), "p"))  # noqa: E731
    assert read({"result": {"data": [tx(100, 1000), tx(101, 70_000_000_000)]}}) == Decimal(70)
    assert read({"result": {"data": [tx(100, 1000), tx(101, 70_000_000_000, err={"x": 1})]}}) == 0  # a failed tx is no buy
    assert read({"result": {"data": []}}) is None
    assert read({"error": {"code": 429}}) is None          # refused: fall back to the free node
