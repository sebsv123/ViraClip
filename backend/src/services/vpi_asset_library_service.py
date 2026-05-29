from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]

_ASSET_PATHS: Dict[str, Tuple[str, ...]] = {
    "broll": (
        "assets/broll",
        "backend/assets/broll",
        "/app/assets/broll",
    ),
    "sfx": (
        "assets/sounds/sfx",
        "backend/assets/sounds/sfx",
        "/app/assets/sounds/sfx",
    ),
    "bgm": (
        "assets/sounds/bgm",
        "backend/assets/sounds/bgm",
        "/app/assets/sounds/bgm",
    ),
    "icons": (
        "assets/icons",
        "backend/assets/icons",
        "/app/assets/icons",
    ),
    "fonts": (
        "assets/fonts",
        "backend/assets/fonts",
        "/app/assets/fonts",
    ),
}

_MANIFEST_CANDIDATES: Tuple[str, ...] = (
    "assets/manifest.json",
    "assets/vpi_asset_manifest.json",
    "backend/assets/manifest.json",
    "/app/assets/manifest.json",
)

_ASSET_EXTS: Dict[str, Tuple[str, ...]] = {
    "broll": (".mp4", ".mov", ".webm", ".m4v", ".jpg", ".jpeg", ".png", ".webp"),
    "sfx": (".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac"),
    "bgm": (".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac"),
    "icons": (".svg", ".png", ".webp"),
    "fonts": (".ttf", ".otf", ".woff", ".woff2"),
}

EDITORIAL_BROLL_INTENTS: Tuple[str, ...] = (
    "family_relief",
    "emotional_support",
    "health_access",
    "practical_explanation",
    "autonomous_work_stability",
    "risk_warning_context",
    "calm_lifestyle",
    "paperwork_support",
    "office_work",
    "medical_care",
    "family_home",
    "no_broll_needed",
)

EDITORIAL_SFX_FAMILIES: Tuple[str, ...] = (
    "dark_riser",
    "high_riser",
    "tension_riser",
    "magic_whoosh",
    "deep_boom",
    "soft_chime",
    "click_soft",
    "ambient_soft",
    "no_sfx_needed",
)

EDITORIAL_ICON_CONCEPTS: Tuple[str, ...] = (
    "family",
    "health",
    "shield",
    "heart",
    "warning",
    "briefcase",
    "document",
    "euro",
    "calendar",
    "phone",
    "support",
)

EDITORIAL_FONT_ROLES: Tuple[str, ...] = (
    "caption_primary",
    "caption_emphasis",
    "lower_third",
    "brand_title",
)


def _abs_path(candidate: str) -> Path:
    path = Path(candidate)
    return path if path.is_absolute() else (_REPO_ROOT / path)


def _allowed_root_paths(asset_type: str) -> List[Path]:
    return [_abs_path(root).resolve() for root in _ASSET_PATHS.get(asset_type, tuple())]


def _path_within_allowed_roots(path: Path, asset_type: str) -> bool:
    try:
        resolved = path.resolve(strict=False)
    except Exception:
        return False
    for root in _allowed_root_paths(asset_type):
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _iter_asset_files(asset_type: str, roots: Iterable[str]) -> List[Path]:
    files: List[Path] = []
    exts = tuple(ext.lower() for ext in _ASSET_EXTS.get(asset_type, tuple()))
    seen: set[str] = set()
    for root in roots:
        root_path = _abs_path(root)
        if not root_path.exists() or not root_path.is_dir():
            continue
        for item in sorted(root_path.rglob("*")):
            if not item.is_file() or item.suffix.lower() not in exts:
                continue
            key = str(item.resolve())
            if key in seen:
                continue
            seen.add(key)
            files.append(item)
    return files


def discover_asset_library() -> Dict[str, Any]:
    discovered: Dict[str, Any] = {}
    summary: Dict[str, int] = {}
    for asset_type, roots in _ASSET_PATHS.items():
        files = _iter_asset_files(asset_type, roots)
        discovered[asset_type] = [str(path) for path in files]
        summary[asset_type] = len(files)
        logger.info("[asset-library] discovered type=%s count=%d", asset_type, len(files))
    discovered["summary"] = summary
    logger.info("[asset-library] taxonomy_loaded=true")
    return discovered


