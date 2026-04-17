"""
Real-time Dashboard API — ViraClip

HTTP endpoints for metric registration, recording, history retrieval,
dashboard summaries, and custom dashboard configuration.
(WebSocket streaming is handled by the service internally when connected.)
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.realtime_dashboard import (
    MetricType,
    TimeRange,
    get_dashboard_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard", tags=["dashboard"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class RegisterMetricRequest(BaseModel):
    metric_id: str
    name: str
    metric_type: str        # counter | gauge | histogram | rate
    description: str
    unit: str = ""
    aggregation: str = "avg"    # sum | avg | max | min | count


class RecordMetricRequest(BaseModel):
    metric_id: str
    value: float
    labels: Optional[Dict[str, str]] = None


class CustomDashboardRequest(BaseModel):
    user_id: str
    name: str
    metric_ids: List[str]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_metric_type(value: str) -> MetricType:
    try:
        return MetricType(value.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown metric_type '{value}'. Valid: {[m.value for m in MetricType]}",
        )


def _parse_time_range(value: str) -> TimeRange:
    try:
        return TimeRange(value)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown time_range '{value}'. Valid: {[t.value for t in TimeRange]}",
        )


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/metrics")
def register_metric(body: RegisterMetricRequest):
    """
    Register a new metric for dashboard tracking.

    `metric_type`: `counter` | `gauge` | `histogram` | `rate`
    `aggregation`: `sum` | `avg` | `max` | `min` | `count`
    """
    metric_type = _parse_metric_type(body.metric_type)
    svc = get_dashboard_service()
    metric = svc.register_metric(
        body.metric_id, body.name, metric_type,
        body.description, body.unit, body.aggregation,
    )
    return {
        "status": "registered",
        "metric": {
            "metric_id": metric.metric_id,
            "name": metric.name,
            "metric_type": metric.metric_type.value,
            "description": metric.description,
            "unit": metric.unit,
            "aggregation": metric.aggregation,
            "current_value": metric.current_value,
        },
    }


@router.post("/metrics/record")
async def record_metric(body: RecordMetricRequest):
    """
    Record a single metric value. Broadcasts to connected WebSocket clients.

    If the metric has not been registered, the call is silently ignored.
    """
    svc = get_dashboard_service()
    await svc.record_metric(body.metric_id, body.value, body.labels)
    return {"status": "recorded", "metric_id": body.metric_id, "value": body.value}


@router.get("/metrics/{metric_id}/history")
def get_metric_history(metric_id: str, time_range: str = "1h"):
    """
    Get historical data points for a metric.

    `time_range`: `1h` | `24h` | `7d` | `30d`
    """
    tr = _parse_time_range(time_range)
    svc = get_dashboard_service()
    history = svc.get_metric_history(metric_id, tr)
    return {
        "metric_id": metric_id,
        "time_range": time_range,
        "count": len(history),
        "data_points": history,
    }


@router.get("/summary")
def dashboard_summary():
    """
    Get a snapshot of all registered metrics with their current values.

    Returns `active_metrics`, `active_connections`, `total_data_points`,
    and a list of each metric's `current_value`.
    """
    svc = get_dashboard_service()
    return {"status": "success", "summary": svc.get_dashboard_summary()}


@router.post("/custom")
def create_custom_dashboard(body: CustomDashboardRequest):
    """
    Create a custom dashboard configuration for a user.

    `metric_ids` is the ordered list of metrics to show on the dashboard.
    """
    if not body.metric_ids:
        raise HTTPException(status_code=400, detail="metric_ids must not be empty")
    svc = get_dashboard_service()
    dashboard = svc.create_custom_dashboard(body.user_id, body.name, body.metric_ids)
    return {"status": "created", "dashboard": dashboard}


@router.get("/time-ranges")
def list_time_ranges():
    """List all supported time range values."""
    return {"time_ranges": [t.value for t in TimeRange]}


@router.get("/metric-types")
def list_metric_types():
    """List all supported metric types."""
    return {"metric_types": [m.value for m in MetricType]}
