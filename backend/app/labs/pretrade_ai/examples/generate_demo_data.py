"""Generate deterministic illustrative data for software smoke tests only.
The values are synthetic fixtures and must not be quoted as strategy performance.
"""
from __future__ import annotations
import argparse, json, random
from datetime import datetime, timedelta, timezone
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--output",required=True); args=ap.parse_args()
    rng=random.Random(7); start=datetime(2026,1,1,tzinfo=timezone.utc); rows=[]
    for i in range(120):
        decision=start+timedelta(hours=6*i); exit_ts=decision+timedelta(minutes=5); label_ts=exit_ts+timedelta(minutes=1)
        liq=[56000,82000,125000,165000,230000][i%5]; creator_rug=1 if i in {17,59,101} else 0
        # Fixture label has mixed classes in every time block. It is not a market claim.
        pnl=[0.7,-0.8,0.25,-1.1,0.1][i%5] + rng.uniform(-0.5,0.5) - creator_rug*1.5
        values={"liquidity_usd":liq,"pool_lifetime_swaps":20+i%70,"graduation_age_seconds":40+i%70,"signal_age_seconds":5+i%25,"quote_age_seconds":1+i%4,"buy_price_impact_pct":0.1+(i%4)*.12,"immediate_round_trip_loss_pct":0.6+(i%4)*.2,"unique_buyers_30s":5+i%18,"buy_sell_notional_ratio_30s":0.8+(i%7)*.3,"top_buyer_cluster_share_pct":15+i%40,"top1_holder_share_pct":4+i%12,"top10_holder_share_pct":18+i%25,"reserve_decline_30s_pct":i%12,"creator_cluster_sale_supply_pct_30s":0.02*(i%8),"creator_prior_confirmed_rug_count_30d":creator_rug,"funder_prior_confirmed_rug_count_30d":0,"malicious_link_recency_days":5 if creator_rug else 90,"identity_confidence":0.9,"sell_route_available":True,"mint_authority_safe":True,"freeze_authority_safe":True}
        observed=(decision-timedelta(seconds=1)).isoformat()
        rows.append({"schema_version":"1.0","opportunity_id":f"demo-{i:03d}","mint":f"DEMO_MINT_{i:03d}","pool":f"DEMO_POOL_{i:03d}","decision_ts":decision.isoformat(),"strategy_version":"DEMO_ONLY","universe":"synthetic_software_fixture","baseline_eligible":True,"features":{k:{"value":v,"observed_at":observed,"source":"synthetic_demo_generator","quality":"observed"} for k,v in values.items()},"identity":{"creator_cluster_id":f"demo_creator_{i:03d}","funder_cluster_id":f"demo_funder_{i:03d}","linkage_observed_at":observed,"linkage_source":"synthetic_demo_generator"},"outcome":{"label_available_ts":label_ts.isoformat(),"exit_ts":exit_ts.isoformat(),"matched_size_entry_cost_usd":10,"matched_size_exit_proceeds_usd":round(max(0,10+pnl),6),"all_costs_included":True,"unresolved":False,"source":"synthetic_demo_generator"},"metadata":{"warning":"Synthetic fixture for execution-path testing only; not performance evidence."}})
    p=Path(args.output); p.parent.mkdir(parents=True,exist_ok=True); p.write_text("\n".join(json.dumps(x,separators=(',',':')) for x in rows)+"\n",encoding="utf-8")
    print(json.dumps({"rows":len(rows),"output":str(p),"warning":"synthetic software fixture only"},indent=2))
if __name__=="__main__": main()
