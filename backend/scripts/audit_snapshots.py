import asyncio
import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def main():
    # Use environment vars or default
    db_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://memescope:memescope@localhost:5433/memescope")
    engine = create_async_engine(db_url)
    
    async with engine.connect() as conn:
        print("--- Total Rows ---")
        res = await conn.execute(text("SELECT count(*) FROM token_market_snapshots;"))
        print(f"Total Rows: {res.scalar()}")
        
        print("\n--- Disk Usage ---")
        res = await conn.execute(text("""
            SELECT pg_size_pretty(pg_relation_size('token_market_snapshots')) as table_size,
                   pg_size_pretty(pg_indexes_size('token_market_snapshots')) as index_size,
                   pg_size_pretty(pg_total_relation_size('token_market_snapshots')) as total_size;
        """))
        print(res.mappings().first())
        
        print("\n--- Top Queries ---")
        res = await conn.execute(text("""
            SELECT query, calls, total_exec_time / 1000 as total_exec_time_sec, mean_exec_time
            FROM pg_stat_statements
            WHERE query LIKE '%token_market_snapshots%' AND query NOT LIKE '%pg_stat_statements%'
            ORDER BY total_exec_time DESC
            LIMIT 5;
        """))
        for row in res.mappings().all():
            print(f"Calls: {row['calls']}, Mean Time: {row['mean_exec_time']:.2f}ms, Query: {row['query'][:200]}...")
            
        print("\n--- Distribution by Age ---")
        res = await conn.execute(text("""
            SELECT 
              CASE 
                WHEN timestamp >= NOW() - INTERVAL '1 day' THEN '< 1 day'
                WHEN timestamp >= NOW() - INTERVAL '7 days' THEN '1-7 days'
                WHEN timestamp >= NOW() - INTERVAL '14 days' THEN '7-14 days'
                WHEN timestamp >= NOW() - INTERVAL '30 days' THEN '14-30 days'
                ELSE '> 30 days'
              END as age_bucket,
              count(*) as num_rows
            FROM token_market_snapshots
            GROUP BY 1
            ORDER BY 1;
        """))
        for row in res.mappings().all():
            print(f"{row['age_bucket']}: {row['num_rows']}")
            
        print("\n--- Rows Per Token (Avg) ---")
        res = await conn.execute(text("""
            SELECT avg(cnt) as avg_rows_per_token, max(cnt) as max_rows_per_token FROM (
                SELECT token_address, count(*) as cnt 
                FROM token_market_snapshots 
                GROUP BY token_address
            ) t;
        """))
        print(res.mappings().first())

        print("\n--- Rows / Day ---")
        res = await conn.execute(text("""
            SELECT date_trunc('day', timestamp) as day, count(*) as num_rows
            FROM token_market_snapshots
            GROUP BY 1
            ORDER BY 1 DESC
            LIMIT 5;
        """))
        for row in res.mappings().all():
            print(f"{row['day']}: {row['num_rows']}")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
