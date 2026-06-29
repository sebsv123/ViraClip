"""
VPI Publishable Gate v3.1 — Beta Clean clip publishability classification.

Deterministic, local-only heuristic engine that classifies each rendered clip
into one of four publishability statuses:

    READY_TO_UPLOAD  — safe to publish as-is
    REVIEW_MANUALLY  — minor issues, human should check
    NEEDS_FIX        — significant issues, needs rework before upload
    DO_NOT_UPLOAD    — forbidden content detected, must not be published

Input data is gathered from the existing VPI pipeline outputs:
  - segment metadata (editorial_type, vpi_score, matched_patterns)
  - hook_plan (hook_type, hook_first_4s_score, low_publish_priority)
  - editing_activity_score (from editing_plan)
  - broll metadata (categories, asset paths, forbidden detection)
  - output_qc (ClipQualityReport)
  - audio_qc (from audio mastering)
  - silence_plan (SilenceEditPlan)
  - captions/branding status
  - editorial_type
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .vpi_visual_effects_service import get_vpi_visual_design_tokens, validate_vpi_visual_identity

logger = logging.getLogger(__name__)

# OUTPUT-QC-GATE-52A: hard floor for the post-cut editorial complete-idea score. Below this the
# clip is genuinely incomplete and physical-probe reconciliation MUST NOT clear the editorial
# failure. Kept in sync with task_service.MIN_FINAL_COMPLETE_IDEA (0.35), below the accepted
# baseline clip 116fe6db (0.45) and above the egregious incomplete case (0.15).
MIN_FINAL_COMPLETE_IDEA = 0.35


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                loaded = json.loads(text)
                return loaded if isinstance(loaded, dict) else {}
            except Exception:
                return {}
    return {}


def _safe_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _normalize_route_name(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _collect_h4_empirical_metadata(*sources: Any) -> Dict[str, Any]:
    h4_keys = (
        "text_overlap_prevented",
        "suppressed_text_layers",
        "text_layer_count_final",
        "caption_priority_enforced",
        "pip_overlay_disabled",
        "thumbnail_overlay_disabled",
        "debug_preview_overlay_disabled",
        "debug_face_box_rendered",
        "debug_overlays_disabled",
        "caption_timebase_corrected",
        "caption_timebase_source",
        "caption_sync_warning",
        "broll_relevance_gate_passed",
        "broll_relevance_score",
        "broll_skipped_unrelated",
        "bgm_volume_empirical_boost_applied",
        "bgm_target_volume_final",
        "bts_tail_detected",
        "bts_tail_trimmed_seconds",
        "viral_window_shifted_back",
        "viral_window_shift_reason",
        "daily_mode_external_route_active",
        "daily_mode_external_route_names",
        "daily_mode_external_source_allowed",
        "non_production_safe_route_used",
        "stage_recorder",
        "ass_event_count_before",
        "ass_event_hard_cap",
        "ass_events_merged_for_daily",
        "forced_shift_back_applied",
        "selected_alternative_for_complete_idea",
        "incomplete_window_uncorrectable",
    )
    collected: Dict[str, Any] = {}
    normalized_sources = [_as_dict(source) for source in sources]
    for key in h4_keys:
        for source in normalized_sources:
            if key in source and source[key] is not None:
                collected[key] = source[key]
                break
    return collected


def _is_daily_mode_external_render_route(route_name: Any) -> bool:
    normalized = _normalize_route_name(route_name)
    if not normalized:
        return False
    metadata_only_routes = {
        "cta_metadata_only",
        "smart_zoom_metadata_only",
        "no_logo_found_text_watermark_used",
        "hook_render_failed_or_skipped",
        "captions_skipped",
        "text_hook",
        "non_text_push_hook",
        "no_extra_hook",
        "ollama",
        "phi3_ollama",
        "visual_scoring_ollama",
    }
    if normalized in metadata_only_routes:
        return False
    external_render_routes = {
        "comfyui",
        "comfyui_upscale",
        "esrgan_upscale",
        "remotion_overlay_compose",
        "external_pexels",
        "external_broll_provider",
        "semantic_broll_external",
        "t2v",
        "legacy_sound_design",
        "legacy_beat_sync_bgm",
        "rvc",
        "translation_dubbing",
        "tts_dubbing",
        "optical_flow_heavy_transition",
    }
    return normalized in external_render_routes


def _is_task_scoped_output_path(path: Path, task_id: str) -> bool:
    if not task_id:
        return False
    try:
        parts = [part for part in Path(str(path or "")).parts if part]
    except Exception:
        return False
    try:
        outputs_idx = parts.index("outputs")
        tasks_idx = parts.index("tasks")
        task_idx = parts.index(task_id)
    except ValueError:
        return False
    return bool(outputs_idx < tasks_idx < task_idx)


def _probe_media_info(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
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
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=20)
        if proc.returncode != 0:
            return {}
        return json.loads(proc.stdout or "{}")
    except Exception:
        return {}


def _resolve_existing_media_path(path: Path) -> Path:
    candidate = Path(str(path or ""))
    if candidate.exists():
        return candidate
    raw = str(candidate)
    if raw.startswith("/app/"):
        relative = raw.removeprefix("/app/").lstrip("/")
        workspace_candidate = Path.cwd() / relative
        if workspace_candidate.exists():
            return workspace_candidate
    return candidate


def _phase_status(
    *,
    expected: bool,
    applied: bool,
    rendered: bool,
    verified: bool,
    skip_reason: str = "",
    budget_reason: str = "",
    asset_reason: str = "",
) -> str:
    if not expected:
        return "not_expected"
    if verified:
        return "verified"
    if rendered:
        return "rendered_unverified"
    if applied:
        return "applied_unverified"
    skip_blob = " ".join([str(skip_reason or ""), str(budget_reason or ""), str(asset_reason or "")]).lower()
    if any(token in skip_blob for token in ("budget", "collision", "overload")):
        return "skipped_by_budget"
    if any(token in skip_blob for token in ("no_asset", "missing_asset", "asset_missing", "no_local_asset", "no_provider", "no_match")):
        return "skipped_no_asset"
    if any(token in skip_blob for token in ("policy", "intentional", "not_needed", "skip", "no_transition", "no_broll", "no_sfx_moment", "neutral", "captions_sufficient")):
        return "skipped_by_policy"
    return "needs_review"


def _dedupe_strings(values: List[Any]) -> List[str]:
    return list(dict.fromkeys([str(value) for value in values if str(value)]))


def validate_phase_metadata_consistency(
    metadata: dict,
    route_registry: dict,
    final_mp4_contract: dict | None = None,
) -> dict:
    meta = _as_dict(metadata)
    final_contract = _as_dict(final_mp4_contract) or meta
    registry = _as_dict(route_registry)
    phase_meta = _as_dict(meta.get("phase_metadata")) or _as_dict(final_contract.get("phase_metadata"))

    def _phase_source(phase: str, *aliases: str) -> Dict[str, Any]:
        candidates = (
            _as_dict(phase_meta.get(phase)),
            _as_dict(meta.get(phase)),
            _as_dict(meta.get(f"{phase}_metadata")),
            _as_dict(final_contract.get(phase)),
            _as_dict(final_contract.get(f"{phase}_metadata")),
        )
        for alias in aliases:
            candidates += (
                _as_dict(meta.get(alias)),
                _as_dict(final_contract.get(alias)),
            )
        return next((candidate for candidate in candidates if candidate), {})

    def _route_allowed(route_name: str) -> bool:
        normalized = str(route_name or "").strip().lower().replace(" ", "_")
        if not normalized:
            return True
        if normalized.startswith("no_") or normalized.endswith("_skipped") or normalized.endswith("_blocked"):
            return True
        if normalized in {
            "none",
            "skipped",
            "skip",
            "no_transition",
            "no_broll",
            "no_extra_hook",
            "captions_skipped",
            "rhythm_skipped",
            "audio_mastering_skipped",
            "bgm_disabled_by_policy",
            "sfx_disabled_by_policy",
            "blocked_by_contract",
            "ready_after_contract",
            "staged",
            "skipped_by_budget",
            "skipped_no_renderer",
            "skipped_no_asset",
            "external_provider_blocked",
            "legacy_pexels_blocked",
            "legacy_sound_design_blocked",
            "legacy_beat_sync_bgm_blocked",
            "heavy_transition_blocked",
            "optical_flow_blocked",
            "beat_sync_legacy_blocked",
        }:
            return True
        try:
            from .vpi_production_safe_edit import production_safe_route_allowed as _production_safe_route_allowed

            return bool(_production_safe_route_allowed(str(route_name)))
        except Exception:
            return True

    def _phase_bundle(
        phase: str,
        *,
        expected: bool,
        applied: bool,
        rendered: bool,
        verified: bool,
        route_used: str,
        fallback_used: bool,
        fallback_route: str,
        route_blocked: List[str],
        metadata_active: bool,
        status: str,
        backend: str = "",
    ) -> Dict[str, Any]:
        warnings: List[str] = []
        errors: List[str] = []
        route_used_clean = str(route_used or "").strip()
        fallback_route_clean = str(fallback_route or "").strip()
        if metadata_active and not route_used_clean:
            warnings.append("route_used_missing")
        if fallback_used and not fallback_route_clean:
            warnings.append("fallback_route_missing")
        if applied and not rendered and phase in {"visual_reinforcement", "broll", "transitions"}:
            warnings.append("applied_without_rendered")
        if rendered and not verified and phase in {"visual_reinforcement", "broll", "transitions"}:
            warnings.append("rendered_without_verified")
        if phase == "visual_reinforcement" and str(backend or "").strip().lower() == "none" and applied:
            warnings.append("visual_reinforcement_backend_none_but_applied")
        if phase == "transitions" and bool(_as_dict(_phase_source("transitions")).get("transition_sfx_sync_allowed")) and not rendered:
            warnings.append("transition_sfx_sync_allowed_without_render")
        if phase == "broll" and applied and not verified:
            warnings.append("broll_applied_without_verified")
        if phase == "bgm" and applied and not bool(_phase_source("bgm").get("music_mix_verified")):
            warnings.append("bgm_applied_without_music_mix_verified")
        if phase == "sfx" and applied and not bool(_phase_source("sfx").get("sfx_verified")):
            warnings.append("sfx_applied_without_verified")
        if phase == "hook" and bool(_phase_source("hook").get("hook_visual_applied")) and not bool(_phase_source("hook").get("hook_visual_verified")):
            warnings.append("hook_visual_applied_without_verified")
        if expected and applied and not verified and phase in {"captions", "bgm", "sfx", "hook", "rhythm", "audio_mastering", "final_qc"}:
            errors.append("applied_without_verified")
        if phase == "captions" and route_used_clean in {"legacy_caption_service_fallback", "legacy_caption_word_level"}:
            warnings.append("legacy_caption_fallback_used")

        return {
            "expected": bool(expected),
            "applied": bool(applied),
            "rendered": bool(rendered),
            "verified": bool(verified),
            "status": str(status or ("verified" if verified else ("rendered_unverified" if rendered else ("applied_unverified" if applied else "needs_review")))),
            "route_used": route_used_clean,
            "route_blocked": _dedupe_strings(route_blocked),
            "fallback_used": bool(fallback_used),
            "fallback_route": fallback_route_clean,
            "backend": str(backend or ""),
            "metadata_active": bool(metadata_active),
            "warnings": _dedupe_strings(warnings),
            "errors": _dedupe_strings(errors),
        }

    captions = _phase_source("captions", "caption_visual_support", "caption_visual_support_plan", "subtitle_intelligence")
    bgm = _phase_source("bgm", "music")
    sfx = _phase_source("sfx")
    hook = _phase_source("hook", "hook_plan")
    rhythm = _phase_source("rhythm", "silence_edit_plan")
    visual_reinforcement = _phase_source("visual_reinforcement")
    broll = _phase_source("broll")
    transitions = _phase_source("transitions")
    audio_mastering = _phase_source("audio_mastering", "audio_qc")
    final_qc = _phase_source("final_qc", "final_qc_report")

    phase_routes = {
        name: _as_dict(registry.get(name))
        for name in (
            "captions",
            "bgm",
            "sfx",
            "hook",
            "rhythm",
            "visual_reinforcement",
            "broll",
            "transitions",
            "audio_mastering",
            "final_qc",
        )
    }

    final_output_verified = bool(final_contract.get("final_output_verified"))
    final_probe_ok = bool(final_contract.get("final_probe_ok"))
    final_publishable = bool(final_contract.get("final_publishable"))
    final_truth_source = str(meta.get("final_truth_source") or final_contract.get("final_truth_source") or "").strip()
    final_path = Path(str(meta.get("final_output_path") or final_contract.get("final_output_path") or meta.get("path") or ""))
    production_safe = bool(meta.get("production_safe", registry.get("production_safe_compliant", True)))
    final_audio_stream_ok = bool(final_contract.get("final_audio_stream_ok"))
    captions_expected = bool(
        captions.get("captions_rendered")
        or captions.get("has_clean_captions")
        or captions.get("caption_presence")
        or meta.get("has_captions")
        or meta.get("has_ass_captions")
        or meta.get("caption_source")
        or _safe_list(meta.get("words"))
    )
    captions_status = str(meta.get("final_captions_status") or final_contract.get("final_captions_status") or captions.get("status") or "").strip().lower()
    captions_applied = bool(captions.get("applied") or captions.get("captions_applied"))
    captions_rendered = bool(captions.get("rendered") or captions.get("captions_rendered") or captions_expected)
    captions_verified = bool(captions_rendered and final_output_verified)
    bgm_expected = bool(
        bgm.get("music_applied")
        or bgm.get("final_output_uses_bgm")
        or bgm.get("music_track")
        or bgm.get("bgm_asset_path")
        or bgm.get("music_final_verified")
        or bgm.get("music_mix_verified")
        or meta.get("has_bgm")
    )
    bgm_applied = bool(bgm.get("music_applied") or bgm.get("final_output_uses_bgm") or meta.get("final_output_uses_music"))
    bgm_rendered = bool(bgm_applied or bgm.get("music_final_verified") or bgm.get("music_mix_verified"))
    bgm_verified = bool(bgm.get("music_mix_verified") or bgm.get("music_final_verified") or bgm.get("final_output_uses_bgm"))
    sfx_expected = bool(
        sfx.get("sfx_applied")
        or sfx.get("sfx_verified")
        or sfx.get("sfx_event_count")
        or sfx.get("sfx_count")
        or meta.get("final_output_uses_sfx")
        or meta.get("has_sfx")
    )
    sfx_applied = bool(sfx.get("sfx_applied") or sfx.get("sfx_event_count") or sfx.get("sfx_count") or meta.get("final_output_uses_sfx"))
    sfx_rendered = bool(sfx_applied or sfx.get("sfx_verified"))
    sfx_verified = bool(sfx.get("sfx_verified") or sfx.get("sfx_final_verified") or sfx.get("sfx_asset_applied_match"))
    hook_expected = bool(
        hook.get("enabled")
        or hook.get("hook_type")
        or hook.get("hook_visual_applied")
        or hook.get("hook_text")
        or hook.get("hook_strategy_final")
        or meta.get("hook_plan")
    )
    hook_applied = bool(
        hook.get("hook_visual_applied")
        or hook.get("hook_text_overlay_rendered")
        or hook.get("hook_non_text_visual_applied")
        or hook.get("hook_card_applied")
        or hook.get("rendered")
        or hook.get("overlay_rendered")
        or hook.get("hook_visual_verified")
    )
    hook_rendered = bool(hook.get("hook_text_overlay_rendered") or hook.get("hook_non_text_visual_applied") or hook.get("hook_card_applied") or hook.get("rendered") or hook.get("overlay_rendered"))
    hook_verified = bool(hook.get("hook_visual_verified") or hook.get("hook_text_overlay_rendered") or hook.get("hook_non_text_visual_applied") or hook.get("hook_card_applied"))
    rhythm_expected = bool(
        rhythm.get("rendered")
        or rhythm.get("applied")
        or rhythm.get("rhythm_edit_applied")
        or rhythm.get("total_removed_s")
        or rhythm.get("cut_zoom_applied")
        or _safe_list(_as_dict(meta.get("premium_layers_trace")).get("applied") or [])
    )
    rhythm_applied = bool(
        rhythm.get("rendered")
        or rhythm.get("applied")
        or rhythm.get("rhythm_edit_applied")
        or float(rhythm.get("total_removed_s") or 0.0) > 0.0
        or bool(rhythm.get("microcuts") or rhythm.get("preserved_pauses") or rhythm.get("pattern_interruptions"))
    )
    rhythm_rendered = bool(rhythm.get("rendered") or rhythm.get("rhythm_verified"))
    rhythm_verified = bool(rhythm.get("rhythm_verified") or rhythm_rendered or rhythm.get("total_removed_s"))
    visual_reinforcement_expected = bool(visual_reinforcement or meta.get("visual_reinforcement_applied") or meta.get("visual_reinforcement"))
    visual_reinforcement_applied = bool(
        visual_reinforcement.get("visual_reinforcement_applied")
        or visual_reinforcement.get("visual_reinforcement_rendered")
        or meta.get("visual_reinforcement_applied")
    )
    visual_reinforcement_rendered = bool(visual_reinforcement.get("visual_reinforcement_rendered") or meta.get("visual_reinforcement_rendered"))
    visual_reinforcement_verified = bool(visual_reinforcement_rendered)
    broll_items = _safe_list(broll.get("items") or meta.get("editorial_broll"))
    broll_expected = bool(broll_items or broll.get("broll_editorial_decision") or broll.get("broll_applied") or broll.get("broll_rendered") or meta.get("has_broll"))
    broll_applied = bool(broll.get("broll_applied") or broll.get("broll_rendered") or broll.get("broll_verified") or broll_items)
    broll_rendered = bool(broll.get("broll_rendered") or broll.get("broll_verified"))
    broll_verified = bool(broll.get("broll_verified") or any(bool((item or {}).get("broll_final_verified")) for item in broll_items))
    transitions_expected = bool(
        transitions.get("transition_planned")
        or transitions.get("transitions_applied")
        or transitions.get("transition_strategy")
        or transitions.get("transition_events")
        or meta.get("has_transition")
    )
    transitions_applied = bool(
        transitions.get("transition_rendered")
        or transitions.get("transition_verified")
        or transitions.get("transitions_applied")
        or transitions.get("final_output_uses_transition")
        or meta.get("final_output_uses_transition")
    )
    transitions_rendered = bool(transitions.get("transition_rendered") or transitions.get("transition_verified") or meta.get("final_output_uses_transition"))
    transitions_verified = bool(transitions.get("transition_verified") or transitions.get("final_output_uses_transition"))
    audio_mastering_expected = bool(
        audio_mastering.get("audio_mastering_applied")
        or audio_mastering.get("mastering_applied")
        or audio_mastering.get("audio_mastering_fallback")
        or bgm.get("audio_mastering_applied")
        or meta.get("audio_mastering_applied")
    )
    audio_mastering_applied = bool(audio_mastering.get("audio_mastering_applied") or audio_mastering.get("mastering_applied") or meta.get("audio_mastering_applied"))
    audio_mastering_rendered = bool(audio_mastering_applied or audio_mastering.get("output_lufs") is not None or audio_mastering.get("audio_voice_status"))
    audio_mastering_verified = bool(audio_mastering_rendered or audio_mastering.get("audio_voice_status"))
    final_qc_expected = bool(final_qc or meta.get("final_qc") or meta.get("final_qc_status") or final_contract)
    final_qc_applied = bool(final_qc or meta.get("final_qc") or meta.get("final_qc_status"))
    final_qc_rendered = bool(final_qc_applied or final_contract.get("final_qc_status"))
    # H13.2 Fix A — `final_qc_verified` must reflect whether the final-QC evaluation was actually
    # COMPUTED with real pipeline data (report built + contract present + probe ran + boundary
    # metadata present + blocking decided), NOT whether the clip ended up publishable. The
    # previous `bool(final_publishable)` definition made it circular: any clip blocked for a
    # genuine editorial reason (e.g. incomplete_viral_window / low complete_idea_score) would
    # automatically also get `final_qc_applied_without_verified` / `applied_without_verified`,
    # adding `metadata_consistency_failed` as a redundant 4th blocking reason that echoes the
    # same root verdict instead of reporting an independent metadata contradiction.
    _embedded_qc_for_verification = _as_dict(final_qc) or _as_dict(final_contract.get("final_qc"))
    final_qc_report_built = bool(_embedded_qc_for_verification)
    final_mp4_contract_present = bool(_as_dict(final_mp4_contract)) or bool(final_contract)
    final_probe_data_present = final_contract.get("final_probe_ok") is not None
    boundary_confidence_present = (
        final_contract.get("boundary_confidence") is not None
        or meta.get("boundary_confidence") is not None
    )
    final_blocking_calculated = (
        final_contract.get("final_blocking_reasons") is not None
        or final_contract.get("final_publishable") is not None
    )
    final_qc_computed_with_real_data = bool(
        final_qc_report_built
        and final_mp4_contract_present
        and final_probe_data_present
        and boundary_confidence_present
        and final_blocking_calculated
    )
    final_qc_verified = final_qc_computed_with_real_data
    if final_qc_verified and not final_publishable:
        logger.info(
            "VPI_METADATA_CONSISTENCY_VERIFIED_WITH_QC_FAILURE task_id=%s final_blocking_reasons=%s",
            str(meta.get("task_id") or "unknown"),
            "|".join(_safe_list(final_contract.get("final_blocking_reasons"))) or "none",
        )
        logger.info(
            "VPI_METADATA_CONSISTENCY_CIRCULAR_ECHO_SUPPRESSED task_id=%s would_be_error=final_qc_applied_without_verified",
            str(meta.get("task_id") or "unknown"),
        )

    phase_consistency = {
        "captions": _phase_bundle(
            "captions",
            expected=captions_expected,
            applied=captions_applied,
            rendered=captions_rendered,
            verified=captions_verified,
            route_used=str(phase_routes["captions"].get("route_used") or ""),
            fallback_used=bool(phase_routes["captions"].get("fallback_used")),
            fallback_route=str(phase_routes["captions"].get("fallback_route") or ""),
            route_blocked=_safe_list(phase_routes["captions"].get("routes_blocked")),
            metadata_active=bool(captions or captions_expected),
            status=captions_status,
        ),
        "bgm": _phase_bundle(
            "bgm",
            expected=bgm_expected,
            applied=bgm_applied,
            rendered=bgm_rendered,
            verified=bgm_verified,
            route_used=str(phase_routes["bgm"].get("route_used") or ""),
            fallback_used=bool(phase_routes["bgm"].get("fallback_used")),
            fallback_route=str(phase_routes["bgm"].get("fallback_route") or ""),
            route_blocked=_safe_list(phase_routes["bgm"].get("routes_blocked")),
            metadata_active=bool(bgm or bgm_expected),
            status=str(final_contract.get("final_bgm_status") or bgm.get("status") or ""),
        ),
        "sfx": _phase_bundle(
            "sfx",
            expected=sfx_expected,
            applied=sfx_applied,
            rendered=sfx_rendered,
            verified=sfx_verified,
            route_used=str(phase_routes["sfx"].get("route_used") or ""),
            fallback_used=bool(phase_routes["sfx"].get("fallback_used")),
            fallback_route=str(phase_routes["sfx"].get("fallback_route") or ""),
            route_blocked=_safe_list(phase_routes["sfx"].get("routes_blocked")),
            metadata_active=bool(sfx or sfx_expected),
            status=str(final_contract.get("final_sfx_status") or sfx.get("status") or ""),
        ),
        "hook": _phase_bundle(
            "hook",
            expected=hook_expected,
            applied=hook_applied,
            rendered=hook_rendered,
            verified=hook_verified,
            route_used=str(phase_routes["hook"].get("route_used") or ""),
            fallback_used=bool(phase_routes["hook"].get("fallback_used")),
            fallback_route=str(phase_routes["hook"].get("fallback_route") or ""),
            route_blocked=_safe_list(phase_routes["hook"].get("routes_blocked")),
            metadata_active=bool(hook or hook_expected),
            status=str(final_contract.get("final_hook_status") or hook.get("status") or ""),
        ),
        "rhythm": _phase_bundle(
            "rhythm",
            expected=rhythm_expected,
            applied=rhythm_applied,
            rendered=rhythm_rendered,
            verified=rhythm_verified,
            route_used=str(phase_routes["rhythm"].get("route_used") or ""),
            fallback_used=bool(phase_routes["rhythm"].get("fallback_used")),
            fallback_route=str(phase_routes["rhythm"].get("fallback_route") or ""),
            route_blocked=_safe_list(phase_routes["rhythm"].get("routes_blocked")),
            metadata_active=bool(rhythm or rhythm_expected),
            status=str(final_contract.get("final_rhythm_status") or rhythm.get("status") or ""),
        ),
        "visual_reinforcement": _phase_bundle(
            "visual_reinforcement",
            expected=visual_reinforcement_expected,
            applied=visual_reinforcement_applied,
            rendered=visual_reinforcement_rendered,
            verified=visual_reinforcement_verified,
            route_used=str(phase_routes["visual_reinforcement"].get("route_used") or ""),
            fallback_used=bool(phase_routes["visual_reinforcement"].get("fallback_used")),
            fallback_route=str(phase_routes["visual_reinforcement"].get("fallback_route") or ""),
            route_blocked=_safe_list(phase_routes["visual_reinforcement"].get("routes_blocked")),
            metadata_active=bool(visual_reinforcement or visual_reinforcement_expected),
            status=str(final_contract.get("final_visual_reinforcement_status") or visual_reinforcement.get("status") or ""),
            backend=str(visual_reinforcement.get("visual_reinforcement_backend") or ""),
        ),
        "broll": _phase_bundle(
            "broll",
            expected=broll_expected,
            applied=broll_applied,
            rendered=broll_rendered,
            verified=broll_verified,
            route_used=str(phase_routes["broll"].get("route_used") or ""),
            fallback_used=bool(phase_routes["broll"].get("fallback_used")),
            fallback_route=str(phase_routes["broll"].get("fallback_route") or ""),
            route_blocked=_safe_list(phase_routes["broll"].get("routes_blocked")),
            metadata_active=bool(broll or broll_expected),
            status=str(final_contract.get("final_broll_status") or broll.get("status") or ""),
        ),
        "transitions": _phase_bundle(
            "transitions",
            expected=transitions_expected,
            applied=transitions_applied,
            rendered=transitions_rendered,
            verified=transitions_verified,
            route_used=str(phase_routes["transitions"].get("route_used") or ""),
            fallback_used=bool(phase_routes["transitions"].get("fallback_used")),
            fallback_route=str(phase_routes["transitions"].get("fallback_route") or ""),
            route_blocked=_safe_list(phase_routes["transitions"].get("routes_blocked")),
            metadata_active=bool(transitions or transitions_expected),
            status=str(final_contract.get("final_transition_status") or transitions.get("status") or ""),
        ),
        "audio_mastering": _phase_bundle(
            "audio_mastering",
            expected=audio_mastering_expected,
            applied=audio_mastering_applied,
            rendered=audio_mastering_rendered,
            verified=audio_mastering_verified,
            route_used=str(phase_routes["audio_mastering"].get("route_used") or ""),
            fallback_used=bool(phase_routes["audio_mastering"].get("fallback_used")),
            fallback_route=str(phase_routes["audio_mastering"].get("fallback_route") or ""),
            route_blocked=_safe_list(phase_routes["audio_mastering"].get("routes_blocked")),
            metadata_active=bool(audio_mastering or audio_mastering_expected),
            status=str(final_contract.get("final_audio_mastering_status") or audio_mastering.get("status") or ""),
        ),
        "final_qc": _phase_bundle(
            "final_qc",
            expected=final_qc_expected,
            applied=final_qc_applied,
            rendered=final_qc_rendered,
            verified=final_qc_verified,
            route_used=str(phase_routes["final_qc"].get("route_used") or ""),
            fallback_used=bool(phase_routes["final_qc"].get("fallback_used")),
            fallback_route=str(phase_routes["final_qc"].get("fallback_route") or ""),
            route_blocked=_safe_list(phase_routes["final_qc"].get("routes_blocked")),
            metadata_active=bool(final_qc or final_qc_expected),
            status=str(final_contract.get("final_qc_status") or final_qc.get("status") or ""),
        ),
    }

    errors: List[str] = []
    warnings: List[str] = []

    if final_output_verified and not final_probe_ok:
        errors.append("final_output_verified_but_final_probe_failed")
    if final_publishable and not bool(final_contract.get("final_publishable", final_publishable)):
        errors.append("final_publishable_but_contract_not_publishable")
    final_output_is_task_scoped = _is_task_scoped_output_path(final_path, str(meta.get("task_id") or ""))
    # H13.2 Fix A (cont.) — detect REAL cross-artifact contradictions, as opposed to the
    # circular echo removed above. We compare editorial-identity fields (boundary_confidence,
    # complete_idea_score, incomplete_viral_window_detected) between the outer/truth contract
    # and the embedded final_qc_report's frozen final_mp4_contract snapshot. These fields are
    # computed ONCE at candidate-selection time and must stay identical across pipeline stages
    # — unlike technical/probe fields (final_probe_ok, final_output_path, final_duration_ok),
    # which legitimately differ between an embedded earlier-stage snapshot and the final
    # verified output (the known stale-snapshot-embedding pattern; not a contradiction).
    real_contradiction_errors: List[str] = []
    _embedded_contract_for_contradiction = _as_dict(_embedded_qc_for_verification.get("final_mp4_contract"))
    if _embedded_contract_for_contradiction:
        for _field, _tolerance in (("boundary_confidence", 0.05), ("complete_idea_score", 0.05)):
            _outer_val = final_contract.get(_field)
            _inner_val = _embedded_contract_for_contradiction.get(_field)
            if _outer_val is None or _inner_val is None:
                continue
            try:
                if abs(float(_outer_val) - float(_inner_val)) > _tolerance:
                    real_contradiction_errors.append(f"{_field}_contradiction")
            except (TypeError, ValueError):
                if str(_outer_val).strip() != str(_inner_val).strip():
                    real_contradiction_errors.append(f"{_field}_contradiction")
        _outer_incomplete = final_contract.get("incomplete_viral_window_detected")
        _inner_incomplete = _embedded_contract_for_contradiction.get("incomplete_viral_window_detected")
        if (
            _outer_incomplete is not None
            and _inner_incomplete is not None
            and bool(_outer_incomplete) != bool(_inner_incomplete)
        ):
            real_contradiction_errors.append("incomplete_viral_window_detected_contradiction")
    if real_contradiction_errors:
        errors.extend(real_contradiction_errors)
        logger.warning(
            "VPI_METADATA_CONSISTENCY_REAL_CONTRADICTION task_id=%s contradictions=%s",
            str(meta.get("task_id") or "unknown"),
            "|".join(real_contradiction_errors),
        )
    if production_safe and final_truth_source and final_truth_source not in {"final_mp4_contract", "task_scoped_output"}:
        errors.append("final_truth_source_mismatch")
    if captions_expected and captions_status in {"failed", "missing"}:
        errors.append("captions_expected_but_failed_or_missing")
    if captions_expected and not captions_verified:
        errors.append("captions_expected_but_unverified")
    audio_expected = bool(
        bgm_expected
        or sfx_expected
        or audio_mastering_expected
        or meta.get("has_audio")
        or meta.get("audio_features")
        or meta.get("audio_qc")
        or meta.get("transcript")
        or meta.get("text")
        or _safe_list(meta.get("words"))
        or meta.get("final_output_uses_music")
        or meta.get("final_output_uses_sfx")
    )
    if audio_expected and not final_audio_stream_ok:
        errors.append("audio_expected_but_final_audio_stream_missing")
    if production_safe and not bool(registry.get("production_safe_compliant", True)):
        non_safe_used = [
            phase
            for phase, bundle in phase_consistency.items()
            if bundle["route_used"] and not _route_allowed(bundle["route_used"]) and not bundle["route_blocked"]
        ]
        if non_safe_used:
            errors.append("production_safe_route_used")
    for phase_name in ("captions", "bgm", "sfx", "hook", "rhythm", "audio_mastering", "final_qc"):
        bundle = _as_dict(phase_consistency.get(phase_name))
        if bundle["applied"] and not bundle["verified"]:
            errors.append(f"{phase_name}_applied_without_verified")
    for phase_name, bundle_raw in phase_consistency.items():
        bundle = _as_dict(bundle_raw)
        warnings.extend(bundle["warnings"])
        errors.extend(bundle["errors"])
        if bundle["applied"] and not bundle["rendered"] and phase_name in {"visual_reinforcement", "broll", "transitions"}:
            warnings.append(f"{phase_name}_applied_without_rendered")
        if bundle["rendered"] and not bundle["verified"] and phase_name in {"visual_reinforcement", "broll", "transitions"}:
            warnings.append(f"{phase_name}_rendered_without_verified")

    if bool(transitions.get("transition_sfx_sync_allowed")) and not bool(transitions.get("transition_rendered")):
        warnings.append("transition_sfx_sync_allowed_but_transition_not_rendered")
    if broll_applied and not broll_verified:
        warnings.append("broll_applied_but_unverified")
    if bgm_applied and not bool(bgm.get("music_mix_verified")):
        warnings.append("bgm_applied_but_music_mix_unverified")
    if sfx_applied and not sfx_verified:
        warnings.append("sfx_applied_but_unverified")
    if bool(hook.get("hook_visual_applied")) and not bool(hook.get("hook_visual_verified")):
        warnings.append("hook_visual_applied_but_unverified")
    if production_safe and not _safe_list(registry.get("production_safe_routes_blocked")):
        legacy_or_external_route_names = {
            "comfyui",
            "t2v",
            "ollama",
            "external_pexels",
            "external_broll_provider",
            "remotion_overlay_compose",
            "legacy_sound_design",
            "legacy_beat_sync_bgm",
            "optical_flow_heavy_transition",
        }
        any_suspicious_route = any(
            str(bundle.get("route_used") or "").strip().lower() in legacy_or_external_route_names
            or str(bundle.get("fallback_route") or "").strip().lower() in legacy_or_external_route_names
            or "legacy" in str(bundle.get("route_used") or "").lower()
            or "external" in str(bundle.get("route_used") or "").lower()
            for bundle in phase_consistency.values()
        )
        if any_suspicious_route:
            warnings.append("production_safe_routes_blocked_empty")

    metadata_consistency_ok = len(errors) == 0
    metadata_consistency = {
        "metadata_consistency_ok": bool(metadata_consistency_ok),
        "metadata_consistency_errors": _dedupe_strings(errors),
        "metadata_consistency_warnings": _dedupe_strings(warnings),
        "phase_consistency": phase_consistency,
    }
    event_name = (
        "METADATA_CONSISTENCY_PASSED"
        if metadata_consistency_ok and not warnings
        else ("METADATA_CONSISTENCY_WARNING" if warnings and not errors else "METADATA_CONSISTENCY_FAILED")
    )
    logger.info(
        "METADATA_CONSISTENCY_CHECKED event=%s ok=%s errors=%d warnings=%d route_compliant=%s",
        event_name,
        str(metadata_consistency_ok).lower(),
        len(metadata_consistency["metadata_consistency_errors"]),
        len(metadata_consistency["metadata_consistency_warnings"]),
        str(bool(registry.get("production_safe_compliant", True))).lower(),
    )
    return metadata_consistency


def build_final_mp4_contract(
    *,
    final_output_path: str | Path,
    expected_duration_s: float | None = None,
    clip_info: Optional[Dict[str, Any]] = None,
    final_qc_report: Optional[Dict[str, Any]] = None,
    production_safe: bool = False,
    captions_metadata: Optional[Dict[str, Any]] = None,
    bgm_metadata: Optional[Dict[str, Any]] = None,
    sfx_metadata: Optional[Dict[str, Any]] = None,
    hook_metadata: Optional[Dict[str, Any]] = None,
    rhythm_metadata: Optional[Dict[str, Any]] = None,
    visual_layer_budget_metadata: Optional[Dict[str, Any]] = None,
    visual_reinforcement_metadata: Optional[Dict[str, Any]] = None,
    broll_metadata: Optional[Dict[str, Any]] = None,
    transitions_metadata: Optional[Dict[str, Any]] = None,
    audio_mastering_metadata: Optional[Dict[str, Any]] = None,
    task_id: str = "",
    clip_order: int = 0,
) -> Dict[str, Any]:
    clip = _as_dict(clip_info)
    qc_report = _as_dict(final_qc_report)
    cap = _as_dict(captions_metadata) or _as_dict(clip.get("caption_visual_support")) or _as_dict(clip.get("caption_visual_support_plan")) or _as_dict(clip.get("subtitle_intelligence"))
    bgm = _as_dict(bgm_metadata) or _as_dict(clip.get("music"))
    sfx = _as_dict(sfx_metadata) or _as_dict(clip.get("sfx"))
    hook = _as_dict(hook_metadata) or _as_dict(clip.get("hook_plan"))
    cta = _as_dict(clip.get("cta")) or _as_dict(clip.get("editing_plan"))
    rhythm = _as_dict(rhythm_metadata) or _as_dict(clip.get("silence_edit_plan"))
    budget = _as_dict(visual_layer_budget_metadata) or _as_dict(_as_dict(clip.get("editing_plan")).get("visual_layer_budget"))
    visual_reinforcement = _as_dict(visual_reinforcement_metadata) or _as_dict(clip.get("visual_reinforcement"))
    broll = _as_dict(broll_metadata) or {"items": _safe_list(clip.get("editorial_broll"))}
    transitions = _as_dict(transitions_metadata) or _as_dict(clip.get("transitions"))
    audio_master = _as_dict(audio_mastering_metadata) or _as_dict(clip.get("audio_qc")) or _as_dict(clip.get("music"))
    route_registry = _as_dict(clip.get("route_registry"))
    try:
        from .vpi_production_safe_edit import (
            get_production_safe_policy,
            get_vpi_daily_mode_policy,
            get_vpi_premium_flow_manifest,
            production_safe_mode_active,
            validate_premium_flow_manifest,
        )
        from .vpi_audio_mastering import analyze_audio_loudness as _analyze_audio_loudness

        production_safe_policy = get_production_safe_policy()
        daily_mode_policy = get_vpi_daily_mode_policy()
        premium_flow_manifest = get_vpi_premium_flow_manifest()
        production_safe_active = bool(production_safe_mode_active())
    except Exception:
        production_safe_policy = {}
        daily_mode_policy = {}
        premium_flow_manifest = {}
        production_safe_active = bool(production_safe)
        validate_premium_flow_manifest = None  # type: ignore[assignment]
        _analyze_audio_loudness = None  # type: ignore[assignment]
    hook_plan = hook
    final_path = _resolve_existing_media_path(Path(str(final_output_path or "")))
    probe = _probe_media_info(final_path) if final_path.exists() else {}
    streams = _safe_list(probe.get("streams"))
    format_info = _as_dict(probe.get("format"))
    video_stream = next((s for s in streams if isinstance(s, dict) and str(s.get("codec_type") or "") == "video"), {})
    audio_stream = next((s for s in streams if isinstance(s, dict) and str(s.get("codec_type") or "") == "audio"), {})
    has_video_stream = bool(video_stream)
    has_audio_stream = bool(audio_stream)
    file_size = int(final_path.stat().st_size or 0) if final_path.exists() else 0
    try:
        actual_duration = float(
            format_info.get("duration")
            or _as_dict(video_stream).get("duration")
            or clip.get("duration")
            or expected_duration_s
            or 0.0
        )
    except Exception:
        actual_duration = float(expected_duration_s or clip.get("duration") or 0.0)
    has_audio_expected = bool(
        clip.get("has_audio")
        or clip.get("audio_features")
        or clip.get("audio_qc")
        or clip.get("transcript")
        or clip.get("text")
        or clip.get("words")
        or (qc_report.get("audio_score") is not None)
        or bool(bgm.get("music_applied"))
        or bool(sfx.get("sfx_applied"))
        or bool(_as_dict(clip.get("final_rendered_contract")).get("has_audio", False))
    )
    video_stream_ok = bool(has_video_stream and int(_as_dict(video_stream).get("width") or 0) > 0 and int(_as_dict(video_stream).get("height") or 0) > 0)
    audio_stream_ok = bool(has_audio_stream or not has_audio_expected)
    duration_ok = bool(actual_duration > 0.0)
    expected_duration_mismatch_s = 0.0
    if expected_duration_s and expected_duration_s > 0:
        tolerance = max(1.5, min(4.0, float(expected_duration_s) * 0.12))
        expected_duration_mismatch_s = abs(actual_duration - float(expected_duration_s))
        if expected_duration_mismatch_s > tolerance:
            logger.info(
                "VPI_FINAL_CONTRACT_DURATION_RECONCILED task_id=%s clip_order=%d expected=%.3f physical=%.3f mismatch=%.3f",
                task_id or "unknown",
                clip_order,
                float(expected_duration_s),
                float(actual_duration),
                float(expected_duration_mismatch_s),
            )
    file_size_ok = bool(file_size > 0)
    probe_ok = bool(final_path.exists() and file_size_ok and video_stream_ok and duration_ok and (audio_stream_ok or not has_audio_expected))
    final_video_exists = bool(final_path.exists() and file_size_ok)
    final_video_stream_ok = bool(video_stream_ok)
    final_audio_stream_ok = bool(audio_stream_ok)
    final_file_size_ok = bool(file_size_ok)
    final_duration_ok = bool(duration_ok)
    final_output_verified = bool(final_video_exists and final_video_stream_ok and (final_audio_stream_ok or not has_audio_expected) and final_duration_ok)
    final_audio_analysis: Dict[str, Any] = {}
    if final_path.exists() and callable(_analyze_audio_loudness):
        try:
            final_audio_analysis = _as_dict(_analyze_audio_loudness(str(final_path)))
        except Exception as exc:
            final_audio_analysis = {
                "audio_analysis_available": False,
                "analysis_error": str(exc),
            }
    final_audio_analysis_available = bool(final_audio_analysis.get("audio_analysis_available"))
    final_audio_silence_likely = bool(
        final_audio_analysis_available and final_audio_analysis.get("silence_likely")
    )
    final_audio_too_quiet = bool(
        final_audio_analysis_available and final_audio_analysis.get("too_quiet")
    )
    final_audio_clipping_risk = bool(
        final_audio_analysis_available and final_audio_analysis.get("clipping_risk")
    )
    if not final_audio_analysis_available and final_audio_stream_ok:
        final_audio_loudness_ok = True
    else:
        final_audio_loudness_ok = bool(final_audio_stream_ok and not final_audio_silence_likely)

    captions_expected = bool(
        clip.get("final_captions_expected")
        if clip.get("final_captions_expected") is not None
        else (
        cap.get("captions_rendered")
        or cap.get("has_clean_captions")
        or cap.get("caption_presence")
        or clip.get("has_captions")
        or clip.get("has_ass_captions")
        or clip.get("caption_source")
        or clip.get("words")
        or bool(_as_dict(_as_dict(clip.get("final_rendered_contract")).get("evidence_sources", {})).get("filename_markers", {}).get("captions"))
        )
    )
    captions_present = bool(
        clip.get("final_captions_present")
        if clip.get("final_captions_present") is not None
        else (
        cap.get("captions_rendered")
        or cap.get("applied")
        or cap.get("rendered")
        or clip.get("has_ass_captions")
        or _as_dict(_as_dict(clip.get("final_rendered_contract")).get("evidence_sources", {})).get("final_output_flags", {}).get("captions")
        )
    )
    captions_status = _phase_status(
        expected=captions_expected,
        applied=bool(cap.get("applied") or cap.get("captions_applied")),
        rendered=bool(cap.get("rendered") or cap.get("captions_rendered") or captions_present),
        verified=bool(captions_present and final_video_exists and final_video_stream_ok),
        skip_reason=str(cap.get("caption_fallback_reason") or clip.get("caption_fallback_reason") or ""),
    )

    bgm_expected = bool(
        bgm.get("music_applied")
        or bgm.get("final_output_uses_bgm")
        or bgm.get("music_track")
        or bgm.get("bgm_asset_path")
        or bgm.get("music_final_verified")
        or bool(_as_dict(_as_dict(clip.get("final_rendered_contract")).get("evidence_sources", {})).get("final_output_flags", {}).get("music"))
    )
    bgm_applied = bool(
        bgm.get("music_applied")
        or bgm.get("final_output_uses_bgm")
        or clip.get("final_output_uses_music")
    )
    bgm_verified = bool(bgm.get("music_final_verified") or bgm.get("final_output_uses_bgm") or _as_dict(_as_dict(clip.get("final_rendered_contract")).get("evidence_sources", {})).get("final_output_flags", {}).get("music"))
    bgm_status = _phase_status(
        expected=bgm_expected,
        applied=bgm_applied,
        rendered=bool(bgm_verified),
        verified=bool(bgm_verified),
        skip_reason=str(bgm.get("music_warning") or bgm.get("music_status") or bgm.get("skip_reason") or ""),
        budget_reason=str((audio_master or {}).get("music_warning") or ""),
    )

    sfx_expected = bool(
        sfx.get("sfx_applied")
        or sfx.get("sfx_verified")
        or sfx.get("sfx_event_count")
        or sfx.get("sfx_count")
        or bool(_as_dict(_as_dict(clip.get("final_rendered_contract")).get("evidence_sources", {})).get("final_output_flags", {}).get("sfx"))
    )
    sfx_applied = bool(sfx.get("sfx_applied") or sfx.get("sfx_event_count") or sfx.get("sfx_count"))
    sfx_verified = bool(sfx.get("sfx_verified") or sfx.get("sfx_final_verified") or sfx.get("sfx_asset_applied_match"))
    sfx_status = _phase_status(
        expected=sfx_expected,
        applied=sfx_applied,
        rendered=bool(sfx_applied or sfx_verified),
        verified=bool(sfx_verified and final_video_exists and final_video_stream_ok),
        skip_reason=str(sfx.get("sfx_warning") or sfx.get("sfx_status") or sfx.get("skip_reason") or ""),
        budget_reason=str(sfx.get("budget_drop_reason") or ""),
        asset_reason=str(sfx.get("sfx_asset_missing_reason") or ""),
    )

    hook_expected = bool(
        hook.get("enabled")
        or hook.get("hook_type")
        or hook.get("hook_visual_applied")
        or hook.get("hook_text")
        or hook.get("hook_strategy_final")
        or clip.get("hook_plan")
    )
    hook_applied = bool(
        hook.get("hook_visual_applied")
        or hook.get("hook_text_overlay_rendered")
        or hook.get("hook_non_text_visual_applied")
        or hook.get("hook_card_applied")
        or hook.get("rendered")
        or hook.get("overlay_rendered")
    )
    hook_verified = bool(
        hook.get("hook_visual_verified")
        or hook.get("hook_text_overlay_rendered")
        or hook.get("hook_non_text_visual_applied")
        or hook.get("hook_card_applied")
    )
    hook_status = _phase_status(
        expected=hook_expected,
        applied=hook_applied,
        rendered=hook_applied,
        verified=hook_verified,
        skip_reason=str(hook.get("hook_strategy_reason") or hook.get("hook_redundancy_reason") or hook.get("hook_missing_reason") or ""),
    )
    if str(hook.get("hook_strategy_final") or "").strip() == "no_extra_hook" and str(hook.get("hook_strategy_reason") or "").strip() in {"captions_sufficient", "visual_density_high", "clip_too_short", "redundancy_with_captions", "caption_redundancy"}:
        hook_status = "skipped_by_policy"

    rhythm_expected = bool(
        rhythm.get("rendered")
        or rhythm.get("applied")
        or rhythm.get("rhythm_edit_applied")
        or rhythm.get("total_removed_s")
        or rhythm.get("cut_zoom_applied")
        or bool(_safe_list(_as_dict(clip.get("premium_layers_trace")).get("applied") or []))
    )
    rhythm_applied = bool(
        rhythm.get("rendered")
        or rhythm.get("applied")
        or rhythm.get("rhythm_edit_applied")
        or float(rhythm.get("total_removed_s") or 0.0) > 0.0
        or bool(rhythm.get("microcuts") or rhythm.get("preserved_pauses") or rhythm.get("pattern_interruptions"))
    )
    rhythm_verified = bool(rhythm.get("rhythm_verified") or rhythm.get("rendered") or rhythm.get("total_removed_s"))
    rhythm_status = _phase_status(
        expected=rhythm_expected,
        applied=rhythm_applied,
        rendered=bool(rhythm.get("rendered") or rhythm.get("rhythm_verified")),
        verified=bool(rhythm_verified),
        skip_reason=str(rhythm.get("rhythm_skip_reason") or rhythm.get("skip_reason") or ""),
    )

    visual_budget_expected = bool(budget)
    visual_budget_applied = bool(budget.get("applied") or budget.get("visual_layer_budget_applied") or budget.get("collision_guard_applied"))
    visual_budget_verified = bool(visual_budget_applied)
    visual_budget_status = _phase_status(
        expected=visual_budget_expected,
        applied=visual_budget_applied,
        rendered=visual_budget_applied,
        verified=visual_budget_verified,
        skip_reason=str(budget.get("reason") or budget.get("collision_guard_reasons") or ""),
        budget_reason=str(budget.get("temporal_density_reason") or ""),
    )

    visual_reinforcement_expected = bool(visual_reinforcement)
    visual_reinforcement_applied = bool(visual_reinforcement.get("visual_reinforcement_applied") or visual_reinforcement.get("visual_reinforcement_rendered"))
    visual_reinforcement_verified = bool(visual_reinforcement.get("visual_reinforcement_rendered"))
    visual_reinforcement_status = _phase_status(
        expected=visual_reinforcement_expected,
        applied=visual_reinforcement_applied,
        rendered=visual_reinforcement_applied,
        verified=visual_reinforcement_verified,
        skip_reason=str(visual_reinforcement.get("visual_reinforcement_dropped_reason") or visual_reinforcement.get("visual_reinforcement_reason") or ""),
        budget_reason=str(visual_reinforcement.get("visual_renderer_fallback_used") or ""),
        asset_reason=str(visual_reinforcement.get("visual_reinforcement_asset") or ""),
    )

    broll_items = _safe_list(_as_dict(broll).get("items")) if isinstance(broll, dict) else _safe_list(clip.get("editorial_broll"))
    broll_expected = bool(
        broll_items
        or broll.get("broll_editorial_decision")
        or broll.get("broll_applied")
        or broll.get("broll_rendered")
    )
    broll_applied = bool(
        broll.get("broll_applied")
        or broll.get("broll_rendered")
        or broll.get("broll_verified")
        or broll_items
    )
    broll_verified = bool(broll.get("broll_verified") or any(bool((item or {}).get("broll_final_verified")) for item in broll_items))
    broll_status = _phase_status(
        expected=broll_expected,
        applied=broll_applied,
        rendered=bool(broll.get("broll_rendered") or broll.get("broll_verified")),
        verified=broll_verified,
        skip_reason=str(broll.get("broll_skip_reason") or broll.get("reason") or ""),
        budget_reason=str(broll.get("broll_budget_allowed") is False and "budget_blocked" or ""),
        asset_reason=str(broll.get("broll_asset_source") or broll.get("broll_asset_id") or ""),
    )

    transitions_expected = bool(
        transitions.get("transition_planned")
        or transitions.get("transitions_applied")
        or transitions.get("transition_strategy")
        or transitions.get("transition_events")
    )
    transitions_applied = bool(
        transitions.get("transition_rendered")
        or transitions.get("transition_verified")
        or transitions.get("transitions_applied")
        or transitions.get("final_output_uses_transition")
    )
    transitions_verified = bool(transitions.get("transition_verified") or transitions.get("final_output_uses_transition"))
    transition_status = _phase_status(
        expected=transitions_expected,
        applied=transitions_applied,
        rendered=bool(transitions.get("transition_rendered") or transitions.get("transition_verified")),
        verified=transitions_verified,
        skip_reason=str(transitions.get("transition_skip_reason") or ""),
        budget_reason=str(transitions.get("transition_budget_exhausted") and "budget_exhausted" or ""),
    )
    if not transitions_expected:
        transition_status = "not_expected"

    audio_mastering_expected = bool(
        audio_master.get("audio_mastering_applied")
        or audio_master.get("mastering_applied")
        or audio_master.get("audio_mastering_fallback")
        or bool(bgm.get("audio_mastering_applied"))
    )
    audio_mastering_applied = bool(audio_master.get("audio_mastering_applied") or audio_master.get("mastering_applied"))
    audio_mastering_verified = bool(audio_mastering_applied or audio_master.get("output_lufs") is not None or audio_master.get("audio_voice_status"))
    audio_mastering_status = _phase_status(
        expected=audio_mastering_expected,
        applied=audio_mastering_applied,
        rendered=audio_mastering_applied,
        verified=audio_mastering_verified,
        skip_reason=str(audio_master.get("audio_mastering_fallback") or audio_master.get("audio_warning") or ""),
    )
    mastering_improved_audio = bool(
        clip.get("mastering_improved_audio")
        if clip.get("mastering_improved_audio") is not None
        else audio_master.get("mastering_improved_audio", False)
    )
    mastering_rejected_reason = str(
        clip.get("mastering_rejected_reason")
        or audio_master.get("mastering_rejected_reason")
        or audio_master.get("audio_mastering_skip_reason")
        or ""
    )

    final_rendered_contract = _as_dict(clip.get("final_rendered_contract"))
    final_contract = _as_dict(final_rendered_contract) or {}
    final_output_is_task_scoped = _is_task_scoped_output_path(final_path, str(task_id or ""))
    final_truth_source = "task_scoped_output" if final_output_is_task_scoped else "final_mp4_contract"
    final_output_truth = _as_dict(clip.get("final_output_truth")) or _as_dict(final_contract.get("final_output_truth"))
    if final_output_truth:
        truth_path = _resolve_existing_media_path(
            Path(
                str(
                    final_output_truth.get("final_output_path")
                    or final_output_truth.get("final_output_path_host_or_relative")
                    or final_output_truth.get("final_output_path_container")
                    or final_path
                    or ""
                )
            )
        )
        if truth_path.exists():
            final_path = truth_path
            final_output_is_task_scoped = _is_task_scoped_output_path(final_path, str(task_id or ""))
            final_truth_source = "task_scoped_output" if final_output_is_task_scoped else "final_mp4_contract"
            probe = _probe_media_info(final_path) or probe
            streams = _safe_list(probe.get("streams"))
            format_info = _as_dict(probe.get("format"))
            video_stream = next((s for s in streams if isinstance(s, dict) and str(s.get("codec_type") or "") == "video"), video_stream)
            audio_stream = next((s for s in streams if isinstance(s, dict) and str(s.get("codec_type") or "") == "audio"), audio_stream)
            has_video_stream = bool(video_stream)
            has_audio_stream = bool(audio_stream)
            file_size = int(final_path.stat().st_size or 0)
            try:
                actual_duration = float(
                    final_output_truth.get("final_duration")
                    or format_info.get("duration")
                    or _as_dict(video_stream).get("duration")
                    or clip.get("duration")
                    or expected_duration_s
                    or 0.0
                )
            except Exception:
                actual_duration = float(expected_duration_s or clip.get("duration") or 0.0)
            final_video_exists = bool(final_output_truth.get("final_output_exists") if final_output_truth.get("final_output_exists") is not None else final_video_exists)
            final_video_stream_ok = bool(final_output_truth.get("final_video_stream_ok") if final_output_truth.get("final_video_stream_ok") is not None else final_video_stream_ok)
            final_audio_stream_ok = bool(final_output_truth.get("final_audio_stream_ok") if final_output_truth.get("final_audio_stream_ok") is not None else final_audio_stream_ok)
            final_file_size_ok = bool(final_output_truth.get("final_file_size") if final_output_truth.get("final_file_size") is not None else final_file_size_ok)
            final_duration_ok = bool(actual_duration > 0.0)
            probe_ok = bool(final_output_truth.get("final_probe_ok") if final_output_truth.get("final_probe_ok") is not None else probe_ok)
            final_output_verified = bool(final_output_truth.get("final_output_verified") if final_output_truth.get("final_output_verified") is not None else final_output_verified)
        if bool(final_output_truth.get("final_output_verified")) and bool(final_output_truth.get("final_probe_ok")):
            logger.info(
                "VPI_FINAL_QC_OLD_PROBE_BLOCKING_SUPPRESSED task_id=%s clip_order=%d path=%s",
                task_id or "unknown",
                clip_order,
                str(final_output_truth.get("final_output_path") or final_output_truth.get("final_output_path_container") or final_path),
            )
    # OUTPUT-QC-GATE-52A: physical truth may reconcile STALE PHYSICAL metadata, but it must NEVER
    # convert an editorially-incomplete idea into a complete one. Compute the post-cut completeness
    # and forbid the gap-only suppression when the final idea is genuinely incomplete.
    _gate_complete_idea_raw = (
        clip.get("complete_idea_score")
        if clip.get("complete_idea_score") is not None
        else final_contract.get("complete_idea_score")
    )
    final_idea_editorially_incomplete = False
    final_complete_idea_score_for_gate = 0.0
    if _gate_complete_idea_raw is not None:
        try:
            final_complete_idea_score_for_gate = float(_gate_complete_idea_raw)
            final_idea_editorially_incomplete = final_complete_idea_score_for_gate < MIN_FINAL_COMPLETE_IDEA
        except Exception:
            final_idea_editorially_incomplete = False
    final_qc_metadata_gap_only = False
    if final_output_verified and final_output_is_task_scoped and qc_report and str(qc_report.get("final_qc_status") or "").upper() == "FAIL":
        qc_reason_set = set(str(item) for item in _safe_list(qc_report.get("reasons")) if str(item))
        qc_gap_only_reasons = {
            "editorial_integrity_failed",
            "final_mp4_contract_final_qc_failed",
            "final_mp4_contract_final_qc_severe",
            "final_mp4_contract_audio_identity_mismatch",
            "final_mp4_contract_metadata_consistency_failed",
            "final_mp4_contract_blocked_publishable",
            "final_mp4_contract_sfx_rendered_unverified",
        }
        if final_video_stream_ok and final_duration_ok and probe_ok:
            qc_gap_only_reasons.update(
                {
                    "render_safety_failed",
                    "final_mp4_contract_invalid_duration",
                    "final_mp4_contract_unreadable_output",
                    "final_mp4_contract_render_safety_failed",
                }
            )
        if (not qc_reason_set or qc_reason_set.issubset(qc_gap_only_reasons)) and not final_idea_editorially_incomplete:
            final_qc_metadata_gap_only = True
            qc_report = dict(qc_report)
            qc_report["final_qc_status"] = "PASS"
            if str(qc_report.get("upload_recommendation") or "").upper() == "DO_NOT_UPLOAD":
                qc_report["upload_recommendation"] = "REVIEW_BEFORE_UPLOAD"
            qc_report["severe"] = False
            qc_report["reasons"] = []
            qc_report["warnings"] = list(
                dict.fromkeys(
                    _safe_list(qc_report.get("warnings"))
                    + ["final_mp4_contract_metadata_gap_only"]
                )
            )
            logger.info(
                "VPI_FINAL_CONTRACT_STALE_FIELD_IGNORED task_id=%s clip_order=%d fields=%s reason=physical_probe_passed",
                task_id or "unknown",
                clip_order,
                "|".join(sorted(qc_reason_set)) or "none",
            )
            final_qc_report = qc_report
            final_qc_verified = True
    final_blocking_reasons: List[str] = []
    final_warning_reasons: List[str] = []
    warnings: List[str] = []
    errors: List[str] = []
    final_warning_reasons.extend([str(x) for x in _safe_list(qc_report.get("warnings")) if str(x)])
    hook_plan = hook
    phase_consistency = _as_dict(clip.get("phase_consistency")) or _as_dict(final_rendered_contract.get("phase_consistency")) or {}
    route_registry_compliant = bool(route_registry.get("production_safe_compliant", True))
    route_registry_blocked = _safe_list(route_registry.get("production_safe_routes_blocked"))
    route_registry_legacy_blocked = _safe_list(route_registry.get("legacy_routes_blocked"))
    route_registry_external_blocked = _safe_list(route_registry.get("external_routes_blocked"))
    route_registry_fallbacks = _safe_list(route_registry.get("fallback_routes_used"))
    route_registry_primaries = _safe_list(route_registry.get("primary_routes_used"))

    all_route_names = set()
    for bundle in phase_consistency.values():
        for key in ("route_used", "fallback_route"):
            route_name = str(bundle.get(key) or "").strip()
            if route_name:
                all_route_names.add(route_name)
        for route_name in _safe_list(bundle.get("route_blocked")):
            route_name = str(route_name or "").strip()
            if route_name:
                all_route_names.add(route_name)

    legacy_routes_quarantined: List[str] = []
    experimental_routes_quarantined: List[str] = []
    deprecated_routes_present: List[str] = []
    deprecated_routes_used: List[str] = []
    deprecated_routes_blocked: List[str] = []
    legacy_route_warning: List[str] = []
    caption_legacy_routes = {"legacy_caption_service_fallback", "legacy_caption_word_level"}
    try:
        from .vpi_production_safe_edit import legacy_route_status, is_legacy_or_experimental_route

        for route_name in sorted(all_route_names):
            if not is_legacy_or_experimental_route(route_name):
                continue
            status_info = legacy_route_status(route_name)
            status = str(status_info.get("status") or "quarantined")
            deprecated_routes_present.append(route_name)
            legacy_routes_quarantined.append(route_name)
            legacy_route_warning.append(f"{route_name}:{status}")
            if status == "experimental":
                experimental_routes_quarantined.append(route_name)
            for phase_name, bundle_raw in phase_consistency.items():
                bundle = _as_dict(bundle_raw)
                if route_name and route_name == str(bundle.get("route_used") or "").strip():
                    deprecated_routes_used.append(route_name)
                    if route_name in _safe_list(bundle.get("route_blocked")):
                        deprecated_routes_blocked.append(route_name)
                if route_name and route_name == str(bundle.get("fallback_route") or "").strip():
                    deprecated_routes_used.append(route_name)
        deprecated_routes_present = _dedupe_strings(deprecated_routes_present)
        deprecated_routes_used = _dedupe_strings(deprecated_routes_used)
        deprecated_routes_blocked = _dedupe_strings(deprecated_routes_blocked)
        legacy_routes_quarantined = _dedupe_strings(legacy_routes_quarantined)
        experimental_routes_quarantined = _dedupe_strings(experimental_routes_quarantined)
        legacy_route_warning = _dedupe_strings(legacy_route_warning)
    except Exception:
        pass

    if production_safe and deprecated_routes_used:
        if any(route_name not in caption_legacy_routes for route_name in deprecated_routes_used):
            errors.append("deprecated_routes_used_in_production_safe")
        else:
            warnings.append("legacy_caption_fallback_used")
    if final_qc_metadata_gap_only and "final_mp4_contract_metadata_gap_only" not in final_warning_reasons:
        final_warning_reasons.append("final_mp4_contract_metadata_gap_only")
    if expected_duration_mismatch_s > 0:
        final_warning_reasons.append("physical_duration_reconciled_from_post_render_probe")

    if route_registry and production_safe and not route_registry_compliant:
        final_warning_reasons.append("non_production_safe_route_used")
    if not final_video_exists:
        final_blocking_reasons.append("missing_final_file")
    if final_video_exists and not final_video_stream_ok:
        final_blocking_reasons.append("missing_video_stream")
    if final_video_exists and has_audio_expected and not final_audio_stream_ok:
        final_blocking_reasons.append("missing_audio_stream")
    if final_audio_silence_likely:
        final_blocking_reasons.append("final_audio_silence_likely")
    if not final_duration_ok:
        final_blocking_reasons.append("invalid_duration")
    if not probe_ok:
        final_blocking_reasons.append("unreadable_output")
    if captions_expected and not captions_present:
        final_blocking_reasons.append("captions_missing")
    if final_qc_report and str(final_qc_report.get("final_qc_status") or "").upper() == "FAIL":
        final_blocking_reasons.append("final_qc_failed")
    if final_qc_report and bool(final_qc_report.get("severe")):
        final_blocking_reasons.append("final_qc_severe")
    # OUTPUT-QC-GATE-52A: hard, non-reconcilable editorial blocker for a genuinely incomplete final
    # idea. Kept distinct from final_qc_failed/severe so no physical-probe gap-only allowlist can
    # clear it downstream (neither here nor in task_service._build_publishable_qc).
    if final_idea_editorially_incomplete and "rejected_incomplete_final_idea" not in final_blocking_reasons:
        final_blocking_reasons.append("rejected_incomplete_final_idea")
        logger.info(
            "VPI_FINAL_EDITORIAL_REJECT_INCOMPLETE_IDEA task_id=%s clip_order=%d complete_idea=%.4f threshold=%.2f reason=physical_truth_cannot_complete_idea",
            task_id or "unknown", clip_order, final_complete_idea_score_for_gate, MIN_FINAL_COMPLETE_IDEA,
        )
    if final_audio_too_quiet:
        final_warning_reasons.append("final_audio_too_quiet")
    if final_audio_clipping_risk:
        final_warning_reasons.append("final_audio_clipping_risk")

    critical_phase_contradictions = []
    for phase_name, status, expected in (
        ("captions", captions_status, captions_expected),
        ("bgm", bgm_status, bgm_expected),
        ("hook", hook_status, hook_expected),
        ("rhythm", rhythm_status, rhythm_expected),
        ("transition", transition_status, transitions_expected),
    ):
        if expected and status in {"applied_unverified", "rendered_unverified", "failed"}:
            critical_phase_contradictions.append(f"{phase_name}_{status}")
    sfx_rendered_unverified_downgraded = False
    sfx_rendered_unverified_downgrade_reason = ""
    if sfx_expected and sfx_status in {"applied_unverified", "rendered_unverified"}:
        _sfx_output_valid = bool(probe_ok and final_audio_stream_ok and final_duration_ok)
        if _sfx_output_valid:
            final_warning_reasons.append(f"sfx_{sfx_status}")
            sfx_rendered_unverified_downgraded = True
            sfx_rendered_unverified_downgrade_reason = "optional_or_expected_audio_pipeline_with_valid_output"
            logger.info(
                "VPI_SFX_RENDERED_UNVERIFIED_DOWNGRADED_VALID_OUTPUT task_id=%s clip_order=%d sfx_status=%s probe_ok=%s audio_ok=%s",
                task_id or "unknown",
                clip_order,
                sfx_status,
                str(probe_ok).lower(),
                str(final_audio_stream_ok).lower(),
            )
        else:
            critical_phase_contradictions.append(f"sfx_{sfx_status}")
            logger.warning(
                "VPI_SFX_RENDERED_UNVERIFIED_BLOCKING_INVALID_OUTPUT task_id=%s clip_order=%d sfx_status=%s probe_ok=%s audio_ok=%s",
                task_id or "unknown",
                clip_order,
                sfx_status,
                str(probe_ok).lower(),
                str(final_audio_stream_ok).lower(),
            )
    elif sfx_expected and sfx_status == "failed":
        critical_phase_contradictions.append("sfx_failed")
        logger.warning(
            "VPI_SFX_RENDERED_UNVERIFIED_BLOCKING_REQUIRED_MISSING task_id=%s clip_order=%d sfx_status=%s",
            task_id or "unknown",
            clip_order,
            sfx_status,
        )
    if captions_expected and captions_status != "verified":
        final_blocking_reasons.append("captions_unverified")
    if has_audio_expected and not final_audio_stream_ok:
        final_blocking_reasons.append("audio_missing")
    if critical_phase_contradictions:
        final_blocking_reasons.extend(critical_phase_contradictions)

    audio_chain_plan = _as_dict(clip.get("audio_chain_plan"))
    audio_chain_state = _as_dict(clip.get("audio_chain_state"))
    base_voice_audio_present = bool(
        clip.get("base_voice_audio_present")
        or clip.get("has_audio")
        or clip.get("audio_features")
        or clip.get("audio_qc")
        or clip.get("transcript")
        or clip.get("text")
        or clip.get("words")
        or audio_master.get("audio_voice_status")
    )
    audio_duplicate_passes_blocked = _safe_list(
        audio_chain_state.get("audio_duplicate_passes_blocked") or clip.get("audio_duplicate_passes_blocked")
    )
    bgm_pass_count = int(audio_chain_state.get("bgm_pass_count") or clip.get("bgm_pass_count") or 0)
    sfx_pass_count = int(audio_chain_state.get("sfx_pass_count") or clip.get("sfx_pass_count") or 0)
    bgm_final_status = str(
        clip.get("bgm_final_status")
        or bgm.get("bgm_final_status")
        or bgm.get("music_status")
        or ("verified" if bgm_verified else "skipped_no_event")
    ).strip()
    sfx_final_status = str(
        clip.get("sfx_final_status")
        or sfx.get("sfx_final_status")
        or sfx.get("sfx_status")
        or ("verified" if sfx_verified else "skipped_no_event")
    ).strip()
    audio_mastering_final_status = str(
        clip.get("audio_mastering_final_status")
        or audio_master.get("audio_mastering_skip_reason")
        or audio_master.get("audio_mastering_method")
        or ("verified" if audio_mastering_verified else "skipped")
    ).strip()
    final_audio_chain_errors: List[str] = []
    final_audio_chain_warnings: List[str] = []
    if has_audio_expected and not final_audio_stream_ok:
        final_audio_chain_errors.append("final_audio_stream_missing")
    if (has_audio_expected or bool(clip.get("transcript") or clip.get("text") or clip.get("words"))) and not base_voice_audio_present:
        if final_audio_stream_ok:
            final_audio_chain_warnings.append("base_voice_audio_missing")
        else:
            final_audio_chain_errors.append("base_voice_audio_missing")
    if audio_mastering_required := bool(audio_master.get("audio_mastering_required") or clip.get("audio_mastering_required")):
        if not bool(audio_master.get("audio_mastering_applied")) and not bool(audio_master.get("audio_mastering_fallback_to_premaster")):
            if final_audio_stream_ok:
                final_audio_chain_warnings.append("audio_mastering_not_applied")
            else:
                final_audio_chain_errors.append("audio_mastering_failed_without_fallback")
    if bgm_expected and bgm_final_status in {"failed", "duplicate_blocked"}:
        final_audio_chain_warnings.append(f"bgm_{bgm_final_status}")
    if sfx_expected and sfx_final_status in {"failed", "duplicate_blocked"}:
        final_audio_chain_warnings.append(f"sfx_{sfx_final_status}")
    if bgm_final_status == "skipped_by_policy":
        final_audio_chain_warnings.append("bgm_skipped_by_policy")
    if sfx_final_status in {"skipped_by_policy", "skipped_no_event"}:
        pass
    if audio_master.get("audio_mastering_fallback_to_premaster"):
        final_audio_chain_warnings.append("audio_mastering_fallback_to_premaster")
    if audio_duplicate_passes_blocked:
        final_audio_chain_warnings.append("audio_duplicate_passes_blocked")
    final_audio_chain_ok = bool(not final_audio_chain_errors)
    if final_audio_chain_errors:
        final_blocking_reasons.append("audio_chain_failed")
    elif final_audio_chain_warnings:
        final_warning_reasons.append("audio_chain_warning")

    audio_editorial_profile = str(clip.get("audio_editorial_profile") or "").strip()
    audio_editorial_profile_reason = str(clip.get("audio_editorial_profile_reason") or "").strip()
    music_mood_selected = str(clip.get("music_mood_selected") or bgm.get("music_mood_selected") or "").strip()
    music_asset_id = str(clip.get("music_asset_id") or bgm.get("music_asset_id") or bgm.get("bgm_asset_id") or "").strip()
    music_selection_reason = str(clip.get("music_selection_reason") or bgm.get("music_selection_reason") or "").strip()
    music_fallback_used = bool(clip.get("music_fallback_used") or bgm.get("music_fallback_used"))
    music_reuse_reason = str(clip.get("music_reuse_reason") or bgm.get("music_reuse_reason") or "").strip()
    sfx_editorial_profile = str(clip.get("sfx_editorial_profile") or sfx.get("sfx_editorial_profile") or "").strip()
    sfx_allowed_families = _safe_list(clip.get("sfx_allowed_families") or sfx.get("sfx_allowed_families"))
    sfx_blocked_families = _safe_list(clip.get("sfx_blocked_families") or sfx.get("sfx_blocked_families"))
    sfx_family_selected = str(clip.get("sfx_family_selected") or sfx.get("sfx_family_selected") or "").strip()
    sfx_variation_ids = [str(item) for item in _safe_list(clip.get("sfx_variation_ids") or sfx.get("sfx_variation_ids")) if str(item)]
    sfx_selection_reason = str(clip.get("sfx_selection_reason") or sfx.get("sfx_selection_reason") or "").strip()
    sfx_reuse_reason = str(clip.get("sfx_reuse_reason") or sfx.get("sfx_reuse_reason") or "").strip()
    vpi_audio_identity_ok = bool(clip.get("vpi_audio_identity_ok") if clip.get("vpi_audio_identity_ok") is not None else True)
    vpi_audio_identity_warnings = [str(item) for item in _safe_list(clip.get("vpi_audio_identity_warnings")) if str(item)]
    audio_asset_inventory_summary = _as_dict(clip.get("audio_asset_inventory_summary"))
    audio_asset_coverage_ok = bool(clip.get("audio_asset_coverage_ok"))
    missing_music_moods = [str(item) for item in _safe_list(clip.get("missing_music_moods")) if str(item)]
    missing_sfx_families = [str(item) for item in _safe_list(clip.get("missing_sfx_families")) if str(item)]
    weak_music_moods = [str(item) for item in _safe_list(clip.get("weak_music_moods")) if str(item)]
    weak_sfx_families = [str(item) for item in _safe_list(clip.get("weak_sfx_families")) if str(item)]
    sensitive_sober_available = bool(clip.get("sensitive_sober_available"))
    music_asset_taxonomy_used = str(clip.get("music_asset_taxonomy_used") or bgm.get("music_asset_taxonomy_used") or "").strip()
    sfx_asset_taxonomy_used = str(clip.get("sfx_asset_taxonomy_used") or sfx.get("sfx_asset_taxonomy_used") or "").strip()
    sensitive_audio_asset_blocked = bool(clip.get("sensitive_audio_asset_blocked"))
    audio_identity_mismatch_downgraded = False
    audio_identity_mismatch_downgrade_reason = ""
    metadata_consistency_failed_downgraded = False
    metadata_consistency_downgrade_reason = ""
    if vpi_audio_identity_warnings:
        final_warning_reasons.append("vpi_audio_identity_warning")
        _audio_mastering_pipeline_active = bool(
            audio_mastering_expected
            or audio_mastering_applied
            or audio_mastering_verified
            or bgm_expected
            or bgm_applied
        )
        _audio_final_valid = bool(
            final_audio_stream_ok
            and probe_ok
            and final_duration_ok
            and not final_audio_silence_likely
        )
        if _audio_mastering_pipeline_active and _audio_final_valid:
            final_warning_reasons.append("audio_identity_mismatch")
            final_warning_reasons.append("audio_identity_changed_by_expected_mastering")
            audio_identity_mismatch_downgraded = True
            audio_identity_mismatch_downgrade_reason = "expected_audio_mastering"
            logger.info(
                "VPI_AUDIO_IDENTITY_MISMATCH_DOWNGRADED_EXPECTED_MASTERING task_id=%s clip_order=%d mastering_applied=%s bgm_expected=%s audio_stream_ok=%s",
                task_id or "unknown",
                clip_order,
                str(audio_mastering_applied).lower(),
                str(bgm_expected).lower(),
                str(final_audio_stream_ok).lower(),
            )
        elif not _audio_final_valid:
            final_blocking_reasons.append("audio_identity_mismatch")
            logger.warning(
                "VPI_AUDIO_IDENTITY_MISMATCH_BLOCKING_INVALID_AUDIO task_id=%s clip_order=%d audio_stream_ok=%s probe_ok=%s duration_ok=%s",
                task_id or "unknown",
                clip_order,
                str(final_audio_stream_ok).lower(),
                str(probe_ok).lower(),
                str(final_duration_ok).lower(),
            )
        else:
            final_blocking_reasons.append("audio_identity_mismatch")
            logger.warning(
                "VPI_AUDIO_IDENTITY_MISMATCH_BLOCKING_UNEXPECTED task_id=%s clip_order=%d sensitive_blocked=%s",
                task_id or "unknown",
                clip_order,
                str(sensitive_audio_asset_blocked).lower(),
            )
    if not audio_asset_coverage_ok and (missing_music_moods or missing_sfx_families):
        final_warning_reasons.append("audio_asset_coverage_gap")
    if audio_editorial_profile == "sensitive_sober" and sfx_family_selected:
        vpi_audio_identity_ok = False
        vpi_audio_identity_warnings = list(dict.fromkeys(vpi_audio_identity_warnings + ["sensitive_profile_sfx_forbidden"]))
        final_blocking_reasons.append("sensitive_audio_identity_violation")
    if audio_editorial_profile == "sensitive_sober" and (music_mood_selected not in {"sensitive_sober", "calm_trust", "no_extra_audio", "cinematic_ambient"}):
        vpi_audio_identity_ok = False
        vpi_audio_identity_warnings = list(dict.fromkeys(vpi_audio_identity_warnings + ["sensitive_profile_music_mismatch"]))
        final_warning_reasons.append("sensitive_profile_music_mismatch")
    if audio_editorial_profile == "sensitive_sober" and not vpi_audio_identity_ok:
        final_blocking_reasons.append("sensitive_audio_identity_failed")
    if final_audio_silence_likely:
        final_blocking_reasons.append("final_audio_silence_likely")
        final_audio_chain_errors.append("final_audio_silence_likely")
        logger.warning(
            "FINAL_AUDIO_SILENCE_DETECTED task_id=%s clip_order=%d mean_db=%s max_db=%s lufs=%s",
            task_id or "unknown",
            clip_order,
            final_audio_analysis.get("mean_volume_db"),
            final_audio_analysis.get("max_volume_db"),
            final_audio_analysis.get("integrated_lufs"),
        )

    _commercial_strength = float(clip.get("commercial_usefulness_score") or 0.0)
    if _commercial_strength <= 1.0:
        _commercial_strength *= 100.0
    weak_editorial_segment = bool(
        clip.get("weak_editorial_segment")
        or float(clip.get("hookability_score") or 0.0) < 45.0
        or float(clip.get("standalone_score") or 0.0) < 45.0
        or _commercial_strength < 40.0
        or float(clip.get("vpi_score") or 0.0) < 35.0
    )
    if weak_editorial_segment:
        final_warning_reasons.append("weak_editorial_segment")
        logger.warning(
            "VPI_SEGMENT_REJECTED_REASON task_id=%s clip_order=%d reason=weak_editorial_segment hook=%.2f standalone=%.2f commercial=%.2f vpi=%.2f",
            task_id or "unknown",
            clip_order,
            float(clip.get("hookability_score") or 0.0),
            float(clip.get("standalone_score") or 0.0),
            float(clip.get("commercial_usefulness_score") or 0.0),
            float(clip.get("vpi_score") or 0.0),
        )
    boundary_confidence = float(
        clip.get("boundary_confidence")
        if clip.get("boundary_confidence") is not None
        else final_contract.get("boundary_confidence")
        if final_contract.get("boundary_confidence") is not None
        else final_output_truth.get("boundary_confidence")
        if final_output_truth.get("boundary_confidence") is not None
        else 0.0
    )
    if boundary_confidence <= 0.0:
        final_warning_reasons.append("no_boundary_confidence")
        final_blocking_reasons.append("no_boundary_confidence")
    elif boundary_confidence < 0.55:
        final_warning_reasons.append("low_boundary_confidence")
    if not bool(clip.get("starts_cleanly", True)):
        final_warning_reasons.append("weak_clip_start")
    if not bool(clip.get("payoff_preserved", True)):
        final_warning_reasons.append("payoff_may_be_cut")
    package_diversity_score = float(clip.get("package_diversity_score") or final_contract.get("package_diversity_score") or 0.0)
    package_category_distribution = dict(clip.get("package_category_distribution") or final_contract.get("package_category_distribution") or {})
    package_theme_distribution = dict(clip.get("package_theme_distribution") or final_contract.get("package_theme_distribution") or {})
    package_diversity_warnings = list(clip.get("package_diversity_warnings") or final_contract.get("package_diversity_warnings") or [])
    campaign_intent = str(clip.get("campaign_intent") or final_contract.get("campaign_intent") or "general_vpi")
    campaign_intent_confidence = float(clip.get("campaign_intent_confidence") or final_contract.get("campaign_intent_confidence") or 0.0)
    campaign_intent_source = str(clip.get("campaign_intent_source") or final_contract.get("campaign_intent_source") or "default_general")
    campaign_intent_reason = str(clip.get("campaign_intent_reason") or final_contract.get("campaign_intent_reason") or "")
    campaign_alignment_score = float(clip.get("campaign_alignment_score") or final_contract.get("campaign_alignment_score") or 0.0)
    campaign_alignment_reason = str(clip.get("campaign_alignment_reason") or final_contract.get("campaign_alignment_reason") or "")
    campaign_boost_applied = bool(clip.get("campaign_boost_applied") if clip.get("campaign_boost_applied") is not None else final_contract.get("campaign_boost_applied"))
    campaign_boost_score = float(clip.get("campaign_boost_score") or final_contract.get("campaign_boost_score") or 0.0)
    selected_campaign_mix = dict(clip.get("selected_campaign_mix") or final_contract.get("selected_campaign_mix") or {})
    campaign_alignment_summary = dict(clip.get("campaign_alignment_summary") or final_contract.get("campaign_alignment_summary") or {})
    preferred_categories = list(clip.get("preferred_categories") or final_contract.get("preferred_categories") or [])
    suppressed_categories = list(clip.get("suppressed_categories") or final_contract.get("suppressed_categories") or [])
    preferred_keywords = list(clip.get("preferred_keywords") or final_contract.get("preferred_keywords") or [])
    sensitive_handling_required = bool(clip.get("sensitive_handling_required") if clip.get("sensitive_handling_required") is not None else final_contract.get("sensitive_handling_required"))
    if package_diversity_score and package_diversity_score < 0.35:
        final_warning_reasons.append("package_diversity_low")
    if package_category_distribution and len(package_category_distribution) == 1 and len(package_category_distribution) >= 1:
        final_warning_reasons.append("package_single_category")
    if sum(1 for value in package_theme_distribution.values() if int(value) > 1) > 2:
        final_warning_reasons.append("package_theme_repeat")
    if package_diversity_warnings:
        final_warning_reasons.extend([str(x) for x in package_diversity_warnings if str(x)])
    selected_for_reason = str(clip.get("selected_for_reason") or final_contract.get("selected_for_reason") or "")
    output_clip_count = int(clip.get("output_clip_count") or final_contract.get("output_clip_count") or 0)
    if selected_for_reason == "diversity_fill" and output_clip_count <= 1:
        final_warning_reasons.append("diversity_fill_not_allowed_for_top1")
        logger.warning(
            "VPI_SELECTION_DIVERSITY_FILL_BLOCKED_FOR_TOP1 task_id=%s clip_order=%d output_clip_count=%d boundary_confidence=%.4f",
            task_id or "unknown",
            clip_order,
            output_clip_count,
            boundary_confidence,
        )
    hook_lower_third_rendered = bool(
        clip.get("hook_lower_third_rendered")
        if clip.get("hook_lower_third_rendered") is not None
        else final_contract.get("hook_lower_third_rendered")
    )
    ass_event_count_final = int(clip.get("ass_event_count_final") or final_contract.get("ass_event_count_final") or 0)
    ass_approx_simple_mode = bool(
        clip.get("ass_approx_simple_mode")
        if clip.get("ass_approx_simple_mode") is not None
        else final_contract.get("ass_approx_simple_mode")
    )
    selection_complete_idea_score = float(
        clip.get("complete_idea_score")
        if clip.get("complete_idea_score") is not None
        else final_contract.get("complete_idea_score") or 0.0
    )
    selection_incomplete_viral_window_detected = bool(
        clip.get("incomplete_viral_window_detected")
        if clip.get("incomplete_viral_window_detected") is not None
        else final_contract.get("incomplete_viral_window_detected")
    )
    # Final closure/timeline truth is written by the render/timeline stage under
    # editing_plan in the live path. Treat top-level selection fields as historical.
    final_closure_contained = bool(
        clip.get("final_closure_contained")
        if clip.get("final_closure_contained") is not None
        else cta.get("final_closure_contained")
        if cta.get("final_closure_contained") is not None
        else final_contract.get("final_closure_contained")
    )
    final_timeline_gate_passed = bool(
        clip.get("publishability_timeline_gate_passed")
        if clip.get("publishability_timeline_gate_passed") is not None
        else cta.get("publishability_timeline_gate_passed")
        if cta.get("publishability_timeline_gate_passed") is not None
        else cta.get("final_timeline_gate_passed")
        if cta.get("final_timeline_gate_passed") is not None
        else final_contract.get("publishability_timeline_gate_passed")
    )
    final_audio_sync_verified = bool(
        clip.get("audio_sync_verified")
        if clip.get("audio_sync_verified") is not None
        else cta.get("audio_sync_verified")
        if cta.get("audio_sync_verified") is not None
        else final_contract.get("audio_sync_verified")
    )
    final_text_complete = bool(
        final_closure_contained
        and (final_timeline_gate_passed or final_audio_sync_verified)
        and not bool(
            clip.get("speech_truncation_detected")
            or cta.get("speech_truncation_detected")
            or final_contract.get("speech_truncation_detected")
        )
    )
    incomplete_viral_window_detected = bool(selection_incomplete_viral_window_detected and not final_text_complete)
    final_contract_reconciled = bool(selection_incomplete_viral_window_detected and final_text_complete)
    reconciliation_reason = "post_render_truth" if final_contract_reconciled else ""
    if final_contract_reconciled:
        final_warning_reasons.append("selection_incomplete_viral_window_reconciled_by_final_closure")
        logger.info(
            "VPI_FINAL_CONTRACT_TEXT_RECONCILED task_id=%s clip_order=%d selection_complete_idea=%.4f final_closure=%s timeline=%s audio_sync=%s",
            task_id or "unknown",
            clip_order,
            selection_complete_idea_score,
            str(final_closure_contained).lower(),
            str(final_timeline_gate_passed).lower(),
            str(final_audio_sync_verified).lower(),
        )
    viral_window_shifted_back = bool(
        clip.get("viral_window_shifted_back")
        if clip.get("viral_window_shifted_back") is not None
        else final_contract.get("viral_window_shifted_back")
    )
    if hook_lower_third_rendered and _is_vpi_daily_mode_active():
        final_warning_reasons.append("hook_lower_third_visible_daily")
        final_blocking_reasons.append("hook_lower_third_visible_daily")
        logger.warning(
            "VPI_HOOK_LOWER_THIRD_VISIBLE_DAILY task_id=%s clip_order=%d hook_lower_third_rendered=%s",
            task_id or "unknown",
            clip_order,
            str(hook_lower_third_rendered).lower(),
        )
    if ass_approx_simple_mode and ass_event_count_final > 24:
        final_warning_reasons.append("captions_too_dense_daily")
        final_blocking_reasons.append("captions_too_dense_daily")
        logger.warning(
            "VPI_CAPTIONS_TOO_DENSE_DAILY task_id=%s clip_order=%d ass_event_count_final=%d",
            task_id or "unknown",
            clip_order,
            ass_event_count_final,
        )
    if incomplete_viral_window_detected and not (
        viral_window_shifted_back
        or bool(clip.get("forced_shift_back_applied"))
        or bool(final_contract.get("forced_shift_back_applied"))
        or bool(clip.get("selected_alternative_for_complete_idea"))
        or bool(final_contract.get("selected_alternative_for_complete_idea"))
    ):
        final_warning_reasons.append("incomplete_viral_window")
        final_blocking_reasons.append("incomplete_viral_window")
        logger.warning(
            "VPI_INCOMPLETE_VIRAL_WINDOW task_id=%s clip_order=%d complete_idea=%.4f boundary=%.4f",
            task_id or "unknown",
            clip_order,
            float(clip.get("complete_idea_score") or final_contract.get("complete_idea_score") or 0.0),
            boundary_confidence,
        )
    if campaign_intent != "general_vpi":
        if campaign_alignment_score < 0.35:
            final_warning_reasons.append("campaign_intent_low_alignment")
        if campaign_intent == "decesos" and not sensitive_handling_required:
            final_warning_reasons.append("decesos_without_sensitive_handling")
    clip_brief = dict(clip.get("clip_brief") or final_contract.get("clip_brief") or {})
    clip_angle = str(clip.get("clip_angle") or final_contract.get("clip_angle") or clip_brief.get("clip_angle") or "")
    clip_value_proposition = str(clip.get("clip_value_proposition") or final_contract.get("clip_value_proposition") or clip_brief.get("clip_value_proposition") or "")
    clip_campaign_fit = dict(clip.get("clip_campaign_fit") or final_contract.get("clip_campaign_fit") or clip_brief.get("clip_campaign_fit") or {})
    clip_recommended_cta = str(clip.get("clip_recommended_cta") or final_contract.get("clip_recommended_cta") or clip_brief.get("clip_recommended_cta") or "")
    clip_confidence_label = str(clip.get("clip_confidence_label") or final_contract.get("clip_confidence_label") or clip_brief.get("clip_confidence_label") or "")
    clip_review_flags = list(clip.get("clip_review_flags") or final_contract.get("clip_review_flags") or clip_brief.get("clip_review_flags") or [])
    clip_publish_notes = str(clip.get("clip_publish_notes") or final_contract.get("clip_publish_notes") or clip_brief.get("clip_publish_notes") or "")
    clip_brief_summary = dict(clip.get("clip_brief_summary") or final_contract.get("clip_brief_summary") or {})
    high_confidence_clip_count = int(clip.get("high_confidence_clip_count") or final_contract.get("high_confidence_clip_count") or clip_brief_summary.get("high_confidence_clip_count") or 0)
    review_clip_count = int(clip.get("review_clip_count") or final_contract.get("review_clip_count") or clip_brief_summary.get("review_clip_count") or 0)
    campaign_fit_summary = dict(clip.get("campaign_fit_summary") or final_contract.get("campaign_fit_summary") or clip_brief_summary.get("campaign_fit_summary") or {})
    if clip_confidence_label == "low":
        final_warning_reasons.append("clip_brief_low_confidence")
    if "sensitive_requires_review" in clip_review_flags:
        final_warning_reasons.append("sensitive_requires_review")
    if "weak_editorial_segment" in clip_review_flags:
        final_warning_reasons.append("weak_editorial_segment")
    if not bool(clip.get("caption_duration_balance_ok") if clip.get("caption_duration_balance_ok") is not None else _as_dict(cap).get("caption_duration_balance_ok", True)):
        final_warning_reasons.append("captions_too_dense")
    if bool(clip.get("caption_polish_partial") if clip.get("caption_polish_partial") is not None else _as_dict(cap).get("caption_polish_partial", False)):
        final_warning_reasons.append("caption_polish_partial")
    if bool(clip.get("caption_timing_polish_applied") if clip.get("caption_timing_polish_applied") is not None else _as_dict(cap).get("caption_timing_polish_applied", False)) and not bool(_safe_list(clip.get("words")) or _safe_list(_as_dict(cap).get("words"))):
        final_warning_reasons.append("timing_approx_without_word_timestamps")

    # H7.7: Normalize base-only clips recovered from temp final MP4 fallback.
    # When the pipeline stalled after base clip creation but before premium phases,
    # the recovered clip_info has recovered_from_temp_final=True. We still want
    # the task to complete (publishable=True) but flagged for review.
    if clip_info.get("recovered_from_temp_final"):
        final_warning_reasons.append("base_clip_only_premium_phases_skipped")
        final_needs_review = True
        final_publishable = True
        # H7.7: Log StageRecorder diagnostic data when present
        _stage_recorder = clip_info.get("stage_recorder")
        if _stage_recorder is not None and isinstance(_stage_recorder, dict):
            logger.warning(
                "STAGE_RECORDER_DIAGNOSTIC recovered_from_temp_final=True "
                "last_successful_stage=%s next_expected_stage=%s "
                "failed_or_timeout_stage=%s exception_type=%s "
                "exception_message=%s input_path=%s expected_output_path=%s "
                "elapsed_seconds=%s ffmpeg_returncode=%s",
                _stage_recorder.get("last_successful_stage", "?"),
                _stage_recorder.get("next_expected_stage", "?"),
                _stage_recorder.get("failed_or_timeout_stage", "?"),
                _stage_recorder.get("exception_type", "?"),
                str(_stage_recorder.get("exception_message", ""))[:200],
                _stage_recorder.get("input_path", "?"),
                _stage_recorder.get("expected_output_path", "?"),
                str(_stage_recorder.get("elapsed_seconds", "?")),
                str(_stage_recorder.get("ffmpeg_returncode", "?")),
            )
    else:
        final_needs_review = bool(
            final_warning_reasons
            or any(status in {"applied_unverified", "rendered_unverified", "needs_review"} for status in (captions_status, bgm_status, sfx_status, hook_status, rhythm_status, visual_budget_status, visual_reinforcement_status, broll_status, transition_status, audio_mastering_status))
            or weak_editorial_segment
        )
        final_publishable = bool(not final_blocking_reasons)
    final_video_exists_flag = bool(final_video_exists)
    final_contract_snapshot = {
        "final_output_path": str(final_path),
        "final_duration": actual_duration,
        "final_probe_ok": bool(probe_ok),
        "final_contract_ok": bool(final_publishable),
        "render_success": bool(final_video_exists and final_video_stream_ok and final_file_size_ok),
        "final_video_exists": bool(final_video_exists),
        "final_video_stream_ok": bool(final_video_stream_ok),
        "final_audio_stream_ok": bool(final_audio_stream_ok),
        "final_duration_ok": bool(final_duration_ok),
        "final_file_size_ok": bool(final_file_size_ok),
        "technical_valid": bool(final_video_exists and final_video_stream_ok and final_audio_stream_ok and final_duration_ok and final_file_size_ok),
        "has_video": bool(final_video_stream_ok),
        "has_audio": bool(final_audio_stream_ok),
        "final_output_is_task_scoped": bool(final_output_is_task_scoped),
        "final_output_not_latest_stage": bool(final_output_verified and not final_output_is_task_scoped),
        "has_captions": bool(captions_present),
        "has_branding": bool(_as_dict(clip.get("brand_treatment")).get("rendered") or clip.get("watermark") or clip.get("branding_applied")),
        "visual_design_version": str(
            clip.get("visual_design_version")
            or _as_dict(cap).get("visual_design_version")
            or _as_dict(hook).get("visual_design_version")
            or _as_dict(visual_reinforcement).get("visual_design_version")
            or _as_dict(_as_dict(clip.get("brand_treatment"))).get("visual_design_version")
            or get_vpi_visual_design_tokens().get("visual_design_version")
            or "a1"
        ),
        "visual_design_tokens_applied": bool(
            clip.get("visual_design_tokens_applied")
            or _as_dict(cap).get("visual_design_tokens_applied")
            or _as_dict(hook).get("visual_design_tokens_applied")
            or _as_dict(visual_reinforcement).get("visual_design_tokens_applied")
            or _as_dict(clip.get("brand_treatment")).get("visual_design_tokens_applied")
        ),
        "visual_design_tokens_applied_to_captions": bool(
            clip.get("visual_design_tokens_applied_to_captions")
            or _as_dict(cap).get("visual_design_tokens_applied_to_captions")
            or _as_dict(captions_metadata).get("visual_design_tokens_applied_to_captions")
        ),
        "caption_polish_profile": str(
            clip.get("caption_polish_profile")
            or _as_dict(cap).get("caption_polish_profile")
            or ""
        ),
        "caption_pacing_reason": str(
            clip.get("caption_pacing_reason")
            or _as_dict(cap).get("caption_pacing_reason")
            or ""
        ),
        "caption_polish_applied": bool(
            clip.get("caption_polish_applied")
            if clip.get("caption_polish_applied") is not None
            else _as_dict(cap).get("caption_polish_applied", False)
        ),
        "caption_polish_partial": bool(
            clip.get("caption_polish_partial")
            if clip.get("caption_polish_partial") is not None
            else _as_dict(cap).get("caption_polish_partial", False)
        ),
        "caption_linebreak_polish_applied": bool(
            clip.get("caption_linebreak_polish_applied")
            if clip.get("caption_linebreak_polish_applied") is not None
            else _as_dict(cap).get("caption_linebreak_polish_applied", False)
        ),
        "caption_orphan_words_avoided": bool(
            clip.get("caption_orphan_words_avoided")
            if clip.get("caption_orphan_words_avoided") is not None
            else _as_dict(cap).get("caption_orphan_words_avoided", False)
        ),
        "caption_protected_phrases_preserved": bool(
            clip.get("caption_protected_phrases_preserved")
            if clip.get("caption_protected_phrases_preserved") is not None
            else _as_dict(cap).get("caption_protected_phrases_preserved", False)
        ),
        "caption_timing_polish_applied": bool(
            clip.get("caption_timing_polish_applied")
            if clip.get("caption_timing_polish_applied") is not None
            else _as_dict(cap).get("caption_timing_polish_applied", False)
        ),
        "caption_too_fast_adjusted": bool(
            clip.get("caption_too_fast_adjusted")
            if clip.get("caption_too_fast_adjusted") is not None
            else _as_dict(cap).get("caption_too_fast_adjusted", False)
        ),
        "caption_duration_balance_ok": bool(
            clip.get("caption_duration_balance_ok")
            if clip.get("caption_duration_balance_ok") is not None
            else _as_dict(cap).get("caption_duration_balance_ok", True)
        ),
        "caption_keyword_highlight_count": int(
            clip.get("caption_keyword_highlight_count")
            if clip.get("caption_keyword_highlight_count") is not None
            else _as_dict(cap).get("caption_keyword_highlight_count", 0)
        ),
        "caption_highlight_policy": str(
            clip.get("caption_highlight_policy")
            or _as_dict(cap).get("caption_highlight_policy")
            or ""
        ),
        "caption_hook_conflict_avoided": bool(
            clip.get("caption_hook_conflict_avoided")
            if clip.get("caption_hook_conflict_avoided") is not None
            else _as_dict(cap).get("caption_hook_conflict_avoided", False)
        ),
        "caption_cta_conflict_avoided": bool(
            clip.get("caption_cta_conflict_avoided")
            if clip.get("caption_cta_conflict_avoided") is not None
            else _as_dict(cap).get("caption_cta_conflict_avoided", False)
        ),
        "caption_broll_conflict_avoided": bool(
            clip.get("caption_broll_conflict_avoided")
            if clip.get("caption_broll_conflict_avoided") is not None
            else _as_dict(cap).get("caption_broll_conflict_avoided", False)
        ),
        "caption_visual_conflict_avoided": bool(
            clip.get("caption_visual_conflict_avoided")
            if clip.get("caption_visual_conflict_avoided") is not None
            else _as_dict(cap).get("caption_visual_conflict_avoided", False)
        ),
        "text_overlap_prevented": bool(
            clip.get("text_overlap_prevented")
            if clip.get("text_overlap_prevented") is not None
            else _as_dict(cap).get("text_overlap_prevented", False)
        ),
        "suppressed_text_layers": list(
            clip.get("suppressed_text_layers")
            or _as_dict(cap).get("suppressed_text_layers")
            or []
        ),
        "text_layer_count_final": int(
            clip.get("text_layer_count_final")
            if clip.get("text_layer_count_final") is not None
            else _as_dict(cap).get("text_layer_count_final", 1)
        ),
        "caption_priority_enforced": bool(
            clip.get("caption_priority_enforced")
            if clip.get("caption_priority_enforced") is not None
            else _as_dict(cap).get("caption_priority_enforced", False)
        ),
        "caption_timebase_corrected": bool(
            clip.get("caption_timebase_corrected")
            if clip.get("caption_timebase_corrected") is not None
            else _as_dict(cap).get("caption_timebase_corrected", False)
        ),
        "caption_timebase_source": str(
            clip.get("caption_timebase_source")
            or _as_dict(cap).get("caption_timebase_source")
            or "clip_relative"
        ),
        "caption_sync_warning": str(
            clip.get("caption_sync_warning")
            or _as_dict(cap).get("caption_sync_warning")
            or ""
        ),
        "visual_design_tokens_applied_to_hook": bool(
            clip.get("visual_design_tokens_applied_to_hook")
            or _as_dict(hook).get("visual_design_tokens_applied_to_hook")
        ),
        "visual_design_tokens_applied_to_reinforcement": bool(
            clip.get("visual_design_tokens_applied_to_reinforcement")
            or _as_dict(visual_reinforcement).get("visual_design_tokens_applied_to_reinforcement")
        ),
        "visual_design_tokens_applied_to_branding": bool(
            clip.get("visual_design_tokens_applied_to_branding")
            or _as_dict(clip.get("brand_treatment")).get("visual_design_tokens_applied_to_branding")
        ),
        "visual_layout_strategy": str(
            clip.get("visual_layout_strategy")
            or _as_dict(visual_reinforcement).get("visual_layout_strategy")
            or _as_dict(clip.get("brand_treatment")).get("visual_layout_strategy")
            or ""
        ),
        "visual_layout_zone": str(
            clip.get("visual_layout_zone")
            or _as_dict(visual_reinforcement).get("visual_layout_zone")
            or _as_dict(clip.get("brand_treatment")).get("visual_layout_zone")
            or ""
        ),
        "visual_layout_size": str(
            clip.get("visual_layout_size")
            or _as_dict(visual_reinforcement).get("visual_layout_size")
            or _as_dict(clip.get("brand_treatment")).get("visual_layout_size")
            or ""
        ),
        "visual_layout_opacity": float(
            clip.get("visual_layout_opacity")
            or _as_dict(visual_reinforcement).get("visual_layout_opacity")
            or _as_dict(clip.get("brand_treatment")).get("visual_layout_opacity")
            or 0.0
        ),
        "visual_layout_duration": float(
            clip.get("visual_layout_duration")
            or _as_dict(visual_reinforcement).get("visual_layout_duration")
            or _as_dict(clip.get("brand_treatment")).get("visual_layout_duration")
            or 0.0
        ),
        "visual_layout_reason": str(
            clip.get("visual_layout_reason")
            or _as_dict(visual_reinforcement).get("visual_layout_reason")
            or _as_dict(clip.get("brand_treatment")).get("visual_layout_reason")
            or ""
        ),
        "visual_layout_face_safe": bool(
            clip.get("visual_layout_face_safe")
            if clip.get("visual_layout_face_safe") is not None
            else _as_dict(visual_reinforcement).get("visual_layout_face_safe", True)
        ),
        "visual_layout_caption_safe": bool(
            clip.get("visual_layout_caption_safe")
            if clip.get("visual_layout_caption_safe") is not None
            else _as_dict(visual_reinforcement).get("visual_layout_caption_safe", True)
        ),
        "visual_layout_ok": bool(
            clip.get("visual_layout_ok")
            if clip.get("visual_layout_ok") is not None
            else _as_dict(visual_reinforcement).get("visual_layout_ok", True)
        ),
        "visual_layout_warnings": list(
            clip.get("visual_layout_warnings")
            or _as_dict(visual_reinforcement).get("visual_layout_warnings")
            or _as_dict(clip.get("brand_treatment")).get("visual_layout_warnings")
            or []
        ),
        "pip_overlay_disabled": bool(
            clip.get("pip_overlay_disabled")
            if clip.get("pip_overlay_disabled") is not None
            else final_contract.get("pip_overlay_disabled", False)
        ),
        "thumbnail_overlay_disabled": bool(
            clip.get("thumbnail_overlay_disabled")
            if clip.get("thumbnail_overlay_disabled") is not None
            else final_contract.get("thumbnail_overlay_disabled", False)
        ),
        "debug_preview_overlay_disabled": bool(
            clip.get("debug_preview_overlay_disabled")
            if clip.get("debug_preview_overlay_disabled") is not None
            else final_contract.get("debug_preview_overlay_disabled", False)
        ),
        "debug_face_box_rendered": bool(
            clip.get("debug_face_box_rendered")
            if clip.get("debug_face_box_rendered") is not None
            else final_contract.get("debug_face_box_rendered", False)
        ),
        "debug_overlays_disabled": bool(
            clip.get("debug_overlays_disabled")
            if clip.get("debug_overlays_disabled") is not None
            else final_contract.get("debug_overlays_disabled", False)
        ),
        "premium_restraint_mode": str(
            clip.get("premium_restraint_mode")
            or _as_dict(visual_reinforcement).get("premium_restraint_mode")
            or _as_dict(clip.get("brand_treatment")).get("premium_restraint_mode")
            or ""
        ),
        "premium_restraint_applied": bool(
            clip.get("premium_restraint_applied")
            if clip.get("premium_restraint_applied") is not None
            else _as_dict(visual_reinforcement).get("premium_restraint_applied", False)
        ),
        "premium_restraint_reason": str(
            clip.get("premium_restraint_reason")
            or _as_dict(visual_reinforcement).get("premium_restraint_reason")
            or _as_dict(clip.get("brand_treatment")).get("premium_restraint_reason")
            or ""
        ),
        "premium_restraint_suppressed_layers": list(
            clip.get("premium_restraint_suppressed_layers")
            or _as_dict(visual_reinforcement).get("premium_restraint_suppressed_layers")
            or _as_dict(clip.get("brand_treatment")).get("premium_restraint_suppressed_layers")
            or []
        ),
        "allowed_visual_support_count": int(
            clip.get("allowed_visual_support_count")
            or _as_dict(visual_reinforcement).get("allowed_visual_support_count")
            or 0
        ),
        "clip_already_strong": bool(
            clip.get("clip_already_strong")
            if clip.get("clip_already_strong") is not None
            else _as_dict(visual_reinforcement).get("clip_already_strong", False)
        ),
        "visual_support_reduced_reason": str(
            clip.get("visual_support_reduced_reason")
            or _as_dict(visual_reinforcement).get("visual_support_reduced_reason")
            or _as_dict(clip.get("brand_treatment")).get("visual_support_reduced_reason")
            or ""
        ),
        "restraint_broll_interaction": str(
            clip.get("restraint_broll_interaction")
            or _as_dict(visual_reinforcement).get("restraint_broll_interaction")
            or _as_dict(clip.get("brand_treatment")).get("restraint_broll_interaction")
            or ""
        ),
        "brand_assets_verified": bool(
            clip.get("brand_assets_verified")
            or _as_dict(clip.get("brand_treatment")).get("brand_assets_verified")
        ),
        "brand_logo_asset_id": str(
            clip.get("brand_logo_asset_id")
            or _as_dict(clip.get("brand_treatment")).get("brand_logo_asset_id")
            or ""
        ),
        "brand_logo_status": str(
            clip.get("brand_logo_status")
            or _as_dict(clip.get("brand_treatment")).get("brand_logo_status")
            or ""
        ),
        "brand_final_mode": str(
            clip.get("brand_final_mode")
            or _as_dict(clip.get("brand_treatment")).get("brand_final_mode")
            or ""
        ),
        "brand_final_verified": bool(
            clip.get("brand_final_verified")
            if clip.get("brand_final_verified") is not None
            else _as_dict(clip.get("brand_treatment")).get("brand_final_verified", False)
        ),
        "brand_final_reason": str(
            clip.get("brand_final_reason")
            or _as_dict(clip.get("brand_treatment")).get("brand_final_reason")
            or ""
        ),
        "cta_decision": str(clip.get("cta_decision") or cta.get("decision") or cta.get("strategy") or ""),
        "cta_type": str(clip.get("cta_type") or cta.get("type") or ""),
        "cta_text": str(clip.get("cta_text") or cta.get("text") or ""),
        "cta_planned": bool(clip.get("cta_planned") if clip.get("cta_planned") is not None else cta.get("planned", False)),
        "cta_rendered": bool(clip.get("cta_rendered") if clip.get("cta_rendered") is not None else cta.get("rendered", False)),
        "cta_verified": bool(clip.get("cta_verified") if clip.get("cta_verified") is not None else cta.get("verified", False)),
        "cta_reason": str(clip.get("cta_reason") or cta.get("reason") or ""),
        "cta_skipped_reason": str(clip.get("cta_skipped_reason") or cta.get("skipped_reason") or ""),
        "cta_safety_ok": bool(clip.get("cta_safety_ok") if clip.get("cta_safety_ok") is not None else cta.get("safety_ok", False)),
        "cta_safety_warnings": list(clip.get("cta_safety_warnings") or cta.get("safety_warnings") or []),
        "cta_safety_rewritten": bool(clip.get("cta_safety_rewritten") if clip.get("cta_safety_rewritten") is not None else cta.get("safety_rewritten", False)),
        "cta_safety_reason": str(clip.get("cta_safety_reason") or cta.get("safety_reason") or ""),
        "visual_asset_inventory_summary": dict(
            clip.get("visual_asset_inventory_summary")
            or final_contract.get("visual_asset_inventory_summary")
            or {}
        ),
        "visual_asset_coverage_ok": bool(
            clip.get("visual_asset_coverage_ok")
            or final_contract.get("visual_asset_coverage_ok")
        ),
        "missing_visual_intents": list(clip.get("missing_visual_intents") or final_contract.get("missing_visual_intents") or []),
        "weak_visual_intents": list(clip.get("weak_visual_intents") or final_contract.get("weak_visual_intents") or []),
        "missing_visual_families": list(clip.get("missing_visual_families") or final_contract.get("missing_visual_families") or []),
        "weak_visual_families": list(clip.get("weak_visual_families") or final_contract.get("weak_visual_families") or []),
        "sensitive_visual_available": bool(clip.get("sensitive_visual_available") or final_contract.get("sensitive_visual_available")),
        "visual_asset_inventory_used": bool(clip.get("visual_asset_inventory_used") or final_contract.get("visual_asset_inventory_used")),
        "visual_asset_selected": str(clip.get("visual_asset_selected") or final_contract.get("visual_asset_selected") or ""),
        "visual_asset_selection_reason": str(clip.get("visual_asset_selection_reason") or final_contract.get("visual_asset_selection_reason") or ""),
        "visual_asset_fallback_used": bool(clip.get("visual_asset_fallback_used") or final_contract.get("visual_asset_fallback_used")),
        "sensitive_visual_asset_blocked": bool(clip.get("sensitive_visual_asset_blocked") or final_contract.get("sensitive_visual_asset_blocked")),
        "visual_asset_identity_warnings": list(clip.get("visual_asset_identity_warnings") or final_contract.get("visual_asset_identity_warnings") or []),
        "motion_profile": str(clip.get("motion_profile") or final_contract.get("motion_profile") or ""),
        "motion_profile_reason": str(clip.get("motion_profile_reason") or final_contract.get("motion_profile_reason") or ""),
        "zoom_intensity": float(clip.get("zoom_intensity") or final_contract.get("zoom_intensity") or 0.0),
        "max_zoom_events": int(clip.get("max_zoom_events") or final_contract.get("max_zoom_events") or 0),
        "actual_zoom_events": int(clip.get("actual_zoom_events") or final_contract.get("actual_zoom_events") or 0),
        "first3_motion_boost_applied": bool(clip.get("first3_motion_boost_applied") or final_contract.get("first3_motion_boost_applied")),
        "first3_motion_boost_reason": str(clip.get("first3_motion_boost_reason") or final_contract.get("first3_motion_boost_reason") or ""),
        "intentional_pause_preserved": bool(clip.get("intentional_pause_preserved") or final_contract.get("intentional_pause_preserved")),
        "dead_pause_trimmed": bool(clip.get("dead_pause_trimmed") or final_contract.get("dead_pause_trimmed")),
        "motion_polish_applied": bool(clip.get("motion_polish_applied") or final_contract.get("motion_polish_applied")),
        "motion_polish_warnings": list(clip.get("motion_polish_warnings") or final_contract.get("motion_polish_warnings") or []),
        "framing_profile": str(clip.get("framing_profile") or final_contract.get("framing_profile") or ""),
        "framing_reason": str(clip.get("framing_reason") or final_contract.get("framing_reason") or ""),
        "target_anchor": str(clip.get("target_anchor") or final_contract.get("target_anchor") or ""),
        "safe_crop_margin": float(clip.get("safe_crop_margin") or final_contract.get("safe_crop_margin") or 0.0),
        "headroom_policy": str(clip.get("headroom_policy") or final_contract.get("headroom_policy") or ""),
        "subtitle_clearance_policy": str(clip.get("subtitle_clearance_policy") or final_contract.get("subtitle_clearance_policy") or ""),
        "max_reframe_shift": float(clip.get("max_reframe_shift") or final_contract.get("max_reframe_shift") or 0.0),
        "face_bbox_present": bool(clip.get("face_bbox_present") or final_contract.get("face_bbox_present")),
        "speaker_bbox_present": bool(clip.get("speaker_bbox_present") or final_contract.get("speaker_bbox_present")),
        "face_framing_safe": bool(clip.get("face_framing_safe") if clip.get("face_framing_safe") is not None else final_contract.get("face_framing_safe", True)),
        "headroom_safe": bool(clip.get("headroom_safe") if clip.get("headroom_safe") is not None else final_contract.get("headroom_safe", True)),
        "face_crop_risk": str(clip.get("face_crop_risk") or final_contract.get("face_crop_risk") or ""),
        "face_framing_adjusted": bool(clip.get("face_framing_adjusted") or final_contract.get("face_framing_adjusted")),
        "subtitle_clearance_applied": bool(clip.get("subtitle_clearance_applied") if clip.get("subtitle_clearance_applied") is not None else final_contract.get("subtitle_clearance_applied", False)),
        "cta_clearance_applied": bool(clip.get("cta_clearance_applied") if clip.get("cta_clearance_applied") is not None else final_contract.get("cta_clearance_applied", False)),
        "reframe_skipped_reason": str(clip.get("reframe_skipped_reason") or final_contract.get("reframe_skipped_reason") or ""),
        "original_frame_preserved": bool(clip.get("original_frame_preserved") if clip.get("original_frame_preserved") is not None else final_contract.get("original_frame_preserved", False)),
        "framing_polish_applied": bool(clip.get("framing_polish_applied") if clip.get("framing_polish_applied") is not None else final_contract.get("framing_polish_applied", False)),
        "framing_polish_warnings": list(clip.get("framing_polish_warnings") or final_contract.get("framing_polish_warnings") or []),
        "has_bgm": bool(bgm_applied or bgm_verified),
        "has_sfx": bool(sfx_applied or sfx_verified),
        "has_broll": bool(broll_applied or broll_verified),
        "broll_timing_strategy": str(clip.get("broll_timing_strategy") or final_contract.get("broll_timing_strategy") or ""),
        "broll_timing_reason": str(clip.get("broll_timing_reason") or final_contract.get("broll_timing_reason") or ""),
        "broll_phrase_matched": bool(clip.get("broll_phrase_matched") or final_contract.get("broll_phrase_matched")),
        "broll_phrase_match_terms": list(clip.get("broll_phrase_match_terms") or final_contract.get("broll_phrase_match_terms") or []),
        "broll_phrase_match_confidence": float(clip.get("broll_phrase_match_confidence") or final_contract.get("broll_phrase_match_confidence") or 0.0),
        "broll_entry_style": str(clip.get("broll_entry_style") or final_contract.get("broll_entry_style") or ""),
        "broll_exit_style": str(clip.get("broll_exit_style") or final_contract.get("broll_exit_style") or ""),
        "broll_transition_sober": bool(clip.get("broll_transition_sober") or final_contract.get("broll_transition_sober")),
        "broll_return_to_speaker": bool(clip.get("broll_return_to_speaker") or final_contract.get("broll_return_to_speaker")),
        "broll_return_reason": str(clip.get("broll_return_reason") or final_contract.get("broll_return_reason") or ""),
        "broll_relevance_gate_passed": bool(clip.get("broll_relevance_gate_passed") or final_contract.get("broll_relevance_gate_passed")),
        "broll_relevance_score": float(clip.get("broll_relevance_score") or final_contract.get("broll_relevance_score") or 0.0),
        "broll_skipped_unrelated": bool(clip.get("broll_skipped_unrelated") or final_contract.get("broll_skipped_unrelated")),
        "final_output_uses_motion_overlay": bool(clip.get("final_output_uses_motion_overlay") or final_contract.get("final_output_uses_motion_overlay")),
        "has_motion_or_vfx": bool(
            visual_reinforcement_applied
            or visual_reinforcement_verified
            or rhythm_applied
            or bool(_as_dict(clip.get("visual_effects")).get("visual_effects_applied"))
            or bool(_as_dict(clip.get("motion_overlay")).get("motion_overlay_applied"))
        ),
        "has_transition": bool(transitions_applied or transitions_verified),
        "final_captions_expected": bool(captions_expected),
        "final_captions_present": bool(captions_present),
        "final_captions_status": captions_status,
        "final_bgm_expected": bool(bgm_expected),
        "final_bgm_applied": bool(bgm_applied),
        "final_bgm_status": bgm_status,
        "final_sfx_expected": bool(sfx_expected),
        "final_sfx_applied": bool(sfx_applied),
        "final_sfx_status": sfx_status,
        "final_hook_status": hook_status,
        "final_rhythm_status": rhythm_status,
        "final_visual_budget_status": visual_budget_status,
        "final_visual_reinforcement_status": visual_reinforcement_status,
        "final_broll_status": broll_status,
        "broll_status": broll_status,
        "final_transition_status": transition_status,
        "transition_status": transition_status,
        "transition_polish_mode": str(clip.get("transition_polish_mode") or final_contract.get("transition_polish_mode") or ""),
        "transition_duration_ms": int(clip.get("transition_duration_ms") or final_contract.get("transition_duration_ms") or 0),
        "transition_reason": str(clip.get("transition_reason") or final_contract.get("transition_reason") or ""),
        "transition_should_render": bool(clip.get("transition_should_render") or final_contract.get("transition_should_render")),
        "transition_repetition_avoided": bool(clip.get("transition_repetition_avoided") or final_contract.get("transition_repetition_avoided")),
        "transition_broll_sync_ok": bool(clip.get("transition_broll_sync_ok") or final_contract.get("transition_broll_sync_ok")),
        "transition_broll_sync_reason": str(clip.get("transition_broll_sync_reason") or final_contract.get("transition_broll_sync_reason") or ""),
        "transition_sfx_allowed": bool(clip.get("transition_sfx_allowed") or final_contract.get("transition_sfx_allowed")),
        "transition_sfx_family": str(clip.get("transition_sfx_family") or final_contract.get("transition_sfx_family") or ""),
        "transition_sfx_suppressed_reason": str(clip.get("transition_sfx_suppressed_reason") or final_contract.get("transition_sfx_suppressed_reason") or ""),
        "final_audio_mastering_status": audio_mastering_status,
        "final_audio_chain_ok": bool(final_audio_chain_ok),
        "final_audio_chain_errors": list(dict.fromkeys(final_audio_chain_errors)),
        "final_audio_chain_warnings": list(dict.fromkeys(final_audio_chain_warnings)),
        "base_voice_audio_present": bool(base_voice_audio_present),
        "audio_duplicate_passes_blocked": list(dict.fromkeys(audio_duplicate_passes_blocked)),
        "bgm_pass_count": int(bgm_pass_count),
        "sfx_pass_count": int(sfx_pass_count),
        "bgm_final_status": bgm_final_status,
        "sfx_final_status": sfx_final_status,
        "audio_mastering_final_status": audio_mastering_final_status,
        "mastering_improved_audio": bool(mastering_improved_audio),
        "mastering_rejected_reason": mastering_rejected_reason,
        "final_publishable": bool(final_publishable),
        "final_needs_review": bool(final_needs_review),
        # OUTPUT-QC-GATE-52A: explicit, honest editorial verdict (separate from physical contract).
        "rejected_incomplete_final_idea": bool(final_idea_editorially_incomplete),
        "final_editorial_integrity_passed": bool(not final_idea_editorially_incomplete),
        "editorial_reconciliation_allowed": bool(not final_idea_editorially_incomplete),
        "final_complete_idea_score": float(final_complete_idea_score_for_gate),
        "final_blocking_reasons": list(dict.fromkeys(final_blocking_reasons)),
        "final_warning_reasons": list(dict.fromkeys(final_warning_reasons)),
        "final_truth_source": final_truth_source,
        "final_truth_source_ok": bool(final_truth_source in {"final_mp4_contract", "task_scoped_output"}),
        "final_output_verified": bool(final_video_exists_flag and final_video_stream_ok and (final_audio_stream_ok or not has_audio_expected) and final_duration_ok),
        "final_audio_analysis": dict(final_audio_analysis or {}),
        "final_audio_loudness_ok": bool(final_audio_loudness_ok),
        "final_audio_too_quiet": bool(final_audio_too_quiet),
        "final_audio_clipping_risk": bool(final_audio_clipping_risk),
        "final_audio_silence_likely": bool(final_audio_silence_likely),
        "weak_editorial_segment": bool(weak_editorial_segment),
        "vpi_editorial_categories": list(_safe_list(clip.get("vpi_editorial_categories"))),
        "hookability_score": float(clip.get("hookability_score") or 0.0),
        "hookability_reason": str(clip.get("hookability_reason") or ""),
        "commercial_usefulness_score": float(clip.get("commercial_usefulness_score") or 0.0),
        "commercial_usefulness_reason": str(clip.get("commercial_usefulness_reason") or ""),
        "standalone_score": float(clip.get("standalone_score") or 0.0),
        "standalone_reason": str(clip.get("standalone_reason") or ""),
        "weak_segment_penalties": list(_safe_list(clip.get("weak_segment_penalties"))),
        "weak_segment_reason": str(clip.get("weak_segment_reason") or ""),
        "segment_selection_confidence": float(clip.get("segment_selection_confidence") or 0.0),
        "selected_for_reason": str(clip.get("selected_for_reason") or ""),
        "rejected_for_reason": str(clip.get("rejected_for_reason") or ""),
        "package_diversity_context": dict(clip.get("package_diversity_context") or final_contract.get("package_diversity_context") or {}),
        "selected_clip_package_summary": dict(clip.get("selected_clip_package_summary") or final_contract.get("selected_clip_package_summary") or {}),
        "package_diversity_score": package_diversity_score,
        "package_diversity_reason": str(clip.get("package_diversity_reason") or final_contract.get("package_diversity_reason") or ""),
        "package_category_distribution": package_category_distribution,
        "package_theme_distribution": package_theme_distribution,
        "package_duration_balance_ok": bool(clip.get("package_duration_balance_ok") if clip.get("package_duration_balance_ok") is not None else final_contract.get("package_duration_balance_ok")),
        "package_duration_warnings": list(clip.get("package_duration_warnings") or final_contract.get("package_duration_warnings") or []),
        "package_diversity_warnings": package_diversity_warnings,
        "campaign_intent": campaign_intent,
        "campaign_intent_confidence": campaign_intent_confidence,
        "campaign_intent_source": campaign_intent_source,
        "campaign_intent_reason": campaign_intent_reason,
        "preferred_categories": preferred_categories,
        "suppressed_categories": suppressed_categories,
        "preferred_keywords": preferred_keywords,
        "campaign_boost_applied": campaign_boost_applied,
        "campaign_boost_score": campaign_boost_score,
        "campaign_alignment_score": campaign_alignment_score,
        "campaign_alignment_reason": campaign_alignment_reason,
        "selected_campaign_mix": selected_campaign_mix,
        "campaign_alignment_summary": campaign_alignment_summary,
        "sensitive_handling_required": sensitive_handling_required,
        "clip_brief": clip_brief,
        "clip_angle": clip_angle,
        "clip_value_proposition": clip_value_proposition,
        "clip_campaign_fit": clip_campaign_fit,
        "clip_recommended_cta": clip_recommended_cta,
        "clip_confidence_label": clip_confidence_label,
        "clip_review_flags": clip_review_flags,
        "clip_publish_notes": clip_publish_notes,
        "clip_brief_summary": clip_brief_summary,
        "high_confidence_clip_count": high_confidence_clip_count,
        "review_clip_count": review_clip_count,
        "campaign_fit_summary": campaign_fit_summary,
        "original_start_time": str(clip.get("original_start_time") or ""),
        "original_end_time": str(clip.get("original_end_time") or ""),
        "refined_start_time": str(clip.get("refined_start_time") or ""),
        "refined_end_time": str(clip.get("refined_end_time") or ""),
        "original_start": float(clip.get("original_start") or 0.0),
        "original_end": float(clip.get("original_end") or 0.0),
        "refined_start": float(clip.get("refined_start") or 0.0),
        "refined_end": float(clip.get("refined_end") or 0.0),
        "boundary_adjustment_applied": bool(clip.get("boundary_adjustment_applied")),
        "boundary_adjustment_reason": str(clip.get("boundary_adjustment_reason") or ""),
        "start_trim_seconds": float(clip.get("start_trim_seconds") or 0.0),
        "start_extend_seconds": float(clip.get("start_extend_seconds") or 0.0),
        "end_extend_seconds": float(clip.get("end_extend_seconds") or 0.0),
        "end_trim_seconds": float(clip.get("end_trim_seconds") or 0.0),
        "payoff_preserved": bool(clip.get("payoff_preserved")),
        "starts_cleanly": bool(clip.get("starts_cleanly")),
        "ends_cleanly": bool(clip.get("ends_cleanly")),
        "first_second_strength": float(clip.get("first_second_strength") or 0.0),
        "first_second_reason": str(clip.get("first_second_reason") or ""),
        "boundary_confidence": boundary_confidence,
        "standalone_after_boundary_score": float(clip.get("standalone_after_boundary_score") or 0.0),
        "standalone_after_boundary_reason": str(clip.get("standalone_after_boundary_reason") or ""),
        "start_filler_trimmed": bool(clip.get("start_filler_trimmed")),
        "start_trim_reason": str(clip.get("start_trim_reason") or ""),
        "start_context_extended": bool(clip.get("start_context_extended")),
        "start_context_reason": str(clip.get("start_context_reason") or ""),
        "payoff_extended": bool(clip.get("payoff_extended")),
        "payoff_extension_reason": str(clip.get("payoff_extension_reason") or ""),
        "end_cleaned": bool(clip.get("end_cleaned")),
        "end_clean_reason": str(clip.get("end_clean_reason") or ""),
        "boundary_reverted": bool(clip.get("boundary_reverted")),
        "boundary_reverted_reason": str(clip.get("boundary_reverted_reason") or ""),
        "bts_tail_detected": bool(clip.get("bts_tail_detected") or final_contract.get("bts_tail_detected")),
        "bts_tail_trimmed_seconds": float(clip.get("bts_tail_trimmed_seconds") or final_contract.get("bts_tail_trimmed_seconds") or 0.0),
        "viral_window_shifted_back": bool(clip.get("viral_window_shifted_back") or final_contract.get("viral_window_shifted_back")),
        "viral_window_shift_reason": str(clip.get("viral_window_shift_reason") or final_contract.get("viral_window_shift_reason") or ""),
        "bgm_voice_priority_ok": bool(clip.get("bgm_voice_priority_ok") or bgm.get("bgm_voice_priority_ok") or (bgm.get("music_mix_verified") and (bgm.get("music_ducking_enabled") or not base_voice_audio_present))),
        "bgm_loudness_checked": bool(clip.get("bgm_loudness_checked") or bgm.get("bgm_loudness_checked") or bgm.get("music_mix_verified")),
        "sfx_voice_clarity_ok": bool(clip.get("sfx_voice_clarity_ok") or sfx.get("sfx_voice_clarity_ok") or (sfx.get("sfx_verified") and not sfx.get("sfx_events_dropped_for_voice"))),
        "audio_editorial_profile": audio_editorial_profile,
        "audio_editorial_profile_reason": audio_editorial_profile_reason,
        "music_mood_selected": music_mood_selected,
        "music_asset_id": music_asset_id,
        "music_selection_reason": music_selection_reason,
        "music_fallback_used": bool(music_fallback_used),
        "music_reuse_reason": music_reuse_reason,
        "bgm_volume_empirical_boost_applied": bool(
            clip.get("bgm_volume_empirical_boost_applied")
            if clip.get("bgm_volume_empirical_boost_applied") is not None
            else final_contract.get("bgm_volume_empirical_boost_applied", False)
        ),
        "bgm_target_volume_final": float(
            clip.get("bgm_target_volume_final")
            if clip.get("bgm_target_volume_final") is not None
            else final_contract.get("bgm_target_volume_final", 0.0)
        ),
        "sfx_editorial_profile": sfx_editorial_profile,
        "sfx_allowed_families": list(sfx_allowed_families),
        "sfx_blocked_families": list(sfx_blocked_families),
        "sfx_family_selected": sfx_family_selected,
        "sfx_variation_ids": list(sfx_variation_ids),
        "sfx_selection_reason": sfx_selection_reason,
        "sfx_reuse_reason": sfx_reuse_reason,
        "music_asset_taxonomy_used": music_asset_taxonomy_used,
        "sfx_asset_taxonomy_used": sfx_asset_taxonomy_used,
        "vpi_audio_identity_ok": bool(vpi_audio_identity_ok),
        "vpi_audio_identity_warnings": list(vpi_audio_identity_warnings),
        "audio_identity_mismatch_downgraded": bool(audio_identity_mismatch_downgraded),
        "audio_identity_mismatch_downgrade_reason": str(audio_identity_mismatch_downgrade_reason),
        "sfx_rendered_unverified_downgraded": bool(sfx_rendered_unverified_downgraded),
        "sfx_rendered_unverified_downgrade_reason": str(sfx_rendered_unverified_downgrade_reason),
        "metadata_consistency_failed_downgraded": bool(metadata_consistency_failed_downgraded),
        "metadata_consistency_downgrade_reason": str(metadata_consistency_downgrade_reason),
        "audio_asset_inventory_summary": dict(audio_asset_inventory_summary),
        "audio_asset_coverage_ok": bool(audio_asset_coverage_ok),
        "missing_music_moods": list(missing_music_moods),
        "missing_sfx_families": list(missing_sfx_families),
        "weak_music_moods": list(weak_music_moods),
        "weak_sfx_families": list(weak_sfx_families),
        "sensitive_sober_available": bool(sensitive_sober_available),
        "sensitive_audio_asset_blocked": bool(sensitive_audio_asset_blocked),
        "route_registry": route_registry,
        "route_registry_version": str(route_registry.get("route_registry_version") or "a2"),
        "production_safe": bool(production_safe),
        "production_safe_mode_active": bool(production_safe_active),
        "production_safe_policy": dict(production_safe_policy or {}),
        "production_safe_policy_version": str((production_safe_policy or {}).get("policy_version") or "a4"),
        "production_safe_external_disabled": bool((production_safe_policy or {}).get("production_safe_external_disabled", production_safe_active)),
        "production_safe_legacy_disabled": bool((production_safe_policy or {}).get("production_safe_legacy_disabled", production_safe_active)),
        "production_safe_routes_allowed": list((production_safe_policy or {}).get("production_safe_routes_allowed") or []),
        "production_safe_routes_blocked": list((production_safe_policy or {}).get("production_safe_routes_blocked") or []),
        "vpi_daily_mode_enabled": bool(_as_dict(daily_mode_policy).get("vpi_daily_mode_enabled")),
        "daily_mode_version": str(_as_dict(daily_mode_policy).get("daily_mode_version") or "a1"),
        "daily_mode_policy": dict(daily_mode_policy or {}),
        "daily_mode_outputs_enabled": bool(_as_dict(daily_mode_policy).get("daily_mode_outputs_enabled")),
        "daily_mode_conflicts_resolved": list(_as_dict(daily_mode_policy).get("daily_mode_conflicts_resolved") or []),
        "daily_mode_unsafe_override_used": bool(_as_dict(daily_mode_policy).get("daily_mode_unsafe_override_used")),
        "audio_chain_plan": dict(audio_chain_plan or {}),
        "audio_chain_state": dict(audio_chain_state or {}),
        "bgm_pass_count": int(bgm_pass_count),
        "sfx_pass_count": int(sfx_pass_count),
        "audio_duplicate_passes_blocked": list(dict.fromkeys(audio_duplicate_passes_blocked)),
        "bgm_final_status": bgm_final_status,
        "sfx_final_status": sfx_final_status,
        "audio_mastering_final_status": audio_mastering_final_status,
        "base_voice_audio_present": bool(base_voice_audio_present),
        "production_safe_compliant": bool(route_registry_compliant),
        "filename_contract_mode": str(clip.get("filename_contract_mode") or "legacy_warning_only"),
        "output_root": str(clip.get("output_root") or ""),
        "clips_output_dir": str(clip.get("clips_output_dir") or ""),
        "output_manifest_path": str(clip.get("output_manifest_path") or ""),
        "output_summary_path": str(clip.get("output_summary_path") or ""),
        "output_filename_strategy": str(clip.get("output_filename_strategy") or "vpi_{campaign_intent}_{clip_angle}_{confidence}_{start}_{end}_{clip_id_hash}"),
        "output_filename_safe": bool(clip.get("output_filename_safe") if clip.get("output_filename_safe") is not None else True),
        "output_filename_collision_resolved": bool(clip.get("output_filename_collision_resolved") if clip.get("output_filename_collision_resolved") is not None else False),
        "output_management_ok": bool(clip.get("output_management_ok") if clip.get("output_management_ok") is not None else False),
        "output_management_warnings": list(clip.get("output_management_warnings") or []),
        "output_clip_count": int(clip.get("output_clip_count") or 0),
        "publishable_clip_count": int(clip.get("publishable_clip_count") or 0),
        "review_clip_count": int(clip.get("review_clip_count") or 0),
        "review_bundle_dir": str(clip.get("review_bundle_dir") or ""),
        "review_index_path": str(clip.get("review_index_path") or ""),
        "review_bundle_json_path": str(clip.get("review_bundle_json_path") or ""),
        "review_bundle_ready": bool(clip.get("review_bundle_ready") if clip.get("review_bundle_ready") is not None else False),
        "review_bundle_warnings": list(clip.get("review_bundle_warnings") or []),
        "legacy_routes_quarantined": list(legacy_routes_quarantined),
        "experimental_routes_quarantined": list(experimental_routes_quarantined),
        "deprecated_routes_present": list(deprecated_routes_present),
        "deprecated_routes_used": list(deprecated_routes_used),
        "deprecated_routes_blocked": list(deprecated_routes_blocked),
        "legacy_route_warning": list(legacy_route_warning),
        "premium_flow_manifest_version": str((premium_flow_manifest or {}).get("manifest_version") or "a1"),
        "phase_metadata": {
            "captions": cap,
            "bgm": bgm,
            "sfx": sfx,
            "hook": hook,
            "rhythm": rhythm,
            "visual_layer_budget": budget,
            "visual_reinforcement": visual_reinforcement,
            "broll": broll,
            "transitions": transitions,
            "audio_mastering": audio_master,
            "final_qc": qc_report,
        },
    }
    visual_identity_source = {
        "forbidden_color_used": bool(
            clip.get("forbidden_color_used")
            or _as_dict(cap).get("forbidden_color_used")
            or _as_dict(hook).get("forbidden_color_used")
            or _as_dict(visual_reinforcement).get("forbidden_color_used")
            or _as_dict(clip.get("brand_treatment")).get("forbidden_color_used")
        ),
        "text_layers": int(
            clip.get("text_layer_count_max")
            or _as_dict(cap).get("text_layers")
            or _as_dict(cap).get("caption_text_layers")
            or 0
        ),
        "heavy_branding": bool(
            _as_dict(clip.get("brand_treatment")).get("heavy_branding")
            or clip.get("branding_heavy")
        ),
        "oversized_badge": bool(_as_dict(visual_reinforcement).get("oversized_badge")),
        "hook_text": str(clip.get("hook_text") or _as_dict(hook).get("hook_text") or _as_dict(hook).get("headline_text") or ""),
        "caption_style_mismatch": bool(
            _as_dict(cap).get("caption_style_mismatch")
            or _as_dict(captions_metadata).get("caption_style_mismatch")
        ),
        "fallback_style_mismatch": bool(
            _as_dict(cap).get("fallback_style_mismatch")
            or _as_dict(captions_metadata).get("fallback_style_mismatch")
        ),
        "captions_ilegible": bool(
            _as_dict(cap).get("captions_ilegible")
            or _as_dict(captions_metadata).get("captions_ilegible")
        ),
        "visual_asset_identity_warnings": list(
            clip.get("visual_asset_identity_warnings")
            or _as_dict(visual_reinforcement).get("visual_asset_identity_warnings")
            or _as_dict(clip.get("brand_treatment")).get("warnings")
            or []
        ),
        "visual_design_tokens_applied": bool(final_contract_snapshot.get("visual_design_tokens_applied")),
    }
    try:
        if validate_premium_flow_manifest is None:
            raise RuntimeError("premium_flow_manifest_validator_unavailable")
        premium_flow_validation = validate_premium_flow_manifest(route_registry, final_contract_snapshot)
    except Exception as exc:
        premium_flow_validation = {
            "premium_flow_manifest_ok": False,
            "premium_flow_manifest_warnings": [],
            "premium_flow_manifest_errors": [f"validation_error:{exc}"],
            "observed_phases": [],
            "missing_critical_phases": [],
            "unexpected_mutators_after_freeze": [],
            "deprecated_routes_in_flow": [],
            "final_truth_source_ok": bool(final_truth_source in {"final_mp4_contract", "task_scoped_output"}),
            "manifest_state": "terminal_failed",
            "manifest_terminal": True,
            "premium_flow_manifest": premium_flow_manifest,
        }
    final_contract_snapshot.update(premium_flow_validation)
    h4_empirical_metadata = _collect_h4_empirical_metadata(
        clip,
        final_rendered_contract,
        final_contract,
        captions_metadata,
        bgm,
        sfx,
        hook,
        rhythm,
        visual_reinforcement,
        broll,
        transitions,
        audio_master,
        route_registry,
    )
    for _h4_key, _h4_default in {
        "text_overlap_prevented": False,
        "suppressed_text_layers": [],
        "text_layer_count_final": 0,
        "caption_priority_enforced": False,
        "pip_overlay_disabled": bool(final_contract_snapshot.get("vpi_daily_mode_enabled") or _as_dict(daily_mode_policy).get("vpi_daily_mode_enabled")),
        "thumbnail_overlay_disabled": bool(final_contract_snapshot.get("vpi_daily_mode_enabled") or _as_dict(daily_mode_policy).get("vpi_daily_mode_enabled")),
        "debug_preview_overlay_disabled": bool(final_contract_snapshot.get("vpi_daily_mode_enabled") or _as_dict(daily_mode_policy).get("vpi_daily_mode_enabled")),
        "debug_face_box_rendered": False,
        "debug_overlays_disabled": bool(final_contract_snapshot.get("vpi_daily_mode_enabled") or _as_dict(daily_mode_policy).get("vpi_daily_mode_enabled")),
        "caption_timebase_corrected": False,
        "caption_timebase_source": "",
        "caption_sync_warning": "",
        "broll_relevance_gate_passed": False,
        "broll_relevance_score": 0.0,
        "broll_skipped_unrelated": False,
        "bgm_volume_empirical_boost_applied": False,
        "bgm_target_volume_final": 0.0,
        "bts_tail_detected": False,
        "bts_tail_trimmed_seconds": 0.0,
        "viral_window_shifted_back": False,
        "viral_window_shift_reason": "",
        "daily_mode_external_route_active": False,
        "daily_mode_external_route_names": [],
        "daily_mode_external_source_allowed": bool(final_contract_snapshot.get("vpi_daily_mode_enabled") or _as_dict(daily_mode_policy).get("vpi_daily_mode_enabled")),
        "non_production_safe_route_used": False,
        "ass_event_count_before": 0,
        "ass_event_hard_cap": 22,
        "ass_events_merged_for_daily": False,
        "forced_shift_back_applied": False,
        "selected_alternative_for_complete_idea": False,
        "incomplete_window_uncorrectable": False,
    }.items():
        h4_empirical_metadata.setdefault(_h4_key, _h4_default)
    if bool(final_contract_snapshot.get("vpi_daily_mode_enabled") or _as_dict(daily_mode_policy).get("vpi_daily_mode_enabled")):
        h4_empirical_metadata.setdefault("pip_overlay_disabled", True)
        h4_empirical_metadata.setdefault("thumbnail_overlay_disabled", True)
        h4_empirical_metadata.setdefault("debug_preview_overlay_disabled", True)
        h4_empirical_metadata.setdefault("debug_face_box_rendered", False)
        h4_empirical_metadata.setdefault("debug_overlays_disabled", True)
        h4_empirical_metadata.setdefault("daily_mode_external_source_allowed", True)
    else:
        h4_empirical_metadata.setdefault("daily_mode_external_source_allowed", False)
    route_registry_used_routes: List[str] = []
    for _route_bundle in (route_registry, phase_consistency):
        bundle_dict = _as_dict(_route_bundle)
        for route_name in _safe_list(bundle_dict.get("primary_routes_used")) + _safe_list(bundle_dict.get("fallback_routes_used")):
            if _is_daily_mode_external_render_route(route_name):
                route_registry_used_routes.append(str(route_name))
        for _phase_bundle in bundle_dict.values():
            phase_dict = _as_dict(_phase_bundle)
            if _is_daily_mode_external_render_route(phase_dict.get("route_used")):
                route_registry_used_routes.append(str(phase_dict.get("route_used")))
            if _is_daily_mode_external_render_route(phase_dict.get("fallback_route")):
                route_registry_used_routes.append(str(phase_dict.get("fallback_route")))
    h4_empirical_metadata["daily_mode_external_route_names"] = _dedupe_strings(route_registry_used_routes)
    h4_empirical_metadata["daily_mode_external_route_active"] = bool(h4_empirical_metadata["daily_mode_external_route_names"])
    if not bool(h4_empirical_metadata["daily_mode_external_route_active"]):
        route_registry["production_safe_compliant"] = True
        route_registry_compliant = True
    final_contract_snapshot.update(h4_empirical_metadata)
    final_contract_snapshot["final_truth_source_ok"] = bool(final_truth_source in {"final_mp4_contract", "task_scoped_output"})
    premium_flow_manifest_errors = _safe_list(final_contract_snapshot.get("premium_flow_manifest_errors"))
    premium_flow_manifest_gap_only = bool(
        final_output_verified
        and final_video_exists
        and final_video_stream_ok
        and final_duration_ok
        and final_audio_stream_ok
        and premium_flow_manifest_errors
        and set(str(item) for item in premium_flow_manifest_errors).issubset(
            {"missing_critical_phases", "final_truth_source_not_contract"}
        )
    )
    if premium_flow_manifest_gap_only and not bool(final_contract_snapshot.get("premium_flow_manifest_ok", True)):
        final_contract_snapshot["premium_flow_manifest_ok"] = True
        final_contract_snapshot["premium_flow_manifest_warnings"] = list(
            dict.fromkeys(
                _safe_list(final_contract_snapshot.get("premium_flow_manifest_warnings"))
                + ["premium_flow_manifest_metadata_gap_only"]
            )
        )
        final_contract_snapshot["premium_flow_manifest_errors"] = []
        premium_flow_validation["premium_flow_manifest_ok"] = True
        premium_flow_validation["premium_flow_manifest_warnings"] = list(final_contract_snapshot["premium_flow_manifest_warnings"])
        premium_flow_validation["premium_flow_manifest_errors"] = []
    premium_flow_missing_critical_phases = _safe_list(final_contract_snapshot.get("missing_critical_phases"))
    premium_flow_metadata_gap_only = bool(
        final_output_verified
        and final_video_exists
        and final_video_stream_ok
        and final_duration_ok
        and final_audio_stream_ok
        and premium_flow_missing_critical_phases
        and set(str(item) for item in premium_flow_missing_critical_phases).issubset({"captions", "final_qc", "final_freeze"})
    )
    if premium_flow_metadata_gap_only and not bool(final_contract_snapshot.get("premium_flow_manifest_ok", True)):
        final_contract_snapshot["premium_flow_manifest_ok"] = True
        final_contract_snapshot["premium_flow_manifest_warnings"] = list(
            dict.fromkeys(
                _safe_list(final_contract_snapshot.get("premium_flow_manifest_warnings"))
                + ["premium_flow_manifest_metadata_gap_only"]
            )
        )
        final_contract_snapshot["premium_flow_manifest_errors"] = []
        premium_flow_validation["premium_flow_manifest_ok"] = True
        premium_flow_validation["premium_flow_manifest_warnings"] = list(final_contract_snapshot["premium_flow_manifest_warnings"])
        premium_flow_validation["premium_flow_manifest_errors"] = []
    visual_identity = validate_vpi_visual_identity(visual_identity_source)
    final_contract_snapshot.update(visual_identity)
    final_contract_snapshot["visual_design_tokens_applied"] = bool(final_contract_snapshot.get("visual_design_tokens_applied"))
    final_contract_snapshot["visual_design_version"] = str(final_contract_snapshot.get("visual_design_version") or get_vpi_visual_design_tokens().get("visual_design_version") or "a1")
    if not visual_identity.get("visual_identity_ok", True):
        final_blocking_reasons = list(dict.fromkeys(final_blocking_reasons + ["visual_identity_failed"]))
        final_publishable = False
        final_needs_review = True
    elif visual_identity.get("visual_identity_warnings"):
        final_warning_reasons = list(dict.fromkeys(final_warning_reasons + ["visual_identity_warning"]))
        final_needs_review = True
    if not bool(premium_flow_validation.get("premium_flow_manifest_ok", True)):
        if premium_flow_metadata_gap_only:
            final_warning_reasons = list(dict.fromkeys(final_warning_reasons + ["premium_flow_manifest_metadata_gap_only"]))
            final_needs_review = True
        else:
            final_blocking_reasons = list(dict.fromkeys(final_blocking_reasons + ["premium_flow_manifest_failed"]))
            final_publishable = False
            final_needs_review = True
    if premium_flow_validation.get("unexpected_mutators_after_freeze"):
        final_blocking_reasons = list(dict.fromkeys(final_blocking_reasons + ["output_mutation_after_final_lock"]))
        final_publishable = False
        final_needs_review = True
    elif premium_flow_validation.get("premium_flow_manifest_warnings"):
        final_warning_reasons = list(dict.fromkeys(final_warning_reasons + ["premium_flow_manifest_warning"]))
        final_needs_review = True
    metadata_consistency = validate_phase_metadata_consistency(
        final_contract_snapshot,
        route_registry,
        final_contract_snapshot,
    )
    phase_consistency = _as_dict(metadata_consistency.get("phase_consistency"))
    final_contract_snapshot.update(metadata_consistency)
    if not bool(final_contract_snapshot.get("visual_asset_coverage_ok", True)):
        final_warning_reasons = list(dict.fromkeys(final_warning_reasons + ["visual_asset_coverage_gap"]))
        final_needs_review = True
    if str(final_contract_snapshot.get("brand_logo_status") or "") == "skipped_no_verified_logo":
        final_warning_reasons = list(dict.fromkeys(final_warning_reasons + ["no_verified_brand_logo"]))
        final_needs_review = True
    metadata_consistency_failed_downgraded = False
    metadata_consistency_downgrade_reason = ""
    if not metadata_consistency["metadata_consistency_ok"]:
        metadata_consistency_errors = set(_safe_list(metadata_consistency.get("metadata_consistency_errors")))
        _sfx_gap_only_errors = {
            "production_safe_route_used",
            "sfx_applied_without_verified",
            "applied_without_verified",
        }
        _blocking_errors_only_sfx_gap = bool(
            metadata_consistency_errors
            and metadata_consistency_errors.issubset(_sfx_gap_only_errors)
            and "sfx_applied_without_verified" in metadata_consistency_errors
        )
        if _blocking_errors_only_sfx_gap:
            logger.info(
                "VPI_METADATA_CONSISTENCY_SFX_GAP_ERRORS_ACCEPTED task_id=%s clip_order=%d errors=%s",
                task_id or "unknown",
                clip_order,
                "|".join(sorted(metadata_consistency_errors)),
            )
        else:
            logger.info(
                "VPI_METADATA_CONSISTENCY_SFX_GAP_ERRORS_REJECTED_REAL_CONTRADICTION task_id=%s clip_order=%d errors=%s",
                task_id or "unknown",
                clip_order,
                "|".join(sorted(metadata_consistency_errors)),
            )
        _task_scope_ok_for_gap = final_output_is_task_scoped or _blocking_errors_only_sfx_gap
        if _blocking_errors_only_sfx_gap and not final_output_is_task_scoped:
            logger.info(
                "VPI_METADATA_CONSISTENCY_TASK_SCOPE_BYPASSED_FOR_SFX_GAP task_id=%s clip_order=%d",
                task_id or "unknown",
                clip_order,
            )
        elif not final_output_is_task_scoped:
            logger.info(
                "VPI_METADATA_CONSISTENCY_TASK_SCOPE_STILL_BLOCKING_REAL_ISSUE task_id=%s clip_order=%d",
                task_id or "unknown",
                clip_order,
            )
        metadata_consistency_gap_only = bool(
            final_output_verified
            and _task_scope_ok_for_gap
            and final_video_exists
            and final_video_stream_ok
            and final_duration_ok
            and final_audio_stream_ok
            and metadata_consistency_errors
            and (
                not any(
                    error in {
                        "final_output_verified_but_final_probe_failed",
                        "captions_expected_but_failed_or_missing",
                        "captions_expected_but_unverified",
                        "audio_expected_but_final_audio_stream_missing",
                        "production_safe_route_used",
                        "deprecated_routes_used_in_production_safe",
                    }
                    for error in metadata_consistency_errors
                )
                or _blocking_errors_only_sfx_gap
            )
        )
        if metadata_consistency_gap_only:
            metadata_consistency_failed_downgraded = True
            metadata_consistency_downgrade_reason = "inner_contract_stale_or_gap_with_verified_final_truth"
            if _blocking_errors_only_sfx_gap:
                logger.info(
                    "VPI_METADATA_CONSISTENCY_OLD_PROBE_ECHO_SUPPRESSED task_id=%s clip_order=%d errors=%s",
                    task_id or "unknown",
                    clip_order,
                    "|".join(sorted(metadata_consistency_errors)),
                )
            logger.info(
                "VPI_METADATA_CONSISTENCY_DOWNGRADED_INNER_CONTRACT_GAP task_id=%s clip_order=%d errors=%s sfx_gap=%s",
                task_id or "unknown",
                clip_order,
                "|".join(sorted(metadata_consistency_errors)),
                str(_blocking_errors_only_sfx_gap).lower(),
            )
            final_warning_reasons = list(dict.fromkeys(final_warning_reasons + ["metadata_consistency_warning"]))
            final_needs_review = True
            final_contract_snapshot["metadata_consistency_ok"] = True
            final_contract_snapshot["metadata_consistency_errors"] = []
            final_contract_snapshot["metadata_consistency_warnings"] = list(
                dict.fromkeys(
                    _safe_list(final_contract_snapshot.get("metadata_consistency_warnings"))
                    + ["metadata_consistency_gap_downgraded_inner_contract"]
                )
            )
        else:
            logger.warning(
                "VPI_METADATA_CONSISTENCY_BLOCKING_REAL_CONTRADICTION task_id=%s clip_order=%d errors=%s",
                task_id or "unknown",
                clip_order,
                "|".join(sorted(metadata_consistency_errors)),
            )
            final_blocking_reasons = list(dict.fromkeys(final_blocking_reasons + ["metadata_consistency_failed"]))
            final_publishable = False
            final_needs_review = True
    elif metadata_consistency["metadata_consistency_warnings"]:
        final_warning_reasons = list(dict.fromkeys(final_warning_reasons + ["metadata_consistency_warning"]))
        final_needs_review = True
    if bool(final_contract_snapshot.get("metadata_consistency_ok")):
        logger.info(
            "VPI_METADATA_CONSISTENCY_POST_MERGE_OK task_id=%s clip_order=%d",
            task_id or "unknown",
            clip_order,
        )
    if not bool(final_contract_snapshot.get("visual_layout_ok", True)):
        final_blocking_reasons = list(dict.fromkeys(final_blocking_reasons + ["visual_layout_invalid"]))
        final_publishable = False
        final_needs_review = True
    elif final_contract_snapshot.get("visual_layout_warnings"):
        final_warning_reasons = list(dict.fromkeys(final_warning_reasons + ["visual_layout_warning"]))
        final_needs_review = True
    text_layer_count_final = int(final_contract_snapshot.get("text_layer_count_final") or 0)
    if text_layer_count_final > 2 and not bool(final_contract_snapshot.get("text_overlap_prevented", True)):
        final_blocking_reasons = list(dict.fromkeys(final_blocking_reasons + ["text_overlap_detected"]))
        final_publishable = False
        final_needs_review = True
    elif text_layer_count_final > 2:
        final_warning_reasons = list(dict.fromkeys(final_warning_reasons + ["text_layer_overload"]))
        final_needs_review = True
    if bool(final_contract_snapshot.get("vpi_daily_mode_enabled")) and bool(final_contract_snapshot.get("debug_face_box_rendered")):
        final_blocking_reasons = list(dict.fromkeys(final_blocking_reasons + ["debug_face_box_rendered"]))
        final_publishable = False
        final_needs_review = True
    if bool(final_contract_snapshot.get("final_output_uses_motion_overlay")) and not bool(final_contract_snapshot.get("pip_overlay_disabled", True)):
        if bool(final_contract_snapshot.get("vpi_daily_mode_enabled")):
            final_blocking_reasons = list(dict.fromkeys(final_blocking_reasons + ["pip_overlay_enabled_in_daily_mode"]))
            final_publishable = False
            final_needs_review = True
        else:
            final_warning_reasons = list(dict.fromkeys(final_warning_reasons + ["pip_overlay_enabled"]))
            final_needs_review = True
    if bool(final_contract_snapshot.get("caption_sync_warning")) and not bool(final_contract_snapshot.get("caption_timebase_corrected", False)):
        final_warning_reasons = list(dict.fromkeys(final_warning_reasons + ["caption_timebase_sync_warning"]))
        final_needs_review = True
    if bool(final_contract_snapshot.get("broll_skipped_unrelated")):
        final_warning_reasons = list(dict.fromkeys(final_warning_reasons + ["broll_quality_warning"]))
        final_needs_review = True
    if bool(final_contract_snapshot.get("bts_tail_detected")) and not float(final_contract_snapshot.get("bts_tail_trimmed_seconds") or 0.0):
        final_warning_reasons = list(dict.fromkeys(final_warning_reasons + ["bts_tail_not_trimmed"]))
        final_needs_review = True
    if not bool(final_contract_snapshot.get("face_bbox_present", True)):
        final_warning_reasons = list(dict.fromkeys(final_warning_reasons + ["no_face_bbox_available"]))
        final_needs_review = True
    if str(final_contract_snapshot.get("face_crop_risk") or "") == "high" and bool(final_contract_snapshot.get("face_bbox_present")):
        final_blocking_reasons = list(dict.fromkeys(final_blocking_reasons + ["face_crop_risk_high"]))
        final_publishable = False
        final_needs_review = True
    elif final_contract_snapshot.get("reframe_skipped_reason"):
        final_warning_reasons = list(dict.fromkeys(final_warning_reasons + ["reframe_skipped_due_safety"]))
        final_needs_review = True
    if not bool(final_contract_snapshot.get("subtitle_clearance_applied", True)):
        final_warning_reasons = list(dict.fromkeys(final_warning_reasons + ["subtitle_clearance_approximate"]))
        final_needs_review = True
    if final_contract_snapshot.get("cta_decision") == "show_cta":
        if not bool(final_contract_snapshot.get("cta_rendered")):
            final_warning_reasons = list(dict.fromkeys(final_warning_reasons + ["cta_skipped_by_safety_or_restraint"]))
            final_needs_review = True
        if not bool(final_contract_snapshot.get("cta_safety_ok", True)) or not bool(final_contract_snapshot.get("visual_layout_caption_safe", True)):
            final_blocking_reasons = list(dict.fromkeys(final_blocking_reasons + ["cta_safety_violation"]))
            final_publishable = False
            final_needs_review = True
    if final_contract_snapshot.get("cta_rendered") and not bool(final_contract_snapshot.get("cta_verified", True)):
        final_warning_reasons = list(dict.fromkeys(final_warning_reasons + ["cta_rendered_unverified"]))
        final_needs_review = True
    if final_contract_snapshot.get("brand_treatment") and final_contract_snapshot.get("brand_final_mode") == "cta_minimal" and not bool(final_contract_snapshot.get("brand_final_verified", False)):
        final_warning_reasons = list(dict.fromkeys(final_warning_reasons + ["brand_final_unverified"]))
        final_needs_review = True
    if final_contract_snapshot.get("premium_restraint_mode") == "sensitive_minimal":
        prohibited_layers_rendered = bool(
            final_contract_snapshot.get("visual_reinforcement_applied")
            or final_contract_snapshot.get("overlay_card_applied")
            or final_contract_snapshot.get("semantic_card_applied")
        )
        if prohibited_layers_rendered and not bool(final_contract_snapshot.get("visual_layout_strategy") in {"no_extra_visual", "branding_minimal"}):
            final_blocking_reasons = list(dict.fromkeys(final_blocking_reasons + ["premium_restraint_sensitive_violation"]))
            final_publishable = False
            final_needs_review = True
    too_many_visual_supports = int(
        bool(final_contract_snapshot.get("visual_reinforcement_applied"))
        + bool(final_contract_snapshot.get("overlay_card_applied"))
        + bool(final_contract_snapshot.get("semantic_card_applied"))
        + bool(final_contract_snapshot.get("hook_card_applied"))
        + bool(final_contract_snapshot.get("brand_assets_verified"))
    )
    if final_contract_snapshot.get("clip_already_strong") and too_many_visual_supports > int(final_contract_snapshot.get("allowed_visual_support_count") or 1):
        final_warning_reasons = list(dict.fromkeys(final_warning_reasons + ["too_many_visual_supports"]))
        final_needs_review = True
        if not bool(final_contract_snapshot.get("visual_layout_face_safe", True)) or not bool(final_contract_snapshot.get("visual_layout_caption_safe", True)):
            final_blocking_reasons = list(dict.fromkeys(final_blocking_reasons + ["premium_restraint_overflow_unsafe"]))
            final_publishable = False
            final_needs_review = True
    if production_safe_active and metadata_consistency.get("deprecated_routes_used"):
        route_registry_compliant = False
        route_registry["production_safe_compliant"] = False
        if any(route_name not in {"legacy_caption_service_fallback", "legacy_caption_word_level"} for route_name in metadata_consistency.get("deprecated_routes_used") or []):
            final_warning_reasons = list(dict.fromkeys(final_warning_reasons + ["non_production_safe_route_used"]))
            final_needs_review = True
        else:
            final_warning_reasons = list(dict.fromkeys(final_warning_reasons + ["legacy_caption_fallback_used"]))
            final_needs_review = True
    if production_safe_active and not bool(route_registry.get("production_safe_compliant", True)):
        final_warning_reasons = list(dict.fromkeys(final_warning_reasons + ["non_production_safe_route_used"]))
        final_needs_review = True
    if daily_mode_policy is not None and not isinstance(daily_mode_policy, dict):
        logger.warning(
            "VPI_PUBLISHABLE_GATE_STR_SAFE_COERCION daily_mode_policy_type=%s",
            type(daily_mode_policy).__name__,
        )
    daily_mode_enabled = bool(final_contract_snapshot.get("vpi_daily_mode_enabled") or _as_dict(daily_mode_policy).get("vpi_daily_mode_enabled"))
    daily_mode_unsafe_override_used = bool(final_contract_snapshot.get("daily_mode_unsafe_override_used") or _as_dict(daily_mode_policy).get("daily_mode_unsafe_override_used"))
    if daily_mode_enabled and not daily_mode_unsafe_override_used and bool(final_contract_snapshot.get("daily_mode_external_route_active")):
        final_blocking_reasons = list(dict.fromkeys(final_blocking_reasons + ["daily_mode_external_route_active"]))
        final_warning_reasons = list(dict.fromkeys(final_warning_reasons + ["daily_mode_external_route_conflict"]))
        final_publishable = False
        final_needs_review = True
    final_contract_snapshot["final_publishable"] = bool(final_publishable)
    final_contract_snapshot["final_needs_review"] = bool(final_needs_review)
    final_contract_snapshot["final_blocking_reasons"] = list(dict.fromkeys(final_blocking_reasons))
    final_contract_snapshot["final_warning_reasons"] = list(dict.fromkeys(final_warning_reasons))
    final_contract_snapshot["production_safe_compliant"] = bool(route_registry_compliant)
    final_contract_snapshot["filename_contract_mode"] = str(clip.get("filename_contract_mode") or "legacy_warning_only")
    final_contract_snapshot["premium_flow_manifest_ok"] = bool(premium_flow_validation.get("premium_flow_manifest_ok", False))
    final_contract_snapshot["premium_flow_manifest_warnings"] = list(premium_flow_validation.get("premium_flow_manifest_warnings") or [])
    final_contract_snapshot["premium_flow_manifest_errors"] = list(premium_flow_validation.get("premium_flow_manifest_errors") or [])
    final_contract_snapshot["observed_phase_order"] = list(premium_flow_validation.get("observed_phases") or [])
    final_contract_snapshot["missing_critical_phases"] = list(premium_flow_validation.get("missing_critical_phases") or [])
    final_contract_snapshot["unexpected_mutators_after_freeze"] = list(premium_flow_validation.get("unexpected_mutators_after_freeze") or [])
    final_contract_snapshot["premium_flow_manifest"] = dict(premium_flow_validation.get("premium_flow_manifest") or premium_flow_manifest or {})
    if production_safe_active and bool(route_registry.get("production_safe_compliant", True)):
        logger.info(
            "PRODUCTION_SAFE_COMPLIANCE_PASSED task_id=%s clip_order=%d blocked=%d allowed=%d",
            task_id or "unknown",
            clip_order,
            len(route_registry.get("production_safe_routes_blocked") or []),
            len((production_safe_policy or {}).get("production_safe_routes_allowed") or []),
        )
    elif production_safe_active:
        logger.warning(
            "PRODUCTION_SAFE_COMPLIANCE_WARNING task_id=%s clip_order=%d blocked=%d compliant=%s",
            task_id or "unknown",
            clip_order,
            len(route_registry.get("production_safe_routes_blocked") or []),
            str(bool(route_registry.get("production_safe_compliant", True))).lower(),
        )
    _manifest_state = str(final_contract_snapshot.get("manifest_state") or ("valid" if not final_contract_snapshot.get("premium_flow_manifest_errors") else "terminal_failed"))
    logger.info(
        "PREMIUM_FLOW_MANIFEST_VALIDATED task_id=%s clip_order=%d ok=%s state=%s missing=%d mutators=%d",
        task_id or "unknown",
        clip_order,
        str(bool(final_contract_snapshot.get("premium_flow_manifest_ok"))).lower(),
        _manifest_state,
        len(final_contract_snapshot.get("missing_critical_phases") or []),
        len(final_contract_snapshot.get("unexpected_mutators_after_freeze") or []),
    )
    if final_contract_snapshot.get("premium_flow_manifest_errors") and _manifest_state == "pending":
        # PREMIUM-44: pre-freeze validation (phases not yet written) — not a terminal failure.
        logger.info(
            "VPI_PREMIUM_MANIFEST_PENDING task_id=%s clip_order=%d errors=%s",
            task_id or "unknown", clip_order,
            "|".join(final_contract_snapshot.get("premium_flow_manifest_errors") or []) or "none",
        )
    elif final_contract_snapshot.get("premium_flow_manifest_errors"):
        logger.warning(
            "PREMIUM_FLOW_MANIFEST_FAILED task_id=%s clip_order=%d errors=%s",
            task_id or "unknown",
            clip_order,
            "|".join(final_contract_snapshot.get("premium_flow_manifest_errors") or []) or "none",
        )
    elif final_contract_snapshot.get("premium_flow_manifest_warnings"):
        logger.warning(
            "PREMIUM_FLOW_MANIFEST_WARNING task_id=%s clip_order=%d warnings=%s",
            task_id or "unknown",
            clip_order,
            "|".join(final_contract_snapshot.get("premium_flow_manifest_warnings") or []) or "none",
        )
    if final_contract_snapshot.get("visual_identity_ok"):
        logger.info(
            "VPI_VISUAL_IDENTITY_CHECKED task_id=%s clip_order=%d ok=%s warnings=%d",
            task_id or "unknown",
            clip_order,
            str(bool(final_contract_snapshot.get("visual_identity_ok"))).lower(),
            len(final_contract_snapshot.get("visual_identity_warnings") or []),
        )
    else:
        logger.warning(
            "VPI_VISUAL_IDENTITY_FAILED task_id=%s clip_order=%d warnings=%s",
            task_id or "unknown",
            clip_order,
            "|".join(final_contract_snapshot.get("visual_identity_warnings") or []) or "none",
        )
    if final_contract_snapshot.get("visual_identity_warnings"):
        logger.warning(
            "VPI_VISUAL_IDENTITY_WARNING task_id=%s clip_order=%d warnings=%s",
            task_id or "unknown",
            clip_order,
            "|".join(final_contract_snapshot.get("visual_identity_warnings") or []) or "none",
        )
    if final_contract_snapshot.get("visual_layout_warnings"):
        if not final_contract_snapshot.get("visual_layout_ok", True):
            logger.warning(
                "VISUAL_LAYOUT_BLOCKED_BY_BUDGET task_id=%s clip_order=%d reason=%s",
                task_id or "unknown",
                clip_order,
                "|".join(final_contract_snapshot.get("visual_layout_warnings") or []) or "none",
            )
        else:
            logger.warning(
                "VISUAL_LAYOUT_WARNING task_id=%s clip_order=%d warnings=%s",
                task_id or "unknown",
                clip_order,
                "|".join(final_contract_snapshot.get("visual_layout_warnings") or []) or "none",
            )
    if final_contract_snapshot.get("premium_restraint_applied"):
        logger.info(
            "PREMIUM_RESTRAINT_APPLIED task_id=%s clip_order=%d mode=%s reason=%s",
            task_id or "unknown",
            clip_order,
            final_contract_snapshot.get("premium_restraint_mode") or "balanced",
            final_contract_snapshot.get("premium_restraint_reason") or "none",
        )
        if final_contract_snapshot.get("premium_restraint_suppressed_layers"):
            logger.info(
                "PREMIUM_RESTRAINT_SUPPRESSED task_id=%s clip_order=%d layers=%s",
                task_id or "unknown",
                clip_order,
                "|".join(final_contract_snapshot.get("premium_restraint_suppressed_layers") or []) or "none",
            )
        if final_contract_snapshot.get("clip_already_strong"):
            logger.info(
                "PREMIUM_RESTRAINT_SELECTED task_id=%s clip_order=%d mode=%s allowed=%d",
                task_id or "unknown",
                clip_order,
                final_contract_snapshot.get("premium_restraint_mode") or "balanced",
                int(final_contract_snapshot.get("allowed_visual_support_count") or 1),
            )
    if final_contract_snapshot.get("premium_restraint_mode") and not final_contract_snapshot.get("premium_restraint_applied"):
        logger.warning(
            "PREMIUM_RESTRAINT_WARNING task_id=%s clip_order=%d reason=restraint_not_applied",
            task_id or "unknown",
            clip_order,
        )
    logger.info(
        "VPI_VISUAL_TOKENS_APPLIED task_id=%s clip_order=%d captions=%s hook=%s reinforcement=%s branding=%s",
        task_id or "unknown",
        clip_order,
        str(bool(final_contract_snapshot.get("visual_design_tokens_applied_to_captions"))).lower(),
        str(bool(final_contract_snapshot.get("visual_design_tokens_applied_to_hook"))).lower(),
        str(bool(final_contract_snapshot.get("visual_design_tokens_applied_to_reinforcement"))).lower(),
        str(bool(final_contract_snapshot.get("visual_design_tokens_applied_to_branding"))).lower(),
    )
    if final_contract_snapshot.get("visual_asset_coverage_ok"):
        logger.info(
            "VISUAL_ASSET_COVERAGE_CHECKED task_id=%s clip_order=%d ok=%s missing=%d",
            task_id or "unknown",
            clip_order,
            str(bool(final_contract_snapshot.get("visual_asset_coverage_ok"))).lower(),
            len(final_contract_snapshot.get("missing_visual_intents") or []),
        )
    else:
        logger.warning(
            "VISUAL_ASSET_COVERAGE_WARNING task_id=%s clip_order=%d missing=%s weak=%s",
            task_id or "unknown",
            clip_order,
            "|".join(final_contract_snapshot.get("missing_visual_intents") or []) or "none",
            "|".join(final_contract_snapshot.get("weak_visual_intents") or []) or "none",
        )
    if final_contract_snapshot.get("visual_asset_selected"):
        logger.info(
            "VISUAL_ASSET_SELECTED task_id=%s clip_order=%d asset=%s reason=%s",
            task_id or "unknown",
            clip_order,
            final_contract_snapshot.get("visual_asset_selected"),
            final_contract_snapshot.get("visual_asset_selection_reason") or "none",
        )
    elif final_contract_snapshot.get("visual_asset_fallback_used"):
        logger.info(
            "VISUAL_ASSET_FALLBACK_USED task_id=%s clip_order=%d reason=%s",
            task_id or "unknown",
            clip_order,
            final_contract_snapshot.get("visual_asset_selection_reason") or "none",
        )
    if final_contract_snapshot.get("sensitive_visual_asset_blocked"):
        logger.warning(
            "SENSITIVE_VISUAL_ASSET_BLOCKED task_id=%s clip_order=%d reason=%s",
            task_id or "unknown",
            clip_order,
            final_contract_snapshot.get("visual_asset_selection_reason") or "sensitive_content",
        )
    if final_contract_snapshot.get("brand_assets_verified"):
        logger.info(
            "BRAND_ASSET_VERIFIED task_id=%s clip_order=%d asset=%s",
            task_id or "unknown",
            clip_order,
            final_contract_snapshot.get("brand_logo_asset_id") or "none",
        )
    else:
        logger.warning(
            "BRAND_ASSET_WARNING task_id=%s clip_order=%d status=%s",
            task_id or "unknown",
            clip_order,
            final_contract_snapshot.get("brand_logo_status") or "none",
        )
    if final_contract_snapshot.get("cta_rendered"):
        logger.info(
            "VPI_CTA_RENDERED task_id=%s clip_order=%d decision=%s type=%s",
            task_id or "unknown",
            clip_order,
            final_contract_snapshot.get("cta_decision") or "no_cta",
            final_contract_snapshot.get("cta_type") or "no_cta",
        )
    elif final_contract_snapshot.get("cta_decision") == "show_cta":
        logger.info(
            "VPI_CTA_SKIPPED_REASON task_id=%s clip_order=%d reason=%s",
            task_id or "unknown",
            clip_order,
            final_contract_snapshot.get("cta_skipped_reason") or "cta_not_rendered",
        )
    if final_contract_snapshot.get("final_audio_chain_errors"):
        logger.warning(
            "FINAL_AUDIO_CHAIN_FAILED task_id=%s clip_order=%d errors=%s",
            task_id or "unknown",
            clip_order,
            "|".join(final_contract_snapshot.get("final_audio_chain_errors") or []) or "none",
        )
    elif final_contract_snapshot.get("final_audio_chain_warnings"):
        logger.warning(
            "FINAL_AUDIO_CHAIN_WARNING task_id=%s clip_order=%d warnings=%s",
            task_id or "unknown",
            clip_order,
            "|".join(final_contract_snapshot.get("final_audio_chain_warnings") or []) or "none",
        )
    else:
        logger.info(
            "FINAL_AUDIO_CHAIN_VERIFIED task_id=%s clip_order=%d base_voice=%s bgm=%s sfx=%s mastering=%s",
            task_id or "unknown",
            clip_order,
            str(bool(final_contract_snapshot.get("base_voice_audio_present"))).lower(),
            str(final_contract_snapshot.get("bgm_final_status") or "").lower(),
            str(final_contract_snapshot.get("sfx_final_status") or "").lower(),
            str(final_contract_snapshot.get("audio_mastering_final_status") or "").lower(),
        )
    if final_contract_snapshot.get("final_audio_silence_likely"):
        logger.warning(
            "FINAL_AUDIO_LOUDNESS_WARNING task_id=%s clip_order=%d too_quiet=%s clipping=%s silence=%s",
            task_id or "unknown",
            clip_order,
            str(bool(final_contract_snapshot.get("final_audio_too_quiet"))).lower(),
            str(bool(final_contract_snapshot.get("final_audio_clipping_risk"))).lower(),
            str(bool(final_contract_snapshot.get("final_audio_silence_likely"))).lower(),
        )
    elif final_contract_snapshot.get("final_audio_too_quiet") or final_contract_snapshot.get("final_audio_clipping_risk"):
        logger.warning(
            "FINAL_AUDIO_LOUDNESS_WARNING task_id=%s clip_order=%d too_quiet=%s clipping=%s silence=%s",
            task_id or "unknown",
            clip_order,
            str(bool(final_contract_snapshot.get("final_audio_too_quiet"))).lower(),
            str(bool(final_contract_snapshot.get("final_audio_clipping_risk"))).lower(),
            str(bool(final_contract_snapshot.get("final_audio_silence_likely"))).lower(),
        )
    elif final_contract_snapshot.get("final_audio_loudness_ok"):
        logger.info(
            "FINAL_AUDIO_LOUDNESS_OK task_id=%s clip_order=%d mean_db=%s lufs=%s",
            task_id or "unknown",
            clip_order,
            _as_dict(final_contract_snapshot.get("final_audio_analysis")).get("mean_volume_db"),
            _as_dict(final_contract_snapshot.get("final_audio_analysis")).get("integrated_lufs"),
        )
    if final_video_exists_flag and final_video_stream_ok and (not has_audio_expected or final_audio_stream_ok) and final_duration_ok:
        logger.info("FINAL_OUTPUT_VERIFIED task_id=%s clip_order=%d path=%s", task_id or "unknown", clip_order, str(final_path))
    if final_publishable:
        logger.info("FINAL_MP4_CONTRACT_PASSED task_id=%s clip_order=%d path=%s", task_id or "unknown", clip_order, str(final_path))
    else:
        logger.info(
            "FINAL_MP4_CONTRACT_FAILED task_id=%s clip_order=%d reason=%s",
            task_id or "unknown",
            clip_order,
            "|".join(final_blocking_reasons) or "unknown",
        )
        logger.info(
            "FINAL_QC_BLOCKED_PUBLISHABLE task_id=%s clip_order=%d reasons=%s",
            task_id or "unknown",
            clip_order,
            "|".join(final_blocking_reasons) or "unknown",
        )

    logger.info(
        "FINAL_MP4_CONTRACT_BUILT task_id=%s clip_order=%d publishable=%s needs_review=%s",
        task_id or "unknown",
        clip_order,
        str(final_publishable).lower(),
        str(final_needs_review).lower(),
    )

    return {
        "contract_version": "v1",
        "final_output_path": str(final_path),
        "final_duration": actual_duration,
        "physical_duration_s": float(actual_duration or 0.0),
        "physical_readable": bool(probe_ok),
        "physical_video_stream_valid": bool(final_video_stream_ok),
        "physical_audio_stream_valid": bool(final_audio_stream_ok),
        "selection_window_duration": float(expected_duration_s or clip.get("duration") or 0.0),
        "selection_complete_idea_score": float(selection_complete_idea_score),
        "selection_incomplete_viral_window_detected": bool(selection_incomplete_viral_window_detected),
        "final_contract_reconciled": bool(final_contract_reconciled),
        "reconciliation_reason": str(reconciliation_reason),
        "duration_reconciliation_delta_s": round(float(expected_duration_mismatch_s or 0.0), 3),
        "render_safety_pass": bool(probe_ok and final_video_stream_ok and final_duration_ok and (final_audio_stream_ok or not has_audio_expected)),
        "final_probe_ok": bool(probe_ok),
        "final_contract_ok": bool(final_publishable),
        "render_success": bool(final_video_exists and final_video_stream_ok and final_file_size_ok),
        "final_video_exists": bool(final_video_exists),
        "final_video_stream_ok": bool(final_video_stream_ok),
        "final_audio_stream_ok": bool(final_audio_stream_ok),
        "final_duration_ok": bool(final_duration_ok),
        "final_file_size_ok": bool(final_file_size_ok),
        "technical_valid": bool(final_video_exists and final_video_stream_ok and final_audio_stream_ok and final_duration_ok and final_file_size_ok),
        "has_video": bool(final_video_stream_ok),
        "has_audio": bool(final_audio_stream_ok),
        "has_captions": bool(captions_present),
        "has_branding": bool(_as_dict(clip.get("brand_treatment")).get("rendered") or clip.get("watermark") or clip.get("branding_applied")),
        "brand_assets_verified": bool(final_contract_snapshot.get("brand_assets_verified")),
        "brand_logo_asset_id": str(final_contract_snapshot.get("brand_logo_asset_id") or ""),
        "brand_logo_status": str(final_contract_snapshot.get("brand_logo_status") or ""),
        "brand_final_mode": str(final_contract_snapshot.get("brand_final_mode") or ""),
        "brand_final_verified": bool(final_contract_snapshot.get("brand_final_verified")),
        "brand_final_reason": str(final_contract_snapshot.get("brand_final_reason") or ""),
        "cta_decision": str(final_contract_snapshot.get("cta_decision") or ""),
        "cta_type": str(final_contract_snapshot.get("cta_type") or ""),
        "cta_text": str(final_contract_snapshot.get("cta_text") or ""),
        "cta_planned": bool(final_contract_snapshot.get("cta_planned")),
        "cta_rendered": bool(final_contract_snapshot.get("cta_rendered")),
        "cta_verified": bool(final_contract_snapshot.get("cta_verified")),
        "cta_reason": str(final_contract_snapshot.get("cta_reason") or ""),
        "cta_skipped_reason": str(final_contract_snapshot.get("cta_skipped_reason") or ""),
        "cta_safety_ok": bool(final_contract_snapshot.get("cta_safety_ok")),
        "cta_safety_warnings": list(final_contract_snapshot.get("cta_safety_warnings") or []),
        "cta_safety_rewritten": bool(final_contract_snapshot.get("cta_safety_rewritten")),
        "cta_safety_reason": str(final_contract_snapshot.get("cta_safety_reason") or ""),
        "visual_design_version": str(final_contract_snapshot.get("visual_design_version") or get_vpi_visual_design_tokens().get("visual_design_version") or "a1"),
        "visual_design_tokens_applied": bool(final_contract_snapshot.get("visual_design_tokens_applied")),
        "visual_design_tokens_applied_to_captions": bool(final_contract_snapshot.get("visual_design_tokens_applied_to_captions")),
        "visual_design_tokens_applied_to_hook": bool(final_contract_snapshot.get("visual_design_tokens_applied_to_hook")),
        "visual_design_tokens_applied_to_reinforcement": bool(final_contract_snapshot.get("visual_design_tokens_applied_to_reinforcement")),
        "visual_design_tokens_applied_to_branding": bool(final_contract_snapshot.get("visual_design_tokens_applied_to_branding")),
        "visual_layout_strategy": str(final_contract_snapshot.get("visual_layout_strategy") or ""),
        "visual_layout_zone": str(final_contract_snapshot.get("visual_layout_zone") or ""),
        "visual_layout_size": str(final_contract_snapshot.get("visual_layout_size") or ""),
        "visual_layout_opacity": float(final_contract_snapshot.get("visual_layout_opacity") or 0.0),
        "visual_layout_duration": float(final_contract_snapshot.get("visual_layout_duration") or 0.0),
        "visual_layout_reason": str(final_contract_snapshot.get("visual_layout_reason") or ""),
        "visual_layout_face_safe": bool(final_contract_snapshot.get("visual_layout_face_safe")),
        "visual_layout_caption_safe": bool(final_contract_snapshot.get("visual_layout_caption_safe")),
        "visual_layout_ok": bool(final_contract_snapshot.get("visual_layout_ok")),
        "visual_layout_warnings": list(final_contract_snapshot.get("visual_layout_warnings") or []),
        "premium_restraint_mode": str(final_contract_snapshot.get("premium_restraint_mode") or ""),
        "premium_restraint_applied": bool(final_contract_snapshot.get("premium_restraint_applied")),
        "premium_restraint_reason": str(final_contract_snapshot.get("premium_restraint_reason") or ""),
        "premium_restraint_suppressed_layers": list(final_contract_snapshot.get("premium_restraint_suppressed_layers") or []),
        "allowed_visual_support_count": int(final_contract_snapshot.get("allowed_visual_support_count") or 0),
        "clip_already_strong": bool(final_contract_snapshot.get("clip_already_strong")),
        "visual_support_reduced_reason": str(final_contract_snapshot.get("visual_support_reduced_reason") or ""),
        "restraint_broll_interaction": str(final_contract_snapshot.get("restraint_broll_interaction") or ""),
        "visual_identity_ok": bool(final_contract_snapshot.get("visual_identity_ok")),
        "visual_identity_warnings": list(final_contract_snapshot.get("visual_identity_warnings") or []),
        "visual_style_consistency_ok": bool(final_contract_snapshot.get("visual_style_consistency_ok")),
        "brand_assets_verified": bool(final_contract_snapshot.get("brand_assets_verified")),
        "brand_logo_asset_id": str(final_contract_snapshot.get("brand_logo_asset_id") or ""),
        "brand_logo_status": str(final_contract_snapshot.get("brand_logo_status") or ""),
        "visual_asset_inventory_summary": dict(final_contract_snapshot.get("visual_asset_inventory_summary") or {}),
        "visual_asset_coverage_ok": bool(final_contract_snapshot.get("visual_asset_coverage_ok")),
        "missing_visual_intents": list(final_contract_snapshot.get("missing_visual_intents") or []),
        "weak_visual_intents": list(final_contract_snapshot.get("weak_visual_intents") or []),
        "missing_visual_families": list(final_contract_snapshot.get("missing_visual_families") or []),
        "weak_visual_families": list(final_contract_snapshot.get("weak_visual_families") or []),
        "sensitive_visual_available": bool(final_contract_snapshot.get("sensitive_visual_available")),
        "visual_asset_inventory_used": bool(final_contract_snapshot.get("visual_asset_inventory_used")),
        "visual_asset_selected": str(final_contract_snapshot.get("visual_asset_selected") or ""),
        "visual_asset_selection_reason": str(final_contract_snapshot.get("visual_asset_selection_reason") or ""),
        "visual_asset_fallback_used": bool(final_contract_snapshot.get("visual_asset_fallback_used")),
        "sensitive_visual_asset_blocked": bool(final_contract_snapshot.get("sensitive_visual_asset_blocked")),
        "visual_asset_identity_warnings": list(final_contract_snapshot.get("visual_asset_identity_warnings") or []),
        "motion_profile": str(final_contract_snapshot.get("motion_profile") or ""),
        "motion_profile_reason": str(final_contract_snapshot.get("motion_profile_reason") or ""),
        "zoom_intensity": float(final_contract_snapshot.get("zoom_intensity") or 0.0),
        "max_zoom_events": int(final_contract_snapshot.get("max_zoom_events") or 0),
        "actual_zoom_events": int(final_contract_snapshot.get("actual_zoom_events") or 0),
        "first3_motion_boost_applied": bool(final_contract_snapshot.get("first3_motion_boost_applied")),
        "first3_motion_boost_reason": str(final_contract_snapshot.get("first3_motion_boost_reason") or ""),
        "intentional_pause_preserved": bool(final_contract_snapshot.get("intentional_pause_preserved")),
        "dead_pause_trimmed": bool(final_contract_snapshot.get("dead_pause_trimmed")),
        "motion_polish_applied": bool(final_contract_snapshot.get("motion_polish_applied")),
        "motion_polish_warnings": list(final_contract_snapshot.get("motion_polish_warnings") or []),
        "framing_profile": str(final_contract_snapshot.get("framing_profile") or ""),
        "framing_reason": str(final_contract_snapshot.get("framing_reason") or ""),
        "target_anchor": str(final_contract_snapshot.get("target_anchor") or ""),
        "safe_crop_margin": float(final_contract_snapshot.get("safe_crop_margin") or 0.0),
        "headroom_policy": str(final_contract_snapshot.get("headroom_policy") or ""),
        "subtitle_clearance_policy": str(final_contract_snapshot.get("subtitle_clearance_policy") or ""),
        "max_reframe_shift": float(final_contract_snapshot.get("max_reframe_shift") or 0.0),
        "face_bbox_present": bool(final_contract_snapshot.get("face_bbox_present")),
        "speaker_bbox_present": bool(final_contract_snapshot.get("speaker_bbox_present")),
        "face_framing_safe": bool(final_contract_snapshot.get("face_framing_safe")),
        "headroom_safe": bool(final_contract_snapshot.get("headroom_safe")),
        "face_crop_risk": str(final_contract_snapshot.get("face_crop_risk") or ""),
        "face_framing_adjusted": bool(final_contract_snapshot.get("face_framing_adjusted")),
        "subtitle_clearance_applied": bool(final_contract_snapshot.get("subtitle_clearance_applied")),
        "cta_clearance_applied": bool(final_contract_snapshot.get("cta_clearance_applied")),
        "reframe_skipped_reason": str(final_contract_snapshot.get("reframe_skipped_reason") or ""),
        "original_frame_preserved": bool(final_contract_snapshot.get("original_frame_preserved")),
        "framing_polish_applied": bool(final_contract_snapshot.get("framing_polish_applied")),
        "framing_polish_warnings": list(final_contract_snapshot.get("framing_polish_warnings") or []),
        "has_bgm": bool(bgm_applied or bgm_verified),
        "has_sfx": bool(sfx_applied or sfx_verified),
        "has_broll": bool(broll_applied or broll_verified),
        "broll_timing_strategy": str(final_contract_snapshot.get("broll_timing_strategy") or ""),
        "broll_timing_reason": str(final_contract_snapshot.get("broll_timing_reason") or ""),
        "broll_phrase_matched": bool(final_contract_snapshot.get("broll_phrase_matched")),
        "broll_phrase_match_terms": list(final_contract_snapshot.get("broll_phrase_match_terms") or []),
        "broll_phrase_match_confidence": float(final_contract_snapshot.get("broll_phrase_match_confidence") or 0.0),
        "broll_entry_style": str(final_contract_snapshot.get("broll_entry_style") or ""),
        "broll_exit_style": str(final_contract_snapshot.get("broll_exit_style") or ""),
        "broll_transition_sober": bool(final_contract_snapshot.get("broll_transition_sober")),
        "broll_return_to_speaker": bool(final_contract_snapshot.get("broll_return_to_speaker")),
        "broll_return_reason": str(final_contract_snapshot.get("broll_return_reason") or ""),
        "has_motion_or_vfx": bool(
            visual_reinforcement_applied
            or visual_reinforcement_verified
            or rhythm_applied
            or bool(_as_dict(clip.get("visual_effects")).get("visual_effects_applied"))
            or bool(_as_dict(clip.get("motion_overlay")).get("motion_overlay_applied"))
        ),
        "has_transition": bool(transitions_applied or transitions_verified),
        "final_captions_expected": bool(captions_expected),
        "final_captions_present": bool(captions_present),
        "final_captions_status": captions_status,
        "final_bgm_expected": bool(bgm_expected),
        "final_bgm_applied": bool(bgm_applied),
        "final_bgm_status": bgm_status,
        "final_sfx_expected": bool(sfx_expected),
        "final_sfx_applied": bool(sfx_applied),
        "final_sfx_status": sfx_status,
        "final_hook_status": hook_status,
        "final_rhythm_status": rhythm_status,
        "final_visual_budget_status": visual_budget_status,
        "final_visual_reinforcement_status": visual_reinforcement_status,
        "final_broll_status": broll_status,
        "broll_status": broll_status,
        "final_transition_status": transition_status,
        "transition_status": transition_status,
        "transition_polish_mode": str(final_contract_snapshot.get("transition_polish_mode") or ""),
        "transition_duration_ms": int(final_contract_snapshot.get("transition_duration_ms") or 0),
        "transition_reason": str(final_contract_snapshot.get("transition_reason") or ""),
        "transition_should_render": bool(final_contract_snapshot.get("transition_should_render")),
        "transition_repetition_avoided": bool(final_contract_snapshot.get("transition_repetition_avoided")),
        "transition_broll_sync_ok": bool(final_contract_snapshot.get("transition_broll_sync_ok")),
        "transition_broll_sync_reason": str(final_contract_snapshot.get("transition_broll_sync_reason") or ""),
        "transition_sfx_allowed": bool(final_contract_snapshot.get("transition_sfx_allowed")),
        "transition_sfx_family": str(final_contract_snapshot.get("transition_sfx_family") or ""),
        "transition_sfx_suppressed_reason": str(final_contract_snapshot.get("transition_sfx_suppressed_reason") or ""),
        "final_audio_mastering_status": audio_mastering_status,
        "final_audio_chain_ok": bool(final_audio_chain_ok),
        "final_audio_chain_errors": list(dict.fromkeys(final_audio_chain_errors)),
        "final_audio_chain_warnings": list(dict.fromkeys(final_audio_chain_warnings)),
        "base_voice_audio_present": bool(base_voice_audio_present),
        "audio_duplicate_passes_blocked": list(dict.fromkeys(audio_duplicate_passes_blocked)),
        "bgm_pass_count": int(bgm_pass_count),
        "sfx_pass_count": int(sfx_pass_count),
        "bgm_final_status": bgm_final_status,
        "sfx_final_status": sfx_final_status,
        "audio_mastering_final_status": audio_mastering_final_status,
        "final_publishable": bool(final_publishable),
        "final_needs_review": bool(final_needs_review),
        "final_blocking_reasons": list(dict.fromkeys(final_blocking_reasons)),
        "final_warning_reasons": list(dict.fromkeys(final_warning_reasons)),
        "complete_idea_score": float(selection_complete_idea_score),
        "incomplete_viral_window_detected": bool(incomplete_viral_window_detected),
        "final_text_complete": bool(final_text_complete),
        "final_closure_contained": bool(final_closure_contained),
        "publishability_timeline_gate_passed": bool(final_timeline_gate_passed),
        "audio_sync_verified": bool(final_audio_sync_verified),
        "final_truth_source": final_truth_source,
        "final_truth_source_ok": bool(final_truth_source in {"final_mp4_contract", "task_scoped_output"}),
        "final_output_verified": bool(final_video_exists_flag and final_video_stream_ok and (final_audio_stream_ok or not has_audio_expected) and final_duration_ok),
        "final_output_is_task_scoped": bool(final_output_is_task_scoped),
        "final_output_not_latest_stage": bool(final_output_verified and not final_output_is_task_scoped),
        "route_registry": route_registry,
        "route_registry_version": str(route_registry.get("route_registry_version") or "a2"),
        "production_safe_compliant": bool(route_registry_compliant),
        "vpi_daily_mode_enabled": bool(final_contract_snapshot.get("vpi_daily_mode_enabled")),
        "daily_mode_version": str(final_contract_snapshot.get("daily_mode_version") or "a1"),
        "daily_mode_policy": dict(final_contract_snapshot.get("daily_mode_policy") or {}),
        "daily_mode_outputs_enabled": bool(final_contract_snapshot.get("daily_mode_outputs_enabled")),
        "daily_mode_conflicts_resolved": list(final_contract_snapshot.get("daily_mode_conflicts_resolved") or []),
        "daily_mode_unsafe_override_used": bool(final_contract_snapshot.get("daily_mode_unsafe_override_used")),
        "daily_mode_external_route_active": bool(final_contract_snapshot.get("daily_mode_external_route_active")),
        "daily_mode_external_route_names": list(final_contract_snapshot.get("daily_mode_external_route_names") or []),
        "daily_mode_external_source_allowed": bool(final_contract_snapshot.get("daily_mode_external_source_allowed")),
        "stage_recorder": dict(_as_dict(clip.get("stage_recorder")) or _as_dict(final_contract.get("stage_recorder")) or {}),
        "ass_event_count_before": int(final_contract_snapshot.get("ass_event_count_before") or 0),
        "ass_event_hard_cap": int(final_contract_snapshot.get("ass_event_hard_cap") or 22),
        "ass_events_merged_for_daily": bool(final_contract_snapshot.get("ass_events_merged_for_daily")),
        "forced_shift_back_applied": bool(final_contract_snapshot.get("forced_shift_back_applied")),
        "selected_alternative_for_complete_idea": bool(final_contract_snapshot.get("selected_alternative_for_complete_idea")),
        "incomplete_window_uncorrectable": bool(final_contract_snapshot.get("incomplete_window_uncorrectable")),
        "text_overlap_prevented": bool(final_contract_snapshot.get("text_overlap_prevented")),
        "suppressed_text_layers": list(final_contract_snapshot.get("suppressed_text_layers") or []),
        "text_layer_count_final": int(final_contract_snapshot.get("text_layer_count_final") or 0),
        "caption_priority_enforced": bool(final_contract_snapshot.get("caption_priority_enforced")),
        "pip_overlay_disabled": bool(final_contract_snapshot.get("pip_overlay_disabled")),
        "thumbnail_overlay_disabled": bool(final_contract_snapshot.get("thumbnail_overlay_disabled")),
        "debug_preview_overlay_disabled": bool(final_contract_snapshot.get("debug_preview_overlay_disabled")),
        "debug_face_box_rendered": bool(final_contract_snapshot.get("debug_face_box_rendered")),
        "debug_overlays_disabled": bool(final_contract_snapshot.get("debug_overlays_disabled")),
        "caption_timebase_corrected": bool(final_contract_snapshot.get("caption_timebase_corrected")),
        "caption_timebase_source": str(final_contract_snapshot.get("caption_timebase_source") or ""),
        "caption_sync_warning": str(final_contract_snapshot.get("caption_sync_warning") or ""),
        "broll_relevance_gate_passed": bool(final_contract_snapshot.get("broll_relevance_gate_passed")),
        "broll_relevance_score": float(final_contract_snapshot.get("broll_relevance_score") or 0.0),
        "broll_skipped_unrelated": bool(final_contract_snapshot.get("broll_skipped_unrelated")),
        "bgm_volume_empirical_boost_applied": bool(final_contract_snapshot.get("bgm_volume_empirical_boost_applied")),
        "bgm_target_volume_final": float(final_contract_snapshot.get("bgm_target_volume_final") or 0.0),
        "bts_tail_detected": bool(final_contract_snapshot.get("bts_tail_detected")),
        "bts_tail_trimmed_seconds": float(final_contract_snapshot.get("bts_tail_trimmed_seconds") or 0.0),
        "viral_window_shifted_back": bool(final_contract_snapshot.get("viral_window_shifted_back")),
        "viral_window_shift_reason": str(final_contract_snapshot.get("viral_window_shift_reason") or ""),
        "filename_contract_mode": str(clip.get("filename_contract_mode") or "legacy_warning_only"),
        "output_root": str(_as_dict(clip).get("output_root") or final_contract_snapshot.get("output_root") or ""),
        "clips_output_dir": str(_as_dict(clip).get("clips_output_dir") or final_contract_snapshot.get("clips_output_dir") or ""),
        "output_manifest_path": str(_as_dict(clip).get("output_manifest_path") or final_contract_snapshot.get("output_manifest_path") or ""),
        "output_summary_path": str(_as_dict(clip).get("output_summary_path") or final_contract_snapshot.get("output_summary_path") or ""),
        "output_filename_strategy": str(_as_dict(clip).get("output_filename_strategy") or final_contract_snapshot.get("output_filename_strategy") or "vpi_{campaign_intent}_{clip_angle}_{confidence}_{start}_{end}_{clip_id_hash}"),
        "output_filename_safe": bool(_as_dict(clip).get("output_filename_safe") if _as_dict(clip).get("output_filename_safe") is not None else final_contract_snapshot.get("output_filename_safe", True)),
        "output_filename_collision_resolved": bool(_as_dict(clip).get("output_filename_collision_resolved") if _as_dict(clip).get("output_filename_collision_resolved") is not None else final_contract_snapshot.get("output_filename_collision_resolved", False)),
        "output_management_ok": bool(_as_dict(clip).get("output_management_ok") if _as_dict(clip).get("output_management_ok") is not None else final_contract_snapshot.get("output_management_ok", False)),
        "output_management_warnings": list(_as_dict(clip).get("output_management_warnings") or final_contract_snapshot.get("output_management_warnings") or []),
        "browser_mp4_normalization_nonfatal": bool(
            _as_dict(clip).get("browser_mp4_normalization_nonfatal")
            if _as_dict(clip).get("browser_mp4_normalization_nonfatal") is not None
            else final_contract_snapshot.get("browser_mp4_normalization_nonfatal", False)
        ),
        "output_clip_count": int(_as_dict(clip).get("output_clip_count") or final_contract_snapshot.get("output_clip_count") or 0),
        "publishable_clip_count": int(_as_dict(clip).get("publishable_clip_count") or final_contract_snapshot.get("publishable_clip_count") or 0),
        "review_clip_count": int(_as_dict(clip).get("review_clip_count") or final_contract_snapshot.get("review_clip_count") or 0),
        "review_bundle_dir": str(_as_dict(clip).get("review_bundle_dir") or final_contract_snapshot.get("review_bundle_dir") or ""),
        "review_index_path": str(_as_dict(clip).get("review_index_path") or final_contract_snapshot.get("review_index_path") or ""),
        "review_bundle_json_path": str(_as_dict(clip).get("review_bundle_json_path") or final_contract_snapshot.get("review_bundle_json_path") or ""),
        "review_bundle_ready": bool(_as_dict(clip).get("review_bundle_ready") if _as_dict(clip).get("review_bundle_ready") is not None else final_contract_snapshot.get("review_bundle_ready", False)),
        "review_bundle_warnings": list(_as_dict(clip).get("review_bundle_warnings") or final_contract_snapshot.get("review_bundle_warnings") or []),
        "production_safe_routes_blocked": list(dict.fromkeys(route_registry_blocked)),
        "legacy_routes_blocked": list(dict.fromkeys(route_registry_legacy_blocked)),
        "external_routes_blocked": list(dict.fromkeys(route_registry_external_blocked)),
        "fallback_routes_used": list(dict.fromkeys(route_registry_fallbacks)),
        "primary_routes_used": list(dict.fromkeys(route_registry_primaries)),
        "legacy_routes_quarantined": list(legacy_routes_quarantined),
        "experimental_routes_quarantined": list(experimental_routes_quarantined),
        "deprecated_routes_present": list(deprecated_routes_present),
        "deprecated_routes_used": list(deprecated_routes_used),
        "deprecated_routes_blocked": list(deprecated_routes_blocked),
        "legacy_route_warning": list(legacy_route_warning),
        "premium_flow_manifest_version": str((premium_flow_manifest or {}).get("manifest_version") or "a1"),
        "premium_flow_manifest_ok": bool(final_contract_snapshot.get("premium_flow_manifest_ok", False)),
        "premium_flow_manifest_warnings": list(final_contract_snapshot.get("premium_flow_manifest_warnings") or []),
        "premium_flow_manifest_errors": list(final_contract_snapshot.get("premium_flow_manifest_errors") or []),
        "observed_phase_order": list(final_contract_snapshot.get("observed_phase_order") or []),
        "missing_critical_phases": list(final_contract_snapshot.get("missing_critical_phases") or []),
        "unexpected_mutators_after_freeze": list(final_contract_snapshot.get("unexpected_mutators_after_freeze") or []),
        "premium_flow_manifest": dict(final_contract_snapshot.get("premium_flow_manifest") or premium_flow_manifest or {}),
        "final_contract": {
            "music": bool(bgm_applied or bgm_verified),
            "sfx": bool(sfx_applied or sfx_verified),
            "vfx": bool(visual_reinforcement_applied or visual_reinforcement_verified or rhythm_applied or bool(_as_dict(clip.get("visual_effects")).get("visual_effects_applied"))),
            "broll": bool(broll_applied or broll_verified),
            "captions": bool(captions_present),
            "transition": bool(transitions_applied or transitions_verified),
            "hook": bool(hook_applied or hook_verified),
            "audio": bool(final_audio_stream_ok),
            "video": bool(final_video_stream_ok),
        },
        "qa_passed": bool(final_publishable),
        "evidence_sources": {
            "final_qc_report": qc_report,
            "final_output_flags": {
                "music": bool(bgm_applied or bgm_verified),
                "sfx": bool(sfx_applied or sfx_verified),
                "vfx": bool(visual_reinforcement_applied or visual_reinforcement_verified or rhythm_applied),
                "captions": bool(captions_present),
            },
            "phase_statuses": {
                "captions": captions_status,
                "bgm": bgm_status,
                "sfx": sfx_status,
                "hook": hook_status,
                "rhythm": rhythm_status,
                "visual_budget": visual_budget_status,
                "visual_reinforcement": visual_reinforcement_status,
                "broll": broll_status,
                "transition": transition_status,
                "audio_mastering": audio_mastering_status,
            },
        },
        "final_qc_report": qc_report,
        "production_safe": bool(production_safe),
        "production_safe_compliant": bool(route_registry_compliant),
        "legacy_routes_quarantined": list(legacy_routes_quarantined),
        "experimental_routes_quarantined": list(experimental_routes_quarantined),
        "deprecated_routes_present": list(deprecated_routes_present),
        "deprecated_routes_used": list(deprecated_routes_used),
        "deprecated_routes_blocked": list(deprecated_routes_blocked),
        "legacy_route_warning": list(legacy_route_warning),
        "phase_metadata": {
            "captions": cap,
            "bgm": bgm,
            "sfx": sfx,
            "hook": hook,
            "rhythm": rhythm,
            "visual_layer_budget": budget,
            "visual_reinforcement": visual_reinforcement,
            "broll": broll,
            "transitions": transitions,
            "audio_mastering": audio_master,
        },
        "production_safe_policy": dict(production_safe_policy or {}),
        "production_safe_policy_version": str((production_safe_policy or {}).get("policy_version") or "a4"),
        "production_safe_mode_active": bool(production_safe_active),
        "production_safe_external_disabled": bool((production_safe_policy or {}).get("production_safe_external_disabled", production_safe_active)),
        "production_safe_legacy_disabled": bool((production_safe_policy or {}).get("production_safe_legacy_disabled", production_safe_active)),
        "production_safe_routes_allowed": list((production_safe_policy or {}).get("production_safe_routes_allowed") or []),
        "production_safe_routes_blocked": list((production_safe_policy or {}).get("production_safe_routes_blocked") or []),
        "audio_chain_plan": dict(audio_chain_plan or {}),
        "audio_chain_state": dict(audio_chain_state or {}),
        "bgm_pass_count": int(bgm_pass_count),
        "sfx_pass_count": int(sfx_pass_count),
        "audio_duplicate_passes_blocked": list(dict.fromkeys(audio_duplicate_passes_blocked)),
        "bgm_final_status": bgm_final_status,
        "sfx_final_status": sfx_final_status,
        "audio_mastering_final_status": audio_mastering_final_status,
        "base_voice_audio_present": bool(base_voice_audio_present),
        "metadata_consistency_ok": bool(metadata_consistency["metadata_consistency_ok"]),
        "metadata_consistency_errors": list(metadata_consistency["metadata_consistency_errors"]),
        "metadata_consistency_warnings": list(metadata_consistency["metadata_consistency_warnings"]),
        "phase_consistency": metadata_consistency["phase_consistency"],
    }


class PublishableStatus(str, Enum):
    """Publishability classification for a single clip."""
    READY_TO_UPLOAD = "ready_to_upload"
    REVIEW_MANUALLY = "review_manually"
    NEEDS_FIX = "needs_fix"
    DO_NOT_UPLOAD = "do_not_upload"


class UploadRecommendation(str, Enum):
    """Upload recommendation after ranking across all clips."""
    BEST_CANDIDATE = "best_candidate"
    GOOD_CANDIDATE = "good_candidate"
    REVIEW_BEFORE_UPLOAD = "review_before_upload"
    DISCARD_RECOMMENDED = "discard_recommended"


@dataclass
class PublishableGateResult:
    """Complete publishability assessment for one clip."""
    publishable_status: PublishableStatus
    publishable_score: float          # 0-100 numeric score
    publishable_reasons: List[str]    # why this status was assigned
    publishable_warnings: List[str]   # non-blocking concerns
    upload_recommendation: UploadRecommendation = UploadRecommendation.REVIEW_BEFORE_UPLOAD
    best_candidate: bool = False
    discard_recommended: bool = False
    weak_intro_detected: bool = False
    generic_broll_detected: bool = False
    forbidden_broll_detected: bool = False
    editing_activity_ok: bool = True
    hook_first_4s_ok: bool = True
    technical_qc_ok: bool = True
    audio_qc_ok: bool = True
    silence_ok: bool = True
    captions_ok: bool = True
    branding_ok: bool = True
    missing_editing_layers: List[str] = field(default_factory=list)
    recommended_next_fix: str = ""
    retention_quality_score: int = 0
    retention_quality_status: str = ""
    retention_missing_layers: List[str] = field(default_factory=list)
    private_premium_status: str = ""
    private_premium_editorial_quality: str = ""
    private_premium_postproduction_richness: str = ""
    private_premium_limited_assets: bool = False

    # ── FASE 5: Editorial Fluency fields ──────────────────────────────────
    editorial_fluency_ok: bool = True
    editorial_fluency_score: float = 0.0
    complete_idea_score: float = 0.0
    fluency_score_after: float = 0.0
    hook_fit_acceptable: bool = False
    editorial_fluency_warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "publishable_status": self.publishable_status.value,
            "publishable_score": self.publishable_score,
            "publishable_reasons": self.publishable_reasons,
            "publishable_warnings": self.publishable_warnings,
            "upload_recommendation": self.upload_recommendation.value,
            "best_candidate": self.best_candidate,
            "discard_recommended": self.discard_recommended,
            "weak_intro_detected": self.weak_intro_detected,
            "generic_broll_detected": self.generic_broll_detected,
            "forbidden_broll_detected": self.forbidden_broll_detected,
            "editing_activity_ok": self.editing_activity_ok,
            "hook_first_4s_ok": self.hook_first_4s_ok,
            "technical_qc_ok": self.technical_qc_ok,
            "audio_qc_ok": self.audio_qc_ok,
            "silence_ok": self.silence_ok,
            "captions_ok": self.captions_ok,
            "branding_ok": self.branding_ok,
            "missing_editing_layers": self.missing_editing_layers,
            "recommended_next_fix": self.recommended_next_fix,
            "retention_quality_score": self.retention_quality_score,
            "retention_quality_status": self.retention_quality_status,
            "retention_missing_layers": self.retention_missing_layers,
            "private_premium_status": self.private_premium_status,
            "private_premium_editorial_quality": self.private_premium_editorial_quality,
            "private_premium_postproduction_richness": self.private_premium_postproduction_richness,
            "private_premium_limited_assets": self.private_premium_limited_assets,
            "editorial_fluency_ok": self.editorial_fluency_ok,
            "editorial_fluency_score": self.editorial_fluency_score,
            "complete_idea_score": self.complete_idea_score,
            "fluency_score_after": self.fluency_score_after,
            "hook_fit_acceptable": self.hook_fit_acceptable,
            "editorial_fluency_warnings": self.editorial_fluency_warnings,
        }


# ── Threshold constants ──────────────────────────────────────────────────────

# Editing activity: number of editorial actions applied (reframe, broll, hook,
# silence, captions, branding).  >= 6 → good activity.
EDITING_ACTIVITY_READY_THRESHOLD = 6
EDITING_ACTIVITY_NEEDS_FIX_THRESHOLD = 5

# Hook first 4s score (0-5).  >= 2 → acceptable hook presence.
HOOK_FIRST_4S_MIN_SCORE = 2

# Minimum publishable score thresholds for each status.
SCORE_READY_MIN = 70.0
SCORE_REVIEW_MIN = 40.0
SCORE_NEEDS_FIX_MIN = 20.0

# B-roll generic penalty when documents_admin is used with emotional editorial.
BROLL_GENERIC_DOCUMENTS_PENALTY = 25.0

# No-B-roll penalty when speaker is the focus (no penalty for talking-head).
NO_BROLL_SPEAKER_PENALTY = 0.0

# Weak intro base penalty.
WEAK_INTRO_PENALTY = 30.0


def _is_vpi_productive_minimum() -> bool:
    """Check if VPI productive minimum mode is active (env or config)."""
    val = os.environ.get("VPI_PRODUCTIVE_MINIMUM", "")
    if val:
        return val.lower() in ("1", "true", "yes")
    beta = os.environ.get("VIRACLIP_BETA_CLEAN", "")
    if beta.lower() in ("1", "true", "yes"):
        return True
    return False


def assess_retention_quality(clip_info: Dict[str, Any]) -> Dict[str, Any]:
    clip_info = _as_dict(clip_info)
    editing_plan = _as_dict(clip_info.get("editing_plan"))
    hook_plan = _as_dict(clip_info.get("hook_plan")) or _as_dict(editing_plan.get("hook_plan"))
    music = _as_dict(clip_info.get("music")) or _as_dict(editing_plan.get("music"))
    sfx = _as_dict(clip_info.get("sfx")) or _as_dict(editing_plan.get("sfx"))
    visual = _as_dict(clip_info.get("visual_effects")) or _as_dict(editing_plan.get("visual_effects"))
    transitions = _as_dict(clip_info.get("transitions")) or _as_dict(editing_plan.get("transitions"))
    broll_items = [item for item in _safe_list(clip_info.get("editorial_broll")) if isinstance(item, dict)]
    silence = _as_dict(clip_info.get("silence_edit_plan")) or _as_dict(editing_plan.get("silence_edit_plan"))
    caption_support = _as_dict(editing_plan.get("caption_visual_support_plan")) or _as_dict(clip_info.get("caption_visual_support"))

    # ── FIX 8: Check premium_layers_applied before trusting optimistic metadata ──
    premium_raw = clip_info.get("premium_layers_applied")
    premium_applied: List[str] = premium_raw if isinstance(premium_raw, list) else []
    has_premium_trace = ("premium_layers_applied" in clip_info) and (premium_raw is not None)
    if has_premium_trace:
        music_verified = "bgm" in premium_applied
        sfx_applied = "sfx" in premium_applied
        vfx_applied = "vfx" in premium_applied
        broll_applied = "broll" in premium_applied
        transition_applied = "transition" in premium_applied
        rhythm_applied = "rhythm" in premium_applied
    else:
        # Fallback: optimistic metadata
        music_verified = bool(music.get("music_final_verified"))
        sfx_applied = bool(sfx.get("sfx_final_verified") or sfx.get("sfx_applied"))
        vfx_applied = bool(visual.get("visual_effects_final_verified") or visual.get("visual_effects_applied") or visual.get("motion_scaling_events"))
        broll_applied = bool(broll_items)
        transition_applied = bool(transitions.get("final_output_uses_transition") or transitions.get("transitions_applied"))
        rhythm_applied = bool(visual.get("frame_rhythm_applied") or editing_plan.get("frame_rhythm_applied"))

    # [vpi-productive-minimum] Check for productive minimum fallback flags in
    # the editing plan sub-plans. These indicate that the layer was applied as
    # a fallback to ensure minimum visual support for strict QC.
    vpi_pm_active = _is_vpi_productive_minimum()
    vfx_pm_fallback = bool(visual.get("vpi_productive_minimum_fallback"))
    trans_pm_fallback = bool(transitions.get("vpi_productive_minimum_fallback"))
    _hook_strategy_raw = editing_plan.get("hook_strategy")
    if _hook_strategy_raw is not None and not isinstance(_hook_strategy_raw, dict):
        logger.warning(
            "VPI_PUBLISHABLE_GATE_ATTRERROR_STR_GET_PREVENTED hook_strategy_type=%s",
            type(_hook_strategy_raw).__name__,
        )
    hook_pm_mitigation = bool(
        hook_plan.get("vpi_productive_minimum_mitigation")
        or _as_dict(_hook_strategy_raw).get("vpi_productive_minimum_mitigation")
    )

    score = 0
    missing: List[str] = []

    hook_score = int(hook_plan.get("hook_first3_score") or hook_plan.get("hook_first3_retention_score") or 0)
    hook_status = str(hook_plan.get("hook_first3_status") or "")
    hook_strong = hook_score >= 5 and hook_status not in {"weak", "weak_intro"} and hook_plan.get("hook_type") != "weak_intro"
    if hook_strong:
        score += 2
    elif vpi_pm_active and hook_pm_mitigation:
        # [vpi-productive-minimum] Accept mitigated hooks as partial credit
        score += 1
        logger.info("[vpi-productive-minimum] hook partial credit: mitigation active for score=%d", hook_score)
    else:
        missing.append("strong_first3_hook")

    silence_summary = silence.get("summary") or {}
    if silence_summary.get("pattern_interruption_opportunities") or silence_summary.get("tension_silences_preserved"):
        score += 2
    else:
        missing.append("silence_pattern_interruption")

    # ── FIX 8: Use premium_layers_applied trace for scoring ──
    # music_verified, sfx_applied, vfx_applied, broll_applied, transition_applied,
    # rhythm_applied are already set from premium_layers_applied (lines 161-177)
    if music_verified:
        score += 2
    else:
        tracks_found = int(music.get("music_tracks_found") or 0)
        if tracks_found > 0:
            missing.append("music_final_verified")

    sfx_assets = sfx.get("sfx_assets_available") or {}
    sfx_assets_found = any(int(sfx_assets.get(key) or 0) > 0 for key in ("low_risers", "high_risers", "whooshes", "booms"))
    if sfx_applied:
        score += 2
    elif sfx_assets_found:
        missing.append("sfx_design")

    if vfx_applied:
        score += 2
    elif vpi_pm_active and vfx_pm_fallback:
        # [vpi-productive-minimum] Accept VFX fallback as partial credit
        score += 1
        logger.info("[vpi-productive-minimum] vfx partial credit: fallback active")
    else:
        missing.append("visual_effects")

    broll_useful = any((item or {}).get("reason") or (item or {}).get("semantic_score") for item in broll_items)
    abrupt_broll = any(
        not bool((item or {}).get("broll_transition_applied"))
        and (item or {}).get("transition_type") in {"", None, "none"}
        for item in broll_items
    )
    image_without_kenburns = any(
        bool((item or {}).get("is_image") or (item or {}).get("broll_is_image"))
        and not bool((item or {}).get("ken_burns_applied") or (item or {}).get("broll_ken_burns_applied"))
        for item in broll_items
    )
    if broll_applied and broll_useful and not abrupt_broll and not image_without_kenburns:
        score += 2
    elif broll_applied:
        missing.append("broll_transition_or_kenburns")

    if caption_support.get("caption_visual_support_applied") or caption_support.get("enabled"):
        score += 1
    if rhythm_applied:
        score += 1
    else:
        missing.append("frame_rhythm")

    planned_transitions = bool(transitions.get("transition_events") or transitions.get("transition_plan"))
    if planned_transitions and not transition_applied:
        missing.append("premium_transition_final_verified")
    elif transition_applied:
        score += 1
    elif vpi_pm_active and trans_pm_fallback:
        # [vpi-productive-minimum] Accept transition fallback as partial credit
        score += 1
        logger.info("[vpi-productive-minimum] transition partial credit: fallback active")

    if score <= 4:
        status = "poor"
    elif score <= 7:
        status = "acceptable"
    elif score <= 10:
        status = "good"
    else:
        status = "strong"
    if not sfx_applied:
        if sfx.get("sfx_warning") == "sfx_missing_worker_assets" and status == "strong":
            status = "good"
        elif sfx_assets_found and status in {"good", "strong"}:
            status = "acceptable"

    if "strong_first3_hook" in missing:
        next_fix = "strengthen_first3_hook"
    elif "music_final_verified" in missing:
        next_fix = "verify_music_final_mix"
    elif "sfx_design" in missing:
        next_fix = "apply_intentional_sfx"
    elif "visual_effects" in missing:
        next_fix = "apply_intentional_visual_effect"
    elif "broll_transition_or_kenburns" in missing:
        next_fix = "fix_broll_transition_or_kenburns"
    else:
        next_fix = "manual_review"
    logger.info("[retention-gate] score=%d status=%s missing=%s", score, status, "|".join(missing) or "none")
    return {
        "retention_quality_score": score,
        "retention_quality_status": status,
        "retention_missing_layers": missing,
        "recommended_next_fix": next_fix,
    }


def assess_private_premium_status(
    *,
    content_quality_reject: bool,
    complete_idea_score: float,
    fluency_score_after: float,
    hook_first3_ok: bool,
    hook_fit_acceptable: bool,
    tech_qc_ok: bool,
    audio_qc_ok: bool,
    captions_ok: bool,
    branding_ok: bool,
    silence_plan: Dict[str, Any],
    visual_effects_meta: Dict[str, Any],
    transitions_meta: Dict[str, Any],
    sfx_meta: Dict[str, Any],
    broll_items: List[Dict[str, Any]],
    editing_richness_status: str,
    editing_richness_warnings: List[str],
    first3_visual_contract: Optional[Dict[str, Any]] = None,
    premium_layers_applied: Optional[List[str]] = None,
    vpi_productive_minimum_mitigation: bool = False,
) -> Dict[str, Any]:
    silence_plan = _as_dict(silence_plan)
    visual_effects_meta = _as_dict(visual_effects_meta)
    transitions_meta = _as_dict(transitions_meta)
    sfx_meta = _as_dict(sfx_meta)
    broll_items = [item for item in _safe_list(broll_items) if isinstance(item, dict)]
    editing_richness_warnings = [str(item) for item in _safe_list(editing_richness_warnings)]
    first3_visual_contract = _as_dict(first3_visual_contract)

    # ── FIX 8: Check premium_layers_applied before trusting optimistic metadata ──
    has_premium_layers_trace = premium_layers_applied is not None
    premium_applied: List[str] = premium_layers_applied if isinstance(premium_layers_applied, list) else []
    vpi_pm_active = _is_vpi_productive_minimum()

    visual_events = list(visual_effects_meta.get("visual_effects_events") or [])
    visual_quality = str(
        visual_effects_meta.get("visual_effect_quality")
        or visual_effects_meta.get("visual_effects_quality")
        or ""
    )

    if has_premium_layers_trace:
        # Honest trace from create_single_clip
        has_premium_visual = "vfx" in premium_applied
        contextual_transition = "transition" in premium_applied
        contextual_sfx = "sfx" in premium_applied
        meaningful_silence = "rhythm" in premium_applied
        shot_rhythm_pack = "rhythm" in premium_applied
        has_broll = "broll" in premium_applied
    else:
        # Fallback: optimistic metadata
        has_premium_visual = bool(
            visual_quality == "premium_visual_effect"
            or any((event or {}).get("visual_effect_classification") == "premium_visual_effect" for event in visual_events)
        )
        contextual_transition = bool(
            transitions_meta.get("transition_contextual")
            or any((event or {}).get("contextual") for event in transitions_meta.get("transition_events") or [])
        )
        contextual_sfx = bool(
            sfx_meta.get("sfx_contextual")
            or any((event or {}).get("contextual") for event in (sfx_meta.get("sfx_design_events") or sfx_meta.get("sfx_events") or []))
        )
        meaningful_silence = bool(
            silence_plan.get("rendered")
            or float(silence_plan.get("total_removed_s") or 0.0) > 0.15
            or (silence_plan.get("summary") or {}).get("tension_silences_preserved")
        )
        shot_rhythm = dict(silence_plan.get("shot_rhythm") or {})
        shot_rhythm_pack = bool(
            shot_rhythm.get("applied")
            and (
                (shot_rhythm.get("microcuts") or [])
                or (shot_rhythm.get("preserved_pauses") or [])
                or (shot_rhythm.get("pattern_interruptions") or [])
                or float(shot_rhythm.get("pacing_score_after_estimate") or 0.0)
                > float(shot_rhythm.get("pacing_score_before") or 0.0) + 0.01
            )
        )
        has_broll = bool(broll_items)

    has_basic_motion = bool(
        visual_quality == "basic_motion"
        or any((event or {}).get("visual_effect_classification") == "basic_motion" for event in visual_events)
    )
    shot_rhythm = dict(silence_plan.get("shot_rhythm") or {})
    pacing_after = float(shot_rhythm.get("pacing_score_after_estimate") or 0.0)
    # [vpi-productive-minimum] Accept productive minimum mitigation as a valid
    # editorial action so that clips with mitigated hooks pass the
    # perceptible_editorial_action gate.
    _hook_first3_effective = hook_first3_ok or (vpi_pm_active and vpi_productive_minimum_mitigation)
    perceptible_editorial_action = bool(
        meaningful_silence
        or shot_rhythm_pack
        or has_premium_visual
        or contextual_transition
        or contextual_sfx
        or has_broll
        or _hook_first3_effective
    )
    broll_missing_opportunity = any(
        str(item) in {"broll_asset_missing_or_conflict", "broll_editorial_opportunity_unfulfilled"}
        for item in (editing_richness_warnings or [])
    )
    sfx_missing_opportunity = any(
        str(item) in {"sfx_editorial_opportunity_unfulfilled", "sfx_low_variation"}
        for item in (editing_richness_warnings or [])
    )
    finish_missing_opportunity = any(
        str(item) in {"finish_limited_assets_or_safety"}
        for item in (editing_richness_warnings or [])
    )
    finish_safety_blocked = any(
        str(item) in {"finish_safety_blocked"}
        for item in (editing_richness_warnings or [])
    )
    limited_assets = (
        (not has_broll and not has_premium_visual and not contextual_transition)
        or broll_missing_opportunity
        or sfx_missing_opportunity
        or finish_missing_opportunity
    )
    # [vpi-productive-minimum] When productive minimum mitigation is active,
    # don't flag limited_assets since fallback layers are intentionally minimal.
    if vpi_pm_active and vpi_productive_minimum_mitigation:
        limited_assets = False

    if has_premium_layers_trace:
        # Use premium_layers_applied for richness too
        if has_broll or has_premium_visual or contextual_transition:
            richness = "rich" if contextual_sfx or "vfx" in premium_applied else "moderate"
        elif has_basic_motion or contextual_sfx or meaningful_silence:
            richness = "moderate"
        else:
            richness = "limited"
    else:
        if has_broll or has_premium_visual or contextual_transition:
            richness = "rich" if contextual_sfx or visual_effects_meta.get("visual_effects_applied") else "moderate"
        elif has_basic_motion or contextual_sfx or meaningful_silence:
            richness = "moderate"
        else:
            richness = "limited"

    # ── CAMBIO 5: first3_visual_contract downgrade ──────────────────────────
    _first3_contract = first3_visual_contract or {}
    _first3_fail_count = int(_first3_contract.get("first3_visual_fail_count") or 0)
    _first3_contract_failed = _first3_fail_count >= 2

    if content_quality_reject:
        status = "DO_NOT_UPLOAD"
        editorial_quality = "blocked_bts_or_low_speech"
        reason = "bts_contamination"
    elif complete_idea_score < 0.75:
        status = "DO_NOT_UPLOAD"
        editorial_quality = "incomplete"
        reason = "incomplete_idea"
    elif fluency_score_after < 0.70:
        status = "DO_NOT_UPLOAD"
        editorial_quality = "disfluent"
        reason = "visible_disfluency"
    elif not tech_qc_ok or not audio_qc_ok or not captions_ok:
        status = "DO_NOT_UPLOAD"
        editorial_quality = "technical_blocked"
        reason = "technical_audio_or_caption_failure"
    elif not _hook_first3_effective:
        status = "PRIVATE_PREMIUM_REVIEW"
        editorial_quality = "review_hook"
        reason = "weak_hook"
    elif _first3_contract_failed:
        status = "PRIVATE_PREMIUM_REVIEW"
        editorial_quality = "review_first3_visual_contract"
        reason = f"first3_visual_contract_failed:{_first3_fail_count}_failures"
    elif finish_safety_blocked:
        status = "PRIVATE_PREMIUM_REVIEW"
        editorial_quality = "review_finish_safety"
        reason = "finish_safety_blocked"
    elif pacing_after and pacing_after < 0.58 and (not hook_fit_acceptable or fluency_score_after < 0.75):
        status = "PRIVATE_PREMIUM_REVIEW"
        editorial_quality = "review_rhythm_pacing"
        reason = "low_pacing_after_rhythm"
    elif not perceptible_editorial_action:
        status = "PRIVATE_PREMIUM_REVIEW"
        editorial_quality = "review_editorial_action"
        reason = "no_perceptible_editorial_action"
    elif limited_assets:
        status = "PRIVATE_PREMIUM_LIMITED_ASSETS"
        editorial_quality = "solid"
        reason = "limited_assets"
    else:
        status = "PRIVATE_PREMIUM_READY"
        editorial_quality = "solid"
        reason = "complete_fluent_contextual_hook"

    if editing_richness_status == "rich" and (
        complete_idea_score < 0.75
        or (not hook_first3_ok and not hook_fit_acceptable)
        or ("visually_too_plain" in editing_richness_warnings)
        or (limited_assets and not has_premium_visual)
    ):
        logger.info("[quality-gate] rich_blocked reason=private_premium_honesty")

    if status == "PRIVATE_PREMIUM_READY":
        logger.info("[quality-gate] ready reason=%s", reason)
    elif status == "PRIVATE_PREMIUM_REVIEW":
        logger.info("[quality-gate] review reason=%s", reason)

    logger.info("[private-premium] status=%s", status)
    logger.info("[private-premium] editorial_quality=%s", editorial_quality)
    logger.info("[private-premium] postproduction_richness=%s", richness)
    logger.info("[private-premium] limited_assets=%s", str(limited_assets).lower())
    if broll_missing_opportunity:
        logger.info("[private-premium] limited_assets=true reason=broll_asset_missing")
    elif sfx_missing_opportunity:
        logger.info("[private-premium] limited_assets=true reason=sfx_asset_missing_or_low_variation")
    elif finish_missing_opportunity:
        logger.info("[private-premium] limited_assets=true reason=finish_limited_assets_or_safety")
    return {
        "private_premium_status": status,
        "private_premium_editorial_quality": editorial_quality,
        "private_premium_postproduction_richness": richness,
        "private_premium_limited_assets": limited_assets,
        "private_premium_reason": reason,
        "private_premium_perceptible_editorial_action": perceptible_editorial_action,
    }


def build_final_qc_report(
    *,
    private_premium_status: str,
    editing_richness: Dict[str, Any],
    composition_decision: Dict[str, Any],
    first3_visual_contract: Dict[str, Any],
    caption_overlay_pack: Dict[str, Any],
    motion_pack: Dict[str, Any],
    broll_metadata: Dict[str, Any],
    sfx_metadata: Dict[str, Any],
    cinematic_finish: Dict[str, Any],
    shot_rhythm: Dict[str, Any],
    audio_metadata: Dict[str, Any],
    subtitle_metadata: Dict[str, Any],
    segment_text: str,
    motion_overlay_metadata: Optional[Dict[str, Any]] = None,
    dynamic_overlay_text_metadata: Optional[Dict[str, Any]] = None,
    final_mp4_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    status_in = str(private_premium_status or "")
    richness = _as_dict(editing_richness)
    first3 = _as_dict(first3_visual_contract)
    cap = _as_dict(caption_overlay_pack)
    comp = _as_dict(composition_decision)
    broll = _as_dict(broll_metadata)
    sfx = _as_dict(sfx_metadata)
    finish = _as_dict(cinematic_finish)
    rhythm = _as_dict(shot_rhythm)
    audio = _as_dict(audio_metadata)
    subs = _as_dict(subtitle_metadata)
    motion_pack = _as_dict(motion_pack)
    motion_overlay = _as_dict(motion_overlay_metadata)
    dynamic_overlay = _as_dict(dynamic_overlay_text_metadata) or motion_overlay
    final_mp4 = _as_dict(final_mp4_contract)
    if any(
        not isinstance(v, dict)
        for v in (
            editing_richness, first3_visual_contract, caption_overlay_pack,
            composition_decision, broll_metadata, sfx_metadata, cinematic_finish,
            shot_rhythm, audio_metadata, subtitle_metadata, motion_overlay_metadata,
            dynamic_overlay_text_metadata, final_mp4_contract,
        )
        if v is not None
    ):
        logger.info("PUBLISHABLE_GATE_META_NORMALIZED")

    checks: Dict[str, Any] = {}
    reasons: List[str] = []
    warnings: List[str] = []

    lower_text = str(segment_text or "").lower()
    incomplete_tail = any(lower_text.strip().endswith(token) for token in (" cuando", " porque", " pero", " y", " para", " si", " entonces"))
    bts_flag = bool("bts" in lower_text or "dale de nuevo" in lower_text or "lo repito" in lower_text)
    weak_hook = bool(int((subs.get("hook_first3_score") or 0)) < 5)
    visible_repetition = bool(
        "repetition" in "|".join(str(x) for x in (rhythm.get("removed_pauses") or []))
        or "visible_repetition" in "|".join(str(x) for x in (richness.get("editing_richness_warnings") or []))
    )
    editorial_integrity = bool(not bts_flag and not incomplete_tail and not visible_repetition and status_in != "DO_NOT_UPLOAD")
    checks["editorial_integrity"] = editorial_integrity
    if not editorial_integrity:
        reasons.append("editorial_integrity_failed")
    elif weak_hook:
        warnings.append("weak_hook_review")

    first3_checks = dict(first3.get("first3_visual_contract") or {})
    first3_quality = bool(
        first3_checks.get("hook_visible_before_1_5s", False)
        and first3_checks.get("caption_readable", False)
        and first3_checks.get("no_layer_overload", False)
        and (
            first3_checks.get("motion_contextual", False)
            or bool(rhythm.get("applied"))
        )
    )
    checks["first3_quality"] = first3_quality
    if not first3_quality:
        warnings.append("first3_quality_review")

    overlays = cap.get("caption_overlay_actions") or []
    caption_quality = bool(
        bool(subs.get("captions_rendered", True))
        and not bool(cap.get("layer_overload"))
        and not (
            bool((cap.get("lower_third") or {}).get("applied"))
            and bool((cap.get("hook_overlay") or {}).get("applied"))
            and float((cap.get("lower_third") or {}).get("start_s") or 0.0) < 1.2
        )
    )
    if len(overlays) > 3:
        caption_quality = False
    checks["caption_quality"] = caption_quality
    if not caption_quality:
        warnings.append("caption_quality_warning")

    voice_conflict = bool(sfx.get("voice_conflict"))
    sfx_over_voice = bool(sfx.get("sfx_applied") and voice_conflict)
    audio_quality = bool(
        not sfx_over_voice
        and not bool(audio.get("voice_buried"))
        and not bool(audio.get("music_too_loud"))
    )
    checks["audio_quality"] = audio_quality
    if not audio_quality:
        warnings.append("audio_quality_warning")

    composition_quality = bool(
        not bool(comp.get("layer_overload") or richness.get("layer_overload"))
        and str(comp.get("composition_quality") or richness.get("composition_quality") or "ok") in {"ok", "good", "strong"}
        and not bool((first3.get("first3_visual_contract") or {}).get("no_layer_overload") is False)
    )
    checks["composition_quality"] = composition_quality
    if not composition_quality:
        warnings.append("composition_quality_warning")

    fake_flags: List[str] = []
    if bool(richness.get("broll")) and not bool(broll.get("broll_asset_applied_match") or broll.get("asset_applied_match")):
        fake_flags.append("broll_true_without_asset")
    if bool(richness.get("sfx")) and not bool(sfx.get("sfx_asset_applied_match")):
        fake_flags.append("sfx_true_without_asset")
    if bool(richness.get("visual_finish")) and not bool(finish.get("visual_finish") and finish.get("finish_applied")):
        fake_flags.append("finish_true_without_filters")
    if bool(richness.get("shot_rhythm_pack")) and not bool(
        rhythm.get("applied")
        and (
            rhythm.get("microcuts")
            or rhythm.get("preserved_pauses")
            or rhythm.get("pattern_interruptions")
            or float(rhythm.get("pacing_score_after_estimate") or 0.0) > float(rhythm.get("pacing_score_before") or 0.0) + 0.01
        )
    ):
        fake_flags.append("rhythm_true_without_action")
    if bool(richness.get("cinematic_finish_pack")) and not bool(finish.get("visual_finish")):
        fake_flags.append("finish_pack_without_visual_finish")
    if bool(richness.get("caption_overlay_pack")) and not bool(overlays):
        fake_flags.append("caption_pack_without_actions")
    if bool(richness.get("composition_pack")) and not bool(
        richness.get("composition_runtime_applied")
        or comp.get("runtime_connected")
        or comp.get("composition_pack")
        or bool(first3.get("status") == "pass")
    ):
        fake_flags.append("composition_pack_without_runtime_proof")
    motion_events = list(motion_pack.get("visual_effects_events") or motion_pack.get("motion_scaling_events") or [])
    motion_contextual = bool(
        motion_pack.get("motion_pack_applied")
        or motion_pack.get("visual_effects_applied")
        and any(
            bool((event or {}).get("motion_pack_contextual") or (event or {}).get("contextual") or (event or {}).get("premium_visual_effect"))
            for event in motion_events
        )
    )
    if bool(richness.get("motion_pack")) and not motion_contextual:
        fake_flags.append("motion_pack_without_contextual_action")
    if bool(richness.get("motion_overlay_pack")) and not bool(motion_overlay.get("motion_overlay_applied")):
        fake_flags.append("motion_overlay_pack_without_apply")
    if bool(motion_overlay.get("motion_overlay_applied")) and not Path(str(motion_overlay.get("motion_overlay_asset_path") or "")).exists():
        fake_flags.append("motion_overlay_applied_missing_asset")
    if bool(motion_overlay.get("motion_overlay_applied")) and not Path(str(motion_overlay.get("motion_overlay_final_output_path") or "")).exists():
        fake_flags.append("motion_overlay_applied_missing_final_output")
    if bool(motion_overlay.get("motion_overlay_applied")) and not bool(motion_overlay.get("motion_overlay_apply_ffprobe_readable", True)):
        fake_flags.append("motion_overlay_applied_ffprobe_unreadable")
    if bool(motion_overlay.get("motion_overlay_applied")) and bool(motion_overlay.get("dynamic_overlay_text_needs_claim_review")) and not bool(
        dynamic_overlay.get("claim_verified") or motion_overlay.get("claim_verified")
    ):
        fake_flags.append("motion_overlay_applied_unresolved_claim_review")
    if bool(motion_overlay.get("motion_overlay_applied")) and bool(motion_overlay.get("motion_overlay_production_mode", True)) and not bool(
        motion_overlay.get("motion_overlay_manifest_verified")
    ):
        fake_flags.append("motion_overlay_applied_unverified_production_asset")
    if bool(motion_overlay.get("final_output_uses_motion_overlay")) and not bool(motion_overlay.get("motion_overlay_applied")):
        fake_flags.append("motion_overlay_final_without_apply")
    if bool(motion_overlay.get("final_output_uses_motion_overlay")) and not bool(motion_overlay.get("motion_overlay_manifest_verified")):
        fake_flags.append("motion_overlay_final_unverified")
    if bool(dynamic_overlay.get("dynamic_overlay_text_applied")) and not bool(motion_overlay.get("motion_overlay_applied")):
        fake_flags.append("dynamic_overlay_text_applied_without_motion_overlay")
    if bool(dynamic_overlay.get("dynamic_overlay_text_rendered")):
        _text_asset = str(dynamic_overlay.get("dynamic_overlay_text_asset_path") or "")
        if not _text_asset or not Path(_text_asset).exists():
            fake_flags.append("dynamic_overlay_text_rendered_missing_asset")
        if not bool(dynamic_overlay.get("dynamic_overlay_text_safe_to_render")):
            fake_flags.append("dynamic_overlay_text_rendered_unsafe")
    if bool(dynamic_overlay.get("dynamic_overlay_text_needs_claim_review")) and bool(dynamic_overlay.get("dynamic_overlay_text_safe_to_render")):
        if not bool(dynamic_overlay.get("claim_verified")):
            fake_flags.append("dynamic_overlay_claim_not_verified")
    if bool(dynamic_overlay.get("dynamic_overlay_text_rendered")) and bool(dynamic_overlay.get("dynamic_overlay_text_needs_claim_review")):
        if not bool(dynamic_overlay.get("claim_verified")):
            fake_flags.append("dynamic_overlay_claim_rendered_unverified")
    if bool(richness.get("broll")) and bool(richness.get("broll_editorial_opportunity")) and not bool(broll.get("broll_asset_applied_match") or broll.get("asset_applied_match")):
        fake_flags.append("broll_opportunity_counted_as_applied")
    if bool(richness.get("sfx")) and bool(richness.get("sfx_editorial_opportunity")) and not bool(sfx.get("sfx_asset_applied_match")):
        fake_flags.append("sfx_opportunity_counted_as_applied")
    premium_truth = len(fake_flags) == 0
    checks["premium_truth"] = premium_truth
    for fake in fake_flags:
        logger.info("[final-qc] fake_premium_flag=%s reason=flag_without_real_action", fake)
        warnings.append(f"fake_premium:{fake}")

    render_safety = bool(
        bool(richness)
        and status_in != ""
        and not (bool(richness.get("broll")) and not bool(broll))
        and not (bool(richness.get("sfx")) and not bool(sfx))
        and not (bool(richness.get("visual_finish")) and not bool(finish))
        and not (bool(richness.get("shot_rhythm_pack")) and not bool(rhythm))
        and not (bool(richness.get("motion_overlay_pack")) and not bool(motion_overlay))
    )
    checks["render_safety"] = render_safety
    if not render_safety:
        reasons.append("render_safety_failed")

    if final_mp4:
        checks["final_mp4_contract"] = bool(final_mp4.get("final_publishable", True))
        if not bool(final_mp4.get("final_publishable", True)):
            final_blocking = [str(x) for x in _safe_list(final_mp4.get("final_blocking_reasons")) if str(x)]
            if final_blocking:
                reasons.extend([f"final_mp4_contract_{reason}" for reason in final_blocking[:6]])
            else:
                reasons.append("final_mp4_contract_failed")
            warnings.extend([f"final_mp4_contract_warning_{w}" for w in _safe_list(final_mp4.get("final_warning_reasons")) if str(w)])

    readability_score = round(1.0 if caption_quality else 0.62, 3)
    audio_score = round(1.0 if audio_quality else 0.58, 3)
    composition_score = round(1.0 if composition_quality else 0.55, 3)
    retention_score = round(
        max(
            0.0,
            min(
                1.0,
                float(rhythm.get("pacing_score_after_estimate") or rhythm.get("pacing_score_after") or 0.68),
            ),
        ),
        3,
    )
    premium_truth_score = 1.0 - (0.14 * len(fake_flags))
    premium_truth_score = round(max(0.0, min(1.0, premium_truth_score)), 3)
    logger.info("[final-qc] premium_truth_score=%.2f", premium_truth_score)

    severe_fake_premium = len(fake_flags) >= 3
    severe = (
        status_in == "DO_NOT_UPLOAD"
        or not editorial_integrity
        or not render_safety
        or severe_fake_premium
        or premium_truth_score < 0.55
    )
    if severe:
        qc_status = "FAIL"
    elif fake_flags or premium_truth_score < 0.75 or not first3_quality or not caption_quality or not audio_quality or not composition_quality:
        qc_status = "REVIEW"
    else:
        qc_status = "PASS"

    if status_in == "DO_NOT_UPLOAD" or qc_status == "FAIL" or (final_mp4 and not bool(final_mp4.get("final_publishable", True))):
        if final_mp4 and not bool(final_mp4.get("final_publishable", True)):
            qc_status = "FAIL"
            severe = True
        upload_reco = "DO_NOT_UPLOAD"
        if final_mp4 and not bool(final_mp4.get("final_publishable", True)):
            reasons.append("final_mp4_contract_blocked_publishable")
            logger.info(
                "FINAL_QC_BLOCKED_PUBLISHABLE final_mp4_contract=%s reasons=%s",
                str(bool(final_mp4.get("final_publishable", True))).lower(),
                "|".join([str(x) for x in _safe_list(final_mp4.get("final_blocking_reasons")) if str(x)]) or "none",
            )
    elif status_in == "PRIVATE_PREMIUM_READY" and qc_status == "PASS" and not warnings:
        upload_reco = "UPLOAD"
    else:
        upload_reco = "REVIEW_MANUALLY"

    logger.info("[final-qc] status=%s", qc_status)
    logger.info("[final-qc] upload_recommendation=%s", upload_reco)
    logger.info("[final-qc] severe=%s reason=%s", str(severe).lower(), "|".join(reasons) or "none")
    for reason in reasons:
        logger.info("[final-qc] reason=%s", reason)
    for warning in warnings:
        logger.info("[final-qc] warning=%s", warning)

    return {
        "final_qc_status": qc_status,
        "upload_recommendation": upload_reco,
        "reasons": reasons,
        "warnings": warnings,
        "checks": checks,
        "premium_truth_score": premium_truth_score,
        "readability_score": readability_score,
        "audio_score": audio_score,
        "composition_score": composition_score,
        "retention_score": retention_score,
        "severe": severe,
        "final_mp4_contract": final_mp4,
    }


def _count_editing_activities(clip_info: Dict[str, Any]) -> int:
    """Count how many editorial activities were applied to this clip.

    Checks premium_layers_applied trace first (FIX 8), falls back to
    optimistic metadata if trace is not available.

    Activities counted:
      - reframe applied
      - broll applied (at least one editorial_broll item)
      - hook overlay rendered
      - silence edit applied (cuts > 0)
      - captions rendered
      - branding applied
    """
    clip_info = _as_dict(clip_info)
    count = 0
    editing_plan = _as_dict(clip_info.get("editing_plan"))

    # ── FIX 8: Check premium_layers_applied before trusting optimistic metadata ──
    premium_raw = clip_info.get("premium_layers_applied")
    premium_applied: List[str] = premium_raw if isinstance(premium_raw, list) else []
    if ("premium_layers_applied" in clip_info) and (premium_raw is not None):
        # Honest trace from create_single_clip
        if "broll" in premium_applied:
            count += 1
        if "vfx" in premium_applied:
            count += 1
        if "hook_card" in premium_applied:
            count += 1
        if "rhythm" in premium_applied:
            count += 1
        if "captions" in premium_applied:
            count += 1
        if "branding" in premium_applied:
            count += 1
        # Reframe is not a premium layer category, check editing_plan directly
        if editing_plan.get("reframe_strategy") and editing_plan.get("reframe_strategy") != "none":
            count += 1
        return count

    # Fallback: optimistic metadata
    # Reframe
    if editing_plan.get("reframe_strategy") and editing_plan.get("reframe_strategy") != "none":
        count += 1

    # B-roll
    broll_items = _safe_list(clip_info.get("editorial_broll"))
    if broll_items:
        count += 1

    visual_effects = _as_dict(clip_info.get("visual_effects")) or _as_dict(editing_plan.get("visual_effects"))
    if visual_effects.get("visual_effects_applied"):
        count += 1

    # Hook overlay
    hook_plan = _as_dict(clip_info.get("hook_plan"))
    if hook_plan.get("rendered") or hook_plan.get("overlay_rendered"):
        count += 1

    # Silence edit
    silence_plan = _as_dict(clip_info.get("silence_edit_plan"))
    silence_summary = silence_plan.get("summary") or {}
    if silence_plan.get("enabled") and (silence_summary.get("total_cuts_applied", 0) > 0 or silence_plan.get("total_removed_s", 0) > 0):
        count += 1

    # Captions
    if clip_info.get("caption_source") or clip_info.get("words"):
        count += 1

    # Branding
    brand_treatment = _as_dict(clip_info.get("brand_treatment"))
    if brand_treatment.get("applied"):
        count += 1

    return count


def _detect_weak_intro(hook_plan: Optional[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    """Detect if the clip has a weak intro based on hook_plan signals."""
    hook_plan = _as_dict(hook_plan)
    if not hook_plan:
        return False, ["no_hook_plan_available"]

    reasons: List[str] = []
    is_weak = False

    hook_type = hook_plan.get("hook_type", "")
    low_priority = hook_plan.get("low_publish_priority", False)
    hook_first_4s = hook_plan.get("hook_first_4s_score", 0)

    if hook_type == "weak_intro":
        reasons.append(f"hook_type_is_weak_intro")
        is_weak = True

    if low_priority:
        reasons.append("low_publish_priority_flag")
        is_weak = True

    if hook_first_4s < HOOK_FIRST_4S_MIN_SCORE and hook_type != "weak_intro":
        reasons.append(f"hook_first_4s_score_{hook_first_4s}_below_min_{HOOK_FIRST_4S_MIN_SCORE}")
        is_weak = True

    if not hook_plan.get("hook_contract_satisfied", False):
        reasons.append("hook_contract_not_satisfied")
        is_weak = True

    return is_weak, reasons


def _detect_generic_broll(
    broll_items: List[Dict[str, Any]],
    editorial_type: str,
) -> Tuple[bool, List[str]]:
    """Detect if B-roll is generic/uninspired.

    Rules:
      - documents_admin category + emotional editorial_type → generic warning
      - No B-roll but speaker focus → no severe penalty (talking-head is fine)
    """
    if not broll_items:
        return False, ["no_broll_available_no_penalty_for_talking_head"]

    reasons: List[str] = []
    is_generic = False

    for item in broll_items:
        if not isinstance(item, dict):
            continue
        category = (item.get("cue_type") or item.get("category") or "").lower()
        asset_path = str(item.get("asset_path") or item.get("asset_url") or "")

        # documents_admin + emotional editorial → generic
        if category == "documents_admin" and editorial_type in (
            "emotional_protection", "client_objection", "risk_warning"
        ):
            reasons.append(
                f"documents_admin_broll_for_{editorial_type}_editorial: {asset_path}"
            )
            is_generic = True

        # Known generic assets (from VPI_ASSET_PENALTIES)
        if "documents_admin/03.jpg" in asset_path:
            reasons.append(f"known_generic_asset_documents_admin_03: {asset_path}")
            is_generic = True

    return is_generic, reasons


def _detect_forbidden_broll(
    broll_items: List[Dict[str, Any]],
    segment_text: str,
) -> Tuple[bool, List[str]]:
    """Detect forbidden B-roll using vpi_broll_intent.is_broll_asset_forbidden().

    Also checks the 'forbidden' flag directly on each broll item as a fallback.
    """
    if not broll_items:
        return False, []

    reasons: List[str] = []
    is_forbidden = False

    # First pass: check direct 'forbidden' flag on items
    for item in broll_items:
        if not isinstance(item, dict):
            continue
        if item.get("forbidden"):
            reason = item.get("forbidden_reason") or "flagged_as_forbidden"
            reasons.append(f"forbidden_flag_{reason}")
            is_forbidden = True

    # Second pass: use vpi_broll_intent if available
    try:
        from .vpi_broll_intent import is_broll_asset_forbidden
    except ImportError:
        if not is_forbidden:
            logger.warning("vpi_broll_intent not available, skipping forbidden broll check")
            reasons.append("vpi_broll_intent_not_available")
        return is_forbidden, reasons

    for item in broll_items:
        if not isinstance(item, dict):
            continue
        context = {
            "category": item.get("cue_type") or item.get("category"),
            "cue_type": item.get("cue_type"),
            "query": item.get("query"),
            "title": item.get("title"),
            "asset_id": item.get("asset_id"),
            "provider_video_id": item.get("provider_video_id"),
            "visual_fingerprint": item.get("visual_fingerprint"),
            "tags": item.get("tags", []),
            "metadata": item.get("metadata"),
            "intent_type": item.get("intent_type"),
        }
        forbidden, forbidden_reasons = is_broll_asset_forbidden(item, context)
        if forbidden:
            reasons.extend(forbidden_reasons)
            is_forbidden = True

    return is_forbidden, reasons


def _assess_technical_qc(output_qc: Optional[Dict[str, Any]]) -> Tuple[bool, float, List[str]]:
    """Assess technical quality from output_qc.

    Returns (passed, score_contribution, reasons).
    """
    if not isinstance(output_qc, dict):
        return True, 0.0, ["no_output_qc_available"]

    reasons: List[str] = []
    overall_score = output_qc.get("overall_score", 100.0)
    quality_level = output_qc.get("quality_level", "good")
    checks = output_qc.get("checks", [])
    passed = output_qc.get("passed", True)

    if not passed:
        reasons.append(f"output_qc_failed_overall_score_{overall_score}")
        return False, -20.0, reasons

    if quality_level in ("poor", "reject"):
        reasons.append(f"output_qc_quality_level_{quality_level}")
        return False, -30.0, reasons

    # Check individual checks
    for check in checks:
        if not check.get("passed", True):
            check_name = check.get("name", "unknown")
            reasons.append(f"qc_check_failed_{check_name}")

    return True, min(overall_score / 100.0 * 10.0, 10.0), reasons


def _assess_audio_qc(audio_qc: Optional[Dict[str, Any]]) -> Tuple[bool, float, List[str]]:
    """Assess audio quality.

    Returns (passed, score_contribution, reasons).
    """
    if not isinstance(audio_qc, dict):
        return True, 0.0, ["no_audio_qc_available"]

    reasons: List[str] = []
    voice_status = audio_qc.get("audio_voice_status") or audio_qc.get("voice_loudness_classification", "unknown")
    input_lufs = audio_qc.get("input_lufs")
    output_lufs = audio_qc.get("output_lufs")

    if voice_status == "too_low":
        reasons.append(f"audio_voice_too_low_lufs_{input_lufs}")
        return False, -15.0, reasons

    if voice_status == "clipping_risk":
        reasons.append(f"audio_clipping_risk_peak_{audio_qc.get('input_peak')}")
        return False, -10.0, reasons

    if voice_status == "slightly_low":
        reasons.append(f"audio_voice_slightly_low_lufs_{input_lufs}")
        return True, -5.0, reasons

    return True, 5.0, reasons


def _assess_silence_quality(silence_plan: Optional[Dict[str, Any]]) -> Tuple[bool, float, List[str]]:
    """Assess silence editing quality.

    Returns (passed, score_contribution, reasons).
    """
    if not isinstance(silence_plan, dict):
        return True, 0.0, ["no_silence_plan_available"]

    reasons: List[str] = []
    warnings = silence_plan.get("warnings", [])
    total_removed = silence_plan.get("total_removed_s", 0.0)

    if warnings:
        for w in warnings[:3]:
            reasons.append(f"silence_warning_{w}")

    # If silence editing removed too much (>40% of typical 30s clip), flag it
    if total_removed > 12.0:
        reasons.append(f"silence_excessive_removal_{total_removed}s")
        return False, -10.0, reasons

    return True, 5.0, reasons


def _assess_captions_branding(clip_info: Dict[str, Any]) -> Tuple[bool, bool, List[str]]:
    """Assess captions and branding status.

    Checks premium_layers_applied trace first (FIX 8), falls back to
    optimistic metadata if trace is not available.

    Returns (captions_ok, branding_ok, reasons).
    """
    clip_info = _as_dict(clip_info)
    reasons: List[str] = []
    captions_ok = True
    branding_ok = True

    # ── FIX 8: Check premium_layers_applied before trusting optimistic metadata ──
    premium_raw = clip_info.get("premium_layers_applied")
    premium_applied: List[str] = premium_raw if isinstance(premium_raw, list) else []
    if ("premium_layers_applied" in clip_info) and (premium_raw is not None):
        # Honest trace from create_single_clip
        captions_ok = "captions" in premium_applied
        branding_ok = "branding" in premium_applied
        if not captions_ok:
            reasons.append("no_captions_in_premium_trace")
        if not branding_ok:
            reasons.append("no_branding_in_premium_trace")
        return captions_ok, branding_ok, reasons

    # Fallback: optimistic metadata
    # Captions check
    has_words = bool(clip_info.get("words"))
    has_caption_source = bool(clip_info.get("caption_source"))
    if not has_words and not has_caption_source:
        captions_ok = False
        reasons.append("no_captions_rendered")

    # Branding check
    brand_treatment = _as_dict(clip_info.get("brand_treatment"))
    if brand_treatment.get("error"):
        branding_ok = False
        reasons.append(f"branding_error_{brand_treatment.get('error')}")

    return captions_ok, branding_ok, reasons


def _compute_base_score(
    vpi_score: Optional[float],
    virality_score: Optional[float],
    editorial_type: str,
) -> float:
    """Compute base publishable score from VPI and virality scores."""
    vpi = float(vpi_score or 0.0)
    virality = float(virality_score or 0.0)

    # Base: weighted combination of VPI score and virality
    base = (vpi * 0.6) + (virality * 0.4)

    # Editorial type bonus
    editorial_bonus = {
        "risk_warning": 8.0,
        "myth_debunk": 6.0,
        "client_objection": 5.0,
        "actionable_advice": 4.0,
        "emotional_protection": 3.0,
        "coverage_explanation": 2.0,
        "revelation": 2.0,
        "generic": -5.0,
    }
    base += editorial_bonus.get(editorial_type, 0.0)

    return max(0.0, min(100.0, base))


def evaluate_clip_publishability(
    clip_info: Dict[str, Any],
    segment: Optional[Dict[str, Any]] = None,
    first3_visual_contract: Optional[Dict[str, Any]] = None,
) -> PublishableGateResult:
    """Evaluate a single clip's publishability.

    Args:
        clip_info: Dict with clip metadata (editing_plan, hook_plan,
                   editorial_broll, output_qc, silence_edit_plan,
                   brand_treatment, words, caption_source, etc.)
        segment: Optional segment dict with editorial metadata
                 (editorial_type, vpi_score, virality_score, etc.)
        first3_visual_contract: Optional result from first3_visual_contract()
                                used to downgrade private premium status.

    Returns:
        PublishableGateResult with full classification.
    """
    clip_info = _as_dict(clip_info)
    segment = _as_dict(segment or clip_info)
    first3_visual_contract = _as_dict(first3_visual_contract)

    # ── 1. Gather input data ────────────────────────────────────────────────
    editorial_type = str(segment.get("editorial_type") or clip_info.get("editorial_type") or "generic")
    vpi_score = segment.get("vpi_score") or clip_info.get("vpi_score")
    virality_score = segment.get("virality_score") or clip_info.get("virality_score")
    hook_plan = _as_dict(clip_info.get("hook_plan"))
    broll_items = [item for item in _safe_list(clip_info.get("editorial_broll")) if isinstance(item, dict)]
    output_qc = _as_dict(clip_info.get("output_qc"))
    audio_qc = _as_dict(clip_info.get("audio_qc"))
    silence_plan = _as_dict(clip_info.get("silence_edit_plan"))
    segment_text = str(segment.get("text") or clip_info.get("text") or "")
    if not segment_text and isinstance(clip_info.get("words"), list):
        segment_text = " ".join(
            str((word or {}).get("word") or "")
            for word in clip_info.get("words") or []
            if isinstance(word, dict)
        ).strip()
    editing_plan = _as_dict(clip_info.get("editing_plan"))
    editing_richness_score = int(
        clip_info.get("editing_richness_score")
        or editing_plan.get("editing_richness_score")
        or 0
    )
    editing_richness_status = str(
        clip_info.get("editing_richness_status")
        or editing_plan.get("editing_richness_status")
        or ""
    )
    editing_richness_warnings = [
        str(item)
        for item in (
            _safe_list(clip_info.get("editing_richness_warnings"))
            or _safe_list(editing_plan.get("editing_richness_warnings"))
        )
    ]
    music_meta = _as_dict(clip_info.get("music")) or _as_dict(editing_plan.get("music"))
    sfx_meta = _as_dict(clip_info.get("sfx")) or _as_dict(editing_plan.get("sfx"))
    visual_effects_meta = _as_dict(clip_info.get("visual_effects")) or _as_dict(editing_plan.get("visual_effects"))
    transitions_meta = _as_dict(clip_info.get("transitions")) or _as_dict(editing_plan.get("transitions"))
    speaker_focus_meta = _as_dict(clip_info.get("speaker_focus")) or _as_dict(editing_plan.get("speaker_focus"))
    no_broll_reason = (
        clip_info.get("broll_no_broll_reason")
        or editing_plan.get("broll_no_broll_reason")
    )

    # ── FIX 8: Check premium_layers_applied before trusting optimistic metadata ──
    premium_raw = clip_info.get("premium_layers_applied")
    has_premium_trace = ("premium_layers_applied" in clip_info) and (premium_raw is not None)
    premium_applied: List[str] = premium_raw if isinstance(premium_raw, list) else []
    if has_premium_trace:
        # Override with honest trace from create_single_clip
        broll_actually_applied = "broll" in premium_applied
        music_actually_applied = "bgm" in premium_applied
        sfx_actually_applied = "sfx" in premium_applied
        vfx_actually_applied = "vfx" in premium_applied
        hook_card_actually_applied = "hook_card" in premium_applied
        semantic_card_actually_applied = "semantic_card" in premium_applied
        motion_pack_actually_applied = "motion_pack" in premium_applied
        speaker_focus_actually_applied = "speaker_focus" in premium_applied
        rhythm_actually_applied = "rhythm" in premium_applied
        transition_actually_applied = "transition" in premium_applied
        branding_actually_applied = "branding" in premium_applied
        captions_actually_applied = "captions" in premium_applied
        audio_mastering_actually_applied = "audio_mastering" in premium_applied
    else:
        # Fall back to optimistic metadata
        broll_actually_applied = bool(broll_items)
        music_actually_applied = bool(music_meta.get("music_applied"))
        sfx_actually_applied = bool(sfx_meta.get("sfx_applied"))
        vfx_actually_applied = bool(visual_effects_meta.get("visual_effects_final_verified") or visual_effects_meta.get("visual_effects_applied"))
        hook_card_actually_applied = bool(hook_plan.get("overlay_rendered") or hook_plan.get("kickframe_applied"))
        motion_overlay = _as_dict(clip_info.get("motion_overlay"))
        semantic_card_actually_applied = bool(motion_overlay.get("dynamic_overlay_card_composed"))
        motion_pack_actually_applied = bool(motion_overlay.get("motion_overlay_applied"))
        speaker_focus_actually_applied = bool(_as_dict(clip_info.get("speaker_focus")).get("speaker_focus_enhanced"))
        rhythm_actually_applied = bool(_as_dict(clip_info.get("silence_edit_plan")).get("rendered"))
        transition_actually_applied = bool(transitions_meta.get("transitions_applied") or transitions_meta.get("final_output_uses_transition"))
        branding_actually_applied = bool(_as_dict(clip_info.get("brand_treatment")).get("rendered"))
        captions_actually_applied = bool(clip_info.get("words") or clip_info.get("caption_source"))
        audio_mastering_actually_applied = bool(_as_dict(clip_info.get("music")).get("audio_mastering_applied"))

    hook_first3_ok = bool(
        hook_plan.get("hook_type") != "weak_intro"
        and str(hook_plan.get("hook_first3_status") or "") == "strong"
        and int(hook_plan.get("hook_first3_score") or 0) >= 5
        and bool(hook_plan.get("hook_first3_final_verified", hook_plan.get("hook_first3_perceptible")))
    )
    visual_final_verified = vfx_actually_applied
    music_required_missing = int((music_meta or {}).get("music_tracks_found") or 0) > 0 and not music_actually_applied
    static_broll_without_kenburns = any(
        bool((item or {}).get("is_image") or (item or {}).get("broll_is_image"))
        and not bool((item or {}).get("ken_burns_applied") or (item or {}).get("broll_ken_burns_applied"))
        for item in broll_items
    )
    broll_cut_is_dry = any(
        not bool((item or {}).get("broll_transition_applied"))
        and not bool((item or {}).get("transition_type"))
        for item in broll_items
    )
    missing_layers: List[str] = []
    if not broll_actually_applied:
        missing_layers.append("broll")
    if not vfx_actually_applied:
        missing_layers.append("visual_effects")
    if not music_actually_applied:
        missing_layers.append("music")
    if not sfx_actually_applied:
        missing_layers.append("sfx")
    no_post_layers = all(layer in missing_layers for layer in ("broll", "visual_effects", "music", "sfx"))
    retention_gate = assess_retention_quality(clip_info)
    content_quality: Dict[str, Any] = {}
    try:
        from .vpi_retention_editing_service import evaluate_content_quality

        quality_source = dict(segment or {})
        if segment_text and not quality_source.get("text"):
            quality_source["text"] = segment_text
        content_quality = evaluate_content_quality(quality_source)
        clip_info.update(content_quality)
        segment.update(content_quality)
    except Exception as exc:
        logger.warning("[content-quality] gate_check_skipped reason=%s", exc)
        content_quality = {
            "content_quality_label": str(clip_info.get("content_quality_label") or ""),
            "content_quality_reason": str(clip_info.get("content_quality_reason") or ""),
        }
    content_quality_reject = (
        content_quality.get("content_quality_label") == "reject"
        or content_quality.get("content_quality_reason") == "behind_the_scenes_low_speech"
    )

    # ── 1.5. Assess editorial fluency (FASE 5) ──────────────────────────────
    editorial_fluency_ok = True
    editorial_fluency_score = 0.0
    complete_idea_score = 0.0
    fluency_score_after = 0.0
    hook_fit_acceptable = False
    editorial_fluency_warnings: List[str] = []
    try:
        from .vpi_editorial_fluency_service import assess_editorial_fluency

        fluency_result = assess_editorial_fluency(
            text=segment_text,
            editorial_type=editorial_type,
            hook_plan=hook_plan,
            silence_plan=silence_plan,
            duration_s=float(clip_info.get("duration_s") or 0.0),
        )
        editorial_fluency_score = float(fluency_result.get("editorial_fluency_score", 0.0))
        complete_idea_score = float(fluency_result.get("complete_idea_score", 0.0))
        fluency_score_after = float(fluency_result.get("fluency_score_after", 0.0))
        hook_fit_acceptable = bool(fluency_result.get("hook_fit", {}).get("hook_fit_acceptable", False))
        editorial_fluency_warnings = list(fluency_result.get("editorial_fluency_warnings", []))

        # Block conditions for READY_TO_UPLOAD
        if complete_idea_score < 0.75:
            editorial_fluency_ok = False
            editorial_fluency_warnings.append("incomplete_idea")
        if fluency_score_after < 0.70:
            editorial_fluency_ok = False
            if "low_fluency" not in editorial_fluency_warnings:
                editorial_fluency_warnings.append("low_fluency")
        hook_first3_score = int(hook_plan.get("hook_first3_score") or 0)
        if hook_first3_score < 5 and not hook_fit_acceptable:
            editorial_fluency_ok = False
            if "hook_fit_unacceptable" not in editorial_fluency_warnings:
                editorial_fluency_warnings.append("hook_fit_unacceptable")
        # Check for at least one perceptible editorial action
        fluency_plan = fluency_result.get("fluency_plan", {})
        edit_list = fluency_result.get("edit_decision_list", {})
        has_editorial_action = bool(
            fluency_plan.get("edits")
            or edit_list.get("decisions")
            or fluency_result.get("complete_idea_assessment") == "expanded"
        )
        if not has_editorial_action:
            editorial_fluency_ok = False
            if "no_editorial_action" not in editorial_fluency_warnings:
                editorial_fluency_warnings.append("no_editorial_action")
    except Exception as exc:
        logger.warning("[editorial-fluency] gate_check_skipped reason=%s", exc)
        editorial_fluency_ok = True  # don't block if service unavailable

    # ── 1.6. Weak hook gate (FASE 4) ─────────────────────────────────────────
    # If hook-first3 stays weak (< 5) and unresolved, force REVIEW_MANUALLY,
    # never READY, never rich.  Try before giving up: adjust start, subtitle
    # emphasis before 1.5s, micro pause/cut entry, visual contextual.
    hook_fit_unresolved = False
    hook_first3_score = int(hook_plan.get("hook_first3_score") or 0)
    if hook_first3_score < 5 and hook_plan.get("hook_type") != "weak_intro":
        try:
            from .vpi_hook_engine import is_weak_hook_unresolved, assess_hook_fit

            hook_fit_result = assess_hook_fit(
                text=segment_text,
                editorial_type=editorial_type,
                hook_type=str(hook_plan.get("hook_type") or ""),
                hook_plan=hook_plan,
            )
            if is_weak_hook_unresolved(hook_plan, hook_fit_result=hook_fit_result):
                hook_fit_unresolved = True
                logger.info(
                    "[hook-fit] status=weak_unresolved "
                    "score=%d intent=%s style=%s",
                    hook_first3_score,
                    hook_fit_result.get("intent", "unknown"),
                    hook_fit_result.get("style", "unknown"),
                )
                logger.info(
                    "[quality-gate] rich_blocked reason=weak_contextual_hook"
                )
                # Force editorial_fluency_ok to False to block READY
                editorial_fluency_ok = False
                if "hook_fit_unresolved" not in editorial_fluency_warnings:
                    editorial_fluency_warnings.append("hook_fit_unresolved")
        except Exception as exc:
            logger.warning("[hook-fit] gate_check_skipped reason=%s", exc)

    # ── 2. Compute editing activity score ───────────────────────────────────
    editing_activity = _count_editing_activities(clip_info)
    editing_activity_ok = editing_activity >= EDITING_ACTIVITY_READY_THRESHOLD

    # ── 3. Detect weak intro ────────────────────────────────────────────────
    is_weak_intro, weak_intro_reasons = _detect_weak_intro(hook_plan)

    # ── 4. Detect generic B-roll ────────────────────────────────────────────
    is_generic_broll, generic_broll_reasons = _detect_generic_broll(
        broll_items, editorial_type
    )

    # ── 5. Detect forbidden B-roll ──────────────────────────────────────────
    is_forbidden_broll, forbidden_broll_reasons = _detect_forbidden_broll(
        broll_items, segment_text
    )

    # ── 6. Assess technical QC ──────────────────────────────────────────────
    tech_qc_ok, tech_qc_score, tech_qc_reasons = _assess_technical_qc(output_qc)

    # ── 7. Assess audio QC ──────────────────────────────────────────────────
    audio_qc_ok, audio_qc_score, audio_qc_reasons = _assess_audio_qc(audio_qc)

    # ── 8. Assess silence quality ───────────────────────────────────────────
    silence_ok, silence_score, silence_reasons = _assess_silence_quality(silence_plan)

    # ── 9. Assess captions and branding ─────────────────────────────────────
    captions_ok, branding_ok, cb_reasons = _assess_captions_branding(clip_info)

    # ── 10. Compute base score ──────────────────────────────────────────────
    base_score = _compute_base_score(vpi_score, virality_score, editorial_type)

    # ── 11. Apply penalties ─────────────────────────────────────────────────
    total_penalty = 0.0
    status_reasons: List[str] = []
    warnings: List[str] = []

    # Forbidden B-roll → DO_NOT_UPLOAD (immediate)
    if is_forbidden_broll:
        for reason in forbidden_broll_reasons:
            status_reasons.append(f"forbidden_broll_{reason}")
        return PublishableGateResult(
            publishable_status=PublishableStatus.DO_NOT_UPLOAD,
            publishable_score=0.0,
            publishable_reasons=status_reasons,
            publishable_warnings=forbidden_broll_reasons,
            upload_recommendation=UploadRecommendation.DISCARD_RECOMMENDED,
            discard_recommended=True,
            forbidden_broll_detected=True,
            editing_activity_ok=editing_activity_ok,
            hook_first_4s_ok=(not is_weak_intro),
            technical_qc_ok=tech_qc_ok,
            audio_qc_ok=audio_qc_ok,
            silence_ok=silence_ok,
            captions_ok=captions_ok,
            branding_ok=branding_ok,
        )

    # Weak intro penalty
    if is_weak_intro:
        total_penalty += WEAK_INTRO_PENALTY
        for reason in weak_intro_reasons:
            status_reasons.append(f"weak_intro_{reason}")

    # Generic B-roll penalty
    if is_generic_broll:
        total_penalty += BROLL_GENERIC_DOCUMENTS_PENALTY
        for reason in generic_broll_reasons:
            warnings.append(f"generic_broll_{reason}")
    if content_quality_reject:
        total_penalty += 60.0
        reason = str(content_quality.get("content_quality_reason") or "content_quality_reject")
        status_reasons.append(f"content_quality_{reason}")
        warnings.append("behind_the_scenes_or_low_speech")

    # Editing activity penalty
    if editing_activity < EDITING_ACTIVITY_NEEDS_FIX_THRESHOLD:
        total_penalty += 20.0
        status_reasons.append(f"low_editing_activity_{editing_activity}")
    elif editing_activity < EDITING_ACTIVITY_READY_THRESHOLD:
        total_penalty += 10.0
        warnings.append(f"moderate_editing_activity_{editing_activity}")

    if editing_richness_status == "too_plain" or "visually_too_plain" in editing_richness_warnings:
        total_penalty += 15.0
        warnings.append("visually_too_plain")
        status_reasons.append(f"editing_richness_too_plain_{editing_richness_score}")
    elif editing_richness_status == "acceptable":
        warnings.append(f"editing_richness_acceptable_{editing_richness_score}")
    if music_meta.get("music_warning") == "missing_music_library":
        warnings.append("missing_music_library")
    if sfx_meta.get("sfx_warning") in {"missing_sfx_library", "missing_sfx_worker_assets"}:
        warnings.append(str(sfx_meta.get("sfx_warning")))
    if no_broll_reason:
        warnings.append(f"no_broll_reason_{no_broll_reason}")
    if speaker_focus_meta.get("speaker_focus_enhanced") and not broll_items:
        status_reasons.append("speaker_focus_preferred")
    if not hook_first3_ok and hook_plan.get("hook_type") != "weak_intro":
        total_penalty += 10.0
        warnings.append("weak_first_3_seconds")
        status_reasons.append("hook_first3_not_perceptible")
    if hook_plan.get("hook_type") != "weak_intro" and not visual_final_verified:
        total_penalty += 15.0
        warnings.append("visual_effects_planned_not_in_final")
        status_reasons.append("visual_effects_final_not_verified")
    if static_broll_without_kenburns:
        total_penalty += 20.0
        warnings.append("static_broll_without_kenburns")
        status_reasons.append("static_broll_without_kenburns")
    if broll_cut_is_dry:
        total_penalty += 15.0
        warnings.append("broll_cut_is_dry")
        status_reasons.append("broll_cut_is_dry")
    if no_post_layers:
        total_penalty += 10.0
        warnings.append("missing_editing_layers")
        status_reasons.append("no_post_production_layers_applied")
    if (transitions_meta.get("transition_events") or transitions_meta.get("transition_plan")) and not transitions_meta.get("final_output_uses_transition"):
        total_penalty += 15.0
        warnings.append("transition_planned_not_in_final")
        status_reasons.append("transition_planned_not_in_final")
    for transition_warning in transitions_meta.get("transition_warnings", []) or []:
        if transition_warning == "transition_failed_fallback_used" or "fallback" in str(transition_warning):
            warnings.append("transition_failed_fallback_used")
            total_penalty += 5.0
        elif transition_warning == "no_premium_transition_needed":
            warnings.append("no_premium_transition_needed")
        elif transition_warning:
            warnings.append(str(transition_warning))
    if retention_gate["retention_quality_status"] == "poor":
        total_penalty += 25.0
        status_reasons.append("retention_quality_poor")
    elif retention_gate["retention_quality_status"] == "acceptable":
        warnings.append("retention_quality_acceptable")
    if music_required_missing:
        total_penalty += 20.0
        status_reasons.append("music_tracks_found_but_not_final_verified")
        warnings.append("music_planned_not_in_final")
    if hook_plan.get("hook_type") == "weak_intro":
        status_reasons.append("weak_intro_never_ready")
    final_name = str(clip_info.get("filename") or clip_info.get("path") or "")
    marker_mismatches: List[str] = []
    if music_meta.get("music_applied") and "music_" not in final_name:
        marker_mismatches.append("music_marker_missing_or_false_positive")
    if sfx_meta.get("sfx_applied") and "sfx_" not in final_name:
        marker_mismatches.append("sfx_marker_missing_or_false_positive")
    if transitions_meta.get("transitions_applied") and "trans_" not in final_name:
        marker_mismatches.append("trans_marker_missing_or_false_positive")
    if visual_effects_meta.get("visual_effects_applied") and "vfx_" not in final_name:
        marker_mismatches.append("vfx_marker_missing_or_false_positive")
    if broll_items and "broll_" not in final_name:
        marker_mismatches.append("broll_marker_missing_or_false_positive")
    if not broll_items and "broll_" in final_name:
        marker_mismatches.append("broll_marker_false_positive")
    if marker_mismatches:
        total_penalty += 10.0
        warnings.extend(marker_mismatches)
        status_reasons.append("final_filename_contract_failed")

    # Technical QC penalties
    if not tech_qc_ok:
        total_penalty += abs(tech_qc_score)
        status_reasons.extend(tech_qc_reasons)

    # Audio QC penalties
    if not audio_qc_ok:
        total_penalty += abs(audio_qc_score)
        status_reasons.extend(audio_qc_reasons)
    elif audio_qc_score < 0:
        warnings.extend(audio_qc_reasons)

    # Silence penalties
    if not silence_ok:
        total_penalty += abs(silence_score)
        status_reasons.extend(silence_reasons)

    # Captions/branding warnings
    if not captions_ok:
        total_penalty += 10.0
        status_reasons.extend(cb_reasons)
    if not branding_ok:
        warnings.extend(cb_reasons)

    _commercial_strength = float(segment.get("commercial_usefulness_score") or 0.0)
    if _commercial_strength <= 1.0:
        _commercial_strength *= 100.0
    weak_editorial_segment = bool(
        float(segment.get("hookability_score") or 0.0) < 45.0
        or float(segment.get("standalone_score") or 0.0) < 45.0
        or _commercial_strength < 40.0
        or float(segment.get("vpi_score") or 0.0) < 35.0
        or bool(segment.get("weak_editorial_segment"))
    )
    if weak_editorial_segment:
        warnings.append("weak_editorial_segment")
        status_reasons.append("weak_editorial_segment")
    package_diversity_score = float(segment.get("package_diversity_score") or 0.0)
    package_category_distribution = dict(segment.get("package_category_distribution") or {})
    package_theme_distribution = dict(segment.get("package_theme_distribution") or {})
    package_diversity_warnings = list(segment.get("package_diversity_warnings") or [])
    clip_brief = dict(segment.get("clip_brief") or {})
    clip_angle = str(segment.get("clip_angle") or clip_brief.get("clip_angle") or "")
    clip_value_proposition = str(segment.get("clip_value_proposition") or clip_brief.get("clip_value_proposition") or "")
    clip_campaign_fit = dict(segment.get("clip_campaign_fit") or clip_brief.get("clip_campaign_fit") or {})
    clip_recommended_cta = str(segment.get("clip_recommended_cta") or clip_brief.get("clip_recommended_cta") or "")
    clip_confidence_label = str(segment.get("clip_confidence_label") or clip_brief.get("clip_confidence_label") or "")
    clip_review_flags = list(segment.get("clip_review_flags") or clip_brief.get("clip_review_flags") or [])
    clip_publish_notes = str(segment.get("clip_publish_notes") or clip_brief.get("clip_publish_notes") or "")
    clip_brief_summary = dict(segment.get("clip_brief_summary") or clip_brief.get("clip_brief_summary") or {})
    high_confidence_clip_count = int(segment.get("high_confidence_clip_count") or clip_brief_summary.get("high_confidence_clip_count") or 0)
    review_clip_count = int(segment.get("review_clip_count") or clip_brief_summary.get("review_clip_count") or 0)
    campaign_fit_summary = dict(segment.get("campaign_fit_summary") or clip_brief_summary.get("campaign_fit_summary") or {})
    campaign_intent = str(segment.get("campaign_intent") or "general_vpi")
    campaign_intent_confidence = float(segment.get("campaign_intent_confidence") or 0.0)
    campaign_intent_source = str(segment.get("campaign_intent_source") or "default_general")
    campaign_intent_reason = str(segment.get("campaign_intent_reason") or "")
    campaign_alignment_score = float(segment.get("campaign_alignment_score") or 0.0)
    campaign_alignment_reason = str(segment.get("campaign_alignment_reason") or "")
    campaign_boost_applied = bool(segment.get("campaign_boost_applied"))
    campaign_boost_score = float(segment.get("campaign_boost_score") or 0.0)
    selected_campaign_mix = dict(segment.get("selected_campaign_mix") or {})
    campaign_alignment_summary = dict(segment.get("campaign_alignment_summary") or {})
    preferred_categories = list(segment.get("preferred_categories") or [])
    suppressed_categories = list(segment.get("suppressed_categories") or [])
    preferred_keywords = list(segment.get("preferred_keywords") or [])
    sensitive_handling_required = bool(segment.get("sensitive_handling_required"))
    if package_diversity_score and package_diversity_score < 0.35:
        warnings.append("package_diversity_low")
    if package_category_distribution and len(package_category_distribution) == 1:
        warnings.append("package_single_category")
    if sum(1 for value in package_theme_distribution.values() if int(value) > 1) > 2:
        warnings.append("package_theme_repeat")
    if package_diversity_warnings:
        warnings.extend([str(x) for x in package_diversity_warnings if str(x)])
    if campaign_intent != "general_vpi":
        if campaign_alignment_score < 0.35:
            warnings.append("campaign_intent_low_alignment")
        if campaign_intent == "decesos" and not sensitive_handling_required:
            warnings.append("decesos_without_sensitive_handling")
    if clip_confidence_label == "low":
        warnings.append("clip_brief_low_confidence")
    if "sensitive_requires_review" in clip_review_flags:
        warnings.append("sensitive_requires_review")
    if "weak_editorial_segment" in clip_review_flags:
        warnings.append("weak_editorial_segment")
    boundary_confidence = float(segment.get("boundary_confidence") or 0.0)
    if boundary_confidence and boundary_confidence < 0.55:
        warnings.append("low_boundary_confidence")
    if not bool(segment.get("starts_cleanly", True)):
        warnings.append("weak_clip_start")
    if not bool(segment.get("payoff_preserved", True)):
        warnings.append("payoff_may_be_cut")

    # ── 12. Compute final score ─────────────────────────────────────────────
    final_score = max(0.0, min(100.0, base_score - total_penalty))

    # ── 13. Classify status ─────────────────────────────────────────────────
    hook_first_4s_ok = True
    if is_weak_intro:
        hook_first_4s_ok = False

    if is_forbidden_broll:
        status = PublishableStatus.DO_NOT_UPLOAD
        recommendation = UploadRecommendation.DISCARD_RECOMMENDED
    elif content_quality_reject:
        status = PublishableStatus.DO_NOT_UPLOAD
        recommendation = UploadRecommendation.DISCARD_RECOMMENDED
        if "content_quality_rejected" not in status_reasons:
            status_reasons.append("content_quality_rejected")
    elif (
        final_score >= SCORE_READY_MIN
        and editing_activity_ok
        and not is_weak_intro
        and hook_first3_ok
        and visual_final_verified
        and not music_required_missing
        and not static_broll_without_kenburns
        and not broll_cut_is_dry
        and retention_gate["retention_quality_status"] in {"good", "strong"}
        and not ((transitions_meta.get("transition_events") or transitions_meta.get("transition_plan")) and not transitions_meta.get("final_output_uses_transition"))
        and not no_post_layers
        and editing_richness_status not in {"too_plain"}
        and "visually_too_plain" not in editing_richness_warnings
        and editorial_fluency_ok
    ):
        status = PublishableStatus.READY_TO_UPLOAD
        recommendation = UploadRecommendation.GOOD_CANDIDATE
        status_reasons.append("all_checks_passed")
    elif final_score >= SCORE_REVIEW_MIN and not is_weak_intro:
        status = PublishableStatus.REVIEW_MANUALLY
        recommendation = UploadRecommendation.REVIEW_BEFORE_UPLOAD
        if is_generic_broll:
            status_reasons.append("generic_broll_needs_review")
        if not editing_activity_ok:
            status_reasons.append("moderate_editing_activity_needs_review")
    elif final_score >= SCORE_NEEDS_FIX_MIN or is_weak_intro:
        status = PublishableStatus.NEEDS_FIX
        recommendation = UploadRecommendation.DISCARD_RECOMMENDED if is_weak_intro else UploadRecommendation.REVIEW_BEFORE_UPLOAD
        if is_weak_intro:
            status_reasons.append("weak_intro_needs_fix")
        if final_score < SCORE_REVIEW_MIN:
            status_reasons.append(f"low_publishable_score_{final_score:.1f}")
    else:
        status = PublishableStatus.DO_NOT_UPLOAD
        recommendation = UploadRecommendation.DISCARD_RECOMMENDED
        status_reasons.append(f"very_low_publishable_score_{final_score:.1f}")

    # Deduplicate reasons
    seen: set[str] = set()
    unique_reasons: List[str] = []
    for r in status_reasons:
        if r not in seen:
            unique_reasons.append(r)
            seen.add(r)

    if not hook_first3_ok:
        recommended_next_fix = "strengthen_first3_hook"
    elif retention_gate["retention_quality_status"] == "poor":
        recommended_next_fix = retention_gate["recommended_next_fix"]
    elif no_post_layers:
        recommended_next_fix = "apply_visual_effects_or_music"
    elif editing_richness_status == "too_plain":
        recommended_next_fix = "increase_editing_richness"
    else:
        recommended_next_fix = "manual_review"

    vpi_productive_minimum_mitigation = bool(
        hook_plan.get("vpi_productive_minimum_mitigation")
        or _as_dict(hook_plan.get("hook_strategy")).get("vpi_productive_minimum_mitigation")
    )
    private_premium = assess_private_premium_status(
        content_quality_reject=content_quality_reject,
        complete_idea_score=complete_idea_score,
        fluency_score_after=fluency_score_after,
        hook_first3_ok=hook_first3_ok,
        hook_fit_acceptable=hook_fit_acceptable,
        tech_qc_ok=tech_qc_ok,
        audio_qc_ok=audio_qc_ok,
        captions_ok=captions_ok,
        branding_ok=branding_ok,
        silence_plan=_as_dict(silence_plan),
        visual_effects_meta=_as_dict(visual_effects_meta),
        transitions_meta=_as_dict(transitions_meta),
        sfx_meta=_as_dict(sfx_meta),
        broll_items=broll_items,
        editing_richness_status=editing_richness_status,
        editing_richness_warnings=editing_richness_warnings,
        first3_visual_contract=first3_visual_contract,
        premium_layers_applied=clip_info.get("premium_layers_applied"),
        vpi_productive_minimum_mitigation=vpi_productive_minimum_mitigation,
    )

    result = PublishableGateResult(
        publishable_status=status,
        publishable_score=round(final_score, 1),
        publishable_reasons=unique_reasons,
        publishable_warnings=warnings,
        upload_recommendation=recommendation,
        discard_recommended=(recommendation == UploadRecommendation.DISCARD_RECOMMENDED),
        weak_intro_detected=is_weak_intro,
        generic_broll_detected=is_generic_broll,
        forbidden_broll_detected=is_forbidden_broll,
        editing_activity_ok=editing_activity_ok,
        hook_first_4s_ok=hook_first_4s_ok,
        technical_qc_ok=tech_qc_ok,
        audio_qc_ok=audio_qc_ok,
        silence_ok=silence_ok,
        captions_ok=captions_ok,
        branding_ok=branding_ok,
        missing_editing_layers=list(dict.fromkeys([*missing_layers, *retention_gate["retention_missing_layers"]])),
        recommended_next_fix=recommended_next_fix,
        retention_quality_score=int(retention_gate["retention_quality_score"]),
        retention_quality_status=str(retention_gate["retention_quality_status"]),
        retention_missing_layers=list(retention_gate["retention_missing_layers"]),
        private_premium_status=str(private_premium["private_premium_status"]),
        private_premium_editorial_quality=str(private_premium["private_premium_editorial_quality"]),
        private_premium_postproduction_richness=str(private_premium["private_premium_postproduction_richness"]),
        private_premium_limited_assets=bool(private_premium["private_premium_limited_assets"]),
        # ── FASE 5: Editorial Fluency ──────────────────────────────────────
        editorial_fluency_ok=editorial_fluency_ok,
        editorial_fluency_score=round(editorial_fluency_score, 2),
        complete_idea_score=round(complete_idea_score, 2),
        fluency_score_after=round(fluency_score_after, 2),
        hook_fit_acceptable=hook_fit_acceptable,
        editorial_fluency_warnings=editorial_fluency_warnings,
    )
    logger.info("[publishable-gate] upload_recommendation=%s", result.upload_recommendation.value)
    return result


def rank_clips(
    clip_results: List[Tuple[int, Dict[str, Any], float]],
) -> List[Dict[str, Any]]:
    """Rank clips after render, marking best_candidate and discard_recommended.

    Args:
        clip_results: List of (index, clip_info_dict, elapsed_s) tuples,
                      same format as render_results in task_service.py.

    Returns:
        The same clip_info dicts with publishable gate metadata injected.
        Each dict gets:
          - publishable_status
          - publishable_score
          - publishable_reasons
          - publishable_warnings
          - upload_recommendation
          - best_candidate (True for the single best clip)
          - discard_recommended (True for clips that should not be uploaded)
    """
    evaluated: List[Tuple[int, Dict[str, Any], PublishableGateResult]] = []

    for idx, clip_info, elapsed in clip_results:
        if clip_info is None:
            continue

        result = evaluate_clip_publishability(clip_info)
        evaluated.append((idx, clip_info, result))

    if not evaluated:
        return []

    # Sort by publishable_score descending
    evaluated.sort(key=lambda x: x[2].publishable_score, reverse=True)

    # Mark best candidate (top scorer that is not DO_NOT_UPLOAD)
    best_found = False
    for idx, clip_info, result in evaluated:
        if not best_found and result.publishable_status != PublishableStatus.DO_NOT_UPLOAD:
            result.best_candidate = True
            result.upload_recommendation = UploadRecommendation.BEST_CANDIDATE
            best_found = True

    # Mark discard_recommended for weak/forbidden clips
    for idx, clip_info, result in evaluated:
        if result.publishable_status in (
            PublishableStatus.DO_NOT_UPLOAD,
            PublishableStatus.NEEDS_FIX,
        ):
            result.discard_recommended = True
            if result.upload_recommendation == UploadRecommendation.REVIEW_BEFORE_UPLOAD:
                result.upload_recommendation = UploadRecommendation.DISCARD_RECOMMENDED

    # Inject metadata back into clip_info dicts
    for idx, clip_info, result in evaluated:
        clip_info["publishable_status"] = result.publishable_status.value
        clip_info["publishable_score"] = result.publishable_score
        clip_info["publishable_reasons"] = result.publishable_reasons
        clip_info["publishable_warnings"] = result.publishable_warnings
        clip_info["upload_recommendation"] = result.upload_recommendation.value
        clip_info["best_candidate"] = result.best_candidate
        clip_info["discard_recommended"] = result.discard_recommended
        clip_info["missing_editing_layers"] = result.missing_editing_layers
        clip_info["recommended_next_fix"] = result.recommended_next_fix
        clip_info["publishable_gate"] = result.to_dict()

        # Also inject into editing_plan if present
        editing_plan = clip_info.get("editing_plan")
        if isinstance(editing_plan, dict):
            editing_plan["publishable_status"] = result.publishable_status.value
            editing_plan["publishable_score"] = result.publishable_score
            editing_plan["publishable_warnings"] = result.publishable_warnings
            editing_plan["upload_recommendation"] = result.upload_recommendation.value
            editing_plan["best_candidate"] = result.best_candidate
            editing_plan["discard_recommended"] = result.discard_recommended
            editing_plan["missing_editing_layers"] = result.missing_editing_layers
            editing_plan["recommended_next_fix"] = result.recommended_next_fix

    # Restore original order
    evaluated.sort(key=lambda x: x[0])
    return [ci for _, ci, _ in evaluated]
