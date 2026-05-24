"""
Recovery script: enqueue a proper job for task 3be81d5d using the backend's JobQueue.
Run this inside the worker container.
"""
import asyncio
import sys
import os

# Ensure we can import from the backend
sys.path.insert(0, "/app")

from src.workers.job_queue import JobQueue
from src.config import get_config


async def main():
    config = get_config()
    print(f"Redis config: host={config.redis_host}, port={config.redis_port}")

    task_id = "3be81d5d-2f08-4fed-83d3-212727820d02"
    url = "https://youtu.be/3wgwaxIfUJQ?si=8Y24uKCeyvPW16UU"
    source_type = "youtube"
    user_id = "0KEupou6ERfOwZlbyOQrE2IONSXRIgyS"

    print(f"Enqueuing job for task {task_id}...")
    print(f"  url={url}")
    print(f"  source_type={source_type}")
    print(f"  user_id={user_id}")

    job_id = await JobQueue.enqueue_job(
        "process_video_task",
        task_id=task_id,
        url=url,
        source_type=source_type,
        user_id=user_id,
        font_family="TikTokSans-Regular",
        font_size=24,
        font_color="#FFFFFF",
        caption_template="default",
        processing_mode="fast",
        output_format="vertical",
        add_subtitles=True,
        target_language="eng",
        auto_center_face=False,
        eye_contact_correction=False,
        include_broll=True,
        split_screen=False,
        target_platform="all",
        num_clips=6,
        jump_cut=True,
        jump_cut_min_silence=0.3,
        zoom_on_cuts=True,
        cut_zoom_factor=1.08,
        denoise_audio=False,
        contextual_overlays=True,
        overlay_frequency="adaptive",
        audio_ducking=True,
        playback_speed=1.0,
        dramatic_slowmo=False,
        speed_ramp_enabled=True,
        use_scene_detection=True,
        force_fresh=True,
        use_comfyui_reframe=False,
        use_comfyui_thumbnail=False,
    )

    print(f"Job enqueued successfully! Job ID: {job_id}")
    print(f"Queue: viraclip_cpu_tasks")

    # Verify the job exists in the queue
    pool = await JobQueue.get_pool()
    queue_len = await pool.zcard("arq:queue:viraclip_cpu_tasks")
    print(f"Queue length: {queue_len}")

    # Also verify the job key exists
    job_key = f"arq:job:{job_id}"
    exists = await pool.exists(job_key)
    print(f"Job key {job_key} exists: {exists}")

    await JobQueue.close_pool()


if __name__ == "__main__":
    asyncio.run(main())
