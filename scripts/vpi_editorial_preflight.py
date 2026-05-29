#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "editorial_eval"
MD_REPORT = REPORT_DIR / "preflight_latest.md"
JSON_REPORT = REPORT_DIR / "preflight_latest.json"

PY_COMPILE_FILES = [
    "backend/src/services/video_service.py",
    "backend/src/services/task_service.py",
    "backend/src/services/vpi_editorial_fluency_service.py",
    "backend/src/services/vpi_retention_editing_service.py",
    "backend/src/services/vpi_hook_engine.py",
    "backend/src/services/vpi_silence_editor.py",
    "backend/src/services/vpi_publishable_gate.py",
    "backend/src/services/vpi_visual_effects_service.py",
    "backend/src/services/vpi_transition_engine.py",
    "backend/src/services/vpi_sfx_service.py",
    "backend/src/services/vpi_broll_intent.py",
    "scripts/evaluate_vpi_editorial_offline.py",
    "scripts/debug_editorial_runtime_integration.py",
    "scripts/debug_retention_editing_system.py",
    "scripts/debug_premium_runtime_contract.py",
    "scripts/debug_motion_pack.py",
    "scripts/debug_caption_overlay_pack.py",
    "scripts/debug_sfx_retention_pack.py",
    "scripts/debug_cinematic_finish_pack.py",
    "scripts/debug_shot_rhythm_pack.py",
    "scripts/debug_broll_editorial_pack.py",
    "scripts/debug_asset_library_pack.py",
    "scripts/debug_asset_intake_pack.py",
    "scripts/debug_final_qc_pack.py",
    "scripts/debug_composition_pack.py",
    "scripts/debug_composition_runtime_integration.py",
    "scripts/vpi_editorial_preflight.py",
]


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run VPI editorial offline preflight without rendering video.")
    parser.add_argument("--strict", action="store_true", help="Fail if any preflight step fails. Enabled by default for compatibility.")
    parser.add_argument("--json-only", action="store_true", help="Print only JSON summary to stdout.")
    parser.add_argument("--skip-pycompile", action="store_true", help="Skip Python syntax compile step.")
    return parser.parse_args(argv)


def run_step(name: str, cmd: List[str]) -> Dict[str, Any]:
    env = os.environ.copy()
    if name == "py_compile":
        env["PYTHONPYCACHEPREFIX"] = "/tmp/viraclip_pycache_check"
    result = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    output = ((result.stdout or "") + ("\n" + result.stderr if result.stderr else "")).strip()
    return {
        "name": name,
        "cmd": cmd,
        "returncode": result.returncode,
        "status": "PASS" if result.returncode == 0 else "FAIL",
        "output_tail": "\n".join(output.splitlines()[-40:]),
    }


def build_pycompile_step() -> List[str]:
    return [
        "python",
        "-m",
        "py_compile",
        *PY_COMPILE_FILES,
    ]


