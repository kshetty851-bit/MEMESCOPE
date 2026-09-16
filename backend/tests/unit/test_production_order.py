"""The order factory is where an authorisation becomes signable bytes.

Every test here tries to get something through it that the strategy and policy
did not authorise.
"""

from __future__ import annotations

import ast
import uuid
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.real_wallet.jupiter_v2 import JupiterV2OrderUnavailableError
from app.real_wallet.order_evidence import OrderEvidenceRejectedError
from app.real_wallet.production_order import (
    ProductionOrderFactory,
    _authorised_amount_raw,
)

pytestmark = pytest.mark.unit

WALLET = "7WctMGpqz1tGkYStBBjJRMnmuh9uwJubYV2tL4pLwRr9"
SOL = "So11111111111111111111111111111111111111112"
TOKEN = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


class _Intent:
    """Only the fields the factory reads."""

    def __init__(self, **kw):
        self.id = uuid.uuid4()
        self.side = kw.get("side", "BUY")
        self.wallet_public_key = kw.get("wallet", WALLET)
        self.input_mint = kw.get("input_mint", SOL)
        self.output_mint = kw.get("output_mint", TOKEN)
        self.requested_usd = kw.get("usd", Decimal("5"))
        self.requested_token_quantity = kw.get("qty")
        self.authorized_input_amount_raw = kw.get("raw")
        self.actual_input_amount_raw = kw.get("lamports", 25_000_000)
        self.position_id = kw.get("position_id")


def _order_body(**over):
    body = {
        "transaction": "BASE64TX",
        "requestId": "req-abc",
        "taker": WALLET,
        "inputMint": SOL,
        "outputMint": TOKEN,
        "inAmount": "25000000",
        "outAmount": "1000000",
        "slippageBps": 50,
        "priceImpactPct": "0.4",
    }
    body.update(over)
    return body


def _client(body, status=200):
    def handler(request):
        return httpx.Response(status, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- the amount is server-derived, never Jupiter's ---------------------------

def test_a_buy_spends_the_lamports_recorded_at_authorisation():
    assert _authorised_amount_raw(_Intent(lamports=25_000_000)) == 25_000_000


def test_a_buy_without_recorded_lamports_is_refused():
    with pytest.raises(JupiterV2OrderUnavailableError, match="missing_lamports"):
        _authorised_amount_raw(_Intent(lamports=None))


def test_a_sell_spends_the_base_units_its_entry_received():
    """`qty` is whole tokens. Read as base units it sold 1,640,115 of the
    1,640,115,442,951 the entry bought — a millionth of the position."""
    got = _authorised_amount_raw(_Intent(
        side="SELL", qty=Decimal("1640115.442951"), raw=Decimal(1640115442951),
        position_id="p1"))
    assert got == 1_640_115_442_951


def test_a_sell_without_a_recorded_base_amount_is_refused():
    with pytest.raises(JupiterV2OrderUnavailableError, match="missing_quantity"):
        _authorised_amount_raw(_Intent(side="SELL", qty=Decimal("2.5"), raw=None,
                                       position_id="p1"))


# --- what comes back must match what was authorised --------------------------

async def test_an_order_for_a_different_wallet_is_refused():
    factory = ProductionOrderFactory(client=_client(_order_body(taker="SOMEONEELSE")))
    with pytest.raises(OrderEvidenceRejectedError):
        await factory.prepare(_Intent())


async def test_an_order_for_a_different_token_is_refused():
    factory = ProductionOrderFactory(client=_client(_order_body(outputMint=SOL)))
    with pytest.raises(OrderEvidenceRejectedError):
        await factory.prepare(_Intent())


async def test_an_order_spending_a_different_amount_is_refused():
    factory = ProductionOrderFactory(client=_client(_order_body(inAmount="99999999")))
    with pytest.raises(OrderEvidenceRejectedError):
        await factory.prepare(_Intent())


async def test_a_thin_pool_refuses_a_buy_and_still_lets_a_sell_leave(monkeypatch):
    """A pool that has thinned out is a reason to leave it. Held to the BUY
    cap, a sell into a 20%-impact pool was refused, which keeps the position
    in exactly that pool."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "REAL_WALLET_SAFETY_MAX_BUY_PRICE_IMPACT_PCT", Decimal("5"))
    monkeypatch.setattr(settings, "REAL_WALLET_EXIT_MAX_PRICE_IMPACT_PCT", Decimal("50"))
    complete = {"otherAmountThreshold": "900000", "routePlan": [{"percent": 100}]}

    calm = _order_body(**complete, priceImpactPct="0.001")
    assert (await ProductionOrderFactory(client=_client(calm)).prepare(_Intent())
            ).input_amount_raw == 25_000_000

    thin = _order_body(**complete, priceImpactPct="0.2")
    with pytest.raises(OrderEvidenceRejectedError, match="PRICE_IMPACT"):
        await ProductionOrderFactory(client=_client(thin)).prepare(_Intent())

    sell = _Intent(side="SELL", input_mint=TOKEN, output_mint=SOL,
                   qty=Decimal("2.5"), raw=Decimal(2_500_000), position_id="p1")
    thin_sell = _order_body(**complete, priceImpactPct="0.2",
                            inputMint=TOKEN, outputMint=SOL, inAmount="2500000")
    prepared = await ProductionOrderFactory(client=_client(thin_sell)).prepare(sell)
    assert prepared.input_amount_raw == 2_500_000


async def test_a_response_without_a_transaction_is_refused():
    body = _order_body(); body.pop("transaction")
    factory = ProductionOrderFactory(client=_client(body))
    with pytest.raises(JupiterV2OrderUnavailableError, match="no_transaction"):
        await factory.prepare(_Intent())


async def test_a_response_without_a_request_id_is_refused():
    body = _order_body(); body.pop("requestId")
    factory = ProductionOrderFactory(client=_client(body))
    with pytest.raises(JupiterV2OrderUnavailableError, match="no_request_id"):
        await factory.prepare(_Intent())


async def test_an_http_failure_is_a_refusal_not_a_guess():
    factory = ProductionOrderFactory(client=_client({"nope": True}, status=503))
    with pytest.raises(JupiterV2OrderUnavailableError, match="unavailable"):
        await factory.prepare(_Intent())


# --- structure ---------------------------------------------------------------

def test_the_factory_cannot_sign_submit_or_hold_a_key():
    import app.real_wallet.production_order as mod

    tree = ast.parse(Path(mod.__file__).read_text())
    imported: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            imported.add(n.module)
        elif isinstance(n, ast.Import):
            imported.update(a.name for a in n.names)
    assert not any(m.startswith("app.real_wallet.signer") for m in imported)
    assert "app.real_wallet.live_transport" not in imported
    assert "solders.keypair" not in imported
    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    for banned in ("sign_jupiter_transaction", "sign_message", "execute_signed_order"):
        assert banned not in called
