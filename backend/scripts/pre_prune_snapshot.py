import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
import shutil

from sqlalchemy import text
from app.db.session import async_session_factory

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def create_pre_prune_snapshot():
    logger.info("Gathering pre-prune snapshot metadata...")
    
    snapshot = {
        "timestamp": datetime.utcnow().isoformat(),
        "system": {
            "disk_free_gb": shutil.disk_usage("/").free / (1024**3)
        },
        "database": {},
        "paper_wallet": {},
        "track_record": {}
    }
    
    async with async_session_factory() as session:
        # DB Size
        db_size = await session.scalar(text("SELECT pg_database_size(current_database())"))
        snapshot["database"]["logical_size_bytes"] = db_size
        
        # Snapshots stats
        snapshot_stats = (await session.execute(text("""
            SELECT count(*), min(captured_at), max(captured_at) 
            FROM token_market_snapshots
        """))).fetchone()
        snapshot["database"]["snapshots_count"] = snapshot_stats[0]
        snapshot["database"]["oldest_snapshot"] = snapshot_stats[1].isoformat() if snapshot_stats[1] else None
        snapshot["database"]["newest_snapshot"] = snapshot_stats[2].isoformat() if snapshot_stats[2] else None
        
        # Paper Wallet State
        watermark = await session.scalar(text("SELECT COALESCE(MIN(last_evaluated_at), NOW()) FROM paper_positions WHERE status = 'open'"))
        open_positions = await session.scalar(text("SELECT count(*) FROM paper_positions WHERE status = 'open'"))
        closed_positions = await session.scalar(text("SELECT count(*) FROM paper_positions WHERE status = 'closed'"))
        snapshot["paper_wallet"]["watermark"] = watermark.isoformat() if hasattr(watermark, 'isoformat') else watermark
        snapshot["paper_wallet"]["open_positions"] = open_positions
        snapshot["paper_wallet"]["closed_positions"] = closed_positions
        
        # Track Record
        radar_tokens = await session.scalar(text("SELECT count(*) FROM radar_tokens"))
        snapshot["track_record"]["radar_tokens_count"] = radar_tokens
        
        # A deterministic checksum of metrics
        # (Assuming paper_positions has some metrics like realized_pnl we can sum)
        try:
            checksum = await session.scalar(text("SELECT COALESCE(SUM(realized_pnl), 0) FROM paper_positions WHERE status = 'closed'"))
            snapshot["track_record"]["pnl_checksum"] = float(checksum)
        except Exception:
            snapshot["track_record"]["pnl_checksum"] = 0.0

    out_dir = Path("research_exports")
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"prune_checkpoint_{int(datetime.utcnow().timestamp())}.json"
    
    with open(out_file, "w") as f:
        json.dump(snapshot, f, indent=2)
        
    logger.info(f"Pre-prune snapshot saved to {out_file}")
    return snapshot

if __name__ == "__main__":
    asyncio.run(create_pre_prune_snapshot())
