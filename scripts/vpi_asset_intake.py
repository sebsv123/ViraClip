#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "assets" / "vpi_asset_manifest.json"
TEMPLATE_MANIFEST = ROOT / "assets" / "vpi_asset_manifest.template.json"

ASSET_TYPE_MAP = {
    "icon": "icons",
    "icons": "icons",
    "font": "fonts",
    "fonts": "fonts",
    "broll": "broll",
    "sfx": "sfx",
    "bgm": "bgm",
}

ALLOWED_ROOTS = {
    "broll": ("assets/broll", "backend/assets/broll", "/app/assets/broll"),
    "sfx": ("assets/sounds/sfx", "backend/assets/sounds/sfx", "/app/assets/sounds/sfx"),
    "bgm": ("assets/sounds/bgm", "backend/assets/sounds/bgm", "/app/assets/sounds/bgm"),
    "icons": ("assets/icons", "backend/assets/icons", "/app/assets/icons"),
    "fonts": ("assets/fonts", "backend/assets/fonts", "/app/assets/fonts"),
}

ALLOWED_EXTS = {
    "broll": {".mp4", ".mov", ".webm"},
    "sfx": {".mp3", ".wav", ".ogg", ".m4a"},
    "bgm": {".mp3", ".wav", ".ogg", ".m4a"},
    "icons": {".svg", ".png"},
    "fonts": {".ttf", ".otf", ".woff", ".woff2"},
}

READY_THRESHOLDS = {"broll": 10, "sfx": 10, "icons": 10, "bgm": 3, "fonts": 1}

KNOWN_SOURCES = {
    "pexels": {"license": "Pexels License", "commercial_use_ok": True, "attribution_required": False},
    "pixabay": {"license": "Pixabay Content License", "commercial_use_ok": True, "attribution_required": False},
    "mixkit": {"license": "Mixkit Free License", "commercial_use_ok": True, "attribution_required": False},
    "coverr": {"license": "Coverr License", "commercial_use_ok": True, "attribution_required": False},
    "freesound_cc0": {"license": "CC0", "commercial_use_ok": True, "attribution_required": False},
    "freesound_cc_by": {"license": "CC BY", "commercial_use_ok": True, "attribution_required": True},
    "freesound_ccby": {"license": "CC BY", "commercial_use_ok": True, "attribution_required": True},
    "lucide": {"license": "ISC", "commercial_use_ok": True, "attribution_required": False},
    "tabler": {"license": "MIT", "commercial_use_ok": True, "attribution_required": False},
    "heroicons": {"license": "MIT", "commercial_use_ok": True, "attribution_required": False},
    "google_fonts_ofl": {"license": "SIL Open Font License", "commercial_use_ok": True, "attribution_required": False},
    "google_fonts": {"license": "SIL Open Font License", "commercial_use_ok": True, "attribution_required": False},
}


def _bool_from_text(value: str) -> bool:
    lowered = str(value).strip().lower()
    if lowered in {"true", "1", "yes"}:
        return True
    if lowered in {"false", "0", "no"}:
        return False
    raise ValueError(f"invalid boolean value: {value}")


def _normalize_type(asset_type: str) -> str:
    return ASSET_TYPE_MAP.get(str(asset_type or "").strip().lower(), "")


def _abs_path(candidate: str) -> Path:
    path = Path(candidate)
    return path if path.is_absolute() else (ROOT / path)


def _allowed_root_paths(asset_type: str) -> List[Path]:
    return [_abs_path(p).resolve() for p in ALLOWED_ROOTS.get(asset_type, tuple())]


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


def _empty_manifest() -> Dict[str, Any]:
    return {"version": "1.0", "sources": {}, "assets": []}


