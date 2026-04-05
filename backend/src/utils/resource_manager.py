"""
Resource Manager — CPU/GPU detection, memory monitoring, and adaptive optimization.

Automatically adjusts processing settings based on available hardware to prevent
system collapse on low-end machines.
"""

import logging
import os
import platform
import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple

try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None  # type: ignore
    _PSUTIL_AVAILABLE = False

logger = logging.getLogger(__name__)


def detect_hardware_capabilities() -> Dict[str, any]:
    """
    Detect CPU cores, RAM, and GPU availability.
    Returns dict with system specs and recommended settings.
    """
    try:
        cpu_count = psutil.cpu_count(logical=False) or 2  # Physical cores
        cpu_count_logical = psutil.cpu_count(logical=True) or 4
        ram_gb = psutil.virtual_memory().total / (1024**3)
        
        # Detect GPU
        has_nvidia = False
        has_amd = False
        
        if platform.system() == "Linux":
            try:
                nvidia_check = subprocess.run(
                    ["nvidia-smi", "-L"],
                    capture_output=True,
                    timeout=2
                )
                has_nvidia = nvidia_check.returncode == 0
            except:
                pass
                
            try:
                amd_check = subprocess.run(
                    ["rocm-smi", "--showproductname"],
                    capture_output=True,
                    timeout=2
                )
                has_amd = amd_check.returncode == 0
            except:
                pass
        
        # Classify system tier
        if has_nvidia or has_amd:
            tier = "high"  # GPU available
        elif cpu_count >= 6 and ram_gb >= 16:
            tier = "medium"  # Good CPU, no GPU
        elif cpu_count >= 4 and ram_gb >= 8:
            tier = "low"  # Minimal viable
        else:
            tier = "minimal"  # Very low-end
        
        logger.info(
            f"[Hardware] Tier: {tier} | CPU: {cpu_count}c/{cpu_count_logical}t "
            f"| RAM: {ram_gb:.1f}GB | GPU: {has_nvidia or has_amd}"
        )
        
        return {
            "tier": tier,
            "cpu_cores": cpu_count,
            "cpu_threads": cpu_count_logical,
            "ram_gb": ram_gb,
            "has_gpu": has_nvidia or has_amd,
            "has_nvidia": has_nvidia,
            "has_amd": has_amd,
        }
    except Exception as e:
        logger.warning(f"Hardware detection failed: {e}, using safe defaults")
        return {
            "tier": "low",
            "cpu_cores": 2,
            "cpu_threads": 4,
            "ram_gb": 8.0,
            "has_gpu": False,
            "has_nvidia": False,
            "has_amd": False,
        }


def get_adaptive_settings(hw_caps: Optional[Dict] = None) -> Dict[str, any]:
    """
    Return optimized settings based on hardware tier.
    
    Settings include:
    - render_concurrency: How many clips to render in parallel
    - whisper_model: Transcription model size
    - ffmpeg_preset: Encoding speed vs quality
    - max_clips: Maximum clips per task
    - enable_heavy_effects: Whether to use grain, beat sync, etc.
    """
    if hw_caps is None:
        hw_caps = detect_hardware_capabilities()
    
    tier = hw_caps.get("tier", "low")
    
    settings = {
        "high": {
            "render_concurrency": 4,
            "whisper_model": "medium",
            "ffmpeg_preset": "fast",
            "max_clips": 6,
            "enable_heavy_effects": True,
            "film_grain": 10,
            "beat_sync": True,
            "crf": 23,
        },
        "medium": {
            "render_concurrency": 2,
            "whisper_model": "small",
            "ffmpeg_preset": "veryfast",
            "max_clips": 4,
            "enable_heavy_effects": False,
            "film_grain": 5,
            "beat_sync": False,
            "crf": 25,
        },
        "low": {
            "render_concurrency": 1,
            "whisper_model": "tiny",
            "ffmpeg_preset": "veryfast",
            "max_clips": 3,
            "enable_heavy_effects": False,
            "film_grain": 0,
            "beat_sync": False,
            "crf": 26,
        },
        "minimal": {
            "render_concurrency": 1,
            "whisper_model": "tiny",
            "ffmpeg_preset": "ultrafast",
            "max_clips": 2,
            "enable_heavy_effects": False,
            "film_grain": 0,
            "beat_sync": False,
            "crf": 28,
        }
    }
    
    return settings.get(tier, settings["low"])


def cleanup_temp_files(base_dir: Path, max_age_hours: int = 24, dry_run: bool = False) -> Tuple[int, int]:
    """
    Aggressively clean up old temporary files to prevent disk bloat.
    
    Args:
        base_dir: Root temp directory to clean
        max_age_hours: Delete files older than this
        dry_run: If True, only report what would be deleted
        
    Returns:
        (files_deleted, mb_freed)
    """
    import time
    
    if not base_dir.exists():
        return 0, 0
    
    now = time.time()
    max_age_seconds = max_age_hours * 3600
    files_deleted = 0
    bytes_freed = 0
    
    patterns = [
        "*.mp4",
        "*.wav",
        "*.m4a",
        "*.jpg",
        "*.png",
        "*.srt",
        "*.ass",
        "segment_*.mp4",
        "temp-audio-*.m4a",
        "dubbed_*.mp4",
        "final_*.mp4",
        "sound_*.mp4",
        "music_*.mp4",
    ]
    
    try:
        for pattern in patterns:
            for file_path in base_dir.rglob(pattern):
                if not file_path.is_file():
                    continue
                    
                try:
                    age = now - file_path.stat().st_mtime
                    if age > max_age_seconds:
                        size = file_path.stat().st_size
                        if not dry_run:
                            file_path.unlink()
                        files_deleted += 1
                        bytes_freed += size
                except Exception as e:
                    logger.debug(f"Could not delete {file_path}: {e}")
        
        mb_freed = bytes_freed / (1024 * 1024)
        
        if files_deleted > 0:
            action = "Would delete" if dry_run else "Deleted"
            logger.info(
                f"[Cleanup] {action} {files_deleted} temp files, "
                f"freed {mb_freed:.1f}MB from {base_dir}"
            )
        
        return files_deleted, int(mb_freed)
        
    except Exception as e:
        logger.error(f"Temp cleanup failed: {e}")
        return 0, 0


def get_memory_pressure() -> str:
    """
    Check current memory pressure.
    Returns: 'low', 'medium', 'high', 'critical'
    """
    try:
        mem = psutil.virtual_memory()
        percent_used = mem.percent
        
        if percent_used < 60:
            return "low"
        elif percent_used < 75:
            return "medium"
        elif percent_used < 90:
            return "high"
        else:
            return "critical"
    except:
        return "medium"


def should_throttle_processing() -> bool:
    """
    Check if system resources are critically low.
    Returns True if processing should be throttled/paused.
    """
    try:
        mem = psutil.virtual_memory()
        cpu_percent = psutil.cpu_percent(interval=1)
        
        # Critical: RAM >95% or CPU sustained >98%
        if mem.percent > 95 or cpu_percent > 98:
            logger.warning(
                f"⚠️ Critical resource usage: RAM {mem.percent:.1f}%, CPU {cpu_percent:.1f}%"
            )
            return True
            
        return False
    except:
        return False
