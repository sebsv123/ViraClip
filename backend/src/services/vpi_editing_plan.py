"""VPI Daily Publishing editing plan and output readiness helpers."""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


@dataclass
class EditingPlan:
    clip_id: str
    editorial_type: str
    central_topic: str
    hook_strategy: str
    pacing_strategy: str
    reframe_strategy: str
    subtitle_strategy: str
    broll_strategy: str
    brand_treatment: str
    cta_strategy: str
    visual_density: str
    emphasis_moments: list = field(default_factory=list)
    smart_zoom_events: list = field(default_factory=list)
    highlighted_terms: list = field(default_factory=list)
    publishable_score: float = 0.0
    reasoning: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


VPI_HIGHLIGHT_TERMS = [
    "pareja",
    "hijos",
    "dependen de ti",
    "proteger",
    "protección",
    "proteccion",
    "miedo",
    "organización",
    "organizacion",
    "responsabilidad",
    "no es solo",
    "personas mayores",
    "más adelante",
    "mas adelante",
    "edad",
    "cobertura",
    "póliza",
    "poliza",
    "seguro de vida",
]


def _theme_topic(theme: Optional[Any]) -> str:
    if theme is None:
        return "unknown"
    if isinstance(theme, dict):
        return str(theme.get("central_topic") or "unknown")
    return str(getattr(theme, "central_topic", "unknown") or "unknown")


def _find_terms(text: str, terms: Sequence[str]) -> List[str]:
    lowered = (text or "").lower()
    found: List[str] = []
    for term in terms:
        if term.lower() in lowered and term not in found:
            found.append(term)
    return found


def _word_time_for_phrase(words: Optional[Sequence[Dict[str, Any]]], phrase: str) -> Optional[float]:
    if not words:
        return None
    tokens = phrase.lower().replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u").split()
    if not tokens:
        return None
    normalized_words: List[Tuple[str, float]] = []
    for word in words:
        raw = str(word.get("word") or word.get("text") or "").lower()
        raw = raw.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
        try:
            start = float(word.get("start", 0.0) or 0.0)
        except (TypeError, ValueError):
            start = 0.0
        if raw:
            normalized_words.append((raw.strip(".,;:!?"), start))
    for idx in range(0, len(normalized_words) - len(tokens) + 1):
        if [item[0] for item in normalized_words[idx : idx + len(tokens)]] == tokens:
            return round(normalized_words[idx][1], 2)
    for raw, start in normalized_words:
        if raw == tokens[0]:
            return round(start, 2)
    return None


def build_editing_plan(
    text: str,
    editorial_type: Optional[str],
    vpi_score: Optional[float],
    matched_patterns: Optional[Sequence[str]],
    clip_duration: float,
    word_timestamps: Optional[Sequence[Dict[str, Any]]] = None,
    theme: Optional[Any] = None,
    has_broll: bool = False,
) -> EditingPlan:
    editorial = editorial_type or "generic"
    topic = _theme_topic(theme)
    lowered = (text or "").lower()
    weak_intro = any(trigger in lowered for trigger in ("hola soy", "vengo a hablar", "en este momento", "hoy quiero hablar"))

    highlighted = _find_terms(text, VPI_HIGHLIGHT_TERMS)
    emphasis_moments = []
    for term in highlighted[:6]:
        ts = _word_time_for_phrase(word_timestamps, term)
        if ts is not None and 0.5 <= ts <= max(0.5, clip_duration - 1.0):
            emphasis_moments.append({"term": term, "start_s": ts})

    if editorial == "emotional_protection":
        hook_strategy = "emotional_open"
        pacing_strategy = "calm_focused"
        reframe_strategy = "subtle_push_in"
        subtitle_strategy = "vpi_clean_highlight"
        broll_strategy = "family_first"
        visual_density = "medium"
        cta_strategy = "optional_end"
    elif editorial == "client_objection":
        hook_strategy = "objection_first"
        pacing_strategy = "sharper"
        reframe_strategy = "emphasis_punch"
        subtitle_strategy = "vpi_clean_highlight"
        broll_strategy = "advisor_support"
        visual_density = "medium_high"
        cta_strategy = "optional_end"
    elif weak_intro or editorial in {"coverage_explanation", "weak_intro"}:
        hook_strategy = "speaker_focus"
        pacing_strategy = "calm"
        reframe_strategy = "no_zoom" if weak_intro else "subtle_push_in"
        subtitle_strategy = "vpi_clean"
        broll_strategy = "no_broll" if weak_intro else "documents_support"
        visual_density = "low"
        cta_strategy = "none" if weak_intro else "metadata_only"
    else:
        hook_strategy = "speaker_focus"
        pacing_strategy = "calm_focused"
        reframe_strategy = "subtle_push_in"
        subtitle_strategy = "vpi_clean"
        broll_strategy = "context_support"
        visual_density = "medium"
        cta_strategy = "metadata_only"

    smart_zoom_events: List[Dict[str, Any]] = []
    if reframe_strategy != "no_zoom":
        max_events = 1 if has_broll else 2
        scale = 1.035 if reframe_strategy == "subtle_push_in" else 1.05
        for moment in emphasis_moments:
            start = float(moment["start_s"])
            if 1.0 <= start <= max(1.0, clip_duration - 2.0):
                smart_zoom_events.append({
                    "start_s": start,
                    "duration_s": 1.2,
                    "scale": scale,
                    "reason": moment["term"],
                })
            if len(smart_zoom_events) >= max_events:
                break

    score = 70.0
    if vpi_score is not None:
        score += min(20.0, max(0.0, float(vpi_score) / 5.0))
    if highlighted:
        score += 4.0
    if has_broll:
        score += 4.0
    if weak_intro:
        score -= 4.0
    score = round(min(100.0, score), 1)

    return EditingPlan(
        clip_id="",
        editorial_type=editorial,
        central_topic=topic,
        hook_strategy=hook_strategy,
        pacing_strategy=pacing_strategy,
        reframe_strategy=reframe_strategy,
        subtitle_strategy=subtitle_strategy,
        broll_strategy=broll_strategy,
        brand_treatment="text_watermark",
        cta_strategy=cta_strategy,
        visual_density=visual_density,
        emphasis_moments=emphasis_moments,
        smart_zoom_events=smart_zoom_events,
        highlighted_terms=highlighted,
        publishable_score=score,
        reasoning=f"VPI daily publishing plan for {editorial}; weak_intro={weak_intro}; broll={has_broll}",
    )


