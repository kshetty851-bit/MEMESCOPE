from conftest import make_op
from memescope_pretrade_ai.config import AppConfig
from memescope_pretrade_ai.scoring import score_opportunity

def test_preferred_band_and_creator_risk():
    cfg=AppConfig()
    clean=score_opportunity(make_op(liquidity=56000,rug=0),cfg)
    risky=score_opportunity(make_op(i=1,liquidity=56000,rug=1),cfg)
    assert clean.score > risky.score
    assert risky.decision == "REJECT"
    assert risky.execution_authorized is False

def test_thresholds_configurable():
    cfg=AppConfig.model_validate({"scoring":{"thresholds":{"accept_score":99,"review_score":98,"hard_reject_risk":80,"minimum_feature_completeness":.65}}})
    result=score_opportunity(make_op(),cfg)
    assert result.decision in {"REJECT","REVIEW"}
