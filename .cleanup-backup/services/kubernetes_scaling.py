"""
Kubernetes Auto-scaling Service
Dynamic scaling of video processing workers based on demand.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class ScalingStrategy(Enum):
    """Auto-scaling strategies."""
    CPU_BASED = "cpu_based"
    QUEUE_BASED = "queue_based"
    SCHEDULED = "scheduled"
    PREDICTIVE = "predictive"


class WorkerStatus(Enum):
    """Worker pod status."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TERMINATING = "terminating"


@dataclass
class WorkerPod:
    """Worker pod information."""
    pod_id: str
    node_name: str
    status: WorkerStatus
    cpu_usage: float
    memory_usage: float
    active_tasks: int
    start_time: str
    estimated_completion: Optional[str]
    clip_id: Optional[str]


@dataclass
class ScalingEvent:
    """Scaling event record."""
    event_id: str
    timestamp: str
    strategy: ScalingStrategy
    previous_replicas: int
    new_replicas: int
    reason: str
    metrics_snapshot: Dict[str, Any]


class KubernetesScalingService:
    """
    Kubernetes-based auto-scaling for video processing workers.
    """
    
    def __init__(self):
        self._deployment_name = "viraclip-workers"
        self._namespace = "production"
        self._current_replicas = 3
        self._min_replicas = 2
        self._max_replicas = 50
        self._target_cpu_utilization = 70
        self._target_queue_depth = 10
        
        self._worker_pods: Dict[str, WorkerPod] = {}
        self._scaling_history: List[ScalingEvent] = []
        self._metrics_buffer: List[Dict[str, Any]] = []
        self._last_scale_time = datetime.now() - timedelta(minutes=5)
        
        # Cooldown periods
        self._scale_up_cooldown = 60   # seconds
        self._scale_down_cooldown = 300  # seconds
    
    async def get_cluster_metrics(self) -> Dict[str, Any]:
        """Get current cluster metrics from Kubernetes."""
        # In production, this would query K8s API
        # Simulated metrics
        return {
            "total_workers": self._current_replicas,
            "active_workers": len([w for w in self._worker_pods.values() if w.status == WorkerStatus.RUNNING]),
            "pending_tasks": sum(w.active_tasks for w in self._worker_pods.values()),
            "avg_cpu_utilization": sum(w.cpu_usage for w in self._worker_pods.values()) / len(self._worker_pods) if self._worker_pods else 0,
            "avg_memory_utilization": sum(w.memory_usage for w in self._worker_pods.values()) / len(self._worker_pods) if self._worker_pods else 0,
            "queue_depth": await self._get_queue_depth(),
            "nodes_available": 10
        }
    
    async def _get_queue_depth(self) -> int:
        """Get current task queue depth."""
        # Would query Redis/RabbitMQ in production
        return sum(w.active_tasks for w in self._worker_pods.values())
    
    async def evaluate_scaling_needs(self) -> Optional[Dict[str, Any]]:
        """Evaluate if scaling is needed."""
        metrics = await self.get_cluster_metrics()
        
        # Store metrics for trend analysis
        self._metrics_buffer.append({
            "timestamp": datetime.now().isoformat(),
            **metrics
        })
        
        # Keep only last 60 minutes
        cutoff = datetime.now() - timedelta(minutes=60)
        self._metrics_buffer = [
            m for m in self._metrics_buffer
            if datetime.fromisoformat(m["timestamp"]) > cutoff
        ]
        
        decision = None
        
        # CPU-based scaling
        if metrics["avg_cpu_utilization"] > self._target_cpu_utilization:
            if self._current_replicas < self._max_replicas:
                decision = {
                    "action": "scale_up",
                    "strategy": ScalingStrategy.CPU_BASED,
                    "reason": f"CPU at {metrics['avg_cpu_utilization']:.1f}%",
                    "desired_replicas": min(
                        self._current_replicas + self._calculate_scale_up(metrics),
                        self._max_replicas
                    )
                }
        
        # Queue-based scaling
        elif metrics["queue_depth"] > self._target_queue_depth * self._current_replicas:
            if self._current_replicas < self._max_replicas:
                decision = {
                    "action": "scale_up",
                    "strategy": ScalingStrategy.QUEUE_BASED,
                    "reason": f"Queue depth {metrics['queue_depth']}",
                    "desired_replicas": min(
                        self._current_replicas + self._calculate_scale_up(metrics),
                        self._max_replicas
                    )
                }
        
        # Scale down check
        elif (metrics["avg_cpu_utilization"] < 30 and 
              metrics["queue_depth"] < self._target_queue_depth and
              self._current_replicas > self._min_replicas):
            decision = {
                "action": "scale_down",
                "strategy": ScalingStrategy.CPU_BASED,
                "reason": f"Low utilization: CPU {metrics['avg_cpu_utilization']:.1f}%",
                "desired_replicas": max(
                    self._current_replicas - 1,
                    self._min_replicas
                )
            }
        
        return decision
    
    def _calculate_scale_up(self, metrics: Dict[str, Any]) -> int:
        """Calculate how many replicas to add."""
        cpu_factor = int(metrics["avg_cpu_utilization"] / self._target_cpu_utilization)
        queue_factor = int(metrics["queue_depth"] / (self._target_queue_depth * self._current_replicas))
        
        return max(1, min(cpu_factor, queue_factor, 5))  # Max 5 at a time
    
    async def execute_scaling(self, decision: Dict[str, Any]) -> bool:
        """Execute scaling decision."""
        # Check cooldown
        time_since_last_scale = (datetime.now() - self._last_scale_time).total_seconds()
        
        if decision["action"] == "scale_up" and time_since_last_scale < self._scale_up_cooldown:
            logger.info("Scale up on cooldown, skipping")
            return False
        
        if decision["action"] == "scale_down" and time_since_last_scale < self._scale_down_cooldown:
            logger.info("Scale down on cooldown, skipping")
            return False
        
        new_replicas = decision["desired_replicas"]
        
        # Execute K8s scale command (simulated)
        success = await self._scale_deployment(new_replicas)
        
        if success:
            import uuid
            event = ScalingEvent(
                event_id=str(uuid.uuid4()),
                timestamp=datetime.now().isoformat(),
                strategy=decision["strategy"],
                previous_replicas=self._current_replicas,
                new_replicas=new_replicas,
                reason=decision["reason"],
                metrics_snapshot=await self.get_cluster_metrics()
            )
            
            self._scaling_history.append(event)
            self._current_replicas = new_replicas
            self._last_scale_time = datetime.now()
            
            logger.info(
                f"Scaled from {event.previous_replicas} to {new_replicas} replicas: {decision['reason']}"
            )
        
        return success
    
    async def _scale_deployment(self, replicas: int) -> bool:
        """Execute Kubernetes scale command."""
        # In production: kubectl scale deployment viraclip-workers --replicas={replicas}
        # Simulated
        await self._simulate_scale_transition(replicas)
        return True
    
    async def _simulate_scale_transition(self, target_replicas: int) -> None:
        """Simulate pod scaling transition."""
        current = len(self._worker_pods)
        
        if target_replicas > current:
            # Scale up - add pods
            for i in range(target_replicas - current):
                import uuid
                pod_id = f"worker-{uuid.uuid4().hex[:8]}"
                self._worker_pods[pod_id] = WorkerPod(
                    pod_id=pod_id,
                    node_name=f"node-{i % 5}",
                    status=WorkerStatus.PENDING,
                    cpu_usage=0.0,
                    memory_usage=0.0,
                    active_tasks=0,
                    start_time=datetime.now().isoformat(),
                    estimated_completion=None,
                    clip_id=None
                )
        else:
            # Scale down - remove pods (graceful termination)
            pods_to_remove = list(self._worker_pods.keys())[:current - target_replicas]
            for pod_id in pods_to_remove:
                self._worker_pods[pod_id].status = WorkerStatus.TERMINATING
                del self._worker_pods[pod_id]
    
    async def auto_scale(self) -> Optional[ScalingEvent]:
        """Run auto-scaling evaluation and execution."""
        decision = await self.evaluate_scaling_needs()
        
        if decision:
            success = await self.execute_scaling(decision)
            if success:
                return self._scaling_history[-1]
        
        return None
    
    def get_worker_status(self) -> List[Dict[str, Any]]:
        """Get status of all worker pods."""
        return [
            {
                "pod_id": pod.pod_id,
                "node": pod.node_name,
                "status": pod.status.value,
                "cpu": f"{pod.cpu_usage:.1f}%",
                "memory": f"{pod.memory_usage:.1f}%",
                "active_tasks": pod.active_tasks,
                "clip_id": pod.clip_id,
                "uptime": pod.start_time
            }
            for pod in self._worker_pods.values()
        ]
    
    def get_scaling_history(
        self,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get scaling history."""
        history = sorted(
            self._scaling_history,
            key=lambda x: x.timestamp,
            reverse=True
        )[:limit]
        
        return [
            {
                "event_id": event.event_id,
                "timestamp": event.timestamp,
                "strategy": event.strategy.value,
                "from_replicas": event.previous_replicas,
                "to_replicas": event.new_replicas,
                "reason": event.reason
            }
            for event in history
        ]
    
    def get_scaling_stats(self) -> Dict[str, Any]:
        """Get scaling statistics."""
        if not self._scaling_history:
            return {}
        
        scale_ups = [e for e in self._scaling_history if e.new_replicas > e.previous_replicas]
        scale_downs = [e for e in self._scaling_history if e.new_replicas < e.previous_replicas]
        
        return {
            "total_scaling_events": len(self._scaling_history),
            "scale_up_events": len(scale_ups),
            "scale_down_events": len(scale_downs),
            "current_replicas": self._current_replicas,
            "min_replicas": self._min_replicas,
            "max_replicas": self._max_replicas,
            "avg_scale_up_size": (
                sum(e.new_replicas - e.previous_replicas for e in scale_ups) / len(scale_ups)
                if scale_ups else 0
            ),
            "last_scale_time": self._last_scale_time.isoformat()
        }
    
    async def predict_scaling_needs(
        self,
        lookahead_minutes: int = 30
    ) -> Dict[str, Any]:
        """Predict future scaling needs based on historical patterns."""
        if len(self._metrics_buffer) < 10:
            return {"error": "Insufficient data for prediction"}
        
        # Simple trend analysis
        recent = self._metrics_buffer[-10:]
        queue_trend = [m["queue_depth"] for m in recent]
        cpu_trend = [m["avg_cpu_utilization"] for m in recent]
        
        # Linear trend
        import numpy as np
        x = np.arange(len(queue_trend))
        
        if len(x) > 1:
            queue_slope = np.polyfit(x, queue_trend, 1)[0]
            cpu_slope = np.polyfit(x, cpu_trend, 1)[0]
        else:
            queue_slope = 0
            cpu_slope = 0
        
        # Predict future values
        future_queue = queue_trend[-1] + queue_slope * (lookahead_minutes / 5)
        future_cpu = cpu_trend[-1] + cpu_slope * (lookahead_minutes / 5)
        
        # Determine if scaling will be needed
        recommended_replicas = self._current_replicas
        if future_cpu > self._target_cpu_utilization or future_queue > self._target_queue_depth * self._current_replicas:
            recommended_replicas = min(self._current_replicas + 2, self._max_replicas)
        elif future_cpu < 30 and future_queue < self._target_queue_depth:
            recommended_replicas = max(self._current_replicas - 1, self._min_replicas)
        
        return {
            "current_replicas": self._current_replicas,
            "predicted_replicas": int(recommended_replicas),
            "predicted_queue_depth": int(future_queue),
            "predicted_cpu": float(future_cpu),
            "queue_trend": "increasing" if queue_slope > 0 else "decreasing",
            "cpu_trend": "increasing" if cpu_slope > 0 else "decreasing",
            "recommended_action": "scale_up" if recommended_replicas > self._current_replicas else "scale_down" if recommended_replicas < self._current_replicas else "maintain"
        }


# Global instance
_k8s_service: Optional[KubernetesScalingService] = None


def get_kubernetes_scaling_service() -> KubernetesScalingService:
    """Get global Kubernetes scaling service."""
    global _k8s_service
    if _k8s_service is None:
        _k8s_service = KubernetesScalingService()
    return _k8s_service


# Convenience functions
async def run_auto_scaling() -> Optional[Dict[str, Any]]:
    """Run auto-scaling cycle."""
    service = get_kubernetes_scaling_service()
    event = await service.auto_scale()
    
    if event:
        return {
            "scaled": True,
            "from": event.previous_replicas,
            "to": event.new_replicas,
            "reason": event.reason
        }
    
    return {"scaled": False}


async def get_cluster_status() -> Dict[str, Any]:
    """Get current cluster status."""
    service = get_kubernetes_scaling_service()
    return await service.get_cluster_metrics()
