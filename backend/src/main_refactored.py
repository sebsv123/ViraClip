"""
Refactored FastAPI application with proper layered architecture.

This is the new main entry point with:
- Separated concerns (routes, services, repositories, workers)
- Async job queue with arq
- Real-time progress updates via SSE
- Thread pool for blocking operations
"""

import sys as _sys
import io as _io

# Force UTF-8 on stdout/stderr so emoji in log messages never crash on Windows cp1252
if hasattr(_sys.stdout, 'buffer'):
    _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
if hasattr(_sys.stderr, 'buffer'):
    _sys.stderr = _io.TextIOWrapper(_sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

from contextlib import asynccontextmanager
from pathlib import Path
import logging
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(_sys.stdout)],
)

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Config, get_config, set_config_override
from .database import close_db, configure_database, get_db, init_db
from .workers.job_queue import JobQueue
from .api.routes import tasks
from .api.routes.admin import router as admin_router
from .observability import (
    TRACE_HEADER,
    clear_trace_id,
    configure_logging,
    generate_trace_id,
    get_trace_id,
    set_trace_id,
)

configure_logging()

logger = logging.getLogger(__name__)
def create_app(
    *,
    config: Config | None = None,
    session_maker=None,
    queue_adapter=JobQueue,
):
    runtime_config = config or get_config()
    set_config_override(runtime_config)
    if session_maker is not None:
        configure_database(
            session_maker=session_maker,
            engine=session_maker.kw.get("bind"),
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Application lifespan: startup and shutdown events."""
        import asyncio
        logger.info("🚀 Starting ViraClip API...")
        try:
            # FIX: Ensure all required directories exist before starting
            from .utils.startup import initialize_application
            initialize_application()
            
            # GPU probe (safe — respects VIRACLIP_GPU_PROBE_ON_START flag)
            try:
                from .utils.gpu_utils import log_gpu_status as _log_gpu
                _log_gpu()
            except Exception as _gpu_e:
                logger.debug("[gpu] Startup probe skipped: %s", _gpu_e)
            
            await init_db()
            logger.info("✅ Database initialized")

            await queue_adapter.get_pool()
            logger.info("✅ Job queue initialized")

            # Kick off Ollama vision model pull in background (non-blocking)
            # Vision is optional — if Ollama isn't running, pipeline continues normally
            if runtime_config.vision_analysis_enabled:
                async def _pull_vision_model():
                    try:
                        from .services.vision_service import ensure_vision_model_pulled
                        model = runtime_config.ollama_vision_model
                        logger.info(f"🔭 Checking Ollama vision model '{model}' in background...")
                        ok = await ensure_vision_model_pulled(model)
                        if ok:
                            logger.info(f"✅ Ollama vision model '{model}' ready")
                        else:
                            logger.info(f"⚠️  Ollama vision model not available — visual scoring disabled")
                    except Exception as e:
                        logger.debug(f"Vision model pull skipped: {e}")
                asyncio.create_task(_pull_vision_model())

            # LUTService: auto-download Film-Luts on first run if no .cube files present
            try:
                from .services.lut_service import get_lut_service as _get_lut_svc
                _lut = _get_lut_svc()
                _lut_info = _lut.get_info()
                if _lut_info["cube_files_present"] == 0:
                    logger.info("[LUT] No .cube files — downloading Film-Luts repo in background...")
                    asyncio.create_task(_lut.download_luts())
                else:
                    logger.info(f"[LUT] {_lut_info['cube_files_present']} LUT presets ready in {_lut_info['lut_dir']}")
            except Exception as _lut_startup_e:
                logger.debug(f"[LUT] startup check skipped: {_lut_startup_e}")

            yield
        finally:
            logger.info("🛑 Shutting down ViraClip API...")
            await close_db()
            await queue_adapter.close_pool()
            logger.info("✅ Cleanup complete")

    app = FastAPI(
        title="ViraClip API",
        description="Refactored Python backend for ViraClip with async job processing",
        version="0.2.0",
        lifespan=lifespan,
    )
    app.state.queue_adapter = queue_adapter
    app.state.config = runtime_config

    app.add_middleware(
        CORSMiddleware,
        allow_origins=runtime_config.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=[
            "Content-Type",
            "Authorization",
            "x-viraclip-user-id",
            "x-viraclip-ts",
            "x-viraclip-signature",
            "x-trace-id",
            "user_id",
        ],
        expose_headers=["x-trace-id"],
    )

    @app.middleware("http")
    async def trace_and_request_logging_middleware(request: Request, call_next):
        trace_id = request.headers.get(TRACE_HEADER) or generate_trace_id()
        set_trace_id(trace_id)
        started_at = time.perf_counter()

        logger.info("Incoming request %s %s", request.method, request.url.path)

        try:
            response = await call_next(request)
        except Exception:
            logger.exception("Unhandled exception while processing request")
            clear_trace_id()
            raise

        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        response.headers[TRACE_HEADER] = trace_id
        logger.info(
            "Completed request %s %s with status %s in %sms",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        clear_trace_id()
        return response

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_: Request, exc: HTTPException):
        trace_id = get_trace_id()
        logger.warning(
            "HTTP exception: status=%s detail=%s", exc.status_code, exc.detail
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "trace_id": trace_id},
            headers={TRACE_HEADER: trace_id},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_: Request, exc: RequestValidationError):
        trace_id = get_trace_id()
        logger.warning("Validation error: %s", exc.errors())
        return JSONResponse(
            status_code=422,
            content={"detail": exc.errors(), "trace_id": trace_id},
            headers={TRACE_HEADER: trace_id},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_: Request, exc: Exception):
        trace_id = get_trace_id()
        logger.error("Unhandled server error: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "An internal server error occurred. Contact support with the trace ID.",
                "trace_id": trace_id,
            },
            headers={TRACE_HEADER: trace_id},
        )

    clips_dir = Path(runtime_config.temp_dir) / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/clips", StaticFiles(directory=str(clips_dir)), name="clips")

    app.include_router(tasks.router)
    app.include_router(admin_router)

    # Core imports (critical — must succeed)
    from .api.middleware.monitoring import router as metrics_router, MetricsMiddleware
    from .api.middleware.rate_limit import RateLimitHeadersMiddleware
    from .api.middleware.compression import CompressionMiddleware

    # Safe include helper: imports a route module and registers it, logging errors
    # instead of crashing on missing dependencies / services.
    def _safe_include(module_path: str, attr: str = "router", note: str = "") -> bool:
        try:
            import importlib
            mod = importlib.import_module(module_path, package=__package__)
            router_obj = getattr(mod, attr)
            app.include_router(router_obj)
            return True
        except Exception as _sie:
            logger.warning("Route %s skipped: %s%s", module_path, _sie, f" ({note})" if note else "")
            return False

    # Routes registered via _safe_include — each one may fail independently
    _routes = [
        ".api.routes.media",
        ".api.routes.feedback",
        ".api.routes.billing",
        ".api.routes.social",
        ".api.routes.clips",
        ".api.routes.gpu_services",
        ".api.routes.health",
        ".api.routes.health_gpu",
        ".api.routes.progress",
        ".api.routes.task_control",
    ]
    for _r in _routes:
        _safe_include(_r)
    app.include_router(metrics_router)

    # All optional routes — each wrapped in try/except via _safe_include
    _optional_routes = [
        ".api.routes.automation",
        ".api.routes.extras",
        ".api.routes.advanced_ml",
        ".api.routes.llm_ops",
        ".api.routes.creative",
        ".api.routes.analytics",
        ".api.routes.timeline",
        ".api.routes.ai_metrics",
        ".api.routes.ab_testing",
        ".api.routes.avatar",
        ".api.routes.translation",
        ".api.routes.campaigns",
        ".api.routes.competitors",
        ".api.routes.scheduler",
        ".api.routes.calendar",
        ".api.routes.search",
        ".api.routes.trending",
        ".api.routes.gamification",
        ".api.routes.notifications",
        ".api.routes.audio",
        ".api.routes.collaboration",
        ".api.routes.moderation",
        ".api.routes.reports",
        ".api.routes.thumbnails",
        ".api.routes.batch",
        ".api.routes.audit",
        ".api.routes.nft",
        ".api.routes.advanced_analytics",
        ".api.routes.virality_ml",
        ".api.routes.feature_flags",
        ".api.routes.genai",
        ".api.routes.livestream",
        ".api.routes.multilanguage",
        ".api.routes.forensic",
        ".api.routes.multi_angle",
        ".api.routes.engagement",
        ".api.routes.templates",
        ".api.routes.audio_rec",
        ".api.routes.computer_vision",
        ".api.routes.competitor_intel",
        ".api.routes.recommendations",
        ".api.routes.voice_synthesis",
        ".api.routes.platform_presets",
        ".api.routes.webhooks",
        ".api.routes.version_control",
        ".api.routes.backup",
        ".api.routes.workflows",
        ".api.routes.dashboard",
        ".api.routes.sentiment",
        ".api.routes.social_media",
        ".api.routes.compression",
        ".api.routes.retention",
        ".api.routes.cdn",
        ".api.routes.ipfs",
        ".api.routes.productivity",
        ".api.routes.auto_editor",
        ".api.routes.integrations",
        ".api.routes.cloud_storage",
        ".api.routes.edge_cdn",
        ".api.routes.email_reports",
        ".api.routes.bulk_ops",
        ".api.routes.cost_optimization",
        ".api.routes.observability",
        ".api.routes.distributed_cache",
        ".api.routes.ai_inference",
        ".api.routes.data_migration",
        ".api.routes.scene_detection",
        ".api.routes.vector_search",
        ".api.routes.vfx",
        ".api.routes.video_polish",
        ".api.routes.onnx",
        ".api.routes.kubernetes",
        ".api.routes.image_gen",
        ".api.routes.federated_learning",
        ".api.routes.external_analytics",
        ".api.routes.langchain_ops",
        ".api.routes.interpreter",
        ".api.routes.captions",
        ".api.routes.lut",
        ".api.routes.beat_sync",
        ".api.routes.creator_profile",
        ".api.routes.ab_feedback",
        ".api.routes.trending_audio",
        ".api.routes.thumbnail_text",
        ".api.routes.subtitle_qa",
        ".api.routes.smart_reframe",
        ".api.routes.language_detect",
        ".api.routes.narrative_arc",
        ".api.routes.brand_overlay",
        ".api.routes.clip_health",
        ".api.routes.tiktok_templates",
        ".api.routes.jump_cut",
        ".api.routes.audio_denoise",
        ".api.routes.performance_webhook",
        ".api.routes.trend_intelligence",
        ".api.routes.niche_virality",
        ".api.routes.ingest",
        ".api.routes.autopilot",
        ".api.routes.export",
        ".api.routes.clip_search",
        ".api.routes.scheduled_publish",
        ".api.routes.user_quota",
        ".api.routes.clip_bulk",
        ".api.routes.health_enhanced",
        ".api.routes.task_retry",
        ".api.routes.usage_analytics",
        ".api.routes.clip_moderation",
        ".api.routes.playlist_ab_webhook",
        ".api.routes.clip_feedback_score",
        ".api.routes.clip_chapters_captions",
        ".api.routes.watermark_search_share",
        ".api.routes.collections_summary_compare",
        ".api.routes.flagging_compression_analytics",
    ]
    _loaded = 0
    _skipped = 0
    for _r in _optional_routes:
        if _safe_include(_r):
            _loaded += 1
        else:
            _skipped += 1
    logger.info("Optional routes: %d loaded, %d skipped", _loaded, _skipped)

    # YouTube Feedback Service — close virality prediction loop with real performance data
    try:
        from fastapi import APIRouter as _YTFB_AR
        _yt_router = _YTFB_AR(prefix="/feedback", tags=["feedback"])

        @_yt_router.get("/youtube/{video_id}")
        async def get_youtube_feedback(video_id: str):
            from .services.youtube_feedback_service import YouTubeFeedbackService
            svc = YouTubeFeedbackService()
            metrics = await svc.get_video_metrics(video_id)
            return metrics.__dict__ if metrics else {"error": "No metrics — check YOUTUBE_DATA_API_KEY"}

        @_yt_router.post("/youtube/record")
        async def record_youtube_feedback(payload: dict):
            from .services.youtube_feedback_service import YouTubeFeedbackService, ViralityPrediction
            svc = YouTubeFeedbackService()
            video_id = payload["video_id"]
            prediction = ViralityPrediction(**payload.get("prediction", {}))
            performance = await svc.get_video_metrics(video_id)
            if not performance:
                return {"error": "Could not fetch YouTube metrics"}
            result = svc.compare_prediction_vs_reality(prediction, performance)
            return result.__dict__ if result else {"error": "Feedback not recorded"}

        app.include_router(_yt_router)
        logger.info("✓ YouTube Feedback router registered at /feedback/youtube")
    except Exception as _ytfb_e:
        logger.warning(f"YouTube Feedback router skipped: {_ytfb_e}")

    # Add middleware
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(RateLimitHeadersMiddleware)
    app.add_middleware(CompressionMiddleware)  # HTTP response compression

    @app.get("/")
    def read_root():
        """Root endpoint."""
        return {
            "name": "ViraClip API",
            "version": "0.2.0",
            "status": "running",
            "docs": "/docs",
            "architecture": "refactored with job queue",
        }

    @app.get("/health")
    async def health_check():
        """Endpoint de diagnóstico completo — verifica todos los servicios."""
        import shutil
        import httpx
        import os
        from sqlalchemy import text
        
        status = {}
        
        # Redis
        try:
            pool = await app.state.queue_adapter.get_pool()
            await pool.ping()
            status["redis"] = "✅ OK"
        except Exception as e:
            status["redis"] = f"❌ {str(e)}"
        
        # PostgreSQL
        try:
            async for db in get_db():
                await db.execute(text("SELECT 1"))
                status["postgres"] = "✅ OK"
                break
        except Exception as e:
            status["postgres"] = f"❌ {str(e)}"
        
        # Ollama + Phi-3 / Qwen
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get("http://ollama:11434/api/tags")
                models = [m["name"] for m in r.json().get("models", [])]
                phi3_ok = any("phi3" in m or "qwen" in m for m in models)
                status["ollama"] = f"✅ OK - modelos: {models}" if phi3_ok else f"⚠️ Sin modelo visión - modelos: {models}"
        except Exception as e:
            status["ollama"] = f"❌ {str(e)}"
        
        # FFmpeg
        ffmpeg_path = shutil.which("ffmpeg")
        status["ffmpeg"] = f"✅ {ffmpeg_path}" if ffmpeg_path else "❌ No encontrado"
        
        # Módulos Python críticos
        modules = ["librosa", "sentence_transformers", "mediapipe", "moviepy", "faster_whisper"]
        for mod in modules:
            try:
                __import__(mod)
                status[f"module_{mod}"] = "✅"
            except ImportError:
                status[f"module_{mod}"] = "❌ No instalado"
        
        # Carpetas críticas
        for folder in ["/app/uploads", "/app/clips", "/app/assets/sounds"]:
            exists = os.path.isdir(folder)
            status[f"dir_{folder.split('/')[-1]}"] = "✅" if exists else "❌ No existe"
        
        all_ok = all("✅" in v for v in status.values())
        return {
            "status": "healthy" if all_ok else "degraded",
            "checks": status
        }

    @app.get("/health/db")
    async def check_database_health(db: AsyncSession = Depends(get_db)):
        """Check database connectivity."""
        from sqlalchemy import text

        try:
            await db.execute(text("SELECT 1"))
            return {"status": "healthy", "database": "connected"}
        except Exception as e:
            return {
                "status": "unhealthy",
                "database": "disconnected",
                "error": str(e),
            }

    @app.get("/health/redis")
    async def check_redis_health():
        """Check Redis connectivity."""
        try:
            pool = await app.state.queue_adapter.get_pool()
            await pool.ping()
            return {"status": "healthy", "redis": "connected"}
        except Exception as e:
            return {
                "status": "unhealthy",
                "redis": "disconnected",
                "error": str(e),
            }

    return app


app = create_app()
