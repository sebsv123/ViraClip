#!/usr/bin/env python3
"""
VPI Render Validation Harness v1.0 — Beta Clean VPI
====================================================

Validates rendered clips for publishability without reading thousands of
lines of logs.  Performs technical QC, editorial validation, B-roll
repetition detection, hook appropriateness, branding/subtitle checks,
thumbnail generation, and produces traffic-light reports.

Usage:
  python scripts/validate_vpi_render_quality.py \\
      --task-id b73edd14-415b-48de-bf29-84598432fd12 \\
      --taskshort b73edd14 \\
      --clips-dir temp/uploads/clips \\
      --out reports/render_validation

  python scripts/validate_vpi_render_quality.py --latest

Outputs (in --out dir):
  - render_validation_{task_id}.md      (Markdown report)
  - render_validation_{task_id}.json    (JSON report)
  - render_validation_{task_id}.csv     (CSV report)
  - thumbnails/                          (per-clip frame grabs)
  - contact_sheet_{task_id}.jpg         (contact sheet)
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import subprocess
import sys
import shutil
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(message)s",
)
log = logging.getLogger("vpi_validate")

# ── Constants ──────────────────────────────────────────────────────────────────
DEFAULT_CLIPS_DIRS = [
    Path("exports/clips"),
    Path("temp/uploads/clips"),
    Path("backend/temp/uploads/clips"),
    Path("/app/exports/clips"),
    Path("/app/temp/uploads/clips"),
]
DEFAULT_OUTPUT_DIR = Path("reports/render_validation")
HOOK_BANK_PATH = Path("configs/vpi_hook_bank.json")

# Editorial types that expect a strong hook
STRONG_HOOK_TYPES = {
    "client_objection", "myth_debunk", "risk_warning",
    "statistic", "story", "question", "bold_statement",
    "curiosity_gap", "pattern_interrupt", "authority",
    "empathy", "future_pacing", "visualization", "metaphor",
    "contrast", "listicle", "testimonial", "scenario",
}

# Types that are weak / speaker-focus only
WEAK_INTRO_TYPES = {"weak_intro", "coverage_explanation", "actionable_advice"}

# Target resolution for vertical shorts
TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
MIN_DURATION_S = 5.0

# ── Scoring weights ────────────────────────────────────────────────────────────
SCORE_TECHNICAL_OK = 30
SCORE_HAS_AUDIO = 10
SCORE_HAS_VIDEO = 10
SCORE_RESOLUTION_OK = 10
SCORE_CAPTIONS = 10
SCORE_HOOK_ACCEPTABLE = 8
SCORE_HOOK_STRONG = 15
SCORE_BROLL_OK = 10
SCORE_BRANDING = 5
SCORE_NO_REPETITION = 10

PENALTY_NO_AUDIO = -80
PENALTY_BAD_RESOLUTION = -60
PENALTY_WEAK_INTRO_WITH_BROLL = -80
PENALTY_EXACT_REPEATED_BROLL = -50
PENALTY_HOOK_MISSING_STRONG = -20
PENALTY_WATERMARK_MISSING = -5
PENALTY_SMART_REF_SKIPPED = -5
PENALTY_PER_WARNING = -10


# ══════════════════════════════════════════════════════════════════════════════
# FASE 1 — File Discovery
# ══════════════════════════════════════════════════════════════════════════════

def derive_taskshort(task_id: Optional[str], taskshort: Optional[str]) -> str:
    """Return explicit taskshort or first 8 chars of a UUID/task id."""
    if taskshort:
        return str(taskshort).strip()[:8]
    if task_id:
        cleaned = str(task_id).strip()
        return cleaned[:8]
    return ""


def _unique_paths(paths: List[Path]) -> List[Path]:
    seen = set()
    out: List[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def _task_output_dirs(taskshort: str, task_id: Optional[str]) -> List[Path]:
    dirs: List[Path] = []
    if taskshort:
        dirs.extend(Path(".").glob(f"outputs/vpi/**/task_{taskshort}"))
        dirs.extend(Path("/app").glob(f"outputs/vpi/**/task_{taskshort}"))
    if task_id:
        dirs.append(Path("temp/uploads/clips") / str(task_id))
        dirs.append(Path("/app/temp/uploads/clips") / str(task_id))
    return _unique_paths([d for d in dirs if d])


def _candidate_clip_dirs(
    clips_dir: Optional[Path],
    taskshort: str,
    task_id: Optional[str],
) -> List[Tuple[Path, str]]:
    candidates: List[Tuple[Path, str]] = []
    if clips_dir:
        candidates.append((clips_dir, "--clips-dir"))
    candidates.extend((path, "default") for path in DEFAULT_CLIPS_DIRS)
    candidates.extend((path, "outputs_vpi_task") for path in _task_output_dirs(taskshort, task_id))
    seen = set()
    out: List[Tuple[Path, str]] = []
    for path, source in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        out.append((path, source))
    return out


def _matches_task(path: Path, task_id: Optional[str], taskshort: str) -> bool:
    haystack = str(path)
    if taskshort and taskshort in haystack:
        return True
    # Metadata may contain the full UUID even when filenames only use short id.
    return bool(task_id and str(task_id) in haystack)


def _is_final_clip(path: Path) -> bool:
    name = path.name.lower()
    if any(token in name for token in ("thumb", "contact_sheet", "preview")):
        return False
    return name.endswith(".mp4") and (
        name.startswith("mastered_")
        or name.startswith("brand_")
        or name.startswith("final_")
        or name.startswith("clip_")
        or "_clip_" in name
    )


def discover_metadata_paths(
    *,
    task_id: Optional[str],
    taskshort: str,
    clips_dir: Optional[Path],
    out_dir: Optional[Path] = None,
) -> Tuple[List[Path], Optional[Path], List[Dict[str, Any]]]:
    """Find sidecar/task metadata without requiring it to live by the clips."""
    roots: List[Tuple[Path, str]] = []
    roots.extend((path, "outputs_vpi_task") for path in _task_output_dirs(taskshort, task_id))
    if clips_dir:
        roots.append((clips_dir, "clips_sidecar"))
    if task_id:
        roots.append((Path("temp/uploads/clips") / str(task_id), "uuid_clip_dir"))
        roots.append((Path("/app/temp/uploads/clips") / str(task_id), "uuid_clip_dir"))
    if out_dir:
        roots.append((out_dir, "previous_report"))
    roots.append((Path("reports/render_validation"), "previous_report"))

    metadata: List[Path] = []
    task_summary: Optional[Path] = None
    checked: List[Dict[str, Any]] = []
    for root, source in roots:
        exists = root.exists()
        checked.append({"path": str(root), "exists": exists, "source": source})
        if not exists:
            continue
        for path in sorted(root.rglob("*.json")):
            if not _matches_task(path, task_id, taskshort):
                # task_summary may be under task_<short>/ without short in file name.
                if path.name != "task_summary.json":
                    continue
            if path.name == "task_summary.json" and task_summary is None:
                task_summary = path
            elif "metadata" in path.name.lower() or "clip" in path.name.lower() or "render_validation" in path.name.lower():
                metadata.append(path)
    return sorted(set(metadata)), task_summary, checked

def find_task_outputs(
    task_id: Optional[str] = None,
    taskshort: Optional[str] = None,
    clips_dir: Optional[Path] = None,
    latest: bool = False,
) -> Dict[str, Any]:
    """Search for clip files, metadata JSONs, and task_summary.json.

    Returns a dict with keys:
      - task_id, taskshort
      - clips: list of clip file Paths
      - broll_clips: list of broll clip Paths
      - sub_clips: list of subtitle clip Paths
      - metadata_jsons: list of per-clip metadata Paths
      - task_summary: Optional[Path] to task_summary.json
      - clips_dir: the directory used
    """
    effective_taskshort = derive_taskshort(task_id, taskshort)
    result: Dict[str, Any] = {
        "task_id": task_id or "unknown",
        "taskshort": effective_taskshort or "unknown",
        "clips": [],
        "broll_clips": [],
        "sub_clips": [],
        "metadata_jsons": [],
        "task_summary": None,
        "clips_dir": None,
        "discovery_log": [],
    }

    log.info("[validator-discovery] taskshort=%s", effective_taskshort or "unknown")
    search_dirs = _candidate_clip_dirs(clips_dir, effective_taskshort, task_id)

    for search_dir, source in search_dirs:
        exists = search_dir.exists()
        log.info("[validator-discovery] clips_dir=%s exists=%s source=%s", search_dir, str(exists).lower(), source)
        result["discovery_log"].append({"path": str(search_dir), "exists": exists, "source": source})
        if not exists:
            continue

        # All mp4 files
        all_mp4s = sorted(search_dir.rglob("*.mp4"))
        all_jsons = sorted(search_dir.rglob("*.json"))

        # Filter by taskshort first; filenames usually do not contain full UUID.
        if task_id or effective_taskshort:
            all_mp4s = [p for p in all_mp4s if _matches_task(p, task_id, effective_taskshort)]
            all_jsons = [p for p in all_jsons if _matches_task(p, task_id, effective_taskshort)]

        # Classify clips
        for p in all_mp4s:
            name = p.name.lower()
            if not _is_final_clip(p):
                continue
            if name.startswith("broll_clip_") or "broll_clip_" in name:
                result["broll_clips"].append(p)
            elif name.startswith("sub_broll_clip_") or "sub_broll_clip_" in name:
                result["broll_clips"].append(p)
            elif name.startswith("sub_clip_") or "sub_clip_" in name:
                result["sub_clips"].append(p)
            elif name.startswith("clip_") or name.startswith("final_clip_"):
                result["clips"].append(p)
            else:
                # Catch-all: treat as clip
                result["clips"].append(p)

        # Find metadata JSONs (per-clip)
        for p in all_jsons:
            if p.name == "task_summary.json":
                result["task_summary"] = p
            elif "metadata" in p.name.lower() or "clip" in p.name.lower():
                result["metadata_jsons"].append(p)

        # If we found something in this dir, stop looking
        if result["clips"] or result["broll_clips"]:
            result["clips_dir"] = search_dir
            break

    # Deduplicate
    result["clips"] = sorted(set(result["clips"]))
    result["broll_clips"] = sorted(set(result["broll_clips"]))
    result["sub_clips"] = sorted(set(result["sub_clips"]))
    result["metadata_jsons"] = sorted(set(result["metadata_jsons"]))

    metadata_paths, task_summary, metadata_checked = discover_metadata_paths(
        task_id=task_id,
        taskshort=effective_taskshort,
        clips_dir=Path(result["clips_dir"]) if result.get("clips_dir") else clips_dir,
    )
    result["metadata_jsons"] = sorted(set(result["metadata_jsons"] + metadata_paths))
    if task_summary and not result["task_summary"]:
        result["task_summary"] = task_summary
    result["metadata_discovery_log"] = metadata_checked
    for item in metadata_checked:
        log.info(
            "[validator-discovery] metadata_dir=%s exists=%s source=%s",
            item["path"],
            str(bool(item["exists"])).lower(),
            item["source"],
        )

    log.info(
        "[validator-discovery] clips_found=%d broll_clips=%d sub_clips=%d metadata_jsons=%d",
        len(result["clips"]),
        len(result["broll_clips"]),
        len(result["sub_clips"]),
        len(result["metadata_jsons"]),
    )
    if result["task_summary"]:
        log.info("Found task_summary.json: %s", result["task_summary"])

    return result


# ══════════════════════════════════════════════════════════════════════════════
# FASE 2 — ffprobe / Technical QC
# ══════════════════════════════════════════════════════════════════════════════

def probe_video(path: Path) -> Dict[str, Any]:
    """Run ffprobe on a video file and return technical metadata.

    Returns a dict with keys:
      path, exists, file_size_bytes, file_size_mb,
      duration, width, height, fps, video_codec, audio_codec,
      has_audio, has_video, aspect_ratio, is_vertical_1080x1920,
      ffprobe_error (if any)
    """
    info: Dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "file_size_bytes": 0,
        "file_size_mb": 0.0,
        "duration": 0.0,
        "width": 0,
        "height": 0,
        "fps": 0.0,
        "video_codec": "",
        "audio_codec": "",
        "has_audio": False,
        "has_video": False,
        "aspect_ratio": "",
        "is_vertical_1080x1920": False,
    }

    if not path.exists():
        return info

    info["file_size_bytes"] = path.stat().st_size
    info["file_size_mb"] = round(path.stat().st_size / (1024 * 1024), 2)

    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format", "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        data = json.loads(result.stdout)
    except FileNotFoundError:
        info["ffprobe_error"] = "ffprobe not found in PATH"
        return info
    except json.JSONDecodeError as e:
        info["ffprobe_error"] = f"ffprobe JSON parse error: {e}"
        return info
    except subprocess.TimeoutExpired:
        info["ffprobe_error"] = "ffprobe timed out after 30s"
        return info
    except Exception as e:
        info["ffprobe_error"] = f"ffprobe error: {e}"
        return info

    # Duration from format
    dur_str = data.get("format", {}).get("duration", "0")
    try:
        info["duration"] = round(float(dur_str), 2)
    except (ValueError, TypeError):
        info["duration"] = 0.0

    # Streams
    for stream in data.get("streams", []):
        codec_type = stream.get("codec_type", "")
        if codec_type == "video":
            info["has_video"] = True
            info["width"] = stream.get("width", 0) or 0
            info["height"] = stream.get("height", 0) or 0
            info["video_codec"] = stream.get("codec_name", "")
            # FPS
            avg_fps = stream.get("avg_frame_rate", "0/1")
            if "/" in avg_fps:
                try:
                    num, den = avg_fps.split("/")
                    num_f = float(num)
                    den_f = float(den) if float(den) > 0 else 1.0
                    info["fps"] = round(num_f / den_f, 2)
                except (ValueError, ZeroDivisionError):
                    info["fps"] = 0.0
            # Aspect ratio
            if info["width"] and info["height"]:
                info["aspect_ratio"] = f"{info['width']}:{info['height']}"
                info["is_vertical_1080x1920"] = (
                    info["width"] == TARGET_WIDTH and info["height"] == TARGET_HEIGHT
                )
        elif codec_type == "audio":
            info["has_audio"] = True
            info["audio_codec"] = stream.get("codec_name", "")

    return info


def technical_qc(probe: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Evaluate technical quality. Returns (pass, list_of_warnings)."""
    warnings: List[str] = []

    if not probe.get("exists"):
        return False, ["File does not exist"]

    if probe.get("file_size_bytes", 0) == 0:
        warnings.append("File is empty (0 bytes)")
    elif probe.get("file_size_bytes", 0) < 1_000_000:
        warnings.append("File size < 1MB")

    if not probe.get("has_video"):
        warnings.append("No video stream detected")
    else:
        w = probe.get("width", 0)
        h = probe.get("height", 0)
        if w != TARGET_WIDTH or h != TARGET_HEIGHT:
            warnings.append(
                f"Resolution {w}x{h} != target {TARGET_WIDTH}x{TARGET_HEIGHT}"
            )
        if not probe.get("is_vertical_1080x1920"):
            warnings.append("Not vertical 1080x1920 (may need rotation)")
        if str(probe.get("video_codec") or "").lower() != "h264":
            warnings.append(f"Video codec {probe.get('video_codec') or '?'} != h264")

    if not probe.get("has_audio"):
        warnings.append("No audio stream detected")
    elif str(probe.get("audio_codec") or "").lower() != "aac":
        warnings.append(f"Audio codec {probe.get('audio_codec') or '?'} != aac")

    duration = probe.get("duration", 0)
    if duration < MIN_DURATION_S:
        warnings.append(f"Duration {duration:.1f}s < minimum {MIN_DURATION_S}s")

    if not probe.get("video_codec"):
        warnings.append("Unknown video codec")

    # Technical pass = file exists, has video, has audio, valid duration, valid codec
    tech_pass = (
        probe.get("exists", False)
        and probe.get("has_video", False)
        and probe.get("has_audio", False)
        and duration >= MIN_DURATION_S
        and probe.get("width") == TARGET_WIDTH
        and probe.get("height") == TARGET_HEIGHT
        and str(probe.get("video_codec") or "").lower() == "h264"
        and str(probe.get("audio_codec") or "").lower() == "aac"
        and probe.get("file_size_bytes", 0) > 1_000_000
    )
    return tech_pass, warnings


