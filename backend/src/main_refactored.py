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
            # FIX: Ensure all required directories exist before starting
            from .utils.startup import initialize_application
            initialize_application()
            
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
    from .api.routes.nft import router as nft_router
    from .api.routes.advanced_analytics import router as advanced_analytics_router
    from .api.routes.virality_ml import router as virality_ml_router
    from .api.routes.feature_flags import router as feature_flags_router
    from .api.routes.genai import router as genai_router
    from .api.routes.livestream import router as livestream_router
    from .api.routes.multilanguage import router as multilanguage_router
    from .api.routes.forensic import router as forensic_router
    from .api.routes.multi_angle import router as multi_angle_router
    from .api.routes.engagement import router as engagement_router
    from .api.routes.templates import router as templates_router
    from .api.routes.audio_rec import router as audio_rec_router
    from .api.routes.computer_vision import router as computer_vision_router
    from .api.routes.competitor_intel import router as competitor_intel_router
    from .api.routes.recommendations import router as recommendations_router
    from .api.routes.voice_synthesis import router as voice_synthesis_router
    from .api.routes.platform_presets import router as platform_presets_router
    from .api.routes.webhooks import router as webhooks_router
    from .api.routes.version_control import router as version_control_router
    from .api.routes.backup import router as backup_router
    from .api.routes.workflows import router as workflows_router
    from .api.routes.dashboard import router as dashboard_router
    from .api.routes.sentiment import router as sentiment_router
    from .api.routes.social_media import router as social_media_router
    from .api.routes.compression import router as compression_router
    from .api.routes.retention import router as retention_router
    from .api.routes.cdn import router as cdn_router
    from .api.routes.ipfs import router as ipfs_router
    from .api.routes.productivity import router as productivity_router
    from .api.routes.auto_editor import router as auto_editor_router
    from .api.routes.integrations import router as integrations_router
    from .api.routes.cloud_storage import router as cloud_storage_router
    from .api.routes.edge_cdn import router as edge_cdn_router
    from .api.routes.email_reports import router as email_reports_router
    from .api.routes.bulk_ops import router as bulk_ops_router
    from .api.routes.cost_optimization import router as cost_router
    from .api.routes.observability import router as observability_router
    from .api.routes.distributed_cache import router as cache_router
    from .api.routes.ai_inference import router as ai_inference_router
    from .api.routes.data_migration import router as migration_router
    from .api.routes.scene_detection import router as scene_detection_router
    from .api.routes.vector_search import router as vector_search_router
    from .api.routes.vfx import router as vfx_router
    from .api.routes.video_polish import router as video_polish_router
    from .api.routes.onnx import router as onnx_router
    from .api.routes.kubernetes import router as kubernetes_router
    from .api.routes.image_gen import router as image_gen_router
    from .api.routes.federated_learning import router as federated_learning_router
    from .api.routes.external_analytics import router as external_analytics_router
    from .api.routes.langchain_ops import router as langchain_ops_router
    from .api.routes.interpreter import router as interpreter_router
    from .api.routes.captions import router as captions_router
    from .api.routes.lut import router as lut_router
    from .api.routes.beat_sync import router as beat_sync_router
    from .api.routes.creator_profile import router as creator_profile_router
    from .api.routes.ab_feedback import router as ab_feedback_router
    from .api.routes.trending_audio import router as trending_audio_router
    from .api.routes.thumbnail_text import router as thumbnail_text_router
    from .api.routes.subtitle_qa import router as subtitle_qa_router
    from .api.routes.smart_reframe import router as smart_reframe_router
    from .api.routes.language_detect import router as language_detect_router
    from .api.routes.narrative_arc import router as narrative_arc_router
    from .api.routes.brand_overlay import router as brand_overlay_router
    from .api.routes.clip_health import router as clip_health_router
    from .api.routes.tiktok_templates import router as tiktok_templates_router
    from .api.routes.jump_cut import router as jump_cut_router
    from .api.routes.audio_denoise import router as audio_denoise_router
    from .api.routes.performance_webhook import router as performance_webhook_router
    from .api.routes.trend_intelligence import router as trend_intelligence_router
    from .api.routes.niche_virality import router as niche_virality_router
    from .api.routes.ingest import router as ingest_router
    from .api.routes.autopilot import router as autopilot_router
    from .api.routes.export import router as export_router
    from .api.routes.clip_search import router as clip_search_router
    from .api.routes.scheduled_publish import router as scheduled_publish_router
    from .api.routes.user_quota import router as user_quota_router
    from .api.routes.clip_bulk import router as clip_bulk_router
    from .api.routes.health_enhanced import router as health_enhanced_router
    from .api.routes.task_retry import router as task_retry_router
    from .api.routes.usage_analytics import router as usage_analytics_router
    from .api.routes.clip_moderation import router as clip_moderation_router
    from .api.routes.playlist_ab_webhook import router as playlist_ab_webhook_router
    from .api.routes.clip_feedback_score import router as clip_feedback_score_router
    from .api.routes.clip_chapters_captions import router as clip_chapters_captions_router
    from .api.routes.watermark_search_share import router as watermark_search_share_router
    from .api.routes.collections_summary_compare import router as collections_summary_compare_router
    from .api.routes.flagging_compression_analytics import router as flagging_compression_analytics_router

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
    app.include_router(nft_router)          # NEW: Blockchain NFT minting + ownership + marketplace
    app.include_router(advanced_analytics_router) # NEW: Clip/user/system analytics + reports
    app.include_router(virality_ml_router)  # NEW: ML virality prediction + online training
    app.include_router(feature_flags_router)# NEW: Feature flags (gradual rollout + per-user)
    app.include_router(genai_router)        # NEW: Generative AI thumbnails/backgrounds/text-effects
    app.include_router(livestream_router)   # NEW: Live stream monitoring + real-time clip extraction
    app.include_router(multilanguage_router)# NEW: Language detection + subtitle/font config (15 langs)
    app.include_router(forensic_router)     # NEW: Deepfake detection + video authenticity forensics
    app.include_router(multi_angle_router)  # NEW: Multi-angle sync + camera switching plans
    app.include_router(engagement_router)   # NEW: LSTM/CNN engagement curve prediction + training
    app.include_router(templates_router)    # NEW: Dynamic niche templates (10 niches, style + timing)
    app.include_router(audio_rec_router)    # NEW: AI audio/music/SFX recommendations + beat-matched cuts
    app.include_router(computer_vision_router) # NEW: Frame visual analysis, faces, colors, engagement
    app.include_router(competitor_intel_router)# NEW: Competitor monitoring, trend insights, comparison
    app.include_router(recommendations_router) # NEW: Personalised content recs + virality tips
    app.include_router(voice_synthesis_router) # NEW: TTS synthesis, voice cloning, video narration
    app.include_router(platform_presets_router)# NEW: Platform export presets + FFmpeg settings (7 platforms)
    app.include_router(webhooks_router)        # NEW: Webhook endpoints + HMAC delivery + retry
    app.include_router(version_control_router) # NEW: Git-like clip versioning + branches + diffs
    app.include_router(backup_router)          # NEW: Backup/restore + disaster recovery
    app.include_router(workflows_router)       # NEW: Visual workflow automation pipelines + templates
    app.include_router(dashboard_router)       # NEW: Real-time metrics dashboard + history
    app.include_router(sentiment_router)       # NEW: Transcript sentiment + emotion + virality correlation
    app.include_router(social_media_router)    # NEW: Social media OAuth + publish + schedule (6 platforms)
    app.include_router(compression_router)     # NEW: Video compression presets + quality analysis
    app.include_router(retention_router)       # NEW: Data retention policies + GDPR cleanup
    app.include_router(cdn_router)             # NEW: CDN upload + signed URLs + cache invalidation
    app.include_router(ipfs_router)            # NEW: IPFS decentralized storage + gateway management
    app.include_router(productivity_router)    # NEW: Slack/Notion/Trello automation rules + event triggers
    app.include_router(auto_editor_router)     # NEW: AI auto-edit plan + silence removal + text pops
    app.include_router(integrations_router)    # NEW: Zapier/Make/n8n/IFTTT webhook integrations
    app.include_router(cloud_storage_router)   # NEW: Multi-cloud upload/download/presign (S3/GCS/Azure)
    app.include_router(edge_cdn_router)        # NEW: Edge CDN processing + global distribution
    app.include_router(email_reports_router)   # NEW: Scheduled email reports + subscriptions
    app.include_router(bulk_ops_router)        # NEW: Bulk video processing jobs management
    app.include_router(cost_router)            # NEW: Cloud cost tracking + optimization analysis
    app.include_router(observability_router)   # NEW: Distributed tracing + performance monitoring
    app.include_router(cache_router)           # NEW: Multi-layer distributed cache management
    app.include_router(ai_inference_router)    # NEW: AI model optimization (TensorRT/ONNX) + inference
    app.include_router(migration_router)       # NEW: GDPR data export/import jobs
    app.include_router(scene_detection_router) # NEW: Scene detection + cut points + keyframe extraction
    app.include_router(vector_search_router)   # NEW: Milvus multimodal vector search (text/visual/hybrid)
    app.include_router(vfx_router)             # NEW: VFX generative style, Kling swap, viral loops, branding
    app.include_router(video_polish_router)    # NEW: Face centering, eye contact, pattern interrupts
    app.include_router(onnx_router)            # NEW: ONNX fast inference for virality + engagement
    app.include_router(kubernetes_router)      # NEW: K8s auto-scaling metrics + worker management
    app.include_router(image_gen_router)       # NEW: DALL-E / SDXL image generation
    app.include_router(federated_learning_router) # NEW: Federated learning rounds + client management
    app.include_router(external_analytics_router) # NEW: GA4/Mixpanel/Amplitude/Segment/PostHog integration
    app.include_router(langchain_ops_router)       # NEW: LangChain virality/metadata/hook/chat chains
    app.include_router(interpreter_router)         # NEW: Natural language task execution (Open Interpreter)
    app.include_router(captions_router)            # NEW: ASS karaoke + highlight caption burn-in
    app.include_router(lut_router)                 # NEW: lut3d cinematic color grading
    app.include_router(beat_sync_router)           # NEW: BPM detection + beat-synced BGM mixing
    app.include_router(creator_profile_router)     # NEW: Per-creator personalization profiles
    app.include_router(ab_feedback_router)         # NEW: Closed A/B feedback loop (analytics import)
    app.include_router(trending_audio_router)      # NEW: Trending sound matching (TikTok/Spotify)
    app.include_router(thumbnail_text_router)      # NEW: Hook-text thumbnail overlays (Pillow)
    app.include_router(subtitle_qa_router)         # NEW: Subtitle QA guard (speed/profanity/emoji)
    app.include_router(smart_reframe_router)       # NEW: Smart reframe 1:1 + 16:9 variants
    app.include_router(language_detect_router)     # NEW: Language detection + locale LLM prompts
    app.include_router(narrative_arc_router)       # NEW: Multi-clip series/best-of/teaser arc
    app.include_router(brand_overlay_router)       # NEW: Brand/watermark overlay (text + image)
    app.include_router(clip_health_router)         # NEW: Actionable clip health report
    app.include_router(tiktok_templates_router)    # NEW: Duet/stitch/green-screen templates
    app.include_router(jump_cut_router)            # NEW: Jump-cut engine (silence + filler removal)
    app.include_router(audio_denoise_router)       # NEW: Audio denoiser (noise reduction + loudnorm)
    app.include_router(performance_webhook_router) # NEW: Performance feedback webhooks + auto-flagging
    app.include_router(trend_intelligence_router)  # NEW: Real-time hook phrases + caption patterns + timing
    app.include_router(niche_virality_router)      # NEW: Per-niche virality scoring + auto-retraining
    app.include_router(ingest_router)              # NEW: Multi-source video ingestion (yt-dlp)
    app.include_router(autopilot_router)           # NEW: Full end-to-end automation pipeline
    app.include_router(export_router)              # NEW: Batch ZIP export
    app.include_router(clip_search_router)         # NEW: Full-text + score clip search
    app.include_router(scheduled_publish_router)   # NEW: Scheduled social publishing
    app.include_router(user_quota_router)           # NEW: User quota + dedup check
    app.include_router(clip_bulk_router)            # NEW: Clip tags + bulk actions
    app.include_router(health_enhanced_router)      # NEW: Detailed health + readiness/liveness probes
    app.include_router(task_retry_router)           # NEW: Task retry + retry-info
    app.include_router(usage_analytics_router)      # NEW: Per-user usage analytics + clip thumbnails
    app.include_router(clip_moderation_router)      # NEW: Clip annotations + content moderation + in-app notifications
    app.include_router(playlist_ab_webhook_router)  # NEW: Playlists + A/B tests + webhook event log
    app.include_router(clip_feedback_score_router)   # NEW: Feedback, score overrides + export history
    app.include_router(clip_chapters_captions_router) # NEW: Clip chapters + caption variants + user activity log
    app.include_router(watermark_search_share_router)  # NEW: Watermark config + transcript search + share links
    app.include_router(collections_summary_compare_router)  # NEW: Clip collections + AI summary + clip comparison
    app.include_router(flagging_compression_analytics_router)  # NEW: Flagging + compression + analytics aggregation

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
