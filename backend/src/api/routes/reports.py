"""
Email Reports API — ViraClip

Endpoints for subscribing to automated email reports, generating
on-demand reports, managing subscriptions, and checking delivery stats.
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...services.email_reports import (
    EmailReportService,
    ReportFrequency,
    ReportType,
    get_email_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reports", tags=["reports"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class SubscribeRequest(BaseModel):
    email: str
    report_type: str            # daily_summary | weekly_analytics | monthly_performance | clip_ready | viral_milestone | system_alert
    frequency: str = "daily"    # realtime | daily | weekly | monthly
    preferences: Dict[str, Any] = {}


class GenerateReportRequest(BaseModel):
    report_type: str
    data: Dict[str, Any] = {}
    send_to: Optional[str] = None   # override email, defaults to subscription email


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_type(value: str) -> ReportType:
    try:
        return ReportType(value)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid report_type '{value}'. Choose: {[t.value for t in ReportType]}",
        )


def _parse_frequency(value: str) -> ReportFrequency:
    try:
        return ReportFrequency(value)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid frequency '{value}'. Choose: {[f.value for f in ReportFrequency]}",
        )


def _fmt_sub(s) -> Dict[str, Any]:
    return {
        "subscription_id": s.subscription_id,
        "user_id": s.user_id,
        "email": s.email,
        "report_type": s.report_type.value,
        "frequency": s.frequency.value,
        "is_active": s.is_active,
        "created_at": s.created_at,
        "last_sent": s.last_sent,
        "preferences": s.preferences,
    }


# ------------------------------------------------------------------
# Subscriptions
# ------------------------------------------------------------------

@router.post("/subscribe")
async def subscribe(request: Request, body: SubscribeRequest):
    """
    Subscribe the current user to automated email reports.

    **report_type**: `daily_summary | weekly_analytics | monthly_performance |
    clip_ready | viral_milestone | system_alert`

    **frequency**: `realtime | daily | weekly | monthly`
    """
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_email_service()
    try:
        sub = await svc.subscribe(
            user_id=user_id,
            email=body.email,
            report_type=_parse_type(body.report_type),
            frequency=_parse_frequency(body.frequency),
            preferences=body.preferences,
        )
        return {"status": "subscribed", "subscription": _fmt_sub(sub)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/subscriptions")
def list_subscriptions(request: Request):
    """List all active subscriptions for the current user."""
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_email_service()
    subs = svc.list_user_subscriptions(user_id)
    return {
        "status": "success",
        "count": len(subs),
        "subscriptions": [_fmt_sub(s) for s in subs],
    }


@router.delete("/subscriptions/{subscription_id}")
async def unsubscribe(subscription_id: str):
    """Cancel (deactivate) a subscription."""
    svc = get_email_service()
    success = await svc.unsubscribe(subscription_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Subscription '{subscription_id}' not found")
    return {"status": "unsubscribed", "subscription_id": subscription_id}


# ------------------------------------------------------------------
# On-demand report generation
# ------------------------------------------------------------------

@router.post("/generate")
async def generate_report(request: Request, body: GenerateReportRequest):
    """
    Generate a report on demand and optionally send it immediately.
    If `send_to` is provided, the report is emailed to that address.
    """
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_email_service()
    try:
        report = await svc.generate_report(
            user_id=user_id,
            report_type=_parse_type(body.report_type),
            data=body.data,
        )
        sent = False
        if body.send_to:
            sent = await svc.send_report(report.report_id, body.send_to)

        return {
            "status": "generated",
            "report_id": report.report_id,
            "subject": report.subject,
            "report_type": report.report_type.value,
            "sent": sent,
            "created_at": report.created_at,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send/{report_id}")
async def send_report(report_id: str, email: Optional[str] = None):
    """Send an already-generated report to the given email (or the user's default)."""
    svc = get_email_service()
    success = await svc.send_report(report_id, email)
    if not success:
        raise HTTPException(status_code=404, detail=f"Report '{report_id}' not found or send failed")
    return {"status": "sent", "report_id": report_id}


@router.post("/process-scheduled")
async def process_scheduled():
    """
    Trigger processing of all due scheduled reports.
    In production this is called by a cron job; this endpoint is for manual trigger / testing.
    """
    svc = get_email_service()
    sent_ids = await svc.process_scheduled_reports()
    return {"status": "processed", "sent_count": len(sent_ids), "report_ids": sent_ids}


# ------------------------------------------------------------------
# Stats & metadata
# ------------------------------------------------------------------

@router.get("/stats")
def get_stats():
    """Overall reporting stats: total/sent/failed/pending + active subscription count."""
    svc = get_email_service()
    stats = svc.get_report_stats()
    return {"status": "success", "stats": stats}


@router.get("/types")
def list_report_types():
    """List all valid report types and frequency options."""
    return {
        "report_types": [t.value for t in ReportType],
        "frequencies": [f.value for f in ReportFrequency],
    }
