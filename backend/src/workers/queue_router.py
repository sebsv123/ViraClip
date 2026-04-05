"""
Queue Router — Phase 5.2
=========================
Decides whether a task goes to the CPU queue or the GPU queue,
and provides a single enqueue() helper so the rest of the codebase
never hard-codes queue names.

CPU queue : "viraclip_cpu_tasks"  (workers 1-3, always available)
GPU queue : "viraclip_gpu_tasks"  (gpu_worker, optional)

If no GPU worker is running, GPU tasks fall back to the CPU queue
so the system degrades gracefully.
"""

import os
import logging
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Queue name constants — single source of truth
CPU_QUEUE = "viraclip_cpu_tasks"
GPU_QUEUE = "viraclip_gpu_tasks"

# Legacy name kept for backwards-compat (old workers still read it)
LEGACY_QUEUE = "viraclip_tasks"


class TaskQueue(str, Enum):
    CPU = CPU_QUEUE
    GPU = GPU_QUEUE


# Tasks that MUST run on the GPU worker when available
_GPU_TASK_NAMES = {
    "generate_broll_t2v",
    "upscale_clip",
    "generate_optical_flow_transition",
    "generate_tts_narration",
    "train_virality_lora",
}


def requires_gpu(function_name: str) -> bool:
    """Return True if the named task should be routed to the GPU queue."""
    return function_name in _GPU_TASK_NAMES


def select_queue(function_name: str, force_cpu: bool = False) -> str:
    """
    Select the correct queue for a task.

    Args:
        function_name: The ARQ task function name (e.g. "generate_broll_t2v")
        force_cpu:     Force CPU queue even for GPU tasks (useful in tests)

    Returns:
        Queue name string
    """
    gpu_enabled = os.getenv("GPU_WORKER_ENABLED", "false").lower() == "true"

    if force_cpu or not gpu_enabled:
        if requires_gpu(function_name) and not force_cpu:
            logger.warning(
                f"[queue_router] GPU task '{function_name}' routed to CPU queue "
                "(GPU_WORKER_ENABLED=false). Will run slowly on CPU."
            )
        return CPU_QUEUE

    return GPU_QUEUE if requires_gpu(function_name) else CPU_QUEUE


async def enqueue(
    redis,
    function_name: str,
    *args,
    queue_override: Optional[str] = None,
    job_id: Optional[str] = None,
    **kwargs,
) -> Any:
    """
    Enqueue a task to the appropriate queue.

    Args:
        redis:          aioredis / arq Redis connection
        function_name:  Name of the ARQ task function
        *args:          Positional args for the task
        queue_override: Force a specific queue name
        job_id:         Optional stable job ID for deduplication
        **kwargs:       Keyword args for the task

    Returns:
        arq Job object

    Example:
        job = await enqueue(redis, "generate_broll_t2v",
                            task_id="abc", prompt="ocean wave")
    """
    from arq import ArqRedis

    queue = queue_override or select_queue(function_name)

    logger.debug(f"[queue_router] Enqueuing '{function_name}' → queue='{queue}'")

    arq_redis = ArqRedis(pool=redis)
    job = await arq_redis.enqueue_job(
        function_name,
        *args,
        _queue_name=queue,
        _job_id=job_id,
        **kwargs,
    )

    if job:
        logger.info(
            f"[queue_router] Job enqueued: id={job.job_id} "
            f"fn={function_name} queue={queue}"
        )
    else:
        logger.warning(
            f"[queue_router] Job already queued (dedup): fn={function_name} id={job_id}"
        )

    return job


def get_queue_stats_keys() -> Dict[str, str]:
    """Return Redis keys used by ARQ for each queue (useful for monitoring)."""
    return {
        "cpu_queue": f"arq:queue:{CPU_QUEUE}",
        "gpu_queue": f"arq:queue:{GPU_QUEUE}",
        "legacy_queue": f"arq:queue:{LEGACY_QUEUE}",
        "cpu_in_progress": f"arq:in-progress:{CPU_QUEUE}",
        "gpu_in_progress": f"arq:in-progress:{GPU_QUEUE}",
    }
