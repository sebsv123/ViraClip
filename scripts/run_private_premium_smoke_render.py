#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


PREFLIGHT_COMMANDS: List[List[str]] = [
    [sys.executable, "scripts/vpi_asset_intake.py", "validate"],
    [sys.executable, "scripts/debug_asset_runtime_selection.py"],
    [sys.executable, "scripts/debug_bgm_manifest_runtime.py"],
    [sys.executable, "scripts/vpi_editorial_preflight.py", "--strict"],
]

DANGEROUS_ENV_TRUE = {
    "T2V_ENABLED",
    "COMFYUI_ENABLED",
    "VIRACLIP_ENABLE_NVENC",
    "VIRACLIP_ENABLE_TORCH_CUDA",
}
DANGEROUS_ENV_VALUES = {
    "WHISPER_DEVICE": {"cuda"},
}
ALLOWED_EXTS = {".mp4", ".mov", ".webm"}


def _strtobool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def run_command(cmd: List[str], *, cwd: Path = ROOT) -> Tuple[int, str]:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    out = ((result.stdout or "") + ("\n" + result.stderr if result.stderr else "")).strip()
    return result.returncode, out


def run_required_preflight() -> Tuple[bool, List[Dict[str, Any]]]:
    results: List[Dict[str, Any]] = []
    ok = True
    for cmd in PREFLIGHT_COMMANDS:
        code, out = run_command(cmd)
        item = {
            "cmd": " ".join(cmd),
            "returncode": code,
            "ok": code == 0,
            "output_tail": "\n".join(out.splitlines()[-25:]),
        }
        results.append(item)
        if code != 0:
            ok = False
            break
    return ok, results


def check_env_safety() -> Tuple[List[str], List[str]]:
    warnings: List[str] = []
    errors: List[str] = []
    for key in sorted(DANGEROUS_ENV_TRUE):
        raw = os.environ.get(key)
        if raw is None:
            warnings.append(f"{key}=unset")
            continue
        if _strtobool(raw):
            errors.append(f"{key}=true_blocked")
    for key, blocked_values in DANGEROUS_ENV_VALUES.items():
        raw = os.environ.get(key)
        if raw is None:
            warnings.append(f"{key}=unset")
            continue
        if raw.strip().lower() in blocked_values:
            errors.append(f"{key}={raw}_blocked")
    if os.environ.get("VIRACLIP_BETA_CLEAN") is None:
        warnings.append("VIRACLIP_BETA_CLEAN=unset")
    return warnings, errors


def probe_video(path: Path) -> Dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {"ok": False, "reason": "missing_input"}
    if path.suffix.lower() not in ALLOWED_EXTS:
        return {"ok": False, "reason": "invalid_extension"}
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(path),
    ]
    code, out = run_command(cmd)
    if code != 0:
        return {"ok": False, "reason": "ffprobe_failed", "stderr": out[-500:]}
    try:
        payload = json.loads(out or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "reason": "ffprobe_json_invalid"}
    duration = float((payload.get("format") or {}).get("duration") or 0.0)
    has_video = any(str(s.get("codec_type")) == "video" for s in payload.get("streams") or [])
    return {"ok": bool(has_video and duration > 0), "duration": duration, "payload": payload}


def timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    mm = total // 60
    ss = total % 60
    return f"{mm:02d}:{ss:02d}"


def extract_premium_evidence(clip: Dict[str, Any]) -> Dict[str, Any]:
    music = dict(clip.get("music") or {})
    sfx = dict(clip.get("sfx") or {})
    broll_items = list(clip.get("editorial_broll") or [])
    caption_overlay_actions = list(((clip.get("editing_plan") or {}).get("caption_overlay_pack") or {}).get("caption_overlay_actions") or [])
    font_registry = dict(((clip.get("editing_plan") or {}).get("caption_overlay_pack") or {}).get("font_registry") or {})
    final_qc = dict(clip.get("final_qc") or {})
    fake_flags = [w for w in (final_qc.get("warnings") or []) if "fake_premium" in str(w)]

    broll_asset_id = ""
    broll_used = False
    if broll_items:
        for item in broll_items:
            if bool(item.get("broll_asset_applied_match")) or bool(item.get("broll_final_verified")):
                broll_used = True
                broll_asset_id = str(item.get("asset_id") or item.get("broll_asset_id") or "")
                break

    sfx_used = bool(sfx.get("sfx_applied") and sfx.get("sfx_asset_applied_match"))
    sfx_asset_id = str(sfx.get("sfx_asset_id") or "")

    bgm_used = bool(music.get("music_applied"))
    bgm_asset_id = str(music.get("bgm_asset_id") or "")
    bgm_manifest_verified = bool(music.get("bgm_manifest_verified"))

    icon_used = bool("icon" in caption_overlay_actions)
    icon_asset_id = str((((clip.get("editing_plan") or {}).get("caption_overlay_pack") or {}).get("caption_icon") or {}).get("asset_id") or "")
    font_used = bool(font_registry.get("selected_caption_font"))
    font_asset_id = str(font_registry.get("selected_caption_font") or "")

    return {
        "broll_used": broll_used,
        "broll_asset_id": broll_asset_id,
        "sfx_used": sfx_used,
        "sfx_asset_id": sfx_asset_id,
        "bgm_used": bgm_used,
        "bgm_asset_id": bgm_asset_id,
        "bgm_manifest_verified": bgm_manifest_verified,
        "icon_used": icon_used,
        "icon_asset_id": icon_asset_id,
        "font_used": font_used,
        "font_asset_id": font_asset_id,
        "final_qc_status": str(clip.get("final_qc_status") or ""),
        "fake_premium_flags": fake_flags,
        "do_not_upload": str(clip.get("final_private_premium_status") or "") == "DO_NOT_UPLOAD",
    }


