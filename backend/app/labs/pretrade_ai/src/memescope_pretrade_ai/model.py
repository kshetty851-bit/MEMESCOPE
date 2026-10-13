from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import joblib
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from .config import AppConfig, config_hash
from .features import FEATURE_NAMES, feature_frame
from .models import Opportunity
from .split import chronological_purged_split

@dataclass
class ModelBundle:
    pipeline: Pipeline
    feature_names: list[str]
    version: str
    trained_at: str
    config_hash: str
    training_range: dict[str, str]

def _labels(rows: list[Opportunity]) -> np.ndarray:
    labels = []
    for o in rows:
        if not o.outcome or o.outcome.unresolved or not o.outcome.all_costs_included:
            raise ValueError(f"{o.opportunity_id}: resolved all-cost outcome required for training")
        labels.append(1 if o.outcome.net_pnl_usd > 0 else 0)
    return np.asarray(labels, dtype=int)

def _metrics(bundle: ModelBundle, rows: list[Opportunity]) -> dict:
    y = _labels(rows)
    p = bundle.pipeline.predict_proba(feature_frame(rows))[:, 1]
    pred = (p >= 0.5).astype(int)
    result = {"rows": len(rows), "positive_rate": float(y.mean()), "brier": float(brier_score_loss(y, p)), "log_loss": float(log_loss(y, p, labels=[0,1])), "accuracy_at_0_5": float(accuracy_score(y, pred))}
    result["roc_auc"] = float(roc_auc_score(y, p)) if len(set(y)) == 2 else None
    return result

def train_model(rows: list[Opportunity], config: AppConfig) -> tuple[ModelBundle, dict]:
    eligible = [o for o in rows if o.outcome and not o.outcome.unresolved and o.outcome.all_costs_included]
    if len(eligible) < config.training.minimum_rows:
        raise ValueError(f"need {config.training.minimum_rows} resolved all-cost rows; found {len(eligible)}")
    split = chronological_purged_split(eligible, config.training.split)
    y = _labels(split.train)
    if len(set(y)) < 2:
        raise ValueError("training partition must contain positive and negative outcomes")
    pipeline = Pipeline([
        ("impute", SimpleImputer(strategy="median", add_indicator=True)),
        ("scale", StandardScaler()),
        ("model", LogisticRegression(max_iter=config.training.max_iter, class_weight=None if config.training.class_weight == "none" else "balanced", random_state=config.training.random_state)),
    ])
    pipeline.fit(feature_frame(split.train), y)
    bundle = ModelBundle(pipeline, FEATURE_NAMES.copy(), "logistic-v1", datetime.now(timezone.utc).isoformat(), config_hash(config), {"train_start": min(o.decision_ts for o in split.train).isoformat(), "train_end": max(o.decision_ts for o in split.train).isoformat(), "labels_available_end": max(o.outcome.label_available_ts for o in split.train).isoformat()})
    report = {"warning": "Metrics describe supplied data only. They are not a performance claim or deployment approval.", "boundaries": split.boundaries, "removed_by_embargo_and_group_purge": split.removed, "train": _metrics(bundle, split.train), "validation": _metrics(bundle, split.validation), "test": _metrics(bundle, split.test)}
    return bundle, report

def save_bundle(bundle: ModelBundle, path: str | Path) -> None:
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True); joblib.dump(bundle, p)

def load_bundle(path: str | Path) -> ModelBundle:
    bundle = joblib.load(path)
    if not isinstance(bundle, ModelBundle) or bundle.feature_names != FEATURE_NAMES:
        raise ValueError("incompatible model bundle or feature schema")
    return bundle
