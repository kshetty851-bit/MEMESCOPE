import os
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text
import json

def main():
    out_dir = "/app/research_exports/checkpoint_5"
    trades_df = pd.read_pickle(os.path.join(out_dir, "research_dataset_trades.pkl"))
    
    # Sort chronologically
    trades_df = trades_df.sort_values("entry_at").reset_index(drop=True)
    
    # --- PHASE 2: Baseline Metrics & Collapse Recalibration ---
    print("=== PHASE 2: BASELINE & COLLAPSE ===")
    
    baseline_win_rate = (trades_df['net_return_pct'] > 0).mean()
    baseline_expectancy = trades_df['net_return_pct'].mean()
    baseline_pf = trades_df[trades_df['net_return_pct'] > 0]['net_return_pct'].sum() / \
                  abs(trades_df[trades_df['net_return_pct'] < 0]['net_return_pct'].sum()) if len(trades_df[trades_df['net_return_pct'] < 0]) > 0 else np.inf
    
    print(f"Baseline Win Rate: {baseline_win_rate:.2%}")
    print(f"Baseline Expectancy: {baseline_expectancy:.2f}%")
    print(f"Baseline Profit Factor: {baseline_pf:.2f}")
    
    collapse_count = trades_df['is_collapse'].sum()
    print(f"Collapse Count (MAE <= -80%): {collapse_count} / {len(trades_df)} ({collapse_count/len(trades_df):.2%})")
    
    # --- PHASE 3: Survival Signal Revalidation ---
    print("\n=== PHASE 3: SURVIVAL SIGNAL ===")
    split_idx = int(len(trades_df) * 0.7)
    train_df = trades_df.iloc[:split_idx]
    test_df = trades_df.iloc[split_idx:]
    
    print(f"Train size: {len(train_df)}, Test size: {len(test_df)}")
    
    thresholds = [0.0, 0.50, 0.75, 1.00, 1.25, 1.50, 2.00]
    
    results = []
    for th in thresholds:
        # Filter train
        mask_train = train_df['volume_24h_to_liquidity'] >= th
        filtered_train = train_df[mask_train]
        collapse_train = filtered_train['is_collapse'].mean() if len(filtered_train) > 0 else 0
        exp_train = filtered_train['net_return_pct'].mean() if len(filtered_train) > 0 else 0
        
        # Filter test
        mask_test = test_df['volume_24h_to_liquidity'] >= th
        filtered_test = test_df[mask_test]
        collapse_test = filtered_test['is_collapse'].mean() if len(filtered_test) > 0 else 0
        exp_test = filtered_test['net_return_pct'].mean() if len(filtered_test) > 0 else 0
        
        results.append({
            "Threshold": th,
            "Train_N": len(filtered_train),
            "Train_Collapse_Rate": collapse_train,
            "Train_Expectancy": exp_train,
            "Test_N": len(filtered_test),
            "Test_Collapse_Rate": collapse_test,
            "Test_Expectancy": exp_test
        })
        
    survival_df = pd.DataFrame(results)
    print(survival_df.to_string(index=False))
    survival_df.to_csv(os.path.join(out_dir, "survival_validation.csv"), index=False)
    
    # Best threshold on train: highest expectancy with sufficient N
    best_th = survival_df.sort_values("Train_Expectancy", ascending=False).iloc[0]['Threshold']
    print(f"Selected Survival Threshold (from Train): {best_th}")
    
    # --- PHASE 4: Radar Inversion Analysis ---
    print("\n=== PHASE 4: RADAR INVERSION ===")
    
    db_url = os.environ.get('DATABASE_URL', 'postgresql://memescope:memescope@postgres:5432/memescope')
    engine = create_engine(db_url)
    
    radar_data = []
    with engine.connect() as conn:
        for idx, row in trades_df.iterrows():
            mint = row['mint_address']
            
            # Get latest radar info before opened_at
            q = text("""
                SELECT first_opportunity_score, first_confidence, first_market_cap, first_liquidity, first_volume_24h, detection_reason
                FROM radar_tokens
                WHERE mint_address = :mint
            """)
            res = conn.execute(q, {"mint": mint}).fetchone()
            if res:
                radar_data.append({
                    "position_id": row['position_id'],
                    "radar_score": float(res[0]) if res[0] else None,
                    "radar_confidence": float(res[1]) if res[1] else None,
                    "first_market_cap": float(res[2]) if res[2] else None,
                    "first_liquidity": float(res[3]) if res[3] else None,
                    "first_volume_24h": float(res[4]) if res[4] else None,
                    "detection_reason": res[5]
                })
                
    radar_df = pd.DataFrame(radar_data)
    radar_merged = trades_df.merge(radar_df, on="position_id", how="left")
    
    # Compare collapsed vs non-collapsed
    collapsed = radar_merged[radar_merged['is_collapse'] == True]
    non_collapsed = radar_merged[radar_merged['is_collapse'] == False]
    
    comparison = []
    metrics = ["radar_score", "radar_confidence", "first_market_cap", "first_liquidity", "first_volume_24h"]
    for m in metrics:
        comparison.append({
            "Metric": m,
            "Collapsed_Mean": collapsed[m].mean(),
            "NonCollapsed_Mean": non_collapsed[m].mean(),
            "Collapsed_Median": collapsed[m].median(),
            "NonCollapsed_Median": non_collapsed[m].median()
        })
        
    comp_df = pd.DataFrame(comparison)
    print(comp_df.to_string(index=False))
    comp_df.to_csv(os.path.join(out_dir, "radar_collapse_attribution.csv"), index=False)

if __name__ == "__main__":
    main()
