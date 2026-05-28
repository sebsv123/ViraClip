#!/usr/bin/env python3
"""Debug local VPI music library discovery without rendering a task."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from src.services.vpi_music_service import discover_music_tracks, music_search_paths, select_music_track  # noqa: E402


def main() -> int:
    print("music_paths_checked:")
    for path in music_search_paths():
        print(f"- {path} exists={path.exists()}")
    tracks = discover_music_tracks()
    print(f"music_tracks={len(tracks)}")
    for track in tracks:
        print(f"- track={track}")
    for editorial_type in ("emotional_protection", "client_objection", "coverage_explanation"):
        track, mood = select_music_track(editorial_type, tracks)
        print(f"{editorial_type}: mood={mood} selected={track if track else 'none'} target_volume_db=-25")
    if not tracks:
        print("[music] skipped reason=no_music_library")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
