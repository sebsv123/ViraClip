"""
Email Reports API — ViraClip

Subscribe to scheduled email reports (daily/weekly/monthly analytics),
generate on-demand reports, and manage subscriptions.
"""

import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.email_reports import ReportType, get_email_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/email-reports", tags=["email-reports"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class SubscribeRequest(BaseModel):
    user_id: str
    email: str
    report_type: str        # ReportType value
    frequency: str = "weekly"


class GenerateRequest(BaseModel):
    user_id: str
    report_type: str
    send_immediately: bool = False
    email: Optional[str] = None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_report_type(value: str) -> ReportType:
    try:
        return ReportType(value.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown report_type '{value}'. Valid: {[r.value for r in ReportType]}",
        )


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/subscribe")
async def subscribe(body: SubscribeRequest):
    """
    Subscribe a user to automated email reports.

    `report_type`: `analytics` | `performance` | `virality` | `weekly_summary`
    `frequency`: `daily` | `weekly` | `monthly`
    """
    if "@" not in body.email:
        raise HTTPException(status_code=400, detail="Invalid email address")
    report_type = _parse_report_type(body.report_type)
    svc = get_email_service()
    try:
        subscription = await svc.subscribe(body.user_id, body.email, report_type, body.frequency)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "subscribed",
        "subscription": {
            "subscription_id": subscription.subscription_id,
            "user_id": subscription.user_id,
            "email": subscription.email,
            "report_type": subscription.report_type.value,
            "frequency": subscription.frequency,
            "is_active": subscription.is_active,
        },
    }


@router.get("/subscriptions/{user_id}")
def list_subscriptions(user_id: str):
    """List all active report subscriptions for a user."""
    svc = get_email_service()
    subscriptions = svc.list_user_subscriptions(user_id)
    return {"count": len(subscriptions), "subscriptions": subscriptions}


@router.delete("/subscriptions/{subscription_id}")
async def unsubscribe(subscription_id: str):
    """Cancel a report subscription."""
    svc = get_email_service()
    success = await svc.unsubscribe(subscription_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Subscription '{subscription_id}' not found")
    return {"status": "unsubscribed", "subscription_id": subscription_id}


@router.post("/generate")
async def generate_report(body: GenerateRequest):
    """
    Generate an on-demand report and optionally send it via email.

    Returns the report record; set `send_immediately=true` to also dispatch the email.
    """
    if "@" not in (body.email or "a@b"):
        raise HTTPException(status_code=400, detail="Invalid email address")
    report_type = _parse_report_type(body.report_type)
    svc = get_email_service()
    try:
        report = await svc.generate_report(body.user_id, report_type)
        if body.send_immediately:
            await svc.send_report(report.report_id, body.email)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "generated",
        "report": {
            "report_id": report.report_id,
            "user_id": report.user_id,
            "report_type": report.report_type.value,
            "status": report.status,
            "created_at": report.created_at,
        },
    }


@router.post("/send/{report_id}")
async def send_report(report_id: str, email: Optional[str] = None):
    """Send a previously generated report by email."""
    svc = get_email_service()
    success = await svc.send_report(report_id, email)
    if not success:
        raise HTTPException(status_code=404, detail=f"Report '{report_id}' not found or send failed")
    return {"status": "sent", "report_id": report_id}


@router.post("/process-scheduled")
async def process_scheduled():
    """Trigger processing of all due scheduled reports (admin / cron endpoint)."""
    svc = get_email_service()
    sent = await svc.process_scheduled_reports()
    return {"status": "success", "reports_sent": len(sent), "report_ids": sent}


@router.get("/stats")
def report_stats():
    """Get email report delivery statistics."""
    svc = get_email_service()
    return {"status": "success", "stats": svc.get_report_stats()}


@router.get("/report-types")
def list_report_types():
    """List all supported report types."""
    return {"report_types": [r.value for r in ReportType]}
