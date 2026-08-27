import asyncio
import uuid
import sys
from decimal import Decimal
from sqlalchemy import select
from app.db.session import SessionFactory
from app.real_wallet.live_readiness import ExecutionState, LiveSubmissionGuard
from app.real_wallet.swap_assembler import SwapOrderFactory
from app.real_wallet.live_repository import LiveIntentRepository
from app.models.real_wallet_execution import RealWalletLiveIntent
from app.real_wallet import live_facts
from app.services.rpc.standard import StandardSolanaRPC
from datetime import datetime, UTC

async def run(intent_id: str):
    async with SessionFactory() as session:
        intent = (
            await session.execute(
                select(RealWalletLiveIntent).where(RealWalletLiveIntent.id == intent_id)
            )
        ).scalar_one_or_none()
        if not intent:
            print("Intent not found!")
            return
        
        print(f"Drilling Intent {intent.id} - state: {intent.state}")
        
        # 1. Run Submission Guard
        print("1. Running LiveSubmissionGuard checks...")
        try:
            now = datetime.now(UTC)
            
            # Dummy signer that just returns the public key
            class DummySigner:
                async def public_key(self):
                    return intent.wallet_public_key

            facts = await live_facts.build(
                session,
                intent=intent,
                now=now,
                signer=DummySigner(),
                wallet_balance_sol=Decimal("0.01") # Mock balance below limit
            )
            decision = LiveSubmissionGuard().evaluate(facts.facts)
            if not decision.allowed:
                print(f"   ⚠️ Safety Guard Failed (expected in dry run): {decision.reasons}")
                print("   ⚠️ Proceeding to assembly anyway for drill purposes.")
            else:
                print("   ✅ Safety Guard Passed!")
            intent.state = ExecutionState.SAFETY_APPROVED
        except Exception as e:
            print(f"   ❌ Safety Guard Exception: {e}")
            return
            
        # 2. Assemble Swap
        print("2. Assembling Swap via Jupiter...")
        try:
            async with StandardSolanaRPC() as rpc:
                factory = SwapOrderFactory(session, rpc)
                prepared = await factory.prepare(intent)
            
            print("   ✅ Swap Assembled Successfully!")
            print(f"   Request ID: {prepared.request_id}")
            print(f"   Unsigned Tx (len): {len(prepared.unsigned_transaction)}")
            intent.state = ExecutionState.ORDER_CREATED
        except Exception as e:
            print(f"   ❌ Swap Assembly Failed: {e}")
            return
            
        # 3. We STOP here without submitting or signing!
        print("🚨 DRILL COMPLETE. We STOP here. No signature, no submission.")
        # Rollback intent state changes to leave it pure for another drill
        await session.rollback()
        
if __name__ == "__main__":
    intent_id = sys.argv[1]
    asyncio.run(run(intent_id))
