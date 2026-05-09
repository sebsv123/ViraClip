"""
ViraClip Constants and Defaults

Centralized configuration values to avoid hardcoded magic numbers.
All timeouts, limits, and default values should be defined here.
"""

# ============================================================================
# TIMEOUTS (seconds)
# ============================================================================

# FFmpeg operation timeouts
FFPROBE_TIMEOUT = 10
FFMPEG_ENCODE_TIMEOUT = 300
FFMPEG_FILTER_TIMEOUT = 180

# External API timeouts
HTTP_REQUEST_TIMEOUT = 30
WEBSOCKET_PING_TIMEOUT = 5

# Background task intervals
WEBSOCKET_CLEANUP_INTERVAL = 300  # 5 minutes
METRICS_BROADCAST_INTERVAL = 30  # 30 seconds
CACHE_CLEANUP_INTERVAL = 3600  # 1 hour


# ============================================================================
# LIMITS AND THRESHOLDS
# ============================================================================

# Social media limits
INSTAGRAM_HASHTAG_LIMIT = 20  # Max hashtags per post
TIKTOK_HASHTAG_LIMIT = 10
YOUTUBE_TITLE_LENGTH = 100

# Video processing limits
MAX_VIDEO_DURATION = 3600  # 1 hour
MIN_CLIP_DURATION = 3.0  # 3 seconds
MAX_CLIPS_PER_TASK = 50

# WebSocket connection limits
MAX_WEBSOCKET_CONNECTIONS_PER_USER = 5
WEBSOCKET_MESSAGE_MAX_SIZE = 1048576  # 1MB

# File size limits (bytes)
MAX_UPLOAD_SIZE = 5368709120  # 5GB
MAX_THUMBNAIL_SIZE = 10485760  # 10MB


# ============================================================================
# DEFAULT VALUES
# ============================================================================

# Video defaults
DEFAULT_VIDEO_DURATION = 30.0  # seconds
DEFAULT_FPS = 30
DEFAULT_RESOLUTION = (1920, 1080)
DEFAULT_BITRATE = "5M"

# Audio defaults
DEFAULT_SAMPLE_RATE = 44100
DEFAULT_AUDIO_CHANNELS = 2
DEFAULT_AUDIO_BITRATE = "192k"
TARGET_LOUDNESS_LUFS = -14.0  # EBU R128 standard

# Processing defaults
DEFAULT_WHISPER_MODEL = "small"
DEFAULT_LLM_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 2048

# Scene detection defaults
DEFAULT_SCENE_LENGTH = 5.0  # seconds
SCENE_CHANGE_THRESHOLD = 0.3  # 0-1 scale

# Viral scoring weights
HOOK_SCORE_WEIGHT = 0.30
PACING_SCORE_WEIGHT = 0.20
EMOTION_SCORE_WEIGHT = 0.20
ML_MODEL_WEIGHT = 0.30


# ============================================================================
# RETRY AND BACKOFF
# ============================================================================

# Retry configuration
MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 2.0  # Exponential backoff
RETRY_INITIAL_DELAY = 1.0  # seconds

# Job queue retries
TASK_MAX_RETRIES = 3
TASK_RETRY_DELAY = 60  # seconds


# ============================================================================
# PATHS AND DIRECTORIES
# ============================================================================

# Relative paths (from /app in Docker)
TEMP_DIR = "/app/temp/uploads"
STORAGE_DIR = "/app/storage"
MODELS_DIR = "/app/models"
DATASETS_DIR = "/app/datasets"
ASSETS_DIR = "/app/assets"


# ============================================================================
# CACHE SETTINGS
# ============================================================================

# Redis TTL values (seconds)
TASK_CACHE_TTL = 86400  # 24 hours
PROGRESS_CACHE_TTL = 3600  # 1 hour
SESSION_CACHE_TTL = 7200  # 2 hours
THUMBNAIL_CACHE_TTL = 604800  # 7 days


# ============================================================================
# FEATURE FLAGS
# ============================================================================

# Enable/disable optional features
ENABLE_GPU_PROCESSING = True
ENABLE_COMFYUI = False
ENABLE_VISION_ANALYSIS = True
ENABLE_MONETIZATION = False


# ============================================================================
# LOGGING
# ============================================================================

# Log levels for different components
DEFAULT_LOG_LEVEL = "INFO"
WORKER_LOG_LEVEL = "INFO"
DATABASE_LOG_LEVEL = "WARNING"
HTTP_LOG_LEVEL = "INFO"


# ============================================================================
# VALIDATION
# ============================================================================

# Input validation patterns
VALID_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
VALID_AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".flac"}
VALID_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# URL validation
MAX_URL_LENGTH = 2048
ALLOWED_URL_SCHEMES = {"http", "https"}


# ============================================================================
# RATE LIMITING
# ============================================================================

# API rate limits (requests per minute)
RATE_LIMIT_ANONYMOUS = 10
RATE_LIMIT_AUTHENTICATED = 60
RATE_LIMIT_PREMIUM = 300

# Task creation limits
TASKS_PER_USER_PER_HOUR = 20
TASKS_PER_USER_PER_DAY = 100


# ============================================================================
# ERROR MESSAGES
# ============================================================================

ERROR_INVALID_VIDEO = "Invalid video file or unsupported format"
ERROR_VIDEO_TOO_LARGE = f"Video file exceeds maximum size of {MAX_UPLOAD_SIZE / (1024**3):.1f}GB"
ERROR_VIDEO_TOO_LONG = f"Video duration exceeds maximum of {MAX_VIDEO_DURATION / 60:.0f} minutes"
ERROR_NO_API_KEY = "No LLM API key configured. Set GROQ_API_KEY, OPENAI_API_KEY, or GOOGLE_API_KEY"
ERROR_TASK_NOT_FOUND = "Task not found or access denied"
ERROR_RATE_LIMIT = "Rate limit exceeded. Please try again later"


# ============================================================================
# HTTP Timeouts (centralized)
# ============================================================================
import httpx as _httpx
BROLL_HTTP_TIMEOUT       = _httpx.Timeout(15.0, connect=5.0)
ELEVENLABS_HTTP_TIMEOUT  = _httpx.Timeout(20.0, connect=5.0)
SFX_HTTP_TIMEOUT         = _httpx.Timeout(15.0, connect=5.0)

# ============================================================================
# Locks and TTLs
# ============================================================================
COMFYUI_LOCK_TIMEOUT_SECONDS  = 120
TASK_STALE_TIMEOUT_MINUTES    = 45
ELEVENLABS_SFX_CACHE_TTL_DAYS = 7

# ============================================================================
# Circuit Breaker (DeepSeek)
# ============================================================================
LLM_CB_WINDOW_SECONDS = 300   # ventana de observación (5 min)
LLM_CB_BYPASS_SECONDS = 600   # tiempo de bypass (10 min)
LLM_CB_THRESHOLD      = 3     # fallos para activar
