"""Real-wallet safety policy evaluation with no execution capability.

The result is intentionally independent of strategies and wallets.  A future
executor must consume an ``ALLOW`` decision; this service cannot create swaps,
sign a transaction, or access wallet credentials.
"""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.market import TokenMarketSnapshot, TradingStatus
from app.models.real_wallet_safety import RealWalletSafetyEvaluation
from app.models.token import DiscoveredToken
from app.repositories.market import MarketSnapshotRepository
from app.repositories.token import TokenRepository
from app.services.jupiter import JupiterExecutionClient
from app.services.rpc.base import RpcError, SolanaRPC
from app.services.rpc.registry import get_rpc

PUMP_FUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"  # noqa: S105
# Canonical Token-2022 owner program. Kept as one literal so it is reviewable.
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"  # noqa: S105

_ZERO = Decimal(0)
_HUNDRED = Decimal(100)


class Reason:
    PROVENANCE_UNVERIFIED = "PROVENANCE_UNVERIFIED"
    VENUE_UNSUPPORTED = "VENUE_UNSUPPORTED"
    MARKET_DATA_MISSING = "MARKET_DATA_MISSING"
    MARKET_DATA_STALE = "MARKET_DATA_STALE"
    PRICE_INVALID = "PRICE_INVALID"
    LIQUIDITY_INVALID = "LIQUIDITY_INVALID"
    TRADING_STATUS_UNSAFE = "TRADING_STATUS_UNSAFE"
    POSITION_TOO_LARGE_FOR_LIQUIDITY = "POSITION_TOO_LARGE_FOR_LIQUIDITY"
    TOKEN_CONFIGURATION_UNKNOWN = "TOKEN_CONFIGURATION_UNKNOWN"  # noqa: S105
    UNSUPPORTED_TOKEN_PROGRAM = "UNSUPPORTED_TOKEN_PROGRAM"  # noqa: S105
    UNSUPPORTED_TOKEN_EXTENSION = "UNSUPPORTED_TOKEN_EXTENSION"  # noqa: S105
    MINT_AUTHORITY_ACTIVE = "MINT_AUTHORITY_ACTIVE"
    FREEZE_AUTHORITY_ACTIVE = "FREEZE_AUTHORITY_ACTIVE"
    BUY_QUOTE_UNAVAILABLE = "BUY_QUOTE_UNAVAILABLE"
    SELL_ROUTE_UNAVAILABLE = "SELL_ROUTE_UNAVAILABLE"
    QUOTE_INVALID = "QUOTE_INVALID"
    BUY_PRICE_IMPACT_TOO_HIGH = "BUY_PRICE_IMPACT_TOO_HIGH"
    SELL_PRICE_IMPACT_TOO_HIGH = "SELL_PRICE_IMPACT_TOO_HIGH"
    EXECUTION_PRICE_DEVIATION_TOO_HIGH = "EXECUTION_PRICE_DEVIATION_TOO_HIGH"
    ROUND_TRIP_LOSS_TOO_HIGH = "ROUND_TRIP_LOSS_TOO_HIGH"
    SAFETY_CALCULATION_FAILED = "SAFETY_CALCULATION_FAILED"


@dataclass(frozen=True, slots=True)
class TokenInspection:
    token_program: str | None
    decimals: int | None
    mint_authority_active: bool | None
    freeze_authority_active: bool | None
    extensions: tuple[int, ...]
    raw: dict[str, object]


@dataclass(frozen=True, slots=True)
class SafetyDecision:
    mint_address: str
    decision: str
    evaluated_at: datetime
    trade_size_usd: Decimal
    reason_codes: tuple[str, ...]
    policy_version: str
    market_snapshot_at: datetime | None
    market_age_seconds: Decimal | None
    market_price_usd: Decimal | None
    liquidity_usd: Decimal | None
    buy_price_impact_pct: Decimal | None
    sell_price_impact_pct: Decimal | None
    round_trip_loss_usd: Decimal | None
    round_trip_loss_pct: Decimal | None
    position_liquidity_ratio: Decimal | None
    token_program: str | None
    mint_authority_active: bool | None
    freeze_authority_active: bool | None
    token_extensions: tuple[int, ...]
    provenance: dict[str, object]
    buy_quote: dict[str, object] | None
    sell_quote: dict[str, object] | None
    token_configuration: dict[str, object] | None
    evaluation_id: uuid.UUID | None = None
    token_decimals: int | None = None


def _decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value)) if value is not None else None
    except (InvalidOperation, ValueError):
        return None


def _u32(raw: bytes, start: int) -> int:
    return int.from_bytes(raw[start : start + 4], "little")


