import asyncio
from datetime import timedelta, datetime
from sqlalchemy import text
from app.db.session import SessionFactory
import statistics

def to_dt(s):
    if isinstance(s, datetime): return s
    return datetime.fromisoformat(str(s).replace('Z', '+00:00'))

async def main():
    async with SessionFactory() as session:
        res = await session.execute(text("""
            SELECT 
                p.mint_address,
                p.opened_at,
                p.closed_at,
                p.size_usd,
                p.entry_price,
                p.exit_price,
                p.quantity,
                p.entry_liquidity_usd,
                (p.quantity * p.exit_price - p.size_usd) as pnl,
                (p.exit_price / p.entry_price - 1) as return_pct
            FROM paper_positions p
            JOIN paper_wallets w ON p.wallet_id = w.id
            WHERE p.status = 'closed' AND w.strategy_id = 'trailing_stop_25_v1'
        """))
        v1_rows = [dict(r) for r in res.mappings().all()]
        
        if not v1_rows:
            print("No V1 rows found.")
            return

        for r in v1_rows:
            r['opened_at'] = to_dt(r['opened_at'])
            r['closed_at'] = to_dt(r['closed_at'])
            r['hold_time'] = r['closed_at'] - r['opened_at']
            r['hold_hours'] = r['hold_time'].total_seconds() / 3600.0
            r['pnl'] = float(r['pnl'])
            r['return_pct'] = float(r['return_pct'])
        
        v2_rows = []
        for r in v1_rows:
            if r['entry_liquidity_usd'] is None or float(r['entry_liquidity_usd']) < 10000:
                continue 
            
            opened = r['opened_at']
            closed = r['closed_at']
            
            if (closed - opened).total_seconds() > 24 * 3600:
                time_stop = opened + timedelta(hours=24)
                snap_res = await session.execute(text("""
                    SELECT price_usd FROM token_market_snapshots 
                    WHERE mint_address = :mint AND captured_at <= :ts 
                    ORDER BY captured_at DESC LIMIT 1
                """), {"mint": r['mint_address'], "ts": time_stop})
                snap = snap_res.mappings().first()
                if snap:
                    exit_price = float(snap['price_usd'])
                    hold_time = time_stop - opened
                else:
                    exit_price = float(r['exit_price'])
                    hold_time = closed - opened
                
                v2_rows.append({
                    'mint_address': r['mint_address'],
                    'return_pct': float(exit_price / float(r['entry_price']) - 1),
                    'pnl': float(float(r['quantity']) * exit_price - float(r['size_usd'])),
                    'hold_hours': hold_time.total_seconds() / 3600.0
                })
            else:
                v2_rows.append({
                    'mint_address': r['mint_address'],
                    'return_pct': r['return_pct'],
                    'pnl': r['pnl'],
                    'hold_hours': r['hold_hours']
                })

        def calc_metrics(d):
            if not d: return {}
            wins = [x for x in d if x['pnl'] > 0]
            losses = [x for x in d if x['pnl'] <= 0]
            gross_profit = sum(x['pnl'] for x in wins)
            gross_loss = abs(sum(x['pnl'] for x in losses))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
            
            holds = sorted([x['hold_hours'] for x in d])
            median_hold = statistics.median(holds) if holds else 0
            p90_idx = int(len(holds) * 0.9)
            p90_hold = holds[p90_idx] if holds else 0
            
            total_pnl = sum(x['pnl'] for x in d)
            total_return_pct = sum(x['return_pct'] for x in d) * 100
            total_hours = sum(x['hold_hours'] for x in d)
            
            return {
                'total_trades': len(d),
                'total_pnl': total_pnl,
                'total_return_pct': total_return_pct,
                'win_rate': len(wins) / len(d) * 100,
                'profit_factor': profit_factor,
                'expectancy': total_pnl / len(d),
                'median_hold': median_hold,
                'p90_hold': p90_hold,
                'capital_hours': total_hours,
                'return_per_cap_hour': total_pnl / total_hours if total_hours > 0 else 0
            }
            
        m1 = calc_metrics(v1_rows)
        m2 = calc_metrics(v2_rows)
        
        print("V1 Metrics:")
        for k,v in m1.items(): print(f"  {k}: {v}")
        print("\nV2 Metrics:")
        for k,v in m2.items(): print(f"  {k}: {v}")

if __name__ == "__main__":
    asyncio.run(main())
