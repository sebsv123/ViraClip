"""
Audit Logging API — ViraClip

Endpoints for querying the compliance audit trail, exporting logs,
getting per-user activity summaries, and detecting anomalies.
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...services.audit_logging import (
    AuditEventType,
    AuditLogger,
    SeverityLevel,
    get_audit_logger,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/audit", tags=["audit"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class LogEventRequest(BaseModel):
    event_type: str
    severity: str = "info"
    resource_type: str
    resource_id: str
    action: str
    status: str = "success"
    details: Dict[str, Any] = {}
    ip_address: Optional[str] = None


class QueryLogsRequest(BaseModel):
    start_date: Optional[str] = None   # YYYY-MM-DD
    end_date: Optional[str] = None
    event_types: Optional[List[str]] = None
    user_id: Optional[str] = None
    resource_type: Optional[str] = None
    severity: Optional[str] = None
    limit: int = 200


class ExportLogsRequest(BaseModel):
    start_date: str     # YYYY-MM-DD
    end_date: str
    format: str = "json"    # json | csv


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_event_type(value: str) -> AuditEventType:
    try:
        return AuditEventType(value)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid event_type '{value}'. Choose: {[e.value for e in AuditEventType]}",
        )


def _parse_severity(value: str) -> SeverityLevel:
    try:
        return SeverityLevel(value)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid severity '{value}'. Choose: {[s.value for s in SeverityLevel]}",
        )


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/log")
async def log_event(request: Request, body: LogEventRequest):
    """
    Manually log an audit event. Useful for recording admin actions,
    permission changes, or security-relevant operations from external services.
    """
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    audit = get_audit_logger()
    try:
        entry = await audit.log_event(
            event_type=_parse_event_type(body.event_type),
            severity=_parse_severity(body.severity),
            resource_type=body.resource_type,
            resource_id=body.resource_id,
            action=body.action,
            status=body.status,
            user_id=user_id,
            ip_address=body.ip_address or request.client.host if request.client else None,
            details=body.details,
        )
        return {
            "status": "logged",
            "entry_id": entry.entry_id,
            "timestamp": entry.timestamp,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query")
async def query_logs(body: QueryLogsRequest):
    """
    Query the audit log with filters. Returns log entries newest-first.

    All filters are optional — omit to return the most recent entries up to `limit`.
    """
    audit = get_audit_logger()

    event_types = None
    if body.event_types:
        event_types = [_parse_event_type(e) for e in body.event_types]

    severity = _parse_severity(body.severity) if body.severity else None

    try:
        entries = await audit.query_logs(
            start_date=body.start_date,
            end_date=body.end_date,
            event_types=event_types,
            user_id=body.user_id,
            resource_type=body.resource_type,
            severity=severity,
            limit=body.limit,
        )
        return {"status": "success", "count": len(entries), "entries": entries}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/user/{user_id}/summary")
async def user_activity_summary(user_id: str, days: int = 30):
    """
    Get an activity summary for a user over the last N days:
    total events, breakdown by type, unique resources accessed,
    and failed-attempt count.
    """
    audit = get_audit_logger()
    try:
        summary = await audit.get_user_activity_summary(user_id, days=days)
        return {"status": "success", "summary": summary}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/export")
async def export_logs(body: ExportLogsRequest):
    """
    Export audit logs for a date range to a JSON or CSV file.
    Returns the server-side path of the exported file.
    """
    if body.format not in ("json", "csv"):
        raise HTTPException(status_code=400, detail="format must be 'json' or 'csv'")

    audit = get_audit_logger()
    try:
        export_path = await audit.export_logs(
            start_date=body.start_date,
            end_date=body.end_date,
            format=body.format,
        )
        return {
            "status": "exported",
            "export_path": str(export_path),
            "start_date": body.start_date,
            "end_date": body.end_date,
            "format": body.format,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/anomalies")
async def detect_anomalies(user_id: Optional[str] = None, hours: int = 24):
    """
    Detect suspicious activity patterns (e.g., multiple failed logins)
    within the specified time window.
    """
    audit = get_audit_logger()
    try:
        anomalies = await audit.detect_anomalies(user_id=user_id, hours=hours)
        return {
            "status": "success",
            "anomaly_count": len(anomalies),
            "anomalies": anomalies,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/event-types")
def list_event_types():
    """List all audit event types and severity levels."""
    return {
        "event_types": [e.value for e in AuditEventType],
        "severity_levels": [s.value for s in SeverityLevel],
    }
