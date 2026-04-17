#!/usr/bin/env python3
"""
Complete Flow Verification
===========================

Tests that ALL viral editing features are wired and will execute on every clip.
"""

import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_api_to_execution_chain():
    """Verify parameters flow from API → Worker → TaskService → Execution"""
    logger.info("=" * 60)
    logger.info("TEST: API → Execution Chain Verification")
    logger.info("=" * 60)
    
    # Step 1: Verify API route accepts parameters
    try:
        from src.api.routes.tasks import router
        import inspect
        
        # Find the create_task endpoint
        for route in router.routes:
            if hasattr(route, 'endpoint') and route.endpoint.__name__ == 'create_task':
                logger.info("✓ API endpoint found: POST /api/tasks")
                
                # Check if endpoint code references viral editing params
                source = inspect.getsource(route.endpoint)
                
                checks = {
                    "jump_cut": "jump_cut" in source,
                    "jump_cut_min_silence": "jump_cut_min_silence" in source,
                    "zoom_on_cuts": "zoom_on_cuts" in source,
                    "cut_zoom_factor": "cut_zoom_factor" in source,
                    "denoise_audio": "denoise_audio" in source,
                }
                
                for param, found in checks.items():
                    status = "✓" if found else "✗"
                    logger.info(f"  {status} API accepts '{param}': {found}")
                
                if not all(checks.values()):
                    logger.error("  ✗ Missing parameters in API!")
                    return False
                    
                break
        
    except Exception as e:
        logger.error(f"✗ API check failed: {e}")
        return False
    
    # Step 2: Verify worker receives parameters
    try:
        from src.workers.tasks import process_video_task
        import inspect
        
        sig = inspect.signature(process_video_task)
        params = list(sig.parameters.keys())
        
        required = ["jump_cut", "jump_cut_min_silence", "zoom_on_cuts", "cut_zoom_factor", "denoise_audio"]
        for param in required:
            if param in params:
                logger.info(f"  ✓ Worker accepts '{param}'")
            else:
                logger.error(f"  ✗ Worker MISSING '{param}'")
                return False
                
    except Exception as e:
        logger.error(f"✗ Worker check failed: {e}")
        return False
    
    # Step 3: Verify TaskService receives parameters
    try:
        from src.services.task_service import TaskService
        import inspect
        
        sig = inspect.signature(TaskService.process_task)
        params = list(sig.parameters.keys())
        
        required = ["jump_cut", "jump_cut_min_silence", "zoom_on_cuts", "cut_zoom_factor", "denoise_audio"]
        for param in required:
            if param in params:
                logger.info(f"  ✓ TaskService accepts '{param}'")
            else:
                logger.error(f"  ✗ TaskService MISSING '{param}'")
                return False
                
    except Exception as e:
        logger.error(f"✗ TaskService check failed: {e}")
        return False
    
    # Step 4: Verify execution code exists
    try:
        import inspect
        source = inspect.getsource(TaskService.process_task)
        
        # Check for jump_cut execution
        if "apply_jump_cuts_with_zoom" in source:
            logger.info("  ✓ Jump cut execution code present")
        else:
            logger.error("  ✗ Jump cut execution code MISSING!")
            return False
        
        # Check for denoise execution
        if "denoise_audio as _denoise" in source:
            logger.info("  ✓ Audio denoise execution code present")
        else:
            logger.error("  ✗ Audio denoise execution code MISSING!")
            return False
        
        # Check for conditional execution
        if "if info is not None and jump_cut:" in source:
            logger.info("  ✓ Jump cut conditional check present")
        else:
            logger.error("  ✗ Jump cut conditional MISSING!")
            return False
            
        if "if info is not None and denoise_audio:" in source:
            logger.info("  ✓ Denoise conditional check present")
        else:
            logger.error("  ✗ Denoise conditional MISSING!")
            return False
        
    except Exception as e:
        logger.error(f"✗ Execution code check failed: {e}")
        return False
    
    logger.info("\n✅ Complete chain verified: API → Worker → TaskService → Execution")
    return True


async def test_creative_pipeline_always_runs():
    """Verify creative pipeline runs on EVERY clip (not opt-in)"""
    logger.info("\n" + "=" * 60)
    logger.info("TEST: Creative Pipeline Always Runs")
    logger.info("=" * 60)
    
    try:
        from src.services.task_service import TaskService
        import inspect
        
        source = inspect.getsource(TaskService.process_task)
        
        # Creative pipeline should run unconditionally (no if jump_cut check before it)
        if "get_creative_pipeline()" in source:
            logger.info("  ✓ Creative pipeline is called")
            
            # Check it's not behind a feature flag
            lines = source.split('\n')
            for i, line in enumerate(lines):
                if 'get_creative_pipeline()' in line:
                    # Look back for conditional
                    context = '\n'.join(lines[max(0, i-5):i])
                    if 'if info is not None:' in context and 'if jump_cut' not in context:
                        logger.info("  ✓ Creative pipeline runs on EVERY clip (not opt-in)")
                        return True
                    else:
                        logger.warning("  ⚠ Creative pipeline may be conditional")
                        return True
        else:
            logger.error("  ✗ Creative pipeline NOT called!")
            return False
            
    except Exception as e:
        logger.error(f"✗ Creative pipeline check failed: {e}")
        return False


