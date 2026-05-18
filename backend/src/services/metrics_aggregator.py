"""
Metrics Aggregator — lightweight telemetry for ViraClip integration usage.

Stores structured events in a JSON log file with automatic rotation (30-day TTL).
Events are best-effort only — never block the pipeline on a write failure.

Usage:
    from src.services.metrics_aggregator import record_event, get_summary

    # Record an event
    record_event("broll_ai_used", clip_id="clip_123", task_id="task_456",
                 workspace_id="ws_001", payload={"source": "pexels", "count": 3})

    # Get summary for last 7 days
    summary = get_summary(last_days=7)

Privacy:
    - Only technical IDs and metrics are stored (no user PII, no video content).
    - Log files are rotated automatically (30-day TTL).
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Configuration ───────────────────────────────────────────────────────────

_METRICS_DIR = Path(os.getenv("METRICS_DIR", "/tmp/viraclip/metrics"))
_METRICS_FILE = _METRICS_DIR / "events.jsonl"
_MAX_EVENTS_PER_FILE = 100_000  # Rotate after this many events
_TTL_DAYS = 30  # Events older than this are pruned

# ── Event types registry ────────────────────────────────────────────────────

# Known event types for validation and documentation
KNOWN_EVENT_TYPES = {
    # B-roll engines
    "broll_ai_used",           # AiBrollRecommender used
    "broll_fallback",          # TF-IDF fallback used
    "broll_pexels_result",     # PexelsClient search result
    "broll_service_result",    # BrollService overlay result
    # Music engines
    "music_background",        # BackgroundMusicService used
    "music_pixabay",           # Pixabay music fetch
    "music_freesound",         # Freesound music fetch
    "music_fallback",          # No music available
    # External clip engines
    "engine_ai_clips_maker",   # ai-clips-maker integration
    "engine_clipsai",          # ClipsAI integration
    "engine_shorts_engine",    # ShortsHighlightEngine
    # Export presets
    "export_preset_used",      # Export preset applied
    "export_preset_fallback",  # Fallback to fast_vertical
    # Feature flags
    "feature_flag_toggle",     # Runtime flag change
    # Errors / timeouts
    "engine_error",            # Any engine error or timeout
    "engine_timeout",          # Specific timeout event
}


def _ensure_metrics_dir() -> None:
    """Ensure the metrics storage directory exists."""
    _METRICS_DIR.mkdir(parents=True, exist_ok=True)


def _get_metrics_file() -> Path:
    """Get the current metrics file path, rotating if needed."""
    _ensure_metrics_dir()
    if _METRICS_FILE.exists():
        line_count = 0
        try:
            with open(_METRICS_FILE) as f:
                for _ in f:
                    line_count += 1
        except OSError:
            pass
        if line_count >= _MAX_EVENTS_PER_FILE:
            # Rotate: rename current file with timestamp
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            rotated = _METRICS_DIR / f"events_{ts}.jsonl"
            try:
                _METRICS_FILE.rename(rotated)
                logger.info("[Metrics] Rotated events file to %s", rotated.name)
            except OSError as e:
                logger.warning("[Metrics] Rotation failed: %s", e)
    return _METRICS_FILE


def _prune_old_events() -> None:
    """Remove events files older than TTL_DAYS."""
    cutoff = time.time() - (_TTL_DAYS * 86400)
    for f in _METRICS_DIR.glob("events*.jsonl"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                logger.debug("[Metrics] Pruned old events file: %s", f.name)
        except OSError:
            pass


def record_event(
    event_type: str,
    clip_id: Optional[str] = None,
    task_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Record a metrics event.

    Best-effort only — never raises. Logs a warning on failure.

    Args:
        event_type: One of KNOWN_EVENT_TYPES (or custom for extensibility).
        clip_id: Optional clip identifier.
        task_id: Optional task identifier.
        workspace_id: Optional workspace identifier.
        payload: Optional dict with event-specific data (e.g. {"count": 3, "source": "pexels"}).
    """
    if not event_type:
        return

    event = {
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "clip_id": clip_id,
        "task_id": task_id,
        "workspace_id": workspace_id,
        "payload": payload or {},
    }

    try:
        _ensure_metrics_dir()
        events_file = _get_metrics_file()
        with open(events_file, "a") as f:
            f.write(json.dumps(event, default=str) + "\n")
        # Prune old files periodically (every 100 writes)
        if int(time.time()) % 100 == 0:
            _prune_old_events()
    except Exception as e:
        logger.warning("[Metrics] Failed to record event '%s': %s", event_type, e)


