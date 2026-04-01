import asyncio
import sys
sys.path.insert(0, '/app/src')

from workers.tasks import process_video_task

async def main():
    result = await process_video_task('24e6ac61-ec57-462e-8c42-63e1d3374aa1')
    print(f"Result: {result}")

asyncio.run(main())