def _decode_mint_account(account: dict[str, Any]) -> TokenInspection:
    """Decode the standard 82-byte Mint prefix and Token-2022 TLV extensions."""
    owner = account.get("owner")
    data = account.get("data")
    if not isinstance(owner, str) or not isinstance(data, list) or not data:
        raise ValueError("Mint account response is incomplete")
    encoded = data[0]
    if not isinstance(encoded, str):
        raise ValueError("Mint account has no base64 payload")
    raw = base64.b64decode(encoded)
    if len(raw) < 82:
        raise ValueError("Mint account is shorter than the Mint layout")
    extensions: list[int] = []
    # Token-2022 places a one-byte AccountType discriminator between the
    # legacy Mint prefix and its TLV area. Plain SPL mints stop at byte 82.
    cursor = 83 if len(raw) > 82 and raw[82] == 1 else 82
    while cursor + 4 <= len(raw):
        extension_type = int.from_bytes(raw[cursor : cursor + 2], "little")
        length = int.from_bytes(raw[cursor + 2 : cursor + 4], "little")
        if extension_type == 0 and length == 0:
            break
        end = cursor + 4 + length
        if end > len(raw):
            raise ValueError("Malformed Token-2022 extension length")
        extensions.append(extension_type)
        cursor = end
    return TokenInspection(
        token_program=owner,
        decimals=int(raw[44]),
        mint_authority_active=_u32(raw, 0) != 0,
        freeze_authority_active=_u32(raw, 46) != 0,
        extensions=tuple(extensions),
        raw={"owner": owner, "data_length": len(raw), "extensions": extensions},
    )


