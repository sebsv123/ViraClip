import asyncio, sys
sys.path.insert(0, '/app')

async def main():
    from src.database import AsyncSessionLocal
    from sqlalchemy import text
    async with AsyncSessionLocal() as db:
        r = await db.execute(text('SELECT id, email FROM users LIMIT 5'))
        rows = r.fetchall()
        for row in rows:
            print('user_id:', row[0], '| email:', row[1])
        if not rows:
            print('NO USERS - inserting test user')
            await db.execute(text(
                "INSERT INTO users (id, email, created_at) VALUES "
                "('test-user-1', 'test@viraclip.io', NOW()) "
                "ON CONFLICT DO NOTHING"
            ))
            await db.commit()
            print('Test user created: test-user-1')

asyncio.run(main())
