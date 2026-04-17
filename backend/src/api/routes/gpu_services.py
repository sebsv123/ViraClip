"""
GPU Services API — Phase 3 REST Endpoints
==========================================
Endpoints for on-demand GPU generative AI features:
  POST /gpu/broll/generate       — T2V B-Roll generation (LTX-Video / AnimateLCM)
  POST /gpu/tts/synthesize       — XTTS v2 narration synthesis
  POST /gpu/upscale              — Real-ESRGAN video upscaling
  POST /gpu/lora/train           — LoRA viral-style fine-tuning
  GET  /gpu/status               — GPU worker health + VRAM info
  GET  /gpu/broll/{job_id}       — Poll async T2V job
"""
from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from ...auth_headers import get_signed_user_id, USER_ID_HEADER
from ...workers.queue_router import enqueue, select_queue, GPU_QUEUE
from ...config import get_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/gpu", tags=["gpu-services"])

TEMP_DIR = Path(os.environ.get("TEMP_DIR", "/app/temp/uploads"))


# ── Request / Response models ─────────────────────────────────────────────────

class BRollGenerateRequest(BaseModel):
    prompt: str       = Field(..., description="Text prompt for B-roll generation")
    duration: float   = Field(3.0, ge=1.0, le=8.0, description="Clip duration in seconds")
    resolution: str   = Field("720p", description="Output resolution: 480p | 720p | 1080p")
    model: str        = Field("ltx-video", description="T2V model: ltx-video | wan2.2-1.3b | animatelcm")
    task_id: Optional[str] = Field(None, description="Parent task ID for progress association")


class TTSSynthesizeRequest(BaseModel):
    text: str             = Field(..., description="Text to synthesize")
    language: str         = Field("en", description="BCP-47 language code (en, es, fr, de, pt, …)")
    speaker_wav: Optional[str] = Field(None, description="Path to reference WAV for voice cloning")
    speed: float          = Field(1.0, ge=0.5, le=2.0, description="Speech speed multiplier")
    task_id: Optional[str] = Field(None)


class UpscaleRequest(BaseModel):
    input_path: str   = Field(..., description="Absolute path to source video inside container")
    scale_factor: int = Field(2, ge=2, le=4, description="Upscale factor: 2 or 4")
    task_id: Optional[str] = Field(None)


class LoRATrainRequest(BaseModel):
    dataset_path: str  = Field(..., description="Path to folder with image+caption pairs")
    base_model: str    = Field("sd1.5", description="Base model: sd1.5 | sdxl | wan2.2-1.3b")
    style_name: str    = Field("viral", description="Style identifier for output filename")
    num_steps: int     = Field(500, ge=100, le=5000)
    task_id: Optional[str] = Field(None)


class JobStatusResponse(BaseModel):
    job_id: str
    status: str         # queued | running | done | error
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# ── In-memory job store (lightweight; replace with DB/Redis for production) ───

_job_store: Dict[str, Dict[str, Any]] = {}


def _store_job(job_id: str, status: str = "queued", result: Any = None, error: str = None):
    _job_store[job_id] = {"job_id": job_id, "status": status, "result": result, "error": error}


def _update_job(job_id: str, **kwargs):
    if job_id in _job_store:
        _job_store[job_id].update(kwargs)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/status")
async def gpu_status():
    """
    Returns GPU availability, VRAM, and whether the GPU worker queue is reachable.
    """
    info: Dict[str, Any] = {"gpu_available": False, "device": None, "vram_gb": None}

    try:
        import torch
        if torch.cuda.is_available():
            info["gpu_available"] = True
            info["device"] = torch.cuda.get_device_name(0)
            info["vram_gb"] = round(
                torch.cuda.get_device_properties(0).total_memory / 1024 ** 3, 1
            )
    except ImportError:
        pass

    # Check GPU worker queue depth
    try:
        cfg = get_config()
        import redis.asyncio as aioredis
        r = aioredis.Redis(
            host=cfg.redis_host, port=cfg.redis_port,
            password=cfg.redis_password, decode_responses=True,
        )
        queue_len = await r.llen("arq:queue:viraclip_gpu_tasks")
        await r.close()
        info["gpu_queue_depth"] = queue_len
        info["gpu_worker_reachable"] = True
    except Exception as _re:
        info["gpu_worker_reachable"] = False
        info["gpu_queue_error"] = str(_re)

    # GPU services enabled flags
    info["services"] = {
        "t2v_broll":  os.environ.get("T2V_MODEL", "ltx-video"),
        "tts":        os.environ.get("TTS_MODEL",  "xtts-v2"),
        "esrgan":     os.environ.get("ESRGAN_ENABLED", "false"),
        "rvc":        os.environ.get("RVC_ENABLED",    "false"),
    }

    return info


