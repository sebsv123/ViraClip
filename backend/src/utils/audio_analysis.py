"""
Audio analysis utilities for ViraClip V2.
Handles synchronization between multiple video sources using cross-correlation.
"""

import logging
import subprocess
import numpy as np
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

def extract_audio_as_array(video_path: Path, sample_rate: int = 16000) -> Optional[np.ndarray]:
    """
    Extract audio from video file and return it as a numpy array.
    Uses ffmpeg for high-performance extraction.
    """
    try:
        cmd = [
            "ffmpeg",
            "-i", str(video_path),
            "-vn",              # No video
            "-ac", "1",         # Mono
            "-ar", str(sample_rate), # 16kHz
            "-f", "s16le",      # PCM 16-bit
            "-",                # Pipe to stdout
        ]
        
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        audio_bytes, _ = process.communicate()
        
        if not audio_bytes:
            return None
            
        audio_array = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
        return audio_array
        
    except Exception as e:
        logger.error(f"Failed to extract audio from {video_path}: {e}")
        return None

def find_audio_offset(video_path_1: Path, video_path_2: Path, sample_rate: int = 16000) -> float:
    """
    Find the time offset (in seconds) between two video files using cross-correlation.
    Positive result means video_2 starts AFTER video_1.
    Negative result means video_2 starts BEFORE video_1.
    """
    logger.info(f"Finding audio offset between {video_path_1.name} and {video_path_2.name}")
    
    # Extract audio (first 60 seconds to speed up)
    audio1 = extract_audio_as_array(video_path_1, sample_rate)
    audio2 = extract_audio_as_array(video_path_2, sample_rate)
    
    if audio1 is None or audio2 is None:
        raise ValueError("Could not extract audio from one or both files")
        
    # Limit to 60s for correlation to avoid memory explosion
    limit = 60 * sample_rate
    audio1 = audio1[:limit]
    audio2 = audio2[:limit]
    
    # Cross-correlation
    correlation = np.correlate(audio1, audio2, mode='full')
    
    # Find the peak
    peak_index = int(np.argmax(correlation))
    
    # Calculate offset
    # The 'full' mode returns a correlation of length len(a1) + len(a2) - 1
    # The middle (zero offset) is at len(audio2) - 1
    offset_samples = peak_index - (len(audio2) - 1)
    offset_seconds = offset_samples / sample_rate
    
    logger.info(f"Detected audio offset: {offset_seconds:.3f}s")
    return offset_seconds
