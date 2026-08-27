import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text
from app.core.config import settings

async def main():
    engine = create_async_engine(settings.DATABASE_URI)
    async with AsyncSession(engine) as session:
        # Get all positions from V1 (we can look at all positions in paper_positions)
        result = await session.execute(text("""
            SELECT 
                p.id, p.mint_address, p.opened_at, p.closed_at, p.status, 
                p.entry_price, p.exit_price, p.peak_price, p.entry_liquidity_usd
            FROM paper_positions p
            WHERE p.opened_at IS NOT NULL
        """))
        positions = result.all()
        
        v1_pnl = []
        v2_pnl = []
        
        print(f"Total positions to backtest: {len(positions)}")
        
        # We need market data to simulate 24h close, let's fetch it for tokens we need
        # It's easier to just do a point query for each position that exceeded 24h
        
        for p in positions:
            # V1 logic:
            if p.status == 'closed' and p.entry_price and p.exit_price:
                v1_pnl.append((float(p.exit_price) / float(p.entry_price)) - 1)
            
            # V2 rules:
            # 1. Liquidity filter
            if not p.entry_liquidity_usd or float(p.entry_liquidity_usd) < 10000:
                continue
                
            # 2. Time stop 24h
            if p.status == 'closed' and p.closed_at:
                hold_sec = (p.closed_at - p.opened_at).total_seconds()
                if hold_sec <= 24 * 3600:
                    # closed naturally within 24h
                    if p.entry_price and p.exit_price:
                        v2_pnl.append((float(p.exit_price) / float(p.entry_price)) - 1)
                else:
                    # hit time stop. find price at 24h
                    res = await session.execute(text("""
                        SELECT price_usd 
                        FROM token_market_snapshots 
                        WHERE mint_address = :m 
                        AND captured_at >= :t
                        ORDER BY captured_at ASC
                        LIMIT 1
                    """), {"m": p.mint_address, "t": p.opened_at + __import__('datetime').timedelta(hours=24)})
                    price_row = res.first()
                    if price_row and price_row[0] and p.entry_price:
                        v2_pnl.append((float(price_row[0]) / float(p.entry_price)) - 1)
            elif p.status == 'open':
                hold_sec = (__import__('datetime').datetime.now(__import__('datetime').timezone.utc) - p.opened_at).total_seconds()
                if hold_sec > 24 * 3600:
                    # hit time stop
                    res = await session.execute(text("""
                        SELECT price_usd 
                        FROM token_market_snapshots 
                        WHERE mint_address = :m 
                        AND captured_at >= :t
                        ORDER BY captured_at ASC
                        LIMIT 1
                    """), {"m": p.mint_address, "t": p.opened_at + __import__('datetime').timedelta(hours=24)})
                    price_row = res.first()
                    if price_row and price_row[0] and p.entry_price:
                        v2_pnl.append((float(price_row[0]) / float(p.entry_price)) - 1)

        print(f"V1 total trades (closed): {len(v1_pnl)}")
        if v1_pnl:
            print(f"V1 average PnL: {sum(v1_pnl)/len(v1_pnl)*100:.2f}%")
            print(f"V1 total PnL: {sum(v1_pnl)*100:.2f}%")
            
        print(f"V2 total trades: {len(v2_pnl)}")
        if v2_pnl:
            print(f"V2 average PnL: {sum(v2_pnl)/len(v2_pnl)*100:.2f}%")
            print(f"V2 total PnL: {sum(v2_pnl)*100:.2f}%")

asyncio.run(main())
