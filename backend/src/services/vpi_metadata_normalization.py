"""Small metadata normalization helpers for post-render task finalization."""

from __future__ import annotations

from typing import Any, Dict


def _normalize_sfx_meta(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, bool):
        return {"sfx_applied": value}
    if value is None:
        return {"sfx_applied": False}
    if isinstance(value, str):
        normalized = value.strip().lower() in {"true", "1", "yes", "applied", "on"}
        return {"sfx_applied": normalized, "raw_sfx_meta": value}
    return {"sfx_applied": False, "raw_sfx_meta_type": type(value).__name__}
