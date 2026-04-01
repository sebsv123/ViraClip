"""
Memory and Resource Management Module
Provides memory monitoring, automatic cleanup, and resource limits.
"""

import gc
import os
import logging
from typing import Optional, Dict, Any, List
from pathlib import Path
from contextlib import contextmanager
import tempfile
import shutil

logger = logging.getLogger(__name__)

def _get_psutil():
    """Lazy import psutil to avoid import errors in worker initialization."""
    import psutil
    return psutil

class MemoryManager:
    """
    Manages memory usage and provides automatic cleanup mechanisms.
    """
    
    def __init__(self, max_memory_percent: float = 85.0, critical_memory_percent: float = 95.0):
        self.max_memory_percent = max_memory_percent
        self.critical_memory_percent = critical_memory_percent
        psutil = _get_psutil()
        self.process = psutil.Process()
        
    def get_memory_usage(self) -> Dict[str, Any]:
        """Get current memory usage statistics."""
        psutil = _get_psutil()
        system_memory = psutil.virtual_memory()
        process_memory = self.process.memory_info()
        
        return {
            "system": {
                "total_gb": system_memory.total / (1024**3),
                "available_gb": system_memory.available / (1024**3),
                "percent": system_memory.percent,
            },
            "process": {
                "rss_mb": process_memory.rss / (1024**2),
                "vms_mb": process_memory.vms / (1024**2),
            },
            "is_critical": system_memory.percent > self.critical_memory_percent,
            "is_high": system_memory.percent > self.max_memory_percent,
        }
    
    def check_memory(self, operation_name: str = "unknown") -> bool:
        """
        Check if memory is within acceptable limits.
        Returns False if memory is critical.
        """
        mem = self.get_memory_usage()
        
        if mem["is_critical"]:
            logger.error(
                f"CRITICAL MEMORY: {mem['system']['percent']:.1f}% - "
                f"Operation '{operation_name}' blocked"
            )
            return False
        
        if mem["is_high"]:
            logger.warning(
                f"High memory usage: {mem['system']['percent']:.1f}% - "
                f"consider throttling '{operation_name}'"
            )
            self.cleanup()
        
        return True
    
    def cleanup(self) -> None:
        """Force garbage collection and log memory state."""
        gc.collect()
        
        mem = self.get_memory_usage()
        logger.info(
            f"Memory cleanup performed: "
            f"System {mem['system']['percent']:.1f}%, "
            f"Process {mem['process']['rss_mb']:.1f}MB RSS"
        )
    
    @contextmanager
    def monitor(self, operation_name: str):
        """
        Context manager to monitor memory during an operation.
        
        Usage:
            with memory_manager.monitor("transcription"):
                # perform operation
                pass
        """
        start_mem = self.get_memory_usage()
        logger.debug(f"[{operation_name}] Starting - Memory: {start_mem['system']['percent']:.1f}%")
        
        try:
            yield self
        finally:
            end_mem = self.get_memory_usage()
            delta_mb = end_mem['process']['rss_mb'] - start_mem['process']['rss_mb']
            logger.debug(
                f"[{operation_name}] Complete - "
                f"Memory delta: {delta_mb:+.1f}MB, "
                f"Total: {end_mem['system']['percent']:.1f}%"
            )


class ResourceLimiter:
    """
    Limits resources for operations to prevent system overload.
    """
    
    def __init__(
        self,
        max_concurrent_ops: int = 5,
        max_memory_percent: float = 85.0,
        max_disk_usage_percent: float = 90.0
    ):
        self.max_concurrent_ops = max_concurrent_ops
        self.max_memory_percent = max_memory_percent
        self.max_disk_usage_percent = max_disk_usage_percent
        self._active_ops = 0
        
    def can_start_operation(self) -> bool:
        """Check if system can handle another operation."""
        if self._active_ops >= self.max_concurrent_ops:
            logger.warning(f"Max concurrent operations ({self.max_concurrent_ops}) reached")
            return False
        
        psutil = _get_psutil()
        mem = psutil.virtual_memory()
        if mem.percent > self.max_memory_percent:
            logger.warning(f"Memory too high ({mem.percent:.1f}%) for new operation")
            return False
        
        return True
    
    def start_operation(self) -> bool:
        """Mark an operation as started."""
        if not self.can_start_operation():
            return False
        self._active_ops += 1
        return True
    
    def end_operation(self) -> None:
        """Mark an operation as ended."""
        self._active_ops = max(0, self._active_ops - 1)


