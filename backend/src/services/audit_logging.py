"""
Audit Logging Service for Compliance
Tracks all security-relevant events for compliance and forensic analysis.
"""

import json
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class AuditEventType(Enum):
    """Types of audit events."""
    USER_LOGIN = "user_login"
    USER_LOGOUT = "user_logout"
    USER_CREATED = "user_created"
    USER_UPDATED = "user_updated"
    USER_DELETED = "user_deleted"
    VIDEO_UPLOADED = "video_uploaded"
    VIDEO_PROCESSED = "video_processed"
    VIDEO_DELETED = "video_deleted"
    CLIP_CREATED = "clip_created"
    CLIP_EXPORTED = "clip_exported"
    CLIP_PUBLISHED = "clip_published"
    API_KEY_CREATED = "api_key_created"
    API_KEY_REVOKED = "api_key_revoked"
    PERMISSION_GRANTED = "permission_granted"
    PERMISSION_REVOKED = "permission_revoked"
    SETTINGS_CHANGED = "settings_changed"
    DATA_EXPORTED = "data_exported"
    DATA_DELETED = "data_deleted"
    SECURITY_ALERT = "security_alert"
    ADMIN_ACTION = "admin_action"


class SeverityLevel(Enum):
    """Severity levels for audit events."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class AuditLogEntry:
    """Single audit log entry."""
    entry_id: str
    timestamp: str
    event_type: AuditEventType
    severity: SeverityLevel
    user_id: Optional[str]
    ip_address: Optional[str]
    user_agent: Optional[str]
    resource_type: str
    resource_id: str
    action: str
    status: str  # success, failure, denied
    details: Dict[str, Any]
    before_state: Optional[Dict[str, Any]]
    after_state: Optional[Dict[str, Any]]
    session_id: Optional[str]
    request_id: Optional[str]


class AuditLogger:
    """
    Comprehensive audit logging for compliance requirements.
    """
    
    def __init__(self, storage_path: Path = Path("/app/data/audit")):
        self.storage_path = storage_path
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._buffer: List[AuditLogEntry] = []
        self._buffer_size = 100
    
    async def log_event(
        self,
        event_type: AuditEventType,
        severity: SeverityLevel,
        resource_type: str,
        resource_id: str,
        action: str,
        status: str,
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        before_state: Optional[Dict[str, Any]] = None,
        after_state: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        request_id: Optional[str] = None
    ) -> AuditLogEntry:
        """Log an audit event."""
        import uuid
        
        entry = AuditLogEntry(
            entry_id=str(uuid.uuid4()),
            timestamp=datetime.utcnow().isoformat(),
            event_type=event_type,
            severity=severity,
            user_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent,
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            status=status,
            details=details or {},
            before_state=before_state,
            after_state=after_state,
            session_id=session_id,
            request_id=request_id
        )
        
        # Add to buffer
        self._buffer.append(entry)
        
        # Flush if buffer is full
        if len(self._buffer) >= self._buffer_size:
            await self._flush_buffer()
        
        # Also log to standard logger for real-time monitoring
        if severity in [SeverityLevel.ERROR, SeverityLevel.CRITICAL]:
            logger.warning(
                f"AUDIT: {event_type.value} - {action} by {user_id} "
                f"on {resource_type}:{resource_id} - {status}"
            )
        
        return entry
    
    async def _flush_buffer(self) -> None:
        """Write buffered entries to storage."""
        if not self._buffer:
            return
        
        # Group by date
        by_date: Dict[str, List[AuditLogEntry]] = {}
        
        for entry in self._buffer:
            date = entry.timestamp[:10]  # YYYY-MM-DD
            if date not in by_date:
                by_date[date] = []
            by_date[date].append(entry)
        
        # Write to files
        for date, entries in by_date.items():
            file_path = self.storage_path / f"audit_{date}.jsonl"
            
            with open(file_path, 'a') as f:
                for entry in entries:
                    record = {
                        "entry_id": entry.entry_id,
                        "timestamp": entry.timestamp,
                        "event_type": entry.event_type.value,
                        "severity": entry.severity.value,
                        "user_id": entry.user_id,
                        "ip_address": entry.ip_address,
                        "user_agent": entry.user_agent,
                        "resource_type": entry.resource_type,
                        "resource_id": entry.resource_id,
                        "action": entry.action,
                        "status": entry.status,
                        "details": entry.details,
                        "before_state": entry.before_state,
                        "after_state": entry.after_state,
                        "session_id": entry.session_id,
                        "request_id": entry.request_id
                    }
                    f.write(json.dumps(record) + '\n')
        
        # Clear buffer
        self._buffer = []
    
    async def query_logs(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        event_types: Optional[List[AuditEventType]] = None,
        user_id: Optional[str] = None,
        resource_type: Optional[str] = None,
        severity: Optional[SeverityLevel] = None,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Query audit logs with filters."""
        results = []
        
        # Determine files to read
        files_to_read = []
        
        if start_date and end_date:
            # Generate date range
            from datetime import datetime, timedelta
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
            
            current = start
            while current <= end:
                file_path = self.storage_path / f"audit_{current.strftime('%Y-%m-%d')}.jsonl"
                if file_path.exists():
                    files_to_read.append(file_path)
                current += timedelta(days=1)
        else:
            # Read all files
            files_to_read = sorted(self.storage_path.glob("audit_*.jsonl"))
        
        # Read and filter
        for file_path in files_to_read:
            with open(file_path, 'r') as f:
                for line in f:
                    try:
                        record = json.loads(line.strip())
                        
                        # Apply filters
                        if event_types and record["event_type"] not in [t.value for t in event_types]:
                            continue
                        
                        if user_id and record["user_id"] != user_id:
                            continue
                        
                        if resource_type and record["resource_type"] != resource_type:
                            continue
                        
                        if severity and record["severity"] != severity.value:
                            continue
                        
                        results.append(record)
                        
                        if len(results) >= limit:
                            break
                            
                    except json.JSONDecodeError:
                        continue
            
            if len(results) >= limit:
                break
        
        # Sort by timestamp
        results.sort(key=lambda x: x["timestamp"], reverse=True)
        
        return results[:limit]
    
    async def get_user_activity_summary(
        self,
        user_id: str,
        days: int = 30
    ) -> Dict[str, Any]:
        """Get activity summary for a user."""
        from datetime import datetime, timedelta
        
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        logs = await self.query_logs(
            start_date=start_date,
            end_date=end_date,
            user_id=user_id
        )
        
        # Calculate summary
        event_counts = {}
        resource_access = set()
        failed_attempts = 0
        
        for log in logs:
            event_type = log["event_type"]
            event_counts[event_type] = event_counts.get(event_type, 0) + 1
            
            resource_access.add((log["resource_type"], log["resource_id"]))
            
            if log["status"] == "failure":
                failed_attempts += 1
        
        return {
            "user_id": user_id,
            "period_days": days,
            "total_events": len(logs),
            "event_breakdown": event_counts,
            "unique_resources_accessed": len(resource_access),
            "failed_attempts": failed_attempts,
            "first_activity": logs[-1]["timestamp"] if logs else None,
            "last_activity": logs[0]["timestamp"] if logs else None
        }
    
    async def export_logs(
        self,
        start_date: str,
        end_date: str,
        format: str = "json"
    ) -> Path:
        """Export audit logs for compliance reporting."""
        logs = await self.query_logs(
            start_date=start_date,
            end_date=end_date,
            limit=100000
        )
        
        export_path = self.storage_path / f"audit_export_{start_date}_{end_date}.{format}"
        
        if format == "json":
            with open(export_path, 'w') as f:
                json.dump(logs, f, indent=2)
        
        elif format == "csv":
            import csv
            
            with open(export_path, 'w', newline='') as f:
                if logs:
                    writer = csv.DictWriter(f, fieldnames=logs[0].keys())
                    writer.writeheader()
                    writer.writerows(logs)
        
        return export_path
    
    async def detect_anomalies(
        self,
        user_id: Optional[str] = None,
        hours: int = 24
    ) -> List[Dict[str, Any]]:
        """Detect suspicious activity patterns."""
        from datetime import datetime, timedelta
        
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d")
        
        logs = await self.query_logs(
            start_date=start_date,
            end_date=end_date,
            user_id=user_id,
            severity=SeverityLevel.WARNING
        )
        
        anomalies = []
        
        # Check for multiple failed logins
        failed_logins = [
            l for l in logs
            if l["event_type"] == AuditEventType.USER_LOGIN.value
            and l["status"] == "failure"
        ]
        
        if len(failed_logins) >= 5:
            anomalies.append({
                "type": "multiple_failed_logins",
                "severity": "high",
                "count": len(failed_logins),
                "user_id": user_id,
                "timeframe_hours": hours
            })
        
        # Check for unusual access patterns
        # (e.g., accessing resources never accessed before)
        
        return anomalies


# Global instance
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Get global audit logger."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


# Convenience functions
async def log_user_action(
    user_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
    status: str = "success",
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None
) -> None:
    """Log a user action."""
    await get_audit_logger().log_event(
        event_type=AuditEventType.ADMIN_ACTION,
        severity=SeverityLevel.INFO,
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        status=status,
        user_id=user_id,
        ip_address=ip_address,
        details=details
    )


async def log_security_event(
    event_type: AuditEventType,
    severity: SeverityLevel,
    details: Dict[str, Any],
    user_id: Optional[str] = None,
    ip_address: Optional[str] = None
) -> None:
    """Log a security event."""
    await get_audit_logger().log_event(
        event_type=event_type,
        severity=severity,
        resource_type="security",
        resource_id=details.get("resource_id", "system"),
        action=event_type.value,
        status=details.get("status", "unknown"),
        user_id=user_id,
        ip_address=ip_address,
        details=details
    )
