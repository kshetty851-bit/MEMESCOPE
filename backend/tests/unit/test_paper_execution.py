from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from app.paper import execution
from app.services.jupiter import JupiterExecutionClient

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 8, 20, 0, tzinfo=UTC)
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
MINT = "probe1111111111111111111111111111111111111"


def client(payload: dict[str, object]) -> JupiterExecutionClient:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/quote")
        return httpx.Response(200, json=payload)

    return JupiterExecutionClient(
        base_url="https://jupiter.test/swap/v1",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


class TestJupiterExecution:
    async def test_buy_quote_turns_jupiter_output_into_quantity_and_price(self) -> None:
        quote = await client(
            {
                "inputMint": USDC,
                "outputMint": MINT,
                "inAmount": "100000000",
                "outAmount": "200000000",
                "priceImpactPct": "0.0125",
                "contextSlot": 123,
                "platformFee": None,
                "routePlan": [{"swapInfo": {"label": "Pump.fun Amm"}}],
            }
        ).buy_quote(output_mint=MINT, input_usd=Decimal(100), output_decimals=6, now=NOW)

        assert quote.model_version == execution.JUPITER_MODEL_VERSION
        assert quote.output_amount == Decimal(200)
        assert quote.estimated_price_usd == Decimal("0.500000000000000000")
        assert quote.price_impact_pct == Decimal("1.2500")
        assert quote.route == "Pump.fun Amm"
        assert quote.context_slot == 123
        assert quote.as_json()["output_decimals"] == 6

    async def test_sell_quote_uses_usdc_out_as_the_execution_proceeds(self) -> None:
        quote = await client(
            {
                "inputMint": MINT,
                "outputMint": USDC,
                "inAmount": "200000000",
                "outAmount": "130000000",
                "priceImpactPct": "0.02",
                "contextSlot": 456,
                "platformFee": {"amount": "100000", "feeMint": USDC},
                "routePlan": [
                    {"swapInfo": {"label": "Pump.fun Amm"}},
                    {"swapInfo": {"label": "HumidiFi"}},
                ],
            }
        ).sell_quote(input_mint=MINT, quantity=Decimal(200), input_decimals=6, now=NOW)

        assert quote.output_amount_usd == Decimal(130)
        assert quote.estimated_price_usd == Decimal("0.650000000000000000")
        assert quote.platform_fee_usd == Decimal("0.1")
        assert quote.route == "Pump.fun Amm / HumidiFi"

    async def test_http_failure_is_explicit_not_silent(self) -> None:
        async def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"error": "down"})

        broken = JupiterExecutionClient(
            base_url="https://jupiter.test/swap/v1",
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

        with pytest.raises(execution.ExecutionQuoteUnavailableError):
            await broken.buy_quote(
                output_mint=MINT,
                input_usd=Decimal(100),
                output_decimals=6,
                now=NOW,
            )
