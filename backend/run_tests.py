#!/usr/bin/env python3
"""
Script standalone para ejecutar tests sin conftest.py
"""
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Set env vars
os.environ["BACKGROUND_COMPOSITE_ENABLED"] = "true"
os.environ["SAM2_ENABLED"] = "true"
os.environ["SAM2_MIN_VIRAL_SCORE"] = "7.5"
os.environ["SAM2_MIN_DURATION"] = "12.0"
os.environ["COMFYUI_ENABLED"] = "true"

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

async def test_imports():
    """Test 1: Verificar imports críticos"""
    print("\n🧪 Test 1: Imports críticos...")
    try:
        from services.virality_engine import get_virality_engine
        from services.smart_templates import get_template_selector
        from services.speed_control_service import get_speed_control_service
        from services.background_composite_service import background_composite_service
        from services.comfyui_integration import ComfyUIIntegrationService
        from services.creative_pipeline import CreativePipeline
        print("   ✅ Todos los imports OK")
        return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

async def test_smart_templates():
    """Test 2: Smart templates tiene los campos necesarios"""
    print("\n🧪 Test 2: Smart templates Preset...")
    try:
        from services.smart_templates import get_template_selector
        
        selector = get_template_selector()
        preset = selector.select("tiktok", "test", 75.0, 0.6)
        
        # Verificar campos
        assert hasattr(preset, 'zoom_punch_zoom'), "Falta zoom_punch_zoom"
        assert hasattr(preset, 'zoom_punch_duration'), "Falta zoom_punch_duration"
        assert preset.zoom_punch_zoom is not None
        assert preset.zoom_punch_duration is not None
        
        print(f"   ✅ Preset OK: zoom_punch_zoom={preset.zoom_punch_zoom}, zoom_punch_duration={preset.zoom_punch_duration}")
        return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

async def test_comfyui_lazy_imports():
    """Test 3: ComfyUI usa lazy imports"""
    print("\n🧪 Test 3: ComfyUI lazy imports...")
    try:
        from services.comfyui_integration import ComfyUIIntegrationService, _get_orchestrator
        
        # Verificar que _get_orchestrator existe
        assert callable(_get_orchestrator), "_get_orchestrator no es callable"
        
        # Crear instancia sin errores
        service = ComfyUIIntegrationService()
        assert hasattr(service, 'enabled')
        assert hasattr(service, 'uploads_path')
        
        print("   ✅ Lazy imports funcionan correctamente")
        return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
        return False

