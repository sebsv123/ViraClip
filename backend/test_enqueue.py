"""Enqueue a test task directly into the worker container, bypassing API."""
import subprocess, sys, time

task_id = f"test_{int(time.time())}"
url = sys.argv[1] if len(sys.argv) > 1 else "https://youtu.be/3wgwaxIfUJQ"

code = f"""
import asyncio
from arq import create_pool
from arq.connections import RedisSettings

async def main():
    r = await create_pool(RedisSettings(host='redis', port=6379))
    j = await r.enqueue_job(
        'process_video_task',
        '{task_id}',
        '{url}',
        'youtube',
        'test-user',
        processing_mode='fast',
        num_clips=3,
        force_fresh=True,
        _queue_name='viraclip_cpu_tasks',
    )
    print(f'OK job={{j.job_id}}')
    await r.close()

asyncio.run(main())
"""

print(f"Enqueueing {task_id} → {url}")
r = subprocess.run(
    ["docker", "exec", "viraclip-worker", ".venv/bin/python", "-c", code],
    capture_output=True, text=True, timeout=30,
)
out = (r.stdout + r.stderr).strip()
print(out)
if r.returncode == 0:
    print(f"\n✓ Monitor: docker logs -f viraclip-worker 2>&1 | grep -E 'LLM translated|BRoll|Step 4.9|RE-ALIGN|CLIP-GUARD'")
else:
    print(f"\n✗ Exit {r.returncode}")
