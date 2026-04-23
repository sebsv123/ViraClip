#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app/src')

import time
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

start = time.time()

print("🎬 ViraClip Pipeline Test - Starting imports...")
from services.coordinator import coordinator
import asyncio

print(f"✅ Imports completed in {time.time() - start:.1f}s")

async def run_test():
    proc_start = time.time()
    print("🔄 Starting process_video...")
    
    result = await coordinator.process_video(
        video_path='/app/uploads/test_input.mp4',
        task_id='test_beta_001',
        options={
            'max_clips': 2,
            'target_duration': 30,
            'aspect_ratio': '9:16',
            'captions': True,
            'broll': True,
            'beat_sync': True,
            'lut': True,
            'hook_visual': True,
            'audio_ducking': True,
            'background_music': True,
            'denoise': True,
            'language': 'auto'
        }
    )
    
    proc_time = time.time() - proc_start
    total_time = time.time() - start
    
    print(f"\n{'='*60}")
    print(f"✅ PIPELINE COMPLETED")
    print(f"{'='*60}")
    print(f"Result: {result}")
    print(f"Processing time: {proc_time:.1f}s ({proc_time/60:.1f} min)")
    print(f"Total time: {total_time:.1f}s ({total_time/60:.1f} min)")
    
    return result

if __name__ == '__main__':
    try:
        result = asyncio.run(run_test())
    except Exception as e:
        print(f"\n{'='*60}")
        print(f"❌ ERROR: {type(e).__name__}: {e}")
        print(f"{'='*60}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
