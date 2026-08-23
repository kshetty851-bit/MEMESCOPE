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
        print("==================================================")
        print("A - TRACE THE TWO 'WAITING FOR LIQUIDITY' POSITIONS")
        print("==================================================")
        
        print("Finding OPEN positions ordered by last_evaluated_at (oldest first) to find stuck ones...")
        stmt = select(PaperPosition, DiscoveredToken).join(
            DiscoveredToken, PaperPosition.mint_address == DiscoveredToken.mint_address
        ).where(PaperPosition.status == "open").order_by(PaperPosition.last_evaluated_at.asc()).limit(5)
        result = await session.execute(stmt)
        waiting_positions = result.all()
                    
        for i, (pos, token) in enumerate(waiting_positions[:2], 1):
            print(f"WAITING FOR LIQUIDITY POSITION #{i}")
            print(f"Mint: {pos.mint_address}")
            wallet = await session.scalar(select(PaperWallet).where(PaperWallet.id == pos.wallet_id))
            gen = wallet.generation if wallet else "Unknown"
            print(f"Generation: {gen}")
            
            print(f"Symbol: {token.symbol}")
            print(f"Opened At: {pos.opened_at}")
            print(f"Entry Price: {pos.entry_price}")
            print(f"Last Evaluated At: {pos.last_evaluated_at}")
            print(f"Last Market Check At: {pos.last_market_check_at}")
            print(f"Position Status: {pos.status}")
            
            enrich_state = await session.scalar(select(TokenEnrichmentState).where(TokenEnrichmentState.mint_address == pos.mint_address))
            if enrich_state:
                print(f"TokenEnrichmentState:")
                print(f"  status: {enrich_state.status}")
                print(f"  priority: {enrich_state.priority}")
                print(f"  tier: {enrich_state.tier}")
                print(f"  last_attempt_at: {enrich_state.last_attempt_at}")
                print(f"  last_success_at: {enrich_state.last_success_at}")
                print(f"  next_refresh_at: {enrich_state.next_refresh_at}")
                print(f"  consecutive_failures: {enrich_state.consecutive_failures}")
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
            
            classification = "UNKNOWN"
            if dex["exists"] == "NO":
                classification = "A. REAL NO-LIQUIDITY TOKEN"
            elif enrich_state:
                if enrich_state.status == "dead":
                    classification = "C. PARSING FAILURE or B. ENRICHMENT FAILURE (Dead)"
                elif enrich_state.priority != 1:
                    classification = "D. PRIORITY/SCHEDULING FAILURE (Open position not in priority)"
                elif enrich_state.last_success_at and (datetime.now(UTC) - enrich_state.last_success_at.replace(tzinfo=UTC)).total_seconds() > 300:
                    classification = "B. ENRICHMENT FAILURE (Market exists but MEMESCOPE stopped refreshing)"
                elif pos.last_evaluated_at and (datetime.now(UTC) - pos.last_evaluated_at.replace(tzinfo=UTC)).total_seconds() < 300:
                    classification = "E. UI/API FAILURE (Backend fresh but wallet says waiting)"
            print(f"Classification: {classification}")
            print("---")
            
        print("\n==================================================")
        print("C - AUDIT TRACK RECORD FRESHNESS")
        print("==================================================")
        now = datetime.now(UTC)
        
        # Track Record tokens are all Radar tokens
        stmt = select(RadarToken, TokenEnrichmentState).join(
            TokenEnrichmentState, RadarToken.mint_address == TokenEnrichmentState.mint_address
        )
        result = await session.execute(stmt)
        tr_tokens = result.all()
        
        print(f"Total Track Record (Radar) Tokens: {len(tr_tokens)}")
        
        bins = {'<1m': 0, '1-5m': 0, '5-15m': 0, '15-60m': 0, '1-6h': 0, '6-24h': 0, '>24h': 0}
        live_gt_24h = []
        
        for radar, enrich in tr_tokens:
            if not enrich.last_success_at:
                age_sec = (now - radar.first_detected_at.replace(tzinfo=UTC)).total_seconds()
            else:
                age_sec = (now - enrich.last_success_at.replace(tzinfo=UTC)).total_seconds()
                
            if age_sec < 60: bins['<1m'] += 1
            elif age_sec < 300: bins['1-5m'] += 1
            elif age_sec < 900: bins['5-15m'] += 1
            elif age_sec < 3600: bins['15-60m'] += 1
            elif age_sec < 21600: bins['1-6h'] += 1
            elif age_sec < 86400: bins['6-24h'] += 1
            else: 
                bins['>24h'] += 1
                if enrich.status != "dead":
                    live_gt_24h.append(radar.mint_address)
                    
        for k, v in bins.items():
            print(f"{k}: {v}")
            
        print(f"Stale >24h (not dead in EnrichmentState): {len(live_gt_24h)}")
        stale_live_markets = 0
        for mint in live_gt_24h[:5]:
            dex = await fetch_dexscreener(mint)
            print(f"Sample >24h stale {mint} live market: {dex}")
            if dex["exists"] == "YES":
                stale_live_markets += 1
                
        print(f"Stale >24h WITH LIVE MARKET (out of first 5 sampled): {stale_live_markets}")
        
        print("\n==================================================")
        print("E - CHECK THE PREVIOUS FIX (Priority Lane)")
        print("==================================================")
        
        print(f"FEATURE_PRIORITY_ENRICHMENT_ENABLED = {settings.FEATURE_PRIORITY_ENRICHMENT_ENABLED}")
        print(f"ENRICHMENT_PRIORITY_MAX_TOKENS = {settings.ENRICHMENT_PRIORITY_MAX_TOKENS}")
        
        open_pos_count = await session.scalar(select(func.count(PaperPosition.id)).where(PaperPosition.status == "open"))
        open_pos_mints_result = await session.execute(select(PaperPosition.mint_address).where(PaperPosition.status == "open").distinct())
        open_pos_mints = [m for (m,) in open_pos_mints_result.all()]
        
        print(f"Open positions: {open_pos_count}")
        
        lane = await session.execute(select(TokenEnrichmentState).where(TokenEnrichmentState.priority == 1))
        lane_tokens = lane.scalars().all()
        lane_mints = {rt.mint_address for rt in lane_tokens}
        missing_mints = [m for m in open_pos_mints if m not in lane_mints]
        
        print(f"Lane capacity used: {len(lane_tokens)}")
        print(f"Open positions covered: {len(open_pos_mints) - len(missing_mints)}")
        if open_pos_mints:
            print(f"Coverage %: {((len(open_pos_mints) - len(missing_mints)) / len(open_pos_mints)) * 100}%")
        print(f"Missing mints: {len(missing_mints)}")

if __name__ == "__main__":
    asyncio.run(main())