def load_asset_manifest() -> Dict[str, Any]:
    for candidate in _MANIFEST_CANDIDATES:
        manifest_path = _abs_path(candidate)
        if not manifest_path.exists():
            continue
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            logger.info("[asset-library] manifest_found=true path=%s", manifest_path)
            return {
                "manifest_found": True,
                "manifest_path": str(manifest_path),
                "version": str(payload.get("version") or "1.0"),
                "sources": dict(payload.get("sources") or {}),
                "assets": list(payload.get("assets") or []),
            }
        except Exception as exc:
            logger.warning("[asset-library] manifest_parse_error path=%s reason=%s", manifest_path, exc)
            continue
    logger.info("[asset-library] manifest_found=false path=")
    return {
        "manifest_found": False,
        "manifest_path": "",
        "version": "1.0",
        "sources": {},
        "assets": [],
    }


def validate_asset_entry(asset: Dict[str, Any]) -> Dict[str, Any]:
    asset_type = str(asset.get("type") or "").strip().lower()
    rel_path = str(asset.get("path") or "").strip()
    path = _abs_path(rel_path) if rel_path else Path("")
    exists = bool(rel_path and path.exists() and path.is_file())
    source_name = str(asset.get("source") or asset.get("source_name") or "").strip()
    license_name = str(asset.get("license_name") or "").strip()
    tags = list(asset.get("tags") or [])
    sensitive_tone = str(asset.get("sensitive_tone") or "safe")
    commercial_use_ok = bool(asset.get("commercial_use_ok", False))
    attribution_required = bool(asset.get("attribution_required", False))
    source_url = str(asset.get("source_url") or "")
    path_allowed = bool(asset_type in _ASSET_PATHS and rel_path and _path_within_allowed_roots(path, asset_type))

    reason = "ok"
    valid = True
    if asset_type not in _ASSET_PATHS:
        valid = False
        reason = "invalid_type"
    elif not rel_path:
        valid = False
        reason = "missing_path"
    elif not path_allowed:
        valid = False
        reason = "path_outside_assets"
    elif not exists:
        valid = False
        reason = "missing_file"
    elif not source_name:
        valid = False
        reason = "source_missing"
    elif not license_name:
        valid = False
        reason = "license_missing"
    elif not tags:
        valid = False
        reason = "tags_missing"
    elif not commercial_use_ok:
        valid = False
        reason = "commercial_use_not_ok"

    result = {
        "id": str(asset.get("id") or ""),
        "type": asset_type,
        "path": str(path) if rel_path else "",
        "exists": exists,
        "path_allowed": path_allowed,
        "source_name": source_name,
        "source_url": source_url,
        "license_name": license_name,
        "tags": tags,
        "topics": list(asset.get("topics") or []),
        "sensitive_tone": sensitive_tone,
        "commercial_use_ok": commercial_use_ok,
        "attribution_required": attribution_required,
        "downloaded_at": str(asset.get("downloaded_at") or ""),
        "asset_valid": valid,
        "reason": reason,
    }
    logger.info("[asset-library] asset_valid=%s path=%s reason=%s", str(valid).lower(), result["path"] or rel_path, reason)
    return result