def _load_manifest(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return _empty_manifest()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"manifest_parse_error:{exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("manifest_invalid_root")
    data.setdefault("version", "1.0")
    data.setdefault("sources", {})
    data.setdefault("assets", [])
    if not isinstance(data["sources"], dict) or not isinstance(data["assets"], list):
        raise RuntimeError("manifest_invalid_structure")
    return data


def _ensure_manifest(path: Path) -> Dict[str, Any]:
    if path.exists():
        return _load_manifest(path)
    if TEMPLATE_MANIFEST.exists():
        data = json.loads(TEMPLATE_MANIFEST.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = _empty_manifest()
    else:
        data = _empty_manifest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return _load_manifest(path)


def _write_manifest(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _validate_new_asset(asset: Dict[str, Any], existing_assets: List[Dict[str, Any]]) -> Tuple[bool, str]:
    asset_type = _normalize_type(asset.get("type"))
    if not asset_type:
        return False, "invalid_type"
    asset_id = str(asset.get("id") or "").strip()
    if not asset_id:
        return False, "missing_id"
    path_text = str(asset.get("path") or "").strip()
    if not path_text:
        return False, "missing_path"
    source = str(asset.get("source") or "").strip()
    if not source:
        return False, "source_missing"
    license_name = str(asset.get("license_name") or "").strip()
    if not license_name:
        return False, "license_missing"
    if "commercial_use_ok" not in asset:
        return False, "commercial_use_missing"
    if "attribution_required" not in asset:
        return False, "attribution_required_missing"

    path_abs = _abs_path(path_text)
    if not _path_within_allowed_roots(path_abs, asset_type):
        return False, "path_outside_assets"
    if not path_abs.exists() or not path_abs.is_file():
        return False, "missing_file"
    ext = path_abs.suffix.lower()
    if ext not in ALLOWED_EXTS[asset_type]:
        return False, "invalid_extension"

    existing_ids = {str(item.get("id") or "").strip() for item in existing_assets if isinstance(item, dict)}
    if asset_id in existing_ids:
        return False, "duplicate_id"

    tags = list(asset.get("tags") or [])
    if asset_type != "fonts" and not tags:
        return False, "tags_missing"
    if asset_type == "broll":
        if not list(asset.get("topics") or []):
            return False, "topics_missing"
        if not str(asset.get("sensitive_tone") or "").strip():
            return False, "sensitive_tone_missing"
    return True, "ok"


def _coerce_path_for_manifest(path_text: str) -> str:
    path = Path(path_text)
    if path.is_absolute():
        try:
            return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
        except ValueError:
            return str(path)
    return str(path).replace("\\", "/")


def _ensure_source_registry(manifest: Dict[str, Any], source: str, asset: Dict[str, Any]) -> str:
    sources = manifest.setdefault("sources", {})
    src_key = str(source).strip()
    known = KNOWN_SOURCES.get(src_key)
    if src_key not in sources:
        if known:
            sources[src_key] = {
                "license": known["license"],
                "commercial_use_ok": bool(known["commercial_use_ok"]),
                "attribution_required": bool(known["attribution_required"]),
                "notes": "Auto-added by vpi_asset_intake.py",
            }
            return "known_source_added"
        sources[src_key] = {
            "license": str(asset.get("license_name") or ""),
            "commercial_use_ok": bool(asset.get("commercial_use_ok")),
            "attribution_required": bool(asset.get("attribution_required")),
            "notes": "Unknown source added manually. Verify legal terms.",
        }
        return "unknown_source_added"
    return "source_exists"


def _normalize_asset_entry(raw: Dict[str, Any]) -> Dict[str, Any]:
    asset_type = _normalize_type(raw.get("type"))
    out: Dict[str, Any] = {
        "id": str(raw.get("id") or "").strip(),
        "type": asset_type,
        "path": _coerce_path_for_manifest(str(raw.get("path") or "").strip()),
        "source": str(raw.get("source") or "").strip(),
        "source_url": str(raw.get("source_url") or "").strip(),
        "license_name": str(raw.get("license_name") or "").strip(),
        "commercial_use_ok": bool(raw.get("commercial_use_ok")),
        "attribution_required": bool(raw.get("attribution_required")),
        "tags": [str(item).strip() for item in list(raw.get("tags") or []) if str(item).strip()],
        "topics": [str(item).strip() for item in list(raw.get("topics") or []) if str(item).strip()],
        "sensitive_tone": str(raw.get("sensitive_tone") or "").strip() or ("safe" if asset_type == "broll" else ""),
    }
    if "duration_hint" in raw and raw.get("duration_hint") is not None:
        out["duration_hint"] = float(raw["duration_hint"])
    if raw.get("avoid_for"):
        out["avoid_for"] = [str(item).strip() for item in list(raw["avoid_for"]) if str(item).strip()]
    return out


def _build_index_from_manifest_data(manifest: Dict[str, Any]) -> Dict[str, Any]:
    verified: Dict[str, List[Dict[str, Any]]] = {k: [] for k in ("broll", "sfx", "bgm", "icons", "fonts")}
    invalid_assets: List[Dict[str, Any]] = []
    warnings: List[str] = []
    assets = [item for item in manifest.get("assets", []) if isinstance(item, dict)]
    for item in assets:
        item_copy = dict(item)
        ok, reason = _validate_new_asset(item_copy, [])
        item_copy["asset_valid"] = ok
        item_copy["reason"] = reason
        typ = _normalize_type(item_copy.get("type"))
        if not typ:
            invalid_assets.append(item_copy)
            warnings.append(f"unknown:{reason}:{item_copy.get('path')}")
            continue
        if ok:
            verified[typ].append(item_copy)
        else:
            invalid_assets.append(item_copy)
            warnings.append(f"{typ}:{reason}:{item_copy.get('path')}")
    return {
        "manifest_found": True,
        "manifest_path": str(DEFAULT_MANIFEST),
        "manifest_version": str(manifest.get("version") or "1.0"),
        "sources": dict(manifest.get("sources") or {}),
        "verified": verified,
        "invalid_assets": invalid_assets,
        "warnings": warnings,
        "unverified_local": {k: [] for k in ("broll", "sfx", "bgm", "icons", "fonts")},
        "all_discovered": {"summary": {k: 0 for k in ("broll", "sfx", "bgm", "icons", "fonts")}},
    }


def cmd_add(args: argparse.Namespace) -> int:
    try:
        commercial_use_ok = _bool_from_text(args.commercial_use_ok)
        attribution_required = _bool_from_text(args.attribution_required)
    except ValueError as exc:
        print(f"[asset-intake] validation_pass=false reason={exc}")
        return 1

    manifest_path = Path(args.manifest).resolve()
    payload = {
        "id": args.id,
        "type": args.type,
        "path": args.path,
        "source": args.source,
        "source_url": args.source_url or "",
        "license_name": args.license_name or "",
        "commercial_use_ok": commercial_use_ok,
        "attribution_required": attribution_required,
        "tags": args.tags or [],
        "topics": args.topics or [],
        "sensitive_tone": args.sensitive_tone or "",
        "duration_hint": args.duration_hint,
    }
    print(f"[asset-intake] add requested id={args.id} type={args.type} path={args.path}")

    try:
        manifest = _ensure_manifest(manifest_path)
    except Exception as exc:
        print(f"[asset-intake] validation_pass=false reason=manifest_error:{exc}")
        return 1

    source_key = str(args.source or "").strip()
    if source_key not in KNOWN_SOURCES and (not args.license_name or args.commercial_use_ok is None or args.attribution_required is None):
        print("[asset-intake] validation_pass=false reason=unknown_source_requires_explicit_license_flags")
        return 1

    normalized = _normalize_asset_entry(payload)
    valid, reason = _validate_new_asset(normalized, manifest.get("assets", []))
    if not valid:
        print(f"[asset-intake] validation_pass=false reason={reason}")
        return 1
    print("[asset-intake] validation_pass=true reason=ok")

    source_status = _ensure_source_registry(manifest, source_key, normalized)
    if source_status == "unknown_source_added":
        print("[asset-intake] warning=unknown_source_added_manual_review_required")
    manifest.setdefault("assets", []).append(normalized)
    _write_manifest(manifest_path, manifest)
    print(f"[asset-intake] manifest_updated=true path={manifest_path}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).resolve()
    if not manifest_path.exists():
        manifest = _empty_manifest()
    else:
        try:
            manifest = _load_manifest(manifest_path)
        except Exception as exc:
            print(f"ASSET_INTAKE_VALIDATE=FAIL")
            print("ASSET_LIBRARY_STATUS=INVALID")
            print(f"[asset-intake] validate_error=manifest_error:{exc}")
            return 1

    if str(ROOT / "backend" / "src") not in sys.path:
        sys.path.insert(0, str(ROOT / "backend" / "src"))
    from services.vpi_asset_library_service import build_asset_library_qc_report  # type: ignore

    index = _build_index_from_manifest_data(manifest)
    qc = build_asset_library_qc_report(index)
    verified = index.get("verified", {})
    invalid_assets = list(index.get("invalid_assets") or [])
    total = len([item for item in manifest.get("assets", []) if isinstance(item, dict)])
    valid_count = sum(len(v) for v in verified.values())
    invalid_count = len(invalid_assets)
    print(f"[asset-intake] total_assets={total}")
    print(f"[asset-intake] valid_assets={valid_count}")
    print(f"[asset-intake] invalid_assets={invalid_count}")
    print(
        "[asset-intake] verified_by_type="
        f"broll:{len(verified.get('broll', []))}|sfx:{len(verified.get('sfx', []))}|bgm:{len(verified.get('bgm', []))}|icons:{len(verified.get('icons', []))}|fonts:{len(verified.get('fonts', []))}"
    )
    for warning in list(qc.get("license_warnings") or []):
        print(f"[asset-intake] warning={warning}")
    status = str(qc.get("asset_library_status") or "INVALID")
    passed = status in {"EMPTY", "PARTIAL", "READY"}
    print(f"ASSET_INTAKE_VALIDATE={'PASS' if passed else 'FAIL'}")
    print(f"ASSET_LIBRARY_STATUS={status}")
    return 0 if passed else 1


def cmd_list(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).resolve()
    manifest = _load_manifest(manifest_path) if manifest_path.exists() else _empty_manifest()
    items = [item for item in manifest.get("assets", []) if isinstance(item, dict)]
    out_rows: List[Dict[str, Any]] = []
    for item in items:
        normalized = _normalize_asset_entry(item)
        valid, reason = _validate_new_asset(normalized, [])
        status = "verified" if valid else "invalid"
        if args.status and status != args.status:
            continue
        if args.type and _normalize_type(args.type) != normalized["type"]:
            continue
        out_rows.append(
            {
                "id": normalized["id"],
                "type": normalized["type"],
                "path": normalized["path"],
                "source": normalized.get("source", ""),
                "license": normalized.get("license_name", ""),
                "commercial": normalized.get("commercial_use_ok", False),
                "attribution": normalized.get("attribution_required", False),
                "tags": ",".join(normalized.get("tags", [])),
                "_reason": reason,
            }
        )
    if args.status == "unverified":
        print("id | type | path | source | license | commercial | attribution | tags")
        return 0
    print("id | type | path | source | license | commercial | attribution | tags")
    for row in out_rows:
        print(
            f"{row['id']} | {row['type']} | {row['path']} | {row['source']} | {row['license']} | "
            f"{str(bool(row['commercial'])).lower()} | {str(bool(row['attribution'])).lower()} | {row['tags']}"
        )
    return 0


def cmd_suggest(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest).resolve()
    manifest = _load_manifest(manifest_path) if manifest_path.exists() else _empty_manifest()
    index = _build_index_from_manifest_data(manifest)
    verified = index["verified"]
    print("Need:")
    for key in ("broll", "sfx", "icons", "bgm", "fonts"):
        current = len(verified.get(key, []))
        required = READY_THRESHOLDS[key]
        label = key
        print(f"- {label}: {required} verified minimum, current {current}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="VPI local asset intake helper")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Manifest path to read/write")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="Add one asset to manifest")
    add.add_argument("--type", required=True)
    add.add_argument("--path", required=True)
    add.add_argument("--id", required=True)
    add.add_argument("--source", required=True)
    add.add_argument("--source-url", default="")
    add.add_argument("--license-name", default="")
    add.add_argument("--commercial-use-ok", required=True)
    add.add_argument("--attribution-required", required=True)
    add.add_argument("--tags", nargs="*", default=[])
    add.add_argument("--topics", nargs="*", default=[])
    add.add_argument("--sensitive-tone", default="")
    add.add_argument("--duration-hint", type=float, default=None)
    add.set_defaults(func=cmd_add)

    validate = sub.add_parser("validate", help="Validate manifest and print status")
    validate.set_defaults(func=cmd_validate)

    list_cmd = sub.add_parser("list", help="List manifest assets")
    list_cmd.add_argument("--type", default="")
    list_cmd.add_argument("--status", choices=["verified", "invalid", "unverified"], default="")
    list_cmd.set_defaults(func=cmd_list)

    suggest = sub.add_parser("suggest", help="Suggest missing assets for READY")
    suggest.set_defaults(func=cmd_suggest)

    return parser


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
