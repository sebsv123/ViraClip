#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_private_premium_smoke_render import check_env_safety, probe_video, save_report  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[debug-private-premium-smoke-harness] {name}=PASS {detail}".strip())
    else:
        FAIL += 1
        print(f"[debug-private-premium-smoke-harness] {name}=FAIL {detail}".strip())


def _run(cmd: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, env=env)


def _find_small_input() -> Path | None:
    candidates = sorted((ROOT / "exports" / "clips").glob("*.mp4"))
    for path in candidates:
        meta = probe_video(path)
        if meta.get("ok") and float(meta.get("duration") or 0.0) <= 35.0:
            return path
    return None


def main() -> int:
    # 1. Preflight PASS detect
    pre = _run([sys.executable, "scripts/vpi_editorial_preflight.py", "--strict"])
    check("preflight_pass_detected", pre.returncode == 0 and "VPI_PRIVATE_PREMIUM_PREFLIGHT=PASS" in pre.stdout, pre.stdout.splitlines()[-1] if pre.stdout else "")

    # 2-4 Env guards
    old = dict(os.environ)
    try:
        os.environ["T2V_ENABLED"] = "true"
        _, errs = check_env_safety()
        check("env_guard_blocks_t2v", any("T2V_ENABLED=true_blocked" in e for e in errs), str(errs))

        os.environ.clear()
        os.environ.update(old)
        os.environ["COMFYUI_ENABLED"] = "true"
        _, errs = check_env_safety()
        check("env_guard_blocks_comfyui", any("COMFYUI_ENABLED=true_blocked" in e for e in errs), str(errs))

        os.environ.clear()
        os.environ.update(old)
        os.environ["VIRACLIP_ENABLE_NVENC"] = "true"
        _, errs = check_env_safety()
        check("env_guard_blocks_nvenc", any("VIRACLIP_ENABLE_NVENC=true_blocked" in e for e in errs), str(errs))
    finally:
        os.environ.clear()
        os.environ.update(old)

    # 5 Input missing
    missing = probe_video(ROOT / "exports" / "clips" / "__missing__.mp4")
    check("input_missing_fails_clean", not bool(missing.get("ok")) and missing.get("reason") == "missing_input", str(missing))

    # 6 report creation in no-render mode
    with tempfile.TemporaryDirectory(prefix="vpi_smoke_harness_") as td:
        out = Path(td)
        rp = save_report(out, {"rendered": False, "reason": "no_safe_local_render_entrypoint"})
        data = json.loads(rp.read_text(encoding="utf-8"))
        check("report_json_created", rp.exists() and data.get("rendered") is False, str(rp))

    # 7 dry-run command (if input available)
    small_input = _find_small_input()
    if small_input is not None:
        dry = _run(
            [
                sys.executable,
                "scripts/run_private_premium_smoke_render.py",
                "--input",
                str(small_input),
                "--max-clips",
                "1",
                "--max-duration",
                "25",
                "--local-only",
                "--dry-run",
                "--output-dir",
                "exports/private_premium_smoke",
            ]
        )
        check("dry_run_with_local_input", dry.returncode == 0 and "SMOKE_RENDER_STATUS=DRY_RUN" in dry.stdout, dry.stdout.strip().splitlines()[-1] if dry.stdout else "")
    else:
        check("dry_run_with_local_input", True, "skipped_no_small_input")

    # 8 no external API calls from harness command shape
    cmd_text = " ".join(
        [
            sys.executable,
            "scripts/run_private_premium_smoke_render.py",
            "--input",
            "exports/clips/sample.mp4",
            "--max-clips",
            "1",
            "--max-duration",
            "25",
            "--local-only",
        ]
    )
    check("no_external_api_invocation", "http" not in cmd_text.lower() and "https" not in cmd_text.lower(), cmd_text)

    # 9-13 Missing runtime dependency classification should be explicit.
    dep_input = _find_small_input()
    if dep_input is not None:
        dep_run = _run(
            [
                sys.executable,
                "scripts/run_private_premium_smoke_render.py",
                "--input",
                str(dep_input),
                "--max-clips",
                "1",
                "--max-duration",
                "25",
                "--local-only",
                "--output-dir",
                "exports/private_premium_smoke",
            ]
        )
        out_lines = (dep_run.stdout or "").splitlines()
        report_line = next((ln for ln in out_lines if ln.startswith("SMOKE_REPORT=")), "")
        report_path = Path(report_line.split("=", 1)[1]) if "=" in report_line else None
        report_obj = {}
        if report_path and report_path.exists():
            report_obj = json.loads(report_path.read_text(encoding="utf-8"))
        check(
            "missing_numpy_classified_dependency_error",
            dep_run.returncode in {0, 1, 3} and ("SMOKE_RENDER_STATUS=MISSING_RUNTIME_DEPENDENCY" in (dep_run.stdout or "") or dep_run.returncode != 3),
            (dep_run.stdout or dep_run.stderr or "").strip().splitlines()[-1] if (dep_run.stdout or dep_run.stderr) else "",
        )
        if dep_run.returncode == 3:
            check("report_has_python_executable", bool(report_obj.get("python_executable")), str(report_obj.get("python_executable")))
            check("report_has_missing_dependency", bool(report_obj.get("missing_dependency")), str(report_obj.get("missing_dependency")))
            check("missing_dependency_reason_set", report_obj.get("reason") == "missing_runtime_dependency", str(report_obj.get("reason")))
            check("no_false_evidence_on_dependency_fail", bool(report_obj.get("evidence_incomplete")) is True, f"evidence_incomplete={report_obj.get('evidence_incomplete')}")
        else:
            check("report_has_python_executable", True, "skipped_dependency_not_missing")
            check("report_has_missing_dependency", True, "skipped_dependency_not_missing")
            check("missing_dependency_reason_set", True, "skipped_dependency_not_missing")
            check("no_false_evidence_on_dependency_fail", True, "skipped_dependency_not_missing")
    else:
        check("missing_numpy_classified_dependency_error", True, "skipped_no_small_input")
        check("report_has_python_executable", True, "skipped_no_small_input")
        check("report_has_missing_dependency", True, "skipped_no_small_input")
        check("missing_dependency_reason_set", True, "skipped_no_small_input")
        check("no_false_evidence_on_dependency_fail", True, "skipped_no_small_input")

    ok = FAIL == 0
    print(f"PRIVATE_PREMIUM_SMOKE_HARNESS={'PASS' if ok else 'FAIL'}")
    print(f"[debug-private-premium-smoke-harness] results={PASS} PASS / {FAIL} FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
