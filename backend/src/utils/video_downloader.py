"""
Async Video Downloader

High-performance async video downloading with connection pooling,
progress tracking, and retry logic.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional, Callable, Dict, Any
from dataclasses import dataclass
from urllib.parse import urlparse

import aiohttp
import aiofiles

logger = logging.getLogger(__name__)


@dataclass
class DownloadResult:
    """Result of video download."""
    success: bool
    file_path: Optional[Path]
    file_size: int
    duration_ms: float
    error: Optional[str] = None


class VideoDownloader:
    """Async video downloader with connection pooling."""
    
    def __init__(
        self,
        max_connections: int = 10,
        chunk_size: int = 8192,  # 8KB chunks
        timeout: int = 300,
    ):
        self.max_connections = max_connections
        self.chunk_size = chunk_size
        self.timeout = timeout
        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore = asyncio.Semaphore(max_connections)
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session with connection pooling."""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=self.max_connections,
                limit_per_host=4,  # Max 4 connections per host
                enable_cleanup_closed=True,
                force_close=False,
            )
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
            )
        return self._session
    
    async def download(
        self,
        url: str,
        output_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> DownloadResult:
        """Download video from URL to file.
        
        Args:
            url: Video URL
            output_path: Local file path
            progress_callback: Optional callback(bytes_downloaded, total_bytes)
            headers: Optional request headers
            
        Returns:
            DownloadResult
        """
        start_time = asyncio.get_event_loop().time()
        
        async with self._semaphore:
            try:
                session = await self._get_session()
                
                # Make request
                request_headers = headers or {}
                async with session.get(url, headers=request_headers) as response:
                    if response.status != 200:
                        error_msg = f"HTTP {response.status}"
                        logger.error(f"Download failed: {error_msg} for {url}")
                        return DownloadResult(
                            success=False,
                            file_path=None,
                            file_size=0,
                            duration_ms=0,
                            error=error_msg
                        )
                    
                    # Get content length if available
                    total_size = int(response.headers.get('content-length', 0))
                    downloaded = 0
                    
                    # Write to file
                    async with aiofiles.open(output_path, 'wb') as f:
                        async for chunk in response.content.iter_chunked(self.chunk_size):
                            await f.write(chunk)
                            downloaded += len(chunk)
                            
                            if progress_callback and total_size > 0:
                                progress_callback(downloaded, total_size)
                    
                    duration = (asyncio.get_event_loop().time() - start_time) * 1000
                    
                    logger.info(
                        f"Downloaded {url} → {output_path} "
                        f"({downloaded/1024/1024:.1f} MB in {duration:.0f}ms)"
                    )
                    
                    return DownloadResult(
                        success=True,
                        file_path=output_path,
                        file_size=downloaded,
                        duration_ms=duration,
                    )
                    
            except asyncio.TimeoutError:
                error_msg = f"Timeout after {self.timeout}s"
                logger.error(f"Download timeout: {url}")
                return DownloadResult(
                    success=False,
                    file_path=None,
                    file_size=0,
                    duration_ms=self.timeout * 1000,
                    error=error_msg
                )
            except Exception as e:
                logger.error(f"Download error: {e} for {url}")
                return DownloadResult(
                    success=False,
                    file_path=None,
                    file_size=0,
                    duration_ms=0,
                    error=str(e)
                )
    
    async def download_with_retry(
        self,
        url: str,
        output_path: Path,
        max_retries: int = 3,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> DownloadResult:
        """Download with automatic retry on failure.
        
        Args:
            url: Video URL
            output_path: Local file path
            max_retries: Maximum retry attempts
            progress_callback: Optional progress callback
            
        Returns:
            DownloadResult
        """
        delays = [1, 5, 15]  # Exponential backoff delays
        
        for attempt in range(max_retries):
            result = await self.download(url, output_path, progress_callback)
            
            if result.success:
                return result
            
            if attempt < max_retries - 1:
                delay = delays[min(attempt, len(delays) - 1)]
                logger.warning(f"Download failed, retrying in {delay}s... (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(delay)
        
        return result
    
    async def batch_download(
        self,
        downloads: list[tuple[str, Path]],
        max_parallel: int = 3,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ) -> list[DownloadResult]:
        """Download multiple videos in parallel.
        
        Args:
            downloads: List of (url, output_path) tuples
            max_parallel: Maximum concurrent downloads
            progress_callback: Optional callback(url, downloaded, total)
            
        Returns:
            List of DownloadResult
        """
        semaphore = asyncio.Semaphore(max_parallel)
        
        async def download_single(url: str, path: Path) -> DownloadResult:
            async with semaphore:
                def progress(downloaded: int, total: int):
                    if progress_callback:
                        progress_callback(url, downloaded, total)
                
                return await self.download_with_retry(url, path, progress_callback=progress)
        
        tasks = [download_single(url, path) for url, path in downloads]
        return await asyncio.gather(*tasks)
    
    async def close(self):
        """Close the download session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None


# Global downloader instance
_downloader: Optional[VideoDownloader] = None


def get_downloader(max_connections: int = 10) -> VideoDownloader:
    """Get or create global video downloader.
    
    Args:
        max_connections: Maximum concurrent connections
        
    Returns:
        VideoDownloader instance
    """
    global _downloader
    if _downloader is None:
        _downloader = VideoDownloader(max_connections=max_connections)
    return _downloader


async def quick_download(url: str, output_path: Path) -> bool:
    """Quick download helper function.
    
    Args:
        url: Video URL
        output_path: Output file path
        
    Returns:
        True if successful
    """
    downloader = get_downloader()
    result = await downloader.download_with_retry(url, output_path)
    return result.success
