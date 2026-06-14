"""VPI Silence Runtime Integration v1.7.

Deterministic, CPU-only silence planning and safe trimming for Beta Clean.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)


@dataclass
class SilenceSegment:
    start_s: float
    end_s: float
    duration_s: float
    before_text: str
    after_text: str
    pause_type: str
    action: str
    target_duration_s: float
    reason: str
    confidence: float
    affects_hook: bool
    affects_broll: bool
    affects_subtitles: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SilenceEditPlan:
    enabled: bool
    mode: str
    segments: List[SilenceSegment] = field(default_factory=list)
    cuts: List[dict] = field(default_factory=list)
    offset_map: List[dict] = field(default_factory=list)
    total_removed_s: float = 0.0
    warnings: List[str] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["segments"] = [segment.to_dict() for segment in self.segments]
        return data


_DEFAULT_RULES: Dict[str, Any] = {
    "global": {
        "min_pause_detect_s": 0.18,
        "dead_air_cut_threshold_s": 0.85,
        "max_preserved_pause_s": 0.65,
        "micro_pause_keep_range_s": [0.12, 0.35],
        "emphasis_pause_keep_range_s": [0.25, 0.60],
        "transition_pause_keep_range_s": [0.20, 0.50],
        "cta_pause_keep_range_s": [0.25, 0.70],
        # Retention v4.0: silence as editorial tool
        "tension_silence_keep_range_s": [0.12, 0.45],
        "pattern_interruption_min_s": 0.25,
        "pattern_interruption_max_s": 0.50,
        "key_phrase_micro_silence_min_s": 0.10,
        "key_phrase_micro_silence_max_s": 0.40,
    }
}

_DEFAULT_CONTEXT: Dict[str, Any] = {
    "before_keywords": [
        "no es solo",
        "responsabilidad",
        "proteger",
        "miedo",
        "dependen de ti",
        "personas mayores",
        "mas adelante",
        "la realidad es",
        "antes de contratar",
        "imprevisto",
    ],
    "after_keywords": [
        "responsabilidad",
        "proteger",
        "personas que dependen",
        "no es solo",
        "la realidad es",
        "conviene",
        "cuidado",
        "antes de",
        "porque",
        "imprevisto",
        "pero",
        "no siempre",
    ],
    "filler_before_keywords": ["eh", "eh...", "mmm", "um", "bueno pues", "pues"],
    "cta_after_keywords": ["lo revisamos", "hablamos", "si quieres", "escribeme", "te ayudo"],
    "between_examples_keywords": ["pareja", "hijos", "hipoteca", "familia", "cobertura", "precio", "edad"],
}

_ACTIONS_FOR_TRIM = {"cut", "shorten"}


def _resolve_config_dir() -> Path:
    """Resolve the configs/ directory robustly.

    Tries (in order):
      1. VIRACLIP_CONFIG_DIR env var (if set)
      2. Path.cwd() / 'configs'
      3. /app/configs
      4. __file__ parents walking up to find configs/
    Returns the first valid directory, or Path.cwd() / 'configs' as fallback.
    """
    env_dir = os.environ.get("VIRACLIP_CONFIG_DIR")
    if env_dir:
        p = Path(env_dir)
        if p.exists():
            logger.debug("[silence-config] config_dir from env: %s", p)
            return p
    cwd_configs = Path.cwd() / "configs"
    if cwd_configs.exists():
        logger.debug("[silence-config] config_dir from cwd: %s", cwd_configs)
        return cwd_configs
    app_configs = Path("/app/configs")
    if app_configs.exists():
        logger.debug("[silence-config] config_dir from /app: %s", app_configs)
        return app_configs
    try:
        f = Path(__file__).resolve()
        for parent in f.parents:
            candidate = parent / "configs"
            if candidate.exists():
                logger.debug("[silence-config] config_dir from __file__ walk: %s", candidate)
                return candidate
    except Exception:
        pass
    logger.warning("[silence-config] config_dir fallback to cwd/configs")
    return cwd_configs


def load_silence_rules() -> Dict[str, Any]:
    config_dir = _resolve_config_dir()
    rules_path = config_dir / "vpi_silence_editing_rules.json"
    context_path = config_dir / "vpi_silence_context_rules.json"
    warnings: List[str] = []
    rules = dict(_DEFAULT_RULES)
    context = dict(_DEFAULT_CONTEXT)
    loaded = False
    try:
        if rules_path.exists():
            rules = json.loads(rules_path.read_text(encoding="utf-8"))
            loaded = True
        else:
            warnings.append("rules_missing")
    except Exception as exc:
        warnings.append(f"rules_invalid:{exc}")
        rules = dict(_DEFAULT_RULES)
    try:
        if context_path.exists():
            context = json.loads(context_path.read_text(encoding="utf-8"))
            loaded = True
        else:
            warnings.append("context_missing")
    except Exception as exc:
        warnings.append(f"context_invalid:{exc}")
        context = dict(_DEFAULT_CONTEXT)
    logger.info("[silence-config] loaded=%s config_dir=%s", str(loaded).lower(), str(config_dir))
    for warning in warnings:
        logger.warning("[silence-config] fallback reason=%s", warning)
    return {"rules": rules, "context": context, "warnings": warnings, "loaded": loaded, "config_dir": str(config_dir)}


def detect_silence_segments_from_words(
    word_timestamps: Optional[Sequence[Dict[str, Any]]],
    text: str,
    *,
    min_pause_detect_s: float = 0.18,
) -> List[Dict[str, Any]]:
    words = _sanitize_words(word_timestamps)
    if len(words) < 2:
        return []
    gaps: List[Dict[str, Any]] = []
    for idx in range(1, len(words)):
        prev = words[idx - 1]
        nxt = words[idx]
        gap_start = float(prev["end"])
        gap_end = float(nxt["start"])
        gap_duration = round(gap_end - gap_start, 3)
        if gap_duration < min_pause_detect_s:
            continue
        before_words = [str(item.get("word") or item.get("text") or "") for item in words[max(0, idx - 12):idx]]
        after_words = [str(item.get("word") or item.get("text") or "") for item in words[idx:min(len(words), idx + 12)]]
        gaps.append({
            "start_s": round(gap_start, 3),
            "end_s": round(gap_end, 3),
            "duration_s": gap_duration,
            "before_text": " ".join(before_words[-12:]).strip(),
            "after_text": " ".join(after_words[:12]).strip(),
            "word_index": idx,
            "text": text,
        })
    return gaps


def classify_pause(
    gap: Dict[str, Any],
    *,
    editorial_type: Optional[str],
    hook_plan: Optional[Dict[str, Any]] = None,
    broll_events: Optional[Sequence[Dict[str, Any]]] = None,
    subtitle_terms: Optional[Sequence[str]] = None,
    rules_bundle: Optional[Dict[str, Any]] = None,
) -> SilenceSegment:
    bundle = rules_bundle or load_silence_rules()
    rules = bundle.get("rules") or _DEFAULT_RULES
    context = bundle.get("context") or _DEFAULT_CONTEXT
    global_rules = rules.get("global", _DEFAULT_RULES["global"])
    editorial = str(editorial_type or "")
    start = float(gap.get("start_s", 0.0) or 0.0)
    end = float(gap.get("end_s", start) or start)
    duration = round(max(0.0, float(gap.get("duration_s", end - start) or 0.0)), 3)
    before = str(gap.get("before_text") or "")
    after = str(gap.get("after_text") or "")
    affects_hook = start < max(3.0, float((hook_plan or {}).get("end_s") or 0.0))
    affects_broll = _near_event(start, broll_events, radius_s=0.6)
    affects_subtitles = _contains_any(before + " " + after, list(subtitle_terms or []))

    before_filler = _contains_any(before, context.get("filler_before_keywords", []))
    before_strong = _contains_any(before, context.get("before_keywords", []))
    after_strong = _contains_any(after, context.get("after_keywords", []))
    after_cta = _contains_any(after, context.get("cta_after_keywords", []))
    between_examples = (
        _contains_any(before, context.get("between_examples_keywords", []))
        and _contains_any(after, context.get("between_examples_keywords", []))
    )
    dead_air_threshold = float(global_rules.get("dead_air_cut_threshold_s", 0.85))

    # Retention v4.0: detect key VPI concepts for micro-silence preservation
    key_vpi_terms = [
        "responsabilidad", "proteger", "imprevisto", "no es solo", "dependen",
        "personas mayores", "mas adelante", "la realidad es", "antes de contratar",
        "cuidado", "conviene", "porque", "pero", "no siempre",
    ]
    after_contains_vpi = _contains_any(after, key_vpi_terms)
    before_contains_vpi = _contains_any(before, key_vpi_terms)

    # Retention v4.0: pattern interruption thresholds
    pi_min_s = float(global_rules.get("pattern_interruption_min_s", 0.25))
    pi_max_s = float(global_rules.get("pattern_interruption_max_s", 0.50))
    key_phrase_micro_min_s = float(global_rules.get("key_phrase_micro_silence_min_s", 0.10))
    key_phrase_micro_max_s = float(global_rules.get("key_phrase_micro_silence_max_s", 0.40))

    pause_type = "breath_pause"
    action = "preserve"
    target = min(duration, float(global_rules.get("max_preserved_pause_s", 0.65)))
    reason = "micro_breath"
    confidence = 0.62

    hard_dead_air_s = float(global_rules.get("hard_dead_air_threshold_s", 1.2))

    # ── OUTPUT-CUTS-8: long dead air overrides keyword-based emphasis branches.
    # Every editorial keep-range tops out at 0.7s, so a pause beyond
    # hard_dead_air_s can never be an expressive pause regardless of the
    # surrounding keywords (COMPRESS_SILENCE: leave 0.25-0.55s, not zero).
    if duration >= hard_dead_air_s:
        pause_type, action, target, reason, confidence = (
            "dead_air", "shorten", 0.35, "long_dead_air_overrides_emphasis", 0.86,
        )
    # ── Retention v4.0: tension silence (micro-silence before key VPI concepts) ──
    elif after_contains_vpi and key_phrase_micro_min_s <= duration <= key_phrase_micro_max_s:
        pause_type, action, target, reason, confidence = (
            "tension_silence", "preserve_for_tension", duration,
            f"micro_silence_before_key_phrase:{after[:40]}", 0.88,
        )
    elif before_contains_vpi and key_phrase_micro_min_s <= duration <= key_phrase_micro_max_s:
        pause_type, action, target, reason, confidence = (
            "tension_silence", "preserve_for_tension", duration,
            f"micro_silence_after_key_phrase:{before[:40]}", 0.85,
        )
    # ── Retention v4.0: pattern interruption (silence before strong phrase in non-weak_intro) ──
    elif (
        editorial not in ("weak_intro",)
        and after_strong
        and pi_min_s <= duration <= pi_max_s
        and not affects_hook
    ):
        pause_type, action, target, reason, confidence = (
            "pattern_interruption_silence", "pattern_interruption", duration,
            f"pattern_interruption_before:{after[:40]}", 0.82,
        )
    elif before_filler and duration >= 0.5:
        pause_type, action, target, reason, confidence = "awkward_pause", "shorten", 0.15, "post_filler", 0.88
    elif editorial == "weak_intro" and duration >= 0.45:
        pause_type, action, target, reason, confidence = "dead_air", "shorten", 0.18, "weak_intro_cleanup", 0.84
    elif affects_broll and not affects_hook and 0.25 <= duration <= 0.7:
        pause_type, action, target, reason, confidence = "transition_pause", "use_as_transition", _clamp(duration, 0.25, 0.45), "broll_transition", 0.74
    elif affects_subtitles and duration <= 0.5:
        pause_type, action, target, reason, confidence = "subtitle_breath_pause", "avoid_cut", duration, "subtitle_breath", 0.72
    elif after_cta and duration <= 0.7:
        pause_type, action, target, reason, confidence = "cta_pause", "preserve", duration, "cta_human_close", 0.72
    elif _inside_syntax(before):
        pause_type, action, target, reason, confidence = "breath_pause", "avoid_cut", duration, "inside_syntax", 0.70
    elif editorial == "risk_warning" and (before_strong or after_strong) and duration > 0.7:
        pause_type, action, target, reason, confidence = "dramatic_pause", "shorten", 0.50, "risk_tension_too_long", 0.78
    elif editorial in {"risk_warning", "myth_debunk"} and after_strong and duration >= 0.35:
        pause_type, action, target, reason, confidence = "dramatic_pause", "preserve_and_emphasize", _clamp(duration, 0.35, 0.45), "controlled_reveal", 0.78
    elif editorial == "emotional_protection" and _contains_any(before, ["dependen de ti", "personas que dependen"]) and duration <= 0.65:
        pause_type, action, target, reason, confidence = "let_it_land_pause", "preserve", _clamp(duration, 0.35, 0.50), "family_phrase_lands", 0.78
    elif editorial == "emotional_protection" and before_strong and affects_hook and duration <= 0.6:
        pause_type, action, target, reason, confidence = "emphasis_pause", "preserve_and_emphasize", _clamp(duration, 0.35, 0.55), "emotional_hook_contrast", 0.80
    elif editorial == "client_objection" and _contains_any(before, ["no es solo"]) and duration <= 0.35:
        pause_type, action, target, reason, confidence = "let_it_land_pause", "preserve", duration, "hook_phrase_lands", 0.74
    elif after_strong and (affects_hook or duration >= 0.2):
        pause_type, action, target, reason, confidence = "emphasis_pause", "preserve_and_emphasize", _clamp(duration, 0.25, 0.45), "before_strong_phrase", 0.80
    elif before_strong and duration <= 0.65:
        pause_type, action, target, reason, confidence = "let_it_land_pause", "preserve", _clamp(duration, 0.30, 0.55), "after_strong_phrase", 0.76
    elif between_examples and duration <= 0.4:
        pause_type, action, target, reason, confidence = "transition_pause", "preserve", duration, "list_rhythm", 0.70
    elif duration >= dead_air_threshold:
        if editorial == "coverage_explanation":
            pause_type, action, target, reason, confidence = "thinking_pause", "shorten", 0.25, "long_thinking_explanation", 0.76
        else:
            pause_type, action, target, reason, confidence = "dead_air", "cut", 0.10, "long_dead_air", 0.82
    elif duration <= float(global_rules.get("micro_pause_keep_range_s", [0.12, 0.35])[1]):
        pause_type, action, target, reason, confidence = "breath_pause", "preserve", duration, "micro_breath", 0.64
    elif editorial in {"client_objection", "myth_debunk"}:
        pause_type, action, target, reason, confidence = "thinking_pause", "shorten", 0.25, "sharp_pace_soft_shorten", 0.66

    segment = SilenceSegment(
        start_s=round(start, 3),
        end_s=round(end, 3),
        duration_s=round(duration, 3),
        before_text=before,
        after_text=after,
        pause_type=pause_type,
        action=action,
        target_duration_s=round(float(target), 3),
        reason=reason,
        confidence=round(float(confidence), 2),
        affects_hook=bool(affects_hook),
        affects_broll=bool(affects_broll),
        affects_subtitles=bool(affects_subtitles),
    )
    logger.info(
        "[silence-classify] start=%.2f dur=%.2f type=%s action=%s reason=%s",
        segment.start_s,
        segment.duration_s,
        segment.pause_type,
        segment.action,
        segment.reason,
    )
    return segment


def build_silence_edit_plan(
    *,
    word_timestamps: Optional[Sequence[Dict[str, Any]]],
    text: str,
    clip_duration: float,
    editorial_type: Optional[str],
    hook_plan: Optional[Dict[str, Any]] = None,
    broll_events: Optional[Sequence[Dict[str, Any]]] = None,
    subtitle_terms: Optional[Sequence[str]] = None,
    mode: Optional[str] = None,
    enabled: Optional[bool] = None,
) -> SilenceEditPlan:
    bundle = load_silence_rules()
    global_rules = (bundle.get("rules") or _DEFAULT_RULES).get("global", _DEFAULT_RULES["global"])
    env_enabled = os.environ.get("VIRACLIP_ENABLE_SILENCE_TRIM", "false").lower() in {"1", "true", "yes"}
    selected_mode = (mode or os.environ.get("VIRACLIP_SILENCE_MODE") or ("safe_trim" if env_enabled else "metadata")).strip().lower()
    plan_enabled = bool(enabled) if enabled is not None else selected_mode in {"metadata", "safe_trim"}
    if not plan_enabled:
        logger.info("[silence-apply] skipped reason=disabled")
        return SilenceEditPlan(enabled=False, mode="disabled", warnings=["disabled"], summary={"total_segments_detected": 0})

    gaps = detect_silence_segments_from_words(
        word_timestamps,
        text,
        min_pause_detect_s=float(global_rules.get("min_pause_detect_s", 0.18)),
    )
    segments = [
        classify_pause(
            gap,
            editorial_type=editorial_type,
            hook_plan=hook_plan,
            broll_events=broll_events,
            subtitle_terms=subtitle_terms,
            rules_bundle=bundle,
        )
        for gap in gaps
    ]
    cuts = _build_safe_cuts(segments, mode=selected_mode)
    offset_map = _build_offset_map(cuts)
    total_removed = round(sum(float(cut.get("removed_s", 0.0) or 0.0) for cut in cuts), 3)
    action_counts: Dict[str, int] = {}
    for segment in segments:
        action_counts[segment.action] = action_counts.get(segment.action, 0) + 1
    warnings = list(bundle.get("warnings") or [])
    if selected_mode == "metadata":
        warnings.append("silence_metadata_only")
    if any(segment.pause_type == "dead_air" and segment.duration_s >= 1.0 for segment in segments):
        warnings.append("excessive_dead_air_detected")
    plan = SilenceEditPlan(
        enabled=True,
        mode=selected_mode,
        segments=segments,
        cuts=cuts,
        offset_map=offset_map,
        total_removed_s=total_removed,
        warnings=warnings,
        summary={
            "total_segments_detected": len(segments),
            "total_cuts_applied": len(cuts),
            "actions_distribution": action_counts,
            "preserved_emphasis_pauses": sum(1 for item in segments if item.action in {"preserve", "preserve_and_emphasize"} and item.pause_type in {"emphasis_pause", "dramatic_pause", "let_it_land_pause"}),
            "tension_silences_preserved": sum(1 for item in segments if item.action == "preserve_for_tension"),
            "pattern_interruption_opportunities": sum(1 for item in segments if item.action == "pattern_interruption"),
            "silence_retention_moments": [
                {"start_s": item.start_s, "duration_s": item.duration_s, "reason": item.reason}
                for item in segments
                if item.action in {"preserve_for_tension", "pattern_interruption", "preserve_and_emphasize"}
            ],
            "preserved_tension_pauses": [
                {"start_s": item.start_s, "duration_s": item.duration_s, "reason": item.reason}
                for item in segments
                if item.action == "preserve_for_tension"
            ],
            "removed_dead_pauses": [
                {"start_s": item.start_s, "duration_s": item.duration_s, "reason": item.reason}
                for item in segments
                if item.pause_type == "dead_air" and item.action in {"cut", "shorten"}
            ],
            "silence_pattern_interruptions": [
                {"start_s": item.start_s, "duration_s": item.duration_s, "reason": item.reason}
                for item in segments
                if item.action == "pattern_interruption"
            ],
            "clip_duration_s": round(float(clip_duration or 0.0), 3),
        },
    )
    for item in segments:
        if item.action == "preserve_for_tension":
            logger.info("[silence-retention] preserve pause=%.2f reason=tension_before_key_phrase", item.start_s)
        elif item.action == "pattern_interruption":
            logger.info("[silence-retention] pattern_interrupt at=%.2f", item.start_s)
        elif item.pause_type == "dead_air" and item.action in {"cut", "shorten"}:
            logger.info("[silence-retention] cut pause=%.2f reason=dead_air", item.start_s)
    logger.info("[silence-plan] segments=%d cuts=%d total_removed=%.2f", len(segments), len(cuts), total_removed)
    return plan


def apply_silence_edit_plan(video_path: Path, output_path: Path, plan: SilenceEditPlan, clip_duration: float) -> Dict[str, Any]:
    if not plan.enabled or plan.mode != "safe_trim":
        logger.info("[silence-apply] skipped reason=%s", "metadata_only" if plan.enabled else "disabled")
        return {"rendered": False, "output_path": str(video_path), "reason": "metadata_only", "warnings": list(plan.warnings)}
    if not plan.cuts:
        logger.info("[silence-apply] skipped reason=no_safe_cuts")
        return {"rendered": False, "output_path": str(video_path), "reason": "no_safe_cuts", "warnings": list(plan.warnings)}
    # OUTPUT-TIMELINE-25 (instrumentation): probe real input media duration vs clip_duration arg.
    try:
        _t25_probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(video_path)],
            capture_output=True, text=True, timeout=30,
        )
        _t25_input_dur = float((_t25_probe.stdout or "0").strip() or 0.0)
    except Exception:
        _t25_input_dur = 0.0
    _t25_clip_arg = float(clip_duration or 0.0)
    logger.info("VPI_TIMELINE25_INPUT_DURATION path=%s probed=%.3f clip_duration_arg=%.3f", video_path.name, _t25_input_dur, _t25_clip_arg)
    logger.info("VPI_TIMELINE25_CLIP_DURATION_ARGUMENT value=%.3f shorter_than_input=%s", _t25_clip_arg, str(_t25_clip_arg + 0.05 < _t25_input_dur).lower())
    # OUTPUT-TIMELINE-25 FIX: canonical duration = real input media (ffprobe), never the
    # stale segment-nominal clip_duration. Prevents last-segment over-reach + A/V desync.
    if _t25_input_dur and _t25_input_dur > 0.0:
        _canonical_dur = round(_t25_input_dur, 3)
    else:
        logger.warning("[silence-apply] skipped reason=duration_probe_failed")
        return {"rendered": False, "output_path": str(video_path), "reason": "duration_probe_failed", "warnings": list(plan.warnings) + ["duration_probe_failed"], "silence_duration_probe_ok": False}
    logger.info("VPI_TIMELINE25_CLIP_DURATION_USED canonical=%.3f source=ffprobe_input_media stale_arg=%.3f", _canonical_dur, _t25_clip_arg)
    intervals = _keep_intervals(_canonical_dur, plan.cuts)
    if intervals and (_canonical_dur - intervals[-1][1] > 0.05):
        intervals.append((round(intervals[-1][1], 3), _canonical_dur))
        logger.info("VPI_KEEP_SEGMENTS_TAIL_APPENDED to=%.3f", _canonical_dur)
    try:
        _t25_last_keep = intervals[-1][1] if intervals else 0.0
        _t25_sum = round(sum(e - s for s, e in intervals), 3)
        logger.info("VPI_TIMELINE25_KEEP_SEGMENTS count=%d segments=%s", len(intervals), intervals)
        logger.info("VPI_TIMELINE25_LAST_KEEP_END value=%.3f input_dur=%.3f tail_omitted=%s", _t25_last_keep, _t25_input_dur, str(_t25_input_dur - _t25_last_keep > 0.05).lower())
        logger.info("VPI_TIMELINE25_EXPECTED_OUTPUT_DURATION sum_keep=%.3f", _t25_sum)
    except Exception:
        pass
    if not intervals:
        logger.info("[silence-apply] skipped reason=no_keep_intervals")
        return {"rendered": False, "output_path": str(video_path), "reason": "no_keep_intervals", "warnings": list(plan.warnings) + ["no_keep_intervals"]}
    filters: List[str] = []
    concat_inputs: List[str] = []
    for idx, (start, end) in enumerate(intervals):
        filters.append(f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{idx}]")
        filters.append(f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{idx}]")
        concat_inputs.append(f"[v{idx}][a{idx}]")
    filter_complex = (
        ";".join(filters)
        + ";"
        + "".join(concat_inputs)
        + f"concat=n={len(intervals)}:v=1:a=1[cv][outa];"
        + "[cv]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[outv]"
    )
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video_path),
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "160k",
        str(output_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if result.returncode == 0 and output_path.exists():
            logger.info("VPI_TIMELINE25_SILENCE_RENDERED removed=%.3f input_media=%.3f", plan.total_removed_s, _t25_input_dur)
            logger.info("[silence-apply] rendered=true total_removed=%.2f", plan.total_removed_s)
            return {"rendered": True, "output_path": str(output_path), "total_removed_s": plan.total_removed_s, "warnings": list(plan.warnings)}
        reason = (result.stderr or "ffmpeg_failed")[-300:]
        logger.warning("[silence-apply] failed fallback=input reason=%s", reason)
        return {"rendered": False, "output_path": str(video_path), "reason": reason, "warnings": list(plan.warnings) + ["silence_trim_failed"]}
    except Exception as exc:
        logger.warning("[silence-apply] failed fallback=input reason=%s", exc)
        return {"rendered": False, "output_path": str(video_path), "reason": str(exc), "warnings": list(plan.warnings) + ["silence_trim_failed"]}


def remap_time(t: float, offset_map: Sequence[Dict[str, Any]]) -> float:
    value = float(t or 0.0)
    removed = 0.0
    for item in sorted(offset_map or [], key=lambda row: float(row.get("original_start", 0.0) or 0.0)):
        original_start = float(item.get("original_start", 0.0) or 0.0)
        original_end = float(item.get("original_end", original_start) or original_start)
        removed_s = float(item.get("removed_s", 0.0) or 0.0)
        new_start = float(item.get("new_start", original_start - removed) or 0.0)
        if value >= original_end:
            removed += removed_s
            continue
        if original_start <= value < original_end:
            return round(new_start, 3)
        break
    return round(max(0.0, value - removed), 3)


def remap_word_timestamps(words: Optional[Sequence[Dict[str, Any]]], offset_map: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    remapped: List[Dict[str, Any]] = []
    for item in words or []:
        new_item = dict(item)
        try:
            new_item["start"] = remap_time(float(item.get("start", 0.0) or 0.0), offset_map)
            new_item["end"] = max(new_item["start"], remap_time(float(item.get("end", new_item["start"]) or new_item["start"]), offset_map))
        except (TypeError, ValueError):
            pass
        remapped.append(new_item)
    return remapped


def remap_events(events: Optional[Sequence[Dict[str, Any]]], offset_map: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    remapped: List[Dict[str, Any]] = []
    for event in events or []:
        new_event = dict(event)
        for key in ("start_s", "end_s", "timestamp", "time_s"):
            if key in new_event:
                try:
                    new_event[key] = remap_time(float(new_event.get(key, 0.0) or 0.0), offset_map)
                except (TypeError, ValueError):
                    pass
        remapped.append(new_event)
    return remapped


def remap_hook_plan(hook_plan: Optional[Dict[str, Any]], offset_map: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    if not hook_plan:
        return {}
    out = dict(hook_plan)
    for key in ("start_s", "end_s", "overlay_start_s", "broll_delay_until_s"):
        if key in out:
            try:
                out[key] = remap_time(float(out.get(key, 0.0) or 0.0), offset_map)
            except (TypeError, ValueError):
                pass
    if isinstance(out.get("zoom_event"), dict):
        out["zoom_event"] = remap_events([out["zoom_event"]], offset_map)[0]
    if isinstance(out.get("kickframe_event"), dict):
        out["kickframe_event"] = remap_events([out["kickframe_event"]], offset_map)[0]
    if isinstance(out.get("hook_headline_overlay"), dict):
        overlay = dict(out["hook_headline_overlay"])
        if "start_s" in overlay:
            overlay["start_s"] = remap_time(float(overlay.get("start_s", 0.0) or 0.0), offset_map)
        if "end_s" in overlay:
            overlay["end_s"] = remap_time(float(overlay.get("end_s", 0.0) or 0.0), offset_map)
        out["hook_headline_overlay"] = overlay
    return out


def _build_safe_cuts(segments: Sequence[SilenceSegment], *, mode: str) -> List[Dict[str, Any]]:
    if mode != "safe_trim":
        return []
    cuts: List[Dict[str, Any]] = []
    total_removed = 0.0
    for segment in sorted(segments, key=lambda item: item.start_s):
        # Retention v4.0: never cut tension silences or pattern interruptions
        if segment.action in {"preserve_for_tension", "pattern_interruption"}:
            logger.info(
                "[silence-retention] action=preserve start=%.2f type=%s reason=%s",
                segment.start_s, segment.pause_type, segment.reason,
            )
            continue
        if segment.action not in _ACTIONS_FOR_TRIM:
            continue
        if segment.confidence < 0.65 or segment.duration_s < 0.35:
            continue
        if segment.affects_hook and segment.pause_type not in {"dead_air", "awkward_pause"}:
            logger.info("[silence-hook] action=preserve_strategy start=%.2f type=%s", segment.start_s, segment.pause_type)
            continue
        target = _target_for_cut(segment)
        removed = round(max(0.0, segment.duration_s - target), 3)
        if removed <= 0.05:
            continue
        # OUTPUT-CUTS-8: long dead air gets a larger removal budget; every
        # other pause type keeps the conservative 2.5s ceiling.
        budget = 12.0 if segment.pause_type in {"dead_air", "awkward_pause"} else 2.5
        if total_removed + removed > budget:
            continue
        if len(cuts) >= 8:
            break
        cut_start = round(segment.start_s + target, 3)
        cut_end = round(segment.end_s, 3)
        cuts.append({
            "start_s": cut_start,
            "end_s": cut_end,
            "removed_s": removed,
            "target_duration_s": target,
            "pause_start_s": segment.start_s,
            "pause_end_s": segment.end_s,
            "pause_type": segment.pause_type,
            "action": segment.action,
            "reason": segment.reason,
        })
        total_removed = round(total_removed + removed, 3)
    return cuts


def _target_for_cut(segment: SilenceSegment) -> float:
    if segment.action == "cut":
        return 0.10
    if segment.pause_type == "dead_air":
        return _clamp(segment.target_duration_s or 0.20, 0.15, 0.25)
    if segment.reason == "weak_intro_cleanup":
        return _clamp(segment.target_duration_s or 0.18, 0.15, 0.25)
    if segment.pause_type == "awkward_pause":
        return _clamp(segment.target_duration_s or 0.15, 0.12, 0.25)
    return _clamp(segment.target_duration_s or 0.25, 0.15, 0.35)


def _build_offset_map(cuts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    offset_map: List[Dict[str, Any]] = []
    removed_before = 0.0
    for cut in sorted(cuts, key=lambda item: float(item.get("start_s", 0.0) or 0.0)):
        start = float(cut.get("start_s", 0.0) or 0.0)
        end = float(cut.get("end_s", start) or start)
        removed = round(max(0.0, end - start), 3)
        offset_map.append({
            "original_start": round(start, 3),
            "original_end": round(end, 3),
            "new_start": round(start - removed_before, 3),
            "removed_before": round(removed_before, 3),
            "removed_s": removed,
            "removed_after": round(removed_before + removed, 3),
        })
        removed_before = round(removed_before + removed, 3)
    return offset_map


def _keep_intervals(duration: float, cuts: Sequence[Dict[str, Any]]) -> List[tuple[float, float]]:
    intervals: List[tuple[float, float]] = []
    cursor = 0.0
    for cut in sorted(cuts, key=lambda item: float(item.get("start_s", 0.0) or 0.0)):
        start = max(0.0, min(duration, float(cut.get("start_s", 0.0) or 0.0)))
        end = max(start, min(duration, float(cut.get("end_s", start) or start)))
        if start - cursor > 0.03:
            intervals.append((round(cursor, 3), round(start, 3)))
        cursor = max(cursor, end)
    if duration - cursor > 0.03:
        intervals.append((round(cursor, 3), round(duration, 3)))
    return intervals


def _sanitize_words(words: Optional[Sequence[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    sanitized: List[Dict[str, Any]] = []
    for item in words or []:
        try:
            start = float(item.get("start", 0.0) or 0.0)
            end = float(item.get("end", start) or start)
        except (TypeError, ValueError):
            continue
        if end < start:
            end = start
        word = str(item.get("word") or item.get("text") or "").strip()
        sanitized.append({**item, "start": start, "end": end, "word": word})
    return sorted(sanitized, key=lambda item: float(item.get("start", 0.0) or 0.0))


def _near_event(t: float, events: Optional[Sequence[Dict[str, Any]]], *, radius_s: float) -> bool:
    for event in events or []:
        try:
            start = float(event.get("start_s", event.get("timestamp", 0.0)) or 0.0)
        except (TypeError, ValueError):
            continue
        if abs(start - t) <= radius_s:
            logger.info("[silence-broll] transition_pause=true start=%.2f event=%.2f", t, start)
            return True
    return False


def _contains_any(text: str, keywords: Sequence[str]) -> bool:
    normalized = _normalize(text)
    return any(_normalize(keyword) in normalized for keyword in keywords if str(keyword).strip())


def _inside_syntax(before: str) -> bool:
    normalized = _normalize(before)
    return normalized.endswith("antes de") or normalized in {"antes de"}


def _clamp(value: float, low: float, high: float) -> float:
    return round(max(low, min(high, float(value or 0.0))), 3)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    ascii_text = re.sub(r"[^a-z0-9\s]", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip()
