"""
AI Inference Optimization API — ViraClip

Optimize AI models (TensorRT/ONNX/OpenVINO/quantization), run batched
inference, and monitor GPU performance profiles.
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.ai_inference_optimization import (
    get_inference_optimization_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai-inference", tags=["ai-inference"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class OptimizeRequest(BaseModel):
    model_id: str
    model_path: str
    target_format: str = "tensorrt"     # "tensorrt" | "onnx" | "openvino"
    precision: str = "fp16"             # "fp32" | "fp16" | "int8"
    batch_size: int = 1


class InferRequest(BaseModel):
    model_id: str
    inputs: List[Any]
    use_cache: bool = True


class QuantizeRequest(BaseModel):
    model_id: str
    bits: int = 8


class PruneRequest(BaseModel):
    model_id: str
    sparsity: float = 0.5


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/optimize")
async def optimize_model(body: OptimizeRequest):
    """
    Optimize an AI model for fast real-time inference.

    Converts to TensorRT / ONNX / OpenVINO and benchmarks latency.
    Returns a model profile with original vs. optimized latency.
    """
    from pathlib import Path
    svc = get_inference_optimization_service()
    try:
        profile = await svc.optimize_model(
            body.model_id,
            Path(body.model_path),
            body.target_format,
            body.precision,
            body.batch_size,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "optimized",
        "profile": {
            "model_id": profile.model_id,
            "original_format": profile.original_format.value,
            "optimized_format": profile.optimized_format.value,
            "original_latency_ms": profile.original_latency_ms,
            "optimized_latency_ms": profile.optimized_latency_ms,
            "throughput_improvement": profile.throughput_improvement,
            "accuracy_loss": profile.accuracy_loss,
        },
    }


@router.post("/infer")
async def run_inference(body: InferRequest):
    """
    Run optimized inference for a model.

    Automatically uses batching when the queue is full.
    """
    if not body.inputs:
        raise HTTPException(status_code=400, detail="inputs must not be empty")
    svc = get_inference_optimization_service()
    try:
        results = await svc.infer_optimized(body.model_id, body.inputs, body.use_cache)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "success", "model_id": body.model_id, "results": results}


@router.post("/quantize")
async def quantize_model(body: QuantizeRequest):
    """Quantize an optimized model to INT8 or INT4 for lower memory/latency."""
    if body.bits not in (4, 8):
        raise HTTPException(status_code=400, detail="bits must be 4 or 8")
    svc = get_inference_optimization_service()
    try:
        success = await svc.quantize_model(body.model_id, body.bits)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not success:
        raise HTTPException(status_code=404, detail=f"Model '{body.model_id}' not found")
    return {"status": "quantized", "model_id": body.model_id, "bits": body.bits}


@router.post("/prune")
async def prune_model(body: PruneRequest):
    """Prune a model by removing low-weight connections to reduce size."""
    if not 0.0 < body.sparsity < 1.0:
        raise HTTPException(status_code=400, detail="sparsity must be between 0 and 1")
    svc = get_inference_optimization_service()
    try:
        success = await svc.prune_model(body.model_id, body.sparsity)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not success:
        raise HTTPException(status_code=404, detail=f"Model '{body.model_id}' not found")
    return {"status": "pruned", "model_id": body.model_id, "sparsity": body.sparsity}


@router.get("/profiles/{model_id}")
def get_model_profile(model_id: str):
    """Get the optimization profile for a specific model."""
    svc = get_inference_optimization_service()
    profile = svc.get_model_profile(model_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"No profile for model '{model_id}'")
    return {
        "model_id": profile.model_id,
        "optimized_format": profile.optimized_format.value,
        "throughput_improvement": profile.throughput_improvement,
        "optimized_latency_ms": profile.optimized_latency_ms,
    }


@router.get("/profiles")
def list_profiles():
    """List all model optimization profiles."""
    svc = get_inference_optimization_service()
    profiles = svc.get_all_profiles()
    return {"count": len(profiles), "profiles": [
        {"model_id": p.model_id, "optimized_format": p.optimized_format.value,
         "throughput_improvement": p.throughput_improvement}
        for p in profiles
    ]}


@router.get("/stats")
def inference_stats():
    """Get inference optimization service statistics."""
    svc = get_inference_optimization_service()
    return {"status": "success", "stats": svc.get_optimization_stats()}