async def render_one_clip(
    *,
    input_path: Path,
    max_duration: int,
    include_broll: bool,
) -> Dict[str, Any]:
    from src.services.video_service import VideoService

    probe = probe_video(input_path)
    if not probe.get("ok"):
        return {"rendered": False, "reason": f"invalid_input:{probe.get('reason')}", "errors": [probe.get("reason")]}
    duration = float(probe.get("duration") or 0.0)
    clip_len = min(float(max_duration), duration)
    if clip_len <= 0.0:
        return {"rendered": False, "reason": "invalid_duration", "errors": ["invalid_duration"]}

    segment = {
        "start_time": "00:00",
        "end_time": timestamp(clip_len),
        "text": "esto mucha gente no lo sabe sobre el seguro de salud y la tranquilidad familiar",
        "relevance_score": 0.8,
        "reasoning": "smoke_local_controlled",
        "virality_score": 55,
        "hook_score": 13,
        "engagement_score": 14,
        "value_score": 14,
        "shareability_score": 14,
        "hook_type": "risk_warning",
        "editorial_type": "salud",
        "matched_patterns": ["salud", "familia"],
        "vpi_score": 0.72,
        "vpi_reason": "smoke_harness_controlled_segment",
    }

    clips = await VideoService.create_video_clips_parallel(
        video_path=input_path,
        segments=[segment],
        task_id=f"smoke_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
        include_broll=include_broll,
        add_subtitles=True,
        max_concurrent=1,
    )
    if not clips:
        return {"rendered": False, "reason": "no_clip_rendered", "errors": ["no_clip_rendered"]}
    clip = clips[0]
    out_path = Path(str(clip.get("path") or ""))
    output_exists = out_path.exists() and out_path.is_file()
    output_size = int(out_path.stat().st_size) if output_exists else 0
    out_probe = probe_video(out_path) if output_exists else {"ok": False, "reason": "missing_output"}
    evidence = extract_premium_evidence(clip)
    return {
        "rendered": bool(output_exists and out_probe.get("ok")),
        "reason": "ok" if output_exists else "missing_output",
        "clip": clip,
        "output_path": str(out_path),
        "output_exists": output_exists,
        "output_size_bytes": output_size,
        "ffprobe_readable": bool(out_probe.get("ok")),
        "output_duration": float(out_probe.get("duration") or 0.0),
        "evidence": evidence,
        "errors": [] if output_exists else ["missing_output"],
    }


