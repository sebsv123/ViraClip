"""
Webhook Management API — ViraClip

Endpoints for registering, managing, and triggering webhook endpoints
for third-party integrations.
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.webhook_service import (
    WebhookEventType,
    get_webhook_manager,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class RegisterRequest(BaseModel):
    user_id: str
    url: str
    secret: str
    events: List[str]           # WebhookEventType values
    headers: Optional[Dict[str, str]] = None


class TriggerRequest(BaseModel):
    user_id: str
    event_type: str
    payload: Dict[str, Any]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_events(raw: List[str]) -> List[WebhookEventType]:
    valid = {e.value for e in WebhookEventType}
    parsed = []
    for ev in raw:
        if ev not in valid:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown event type '{ev}'. Valid: {sorted(valid)}",
            )
        parsed.append(WebhookEventType(ev))
    return parsed


def _fmt_endpoint(ep) -> Dict[str, Any]:
    return {
        "endpoint_id": ep.endpoint_id,
        "url": ep.url,
        "events": [e.value for e in ep.events],
        "is_active": ep.is_active,
        "created_at": ep.created_at,
        "retry_count": ep.retry_count,
        "timeout_seconds": ep.timeout_seconds,
    }


def _fmt_delivery(d) -> Dict[str, Any]:
    return {
        "delivery_id": d.delivery_id,
        "endpoint_id": d.endpoint_id,
        "event_type": d.event_type.value,
        "status": d.status,
        "attempts": d.attempts,
        "http_status": d.http_status,
        "created_at": d.created_at,
        "delivered_at": d.delivered_at,
        "error_message": d.error_message,
    }


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/endpoints")
def register_endpoint(body: RegisterRequest):
    """
    Register a new webhook endpoint.

    `events` must be a subset of the supported event types
    (see GET /webhooks/events). A shared `secret` is used to sign
    each delivery with `X-Webhook-Signature: sha256=...`.
    """
    if not body.url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="url must start with http:// or https://")
    if not body.events:
        raise HTTPException(status_code=400, detail="events must not be empty")

    event_types = _parse_events(body.events)
    mgr = get_webhook_manager()
    endpoint = mgr.register_endpoint(
        body.user_id, body.url, body.secret, event_types, body.headers
    )
    return {"status": "registered", "endpoint": _fmt_endpoint(endpoint)}


@router.get("/endpoints/{user_id}")
def list_endpoints(user_id: str):
    """List all webhook endpoints registered by a user."""
    mgr = get_webhook_manager()
    endpoints = mgr.get_user_endpoints(user_id)
    return {"count": len(endpoints), "endpoints": [_fmt_endpoint(e) for e in endpoints]}


@router.delete("/endpoints/{user_id}/{endpoint_id}")
def delete_endpoint(user_id: str, endpoint_id: str):
    """Delete a webhook endpoint."""
    mgr = get_webhook_manager()
    deleted = mgr.delete_endpoint(user_id, endpoint_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Endpoint '{endpoint_id}' not found")
    return {"status": "deleted", "endpoint_id": endpoint_id}


@router.post("/trigger")
async def trigger_event(body: TriggerRequest):
    """
    Manually trigger a webhook event for all matching active endpoints.

    Returns the list of delivery records (with status/http_status/attempts).
    """
    event_type = _parse_events([body.event_type])[0]
    mgr = get_webhook_manager()
    try:
        deliveries = await mgr.trigger_event(body.user_id, event_type, body.payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "triggered",
        "event_type": body.event_type,
        "deliveries": len(deliveries),
        "results": [_fmt_delivery(d) for d in deliveries],
    }


@router.get("/deliveries/{endpoint_id}")
def get_delivery_history(endpoint_id: str, limit: int = 100):
    """Get delivery history for a webhook endpoint."""
    mgr = get_webhook_manager()
    deliveries = mgr.get_delivery_history(endpoint_id, limit)
    return {"count": len(deliveries), "deliveries": [_fmt_delivery(d) for d in deliveries]}


@router.post("/deliveries/{endpoint_id}/retry")
async def retry_failed(endpoint_id: str):
    """Retry all failed deliveries for a webhook endpoint."""
    mgr = get_webhook_manager()
    try:
        retried = await mgr.retry_failed_deliveries(endpoint_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "retried", "endpoint_id": endpoint_id, "retried_count": retried}


@router.get("/events")
def list_event_types():
    """List all supported webhook event types."""
    return {"events": [e.value for e in WebhookEventType]}
