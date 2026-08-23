import asyncio
from app.main import app
from app.repositories.market import MarketSnapshotRepository
from datetime import datetime, timezone

async def main():
    await app.db.setup()
    session_factory = app.db.session.SessionFactory
    async with session_factory() as session:
        repo = MarketSnapshotRepository(session)
        since = datetime(2026, 8, 5, tzinfo=timezone.utc)
        mints = ["8KomtC3jBZiW1g791pnHVxcNyX5JhTPMKJpsv232dPcy"]
        series = await repo.series_for_mints(mints, since=since)
        rows = series.get(mints[0], [])
        print(f"Found {len(rows)} rows for mint")
        if rows:
            print(f"First row: {rows[0].captured_at}, price={rows[0].price_usd}, status={rows[0].trading_status}")
            print(f"Last row: {rows[-1].captured_at}, price={rows[-1].price_usd}, status={rows[-1].trading_status}")

if __name__ == "__main__":
    asyncio.run(main())
