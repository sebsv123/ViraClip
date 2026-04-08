#!/usr/bin/env python3
"""
Diagnostic script to test each creative service independently.
Run with: docker exec viraclip-backend python /app/scripts/test_creative_services.py
"""
import asyncio
import sys
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.DEBUG,
    format='%(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_imports():
    """Test if all creative service modules can be imported."""
    logger.info("=" * 60)
    logger.info("PHASE 1: Testing imports...")
    logger.info("=" * 60)
    
    services = [
        ("multimodal_detector", "src.services.multimodal_detector", "get_multimodal_detector"),
        ("virality_engine", "src.services.virality_engine", "get_virality_engine"),
        ("hook_engine", "src.services.hook_engine", "get_hook_engine"),
        ("smart_templates", "src.services.smart_templates", "get_template_selector"),
        ("contextual_broll", "src.services.contextual_broll", "get_contextual_broll"),
        ("video_effects", "src.services.video_effects", "apply_preset_effects"),
        ("smart_audio", "src.services.smart_audio", "get_smart_audio"),
        ("learning_loop", "src.services.learning_loop", "get_learning_loop"),
        ("smart_auto_editor", "src.services.smart_auto_editor", "SmartAutoEditor"),
    ]
    
    results = {}
    for name, module_path, func_name in services:
        try:
            logger.info(f"Testing {name}...")
            module = __import__(module_path, fromlist=[func_name])
            func = getattr(module, func_name)
            logger.info(f"  ✓ {name}: import OK, {func_name} available")
            results[name] = {"status": "OK", "error": None}
        except ImportError as e:
            logger.error(f"  ✗ {name}: ImportError - {e}")
            results[name] = {"status": "IMPORT_ERROR", "error": str(e)}
        except Exception as e:
            logger.error(f"  ✗ {name}: {type(e).__name__} - {e}")
            results[name] = {"status": "ERROR", "error": str(e)}
    
    return results

async def test_dependencies():
    """Test critical Python dependencies."""
    logger.info("\n" + "=" * 60)
    logger.info("PHASE 2: Testing dependencies...")
    logger.info("=" * 60)
    
    deps = [
        "librosa",
        "moviepy", 
        "pydantic",
        "httpx",
        "faster_whisper",
        "numpy",
        "scipy",
    ]
    
    results = {}
    for dep in deps:
        try:
            __import__(dep)
            logger.info(f"  ✓ {dep}: installed")
            results[dep] = "OK"
        except ImportError as e:
            logger.error(f"  ✗ {dep}: NOT INSTALLED - {e}")
            results[dep] = f"MISSING: {e}"
    
    return results

async def test_multimodal_detector():
    """Test multimodal_detector with minimal data."""
    logger.info("\n" + "=" * 60)
    logger.info("PHASE 3: Testing multimodal_detector.generate_timeline()...")
    logger.info("=" * 60)
    
    try:
        from src.services.multimodal_detector import get_multimodal_detector
        
        detector = get_multimodal_detector()
        
        # Mock video path (doesn't need to exist for import test)
        mock_video = Path("/tmp/test_video.mp4")
        mock_words = [
            {"word": "hello", "start": 0.0, "end": 0.5},
            {"word": "world", "start": 0.5, "end": 1.0},
        ]
        
        logger.info("  Calling generate_timeline with mock data...")
        # This will likely fail on execution but shows if imports work
        try:
            timeline = await detector.generate_timeline(
                video_path=mock_video,
                segment_start=0.0,
                segment_end=2.0,
                words=mock_words,
            )
            logger.info(f"  ✓ generate_timeline returned: {len(timeline)} events")
            return "OK"
        except FileNotFoundError:
            logger.info("  ⚠ generate_timeline failed (expected - mock file), but method callable")
            return "CALLABLE"
        except Exception as e:
            logger.error(f"  ✗ generate_timeline execution failed: {e}")
            return f"EXEC_ERROR: {e}"
    
    except ImportError as e:
        logger.error(f"  ✗ Import failed: {e}")
        return f"IMPORT_ERROR: {e}"
    except Exception as e:
        logger.error(f"  ✗ Unexpected error: {e}")
        return f"ERROR: {e}"

