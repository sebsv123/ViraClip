"""
Performance Metrics and Monitoring Module
Tracks performance, success rates, and pipeline health.
"""

import time
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PipelineMetrics:
    """Metrics for a single pipeline run."""
    task_id: str
    start_time: float
    end_time: Optional[float] = None
    stages: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    success: bool = False
    errors: List[str] = field(default_factory=list)
    
    def record_stage(self, stage_name: str, duration: float, success: bool = True, metadata: Optional[Dict] = None):
        """Record metrics for a pipeline stage."""
        self.stages[stage_name] = {
            "duration_ms": duration * 1000,
            "success": success,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {},
        }
    
    def finish(self, success: bool = True, error: Optional[str] = None):
        """Mark pipeline as complete."""
        self.end_time = time.time()
        self.success = success
        if error:
            self.errors.append(error)
    
    @property
    def total_duration(self) -> float:
        """Get total pipeline duration in seconds."""
        if self.end_time:
            return self.end_time - self.start_time
        return time.time() - self.start_time
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "task_id": self.task_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_duration_sec": self.total_duration,
            "success": self.success,
            "stages": self.stages,
            "errors": self.errors,
        }


class MetricsCollector:
    """Collects and aggregates pipeline metrics."""
    
    def __init__(self):
        self._active_pipelines: Dict[str, PipelineMetrics] = {}
        self._completed_pipelines: List[PipelineMetrics] = []
        self._stage_stats: Dict[str, List[float]] = defaultdict(list)
        self._error_counts: Dict[str, int] = defaultdict(int)
        self._daily_stats: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"total": 0, "success": 0, "failed": 0}
        )
    
    def start_pipeline(self, task_id: str) -> PipelineMetrics:
        """Start tracking a new pipeline."""
        metrics = PipelineMetrics(
            task_id=task_id,
            start_time=time.time()
        )
        self._active_pipelines[task_id] = metrics
        logger.debug(f"Started metrics tracking for task {task_id}")
        return metrics
    
    def get_pipeline(self, task_id: str) -> Optional[PipelineMetrics]:
        """Get active pipeline metrics."""
        return self._active_pipelines.get(task_id)
    
    def finish_pipeline(self, task_id: str, success: bool = True, error: Optional[str] = None):
        """Finish tracking a pipeline."""
        if task_id not in self._active_pipelines:
            logger.warning(f"No active pipeline found for task {task_id}")
            return
        
        metrics = self._active_pipelines[task_id]
        metrics.finish(success, error)
        
        # Move to completed
        self._completed_pipelines.append(metrics)
        del self._active_pipelines[task_id]
        
        # Update stats
        today = datetime.now().strftime("%Y-%m-%d")
        self._daily_stats[today]["total"] += 1
        if success:
            self._daily_stats[today]["success"] += 1
        else:
            self._daily_stats[today]["failed"] += 1
        
        # Update stage stats
        for stage_name, stage_data in metrics.stages.items():
            duration = stage_data["duration_ms"]
            self._stage_stats[stage_name].append(duration)
        
        # Update error counts
        if error:
            error_type = error.split(":")[0] if ":" in error else "unknown"
            self._error_counts[error_type] += 1
        
        # Log summary
        status = "✅ SUCCESS" if success else "❌ FAILED"
        logger.info(
            f"Pipeline {task_id} {status} in {metrics.total_duration:.1f}s "
            f"({len(metrics.stages)} stages)"
        )
    
    def record_stage(
        self, 
        task_id: str, 
        stage_name: str, 
        duration: float,
        success: bool = True,
        metadata: Optional[Dict] = None
    ):
        """Record a stage completion."""
        if task_id in self._active_pipelines:
            self._active_pipelines[task_id].record_stage(
                stage_name, duration, success, metadata
            )
    
    def get_summary(self, days: int = 7) -> Dict[str, Any]:
        """Get performance summary."""
        # Recent pipelines
        recent = self._completed_pipelines[-100:]
        
        # Success rate
        total_recent = len(recent)
        success_recent = sum(1 for p in recent if p.success)
        success_rate = success_recent / total_recent if total_recent > 0 else 0
        
        # Stage averages
        stage_averages = {}
        for stage_name, durations in self._stage_stats.items():
            if durations:
                avg = sum(durations) / len(durations)
                stage_averages[stage_name] = {
                    "avg_ms": avg,
                    "count": len(durations),
                    "min_ms": min(durations),
                    "max_ms": max(durations),
                }
        
        # Daily stats
        dates = sorted(self._daily_stats.keys())[-days:]
        daily = {d: self._daily_stats[d] for d in dates}
        
        return {
            "total_pipelines": len(self._completed_pipelines),
            "recent_success_rate": success_rate,
            "active_pipelines": len(self._active_pipelines),
            "stage_averages": stage_averages,
            "daily_stats": daily,
            "top_errors": dict(self._error_counts.most_common(10) if hasattr(self._error_counts, 'most_common') else sorted(self._error_counts.items(), key=lambda x: x[1], reverse=True)[:10]),
        }
    
    def get_pipeline_report(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed report for a specific pipeline."""
        # Check active
        if task_id in self._active_pipelines:
            return self._active_pipelines[task_id].to_dict()
        
        # Check completed
        for pipeline in reversed(self._completed_pipelines):
            if pipeline.task_id == task_id:
                return pipeline.to_dict()
        
        return None
    
    def get_slow_stages(self, threshold_ms: float = 5000) -> List[Dict[str, Any]]:
        """Get stages that are consistently slow."""
        slow = []
        for stage_name, durations in self._stage_stats.items():
            if durations:
                avg = sum(durations) / len(durations)
                if avg > threshold_ms:
                    slow.append({
                        "stage": stage_name,
                        "avg_duration_ms": avg,
                        "count": len(durations),
                    })
        return sorted(slow, key=lambda x: x["avg_duration_ms"], reverse=True)


# Global instance
_metrics_collector: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """Get global metrics collector."""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


# Decorator for automatic metrics collection
def timed_stage(stage_name: str):
    """Decorator to automatically time a pipeline stage."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            task_id = kwargs.get('task_id') or (args[0] if args else 'unknown')
            collector = get_metrics_collector()
            
            start = time.time()
            success = True
            error = None
            
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                success = False
                error = str(e)
                raise
            finally:
                duration = time.time() - start
                collector.record_stage(task_id, stage_name, duration, success)
        
        return wrapper
    return decorator


class HealthChecker:
    """System health monitoring."""
    
    def __init__(self):
        self._checks: Dict[str, Any] = {}
        self._last_check: Optional[datetime] = None
    
    def register_check(self, name: str, check_func, critical: bool = True):
        """Register a health check."""
        self._checks[name] = {
            "func": check_func,
            "critical": critical,
        }
    
    async def run_checks(self) -> Dict[str, Any]:
        """Run all health checks."""
        results = {
            "status": "healthy",
            "checks": {},
            "timestamp": datetime.now().isoformat(),
        }
        
        for name, check in self._checks.items():
            try:
                result = await check["func"]()
                results["checks"][name] = {
                    "status": "pass",
                    "result": result,
                }
            except Exception as e:
                results["checks"][name] = {
                    "status": "fail",
                    "error": str(e),
                }
                if check["critical"]:
                    results["status"] = "unhealthy"
        
        self._last_check = datetime.now()
        return results


# Predefined health checks
async def check_redis_connection():
    """Check Redis connectivity."""
    try:
        import redis.asyncio as aioredis
        from ..config import get_config
        config = get_config()
        
        redis = aioredis.Redis(
            host=config.redis_host,
            port=config.redis_port,
            password=config.redis_password,
        )
        await redis.ping()
        await redis.aclose()
        return "connected"
    except Exception as e:
        raise Exception(f"Redis check failed: {e}")


async def check_disk_space():
    """Check available disk space."""
    import shutil
    from ..config import get_config
    config = get_config()
    
    temp_dir = Path(config.temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    stat = shutil.disk_usage(temp_dir)
    free_gb = stat.free / (1024**3)
    total_gb = stat.total / (1024**3)
    
    if free_gb < 1.0:  # Less than 1GB
        raise Exception(f"Low disk space: {free_gb:.1f}GB remaining")
    
    return {"free_gb": free_gb, "total_gb": total_gb}


async def check_gpu_availability():
    """Check GPU availability."""
    try:
        import torch
        if torch.cuda.is_available():
            return {
                "available": True,
                "device_count": torch.cuda.device_count(),
                "device_name": torch.cuda.get_device_name(0),
            }
        return {"available": False}
    except ImportError:
        return {"available": False, "reason": "torch not installed"}
