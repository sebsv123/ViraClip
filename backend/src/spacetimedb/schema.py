from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

@dataclass
class TelemetryRow:
    """SpaceTimeDB Telemetry Table Schema."""
    task_id: str
    clip_index: int
    progress: float
    message: str
    status: str = "processing"

def broadcast_telemetry(task_id: str, clip_index: int, progress: float, message: str):
    """
    Broadcasts real-time telemetry to the SpaceTimeDB/Reactive layer.
    
    In Phase 0, this acts as an abstraction layer. It will be hooked into
    either the SpaceTimeDB Python SDK or a custom WebSocket bridge.
    """
    try:
        # Placeholder for SpaceTimeDB SDK reducer call:
        # spacetime.reducers.update_telemetry(task_id, clip_index, progress, message)
        
        # For the Pilot, we log it with a special R-TIME prefix for the frontend to scavenge if needed
        # or for us to hook into a real hub later.
        logger.info(f"[R-TIME][{task_id}] Clip {clip_index}: {progress}% - {message}")
        
    except Exception as e:
        logger.error(f"Failed to broadcast telemetry: {e}")
