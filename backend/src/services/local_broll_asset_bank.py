"""
local_broll_asset_bank.py — Local B-roll Asset Bank VPI v2.

Maps editorial cue types to local asset directories and returns a varied
asset using a simple usage-history JSON file to avoid visual repetition.

No external APIs, no embeddings, no downloads, no database.

Directory structure expected under LOCAL_BROLL_ASSET_DIR:

    /app/assets/broll/
        family_protection/
        emotional_reassurance/
        risk_warning/
        documents_admin/
        advisor_meeting/
        healthy_lifestyle/
        financial_planning/

Compatible extensions: .mp4, .mov, .webm, .jpg, .jpeg, .png
"""
import json
import logging
import os
import random
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────────────
_DEFAULT_ASSET_DIR = "/app/assets/broll"
_HISTORY_FILENAME = ".usage_history.json"
_MAX_RECENT = 10
_RECENT_PENALTY = 100
_VERY_RECENT_PENALTY = 300
_USES_PENALTY_PER_USE = 10
_JITTER_MAX = 5

# ── Cue type → subdirectory mapping ───────────────────────────────────────────
# Maps allowed VPI B-roll categories to local asset subdirectories.
# Allowed categories: family_relief, family_protection, health_access,
# risk_warning_context, paperwork_support, documents_admin, financial_planning,
# practical_explanation, autonomous_work_stability, emotional_reassurance
_CUE_TYPE_DIR_MAP: dict[str, str | None] = {
    "family_protection":           "family_protection",
    "family_relief":               "family_protection",       # shares family assets
    "emotional_reassurance":       "emotional_reassurance",
    "risk_warning":                "risk_warning",
    "risk_warning_context":        "risk_warning",            # shares risk assets
    "documents_admin":             "documents_admin",
    "paperwork_support":           "documents_admin",         # shares documents assets
    "advisor_meeting":             "advisor_meeting",
    "healthy_lifestyle":           "healthy_lifestyle",
    "health_access":               "healthy_lifestyle",       # shares lifestyle assets
    "financial_planning":          "financial_planning",
    "practical_explanation":       "practical_explanation",
    "autonomous_work_stability":   "financial_planning",      # shares financial assets
    "no_broll":                    None,
}

