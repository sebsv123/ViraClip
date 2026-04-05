"""
Performance Monitor — Profiling & Optimization
==============================================
Monitor and profile performance of critical operations.

Features:
- Function execution time tracking
- Memory usage profiling
- Bottleneck detection
- Performance metrics export
"""

import os
import time
import logging
import asyncio
import psutil
from typing import Callable, Dict, Any, Optional
from functools import wraps
from datetime import datetime
from pathlib import Path
import json

logger = logging.getLogger(__name__)

# Global metrics storage
_performance_metrics: Dict[str, list] = {}
_enabled = os.getenv("PERFORMANCE_MONITORING", "false").lower() == "true"


def profile_execution(
    name: Optional[str] = None,
    track_memory: bool = True,
    log_slow: float = 1.0  # Log if slower than 1 second
):
    """
    Decorator to profile function execution time and memory usage.
    
    Args:
        name: Custom metric name (default: function name)
        track_memory: Whether to track memory usage
        log_slow: Log warning if execution > this many seconds
    
    Example:
        @profile_execution(name="video_processing", log_slow=5.0)
        async def process_video(path: str):
            # ... processing
            pass
    """
    def decorator(func: Callable):
        metric_name = name or f"{func.__module__}.{func.__name__}"
        
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            if not _enabled:
                return await func(*args, **kwargs)
            
            process = psutil.Process()
            mem_before = process.memory_info().rss / 1024 / 1024 if track_memory else 0
            
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start
                
                mem_after = process.memory_info().rss / 1024 / 1024 if track_memory else 0
                mem_delta = mem_after - mem_before
                
                # Store metrics
                if metric_name not in _performance_metrics:
                    _performance_metrics[metric_name] = []
                
                _performance_metrics[metric_name].append({
                    "duration": duration,
                    "memory_delta_mb": mem_delta if track_memory else None,
                    "timestamp": datetime.now().isoformat()
                })
                
                # Log slow operations
                if duration > log_slow:
                    logger.warning(
                        f"[perf] SLOW: {metric_name} took {duration:.2f}s "
                        f"(threshold: {log_slow}s)"
                    )
                else:
                    logger.debug(f"[perf] {metric_name}: {duration:.3f}s")
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            if not _enabled:
                return func(*args, **kwargs)
            
            process = psutil.Process()
            mem_before = process.memory_info().rss / 1024 / 1024 if track_memory else 0
            
            start = time.time()
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start
                
                mem_after = process.memory_info().rss / 1024 / 1024 if track_memory else 0
                mem_delta = mem_after - mem_before
                
                if metric_name not in _performance_metrics:
                    _performance_metrics[metric_name] = []
                
                _performance_metrics[metric_name].append({
                    "duration": duration,
                    "memory_delta_mb": mem_delta if track_memory else None,
                    "timestamp": datetime.now().isoformat()
                })
                
                if duration > log_slow:
                    logger.warning(
                        f"[perf] SLOW: {metric_name} took {duration:.2f}s "
                        f"(threshold: {log_slow}s)"
                    )
                else:
                    logger.debug(f"[perf] {metric_name}: {duration:.3f}s")
        
        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def get_performance_stats(metric_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Get performance statistics for metrics.
    
    Args:
        metric_name: Specific metric to get stats for, or None for all
    
    Returns:
        Dictionary with min, max, avg, p95, p99 for each metric
    """
    if not _enabled:
        return {"enabled": False}
    
    stats = {}
    
    metrics_to_process = (
        {metric_name: _performance_metrics[metric_name]} 
        if metric_name and metric_name in _performance_metrics
        else _performance_metrics
    )
    
    for name, measurements in metrics_to_process.items():
        if not measurements:
            continue
        
        durations = [m["duration"] for m in measurements]
        durations.sort()
        
        n = len(durations)
        p95_idx = int(n * 0.95)
        p99_idx = int(n * 0.99)
        
        stats[name] = {
            "count": n,
            "min": durations[0],
            "max": durations[-1],
            "avg": sum(durations) / n,
            "p50": durations[n // 2],
            "p95": durations[p95_idx] if p95_idx < n else durations[-1],
            "p99": durations[p99_idx] if p99_idx < n else durations[-1]
        }
        
        # Add memory stats if tracked
        memory_deltas = [m["memory_delta_mb"] for m in measurements if m["memory_delta_mb"] is not None]
        if memory_deltas:
            stats[name]["memory_avg_mb"] = sum(memory_deltas) / len(memory_deltas)
            stats[name]["memory_max_mb"] = max(memory_deltas)
    
    return stats


def export_performance_report(output_path: str):
    """Export performance metrics to JSON file."""
    if not _enabled:
        logger.info("[perf] Performance monitoring not enabled")
        return
    
    stats = get_performance_stats()
    
    report = {
        "generated_at": datetime.now().isoformat(),
        "metrics": stats,
        "system_info": {
            "cpu_percent": psutil.cpu_percent(interval=1),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage('/').percent
        }
    }
    
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w') as f:
        json.dump(report, f, indent=2)
    
    logger.info(f"[perf] Performance report exported: {output_path}")


def clear_metrics(metric_name: Optional[str] = None):
    """Clear performance metrics."""
    if metric_name:
        if metric_name in _performance_metrics:
            _performance_metrics[metric_name].clear()
            logger.info(f"[perf] Cleared metrics: {metric_name}")
    else:
        _performance_metrics.clear()
        logger.info("[perf] Cleared all metrics")


def get_system_stats() -> Dict[str, Any]:
    """Get current system resource usage."""
    return {
        "cpu": {
            "percent": psutil.cpu_percent(interval=0.1),
            "count": psutil.cpu_count(),
            "freq_mhz": psutil.cpu_freq().current if psutil.cpu_freq() else None
        },
        "memory": {
            "total_gb": psutil.virtual_memory().total / 1024 / 1024 / 1024,
            "available_gb": psutil.virtual_memory().available / 1024 / 1024 / 1024,
            "used_gb": psutil.virtual_memory().used / 1024 / 1024 / 1024,
            "percent": psutil.virtual_memory().percent
        },
        "disk": {
            "total_gb": psutil.disk_usage('/').total / 1024 / 1024 / 1024,
            "used_gb": psutil.disk_usage('/').used / 1024 / 1024 / 1024,
            "free_gb": psutil.disk_usage('/').free / 1024 / 1024 / 1024,
            "percent": psutil.disk_usage('/').percent
        }
    }
