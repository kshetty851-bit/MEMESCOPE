"""Jupiter quote capture for future paper executions.

This is an I/O seam. The paper simulation core stays pure; it receives the
captured quote as data and persists it for deterministic replay.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from time import perf_counter
from typing import Any, cast

import httpx

from app.core.config import settings
from app.paper.execution import (
    USDC_DECIMALS,
    ExecutionQuote,
    ExecutionQuoteUnavailableError,
    _amount_to_raw,
    _raw_to_amount,
    jupiter_quote_from_raw,
)


class JupiterExecutionClient:
    """Small async client for Jupiter's quote endpoint."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        slippage_bps: int | None = None,
        timeout_seconds: float | None = None,
        usdc_mint: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = (base_url or settings.JUPITER_QUOTE_BASE_URL).rstrip("/")
        self._slippage_bps = slippage_bps or settings.JUPITER_QUOTE_SLIPPAGE_BPS
        self._usdc = usdc_mint or settings.JUPITER_USDC_MINT
        self._client = client
        self._timeout = httpx.Timeout(
            timeout_seconds or settings.JUPITER_QUOTE_TIMEOUT_SECONDS
        )

    async def buy_quote(
        self,
        *,
        output_mint: str,
        input_usd: Decimal,
        output_decimals: int,
        now: datetime,
    ) -> ExecutionQuote:
        raw = await self._quote(
            input_mint=self._usdc,
            output_mint=output_mint,
            amount=_amount_to_raw(input_usd, USDC_DECIMALS),
        )
        output_raw = str(raw["outAmount"])
        tokens = _raw_to_amount(output_raw, output_decimals)
        if tokens <= 0:
            raise ExecutionQuoteUnavailableError("Jupiter returned zero output tokens.")
        return jupiter_quote_from_raw(
            raw,
            side="entry",
            quoted_at=now,
            input_decimals=USDC_DECIMALS,
            output_decimals=output_decimals,
            input_amount_usd=input_usd,
            output_amount_usd=None,
            estimated_price_usd=input_usd / tokens,
            usdc_mint=self._usdc,
        )

    async def sell_quote(
        self,
        *,
        input_mint: str,
        quantity: Decimal,
        input_decimals: int,
        now: datetime,
    ) -> ExecutionQuote:
        raw = await self._quote(
            input_mint=input_mint,
            output_mint=self._usdc,
            amount=_amount_to_raw(quantity, input_decimals),
        )
        output_usd = _raw_to_amount(str(raw["outAmount"]), USDC_DECIMALS)
        if quantity <= 0:
            raise ExecutionQuoteUnavailableError("Cannot sell a non-positive paper quantity.")
        return jupiter_quote_from_raw(
            raw,
            side="exit",
            quoted_at=now,
            input_decimals=input_decimals,
            output_decimals=USDC_DECIMALS,
            input_amount_usd=None,
            output_amount_usd=output_usd,
            estimated_price_usd=output_usd / quantity,
            usdc_mint=self._usdc,
        )

    async def _quote(
        self, *, input_mint: str, output_mint: str, amount: int
    ) -> dict[str, object]:
        if amount <= 0:
            raise ExecutionQuoteUnavailableError("Jupiter amount must be positive.")
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount),
            "slippageBps": str(self._slippage_bps),
        }
        start = perf_counter()
        try:
            client = self._client
            if client is None:
                async with httpx.AsyncClient(timeout=self._timeout) as transient:
                    response = await transient.get(f"{self._base_url}/quote", params=params)
            else:
                response = await client.get(f"{self._base_url}/quote", params=params)
            response.raise_for_status()
            payload = cast(dict[str, Any], response.json())
        except (httpx.HTTPError, ValueError) as exc:
            raise ExecutionQuoteUnavailableError(str(exc)) from exc
        payload["_memescope_latency_ms"] = str(
            (Decimal(str(perf_counter() - start)) * Decimal(1000)).quantize(Decimal("0.001"))
        )
        return payload
