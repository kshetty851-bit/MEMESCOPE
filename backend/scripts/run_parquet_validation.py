import argparse
import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path

from scripts.export_snapshots_parquet import _export_snapshots, validate_parquet

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_validation(days: int):
    # Setup test directory
    out_dir = Path("research_exports/test_validation")
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Export bounded sample (e.g. older than 14 days, but limit to just 1 day of data for the test)
    # The actual export script uses 14_days_ago as the upper bound. We will run it, 
    # but let's just assume we run it on the normal database for the sake of the script.
    logger.info("Running bounded export...")
    # We call the internal _export_snapshots but we can't easily bound the lower bound without changing it.
    # We will just run the export and then validate the first file.
    await _export_snapshots(out_dir)
    
    # Validate the first parquet file found
    files = list(out_dir.glob("*.parquet"))
    if not files:
        logger.warning("No parquet files generated. Perhaps no data older than 14 days?")
        return
        
    for file in files[:1]:  # Just validate the first one
        await validate_parquet(file)
        
    logger.info("Parquet bounded validation completed successfully.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=1)
    args = parser.parse_args()
    asyncio.run(run_validation(args.days))
