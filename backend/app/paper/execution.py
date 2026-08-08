"""Paper execution estimates captured at decision time.

Sprint 39 replaces the future paper-wallet cost estimate with Jupiter quotes,
without touching historical rows. The rule is simple:

* Entry and exit decisions may call Jupiter once, at the moment the decision is
  made.
* The quote payload and its summaries are stored with the position/audit.
* Replay and read paths consume stored facts. They never re-quote.
* If Jupiter cannot quote, the caller records a fallback reason and uses the
  legacy deterministic model for that trade.

No swap transaction is built or submitted here. This is still paper trading.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from app.paper import costs

USDC_DECIMALS = 6
LEGACY_MODEL_VERSION = "legacy_constant_product_v1"
JUPITER_MODEL_VERSION = "jupiter_quote_v2"

_ZERO = Decimal(0)
_HUNDRED = Decimal(100)
_PRICE = Decimal("0.000000000000000001")
_MONEY = Decimal("0.0001")
_PCT = Decimal("0.0001")


class ExecutionQuoteUnavailableError(RuntimeError):
    """Raised when a quote cannot be captured honestly."""


@dataclass(frozen=True, slots=True)
class ExecutionQuote:
    side: str
    model_version: str
    quoted_at: datetime
    latency_ms: Decimal
    input_mint: str
    output_mint: str
    input_amount_raw: str
    output_amount_raw: str
    input_decimals: int
    output_decimals: int
    input_amount: Decimal
    output_amount: Decimal
    input_amount_usd: Decimal | None
    output_amount_usd: Decimal | None
    estimated_price_usd: Decimal
    price_impact_pct: Decimal | None
    context_slot: int | None
    platform_fee_usd: Decimal | None
    route: str
    amms: tuple[str, ...]
    raw: dict[str, object]

    @property
    def confidence(self) -> str:
        return "jupiter_route"

    def as_json(self) -> dict[str, object]:
        return {
            "side": self.side,
            "model_version": self.model_version,
            "quoted_at": self.quoted_at.isoformat(),
            "latency_ms": str(self.latency_ms),
            "input_mint": self.input_mint,
            "output_mint": self.output_mint,
            "input_amount_raw": self.input_amount_raw,
            "output_amount_raw": self.output_amount_raw,
            "input_decimals": self.input_decimals,
            "output_decimals": self.output_decimals,
            "input_amount": str(self.input_amount),
            "output_amount": str(self.output_amount),
            "input_amount_usd": (
                None if self.input_amount_usd is None else str(self.input_amount_usd)
            ),
            "output_amount_usd": (
                None if self.output_amount_usd is None else str(self.output_amount_usd)
            ),
            "estimated_price_usd": str(self.estimated_price_usd),
            "price_impact_pct": (
                None if self.price_impact_pct is None else str(self.price_impact_pct)
            ),
            "context_slot": self.context_slot,
            "platform_fee_usd": (
                None if self.platform_fee_usd is None else str(self.platform_fee_usd)
            ),
            "route": self.route,
            "amms": list(self.amms),
            "raw": self.raw,
        }


@dataclass(frozen=True, slots=True)
class LegacyExecution:
    reason: str

    @property
    def model_version(self) -> str:
        return LEGACY_MODEL_VERSION

    @property
    def confidence(self) -> str:
        return "legacy_fallback"


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _raw_to_amount(value: str, decimals: int) -> Decimal:
    return Decimal(value) / (Decimal(10) ** decimals)


def _amount_to_raw(value: Decimal, decimals: int) -> int:
    return int((value * (Decimal(10) ** decimals)).to_integral_value())


def _route_plan(raw: dict[str, object]) -> tuple[str, ...]:
    route = raw.get("routePlan")
    if not isinstance(route, list):
        return ()
    amms: list[str] = []
    for item in route:
        if not isinstance(item, dict):
            continue
        swap = item.get("swapInfo")
        if not isinstance(swap, dict):
            continue
        label = swap.get("label")
        if isinstance(label, str) and label:
            amms.append(label)
    return tuple(amms)


def _platform_fee_usd(raw: dict[str, object], *, usdc_mint: str) -> Decimal | None:
    fee = raw.get("platformFee")
    if not isinstance(fee, dict):
        return Decimal(0)
    amount = fee.get("amount")
    fee_mint = fee.get("feeMint")
    if not isinstance(amount, str):
        return Decimal(0)
    if fee_mint is not None and fee_mint != usdc_mint:
        return None
    return _raw_to_amount(amount, USDC_DECIMALS)


def jupiter_quote_from_raw(
    raw: dict[str, object],
    *,
    side: str,
    quoted_at: datetime,
    input_decimals: int,
    output_decimals: int,
    input_amount_usd: Decimal | None,
    output_amount_usd: Decimal | None,
    estimated_price_usd: Decimal,
    usdc_mint: str,
) -> ExecutionQuote:
    input_raw = str(raw["inAmount"])
    output_raw = str(raw["outAmount"])
    amms = _route_plan(raw)
    impact = _decimal(raw.get("priceImpactPct"))
    return ExecutionQuote(
        side=side,
        model_version=JUPITER_MODEL_VERSION,
        quoted_at=quoted_at.astimezone(UTC),
        latency_ms=(_decimal(raw.get("_memescope_latency_ms")) or _ZERO),
        input_mint=str(raw.get("inputMint") or ""),
        output_mint=str(raw.get("outputMint") or ""),
        input_amount_raw=input_raw,
        output_amount_raw=output_raw,
        input_decimals=input_decimals,
        output_decimals=output_decimals,
        input_amount=_raw_to_amount(input_raw, input_decimals),
        output_amount=_raw_to_amount(output_raw, output_decimals),
        input_amount_usd=input_amount_usd,
        output_amount_usd=output_amount_usd,
        estimated_price_usd=estimated_price_usd.quantize(_PRICE),
        price_impact_pct=(None if impact is None else (impact * _HUNDRED).quantize(_PCT)),
        context_slot=(
            int(str(raw["contextSlot"])) if raw.get("contextSlot") is not None else None
        ),
        platform_fee_usd=_platform_fee_usd(raw, usdc_mint=usdc_mint),
        route=" / ".join(amms),
        amms=amms,
        raw=raw,
    )


def legacy_side_summary(
    *,
    side: str,
    notional_usd: Decimal,
    liquidity_usd: Decimal | None,
    reason: str,
) -> dict[str, object]:
    side_cost = costs.side_cost(notional_usd, liquidity_usd)
    return {
        "side": side,
        "model_version": LEGACY_MODEL_VERSION,
        "fallback_reason": reason,
        "notional_usd": str(notional_usd),
        "fee_usd": None if side_cost is None else str(side_cost.fee.quantize(_MONEY)),
        "price_impact_usd": (
            None if side_cost is None else str(side_cost.impact.quantize(_MONEY))
        ),
        "price_impact_pct": (
            None
            if side_cost is None or side_cost.total_pct is None
            else str(side_cost.total_pct)
        ),
    }
