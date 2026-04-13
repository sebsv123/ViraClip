import asyncio, sys
sys.path.insert(0, '/app')

async def main():
    from src.database import AsyncSessionLocal
    from sqlalchemy import text
    async with AsyncSessionLocal() as db:
        # Get table list
        tbls = await db.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"))
        print("Tables:", [t[0] for t in tbls.fetchall()])

        r = await db.execute(text("""
            SELECT id, status, updated_at
            FROM tasks
            WHERE user_id = 'test_user_001'
            ORDER BY created_at DESC LIMIT 6
        """))
        rows = r.fetchall()
        print(f"\n{'ID':36} | {'STATUS':12} | UPDATED")
        print("-" * 75)
        for row in rows:
            print(f"{str(row[0])} | {str(row[1]):12} | {row[2]}")

asyncio.run(main())
