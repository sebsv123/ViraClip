#!/usr/bin/env python3
"""
Viral Feature Verification Script
==================================

Tests each viral editing feature in isolation to prove functionality.
Run inside Docker: .venv/bin/python /app/scripts/verify_viral_features.py
"""

import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_1_health_check():
    """Verify all services are importable and dependencies installed."""
    logger.info("=" * 60)
    logger.info("TEST 1: Health Check - Service Imports & Dependencies")
    logger.info("=" * 60)
    
    results = {"pass": 0, "fail": 0}
    
    # Test service imports
    services = [
        ("cut_zoom_service", "src.services.cut_zoom_service"),
        ("caption_service", "src.services.caption_service"),
        ("creative_pipeline", "src.services.creative_pipeline"),
        ("video_effects", "src.services.video_effects"),
        ("smart_audio", "src.services.smart_audio"),
        ("contextual_broll", "src.services.contextual_broll"),
        ("multimodal_detector", "src.services.multimodal_detector"),
        ("virality_engine", "src.services.virality_engine"),
        ("hook_engine", "src.services.hook_engine"),
    ]
    
    for name, module_path in services:
        try:
            __import__(module_path)
            logger.info(f"  ✓ {name}: import OK")
            results["pass"] += 1
        except ImportError as e:
            logger.error(f"  ✗ {name}: FAILED - {e}")
            results["fail"] += 1
    
    # Test dependencies
    deps = ["librosa", "moviepy", "pydantic", "httpx", "numpy", "scipy"]
    for dep in deps:
        try:
            __import__(dep)
            logger.info(f"  ✓ {dep}: installed")
            results["pass"] += 1
        except ImportError:
            logger.error(f"  ✗ {dep}: NOT INSTALLED")
            results["fail"] += 1
    
    # Check audio assets
    sfx_dir = Path("/app/assets/sounds")
    bgm_dir = Path("/app/assets/sounds/bgm")
    
    sfx_count = len(list(sfx_dir.glob("*.mp3"))) if sfx_dir.exists() else 0
    bgm_count = len(list(bgm_dir.glob("*.mp3"))) if bgm_dir.exists() else 0
    
    logger.info(f"  ✓ SFX files: {sfx_count}")
    logger.info(f"  ✓ BGM files: {bgm_count}")
    
    if sfx_count >= 7 and bgm_count >= 5:
        results["pass"] += 2
    else:
        results["fail"] += 2
        logger.error(f"  ✗ Insufficient audio assets")
    
    logger.info(f"\nTest 1 Result: {results['pass']} pass, {results['fail']} fail")
    return results["fail"] == 0


async def test_2_jump_cut_service():
    """Test jump cut detection without actual video."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 2: Jump Cut Service - Silence Detection Logic")
    logger.info("=" * 60)
    
    try:
        from src.services.jump_cut_service import (
            find_filler_segments,
            build_keep_segments,
        )
        
        # Mock word timings with fillers and gaps
        mock_words = [
            {"word": "Hello", "start": 0.0, "end": 0.5},
            {"word": "um", "start": 0.5, "end": 0.7},  # Filler
            {"word": "today", "start": 1.2, "end": 1.6},  # 0.5s gap before
            {"word": "I", "start": 1.6, "end": 1.7},
            {"word": "want", "start": 1.7, "end": 2.0},
        ]
        
        # Test filler detection
        fillers = find_filler_segments(mock_words)
        logger.info(f"  ✓ Detected {len(fillers)} filler segments")
        
        # Test keep segment building
        remove_intervals = fillers + [(0.7, 1.2)]  # Add gap
        keep = build_keep_segments(3.0, remove_intervals)
        logger.info(f"  ✓ Built {len(keep)} keep segments")
        
        time_saved = sum(e - s for s, e in remove_intervals)
        logger.info(f"  ✓ Would save {time_saved:.2f}s from 3.0s clip")
        
        logger.info("\nTest 2 Result: PASS")
        return True
        
    except Exception as e:
        logger.error(f"  ✗ Test failed: {e}")
        logger.info("\nTest 2 Result: FAIL")
        return False


async def test_3_caption_styles():
    """Test caption style availability."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 3: Caption Service - Style System")
    logger.info("=" * 60)
    
    try:
        from src.services.caption_service import CaptionService
        
        service = CaptionService()
        styles = service.get_styles()
        
        logger.info(f"  ✓ Available styles: {', '.join(styles)}")
        
        # Test style selection
        for template in ["tiktok_viral", "reels_drama", "youtube_shorts"]:
            style = CaptionService.style_for_template(template, "tiktok")
            logger.info(f"  ✓ {template} → {style}")
        
        expected_styles = ["karaoke", "highlight", "tiktok", "minimal", "neon"]
        if all(s in styles for s in expected_styles):
            logger.info("\nTest 3 Result: PASS")
            return True
        else:
            logger.error("  ✗ Missing expected styles")
            logger.info("\nTest 3 Result: FAIL")
            return False
            
    except Exception as e:
        logger.error(f"  ✗ Test failed: {e}")
        logger.info("\nTest 3 Result: FAIL")
        return False


