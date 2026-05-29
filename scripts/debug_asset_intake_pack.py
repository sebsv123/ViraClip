#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTAKE = ROOT / "scripts" / "vpi_asset_intake.py"

PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[debug-asset-intake-pack] {name}=PASS {detail}".strip())
    else:
        FAIL += 1
        print(f"[debug-asset-intake-pack] {name}=FAIL {detail}".strip())


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(INTAKE), *args]
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="vpi_intake_debug_") as td:
        tmp = Path(td)
        manifest = tmp / "vpi_asset_manifest.json"
        debug_tag = "__debug_intake_pack__"
        broll_dir = ROOT / "assets" / "broll" / debug_tag / "family_relief"
        broll_dir.mkdir(parents=True, exist_ok=True)
        broll_file = broll_dir / "family_relief_pexels_001.mp4"
        broll_file.write_bytes(b"video")

        sfx_dir = ROOT / "assets" / "sounds" / "sfx" / debug_tag / "soft_chime"
        sfx_dir.mkdir(parents=True, exist_ok=True)
        sfx_file = sfx_dir / "soft_chime_mixkit_001.mp3"
        sfx_file.write_bytes(b"audio")

        icon_dir = ROOT / "assets" / "icons" / debug_tag / "family"
        icon_dir.mkdir(parents=True, exist_ok=True)
        icon_file = icon_dir / "family_lucide_001.svg"
        icon_file.write_text("<svg/>", encoding="utf-8")

        font_dir = ROOT / "assets" / "fonts" / debug_tag / "manrope"
        font_dir.mkdir(parents=True, exist_ok=True)

        # 1. add valid broll
        r = run_cli(
            "--manifest",
            str(manifest),
            "add",
            "--type",
            "broll",
            "--path",
            str(broll_file),
            "--id",
            "family_relief_001",
            "--source",
            "pexels",
            "--source-url",
            "",
            "--license-name",
            "Pexels License",
            "--commercial-use-ok",
            "true",
            "--attribution-required",
            "false",
            "--tags",
            "family_relief",
            "emotional_support",
            "--topics",
            "decesos",
            "vida",
            "--sensitive-tone",
            "safe",
            "--duration-hint",
            "2.0",
        )
        check("add_valid_broll", r.returncode == 0 and manifest.exists(), r.stdout.strip())

        # 2. duplicate id => fail
        r = run_cli(
            "--manifest",
            str(manifest),
            "add",
            "--type",
            "broll",
            "--path",
            str(broll_file),
            "--id",
            "family_relief_001",
            "--source",
            "pexels",
            "--license-name",
            "Pexels License",
            "--commercial-use-ok",
            "true",
            "--attribution-required",
            "false",
            "--tags",
            "family_relief",
            "--topics",
            "decesos",
            "--sensitive-tone",
            "safe",
        )
        check("duplicate_id_fail", r.returncode != 0 and "duplicate_id" in r.stdout, r.stdout.strip())

        # 3. missing file => fail
        r = run_cli(
            "--manifest",
            str(manifest),
            "add",
            "--type",
            "broll",
            "--path",
            str(ROOT / "assets" / "broll" / debug_tag / "family_relief" / "missing.mp4"),
            "--id",
            "family_relief_002",
            "--source",
            "pexels",
            "--license-name",
            "Pexels License",
            "--commercial-use-ok",
            "true",
            "--attribution-required",
            "false",
            "--tags",
            "family_relief",
            "--topics",
            "decesos",
            "--sensitive-tone",
            "safe",
        )
        check("missing_file_fail", r.returncode != 0 and "missing_file" in r.stdout, r.stdout.strip())

        # 4. path traversal => fail
        r = run_cli(
            "--manifest",
            str(manifest),
            "add",
            "--type",
            "broll",
            "--path",
            "assets/broll/../../../../tmp/evil.mp4",
            "--id",
            "family_relief_003",
            "--source",
            "pexels",
            "--license-name",
            "Pexels License",
            "--commercial-use-ok",
            "true",
            "--attribution-required",
            "false",
            "--tags",
            "family_relief",
            "--topics",
            "decesos",
            "--sensitive-tone",
            "safe",
        )
        check("path_traversal_fail", r.returncode != 0 and "path_outside_assets" in r.stdout, r.stdout.strip())

        # 5. commercial_use_ok=false => add allowed, validate fails
        r = run_cli(
            "--manifest",
            str(manifest),
            "add",
            "--type",
            "sfx",
            "--path",
            str(sfx_file),
            "--id",
            "soft_chime_001",
            "--source",
            "mixkit",
            "--license-name",
            "Mixkit Free License",
            "--commercial-use-ok",
            "false",
            "--attribution-required",
            "false",
            "--tags",
            "soft_chime",
        )
        check("commercial_false_add_allowed", r.returncode == 0, r.stdout.strip())
        r = run_cli("--manifest", str(manifest), "validate")
        check("commercial_false_validate_invalid", r.returncode == 1 and "ASSET_LIBRARY_STATUS=INVALID" in r.stdout, r.stdout.strip())

        # 6. attribution_required=true preserved
        r = run_cli(
            "--manifest",
            str(manifest),
            "add",
            "--type",
            "sfx",
            "--path",
            str(sfx_file),
            "--id",
            "soft_chime_002",
            "--source",
            "freesound_cc_by",
            "--license-name",
            "CC BY",
            "--commercial-use-ok",
            "true",
            "--attribution-required",
            "true",
            "--tags",
            "soft_chime",
        )
        check("attribution_required_preserved", r.returncode == 0, r.stdout.strip())
        data = json.loads(manifest.read_text(encoding="utf-8"))
        attr_asset = next((a for a in data.get("assets", []) if a.get("id") == "soft_chime_002"), {})
        check("attribution_required_true", bool(attr_asset.get("attribution_required")), str(attr_asset))

        # 7. known source registry auto-added
        sources = dict(data.get("sources") or {})
        check("known_source_added", "pexels" in sources, str(sorted(sources.keys())))

        # 8. unknown source without license => fail
        r = run_cli(
            "--manifest",
            str(manifest),
            "add",
            "--type",
            "icon",
            "--path",
            str(icon_file),
            "--id",
            "family_icon_001",
            "--source",
            "unknown_source",
            "--license-name",
            "",
            "--commercial-use-ok",
            "true",
            "--attribution-required",
            "false",
            "--tags",
            "family",
        )
        check("unknown_source_without_license_fail", r.returncode != 0, r.stdout.strip())

        # 9. list command works
        r = run_cli("--manifest", str(manifest), "list", "--type", "broll")
        check("list_command_works", r.returncode == 0 and "id | type | path" in r.stdout, r.stdout.strip().splitlines()[0] if r.stdout else "")

        # 10. suggest command works
        r = run_cli("--manifest", str(manifest), "suggest")
        check("suggest_command_works", r.returncode == 0 and "Need:" in r.stdout and "broll:" in r.stdout, r.stdout.strip())

        # 11. validate empty manifest => PASS/EMPTY
        empty_manifest = tmp / "empty_manifest.json"
        write_json(empty_manifest, {"version": "1.0", "sources": {}, "assets": []})
        r = run_cli("--manifest", str(empty_manifest), "validate")
        check("validate_empty_pass", r.returncode == 0 and "ASSET_LIBRARY_STATUS=EMPTY" in r.stdout, r.stdout.strip())

        # 12. font missing fallback no rompe
        missing_font = ROOT / "assets" / "fonts" / debug_tag / "manrope" / "missing.ttf"
        r = run_cli(
            "--manifest",
            str(manifest),
            "add",
            "--type",
            "font",
            "--path",
            str(missing_font),
            "--id",
            "font_missing_001",
            "--source",
            "google_fonts_ofl",
            "--license-name",
            "SIL Open Font License",
            "--commercial-use-ok",
            "true",
            "--attribution-required",
            "false",
        )
        check("font_missing_fail", r.returncode != 0 and "missing_file" in r.stdout, r.stdout.strip())

        # 13. icon with missing license => fail
        r = run_cli(
            "--manifest",
            str(manifest),
            "add",
            "--type",
            "icon",
            "--path",
            str(icon_file),
            "--id",
            "family_icon_002",
            "--source",
            "lucide",
            "--license-name",
            "",
            "--commercial-use-ok",
            "true",
            "--attribution-required",
            "false",
            "--tags",
            "family",
        )
        check("icon_missing_license_fail", r.returncode != 0 and "license_missing" in r.stdout, r.stdout.strip())

        # 14. sfx valid with family tag
        r = run_cli(
            "--manifest",
            str(manifest),
            "add",
            "--type",
            "sfx",
            "--path",
            str(sfx_file),
            "--id",
            "soft_chime_003",
            "--source",
            "mixkit",
            "--license-name",
            "Mixkit Free License",
            "--commercial-use-ok",
            "true",
            "--attribution-required",
            "false",
            "--tags",
            "soft_chime",
        )
        check("sfx_valid_added", r.returncode == 0, r.stdout.strip())
        data = json.loads(manifest.read_text(encoding="utf-8"))
        sfx_asset = next((a for a in data.get("assets", []) if a.get("id") == "soft_chime_003"), {})
        check("sfx_family_tag_present", "soft_chime" in list(sfx_asset.get("tags") or []), str(sfx_asset))

        # cleanup debug files from repo tree
        for file_path in (broll_file, sfx_file, icon_file):
            if file_path.exists():
                file_path.unlink()
        for directory in (
            font_dir,
            font_dir.parent,
            font_dir.parent.parent,
            icon_dir,
            icon_dir.parent,
            icon_dir.parent.parent,
            sfx_dir,
            sfx_dir.parent,
            sfx_dir.parent.parent,
            sfx_dir.parent.parent.parent,
            broll_dir,
            broll_dir.parent,
            broll_dir.parent.parent,
        ):
            try:
                directory.rmdir()
            except OSError:
                pass

    print(f"[debug-asset-intake-pack] results={PASS} PASS / {FAIL} FAIL")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
