from dotenv import load_dotenv
from typing import Optional
import os
import logging

load_dotenv()

_config_override = None
_config_singleton = None
logger = logging.getLogger(__name__)


class Config:
    def __init__(self):
        self.openai_api_key = self._get_optional_env("OPENAI_API_KEY")
        self.anthropic_api_key = self._get_optional_env("ANTHROPIC_API_KEY")
        self.google_api_key = self._get_optional_env("GOOGLE_API_KEY")
        self.groq_api_key = self._get_optional_env("GROQ_API_KEY")
        self.deepseek_api_key = self._get_optional_env("DEEPSEEK_API_KEY")
        self.youtube_data_api_key = self._get_optional_env("YOUTUBE_DATA_API_KEY")
        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
        self.ollama_api_key = self._get_optional_env("OLLAMA_API_KEY")
        # Vision model for local multimodal analysis (Qwen3-VL via Ollama)
        # Options: qwen3-vl:8b (best), qwen3-vl:4b (lighter), moondream:v2 (CPU fallback)
        self.ollama_vision_model = os.getenv("OLLAMA_VISION_MODEL", "qwen3-vl:8b")
        self.vision_analysis_enabled = self._get_bool_env("VISION_ANALYSIS_ENABLED", True)

        self.whisper_model = os.getenv("WHISPER_MODEL_SIZE", "medium")
        self.llm = self._get_optional_env("LLM") or self._infer_default_llm()
        self.viral_scoring_llm = os.getenv("VIRAL_SCORING_LLM") or self.llm
        self.llm_fallback = self._get_optional_env("LLM_FALLBACK") or ""
        self.hf_token = self._get_optional_env("HF_TOKEN")
        self.assembly_ai_api_key = os.getenv("ASSEMBLY_AI_API_KEY")
        self.pexels_api_key = os.getenv("PEXELS_API_KEY")
        self.apify_api_token = self._get_optional_env("APIFY_API_TOKEN")
        self.youtube_metadata_provider = self._normalize_youtube_metadata_provider(
            os.getenv("YOUTUBE_METADATA_PROVIDER", "youtube_data_api")
        )
        self.apify_youtube_default_quality = self._normalize_apify_quality(
            os.getenv("APIFY_YOUTUBE_DEFAULT_QUALITY", "1080")
        )

        self.max_video_duration = int(os.getenv("MAX_VIDEO_DURATION", "5400"))
        self.output_dir = os.getenv("OUTPUT_DIR", "/tmp/viraclip/outputs")

        self.max_clips = int(os.getenv("MAX_CLIPS", "10"))
        self.clip_duration = int(os.getenv("CLIP_DURATION", "30"))  # seconds

        self.temp_dir = os.getenv("TEMP_DIR", "/tmp/viraclip/temp")

        # Database
        self.database_url = os.getenv(
            "DATABASE_URL",
            "postgresql+asyncpg://viraclip:viraclip_password@postgres:5432/viraclip",
        )

        # Redis settings for ARQ task queue
        self.redis_host: str = os.getenv("REDIS_HOST", "redis")
        self.redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
        self.redis_password: Optional[str] = os.getenv("REDIS_PASSWORD")
        
        # Redis Sentinel for high availability (optional)
        self.redis_sentinel_hosts: Optional[str] = os.getenv("REDIS_SENTINEL_HOSTS")  # "host1:port1,host2:port2"
        self.redis_sentinel_master_name: str = os.getenv("REDIS_SENTINEL_MASTER", "mymaster")

        # Fail-safe: queued tasks should not stay queued forever
        self.queued_task_timeout_seconds = int(
            os.getenv("QUEUED_TASK_TIMEOUT_SECONDS", "180")
        )

        self.self_host = self._get_bool_env("SELF_HOST", True)
        self.monetization_enabled = not self.self_host
        self.backend_auth_secret = self._get_optional_env("BACKEND_AUTH_SECRET")
        self.auth_signature_ttl_seconds = int(
            os.getenv("AUTH_SIGNATURE_TTL_SECONDS", "300")
        )
        self.free_plan_task_limit = int(os.getenv("FREE_PLAN_TASK_LIMIT", "10"))
        self.pro_plan_task_limit = int(os.getenv("PRO_PLAN_TASK_LIMIT", "0"))
        self.cors_origins = self._get_csv_env(
            "CORS_ORIGINS",
            [
                "http://localhost:3000",
                "http://sp.localhost:3000",
            ],
        )
        self.resend_api_key = self._get_optional_env("RESEND_API_KEY")
        self.resend_from_email = os.getenv(
            "RESEND_FROM_EMAIL", "ViraClip <onboarding@resend.dev>"
        )
        self.app_base_url = (
            self._get_optional_env("NEXT_PUBLIC_APP_URL") or "http://localhost:3000"
        ).rstrip("/")
        self.discord_feedback_webhook_url = self._get_optional_env("DISCORD_FEEDBACK_WEBHOOK_URL")
        self.discord_sales_webhook_url = self._get_optional_env("DISCORD_SALES_WEBHOOK_URL")
        self.default_processing_mode = os.getenv("DEFAULT_PROCESSING_MODE", "fast")
        self.fast_mode_max_clips = int(os.getenv("FAST_MODE_MAX_CLIPS", "6"))
        self.max_elite_clips = int(os.getenv("MAX_ELITE_CLIPS", "6"))
        self.fast_mode_transcript_model = os.getenv(
            "FAST_MODE_TRANSCRIPT_MODEL", "nano"
        )
        
        # Render concurrency: auto-detect based on GPU, or manual override
        # auto = detect GPU and use optimal value (2-4)
        # 2/3/4/6/8 = manual override
        self.render_concurrency = os.getenv("RENDER_CONCURRENCY", "auto")
        self.pixabay_api_key = os.getenv("PIXABAY_API_KEY", "")
        self.pexels_api_key = os.getenv("PEXELS_API_KEY", "")
        self.coverr_api_key = os.getenv("COVERR_API_KEY", "")
        self.replicate_api_token = os.getenv("REPLICATE_API_TOKEN", "")
        self.freesound_api_key = os.getenv("FREESOUND_API_KEY", "")
        self.freesound_auto_match = self._get_bool_env("FREESOUND_AUTO_MATCH", True)
        self.freesound_sfx_enabled = self._get_bool_env("FREESOUND_SFX_ENABLED", True)
        self.broll_enabled = self._get_bool_env("BROLL_ENABLED", False)
        self.sam2_enabled = self._get_bool_env("SAM2_ENABLED", False)

        # Rust sidecar agent
        self.rust_agent_url = os.getenv("RUST_AGENT_URL", "http://rust-agent:8001")
        self.rust_agent_enabled = self._get_bool_env("RUST_AGENT_ENABLED", False)

        # LLM optimization & dataset collection
        self.dataset_dir = os.getenv("DATASET_DIR", "/app/datasets")
        self.llm_routing_enabled = self._get_bool_env("LLM_ROUTING_ENABLED", False)
        self.dspy_optimized_prompt_path = os.getenv(
            "DSPY_OPTIMIZED_PROMPT_PATH", "/app/datasets/dspy_optimized_prompt.txt"
        )

        # ============================================================================
        # FEATURE FLAGS — Integration Module Toggles
        # All new integrations are OFF by default (opt-in via env).
        # See backend/.env.example for recommended values per environment.
        # ============================================================================

        # Legacy / admin / feedback
        self.admin_enabled = self._get_bool_env("ADMIN_ENABLED", False)
        self.feedback_enabled = self._get_bool_env("FEEDBACK_ENABLED", False)
        self.notifications_enabled = self._get_bool_env("NOTIFICATIONS_ENABLED", False)
        self.music_ducking_enabled = self._get_bool_env("MUSIC_DUCKING_ENABLED", True)

        # ── AI B-Roll Recommender ──────────────────────────────────────────────
        # LLM-powered B-roll keyword extraction from transcript segments.
        # Fallback: uses simple TF-IDF keyword extraction (no LLM call).
        self.ai_broll_enabled = self._get_bool_env("AI_BROLL_ENABLED", False)

        # ── Short Video Maker Pexels Integration ───────────────────────────────
        # Port of short-video-maker's Pexels client for B-roll fetching.
        # Fallback: uses the existing PexelsService (pexels_client.py) directly.
        self.short_video_maker_pexels_enabled = self._get_bool_env("SHORT_VIDEO_MAKER_PEXELS_ENABLED", False)

        # ── Background Music Service ───────────────────────────────────────────
        # Mood-based background music selection from local library.
        # Fallback: no background music (pipeline continues silently).
        self.background_music_enabled = self._get_bool_env("BACKGROUND_MUSIC_ENABLED", False)

        # ── AI Clips Maker ─────────────────────────────────────────────────────
        # External AI-driven clip segmentation (ai-clips-maker integration).
        # Fallback: uses internal viral_gate segmentation only.
        self.ai_clips_maker_enabled = self._get_bool_env("AI_CLIPS_MAKER_ENABLED", False)

        # ── ClipsAI Integration ────────────────────────────────────────────────
        # Third-party ClipsAI service for automated clip generation.
        # Fallback: skips ClipsAI, uses native pipeline.
        self.clipsai_enabled = self._get_bool_env("CLIPSAI_ENABLED", False)

        # ── Shorts Highlight Engine ────────────────────────────────────────────
        # LLM-based highlight detection + OpenCV face-aware vertical crop.
        # Fallback: uses existing segment boundaries (no highlight re-ranking).
        self.shorts_engine_enabled = self._get_bool_env("SHORTS_ENGINE_ENABLED", False)
        self.shorts_engine_provider = os.getenv("SHORTS_ENGINE_PROVIDER", "samuraigpt")

        # ── Editlist Backend ───────────────────────────────────────────────────
        # Declarative editlist pipeline (gradual rollout: cuts → overlays → transitions).
        # Fallback: builds FFmpeg commands directly (legacy approach).
        self.editlist_enabled = self._get_bool_env("EDITLIST_ENABLED", True)  # master switch
        self.editlist_enable_cuts = self._get_bool_env("EDITLIST_ENABLE_CUTS", True)
        self.editlist_enable_overlays = self._get_bool_env("EDITLIST_ENABLE_OVERLAYS", False)
        self.editlist_enable_transitions = self._get_bool_env("EDITLIST_ENABLE_TRANSITIONS", False)

        # ── Face Auto-Crop ─────────────────────────────────────────────────────
        # Intelligent face-tracking auto-crop to 9:16 using OpenCV Haar cascades.
        # When enabled, takes priority over ImpactZoomService and zoom_punch
        # to avoid conflicting crop trajectories.
        # Fallback: fixed center crop (no face tracking).
        self.face_autocrop_enabled = self._get_bool_env("FACE_AUTOCROP_ENABLED", True)

        # ── Faceless Feature ───────────────────────────────────────────────────
        # Automated faceless video generation (text-to-video + TTS narration).
        # Fallback: requires source video input (no auto-generation).
        self.faceless_feature_enabled = self._get_bool_env("FACELESS_FEATURE_ENABLED", False)

        # ── Caption Backend Selector ───────────────────────────────────────────
        # "legacy" = original subtitle rendering (drawtext filter)
        # "auto_subtitle" = new auto-subtitle service (AssemblyAI + confidence-based)
        self.caption_backend = os.getenv("CAPTION_BACKEND", "legacy")

        # ── Export Preset ──────────────────────────────────────────────────────
        # "tiktok_basic" = 9:16, 30fps, AAC 128k
        # "fast_vertical" = 9:16, 24fps, AAC 96k (faster encode)
        # "youtube_shorts" = 9:16, 30fps, AAC 192k
        # "instagram_reels" = 9:16, 30fps, AAC 128k + interlace
        self.export_preset = os.getenv("EXPORT_PRESET", "tiktok_basic")

        # ── Optimization Loop ──────────────────────────────────────────────────
        # Clip performance analysis + creative hints feedback loop.
        # Fallback: no performance-driven optimization.
        self.optimization_loop_enabled = self._get_bool_env("OPTIMIZATION_LOOP_ENABLED", False)
        self.optimization_loop_workspace_id = os.getenv("OPTIMIZATION_LOOP_WORKSPACE_ID", "default")
        self.optimization_loop_min_samples = int(os.getenv("OPTIMIZATION_LOOP_MIN_SAMPLES", "10"))
        self.optimization_loop_min_delta = float(os.getenv("OPTIMIZATION_LOOP_MIN_DELTA", "0.05"))

        # Hook visual delay when captions are active (avoids text overlap)
        self.hook_visual_delay_if_captions = float(os.getenv("HOOK_VISUAL_DELAY_IF_CAPTIONS", "2.0"))

        # Subtitle Re-alignment
        self.subtitle_realign_enabled = self._get_bool_env("SUBTITLE_REALIGN_ENABLED", True)
        self.subtitle_realign_model = os.getenv("SUBTITLE_REALIGN_MODEL", "small")
        self.subtitle_anticipation_ms = float(os.getenv("SUBTITLE_ANTICIPATION_MS", "-50"))

        # Audio Ducking Adaptativo
        self.ducking_mode = os.getenv("DUCKING_MODE", "predictive")
        self.ducking_voice_ratio = float(os.getenv("DUCKING_VOICE_RATIO", "0.45"))
        self.ducking_long_pause_boost = float(os.getenv("DUCKING_LONG_PAUSE_BOOST", "2.0"))
        self.ducking_short_pause_boost = float(os.getenv("DUCKING_SHORT_PAUSE_BOOST", "1.2"))

        # Voice Enhancement
        self.voice_enhancement_enabled = self._get_bool_env("VOICE_ENHANCEMENT_ENABLED", True)
        self.voice_noise_gate_threshold = float(os.getenv("VOICE_NOISE_GATE_THRESHOLD", "-35"))
        self.voice_presence_boost = float(os.getenv("VOICE_PRESENCE_BOOST", "2.5"))

        # Admin JWT auth
        self.admin_secret = os.getenv("ADMIN_SECRET", "")
        
        # FIX: Validate configuration on startup
        self._validate_config()
    
    def _validate_config(self):
        """Validate critical configuration and log warnings."""
        # Check if any LLM API key is configured
        has_llm = any([
            self.openai_api_key,
            self.google_api_key,
            self.anthropic_api_key,
            self.groq_api_key,
            self.deepseek_api_key,
        ])
        
        if not has_llm:
            logger.warning(
                "[WARN] No LLM API key found! Pipeline will use fallback text-based analysis. "
                "Set GROQ_API_KEY (recommended), OPENAI_API_KEY, GOOGLE_API_KEY, ANTHROPIC_API_KEY, "
                "or DEEPSEEK_API_KEY for best quality."
            )
        
        # Check Whisper device configuration
        whisper_device = os.getenv("WHISPER_DEVICE", "cpu")
        if whisper_device == "cuda":
            logger.info("[GPU] Whisper configured for CUDA/GPU.")
        
        # Check if critical directories exist (Docker handles this, but warn in standalone mode)
        if not os.path.exists(self.temp_dir):
            logger.warning(f"[WARN] Temp directory not found: {self.temp_dir}. Will be created on first use.")
        
        # Log configured LLM
        logger.info(f"[LLM] configured: {self.llm}")
        logger.info(f"[LLM] viral_scoring_llm: {self.viral_scoring_llm}")

    @staticmethod
    def _get_optional_env(name: str):
        value = os.getenv(name)
        if value is None:
            return None

        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _get_bool_env(name: str, default: bool) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return default

    @staticmethod
    def _get_csv_env(name: str, default: list[str]) -> list[str]:
        value = os.getenv(name)
        if not value:
            return default
        return [item.strip() for item in value.split(",") if item.strip()]

    @staticmethod
    def _normalize_apify_quality(value: str | None) -> str:
        normalized = (value or "").strip()
        if normalized in {"360", "480", "720", "1080"}:
            return normalized
        return "1080"

    @staticmethod
    def _normalize_youtube_metadata_provider(value: str | None) -> str:
        normalized = (value or "").strip().lower()
        if normalized == "youtube_data_api":
            return "youtube_data_api"
        return "yt_dlp"

    def resolve_youtube_data_api_key(self) -> str | None:
        return self.youtube_data_api_key or self.google_api_key

    def _infer_default_llm(self) -> str:
        """
        Infer a usable default model based on whichever API key is present.
        Priority order: Google > OpenAI > Anthropic > Groq > Ollama
        Falls back to Google for backward compatibility.
        """
        if self.google_api_key:
            return "google-gla:gemini-2.0-flash"
        if self.openai_api_key:
            return "openai:gpt-4o-mini"
        if self.anthropic_api_key:
            return "anthropic:claude-3-5-haiku-latest"
        if self.deepseek_api_key:
            return "deepseek:deepseek-chat"
        if self.groq_api_key:
            return "groq:llama-3.3-70b-versatile"
        if self.ollama_base_url:
            return "ollama:llama3.2"
        return "google-gla:gemini-2.0-flash"


def get_config() -> Config:
    """Return a cached Config singleton to avoid re-initializing on every call."""
    global _config_singleton
    override = _config_override
    if override is not None:
        return override
    if _config_singleton is None:
        _config_singleton = Config()
    return _config_singleton


def set_config_override(config: Config | None) -> None:
    global _config_override
    _config_override = config
