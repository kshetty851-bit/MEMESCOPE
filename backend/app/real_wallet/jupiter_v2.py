"""Separate Jupiter Swap API V2 order client for autonomous dry-run evidence.

It deliberately exposes `/order` only. There is no `/execute`, signer, RPC
submission, or transaction deserialization in this module.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter
from typing import Any, cast

import httpx

from app.core.config import settings


class JupiterV2OrderUnavailableError(RuntimeError):
    """Jupiter could not provide a usable V2 order."""


@dataclass(frozen=True, slots=True)
class JupiterV2OrderEvidence:
    side: str
    request_id: str | None
    price_impact_pct: Decimal | None
    route_plan: list[dict[str, object]]
    raw: dict[str, object]

    def as_json(self) -> dict[str, object]:
        """Persist quote evidence, never the unsigned transaction payload."""
        return {
            "side": self.side,
            "request_id": self.request_id,
            "price_impact_pct": (
                None if self.price_impact_pct is None else str(self.price_impact_pct)
            ),
            "route_plan": self.route_plan,
            "raw": self.raw,
            "assembled_payload_omitted": True,
        }


class RealWalletJupiterV2Client:
    """Read-only V2 `/order` client, separate from Paper Wallet's V1 client."""

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._base_url = settings.JUPITER_V2_BASE_URL.rstrip("/")
        self._timeout = httpx.Timeout(settings.JUPITER_V2_ORDER_TIMEOUT_SECONDS)
        self._last_keyless_request_at: float | None = None

    async def order(
        self,
        *,
        side: str,
        input_mint: str,
        output_mint: str,
        amount_raw: int,
        taker_public_key: str,
    ) -> JupiterV2OrderEvidence:
        if amount_raw <= 0 or not taker_public_key:
            raise JupiterV2OrderUnavailableError("invalid_v2_order_input")
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount_raw),
            "taker": taker_public_key,
        }
        headers: dict[str, str] = {}
        api_key = settings.JUPITER_API_KEY.get_secret_value()
        if api_key:
            headers["x-api-key"] = api_key
        else:
            await self._respect_keyless_rate_limit()
        started = perf_counter()
        try:
            if self._client is None:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.get(
                        f"{self._base_url}/order", params=params, headers=headers
                    )
            else:
                response = await self._client.get(
                    f"{self._base_url}/order", params=params, headers=headers
                )
            response.raise_for_status()
            body = cast(dict[str, Any], response.json())
        except (httpx.HTTPError, ValueError) as exc:
            raise JupiterV2OrderUnavailableError("jupiter_v2_order_unavailable") from exc
        route = body.get("routePlan")
        route_plan: list[dict[str, object]] = []
        if isinstance(route, list):
            route_plan = [item for item in route if isinstance(item, dict)]
        impact_raw = body.get("priceImpactPct")
        try:
            impact = Decimal(str(impact_raw)) if impact_raw is not None else None
        except Exception:
            impact = None
        safe_raw = {
            key: value for key, value in body.items() if key not in {"transaction", "tx"}
        }
        safe_raw["latency_ms"] = str(
            (Decimal(str(perf_counter() - started)) * Decimal(1000)).quantize(Decimal("0.001"))
        )
        return JupiterV2OrderEvidence(
            side=side,
            request_id=str(body["requestId"]) if body.get("requestId") else None,
            price_impact_pct=impact,
            route_plan=route_plan,
            raw=safe_raw,
        )

    async def _respect_keyless_rate_limit(self) -> None:
        """Keep the dry-run client within Jupiter's documented 0.5 RPS tier."""
        minimum_interval_seconds = 2.0
        if self._last_keyless_request_at is not None:
            elapsed = perf_counter() - self._last_keyless_request_at
            if elapsed < minimum_interval_seconds:
                await asyncio.sleep(minimum_interval_seconds - elapsed)
        self._last_keyless_request_at = perf_counter()
