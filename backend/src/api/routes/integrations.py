"""
Third-Party Integrations API — ViraClip

Register webhooks for Zapier, Make, n8n, IFTTT, Google Sheets, etc.
and trigger integration events when clips are created/published/go viral.
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.third_party_integrations import (
    IntegrationType,
    TriggerEvent,
    get_integration_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/integrations", tags=["integrations"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class RegisterWebhookRequest(BaseModel):
    user_id: str
    integration_type: str       # IntegrationType value
    trigger_event: str          # TriggerEvent value
    webhook_url: str
    headers: Optional[Dict[str, str]] = None


class TriggerRequest(BaseModel):
    user_id: str
    event: str              # TriggerEvent value
    data: Dict[str, Any]


class ToggleRequest(BaseModel):
    active: bool


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_integration(value: str) -> IntegrationType:
    try:
        return IntegrationType(value.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown integration_type '{value}'. Valid: {[t.value for t in IntegrationType]}",
        )


def _parse_event(value: str) -> TriggerEvent:
    try:
        return TriggerEvent(value.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown event '{value}'. Valid: {[e.value for e in TriggerEvent]}",
        )


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/webhooks")
async def register_webhook(body: RegisterWebhookRequest):
    """
    Register a webhook for a third-party integration.

    `integration_type`: `zapier` | `make` | `n8n` | `ifttt` | `google_sheets`
    `events`: list of trigger event names, e.g. `["clip_created", "clip_viral"]`
    """
    if not body.webhook_url.startswith("http"):
        raise HTTPException(status_code=400, detail="webhook_url must be a valid HTTP URL")

    integration_type = _parse_integration(body.integration_type)
    trigger_event = _parse_event(body.trigger_event)
    svc = get_integration_service()
    try:
        webhook = await svc.register_webhook(
            body.user_id, integration_type, trigger_event, body.webhook_url, body.headers
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "registered",
        "webhook": {
            "webhook_id": webhook.webhook_id,
            "user_id": webhook.user_id,
            "integration_type": webhook.integration_type.value,
            "trigger_event": webhook.trigger_event.value,
            "webhook_url": webhook.webhook_url,
            "is_active": webhook.is_active,
        },
    }


@router.get("/webhooks/{user_id}")
def list_integrations(user_id: str):
    """List all registered integrations for a user."""
    svc = get_integration_service()
    integrations = svc.get_user_integrations(user_id)
    return {"count": len(integrations), "integrations": integrations}


@router.patch("/webhooks/{webhook_id}/toggle")
async def toggle_integration(webhook_id: str, body: ToggleRequest):
    """Enable or disable a webhook integration."""
    svc = get_integration_service()
    success = await svc.toggle_integration(webhook_id, body.active)
    if not success:
        raise HTTPException(status_code=404, detail=f"Webhook '{webhook_id}' not found")
    return {"status": "active" if body.active else "disabled", "webhook_id": webhook_id}


@router.delete("/webhooks/{webhook_id}")
async def delete_integration(webhook_id: str):
    """Delete a webhook integration."""
    svc = get_integration_service()
    success = await svc.delete_integration(webhook_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Webhook '{webhook_id}' not found")
    return {"status": "deleted", "webhook_id": webhook_id}


@router.post("/trigger")
async def trigger_event(body: TriggerRequest):
    """
    Manually trigger an integration event for a user.

    Fires all active webhooks subscribed to the given event.
    Returns per-webhook delivery results.
    """
    event = _parse_event(body.event)
    svc = get_integration_service()
    try:
        results = await svc.trigger_integration(body.user_id, event, body.data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "triggered", "event": body.event, "results": results}


@router.get("/stats")
def integration_stats():
    """Get integration delivery statistics."""
    svc = get_integration_service()
    return {"status": "success", "stats": svc.get_integration_stats()}


@router.get("/types")
def list_types():
    """List supported integration platforms and trigger events."""
    return {
        "integration_types": [t.value for t in IntegrationType],
        "trigger_events": [e.value for e in TriggerEvent],
    }
