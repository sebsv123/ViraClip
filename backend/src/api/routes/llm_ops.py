"""
LLM operations routes — dataset stats, routing status, export, optimization.
"""
import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional

from ...config import get_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/llm-ops", tags=["llm-ops"])


# ─────────────────────────────────────────────────────────────────────────────
# Dataset endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/dataset/stats", summary="Get LLM training dataset statistics")
async def dataset_stats():
    """Returns total examples, ratings breakdown, and readiness thresholds."""
    from ...services.dataset_collector import get_dataset_collector
    config = get_config()
    collector = get_dataset_collector(config.dataset_dir)
    return await collector.get_stats()


@router.get("/dataset/export/dspy", summary="Export dataset in DSPy format")
async def export_dspy():
    """Export rated examples for DSPy optimization (requires 50+ examples)."""
    from ...services.dataset_collector import get_dataset_collector
    config = get_config()
    collector = get_dataset_collector(config.dataset_dir)

    stats = await collector.get_stats()
    if not stats["ready_for_dspy"]:
        raise HTTPException(
            status_code=400,
            detail=f"Need 50+ examples for DSPy, currently have {stats['total_examples']}"
        )

    path = await collector.export_for_dspy()
    return {"exported_to": path, "examples": stats["total_examples"]}


@router.get("/dataset/export/finetuning", summary="Export dataset for fine-tuning")
async def export_finetuning():
    """Export positive examples in JSONL fine-tuning format (requires 200+ examples)."""
    from ...services.dataset_collector import get_dataset_collector
    config = get_config()
    collector = get_dataset_collector(config.dataset_dir)

    stats = await collector.get_stats()
    if not stats["ready_for_finetuning"]:
        raise HTTPException(
            status_code=400,
            detail=f"Need 200+ examples for fine-tuning, currently have {stats['total_examples']}"
        )

    path = await collector.export_for_finetuning()
    return {"exported_to": path, "positive_examples": stats["positive"]}


# ─────────────────────────────────────────────────────────────────────────────
# LLM routing endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/routing/status", summary="Get current LLM routing configuration")
async def routing_status():
    """Returns which backend is active and the dataset size thresholds."""
    from ...services.llm_router import get_llm_router
    from ...services.dataset_collector import get_dataset_collector
    from ...config import get_config

    config = get_config()
    router_svc = get_llm_router()
    collector = get_dataset_collector(config.dataset_dir)

    stats = await collector.get_stats()
    routing = await router_svc.get_routing_stats()

    return {
        "current_backend": routing["current_backend"],
        "dataset_size": stats["total_examples"],
        "thresholds": routing["thresholds"],
        "dspy_ready": stats["ready_for_dspy"],
        "finetuning_ready": stats["ready_for_finetuning"],
        "routing_enabled": config.llm_routing_enabled,
    }


class OptimizeRequest(BaseModel):
    teacher_model: str = "claude-3-5-sonnet-20241022"
    student_model: str = "ollama/qwen3-vl:8b"
    trials: int = 10


@router.post("/optimize/dspy", summary="Trigger DSPy optimization (background)")
async def trigger_dspy_optimization(body: OptimizeRequest, background_tasks: BackgroundTasks):
    """
    Launches DSPy prompt optimization in the background.
    Requires 50+ rated examples in the dataset.
    """
    from ...services.dataset_collector import get_dataset_collector
    from ...config import get_config

    config = get_config()
    collector = get_dataset_collector(config.dataset_dir)
    stats = await collector.get_stats()

    if not stats["ready_for_dspy"]:
        raise HTTPException(
            status_code=400,
            detail=f"Need 50+ examples, currently have {stats['total_examples']}"
        )

    async def _run_optimization():
        from ...services.dspy_optimizer import DSPyOptimizer
        try:
            dspy_path = f"{config.dataset_dir}/dspy_dataset.json"
            await collector.export_for_dspy(dspy_path)
            optimizer = DSPyOptimizer(dspy_path)
            result = await optimizer.optimize(
                teacher_model=body.teacher_model,
                student_model=body.student_model,
                trials=body.trials,
            )
            if result.get("success"):
                await optimizer.save_optimized_prompt(config.dspy_optimized_prompt_path)
                logger.info(f"✅ DSPy optimization complete: {result.get('dev_accuracy', 0):.2%}")
            else:
                logger.error(f"❌ DSPy optimization failed: {result.get('error')}")
        except Exception as e:
            logger.error(f"DSPy background task error: {e}", exc_info=True)

    background_tasks.add_task(_run_optimization)

    return {
        "status": "started",
        "message": "DSPy optimization running in background",
        "examples_used": stats["total_examples"],
        "teacher_model": body.teacher_model,
        "student_model": body.student_model,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Rust agent endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/rust-agent/status", summary="Check Rust agent availability")
async def rust_agent_status():
    """Returns Rust agent health and available tools."""
    from ...services.rust_bridge import get_rust_bridge
    bridge = get_rust_bridge()

    healthy = await bridge.health_check()

    if not healthy:
        return {"available": False, "url": bridge.base_url}

    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{bridge.base_url}/agent/health")
            data = r.json()
        return {
            "available": True,
            "url": bridge.base_url,
            "version": data.get("version"),
            "tools": data.get("tools_available", []),
            "ffmpeg_available": data.get("ffmpeg_available", False),
        }
    except Exception as e:
        return {"available": False, "url": bridge.base_url, "error": str(e)}
