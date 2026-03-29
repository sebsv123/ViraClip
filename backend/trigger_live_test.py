import httpx
import asyncio
import os
import sys

API_URL = "http://localhost:8000"

async def create_task(source_url, target_language="eng", split_screen=False, auto_center=False, eye_contact=False, include_broll=False):
    payload = {
        "source": {
            "url": source_url,
            "title": None
        },
        "font_options": {
            "font_family": "TikTokSans-Regular",
            "font_size": 24,
            "font_color": "#FFFFFF"
        },
        "caption_template": "default",
        "include_broll": include_broll,
        "processing_mode": "fast",
        "output_format": "vertical",
        "add_subtitles": True,
        "target_language": target_language,
        "auto_center_face": auto_center,
        "eye_contact_correction": eye_contact,
        "split_screen": split_screen
    }
    
    headers = {
        "user_id": "RA1McpZ5INrlo6GV3qJkrzRiCJJdtUeC",
        "Content-Type": "application/json"
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(f"{API_URL}/tasks/", json=payload, headers=headers)
            if response.status_code == 200:
                print(f"✅ Task created for {source_url}: {response.json().get('task_id')}")
                return response.json().get('task_id')
            else:
                print(f"❌ Failed to create task for {source_url}: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"❌ Error connecting to API for {source_url}: {e}")
            return None

async def main():
    print("🚀 Starting Live Testing Trigger...")
    
    # 1. Local Taekwondo (Auto-center + Split-screen)
    # Using the local path provided by the user
    await create_task(
        source_url=r"C:\Users\Sebitas\Downloads\Video.mov",
        auto_center=True,
        split_screen=True,
        include_broll=False # Split-screen uses fixed satisfying background usually
    )
    
    # 2. YouTube Short (Hook Titles)
    await create_task(
        source_url="https://youtube.com/shorts/I0hyQ2XQg2k?si=HEbDDieTSLNsHj-F",
        auto_center=False, # Already vertical
        split_screen=False
    )
    
    # 3. YouTube Desert (Scenario B-Roll)
    await create_task(
        source_url="https://youtu.be/3wgwaxIfUJQ?si=FE5xKiQb8k8WyKo5",
        include_broll=True,
        auto_center=True
    )
    
    # 4. YouTube Tech (Dubbing ES)
    await create_task(
        source_url="https://youtu.be/DHSigj8uPnE?si=jSoiW8g_cPUOOF_G",
        target_language="spa",
        auto_center=True
    )

if __name__ == "__main__":
    asyncio.run(main())
