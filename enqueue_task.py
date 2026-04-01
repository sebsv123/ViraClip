import asyncio
import arq

async def main():
    redis = await arq.create_pool(arq.connections.RedisSettings(host='redis', port=6379))
    job = await redis.enqueue_job('process_video_task', '24e6ac61-ec57-462e-8c42-63e1d3374aa1')
    print('Enqueued:', job)
    await redis.close()

asyncio.run(main())
