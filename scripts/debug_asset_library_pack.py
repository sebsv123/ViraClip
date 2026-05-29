#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from services.vpi_asset_library_service import (  # noqa: E402
    build_asset_index,
    build_asset_library_qc_report,
    load_asset_manifest,
    validate_asset_entry,
)
from services.caption_service import plan_caption_overlay_pack  # noqa: E402
from services.vpi_broll_intent import match_broll_asset  # noqa: E402
from services.vpi_sfx_service import match_sfx_asset  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[debug-asset-library-pack] {name}=PASS {detail}".strip())
    else:
        FAIL += 1
        print(f"[debug-asset-library-pack] {name}=FAIL {detail}".strip())


def main() -> int:
    empty_qc = build_asset_library_qc_report({"verified": {"broll": [], "sfx": [], "bgm": [], "icons": [], "fonts": []}})
    check("empty_library_no_fail", empty_qc.get("asset_library_status") == "EMPTY", str(empty_qc))

    manifest = load_asset_manifest()
    check("manifest_missing_no_fail", isinstance(manifest, dict) and "assets" in manifest, str(manifest.get("manifest_found")))

    with tempfile.TemporaryDirectory(prefix="vpi_asset_lib_") as td:
        tmp = Path(td)
        outside_broll = tmp / "sample_broll.mp4"
        outside_broll.write_bytes(b"fake")
        allowed_broll = ROOT / "assets" / "broll" / "family_protection" / "01.mp4"
        allowed_sfx_dir = ROOT / "assets" / "sounds" / "sfx" / "__debug_tmp__"
        allowed_sfx_dir.mkdir(parents=True, exist_ok=True)
        allowed_sfx = allowed_sfx_dir / "debug_soft_chime.mp3"
        allowed_sfx.write_bytes(b"fake")
        valid_entry = validate_asset_entry(
            {
                "id": "test_broll",
                "type": "broll",
                "path": str(allowed_broll),
                "source": "pexels",
                "license_name": "Pexels License",
                "commercial_use_ok": True,
                "attribution_required": False,
                "tags": ["family_relief"],
                "sensitive_tone": "safe",
            }
        )
        check("valid_broll_manifest_asset", bool(valid_entry.get("asset_valid")), str(valid_entry))

        missing_entry = validate_asset_entry(
            {
                "id": "missing_broll",
                "type": "broll",
                "path": str(ROOT / "assets" / "broll" / "__missing__.mp4"),
                "source": "pexels",
                "license_name": "Pexels License",
                "commercial_use_ok": True,
                "attribution_required": False,
                "tags": ["family_relief"],
                "sensitive_tone": "safe",
            }
        )
        check("missing_file_warning", not bool(missing_entry.get("asset_valid")) and missing_entry.get("reason") == "missing_file", str(missing_entry))

        blocked_entry = validate_asset_entry(
            {
                "id": "blocked_commercial",
                "type": "sfx",
                "path": str(allowed_sfx),
                "source": "mixkit",
                "license_name": "Mixkit Free License",
                "commercial_use_ok": False,
                "attribution_required": False,
                "tags": ["soft_chime"],
                "sensitive_tone": "safe",
            }
        )
        check("commercial_use_not_ok", not bool(blocked_entry.get("asset_valid")) and blocked_entry.get("reason") == "commercial_use_not_ok", str(blocked_entry))

        attr_entry = validate_asset_entry(
            {
                "id": "attr_sfx",
                "type": "sfx",
                "path": str(allowed_sfx),
                "source": "custom",
                "license_name": "CC BY 4.0",
                "commercial_use_ok": True,
                "attribution_required": True,
                "tags": ["soft_chime"],
                "sensitive_tone": "safe",
            }
        )
        check("attribution_allowed", bool(attr_entry.get("asset_valid")) and bool(attr_entry.get("attribution_required")), str(attr_entry))

        outside_entry = validate_asset_entry(
            {
                "id": "outside_path",
                "type": "broll",
                "path": str(outside_broll),
                "source": "pexels",
                "license_name": "Pexels License",
                "commercial_use_ok": True,
                "attribution_required": False,
                "tags": ["family_relief"],
                "sensitive_tone": "safe",
            }
        )
        check("path_outside_assets_blocked", not bool(outside_entry.get("asset_valid")) and outside_entry.get("reason") == "path_outside_assets", str(outside_entry))

        traversal_entry = validate_asset_entry(
            {
                "id": "traversal_path",
                "type": "broll",
                "path": "assets/broll/../../../../tmp/evil.mp4",
                "source": "pexels",
                "license_name": "Pexels License",
                "commercial_use_ok": True,
                "attribution_required": False,
                "tags": ["family_relief"],
                "sensitive_tone": "safe",
            }
        )
        check("path_traversal_blocked", not bool(traversal_entry.get("asset_valid")) and traversal_entry.get("reason") == "path_outside_assets", str(traversal_entry))
        try:
            allowed_sfx.unlink()
            allowed_sfx_dir.rmdir()
        except OSError:
            pass

    broll_match = match_broll_asset(broll_intent="family_relief", topic="decesos", segment_text="alivio para la familia")
    if broll_match.get("matched"):
        check("broll_verified_or_unverified_metadata", "verification_status" in broll_match, str(broll_match))
    else:
        check("broll_unverified_not_auto_true", broll_match.get("reason") in {"no_local_asset", "unverified_local"}, str(broll_match))

    sfx_match = match_sfx_asset(sfx_family="soft_chime", hook_intent="practical_advice", task_id="debug_asset_lib")
    if sfx_match.get("matched"):
        check("sfx_verified_metadata", "sfx_asset_verified" in sfx_match, str(sfx_match))
    else:
        check("sfx_no_verified_asset_handled", sfx_match.get("reason") in {"no_local_asset", "no_verified_asset"}, str(sfx_match))

    icon_check = validate_asset_entry(
        {
            "id": "icon_missing_license",
            "type": "icons",
            "path": str(ROOT / "assets" / "icons" / "missing.svg"),
            "source": "lucide",
            "license_name": "",
            "commercial_use_ok": True,
            "attribution_required": False,
            "tags": ["family"],
            "sensitive_tone": "safe",
        }
    )
    check("icons_without_license_invalid", not bool(icon_check.get("asset_valid")), str(icon_check.get("reason")))

    invalid_qc = build_asset_library_qc_report(
        {
            "verified": {"broll": [], "sfx": [], "bgm": [], "icons": [], "fonts": []},
            "invalid_assets": [{"type": "broll", "path": "assets/broll/bad.mp4", "reason": "commercial_use_not_ok"}],
        }
    )
    check("qc_invalid_blocks", invalid_qc.get("asset_library_status") == "INVALID", str(invalid_qc))

    partial_qc = build_asset_library_qc_report(
        {
            "verified": {
                "broll": [{"path": "a", "commercial_use_ok": True}] * 2,
                "sfx": [{"path": "a", "commercial_use_ok": True}] * 2,
                "bgm": [],
                "icons": [{"path": "a", "commercial_use_ok": True}],
                "fonts": [],
            }
        }
    )
    ready_qc = build_asset_library_qc_report(
        {
            "verified": {
                "broll": [{"path": "a", "commercial_use_ok": True}] * 10,
                "sfx": [{"path": "a", "commercial_use_ok": True}] * 10,
                "bgm": [{"path": "a", "commercial_use_ok": True}] * 3,
                "icons": [{"path": "a", "commercial_use_ok": True}] * 10,
                "fonts": [{"path": "a", "commercial_use_ok": True}],
            }
        }
    )
    check("qc_partial_thresholds", partial_qc.get("asset_library_status") == "PARTIAL", str(partial_qc))
    check("qc_ready_thresholds", ready_qc.get("asset_library_status") == "READY", str(ready_qc))

    caption_plan = plan_caption_overlay_pack("Texto limpio sin iconos locales verificados.", hook_intent="neutral_explanation")
    font_registry = dict(caption_plan.get("font_registry") or {})
    check("fonts_missing_fallback_safe", bool(font_registry.get("caption_font_fallback")), str(font_registry))

    runtime_index = build_asset_index()
    runtime_qc = build_asset_library_qc_report(runtime_index)
    print(f"ASSET_LIBRARY_STATUS={runtime_qc.get('asset_library_status')}")
    print(f"[debug-asset-library-pack] results={PASS} PASS / {FAIL} FAIL")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
