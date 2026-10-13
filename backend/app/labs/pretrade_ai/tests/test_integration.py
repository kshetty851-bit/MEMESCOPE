import json, os
from conftest import make_op
from memescope_pretrade_ai.config import AppConfig
from memescope_pretrade_ai.integration import write_safe_outbox
from memescope_pretrade_ai.scoring import score_opportunity

def test_safe_outbox(tmp_path):
    path=tmp_path/"out.jsonl"; result=score_opportunity(make_op(),AppConfig())
    write_safe_outbox([result],path,True)
    row=json.loads(path.read_text())
    assert row["execution_authorized"] is False
    assert row["integration_contract"]["may_execute_trade"] is False
    assert os.stat(path).st_mode & 0o777 == 0o600