def build_asset_index() -> Dict[str, Any]:
    discovered = discover_asset_library()
    manifest = load_asset_manifest()
    validated_assets: List[Dict[str, Any]] = []
    for entry in manifest.get("assets", []):
        if isinstance(entry, dict):
            validated_assets.append(validate_asset_entry(entry))

    by_type_verified: Dict[str, List[Dict[str, Any]]] = {key: [] for key in _ASSET_PATHS}
    by_type_unverified: Dict[str, List[Dict[str, Any]]] = {key: [] for key in _ASSET_PATHS}
    invalid_assets: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for item in validated_assets:
        asset_type = str(item.get("type") or "")
        if asset_type not in by_type_verified:
            continue
        if item.get("asset_valid"):
            by_type_verified[asset_type].append(item)
        else:
            invalid_assets.append(item)
            warnings.append(f"{asset_type}:{item.get('reason')}:{item.get('path')}")

    verified_paths = {str(item.get("path")) for item in validated_assets if item.get("asset_valid")}
    for asset_type in _ASSET_PATHS:
        for path in discovered.get(asset_type, []):
            if path in verified_paths:
                continue
            by_type_unverified[asset_type].append(
                {
                    "id": "",
                    "type": asset_type,
                    "path": path,
                    "exists": True,
                    "source_name": "unverified_local",
                    "source_url": "",
                    "license_name": "",
                    "tags": [],
                    "topics": [],
                    "sensitive_tone": "unknown",
                    "commercial_use_ok": False,
                    "attribution_required": False,
                    "downloaded_at": "",
                    "asset_valid": False,
                    "reason": "unverified_local",
                }
            )

    index = {
        "manifest_found": bool(manifest.get("manifest_found")),
        "manifest_path": str(manifest.get("manifest_path") or ""),
        "manifest_version": str(manifest.get("version") or "1.0"),
        "sources": dict(manifest.get("sources") or {}),
        "taxonomy": {
            "broll_intents": list(EDITORIAL_BROLL_INTENTS),
            "sfx_families": list(EDITORIAL_SFX_FAMILIES),
            "icon_concepts": list(EDITORIAL_ICON_CONCEPTS),
            "font_roles": list(EDITORIAL_FONT_ROLES),
        },
        "verified": by_type_verified,
        "unverified_local": by_type_unverified,
        "invalid_assets": invalid_assets,
        "warnings": warnings,
        "all_discovered": discovered,
    }
    logger.info(
        "[asset-library] index_ready=true broll=%d sfx=%d icons=%d fonts=%d",
        len(by_type_verified["broll"]),
        len(by_type_verified["sfx"]),
        len(by_type_verified["icons"]),
        len(by_type_verified["fonts"]),
    )
    return index


def build_asset_library_qc_report(index: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    idx = index or {}
    verified = dict(idx.get("verified") or {})
    invalid_assets = list(idx.get("invalid_assets") or [])
    counts = {
        "broll": len(verified.get("broll") or []),
        "sfx": len(verified.get("sfx") or []),
        "bgm": len(verified.get("bgm") or []),
        "icons": len(verified.get("icons") or []),
        "fonts": len(verified.get("fonts") or []),
    }
    missing = [key for key, value in counts.items() if value == 0]
    license_warnings: List[str] = []
    recommendations: List[str] = []

    invalid_manifest_assets = [str(item.get("path") or "") for item in invalid_assets]
    for asset_type, assets in verified.items():
        for item in assets:
            if not item.get("commercial_use_ok"):
                invalid_manifest_assets.append(str(item.get("path") or ""))
                license_warnings.append(f"{asset_type}:commercial_use_not_ok:{item.get('path')}")
    for item in invalid_assets:
        license_warnings.append(f"{item.get('type')}:{item.get('reason')}:{item.get('path')}")

    if counts["broll"] >= 10 and counts["sfx"] >= 10 and counts["icons"] >= 10 and counts["bgm"] >= 3 and counts["fonts"] >= 1:
        status = "READY"
    elif sum(counts.values()) == 0:
        status = "EMPTY"
        recommendations.append("add_verified_assets_with_manifest")
    else:
        status = "PARTIAL"
        recommendations.append("increase_verified_assets_for_missing_categories")

    if invalid_manifest_assets:
        status = "INVALID"

    logger.info("[asset-library-qc] status=%s", status)
    logger.info("[asset-library-qc] missing=%s", "|".join(missing) or "none")
    for warning in license_warnings:
        logger.info("[asset-library-qc] warning=%s", warning)
    return {
        "asset_library_status": status,
        "counts": counts,
        "missing_categories": missing,
        "license_warnings": license_warnings,
        "recommendations": recommendations,
        "invalid_assets": invalid_manifest_assets,
    }
