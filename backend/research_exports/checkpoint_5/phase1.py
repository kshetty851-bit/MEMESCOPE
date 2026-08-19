import os
import pandas as pd
from sqlalchemy import create_engine, text

def main():
    db_url = os.environ.get('DATABASE_URL', 'postgresql://memescope:memescope@postgres:5432/memescope')
    engine = create_engine(db_url)
    
    print("Extracting trades and positions...")
    # Get all trades
    trades_query = """
        SELECT 
            pta.id as audit_id,
            pta.position_id,
            pta.mint_address,
            pta.entry_at,
            pta.exit_at,
            pta.entry_price,
            pta.exit_price,
            pta.net_return_pct,
            pta.entry_liquidity_usd,
            pta.exit_liquidity_usd,
            pta.entry_market_cap,
            pp.opened_at,
            pp.entry_rank
        FROM paper_trade_audit pta
        JOIN paper_positions pp ON pta.position_id = pp.id
    """
    trades_df = pd.read_sql(trades_query, engine)
    print(f"Loaded {len(trades_df)} trades.")
    
    # We need to find the latest volume_24h prior to opened_at
    print("Reconstructing entry_volume_24h from snapshots...")
    volume_records = []
    
    # We also want the full continuous path
    paths = []
    
    with engine.connect() as conn:
        for idx, row in trades_df.iterrows():
            mint = row['mint_address']
            opened_at = row['opened_at']
            entry_at = row['entry_at']
            exit_at = row['exit_at']
            
            # 1. Fetch volume_24h right before entry
            vol_query = text("""
                SELECT volume_24h, liquidity_usd 
                FROM token_market_snapshots
                WHERE mint_address = :mint AND captured_at <= :opened_at
                ORDER BY captured_at DESC
                LIMIT 1
            """)
            vol_res = conn.execute(vol_query, {"mint": mint, "opened_at": opened_at}).fetchone()
            
            vol_24h = float(vol_res[0]) if vol_res and vol_res[0] is not None else None
            liq_usd = float(vol_res[1]) if vol_res and vol_res[1] is not None else None
            
            volume_records.append({
                "position_id": row['position_id'],
                "entry_volume_24h": vol_24h,
                "snapshot_liquidity_usd": liq_usd,
            })
            
            # 2. Fetch full path for MFE/MAE
            path_query = text("""
                SELECT captured_at, price_usd, liquidity_usd, market_cap
                FROM token_market_snapshots
                WHERE mint_address = :mint AND captured_at >= :entry_at AND captured_at <= :exit_at
                ORDER BY captured_at ASC
            """)
            path_res = conn.execute(path_query, {"mint": mint, "entry_at": entry_at, "exit_at": exit_at}).fetchall()
            
            for p in path_res:
                paths.append({
                    "position_id": row['position_id'],
                    "mint_address": mint,
                    "captured_at": p[0],
                    "price_usd": float(p[1]) if p[1] else None,
                    "liquidity_usd": float(p[2]) if p[2] else None,
                    "market_cap": float(p[3]) if p[3] else None
                })
                
    vol_df = pd.DataFrame(volume_records)
    trades_df = trades_df.merge(vol_df, on="position_id", how="left")
    
    paths_df = pd.DataFrame(paths)
    
    # Calculate MFE and MAE for each trade based on paths
    print("Calculating MFE/MAE...")
    
    results = []
    for pos_id, grp in paths_df.groupby("position_id"):
        trade = trades_df[trades_df['position_id'] == pos_id].iloc[0]
        entry_price = float(trade['entry_price'])
        
        grp = grp.dropna(subset=['price_usd']).sort_values('captured_at')
        if len(grp) == 0:
            continue
            
        grp['return_pct'] = (grp['price_usd'] - entry_price) / entry_price * 100
        
        mfe = grp['return_pct'].max()
        mae = grp['return_pct'].min()
        
        mfe_time = grp.loc[grp['return_pct'].idxmax(), 'captured_at']
        mae_time = grp.loc[grp['return_pct'].idxmin(), 'captured_at']
        
        # Determine if collapse (-80% or worse without recovery)
        # We can just define collapse as MAE <= -80
        collapse = bool(mae <= -80)
        
        results.append({
            "position_id": pos_id,
            "mfe_pct": mfe,
            "mae_pct": mae,
            "mfe_time": mfe_time,
            "mae_time": mae_time,
            "is_collapse": collapse,
            "path_length": len(grp)
        })
        
    res_df = pd.DataFrame(results)
    trades_df = trades_df.merge(res_df, on="position_id", how="left")
    
    # Calculate volume-to-liquidity ratio
    trades_df['volume_24h_to_liquidity'] = trades_df['entry_volume_24h'] / trades_df['snapshot_liquidity_usd']
    
    out_dir = "/app/research_exports/checkpoint_5"
    os.makedirs(out_dir, exist_ok=True)
    
    trades_df.to_pickle(os.path.join(out_dir, "research_dataset_trades.pkl"))
    paths_df.to_pickle(os.path.join(out_dir, "research_dataset_paths.pkl"))
    trades_df.to_csv(os.path.join(out_dir, "research_dataset_trades.csv"), index=False)
    
    print(f"Exported trades dataset with {len(trades_df)} rows and paths dataset with {len(paths_df)} rows.")

if __name__ == "__main__":
    main()
