"""Re-check a Jupiter order against the intent that authorised it, before signing.

## The gap this closes

`FileExecutionSigner.sign_jupiter_transaction` documents its own limit honestly:
it verifies the required signer set and that the fee payer is our pinned wallet,
and it stops there. It cannot do more. Route instructions arrive compiled and
may resolve accounts through address lookup tables, so the mints and amounts a
transaction will actually move are not readable from the bytes being signed.

Structural validation therefore answers "is this a transaction only my wallet
can pay for" and *not* "is this the swap I authorised". Those are different
questions, and only the second one protects the balance.

So the semantics are checked here instead, against the JSON `/order` response —
which does state `inputMint`, `outputMint`, `inAmount`, `outAmount`,
`otherAmountThreshold`, `slippageBps`, `taker` and `requestId` — and against the
intent the strategy and safety gate actually approved. The transaction is then
signed only if this agrees.

## What this cannot do, stated plainly

This trusts that the assembled transaction corresponds to the JSON that
accompanied it. Nothing available at this boundary can prove that; the proof
arrives after the fact, from the chain, in `reconciliation.py`, which derives
real quantities from wallet-owned balance deltas and refuses to settle a
position whose numbers disagree. Defence in depth, not a single perfect check:
this makes a wrong order overwhelmingly likely to be caught before it is
signed, and reconciliation makes a wrong *settlement* impossible after it.

Pure: no I/O, no clock, no database. `now` is a parameter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any


class OrderRejection(StrEnum):
    """Why an order may not be signed. Persisted verbatim on the intent."""

    TAKER_MISMATCH = "ORDER_TAKER_MISMATCH"
    INPUT_MINT_MISMATCH = "ORDER_INPUT_MINT_MISMATCH"
    OUTPUT_MINT_MISMATCH = "ORDER_OUTPUT_MINT_MISMATCH"
    INPUT_AMOUNT_MISMATCH = "ORDER_INPUT_AMOUNT_MISMATCH"
    OUTPUT_AMOUNT_INVALID = "ORDER_OUTPUT_AMOUNT_INVALID"
    MINIMUM_OUTPUT_MISSING = "ORDER_MINIMUM_OUTPUT_MISSING"
    MINIMUM_OUTPUT_ABOVE_EXPECTED = "ORDER_MINIMUM_OUTPUT_ABOVE_EXPECTED"
    SLIPPAGE_MISSING = "ORDER_SLIPPAGE_MISSING"
    SLIPPAGE_ABOVE_POLICY = "ORDER_SLIPPAGE_ABOVE_POLICY"
    REQUEST_ID_MISSING = "ORDER_REQUEST_ID_MISSING"
    REQUEST_ID_MISMATCH = "ORDER_REQUEST_ID_MISMATCH"
    ORDER_STALE = "ORDER_STALE"
    PRICE_IMPACT_ABOVE_POLICY = "ORDER_PRICE_IMPACT_ABOVE_POLICY"
    ROUTE_EVIDENCE_MISSING = "ORDER_ROUTE_EVIDENCE_MISSING"
    MALFORMED_ORDER = "ORDER_MALFORMED"
    SIDE_UNSUPPORTED = "ORDER_SIDE_UNSUPPORTED"
    POSITION_BINDING_INVALID = "ORDER_POSITION_BINDING_INVALID"
    SELL_QUANTITY_NOT_CONFIRMED = "ORDER_SELL_QUANTITY_NOT_CONFIRMED"


@dataclass(frozen=True, slots=True)
class AuthorizedOrder:
    """What the strategy, safety gate and policy actually approved.

    Every field is server-derived. Nothing here comes from the Jupiter response
    — that is the whole point of comparing the two.
    """

    side: str
    wallet_public_key: str
    input_mint: str
    output_mint: str
    #: Exact raw base units the order must spend. For a SELL this is the
    #: confirmed on-chain position quantity, never a recomputed estimate.
    input_amount_raw: int
    request_id: str
    ordered_at: datetime
    max_slippage_bps: int
    max_price_impact_pct: Decimal
    max_order_age_seconds: int
    #: SELL only: the position this exit is bound to, and whether its entry
    #: quantity was confirmed from chain evidence rather than assumed.
    position_id: str | None = None
    position_quantity_confirmed: bool = True


@dataclass(frozen=True, slots=True)
class OrderVerdict:
    approved: bool
    reason_codes: tuple[str, ...]
    #: Parsed figures, for the audit row. Present even when rejected, so the
    #: record shows what was offered as well as why it was refused.
    observed: dict[str, str]

    def require(self) -> None:
        if not self.approved:
            raise OrderEvidenceRejectedError(self.reason_codes)


class OrderEvidenceRejectedError(RuntimeError):
    """The order did not match its authorisation; it must not be signed."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        super().__init__(",".join(reasons) or "order_evidence_rejected")
        self.reasons = reasons


