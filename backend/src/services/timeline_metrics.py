"""
Timeline metrics collection and monitoring.
Tracks timeline building performance, Vision AI usage, and errors.
"""

import time
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TimelineMetrics:
    """Metrics for a single timeline building operation."""
    
    task_id: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    
    # Timing metrics (seconds)
    total_duration: float = 0.0
    frame_extraction_duration: float = 0.0
    vision_ai_duration: float = 0.0
    placement_duration: float = 0.0
    timeline_building_duration: float = 0.0
    
    # Resource metrics
    frames_extracted: int = 0
    frames_described: int = 0
    segments_created: int = 0
    text_lines_created: int = 0
    
    # Vision AI metrics
    vision_ai_enabled: bool = False
    vision_api_calls: int = 0
    vision_api_errors: int = 0
    
    # Status
    success: bool = False
    error_message: Optional[str] = None
    
    def mark_complete(self, success: bool = True, error: Optional[str] = None):
        """Mark timeline building as complete."""
        self.completed_at = datetime.now(timezone.utc)
        self.success = success
        self.error_message = error
        if self.started_at:
            self.total_duration = (self.completed_at - self.started_at).total_seconds()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary for logging/storage."""
        return {
            "task_id": self.task_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "total_duration": round(self.total_duration, 3),
            "frame_extraction_duration": round(self.frame_extraction_duration, 3),
            "vision_ai_duration": round(self.vision_ai_duration, 3),
            "placement_duration": round(self.placement_duration, 3),
            "timeline_building_duration": round(self.timeline_building_duration, 3),
            "frames_extracted": self.frames_extracted,
            "frames_described": self.frames_described,
            "segments_created": self.segments_created,
            "text_lines_created": self.text_lines_created,
            "vision_ai_enabled": self.vision_ai_enabled,
            "vision_api_calls": self.vision_api_calls,
            "vision_api_errors": self.vision_api_errors,
            "success": self.success,
            "error_message": self.error_message,
        }


class TimelineMetricsCollector:
    """Collects and aggregates timeline metrics across tasks."""
    
    def __init__(self):
        self._metrics: Dict[str, TimelineMetrics] = {}
        self._aggregate_stats = {
            "total_timelines": 0,
            "successful_timelines": 0,
            "failed_timelines": 0,
            "total_frames_extracted": 0,
            "total_frames_described": 0,
            "total_vision_api_calls": 0,
            "total_vision_api_errors": 0,
            "avg_total_duration": 0.0,
            "avg_vision_ai_duration": 0.0,
        }
    
    def start_timeline(self, task_id: str, vision_enabled: bool = False) -> TimelineMetrics:
        """Start tracking a timeline building operation."""
        metrics = TimelineMetrics(task_id=task_id, vision_ai_enabled=vision_enabled)
        self._metrics[task_id] = metrics
        logger.debug(f"[Metrics] Started tracking timeline for task {task_id}")
        return metrics
    
    def get_metrics(self, task_id: str) -> Optional[TimelineMetrics]:
        """Get metrics for a specific task."""
        return self._metrics.get(task_id)
    
    def complete_timeline(
        self,
        task_id: str,
        success: bool = True,
        error: Optional[str] = None,
    ):
        """Mark timeline as complete and update aggregate stats."""
        metrics = self._metrics.get(task_id)
        if not metrics:
            logger.warning(f"[Metrics] No metrics found for task {task_id}")
            return
        
        metrics.mark_complete(success, error)
        self._update_aggregate_stats(metrics)
        
        # Log summary
        logger.info(
            f"[Metrics] Timeline {task_id}: "
            f"success={success}, "
            f"duration={metrics.total_duration:.2f}s, "
            f"frames={metrics.frames_described}, "
            f"segments={metrics.segments_created}"
        )
    
    def _update_aggregate_stats(self, metrics: TimelineMetrics):
        """Update aggregate statistics with new metrics."""
        self._aggregate_stats["total_timelines"] += 1
        
        if metrics.success:
            self._aggregate_stats["successful_timelines"] += 1
        else:
            self._aggregate_stats["failed_timelines"] += 1
        
        self._aggregate_stats["total_frames_extracted"] += metrics.frames_extracted
        self._aggregate_stats["total_frames_described"] += metrics.frames_described
        self._aggregate_stats["total_vision_api_calls"] += metrics.vision_api_calls
        self._aggregate_stats["total_vision_api_errors"] += metrics.vision_api_errors
        
        # Update averages
        successful = self._aggregate_stats["successful_timelines"]
        if successful > 0:
            total_durations = sum(
                m.total_duration for m in self._metrics.values()
                if m.success and m.total_duration > 0
            )
            self._aggregate_stats["avg_total_duration"] = total_durations / successful
            
            if metrics.vision_ai_enabled:
                vision_durations = sum(
                    m.vision_ai_duration for m in self._metrics.values()
                    if m.success and m.vision_ai_enabled and m.vision_ai_duration > 0
                )
                vision_count = sum(
                    1 for m in self._metrics.values()
                    if m.success and m.vision_ai_enabled
                )
                if vision_count > 0:
                    self._aggregate_stats["avg_vision_ai_duration"] = vision_durations / vision_count
    
    def get_aggregate_stats(self) -> Dict[str, Any]:
        """Get aggregate statistics across all timelines."""
        stats = dict(self._aggregate_stats)
        
        # Add success rate
        total = stats["total_timelines"]
        if total > 0:
            stats["success_rate"] = stats["successful_timelines"] / total
        else:
            stats["success_rate"] = 0.0
        
        # Add Vision AI stats
        if stats["total_vision_api_calls"] > 0:
            stats["vision_error_rate"] = (
                stats["total_vision_api_errors"] / stats["total_vision_api_calls"]
            )
        else:
            stats["vision_error_rate"] = 0.0
        
        return stats
    
    def get_recent_metrics(self, limit: int = 10) -> list[Dict[str, Any]]:
        """Get most recent timeline metrics."""
        sorted_metrics = sorted(
            self._metrics.values(),
            key=lambda m: m.started_at,
            reverse=True
        )
        return [m.to_dict() for m in sorted_metrics[:limit]]
    
    def clear_old_metrics(self, max_age_hours: int = 24):
        """Clear metrics older than specified hours."""
        now = datetime.now(timezone.utc)
        cutoff = now.timestamp() - (max_age_hours * 3600)
        
        old_tasks = [
            task_id for task_id, m in self._metrics.items()
            if m.started_at.timestamp() < cutoff
        ]
        
        for task_id in old_tasks:
            del self._metrics[task_id]
        
        if old_tasks:
            logger.info(f"[Metrics] Cleared {len(old_tasks)} old metric entries")


# Global metrics collector singleton
_metrics_collector: Optional[TimelineMetricsCollector] = None


def get_metrics_collector() -> TimelineMetricsCollector:
    """Get or create the global metrics collector."""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = TimelineMetricsCollector()
    return _metrics_collector


def reset_metrics_collector():
    """Reset the global metrics collector (for testing)."""
    global _metrics_collector
    _metrics_collector = None


# Decorator for timing functions
class TimelineTimer:
    """Context manager for timing timeline operations."""
    
    def __init__(self, task_id: str, operation: str):
        self.task_id = task_id
        self.operation = operation
        self.start_time: Optional[float] = None
        self.duration: float = 0.0
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            self.duration = time.time() - self.start_time
            
            # Update metrics if available
            collector = get_metrics_collector()
            metrics = collector.get_metrics(self.task_id)
            if metrics:
                if self.operation == "frame_extraction":
                    metrics.frame_extraction_duration = self.duration
                elif self.operation == "vision_ai":
                    metrics.vision_ai_duration = self.duration
                elif self.operation == "placement":
                    metrics.placement_duration = self.duration
                elif self.operation == "timeline_building":
                    metrics.timeline_building_duration = self.duration
            
            logger.debug(
                f"[Metrics] {self.operation} for {self.task_id}: {self.duration:.3f}s"
            )
        
        return False  # Don't suppress exceptions
