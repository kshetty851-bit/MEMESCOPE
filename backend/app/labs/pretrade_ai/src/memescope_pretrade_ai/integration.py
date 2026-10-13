from __future__ import annotations
from pathlib import Path
import json, os, tempfile
from .models import ScoreResult

def write_safe_outbox(results: list[ScoreResult], output: str | Path, acknowledged: bool) -> None:
    if not acknowledged:
        raise PermissionError("refusing to write integration outbox without --acknowledge-no-execution")
    p = Path(output)
    p.parent.mkdir(parents=True, exist_ok=True)
    records = []
    for result in results:
        record = result.model_dump(mode="json")
        record["integration_contract"] = {"mode":"advisory_only", "may_execute_trade":False, "may_modify_production":False, "consumer_must_revalidate_at_use_time":True}
        records.append(json.dumps(record, sort_keys=True))
    fd, tmp = tempfile.mkstemp(prefix=p.name+".", dir=p.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(records) + ("\n" if records else "")); f.flush(); os.fsync(f.fileno())
        os.chmod(tmp, 0o600); os.replace(tmp, p)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
