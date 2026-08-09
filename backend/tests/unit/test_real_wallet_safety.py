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
    TOKEN_2022_PROGRAM,
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
    def __init__(self, inspection: TokenInspection, quotes: _Quotes) -> None:
        super().__init__(
            SimpleNamespace(add=lambda _: None, flush=self._flush), jupiter=quotes
        )  # type: ignore[arg-type]
        self.inspection = inspection

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
    inspection = service._decode_mint_account(
        {"owner": TOKEN_2022_PROGRAM, "data": [encoded, "base64"]}
    )
    assert inspection.decimals == 6
    assert inspection.extensions == (18,)
    assert inspection.mint_authority_active is False
    assert inspection.freeze_authority_active is False
