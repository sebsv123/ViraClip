import json
import sys as _sys
import io as _io

# Force UTF-8 on stdout/stderr so emoji in log messages never crash on Windows cp1252
if hasattr(_sys.stdout, 'buffer'):
    _sys.stdout = _io.TextIOWrapper(_sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
if hasattr(_sys.stderr, 'buffer'):
    _sys.stderr = _io.TextIOWrapper(_sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

from .video_processing import get_available_transitions
from .config import get_config
from .caption_templates import get_template_info
from contextlib import asynccontextmanager
from pathlib import Path
import logging
import shutil
import uuid
from typing import List

# Configure logging — UTF-8 handlers
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(_sys.stdout),
        logging.FileHandler("logs/backend.log", encoding="utf-8"),
    ],
)

logger = logging.getLogger(__name__)
from sqlalchemy.ext.asyncio import AsyncSession
import os as _os
import os  # noqa: E401 — explicit public alias so `os.getenv` works in middleware
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import text

from .database import init_db, close_db, get_db, AsyncSessionLocal
from .auth_headers import USER_ID_HEADER
from .api.routes.tasks import router as tasks_router
from .api.routes.feedback import router as feedback_router
from .api.routes.billing import router as billing_router
from .api.routes.clips import router as clips_router
from .api.routes.jobs import router as jobs_router
from .api.routes.whatsapp import router as whatsapp_router
from .domains.video.video_service import UPLOAD_URL_PREFIX

config = get_config()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        # Initialize database
        await init_db()
        
        # FIX Problema 3: Startup log for Groq API key
        import os as _os
        if _os.environ.get("GROQ_API_KEY", "").strip():
            logger.info("[STARTUP] Groq API: ✅ configured")
        else:
            logger.warning("[STARTUP] Groq API: ❌ missing key — using fallback")
        
        # Initialize Redis for caching and rate limiting
        from .scaling.redis_manager import get_redis_client
        from .middleware.rate_limiter import init_rate_limiter
        from .caching import init_cache
        
        redis_client = await get_redis_client()
        if redis_client:
            await init_rate_limiter(redis_client)
            await init_cache(redis_client)
            logger.info("✅ Rate limiting and caching initialized")
        else:
            logger.warning("⚠️ Redis unavailable - rate limiting and caching disabled")
        
        # LUTService: auto-download film LUTs if not present
        try:
            from .domains.video.lut_service import get_lut_service as _get_lut
            _lut_svc = _get_lut()
            _lut_info = _lut_svc.get_info()
            if _lut_info["cube_files_present"] == 0:
                logger.info("[LUT] No .cube files found — downloading Film-Luts (background)...")
                import asyncio as _aio
                _aio.create_task(_lut_svc.download_luts())
            else:
                logger.info(f"[LUT] {_lut_info['cube_files_present']} LUT presets ready")
        except Exception as _lut_e:
            logger.debug(f"[LUT] Auto-download skipped: {_lut_e}")

        yield
    finally:
        await close_db()
        
        # Close Redis connections
        from .scaling.redis_manager import get_redis_manager
        manager = await get_redis_manager()
        await manager.close()


app = FastAPI(
    title="ViraClip API",
    description="Python-based backend for ViraClip",
    version="0.1.0",
    lifespan=lifespan,
)

# Upload size limit middleware (ASGI-level, NOT BaseHTTPMiddleware — avoids
# the known Starlette bug where BaseHTTPMiddleware consumes the ASGI receive
# stream, preventing request.json() from ever receiving the body).
from starlette.types import ASGIApp, Receive, Scope, Send


