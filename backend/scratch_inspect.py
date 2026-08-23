import asyncio
from sqlalchemy import select, text
from app.db.session import SessionFactory
from app.db.session import SessionFactory
from app.models.paper import PaperPosition
from app.models.market import TokenEnrichmentState, TokenMarketSnapshot
import json

async def main():
    async with SessionFactory() as session:
        # Find 5 open positions that have the oldest last_evaluated_at
        stmt = (
            select(PaperPosition)
            .where(PaperPosition.status == "open")
            .order_by(PaperPosition.last_evaluated_at.asc())
            .limit(5)
        )
        positions = (await session.execute(stmt)).scalars().all()
        
        print(f"Found {len(positions)} open positions")
        
        for p in positions:
            print(f"\n=================================")
            print(f"Mint: {p.mint_address}")
            print(f"last_evaluated_at: {p.last_evaluated_at}")
            
            # Enrichment State
            state = (await session.execute(
                select(TokenEnrichmentState).where(TokenEnrichmentState.mint_address == p.mint_address)
            )).scalars().first()
            
            if state:
                print(f"\nEnrichment State:")
                print(f"  status: {state.status}")
                print(f"  priority: {state.priority}")
                print(f"  next_refresh_at: {state.next_refresh_at}")
                print(f"  last_attempt_at: {state.last_attempt_at}")
                print(f"  last_success_at: {state.last_success_at}")
                print(f"  consecutive_empty: {state.consecutive_empty}")
                print(f"  consecutive_failures: {state.consecutive_failures}")
                print(f"  last_error: {state.last_error}")
            else:
                print(f"  No enrichment state found!")
                
            # Latest Snapshot
            snap = (await session.execute(
                select(TokenMarketSnapshot)
                .where(TokenMarketSnapshot.mint_address == p.mint_address)
                .order_by(TokenMarketSnapshot.captured_at.desc())
                .limit(1)
            )).scalars().first()
            
            if snap:
                print(f"\nLatest Snapshot:")
                print(f"  captured_at: {snap.captured_at}")
                print(f"  trading_status: {snap.trading_status}")
                print(f"  price_usd: {snap.price_usd}")
            else:
                print(f"  No snapshots found!")

if __name__ == "__main__":
    asyncio.run(main())
