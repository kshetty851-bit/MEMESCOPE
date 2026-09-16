"""Read-only balance lookup for a configured execution-wallet public address."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.services.rpc.base import SolanaRPC

LAMPORTS_PER_SOL = 1_000_000_000
TOKEN_PROGRAM_IDS = (
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",  # Token-2022
)


@dataclass(frozen=True, slots=True)
class ExecutionWalletBalance:
    public_key: str
    lamports: int

    @property
    def sol(self) -> float:
        return self.lamports / LAMPORTS_PER_SOL


@dataclass(frozen=True, slots=True)
class ExecutionWalletTokenBalance:
    token_account: str
    mint_address: str
    raw_amount: str
    decimals: int
    program_id: str
    #: What decides whether the account may be closed: "initialized" or
    #: "frozen"; who else may close it; wrapped SOL; Token-2022 fees withheld.
    state: str = "initialized"
    close_authority: str | None = None
    is_native: bool = False
    withheld_amount: int = 0

    @property
    def quantity(self) -> str:
        amount = Decimal(self.raw_amount).scaleb(-self.decimals)
        return format(amount, "f")


def _withheld(extensions: Any) -> int:
    """Token-2022 transfer fees held in the account; -1 when unreadable."""
    total = 0
    for ext in extensions if isinstance(extensions, list) else []:
        if isinstance(ext, dict) and ext.get("extension") == "transferFeeAmount":
            state = ext.get("state")
            try:
                total += int((state or {}).get("withheldAmount") or 0)
            except (AttributeError, TypeError, ValueError):
                return -1
    return total


class ExecutionWalletBalanceService:
    """Uses public RPC `getBalance`; it never loads or needs a signer."""

    def __init__(self, rpc: SolanaRPC) -> None:
        self._rpc = rpc

    async def get_sol_balance(self, public_key: str) -> ExecutionWalletBalance:
        result = await self._rpc.call("getBalance", [public_key, {"commitment": "confirmed"}])
        if not isinstance(result, dict) or not isinstance(result.get("value"), int):
            raise ValueError("execution_wallet_balance_unavailable")
        return ExecutionWalletBalance(public_key=public_key, lamports=result["value"])

    async def get_spl_balances(
        self, public_key: str
    ) -> list[ExecutionWalletTokenBalance]:
        """Read token-program and Token-2022 accounts from standard RPC only."""
        balances: list[ExecutionWalletTokenBalance] = []
        for program_id in TOKEN_PROGRAM_IDS:
            result = await self._rpc.call(
                "getTokenAccountsByOwner",
                [
                    public_key,
                    {"programId": program_id},
                    {"encoding": "jsonParsed", "commitment": "confirmed"},
                ],
            )
            balances.extend(self._parse_token_accounts(result, program_id=program_id))
        return balances

    @staticmethod
    def _parse_token_accounts(
        result: Any, *, program_id: str
    ) -> list[ExecutionWalletTokenBalance]:
        if not isinstance(result, dict) or not isinstance(result.get("value"), list):
            raise ValueError("execution_wallet_spl_balance_unavailable")
        parsed: list[ExecutionWalletTokenBalance] = []
        for account in result["value"]:
            if not isinstance(account, dict) or not isinstance(account.get("pubkey"), str):
                continue
            data = account.get("account", {}).get("data", {})
            info = data.get("parsed", {}).get("info", {}) if isinstance(data, dict) else {}
            token_amount = info.get("tokenAmount", {}) if isinstance(info, dict) else {}
            mint = info.get("mint") if isinstance(info, dict) else None
            raw_amount = token_amount.get("amount") if isinstance(token_amount, dict) else None
            decimals = token_amount.get("decimals") if isinstance(token_amount, dict) else None
            if (
                not isinstance(mint, str)
                or not isinstance(raw_amount, str)
                or not raw_amount.isdigit()
                or not isinstance(decimals, int)
                or decimals < 0
            ):
                continue
            close_authority = info.get("closeAuthority")
            parsed.append(
                ExecutionWalletTokenBalance(
                    token_account=account["pubkey"],
                    mint_address=mint,
                    raw_amount=raw_amount,
                    decimals=decimals,
                    program_id=program_id,
                    state=str(info.get("state") or "unknown"),
                    # Anything unreadable here reads as "someone else may close
                    # it", which keeps the account open.
                    close_authority=(close_authority
                                     if close_authority is None
                                     or isinstance(close_authority, str)
                                     else "unreadable"),
                    is_native=bool(info.get("isNative")),
                    withheld_amount=_withheld(info.get("extensions")),
                )
            )
        return parsed
