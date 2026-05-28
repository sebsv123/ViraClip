"""
VPI SFX Service v1.0 — Retention Editing System v4.0

Generates sound effects for retention editing:
  - dark_riser_combo : low + high riser for tension
  - magic_whoosh     : quick whoosh for transitions/contrast
  - deep_boom        : sub-bass hit for emphasis

All generated via FFmpeg (CPU-only, no external samples needed).
Repetition guard built into the plan layer (vpi_retention_editing_service).
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

# ── SFX generation ─────────────────────────────────────────────────────────────

_SAMPLE_RATE = 44100
_CHANNELS = 2
_AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac"}
_SFX_DIRS = (
    "assets/sfx",
    "assets/sounds",
    "assets/sounds/sfx",
    "assets/sounds/risers",
    "assets/sounds/booms",
    "assets/sounds/whooshes",
    "/app/assets/sfx",
    "/app/assets/sounds",
    "/app/assets/sounds/sfx",
    "/app/assets/sounds/risers",
    "/app/assets/sounds/booms",
    "/app/assets/sounds/whooshes",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _candidate_sfx_dirs() -> Iterable[Path]:
    root = _repo_root()
    for item in _SFX_DIRS:
        path = Path(item)
        yield path if path.is_absolute() else root / path


def classify_sfx_asset(path: Path) -> Optional[str]:
    name = path.stem.lower()
    if any(term in name for term in ("magic", "sparkle", "shimmer", "whoosh", "tick", "click", "glitch")):
        return "magic_whoosh"
    if any(term in name for term in ("boom", "deep", "hit", "impact", "sub")):
        return "deep_boom"
    if any(term in name for term in ("dark", "low", "bass", "rumble", "riser")):
        return "low_riser"
    if any(term in name for term in ("high", "bright", "tension", "rise")):
        return "high_riser"
    return None


def discover_sfx_assets() -> Dict[str, List[Path]]:
    assets: Dict[str, List[Path]] = {
        "low_riser": [],
        "high_riser": [],
        "magic_whoosh": [],
        "deep_boom": [],
    }
    seen: set[str] = set()
    for directory in _candidate_sfx_dirs():
        if not directory.exists() or not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in _AUDIO_EXTS:
                continue
            kind = classify_sfx_asset(path)
            if not kind:
                continue
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            assets[kind].append(path)
    logger.info(
        "[sfx-design] available low_risers=%d high_risers=%d whooshes=%d booms=%d",
        len(assets["low_riser"]),
        len(assets["high_riser"]),
        len(assets["magic_whoosh"]),
        len(assets["deep_boom"]),
    )
    return assets


def _asset_label(path: Optional[Path]) -> Optional[str]:
    return str(path) if path else None


def _deep_boom_guard_path(task_id: Optional[str]) -> Path:
    suffix = str(task_id or "global").replace("/", "_")
    return Path(os.environ.get("VIRACLIP_SFX_GUARD_DIR") or "/tmp") / f"viraclip_deep_boom_guard_{suffix}.txt"


def select_deep_boom_variant(
    assets: Dict[str, List[Path]],
    *,
    task_id: Optional[str] = None,
    used_assets: Optional[Iterable[str]] = None,
) -> tuple[Optional[Path], str, bool]:
    booms = list(assets.get("deep_boom") or [])
    if not booms:
        return None, "", False
    used = set(str(item) for item in (used_assets or []))
    guard_path = _deep_boom_guard_path(task_id)
    if guard_path.exists():
        try:
            used.update(line.strip() for line in guard_path.read_text(encoding="utf-8").splitlines() if line.strip())
        except Exception:
            pass
    selected = next((asset for asset in booms if str(asset) not in used), booms[0])
    repeated = str(selected) in used
    try:
        guard_path.write_text((guard_path.read_text(encoding="utf-8") if guard_path.exists() else "") + str(selected) + "\n", encoding="utf-8")
    except Exception:
        pass
    if repeated:
        logger.info("[sfx-design] repetition_guard asset=%s", selected)
    return selected, f"deep_boom_{booms.index(selected) + 1}", not repeated


def build_sfx_design_plan(
    *,
    hook_plan: Optional[Dict[str, Any]] = None,
    broll_events: Optional[List[Dict[str, Any]]] = None,
    transition_events: Optional[List[Dict[str, Any]]] = None,
    editorial_type: str = "",
    clip_duration_s: float = 0.0,
    task_id: Optional[str] = None,
    assets: Optional[Dict[str, List[Path]]] = None,
    used_deep_boom_assets: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    assets = assets or discover_sfx_assets()
    events: List[Dict[str, Any]] = []
    missing: List[str] = []
    hook_type = str((hook_plan or {}).get("hook_type") or "")
    strong_hook = hook_type not in {"", "weak_intro"} and int((hook_plan or {}).get("hook_first3_score") or 0) >= 5

    low = (assets.get("low_riser") or [None])[0]
    high = (assets.get("high_riser") or [None])[0]
    if strong_hook or editorial_type in {"risk_warning", "myth_debunk", "client_objection"}:
        if not low:
            missing.append("low_riser")
        if not high:
            missing.append("high_riser")
        if low or high:
            events.append({
                "event": "hook",
                "type": "dark_riser_combo",
                "start_s": 0.25,
                "duration_s": 0.9,
                "volume": 0.24,
                "low_riser_asset": _asset_label(low),
                "high_riser_asset": _asset_label(high),
                "dark_riser_combo_applied": True,
                "reason": "strong_hook_or_tension_shift",
            })
            logger.info("[sfx-design] applied event=hook type=dark_riser_combo low=%s high=%s", low, high)

    whoosh = (assets.get("magic_whoosh") or [None])[0]
    key_broll = [item for item in (broll_events or []) if item]
    if whoosh and (key_broll or editorial_type in {"myth_debunk", "client_objection", "actionable_advice"}):
        start = float((key_broll[0] or {}).get("start_s") or (3.2 if clip_duration_s >= 6 else 1.2))
        events.append({
            "event": "key_moment",
            "type": "magic_whoosh",
            "start_s": round(max(0.0, start), 2),
            "duration_s": 0.45,
            "volume": 0.20,
            "asset": _asset_label(whoosh),
            "reason": "caption_or_broll_reveal",
        })
        logger.info("[sfx-design] applied event=key_moment type=magic_whoosh asset=%s", whoosh)
    elif key_broll:
        missing.append("magic_whoosh")

    for transition in transition_events or []:
        hint = str((transition or {}).get("sfx_hint") or (transition or {}).get("transition_sfx_type") or "")
        transition_type = str((transition or {}).get("transition_type") or "")
        if not hint:
            continue
        if whoosh:
            events.append({
                "event": f"transition_{transition_type}",
                "type": "magic_whoosh",
                "start_s": round(float((transition or {}).get("start_time") or (transition or {}).get("start_s") or 0.5), 2),
                "duration_s": 0.35,
                "volume": 0.16,
                "asset": _asset_label(whoosh),
                "reason": f"transition_sfx:{transition_type}",
            })
            logger.info("[sfx-design] applied event=transition_%s type=magic_whoosh asset=%s", transition_type, whoosh)
            logger.info("[transition-sfx] applied=%s transition=%s", whoosh, transition_type)
        else:
            missing.append(hint)
            logger.info("[transition-sfx] missing=%s transition=%s", hint, transition_type)

    boom, variant_id, guard_ok = select_deep_boom_variant(
        assets,
        task_id=task_id,
        used_assets=used_deep_boom_assets,
    )
    impact_editorial = editorial_type in {"risk_warning", "emotional_protection", "myth_debunk"}
    if boom and impact_editorial:
        events.append({
            "event": "impact",
            "type": "deep_boom",
            "start_s": round(min(max(clip_duration_s * 0.45, 2.6), max(2.6, clip_duration_s - 0.8)), 2),
            "duration_s": 0.55,
            "volume": 0.18,
            "asset": _asset_label(boom),
            "deep_boom_asset": _asset_label(boom),
            "deep_boom_variant_id": variant_id,
            "deep_boom_repetition_guard": guard_ok,
            "reason": "impact_phrase_weight",
        })
        logger.info("[sfx-design] applied event=impact type=deep_boom asset=%s", boom)
    elif impact_editorial:
        missing.append("deep_boom")

    if missing:
        logger.info("[sfx-design] skipped reason=missing_asset_type types=%s", "|".join(sorted(set(missing))))
    return {
        "sfx_design_applied": bool(events),
        "sfx_design_events": events[:4],
        "sfx_design_missing_assets": sorted(set(missing)),
        "sfx_assets_available": {
            "low_risers": len(assets.get("low_riser") or []),
            "high_risers": len(assets.get("high_riser") or []),
            "whooshes": len(assets.get("magic_whoosh") or []),
            "booms": len(assets.get("deep_boom") or []),
        },
        "sfx_repetition_guard": {"task_id": task_id, "deep_boom_guarded": bool(events)},
    }


def _ffmpeg_sfx(
    filter_complex: str,
    duration_s: float,
    output_path: Path,
    *,
    volume: float = 0.25,
) -> bool:
    """Render a synthetic SFX via FFmpeg filter graph."""
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-filter_complex", filter_complex,
        "-t", f"{duration_s:.3f}",
        "-ac", str(_CHANNELS),
        "-ar", str(_SAMPLE_RATE),
        "-c:a", "pcm_s16le",
        str(output_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            logger.info("[sfx] rendered path=%s dur=%.2f vol=%.2f", output_path, duration_s, volume)
            return True
        logger.warning("[sfx] ffmpeg failed: %s", (result.stderr or "")[-300:])
    except Exception as exc:
        logger.warning("[sfx] exception: %s", exc)
    return False


def render_dark_riser_combo(
    output_dir: Path,
    *,
    duration_s: float = 0.8,
    volume: float = 0.35,
) -> Optional[Path]:
    """Render a dark riser combo: low rumble + high riser.

    Low riser: sine sweep 60→120 Hz over full duration.
    High riser: sine sweep 800→4000 Hz over full duration.
    Combined with noise floor for texture.
    """
    output_path = output_dir / f"sfx_dark_riser_combo_{int(duration_s * 1000)}ms.wav"
    if output_path.exists():
        logger.info("[sfx] cache hit %s", output_path)
        return output_path

    # Low riser: 60→120 Hz sine sweep
    # High riser: 800→4000 Hz sine sweep
    # Noise: white noise for texture
    filter_complex = (
        f"[0]aformat=sample_rates={_SAMPLE_RATE}:channel_layouts=stereo,volume={volume:.2f}[a];"
        f"sine=frequency=60:frequency2=120:duration={duration_s:.3f}[low];"
        f"sine=frequency=800:frequency2=4000:duration={duration_s:.3f}[high];"
        f"anoisesrc=d={duration_s:.3f}:c=pink:a=0.05[noise];"
        f"[low][high]amix=inputs=2:duration=first:weights=1 0.6[risers];"
        f"[risers][noise]amix=inputs=2:duration=first:weights=1 0.15[mixed];"
        f"[mixed]aformat=sample_rates={_SAMPLE_RATE}:channel_layouts=stereo,volume={volume:.2f}[out]"
    )
    # Use a dummy input to satisfy filter chain
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-t", f"{duration_s:.3f}",
        "-c:a", "pcm_s16le",
        str(output_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            logger.info("[sfx] dark_riser_combo rendered path=%s", output_path)
            return output_path
        logger.warning("[sfx] dark_riser_combo failed: %s", (result.stderr or "")[-300:])
    except Exception as exc:
        logger.warning("[sfx] dark_riser_combo exception: %s", exc)
    return None


def render_magic_whoosh(
    output_dir: Path,
    *,
    duration_s: float = 0.6,
    volume: float = 0.30,
) -> Optional[Path]:
    """Render a magic whoosh: quick frequency sweep with shimmer.

    Sine sweep 200→6000 Hz with exponential fade-in/out.
    """
    output_path = output_dir / f"sfx_magic_whoosh_{int(duration_s * 1000)}ms.wav"
    if output_path.exists():
        logger.info("[sfx] cache hit %s", output_path)
        return output_path

    # Sine sweep 200→6000 Hz with fade envelope
    filter_complex = (
        f"aformat=sample_rates={_SAMPLE_RATE}:channel_layouts=stereo,"
        f"sine=frequency=200:frequency2=6000:duration={duration_s:.3f},"
        f"afade=t=in:d={duration_s*0.15:.3f},"
        f"afade=t=out:st={duration_s*0.7:.3f}:d={duration_s*0.3:.3f},"
        f"volume={volume:.2f}[out]"
    )
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-t", f"{duration_s:.3f}",
        "-ac", str(_CHANNELS),
        "-ar", str(_SAMPLE_RATE),
        "-c:a", "pcm_s16le",
        str(output_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            logger.info("[sfx] magic_whoosh rendered path=%s", output_path)
            return output_path
        logger.warning("[sfx] magic_whoosh failed: %s", (result.stderr or "")[-300:])
    except Exception as exc:
        logger.warning("[sfx] magic_whoosh exception: %s", exc)
    return None


def render_deep_boom(
    output_dir: Path,
    *,
    duration_s: float = 0.5,
    volume: float = 0.25,
) -> Optional[Path]:
    """Render a deep boom: sub-bass hit with quick decay.

    Low sine 40→80 Hz with exponential decay.
    """
    output_path = output_dir / f"sfx_deep_boom_{int(duration_s * 1000)}ms.wav"
    if output_path.exists():
        logger.info("[sfx] cache hit %s", output_path)
        return output_path

    # Sub-bass hit: 40→80 Hz with fast decay
    filter_complex = (
        f"aformat=sample_rates={_SAMPLE_RATE}:channel_layouts=stereo,"
        f"sine=frequency=40:frequency2=80:duration={duration_s:.3f},"
        f"afade=t=out:st={duration_s*0.15:.3f}:d={duration_s*0.85:.3f},"
        f"volume={volume:.2f}[out]"
    )
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-t", f"{duration_s:.3f}",
        "-ac", str(_CHANNELS),
        "-ar", str(_SAMPLE_RATE),
        "-c:a", "pcm_s16le",
        str(output_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            logger.info("[sfx] deep_boom rendered path=%s", output_path)
            return output_path
        logger.warning("[sfx] deep_boom failed: %s", (result.stderr or "")[-300:])
    except Exception as exc:
        logger.warning("[sfx] deep_boom exception: %s", exc)
    return None


# ── SFX mixer ──────────────────────────────────────────────────────────────────

def mix_sfx_into_audio(
    video_path: Path,
    output_path: Path,
    sfx_events: List[Dict[str, Any]],
    sfx_dir: Path,
    *,
    master_volume: float = 0.25,
) -> Dict[str, Any]:
    """Mix SFX events into video audio track.

    Each sfx_event must have:
      - start_s: float  (when to place the SFX)
      - type: str       (dark_riser_combo | magic_whoosh | deep_boom)
      - volume: float   (0.0-1.0, optional, default 0.25)
      - duration_s: float (optional, default per-type)

    Returns dict with rendered status and warnings.
    """
    if not sfx_events:
        logger.info("[sfx-mix] no sfx events, copying audio")
        return {"rendered": False, "reason": "no_sfx_events", "warnings": []}

    # Ensure SFX directory exists
    sfx_dir.mkdir(parents=True, exist_ok=True)

    # Resolve all SFX files. Prefer discovered local assets; render CPU-local
    # fallbacks only for planned events that have no matching asset.
    sfx_inputs: List[tuple[Dict[str, Any], Path, float]] = []
    rendered_cache: Dict[str, Path] = {}
    for event in sfx_events:
        sfx_type = str(event.get("type", "magic_whoosh"))
        dur = float(event.get("duration_s", 0.0) or 0.0)
        vol = float(event.get("volume", 0.25) or 0.25)
        local_assets: List[Path] = []
        if event.get("asset") and Path(str(event["asset"])).exists():
            local_assets.append(Path(str(event["asset"])))
        if sfx_type == "dark_riser_combo":
            for key in ("low_riser_asset", "high_riser_asset"):
                value = event.get(key)
                if value and Path(str(value)).exists():
                    local_assets.append(Path(str(value)))
        if local_assets:
            weight = vol / max(1, len(local_assets))
            for asset in local_assets:
                sfx_inputs.append((event, asset, weight))
            continue
        if sfx_type in rendered_cache:
            sfx_inputs.append((event, rendered_cache[sfx_type], vol))
            continue
        if sfx_type == "dark_riser_combo":
            path = render_dark_riser_combo(sfx_dir, duration_s=dur or 0.8, volume=vol)
        elif sfx_type == "deep_boom":
            path = render_deep_boom(sfx_dir, duration_s=dur or 0.5, volume=vol)
        else:
            path = render_magic_whoosh(sfx_dir, duration_s=dur or 0.6, volume=vol)
        if path:
            rendered_cache[sfx_type] = path
            sfx_inputs.append((event, path, vol))

    if not sfx_inputs:
        logger.warning("[sfx-mix] no sfx could be rendered")
        return {"rendered": False, "reason": "no_sfx_rendered", "warnings": ["sfx_render_failed"]}

    # Build FFmpeg filter graph with delayed SFX inserts
    # Strategy: extract audio, apply adelay for each SFX, mix with original
    filter_parts: List[str] = []
    mix_inputs: List[str] = []

    # Original audio
    filter_parts.append("[0:a]acopy[a_orig]")
    mix_inputs.append("[a_orig]")

    for i, (event, _sfx_path, input_volume) in enumerate(sfx_inputs):
        start_ms = int(float(event.get("start_s", 0.0) or 0.0) * 1000)

        # Read SFX file, apply volume, delay, mix
        filter_parts.append(
            f"[{i + 1}:a]adelay={start_ms}|{start_ms},volume={input_volume:.2f}[sfx{i}]"
        )
        mix_inputs.append(f"[sfx{i}]")

    # Mix all together
    mix_str = "".join(mix_inputs)
    filter_parts.append(
        f"{mix_str}amix=inputs={len(mix_inputs)}:duration=first:dropout_transition=2[outa]"
    )

    filter_complex = ";".join(filter_parts)

    # Build command
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video_path),
    ]
    for _event, sfx_path, _input_volume in sfx_inputs:
        cmd.extend(["-i", str(sfx_path)])

    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", "[outa]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "160k",
        "-shortest",
        str(output_path),
    ])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            logger.info("[sfx-mix] rendered=true events=%d output=%s", len(sfx_events), output_path)
            return {
                "rendered": True,
                "output_path": str(output_path),
                "sfx_count": len(sfx_events),
                "sfx_types": sorted({str(event.get("type", "magic_whoosh")) for event in sfx_events}),
                "warnings": [],
            }
        reason = (result.stderr or "ffmpeg_failed")[-300:]
        logger.warning("[sfx-mix] failed reason=%s", reason)
        return {"rendered": False, "reason": reason, "warnings": ["sfx_mix_failed"]}
    except Exception as exc:
        logger.warning("[sfx-mix] exception: %s", exc)
        return {"rendered": False, "reason": str(exc), "warnings": ["sfx_mix_exception"]}


def apply_sfx_bed(
    input_path: Path,
    output_path: Path,
    *,
    hook_plan: Optional[Dict[str, Any]] = None,
    broll_events: Optional[List[Dict[str, Any]]] = None,
    transition_events: Optional[List[Dict[str, Any]]] = None,
    editorial_type: str = "",
    task_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Apply intentional local SFX if matching local assets exist.

    This v4 layer is conservative: missing libraries produce metadata and
    warnings instead of synthetic filler, so flat clips do not get false
    editing richness.
    """
    design = build_sfx_design_plan(
        hook_plan=hook_plan,
        broll_events=broll_events,
        transition_events=transition_events,
        editorial_type=editorial_type,
        task_id=task_id,
    )
    events = list(design.get("sfx_design_events") or [])
    if not events:
        warning = "sfx_missing_worker_assets" if design.get("sfx_design_missing_assets") else "no_sfx_moment"
        logger.info("[sfx-design] final_output_uses_sfx=false")
        return {
            "sfx_applied": False,
            "sfx_count": 0,
            "sfx_warning": warning,
            **design,
        }
    # The current mixer renders CPU-local approximations for event timing while
    # preserving discovered asset metadata for auditability.
    with tempfile.TemporaryDirectory(prefix="viraclip_sfx_") as tmp_dir:
        result = mix_sfx_into_audio(
            input_path,
            output_path,
            events,
            Path(tmp_dir),
        )
    applied = bool(result.get("rendered"))
    logger.info("[sfx-design] final_output_uses_sfx=%s", str(applied).lower())
    return {
        "sfx_applied": applied,
        "sfx_count": len(events) if applied else 0,
        "sfx_events": events,
        "sfx_warning": None if applied else result.get("reason", "sfx_mix_failed"),
        **design,
        **result,
    }
