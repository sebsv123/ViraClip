#!/usr/bin/env python3
import asyncio
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, "/app/src")

from observability import configure_logging, set_trace_id
from workers.tasks import process_video_task
from redis.asyncio import Redis

async def main():
    task_id = str(uuid.uuid4())
    
    print("🎬 INICIANDO PROCESAMIENTO VIRACLIP")
    print("=" * 50)
    print(f"📹 Video: /app/uploads/video.mp4")
    print(f"🆔 Task ID: {task_id}")
    print("=" * 50)
    print()
    
    redis = Redis.from_url("redis://viraclip-redis:6379")
    ctx = {"redis": redis}
    
    result = await process_video_task(
        ctx=ctx,
        task_id=task_id,
        url="/app/uploads/video.mp4",
        source_type="upload",
        user_id="test_user",
        target_platform="tiktok",
        num_clips=3
    )
    
    print()
    print("=" * 50)
    print("✅ RESULTADO:")
    print("=" * 50)
    print(json.dumps(result, indent=2, default=str))
    
    with open("/app/result.json", "w") as f:
        json.dump(result, f, indent=2, default=str)
    
    print()
    print("💾 Resultado guardado en: /app/result.json")
    print("🏁 PROCESO COMPLETADO")

if __name__ == "__main__":
    asyncio.run(main())