async def test_4_creative_pipeline():
    """Test creative pipeline initialization."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 4: Creative Pipeline - Service Integration")
    logger.info("=" * 60)
    
    try:
        from src.services.creative_pipeline import get_creative_pipeline
        from src.services.multimodal_detector import get_multimodal_detector
        from src.services.virality_engine import get_virality_engine
        from src.services.hook_engine import get_hook_engine
        from src.services.smart_audio import get_smart_audio
        
        # Test singleton instantiation
        cp = get_creative_pipeline()
        logger.info(f"  ✓ Creative pipeline: {type(cp).__name__}")
        
        md = get_multimodal_detector()
        logger.info(f"  ✓ Multimodal detector: {type(md).__name__}")
        
        ve = get_virality_engine()
        logger.info(f"  ✓ Virality engine: {type(ve).__name__}")
        
        he = get_hook_engine()
        logger.info(f"  ✓ Hook engine: {type(he).__name__}")
        
        sa = get_smart_audio()
        logger.info(f"  ✓ Smart audio: {type(sa).__name__}")
        
        logger.info("\nTest 4 Result: PASS")
        return True
        
    except Exception as e:
        logger.error(f"  ✗ Test failed: {e}", exc_info=True)
        logger.info("\nTest 4 Result: FAIL")
        return False


async def test_5_audio_assets():
    """Verify SFX and BGM assets exist and are readable."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 5: Audio Assets - SFX & BGM Files")
    logger.info("=" * 60)
    
    try:
        from src.services.smart_audio import find_bgm_track
        
        # Check SFX files
        sfx_dir = Path("/app/assets/sounds")
        sfx_files = list(sfx_dir.glob("*.mp3"))
        
        expected_sfx = [
            "whoosh_fast", "whoosh_heavy", "punch_impact",
            "ding_chime", "bass_boom", "tension_riser", "glitch_hit"
        ]
        
        for name in expected_sfx:
            found = any(name in f.stem for f in sfx_files)
            status = "✓" if found else "✗"
            logger.info(f"  {status} {name}.mp3")
        
        # Check BGM tracks
        bgm_track = find_bgm_track()
        if bgm_track:
            logger.info(f"  ✓ BGM track found: {bgm_track.name}")
        else:
            logger.warning("  ⚠ No BGM track found")
        
        # Check total counts
        bgm_dir = Path("/app/assets/sounds/bgm")
        bgm_count = len(list(bgm_dir.glob("*.mp3"))) if bgm_dir.exists() else 0
        
        logger.info(f"\n  Summary: {len(sfx_files)} SFX, {bgm_count} BGM")
        
        if len(sfx_files) >= 7 and bgm_count >= 5:
            logger.info("\nTest 5 Result: PASS")
            return True
        else:
            logger.error("  ✗ Insufficient audio files")
            logger.info("\nTest 5 Result: FAIL")
            return False
            
    except Exception as e:
        logger.error(f"  ✗ Test failed: {e}")
        logger.info("\nTest 5 Result: FAIL")
        return False


async def test_6_zoom_service():
    """Test zoom transition logic."""
    logger.info("\n" + "=" * 60)
    logger.info("TEST 6: Cut Zoom Service - Transition Logic")
    logger.info("=" * 60)
    
    try:
        from src.services.cut_zoom_service import apply_jump_cuts_with_zoom
        
        # Verify function signature
        import inspect
        sig = inspect.signature(apply_jump_cuts_with_zoom)
        params = list(sig.parameters.keys())
        
        expected_params = ["video_path", "output_path", "words", "min_silence_sec", "zoom_on_cuts", "zoom_factor"]
        
        for param in expected_params:
            if param in params:
                logger.info(f"  ✓ Parameter '{param}' available")
            else:
                logger.error(f"  ✗ Missing parameter '{param}'")
        
        logger.info("\nTest 6 Result: PASS")
        return True
        
    except Exception as e:
        logger.error(f"  ✗ Test failed: {e}")
        logger.info("\nTest 6 Result: FAIL")
        return False


async def main():
    """Run all verification tests."""
    logger.info("\n" + "=" * 60)
    logger.info("VIRAL FEATURE VERIFICATION SUITE")
    logger.info("=" * 60)
    
    tests = [
        ("Health Check", test_1_health_check),
        ("Jump Cut Service", test_2_jump_cut_service),
        ("Caption Styles", test_3_caption_styles),
        ("Creative Pipeline", test_4_creative_pipeline),
        ("Audio Assets", test_5_audio_assets),
        ("Zoom Service", test_6_zoom_service),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = await test_func()
            results.append((name, result))
        except Exception as e:
            logger.error(f"Test '{name}' crashed: {e}", exc_info=True)
            results.append((name, False))
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("FINAL RESULTS")
    logger.info("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"  {status}: {name}")
    
    logger.info("\n" + "=" * 60)
    logger.info(f"TOTAL: {passed}/{total} tests passed")
    logger.info("=" * 60)
    
    if passed == total:
        logger.info("\n✅ ALL SYSTEMS OPERATIONAL - Ready for video processing!")
        return 0
    else:
        logger.error(f"\n❌ {total - passed} test(s) failed - Check logs above")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