class RealWalletSafetyGate:
    """Evaluate and persist one fail-closed decision.

    ``evaluate`` performs public market/RPC reads and Jupiter quote requests
    only. It persists the resulting audit row inside the caller's transaction;
    the caller is responsible for commit/rollback exactly as for other service
    writes in this application.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        rpc: SolanaRPC | None = None,
        jupiter: JupiterExecutionClient | None = None,
    ) -> None:
        self._session = session
        self._rpc = rpc or get_rpc()
        self._jupiter = jupiter or JupiterExecutionClient()

    async def evaluate(
        self, *, mint_address: str, trade_size_usd: Decimal, now: datetime | None = None
    ) -> SafetyDecision:
        evaluated_at = (now or datetime.now(UTC)).astimezone(UTC)
        if trade_size_usd <= 0:
            return await self._persist(
                self._blank(
                    mint_address,
                    trade_size_usd,
                    evaluated_at,
                    [Reason.SAFETY_CALCULATION_FAILED],
                )
            )

        token = await TokenRepository(self._session).get_by_mint(mint_address)
        snapshot = await MarketSnapshotRepository(self._session).latest_for_mint(mint_address)
        reasons: list[str] = []
        provenance = self._provenance(token, snapshot)
        if not bool(provenance["verified"]):
            reasons.append(Reason.PROVENANCE_UNVERIFIED)
        if snapshot is not None and (snapshot.dex_name or "").lower() not in {
            value.lower() for value in settings.REAL_WALLET_SAFETY_SUPPORTED_VENUES
        }:
            reasons.append(Reason.VENUE_UNSUPPORTED)

        market_age, price, liquidity = self._market_reasons(snapshot, evaluated_at, reasons)
        ratio = None if liquidity is None or liquidity <= 0 else trade_size_usd / liquidity
        if (
            ratio is not None
            and ratio > settings.REAL_WALLET_SAFETY_MAX_POSITION_LIQUIDITY_RATIO
        ):
            reasons.append(Reason.POSITION_TOO_LARGE_FOR_LIQUIDITY)

        inspection: TokenInspection | None = None
        if token is not None:
            try:
                inspection = await self._inspect_mint(mint_address)
                self._token_reasons(inspection, reasons)
            except (RpcError, ValueError, TypeError):
                reasons.append(Reason.TOKEN_CONFIGURATION_UNKNOWN)
        else:
            reasons.append(Reason.TOKEN_CONFIGURATION_UNKNOWN)

        buy: dict[str, object] | None = None
        sell: dict[str, object] | None = None
        buy_impact = sell_impact = round_trip_loss = round_trip_loss_pct = None
        # Quotes and calculations only make sense when all preceding mandatory
        # data is usable. The final result remains REJECT either way.
        if inspection is not None and price is not None and liquidity is not None:
            try:
                quote = await self._jupiter.buy_quote(
                    output_mint=mint_address,
                    input_usd=trade_size_usd,
                    output_decimals=inspection.decimals or 0,
                    now=evaluated_at,
                )
                buy = quote.as_json()
                buy_impact = quote.price_impact_pct
                if quote.output_amount <= 0 or quote.estimated_price_usd <= 0:
                    reasons.append(Reason.QUOTE_INVALID)
                else:
                    self._quote_checks(
                        quote.quoted_at, quote.price_impact_pct, "buy", evaluated_at, reasons
                    )
                    deviation = abs(quote.estimated_price_usd - price) / price * _HUNDRED
                    if deviation > settings.REAL_WALLET_SAFETY_MAX_PRICE_DEVIATION_PCT:
                        reasons.append(Reason.EXECUTION_PRICE_DEVIATION_TOO_HIGH)
                    try:
                        sell_quote = await self._jupiter.sell_quote(
                            input_mint=mint_address,
                            quantity=quote.output_amount,
                            input_decimals=inspection.decimals or 0,
                            now=evaluated_at,
                        )
                        sell = sell_quote.as_json()
                        sell_impact = sell_quote.price_impact_pct
                        self._quote_checks(
                            sell_quote.quoted_at,
                            sell_quote.price_impact_pct,
                            "sell",
                            evaluated_at,
                            reasons,
                        )
                        returned = sell_quote.output_amount_usd
                        if returned is None or returned <= 0:
                            reasons.append(Reason.QUOTE_INVALID)
                        else:
                            round_trip_loss = trade_size_usd - returned
                            round_trip_loss_pct = round_trip_loss / trade_size_usd * _HUNDRED
                            if (
                                round_trip_loss_pct
                                > settings.REAL_WALLET_SAFETY_MAX_ROUND_TRIP_LOSS_PCT
                            ):
                                reasons.append(Reason.ROUND_TRIP_LOSS_TOO_HIGH)
                    except Exception:
                        reasons.append(Reason.SELL_ROUTE_UNAVAILABLE)
            except Exception:
                reasons.append(Reason.BUY_QUOTE_UNAVAILABLE)

        decision = SafetyDecision(
            mint_address=mint_address,
            decision="ALLOW" if not reasons else "REJECT",
            evaluated_at=evaluated_at,
            trade_size_usd=trade_size_usd,
            reason_codes=tuple(dict.fromkeys(reasons)),
            policy_version=settings.REAL_WALLET_SAFETY_POLICY_VERSION,
            market_snapshot_at=(snapshot.captured_at if snapshot else None),
            market_age_seconds=market_age,
            market_price_usd=price,
            liquidity_usd=liquidity,
            buy_price_impact_pct=buy_impact,
            sell_price_impact_pct=sell_impact,
            round_trip_loss_usd=round_trip_loss,
            round_trip_loss_pct=round_trip_loss_pct,
            position_liquidity_ratio=ratio,
            token_program=(inspection.token_program if inspection else None),
            mint_authority_active=(inspection.mint_authority_active if inspection else None),
            freeze_authority_active=(
                inspection.freeze_authority_active if inspection else None
            ),
            token_extensions=(inspection.extensions if inspection else ()),
            provenance=provenance,
            buy_quote=buy,
            sell_quote=sell,
            token_configuration=(inspection.raw if inspection else None),
            token_decimals=(inspection.decimals if inspection else None),
        )
        return await self._persist(decision)

    def _blank(
        self, mint: str, size: Decimal, now: datetime, reasons: list[str]
    ) -> SafetyDecision:
        return SafetyDecision(
            mint_address=mint,
            decision="REJECT",
            evaluated_at=now,
            trade_size_usd=size,
            reason_codes=tuple(reasons),
            policy_version=settings.REAL_WALLET_SAFETY_POLICY_VERSION,
            market_snapshot_at=None,
            market_age_seconds=None,
            market_price_usd=None,
            liquidity_usd=None,
            buy_price_impact_pct=None,
            sell_price_impact_pct=None,
            round_trip_loss_usd=None,
            round_trip_loss_pct=None,
            position_liquidity_ratio=None,
            token_program=None,
            mint_authority_active=None,
            freeze_authority_active=None,
            token_extensions=(),
            provenance={"verified": False},
            buy_quote=None,
            sell_quote=None,
            token_configuration=None,
        )

    @staticmethod
    def _provenance(
        token: DiscoveredToken | None, snapshot: TokenMarketSnapshot | None
    ) -> dict[str, object]:
        return {
            "verified": bool(
                token
                and token.source_program == PUMP_FUN_PROGRAM
                and token.signature
                and token.slot > 0
            ),
            "source_program": token.source_program if token else None,
            "discovery_signature": token.signature if token else None,
            "discovery_slot": token.slot if token else None,
            "venue": snapshot.dex_name if snapshot else None,
        }

    @staticmethod
    def _market_reasons(
        snapshot: TokenMarketSnapshot | None, now: datetime, reasons: list[str]
    ) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
        if snapshot is None:
            reasons.append(Reason.MARKET_DATA_MISSING)
            return None, None, None
        age = Decimal(str((now - snapshot.captured_at).total_seconds()))
        if age < 0 or age > settings.REAL_WALLET_SAFETY_MAX_MARKET_AGE_SECONDS:
            reasons.append(Reason.MARKET_DATA_STALE)
        price, liquidity = snapshot.price_usd, snapshot.liquidity_usd
        if price is None or price <= 0:
            reasons.append(Reason.PRICE_INVALID)
        if liquidity is None or liquidity <= 0:
            reasons.append(Reason.LIQUIDITY_INVALID)
        if snapshot.trading_status is not TradingStatus.TRADING:
            reasons.append(Reason.TRADING_STATUS_UNSAFE)
        return age, price, liquidity

    async def _inspect_mint(self, mint: str) -> TokenInspection:
        await self._rpc.start()
        try:
            result = await self._rpc.call(
                "getAccountInfo", [mint, {"encoding": "base64", "commitment": "confirmed"}]
            )
        finally:
            await self._rpc.close()
        value = (result or {}).get("value") if isinstance(result, dict) else None
        if not isinstance(value, dict):
            raise ValueError("Mint account unavailable")
        return _decode_mint_account(value)

    @staticmethod
    def _token_reasons(inspection: TokenInspection, reasons: list[str]) -> None:
        if inspection.token_program not in {TOKEN_PROGRAM, TOKEN_2022_PROGRAM}:
            reasons.append(Reason.UNSUPPORTED_TOKEN_PROGRAM)
        if inspection.token_program == TOKEN_2022_PROGRAM:
            allowed = {
                int(value)
                for value in settings.REAL_WALLET_SAFETY_SUPPORTED_TOKEN_2022_EXTENSIONS
            }
            if any(value not in allowed for value in inspection.extensions):
                reasons.append(Reason.UNSUPPORTED_TOKEN_EXTENSION)
        if inspection.mint_authority_active:
            reasons.append(Reason.MINT_AUTHORITY_ACTIVE)
        if inspection.freeze_authority_active:
            reasons.append(Reason.FREEZE_AUTHORITY_ACTIVE)

    @staticmethod
    def _quote_checks(
        quoted_at: datetime,
        impact: Decimal | None,
        side: str,
        now: datetime,
        reasons: list[str],
    ) -> None:
        age = Decimal(str((now - quoted_at).total_seconds()))
        if (
            age < 0
            or age > settings.REAL_WALLET_SAFETY_MAX_QUOTE_AGE_SECONDS
            or impact is None
        ):
            reasons.append(Reason.QUOTE_INVALID)
            return
        max_impact = (
            settings.REAL_WALLET_SAFETY_MAX_BUY_PRICE_IMPACT_PCT
            if side == "buy"
            else settings.REAL_WALLET_SAFETY_MAX_SELL_PRICE_IMPACT_PCT
        )
        if impact > max_impact:
            reasons.append(
                Reason.BUY_PRICE_IMPACT_TOO_HIGH
                if side == "buy"
                else Reason.SELL_PRICE_IMPACT_TOO_HIGH
            )

    async def _persist(self, decision: SafetyDecision) -> SafetyDecision:
        row = RealWalletSafetyEvaluation(
            mint_address=decision.mint_address,
            decision=decision.decision,
            evaluated_at=decision.evaluated_at,
            trade_size_usd=decision.trade_size_usd,
            policy_version=decision.policy_version,
            reason_codes=list(decision.reason_codes),
            market_snapshot_at=decision.market_snapshot_at,
            market_age_seconds=decision.market_age_seconds,
            market_price_usd=decision.market_price_usd,
            liquidity_usd=decision.liquidity_usd,
            buy_price_impact_pct=decision.buy_price_impact_pct,
            sell_price_impact_pct=decision.sell_price_impact_pct,
            round_trip_loss_usd=decision.round_trip_loss_usd,
            round_trip_loss_pct=decision.round_trip_loss_pct,
            position_liquidity_ratio=decision.position_liquidity_ratio,
            token_program=decision.token_program,
            mint_authority_active=decision.mint_authority_active,
            freeze_authority_active=decision.freeze_authority_active,
            token_extensions=list(decision.token_extensions),
            provenance=decision.provenance,
            buy_quote=decision.buy_quote,
            sell_quote=decision.sell_quote,
            token_configuration=decision.token_configuration,
        )
        self._session.add(row)
        await self._session.flush()
        return replace(decision, evaluation_id=row.id)
