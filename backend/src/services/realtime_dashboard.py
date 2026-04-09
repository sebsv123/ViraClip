"""
Real-time Analytics Dashboard with WebSockets
Live metrics and analytics streaming for monitoring.
"""

import json
import logging
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import asyncio

logger = logging.getLogger(__name__)


class MetricType(Enum):
    """Types of metrics to track."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    RATE = "rate"


class TimeRange(Enum):
    """Time ranges for analytics."""
    LAST_HOUR = "1h"
    LAST_24H = "24h"
    LAST_7D = "7d"
    LAST_30D = "30d"


@dataclass
class MetricDataPoint:
    """Single metric data point."""
    timestamp: str
    value: float
    labels: Dict[str, str]


@dataclass
class RealtimeMetric:
    """Real-time metric definition."""
    metric_id: str
    name: str
    metric_type: MetricType
    description: str
    unit: str
    current_value: float
    data_points: List[MetricDataPoint]
    aggregation: str  # sum, avg, max, min


class RealtimeDashboardService:
    """
    Real-time analytics dashboard with WebSocket streaming.
    """
    
    def __init__(self):
        self._metrics: Dict[str, RealtimeMetric] = {}
        self._connected_clients: Set = set()
        self._user_sessions: Dict[str, Dict[str, Any]] = {}
        self._broadcast_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
    
    async def start(self):
        """Start the real-time dashboard service."""
        self._broadcast_task = asyncio.create_task(self._periodic_broadcast())
        # FIX: Start cleanup task for dead connections
        self._cleanup_task = asyncio.create_task(self._cleanup_dead_connections_loop())
        logger.info("Real-time dashboard service started")
    
    async def stop(self):
        """Stop the dashboard service."""
        if self._broadcast_task:
            self._broadcast_task.cancel()
        # FIX: Stop cleanup task
        if self._cleanup_task:
            self._cleanup_task.cancel()
        logger.info("Real-time dashboard service stopped")
    
    def register_metric(
        self,
        metric_id: str,
        name: str,
        metric_type: MetricType,
        description: str,
        unit: str = "",
        aggregation: str = "avg"
    ) -> RealtimeMetric:
        """Register a new metric for tracking."""
        metric = RealtimeMetric(
            metric_id=metric_id,
            name=name,
            metric_type=metric_type,
            description=description,
            unit=unit,
            current_value=0.0,
            data_points=[],
            aggregation=aggregation
        )
        
        self._metrics[metric_id] = metric
        return metric
    
    async def record_metric(
        self,
        metric_id: str,
        value: float,
        labels: Optional[Dict[str, str]] = None
    ) -> None:
        """Record a metric value."""
        if metric_id not in self._metrics:
            return
        
        metric = self._metrics[metric_id]
        
        # Create data point
        data_point = MetricDataPoint(
            timestamp=datetime.now().isoformat(),
            value=value,
            labels=labels or {}
        )
        
        # Add to metric
        metric.data_points.append(data_point)
        
        # Keep only last 1000 points per metric
        if len(metric.data_points) > 1000:
            metric.data_points = metric.data_points[-1000:]
        
        # Update current value based on aggregation
        metric.current_value = self._calculate_aggregation(
            metric.data_points, metric.aggregation
        )
        
        # Broadcast to clients
        await self._broadcast_metric_update(metric_id, value, labels)
    
    def _calculate_aggregation(
        self,
        data_points: List[MetricDataPoint],
        aggregation: str
    ) -> float:
        """Calculate aggregated value."""
        if not data_points:
            return 0.0
        
        values = [dp.value for dp in data_points[-100:]]  # Last 100 points
        
        if aggregation == "sum":
            return sum(values)
        elif aggregation == "avg":
            return sum(values) / len(values)
        elif aggregation == "max":
            return max(values)
        elif aggregation == "min":
            return min(values)
        elif aggregation == "count":
            return len(values)
        
        return sum(values) / len(values)
    
    async def client_connect(self, websocket, user_id: str) -> None:
        """Handle new WebSocket client connection."""
        self._connected_clients.add(websocket)
        self._user_sessions[user_id] = {
            "websocket": websocket,
            "connected_at": datetime.now().isoformat(),
            "subscribed_metrics": []
        }
        
        # Send initial dashboard state
        await self._send_initial_state(websocket)
        
        logger.info(f"Dashboard client connected: {user_id}")
    
    async def client_disconnect(self, websocket, user_id: str) -> None:
        """Handle client disconnection."""
        self._connected_clients.discard(websocket)
        if user_id in self._user_sessions:
            del self._user_sessions[user_id]
        
        logger.info(f"Dashboard client disconnected: {user_id}")
    
    async def _send_initial_state(self, websocket) -> None:
        """Send initial dashboard state to client."""
        state = {
            "type": "initial_state",
            "timestamp": datetime.now().isoformat(),
            "metrics": [
                {
                    "metric_id": m.metric_id,
                    "name": m.name,
                    "type": m.metric_type.value,
                    "current_value": m.current_value,
                    "unit": m.unit,
                    "description": m.description
                }
                for m in self._metrics.values()
            ]
        }
        
        try:
            await websocket.send_json(state)
        except (ConnectionError, RuntimeError, Exception) as e:
            # FIX: Log error and remove dead connection
            logger.debug(f"Failed to send initial state: {e}")
            self._connected_clients.discard(websocket)
    
    async def _broadcast_metric_update(
        self,
        metric_id: str,
        value: float,
        labels: Optional[Dict[str, str]]
    ) -> None:
        """Broadcast metric update to all clients."""
        message = {
            "type": "metric_update",
            "timestamp": datetime.now().isoformat(),
            "metric_id": metric_id,
            "value": value,
            "labels": labels or {}
        }
        
        # Send to all connected clients
        disconnected = []
        for ws in self._connected_clients:
            try:
                await ws.send_json(message)
            except (ConnectionError, RuntimeError, Exception) as e:
                # FIX: Better error logging
                logger.debug(f"Dead connection during broadcast: {e}")
                disconnected.append(ws)
        
        # Clean up disconnected clients
        for ws in disconnected:
            self._connected_clients.discard(ws)
    
    async def _periodic_broadcast(self) -> None:
        """Periodic full state broadcast."""
        while True:
            try:
                await asyncio.sleep(5)  # Broadcast every 5 seconds
                
                # Prepare full dashboard update
                update = {
                    "type": "dashboard_update",
                    "timestamp": datetime.now().isoformat(),
                    "metrics": {
                        m.metric_id: {
                            "current_value": m.current_value,
                            "data_points_count": len(m.data_points)
                        }
                        for m in self._metrics.values()
                    },
                    "system_status": await self._get_system_status()
                }
                
                # Broadcast to all clients
                disconnected = []
                for ws in self._connected_clients:
                    try:
                        await ws.send_json(update)
                    except (ConnectionError, RuntimeError, Exception) as e:
                        # FIX: Better error logging
                        logger.debug(f"Dead connection during periodic broadcast: {e}")
                        disconnected.append(ws)
                
                # Clean up
                for ws in disconnected:
                    self._connected_clients.discard(ws)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Periodic broadcast error: {e}")
    
    async def _cleanup_dead_connections_loop(self) -> None:
        """FIX: Periodically cleanup dead WebSocket connections."""
        while True:
            try:
                await asyncio.sleep(300)  # Every 5 minutes
                
                dead = []
                for ws in self._connected_clients:
                    try:
                        # Try a ping to check if alive
                        await ws.send_json({"type": "ping"})
                    except Exception:
                        dead.append(ws)
                
                for ws in dead:
                    self._connected_clients.discard(ws)
                
                if dead:
                    logger.info(f"Cleaned up {len(dead)} dead dashboard connections")
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup loop error: {e}")
    
    async def _get_system_status(self) -> Dict[str, Any]:
        """Get current system status."""
        return {
            "active_connections": len(self._connected_clients),
            "active_metrics": len(self._metrics),
            "last_update": datetime.now().isoformat()
        }
    
    def get_metric_history(
        self,
        metric_id: str,
        time_range: TimeRange = TimeRange.LAST_HOUR
    ) -> List[Dict[str, Any]]:
        """Get historical data for a metric."""
        if metric_id not in self._metrics:
            return []
        
        metric = self._metrics[metric_id]
        
        # Calculate time cutoff
        now = datetime.now()
        if time_range == TimeRange.LAST_HOUR:
            cutoff = now - __import__('datetime').timedelta(hours=1)
        elif time_range == TimeRange.LAST_24H:
            cutoff = now - __import__('datetime').timedelta(days=1)
        elif time_range == TimeRange.LAST_7D:
            cutoff = now - __import__('datetime').timedelta(days=7)
        else:
            cutoff = now - __import__('datetime').timedelta(days=30)
        
        # Filter data points
        filtered = [
            {
                "timestamp": dp.timestamp,
                "value": dp.value,
                "labels": dp.labels
            }
            for dp in metric.data_points
            if datetime.fromisoformat(dp.timestamp) > cutoff
        ]
        
        return filtered
    
    def get_dashboard_summary(self) -> Dict[str, Any]:
        """Get dashboard summary."""
        return {
            "active_metrics": len(self._metrics),
            "active_connections": len(self._connected_clients),
            "total_data_points": sum(len(m.data_points) for m in self._metrics.values()),
            "metrics": [
                {
                    "metric_id": m.metric_id,
                    "name": m.name,
                    "current_value": m.current_value,
                    "type": m.metric_type.value
                }
                for m in self._metrics.values()
            ]
        }
    
    def create_custom_dashboard(
        self,
        user_id: str,
        name: str,
        metric_ids: List[str]
    ) -> Dict[str, Any]:
        """Create custom dashboard configuration."""
        return {
            "dashboard_id": f"dash_{user_id}_{name}",
            "user_id": user_id,
            "name": name,
            "metrics": metric_ids,
            "created_at": datetime.now().isoformat()
        }


# Global instance
_dashboard_service: Optional[RealtimeDashboardService] = None


def get_dashboard_service() -> RealtimeDashboardService:
    """Get global dashboard service."""
    global _dashboard_service
    if _dashboard_service is None:
        _dashboard_service = RealtimeDashboardService()
    return _dashboard_service


# Convenience functions
async def record_dashboard_metric(metric_id: str, value: float, labels: Optional[Dict] = None) -> None:
    """Record a metric for the dashboard."""
    await get_dashboard_service().record_metric(metric_id, value, labels)


def get_realtime_metrics() -> Dict[str, Any]:
    """Get current real-time metrics."""
    return get_dashboard_service().get_dashboard_summary()
