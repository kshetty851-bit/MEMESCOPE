"""Create a Canary Intent for manual Mainnet drill validation.

This generates a RealWalletLiveIntent record mapped to a passed safety evaluation
so it can be dry-run via swap assembler or transport testing locally without
waiting for the radar loop.
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionFactory
from app.models.real_wallet_safety import RealWalletSafetyEvaluation
from app.real_wallet.live_repository import LiveIntentRepository
from app.real_wallet.live_readiness import ExecutionState
from app.models.token import DiscoveredToken


async def run(*, side: str, mint: str, amount_usd: Decimal) -> None:
    async with SessionFactory() as session:
        # Require the token to exist, to attach the evaluation cleanly.
        token = (
            await session.execute(select(DiscoveredToken).where(DiscoveredToken.mint_address == mint))
        ).scalar_one_or_none()
        if not token:
            print(f"Token {mint} not found in database. The radar must discover it first.")
            return

        evaluation = RealWalletSafetyEvaluation(
            mint_address=mint,
            decision="ALLOW",
            trade_size_usd=amount_usd,
            policy_version="canary_manual",
            reason_codes=[],
            provenance={"source": "cli_canary"}
        )
        session.add(evaluation)
        await session.flush()

        values: dict[str, Any] = {
            "idempotency_key": f"canary-{uuid.uuid4()}",
            "mint_address": mint,
            "side": side.upper(),
            "strategy_id": "canary_manual",
            "strategy_version": "1.0.0",
            "wallet_public_key": settings.REAL_WALLET_PUBLIC_KEY or "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",
            "requested_usd": amount_usd,
            "input_mint": settings.EXECUTION_SOL_MINT if side.upper() == "BUY" else mint,
            "output_mint": mint if side.upper() == "BUY" else settings.EXECUTION_SOL_MINT,
            "safety_evaluation_id": evaluation.id,
        }
        repo = LiveIntentRepository(session)
        intent = await repo.create_intent(**values)
        if intent:
            intent.state = ExecutionState.CREATED
            await session.commit()
            print(f"Canary Intent Created! ID: {intent.id}")
            print(f"Side: {intent.side}, Mint: {intent.mint_address}, Amount USD: {intent.requested_usd}")
            print("To test: Validate this intent via the real wallet pipeline.")
        else:
            print("Failed to create intent.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--side", type=str, choices=["BUY", "SELL"], default="BUY")
    parser.add_argument("--mint", type=str, required=True, help="Mint address for the token.")
    parser.add_argument("--amount-usd", type=Decimal, default=Decimal("0.01"), help="Amount in USD (default 0.01)")
    args = parser.parse_args()
    asyncio.run(run(side=args.side, mint=args.mint, amount_usd=args.amount_usd))


if __name__ == "__main__":
    main()
