import asyncio
import arq
from datetime import datetime
import time

async def main():
    redis = await arq.create_pool(arq.connections.RedisSettings(host='redis', port=6379))
    # Enqueue with current timestamp
    job = await redis.enqueue_job(
        'process_video_task',
        '24e6ac61-ec57-462e-8c42-63e1d3374aa1',
        _queue_name='arq:queue'
    )
    print(f'Enqueued at {datetime.now().isoformat()}: {job}')
    await redis.aclose()

asyncio.run(main())
