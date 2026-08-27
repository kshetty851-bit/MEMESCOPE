import asyncio
from datetime import datetime, UTC
from sqlalchemy import select
from app.db.session import SessionFactory
from app.models.paper import PaperPosition, PositionStatus
from app.models.market import TokenEnrichmentState, MarketSnapshot

async def main():
    async with SessionFactory() as session:
        # Open Paper Positions
        stmt = select(PaperPosition).where(PaperPosition.status == PositionStatus.OPEN.value)
        open_positions = (await session.scalars(stmt)).all()
        
        now = datetime.now(UTC)
        print("=== OPEN PAPER WALLET POSITIONS ===")
        buckets = {"< 1m": 0, "1-5m": 0, "5-15m": 0, "15-60m": 0, "> 1h": 0, "no market": 0}
        
        for pos in open_positions:
            state = await session.scalar(select(TokenEnrichmentState).where(TokenEnrichmentState.mint_address == pos.mint_address))
            latest_snap = await session.scalar(select(MarketSnapshot).where(MarketSnapshot.mint_address == pos.mint_address).order_by(MarketSnapshot.captured_at.desc()).limit(1))
            
            if not latest_snap:
                buckets["no market"] += 1
                continue
            
            age = (now - latest_snap.captured_at).total_seconds()
            if age < 60: buckets["< 1m"] += 1
            elif age < 300: buckets["1-5m"] += 1
            elif age < 900: buckets["5-15m"] += 1
            elif age < 3600: buckets["15-60m"] += 1
            else: buckets["> 1h"] += 1
            
            print(f"{pos.mint_address}: age={age:.1f}s, last_snap={latest_snap.captured_at}, last_eval={pos.last_evaluated_at}, priority={state.priority if state else 'None'}")
            
        print("\n=== BUCKETS ===")
        for k, v in buckets.items():
            print(f"{k}: {v}")

if __name__ == "__main__":
    asyncio.run(main())
