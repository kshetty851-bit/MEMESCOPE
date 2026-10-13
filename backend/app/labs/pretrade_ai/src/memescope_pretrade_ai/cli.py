from __future__ import annotations
import argparse, json
from pathlib import Path
from .adapters.mapping import load_mapping, map_record
from .backtest import run_selection_backtest
from .config import load_config
from .integration import write_safe_outbox
from .io import jsonl_records, read_opportunities, write_json
from .model import load_bundle, save_bundle, train_model
from .scoring import score_many

def parser():
    p=argparse.ArgumentParser(prog="memescope-score", description="Read-only MEMESCOPE pre-trade scoring research package")
    sub=p.add_subparsers(dest="command",required=True)
    v=sub.add_parser("validate"); v.add_argument("--input",required=True)
    t=sub.add_parser("train"); t.add_argument("--input",required=True); t.add_argument("--config",required=True); t.add_argument("--output-dir",required=True)
    s=sub.add_parser("score"); s.add_argument("--input",required=True); s.add_argument("--config",required=True); s.add_argument("--model"); s.add_argument("--output",required=True); s.add_argument("--acknowledge-no-execution",action="store_true")
    b=sub.add_parser("backtest"); b.add_argument("--input",required=True); b.add_argument("--config",required=True); b.add_argument("--model"); b.add_argument("--output",required=True)
    m=sub.add_parser("map-records"); m.add_argument("--input",required=True); m.add_argument("--mapping",required=True); m.add_argument("--output",required=True)
    return p

def main(argv=None):
    args=parser().parse_args(argv)
    if args.command=="validate":
        rows=read_opportunities(args.input); print(json.dumps({"valid":True,"rows":len(rows),"with_outcomes":sum(o.outcome is not None for o in rows)},indent=2)); return
    if args.command=="map-records":
        mapping=load_mapping(args.mapping); mapped=[map_record(r,mapping) for r in jsonl_records(args.input)]
        p=Path(args.output); p.parent.mkdir(parents=True,exist_ok=True); p.write_text("\n".join(x.model_dump_json() for x in mapped)+"\n",encoding="utf-8"); print(json.dumps({"mapped":len(mapped),"output":str(p)},indent=2)); return
    config=load_config(args.config)
    bundle=load_bundle(args.model) if getattr(args,"model",None) else None
    rows=read_opportunities(args.input)
    if args.command=="train":
        bundle,report=train_model(rows,config); out=Path(args.output_dir); out.mkdir(parents=True,exist_ok=True); save_bundle(bundle,out/"model.joblib"); write_json(out/"training_report.json",report); print(json.dumps({"model":str(out/"model.joblib"),"report":str(out/"training_report.json")},indent=2)); return
    if args.command=="score":
        results=score_many(rows,config,bundle); write_safe_outbox(results,args.output,args.acknowledge_no_execution); print(json.dumps({"scored":len(results),"output":args.output,"execution_authorized":False},indent=2)); return
    if args.command=="backtest":
        report=run_selection_backtest(rows,config,bundle); write_json(args.output,report); print(json.dumps({"output":args.output,"scope":report["scope"]},indent=2)); return

if __name__=="__main__": main()
