"""Read-only balance lookup for a configured execution-wallet public address."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.rpc.base import SolanaRPC

LAMPORTS_PER_SOL = 1_000_000_000


@dataclass(frozen=True, slots=True)
class ExecutionWalletBalance:
    public_key: str
    lamports: int

    @property
    def sol(self) -> float:
        return self.lamports / LAMPORTS_PER_SOL


class ExecutionWalletBalanceService:
    """Uses public RPC `getBalance`; it never loads or needs a signer."""

    def __init__(self, rpc: SolanaRPC) -> None:
        self._rpc = rpc

    async def get_sol_balance(self, public_key: str) -> ExecutionWalletBalance:
        result = await self._rpc.call("getBalance", [public_key, {"commitment": "confirmed"}])
        if not isinstance(result, dict) or not isinstance(result.get("value"), int):
            raise ValueError("execution_wallet_balance_unavailable")
        return ExecutionWalletBalance(public_key=public_key, lamports=result["value"])
