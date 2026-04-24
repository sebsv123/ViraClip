"""
GPU Worker Tasks — Phase 5.2
==============================
Tareas ARQ que requieren GPU: T2V B-roll, TTS, upscaling, LoRA training.
Los workers CPU nunca toman estas tareas; solo el gpu_worker las procesa.

Queue name: "viraclip_gpu_tasks"
"""

import logging
from typing import Dict, Any, Optional

from ..observability import set_trace_id

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# GPU Task: Text-to-Video B-Roll generation
# ─────────────────────────────────────────────

async def generate_broll_t2v(
    ctx: Dict[str, Any],
    task_id: str,
    prompt: str,
    duration_seconds: float = 4.0,
    resolution: str = "720p",
    model: str = "ltx-video",          # ltx-video | wan2.2-1.3b | wan2.2-14b
    clip_index: int = 0,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate B-roll clip from text prompt using T2V model.
    Dispatched from CPU worker when include_broll=True and GPU available.

    Args:
        task_id:    Parent task ID for progress updates
        prompt:     Text prompt for video generation
        duration_seconds: Clip duration (2–8s recommended)
        resolution: "480p" | "720p" | "1080p"
        model:      T2V model to use
        clip_index: Index in parent clip sequence
        output_path: Where to write the generated clip

    Returns:
        {"clip_path": str, "duration": float, "model": str}
    """
    set_trace_id(f"gpu-broll-{task_id}-{clip_index}")
    logger.info(f"[gpu] Generating B-roll for task {task_id} | prompt='{prompt[:60]}...'")

    from ..services.t2v_broll_service import T2VBrollService

    service = T2VBrollService()
    result = await service.generate(
        prompt=prompt,
        duration=duration_seconds,
        resolution=resolution,
        model=model,
        output_path=output_path,
    )

    logger.info(f"[gpu] B-roll done: {result.get('clip_path')}")
    return result


# ─────────────────────────────────────────────
# GPU Task: ESRGAN video upscaling
# ─────────────────────────────────────────────

async def upscale_clip(
    ctx: Dict[str, Any],
    task_id: str,
    input_path: str,
    scale_factor: int = 4,
    model: str = "realesrgan",          # realesrgan | esrgan
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Upscale a video clip using Real-ESRGAN.
    Triggered when source resolution < 720p.

    Args:
        task_id:      Parent task ID
        input_path:   Source clip path
        scale_factor: 2x or 4x upscale
        model:        Upscaling model
        output_path:  Output path for upscaled clip

    Returns:
        {"output_path": str, "original_resolution": str, "output_resolution": str}
    """
    set_trace_id(f"gpu-upscale-{task_id}")
    logger.info(f"[gpu] Upscaling clip for task {task_id} | {scale_factor}x | model={model}")

    from ..domains.upscaling.upscaling_service import UpscalingService

    service = UpscalingService()
    result = await service.upscale(
        input_path=input_path,
        scale_factor=scale_factor,
        model=model,
        output_path=output_path,
    )

    logger.info(f"[gpu] Upscale done: {result.get('output_path')}")
    return result


# ─────────────────────────────────────────────
# GPU Task: RAFT optical-flow transitions
# ─────────────────────────────────────────────

async def generate_optical_flow_transition(
    ctx: Dict[str, Any],
    task_id: str,
    clip_a_path: str,
    clip_b_path: str,
    transition_duration: float = 0.5,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate smooth morph transition between two clips via RAFT optical flow.

    Args:
        task_id:             Parent task ID
        clip_a_path:         First clip (tail frames used)
        clip_b_path:         Second clip (head frames used)
        transition_duration: Duration of the blended transition (seconds)
        output_path:         Path for the transition clip

    Returns:
        {"output_path": str, "transition_frames": int}
    """
    set_trace_id(f"gpu-transition-{task_id}")
    logger.info(f"[gpu] Generating optical flow transition for task {task_id}")

    from ..services.optical_flow_service import OpticalFlowService

    service = OpticalFlowService()
    result = await service.generate_transition(
        clip_a=clip_a_path,
        clip_b=clip_b_path,
        duration=transition_duration,
        output_path=output_path,
    )

    logger.info(f"[gpu] Transition done: {result.get('output_path')}")
    return result


# ─────────────────────────────────────────────
# GPU Task: TTS voice narration
# ─────────────────────────────────────────────

async def generate_tts_narration(
    ctx: Dict[str, Any],
    task_id: str,
    text: str,
    speaker_sample_path: Optional[str] = None,
    language: str = "en",
    model: str = "xtts-v2",             # xtts-v2 | tortoise
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate TTS narration using Coqui XTTS v2 or Tortoise.
    Used when source audio SNR is below threshold.

    Args:
        task_id:             Parent task ID
        text:                Narration text
        speaker_sample_path: 3-second speaker sample for voice cloning (optional)
        language:            Output language code
        model:               TTS model to use
        output_path:         Where to write the audio file (.wav)

    Returns:
        {"audio_path": str, "duration": float, "language": str}
    """
    set_trace_id(f"gpu-tts-{task_id}")
    logger.info(f"[gpu] Generating TTS for task {task_id} | model={model} | lang={language}")

    from ..domains.audio.tts_service import TTSService

    service = TTSService()
    result = await service.synthesize(
        text=text,
        speaker_sample=speaker_sample_path,
        language=language,
        model=model,
        output_path=output_path,
    )

    logger.info(f"[gpu] TTS done: {result.get('audio_path')}")
    return result


# ─────────────────────────────────────────────
# GPU Task: LoRA fine-tuning
# ─────────────────────────────────────────────

async def train_virality_lora(
    ctx: Dict[str, Any],
    training_run_id: str,
    dataset_path: str,
    base_model: str = "wan2.2-1.3b",
    style_name: str = "viral_tiktok",
    num_steps: int = 500,
    batch_size: int = 4,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Fine-tune a virality LoRA on the given dataset.
    Scheduled weekly via ARQ cron; also triggerable via API.

    Args:
        training_run_id: Unique ID for this training run
        dataset_path:    Path to prepared dataset (parquet or folder)
        base_model:      Base model to fine-tune
        style_name:      LoRA style tag
        num_steps:       Training iterations
        batch_size:      Samples per step
        output_path:     Where to save the .safetensors file

    Returns:
        {"lora_path": str, "loss": float, "steps": int, "style": str}
    """
    set_trace_id(f"gpu-lora-{training_run_id}")
    logger.info(
        f"[gpu] Training LoRA '{style_name}' | base={base_model} | steps={num_steps}"
    )

    from ..services.lora_training_service import LoRATrainingService

    service = LoRATrainingService()
    result = await service.train(
        dataset_path=dataset_path,
        base_model=base_model,
        style_name=style_name,
        num_steps=num_steps,
        batch_size=batch_size,
        output_path=output_path,
    )

    logger.info(f"[gpu] LoRA training done: {result.get('lora_path')}")
    return result


# ─────────────────────────────────────────────
# GPU Worker startup hook
# ─────────────────────────────────────────────

async def gpu_worker_startup(ctx: Dict[str, Any]) -> None:
    """Verify GPU availability and pre-load models on GPU worker startup."""
    import os

    logger.info("[gpu-worker] Starting up...")

    # Check GPU availability
    gpu_available = False
    try:
        import torch
        gpu_available = torch.cuda.is_available()
        if gpu_available:
            device_name = torch.cuda.get_device_name(0)
            vram_gb = torch.cuda.get_device_properties(0).total_memory / 1024 ** 3
            logger.info(f"[gpu-worker] GPU detected: {device_name} ({vram_gb:.1f} GB VRAM)")
        else:
            logger.warning(
                "[gpu-worker] No GPU detected — GPU tasks will run on CPU (slow fallback)"
            )
    except ImportError:
        logger.warning("[gpu-worker] PyTorch not available")

    ctx["gpu_available"] = gpu_available


# ─────────────────────────────────────────────
# GPU WorkerSettings
# ─────────────────────────────────────────────

class GpuWorkerSettings:
    """
    ARQ WorkerSettings for the GPU worker.
    Reads from the SAME Redis instance but a DIFFERENT queue: viraclip_gpu_tasks.
    """

    from ..config import Config
    from arq.connections import RedisSettings

    config = Config()

    functions = [
        generate_broll_t2v,
        upscale_clip,
        generate_optical_flow_transition,
        generate_tts_narration,
        train_virality_lora,
    ]

    queue_name = "viraclip_gpu_tasks"

    redis_settings = RedisSettings(
        host=config.redis_host,
        port=config.redis_port,
        password=config.redis_password,
        database=0,
    )

    # GPU tasks are long — allow up to 4h for T2V / LoRA
    max_tries = 2
    job_timeout = 14400   # 4 hours

    # Only 1 GPU job at a time to avoid VRAM contention
    max_jobs = 1

    on_startup = gpu_worker_startup
    cron_jobs = []  # populated below after class definition


# Activate GPU cron jobs — weekly LoRA retrain (Sunday 02:30 UTC)
def _safe_cron_gpu(func, name, **kwargs):
    """Safely create a cron job with individual error handling."""
    try:
        from arq import cron
        job = cron(func, **kwargs)
        logger.debug(f"[Scheduler] Registered GPU cron job: {name}")
        return job
    except Exception as e:
        logger.warning(f"[Scheduler] Failed to register GPU cron job '{name}': {e} — skipping")
        return None


try:
    from .data_pipeline_cron import retrain_lora_weekly
    
    _job = _safe_cron_gpu(
        retrain_lora_weekly,
        "retrain_lora_weekly",
        hour=2, minute=30, day_of_week=0
    )
    GpuWorkerSettings.cron_jobs = [_job] if _job else []
    
    if _job:
        logger.info(f"[GpuWorkerSettings] Successfully registered GPU cron job")
        
except Exception as _cron_err:
    logger.warning(
        f"[GpuWorkerSettings] GPU cron_jobs setup failed: {_cron_err} — "
        "LoRA weekly retrain will NOT run."
    )
    GpuWorkerSettings.cron_jobs = []
