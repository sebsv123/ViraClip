"""Internal editorial visual fallback cards for VPI clips.

This route is intentionally local-only: no stock providers, no generated media,
and no dependency on user-supplied B-roll. It is a restrained visual support
when a strong B-roll intent exists but compatible local assets are unavailable.
"""
from __future__ import annotations

import hashlib
import logging
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


ALLOWED_VISUAL_FALLBACK_INTENTS = {
    "travel_assistance",
    "student_abroad",
    "coverage_explanation",
    "advisor_explanation",
    "risk_warning",
    "emotional_protection",
}

ASSET_MISSING_REASONS = {
    "no_local_assets_in_family",
    "no_compatible_local_asset",
    "no_assets",
    "no_local_asset_match",
    "asset_missing",
}

INTENT_CARD_COPY: Dict[str, Tuple[str, str]] = {
    "travel_assistance": ("ANTES DE VIAJAR", "passport"),
    "student_abroad": ("SEGURO PARA TRAMITE", "document"),
    "coverage_explanation": ("REVISA COBERTURAS", "document"),
    "advisor_explanation": ("ANTES DE CONTRATAR", "checklist"),
    "risk_warning": ("POR SI ACASO", "shield"),
    "emotional_protection": ("PROTECCION", "shield"),
}

ICON_CANDIDATES: Dict[str, Tuple[str, ...]] = {
    "passport": (
        "assets/icons/vpi/travel_passport.svg",
        "assets/icons/vpi/travel_suitcase.svg",
        "assets/icons/vpi/folder_paperwork.svg",
        "assets/icons/document/file-search-corner.svg",
    ),
    "document": (
        "assets/icons/vpi/signature_form.svg",
        "assets/icons/vpi/folder_paperwork.svg",
        "assets/icons/document/file-search-corner.svg",
    ),
    "checklist": (
        "assets/icons/vpi/checklist_advice.svg",
        "assets/icons/checklist/check-check.svg",
    ),
    "shield": (
        "assets/icons/vpi/shield_check.svg",
        "assets/icons/shield/shield-plus.svg",
    ),
    "heart": (
        "assets/icons/vpi/heart_shield.svg",
        "assets/icons/heart/heart-pulse.svg",
    ),
}


# OUTPUT-VISUALS-16 — single principal icon composited inside the card.
# Card box spans x=96..984, y=270..510 on the 1080x1920 output.
ICON_RENDER_PX = 150          # within the 110-180 px perceptible range
ICON_POS_X = 792              # right side of the card, clear of the left-aligned text
ICON_POS_Y = 315              # vertically centred inside the 240px-tall card
ICON_POSITION_LABEL = "card_right"


def _icon_abs_path(icon: str) -> str:
    """Resolve an icon reference (possibly repo-relative) to an existing absolute path."""
    if not icon:
        return ""
    p = Path(icon)
    if p.is_absolute():
        return str(p) if p.exists() else ""
    base = Path(__file__).resolve().parents[2]  # services -> src -> repo root
    cand = base / icon
    if cand.exists():
        return str(cand)
    if p.exists():
        return str(p.resolve())
    return ""


