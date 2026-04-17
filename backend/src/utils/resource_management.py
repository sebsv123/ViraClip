"""
Resource Management Utility - handles deterministic cleanup of heavy objects.
"""

import gc
import logging
from contextlib import contextmanager
from typing import Any, List, Optional
import torch

logger = logging.getLogger(__name__)

class ResourceGuard:
    """
    Context manager and tracker for heavy resources (MoviePy clips, GPU memory).
    Ensures all registered objects are cleaned up even on failure.
    """
    
    def __init__(self):
        self.resources: List[Any] = []

    def track(self, resource: Any) -> Any:
        """Register a resource for later cleanup."""
        if resource is not None:
            self.resources.append(resource)
        return resource

    def cleanup(self):
        """Deterministically close all tracked resources and free GPU memory."""
        logger.info(f"💾 ResourceGuard: Cleaning up {len(self.resources)} resources...")
        
        for res in reversed(self.resources):
            try:
                # 1. Close MoviePy/OpenCV handles
                if hasattr(res, "close"):
                    res.close()
                
                # 2. De-reference
                del res
            except Exception as e:
                logger.warning(f"⚠️ Error closing resource: {e}")
        
        self.resources = []
        
        # 3. Force Python garbage collection
        gc.collect()
        
        # 4. Clear CUDA cache if GPU is available
        if torch.cuda.is_available():
            try:
                torch.cuda.empty_cache()
                logger.info("🚀 CUDA Cache Cleared")
            except Exception as e:
                logger.warning(f"⚠️ CUDA cleanup failed: {e}")

    @contextmanager
    def manage(self):
        """Context manager protocol for the guard itself."""
        try:
            yield self
        finally:
            self.cleanup()

# Helper for quick one-off managed clips
@contextmanager
def managed_resource(resource: Any):
    """Simple wrapper for a single resource with close() capability."""
    try:
        yield resource
    finally:
        if hasattr(resource, "close"):
            resource.close()
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
