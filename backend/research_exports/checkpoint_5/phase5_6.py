import os
import pandas as pd
import numpy as np

def main():
    out_dir = "/app/research_exports/checkpoint_5"
    paths_df = pd.read_pickle(os.path.join(out_dir, "research_dataset_paths.pkl"))
    trades_df = pd.read_pickle(os.path.join(out_dir, "research_dataset_trades.pkl"))
    
    # Sort chronologically by entry_at
    trades_df = trades_df.sort_values("entry_at").reset_index(drop=True)
    split_idx = int(len(trades_df) * 0.7)
    train_ids = set(trades_df.iloc[:split_idx]['position_id'])
    test_ids = set(trades_df.iloc[split_idx:]['position_id'])
    
    print("=== PHASE 5: TIME-TO-MFE ===")
    
    mfe_data = []
    
    for pos_id, grp in paths_df.groupby("position_id"):
        trade = trades_df[trades_df['position_id'] == pos_id].iloc[0]
        entry_price = float(trade['entry_price'])
        entry_at = trade['entry_at']
        
        grp = grp.dropna(subset=['price_usd']).sort_values('captured_at')
        if len(grp) == 0:
            continue
            
        grp['return_pct'] = (grp['price_usd'] - entry_price) / entry_price * 100
        grp['elapsed_min'] = (grp['captured_at'] - entry_at).dt.total_seconds() / 60
        
        mfe_row = grp.loc[grp['return_pct'].idxmax()]
        
        mfe_data.append({
            "position_id": pos_id,
            "mfe_pct": mfe_row['return_pct'],
            "mfe_elapsed_min": mfe_row['elapsed_min'],
            "is_train": pos_id in train_ids
        })
        
    mfe_df = pd.DataFrame(mfe_data)
    
    train_mfe = mfe_df[mfe_df['is_train']]
    print("Train Set MFE Time Distribution (minutes):")
    print(train_mfe['mfe_elapsed_min'].describe())
    
    # Find MFE decay (how many trades reach MFE within 15 mins vs later)
    under_15 = len(train_mfe[train_mfe['mfe_elapsed_min'] <= 15])
    under_60 = len(train_mfe[train_mfe['mfe_elapsed_min'] <= 60])
    total = len(train_mfe)
    print(f"MFE achieved <= 15 mins: {under_15} / {total} ({under_15/total:.2%})")
    print(f"MFE achieved <= 60 mins: {under_60} / {total} ({under_60/total:.2%})")
    
    print("\n=== PHASE 6: EXIT STATE MACHINE SIMULATION ===")
    # Simulate a few different rule configurations on the train set
    # We will simulate standard:
    # Strategy 1: Hard Stop -25%
    # Strategy 2: Hard Stop -25%, Take Profit at +30%
    # Strategy 3: Hard Stop -25%, Trail Stop -15% from HWM
    
    sim_results = []
    
    for pos_id, grp in paths_df.groupby("position_id"):
        trade = trades_df[trades_df['position_id'] == pos_id].iloc[0]
        entry_price = float(trade['entry_price'])
        
        grp = grp.dropna(subset=['price_usd']).sort_values('captured_at')
        if len(grp) == 0:
            continue
            
        returns = (grp['price_usd'] - entry_price) / entry_price * 100
        
        # S1: HS -25%
        s1_return = returns.iloc[-1]
        for r in returns:
            if r <= -25:
                s1_return = -25
                break
                
        # S2: HS -25%, TP +30%
        s2_return = returns.iloc[-1]
        for r in returns:
            if r <= -25:
                s2_return = -25
                break
            if r >= 30:
                s2_return = 30
                break
                
        # S3: HS -25%, Trail Stop -15%
        s3_return = returns.iloc[-1]
        hwm = 0
        for r in returns:
            if r > hwm:
                hwm = r
            if r <= -25:
                s3_return = -25
                break
            # Trail stop triggers if current return drops 15% below HWM
            # (e.g. hwm is +20%, r falls to +5%)
            if hwm - r >= 15:
                s3_return = r
                break
                
        sim_results.append({
            "position_id": pos_id,
            "s1_return": s1_return,
            "s2_return": s2_return,
            "s3_return": s3_return,
            "baseline": returns.iloc[-1],
            "is_train": pos_id in train_ids
        })
        
    sim_df = pd.DataFrame(sim_results)
    
    train_sim = sim_df[sim_df['is_train'] == True]
    test_sim = sim_df[sim_df['is_train'] == False]
    
    print("Train Set Strategy Expectations (N={}):".format(len(train_sim)))
    print(f"Baseline (Hold to end):   {train_sim['baseline'].mean():.2f}%")
    print(f"S1 (HS -25):              {train_sim['s1_return'].mean():.2f}%")
    print(f"S2 (HS -25, TP +30):      {train_sim['s2_return'].mean():.2f}%")
    print(f"S3 (HS -25, Trail -15):   {train_sim['s3_return'].mean():.2f}%")
    
    print("\nTest Set Strategy Expectations (N={}):".format(len(test_sim)))
    print(f"Baseline (Hold to end):   {test_sim['baseline'].mean():.2f}%")
    print(f"S1 (HS -25):              {test_sim['s1_return'].mean():.2f}%")
    print(f"S2 (HS -25, TP +30):      {test_sim['s2_return'].mean():.2f}%")
    print(f"S3 (HS -25, Trail -15):   {test_sim['s3_return'].mean():.2f}%")
    
    # Phase 7: Combined Best Rules
    # Only enter if volume_24h_to_liquidity >= 1.25, and use S2
    # Apply on both Train and Test
    
    print("\n=== PHASE 7: CHRONOLOGICAL VALIDATION ===")
    trades_df['volume_24h_to_liquidity'] = trades_df['entry_volume_24h'] / trades_df['snapshot_liquidity_usd']
    
    combo_train = trades_df[(trades_df['position_id'].isin(train_ids)) & (trades_df['volume_24h_to_liquidity'] >= 1.25)]
    combo_test = trades_df[(~trades_df['position_id'].isin(train_ids)) & (trades_df['volume_24h_to_liquidity'] >= 1.25)]
    
    combo_train_sim = sim_df[sim_df['position_id'].isin(combo_train['position_id'])]
    combo_test_sim = sim_df[sim_df['position_id'].isin(combo_test['position_id'])]
    
    print("Train Set + Entry Filter (Vol/Liq >= 1.25) + S2 (N={}):".format(len(combo_train_sim)))
    print(f"Expectancy: {combo_train_sim['s2_return'].mean():.2f}%")
    
    print("Test Set + Entry Filter (Vol/Liq >= 1.25) + S2 (N={}):".format(len(combo_test_sim)))
    print(f"Expectancy: {combo_test_sim['s2_return'].mean():.2f}%")

if __name__ == "__main__":
    main()