def _svg_looks_renderable(path: str) -> bool:
    """Cheap structural check so a malformed SVG fails fast instead of stalling ffmpeg."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            head = fh.read(2048).lower()
    except Exception:
        return False
    return "<svg" in head and ("viewbox" in head or "width=" in head or "height=" in head)


@dataclass(frozen=True)
class VisualFallbackPlan:
    planned: bool
    intent: str = ""
    text: str = ""
    icon: str = ""
    start_s: float = 0.0
    end_s: float = 0.0
    duration_s: float = 0.0
    skip_reason: str = ""
    confidence: float = 0.0
    icon_family: str = ""
    icon_match_reason: str = ""
    icon_match_confidence: float = 0.0
    icon_candidates: Tuple[str, ...] = ()
    fallback_type: str = "INTERNAL_EDITORIAL_VISUAL_CARD"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "visual_fallback_planned": self.planned,
            "visual_fallback_type": self.fallback_type if self.planned else "",
            "visual_fallback_intent": self.intent,
            "visual_fallback_text": self.text,
            "visual_fallback_icon": self.icon,
            "visual_fallback_start_s": round(self.start_s, 2),
            "visual_fallback_end_s": round(self.end_s, 2),
            "visual_fallback_duration_s": round(self.duration_s, 2),
            "visual_fallback_skip_reason": self.skip_reason,
            "visual_fallback_confidence": round(self.confidence, 3),
            "visual_fallback_icon_family": self.icon_family,
            "visual_fallback_icon_match_reason": self.icon_match_reason,
            "visual_fallback_icon_match_confidence": round(self.icon_match_confidence, 3),
            "visual_fallback_icon_candidates": list(self.icon_candidates),
        }


def _normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")


def _contains_missing_asset_reason(reason: str) -> bool:
    parts = {part.strip() for part in str(reason or "").split("|") if part.strip()}
    return bool(parts & ASSET_MISSING_REASONS)


def resolve_internal_icon(icon_key: str) -> str:
    for candidate in ICON_CANDIDATES.get(_normalize_token(icon_key), ()):
        path = Path(candidate)
        if path.exists():
            return str(path)
    return ""


# OUTPUT-VISUALS-17: conservative per-intent semantic icon hierarchy over LOCAL
# existing icons only (no new/downloaded assets). Ordered best -> acceptable;
# the resolver returns the first existing + renderable candidate, else text-only.
# Travel now has dedicated local icons. Student remains document-only until real
# demand justifies adding education/passport-specific assets.
FAMILY_ICON_HIERARCHY: Dict[str, Tuple[str, ...]] = {
    "travel_assistance": (
        "assets/icons/vpi/travel_suitcase.svg",
        "assets/icons/vpi/travel_passport.svg",
        "assets/icons/document/file-search-corner.svg",
        "assets/icons/briefcase/briefcase-business.svg",
    ),
    "student_abroad": (
        "assets/icons/document/file-search-corner.svg",
        "assets/icons/vpi/signature_form.svg",
        "assets/icons/vpi/folder_paperwork.svg",
    ),
    "coverage_explanation": (
        "assets/icons/checklist/check-check.svg",
        "assets/icons/vpi/checklist_advice.svg",
        "assets/icons/document/file-search-corner.svg",
        "assets/icons/shield/shield-plus.svg",
        "assets/icons/vpi/folder_paperwork.svg",
    ),
    "advisor_explanation": (
        "assets/icons/checklist/check-check.svg",
        "assets/icons/vpi/checklist_advice.svg",
        "assets/icons/document/file-search-corner.svg",
    ),
    "risk_warning": (
        "assets/icons/warning/octagon-alert.svg",
        "assets/icons/vpi/alert_line.svg",
        "assets/icons/shield/shield-plus.svg",
        "assets/icons/health/heart-pulse.svg",
    ),
    "emotional_protection": (
        "assets/icons/vpi/family_shield.svg",
        "assets/icons/heart/heart-pulse.svg",
        "assets/icons/vpi/heart_shield.svg",
        "assets/icons/family/contact.svg",
        "assets/icons/shield/shield-plus.svg",
    ),
    "healthcare": (
        "assets/icons/health/heart-pulse.svg",
        "assets/icons/vpi/medical_cross.svg",
        "assets/icons/hospital/hospital.svg",
        "assets/icons/shield/shield-plus.svg",
    ),
    "financial_planning": (
        "assets/icons/vpi/budget_document.svg",
        "assets/icons/euro/badge-euro.svg",
        "assets/icons/vpi/capital_stack.svg",
        "assets/icons/checklist/check-check.svg",
        "assets/icons/document/file-search-corner.svg",
    ),
}

ICON_FAMILY_LABEL: Dict[str, str] = {
    "travel_assistance": "travel",
    "student_abroad": "education",
    "coverage_explanation": "checklist",
    "advisor_explanation": "checklist",
    "risk_warning": "warning",
    "emotional_protection": "protection",
    "healthcare": "health",
    "financial_planning": "finance",
}


def resolve_visual_fallback_icon(
    intent: str,
    text: str = "",
    available_icons: Optional[Any] = None,
) -> Dict[str, Any]:
    """Pick the best LOCAL, existing, renderable icon for an intent; else text-only."""
    intent_n = _normalize_token(intent)
    candidates = list(FAMILY_ICON_HIERARCHY.get(intent_n, ()))
    family = ICON_FAMILY_LABEL.get(intent_n, "generic")
    logger.info(
        "VPI_VISUAL_ICON_MAPPING_REQUEST intent=%s family=%s candidates=%d",
        intent_n, family, len(candidates),
    )
    avail = set(available_icons) if available_icons is not None else None
    for rank, cand in enumerate(candidates):
        abs_path = _icon_abs_path(cand)
        if not abs_path:
            continue
        if avail is not None and cand not in avail and abs_path not in avail:
            continue
        if not _svg_looks_renderable(abs_path):
            continue
        confidence = round(max(0.5, 1.0 - 0.12 * rank), 2)
        reason = "primary_family_match" if rank == 0 else f"fallback_rank_{rank}"
        logger.info(
            "VPI_VISUAL_ICON_MAPPING_MATCH intent=%s icon=%s rank=%s reason=%s confidence=%s",
            intent_n, cand, rank, reason, confidence,
        )
        if rank > 0:
            logger.info(
                "VPI_VISUAL_ICON_MAPPING_FALLBACK intent=%s icon=%s rank=%s",
                intent_n, cand, rank,
            )
        return {
            "icon": cand,
            "family": family,
            "match_reason": reason,
            "match_confidence": confidence,
            "candidates": candidates,
        }
    logger.info("VPI_VISUAL_ICON_MAPPING_TEXT_ONLY intent=%s family=%s", intent_n, family)
    return {
        "icon": "",
        "family": family,
        "match_reason": "no_renderable_local_icon",
        "match_confidence": 0.0,
        "candidates": candidates,
    }


def build_visual_fallback_plan(
    *,
    broll_decision: Dict[str, Any],
    broll_asset_match: Dict[str, Any],
    segment: Dict[str, Any],
    clip_duration_s: float,
    broll_skip_reason: str = "",
) -> VisualFallbackPlan:
    """Return a conservative visual fallback plan, or an explicit skip reason."""
    segment = segment if isinstance(segment, dict) else {}
    decision = broll_decision if isinstance(broll_decision, dict) else {}
    asset_match = broll_asset_match if isinstance(broll_asset_match, dict) else {}

    intent = _normalize_token(
        str(decision.get("broll_intent") or asset_match.get("broll_taxonomy_intent") or asset_match.get("asset_category") or "")
    )
    confidence = float(decision.get("confidence") or decision.get("broll_confidence") or 0.0)
    skip_reason = str(
        broll_skip_reason
        or decision.get("skip_reason")
        or asset_match.get("reason")
        or "|".join(str(item) for item in (asset_match.get("reasons") or []) if str(item))
        or ""
    )

    if intent not in ALLOWED_VISUAL_FALLBACK_INTENTS:
        return VisualFallbackPlan(False, intent=intent, skip_reason="intent_not_allowed", confidence=confidence)
    if not _contains_missing_asset_reason(skip_reason):
        return VisualFallbackPlan(False, intent=intent, skip_reason="broll_skip_not_asset_gap", confidence=confidence)
    if bool(segment.get("opening_context_weak")):
        return VisualFallbackPlan(False, intent=intent, skip_reason="opening_context_weak", confidence=confidence)
    if bool(segment.get("narrative_closure_weak")):
        return VisualFallbackPlan(False, intent=intent, skip_reason="narrative_closure_weak", confidence=confidence)
    if float(clip_duration_s or 0.0) < 8.0:
        return VisualFallbackPlan(False, intent=intent, skip_reason="clip_too_short", confidence=confidence)
    if confidence < 0.70:
        return VisualFallbackPlan(False, intent=intent, skip_reason="low_confidence", confidence=confidence)

    text, icon_key = INTENT_CARD_COPY.get(intent, ("REVISA ESTO", "document"))
    duration = max(1.2, min(1.8, float(decision.get("duration") or 1.5)))
    start = max(3.2, float(decision.get("start_offset") or decision.get("broll_start_time") or 4.2))
    latest_start = float(clip_duration_s or 0.0) - 2.5 - duration
    if latest_start < 3.2:
        return VisualFallbackPlan(False, intent=intent, skip_reason="no_safe_window", confidence=confidence)
    start = min(start, latest_start)
    end = start + duration
    _icon_res = resolve_visual_fallback_icon(intent, text)
    return VisualFallbackPlan(
        True,
        intent=intent,
        text=text,
        icon=_icon_res["icon"],
        icon_family=_icon_res["family"],
        icon_match_reason=_icon_res["match_reason"],
        icon_match_confidence=float(_icon_res["match_confidence"]),
        icon_candidates=tuple(_icon_res["candidates"]),
        start_s=round(start, 2),
        end_s=round(end, 2),
        duration_s=round(duration, 2),
        confidence=confidence,
    )


def _escape_drawtext(text: str) -> str:
    return (
        str(text or "")
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace("%", "\\%")
        .replace("\n", " ")
    )


def render_internal_visual_card(
    *,
    input_video: str | Path,
    output_video: str | Path,
    plan: VisualFallbackPlan | Dict[str, Any],
) -> Dict[str, Any]:
    """Render a sober internal visual card over the video, preserving audio."""
    input_path = Path(input_video)
    output_path = Path(output_video)
    plan_dict = plan.as_dict() if isinstance(plan, VisualFallbackPlan) else dict(plan or {})
    if not bool(plan_dict.get("visual_fallback_planned")):
        return {"rendered": False, "output_path": str(input_path), "reason": "not_planned"}
    if not input_path.exists():
        return {"rendered": False, "output_path": str(input_path), "reason": "input_missing"}

    start = float(plan_dict.get("visual_fallback_start_s") or 0.0)
    end = float(plan_dict.get("visual_fallback_end_s") or 0.0)
    if end <= start:
        end = start + max(1.2, min(1.8, float(plan_dict.get("visual_fallback_duration_s") or 1.5)))
    safe_text = _escape_drawtext(str(plan_dict.get("visual_fallback_text") or "REVISA ESTO"))
    enable = f"between(t\\,{start:.3f}\\,{end:.3f})"
    fade = 0.18
    alpha = (
        f"if(lt(t\\,{start + fade:.3f})\\,(t-{start:.3f})/{fade:.3f}\\,"
        f"if(gt(t\\,{end - fade:.3f})\\,({end:.3f}-t)/{fade:.3f}\\,1))"
    )
    bg_chain = [
        f"drawbox=x=96:y=270:w=888:h=240:color=#07111fcc:t=fill:enable='{enable}'",
        f"drawbox=x=96:y=270:w=8:h=240:color=#f8fafc@0.80:t=fill:enable='{enable}'",
        f"drawtext=text='{safe_text}':x=138:y=340:fontsize=58:fontcolor=white:alpha='{alpha}':box=0:enable='{enable}'",
        f"drawtext=text='VPI':x=138:y=432:fontsize=28:fontcolor=#cbd5e1:alpha='{alpha}':box=0:enable='{enable}'",
    ]
    vf_text_only = ",".join(bg_chain)

    # OUTPUT-VISUALS-16: composite a single principal icon (librsvg-rasterised) inside the card.
    icon_requested = str(plan_dict.get("visual_fallback_icon") or "")
    icon_resolved = _icon_abs_path(icon_requested)
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    intent_label = str(plan_dict.get("visual_fallback_intent") or "")
    if icon_requested:
        logger.info("VPI_VISUAL_ICON_SELECTED icon=%s intent=%s", icon_requested, intent_label)
        logger.info("VPI_VISUAL_ICON_VALIDATED icon=%s exists=%s", icon_requested, str(bool(icon_resolved)).lower())

    icon_meta = {
        "icon_requested": icon_requested,
        "icon_resolved": icon_resolved,
        "icon_rendered": False,
        "icon_width": 0,
        "icon_height": 0,
        "icon_position": "",
    }

    def _run(cmd):
        return subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if icon_resolved and not _svg_looks_renderable(icon_resolved):
        logger.info("VPI_VISUAL_ICON_VALIDATED icon=%s renderable=false reason=svg_malformed", icon_resolved)
        icon_resolved = ""
    if icon_resolved:
        fade_out_st = max(start, end - fade)
        filter_complex = (
            "[0:v]" + vf_text_only + "[bg];"
            f"[1:v]scale={ICON_RENDER_PX}:{ICON_RENDER_PX}:flags=lanczos,format=rgba,"
            f"fade=t=in:st={start:.3f}:d={fade:.3f}:alpha=1,"
            f"fade=t=out:st={fade_out_st:.3f}:d={fade:.3f}:alpha=1[ic];"
            f"[bg][ic]overlay=x={ICON_POS_X}:y={ICON_POS_Y}:enable='{enable}'[v]"
        )
        # OUTPUT-TIMELINE-25 FIX: bound output to the input duration instead of -shortest.
        # `-loop 1 -i icon` (infinite image) + `-shortest` truncated the video below the
        # input (ffmpeg gotcha); `-t input_dur` preserves the full clip and terminates.
        try:
            _vc_probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(input_path)],
                capture_output=True, text=True, timeout=20,
            )
            _vc_input_dur = float((_vc_probe.stdout or "0").strip() or 0.0)
        except Exception:
            _vc_input_dur = 0.0
        _vc_tail = ["-t", f"{_vc_input_dur:.3f}"] if _vc_input_dur > 0.0 else ["-shortest"]
        cmd_icon = [
            ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(input_path),
            "-loop", "1", "-i", icon_resolved,
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "copy", *_vc_tail,
            str(output_path),
        ]
        logger.info(
            "VPI_VISUAL_ICON_RASTERIZED icon=%s renderer=librsvg w=%s h=%s",
            icon_resolved, ICON_RENDER_PX, ICON_RENDER_PX,
        )
        try:
            result = _run(cmd_icon)
            if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                icon_meta.update({
                    "icon_rendered": True,
                    "icon_width": ICON_RENDER_PX,
                    "icon_height": ICON_RENDER_PX,
                    "icon_position": ICON_POSITION_LABEL,
                })
                logger.info(
                    "VPI_VISUAL_ICON_COMPOSITED icon=%s w=%s h=%s position=%s x=%s y=%s",
                    icon_resolved, ICON_RENDER_PX, ICON_RENDER_PX, ICON_POSITION_LABEL, ICON_POS_X, ICON_POS_Y,
                )
                return {
                    "rendered": True,
                    "output_path": str(output_path),
                    "method": "ffmpeg_card_with_librsvg_icon",
                    "filtergraph": filter_complex,
                    "start_s": round(start, 2),
                    "end_s": round(end, 2),
                    "duration_s": round(end - start, 2),
                    **icon_meta,
                }
            logger.warning(
                "VPI_VISUAL_ICON_COMPOSITED icon=%s rendered=false reason=%s",
                icon_resolved, (result.stderr or "ffmpeg_failed")[-200:],
            )
        except Exception as exc:
            logger.warning(
                "VPI_VISUAL_ICON_COMPOSITED icon=%s rendered=false reason=%s",
                icon_resolved, str(exc),
            )

    # Safe fallback: text-only card (no icon resolved, or icon composition failed).
    cmd_text = [
        ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(input_path),
        "-vf", vf_text_only,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "copy",
        str(output_path),
    ]
    try:
        result = _run(cmd_text)
        if result.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            return {
                "rendered": True,
                "output_path": str(output_path),
                "method": "ffmpeg_drawtext_internal_visual_card",
                "filtergraph": vf_text_only,
                "start_s": round(start, 2),
                "end_s": round(end, 2),
                "duration_s": round(end - start, 2),
                **icon_meta,
            }
        return {
            "rendered": False,
            "output_path": str(input_path),
            "reason": (result.stderr or "ffmpeg_failed")[-300:],
            "filtergraph": vf_text_only,
            **icon_meta,
        }
    except Exception as exc:
        return {"rendered": False, "output_path": str(input_path), "reason": str(exc), "filtergraph": vf_text_only, **icon_meta}


def probe_visual_card_visibility(input_video: str | Path, output_video: str | Path, t_s: float) -> Dict[str, Any]:
    """Compare frame hashes at t_s to prove the visual card changed the final MP4."""
    input_path = Path(input_video)
    output_path = Path(output_video)
    if not input_path.exists() or not output_path.exists():
        return {"visible": False, "reason": "input_or_output_missing"}
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    frame_paths = []
    try:
        digests = []
        for src in (input_path, output_path):
            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            tmp.close()
            frame_paths.append(Path(tmp.name))
            subprocess.run(
                [ffmpeg, "-y", "-v", "error", "-ss", f"{float(t_s):.2f}", "-i", str(src), "-frames:v", "1", tmp.name],
                capture_output=True,
                timeout=30,
            )
            if not Path(tmp.name).exists() or Path(tmp.name).stat().st_size <= 0:
                return {"visible": False, "reason": "frame_extract_failed", "t_s": round(float(t_s), 2)}
            digests.append(hashlib.md5(Path(tmp.name).read_bytes()).hexdigest())
        return {"visible": digests[0] != digests[1], "reason": "ok", "t_s": round(float(t_s), 2)}
    except Exception as exc:
        return {"visible": False, "reason": f"probe_failed:{exc}", "t_s": round(float(t_s), 2)}
    finally:
        for frame_path in frame_paths:
            frame_path.unlink(missing_ok=True)