async def test_virality_engine():
    """Test virality_engine with minimal data."""
    logger.info("\n" + "=" * 60)
    logger.info("PHASE 4: Testing virality_engine.predict()...")
    logger.info("=" * 60)
    
    try:
        from src.services.virality_engine import get_virality_engine
        
        engine = get_virality_engine()
        
        logger.info("  Calling predict with mock data...")
        try:
            result = await engine.predict(
                transcript="This is a test transcript",
                words=[{"word": "test", "start": 0.0, "end": 0.5}],
                audio_features={"energy": 0.5, "tempo_bpm": 120},
                timeline_events=[],
            )
            logger.info(f"  ✓ predict returned: score={result.score}")
            return "OK"
        except Exception as e:
            logger.error(f"  ✗ predict execution failed: {e}")
            return f"EXEC_ERROR: {e}"
    
    except ImportError as e:
        logger.error(f"  ✗ Import failed: {e}")
        return f"IMPORT_ERROR: {e}"
    except Exception as e:
        logger.error(f"  ✗ Unexpected error: {e}")
        return f"ERROR: {e}"

async def test_smart_auto_editor():
    """Test smart_auto_editor instantiation."""
    logger.info("\n" + "=" * 60)
    logger.info("PHASE 5: Testing SmartAutoEditor...")
    logger.info("=" * 60)
    
    try:
        from src.services.smart_auto_editor import SmartAutoEditor
        
        editor = SmartAutoEditor()
        logger.info(f"  ✓ SmartAutoEditor instantiated: {editor}")
        
        # Test detect_edit_decisions
        mock_words = [
            {"word": "hello", "start": 0.0, "end": 0.5},
            {"word": "world", "start": 1.5, "end": 2.0},  # 1s gap
        ]
        
        decisions = editor.detect_edit_decisions(
            transcript="hello world",
            word_timings=mock_words,
        )
        logger.info(f"  ✓ detect_edit_decisions returned {len(decisions)} decisions")
        return "OK"
    
    except ImportError as e:
        logger.error(f"  ✗ Import failed: {e}")
        return f"IMPORT_ERROR: {e}"
    except Exception as e:
        logger.error(f"  ✗ Unexpected error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return f"ERROR: {e}"

async def main():
    """Run all diagnostic tests."""
    logger.info("STARTING CREATIVE SERVICES DIAGNOSTIC TEST")
    logger.info("This will test if services can be imported and instantiated")
    logger.info("")
    
    results = {}
    
    # Phase 1: Test imports
    results["imports"] = await test_imports()
    
    # Phase 2: Test dependencies
    results["dependencies"] = await test_dependencies()
    
    # Phase 3-5: Test individual services
    results["multimodal_detector"] = await test_multimodal_detector()
    results["virality_engine"] = await test_virality_engine()
    results["smart_auto_editor"] = await test_smart_auto_editor()
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    
    import_failures = [k for k, v in results["imports"].items() if v["status"] != "OK"]
    dep_failures = [k for k, v in results["dependencies"].items() if v != "OK"]
    
    logger.info(f"Imports: {len(results['imports']) - len(import_failures)}/{len(results['imports'])} OK")
    if import_failures:
        logger.error(f"  Failed: {', '.join(import_failures)}")
    
    logger.info(f"Dependencies: {len(results['dependencies']) - len(dep_failures)}/{len(results['dependencies'])} OK")
    if dep_failures:
        logger.error(f"  Missing: {', '.join(dep_failures)}")
    
    logger.info(f"multimodal_detector: {results['multimodal_detector']}")
    logger.info(f"virality_engine: {results['virality_engine']}")
    logger.info(f"smart_auto_editor: {results['smart_auto_editor']}")
    
    # Exit code
    if import_failures or dep_failures:
        logger.error("\n❌ CRITICAL ISSUES FOUND - creative services cannot run")
        sys.exit(1)
    else:
        logger.info("\n✅ All critical imports and dependencies OK")
        sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())
