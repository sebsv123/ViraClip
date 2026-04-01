"""
System Health Dashboard Service
Real-time system monitoring and health status.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import asyncio

logger = logging.getLogger(__name__)

def _get_psutil():
    """Lazy import psutil to avoid import errors in worker initialization."""
    import psutil
    return psutil


class ServiceStatus(Enum):
    """Service health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    DOWN = "down"


@dataclass
class HealthMetric:
    """Health metric data point."""
    metric_name: str
    value: float
    unit: str
    timestamp: str
    threshold_warning: float
    threshold_critical: float


@dataclass
class ServiceHealth:
    """Service health status."""
    service_name: str
    status: ServiceStatus
    latency_ms: float
    uptime_seconds: float
    last_check: str
    error_rate: float
    dependencies: List[str]


class SystemHealthService:
    """
    Real-time system health monitoring dashboard.
    """
    
    def __init__(self):
        self._service_health: Dict[str, ServiceHealth] = {}
        self._metrics_history: Dict[str, List[HealthMetric]] = {}
        self._alerts: List[Dict[str, Any]] = []
        
        # Initialize services to monitor
        self._initialize_services()
    
    def _initialize_services(self):
        """Initialize service health tracking."""
        services = [
            "api_server",
            "video_processor",
            "ai_worker",
            "database",
            "redis_cache",
            "storage",
            "queue_worker"
        ]
        
        for service in services:
            self._service_health[service] = ServiceHealth(
                service_name=service,
                status=ServiceStatus.HEALTHY,
                latency_ms=0,
                uptime_seconds=0,
                last_check=datetime.now().isoformat(),
                error_rate=0.0,
                dependencies=[]
            )
    
    async def check_system_health(self) -> Dict[str, Any]:
        """Perform comprehensive system health check."""
        checks = await asyncio.gather(
            self._check_cpu_health(),
            self._check_memory_health(),
            self._check_disk_health(),
            self._check_network_health(),
            self._check_services_health()
        )
        
        cpu, memory, disk, network, services = checks
        
        # Determine overall status
        all_statuses = [
            cpu["status"],
            memory["status"],
            disk["status"],
            network["status"],
            services["overall_status"]
        ]
        
        if ServiceStatus.DOWN in all_statuses:
            overall_status = ServiceStatus.DOWN
        elif ServiceStatus.UNHEALTHY in all_statuses:
            overall_status = ServiceStatus.UNHEALTHY
        elif ServiceStatus.DEGRADED in all_statuses:
            overall_status = ServiceStatus.DEGRADED
        else:
            overall_status = ServiceStatus.HEALTHY
        
        return {
            "timestamp": datetime.now().isoformat(),
            "overall_status": overall_status.value,
            "components": {
                "cpu": cpu,
                "memory": memory,
                "disk": disk,
                "network": network,
                "services": services
            },
            "alerts": len(self._alerts),
            "uptime_seconds": self._get_system_uptime()
        }
    
    async def _check_cpu_health(self) -> Dict[str, Any]:
        """Check CPU health."""
        psutil = _get_psutil()
        cpu_percent = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()
        load_avg = psutil.getloadavg() if hasattr(psutil, 'getloadavg') else (0, 0, 0)
        
        if cpu_percent > 90:
            status = ServiceStatus.UNHEALTHY
        elif cpu_percent > 70:
            status = ServiceStatus.DEGRADED
        else:
            status = ServiceStatus.HEALTHY
        
        return {
            "status": status,
            "usage_percent": cpu_percent,
            "core_count": cpu_count,
            "load_average": load_avg,
            "timestamp": datetime.now().isoformat()
        }
    
    async def _check_memory_health(self) -> Dict[str, Any]:
        """Check memory health."""
        psutil = _get_psutil()
        memory = psutil.virtual_memory()
        swap = psutil.swap_memory()
        
        if memory.percent > 90 or swap.percent > 50:
            status = ServiceStatus.UNHEALTHY
        elif memory.percent > 80:
            status = ServiceStatus.DEGRADED
        else:
            status = ServiceStatus.HEALTHY
        
        return {
            "status": status,
            "total_gb": memory.total / (1024**3),
            "available_gb": memory.available / (1024**3),
            "used_percent": memory.percent,
            "swap_used_percent": swap.percent,
            "timestamp": datetime.now().isoformat()
        }
    
    async def _check_disk_health(self) -> Dict[str, Any]:
        """Check disk health."""
        psutil = _get_psutil()
        disk = psutil.disk_usage('/')
        
        if disk.percent > 90:
            status = ServiceStatus.UNHEALTHY
        elif disk.percent > 80:
            status = ServiceStatus.DEGRADED
        else:
            status = ServiceStatus.HEALTHY
        
        return {
            "status": status,
            "total_gb": disk.total / (1024**3),
            "free_gb": disk.free / (1024**3),
            "used_percent": disk.percent,
            "timestamp": datetime.now().isoformat()
        }
    
    async def _check_network_health(self) -> Dict[str, Any]:
        """Check network health."""
        psutil = _get_psutil()
        net_io = psutil.net_io_counters()
        
        # Calculate bandwidth usage (simplified)
        bytes_sent_mb = net_io.bytes_sent / (1024**2)
        bytes_recv_mb = net_io.bytes_recv / (1024**2)
        
        # Check for network errors
        if net_io.errin > 1000 or net_io.errout > 1000:
            status = ServiceStatus.DEGRADED
        else:
            status = ServiceStatus.HEALTHY
        
        return {
            "status": status,
            "bytes_sent_mb": bytes_sent_mb,
            "bytes_recv_mb": bytes_recv_mb,
            "packets_sent": net_io.packets_sent,
            "packets_recv": net_io.packets_recv,
            "errors_in": net_io.errin,
            "errors_out": net_io.errout,
            "timestamp": datetime.now().isoformat()
        }
    
    async def _check_services_health(self) -> Dict[str, Any]:
        """Check all service health."""
        service_statuses = {}
        
        for name, health in self._service_health.items():
            # Update service check
            latency = await self._ping_service(name)
            
            if latency < 0:
                health.status = ServiceStatus.DOWN
            elif latency > 1000:
                health.status = ServiceStatus.UNHEALTHY
            elif latency > 500:
                health.status = ServiceStatus.DEGRADED
            else:
                health.status = ServiceStatus.HEALTHY
            
            health.latency_ms = latency if latency > 0 else 9999
            health.last_check = datetime.now().isoformat()
            
            service_statuses[name] = {
                "status": health.status.value,
                "latency_ms": health.latency_ms,
                "uptime_seconds": health.uptime_seconds,
                "error_rate": health.error_rate
            }
        
        # Determine overall service status
        statuses = [s["status"] for s in service_statuses.values()]
        if "down" in statuses:
            overall = ServiceStatus.DOWN
        elif "unhealthy" in statuses:
            overall = ServiceStatus.UNHEALTHY
        elif "degraded" in statuses:
            overall = ServiceStatus.DEGRADED
        else:
            overall = ServiceStatus.HEALTHY
        
        return {
            "overall_status": overall.value,
            "services": service_statuses
        }
    
    async def _ping_service(self, service_name: str) -> float:
        """Ping a service to check latency."""
        # Simulated ping
        import random
        await asyncio.sleep(0.01)
        return random.uniform(10, 200)
    
    def _get_system_uptime(self) -> float:
        """Get system uptime in seconds."""
        try:
            with open('/proc/uptime', 'r') as f:
                uptime_seconds = float(f.readline().split()[0])
                return uptime_seconds
        except:
            return 0
    
    async def record_metric(
        self,
        metric_name: str,
        value: float,
        unit: str,
        threshold_warning: float = 80.0,
        threshold_critical: float = 90.0
    ):
        """Record a health metric."""
        metric = HealthMetric(
            metric_name=metric_name,
            value=value,
            unit=unit,
            timestamp=datetime.now().isoformat(),
            threshold_warning=threshold_warning,
            threshold_critical=threshold_critical
        )
        
        if metric_name not in self._metrics_history:
            self._metrics_history[metric_name] = []
        
        self._metrics_history[metric_name].append(metric)
        
        # Keep only last 24 hours
        cutoff = datetime.now() - timedelta(hours=24)
        self._metrics_history[metric_name] = [
            m for m in self._metrics_history[metric_name]
            if datetime.fromisoformat(m.timestamp) > cutoff
        ]
        
        # Check thresholds
        if value > threshold_critical:
            await self._create_alert(
                "critical",
                metric_name,
                f"{metric_name} exceeded critical threshold: {value}{unit}"
            )
        elif value > threshold_warning:
            await self._create_alert(
                "warning",
                metric_name,
                f"{metric_name} exceeded warning threshold: {value}{unit}"
            )
    
    async def _create_alert(self, severity: str, source: str, message: str):
        """Create health alert."""
        alert = {
            "id": f"alert_{datetime.now().timestamp()}",
            "severity": severity,
            "source": source,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "acknowledged": False
        }
        
        self._alerts.append(alert)
        logger.warning(f"Health alert: {message}")
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get data for health dashboard."""
        return {
            "services": [
                {
                    "name": s.service_name,
                    "status": s.status.value,
                    "latency_ms": s.latency_ms,
                    "uptime_hours": s.uptime_seconds / 3600,
                    "last_check": s.last_check
                }
                for s in self._service_health.values()
            ],
            "alerts": [
                {
                    "id": a["id"],
                    "severity": a["severity"],
                    "message": a["message"],
                    "timestamp": a["timestamp"],
                    "acknowledged": a["acknowledged"]
                }
                for a in sorted(self._alerts, key=lambda x: x["timestamp"], reverse=True)[:10]
            ],
            "metrics_history": {
                name: [
                    {
                        "value": m.value,
                        "unit": m.unit,
                        "timestamp": m.timestamp
                    }
                    for m in history[-50:]  # Last 50 data points
                ]
                for name, history in self._metrics_history.items()
            }
        }


# Global instance
_health_service: Optional[SystemHealthService] = None


def get_system_health_service() -> SystemHealthService:
    """Get global system health service."""
    global _health_service
    if _health_service is None:
        _health_service = SystemHealthService()
    return _health_service