def probe_output_qc(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    warnings: List[str] = []
    qc: Dict[str, Any] = {
        "ok": False,
        "path": str(p),
        "exists": p.exists(),
        "file_size": p.stat().st_size if p.exists() else 0,
        "duration": None,
        "width": None,
        "height": None,
        "resolution": None,
        "fps": None,
        "video_codec": None,
        "audio_codec": None,
        "video_stream_exists": False,
        "audio_stream_exists": False,
        "warnings": warnings,
    }
    if not p.exists():
        warnings.append("missing_output")
        return qc
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration,size:stream=codec_type,codec_name,width,height,r_frame_rate",
            "-of", "json", str(p),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            warnings.append("ffprobe_failed")
            return qc
        data = json.loads(result.stdout or "{}")
        fmt = data.get("format", {})
        qc["duration"] = float(fmt.get("duration")) if fmt.get("duration") else None
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video" and not qc["video_stream_exists"]:
                qc["video_stream_exists"] = True
                qc["video_codec"] = stream.get("codec_name")
                qc["width"] = int(stream.get("width") or 0)
                qc["height"] = int(stream.get("height") or 0)
                qc["resolution"] = f"{qc['width']}x{qc['height']}"
                rate = str(stream.get("r_frame_rate") or "")
                if "/" in rate:
                    num, den = rate.split("/", 1)
                    try:
                        qc["fps"] = round(float(num) / max(1.0, float(den)), 3)
                    except ValueError:
                        qc["fps"] = None
            elif stream.get("codec_type") == "audio" and not qc["audio_stream_exists"]:
                qc["audio_stream_exists"] = True
                qc["audio_codec"] = stream.get("codec_name")
        if not qc["video_stream_exists"]:
            warnings.append("missing_video_stream")
        if not qc["audio_stream_exists"]:
            warnings.append("missing_audio_stream")
        if qc["resolution"] != "1080x1920":
            warnings.append("unexpected_resolution")
        qc["ok"] = qc["video_stream_exists"] and qc["audio_stream_exists"] and qc["exists"]
        logger.info(
            "[output-qc] resolution=%s duration=%s audio=%s video=%s ok=%s",
            qc["resolution"],
            qc["duration"],
            qc["audio_codec"] or "none",
            qc["video_codec"] or "none",
            qc["ok"],
        )
        return qc
    except Exception as exc:
        warnings.append(f"qc_exception:{exc}")
        logger.warning("[output-qc] failed path=%s error=%s", p, exc)
        return qc


def determine_publishable_status(
    *,
    task_completed: bool,
    final_file_exists: bool,
    subtitles: bool,
    output_qc: Dict[str, Any],
    beta_clean: bool = True,
    legacy_runtime: bool = False,
    error_code: Optional[str] = None,
    repeated_exact_broll_same_task: bool = False,
    weak_intro_forced_broll: bool = False,
    warnings: Optional[List[str]] = None,
    first3_visual_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    publish_warnings = list(warnings or [])
    publish_score = 100.0

    hard_failures = []
    if not task_completed:
        hard_failures.append("task_not_completed")
    if not final_file_exists:
        hard_failures.append("missing_output")
    if not output_qc.get("video_stream_exists"):
        hard_failures.append("missing_video")
    if not output_qc.get("audio_stream_exists"):
        hard_failures.append("missing_audio")
    if output_qc.get("resolution") not in (None, "1080x1920"):
        hard_failures.append("bad_resolution")
    if legacy_runtime:
        hard_failures.append("legacy_fallback")
    if error_code:
        hard_failures.append(f"error_code:{error_code}")
    if repeated_exact_broll_same_task:
        hard_failures.append("repeated_exact_broll_same_task")
    if weak_intro_forced_broll:
        hard_failures.append("weak_intro_forced_broll")

    # ── CAMBIO 5: first3_visual_contract affects status ──────────────────────
    _first3_contract = first3_visual_contract or {}
    _first3_fail_count = int(_first3_contract.get("first3_visual_fail_count") or 0)
    if _first3_fail_count >= 2:
        hard_failures.append("first3_visual_contract_failed")
        publish_warnings.append(f"first3_visual_contract_failed:{_first3_fail_count}_failures")

    if hard_failures:
        status = "not_ready"
        publish_score = 0.0
        publish_warnings.extend(hard_failures)
    else:
        if not subtitles:
            publish_warnings.append("subtitles_missing_or_metadata_unknown")
            publish_score -= 15
        for warning in output_qc.get("warnings", []):
            if warning not in publish_warnings:
                publish_warnings.append(warning)
                publish_score -= 5
        status = "ready" if not publish_warnings else "usable_with_warnings"

    return {
        "publishable_status": status,
        "publishable_warnings": publish_warnings,
        "publishable_score": round(max(0.0, publish_score), 1),
    }


def assess_visual_density(
    *,
    editing_plan: Dict[str, Any],
    broll_events: Optional[Sequence[Dict[str, Any]]] = None,
    subtitle_highlight_count: int = 0,
    watermark_applied: bool = False,
) -> Dict[str, Any]:
    """Lightweight metadata guard for visual event saturation."""
    density = str(editing_plan.get("visual_density") or "medium")
    zoom_events = list(editing_plan.get("smart_zoom_events") or [])
    broll_events = list(broll_events or [])
    warnings: List[str] = []
    actions: List[str] = []
    windows: Dict[int, float] = {}

    def add_event(start: float, weight: float) -> None:
        bucket = int(max(0.0, start) // 2)
        windows[bucket] = windows.get(bucket, 0.0) + weight

    for event in zoom_events:
        add_event(float(event.get("start_s", 0.0) or 0.0), 1.4)
    for event in broll_events:
        add_event(float(event.get("start_s", 0.0) or 0.0), 2.0)
    if subtitle_highlight_count:
        # Spread highlights conservatively; exact line timestamps live in ASS.
        for idx in range(min(subtitle_highlight_count, 8)):
            add_event(float(idx * 2.0 + 1.0), 0.7)
    if watermark_applied:
        add_event(0.0, 0.4)

    threshold = {"low": 2.0, "medium": 3.6, "medium_high": 4.2}.get(density, 3.6)
    adjusted_zoom_events = list(zoom_events)
    for bucket, score in sorted(windows.items()):
        if score > threshold:
            warning = f"dense_window_{bucket * 2}-{bucket * 2 + 2}s:{score:.1f}"
            warnings.append(warning)
            action = "skip_zoom_first"
            if adjusted_zoom_events:
                removed = adjusted_zoom_events.pop(0)
                actions.append(action)
                logger.info("[visual-density] window=%s-%s score=%.1f action=%s", bucket * 2, bucket * 2 + 2, score, action)
                logger.debug("[visual-density] removed_zoom=%s", removed)
            else:
                action = "metadata_warning_only"
                actions.append(action)
                logger.info("[visual-density] window=%s-%s score=%.1f action=%s", bucket * 2, bucket * 2 + 2, score, action)

    return {
        "visual_density_score": round(max(windows.values()) if windows else 0.0, 2),
        "visual_density_warnings": warnings,
        "visual_density_actions": actions,
        "smart_zoom_events": adjusted_zoom_events,
    }


def extend_output_qc_visual(
    output_qc: Dict[str, Any],
    *,
    watermark_applied: bool,
    captions_applied: bool,
    subtitle_highlight_count: int,
    broll_count: int,
    smart_reframe_applied: bool,
    visual_density_warnings: Optional[Sequence[str]] = None,
    branding_warnings: Optional[Sequence[str]] = None,
    broll_repetition_warnings: Optional[Sequence[str]] = None,
    hook_applied: bool = False,
    hook_type: str = "",
    hook_rendered: bool = False,
) -> Dict[str, Any]:
    qc = dict(output_qc or {})
    qc.update({
        "watermark_applied": bool(watermark_applied),
        "captions_applied": bool(captions_applied),
        "subtitle_highlight_count": int(subtitle_highlight_count or 0),
        "broll_count": int(broll_count or 0),
        "smart_reframe_applied": bool(smart_reframe_applied),
        "visual_density_warnings": list(visual_density_warnings or []),
        "branding_warnings": list(branding_warnings or []),
        "broll_repetition_warnings": list(broll_repetition_warnings or []),
        "hook_applied": bool(hook_applied),
        "hook_type": hook_type,
        "hook_rendered": bool(hook_rendered),
    })
    logger.info(
        "[output-qc] visual watermark=%s captions=%s highlights=%d broll=%d reframe=%s",
        str(qc["watermark_applied"]).lower(),
        str(qc["captions_applied"]).lower(),
        qc["subtitle_highlight_count"],
        qc["broll_count"],
        str(qc["smart_reframe_applied"]).lower(),
    )
    return qc
