"""
Unit Tests — Phase 5.2: GPU Worker Tier
=========================================
Tests for queue routing, GpuWorkerSettings, and graceful CPU fallback.
"""

import os
import pytest
from unittest.mock import patch


class TestQueueRouter:
    """Test queue routing logic."""

    def test_cpu_tasks_go_to_cpu_queue(self):
        from workers.queue_router import select_queue, CPU_QUEUE

        assert select_queue("process_video_task") == CPU_QUEUE

    def test_gpu_tasks_go_to_gpu_queue_when_enabled(self):
        from workers.queue_router import select_queue, GPU_QUEUE

        with patch.dict(os.environ, {"GPU_WORKER_ENABLED": "true"}):
            assert select_queue("generate_broll_t2v") == GPU_QUEUE
            assert select_queue("upscale_clip") == GPU_QUEUE
            assert select_queue("generate_tts_narration") == GPU_QUEUE
            assert select_queue("train_virality_lora") == GPU_QUEUE
            assert select_queue("generate_optical_flow_transition") == GPU_QUEUE

    def test_gpu_tasks_fallback_to_cpu_when_disabled(self):
        from workers.queue_router import select_queue, CPU_QUEUE

        with patch.dict(os.environ, {"GPU_WORKER_ENABLED": "false"}):
            assert select_queue("generate_broll_t2v") == CPU_QUEUE
            assert select_queue("upscale_clip") == CPU_QUEUE

    def test_force_cpu_override(self):
        from workers.queue_router import select_queue, CPU_QUEUE

        with patch.dict(os.environ, {"GPU_WORKER_ENABLED": "true"}):
            # Even GPU task goes to CPU when force_cpu=True
            assert select_queue("generate_broll_t2v", force_cpu=True) == CPU_QUEUE

    def test_requires_gpu_classification(self):
        from workers.queue_router import requires_gpu

        # GPU tasks
        assert requires_gpu("generate_broll_t2v") is True
        assert requires_gpu("upscale_clip") is True
        assert requires_gpu("generate_optical_flow_transition") is True
        assert requires_gpu("generate_tts_narration") is True
        assert requires_gpu("train_virality_lora") is True

        # CPU tasks
        assert requires_gpu("process_video_task") is False
        assert requires_gpu("periodic_model_retraining") is False
        assert requires_gpu("unknown_task") is False

    def test_queue_constants(self):
        from workers.queue_router import CPU_QUEUE, GPU_QUEUE, LEGACY_QUEUE

        assert CPU_QUEUE == "viraclip_cpu_tasks"
        assert GPU_QUEUE == "viraclip_gpu_tasks"
        assert LEGACY_QUEUE == "viraclip_tasks"

    def test_get_queue_stats_keys(self):
        from workers.queue_router import get_queue_stats_keys, CPU_QUEUE, GPU_QUEUE

        keys = get_queue_stats_keys()

        assert "cpu_queue" in keys
        assert "gpu_queue" in keys
        assert CPU_QUEUE in keys["cpu_queue"]
        assert GPU_QUEUE in keys["gpu_queue"]
        assert "in-progress" in keys["cpu_in_progress"]


class TestCpuWorkerSettings:
    """Test CPU WorkerSettings configuration."""

    def test_cpu_queue_name(self):
        from workers.tasks import WorkerSettings

        assert WorkerSettings.queue_name == "viraclip_cpu_tasks"

    def test_cpu_worker_has_process_video_task(self):
        from workers.tasks import WorkerSettings, process_video_task

        assert process_video_task in WorkerSettings.functions

    def test_cpu_worker_max_jobs(self):
        from workers.tasks import WorkerSettings

        # 1 job per worker keeps CPU saturation manageable
        assert WorkerSettings.max_jobs == 1

    def test_cpu_worker_timeout(self):
        from workers.tasks import WorkerSettings

        # 1 hour is sufficient for CPU video processing
        assert WorkerSettings.job_timeout == 3600


class TestGpuWorkerSettings:
    """Test GpuWorkerSettings configuration."""

    def test_gpu_queue_name(self):
        from workers.gpu_tasks import GpuWorkerSettings

        assert GpuWorkerSettings.queue_name == "viraclip_gpu_tasks"

    def test_gpu_worker_has_all_gpu_tasks(self):
        from workers.gpu_tasks import (
            GpuWorkerSettings,
            generate_broll_t2v,
            upscale_clip,
            generate_optical_flow_transition,
            generate_tts_narration,
            train_virality_lora,
        )

        funcs = GpuWorkerSettings.functions
        assert generate_broll_t2v in funcs
        assert upscale_clip in funcs
        assert generate_optical_flow_transition in funcs
        assert generate_tts_narration in funcs
        assert train_virality_lora in funcs

    def test_gpu_worker_single_job(self):
        from workers.gpu_tasks import GpuWorkerSettings

        # Only 1 GPU job at a time to avoid VRAM contention
        assert GpuWorkerSettings.max_jobs == 1

    def test_gpu_worker_long_timeout(self):
        from workers.gpu_tasks import GpuWorkerSettings

        # T2V / LoRA can take hours
        assert GpuWorkerSettings.job_timeout >= 3600

    def test_gpu_worker_fewer_retries(self):
        from workers.gpu_tasks import GpuWorkerSettings

        # GPU OOM errors usually aren't retriable; keep retries low
        assert GpuWorkerSettings.max_tries <= 3

    def test_gpu_queues_are_different(self):
        from workers.tasks import WorkerSettings
        from workers.gpu_tasks import GpuWorkerSettings

        assert WorkerSettings.queue_name != GpuWorkerSettings.queue_name


class TestGpuTaskFunctions:
    """Test GPU task function signatures."""

    def test_broll_task_signature(self):
        import inspect
        from workers.gpu_tasks import generate_broll_t2v

        sig = inspect.signature(generate_broll_t2v)
        params = sig.parameters

        assert "ctx" in params
        assert "task_id" in params
        assert "prompt" in params
        assert "model" in params
        assert "duration_seconds" in params

    def test_upscale_task_signature(self):
        import inspect
        from workers.gpu_tasks import upscale_clip

        sig = inspect.signature(upscale_clip)
        params = sig.parameters

        assert "ctx" in params
        assert "task_id" in params
        assert "input_path" in params
        assert "scale_factor" in params

    def test_tts_task_signature(self):
        import inspect
        from workers.gpu_tasks import generate_tts_narration

        sig = inspect.signature(generate_tts_narration)
        params = sig.parameters

        assert "text" in params
        assert "language" in params
        assert "model" in params

    def test_lora_task_signature(self):
        import inspect
        from workers.gpu_tasks import train_virality_lora

        sig = inspect.signature(train_virality_lora)
        params = sig.parameters

        assert "dataset_path" in params
        assert "base_model" in params
        assert "num_steps" in params


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
