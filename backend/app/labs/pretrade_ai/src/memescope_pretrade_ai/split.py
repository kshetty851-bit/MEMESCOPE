from __future__ import annotations
from dataclasses import dataclass
from datetime import timedelta
from .config import SplitConfig
from .models import Opportunity

@dataclass
class SplitResult:
    train: list[Opportunity]
    validation: list[Opportunity]
    test: list[Opportunity]
    removed: dict[str, int]
    boundaries: dict[str, str]

def _group_value(op: Opportunity, field: str):
    if field == "mint": return op.mint
    if field == "pool": return op.pool
    if field == "creator_cluster_id": return op.identity.creator_cluster_id
    if field == "funder_cluster_id": return op.identity.funder_cluster_id
    raise ValueError(field)

def chronological_purged_split(rows: list[Opportunity], cfg: SplitConfig) -> SplitResult:
    rows = sorted(rows, key=lambda x: (x.decision_ts, x.opportunity_id))
    n = len(rows)
    if n < 12:
        raise ValueError("at least 12 chronological rows are required")
    i = max(1, min(n - 2, int(n * cfg.train_fraction)))
    j = max(i + 1, min(n - 1, int(n * (cfg.train_fraction + cfg.validation_fraction))))
    val_start, test_start = rows[i].decision_ts, rows[j].decision_ts
    embargo = timedelta(minutes=cfg.embargo_minutes)
    train0, val0, test0 = rows[:i], rows[i:j], rows[j:]
    train = [o for o in train0 if o.outcome and o.outcome.label_available_ts <= val_start - embargo]
    val = [o for o in val0 if o.decision_ts >= val_start + embargo and o.outcome and o.outcome.label_available_ts <= test_start - embargo]
    test = [o for o in test0 if o.decision_ts >= test_start + embargo]
    removed = {"train_time_embargo": len(train0)-len(train), "validation_time_embargo": len(val0)-len(val), "test_time_embargo": len(test0)-len(test), "train_group_purge": 0, "validation_group_purge": 0}
    for field in cfg.purge_group_fields:
        later = {_group_value(o, field) for o in val + test} - {None, ""}
        before = len(train)
        train = [o for o in train if _group_value(o, field) not in later]
        removed["train_group_purge"] += before - len(train)
        test_values = {_group_value(o, field) for o in test} - {None, ""}
        before = len(val)
        val = [o for o in val if _group_value(o, field) not in test_values]
        removed["validation_group_purge"] += before - len(val)
    if not train or not val or not test:
        raise ValueError(f"split empty after embargo/purge: train={len(train)}, validation={len(val)}, test={len(test)}; removed={removed}")
    return SplitResult(train, val, test, removed, {"validation_boundary": val_start.isoformat(), "test_boundary": test_start.isoformat()})
