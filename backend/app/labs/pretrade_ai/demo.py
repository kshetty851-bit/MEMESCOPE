"""End-to-end software fixture; never reported as real trading performance."""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys


def run_demo():
    from .__main__ import LAB, output_path
    sys.path.insert(0, str(LAB / 'src'))
    from memescope_pretrade_ai.config import load_config
    from memescope_pretrade_ai.io import read_opportunities, write_json
    from memescope_pretrade_ai.model import train_model, save_bundle
    from memescope_pretrade_ai.split import chronological_purged_split
    from memescope_pretrade_ai.scoring import score_many
    from memescope_pretrade_ai.integration import write_safe_outbox
    from memescope_pretrade_ai.backtest import run_selection_backtest
    folder = Path(output_path(str(LAB / 'artifacts/demo')))
    folder.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(LAB / 'examples/generate_demo_data.py'),
                    '--output', str(folder / 'history.jsonl')], check=True)
    config = load_config(LAB / 'config/default.yaml')
    rows = read_opportunities(folder / 'history.jsonl')
    bundle, training = train_model(rows, config)
    save_bundle(bundle, folder / 'model.joblib')
    write_json(folder / 'training_report.json', training)
    test = chronological_purged_split(rows, config.training.split).test
    (folder / 'holdout.jsonl').write_text(''.join(o.model_dump_json() + '\n' for o in test))
    write_safe_outbox(score_many(test, config, bundle), folder / 'scores.jsonl', True)
    result = run_selection_backtest(test, config, bundle)
    result['dataset_kind'] = 'synthetic_software_fixture'
    result['performance_evidence'] = False
    write_json(folder / 'backtest.json', result)
    write_json(folder / 'summary.json', {'status': 'passed', 'dataset_kind': 'synthetic_software_fixture',
               'performance_evidence': False, 'input_rows': len(rows), 'holdout_rows': len(test),
               'execution_authorized': False, 'production_write_authorized': False})
    print(json.dumps({'status': 'passed', 'outputs': str(folder),
                      'warning': 'Synthetic fixture only; not strategy performance.'}, indent=2))
