import pytest
from datetime import timedelta
from conftest import make_op
from memescope_pretrade_ai.models import Opportunity

def test_future_feature_rejected():
    op=make_op(); data=op.model_dump(); data["features"]["liquidity_usd"]["observed_at"]=op.decision_ts+timedelta(seconds=1)
    with pytest.raises(ValueError,match="after decision_ts"): Opportunity.model_validate(data)