# ══════════════════════════════════════════════════════════════════════════════
# FASE 3 — Metadata Parser
# ══════════════════════════════════════════════════════════════════════════════

def load_metadata_jsons(metadata_paths: List[Path]) -> Dict[int, Dict[str, Any]]:
    """Load per-clip metadata JSONs, keyed by clip_index.

    Returns {clip_index: metadata_dict}.
    """
    metadata_by_index: Dict[int, Dict[str, Any]] = {}

    for mp in metadata_paths:
        try:
            data = json.loads(mp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Cannot read metadata %s: %s", mp.name, e)
            continue

        clip_index = data.get("clip_index")
        if clip_index is None:
            # Try to extract from filename
            m = re.search(r"clip_(\d+)", mp.name)
            if m:
                clip_index = int(m.group(1))
            else:
                continue

        metadata_by_index[clip_index] = data

    return metadata_by_index


def load_task_summary(task_summary_path: Optional[Path]) -> Dict[str, Any]:
    """Load task_summary.json if it exists."""
    if task_summary_path and task_summary_path.exists():
        try:
            return json.loads(task_summary_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Cannot read task_summary: %s", e)
    return {}


def infer_from_filename(filename: str) -> Dict[str, Any]:
    """Infer clip metadata from filename when no JSON is available."""
    info: Dict[str, Any] = {}
    f = filename.lower()

    # VPI score
    m = re.search(r"viral_(\d+)", f)
    if m:
        info["vpi_score"] = float(m.group(1))

    # Timestamps
    m = re.search(r"(\d{4})-(\d{4})", f)
    if m:
        info["start_time"] = m.group(1)
        info["end_time"] = m.group(2)

    # Editorial type from filename patterns
    if "broll" in f:
        info["intent_type"] = "broll_enhanced"
    elif "sub_clip" in f and "broll" not in f:
        info["intent_type"] = "weak_intro"
    elif "final_clip" in f:
        info["intent_type"] = "final_clean"

    # Clip index
    m = re.search(r"clip_(\d+)", f)
    if m:
        info["clip_index"] = int(m.group(1))

    # Variant
    if "_va" in f:
        info["variant"] = "va"
    elif "_vb" in f:
        info["variant"] = "vb"

    return info


# ══════════════════════════════════════════════════════════════════════════════
# FASE 4 — Editorial Validation
# ══════════════════════════════════════════════════════════════════════════════

def load_hook_bank() -> Dict[str, Any]:
    """Load hook bank config."""
    if HOOK_BANK_PATH.exists():
        try:
            return json.loads(HOOK_BANK_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log.warning("Cannot load hook bank from %s", HOOK_BANK_PATH)
    return {}


def validate_hook(
    editorial_type: str,
    metadata: Dict[str, Any],
    hook_bank: Dict[str, Any],
) -> Tuple[str, List[str]]:
    """Validate hook appropriateness for editorial type.

    Returns (hook_quality: strong|acceptable|weak|missing, warnings[]).
    """
    warnings: List[str] = []
    hook_plan = metadata.get("hook_plan", {})
    hook_type = hook_plan.get("hook_type", "") or metadata.get("hook_type", "")
    hook_rendered = hook_plan.get("hook_rendered", False)
    hook_quality = hook_plan.get("hook_quality", "")

    # If metadata explicitly says hook quality
    if hook_quality in ("strong", "good"):
        return "strong", []
    if hook_quality == "acceptable":
        return "acceptable", []

    # Check if editorial type exists in hook bank
    if editorial_type in hook_bank:
        bank_hooks = hook_bank[editorial_type]
        if isinstance(bank_hooks, list) and bank_hooks:
            # Has defined hooks — expect one to be used
            if not hook_type or hook_type == "weak_intro":
                warnings.append(
                    f"Editorial type '{editorial_type}' expects a strong hook, "
                    f"but hook_type is '{hook_type or 'missing'}'"
                )
                return "missing", warnings
            return "acceptable", warnings
        elif isinstance(bank_hooks, dict) and "rules" in bank_hooks:
            # weak_intro rules — no hook expected
            return "weak_intro", []

    # Fallback: infer from editorial type name
    if editorial_type in WEAK_INTRO_TYPES:
        return "weak_intro", []

    if editorial_type in STRONG_HOOK_TYPES:
        if not hook_type or hook_type == "weak_intro":
            warnings.append(
                f"Editorial type '{editorial_type}' in strong types but "
                f"hook_type is '{hook_type or 'missing'}'"
            )
            return "missing", warnings
        return "acceptable", []

    return "acceptable", []


def validate_broll_for_weak_intro(
    editorial_type: str,
    metadata: Dict[str, Any],
    clip_has_broll_files: bool,
) -> List[str]:
    """Check that weak_intro clips have NO B-roll."""
    warnings: List[str] = []
    if editorial_type not in WEAK_INTRO_TYPES:
        return warnings

    broll_count = metadata.get("broll_count", 0) or 0
    broll_assets = metadata.get("broll_assets", []) or []

    if broll_count > 0 or broll_assets or clip_has_broll_files:
        warnings.append(
            f"WEAK_INTRO clip has {broll_count} B-roll assets "
            f"({len(broll_assets)} in metadata) — should be 0"
        )
    return warnings


def validate_branding(metadata: Dict[str, Any]) -> List[str]:
    """Check branding/watermark presence."""
    warnings: List[str] = []
    watermark = metadata.get("watermark_applied", False)
    brand_treatment = metadata.get("brand_treatment", {})

    if not watermark:
        warnings.append("Watermark/logo not applied")

    if isinstance(brand_treatment, dict) and not brand_treatment.get("applied", True):
        warnings.append("Brand treatment not applied")

    return warnings


def validate_subtitles(metadata: Dict[str, Any]) -> List[str]:
    """Check subtitle presence."""
    warnings: List[str] = []
    subtitle_intel = metadata.get("subtitle_intelligence", {})
    if isinstance(subtitle_intel, dict):
        if not subtitle_intel.get("has_subtitles", False):
            warnings.append("No subtitles detected in metadata")
    return warnings


def validate_smart_reframe(metadata: Dict[str, Any]) -> List[str]:
    """Check smart reframe status."""
    warnings: List[str] = []
    smart_reframe = metadata.get("smart_reframe", {})
    if isinstance(smart_reframe, dict):
        if smart_reframe.get("skipped", False):
            warnings.append("Smart reframe was skipped")
    return warnings


def validate_silence_edit(metadata: Dict[str, Any]) -> List[str]:
    """Check silence edit plan."""
    warnings: List[str] = []
    silence_plan = metadata.get("silence_edit_plan", {})
    if isinstance(silence_plan, dict):
        if silence_plan.get("errors"):
            warnings.append(f"Silence edit errors: {silence_plan['errors']}")
    return warnings


# ══════════════════════════════════════════════════════════════════════════════
# FASE 5 — B-roll Repetition Detection
# ══════════════════════════════════════════════════════════════════════════════

def detect_broll_repetition(
    metadata_by_index: Dict[int, Dict[str, Any]],
) -> Dict[str, Any]:
    """Build asset table and detect repeated B-roll across clips.

    Returns dict with:
      - asset_table: list of {clip_index, asset_id, provider_video_id, ...}
      - exact_repeats: list of asset_ids used more than once
      - provider_repeats: list of provider_video_ids used more than once
      - fingerprint_repeats: list of visual_fingerprints used more than once
      - total_unique_assets: int
      - total_uses: int
    """
    asset_table: List[Dict[str, Any]] = []
    asset_id_counter: Counter = Counter()
    provider_id_counter: Counter = Counter()
    fingerprint_counter: Counter = Counter()

    for clip_index in sorted(metadata_by_index.keys()):
        meta = metadata_by_index[clip_index]
        broll_assets = meta.get("broll_assets", []) or []

        for asset in broll_assets:
            asset_id = asset.get("asset_id", "")
            provider_id = asset.get("provider_video_id", "")
            fingerprint = asset.get("visual_fingerprint", "")

            entry = {
                "clip_index": clip_index,
                "asset_id": asset_id,
                "provider_video_id": provider_id,
                "visual_fingerprint": fingerprint,
                "category": asset.get("category", ""),
                "source": asset.get("source", ""),
                "query": asset.get("query", ""),
            }
            asset_table.append(entry)

            if asset_id:
                asset_id_counter[asset_id] += 1
            if provider_id:
                provider_id_counter[provider_id] += 1
            if fingerprint:
                fingerprint_counter[fingerprint] += 1

    exact_repeats = [aid for aid, cnt in asset_id_counter.items() if cnt > 1]
    provider_repeats = [pid for pid, cnt in provider_id_counter.items() if cnt > 1]
    fingerprint_repeats = [fp for fp, cnt in fingerprint_counter.items() if cnt > 1]

    return {
        "asset_table": asset_table,
        "exact_repeats": exact_repeats,
        "provider_repeats": provider_repeats,
        "fingerprint_repeats": fingerprint_repeats,
        "total_unique_assets": len(asset_id_counter),
        "total_uses": len(asset_table),
    }


# ══════════════════════════════════════════════════════════════════════════════
# FASE 6 — Thumbnails / Contact Sheet
# ══════════════════════════════════════════════════════════════════════════════

def extract_thumbnails(
    video_path: Path,
    output_dir: Path,
    num_frames: int = 4,
) -> List[Path]:
    """Extract keyframes from video for thumbnail/contact sheet.

    Extracts at: 1s, 3s, middle, near-end.
    Returns list of thumbnail Paths.
    """
    thumbnails: List[Path] = []
    probe = probe_video(video_path)
    duration = probe.get("duration", 0)

    if duration <= 0:
        log.warning("Cannot extract thumbnails: unknown duration for %s", video_path.name)
        return thumbnails

    # Timestamps to capture
    timestamps = [1.0, 3.0]
    mid = duration / 2
    near_end = max(duration - 1.0, mid + 1.0)
    timestamps.append(mid)
    timestamps.append(near_end)

    # Deduplicate and sort
    timestamps = sorted(set(round(t, 1) for t in timestamps if t < duration))

    output_dir.mkdir(parents=True, exist_ok=True)
    base = video_path.stem

    for i, ts in enumerate(timestamps):
        out_path = output_dir / f"{base}_thumb_{i+1}.jpg"
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y", "-v", "quiet",
                    "-ss", str(ts),
                    "-i", str(video_path),
                    "-vframes", "1",
                    "-q:v", "2",
                    str(out_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if out_path.exists() and out_path.stat().st_size > 0:
                thumbnails.append(out_path)
        except Exception as e:
            log.warning("Thumbnail extraction failed for %s at %.1fs: %s", video_path.name, ts, e)

    return thumbnails


def generate_contact_sheet(
    thumbnails: List[Path],
    output_path: Path,
    cols: int = 4,
) -> bool:
    """Generate a contact sheet JPG from thumbnails using ffmpeg.

    Falls back to a simple markdown-based contact sheet if ffmpeg fails.
    """
    if not thumbnails:
        return False

    # Try ffmpeg tile filter
    try:
        # Create a concat file for ffmpeg
        tile_list = output_path.with_suffix(".txt")
        tile_list.write_text(
            "\n".join(f"file '{p.resolve()}'" for p in thumbnails),
            encoding="utf-8",
        )

        rows = (len(thumbnails) + cols - 1) // cols
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "quiet",
                "-f", "concat", "-safe", "0",
                "-i", str(tile_list),
                "-vf", f"tile={cols}x{rows}",
                "-q:v", "2",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if tile_list.exists():
            tile_list.unlink()
        if output_path.exists() and output_path.stat().st_size > 0:
            return True
    except Exception as e:
        log.warning("Contact sheet ffmpeg failed: %s", e)

    return False


# ══════════════════════════════════════════════════════════════════════════════
# FASE 7 — Reports
# ══════════════════════════════════════════════════════════════════════════════

def traffic_light(status: str) -> str:
    """Return emoji traffic light for a status."""
    mapping = {
        "READY": "🟢",
        "READY_TO_UPLOAD": "🟢",
        "USABLE_WITH_WARNINGS": "🟡",
        "REVIEW_MANUALLY": "🟡",
        "NOT_READY": "🔴",
        "NEEDS_FIX": "🔴",
        "DO_NOT_UPLOAD": "⛔",
    }
    return mapping.get(status, "⚪")


def generate_markdown_report(
    clips_data: List[Dict[str, Any]],
    repetition: Dict[str, Any],
    task_id: str,
    taskshort: str,
    output_path: Path,
):
    """Generate a comprehensive Markdown validation report."""
    lines = [
        f"# VPI Render Validation Report",
        f"**Task:** `{task_id}` (short: `{taskshort}`)",
        f"**Generated:** {datetime.now().isoformat()}",
        f"**Clips evaluated:** {len(clips_data)}",
        "",
        "## Summary",
        "",
    ]

    # Count statuses
    statuses = Counter(c.get("visual_publishability", {}).get("classification", "UNKNOWN") for c in clips_data)
    ready = statuses.get("READY_TO_UPLOAD", 0)
    review = statuses.get("REVIEW_MANUALLY", 0)
    needs_fix = statuses.get("NEEDS_FIX", 0)
    do_not = statuses.get("DO_NOT_UPLOAD", 0)

    lines.append(f"- 🟢 **READY_TO_UPLOAD:** {ready}")
    lines.append(f"- 🟡 **REVIEW_MANUALLY:** {review}")
    lines.append(f"- 🔴 **NEEDS_FIX:** {needs_fix}")
    lines.append(f"- ⛔ **DO_NOT_UPLOAD:** {do_not}")
    lines.append("")

    # Per-clip table
    lines.append("## Per-Clip Validation")
    lines.append("")
    lines.append(
        "| # | Status | Score | File | Duration | Resolution | Audio | "
        "Hook | B-roll | Warnings |"
    )
    lines.append(
        "|---|--------|-------|------|----------|------------|-------|"
        "------|--------|----------|"
    )

    for i, clip in enumerate(clips_data, 1):
        vp = clip.get("visual_publishability", {})
        status = vp.get("classification", "UNKNOWN")
        score = vp.get("score", 0)
        probe = clip.get("probe", {})
        tech = clip.get("technical_qc", {})
        tech_pass = tech.get("passed", False)
        warnings = clip.get("all_warnings", [])

        lines.append(
            f"| {i} "
            f"| {traffic_light(status)} {status} "
            f"| {score}/100 "
            f"| `{Path(clip['path']).name}` "
            f"| {probe.get('duration', 0):.1f}s "
            f"| {probe.get('width', 0)}x{probe.get('height', 0)} "
            f"| {'✅' if probe.get('has_audio') else '❌'} "
            f"| {clip.get('hook_quality', '?')} "
            f"| {clip.get('broll_count', 0)} "
            f"| {', '.join(warnings[:3]) or '—'} |"
        )

    lines.append("")

    # B-roll repetition section
    lines.append("## B-roll Repetition Analysis")
    lines.append("")
    if repetition.get("exact_repeats"):
        lines.append(
            f"⚠ **Exact asset repeats:** "
            f"{', '.join(repetition['exact_repeats'])}"
        )
    else:
        lines.append("✅ No exact asset repeats detected")
    if repetition.get("provider_repeats"):
        lines.append(
            f"⚠ **Provider video repeats:** "
            f"{', '.join(repetition['provider_repeats'])}"
        )
    else:
        lines.append("✅ No provider video repeats detected")
    if repetition.get("fingerprint_repeats"):
        lines.append(
            f"⚠ **Visual fingerprint repeats:** "
            f"{', '.join(repetition['fingerprint_repeats'])}"
        )
    else:
        lines.append("✅ No visual fingerprint repeats detected")
    lines.append(f"- **Total unique assets:** {repetition.get('total_unique_assets', 0)}")
    lines.append(f"- **Total B-roll uses:** {repetition.get('total_uses', 0)}")
    lines.append("")

    # Detailed per-clip section
    lines.append("## Detailed Clip Analysis")
    lines.append("")
    for clip in clips_data:
        clip_path = Path(clip["path"])
        lines.append(f"### {clip_path.name}")
        lines.append("")

        vp = clip.get("visual_publishability", {})
        lines.append(f"- **Publishability Score:** {vp.get('score', 0)}/100")
        lines.append(f"- **Classification:** {traffic_light(vp.get('classification', ''))} {vp.get('classification', 'UNKNOWN')}")
        lines.append("")

        # Technical
        probe = clip.get("probe", {})
        lines.append("**Technical QC:**")
        lines.append(f"- File size: {probe.get('file_size_mb', 0):.1f} MB")
        lines.append(f"- Duration: {probe.get('duration', 0):.1f}s")
        lines.append(f"- Resolution: {probe.get('width', 0)}x{probe.get('height', 0)}")
        lines.append(f"- FPS: {probe.get('fps', 0)}")
        lines.append(f"- Video codec: {probe.get('video_codec', '?')}")
        lines.append(f"- Audio codec: {probe.get('audio_codec', '?')}")
        lines.append(f"- Has audio: {'✅' if probe.get('has_audio') else '❌'}")
        lines.append(f"- Vertical 1080x1920: {'✅' if probe.get('is_vertical_1080x1920') else '❌'}")
        lines.append("")

        # Editorial
        lines.append("**Editorial:**")
        lines.append(f"- Editorial type: {clip.get('editorial_type', '?')}")
        lines.append(f"- Hook quality: {clip.get('hook_quality', '?')}")
        lines.append(f"- B-roll count: {clip.get('broll_count', 0)}")
        lines.append("")

        # Branding
        lines.append("**Branding:**")
        branding = clip.get("branding", {})
        lines.append(f"- Watermark: {'✅' if branding.get('watermark_applied') else '❌'}")
        lines.append(f"- Brand treatment: {branding.get('brand_treatment', '?')}")
        lines.append("")

        # Subtitles
        lines.append("**Subtitles:**")
        subs = clip.get("subtitles", {})
        lines.append(f"- Captions present: {'✅' if subs.get('captions_present') else '❌'}")
        lines.append(f"- Karaoke: {'✅' if subs.get('karaoke') else '❌'}")
        lines.append(f"- Highlight: {'✅' if subs.get('highlight') else '❌'}")
        lines.append("")

        # Smart reframe
        lines.append("**Smart Reframe:**")
        sr = clip.get("smart_reframe", {})
        lines.append(f"- Applied: {'✅' if sr.get('applied') else '❌'}")
        lines.append(f"- Reason: {sr.get('reason', '?')}")
        lines.append("")

        # Silence edit
        lines.append("**Silence Edit:**")
        se = clip.get("silence_edit", {})
        lines.append(f"- Applied: {'✅' if se.get('applied') else '❌'}")
        lines.append(f"- Segments removed: {se.get('segments_removed', 0)}")
        lines.append("")

        # B-roll details
        lines.append("**B-roll Details:**")
        lines.append(f"- Sources: {clip.get('broll_sources', '?')}")
        broll_assets = clip.get("broll_assets", [])
        for ba in broll_assets:
            lines.append(f"  - `{ba.get('filename', '?')}` ({ba.get('provider', '?')})")
        lines.append("")

        # Warnings
        if clip.get("all_warnings"):
            lines.append("**Warnings:**")
            for w in clip["all_warnings"]:
                lines.append(f"- ⚠ {w}")
            lines.append("")

        # Visual publishability breakdown
        vp = clip.get("visual_publishability", {})
        if vp.get("breakdown"):
            lines.append("**Score Breakdown:**")
            for k, v in vp["breakdown"].items():
                sign = "+" if v >= 0 else ""
                lines.append(f"- {k}: {sign}{v}")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def generate_csv_report(
    clips_data: List[Dict[str, Any]],
    repetition: Dict[str, Any],
    output_path: Path,
) -> str:
    """FASE 7 — Generate CSV report with traffic-light status per clip."""
    rows = []
    for clip in clips_data:
        probe = clip.get("probe", {})
        vp = clip.get("visual_publishability", {})
        rows.append({
            "clip_index": clip.get("clip_index", 0),
            "filename": Path(clip["path"]).name,
            "status": vp.get("classification", "UNKNOWN"),
            "score": vp.get("score", 0),
            "duration_s": round(probe.get("duration", 0), 1),
            "resolution": f"{probe.get('width', 0)}x{probe.get('height', 0)}",
            "has_audio": probe.get("has_audio", False),
            "has_video": probe.get("has_video", False),
            "file_size_mb": round(probe.get("file_size_mb", 0), 1),
            "video_codec": probe.get("video_codec", "?"),
            "audio_codec": probe.get("audio_codec", "?"),
            "fps": probe.get("fps", 0),
            "editorial_type": clip.get("editorial_type", "?"),
            "hook_quality": clip.get("hook_quality", "?"),
            "broll_count": clip.get("broll_count", 0),
            "broll_sources": clip.get("broll_sources", "?"),
            "watermark_applied": clip.get("branding", {}).get("watermark_applied", False),
            "captions_present": clip.get("subtitles", {}).get("captions_present", False),
            "smart_reframe_applied": clip.get("smart_reframe", {}).get("applied", False),
            "silence_edit_applied": clip.get("silence_edit", {}).get("applied", False),
            "warnings": "; ".join(clip.get("all_warnings", [])),
        })

    fieldnames = [
        "clip_index", "filename", "status", "score", "duration_s",
        "resolution", "has_audio", "has_video", "file_size_mb",
        "video_codec", "audio_codec", "fps",
        "editorial_type", "hook_quality", "broll_count", "broll_sources",
        "watermark_applied", "captions_present",
        "smart_reframe_applied", "silence_edit_applied", "warnings",
    ]

    csv_path = output_path / f"render_validation.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    log.info("CSV report written → %s", csv_path)
    return str(csv_path)


def generate_json_report(
    clips_data: List[Dict[str, Any]],
    repetition: Dict[str, Any],
    output_path: Path,
    task_id: str,
) -> str:
    """FASE 7 — Generate JSON report with full structured data."""
    report = {
        "report_type": "vpi_render_validation",
        "version": "1.0",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "task_id": task_id,
        "clips": [],
        "broll_repetition": repetition,
        "summary": {
            "total_clips": len(clips_data),
            "ready_to_upload": sum(
                1 for c in clips_data
                if c.get("visual_publishability", {}).get("classification") == "READY_TO_UPLOAD"
            ),
            "review_manually": sum(
                1 for c in clips_data
                if c.get("visual_publishability", {}).get("classification") == "REVIEW_MANUALLY"
            ),
            "needs_fix": sum(
                1 for c in clips_data
                if c.get("visual_publishability", {}).get("classification") == "NEEDS_FIX"
            ),
            "do_not_upload": sum(
                1 for c in clips_data
                if c.get("visual_publishability", {}).get("classification") == "DO_NOT_UPLOAD"
            ),
        },
    }

    for clip in clips_data:
        report["clips"].append({
            "clip_index": clip.get("clip_index"),
            "filename": Path(clip["path"]).name,
            "path": clip["path"],
            "probe": clip.get("probe", {}),
            "editorial_type": clip.get("editorial_type"),
            "hook_quality": clip.get("hook_quality"),
            "broll_count": clip.get("broll_count"),
            "broll_sources": clip.get("broll_sources"),
            "broll_assets": clip.get("broll_assets", []),
            "branding": clip.get("branding", {}),
            "subtitles": clip.get("subtitles", {}),
            "smart_reframe": clip.get("smart_reframe", {}),
            "silence_edit": clip.get("silence_edit", {}),
            "visual_publishability": clip.get("visual_publishability", {}),
            "all_warnings": clip.get("all_warnings", []),
        })

    json_path = output_path / f"render_validation_{task_id}.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    log.info("JSON report written → %s", json_path)
    return str(json_path)


# ── FASE 8: Visual Publishability Score ──────────────────────────────────────────


def compute_visual_publishability_score(
    clip: Dict[str, Any],
    probe: Dict[str, Any],
    repetition: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Compute a 0-100 visual publishability score for a single clip.

    Scoring rules (from spec):
      Base: technical_qc ok (+30), has_audio/video/resolution (+20),
            captions (+10), hook acceptable/strong (+15), broll okay (+10),
            branding (+5), no repetition (+10)
      Penalties: no audio (-80), bad resolution (-60),
                 weak_intro with broll (-80), exact repeated broll (-50),
                 hook missing for strong editorial (-20),
                 watermark missing (-5), smart reframe skipped (-5),
                 many warnings (-10 to -25)
    """
    score = 0
    breakdown: Dict[str, int] = {}
    warnings: List[str] = []

    # ── Base: technical QC ──
    if probe.get("has_video") and probe.get("has_audio"):
        score += 30
        breakdown["technical_qc_ok"] = 30
    else:
        breakdown["technical_qc_ok"] = 0

    # ── Has audio ──
    if probe.get("has_audio"):
        score += 10
        breakdown["has_audio"] = 10
    else:
        score -= 80
        breakdown["has_audio"] = -80
        warnings.append("No audio track detected")

    # ── Has video ──
    if probe.get("has_video"):
        score += 5
        breakdown["has_video"] = 5
    else:
        breakdown["has_video"] = 0
        warnings.append("No video track detected")

    # ── Resolution ──
    is_vertical = probe.get("is_vertical_1080x1920", False)
    if is_vertical:
        score += 5
        breakdown["resolution_ok"] = 5
    else:
        score -= 60
        breakdown["resolution_ok"] = -60
        warnings.append(
            f"Bad resolution: {probe.get('width', 0)}x{probe.get('height', 0)} "
            f"(expected 1080x1920)"
        )

    # ── Captions ──
    captions_present = clip.get("subtitles", {}).get("captions_present", False)
    if captions_present:
        score += 10
        breakdown["captions"] = 10
    else:
        breakdown["captions"] = 0

    # ── Hook quality ──
    hook_quality = clip.get("hook_quality", "missing")
    if hook_quality in ("strong", "acceptable"):
        score += 15
        breakdown["hook_quality"] = 15
    elif hook_quality == "weak":
        score += 5
        breakdown["hook_quality"] = 5
    else:
        breakdown["hook_quality"] = 0
        editorial_type = clip.get("editorial_type", "")
        if editorial_type in (
            "client_objection", "myth_debunk", "risk_warning",
            "statistic", "story", "question", "bold_statement",
        ):
            score -= 20
            breakdown["hook_missing_penalty"] = -20
            warnings.append(
                f"Hook missing for strong editorial type '{editorial_type}'"
            )

    # ── B-roll ──
    broll_count = clip.get("broll_count", 0)
    editorial_type = clip.get("editorial_type", "")
    if editorial_type == "weak_intro" and broll_count > 0:
        score -= 80
        breakdown["weak_intro_broll_penalty"] = -80
        warnings.append("weak_intro should have NO B-roll")
    elif broll_count > 0:
        score += 10
        breakdown["broll_ok"] = 10
    else:
        breakdown["broll_ok"] = 0

    # ── Branding ──
    watermark = clip.get("branding", {}).get("watermark_applied", False)
    if watermark:
        score += 5
        breakdown["branding"] = 5
    else:
        breakdown["branding"] = 0
        warnings.append("Watermark not applied")

    # ── B-roll repetition ──
    clip_filename = Path(clip["path"]).name
    exact_repeats = repetition.get("exact_repeats", [])
    if any(clip_filename in r for r in exact_repeats):
        score -= 50
        breakdown["exact_repeat_penalty"] = -50
        warnings.append("Clip uses exact repeated B-roll asset")
    else:
        breakdown["exact_repeat_penalty"] = 0

    # ── Smart reframe ──
    sr_applied = clip.get("smart_reframe", {}).get("applied", False)
    sr_reason = clip.get("smart_reframe", {}).get("reason", "")
    if not sr_applied and sr_reason != "not_needed":
        score -= 5
        breakdown["smart_reframe_penalty"] = -5
        warnings.append("Smart reframe skipped without justification")
    else:
        breakdown["smart_reframe_penalty"] = 0

    # ── Silence edit ──
    se_applied = clip.get("silence_edit", {}).get("applied", False)
    if se_applied:
        score += 3
        breakdown["silence_edit"] = 3
    else:
        breakdown["silence_edit"] = 0

    # ── Warning penalty ──
    all_warnings = clip.get("all_warnings", [])
    num_warnings = len(all_warnings)
    if num_warnings >= 5:
        penalty = -25
    elif num_warnings >= 3:
        penalty = -15
    elif num_warnings >= 1:
        penalty = -10
    else:
        penalty = 0
    if penalty:
        score += penalty
        breakdown["warning_penalty"] = penalty

    # Clamp to 0-100
    score = max(0, min(100, score))

    tech_pass = bool(clip.get("technical_qc", {}).get("passed"))
    severe_technical = (
        not probe.get("has_video")
        or not probe.get("has_audio")
        or not probe.get("exists")
        or probe.get("duration", 0) < MIN_DURATION_S
        or probe.get("width") != TARGET_WIDTH
        or probe.get("height") != TARGET_HEIGHT
    )
    major_issue = any(
        marker in warning.lower()
        for warning in clip.get("all_warnings", [])
        for marker in (
            "no captions",
            "no subtitles",
            "watermark/logo not applied",
            "hook missing",
            "weak_intro should have no b-roll",
            "exact repeated",
            "audio suspicious",
        )
    )

    # Classification
    if severe_technical:
        classification = "DO_NOT_UPLOAD"
    elif tech_pass and clip.get("metadata_missing"):
        classification = "REVIEW_MANUALLY"
        score = max(score, 70)
    elif tech_pass and major_issue:
        classification = "NEEDS_FIX"
    elif score >= 85:
        classification = "READY_TO_UPLOAD"
    elif score >= 70:
        classification = "REVIEW_MANUALLY"
    elif score >= 50:
        classification = "NEEDS_FIX"
    else:
        classification = "DO_NOT_UPLOAD"

    return {
        "score": score,
        "classification": classification,
        "breakdown": breakdown,
    }


# ── FASE 1+7+8 Orchestrator ──────────────────────────────────────────────────────


def validate_task(
    task_id: str,
    taskshort: str,
    clips_dir: Optional[str],
    output_dir: str,
    hook_bank_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run the full validation pipeline for a single task.

    Returns a dict with:
      - task_id
      - clips: list of enriched clip dicts
      - repetition: b-roll repetition analysis
      - reports: paths to generated reports
    """
    taskshort = derive_taskshort(task_id, taskshort)
    clips_path = Path(clips_dir) if clips_dir else None
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # FASE 1: File discovery
    log.info("FASE 1 — Discovering files for task %s (%s)", task_id, taskshort)
    discovery = find_task_outputs(
        task_id=task_id,
        taskshort=taskshort,
        clips_dir=clips_path,
    )
    clip_paths = discovery["clips"]
    metadata_jsons = discovery["metadata_jsons"]
    task_summary = discovery["task_summary"]
    log.info("  → Found %d clip files, %d metadata JSONs", len(clip_paths), len(metadata_jsons))

    # Load hook bank
    hook_bank = load_hook_bank()

    # Load metadata by index
    metadata_by_index = load_metadata_jsons(metadata_jsons)

    # Enrich each clip
    enriched_clips: List[Dict[str, Any]] = []

    for clip_path in clip_paths:
        clip_info: Dict[str, Any] = {
            "path": str(clip_path),
            "clip_index": 0,
            "filename": clip_path.name,
        }

        # FASE 2: ffprobe
        log.debug("FASE 2 — Probing %s", clip_path.name)
        probe = probe_video(clip_path)
        clip_info["probe"] = probe

        # FASE 3: Metadata
        log.debug("FASE 3 — Loading metadata for %s", clip_path.name)
        # Find matching metadata by clip_index or filename
        inferred = infer_from_filename(clip_path.name)
        clip_index = inferred.get("clip_index", 0)
        clip_info["clip_index"] = clip_index
        clip_info["editorial_type"] = inferred.get("editorial_type", "?")
        meta = metadata_by_index.get(clip_index, {})
        metadata_found = bool(meta)
        if meta:
            clip_info.update(meta)
        else:
            f = clip_path.name.lower()
            clip_info["metadata_missing"] = True
            clip_info["watermark_applied"] = "brand" in f
            clip_info["subtitle_intelligence"] = {"has_subtitles": "sub" in f}
            clip_info["broll_count"] = 1 if "broll" in f else 0
            clip_info["smart_reframe"] = {"skipped": False, "applied": "reframe" in f, "reason": "filename_inferred"}
            clip_info["silence_edit_plan"] = {"applied": "silence" in f}

        # FASE 4: Editorial validation
        log.debug("FASE 4 — Editorial validation for %s", clip_path.name)
        editorial_type = clip_info.get("editorial_type", "?")
        hook_quality, hook_warnings = validate_hook(editorial_type, clip_info, hook_bank)
        clip_info["hook_quality"] = hook_quality
        clip_info["hook_validation"] = {"quality": hook_quality, "warnings": hook_warnings}

        broll_warnings = validate_broll_for_weak_intro(editorial_type, clip_info, False)
        branding_warnings = validate_branding(clip_info)
        subtitle_warnings = validate_subtitles(clip_info)
        sr_warnings = validate_smart_reframe(clip_info)
        se_warnings = validate_silence_edit(clip_info)

        clip_info["branding"] = {"watermark_applied": clip_info.get("watermark_applied", False), "warnings": branding_warnings}
        clip_info["subtitles"] = {"captions_present": clip_info.get("subtitle_intelligence", {}).get("has_subtitles", False), "warnings": subtitle_warnings}
        clip_info["smart_reframe"] = {"applied": not clip_info.get("smart_reframe", {}).get("skipped", False), "warnings": sr_warnings}
        clip_info["silence_edit"] = {"applied": True, "warnings": se_warnings}

        tech_pass, tech_warnings = technical_qc(probe)
        clip_info["technical_qc"] = {
            "passed": tech_pass,
            "status": "PASS" if tech_pass else "FAIL",
            "warnings": tech_warnings,
        }

        # Collect warnings
        warnings: List[str] = []
        if not metadata_found and tech_pass:
            warnings.append("metadata_not_found_but_technical_qc_passed")
        warnings.extend(hook_warnings)
        warnings.extend(broll_warnings)
        warnings.extend(branding_warnings)
        warnings.extend(subtitle_warnings)
        warnings.extend(sr_warnings)
        warnings.extend(se_warnings)
        warnings.extend(tech_warnings)
        clip_info["all_warnings"] = warnings

        enriched_clips.append(clip_info)

    # FASE 5: B-roll repetition detection
    log.info("FASE 5 — Detecting B-roll repetition across %d clips", len(enriched_clips))
    repetition = detect_broll_repetition(metadata_by_index)

    # FASE 8: Scoring
    log.info("FASE 8 — Computing visual publishability scores")
    for clip in enriched_clips:
        vp = compute_visual_publishability_score(
            clip, clip.get("probe", {}), repetition
        )
        clip["visual_publishability"] = vp

    # FASE 6: Thumbnails
    log.info("FASE 6 — Extracting thumbnails")
    thumb_dir = out_path / "thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    for clip in enriched_clips:
        clip_path = Path(clip["path"])
        thumb_path = thumb_dir / f"{clip_path.stem}_thumb.jpg"
        extract_thumbnails(clip_path, thumb_dir)
        clip["thumbnail"] = str(thumb_path)

    contact_sheet_path = out_path / f"contact_sheet_{task_id}.jpg"
    clip_paths_list = [Path(c["path"]) for c in enriched_clips]
    # Generate contact sheet from thumbnails
    thumb_files = sorted(thumb_dir.glob("*.jpg"))
    generate_contact_sheet(thumb_files, contact_sheet_path)


    # FASE 7: Reports
    log.info("FASE 7 — Generating reports")
    md_path = generate_markdown_report(
        enriched_clips, repetition, task_id, taskshort, out_path
    )
    md_file = out_path / f"render_validation_{task_id}.md"
    md_file.write_text(md_path, encoding="utf-8")
    csv_path = generate_csv_report(
        enriched_clips, repetition, out_path
    )
    json_path = generate_json_report(
        enriched_clips, repetition, out_path, task_id
    )

    result = {
        "task_id": task_id,
        "taskshort": taskshort,
        "clips": enriched_clips,
        "repetition": repetition,
        "reports": {
            "markdown": str(md_file),
            "csv": csv_path,
            "json": json_path,
            "contact_sheet": str(contact_sheet_path),
        },
        "summary": {
            "total_clips": len(enriched_clips),
            "ready_to_upload": sum(
                1 for c in enriched_clips
                if c.get("visual_publishability", {}).get("classification") == "READY_TO_UPLOAD"
            ),
            "review_manually": sum(
                1 for c in enriched_clips
                if c.get("visual_publishability", {}).get("classification") == "REVIEW_MANUALLY"
            ),
            "needs_fix": sum(
                1 for c in enriched_clips
                if c.get("visual_publishability", {}).get("classification") == "NEEDS_FIX"
            ),
            "do_not_upload": sum(
                1 for c in enriched_clips
                if c.get("visual_publishability", {}).get("classification") == "DO_NOT_UPLOAD"
            ),
        },
    }

    # Print summary
    log.info("=" * 60)
    log.info("VALIDATION COMPLETE — %s", task_id)
    log.info("  Total clips: %d", result["summary"]["total_clips"])
    log.info("  READY_TO_UPLOAD: %d", result["summary"]["ready_to_upload"])
    log.info("  REVIEW_MANUALLY: %d", result["summary"]["review_manually"])
    log.info("  NEEDS_FIX: %d", result["summary"]["needs_fix"])
    log.info("  DO_NOT_UPLOAD: %d", result["summary"]["do_not_upload"])
    log.info("  Reports: %s", json.dumps(result["reports"], indent=2))
    log.info("=" * 60)

    return result


# ── CLI ──────────────────────────────────────────────────────────────────────────


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="VPI Render Validation Harness v1.0",
    )
    parser.add_argument(
        "--task-id",
        default=None,
        help="Full task UUID (e.g. b73edd14-415b-48de-bf29-84598432fd12)",
    )
    parser.add_argument(
        "--taskshort",
        default=None,
        help="Short task ID (first 8 chars of UUID)",
    )
    parser.add_argument(
        "--clips-dir",
        default=None,
        help="Directory containing rendered clips and metadata",
    )
    parser.add_argument(
        "--out",
        default="reports/render_validation",
        help="Output directory for reports",
    )
    parser.add_argument(
        "--hook-bank",
        default=None,
        help="Path to hook bank JSON (default: configs/vpi_hook_bank.json)",
    )
    parser.add_argument(
        "--latest",
        action="store_true",
        help="Auto-detect the latest task from clips directory",
    )
    return parser.parse_args(argv)


def find_latest_task(clips_dir: str) -> Tuple[str, str]:
    """
    Auto-detect the latest task from the clips directory by scanning
    for clip files and extracting task IDs from filenames.
    """
    clips_path = Path(clips_dir) if clips_dir else None
    search_dirs = _candidate_clip_dirs(clips_path, "", None)

    # Look for metadata JSONs first (most reliable)
    metadata_files: List[Path] = []
    for root, _source in search_dirs:
        if root.exists():
            metadata_files.extend(sorted(root.rglob("*_metadata.json")))
    if metadata_files:
        latest_meta = max(metadata_files, key=lambda p: p.stat().st_mtime)
        try:
            with open(latest_meta) as f:
                data = json.load(f)
            task_id = data.get("task_id", "")
            taskshort = task_id[:8] if task_id else ""
            if task_id:
                log.info("Auto-detected task from metadata: %s", task_id)
                return task_id, taskshort
        except (json.JSONDecodeError, KeyError):
            pass

    # Fallback: scan clip filenames
    clip_files: List[Path] = []
    for root, _source in search_dirs:
        if root.exists():
            clip_files.extend([p for p in root.rglob("*.mp4") if _is_final_clip(p)])
    if not clip_files:
        log.error("No clip files found in discovered clip directories")
        sys.exit(1)

    # Extract task short from the last clip file
    latest_clip = max(clip_files, key=lambda p: p.stat().st_mtime).stem
    match = re.search(r"clip_([a-f0-9]{8})", latest_clip)
    if match:
        taskshort = match.group(1)
        log.info("Auto-detected taskshort from filename: %s", taskshort)
        return f"{taskshort}-auto-detected", taskshort

    log.error("Could not auto-detect task from clip filenames")
    sys.exit(1)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)

    if args.latest:
        task_id, taskshort = find_latest_task(args.clips_dir)
    elif args.task_id:
        task_id = args.task_id
        taskshort = derive_taskshort(args.task_id, args.taskshort)
    elif args.taskshort:
        taskshort = derive_taskshort(None, args.taskshort)
        task_id = f"{taskshort}-taskshort"
    else:
        log.error(
            "Provide --task-id, --taskshort, or use --latest"
        )
        sys.exit(1)

    hook_bank = args.hook_bank
    if hook_bank is None:
        # Default: look relative to script location
        script_dir = Path(__file__).resolve().parent.parent
        default_hook_bank = script_dir / "configs" / "vpi_hook_bank.json"
        if default_hook_bank.exists():
            hook_bank = str(default_hook_bank)

    validate_task(
        task_id=task_id,
        taskshort=taskshort,
        clips_dir=args.clips_dir,
        output_dir=args.out,
        hook_bank_path=hook_bank,
    )


if __name__ == "__main__":
    main()
