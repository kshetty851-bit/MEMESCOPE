from __future__ import annotations
from datetime import datetime
from pathlib import Path
import yaml
from ..models import Opportunity

def _get(row, dotted):
    value = row
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value: return None
        value = value[part]
    return value

def load_mapping(path):
    with Path(path).open("r", encoding="utf-8") as f: mapping = yaml.safe_load(f)
    if mapping.get("status") != "connected":
        raise ValueError("mapping status is not 'connected'; resolve every TODO and document provenance first")
    def unresolved(value):
        if isinstance(value, dict): return any(unresolved(v) for v in value.values())
        if isinstance(value, list): return any(unresolved(v) for v in value)
        return isinstance(value, str) and 'TODO' in value
    if unresolved(mapping):
        raise ValueError("mapping still contains unresolved TODO values")
    return mapping

def map_record(row: dict, mapping: dict) -> Opportunity:
    base = mapping["canonical_fields"]
    features = {}
    for name, spec in mapping["features"].items():
        value = _get(row, spec["value"])
        observed = _get(row, spec["observed_at"])
        if observed is not None:
            features[name] = {"value":value, "observed_at":observed, "source":spec["source"], "quality":spec.get("quality","observed")}
    payload = {"schema_version":"1.0", "opportunity_id":_get(row,base["opportunity_id"]), "mint":_get(row,base["mint"]), "pool":_get(row,base["pool"]), "decision_ts":_get(row,base["decision_ts"]), "strategy_version":_get(row,base["strategy_version"]), "universe":_get(row,base["universe"]), "baseline_eligible":_get(row,base["baseline_eligible"]), "features":features, "identity":{}, "metadata":{"adapter":"memescope_mapping_v1"}}
    for k, dotted in mapping.get("identity",{}).items(): payload["identity"][k] = _get(row,dotted)
    if mapping.get("outcome"):
        payload["outcome"] = {k: _get(row, dotted) for k, dotted in mapping["outcome"].items()}
    return Opportunity.model_validate(payload)
