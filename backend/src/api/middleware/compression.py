"""
HTTP Compression Middleware

Adds Gzip and Brotli compression for API responses.
Reduces bandwidth and improves response times.
"""
from __future__ import annotations

import gzip
import logging
from typing import Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


class CompressionMiddleware(BaseHTTPMiddleware):
    """Middleware to compress HTTP responses."""
    
    def __init__(
        self,
        app: ASGIApp,
        minimum_size: int = 500,  # Don't compress responses < 500 bytes
        compresslevel: int = 6,   # Gzip compression level (1-9)
    ):
        super().__init__(app)
        self.minimum_size = minimum_size
        self.compresslevel = compresslevel
    
    async def dispatch(self, request: Request, call_next) -> Response:
        # Check if client accepts gzip
        accept_encoding = request.headers.get("accept-encoding", "")
        supports_gzip = "gzip" in accept_encoding
        
        # Get response
        response = await call_next(request)
        
        # Skip if:
        # - Response already has content encoding
        # - Client doesn't support gzip
        # - Response is too small
        # - Response is streaming (SSE)
        if (
            response.headers.get("content-encoding")
            or not supports_gzip
            or response.headers.get("content-type", "").startswith("text/event-stream")
        ):
            return response
        
        # Get body
        body = b""
        async for chunk in response.body_iterator:
            if isinstance(chunk, str):
                chunk = chunk.encode("utf-8")
            body += chunk
        
        # Skip small responses
        if len(body) < self.minimum_size:
            response.body_iterator = self._iterator(body)
            return response
        
        # Compress
        compressed = gzip.compress(body, compresslevel=self.compresslevel)
        
        # Only use compressed if it's actually smaller
        if len(compressed) < len(body):
            response.body_iterator = self._iterator(compressed)
            response.headers["content-encoding"] = "gzip"
            response.headers["content-length"] = str(len(compressed))
            logger.debug(f"[Compression] {len(body)} → {len(compressed)} bytes ({len(compressed)/len(body)*100:.1f}%)")
        else:
            response.body_iterator = self._iterator(body)
        
        return response
    
    @staticmethod
    async def _iterator(body: bytes):
        """Create an async iterator for the body."""
        yield body


# FastAPI-compatible middleware factory
def setup_compression(app: ASGIApp, minimum_size: int = 500) -> ASGIApp:
    """Add compression middleware to FastAPI app.
    
    Usage:
        from fastapi import FastAPI
        from .compression import setup_compression
        
        app = FastAPI()
        app = setup_compression(app)
    """
    return CompressionMiddleware(app, minimum_size=minimum_size)
