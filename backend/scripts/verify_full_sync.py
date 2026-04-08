#!/usr/bin/env python3
"""
Complete ViraClip Synchronization Verification
Checks all dependencies, services, routes, and features are connected
"""
import os
import sys
from pathlib import Path


def check_env_vars():
    """Verify all viral feature env vars are set"""
    print("\n" + "=" * 60)
    print("1. ENVIRONMENT VARIABLES CHECK")
    print("=" * 60)
    
    required_vars = {
        "PEXELS_API_KEY": "Pexels stock media",
        "UNSPLASH_ACCESS_KEY": "Unsplash stock photos",
        "GROQ_API_KEY": "AI inference",
        "CONTEXTUAL_OVERLAYS_ENABLED": "Overlays feature",
        "SPEED_CONTROL_ENABLED": "Speed control",
        "SCENE_DETECTION_ENABLED": "Scene detection",
        "AUDIO_DUCKING_ENABLED": "Audio ducking",
        "WHISPER_MODEL_SIZE": "Transcription model",
    }
    
    missing = []
    configured = []
    
    for var, desc in required_vars.items():
        value = os.environ.get(var)
        if value:
            # Don't show full API keys
            if "KEY" in var or "ACCESS" in var:
                display = f"{value[:8]}..." if len(value) > 8 else "SET"
            else:
                display = value
            configured.append(f"  ✅ {var}: {display} ({desc})")
        else:
            missing.append(f"  ❌ {var}: NOT SET ({desc})")
    
    for line in configured:
        print(line)
    for line in missing:
        print(line)
    
    return len(missing) == 0


def check_audio_library():
    """Verify audio library structure"""
    print("\n" + "=" * 60)
    print("2. AUDIO LIBRARY CHECK")
    print("=" * 60)
    
    audio_path = Path("/app/assets/sounds")
    bgm_path = audio_path / "bgm"
    sfx_path = audio_path / "sfx"
    
    bgm_files = list(bgm_path.glob("*.mp3")) if bgm_path.exists() else []
    sfx_files = list(sfx_path.glob("*.mp3")) if sfx_path.exists() else []
    
    # Also check root for SFX
    root_sfx = list(audio_path.glob("*.mp3")) if audio_path.exists() else []
    
    total_bgm = len(bgm_files)
    total_sfx = len(sfx_files) + len(root_sfx)
    
    print(f"  BGM files: {total_bgm}")
    print(f"  SFX files: {total_sfx}")
    print(f"  Total: {total_bgm + total_sfx} audio files")
    
    if total_bgm >= 5 and total_sfx >= 5:
        print("  ✅ Audio library sufficient for production")
        return True
    else:
        print("  ⚠️  Audio library minimal (still functional)")
        return True  # Non-critical


def check_services():
    """Verify critical services exist"""
    print("\n" + "=" * 60)
    print("3. CRITICAL SERVICES CHECK")
    print("=" * 60)
    
    services_dir = Path("/app/src/services")
    critical_services = [
        "coordinator.py",
        "video_service.py",
        "creative_pipeline.py",
        "overlay_content_source.py",
        "audio_library_service.py",
        "audio_ducking_service.py",
        "scene_aware_segmenter.py",
        "transition_selector.py",
        "virality_engine.py",
    ]
    
    all_exist = True
    for service in critical_services:
        path = services_dir / service
        if path.exists():
            print(f"  ✅ {service}")
        else:
            print(f"  ❌ {service} NOT FOUND")
            all_exist = False
    
    return all_exist


def check_viral_features():
    """Test if viral features can be imported"""
    print("\n" + "=" * 60)
    print("4. VIRAL FEATURES INTEGRATION CHECK")
    print("=" * 60)
    
    features = []
    
    # Test imports
    try:
        from src.services.overlay_content_source import get_overlay_content_source
        features.append(("Contextual Overlays", True))
    except Exception as e:
        print(f"  ERROR: {e}")
        features.append(("Contextual Overlays", False))
    
    try:
        from src.services.audio_ducking_service import get_audio_ducking_service
        features.append(("Audio Ducking", True))
    except Exception as e:
        features.append(("Audio Ducking", False))
    
    try:
        from src.services.scene_aware_segmenter import get_scene_aware_segmenter
        features.append(("Scene Detection", True))
    except Exception as e:
        features.append(("Scene Detection", False))
    
    try:
        from src.services.transition_selector import get_transition_selector
        features.append(("Transitions", True))
    except Exception as e:
        features.append(("Transitions", False))
    
    try:
        from src.services.audio_library_service import get_audio_library
        features.append(("Audio Library", True))
    except Exception as e:
        features.append(("Audio Library", False))
    
    for name, working in features:
        status = "✅" if working else "❌"
        print(f"  {status} {name}")
    
    return all(working for _, working in features)


def check_api_routes():
    """Verify API routes are registered"""
    print("\n" + "=" * 60)
    print("5. API ROUTES CHECK")
    print("=" * 60)
    
    routes_dir = Path("/app/src/api/routes")
    route_files = list(routes_dir.glob("*.py")) if routes_dir.exists() else []
    
    critical_routes = [
        "tasks.py",
        "clips.py",
        "creative.py",
        "analytics.py",
        "progress.py",
    ]
    
    all_exist = True
    for route in critical_routes:
        path = routes_dir / route
        if path.exists():
            print(f"  ✅ {route}")
        else:
            print(f"  ❌ {route} NOT FOUND")
            all_exist = False
    
    print(f"\n  Total route files: {len(route_files)}")
    
    return all_exist


def main():
    print("=" * 60)
    print("VIRACLIP FULL SYNCHRONIZATION VERIFICATION")
    print("=" * 60)
    
    checks = [
        ("Environment Variables", check_env_vars),
        ("Audio Library", check_audio_library),
        ("Critical Services", check_services),
        ("Viral Features", check_viral_features),
        ("API Routes", check_api_routes),
    ]
    
    results = []
    for name, check_func in checks:
        try:
            result = check_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n  ❌ {name} check failed: {e}")
            results.append((name, False))
    
    # Summary
    print("\n" + "=" * 60)
    print("VERIFICATION SUMMARY")
    print("=" * 60)
    
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {name}")
    
    all_passed = all(passed for _, passed in results)
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ ALL CHECKS PASSED - VIRACLIP FULLY SYNCHRONIZED!")
    else:
        print("⚠️  SOME CHECKS FAILED - REVIEW ABOVE")
    print("=" * 60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
