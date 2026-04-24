"""Public API for the clip rendering subsystem.

This module is a re-export facade so callers can keep importing from
``._clips`` while the implementations live in dedicated files:

- :mod:`._clips_batch`        — `create_video_clips_parallel`, `create_video_clips`
- :mod:`._clip_renderer`      — `create_single_clip`
- :mod:`._clips_transitions`  — `apply_single_transition`
"""

from ._clip_renderer import create_single_clip
from ._clips_batch import create_video_clips, create_video_clips_parallel
from ._clips_transitions import apply_single_transition

__all__ = [
    "create_video_clips_parallel",
    "create_video_clips",
    "create_single_clip",
    "apply_single_transition",
]