def _load_events(last_days: int = 7) -> List[Dict[str, Any]]:
    """Load events from all metrics files within the given time window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=last_days)
    events: List[Dict[str, Any]] = []

    for f in sorted(_METRICS_DIR.glob("events*.jsonl")):
        try:
            with open(f) as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        ts_str = event.get("timestamp", "")
                        if ts_str:
                            ts = datetime.fromisoformat(ts_str)
                            if ts >= cutoff:
                                events.append(event)
                    except (json.JSONDecodeError, ValueError):
                        continue
        except OSError:
            continue

    return events


def get_summary(last_days: int = 7) -> Dict[str, Any]:
    """
    Generate an aggregated metrics summary for the given time window.

    Returns a dict with:
        - total_events: int
        - time_window_days: int
        - clips_total: int (unique clip_ids)
        - by_engine: dict of event_type -> count
        - broll: dict with ai_used, fallback, pexels_results
        - music: dict with background, pixabay, freesound, fallback
        - engines: dict with ai_clips_maker, clipsai, shorts_engine
        - presets: dict with preset_name -> count
        - errors: dict with error_type -> count
        - top_errors: list of (event_type, count) sorted desc
    """
    events = _load_events(last_days=last_days)

    total_events = len(events)
    clip_ids: set = set()
    by_engine: Counter = Counter()
    by_preset: Counter = Counter()
    errors: Counter = Counter()
    broll_ai = 0
    broll_fallback = 0
    broll_pexels = 0
    music_background = 0
    music_pixabay = 0
    music_freesound = 0
    music_fallback = 0
    ai_clips_maker = 0
    clipsai = 0
    shorts_engine = 0

    for event in events:
        etype = event.get("event_type", "unknown")
        by_engine[etype] += 1

        if event.get("clip_id"):
            clip_ids.add(event["clip_id"])

        # Categorize
        if etype == "broll_ai_used":
            broll_ai += 1
        elif etype == "broll_fallback":
            broll_fallback += 1
        elif etype == "broll_pexels_result":
            broll_pexels += 1
        elif etype == "music_background":
            music_background += 1
        elif etype == "music_pixabay":
            music_pixabay += 1
        elif etype == "music_freesound":
            music_freesound += 1
        elif etype == "music_fallback":
            music_fallback += 1
        elif etype == "engine_ai_clips_maker":
            ai_clips_maker += 1
        elif etype == "engine_clipsai":
            clipsai += 1
        elif etype == "engine_shorts_engine":
            shorts_engine += 1
        elif etype in ("engine_error", "engine_timeout"):
            errors[etype] += 1
            # Include error details from payload
            err_detail = event.get("payload", {}).get("error", "")
            if err_detail:
                errors[f"{etype}:{err_detail}"] += 1

        # Export presets
        if etype == "export_preset_used":
            preset_name = event.get("payload", {}).get("preset", "unknown")
            by_preset[preset_name] += 1
        elif etype == "export_preset_fallback":
            by_preset["fallback_to_fast_vertical"] += 1

    clips_total = len(clip_ids)

    # Build summary
    summary: Dict[str, Any] = {
        "total_events": total_events,
        "time_window_days": last_days,
        "clips_total": clips_total,
        "by_engine": dict(by_engine.most_common()),
        "broll": {
            "ai_used": broll_ai,
            "fallback": broll_fallback,
            "pexels_results": broll_pexels,
            "ai_pct": round(broll_ai / max(broll_ai + broll_fallback, 1) * 100, 1),
        },
        "music": {
            "background_service": music_background,
            "pixabay": music_pixabay,
            "freesound": music_freesound,
            "fallback_no_music": music_fallback,
        },
        "engines": {
            "ai_clips_maker": ai_clips_maker,
            "clipsai": clipsai,
            "shorts_engine": shorts_engine,
        },
        "presets": dict(by_preset.most_common()),
        "errors": dict(errors.most_common()),
        "top_errors": [
            {"event_type": k, "count": v}
            for k, v in errors.most_common(5)
        ],
    }

    return summary


def format_summary_text(summary: Dict[str, Any]) -> str:
    """Format a metrics summary as human-readable text (for CLI output)."""
    lines: List[str] = []
    lines.append("=" * 60)
    lines.append(f"  ViraClip Metrics Summary (last {summary['time_window_days']} days)")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"  Total events recorded:  {summary['total_events']}")
    lines.append(f"  Unique clips processed: {summary['clips_total']}")
    lines.append("")

    # B-roll
    b = summary["broll"]
    total_broll = b["ai_used"] + b["fallback"]
    lines.append("  ── B-Roll Engines ──")
    lines.append(f"     AI B-roll used:     {b['ai_used']} ({b['ai_pct']}%)")
    lines.append(f"     Fallback (TF-IDF):  {b['fallback']} ({100 - b['ai_pct']}%)")
    lines.append(f"     Pexels results:     {b['pexels_results']}")
    lines.append("")

    # Music
    m = summary["music"]
    lines.append("  ── Music Engines ──")
    lines.append(f"     BackgroundMusicService: {m['background_service']}")
    lines.append(f"     Pixabay:                {m['pixabay']}")
    lines.append(f"     Freesound:              {m['freesound']}")
    lines.append(f"     Fallback (no music):    {m['fallback_no_music']}")
    lines.append("")

    # External engines
    e = summary["engines"]
    lines.append("  ── External Clip Engines ──")
    lines.append(f"     ai-clips-maker:  {e['ai_clips_maker']}")
    lines.append(f"     ClipsAI:         {e['clipsai']}")
    lines.append(f"     ShortsEngine:    {e['shorts_engine']}")
    lines.append("")

    # Presets
    lines.append("  ── Export Presets ──")
    for preset_name, count in summary["presets"].items():
        lines.append(f"     {preset_name}: {count}")
    lines.append("")

    # Errors
    if summary["errors"]:
        lines.append("  ── Errors / Timeouts ──")
        for err in summary["top_errors"]:
            lines.append(f"     {err['event_type']}: {err['count']}")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)
