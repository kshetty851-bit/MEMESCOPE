from datetime import datetime, timedelta, timezone
from conftest import make_op
from memescope_pretrade_ai.config import SplitConfig
from memescope_pretrade_ai.split import chronological_purged_split

def test_chronological_split_and_group_purge():
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    rows=[make_op(i, start+timedelta(hours=i), pnl=1 if i%2 else -1, creator=f"c{i}") for i in range(40)]
    rows[0]=make_op(0,start,pnl=-1,creator="repeat")
    rows[35]=make_op(35,start+timedelta(hours=35),pnl=1,creator="repeat")
    result=chronological_purged_split(rows,SplitConfig(embargo_minutes=15,purge_group_fields=["creator_cluster_id"]))
    assert max(x.decision_ts for x in result.train) < min(x.decision_ts for x in result.validation)
    assert max(x.decision_ts for x in result.validation) < min(x.decision_ts for x in result.test)
    assert all(x.identity.creator_cluster_id!="repeat" for x in result.train)
    assert all(x.outcome.label_available_ts <= min(y.decision_ts for y in result.validation) for x in result.train)