def save_report(output_dir: Path, report: Dict[str, Any]) -> Path:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        output_dir = Path("/tmp/viraclip_smoke_reports")
        output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_path = output_dir / f"{stamp}_smoke_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report_path


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one controlled private premium smoke render.")
    parser.add_argument("--input", required=True, help="Local video input path.")
    parser.add_argument("--max-clips", type=int, default=1)
    parser.add_argument("--max-duration", type=int, default=25)
    parser.add_argument("--local-only", action="store_true")
    parser.add_argument("--output-dir", default="exports/private_premium_smoke")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    os.environ.setdefault("VIRACLIP_BETA_CLEAN", "true")
    os.environ.setdefault("T2V_ENABLED", "false")
    os.environ.setdefault("COMFYUI_ENABLED", "false")
    os.environ.setdefault("VIRACLIP_ENABLE_NVENC", "false")
    os.environ.setdefault("VIRACLIP_ENABLE_TORCH_CUDA", "false")
    os.environ.setdefault("WHISPER_DEVICE", "cpu")
    os.environ.setdefault("BROLL_ENABLED", "false")

    output_dir = Path(args.output_dir)
    input_path = Path(args.input)
    warnings: List[str] = []
    errors: List[str] = []

    preflight_ok, preflight_steps = run_required_preflight()
    if not preflight_ok:
        errors.append("preflight_failed")

    env_warnings, env_errors = check_env_safety()
    warnings.extend(env_warnings)
    errors.extend(env_errors)

    if args.max_clips != 1:
        errors.append("max_clips_must_be_1")
    if args.max_duration > 25:
        errors.append("max_duration_exceeds_25")
    if not args.local_only:
        errors.append("local_only_required")

    input_probe = probe_video(input_path)
    if not input_probe.get("ok"):
        errors.append(f"input_invalid:{input_probe.get('reason')}")
    elif float(input_probe.get("duration") or 0.0) > 60.0 and args.max_duration > 25:
        errors.append("input_too_long_without_limit")

    report: Dict[str, Any] = {
        "rendered": False,
        "input_path": str(input_path),
        "output_path": "",
        "output_exists": False,
        "output_size_bytes": 0,
        "ffprobe_readable": False,
        "output_duration": 0.0,
        "asset_library_status": "",
        "broll_used": False,
        "broll_asset_id": "",
        "sfx_used": False,
        "sfx_asset_id": "",
        "bgm_used": False,
        "bgm_asset_id": "",
        "bgm_manifest_verified": False,
        "icon_used": False,
        "icon_asset_id": "",
        "font_used": False,
        "font_asset_id": "",
        "final_qc_status": "",
        "fake_premium_flags": [],
        "do_not_upload": False,
        "evidence_incomplete": True,
        "warnings": warnings,
        "errors": errors,
        "preflight_steps": preflight_steps,
    }

    for step in preflight_steps:
        tail = str(step.get("output_tail") or "")
        for line in tail.splitlines():
            if line.startswith("ASSET_LIBRARY_STATUS="):
                report["asset_library_status"] = line.split("=", 1)[1].strip()

    if errors:
        report["reason"] = "guard_blocked"
        report_path = save_report(output_dir, report)
        print(f"SMOKE_RENDER_STATUS=BLOCKED")
        print(f"SMOKE_REPORT={report_path}")
        return 2

    if args.dry_run:
        report["reason"] = "dry_run"
        report_path = save_report(output_dir, report)
        print("SMOKE_RENDER_STATUS=DRY_RUN")
        print(f"SMOKE_REPORT={report_path}")
        return 0

    try:
        render_result = asyncio.run(
            render_one_clip(
                input_path=input_path,
                max_duration=max(1, min(int(args.max_duration), 25)),
                include_broll=True,
            )
        )
    except Exception as exc:
        _exc_txt = str(exc)
        _reason = "render_exception"
        if "No module named 'yt_dlp'" in _exc_txt or "No module named \"yt_dlp\"" in _exc_txt:
            _reason = "no_safe_local_render_entrypoint"
        render_result = {"rendered": False, "reason": _reason, "errors": [_exc_txt]}

    if render_result.get("rendered"):
        report["rendered"] = True
        report["output_path"] = str(render_result.get("output_path") or "")
        report["output_exists"] = bool(render_result.get("output_exists"))
        report["output_size_bytes"] = int(render_result.get("output_size_bytes") or 0)
        report["ffprobe_readable"] = bool(render_result.get("ffprobe_readable"))
        report["output_duration"] = float(render_result.get("output_duration") or 0.0)
        evidence = dict(render_result.get("evidence") or {})
        report.update(evidence)
        report["evidence_incomplete"] = False
    else:
        report["errors"].extend(list(render_result.get("errors") or []))
        report["reason"] = str(render_result.get("reason") or "no_safe_local_render_entrypoint")
        if report["reason"] == "no_safe_local_render_entrypoint":
            report_path = save_report(output_dir, report)
            print("SMOKE_RENDER_STATUS=NO_SAFE_ENTRYPOINT")
            print(f"SMOKE_REPORT={report_path}")
            return 2

    report_path = save_report(output_dir, report)
    if report.get("rendered"):
        print("SMOKE_RENDER_STATUS=PASS")
        print(f"SMOKE_REPORT={report_path}")
        print(f"SMOKE_OUTPUT={report.get('output_path')}")
        return 0
    print("SMOKE_RENDER_STATUS=FAIL")
    print(f"SMOKE_REPORT={report_path}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
