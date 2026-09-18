"""Real-wallet safety policy evaluation with no execution capability.

The result is intentionally independent of strategies and wallets.  A future
executor must consume an ``ALLOW`` decision; this service cannot create swaps,
sign a transaction, or access wallet credentials.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.labs.graduation.models import (
    SOURCE_HELD_WS,
    GradPaperPosition,
    GradPostgradSample,
    GradToken,
)
from app.models.market import TokenMarketSnapshot, TradingStatus
from app.models.real_wallet_execution import RealWalletPosition
from app.models.real_wallet_safety import RealWalletSafetyEvaluation
from app.models.token import DiscoveredToken
from app.real_wallet_safety import holders, sources
from app.repositories.market import MarketSnapshotRepository
from app.repositories.token import TokenRepository
from app.security.liquidity import PUMPSWAP_PROGRAM
from app.security.mint import (
    PUMP_FUN_PROGRAM,
    TOKEN_2022_PROGRAM,
    TOKEN_PROGRAM,
    TokenInspection,
    decode_mint_account,
)
from app.services.jupiter import JupiterExecutionClient
from app.services.rpc.base import RpcError, SolanaRPC
from app.services.rpc.registry import get_rpc

_ZERO = Decimal(0)
_HUNDRED = Decimal(100)

#: Discovery programs whose observation counts as provenance.
#:
#: What provenance actually asserts is narrow and worth stating plainly: THIS
#: PLATFORM WATCHED THIS TOKEN BEING CREATED ON CHAIN. Not that the token is
#: good, not that it is safe -- only that its existence is first-party
#: evidence, carrying a transaction signature and a slot, rather than a mint
#: address some API handed us. That is what stops money going to a lookalike
#: address, and it is the only thing this particular check defends.
#:
#: PumpSwap was added on 2026-08-27. It had been pump.fun alone since the gate
#: was written on 2026-08-09, when pump.fun was the only thing the scanner
#: discovered -- an artefact of the scanner's population at the time, never a
#: finding that a graduation pool is weaker evidence. It is not weaker: same
#: scanner, same chain observation, same signature, same slot. The only
#: difference is WHICH on-chain event was witnessed, the initial mint or the
#: graduation pool.
#:
#: A constant rather than a setting, deliberately. Everything else the real
#: wallet may reach is a setting, but those answer "how much" and "how often";
#: this answers WHICH TOKENS EXIST ENOUGH TO SEND MONEY TO. Widening it should
#: cost a code review and appear in a diff, not an env var.
#:
#: NOT included, and this is the point of a set rather than a boolean: sources
#: with no slot, such as `jupiter_verified`. A third party's assurance that a
#: token is real is somebody else's evidence, and `slot > 0` below is what
#: makes that distinction load-bearing rather than decorative.
VERIFIED_DISCOVERY_PROGRAMS = frozenset({PUMP_FUN_PROGRAM, PUMPSWAP_PROGRAM})

#: How recent the graduation lab's own read of a pool's vaults must be to stand
#: as the price a quote is judged against (the lab's own `HELD_TRUST_S`).
POOL_PRICE_TRUST_S = 30


class Reason:
    PROVENANCE_UNVERIFIED = "PROVENANCE_UNVERIFIED"
    VENUE_UNSUPPORTED = "VENUE_UNSUPPORTED"
    MARKET_DATA_MISSING = "MARKET_DATA_MISSING"
    MARKET_DATA_STALE = "MARKET_DATA_STALE"
    PRICE_INVALID = "PRICE_INVALID"
    LIQUIDITY_INVALID = "LIQUIDITY_INVALID"
    TRADING_STATUS_UNSAFE = "TRADING_STATUS_UNSAFE"
    POSITION_TOO_LARGE_FOR_LIQUIDITY = "POSITION_TOO_LARGE_FOR_LIQUIDITY"
    POSITION_TOO_LARGE_FOR_SUPPLY = "POSITION_TOO_LARGE_FOR_SUPPLY"
    TOKEN_SUPPLY_UNREADABLE = "TOKEN_SUPPLY_UNREADABLE"  # noqa: S105
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
    SYMBOL_RUGGED_BEFORE = "SYMBOL_RUGGED_BEFORE"
    HOLDER_TOO_LARGE = "HOLDER_TOO_LARGE"
    HOLDERS_UNREADABLE = "HOLDERS_UNREADABLE"
    LINKED_TO_RECENT_RUG = "LINKED_TO_RECENT_RUG"
    KNOWN_RUG_MONEY = "KNOWN_RUG_MONEY"
    SOURCES_UNREADABLE = "SOURCES_UNREADABLE"
    SAFETY_CALCULATION_FAILED = "SAFETY_CALCULATION_FAILED"


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
    #: Fraction of the token's whole supply this position would buy, and the
    #: supply it was measured against. Both None when the supply was unreadable.
    position_supply_ratio: Decimal | None = None
    token_supply: Decimal | None = None


def _decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value)) if value is not None else None
    except (InvalidOperation, ValueError):
        return None


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
        holders_rpc: SolanaRPC | None = None,
    ) -> None:
        self._session = session
        self._rpc = rpc or get_rpc()
        self._jupiter = jupiter or JupiterExecutionClient()
        # Helius, not `get_rpc()`: the platform's node refuses the holder read
        # (public 429s it, this Chainstack plan 403s it). Made on first use.
        self._holders_rpc = holders_rpc

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

        if await self._symbol_has_rugged(mint_address, token):
            reasons.append(Reason.SYMBOL_RUGGED_BEFORE)

        market_age, price, liquidity = self._market_reasons(snapshot, evaluated_at, reasons)
        pool_price = await self._pool_price(mint_address, snapshot, evaluated_at)
        if pool_price is not None:
            provenance = {**provenance,
                          "feed_price_usd": None if price is None else str(price),
                          "pool_price_usd": str(pool_price)}
            price = pool_price
        ratio = None if liquidity is None or liquidity <= 0 else trade_size_usd / liquidity
        if (
            ratio is not None
            and ratio > settings.REAL_WALLET_SAFETY_MAX_POSITION_LIQUIDITY_RATIO
        ):
            reasons.append(Reason.POSITION_TOO_LARGE_FOR_LIQUIDITY)

        # How much of the token itself this buys. A separate question from the
        # liquidity ratio and both are kept: liquidity decides whether the
        # position can be SOLD, supply decides how much of the thing you become.
        # A deep pool will happily fill an order that leaves you holding a tenth
        # of everything in existence, and the exit price for that is not the
        # entry price.
        supply, supply_ratio = await self._supply_reasons(
            mint_address, trade_size_usd, price, reasons
        )

        if settings.REAL_WALLET_HOLDER_GATE_ENABLED:
            view = await self._holder_reasons(mint_address, evaluated_at, reasons)
            if view is not None:
                provenance = {**provenance, "holders": view.summary()}

        if settings.REAL_WALLET_SOURCE_BLOCK_ENABLED:
            provenance = {**provenance, "sources": await self._source_reasons(
                mint_address, evaluated_at, reasons)}

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
            position_supply_ratio=supply_ratio,
            token_supply=supply,
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
                and token.source_program in VERIFIED_DISCOVERY_PROGRAMS
                and token.signature
                and token.slot > 0
            ),
            "source_program": token.source_program if token else None,
            "discovery_signature": token.signature if token else None,
            "discovery_slot": token.slot if token else None,
            "venue": snapshot.dex_name if snapshot else None,
        }

    async def _holder_reasons(
        self, mint: str, at: datetime, reasons: list[str]
    ) -> holders.Holders | None:
        """Who already holds the coin, at the buy; see `holders`. Every reading,
        refused or not, is kept as a `holder_snapshots` row."""
        rpc = self._holders_rpc or get_rpc("helius")
        view: holders.Holders | None = None
        failure: str | None = None
        try:
            await rpc.start()
            try:
                view = await holders.read(rpc, mint)
            finally:
                await rpc.close()
        except Exception as exc:  # an unreadable holder list refuses
            failure = type(exc).__name__
            reasons.append(Reason.HOLDERS_UNREADABLE)
        else:
            reasons.extend(holders.reasons(view, max_pct=settings.REAL_WALLET_MAX_HOLDER_PCT))
        self._session.add(holders.to_row(view, mint, "wallet_gate", at=at, failure=failure))
        return view

    async def _source_reasons(
        self, mint: str, at: datetime, reasons: list[str]
    ) -> dict[str, object]:
        """Is this coin's money the money behind a rug? See `sources`: a rug
        that closed in the window (`LINKED_TO_RECENT_RUG`), or the standing
        list (`KNOWN_RUG_MONEY`). Every buy is traced for the standing list.
        A coin that cannot be traced refuses inside a rug window, as every
        unreadable fact here does; outside one it is let through, so a Helius
        hiccup cannot stop the wallet for a list of three operators."""
        recent = await sources.recent_rug_ids(
            self._session,
            since=at - timedelta(hours=settings.REAL_WALLET_SOURCE_BLOCK_HOURS),
            rug_return=settings.REAL_WALLET_RUG_RETURN)
        rpc = self._holders_rpc or get_rpc("helius")
        try:
            await rpc.start()
            try:
                view = await holders.read(rpc, mint)
                mine = await sources.trace(rpc, [w for w, _ in view.wallets[:2]])
            finally:
                await rpc.close()
        except Exception as exc:
            if recent:
                reasons.append(Reason.SOURCES_UNREADABLE)
            return {"recent_rug_ids": len(recent), "failure": type(exc).__name__}
        ids = mine.ids()
        matched = sorted(ids & (recent | sources.ALWAYS_BLOCKED))
        if ids & recent:
            reasons.append(Reason.LINKED_TO_RECENT_RUG)
        if ids & sources.ALWAYS_BLOCKED:
            reasons.append(Reason.KNOWN_RUG_MONEY)
        return {"recent_rug_ids": len(recent), **mine.as_json(), "matched": matched}

    async def _symbol_has_rugged(
        self, mint_address: str, token: DiscoveredToken | None
    ) -> bool:
        """Has a token by this NAME already rugged, here or in the books?

        The wallet already refuses a mint it has traded, so this is only about
        the name. Karthik asked for it after ZBCN; the measurement is in
        `REAL_WALLET_BLOCK_RUGGED_SYMBOLS` and does not support it, which is
        why it is a setting rather than a rule of the gate.

        The name comes from the graduation lab first: `grad_tokens` carries the
        symbol from the launch message, minutes before `discovered_tokens` has
        one, and a gate that cannot name the token cannot refuse it. An unnamed
        token is allowed through — refusing every nameless mint would refuse
        most of the book, which is a different rule nobody asked for.
        """
        if not settings.REAL_WALLET_BLOCK_RUGGED_SYMBOLS:
            return False
        symbol = await self._session.scalar(
            select(func.coalesce(GradToken.symbol, ""))
            .where(GradToken.mint == mint_address)
        ) or (token.symbol if token is not None else None)
        name = (symbol or "").strip().lower()
        if not name:
            return False
        floor = settings.REAL_WALLET_RUG_RETURN
        paper = select(GradPaperPosition.id).where(
            func.lower(func.trim(GradPaperPosition.symbol)) == name,
            GradPaperPosition.closed_at.is_not(None),
            GradPaperPosition.net_return <= floor,
            GradPaperPosition.mint != mint_address)
        mine = (select(RealWalletPosition.id)
                .join(DiscoveredToken,
                      DiscoveredToken.mint_address == RealWalletPosition.mint_address)
                .where(func.lower(func.trim(DiscoveredToken.symbol)) == name,
                       RealWalletPosition.status == "CLOSED",
                       RealWalletPosition.realised_net_pnl_usd.is_not(None),
                       RealWalletPosition.entry_price_usd * RealWalletPosition.quantity > 0,
                       RealWalletPosition.realised_net_pnl_usd
                       / (RealWalletPosition.entry_price_usd
                          * RealWalletPosition.quantity) <= floor,
                       RealWalletPosition.mint_address != mint_address))
        return bool(await self._session.scalar(
            select(func.count()).select_from(paper.union_all(mine).subquery())))

    async def _supply_reasons(
        self,
        mint_address: str,
        trade_size_usd: Decimal,
        price: Decimal | None,
        reasons: list[str],
    ) -> tuple[Decimal | None, Decimal | None]:
        """What fraction of the token this position would own, and is it too much.

        Read from the chain, not from a stored column: nothing in the token table
        carries supply, and a cached supply is a supply that was true once. Mints
        with an active mint authority can issue more, which is itself a refusal
        the inspector raises separately.

        **Unreadable supply refuses.** `None` here means the read did not happen,
        never that the supply is zero, and a concentration cap that cannot measure
        concentration has not shown the position to be small. Every other
        unmeasured fact in this rail refuses; this one does too.
        """
        if price is None or price <= 0:
            # No price means no token quantity to compute; the market reasons
            # already refused, and adding a second reason would just be noise.
            return None, None
        # Started and closed around the call, exactly as `_inspect_mint` does.
        # `get_rpc()` hands back a NEW, UNSTARTED client, so calling it directly
        # raises "not started" — which this function turns into `None`, which
        # means unreadable, which REFUSES. Every token failed the gate and the
        # reason blamed the token rather than the missing `start()`.
        try:
            await self._rpc.start()
            try:
                supply = await self._rpc.get_token_supply(mint_address)
            finally:
                await self._rpc.close()
        except Exception:  # noqa: BLE001 - an unreadable supply still refuses
            supply = None
        if supply is None:
            reasons.append(Reason.TOKEN_SUPPLY_UNREADABLE)
            return None, None
        quantity = trade_size_usd / price
        ratio = quantity / supply
        if ratio > settings.REAL_WALLET_SAFETY_MAX_SUPPLY_RATIO:
            reasons.append(Reason.POSITION_TOO_LARGE_FOR_SUPPLY)
        return supply, ratio

    async def _pool_price(self, mint: str, snapshot: TokenMarketSnapshot | None,
                          at: datetime) -> Decimal | None:
        """The pool's own price in dollars, from the graduation lab's live read of
        its vaults, when there is one this recent; None otherwise.

        A feed snapshot can carry a price from before a move: DexScreener stamps
        a row with its FETCH time, and the price in it is ~27s older. GitHub,
        2026-09-18 18:14: a 7s-old snapshot still showed the price from before
        an 88% crash; the vaults, read 3s earlier, had the real one. Jupiter's
        quote matched the vaults, the gate compared it with the feed and refused
        EXECUTION_PRICE_DEVIATION_TOO_HIGH, and the paper book the wallet copies
        made +346% on that coin. So a quote is judged against the pool's own
        price when the lab is reading it - it reads every coin its book holds -
        and against the feed's otherwise. A quote far from the POOL is still
        refused, which is what the check is for.

        Dollars through the feed's own SOL rate (price_usd over price_native),
        which a stale print still carries correctly.
        """
        feed_usd = None if snapshot is None else snapshot.price_usd
        feed_native = None if snapshot is None else getattr(snapshot, "price_native", None)
        if not feed_usd or not feed_native or feed_usd <= 0 or feed_native <= 0:
            return None
        native = await self._session.scalar(
            select(GradPostgradSample.price_native)
            .where(GradPostgradSample.mint == mint,
                   GradPostgradSample.source == SOURCE_HELD_WS,
                   GradPostgradSample.price_native > 0,
                   GradPostgradSample.ts <= at,
                   GradPostgradSample.ts >= at - timedelta(seconds=POOL_PRICE_TRUST_S))
            .order_by(GradPostgradSample.ts.desc())
            .limit(1))
        return None if native is None else native * feed_usd / feed_native

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
        return decode_mint_account(value)

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
