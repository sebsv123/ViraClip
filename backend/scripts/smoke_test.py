"""
smoke_test.py — ViraClip End-to-End Smoke Test
===============================================
Verifica que todo el pipeline funciona correctamente:
  1. Crear task con video de prueba
  2. Procesar y generar clips
  3. Validar outputs (transcripción, virality scores, engagement curves)
  4. Verificar que archivos existen

Usage (PowerShell):
    # Test completo con video sample
    docker-compose exec backend python /app/scripts/smoke_test.py

    # Test con URL de YouTube
    docker-compose exec backend python /app/scripts/smoke_test.py --url "https://youtube.com/watch?v=..."

    # Test rápido (solo verificar imports y servicios)
    docker-compose exec backend python /app/scripts/smoke_test.py --quick

Exit codes:
    0 = smoke test passed
    1 = smoke test failed
    2 = configuration error
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Dict, Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


async def test_imports() -> bool:
    """Verificar que todos los módulos críticos se importan sin error."""
    logger.info("\n📦 Testing imports...")
    
    modules = [
        "faster_whisper",
        "transformers",
        "librosa",
        "scenedetect",
        "mediapipe",
        "moviepy",
        "sklearn",
        "torch",
        "numpy",
        "redis",
        "psutil",
    ]
    
    failed = []
    for mod in modules:
        try:
            __import__(mod)
            logger.info(f"  ✓ {mod}")
        except ImportError as e:
            logger.warning(f"  ⚠ {mod}: {e}")
            failed.append(mod)
    
    if failed:
        logger.warning(f"Missing optional modules: {', '.join(failed)}")
    
    return len(failed) == 0


async def test_services() -> bool:
    """Verificar que servicios críticos están disponibles."""
    logger.info("\n🔧 Testing services...")
    
    tests = []
    
    # Whisper
    try:
        from faster_whisper import WhisperModel
        model_size = os.getenv("WHISPER_MODEL_SIZE", "medium")
        logger.info(f"  ✓ Whisper service: model_size={model_size} (faster-whisper ready)")
        tests.append(True)
    except Exception as e:
        logger.error(f"  ❌ Whisper service: {e}")
        tests.append(False)
    
    # Viral scorer
    try:
        from services.viral_scorer_service import get_viral_scorer
        svc = get_viral_scorer()
        available = svc.is_available()
        if available:
            logger.info(f"  ✓ Viral scorer: trained model loaded")
        else:
            logger.warning(f"  ⚠ Viral scorer: no trained model (using heuristic)")
        tests.append(True)
    except Exception as e:
        logger.error(f"  ❌ Viral scorer: {e}")
        tests.append(False)
    
    # Engagement predictor
    try:
        from services.engagement_prediction_service import get_engagement_predictor
        svc = get_engagement_predictor()
        available = svc.is_available()
        if available:
            logger.info(f"  ✓ Engagement predictor: trained model loaded")
        else:
            logger.warning(f"  ⚠ Engagement predictor: no trained model (using heuristic)")
        tests.append(True)
    except Exception as e:
        logger.error(f"  ❌ Engagement predictor: {e}")
        tests.append(False)
    
    # ONNX service
    try:
        from services.onnx_inference_service import get_onnx_service
        svc = get_onnx_service()
        caps = svc.get_capabilities()
        if caps["viral_scorer_onnx"] or caps["engagement_onnx"]:
            n_loaded = sum(1 for k, v in caps.items() if isinstance(v, bool) and v)
            logger.info(f"  ✓ ONNX service: {n_loaded} model(s) loaded")
        else:
            logger.info(f"  ℹ ONNX service: no exported models (OK for development)")
        tests.append(True)
    except Exception as e:
        logger.error(f"  ❌ ONNX service: {e}")
        tests.append(False)
    
    return all(tests)


async def test_database() -> bool:
    """Verificar conexión a PostgreSQL."""
    logger.info("\n🗄 Testing database...")
    
    try:
        import asyncpg
        db_url = os.getenv("DATABASE_URL", "").replace("postgres://", "postgresql://").replace("postgresql+asyncpg://", "postgresql://")
        if not db_url:
            logger.warning("  ⚠ DATABASE_URL not set")
            return False
        
        conn = await asyncpg.connect(db_url)
        try:
            # Simple query
            result = await conn.fetchval("SELECT COUNT(*) FROM tasks")
            logger.info(f"  ✓ PostgreSQL connected ({result} tasks in DB)")
            return True
        finally:
            await conn.close()
            
    except Exception as e:
        logger.error(f"  ❌ Database connection failed: {e}")
        return False


async def test_redis() -> bool:
    """Verificar conexión a Redis."""
    logger.info("\n💾 Testing Redis...")
    
    try:
        import redis.asyncio as aioredis
        redis_host = os.getenv("REDIS_HOST", "redis")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))
        redis_url = os.getenv("REDIS_URL", f"redis://{redis_host}:{redis_port}")
        redis = await aioredis.from_url(redis_url)
        
        # Ping test
        await redis.ping()
        logger.info(f"  ✓ Redis connected")
        
        # Set/get test
        await redis.set("smoke_test", "ok", ex=5)
        val = await redis.get("smoke_test")
        assert val == b"ok"
        
        await redis.close()
        return True
        
    except Exception as e:
        logger.error(f"  ❌ Redis connection failed: {e}")
        return False


async def test_ffmpeg() -> bool:
    """Verificar que FFmpeg funciona."""
    logger.info("\n🎬 Testing FFmpeg...")
    
    try:
        import subprocess
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        
        if result.returncode == 0:
            version_line = result.stdout.split("\n")[0]
            logger.info(f"  ✓ {version_line}")
            
            # Check for key features
            features = result.stdout
            if "libx264" in features:
                logger.info(f"  ✓ H.264 encoder available")
            if "libfdk_aac" in features or "aac" in features:
                logger.info(f"  ✓ AAC encoder available")
            
            return True
        else:
            logger.error(f"  ❌ FFmpeg not working")
            return False
            
    except Exception as e:
        logger.error(f"  ❌ FFmpeg test failed: {e}")
        return False


async def test_end_to_end(video_url: str = None) -> bool:
    """
    Test completo del pipeline: task creation → processing → clip generation.
    
    Args:
        video_url: URL de YouTube para test (None = usar sample sintético)
    """
    logger.info("\n🚀 Testing end-to-end pipeline...")
    
    try:
        from services.video_service import VideoService
        
        if video_url:
            logger.info(f"  Input: {video_url}")
            # TODO: implementar download + processing de URL real
            logger.warning("  ⚠ URL processing not implemented in smoke test yet")
            return False
        else:
            # Crear video sintético corto (5 segundos silencio)
            logger.info("  Creating synthetic 5-second test video...")
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                test_video = Path(tmp.name)
            
            try:
                import subprocess
                # Generar 5s de video negro con audio silencioso
                subprocess.run([
                    "ffmpeg", "-f", "lavfi", "-i", "color=black:s=1280x720:d=5",
                    "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                    "-t", "5", "-c:v", "libx264", "-c:a", "aac",
                    "-y", str(test_video)
                ], check=True, capture_output=True)
                
                logger.info(f"  ✓ Test video created: {test_video}")
                
                # Procesar con VideoService
                logger.info("  Processing video (this may take 10-30s)...")
                
                # Mock task data
                from models import Platform
                result = await VideoService.process_video(
                    video_path=str(test_video),
                    task_id=999999,  # fake task ID
                    target_platform=Platform.TIKTOK,
                    num_clips=1,
                )
                
                if result and "clips" in result:
                    n_clips = len(result["clips"])
                    logger.info(f"  ✓ Generated {n_clips} clip(s)")
                    
                    # Verificar primer clip
                    if n_clips > 0:
                        clip = result["clips"][0]
                        logger.info(f"  ✓ Clip duration: {clip.get('duration', 0):.1f}s")
                        logger.info(f"  ✓ Virality score: {clip.get('virality_score', 0)}")
                        
                        # Check engagement curve (Phase 8.3)
                        if "engagement_curve" in clip:
                            logger.info(f"  ✓ Engagement curve: {len(clip['engagement_curve'])} points")
                        if "retention_score" in clip:
                            logger.info(f"  ✓ Retention score: {clip['retention_score']}")
                        
                        # Verificar archivo existe
                        clip_path = Path(clip.get("path", ""))
                        if clip_path.exists():
                            logger.info(f"  ✓ Clip file exists: {clip_path.name}")
                            return True
                        else:
                            logger.error(f"  ❌ Clip file not found: {clip_path}")
                            return False
                    else:
                        logger.error("  ❌ No clips generated")
                        return False
                else:
                    logger.error("  ❌ Processing failed or returned invalid result")
                    return False
                    
            finally:
                # Cleanup
                if test_video.exists():
                    test_video.unlink()
                    
    except Exception as e:
        logger.error(f"  ❌ End-to-end test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    parser = argparse.ArgumentParser(description="ViraClip smoke test")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Quick test (imports + services only, skip E2E)",
    )
    parser.add_argument(
        "--url",
        help="YouTube URL for end-to-end test (optional)",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Skip database tests (useful in local dev without DB)",
    )
    args = parser.parse_args()
    
    print("\n" + "="*60)
    print("🧪 ViraClip Smoke Test")
    print("="*60)
    print(f"Mode: {'Quick' if args.quick else 'Full'}")
    if args.url:
        print(f"Video URL: {args.url}")
    print("="*60)
    
    results = {}
    
    # Always run these
    results["imports"] = await test_imports()
    results["services"] = await test_services()
    results["ffmpeg"] = await test_ffmpeg()
    
    # Conditional tests
    if not args.skip_db:
        results["database"] = await test_database()
        results["redis"] = await test_redis()
    
    # E2E test (skip if quick mode)
    if not args.quick:
        results["e2e"] = await test_end_to_end(video_url=args.url)
    
    # Summary
    print("\n" + "="*60)
    print("📊 Smoke Test Results")
    print("="*60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, ok in results.items():
        icon = "✅" if ok else "❌"
        print(f"  {icon} {test_name}")
    
    print(f"\nPassed: {passed}/{total}")
    print("="*60 + "\n")
    
    if passed == total:
        print("🎉 All smoke tests passed!\n")
        return 0
    else:
        print("⚠ Some tests failed. Check logs above.\n")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