async def test_background_composite_service():
    """Test 4: Background composite service con mocks"""
    print("\n🧪 Test 4: Background composite service...")
    try:
        # Mockear dependencias antes de importar
        mock_scene_analyzer = MagicMock()
        mock_scene_analyzer.analyze = AsyncMock(return_value={
            "mode": "C",
            "confidence": 0.9,
            "reason": "viral_clean_clip"
        })
        
        mock_person_seg = MagicMock()
        mock_person_seg.extract_person = AsyncMock(return_value="/tmp/person.webm")
        
        mock_composite = MagicMock()
        mock_composite.composite = AsyncMock(return_value="/tmp/composite.mp4")
        
        mock_comfyui = MagicMock()
        mock_comfyui.process_with_comfyui = AsyncMock(return_value="/tmp/background.mp4")
        
        # Parchear
        with patch.dict('sys.modules', {
            'services.scene_analyzer': MagicMock(scene_analyzer=mock_scene_analyzer),
            'services.person_segmentation': MagicMock(person_segmentation_service=mock_person_seg),
            'services.composite_engine': MagicMock(composite_engine=mock_composite),
            'services.comfyui_integration': MagicMock(comfyui_integration=mock_comfyui),
        }):
            from services.background_composite_service import BackgroundCompositeService
            
            service = BackgroundCompositeService()
            
            # Test modo C (viral clean clip)
            result = await service.process(
                clip_path="/tmp/clip.mp4",
                task_id="test_mode_c",
                viral_score=8.5,
                duration=15.0,
                broll_prompt="cinematic background"
            )
            
            assert result["mode_used"] == "C", f"Expected mode C, got {result['mode_used']}"
            assert result["success"] is True
            assert result["reason"] == "viral_clean_clip"
            
        print("   ✅ Mode C funciona correctamente")
        return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_composite_mode_a():
    """Test 5: Composite Mode A (SAM2 + LTX)"""
    print("\n🧪 Test 5: Composite Mode A...")
    try:
        mock_scene_analyzer = MagicMock()
        mock_scene_analyzer.analyze = AsyncMock(return_value={
            "mode": "A",
            "confidence": 0.9,
            "reason": "talking_head_suitable"
        })
        
        mock_person_seg = MagicMock()
        mock_person_seg.extract_person = AsyncMock(return_value="/tmp/person.webm")
        
        mock_composite = MagicMock()
        mock_composite.composite = AsyncMock(return_value="/tmp/composite.mp4")
        
        mock_comfyui = MagicMock()
        mock_comfyui.process_with_comfyui = AsyncMock(return_value="/tmp/background.mp4")
        
        with patch.dict('sys.modules', {
            'services.scene_analyzer': MagicMock(scene_analyzer=mock_scene_analyzer),
            'services.person_segmentation': MagicMock(person_segmentation_service=mock_person_seg),
            'services.composite_engine': MagicMock(composite_engine=mock_composite),
            'services.comfyui_integration': MagicMock(comfyui_integration=mock_comfyui),
        }):
            from services.background_composite_service import BackgroundCompositeService
            
            service = BackgroundCompositeService()
            
            result = await service.process(
                clip_path="/tmp/clip.mp4",
                task_id="test_mode_a",
                viral_score=8.5,
                duration=15.0,
                broll_prompt="cinematic background"
            )
            
            assert result["mode_used"] == "A", f"Expected mode A, got {result['mode_used']}"
            assert result["success"] is True
            assert result["output_path"] == "/tmp/composite.mp4"
            
        print("   ✅ Mode A funciona correctamente")
        return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_composite_mode_b():
    """Test 6: Composite Mode B (fallback to B-roll)"""
    print("\n🧪 Test 6: Composite Mode B...")
    try:
        mock_scene_analyzer = MagicMock()
        mock_scene_analyzer.analyze = AsyncMock(return_value={
            "mode": "B",
            "confidence": 0.7,
            "reason": "too_long_for_sam2"
        })
        
        with patch.dict('sys.modules', {
            'services.scene_analyzer': MagicMock(scene_analyzer=mock_scene_analyzer),
        }):
            from services.background_composite_service import BackgroundCompositeService
            
            service = BackgroundCompositeService()
            
            result = await service.process(
                clip_path="/tmp/clip.mp4",
                task_id="test_mode_b",
                viral_score=8.5,
                duration=30.0,
                broll_prompt="cinematic background"
            )
            
            assert result["mode_used"] == "B", f"Expected mode B, got {result['mode_used']}"
            assert result["success"] is True
            assert result["reason"] == "too_long_for_sam2"
            
        print("   ✅ Mode B funciona correctamente")
        return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_composite_error_handling():
    """Test 7: Error handling - pipeline continues on errors"""
    print("\n🧪 Test 7: Error handling...")
    try:
        mock_scene_analyzer = MagicMock()
        mock_scene_analyzer.analyze = AsyncMock(side_effect=Exception("Scene analysis failed"))
        
        with patch.dict('sys.modules', {
            'services.scene_analyzer': MagicMock(scene_analyzer=mock_scene_analyzer),
        }):
            from services.background_composite_service import BackgroundCompositeService
            
            service = BackgroundCompositeService()
            
            result = await service.process(
                clip_path="/tmp/clip.mp4",
                task_id="test_error",
                viral_score=8.5,
                duration=15.0,
                broll_prompt="cinematic background"
            )
            
            assert result["mode_used"] == "B", f"Expected mode B on error, got {result['mode_used']}"
            assert result["success"] is True
            assert "error" in result["reason"].lower() or "fallback" in result["reason"].lower()
            
        print("   ✅ Error handling funciona correctamente")
        return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    print("=" * 60)
    print("RUNNING STANDALONE TESTS")
    print("=" * 60)
    
    tests = [
        test_imports,
        test_smart_templates,
        test_comfyui_lazy_imports,
        test_background_composite_service,
        test_composite_mode_a,
        test_composite_mode_b,
        test_composite_error_handling,
    ]
    
    results = []
    for test in tests:
        try:
            result = await test()
            results.append(result)
        except Exception as e:
            print(f"   ❌ Test failed with exception: {e}")
            results.append(False)
    
    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"RESULTS: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed!")
        return 0
    else:
        print("⚠️  Some tests failed")
        return 1

if __name__ == "__main__":
    exit(asyncio.run(main()))
