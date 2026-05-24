"""
Enqueue task 3be81d5d-2f08-4fed-83d3-212727820d02 into ARQ/Redis for processing.
"""
import asyncio
import sys
import os

# Add backend/src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend/src"))

async def main():
    from workers.job_queue import JobQueue
    
    task_id = "3be81d5d-2f08-4fed-83d3-212727820d02"
    source_url = "https://youtu.be/3wgwaxIfUJQ?si=8Y24uKCeyvPW16UU"
    source_type = "youtube"
    user_id = "0KEupou6ERfOwZlbyOQrE2IONSXRIgyS"
    processing_mode = "elite"
    output_format = "vertical"
    add_subtitles = True
    
    print(f"Enqueuing task {task_id}...")
    print(f"  source_url: {source_url}")
    print(f"  source_type: {source_type}")
    print(f"  user_id: {user_id}")
    print(f"  processing_mode: {processing_mode}")
    
    job_id = await JobQueue.enqueue_processing_job(
        "process_video_task",
        processing_mode,
        task_id,
        source_url,
        source_type,
        user_id,
        "TikTokSans-Regular",  # font_family
        24,                     # font_size
        "#FFFFFF",              # font_color
        "hormozi",              # caption_template
        processing_mode,        # processing_mode (again, as positional arg)
        output_format,          # output_format
        add_subtitles,          # add_subtitles
    )
    
    print(f"✅ Job enqueued successfully! job_id={job_id}")

if __name__ == "__main__":
    asyncio.run(main())
