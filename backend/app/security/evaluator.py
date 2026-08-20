"""The shared token-security evaluator.

Read-only. It performs one public `getAccountInfo` per mint and reads the
market snapshot the platform already stores. It cannot open a position, build
a transaction, request a wallet, or touch a kill switch.

LIQUIDITY SECURITY — VERIFIED ON-CHAIN AS OF SEC-1

HQ-6 answered `LIQUIDITY_SECURITY` as UNKNOWN for every token, because nothing
in this codebase had ever read a pool account. (`verify_liquidity_security()`,
which an earlier phase believed existed, never did — it was hallucinated into
`paper/service.py` and removed in commit `3bac791`.)

SEC-1 replaces that constant with real verification. See
`app/security/liquidity.py` for the protocol facts and how each was
established from live mainnet state, and `liquidity_verifier.py` for what a
PASS does and does not prove.

`VENUE` remains a separate check and remains what it always was: a comparison
of `snapshot.dex_name` against a configured list. It is venue *recognition*
and it is never evidence about custody. The two checks are kept apart so that
recognising a venue can never stand in for proving the liquidity is safe —
which is the mistake this whole area of the codebase exists to prevent.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.market import TokenMarketSnapshot
from app.repositories.market import MarketSnapshotRepository
from app.security.contract import (
    EVALUATOR_VERSION,
    CheckName,
    CheckStatus,
    Reason,
    SecurityCheck,
    TokenSecurityEvaluation,
    roll_up,
)
from app.security.liquidity_verifier import LiquiditySecurityVerifier, to_check
from app.security.mint import (
    DANGEROUS_EXTENSIONS,
    TOKEN_2022_PROGRAM,
    TOKEN_PROGRAM,
    TokenInspection,
    decode_mint_account,
)
from app.services.rpc.base import RpcError, SolanaRPC
from app.services.rpc.registry import get_rpc

logger = get_logger(__name__)


def _unknown(name: CheckName, code: str, detail: str) -> SecurityCheck:
    return SecurityCheck(
        name=name, status=CheckStatus.UNKNOWN, reason_codes=(code,), detail=detail
    )


def evaluate_inspection(inspection: TokenInspection | None) -> list[SecurityCheck]:
    """The four mint-account checks. Pure — this is the testable core.

    A `None` inspection means the account could not be read, and every check
    it would have answered becomes UNKNOWN rather than absent. A check that
    silently disappears when its source fails would make `roll_up` compute
    VERIFIED over a shorter list, which is the exact bug the contract is
    designed to make impossible.
    """
    if inspection is None:
        return [
            _unknown(
                name,
                Reason.MINT_ACCOUNT_UNAVAILABLE,
                "The mint account could not be read, so this could not be checked.",
            )
            for name in (
                CheckName.MINT_AUTHORITY,
                CheckName.FREEZE_AUTHORITY,
                CheckName.TOKEN_PROGRAM,
                CheckName.TOKEN_EXTENSIONS,
            )
        ]

    checks: list[SecurityCheck] = []

    for name, active, code, noun in (
        (
            CheckName.MINT_AUTHORITY,
            inspection.mint_authority_active,
            Reason.MINT_AUTHORITY_ACTIVE,
            "Mint authority",
        ),
        (
            CheckName.FREEZE_AUTHORITY,
            inspection.freeze_authority_active,
            Reason.FREEZE_AUTHORITY_ACTIVE,
            "Freeze authority",
        ),
    ):
        if active is None:
            checks.append(
                _unknown(
                    name,
                    Reason.TOKEN_CONFIGURATION_UNKNOWN,
                    f"{noun} could not be read from the mint account.",
                )
            )
        elif active:
            checks.append(
                SecurityCheck(
                    name=name,
                    status=CheckStatus.FAIL,
                    reason_codes=(code,),
                    detail=f"{noun} is still held and can be used against holders.",
                    evidence={"active": True},
                )
            )
        else:
            checks.append(
                SecurityCheck(
                    name=name,
                    status=CheckStatus.PASS,
                    detail=f"{noun} is revoked. Revocation is irreversible.",
                    evidence={"active": False},
                )
            )

    program = inspection.token_program
    if program is None:
        checks.append(
            _unknown(
                CheckName.TOKEN_PROGRAM,
                Reason.TOKEN_CONFIGURATION_UNKNOWN,
                "The owning token program could not be read.",
            )
        )
    elif program in {TOKEN_PROGRAM, TOKEN_2022_PROGRAM}:
        checks.append(
            SecurityCheck(
                name=CheckName.TOKEN_PROGRAM,
                status=CheckStatus.PASS,
                detail=(
                    "Owned by Token-2022."
                    if program == TOKEN_2022_PROGRAM
                    else "Owned by the SPL Token program."
                ),
                evidence={"token_program": program},
            )
        )
    else:
        checks.append(
            SecurityCheck(
                name=CheckName.TOKEN_PROGRAM,
                status=CheckStatus.FAIL,
                reason_codes=(Reason.UNSUPPORTED_TOKEN_PROGRAM,),
                detail="The mint is owned by an unrecognised program.",
                evidence={"token_program": program},
            )
        )

    # Extensions only exist under Token-2022. A plain SPL mint is answered
    # NOT_APPLICABLE — a complete answer — and never UNKNOWN.
    if program == TOKEN_2022_PROGRAM:
        dangerous = {
            value: DANGEROUS_EXTENSIONS[value]
            for value in inspection.extensions
            if value in DANGEROUS_EXTENSIONS
        }
        allowed = {
            int(value)
            for value in settings.REAL_WALLET_SAFETY_SUPPORTED_TOKEN_2022_EXTENSIONS
        }
        unrecognised = [
            value
            for value in inspection.extensions
            if value not in allowed and value not in DANGEROUS_EXTENSIONS
        ]
        if dangerous:
            checks.append(
                SecurityCheck(
                    name=CheckName.TOKEN_EXTENSIONS,
                    status=CheckStatus.FAIL,
                    reason_codes=(Reason.UNSUPPORTED_TOKEN_EXTENSION,),
                    detail="Dangerous extension: " + ", ".join(sorted(dangerous.values())),
                    evidence={
                        "extensions": list(inspection.extensions),
                        "dangerous": dangerous,
                    },
                )
            )
        elif unrecognised:
            # Not presumed safe and not declared dangerous: an extension
            # nobody has classified is the definition of UNKNOWN.
            checks.append(
                SecurityCheck(
                    name=CheckName.TOKEN_EXTENSIONS,
                    status=CheckStatus.UNKNOWN,
                    reason_codes=(Reason.UNSUPPORTED_TOKEN_EXTENSION,),
                    detail=(
                        "Carries extensions this platform has not classified: "
                        + ", ".join(str(value) for value in sorted(unrecognised))
                    ),
                    evidence={
                        "extensions": list(inspection.extensions),
                        "unclassified": sorted(unrecognised),
                    },
                )
            )
        else:
            checks.append(
                SecurityCheck(
                    name=CheckName.TOKEN_EXTENSIONS,
                    status=CheckStatus.PASS,
                    detail=(
                        "No extensions."
                        if not inspection.extensions
                        else "Only metadata extensions, which cannot move or freeze a balance."
                    ),
                    evidence={"extensions": list(inspection.extensions)},
                )
            )
    else:
        checks.append(
            SecurityCheck(
                name=CheckName.TOKEN_EXTENSIONS,
                status=CheckStatus.NOT_APPLICABLE,
                detail="Not a Token-2022 mint, so there are no extensions to carry.",
            )
        )

    return checks


def evaluate_venue(snapshot: TokenMarketSnapshot | None) -> list[SecurityCheck]:
    """Venue recognition only.

    `VENUE` says whether the market is one the platform recognises. It says
    nothing about custody, and since SEC-1 it no longer pretends to: the
    liquidity verdict comes from `liquidity_verifier`, which reads accounts.
    """
    venue = (snapshot.dex_name or "").strip().lower() if snapshot else ""
    supported = {value.lower() for value in settings.REAL_WALLET_SAFETY_SUPPORTED_VENUES}

    if not venue:
        venue_check = _unknown(
            CheckName.VENUE,
            Reason.VENUE_UNKNOWN,
            "No market snapshot names a venue for this token.",
        )
    elif venue in supported:
        venue_check = SecurityCheck(
            name=CheckName.VENUE,
            status=CheckStatus.PASS,
            detail=f"Trading on {venue}, a recognised venue.",
            evidence={"venue": venue},
        )
    else:
        venue_check = SecurityCheck(
            name=CheckName.VENUE,
            status=CheckStatus.FAIL,
            reason_codes=(Reason.VENUE_UNSUPPORTED,),
            detail=f"Trading on {venue}, which this platform does not recognise.",
            evidence={"venue": venue},
        )

    return [venue_check]


class TokenSecurityEvaluator:
    """Evaluate one mint. Read-only, one RPC call, no trade size required.

    Independence from `REAL_WALLET_EXECUTION_MODE` is the point. HQ-5 found
    that the only per-mint security evidence in the platform was written by
    the Real Wallet's dry-run preview, so with the wallet disabled the whole
    deployment could say nothing at all about any token. Security is a
    property of the token, not of whether someone enabled a wallet.
    """

    def __init__(self, session: AsyncSession, *, rpc: SolanaRPC | None = None) -> None:
        self._session = session
        self._rpc = rpc or get_rpc()
        self._market = MarketSnapshotRepository(session)

    async def evaluate(
        self, *, mint_address: str, now: datetime | None = None
    ) -> TokenSecurityEvaluation:
        evaluated_at = (now or datetime.now(UTC)).astimezone(UTC)
        snapshot = await self._market.latest_for_mint(mint_address)
        inspection = await self._inspect(mint_address)
        liquidity = await self._verify_liquidity(mint_address, snapshot)

        checks = tuple(
            evaluate_inspection(inspection) + evaluate_venue(snapshot) + [liquidity]
        )
        return TokenSecurityEvaluation(
            mint_address=mint_address,
            evaluated_at=evaluated_at,
            overall_status=roll_up(checks),
            checks=checks,
            evaluator_version=EVALUATOR_VERSION,
            market_snapshot_at=snapshot.captured_at if snapshot else None,
            evidence={
                "token_program": inspection.token_program if inspection else None,
                "decimals": inspection.decimals if inspection else None,
                "extensions": list(inspection.extensions) if inspection else None,
                "venue": (snapshot.dex_name if snapshot else None),
                "liquidity_usd": (
                    str(snapshot.liquidity_usd)
                    if snapshot and snapshot.liquidity_usd is not None
                    else None
                ),
            },
        )

    async def _verify_liquidity(
        self, mint: str, snapshot: TokenMarketSnapshot | None
    ) -> SecurityCheck:
        """Read the chain, or answer UNKNOWN. Never FAIL on infrastructure.

        Wrapped whole: a verifier that raised would take the entire evaluation
        with it, and an evaluation that vanishes is worse than one that admits
        it does not know.
        """
        try:
            await self._rpc.start()
            try:
                finding = await LiquiditySecurityVerifier(self._rpc).verify(
                    mint,
                    # The market the platform actually prices. Passed in so a
                    # verified mechanism can never vouch for a different venue.
                    traded_venue=(snapshot.dex_name if snapshot else None),
                    traded_pool=(snapshot.pool_address if snapshot else None),
                )
            finally:
                await self._rpc.close()
            return to_check(finding)
        except Exception:
            logger.warning("liquidity_security_failed", mint_address=mint)
            return SecurityCheck(
                name=CheckName.LIQUIDITY_SECURITY,
                status=CheckStatus.UNKNOWN,
                reason_codes=(Reason.LIQUIDITY_SECURITY_UNVERIFIED,),
                detail="Liquidity security could not be checked.",
                evidence={"mechanism": "NONE"},
            )

    async def _inspect(self, mint: str) -> TokenInspection | None:
        """Read the mint account, or answer `None` so every check reads UNKNOWN.

        Provider failure and malformed data are both swallowed here on
        purpose. They are *infrastructure* outcomes and the contract's job is
        to keep them separate from "this token was inspected and is unsafe" —
        so they arrive as an absence of evidence, never as a rejection.
        """
        try:
            await self._rpc.start()
            try:
                result = await self._rpc.call(
                    "getAccountInfo",
                    [mint, {"encoding": "base64", "commitment": "confirmed"}],
                )
            finally:
                await self._rpc.close()
            value = (result or {}).get("value") if isinstance(result, dict) else None
            if not isinstance(value, dict):
                return None
            return decode_mint_account(value)
        except (RpcError, ValueError, TypeError, KeyError):
            logger.warning("token_security_inspect_failed", mint_address=mint)
            return None
        except Exception:
            logger.exception("token_security_inspect_error", mint_address=mint)
            return None