def _int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)) if value is not None else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def verify(
    *, authorized: AuthorizedOrder, order: dict[str, Any], now: datetime
) -> OrderVerdict:
    """Compare one Jupiter order against its authorisation.

    Reasons accumulate; approval is their absence. Every mismatch is reported
    rather than short-circuiting on the first, because an order that is wrong in
    three ways is a different kind of event from one that is stale, and the
    audit row should say which happened.
    """
    reasons: list[str] = []
    observed: dict[str, str] = {}

    if authorized.side not in {"BUY", "SELL"}:
        return OrderVerdict(False, (OrderRejection.SIDE_UNSUPPORTED,), observed)

    # A SELL may only ever be sized from a confirmed position. An exit computed
    # from an assumed balance is how a wallet tries to sell tokens it does not
    # hold, and the transaction fails after the fee has been paid.
    if authorized.side == "SELL":
        if not authorized.position_id:
            reasons.append(OrderRejection.POSITION_BINDING_INVALID)
        if not authorized.position_quantity_confirmed:
            reasons.append(OrderRejection.SELL_QUANTITY_NOT_CONFIRMED)

    taker = order.get("taker")
    observed["taker"] = str(taker)
    if not isinstance(taker, str) or taker != authorized.wallet_public_key:
        reasons.append(OrderRejection.TAKER_MISMATCH)

    input_mint, output_mint = order.get("inputMint"), order.get("outputMint")
    observed["input_mint"] = str(input_mint)
    observed["output_mint"] = str(output_mint)
    if input_mint != authorized.input_mint:
        reasons.append(OrderRejection.INPUT_MINT_MISMATCH)
    if output_mint != authorized.output_mint:
        reasons.append(OrderRejection.OUTPUT_MINT_MISMATCH)

    in_amount = _int(order.get("inAmount"))
    observed["in_amount"] = str(in_amount)
    # Exact, not approximate. The authorised amount is what the limits, the
    # safety gate and the position ledger were all computed against.
    if in_amount is None or in_amount != authorized.input_amount_raw:
        reasons.append(OrderRejection.INPUT_AMOUNT_MISMATCH)

    out_amount = _int(order.get("outAmount"))
    observed["out_amount"] = str(out_amount)
    if out_amount is None or out_amount <= 0:
        reasons.append(OrderRejection.OUTPUT_AMOUNT_INVALID)

    minimum_out = _int(order.get("otherAmountThreshold"))
    observed["minimum_out"] = str(minimum_out)
    if minimum_out is None or minimum_out <= 0:
        reasons.append(OrderRejection.MINIMUM_OUTPUT_MISSING)
    elif out_amount is not None and minimum_out > out_amount:
        # A floor above the quote is incoherent, and the direction that would
        # matter: it would describe a trade better than the one on offer.
        reasons.append(OrderRejection.MINIMUM_OUTPUT_ABOVE_EXPECTED)

    slippage = _int(order.get("slippageBps"))
    observed["slippage_bps"] = str(slippage)
    if slippage is None or slippage < 0:
        reasons.append(OrderRejection.SLIPPAGE_MISSING)
    elif slippage > authorized.max_slippage_bps:
        reasons.append(OrderRejection.SLIPPAGE_ABOVE_POLICY)

    request_id = order.get("requestId")
    observed["request_id"] = str(request_id)
    if not isinstance(request_id, str) or not request_id:
        reasons.append(OrderRejection.REQUEST_ID_MISSING)
    elif request_id != authorized.request_id:
        # The request id binds this order to the `/execute` call that will carry
        # it. A mismatch means the transaction and the evidence describe
        # different orders.
        reasons.append(OrderRejection.REQUEST_ID_MISMATCH)

    age = (now - authorized.ordered_at).total_seconds()
    observed["order_age_seconds"] = f"{age:.3f}"
    if age < 0 or age > authorized.max_order_age_seconds:
        reasons.append(OrderRejection.ORDER_STALE)

    impact = _decimal(order.get("priceImpactPct"))
    if impact is not None:
        observed["price_impact_pct"] = str(impact)
        # Jupiter reports a fraction; the policy is written in percent.
        if abs(impact) * 100 > authorized.max_price_impact_pct:
            reasons.append(OrderRejection.PRICE_IMPACT_ABOVE_POLICY)

    route = order.get("routePlan")
    if not isinstance(route, list) or not route:
        # An order with no route is an order nobody can audit afterwards.
        reasons.append(OrderRejection.ROUTE_EVIDENCE_MISSING)
    else:
        observed["route_hops"] = str(len(route))

    return OrderVerdict(
        approved=not reasons,
        reason_codes=tuple(dict.fromkeys(reasons)),
        observed=observed,
    )


def to_raw_amount(ui_amount: Decimal, decimals: int) -> int:
    """Convert a UI amount to base units, refusing anything inexact.

    A SELL must offer the *exact* confirmed quantity. Rounding here would
    produce an order for slightly more or less than the wallet holds, and the
    difference is the kind that leaves dust or fails on chain after paying a fee.
    """
    if decimals < 0:
        raise ValueError("decimals_must_not_be_negative")
    scaled = ui_amount.scaleb(decimals)
    if scaled != scaled.to_integral_value():
        raise ValueError("quantity_is_not_representable_in_base_units")
    return int(scaled)