_ASSET_EXTENSIONS = {".mp4", ".mov", ".webm", ".jpg", ".jpeg", ".png"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_asset_dir() -> Path:
    return Path(os.environ.get("LOCAL_BROLL_ASSET_DIR", _DEFAULT_ASSET_DIR))


def _history_path() -> Path:
    return _get_asset_dir() / _HISTORY_FILENAME


# ── History persistence ───────────────────────────────────────────────────────

def _load_history() -> dict:
    """
    Load usage history from the JSON file.

    Returns a dict with keys ``assets`` (dict) and ``recent`` (list).
    On corruption or missing file, returns an empty history and logs a warning.
    """
    empty: dict = {"assets": {}, "recent": []}
    path = _history_path()
    if not path.exists():
        return empty
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("root is not a dict")
        data.setdefault("assets", {})
        data.setdefault("recent", [])
        return data
    except Exception as exc:
        logger.warning("[local-broll] history corrupt; resetting: %s", exc)
        # Attempt to move the corrupt file aside for debugging
        try:
            corrupt = path.with_name(".usage_history_corrupt.json")
            path.rename(corrupt)
        except Exception:
            path.unlink(missing_ok=True)
        return empty


def _save_history_atomic(data: dict) -> None:
    """Write *data* to the history file atomically (tmp + replace)."""
    path = _history_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{_HISTORY_FILENAME}.tmp")
        tmp.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(path)
    except Exception as exc:
        logger.warning("[local-broll] failed to save history: %s", exc)


# ── Asset listing ─────────────────────────────────────────────────────────────

def list_assets(cue_type: str) -> list[Path]:
    """
    Return all compatible video files for *cue_type*, sorted by name.

    Returns an empty list if the directory is missing or empty.
    """
    asset_root = _get_asset_dir()
    subdir_name = _CUE_TYPE_DIR_MAP.get(cue_type)
    if subdir_name is None:
        return []

    cue_dir = asset_root / subdir_name
    if not cue_dir.is_dir():
        return []

    result: list[Path] = []
    try:
        for entry in sorted(cue_dir.iterdir()):
            if entry.name.startswith("."):
                continue
            if entry.suffix.lower() in _ASSET_EXTENSIONS and entry.is_file():
                result.append(entry)
    except PermissionError as exc:
        logger.warning("[local-broll] permission error reading %s: %s", cue_dir, exc)
        return []

    return result


# ── Scoring & selection ───────────────────────────────────────────────────────

def _score_asset(
    asset_path: Path,
    history: dict,
    recent_list: list[str],
) -> int:
    """
    Compute a score for *asset_path* — lower is better (more likely to be chosen).

    Factors:
      - uses × 10
      - recent penalty: +100 if in last 10, +300 if in last 3
      - random jitter 0-5
    """
    info = history.get("assets", {}).get(str(asset_path), {})
    uses = info.get("uses", 0)
    score = uses * _USES_PENALTY_PER_USE

    asset_str = str(asset_path)
    try:
        idx = recent_list.index(asset_str)
        if idx < 3:
            score += _VERY_RECENT_PENALTY
        else:
            score += _RECENT_PENALTY
    except ValueError:
        pass  # not recent — no penalty

    score += random.randint(0, _JITTER_MAX)
    return score


def find_asset(
    cue_type: str,
    task_id: Optional[str] = None,
    avoid_recent: bool = True,
) -> Optional[Path]:
    """
    Search for a local B-roll asset matching *cue_type*.

    Uses usage-history scoring to avoid repeating recently-used assets.
    Returns the path to the best candidate, or None.
    """
    candidates = list_assets(cue_type)
    if not candidates:
        logger.info("[local-broll] no local asset found for cue_type=%s", cue_type)
        return None

    logger.info(
        "[local-broll] candidates=%d cue_type=%s",
        len(candidates), cue_type,
    )

    if len(candidates) == 1:
        selected = candidates[0]
        logger.info(
            "[local-broll] selected asset=%s (only candidate)",
            selected,
        )
        return selected

    history = _load_history()
    recent_list = history.get("recent", [])

    scored = [
        (_score_asset(p, history, recent_list) if avoid_recent else 0, p)
        for p in candidates
    ]
    scored.sort(key=lambda x: x[0])

    selected = scored[0][1]
    info = history.get("assets", {}).get(str(selected), {})
    logger.info(
        "[local-broll] selected asset=%s uses=%d recent_penalty=%d",
        selected,
        info.get("uses", 0),
        scored[0][0] - info.get("uses", 0) * _USES_PENALTY_PER_USE,
    )
    return selected


# ── Usage tracking ────────────────────────────────────────────────────────────

def mark_used(asset_path: Path, task_id: Optional[str] = None) -> None:
    """
    Record that *asset_path* was used, updating the history file.

    Safe to call even if the history file doesn't exist yet.
    """
    history = _load_history()
    assets = history.setdefault("assets", {})
    recent = history.setdefault("recent", [])

    asset_str = str(asset_path)
    entry = assets.setdefault(asset_str, {"uses": 0})
    entry["uses"] += 1
    entry["last_used_at"] = datetime.now(timezone.utc).isoformat()
    if task_id is not None:
        entry["last_task_id"] = task_id

    # Move to front of recent list
    if asset_str in recent:
        recent.remove(asset_str)
    recent.insert(0, asset_str)
    # Trim
    history["recent"] = recent[:_MAX_RECENT]

    _save_history_atomic(history)
    logger.info("[local-broll] marked used asset=%s task_id=%s", asset_str, task_id or "")


class LocalBrollAssetBank:
    """Small object facade for manual smoke tests and callers that prefer methods."""

    def list_assets(self, cue_type: str) -> list[Path]:
        return list_assets(cue_type)

    def find_asset(
        self,
        cue_type: str,
        task_id: Optional[str] = None,
        avoid_recent: bool = True,
    ) -> Optional[Path]:
        return find_asset(cue_type, task_id=task_id, avoid_recent=avoid_recent)

    def mark_used(self, asset_path: Path, task_id: Optional[str] = None) -> None:
        mark_used(asset_path, task_id=task_id)