class TempFileManager:
    """
    Manages temporary files with automatic cleanup.
    """
    
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or Path(tempfile.gettempdir()) / "viraclip"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._tracked_files: List[Path] = []
        
    def create_temp_dir(self, prefix: str = "clip_") -> Path:
        """Create a temporary directory."""
        temp_dir = Path(tempfile.mkdtemp(prefix=prefix, dir=self.base_dir))
        return temp_dir
    
    def track_file(self, file_path: Path) -> None:
        """Track a file for later cleanup."""
        self._tracked_files.append(file_path)
    
    def cleanup_file(self, file_path: Path) -> bool:
        """Clean up a specific file."""
        try:
            if file_path.exists():
                if file_path.is_file():
                    file_path.unlink()
                elif file_path.is_dir():
                    shutil.rmtree(file_path)
                logger.debug(f"Cleaned up: {file_path}")
                return True
        except Exception as e:
            logger.warning(f"Failed to cleanup {file_path}: {e}")
        return False
    
    def cleanup_old_files(self, max_age_hours: int = 24) -> int:
        """
        Clean up files older than specified hours.
        Returns number of files cleaned.
        """
        import time
        
        cleaned = 0
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600
        
        for item in self.base_dir.iterdir():
            try:
                item_age = current_time - item.stat().st_mtime
                if item_age > max_age_seconds:
                    if self.cleanup_file(item):
                        cleaned += 1
            except Exception as e:
                logger.warning(f"Error checking {item}: {e}")
        
        logger.info(f"Cleaned up {cleaned} old temporary files")
        return cleaned
    
    def cleanup_all_tracked(self) -> int:
        """Clean up all tracked files."""
        cleaned = 0
        for file_path in self._tracked_files:
            if self.cleanup_file(file_path):
                cleaned += 1
        self._tracked_files.clear()
        return cleaned


class VideoMemoryOptimizer:
    """
    Optimizes memory usage specifically for video processing.
    """
    
    @staticmethod
    def estimate_video_memory(video_path: Path) -> Dict[str, float]:
        """
        Estimate memory needed to process a video.
        Returns dict with memory estimates in MB.
        """
        try:
            # Get video info using ffprobe
            import subprocess
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=width,height,bit_rate",
                    "-show_entries", "format=duration",
                    "-of", "json",
                    str(video_path)
                ],
                capture_output=True,
                text=True
            )
            
            import json
            info = json.loads(result.stdout)
            
            stream = info.get("streams", [{}])[0]
            format_info = info.get("format", {})
            
            width = int(stream.get("width", 1920))
            height = int(stream.get("height", 1080))
            duration = float(format_info.get("duration", 0))
            
            # Estimate: 3 frames at full resolution (RGBA) for processing
            frame_memory = (width * height * 4) / (1024**2)  # MB
            
            return {
                "frame_mb": frame_memory,
                "duration_sec": duration,
                "resolution": f"{width}x{height}",
                "estimated_peak_mb": frame_memory * 5,  # 5 frames buffer
                "recommended_max_concurrent": max(1, int(4000 / frame_memory)),
            }
        except Exception as e:
            logger.warning(f"Failed to estimate video memory: {e}")
            return {
                "frame_mb": 100,
                "duration_sec": 0,
                "resolution": "unknown",
                "estimated_peak_mb": 500,
                "recommended_max_concurrent": 4,
            }
    
    @staticmethod
    def get_optimal_concurrency(video_paths: List[Path]) -> int:
        """
        Calculate optimal number of concurrent operations based on
        available memory and video requirements.
        """
        psutil = _get_psutil()
        mem = psutil.virtual_memory()
        available_mb = mem.available / (1024**2)
        
        # Conservative: use only 50% of available memory
        usable_mb = available_mb * 0.5
        
        # Estimate memory per video
        total_estimated_mb = 0
        for path in video_paths:
            est = VideoMemoryOptimizer.estimate_video_memory(path)
            total_estimated_mb += est["estimated_peak_mb"]
        
        if total_estimated_mb == 0:
            return 2
        
        optimal = max(1, int(usable_mb / (total_estimated_mb / len(video_paths))))
        
        # Cap at CPU count
        cpu_count = os.cpu_count() or 4
        return min(optimal, cpu_count, 8)  # Max 8 concurrent


# Global instances
_memory_manager: Optional[MemoryManager] = None
_resource_limiter: Optional[ResourceLimiter] = None
_temp_file_manager: Optional[TempFileManager] = None


def get_memory_manager() -> MemoryManager:
    """Get global memory manager instance."""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager


def get_resource_limiter() -> ResourceLimiter:
    """Get global resource limiter instance."""
    global _resource_limiter
    if _resource_limiter is None:
        _resource_limiter = ResourceLimiter()
    return _resource_limiter


def get_temp_file_manager() -> TempFileManager:
    """Get global temp file manager instance."""
    global _temp_file_manager
    if _temp_file_manager is None:
        _temp_file_manager = TempFileManager()
    return _temp_file_manager


# Convenience functions
def check_memory(operation_name: str = "unknown") -> bool:
    """Quick check if memory is available for operation."""
    return get_memory_manager().check_memory(operation_name)


def cleanup_memory() -> None:
    """Force memory cleanup."""
    get_memory_manager().cleanup()


def cleanup_old_temp_files(max_age_hours: int = 24) -> int:
    """Clean up old temporary files."""
    return get_temp_file_manager().cleanup_old_files(max_age_hours)
