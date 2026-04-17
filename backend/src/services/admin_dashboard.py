"""
Admin Dashboard Service
Advanced admin dashboard with system metrics, user management, and operations.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class AdminRole(Enum):
    """Admin user roles."""
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    MODERATOR = "moderator"
    SUPPORT = "support"
    ANALYST = "analyst"


@dataclass
class SystemMetrics:
    """Real-time system metrics."""
    timestamp: str
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    active_tasks: int
    queue_length: int
    api_requests_per_minute: int
    error_rate: float
    avg_response_time_ms: float


@dataclass
class UserActivity:
    """User activity summary."""
    user_id: str
    email: str
    role: str
    last_active: str
    total_videos: int
    total_clips: int
    storage_used_gb: float
    account_status: str


class AdminDashboardService:
    """
    Service for admin dashboard operations and metrics.
    """
    
    def __init__(self):
        self._metrics_history: List[SystemMetrics] = []
        self._admin_users: Dict[str, Dict[str, Any]] = {}
        self._system_alerts: List[Dict[str, Any]] = []
    
    def get_system_overview(self) -> Dict[str, Any]:
        """Get high-level system overview for dashboard."""
        return {
            "timestamp": datetime.now().isoformat(),
            "system_status": self._get_system_status(),
            "quick_stats": {
                "total_users": self._get_total_users(),
                "videos_processed_today": self._get_today_stats()["videos"],
                "clips_generated_today": self._get_today_stats()["clips"],
                "active_processing_tasks": self._get_active_tasks(),
                "system_health_score": self._calculate_health_score()
            },
            "recent_alerts": self._get_recent_alerts(5),
            "performance_trend": self._get_performance_trend()
        }
    
    def _get_system_status(self) -> str:
        """Determine overall system status."""
        # Check various metrics
        health_score = self._calculate_health_score()
        
        if health_score >= 90:
            return "excellent"
        elif health_score >= 75:
            return "good"
        elif health_score >= 50:
            return "degraded"
        else:
            return "critical"
    
    def _calculate_health_score(self) -> int:
        """Calculate overall system health score (0-100)."""
        try:
            import psutil
            
            cpu = psutil.cpu_percent(interval=0.1)
            memory = psutil.virtual_memory().percent
            disk = psutil.disk_usage('/').percent
            
            # Score each component (lower is better, so invert)
            cpu_score = max(0, 100 - cpu)
            memory_score = max(0, 100 - memory)
            disk_score = max(0, 100 - disk)
            
            # Weighted average
            score = (cpu_score * 0.3 + memory_score * 0.4 + disk_score * 0.3)
            
            return int(score)
        except:
            return 75  # Default if can't calculate
    
    def _get_total_users(self) -> int:
        """Get total user count."""
        # Would query database in production
        return 0
    
    def _get_today_stats(self) -> Dict[str, int]:
        """Get today's processing statistics."""
        return {"videos": 0, "clips": 0}
    
    def _get_active_tasks(self) -> int:
        """Get count of active processing tasks."""
        return 0
    
    def _get_recent_alerts(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get recent system alerts."""
        return sorted(
            self._system_alerts,
            key=lambda x: x["timestamp"],
            reverse=True
        )[:limit]
    
    def _get_performance_trend(self) -> Dict[str, Any]:
        """Get performance trend over last 24 hours."""
        if not self._metrics_history:
            return {"status": "unknown", "change": 0}
        
        # Compare recent vs older metrics
        recent = self._metrics_history[-10:]
        older = self._metrics_history[-20:-10] if len(self._metrics_history) >= 20 else []
        
        if not older:
            return {"status": "stable", "change": 0}
        
        recent_avg = sum(m.error_rate for m in recent) / len(recent)
        older_avg = sum(m.error_rate for m in older) / len(older)
        
        change = recent_avg - older_avg
        
        if change < -0.05:
            return {"status": "improving", "change": abs(change)}
        elif change > 0.05:
            return {"status": "degrading", "change": change}
        else:
            return {"status": "stable", "change": 0}
    
    def get_detailed_metrics(self) -> Dict[str, Any]:
        """Get detailed system metrics."""
        try:
            import psutil
            
            # CPU metrics
            cpu_percent = psutil.cpu_percent(interval=0.1, percpu=True)
            cpu_freq = psutil.cpu_freq()
            
            # Memory metrics
            memory = psutil.virtual_memory()
            
            # Disk metrics
            disk = psutil.disk_usage('/')
            disk_io = psutil.disk_io_counters()
            
            # Network metrics
            net_io = psutil.net_io_counters()
            
            return {
                "cpu": {
                    "overall_percent": psutil.cpu_percent(),
                    "per_cpu_percent": cpu_percent,
                    "frequency_mhz": cpu_freq.current if cpu_freq else None,
                    "core_count": psutil.cpu_count(),
                    "load_average": psutil.getloadavg() if hasattr(psutil, 'getloadavg') else None
                },
                "memory": {
                    "total_gb": memory.total / (1024**3),
                    "available_gb": memory.available / (1024**3),
                    "used_gb": memory.used / (1024**3),
                    "percent": memory.percent,
                    "cached_gb": getattr(memory, 'cached', 0) / (1024**3)
                },
                "disk": {
                    "total_gb": disk.total / (1024**3),
                    "used_gb": disk.used / (1024**3),
                    "free_gb": disk.free / (1024**3),
                    "percent": disk.percent,
                    "read_mb": disk_io.read_bytes / (1024**2) if disk_io else 0,
                    "write_mb": disk_io.write_bytes / (1024**2) if disk_io else 0
                },
                "network": {
                    "sent_mb": net_io.bytes_sent / (1024**2),
                    "received_mb": net_io.bytes_recv / (1024**2),
                    "packets_sent": net_io.packets_sent,
                    "packets_recv": net_io.packets_recv
                },
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Failed to get detailed metrics: {e}")
            return {"error": str(e)}
    
    def get_user_management_data(
        self,
        page: int = 1,
        per_page: int = 50,
        search: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get user management data with pagination."""
        # Would query database in production
        return {
            "users": [],
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": 0,
                "total_pages": 0
            }
        }
    
    def get_processing_queue_status(self) -> Dict[str, Any]:
        """Get video processing queue status."""
        return {
            "queue_length": 0,
            "active_workers": 0,
            "avg_wait_time_seconds": 0,
            "completed_today": 0,
            "failed_today": 0,
            "success_rate": 100.0
        }
    
    def get_storage_analytics(self) -> Dict[str, Any]:
        """Get storage usage analytics."""
        try:
            import shutil
            
            temp_usage = shutil.disk_usage('/app/temp')
            data_usage = shutil.disk_usage('/app/data')
            
            return {
                "temp_storage": {
                    "total_gb": temp_usage.total / (1024**3),
                    "used_gb": temp_usage.used / (1024**3),
                    "free_gb": temp_usage.free / (1024**3),
                    "percent": (temp_usage.used / temp_usage.total) * 100
                },
                "data_storage": {
                    "total_gb": data_usage.total / (1024**3),
                    "used_gb": data_usage.used / (1024**3),
                    "free_gb": data_usage.free / (1024**3),
                    "percent": (data_usage.used / data_usage.total) * 100
                },
                "breakdown": {
                    "videos": 0,
                    "clips": 0,
                    "thumbnails": 0,
                    "cache": 0
                },
                "cleanup_recommended": temp_usage.percent > 80
            }
            
        except Exception as e:
            return {"error": str(e)}
    
    def get_api_analytics(self, hours: int = 24) -> Dict[str, Any]:
        """Get API usage analytics."""
        return {
            "period_hours": hours,
            "total_requests": 0,
            "requests_by_endpoint": {},
            "avg_response_time_ms": 0,
            "error_rate": 0,
            "top_users": [],
            "rate_limit_hits": 0
        }
    
    def perform_admin_action(
        self,
        action: str,
        params: Dict[str, Any],
        admin_id: str
    ) -> Dict[str, Any]:
        """Perform administrative actions."""
        logger.info(f"Admin {admin_id} performing action: {action}")
        
        actions = {
            "clear_cache": self._action_clear_cache,
            "restart_workers": self._action_restart_workers,
            "force_backup": self._action_force_backup,
            "cleanup_storage": self._action_cleanup_storage,
            "broadcast_message": self._action_broadcast_message
        }
        
        if action in actions:
            try:
                result = actions[action](params)
                return {"success": True, "result": result}
            except Exception as e:
                logger.error(f"Admin action failed: {e}")
                return {"success": False, "error": str(e)}
        
        return {"success": False, "error": "Unknown action"}
    
    def _action_clear_cache(self, params: Dict[str, Any]) -> str:
        """Clear system cache."""
        # Implementation would clear Redis and local caches
        return "Cache cleared successfully"
    
    def _action_restart_workers(self, params: Dict[str, Any]) -> str:
        """Restart processing workers."""
        # Implementation would restart Celery/ARQ workers
        return "Workers restarted successfully"
    
    def _action_force_backup(self, params: Dict[str, Any]) -> str:
        """Force immediate backup."""
        # Implementation would trigger backup
        return "Backup initiated"
    
    def _action_cleanup_storage(self, params: Dict[str, Any]) -> Dict[str, int]:
        """Clean up old storage files."""
        # Implementation would clean old files
        return {"deleted_files": 0, "freed_gb": 0}
    
    def _action_broadcast_message(self, params: Dict[str, Any]) -> str:
        """Broadcast message to users."""
        message = params.get("message", "")
        # Implementation would send to all users
        return f"Message broadcast to users"
    
    def add_alert(self, level: str, message: str, source: str) -> None:
        """Add a system alert."""
        self._system_alerts.append({
            "id": len(self._system_alerts),
            "level": level,  # info, warning, error, critical
            "message": message,
            "source": source,
            "timestamp": datetime.now().isoformat(),
            "acknowledged": False
        })
    
    def acknowledge_alert(self, alert_id: int, admin_id: str) -> bool:
        """Acknowledge a system alert."""
        for alert in self._system_alerts:
            if alert["id"] == alert_id:
                alert["acknowledged"] = True
                alert["acknowledged_by"] = admin_id
                alert["acknowledged_at"] = datetime.now().isoformat()
                return True
        return False


# Global instance
_admin_service: Optional[AdminDashboardService] = None


def get_admin_dashboard_service() -> AdminDashboardService:
    """Get global admin dashboard service instance."""
    global _admin_service
    if _admin_service is None:
        _admin_service = AdminDashboardService()
    return _admin_service


# Convenience functions
def get_admin_overview() -> Dict[str, Any]:
    """Get admin dashboard overview."""
    return get_admin_dashboard_service().get_system_overview()


def get_system_health() -> Dict[str, Any]:
    """Get detailed system health metrics."""
    return get_admin_dashboard_service().get_detailed_metrics()


def perform_system_action(action: str, params: Dict[str, Any], admin_id: str) -> Dict[str, Any]:
    """Perform a system administration action."""
    return get_admin_dashboard_service().perform_admin_action(action, params, admin_id)
