from __future__ import annotations
from pathlib import Path
from typing import Iterable
import json
from .models import Opportunity, ScoreResult

def read_opportunities(path: str | Path) -> list[Opportunity]:
    out = []
    seen = set()
    with Path(path).open("r", encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = Opportunity.model_validate_json(line)
                if row.opportunity_id in seen:
                    raise ValueError(f"duplicate opportunity_id: {row.opportunity_id}")
                seen.add(row.opportunity_id)
                out.append(row)
            except Exception as e:
                raise ValueError(f"{path}:{n}: {e}") from e
    return out

def write_json(path: str | Path, value) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")

def jsonl_records(path: str | Path):
    with Path(path).open("r", encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as e:
                    raise ValueError(f"{path}:{n}: invalid JSON: {e}") from e
