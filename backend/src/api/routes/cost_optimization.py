"""
Cost Optimization API — ViraClip

Track cloud resource usage, monitor cost alerts, and run optimization
analysis to reduce infrastructure spend.
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.cost_optimization import (
    CostAlertSeverity,
    ResourceType,
    get_cost_optimization_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cost", tags=["cost-optimization"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class TrackUsageRequest(BaseModel):
    resource_type: str      # ResourceType value
    usage_amount: float
    metadata: Optional[dict] = None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_resource(value: str) -> ResourceType:
    try:
        return ResourceType(value.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown resource_type '{value}'. Valid: {[r.value for r in ResourceType]}",
        )


def _parse_severity(value: str) -> CostAlertSeverity:
    try:
        return CostAlertSeverity(value.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown severity '{value}'. Valid: {[s.value for s in CostAlertSeverity]}",
        )


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/track")
async def track_usage(body: TrackUsageRequest):
    """
    Record resource usage for cost tracking.

    `resource_type`: `compute` | `storage` | `bandwidth` | `api_calls` | `cache`
    `usage_amount`: units consumed (GB, calls, CPU-hours, etc.)
    """
    resource = _parse_resource(body.resource_type)
    svc = get_cost_optimization_service()
    try:
        usage = await svc.track_usage(resource, body.usage_amount, body.metadata)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "tracked",
        "usage": {
            "resource_type": usage.resource_type.value,
            "usage_amount": usage.usage_amount,
            "cost_usd": usage.cost_usd,
            "timestamp": usage.timestamp,
        },
    }


@router.get("/summary")
def cost_summary(days: int = 30):
    """
    Get cost summary for the past N days.

    Returns total cost, per-resource breakdown, and active alert count.
    """
    if days < 1 or days > 365:
        raise HTTPException(status_code=400, detail="days must be between 1 and 365")
    svc = get_cost_optimization_service()
    return {"status": "success", "summary": svc.get_cost_summary(days)}


@router.get("/alerts")
def list_alerts(severity: Optional[str] = None, resource_type: Optional[str] = None):
    """
    List active cost alerts, optionally filtered by severity or resource type.
    """
    svc = get_cost_optimization_service()
    severity_enum = _parse_severity(severity) if severity else None
    resource_enum = _parse_resource(resource_type) if resource_type else None
    alerts = svc.get_alerts(severity_enum, resource_enum)
    return {"count": len(alerts), "alerts": alerts}


@router.post("/optimize")
async def optimize_resources():
    """
    Run a resource optimization analysis and return cost-saving recommendations.
    """
    svc = get_cost_optimization_service()
    try:
        result = await svc.optimize_resources()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "analyzed", "result": result}


@router.get("/resource-types")
def list_resource_types():
    """List all supported resource types and their unit costs."""
    svc = get_cost_optimization_service()
    return {
        "resource_types": [r.value for r in ResourceType],
        "unit_costs": {k.value: v for k, v in svc._resource_rates.items()},
    }
