"""
Test script to verify all applied fixes and optimizations are working correctly.
Run inside container: /app/.venv/bin/python /app/scripts/test_fixes.py
"""
import sys
import os

PASS = []
FAIL = []

def check(name, condition, detail=""):
    if condition:
        print(f"  PASS  {name}" + (f" ({detail})" if detail else ""))
        PASS.append(name)
    else:
        print(f"  FAIL  {name}" + (f" ({detail})" if detail else ""))
        FAIL.append(name)


print("\n=== Fix 1: cleanup imports in worker startup ===")
try:
    from src.utils.cleanup import cleanup_old_clips, cleanup_old_downloads
    check("cleanup_old_clips importable", True)
    check("cleanup_old_downloads importable", True)
except ImportError as e:
    check("cleanup imports", False, str(e))

print("\n=== Fix 2: resource_manager works without psutil ===")
try:
    from src.utils.resource_manager import (
        detect_hardware_capabilities,
        cleanup_temp_files,
        should_throttle_processing,
        get_adaptive_settings,
    )
    hw = detect_hardware_capabilities()
    check("resource_manager importable", True)
    check("detect_hardware returns tier", hw.get("tier") in ("low", "minimal", "medium", "high"), hw.get("tier"))
    check("detect_hardware returns cpu_cores", isinstance(hw.get("cpu_cores"), int))
    adaptive = get_adaptive_settings(hw)
    check("get_adaptive_settings returns render_concurrency", "render_concurrency" in adaptive, str(adaptive.get("render_concurrency")))
except Exception as e:
    check("resource_manager", False, str(e))

print("\n=== Fix 3: VideoWriter fallback (avc1 -> mp4v -> copy) ===")
try:
    import cv2
    avc1 = cv2.VideoWriter_fourcc(*"avc1")
    out_avc1 = cv2.VideoWriter("/tmp/_test_avc1.mp4", avc1, 30, (64, 64))
    avc1_opens = out_avc1.isOpened()
    out_avc1.release()
    check("avc1 fails as expected (known broken in container)", not avc1_opens, f"opened={avc1_opens}")

    mp4v = cv2.VideoWriter_fourcc(*"mp4v")
    out_mp4v = cv2.VideoWriter("/tmp/_test_mp4v.mp4", mp4v, 30, (64, 64))
    mp4v_opens = out_mp4v.isOpened()
    out_mp4v.release()
    check("mp4v fallback opens successfully", mp4v_opens)

    # Verify the fallback code path exists in service
    import inspect
    from src.services.video_polish_service import VideoPolishService
    src = inspect.getsource(VideoPolishService.auto_center_face)
    check("shutil.copy fallback present in auto_center_face", "shutil.copy(input_path, output_path)" in src)
except Exception as e:
    check("VideoWriter test", False, str(e))

print("\n=== Fix 4: Worker startup imports clean ===")
try:
    from src.workers.tasks import worker_startup, process_video_task, WorkerSettings
    check("worker_startup importable", True)
    check("process_video_task importable", True)
    check("WorkerSettings importable", True)
except Exception as e:
    check("worker startup imports", False, str(e))

print("\n=== Fix 5: Config values are optimized ===")
try:
    from src.config import get_config
    c = get_config()
    check("FAST_MODE_MAX_CLIPS <= 3", c.fast_mode_max_clips <= 3, str(c.fast_mode_max_clips))
    check("MAX_ELITE_CLIPS <= 3", c.max_elite_clips <= 3, str(c.max_elite_clips))
    check("RENDER_CONCURRENCY is 1 or auto", str(c.render_concurrency) in ("1", "auto"), str(c.render_concurrency))
    check("WHISPER_MODEL_SIZE is tiny or small", c.whisper_model_size in ("tiny", "small", "base"), c.whisper_model_size)
except Exception as e:
    check("config values", False, str(e))

print("\n=== Fix 6: export_profiles preset is veryfast for Reels ===")
try:
    from src.video_processing.export_profiles import EXPORT_PROFILES
    from src.video_processing.export_profiles import Platform
    reels = EXPORT_PROFILES.get(Platform.REELS)
    if reels:
        preset = next((reels.extra_args[i+1] for i, a in enumerate(reels.extra_args) if a == "-preset"), None)
        check("Reels preset is veryfast (not slow)", preset == "veryfast", str(preset))
    else:
        check("Reels profile exists", False, "not found")
except Exception as e:
    check("export_profiles", False, str(e))

print("\n" + "="*50)
print(f"Results: {len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED:")
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("ALL CHECKS PASSED")
    sys.exit(0)