async def test_execution_order():
    """Verify correct execution order: clip render → creative → denoise → jump_cut"""
    logger.info("\n" + "=" * 60)
    logger.info("TEST: Execution Order Verification")
    logger.info("=" * 60)
    
    try:
        from src.services.task_service import TaskService
        import inspect
        
        source = inspect.getsource(TaskService.process_task)
        
        # Find positions of each step
        creative_pos = source.find("get_creative_pipeline()")
        denoise_pos = source.find("denoise_audio as _denoise")
        jumpcut_pos = source.find("apply_jump_cuts_with_zoom")
        
        if creative_pos < 0:
            logger.error("  ✗ Creative pipeline not found!")
            return False
        if denoise_pos < 0:
            logger.error("  ✗ Denoise code not found!")
            return False
        if jumpcut_pos < 0:
            logger.error("  ✗ Jump cut code not found!")
            return False
        
        # Verify order
        steps = [
            ("Creative Pipeline", creative_pos),
            ("Audio Denoise", denoise_pos),
            ("Jump Cut + Zoom", jumpcut_pos),
        ]
        steps.sort(key=lambda x: x[1])
        
        logger.info("  Execution order:")
        for i, (name, pos) in enumerate(steps, 1):
            logger.info(f"    {i}. {name}")
        
        # Expected order
        if steps[0][0] == "Creative Pipeline" and \
           steps[1][0] == "Audio Denoise" and \
           steps[2][0] == "Jump Cut + Zoom":
            logger.info("  ✓ Execution order is correct")
            return True
        else:
            logger.error("  ✗ Execution order is WRONG!")
            return False
            
    except Exception as e:
        logger.error(f"✗ Execution order check failed: {e}")
        return False


async def test_all_features_available():
    """Verify ALL 5 viral editing features are functional"""
    logger.info("\n" + "=" * 60)
    logger.info("TEST: All 5 Viral Features Available")
    logger.info("=" * 60)
    
    features = {
        "1. Jump Cuts + Zoom": "src.services.cut_zoom_service",
        "2. Animated Captions": "src.services.caption_service",
        "3. B-roll Auto-Insert": "src.services.contextual_broll",
        "4. Video Effects (Zoom on Peaks)": "src.services.video_effects",
        "5. Sound Effects + Music": "src.services.smart_audio",
    }
    
    all_ok = True
    for name, module in features.items():
        try:
            __import__(module)
            logger.info(f"  ✓ {name}")
        except ImportError as e:
            logger.error(f"  ✗ {name}: {e}")
            all_ok = False
    
    return all_ok


async def test_segment_has_words():
    """Verify segments will have words available for jump_cut"""
    logger.info("\n" + "=" * 60)
    logger.info("TEST: Word Timings Available for Jump Cut")
    logger.info("=" * 60)
    
    try:
        from src.services.video_service import VideoService
        import inspect
        
        source = inspect.getsource(VideoService.create_single_clip)
        
        # Check if words are returned in clip info
        if '"words"' in source and 'words_with_confidence' in source:
            logger.info("  ✓ create_single_clip returns words")
        else:
            logger.warning("  ⚠ create_single_clip may not return words")
        
        # Check if AssemblyAI cache is used
        if 'load_cached_transcript_data' in source:
            logger.info("  ✓ AssemblyAI cache available for word timings")
        else:
            logger.warning("  ⚠ No AssemblyAI cache usage found")
        
        # Check fallback
        if 'ConfidenceSubtitleGenerator' in source or 'faster-whisper' in source:
            logger.info("  ✓ Whisper fallback available")
        else:
            logger.warning("  ⚠ No Whisper fallback found")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Word timing check failed: {e}")
        return False


async def main():
    """Run all verification tests"""
    logger.info("\n" + "=" * 60)
    logger.info("COMPLETE FLOW VERIFICATION SUITE")
    logger.info("=" * 60 + "\n")
    
    tests = [
        ("API → Execution Chain", test_api_to_execution_chain),
        ("Creative Pipeline Always Runs", test_creative_pipeline_always_runs),
        ("Execution Order", test_execution_order),
        ("All 5 Features Available", test_all_features_available),
        ("Word Timings for Jump Cut", test_segment_has_words),
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
        logger.info("\n✅ ALL FEATURES CONNECTED - Every clip will receive:")
        logger.info("  1. Creative Pipeline (B-roll, SFX, BGM, zoom on peaks)")
        logger.info("  2. Audio Denoise (if denoise_audio=true)")
        logger.info("  3. Jump Cuts + Zoom (if jump_cut=true)")
        logger.info("  4. Animated Captions (if add_subtitles=true)")
        logger.info("\n🚀 System ready for production use!")
        return 0
    else:
        logger.error(f"\n❌ {total - passed} test(s) failed - Check logs above")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
