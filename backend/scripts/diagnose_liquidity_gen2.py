import asyncio
import httpx
from datetime import datetime, timedelta, UTC
from sqlalchemy import select, func, and_, or_
from app.db.session import SessionFactory
from app.models.paper import PaperPosition, PaperWallet
from app.models.token import DiscoveredToken
from app.models.market import TokenMarketSnapshot, TokenEnrichmentState
from app.models.radar import RadarToken
from app.core.config import settings

async def fetch_dexscreener(mint: str):
    url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                pairs = data.get("pairs", [])
                if pairs:
                    pairs.sort(key=lambda p: p.get("liquidity", {}).get("usd", 0), reverse=True)
                    best = pairs[0]
                    return {
                        "exists": "YES",
                        "status": "active" if best.get("liquidity", {}).get("usd", 0) > 0 else "inactive"
                    }
    except Exception as e:
        pass
    return {"exists": "NO"}

async def main():
    async with SessionFactory() as session:
        print("Finding OPEN positions in Gen 2 ordered by last_evaluated_at (oldest first) to find stuck ones...")
        
        # Get Gen 2 wallet ID
        gen2_wallet = await session.scalar(
            select(PaperWallet).where(and_(PaperWallet.generation == 2, PaperWallet.strategy_id == "trailing_stop_25_v1"))
        )
        if not gen2_wallet:
            print("Gen 2 wallet not found!")
            return
            
        print(f"Gen 2 Wallet ID: {gen2_wallet.id}")
        
        stmt = select(PaperPosition, DiscoveredToken).join(
            DiscoveredToken, PaperPosition.mint_address == DiscoveredToken.mint_address
        ).where(
            and_(PaperPosition.status == "open", PaperPosition.wallet_id == gen2_wallet.id)
        ).order_by(PaperPosition.last_evaluated_at.asc()).limit(5)
        
        result = await session.execute(stmt)
        waiting_positions = result.all()
                    
        for i, (pos, token) in enumerate(waiting_positions[:2], 1):
            print(f"WAITING FOR LIQUIDITY POSITION #{i}")
            print(f"Mint: {pos.mint_address}")
            print(f"Generation: 2")
            print(f"Symbol: {token.symbol}")
            print(f"Opened At: {pos.opened_at}")
            print(f"Entry Price: {pos.entry_price}")
            print(f"Last Evaluated At: {pos.last_evaluated_at}")
            print(f"Last Market Check At: {pos.last_market_check_at}")
            print(f"Position Status: {pos.status}")
            
            enrich_state = await session.scalar(select(TokenEnrichmentState).where(TokenEnrichmentState.mint_address == pos.mint_address))
            if enrich_state:
                print(f"TokenEnrichmentState: status={enrich_state.status}, priority={enrich_state.priority}, tier={enrich_state.tier}, last_success={enrich_state.last_success_at}")
            else:
                print("TokenEnrichmentState: NO")
                
            snap = await session.scalar(
                select(TokenMarketSnapshot)
                .where(TokenMarketSnapshot.mint_address == pos.mint_address)
                .order_by(TokenMarketSnapshot.captured_at.desc())
                .limit(1)
            )
            if snap:
                print(f"Latest Snapshot At: {snap.captured_at} (Status: {snap.trading_status})")
            else:
                print("Latest Snapshot: None")
                
            dex = await fetch_dexscreener(pos.mint_address)
            print(f"DexScreener market: {dex}")
            print("---")
            
        # Count current Gen 2 open positions
        count = await session.scalar(select(func.count(PaperPosition.id)).where(
            and_(PaperPosition.status == "open", PaperPosition.wallet_id == gen2_wallet.id)
        ))
        print(f"\nTOTAL OPEN GEN 2 POSITIONS: {count}")

if __name__ == "__main__":
    asyncio.run(main())