class UploadSizeLimitMiddlewareASGI:
    """ASGI middleware that rejects oversized requests before body is read."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http" and scope["method"] in ("POST", "PUT", "PATCH"):
            headers = dict(scope.get("headers", []))
            content_length = None
            for key, val in headers.items():
                if key == b"content-length":
                    content_length = val
                    break
            if content_length:
                try:
                    size = int(content_length)
                    max_bytes = int(_os.getenv("MAX_UPLOAD_MB", "500")) * 1024 * 1024
                    if size > max_bytes:
                        max_mb = int(_os.getenv("MAX_UPLOAD_MB", "500"))
                        body = json.dumps({
                            "error": "File too large",
                            "max_mb": max_mb,
                            "received_mb": round(size / 1024 / 1024, 1),
                            "message": f"Maximum upload size is {max_mb}MB",
                        }).encode("utf-8")
                        await send({
                            "type": "http.response.start",
                            "status": 413,
                            "headers": [
                                (b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode()),
                            ],
                        })
                        await send({
                            "type": "http.response.body",
                            "body": body,
                        })
                        return
                except ValueError:
                    pass
        await self.app(scope, receive, send)


app.add_middleware(UploadSizeLimitMiddlewareASGI)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "x-viraclip-user-id",
        "x-viraclip-ts",
        "x-viraclip-signature",
        "user_id",
    ],
)

# Include API routers
app.include_router(tasks_router)
app.include_router(feedback_router)
app.include_router(billing_router)
#app.include_router(social_router)
app.include_router(clips_router)
app.include_router(jobs_router)
app.include_router(whatsapp_router)

# Include admin routers
from .api.routes.admin import router as admin_router
from .api.routes.ai_metrics import router as ai_metrics_router
from .api.routes.health import router as health_router
app.include_router(admin_router)
app.include_router(ai_metrics_router)
app.include_router(health_router)

# Autopilot — end-to-end automation pipeline
try:
    from .api.routes.autopilot import router as autopilot_router
    app.include_router(autopilot_router)
except Exception as _ap_e:
    import logging as _log; _log.getLogger(__name__).warning(f"Autopilot router skipped: {_ap_e}")

# Workflow Automation — visual workflow builder
try:
    from .api.routes.workflows import router as workflows_router
    app.include_router(workflows_router)
except Exception as _wf_e:
    import logging as _log; _log.getLogger(__name__).warning(f"Workflows router skipped: {_wf_e}")

# LUT Service — cinematic color grading
try:
    from .api.routes.lut import router as lut_router
    app.include_router(lut_router)
except Exception as _lut_e:
    logger.warning(f"LUT router skipped: {_lut_e}")

# Mount static files for serving clips
clips_dir = Path(config.temp_dir) / "clips"
clips_dir.mkdir(parents=True, exist_ok=True)
app.mount("/clips", StaticFiles(directory=str(clips_dir)), name="clips")


# ── Upload directory ─────────────────────────────────────────────────────────
UPLOAD_DIR = Path(config.temp_dir) / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/")
def read_root():
    return {
        "message": "This is the ViraClip FastAPI-based API. Visit /docs for the API documentation."
    }


@app.get("/health/db")
async def check_database_health(db: AsyncSession = Depends(get_db)):
    """Check database connectivity"""
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "database": "disconnected", "error": str(e)}


# ── Upload endpoints ─────────────────────────────────────────────────────────

@app.post("/upload")
async def upload_video(request: Request):
    """Upload a single video file"""
    try:
        import aiofiles

        user_id = request.headers.get("user_id") or request.headers.get(USER_ID_HEADER)
        if not user_id:
            raise HTTPException(status_code=401, detail="User authentication required")

        form_data = await request.form()
        video_file = form_data.get("video")
        if not video_file or not hasattr(video_file, "filename"):
            raise HTTPException(status_code=400, detail="No video file provided")

        uploads_dir = Path(config.temp_dir)
        uploads_dir.mkdir(parents=True, exist_ok=True)
        file_extension = Path(video_file.filename).suffix
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        video_path = uploads_dir / unique_filename

        async with aiofiles.open(video_path, "wb") as f:
            await f.write(await video_file.read())

        return {"message": "Video uploaded successfully", "video_path": f"{UPLOAD_URL_PREFIX}{unique_filename}"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading video: {e}")
        raise HTTPException(status_code=500, detail=f"Error uploading video: {e}")


@app.post("/api/upload-batch")
async def upload_batch(files: List[UploadFile] = File(...)):
    """Batch upload of up to 20 video files"""
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    if len(files) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 videos per batch")
    uploaded = []
    for file in files:
        if not file.content_type or not file.content_type.startswith("video/"):
            raise HTTPException(status_code=400, detail=f"{file.filename} is not a valid video")
        unique_filename = f"{uuid.uuid4()}{Path(file.filename).suffix.lower()}"
        file_path = UPLOAD_DIR / unique_filename
        with open(file_path, "wb") as buf:
            shutil.copyfileobj(file.file, buf)
        uploaded.append({"filename": unique_filename, "original_name": file.filename,
                         "size": file.size, "url": f"/uploads/{unique_filename}"})
    return {"uploaded": len(uploaded), "files": uploaded}


# ── Asset endpoints ───────────────────────────────────────────────────────────

@app.get("/fonts")
async def get_available_fonts():
    """List available font files"""
    fonts_dir = Path(__file__).parent.parent / "fonts"
    if not fonts_dir.exists():
        return {"fonts": []}
    return {"fonts": [{"name": f.stem, "display_name": f.stem.replace("-", " ").replace("_", " ").title(),
                       "file_path": str(f)} for f in fonts_dir.glob("*.ttf")]}


@app.get("/fonts/{font_name}")
async def get_font_file(font_name: str):
    """Serve a specific font file"""
    font_path = Path(__file__).parent.parent / "fonts" / f"{font_name}.ttf"
    if not font_path.exists():
        raise HTTPException(status_code=404, detail="Font not found")
    return FileResponse(str(font_path), media_type="font/ttf",
                        headers={"Cache-Control": "public, max-age=31536000"})


@app.get("/transitions")
async def list_transitions():
    """List available transition effects"""
    return {"transitions": [{"name": Path(t).stem,
                             "display_name": Path(t).stem.replace("_", " ").replace("-", " ").title(),
                             "file_path": t} for t in get_available_transitions()]}


@app.get("/caption-templates")
async def get_caption_templates():
    """List available caption templates"""
    return {"templates": get_template_info()}


@app.get("/broll/search")
async def search_broll(query: str, count: int = 5, orientation: str = "portrait"):
    """Search for B-roll footage from Pexels"""
    if not config.pexels_api_key:
        raise HTTPException(status_code=503, detail="B-roll service not configured")
    from .video_processing.broll import search_broll_videos, get_video_download_url
    videos = await search_broll_videos(query, orientation=orientation, per_page=count)
    return {"query": query, "total": len(videos),
            "videos": [{"id": v.get("id"), "duration": v.get("duration"),
                        "thumbnail": v.get("image"),
                        "download_url": get_video_download_url(v, quality="hd", orientation=orientation),
                        "user": v.get("user", {}).get("name", "Unknown")} for v in videos]}


@app.get("/broll/status")
async def broll_status():
    """Check B-roll service availability"""
    return {"configured": bool(config.pexels_api_key),
            "provider": "pexels" if config.pexels_api_key else None}


