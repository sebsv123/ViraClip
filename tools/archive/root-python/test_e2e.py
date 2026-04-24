#!/usr/bin/env python3
import sys
sys.path.insert(0, '/app/src')

import time
import logging
import asyncio

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

start = time.time()

print("="*70)
print("🎬 ViraClip End-to-End Test")
print("="*70)

print("[1/4] Importing VideoCoordinator...")
from services.coordinator import VideoCoordinator

config = {
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

coordinator = VideoCoordinator(
    task_id='test_beta_001',
    video_path='/app/uploads/test_input.mp4',
    config=config
)
print(f"✅ Coordinator ready ({time.time() - start:.1f}s)")

print("[2/4] Starting coordinator.run()...")
print("-" * 70)

async def run_test():
    proc_start = time.time()
    
    result = await coordinator.run()
    
    proc_time = time.time() - proc_start
    total_time = time.time() - start
    
    print("-" * 70)
    print("✅ PIPELINE COMPLETED")
    print("=" * 70)
    print(f"\n📊 RESULT:")
    print(f"   Type: {type(result)}")
    print(f"   Value: {result}")
    print(f"\n⏱️  TIMING:")
    print(f"   Processing: {proc_time:.1f}s ({proc_time/60:.1f} min)")
    print(f"   Total: {total_time:.1f}s ({total_time/60:.1f} min)")
    
    return result, proc_time

try:
    result, proc_time = asyncio.run(run_test())
    
    # Check outputs
    print("\n[3/4] Checking outputs...")
    import os
    output_dir = '/app/exports/clips/test_beta_001'
    if os.path.exists(output_dir):
        files = os.listdir(output_dir)
        mp4_files = [f for f in files if f.endswith('.mp4')]
        print(f"✅ Output dir: {output_dir}")
        print(f"   Total files: {len(files)}")
        print(f"   MP4 files: {len(mp4_files)}")
        for f in mp4_files:
            fpath = os.path.join(output_dir, f)
            fsize = os.path.getsize(fpath) / (1024*1024)
            print(f"   - {f} ({fsize:.1f} MB)")
    else:
        print(f"⚠️  Output dir not found: {output_dir}")
        
    print("\n[4/4] Test completed successfully!")
    
except Exception as e:
    print("=" * 70)
    print("❌ ERROR IN PIPELINE")
    print("=" * 70)
    print(f"Type: {type(e).__name__}")
    print(f"Message: {e}")
    print("\n--- TRACEBACK ---")
    import traceback
    traceback.print_exc()
    sys.exit(1)