def write_reports(payload: Dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# VPI Editorial Preflight",
        "",
        f"- Generated: `{payload['generated_at']}`",
        f"- Status: `{payload['status']}`",
        f"- Ready for render: `{str(payload['ready_for_render']).lower()}`",
        "",
        "## Steps",
        "",
    ]
    for step in payload["steps"]:
        lines.append(f"- `{step['name']}`: `{step['status']}` (`returncode={step['returncode']}`)")
    lines.extend(["", "## Output Tails", ""])
    for step in payload["steps"]:
        lines.append(f"### {step['name']}")
        lines.append("")
        lines.append("```text")
        lines.append(step.get("output_tail") or "")
        lines.append("```")
        lines.append("")
    MD_REPORT.write_text("\n".join(lines), encoding="utf-8")


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    python = sys.executable or "python"

    steps = [
        ("offline_editorial_eval", [python, "scripts/evaluate_vpi_editorial_offline.py", "--strict"]),
        ("composition_pack", [python, "scripts/debug_composition_pack.py"]),
        ("composition_runtime_integration", [python, "scripts/debug_composition_runtime_integration.py"]),
        ("motion_pack", [python, "scripts/debug_motion_pack.py"]),
        ("caption_overlay_pack", [python, "scripts/debug_caption_overlay_pack.py"]),
        ("sfx_retention_pack", [python, "scripts/debug_sfx_retention_pack.py"]),
        ("cinematic_finish_pack", [python, "scripts/debug_cinematic_finish_pack.py"]),
        ("shot_rhythm_pack", [python, "scripts/debug_shot_rhythm_pack.py"]),
        ("broll_editorial_pack", [python, "scripts/debug_broll_editorial_pack.py"]),
        ("asset_library_pack", [python, "scripts/debug_asset_library_pack.py"]),
        ("asset_intake_pack", [python, "scripts/debug_asset_intake_pack.py"]),
        ("final_qc_pack", [python, "scripts/debug_final_qc_pack.py"]),
        ("editorial_runtime_integration", [python, "scripts/debug_editorial_runtime_integration.py"]),
        ("retention_editing_system", [python, "scripts/debug_retention_editing_system.py"]),
        ("premium_runtime_contract", [python, "scripts/debug_premium_runtime_contract.py"]),
    ]
    if not args.skip_pycompile:
        steps.append(("py_compile", build_pycompile_step()))

    results: List[Dict[str, Any]] = []
    for name, cmd in steps:
        step_result = run_step(name, cmd)
        results.append(step_result)
        if not args.json_only:
            print(f"[preflight] {name}={step_result['status']} returncode={step_result['returncode']}")
        if step_result["returncode"] != 0:
            break

    passed = all(step["returncode"] == 0 for step in results) and len(results) == len(steps)
    asset_library_status = "UNKNOWN"
    for step in results:
        if step["name"] == "asset_library_pack":
            for line in (step.get("output_tail") or "").splitlines():
                if line.startswith("ASSET_LIBRARY_STATUS="):
                    asset_library_status = line.split("=", 1)[1].strip() or "UNKNOWN"
                    break
            break
    if asset_library_status == "INVALID":
        passed = False
    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "status": "PASS" if passed else "FAIL",
        "ready_for_render": bool(passed),
        "ready_for_private_premium_render": bool(passed),
        "composition_runtime_connected": bool(
            passed and any(step["name"] == "composition_runtime_integration" and step["returncode"] == 0 for step in results)
        ),
        "broll_editorial_pack": bool(
            passed and any(step["name"] == "broll_editorial_pack" and step["returncode"] == 0 for step in results)
        ),
        "sfx_retention_pack": bool(
            passed and any(step["name"] == "sfx_retention_pack" and step["returncode"] == 0 for step in results)
        ),
        "cinematic_finish_pack": bool(
            passed and any(step["name"] == "cinematic_finish_pack" and step["returncode"] == 0 for step in results)
        ),
        "shot_rhythm_pack": bool(
            passed and any(step["name"] == "shot_rhythm_pack" and step["returncode"] == 0 for step in results)
        ),
        "asset_library_status": asset_library_status,
        "asset_intake_pack": bool(
            passed and any(step["name"] == "asset_intake_pack" and step["returncode"] == 0 for step in results)
        ),
        "final_qc_pack": bool(
            passed and any(step["name"] == "final_qc_pack" and step["returncode"] == 0 for step in results)
        ),
        "pycompile_skipped": bool(args.skip_pycompile),
        "steps": results,
        "reports": {
            "md": str(MD_REPORT.relative_to(ROOT)),
            "json": str(JSON_REPORT.relative_to(ROOT)),
        },
    }
    write_reports(payload)

    if args.json_only:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(f"VPI_PRIVATE_PREMIUM_PREFLIGHT={'PASS' if passed else 'FAIL'}")
        print(f"READY_FOR_PRIVATE_PREMIUM_RENDER={'true' if passed else 'false'}")
        print(f"COMPOSITION_RUNTIME_CONNECTED={'true' if passed else 'false'}")
        print(f"BROLL_EDITORIAL_PACK={'true' if payload.get('broll_editorial_pack') else 'false'}")
        print(f"SFX_RETENTION_PACK={'true' if payload.get('sfx_retention_pack') else 'false'}")
        print(f"CINEMATIC_FINISH_PACK={'true' if payload.get('cinematic_finish_pack') else 'false'}")
        print(f"SHOT_RHYTHM_PACK={'true' if payload.get('shot_rhythm_pack') else 'false'}")
        print(f"ASSET_LIBRARY_STATUS={payload.get('asset_library_status')}")
        print(f"ASSET_INTAKE_PACK={'true' if payload.get('asset_intake_pack') else 'false'}")
        print(f"FINAL_QC_PACK={'true' if payload.get('final_qc_pack') else 'false'}")
        print(f"VPI_EDITORIAL_PREFLIGHT={'PASS' if passed else 'FAIL'}")
        print(f"READY_FOR_RENDER={'true' if passed else 'false'}")
        print(f"REPORT_MD={payload['reports']['md']}")
        print(f"REPORT_JSON={payload['reports']['json']}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