@router.post("/broll/generate")
async def generate_broll(
    req: BRollGenerateRequest,
    background_tasks: BackgroundTasks,
    request: Request,
):
    """
    Dispatch an async T2V B-Roll generation job to the GPU worker queue.
    Returns a job_id that can be polled via GET /gpu/broll/{job_id}.
    """
    job_id = str(uuid.uuid4())
    _store_job(job_id, status="queued")
    output_path = str(TEMP_DIR / "broll" / f"{job_id}.mp4")

    async def _run():
        _update_job(job_id, status="running")
        try:
            from ...services.t2v_broll_service import T2VBrollService
            svc = T2VBrollService()
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            result = await svc.generate(
                prompt=req.prompt,
                duration=req.duration,
                resolution=req.resolution,
                model=req.model,
                output_path=output_path,
            )
            _update_job(job_id, status="done", result=result)
        except Exception as exc:
            logger.error(f"[gpu/broll] Job {job_id} failed: {exc}")
            _update_job(job_id, status="error", error=str(exc))

    background_tasks.add_task(_run)
    return {"job_id": job_id, "status": "queued", "output_path": output_path}


@router.get("/broll/{job_id}", response_model=JobStatusResponse)
async def get_broll_job(job_id: str):
    """Poll the status of a T2V B-Roll generation job."""
    job = _job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job


@router.post("/tts/synthesize")
async def synthesize_tts(req: TTSSynthesizeRequest, background_tasks: BackgroundTasks):
    """
    Synthesize speech via Coqui XTTS v2.
    Dispatches to GPU worker; returns job_id for polling.
    """
    job_id = str(uuid.uuid4())
    _store_job(job_id, status="queued")
    output_path = str(TEMP_DIR / "tts" / f"{job_id}.wav")

    async def _run():
        _update_job(job_id, status="running")
        try:
            from ...services.tts_service import TTSService
            svc = TTSService()
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            result = await svc.synthesize(
                text=req.text,
                language=req.language,
                speaker_wav=req.speaker_wav,
                speed=req.speed,
                output_path=output_path,
            )
            _update_job(job_id, status="done", result=result)
        except Exception as exc:
            logger.error(f"[gpu/tts] Job {job_id} failed: {exc}")
            _update_job(job_id, status="error", error=str(exc))

    background_tasks.add_task(_run)
    return {"job_id": job_id, "status": "queued", "output_path": output_path}


@router.get("/tts/{job_id}", response_model=JobStatusResponse)
async def get_tts_job(job_id: str):
    """Poll TTS synthesis job status."""
    job = _job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job


@router.post("/upscale")
async def upscale_video(req: UpscaleRequest, background_tasks: BackgroundTasks):
    """
    Upscale a video via Real-ESRGAN (GPU) or FFmpeg bilinear (CPU fallback).
    Returns job_id; poll GET /gpu/upscale/{job_id}.
    """
    job_id = str(uuid.uuid4())
    _store_job(job_id, status="queued")

    input_p = Path(req.input_path)
    output_path = str(input_p.with_name(f"up_{job_id}_{input_p.name}"))

    async def _run():
        _update_job(job_id, status="running")
        try:
            from ...services.upscaling_service import UpscalingService
            svc = UpscalingService()
            result = await svc.upscale(
                req.input_path,
                scale_factor=req.scale_factor,
                output_path=output_path,
            )
            _update_job(job_id, status="done", result=result)
        except Exception as exc:
            logger.error(f"[gpu/upscale] Job {job_id} failed: {exc}")
            _update_job(job_id, status="error", error=str(exc))

    background_tasks.add_task(_run)
    return {"job_id": job_id, "status": "queued", "output_path": output_path}


