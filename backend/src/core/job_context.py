"""
Job Context — shared mutable state for a single video-processing job.

Instantiated once at the start of a job (e.g. in _clips_batch.py) and
threaded through every service that processes individual clips so they
can coordinate choices and avoid repeating the same assets, LUTs, or
effects across clips in the same job.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Set


@dataclass
class JobContext:
    """Shared context for a single video-processing job.

    Attributes:
        job_id: Unique identifier for this job (e.g. task_id).
        clip_count: Number of clips processed so far.
        used_asset_ids: Set of Pexels/Pixabay video IDs already assigned
            to any clip in this job. Prevents the same asset from being
            reused across clips.
        used_lut_presets: List of LUT preset names already applied.
            Enables round-robin / rotation across clips.
        used_broll_queries: Set of search query strings already used
            for B-roll fetching. Prevents redundant API calls.
        clip_styles: One entry per clip, storing the style profile
            (caption style, LUT, zoom intensity, etc.) chosen for that
            clip so later clips can pick different ones.
    """

    job_id: str = ""
    clip_count: int = 0
    used_asset_ids: Set[int] = field(default_factory=set)
    used_lut_presets: List[str] = field(default_factory=list)
    used_broll_queries: Set[str] = field(default_factory=set)
    clip_styles: List[Dict[str, Any]] = field(default_factory=list)
