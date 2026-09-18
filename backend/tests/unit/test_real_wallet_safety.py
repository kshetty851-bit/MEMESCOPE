"""Fail-closed regression coverage for the future execution safety boundary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.market import TradingStatus
from app.paper.execution import ExecutionQuote, ExecutionQuoteUnavailableError
from app.real_wallet_safety import service
from app.real_wallet_safety.service import (
    PUMP_FUN_PROGRAM,
    PUMPSWAP_PROGRAM,
    TOKEN_2022_PROGRAM,
    VERIFIED_DISCOVERY_PROGRAMS,
    RealWalletSafetyGate,
    Reason,
    TokenInspection,
)
from app.services.rpc.base import RpcError

pytestmark = pytest.mark.unit

MINT = "HHbRJ9Fw2tPxETGSsaeQhpgdizfVafLvXK7eo5mwpump"
NOW = datetime(2026, 8, 9, tzinfo=UTC)
UNSET = object()


def _quote(*, side: str, output: str, impact: str = "1") -> ExecutionQuote:
    is_buy = side == "entry"
    return ExecutionQuote(
        side=side,
        model_version="jupiter_quote_v2",
        quoted_at=NOW,
        latency_ms=Decimal("1"),
        input_mint="USDC" if is_buy else MINT,
        output_mint=MINT if is_buy else "USDC",
        input_amount_raw="100000000",
        output_amount_raw=output,
        input_decimals=6,
        output_decimals=6,
        input_amount=Decimal("100"),
        output_amount=Decimal(output) / Decimal(1_000_000),
        input_amount_usd=Decimal("100") if is_buy else None,
        output_amount_usd=None if is_buy else Decimal(output) / Decimal(1_000_000),
        estimated_price_usd=Decimal("1"),
        price_impact_pct=Decimal(impact),
        context_slot=1,
        platform_fee_usd=Decimal(0),
        route="PumpSwap",
        amms=("PumpSwap",),
        raw={"inAmount": "100000000", "outAmount": output},
    )


class _Quotes:
    def __init__(
        self, buy: ExecutionQuote | Exception, sell: ExecutionQuote | Exception
    ) -> None:
        self.buy = buy
        self.sell = sell

    async def buy_quote(self, **_: object) -> ExecutionQuote:
        if isinstance(self.buy, Exception):
            raise self.buy
        return self.buy

    async def sell_quote(self, **_: object) -> ExecutionQuote:
        if isinstance(self.sell, Exception):
            raise self.sell
        return self.sell


class _Gate(RealWalletSafetyGate):
    #: Whole-token supply the fake chain reports. The default is large enough
    #: that the $100 test position is a rounding error against it, so the supply
    #: cap never fires by accident; tests that mean to trip it pass their own.
    #: `None` means the read failed, which REFUSES — an unmeasured concentration
    #: has not been shown to be small.
    supply: Decimal | None = Decimal("1000000000")

    def __init__(self, inspection: TokenInspection, quotes: _Quotes,
                 supply: Decimal | None = Decimal("1000000000")) -> None:
        super().__init__(
            SimpleNamespace(add=lambda _: None, flush=self._flush), jupiter=quotes
        )  # type: ignore[arg-type]
        self.inspection = inspection
        self.supply = supply
        gate = self

        class _SupplyRPC:
            #: The real client must be started before use and closed after —
            #: `get_rpc()` returns a NEW, UNSTARTED one every call. The double
            #: carries them so the production start/close is exercised here
            #: rather than only discovered against a live node.
            started = 0

            async def start(self):
                type(self).started += 1

            async def close(self): ...

            async def get_token_supply(self, mint_address: str):
                assert type(self).started, "supply read before start()"
                return gate.supply

        self._rpc = _SupplyRPC()  # type: ignore[assignment]

    async def _flush(self) -> None: ...

    async def _inspect_mint(self, mint: str) -> TokenInspection:
        return self.inspection


    async def _persist(self, decision: service.SafetyDecision) -> service.SafetyDecision:
        return decision


def _inspection(**overrides: object) -> TokenInspection:
    values: dict[str, object] = {
        "token_program": TOKEN_2022_PROGRAM,
        "decimals": 6,
        "mint_authority_active": False,
        "freeze_authority_active": False,
        "extensions": (18, 19),
        "raw": {},
    }
    values.update(overrides)
    return TokenInspection(**values)  # type: ignore[arg-type]


def _token() -> SimpleNamespace:
    return SimpleNamespace(source_program=PUMP_FUN_PROGRAM, signature="sig", slot=1)


def _snapshot(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "captured_at": NOW,
        "dex_name": "pumpswap",
        "price_usd": Decimal("1"),
        "liquidity_usd": Decimal("100000"),
        "trading_status": TradingStatus.TRADING,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


async def _decision(
    monkeypatch: pytest.MonkeyPatch,
    *,
    inspection: TokenInspection | None = None,
    quotes: _Quotes | None = None,
    token: object = UNSET,
    snapshot: object = UNSET,
    supply: Decimal | None = Decimal("1000000000"),
) -> service.SafetyDecision:
    token_row = _token() if token is UNSET else token
    snapshot_row = _snapshot() if snapshot is UNSET else snapshot
    monkeypatch.setattr(
        service,
        "TokenRepository",
        lambda _: SimpleNamespace(get_by_mint=lambda __: _return(token_row)),
    )
    monkeypatch.setattr(
        service,
        "MarketSnapshotRepository",
        lambda _: SimpleNamespace(latest_for_mint=lambda __: _return(snapshot_row)),
    )
    gate = _Gate(
        inspection or _inspection(),
        quotes
        or _Quotes(
            _quote(side="entry", output="100000000"), _quote(side="exit", output="98000000")
        ),
        supply=supply,
    )
    return await gate.evaluate(mint_address=MINT, trade_size_usd=Decimal("100"), now=NOW)


async def _return(value: object) -> object:
    return value


async def test_all_mandatory_checks_pass_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    decision = await _decision(monkeypatch)
    assert decision.decision == "ALLOW"
    assert decision.reason_codes == ()


async def test_buyable_but_unsellable_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    decision = await _decision(
        monkeypatch,
        quotes=_Quotes(
            _quote(side="entry", output="100000000"),
            ExecutionQuoteUnavailableError("no route"),
        ),
    )
    assert decision.decision == "REJECT"
    assert Reason.SELL_ROUTE_UNAVAILABLE in decision.reason_codes


@pytest.mark.parametrize(
    ("buy_impact", "sell_impact", "expected"),
    [
        ("6", "1", Reason.BUY_PRICE_IMPACT_TOO_HIGH),
        ("1", "6", Reason.SELL_PRICE_IMPACT_TOO_HIGH),
    ],
)
async def test_directional_impact_rejects(
    monkeypatch: pytest.MonkeyPatch, buy_impact: str, sell_impact: str, expected: str
) -> None:
    decision = await _decision(
        monkeypatch,
        quotes=_Quotes(
            _quote(side="entry", output="100000000", impact=buy_impact),
            _quote(side="exit", output="98000000", impact=sell_impact),
        ),
    )
    assert expected in decision.reason_codes


async def test_excessive_round_trip_loss_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    decision = await _decision(
        monkeypatch,
        quotes=_Quotes(
            _quote(side="entry", output="100000000"), _quote(side="exit", output="85000000")
        ),
    )
    assert Reason.ROUND_TRIP_LOSS_TOO_HIGH in decision.reason_codes


async def test_stale_market_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    decision = await _decision(
        monkeypatch, snapshot=_snapshot(captured_at=NOW - timedelta(minutes=2))
    )
    assert Reason.MARKET_DATA_STALE in decision.reason_codes


async def test_unknown_provenance_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    decision = await _decision(
        monkeypatch, token=SimpleNamespace(source_program="other", signature="sig", slot=1)
    )
    assert Reason.PROVENANCE_UNVERIFIED in decision.reason_codes


class TestProvenanceAcceptsEveryRecognisedDiscoveryProgram:
    """Widened from pump.fun-only on 2026-08-27.

    A V6 Lab strategy trading deep pools ($500k+) is by construction trading
    GRADUATED tokens, and those are discovered by the PumpSwap program rather
    than pump.fun's. Every one of them failed provenance and the real wallet
    could not touch the strategy at all -- while the rest of the stack, LP
    custody included (`PUMPSWAP_MIGRATED_LP_BURNED`), had been built for
    graduated pools all along.

    The tests below are deliberately lopsided: one proves the gate opened, four
    prove it did not open any further than intended.
    """

    async def test_a_graduated_pumpswap_token_is_verified(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The fix. Same scanner, same chain, same signature and slot -- the
        only difference is which on-chain event was witnessed."""
        decision = await _decision(
            monkeypatch,
            token=SimpleNamespace(
                source_program=PUMPSWAP_PROGRAM, signature="sig", slot=1
            ),
        )
        assert Reason.PROVENANCE_UNVERIFIED not in decision.reason_codes

    async def test_pump_fun_is_still_verified(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression: widening must not swap one program for another."""
        decision = await _decision(
            monkeypatch,
            token=SimpleNamespace(
                source_program=PUMP_FUN_PROGRAM, signature="sig", slot=1
            ),
        )
        assert Reason.PROVENANCE_UNVERIFIED not in decision.reason_codes

    async def test_a_third_partys_word_is_still_not_provenance(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`jupiter_verified` carries slot 0 -- nobody here watched it happen.

        This is the case the whole check exists for, and the one most likely to
        be waved through by anyone widening the gate in a hurry: it is real,
        it trades, and a reputable third party vouches for it. It is still
        somebody else's evidence.
        """
        decision = await _decision(
            monkeypatch,
            token=SimpleNamespace(
                source_program="jupiter_verified", signature="sig", slot=0
            ),
        )
        assert Reason.PROVENANCE_UNVERIFIED in decision.reason_codes

    async def test_a_recognised_program_without_a_slot_still_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Being on the list is necessary, not sufficient. No slot means the
        observation was never anchored to a block."""
        decision = await _decision(
            monkeypatch,
            token=SimpleNamespace(
                source_program=PUMPSWAP_PROGRAM, signature="sig", slot=0
            ),
        )
        assert Reason.PROVENANCE_UNVERIFIED in decision.reason_codes

    async def test_a_recognised_program_without_a_signature_still_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        decision = await _decision(
            monkeypatch,
            token=SimpleNamespace(
                source_program=PUMPSWAP_PROGRAM, signature=None, slot=1
            ),
        )
        assert Reason.PROVENANCE_UNVERIFIED in decision.reason_codes

    def test_the_accepted_set_is_exactly_two_programs(self) -> None:
        """Pinned. A third entry is a decision about where real money may go,
        and it should fail a test rather than arrive quietly in a diff."""
        assert VERIFIED_DISCOVERY_PROGRAMS == frozenset(
            {PUMP_FUN_PROGRAM, PUMPSWAP_PROGRAM}
        )


async def test_missing_market_data_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    decision = await _decision(monkeypatch, snapshot=None)
    assert Reason.MARKET_DATA_MISSING in decision.reason_codes


async def test_rpc_inspection_failure_rejects(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = _Gate(
        _inspection(),
        _Quotes(
            _quote(side="entry", output="100000000"), _quote(side="exit", output="98000000")
        ),
    )

    async def unavailable(_: str) -> TokenInspection:
        raise RpcError("RPC unavailable")

    monkeypatch.setattr(gate, "_inspect_mint", unavailable)
    monkeypatch.setattr(
        service,
        "TokenRepository",
        lambda _: SimpleNamespace(get_by_mint=lambda __: _return(_token())),
    )
    monkeypatch.setattr(
        service,
        "MarketSnapshotRepository",
        lambda _: SimpleNamespace(latest_for_mint=lambda __: _return(_snapshot())),
    )
    decision = await gate.evaluate(mint_address=MINT, trade_size_usd=Decimal("100"), now=NOW)
    assert Reason.TOKEN_CONFIGURATION_UNKNOWN in decision.reason_codes


@pytest.mark.parametrize(
    "inspection,expected",
    [
        (_inspection(extensions=(18, 99)), Reason.UNSUPPORTED_TOKEN_EXTENSION),
        (_inspection(token_program="unsupported"), Reason.UNSUPPORTED_TOKEN_PROGRAM),
        (_inspection(mint_authority_active=True), Reason.MINT_AUTHORITY_ACTIVE),
        (_inspection(freeze_authority_active=True), Reason.FREEZE_AUTHORITY_ACTIVE),
    ],
)
async def test_unsafe_token_configuration_rejects(
    monkeypatch: pytest.MonkeyPatch, inspection: TokenInspection, expected: str
) -> None:
    decision = await _decision(monkeypatch, inspection=inspection)
    assert expected in decision.reason_codes


def test_token_2022_mint_decoder_reads_authorities_and_extensions() -> None:
    raw = bytearray(83 + 4 + 2)
    raw[44] = 6
    raw[82] = 1  # Mint account type
    raw[83:85] = (18).to_bytes(2, "little")
    raw[85:87] = (2).to_bytes(2, "little")
    raw[87:89] = b"xx"
    encoded = __import__("base64").b64encode(bytes(raw)).decode()
    inspection = service.decode_mint_account(
        {"owner": TOKEN_2022_PROGRAM, "data": [encoded, "base64"]}
    )
    assert inspection.decimals == 6
    assert inspection.extensions == (18,)
    assert inspection.mint_authority_active is False
    assert inspection.freeze_authority_active is False


async def test_a_position_over_three_percent_of_supply_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Liquidity decides whether a position can be SOLD; supply decides how much
    of the token you become. A deep pool will happily fill an order that leaves
    you holding a tenth of everything in existence, and the exit price for that
    is not the entry price."""
    # $100 at the fixture's price buys a quantity that is >3% of this supply.
    decision = await _decision(monkeypatch, supply=Decimal("1000"))
    assert decision.decision == "REJECT"
    assert service.Reason.POSITION_TOO_LARGE_FOR_SUPPLY in decision.reason_codes
    assert decision.position_supply_ratio is not None
    assert decision.position_supply_ratio > Decimal("0.03")


async def test_a_position_inside_the_supply_cap_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decision = await _decision(monkeypatch, supply=Decimal("1000000000"))
    assert service.Reason.POSITION_TOO_LARGE_FOR_SUPPLY not in decision.reason_codes
    assert decision.token_supply == Decimal("1000000000")


async def test_an_unreadable_supply_refuses_rather_than_assuming_it_is_small(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`None` means the read did not happen, never that the supply is zero. A
    concentration cap that cannot measure concentration has not shown the
    position to be small, and every other unmeasured fact in this rail refuses."""
    decision = await _decision(monkeypatch, supply=None)
    assert decision.decision == "REJECT"
    assert service.Reason.TOKEN_SUPPLY_UNREADABLE in decision.reason_codes
    assert decision.position_supply_ratio is None


async def test_the_supply_cap_is_the_configured_three_percent() -> None:
    from app.core.config import settings

    assert settings.REAL_WALLET_SAFETY_MAX_SUPPLY_RATIO == Decimal("0.03")
    # Both concentration caps are kept: they answer different questions.
    assert settings.REAL_WALLET_SAFETY_MAX_POSITION_LIQUIDITY_RATIO == Decimal("0.01")


def test_every_rpc_implementation_can_read_a_token_supply():
    """A default that silently disables a check is worse than no check.

    `FallbackRPC` inherited the abstract base's `None`, which the concentration
    cap reads as "unreadable" and therefore REFUSES. Every token failed the gate
    for a fact nobody could measure — fail-closed, so nothing unsafe shipped, but
    nothing tradeable either, and the report said TOKEN_SUPPLY_UNREADABLE rather
    than "this call is not implemented here".
    """
    import inspect

    from app.services.rpc.base import SolanaRPC
    from app.services.rpc.router import FallbackRPC
    from app.services.rpc.standard import StandardSolanaRPC

    base = inspect.getsource(SolanaRPC.get_token_supply)
    for impl in (StandardSolanaRPC, FallbackRPC):
        own = inspect.getsource(impl.get_token_supply)
        assert own != base, f"{impl.__name__} inherits the refusing default"
        assert "getTokenSupply" in own, impl.__name__


# --- who already holds the coin, at the buy ------------------------------------

SUPPLY_RAW = 10**15  # pump.fun: 1B tokens, 6 decimals


def _pct(p: str) -> int:
    return int(Decimal(p) * SUPPLY_RAW / 100)


class _Helius:
    """One coin's chain. `bags` are (owner, raw amount, owned by a program);
    `funders` maps a wallet to the account that first paid SOL into it."""

    def __init__(self, bags: list[tuple[str, int, bool]], *, fail: bool = False,
                 mint: str = MINT, funders: dict[str, str] | None = None) -> None:
        self.bags, self.fail, self.started, self.mint = bags, fail, 0, mint
        self.funders = funders or {}

    async def start(self) -> None:
        self.started += 1

    async def close(self) -> None: ...

    async def call(self, method: str, params: list) -> dict:
        assert self.started, "holder read before start()"
        if self.fail:
            raise RpcError("getTokenLargestAccounts rate limited")
        if method == "getTransactionsForAddress":
            wallet = params[0]
            if wallet not in self.funders:
                return {"data": []}
            return {"data": [{
                "transaction": {"message": {"accountKeys": [
                    {"pubkey": self.funders[wallet]}, {"pubkey": wallet}]}},
                "meta": {"preBalances": [9_000_000_000, 0],
                         "postBalances": [7_999_995_000, 1_000_000_000]}}]}
        if method == "getTokenLargestAccounts":
            return {"value": [{"address": f"acct{i}", "amount": str(a)}
                              for i, (_, a, _) in enumerate(self.bags)]}
        keys = params[0]
        if keys[0] == self.mint:  # the mint, then each token account
            return {"value": [{"data": {"parsed": {"info": {"supply": str(SUPPLY_RAW)}}}}]
                    + [{"data": {"parsed": {"info": {"owner": o}}}} for o, _, _ in self.bags]}
        program = {o: p for o, _, p in self.bags}
        return {"value": [{"owner": PUMPSWAP_PROGRAM if program[k]
                           else "11111111111111111111111111111111"} for k in keys]}


async def _holder_decision(
    monkeypatch: pytest.MonkeyPatch, chain: _Helius, *, enabled: bool = True
) -> service.SafetyDecision:
    from app.core.config import settings

    monkeypatch.setattr(settings, "REAL_WALLET_HOLDER_GATE_ENABLED", enabled)
    monkeypatch.setattr(settings, "REAL_WALLET_MAX_HOLDER_PCT", Decimal("10"))
    monkeypatch.setattr(service, "TokenRepository",
                        lambda _: SimpleNamespace(get_by_mint=lambda __: _return(_token())))
    monkeypatch.setattr(service, "MarketSnapshotRepository",
                        lambda _: SimpleNamespace(latest_for_mint=lambda __: _return(_snapshot())))
    gate = _Gate(_inspection(), _Quotes(_quote(side="entry", output="100000000"),
                                        _quote(side="exit", output="98000000")))
    gate._holders_rpc = chain  # type: ignore[assignment]
    return await gate.evaluate(mint_address=MINT, trade_size_usd=Decimal("100"), now=NOW)


async def test_a_wallet_already_holding_a_sixth_of_the_coin_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SUUB, 2026-09-18: one wallet held 16.94% when the wallet bought, beside a
    pool of 3.54%, did not move for three minutes, then dumped for -82%."""
    chain = _Helius([("Whale", _pct("16.94"), False), ("PoolPDA", _pct("3.54"), True),
                     ("Small", _pct("0.40"), False)])
    decision = await _holder_decision(monkeypatch, chain)
    assert decision.decision == "REJECT"
    assert decision.reason_codes == (Reason.HOLDER_TOO_LARGE,)
    assert decision.provenance["holders"]["top_pct"] == "16.94"
    assert decision.provenance["holders"]["pool_pct"] == "3.54"


async def test_holders_under_the_line_do_not_refuse(monkeypatch: pytest.MonkeyPatch) -> None:
    chain = _Helius([("Holder", _pct("7.01"), False), ("PoolPDA", _pct("3.52"), True)])
    decision = await _holder_decision(monkeypatch, chain)
    assert decision.decision == "ALLOW", decision.reason_codes


async def test_an_unreadable_holder_list_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    decision = await _holder_decision(monkeypatch, _Helius([], fail=True))
    assert decision.reason_codes == (Reason.HOLDERS_UNREADABLE,)


async def test_the_holder_check_is_off_unless_switched_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _Helius([("Whale", _pct("40"), False)])
    decision = await _holder_decision(monkeypatch, chain, enabled=False)
    assert decision.decision == "ALLOW"
    assert chain.started == 0, "Helius asked while the check is off"


async def test_the_pool_is_found_by_its_owner_not_an_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pool is the biggest account on a fresh coin. Counted as a wallet it
    would refuse every buy; it is told apart by being a program's account."""
    chain = _Helius([("PoolPDA", _pct("45"), True), ("Holder", _pct("4"), False)])
    decision = await _holder_decision(monkeypatch, chain)
    assert decision.decision == "ALLOW", decision.reason_codes


async def test_one_wallets_several_accounts_are_one_bag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _Helius([("Whale", _pct("6"), False), ("Whale", _pct("6"), False),
                     ("PoolPDA", _pct("3"), True)])
    decision = await _holder_decision(monkeypatch, chain)
    assert decision.reason_codes == (Reason.HOLDER_TOO_LARGE,)


def test_bags_split_evenly_are_counted_as_a_bundle() -> None:
    """16 Sep: pairs and fours of near-identical bags, sold together."""
    from app.real_wallet_safety.holders import Holders

    h = Holders(supply=SUPPLY_RAW, pool=_pct("3.3"), latency_ms=1,
                wallets=(("A", _pct("1.26")), ("B", _pct("1.259")), ("C", _pct("0.30"))))
    assert h.pct(h.bundle) == Decimal("2.519")
    assert Holders(supply=SUPPLY_RAW, pool=None, latency_ms=1,
                   wallets=(("A", _pct("2")), ("B", _pct("1.5")))).bundle == 0


def test_the_pool_rules_only_refuse_when_given_a_line() -> None:
    from app.real_wallet_safety.holders import Holders, reasons

    h = Holders(supply=SUPPLY_RAW, pool=_pct("1.5"), latency_ms=1,
                wallets=(("A", _pct("7")), ("B", _pct("3")), ("C", _pct("2.99"))))
    assert reasons(h, max_pct=Decimal("10")) == []
    assert reasons(h, max_pct=Decimal("10"), max_vs_pool=Decimal("1"),
                   max_bundle_vs_pool=Decimal("1")) == [
        "HOLDER_BIGGER_THAN_POOL", "BUNDLE_BIGGER_THAN_POOL"]


# The money-source block: after a rug, the wallets and funders behind it are
# blocked for a few hours. A fresh coin always has the same shape (the curve
# buyer, the pool buyer, the pool), so the chain below is that shape.
_COIN = [("CurveBuyer", _pct("79.31"), False), ("PoolBuyer", _pct("17.01"), False),
         ("PoolPDA", _pct("3.68"), True)]
_FUNDED = {"CurveBuyer": "FunderA", "PoolBuyer": "FunderB"}


async def _source_decision(
    monkeypatch: pytest.MonkeyPatch, chain: _Helius, *, blocked: set[str],
    enabled: bool = True,
) -> service.SafetyDecision:
    from app.core.config import settings

    asked: list[object] = []

    async def recent_rug_ids(session, *, since, rug_return):
        asked.append((since, rug_return))
        return blocked

    monkeypatch.setattr(settings, "REAL_WALLET_HOLDER_GATE_ENABLED", False)
    monkeypatch.setattr(settings, "REAL_WALLET_SOURCE_BLOCK_ENABLED", enabled)
    monkeypatch.setattr(settings, "REAL_WALLET_SOURCE_BLOCK_HOURS", 3)
    monkeypatch.setattr(service.sources, "recent_rug_ids", recent_rug_ids)
    monkeypatch.setattr(service, "TokenRepository",
                        lambda _: SimpleNamespace(get_by_mint=lambda __: _return(_token())))
    monkeypatch.setattr(
        service, "MarketSnapshotRepository",
        lambda _: SimpleNamespace(latest_for_mint=lambda __: _return(_snapshot())))
    gate = _Gate(_inspection(), _Quotes(_quote(side="entry", output="100000000"),
                                        _quote(side="exit", output="98000000")))
    gate._holders_rpc = chain  # type: ignore[assignment]
    decision = await gate.evaluate(mint_address=MINT, trade_size_usd=Decimal("100"), now=NOW)
    if enabled:
        assert asked == [(NOW - timedelta(hours=3), settings.REAL_WALLET_RUG_RETURN)]
    else:
        assert not asked, "rugs looked up while the block is off"
    return decision


async def test_a_coin_funded_by_the_money_behind_a_recent_rug_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SUUB then SOLCAT, 18 Sep: new wallets, the same two funders, both rugs."""
    chain = _Helius(_COIN, funders=_FUNDED)
    decision = await _source_decision(monkeypatch, chain, blocked={"FunderB", "Elsewhere"})
    assert decision.decision == "REJECT"
    assert decision.reason_codes == (Reason.LINKED_TO_RECENT_RUG,)
    assert decision.provenance["sources"] == {
        "recent_rug_ids": 2, "wallets": ["CurveBuyer", "PoolBuyer"],
        "funders": ["FunderA", "FunderB"], "matched": ["FunderB"]}


async def test_a_wallet_that_was_itself_behind_a_recent_rug_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _Helius(_COIN, funders=_FUNDED)
    decision = await _source_decision(monkeypatch, chain, blocked={"CurveBuyer"})
    assert decision.reason_codes == (Reason.LINKED_TO_RECENT_RUG,)


async def test_the_pool_is_never_one_of_the_wallets_traced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pool's own account is not a wallet: blocking it would block the coin
    for having a pool."""
    chain = _Helius([("PoolPDA", _pct("40"), True), ("CurveBuyer", _pct("55"), False)],
                    funders=_FUNDED)
    decision = await _source_decision(monkeypatch, chain, blocked={"PoolPDA"})
    assert decision.decision == "ALLOW", decision.reason_codes
    assert decision.provenance["sources"]["wallets"] == ["CurveBuyer"]


async def test_money_behind_no_recent_rug_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    chain = _Helius(_COIN, funders=_FUNDED)
    decision = await _source_decision(monkeypatch, chain, blocked={"SomeoneElse"})
    assert decision.decision == "ALLOW", decision.reason_codes
    assert decision.provenance["sources"]["matched"] == []


async def test_with_no_recent_rug_a_failed_read_lets_the_buy_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Outside a rug window only the standing list is in play, and a Helius
    hiccup must not stop the wallet for a list of three operators."""
    chain = _Helius(_COIN, fail=True)
    decision = await _source_decision(monkeypatch, chain, blocked=set())
    assert decision.decision == "ALLOW", decision.reason_codes
    assert decision.provenance["sources"] == {"recent_rug_ids": 0, "failure": "RpcError"}


async def test_money_on_the_standing_list_is_refused_without_a_recent_rug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 16-Sep operator's funders are blocked for good, not three hours."""
    monkeypatch.setattr(service.sources, "ALWAYS_BLOCKED", frozenset({"FunderA"}))
    chain = _Helius(_COIN, funders=_FUNDED)
    decision = await _source_decision(monkeypatch, chain, blocked=set())
    assert decision.decision == "REJECT"
    assert decision.reason_codes == (Reason.KNOWN_RUG_MONEY,)
    assert decision.provenance["sources"]["matched"] == ["FunderA"]


async def test_an_untraceable_coin_refuses_inside_a_rug_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decision = await _source_decision(monkeypatch, _Helius(_COIN, fail=True),
                                      blocked={"FunderB"})
    assert decision.reason_codes == (Reason.SOURCES_UNREADABLE,)


async def test_the_source_block_is_off_unless_switched_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _Helius(_COIN, funders=_FUNDED)
    decision = await _source_decision(monkeypatch, chain, blocked={"FunderB"}, enabled=False)
    assert decision.decision == "ALLOW"
    assert chain.started == 0
    assert "sources" not in decision.provenance