@router.get("/upscale/{job_id}", response_model=JobStatusResponse)
async def get_upscale_job(job_id: str):
    """Poll ESRGAN upscale job status."""
    job = _job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job


@router.post("/lora/train")
async def train_lora(req: LoRATrainRequest, background_tasks: BackgroundTasks):
    """
    Start a LoRA fine-tuning job on the GPU worker.
    Returns job_id; poll GET /gpu/lora/{job_id}.
    """
    job_id = str(uuid.uuid4())
    _store_job(job_id, status="queued")

    lora_out = str(
        Path(os.environ.get("LORA_OUTPUT_DIR", "/app/models/lora"))
        / f"{req.style_name}_{job_id[:8]}.safetensors"
    )

    async def _run():
        _update_job(job_id, status="running")
        try:
            from ...services.lora_training_service import LoRATrainingService
            svc = LoRATrainingService()
            result = await svc.train(
                dataset_path=req.dataset_path,
                base_model=req.base_model,
                style_name=req.style_name,
                num_steps=req.num_steps,
                output_path=lora_out,
            )
            _update_job(job_id, status="done", result=result)
        except Exception as exc:
            logger.error(f"[gpu/lora] Job {job_id} failed: {exc}")
            _update_job(job_id, status="error", error=str(exc))

    background_tasks.add_task(_run)
    return {"job_id": job_id, "status": "queued", "lora_path": lora_out}


@router.get("/lora/{job_id}", response_model=JobStatusResponse)
async def get_lora_job(job_id: str):
    """Poll LoRA training job status."""
    job = _job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job


# ── Phase 9.3: 8K/Hollywood-Quality Upscaling ────────────────────────────────

class Upscale8KRequest(BaseModel):
    input_path: str = Field(..., description="Absolute path to source video")
    mode: str = Field("dual", description="Upscale mode: direct | dual | 4k_intermediate")
    denoise: bool = Field(False, description="Apply AI denoising before upscaling")
    hdr: bool = Field(False, description="Enable HDR10 tone mapping")
    task_id: Optional[str] = Field(None)


@router.post("/upscale/8k")
async def upscale_8k(req: Upscale8KRequest, background_tasks: BackgroundTasks):
    """
    Upscale video to 8K (7680×4320) Hollywood quality.

    Modes:
      - direct: Single 4× pass (fastest)
      - dual: Two 2× passes (best quality)
      - 4k_intermediate: 4K ProRes then 2× to 8K (balanced)

    Returns job_id for polling via GET /gpu/upscale/8k/{job_id}
    """
    job_id = str(uuid.uuid4())
    _store_job(job_id, status="queued")

    input_p = Path(req.input_path)
    output_path = str(input_p.with_name(f"8k_{job_id}_{input_p.name}"))

    async def _run():
        _update_job(job_id, status="running")
        try:
            from ...services.upscaling_8k_service import Upscale8KService
            svc = Upscale8KService()
            result = await svc.upscale_8k(
                req.input_path,
                mode=req.mode,  # type: ignore
                denoise=req.denoise,
                hdr=req.hdr,
                output_path=output_path,
            )
            _update_job(job_id, status="done", result=result)
        except Exception as exc:
            logger.error(f"[gpu/8k] Job {job_id} failed: {exc}")
            _update_job(job_id, status="error", error=str(exc))

    background_tasks.add_task(_run)
    return {"job_id": job_id, "status": "queued", "output_path": output_path}


@router.get("/upscale/8k/{job_id}", response_model=JobStatusResponse)
async def get_8k_upscale_job(job_id: str):
    """Poll 8K upscaling job status."""
    job = _job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job


@router.get("/upscale/8k/info")
async def get_8k_info():
    """Get 8K upscaling capability info (VRAM requirements, recommended mode)."""
    try:
        from ...services.upscaling_8k_service import Upscale8KService
        svc = Upscale8KService()
        return svc.get_8k_info()
    except Exception as exc:
        logger.error(f"[gpu/8k] Error getting 8K info: {exc}")
        return {"error": str(exc), "8k_supported": False}
