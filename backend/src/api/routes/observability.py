"""
Observability API — ViraClip

Distributed tracing, span management, and performance monitoring
for production pipeline visibility.
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.observability import get_observability, get_performance_monitor

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/observability", tags=["observability"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class StartSpanRequest(BaseModel):
    span_name: str
    request_id: Optional[str] = None
    labels: Optional[dict] = None


class EndSpanRequest(BaseModel):
    span_id: str
    status: str = "success"     # "success" | "error"
    metadata: Optional[dict] = None


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/spans/start")
def start_span(body: StartSpanRequest):
    """
    Start a distributed tracing span.

    Returns the `span_id` to pass to `POST /spans/end`.
    """
    obs = get_observability()
    try:
        span_id = obs.start_span(body.span_name, body.request_id, body.labels)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "started", "span_id": span_id}


@router.post("/spans/end")
def end_span(body: EndSpanRequest):
    """End a distributed tracing span and record its duration."""
    obs = get_observability()
    try:
        obs.end_span(body.span_id, body.status, body.metadata)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "ended", "span_id": body.span_id}


@router.get("/spans/{request_id}")
def span_tree(request_id: str):
    """
    Get all tracing spans for a given request ID as a tree.
    """
    obs = get_observability()
    spans = obs.get_span_tree(request_id)
    return {"request_id": request_id, "count": len(spans), "spans": spans}


@router.get("/performance/{operation}")
def operation_stats(operation: str):
    """
    Get timing statistics for a named operation: mean, p50, p95, p99, count.
    """
    monitor = get_performance_monitor()
    stats = monitor.get_stats(operation)
    if not stats:
        raise HTTPException(status_code=404, detail=f"No data for operation '{operation}'")
    return {"operation": operation, "stats": stats}


@router.get("/health")
def observability_health():
    """Quick health check — returns active span count and monitor status."""
    obs = get_observability()
    monitor = get_performance_monitor()
    return {
        "status": "ok",
        "active_spans": len(obs._spans),
        "tracked_operations": len(monitor._operation_times),
    }
