"""Regression tests for the isolated MEMESCOPE lab boundary."""
import ast
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
import yaml
from conftest import make_op
from memescope_pretrade_ai.adapters.mapping import load_mapping, map_record
from memescope_pretrade_ai.backtest import run_selection_backtest
from memescope_pretrade_ai.config import AppConfig
from memescope_pretrade_ai.io import read_opportunities
from memescope_pretrade_ai.models import Opportunity

LAB = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pretrade_lab_cli', LAB / '__main__.py')
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def test_no_application_or_trading_imports():
    forbidden = {'app', 'sqlalchemy', 'asyncpg', 'psycopg', 'celery', 'httpx',
                 'requests', 'aiohttp', 'socket', 'solana', 'solders', 'ccxt'}
    paths = list((LAB / 'src').rglob('*.py')) + list(LAB.glob('*.py'))
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [n.name for n in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or '']
            else:
                continue
            assert not any(n.split('.')[0] in forbidden for n in names), path


def test_status_without_application_imports(capsys):
    cli.main(['status'])
    result = json.loads(capsys.readouterr().out)
    assert result['wallet_connected'] is False
    assert result['database_connected'] is False
    assert result['automatic_execution'] is False
    assert result['live_mapping'] == 'unresolved'


def test_output_path_cannot_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, 'ARTIFACTS', tmp_path / 'artifacts')
    assert cli.output_path(str(tmp_path / 'artifacts/model/x'))
    with pytest.raises(ValueError):
        cli.output_path(str(tmp_path / 'wallet.json'))
    with pytest.raises(ValueError):
        cli.output_path(str(tmp_path / 'artifacts/../wallet.json'))
    (tmp_path / 'artifacts').mkdir()
    (tmp_path / 'artifacts/escape').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        cli.output_path(str(tmp_path / 'artifacts/escape/wallet.json'))


def test_refuse_symlink_artifact_root(tmp_path, monkeypatch):
    (tmp_path / 'artifacts').symlink_to(tmp_path, target_is_directory=True)
    monkeypatch.setattr(cli, 'ARTIFACTS', tmp_path / 'artifacts')
    with pytest.raises(ValueError):
        cli.output_path(str(tmp_path / 'artifacts/wallet.json'))


def test_duplicate_inputs_rejected(tmp_path):
    path = tmp_path / 'rows.jsonl'
    path.write_text((make_op().model_dump_json() + '\n') * 2)
    with pytest.raises(ValueError, match='duplicate'):
        read_opportunities(path)
    with pytest.raises(ValueError, match='duplicate'):
        run_selection_backtest([make_op(), make_op()], AppConfig())


def test_training_overlap_rejected_before_scoring():
    row = make_op()
    bundle = SimpleNamespace(training_range={'train_end': row.decision_ts.isoformat()})
    with pytest.raises(ValueError, match='overlap'):
        run_selection_backtest([row], AppConfig(), bundle)


def test_bundled_mapping_is_unconnected():
    with pytest.raises(ValueError, match='not.*connected'):
        load_mapping(LAB / 'config/memescope_mapping.yaml')


def test_connected_status_cannot_bypass_todos(tmp_path):
    path = tmp_path / 'mapping.yaml'
    path.write_text(yaml.safe_dump({'status': 'connected', 'features': {'x': {'value': 'TODO.x'}}}))
    with pytest.raises(ValueError, match='TODO'):
        load_mapping(path)


def test_mapping_keeps_false_and_outcomes():
    raw = make_op().model_dump(mode='json')
    raw['baseline_eligible'] = False
    base = {k: k for k in ['opportunity_id', 'mint', 'pool', 'decision_ts',
                           'strategy_version', 'universe', 'baseline_eligible']}
    mapping = {'canonical_fields': base, 'features': {},
               'outcome': {k: 'outcome.' + k for k in raw['outcome']}}
    op = map_record(raw, mapping)
    assert op.baseline_eligible is False
    assert op.outcome.net_pnl_usd == 1
    raw['baseline_eligible'] = 'false'
    with pytest.raises(ValueError):
        map_record(raw, mapping)
    del raw['baseline_eligible']
    with pytest.raises(ValueError):
        map_record(raw, mapping)


def test_identity_needs_knowledge_timestamp():
    raw = make_op().model_dump(mode='json')
    raw['identity']['linkage_observed_at'] = None
    with pytest.raises(ValueError, match='observation timestamp'):
        Opportunity.model_validate(raw)


def test_nonfinite_outcome_rejected():
    raw = make_op().model_dump(mode='json')
    raw['outcome']['matched_size_exit_proceeds_usd'] = float('inf')
    with pytest.raises(ValueError):
        Opportunity.model_validate(raw)
