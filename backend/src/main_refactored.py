"""
Refactored FastAPI application with proper layered architecture.

This is the new main entry point with:
- Separated concerns (routes, services, repositories, workers)
- Async job queue with arq
- Real-time progress updates via SSE
- Thread pool for blocking operations
"""

from contextlib import asynccontextmanager
from pathlib import Path
import logging
import time

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

    from .api.routes.media import router as media_router
    from .api.routes.feedback import router as feedback_router
    from .api.routes.billing import router as billing_router
    from .api.routes.social import router as social_router
    from .api.routes.clips import router as clips_router
    from .api.routes.gpu_services import router as gpu_router
    from .api.routes.health import router as health_router
    from .api.routes.health_gpu import router as health_gpu_router
    from .api.routes.progress import router as progress_router  # SSE streaming
    from .api.routes.task_control import router as task_control_router  # Background tasks
    from .api.middleware.monitoring import router as metrics_router, MetricsMiddleware
    from .api.middleware.rate_limit import RateLimitHeadersMiddleware
    from .api.middleware.compression import CompressionMiddleware
    from .api.routes.automation import router as automation_router
    from .api.routes.extras import router as extras_router
    from .api.routes.advanced_ml import router as advanced_ml_router
    from .api.routes.llm_ops import router as llm_ops_router
    from .api.routes.creative import router as creative_router
    from .api.routes.analytics import router as analytics_router
    from .api.routes.timeline import router as timeline_router
    from .api.routes.ai_metrics import router as ai_metrics_router
    from .api.routes.ab_testing import router as ab_testing_router
    from .api.routes.avatar import router as avatar_router
    from .api.routes.translation import router as translation_router
    from .api.routes.campaigns import router as campaigns_router
    from .api.routes.competitors import router as competitors_router
    from .api.routes.scheduler import router as scheduler_router
    from .api.routes.calendar import router as calendar_router
    from .api.routes.search import router as search_router
    from .api.routes.trending import router as trending_router
    from .api.routes.gamification import router as gamification_router
    from .api.routes.notifications import router as notifications_router
    from .api.routes.audio import router as audio_router
    from .api.routes.collaboration import router as collaboration_router
    from .api.routes.moderation import router as moderation_router
    from .api.routes.reports import router as reports_router
    from .api.routes.thumbnails import router as thumbnails_router
    from .api.routes.batch import router as batch_router
    from .api.routes.audit import router as audit_router

    app.include_router(media_router)
    app.include_router(feedback_router)
    app.include_router(billing_router)
    app.include_router(social_router)
    app.include_router(clips_router)
    app.include_router(gpu_router)
    app.include_router(health_router)
    app.include_router(health_gpu_router)
    app.include_router(progress_router)
    app.include_router(task_control_router)
    app.include_router(metrics_router)
    app.include_router(automation_router)
    app.include_router(extras_router)
    app.include_router(advanced_ml_router)
    app.include_router(llm_ops_router)
    app.include_router(creative_router)
    app.include_router(analytics_router)    # NEW: Analytics dashboard
    app.include_router(timeline_router)     # NEW: Timeline API & metrics
    app.include_router(ai_metrics_router)   # NEW: AI quality metrics & anomaly detection
    app.include_router(ab_testing_router)   # NEW: A/B testing for clip variants
    app.include_router(avatar_router)       # NEW: NeRF avatars (ERNeRF/AvatarCraft/AnimNeRF/UV-Volumes)
    app.include_router(translation_router)  # NEW: Auto-translation (multi-language clip localization)
    app.include_router(campaigns_router)    # NEW: Campaign A/B testing + performance tracking
    app.include_router(competitors_router)  # NEW: Competitor intelligence & trend analysis
    app.include_router(scheduler_router)    # NEW: Auto-scheduler (recurring jobs + trend triggers)
    app.include_router(calendar_router)     # NEW: Content calendar & optimal scheduling
    app.include_router(search_router)       # NEW: Full-text clip search with filters + facets
    app.include_router(trending_router)     # NEW: Trending topics + content recommendations
    app.include_router(gamification_router) # NEW: Points, levels, achievements, leaderboard
    app.include_router(notifications_router)# NEW: Smart notifications (ML-optimised delivery)
    app.include_router(audio_router)        # NEW: Audio recommendations + beat-matched cuts
    app.include_router(collaboration_router)# NEW: Multi-user collaboration + comments
    app.include_router(moderation_router)   # NEW: Content moderation & safety filters
    app.include_router(reports_router)      # NEW: Automated email reports & subscriptions
    app.include_router(thumbnails_router)   # NEW: AI thumbnail generation + frame analysis
    app.include_router(batch_router)        # NEW: Batch video processing jobs
    app.include_router(audit_router)        # NEW: Compliance audit log (query/export/anomaly)

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
