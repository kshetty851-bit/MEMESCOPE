import asyncio
from sqlalchemy import text
from app.db.session import engine

async def main():
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT COUNT(*) FROM paper_trade_audit"))
        total_trades = result.fetchone()[0] if result else 0
        print(f"Total trades in paper_trade_audit: {total_trades}")
        
        # Counts of not null fields
        fields_to_check = [
            "entry_execution_model_version",
            "exit_execution_model_version",
            "entry_execution_price_impact_pct",
            "exit_execution_price_impact_pct",
            "entry_liquidity_usd",
            "exit_liquidity_usd"
        ]
        
        print("\nCounts of populated fields:")
        for field in fields_to_check:
            res = await conn.execute(text(f"SELECT COUNT(*) FROM paper_trade_audit WHERE {field} IS NOT NULL"))
            val = res.fetchone()[0]
            print(f"  {field}_present: {val} / {total_trades}")
            
        # Entry executions
        print("\nExecution Provenance (Entry):")
        for val in ['jupiter', 'legacy']:
            res = await conn.execute(text(f"SELECT COUNT(*) FROM paper_trade_audit WHERE lower(entry_execution_model_version) = '{val}'"))
            print(f"  {val.capitalize()}: {res.fetchone()[0]}")
        res = await conn.execute(text("SELECT COUNT(*) FROM paper_trade_audit WHERE entry_execution_model_version IS NULL"))
        print(f"  Null/Unknown: {res.fetchone()[0]}")
        
        # Exit executions
        print("\nExecution Provenance (Exit):")
        for val in ['jupiter', 'legacy']:
            res = await conn.execute(text(f"SELECT COUNT(*) FROM paper_trade_audit WHERE lower(exit_execution_model_version) = '{val}'"))
            print(f"  {val.capitalize()}: {res.fetchone()[0]}")
        res = await conn.execute(text("SELECT COUNT(*) FROM paper_trade_audit WHERE exit_execution_model_version IS NULL"))
        print(f"  Null/Unknown: {res.fetchone()[0]}")

if __name__ == "__main__":
    asyncio.run(main())
