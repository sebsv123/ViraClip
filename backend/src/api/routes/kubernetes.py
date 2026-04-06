"""
Kubernetes Scaling API Routes
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ...services.kubernetes_scaling import get_kubernetes_scaling_service

router = APIRouter(prefix="/kubernetes", tags=["Kubernetes Scaling"])


class ExecuteScalingRequest(BaseModel):
    decision: Dict[str, Any]


@router.get("/metrics")
async def get_cluster_metrics() -> Dict[str, Any]:
    """Get current Kubernetes cluster metrics (CPU, queue depth, active workers)."""
    svc = get_kubernetes_scaling_service()
    try:
        return await svc.get_cluster_metrics()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/workers")
async def get_worker_status() -> Dict[str, Any]:
    """Get status of all worker pods."""
    svc = get_kubernetes_scaling_service()
    try:
        pods = svc.get_worker_status()
        return {"worker_count": len(pods), "workers": pods}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scaling/history")
async def get_scaling_history(limit: int = Query(50, ge=1, le=500)) -> Dict[str, Any]:
    """Get recent scaling events history."""
    svc = get_kubernetes_scaling_service()
    try:
        history = svc.get_scaling_history(limit=limit)
        return {"limit": limit, "event_count": len(history), "events": history}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scaling/stats")
async def get_scaling_stats() -> Dict[str, Any]:
    """Get aggregate scaling statistics."""
    svc = get_kubernetes_scaling_service()
    try:
        return svc.get_scaling_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scaling/evaluate")
async def evaluate_scaling_needs() -> Dict[str, Any]:
    """Evaluate whether scaling is currently needed based on cluster metrics."""
    svc = get_kubernetes_scaling_service()
    try:
        decision = await svc.evaluate_scaling_needs()
        return decision if decision else {"action": "none", "reason": "No scaling needed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scaling/predict")
async def predict_scaling_needs(
    lookahead_minutes: int = Query(30, ge=5, le=180)
) -> Dict[str, Any]:
    """Predict scaling needs over a future lookahead window."""
    svc = get_kubernetes_scaling_service()
    try:
        return await svc.predict_scaling_needs(lookahead_minutes=lookahead_minutes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scaling/auto")
async def auto_scale() -> Dict[str, Any]:
    """Run auto-scaling evaluation and execute if needed."""
    svc = get_kubernetes_scaling_service()
    try:
        event = await svc.auto_scale()
        if event is None:
            return {"scaled": False, "reason": "No scaling action taken"}
        return {
            "scaled": True,
            "event_id": event.event_id,
            "timestamp": event.timestamp,
            "action": event.action,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scaling/execute")
async def execute_scaling(body: ExecuteScalingRequest) -> Dict[str, Any]:
    """Execute a specific scaling decision."""
    svc = get_kubernetes_scaling_service()
    try:
        success = await svc.execute_scaling(body.decision)
        return {"decision": body.decision, "executed": success}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
