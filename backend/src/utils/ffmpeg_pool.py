"""
Optimized FFmpeg Operations

Async FFmpeg processing with connection pooling and batch operations.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass

from src import gpu_utils

logger = logging.getLogger(__name__)


@dataclass
class FFmpegResult:
    """Result of FFmpeg operation."""
    success: bool
    output_path: Optional[Path]
    stdout: str
    stderr: str
    duration_ms: float


class FFmpegPool:
    """Pool for managing concurrent FFmpeg processes."""
    
    def __init__(self, max_concurrent: int = 4):
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_processes: List[asyncio.subprocess.Process] = []
    
    async def run_command(
        self,
        cmd: List[str],
        input_data: Optional[bytes] = None,
        timeout: int = 300
    ) -> FFmpegResult:
        """Run FFmpeg command with semaphore-controlled concurrency.
        
        Args:
            cmd: FFmpeg command and arguments
            input_data: Optional input data for stdin
            timeout: Maximum execution time in seconds
            
        Returns:
            FFmpegResult with success status and output
        """
        start_time = asyncio.get_event_loop().time()
        
        async with self._semaphore:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE if input_data else None,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                self._active_processes.append(proc)
                
                try:
                    stdout, stderr = await asyncio.wait_for(
                        proc.communicate(input=input_data),
                        timeout=timeout
                    )
                    
                    duration = (asyncio.get_event_loop().time() - start_time) * 1000
                    
                    success = proc.returncode == 0
                    stdout_str = stdout.decode('utf-8', errors='ignore') if stdout else ""
                    stderr_str = stderr.decode('utf-8', errors='ignore') if stderr else ""
                    
                    if success:
                        logger.debug(f"FFmpeg completed in {duration:.0f}ms")
                    else:
                        logger.warning(f"FFmpeg failed: {stderr_str[:200]}")
                    
                    return FFmpegResult(
                        success=success,
                        output_path=None,
                        stdout=stdout_str,
                        stderr=stderr_str,
                        duration_ms=duration
                    )
                    
                finally:
                    self._active_processes.remove(proc)
                    if proc.returncode is None:
                        proc.kill()
                        
            except asyncio.TimeoutError:
                logger.error(f"FFmpeg timeout after {timeout}s")
                return FFmpegResult(
                    success=False,
                    output_path=None,
                    stdout="",
                    stderr=f"Timeout after {timeout}s",
                    duration_ms=timeout * 1000
                )
            except Exception as e:
                logger.error(f"FFmpeg error: {e}")
                return FFmpegResult(
                    success=False,
                    output_path=None,
                    stdout="",
                    stderr=str(e),
                    duration_ms=0
                )
    
    async def extract_clip_fast(
        self,
        input_path: Path,
        output_path: Path,
        start_time: float,
        duration: float,
        copy_stream: bool = True
    ) -> FFmpegResult:
        """Fast clip extraction using stream copy when possible.
        
        Args:
            input_path: Source video path
            output_path: Output clip path
            start_time: Start time in seconds
            duration: Duration in seconds
            copy_stream: Use -c copy for fast extraction (no re-encode)
            
        Returns:
            FFmpegResult
        """
        if copy_stream:
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start_time),
                "-i", str(input_path),
                "-t", str(duration),
                "-c", "copy",
                "-movflags", "+faststart",
                str(output_path)
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start_time),
                "-i", str(input_path),
                "-t", str(duration),
                *gpu_utils.ffmpeg_codec_flags("medium"),
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                str(output_path)
            ]
        
        result = await self.run_command(cmd)
        result.output_path = output_path if result.success else None
        return result
    
    async def batch_extract_clips(
        self,
        input_path: Path,
        clips: List[Tuple[float, float, Path]],  # (start, duration, output)
        max_parallel: int = 2
    ) -> List[FFmpegResult]:
        """Extract multiple clips in parallel batches.
        
        Args:
            input_path: Source video path
            clips: List of (start_time, duration, output_path) tuples
            max_parallel: Maximum parallel extractions
            
        Returns:
            List of FFmpegResult
        """
        semaphore = asyncio.Semaphore(max_parallel)
        
        async def extract_single(start: float, duration: float, output: Path) -> FFmpegResult:
            async with semaphore:
                return await self.extract_clip_fast(input_path, output, start, duration)
        
        tasks = [
            extract_single(start, duration, output)
            for start, duration, output in clips
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle exceptions
        processed_results = []
        for result in results:
            if isinstance(result, Exception):
                processed_results.append(FFmpegResult(
                    success=False,
                    output_path=None,
                    stdout="",
                    stderr=str(result),
                    duration_ms=0
                ))
            else:
                processed_results.append(result)
        
        return processed_results
    
    async def merge_clips_concat(
        self,
        clip_paths: List[Path],
        output_path: Path,
        re_encode: bool = False
    ) -> FFmpegResult:
        """Merge clips using concat demuxer (fastest) or filter.
        
        Args:
            clip_paths: List of clip paths to merge
            output_path: Output path
            re_encode: Force re-encoding (slower but more compatible)
            
        Returns:
            FFmpegResult
        """
        # Create concat list file
        concat_list = output_path.with_suffix('.concat.txt')
        concat_content = "\n".join(f"file '{p.absolute()}'" for p in clip_paths)
        concat_list.write_text(concat_content)
        
        try:
            if re_encode:
                # Re-encode for maximum compatibility
                cmd = [
                    "ffmpeg", "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", str(concat_list),
                    *gpu_utils.ffmpeg_codec_flags("medium"),
                    "-c:a", "aac", "-b:a", "128k",
                    str(output_path)
                ]
            else:
                # Stream copy (fast)
                cmd = [
                    "ffmpeg", "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", str(concat_list),
                    "-c", "copy",
                    str(output_path)
                ]
            
            result = await self.run_command(cmd)
            result.output_path = output_path if result.success else None
            return result
            
        finally:
            concat_list.unlink(missing_ok=True)


# Global pool instance
_ffmpeg_pool: Optional[FFmpegPool] = None


def get_ffmpeg_pool(max_concurrent: int = 4) -> FFmpegPool:
    """Get or create global FFmpeg pool.
    
    Args:
        max_concurrent: Maximum concurrent FFmpeg processes
        
    Returns:
        FFmpegPool instance
    """
    global _ffmpeg_pool
    if _ffmpeg_pool is None:
        _ffmpeg_pool = FFmpegPool(max_concurrent=max_concurrent)
    return _ffmpeg_pool


async def quick_extract(
    input_path: Path,
    output_path: Path,
    start: float,
    duration: float
) -> bool:
    """Quick clip extraction helper function.
    
    Args:
        input_path: Source video
        output_path: Output clip
        start: Start time in seconds
        duration: Duration in seconds
        
    Returns:
        True if successful
    """
    pool = get_ffmpeg_pool()
    result = await pool.extract_clip_fast(input_path, output_path, start, duration)
    return result.success
