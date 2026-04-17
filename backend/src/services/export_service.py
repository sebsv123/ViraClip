"""
Export Service — Phase 16

Provides batch ZIP export for all clips belonging to a task.
Files are assembled on demand and returned as an in-memory BytesIO archive.
"""

import io
import logging
import zipfile
from pathlib import Path
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


async def build_task_zip(
    clips: List[Dict[str, Any]],
    task_title: str = "clips",
    include_metadata: bool = True,
    clips_base_dir: Optional[Path] = None,
) -> io.BytesIO:
    """
    Build a ZIP archive containing all clip files for a task.

    Args:
        clips:            List of clip dicts (must have 'file_path' and 'filename').
        task_title:       Used as the top-level folder name inside the ZIP.
        include_metadata: When True, adds a metadata.json with per-clip scores.
        clips_base_dir:   Optional base directory; if given, relative paths are
                          resolved against it.  When None, file_path is used as-is.

    Returns:
        BytesIO containing the ZIP data, seeked to position 0.
    """
    buf = io.BytesIO()
    folder = _safe_folder_name(task_title)
    missing: List[str] = []
    added = 0

    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for clip in clips:
            raw_path = clip.get("file_path", "")
            path = Path(raw_path)
            if clips_base_dir and not path.is_absolute():
                path = clips_base_dir / path

            if not path.exists():
                logger.warning("[export] Clip file not found: %s", path)
                missing.append(clip.get("filename", str(path)))
                continue

            arcname = f"{folder}/{clip.get('filename', path.name)}"
            zf.write(path, arcname=arcname)
            added += 1

        if include_metadata and clips:
            import json as _json
            meta = _build_metadata(clips, added, missing, task_title)
            zf.writestr(f"{folder}/metadata.json", _json.dumps(meta, indent=2))

    buf.seek(0)
    logger.info("[export] Built ZIP: task=%s clips=%d missing=%d bytes=%d",
                task_title, added, len(missing), buf.getbuffer().nbytes)
    return buf


def _safe_folder_name(title: str) -> str:
    """Strip characters not safe for ZIP entry names."""
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in title).strip()
    return safe[:64] or "clips"


def _build_metadata(
    clips: List[Dict[str, Any]],
    added: int,
    missing: List[str],
    task_title: str,
) -> Dict[str, Any]:
    return {
        "task_title": task_title,
        "total_clips": len(clips),
        "exported_clips": added,
        "missing_files": missing,
        "clips": [
            {
                "filename": c.get("filename"),
                "start_time": c.get("start_time"),
                "end_time": c.get("end_time"),
                "duration": c.get("duration"),
                "virality_score": c.get("virality_score", 0),
                "hook_score": c.get("hook_score", 0),
                "relevance_score": c.get("relevance_score", 0),
                "text": (c.get("text") or "")[:200],
                "hook_type": c.get("hook_type"),
                "social_title": c.get("social_title"),
                "suggested_hashtags": c.get("suggested_hashtags") or [],
            }
            for c in clips
        ],
    }
