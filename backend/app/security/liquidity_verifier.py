"""Fetches the accounts that decide liquidity security, and classifies them.

Two `getMultipleAccounts` calls per token, both batched:

    1. [bonding curve, migration pool]      — both addresses derived locally
    2. [lp mint, base vault, quote vault]   — only when a pool was found

Nothing is searched for. `getProgramAccounts` is never used: the curve and the
canonical migration pool are program-derived from the mint, so the evaluator
addresses accounts it has never seen, exactly as `curve/collector.py` does.

WHAT A PASS PROVES — AND WHAT IT DOES NOT
-----------------------------------------

PASS answers one narrow question:

    Can the token's creator unilaterally remove the liquidity backing this
    market?

It does **not** mean the token is safe, cannot lose value, cannot be dumped by
holders, or is free of contract risk. Those are different checks and some of
them (mint authority, freeze authority, extensions) are separate members of
the same evaluation. Sellability is deliberately not folded in here (§14).

For `PUMPSWAP_MIGRATED_LP_BURNED` the proof is strong: the pool address is
derived from the pump.fun migration authority, so a matching account proves
provenance cryptographically, and an LP supply of zero proves no redeemable
claim on the reserves exists. Neither fact rests on `dex_name`.

For `BONDING_CURVE_CUSTODY` the proof is narrower and the limit is stated
rather than hidden: the reserves are held by a program-derived curve account
with no LP token and no user-held authority, so no *creator* withdrawal path
exists through account authority. It does not prove the pump.fun program
itself contains no privileged instruction — that is a program-audit question,
not an account-state one, and this module does not claim to have answered it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.security.contract import CheckName, CheckStatus, Reason, SecurityCheck
from app.security.liquidity import (
    PUMPSWAP_PROGRAM,
    WSOL_MINT,
    Mechanism,
    PoolState,
    derive_or_none,
    parse_pool,
)
from app.services.curve.state import CurveState
from app.services.curve.state import parse as parse_curve
from app.services.rpc.base import RpcError, SolanaRPC

logger = get_logger(__name__)

_TOKEN_PROGRAMS = {
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
}


@dataclass(frozen=True, slots=True)
class LiquidityFinding:
    """The classified result, plus the evidence that produced it."""

    status: CheckStatus
    mechanism: Mechanism
    reason_codes: tuple[str, ...]
    detail: str
    evidence: dict[str, Any]


def _finding(
    status: CheckStatus,
    mechanism: Mechanism,
    detail: str,
    evidence: dict[str, Any],
    *codes: str,
) -> LiquidityFinding:
    return LiquidityFinding(
        status=status,
        mechanism=mechanism,
        reason_codes=tuple(codes),
        detail=detail,
        evidence=evidence,
    )


def classify(
    *,
    mint: str,
    curve_account: dict[str, Any] | None,
    curve_state: CurveState | None,
    pool_account: dict[str, Any] | None,
    pool_state: PoolState | None,
    lp_supply: int | None,
    vaults: dict[str, dict[str, Any] | None],
    pumpfun_program: str,
    derived: dict[str, str],
    traded_venue: str | None = None,
    traded_pool: str | None = None,
) -> LiquidityFinding:
    """The whole decision, as a pure function of already-fetched accounts.

    Written this way so every branch — including the adversarial ones — is
    testable against literal account dictionaries with no network.
    """
    evidence: dict[str, Any] = {"derived": derived}

    # --- still on the bonding curve? ------------------------------------
    curve_owned = (
        isinstance(curve_account, dict) and curve_account.get("owner") == pumpfun_program
    )
    if curve_owned and curve_state is not None and not curve_state.complete:
        evidence |= {
            "curve_complete": False,
            "real_sol_reserves": curve_state.real_sol_reserves,
            "real_token_reserves": curve_state.real_token_reserves,
        }
        return _traded_market_guard(
            _finding(
                CheckStatus.PASS,
                Mechanism.BONDING_CURVE_CUSTODY,
                (
                    "Still on its pump.fun bonding curve. The reserves are held by the "
                    "program-derived curve account, there is no LP token, and no "
                    "creator-held authority over them exists."
                ),
                evidence,
            ),
            traded_venue=traded_venue,
            traded_pool=traded_pool,
            expected_venue="pumpfun",
            expected_pool=None,
        )

    if curve_owned and curve_state is None:
        return _finding(
            CheckStatus.UNKNOWN,
            Mechanism.NONE,
            "A pump.fun curve account exists for this mint but did not decode.",
            evidence,
            Reason.BONDING_CURVE_INVALID,
        )

    evidence["curve_complete"] = bool(curve_state.complete) if curve_state else None

    # --- graduated: verify the destination ------------------------------
    if pool_account is None:
        # No account at the derived canonical migration pool address. The
        # token's liquidity is somewhere this evaluator cannot name, which is
        # an absence of evidence and never a failure of the token.
        return _finding(
            CheckStatus.UNKNOWN,
            Mechanism.NONE,
            (
                "No pump.fun migration pool exists at the derived address, so the "
                "liquidity backing this market has not been located on-chain."
            ),
            evidence,
            Reason.POOL_NOT_PROTOCOL_MIGRATED,
            *(
                (Reason.MIGRATION_DESTINATION_UNVERIFIED,)
                if curve_state is not None and curve_state.complete
                else ()
            ),
        )

    owner = pool_account.get("owner")
    evidence["pool_owner"] = owner
    if owner != PUMPSWAP_PROGRAM:
        # The derived address exists but is not a PumpSwap account. Refuse.
        return _finding(
            CheckStatus.UNKNOWN,
            Mechanism.NONE,
            "The derived pool address is not owned by the PumpSwap program.",
            evidence,
            Reason.POOL_PROGRAM_MISMATCH,
        )

    if pool_state is None:
        return _finding(
            CheckStatus.UNKNOWN,
            Mechanism.NONE,
            "The pool account did not decode as a PumpSwap pool.",
            evidence,
            Reason.POOL_ACCOUNT_INVALID,
        )

    evidence |= {
        "pool": derived.get("pool"),
        "pool_authority": derived.get("pool_authority"),
        "creator": pool_state.creator,
        "base_mint": pool_state.base_mint,
        "quote_mint": pool_state.quote_mint,
        "lp_mint": pool_state.lp_mint,
    }

    # The mint relationship. The address derivation already encodes it, so a
    # mismatch here means the chain disagrees with the derivation and the only
    # safe response is to stop.
    if pool_state.base_mint != mint or pool_state.quote_mint != WSOL_MINT:
        return _finding(
            CheckStatus.UNKNOWN,
            Mechanism.NONE,
            "The pool's mint pair is not this token quoted in wrapped SOL.",
            evidence,
            Reason.POOL_MINT_MISMATCH,
        )

    # Defence in depth: the pool address was derived *from* this authority, so
    # this can only fail if the layout drifted.
    if pool_state.creator != derived.get("pool_authority"):
        return _finding(
            CheckStatus.UNKNOWN,
            Mechanism.NONE,
            "The pool's creator is not the pump.fun migration authority for this mint.",
            evidence,
            Reason.POOL_NOT_PROTOCOL_MIGRATED,
        )

    # --- vaults ---------------------------------------------------------
    for label, address in (("base", pool_state.base_vault), ("quote", pool_state.quote_vault)):
        account = vaults.get(address)
        parsed = _parsed_token_account(account)
        if parsed is None:
            return _finding(
                CheckStatus.UNKNOWN,
                Mechanism.NONE,
                f"The pool's {label} vault could not be read.",
                evidence,
                Reason.POOL_VAULT_INVALID,
            )
        expected_mint = pool_state.base_mint if label == "base" else pool_state.quote_mint
        if parsed["mint"] != expected_mint or parsed["owner"] != derived.get("pool"):
            # A vault whose authority is not the pool is the exact shape of a
            # pool that looks valid and is not.
            return _finding(
                CheckStatus.UNKNOWN,
                Mechanism.NONE,
                f"The pool's {label} vault is not held by this pool for this mint.",
                evidence,
                Reason.POOL_VAULT_INVALID,
            )
        evidence[f"{label}_vault_amount"] = parsed["amount"]

    # --- the LP claim ---------------------------------------------------
    if lp_supply is None:
        return _finding(
            CheckStatus.UNKNOWN,
            Mechanism.NONE,
            "The LP mint supply could not be read, so redeemable claims are unknown.",
            evidence,
            Reason.LP_CUSTODY_UNKNOWN,
        )
    evidence["lp_supply"] = str(lp_supply)

    if lp_supply > 0:
        # Somebody can redeem LP for a share of the reserves. This evaluator
        # does not resolve holders, and guessing would be worse than silence.
        return _finding(
            CheckStatus.UNKNOWN,
            Mechanism.NONE,
            (
                "LP tokens are outstanding, so a redeemable claim on these reserves "
                "exists. Who holds them was not established."
            ),
            evidence,
            Reason.LP_OUTSTANDING,
        )

    return _traded_market_guard(
        _finding(
            CheckStatus.PASS,
            Mechanism.PUMPSWAP_MIGRATED_LP_BURNED,
            (
                "Pump.fun migration pool with no outstanding LP supply: the migration LP "
                "was burned, so no redeemable claim on these reserves exists and the "
                "creator cannot withdraw them."
            ),
            evidence,
        ),
        traded_venue=traded_venue,
        traded_pool=traded_pool,
        expected_venue="pumpswap",
        expected_pool=derived.get("pool"),
    )


def _traded_market_guard(
    finding: LiquidityFinding,
    *,
    traded_venue: str | None,
    traded_pool: str | None,
    expected_venue: str,
    expected_pool: str | None,
) -> LiquidityFinding:
    """Refuse to let a verified mechanism vouch for a market it is not.

    Found the hard way during SEC-1. Mint
    `GbM8TcLhMnRAda4ccagVvxRXiiDa7sQvPFKUivqNpump` is genuinely still on its
    pump.fun bonding curve — 24.5% progress, 6.6 SOL of real reserves, and the
    curve custody verdict for it is entirely correct. It also has an **Orca**
    pool holding $194,646, and Orca is the venue this platform prices and
    would trade.

    Verifying the curve and reporting PASS would therefore have been true
    about the wrong market. The curve's 6.6 SOL is secure; the $194k that
    actually backs the price is not something this evaluator has looked at.

    So a PASS survives only when the market the platform reads is the market
    that was verified. Anything else is UNKNOWN — the honest statement being
    "we proved custody somewhere, but not here". This is also §12's
    multiple-pool rule: rather than picking a pool, the evaluator refuses when
    the traded one is not the derived one.
    """
    venue = (traded_venue or "").strip().lower()
    if venue and venue != expected_venue:
        return LiquidityFinding(
            status=CheckStatus.UNKNOWN,
            mechanism=Mechanism.NONE,
            reason_codes=(Reason.TRADED_POOL_UNVERIFIED,),
            detail=(
                f"Custody was verified for this token's {expected_venue} liquidity, "
                f"but the market this platform prices is on {venue}, which was not "
                "verified."
            ),
            evidence={
                **finding.evidence,
                "verified_mechanism": str(finding.mechanism),
                "traded_venue": venue,
                "traded_pool": traded_pool,
            },
        )
    if expected_pool and traded_pool and traded_pool != expected_pool:
        return LiquidityFinding(
            status=CheckStatus.UNKNOWN,
            mechanism=Mechanism.NONE,
            reason_codes=(Reason.TRADED_POOL_UNVERIFIED,),
            detail=(
                "The pool this platform prices is not the pump.fun migration pool "
                "that was verified."
            ),
            evidence={
                **finding.evidence,
                "verified_mechanism": str(finding.mechanism),
                "traded_pool": traded_pool,
                "verified_pool": expected_pool,
            },
        )
    return finding


def _parsed_token_account(account: dict[str, Any] | None) -> dict[str, Any] | None:
    """Read a `jsonParsed` SPL token account, or `None` if it is not one."""
    if not isinstance(account, dict) or account.get("owner") not in _TOKEN_PROGRAMS:
        return None
    data = account.get("data")
    parsed = data.get("parsed") if isinstance(data, dict) else None
    if not isinstance(parsed, dict) or parsed.get("type") != "account":
        return None
    info = parsed.get("info")
    if not isinstance(info, dict):
        return None
    amount = (info.get("tokenAmount") or {}).get("amount")
    if not isinstance(info.get("mint"), str) or not isinstance(info.get("owner"), str):
        return None
    return {"mint": info["mint"], "owner": info["owner"], "amount": amount}


def _parsed_mint_supply(account: dict[str, Any] | None) -> int | None:
    if not isinstance(account, dict) or account.get("owner") not in _TOKEN_PROGRAMS:
        return None
    data = account.get("data")
    parsed = data.get("parsed") if isinstance(data, dict) else None
    if not isinstance(parsed, dict) or parsed.get("type") != "mint":
        return None
    supply = (parsed.get("info") or {}).get("supply")
    try:
        return int(supply)
    except (TypeError, ValueError):
        return None


class LiquiditySecurityVerifier:
    """Read-only. Cannot build, sign or submit a transaction."""

    def __init__(self, rpc: SolanaRPC, *, pumpfun_program: str | None = None) -> None:
        self._rpc = rpc
        self._pumpfun = pumpfun_program or settings.PUMPFUN_PROGRAM_ID

    async def verify(
        self, mint: str, *, traded_venue: str | None = None, traded_pool: str | None = None
    ) -> LiquidityFinding:
        derived_pair = derive_or_none(mint, pumpfun_program=self._pumpfun)
        if derived_pair is None:
            return _finding(
                CheckStatus.UNKNOWN,
                Mechanism.NONE,
                "The mint address could not be decoded, so no account could be derived.",
                {},
                Reason.LIQUIDITY_SECURITY_UNVERIFIED,
            )
        pool_address, authority = derived_pair
        from app.services.curve.pda import bonding_curve_address

        try:
            curve_address = bonding_curve_address(mint, program_id=self._pumpfun)
        except (ValueError, RuntimeError):
            curve_address = None

        derived = {
            "pool": pool_address,
            "pool_authority": authority,
            "bonding_curve": curve_address,
            "pumpswap_program": PUMPSWAP_PROGRAM,
            "pumpfun_program": self._pumpfun,
        }

        try:
            first = await self._accounts(
                [address for address in (curve_address, pool_address) if address],
                encoding="base64",
            )
        except (RpcError, ValueError, TypeError):
            return _finding(
                CheckStatus.UNKNOWN,
                Mechanism.NONE,
                "The chain could not be read, so liquidity security is unknown.",
                {"derived": derived},
                Reason.LIQUIDITY_SECURITY_UNVERIFIED,
            )

        curve_account = first.get(curve_address) if curve_address else None
        pool_account = first.get(pool_address)
        curve_state = parse_curve(_raw(curve_account)) if curve_account else None
        pool_state = parse_pool(_raw(pool_account)) if pool_account else None

        lp_supply: int | None = None
        vaults: dict[str, dict[str, Any] | None] = {}
        if pool_state is not None:
            wanted = [pool_state.lp_mint, pool_state.base_vault, pool_state.quote_vault]
            try:
                second = await self._accounts(wanted, encoding="jsonParsed")
            except (RpcError, ValueError, TypeError):
                second = {}
            lp_supply = _parsed_mint_supply(second.get(pool_state.lp_mint))
            vaults = {
                pool_state.base_vault: second.get(pool_state.base_vault),
                pool_state.quote_vault: second.get(pool_state.quote_vault),
            }

        return classify(
            mint=mint,
            curve_account=curve_account,
            curve_state=curve_state,
            pool_account=pool_account,
            pool_state=pool_state,
            lp_supply=lp_supply,
            vaults=vaults,
            pumpfun_program=self._pumpfun,
            derived=derived,
            traded_venue=traded_venue,
            traded_pool=traded_pool,
        )

    async def _accounts(
        self, addresses: list[str], *, encoding: str
    ) -> dict[str, dict[str, Any] | None]:
        """One `getMultipleAccounts` call, keyed by address."""
        if not addresses:
            return {}
        result = await self._rpc.call(
            "getMultipleAccounts",
            [addresses, {"encoding": encoding, "commitment": "confirmed"}],
        )
        values = (result or {}).get("value") if isinstance(result, dict) else None
        if not isinstance(values, list):
            raise ValueError("getMultipleAccounts returned no value array")
        return dict(zip(addresses, values, strict=False))


def _raw(account: dict[str, Any] | None) -> bytes | None:
    import base64

    if not isinstance(account, dict):
        return None
    data = account.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], str):
        return None
    try:
        return base64.b64decode(data[0])
    except Exception:
        return None


def to_check(finding: LiquidityFinding) -> SecurityCheck:
    """Render a finding as the shared contract's `LIQUIDITY_SECURITY` check."""
    return SecurityCheck(
        name=CheckName.LIQUIDITY_SECURITY,
        status=finding.status,
        reason_codes=finding.reason_codes,
        detail=finding.detail,
        evidence={"mechanism": str(finding.mechanism), **finding.evidence},
    )
