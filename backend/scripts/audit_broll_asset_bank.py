#!/usr/bin/env python3
"""Audit the local VPI B-roll asset bank without network access."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


CATEGORIES = [
    "family_protection",
    "emotional_reassurance",
    "financial_planning",
    "documents_admin",
    "risk_warning",
]

VALID_EXTENSIONS = {".mp4", ".mov", ".webm", ".jpg", ".jpeg", ".png"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm"}
DEFAULT_ROOT = Path("/app/assets/broll")


def _ffprobe(path: Path) -> tuple[dict, str | None]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {}, "ffprobe unavailable"

    cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,duration:format=duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except Exception as exc:
        return {}, f"ffprobe failed: {exc}"

    if proc.returncode != 0:
        return {}, f"corrupt or unreadable: {proc.stderr.strip()[:160]}"

    try:
        return json.loads(proc.stdout or "{}"), None
    except Exception as exc:
        return {}, f"ffprobe json parse failed: {exc}"


def _audit_video(path: Path) -> list[str]:
    warnings: list[str] = []
    data, err = _ffprobe(path)
    if err:
        warnings.append(f"{path.name}: {err}")
        return warnings

    streams = data.get("streams") or []
    stream = streams[0] if streams else {}
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    duration_raw = stream.get("duration") or (data.get("format") or {}).get("duration") or 0
    try:
        duration = float(duration_raw)
    except Exception:
        duration = 0.0

    if width < 720 and height < 720:
        warnings.append(f"{path.name}: video < 720p ({width}x{height})")
    if duration < 2.8:
        warnings.append(f"{path.name}: video < 2.8s ({duration:.2f}s)")
    return warnings


def audit_category(root: Path, category: str) -> dict:
    category_dir = root / category
    warnings: list[str] = []
    assets: list[Path] = []

    if not category_dir.is_dir():
        warnings.append("category directory missing")
        return {"category": category, "count": 0, "valid": 0, "warnings": warnings}

    for path in sorted(category_dir.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() not in VALID_EXTENSIONS:
            warnings.append(f"{path.name}: unsupported extension")
            continue
        if path.stat().st_size <= 0:
            warnings.append(f"{path.name}: empty file")
            continue
        assets.append(path)
        if path.suffix.lower() in VIDEO_EXTENSIONS:
            warnings.extend(_audit_video(path))

    if not assets:
        warnings.append("category empty")

    return {
        "category": category,
        "count": len(assets),
        "valid": len(assets),
        "warnings": warnings,
    }


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ROOT
    print(f"asset_root={root}")
    print("category,count,valid,warnings")

    total_warnings = 0
    for category in CATEGORIES:
        result = audit_category(root, category)
        warnings = result["warnings"]
        total_warnings += len(warnings)
        warning_text = " | ".join(warnings) if warnings else "-"
        print(f"{category},{result['count']},{result['valid']},{warning_text}")

    print(f"summary categories={len(CATEGORIES)} warnings={total_warnings}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
