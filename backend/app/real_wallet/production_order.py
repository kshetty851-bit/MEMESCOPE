"""Assemble one real Jupiter order and hand it to the lifecycle.

This is the boundary where an authorised intent becomes bytes that could be
signed, and it is deliberately the narrowest thing that can do that.

## Why it does not reuse `RealWalletJupiterV2Client.order()`

That client strips `transaction` from the response on purpose — it exists for
the observation-only phase, where holding an unsigned payload would be a
capability nobody had asked for. Signing needs those bytes, so this module
fetches them explicitly rather than loosening the read-only client. Two callers,
two capabilities, and the safe one stays safe.

## What must be true before anything is signed

`sign_jupiter_transaction` cannot read mint or amount semantics out of compiled
route bytes — nobody can. So the JSON body is checked here, by
`order_evidence.verify`, against what the strategy and policy actually
authorised: taker, both mints, the exact input amount, slippage, price impact
and order age. Only then is the fingerprint computed and stored, and the signer
recomputes it independently from the intent before it will sign.

Nothing here signs, submits, or holds a key.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.models.real_wallet_execution import RealWalletLiveIntent
from app.real_wallet import order_evidence, tx_inspect
from app.real_wallet.jupiter_v2 import JupiterV2OrderUnavailableError

logger = get_logger(__name__)

#: Orders asked for when Jupiter's route would be refused by the signer
#: (Karthik, 2026-10-13: "yes build the instant retry"). On 13 Oct a GTA 6 Coin
#: sell came back routed through a program off the signer's allowlist
#: (proVF4p...), was refused, and the next loop's sell 17 s later landed after
#: the pool was drained: -82% where the lab sold at +13%. Asking again at once
#: with that router excluded gets a route the signer accepts.
ROUTE_TRIES = 3


def _refused_programs(transaction: str) -> tuple[str, ...]:
    """Programs in these bytes the signer would refuse, by the signer's own
    rule. Undecodable bytes return nothing: the signer refuses those itself."""
    configured = settings.REAL_WALLET_ALLOWED_PROGRAM_IDS
    allowed = frozenset(configured) if configured else tx_inspect.DEFAULT_ALLOWED_PROGRAMS
    try:
        facts = tx_inspect.inspect(transaction)
    except tx_inspect.TransactionRejectedError:
        return ()
    return tuple(p for p in facts.program_ids if p not in allowed)


@dataclass(frozen=True, slots=True)
class PreparedOrder:
    """Exactly what the lifecycle needs, and nothing it does not."""

    unsigned_transaction: str
    request_id: str
    input_amount_raw: int
    intent_fingerprint: str
    evidence: dict[str, Any]


class ProductionOrderFactory:
    """Fetch, verify, and fingerprint one real order."""

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._base_url = settings.JUPITER_V2_BASE_URL.rstrip("/")
        self._timeout = httpx.Timeout(settings.JUPITER_V2_ORDER_TIMEOUT_SECONDS)

    async def prepare(self, intent: RealWalletLiveIntent, *,
                      reference_out_raw: int | None = None) -> PreparedOrder:
        if not intent.input_mint or not intent.output_mint:
            raise JupiterV2OrderUnavailableError("intent_missing_mints")
        amount_raw = _authorised_amount_raw(intent)
        excluded: list[str] = []
        for _ in range(ROUTE_TRIES):
            body = await self._fetch(
                input_mint=intent.input_mint,
                output_mint=intent.output_mint,
                amount_raw=amount_raw,
                taker=intent.wallet_public_key,
                exclude_routers=excluded,
            )
            transaction = body.get("transaction") or body.get("tx")
            if not isinstance(transaction, str) or not transaction:
                raise JupiterV2OrderUnavailableError("jupiter_order_returned_no_transaction")
            refused = _refused_programs(transaction)
            router = body.get("router")
            if (not refused or not isinstance(router, str) or not router
                    or router in excluded or len(excluded) == ROUTE_TRIES - 1):
                break
            # Nothing is widened: the route is swapped, and the signer still
            # checks the new one itself. A third refusal goes on to the signer
            # and is refused there, as before.
            logger.warning("real_wallet_route_refused_retrying", intent_id=str(intent.id),
                           router=router, programs=list(refused))
            excluded.append(router)
        request_id = body.get("requestId")
        if not isinstance(request_id, str) or not request_id:
            raise JupiterV2OrderUnavailableError("jupiter_order_returned_no_request_id")

        now = datetime.now(UTC)
        verdict = order_evidence.verify(
            authorized=order_evidence.AuthorizedOrder(
                side=intent.side.upper(),
                wallet_public_key=intent.wallet_public_key,
                input_mint=intent.input_mint,
                output_mint=intent.output_mint,
                input_amount_raw=amount_raw,
                request_id=request_id,
                ordered_at=now,
                max_slippage_bps=int(settings.REAL_WALLET_EXIT_MAX_SLIPPAGE_BPS),
                # A sell has its own, wider bound: refusing to leave a pool
                # because it got thin keeps the position in the thin pool.
                max_price_impact_pct=Decimal(str(
                    settings.REAL_WALLET_EXIT_MAX_PRICE_IMPACT_PCT
                    if intent.side.upper() == "SELL"
                    else settings.REAL_WALLET_SAFETY_MAX_BUY_PRICE_IMPACT_PCT
                )),
                max_order_age_seconds=int(
                    settings.REAL_WALLET_EXIT_MAX_QUOTE_AGE_SECONDS
                ),
                position_id=(str(intent.position_id) if intent.position_id else None),
                position_quantity_confirmed=True,
                reference_out_raw=reference_out_raw,
            ),
            order=body,
            now=now,
        )
        # Raises with every reason, not just the first.
        verdict.require()

        fingerprint = tx_inspect.intent_fingerprint(
            intent_id=str(intent.id),
            side=intent.side,
            wallet_public_key=intent.wallet_public_key,
            input_mint=intent.input_mint,
            output_mint=intent.output_mint,
            input_amount_raw=amount_raw,
            request_id=request_id,
            max_slippage_bps=int(settings.REAL_WALLET_EXIT_MAX_SLIPPAGE_BPS),
        )
        logger.info("real_wallet_order_prepared", intent_id=str(intent.id),
                    request_id=request_id, amount_raw=amount_raw)
        return PreparedOrder(
            unsigned_transaction=transaction,
            request_id=request_id,
            input_amount_raw=amount_raw,
            intent_fingerprint=fingerprint,
            evidence={
                # The payload IS persisted here, unlike the read-only client:
                # the signer reloads the intent and needs the exact bytes it is
                # being asked about. Everything else is quote evidence.
                "unsigned_transaction": transaction,
                "input_amount_raw": str(amount_raw),
                "intent_fingerprint": fingerprint,
                "request_id": request_id,
                "observed": verdict.observed,
                "price_impact_pct": verdict.observed.get("price_impact_pct"),
            },
        )

    async def _fetch(
        self, *, input_mint: str, output_mint: str, amount_raw: int, taker: str,
        exclude_routers: list[str] | None = None,
    ) -> dict[str, Any]:
        # The SAME policy the evidence check verifies against, sent with the
        # request. Omitting it let Jupiter apply its own auto-slippage — 500 bps
        # against a policy of 300 — so `verify` refused every order this factory
        # ever built, and the tolerance inside the signed transaction was
        # Jupiter's rather than ours.
        #
        # This is the SECOND place that builds an order request; the client in
        # `jupiter_v2.py` is the other, and it was fixed first while this one
        # went on failing. Two copies of a request is two places to forget.
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount_raw),
            "taker": taker,
            "slippageBps": str(int(settings.REAL_WALLET_EXIT_MAX_SLIPPAGE_BPS)),
        }
        if exclude_routers:
            params["excludeRouters"] = ",".join(exclude_routers)
        headers: dict[str, str] = {}
        api_key = settings.JUPITER_API_KEY.get_secret_value()
        if api_key:
            headers["x-api-key"] = api_key
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
            return cast(dict[str, Any], response.json())
        except (httpx.HTTPError, ValueError) as exc:
            raise JupiterV2OrderUnavailableError("jupiter_v2_order_unavailable") from exc


def _authorised_amount_raw(intent: RealWalletLiveIntent) -> int:
    """The exact base units this intent may spend.

    A BUY spends lamports derived from the server-set USD size; a SELL spends
    the base units its entry measurably received, recorded on the intent when
    it was created. Neither is ever taken from a Jupiter response, which is
    what makes the comparison meaningful.

    Not `requested_token_quantity`: that is whole tokens, and `int()` of it
    asked Jupiter to sell 1,640,115 base units of a 1,640,115.44-token bag.
    """
    if intent.side.upper() == "SELL":
        raw = intent.authorized_input_amount_raw
        if raw is None or raw <= 0:
            raise JupiterV2OrderUnavailableError("sell_intent_missing_quantity")
        return int(raw)
    if intent.requested_usd is None or intent.requested_usd <= 0:
        raise JupiterV2OrderUnavailableError("buy_intent_missing_size")
    # SOL in, priced by the wallet's own SOL/USD source at intent creation and
    # stored on the row; recomputing it here would let a price move between
    # authorisation and assembly change what gets spent.
    lamports = intent.actual_input_amount_raw
    if lamports is None or lamports <= 0:
        raise JupiterV2OrderUnavailableError("buy_intent_missing_lamports")
    return int(lamports)
