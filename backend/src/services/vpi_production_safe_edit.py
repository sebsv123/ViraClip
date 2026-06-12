"""Production-safe edit helpers for visible VPI quality improvements.

This module keeps the visible edit policy in one place without affecting
selection, source contracts, queues, or Remotion.
"""
from __future__ import annotations

import logging
import os
import re
import unicodedata
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)

PRODUCTION_SAFE_EDIT_ENV = "VPI_PRODUCTION_SAFE_EDIT"
DAILY_MODE_ENV = "VPI_DAILY_MODE"
DAILY_MODE_ALLOW_UNSAFE_ENV = "VPI_DAILY_MODE_ALLOW_UNSAFE"
TYPEWRITER_SFX_ENV = "VPI_DISABLE_TYPEWRITER_SFX"

PRODUCTION_SAFE_POLICY_VERSION = "a4"
VPI_DAILY_MODE_VERSION = "a1"
VPI_PREMIUM_FLOW_MANIFEST_VERSION = "a1"
_PRODUCTION_SAFE_ALLOWED_ROUTES = {
    "vpi_music_service",
    "vpi_sfx_service",
    "ass_premium_captions",
    "local_broll_asset_bank",
    "ffmpeg_native_visual_fallback",
    "vpi_transition_engine_sober",
    "vpi_audio_mastering",
    "final_mp4_contract",
}
_PRODUCTION_SAFE_BLOCKED_ROUTES = {
    "comfyui",
    "comfyui_upscale",
    "t2v",
    "ollama",
    "phi3_ollama",
    "visual_scoring_ollama",
    "external_pexels",
    "pexels_overlay",
    "external_broll_provider",
    "semantic_broll_external",
    "remotion_overlay_compose",
    "legacy_sound_design",
    "legacy_beat_sync_bgm",
    "background_music_legacy",
    "smart_audio_legacy",
    "optical_flow_heavy_transition",
    "rvc",
    "tts_dubbing",
    "translation_dubbing",
    "esrgan_upscale",
}

_LEGACY_OR_EXPERIMENTAL_ROUTES = {
    "apply_single_transition_optical_flow": {
        "status": "quarantined",
        "reason": "legacy_optical_flow_transition_path",
    },
    "legacy_pexels_overlay": {
        "status": "quarantined",
        "reason": "legacy_external_stock_overlay",
    },
    "background_music_legacy": {
        "status": "deprecated",
        "reason": "legacy_bgm_path",
    },
    "smart_audio_legacy": {
        "status": "deprecated",
        "reason": "legacy_audio_mastering_path",
    },
    "legacy_caption_word_level": {
        "status": "experimental",
        "reason": "last_resort_caption_fallback",
    },
    "legacy_caption_service_fallback": {
        "status": "quarantined",
        "reason": "caption_service_fallback_path",
    },
    "comfyui_enhance": {
        "status": "quarantined",
        "reason": "legacy_comfyui_enhancement",
    },
    "remotion_overlay_compose": {
        "status": "deprecated",
        "reason": "legacy_remotion_overlay_path",
    },
    "esrgan_upscale": {
        "status": "deprecated",
        "reason": "legacy_external_upscale_path",
    },
    "rvc_voice": {
        "status": "quarantined",
        "reason": "legacy_voice_conversion_path",
    },
    "tts_dubbing": {
        "status": "quarantined",
        "reason": "legacy_tts_dubbing_path",
    },
    "translation_dubbing": {
        "status": "quarantined",
        "reason": "legacy_translation_dubbing_path",
    },
    "filename_contract_truth": {
        "status": "deprecated",
        "reason": "legacy_filename_truth_source",
    },
    "viral_effects_legacy": {
        "status": "deprecated",
        "reason": "legacy_viral_effects_path",
    },
    "contextual_overlay_legacy": {
        "status": "deprecated",
        "reason": "legacy_contextual_overlay_path",
    },
}

_HOOK_FALLBACK_PHRASES = [
    "Esto mucha gente no lo sabe",
    "Cuidado con esto",
    "Antes de contratar, mira esto",
    "Esto puede ahorrarte un problema",
]

_BROLL_SAFE_TERMS = (
    "proteccion familiar",
    "protección familiar",
    "tranquilidad",
    "salud",
    "médico",
    "medico",
    "hospitalizacion",
    "hospitalización",
    "accidente",
    "riesgo",
    "ahorro",
    "dinero",
    "imprevisto",
    "familia",
    "proteger",
)


def _truthy(value: str, default: bool = False) -> bool:
    raw = os.environ.get(value)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dedupe_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def vpi_daily_mode_enabled() -> bool:
    return _truthy(DAILY_MODE_ENV, default=False)


def vpi_daily_mode_unsafe_override_used() -> bool:
    return _truthy(DAILY_MODE_ALLOW_UNSAFE_ENV, default=False)


def production_safe_edit_enabled() -> bool:
    return bool(_truthy(PRODUCTION_SAFE_EDIT_ENV, default=True) or (vpi_daily_mode_enabled() and not vpi_daily_mode_unsafe_override_used()))


def production_safe_mode_active() -> bool:
    return production_safe_edit_enabled()


def get_vpi_daily_mode_policy() -> Dict[str, Any]:
    enabled = bool(vpi_daily_mode_enabled())
    unsafe_override = bool(vpi_daily_mode_unsafe_override_used())
    enforced_flags = []
    disabled_routes = []
    enabled_local_features = []
    daily_mode_conflicts_resolved: list[str] = []
    if enabled and not unsafe_override:
        enforced_flags = [
            "VIRACLIP_BETA_CLEAN=true",
            "VPI_PRODUCTION_SAFE_EDIT=true",
            "VIRACLIP_ENABLE_PREMIUM_EDITING=true",
            "VIRACLIP_REMOTION_OVERLAYS=false",
            "VIRACLIP_COMPOSE_REMOTION_OVERLAY=false",
        ]
        disabled_routes = sorted(
            set(_PRODUCTION_SAFE_BLOCKED_ROUTES)
            | {
                "comfyui",
                "comfyui_upscale",
                "t2v",
                "ollama",
                "phi3_ollama",
                "visual_scoring_ollama",
                "external_pexels",
                "pexels_overlay",
                "external_broll_provider",
                "semantic_broll_external",
                "remotion_overlay_compose",
                "legacy_sound_design",
                "legacy_beat_sync_bgm",
                "background_music_legacy",
                "smart_audio_legacy",
            }
        )
        enabled_local_features = [
            "premium_local_audio",
            "premium_local_visuals",
            "premium_editorial_selection",
            "output_manifest_json",
            "summary_markdown",
            "local_review_bundle",
            "production_safe_routes",
        ]
        for route_name in disabled_routes:
            logger.info("VPI_DAILY_MODE_ROUTE_DISABLED route=%s reason=daily_mode", route_name)
        if enforced_flags:
            daily_mode_conflicts_resolved.append("env_flags_enforced")
    elif enabled and unsafe_override:
        daily_mode_conflicts_resolved.append("unsafe_override_used")

    policy = {
        "vpi_daily_mode_enabled": bool(enabled),
        "daily_mode_version": VPI_DAILY_MODE_VERSION,
        "enforced_flags": enforced_flags,
        "disabled_routes": disabled_routes,
        "enabled_local_features": enabled_local_features,
        "daily_mode_reason": "stable_local_production_defaults" if enabled else "disabled",
        "daily_mode_conflicts_resolved": _dedupe_strings(daily_mode_conflicts_resolved),
        "daily_mode_unsafe_override_used": bool(unsafe_override),
        "daily_mode_outputs_enabled": bool(enabled),
    }
    if enabled:
        logger.info(
            "VPI_DAILY_MODE_POLICY_LOADED version=%s enabled=%s unsafe_override=%s enforced_flags=%d disabled_routes=%d local_features=%d",
            policy["daily_mode_version"],
            str(policy["vpi_daily_mode_enabled"]).lower(),
            str(policy["daily_mode_unsafe_override_used"]).lower(),
            len(policy["enforced_flags"]),
            len(policy["disabled_routes"]),
            len(policy["enabled_local_features"]),
        )
        logger.info(
            "VPI_DAILY_MODE_ENABLED version=%s outputs_enabled=%s reason=%s",
            policy["daily_mode_version"],
            str(policy["daily_mode_outputs_enabled"]).lower(),
            policy["daily_mode_reason"],
        )
        if policy["daily_mode_conflicts_resolved"]:
            logger.info(
                "VPI_DAILY_MODE_CONFLICT_RESOLVED conflicts=%s",
                "|".join(policy["daily_mode_conflicts_resolved"]),
            )
    return policy


def get_production_safe_policy() -> Dict[str, Any]:
    daily_mode_policy = get_vpi_daily_mode_policy()
    policy = {
        "policy_version": PRODUCTION_SAFE_POLICY_VERSION,
        "allow_external_ai": False,
        "allow_external_stock": False,
        "allow_remotion": False,
        "allow_comfyui": False,
        "allow_ollama": False,
        "allow_t2v": False,
        "allow_legacy_audio": False,
        "allow_legacy_sfx": False,
        "allow_legacy_broll": False,
        "allow_heavy_optical_flow": False,
        "allow_local_assets": True,
        "allow_nvenc": True,
        "allow_ffmpeg_native_fallbacks": True,
        "allow_verified_local_broll": True,
        "production_safe_external_disabled": True,
        "production_safe_legacy_disabled": True,
        "production_safe_mode_active": production_safe_mode_active(),
        "production_safe_routes_allowed": sorted(_PRODUCTION_SAFE_ALLOWED_ROUTES),
        "production_safe_routes_blocked": sorted(set(_PRODUCTION_SAFE_BLOCKED_ROUTES) | set(daily_mode_policy.get("disabled_routes") or [])),
        "vpi_daily_mode_enabled": bool(daily_mode_policy.get("vpi_daily_mode_enabled")),
        "daily_mode_version": str(daily_mode_policy.get("daily_mode_version") or VPI_DAILY_MODE_VERSION),
        "daily_mode_policy": dict(daily_mode_policy),
        "daily_mode_outputs_enabled": bool(daily_mode_policy.get("daily_mode_outputs_enabled")),
        "daily_mode_conflicts_resolved": list(daily_mode_policy.get("daily_mode_conflicts_resolved") or []),
        "daily_mode_unsafe_override_used": bool(daily_mode_policy.get("daily_mode_unsafe_override_used")),
    }
    logger.info(
        "PRODUCTION_SAFE_POLICY_LOADED version=%s active=%s external_disabled=%s legacy_disabled=%s daily_mode=%s",
        policy["policy_version"],
        str(policy["production_safe_mode_active"]).lower(),
        str(policy["production_safe_external_disabled"]).lower(),
        str(policy["production_safe_legacy_disabled"]).lower(),
        str(policy["vpi_daily_mode_enabled"]).lower(),
    )
    return policy


def get_vpi_premium_flow_manifest() -> Dict[str, Any]:
    manifest = {
        "manifest_version": VPI_PREMIUM_FLOW_MANIFEST_VERSION,
        "expected_phase_order": [
            "base_clip",
            "rhythm",
            "hook",
            "broll",
            "captions",
            "visual_layer_budget",
            "visual_reinforcement",
            "transitions",
            "bgm",
            "sfx",
            "audio_mastering",
            "final_qc",
            "final_freeze",
            "persistence_handoff",
        ],
        "critical_phases": [
            "base_clip",
            "captions",
            "audio_base",
            "final_qc",
            "final_freeze",
        ],
        "optional_phases": [
            "bgm",
            "sfx",
            "broll",
            "visual_reinforcement",
            "transitions",
            "branding",
            "visual_effects",
        ],
        "allowed_output_mutators_before_freeze": [
            "rhythm",
            "hook",
            "broll",
            "captions",
            "visual_reinforcement",
            "transitions",
            "bgm",
            "sfx",
            "audio_mastering",
            "branding_if_allowed",
            "cinematic_finish_if_allowed",
        ],
        "forbidden_output_mutators_after_freeze": [
            "remotion_overlay_compose",
            "pexels_overlay",
            "comfyui",
            "t2v",
            "ollama",
            "legacy_sound_design",
            "legacy_beat_sync_bgm",
            "optical_flow_heavy_transition",
        ],
        "production_safe_required_truth_source": "final_mp4_contract",
    }
    logger.info(
        "PREMIUM_FLOW_MANIFEST_LOADED version=%s phases=%d critical=%d optional=%d",
        manifest["manifest_version"],
        len(manifest["expected_phase_order"]),
        len(manifest["critical_phases"]),
        len(manifest["optional_phases"]),
    )
    return manifest


def validate_premium_flow_manifest(route_registry: Dict[str, Any], final_metadata: Dict[str, Any]) -> Dict[str, Any]:
    manifest = get_vpi_premium_flow_manifest()
    registry = route_registry if isinstance(route_registry, dict) else {}
    metadata = final_metadata if isinstance(final_metadata, dict) else {}
    phase_names = list(manifest.get("expected_phase_order") or [])

    def _phase_has_state(phase_name: str) -> bool:
        phase_meta = _safe_dict(metadata.get("phase_consistency", {}).get(phase_name))
        registry_meta = _safe_dict(registry.get(phase_name))
        if phase_name == "base_clip":
            return bool(metadata.get("final_output_path") or metadata.get("final_video_exists") or metadata.get("render_success"))
        if phase_name == "audio_base":
            return bool(metadata.get("final_audio_stream_ok") or metadata.get("has_audio") or metadata.get("has_bgm") or metadata.get("has_sfx"))
        if phase_name == "final_freeze":
            return bool(metadata.get("final_render_locked") or metadata.get("final_render_locked_at_stage"))
        if phase_name == "persistence_handoff":
            return bool(metadata.get("final_output_path") or metadata.get("route_registry"))
        if isinstance(phase_meta, dict) and (phase_meta.get("route_used") or phase_meta.get("status") or phase_meta.get("fallback_used")):
            return True
        if isinstance(registry_meta, dict) and (registry_meta.get("route_used") or registry_meta.get("fallback_used") or registry_meta.get("reason")):
            return True
        return False

    observed_phases = []
    for phase_name in phase_names:
        if _phase_has_state(phase_name):
            observed_phases.append(phase_name)

    missing_critical_phases = []
    for critical_phase in manifest.get("critical_phases") or []:
        if not _phase_has_state(critical_phase):
            missing_critical_phases.append(critical_phase)

    final_truth_source = str(metadata.get("final_truth_source") or metadata.get("final_contract", {}).get("final_truth_source") or "").strip()
    final_truth_source_ok = bool(final_truth_source == manifest.get("production_safe_required_truth_source"))

    observed_route_names = []
    for value in registry.values():
        if not isinstance(value, dict):
            continue
        for key in ("route_used", "fallback_route"):
            route_name = str(value.get(key) or "").strip()
            if route_name:
                observed_route_names.append(route_name)

    unexpected_mutators_after_freeze = []
    freeze_locked = bool(metadata.get("final_render_locked") or metadata.get("final_render_locked_at_stage"))
    if freeze_locked:
        forbidden_routes = set(str(item or "").strip() for item in (manifest.get("forbidden_output_mutators_after_freeze") or []))
        for route_name in observed_route_names:
            if route_name in forbidden_routes:
                unexpected_mutators_after_freeze.append(route_name)

    deprecated_routes_in_flow = []
    for route_name in list(_safe_list(registry.get("production_safe_routes_blocked"))) + list(_safe_list(metadata.get("deprecated_routes_used"))):
        if str(route_name or "").strip():
            deprecated_routes_in_flow.append(str(route_name))

    premium_flow_manifest_errors = []
    premium_flow_manifest_warnings = []
    if missing_critical_phases:
        premium_flow_manifest_errors.append("missing_critical_phases")
    if unexpected_mutators_after_freeze:
        premium_flow_manifest_errors.append("output_mutation_after_final_lock")
    if deprecated_routes_in_flow:
        premium_flow_manifest_warnings.append("deprecated_routes_in_flow")
    if not final_truth_source_ok:
        premium_flow_manifest_errors.append("final_truth_source_not_contract")

    premium_flow_manifest_ok = len(premium_flow_manifest_errors) == 0
    result = {
        "premium_flow_manifest_ok": bool(premium_flow_manifest_ok),
        "premium_flow_manifest_warnings": _dedupe_strings(premium_flow_manifest_warnings),
        "premium_flow_manifest_errors": _dedupe_strings(premium_flow_manifest_errors),
        "observed_phases": observed_phases,
        "missing_critical_phases": _dedupe_strings(missing_critical_phases),
        "unexpected_mutators_after_freeze": _dedupe_strings(unexpected_mutators_after_freeze),
        "deprecated_routes_in_flow": _dedupe_strings(deprecated_routes_in_flow),
        "final_truth_source_ok": bool(final_truth_source_ok),
        "premium_flow_manifest": manifest,
    }
    logger.info(
        "PREMIUM_FLOW_MANIFEST_VALIDATED ok=%s observed=%d missing=%d mutators=%d deprecated=%d truth_ok=%s",
        str(result["premium_flow_manifest_ok"]).lower(),
        len(result["observed_phases"]),
        len(result["missing_critical_phases"]),
        len(result["unexpected_mutators_after_freeze"]),
        len(result["deprecated_routes_in_flow"]),
        str(result["final_truth_source_ok"]).lower(),
    )
    if result["premium_flow_manifest_errors"]:
        logger.warning(
            "PREMIUM_FLOW_MANIFEST_FAILED errors=%s",
            "|".join(result["premium_flow_manifest_errors"]),
        )
    elif result["premium_flow_manifest_warnings"]:
        logger.warning(
            "PREMIUM_FLOW_MANIFEST_WARNING warnings=%s",
            "|".join(result["premium_flow_manifest_warnings"]),
    )
    return result


def build_audio_chain_plan(*, production_safe: bool | None = None, audio_expected: bool = True) -> Dict[str, Any]:
    plan = {
        "audio_chain_version": "a1",
        "expected_order": [
            "base_audio",
            "bgm",
            "sfx",
            "mastering",
            "final_audio_verify",
        ],
        "bgm_allowed": bool(not production_safe or production_safe_mode_active()),
        "sfx_allowed": True,
        "mastering_required": bool(audio_expected),
        "voice_priority": True,
        "allow_duplicate_bgm": False,
        "allow_duplicate_sfx": False,
    }
    logger.info(
        "AUDIO_CHAIN_PLAN_BUILT version=%s order=%s bgm_allowed=%s sfx_allowed=%s mastering_required=%s voice_priority=%s",
        plan["audio_chain_version"],
        "|".join(plan["expected_order"]),
        str(plan["bgm_allowed"]).lower(),
        str(plan["sfx_allowed"]).lower(),
        str(plan["mastering_required"]).lower(),
        str(plan["voice_priority"]).lower(),
    )
    return plan


def audio_chain_state_template() -> Dict[str, Any]:
    return {
        "base_audio_detected": False,
        "bgm_passes": [],
        "sfx_passes": [],
        "mastering_passes": [],
        "audio_routes_blocked": [],
        "audio_chain_errors": [],
        "audio_chain_warnings": [],
    }


def _normalize_route(route_name: str) -> str:
    return _normalize(route_name).replace(" ", "_")


def production_safe_route_allowed(route_name: str) -> bool:
    normalized = _normalize_route(route_name)
    if not production_safe_mode_active():
        return True
    if normalized in _PRODUCTION_SAFE_ALLOWED_ROUTES:
        logger.info("PRODUCTION_SAFE_ROUTE_ALLOWED route=%s reason=explicit_allowlist", normalized)
        return True
    if normalized == "explicit_verified_clip_transition":
        logger.info("PRODUCTION_SAFE_ROUTE_ALLOWED route=%s reason=explicit_verified_clip_transition", normalized)
        return True
    if normalized in {"legacy_caption_service_fallback", "legacy_caption_word_level"}:
        return True
    if normalized in _LEGACY_OR_EXPERIMENTAL_ROUTES:
        return False
    if normalized in _PRODUCTION_SAFE_BLOCKED_ROUTES:
        return False
    if any(token in normalized for token in ("comfyui", "ollama", "pexels", "t2v", "remotion", "rvc", "dubbing", "translation", "esrgan", "optical_flow")):
        return False
    return True


def production_safe_route_block_reason(route_name: str) -> str:
    if production_safe_edit_enabled() and not production_safe_route_allowed(route_name):
        return "premium_local_stability"
    return ""


def should_block_production_safe_route(route_name: str) -> bool:
    return bool(production_safe_edit_enabled() and not production_safe_route_allowed(route_name))


def is_legacy_or_experimental_route(route_name: str) -> bool:
    normalized = _normalize_route(route_name)
    return bool(normalized in _LEGACY_OR_EXPERIMENTAL_ROUTES)


def legacy_route_status(route_name: str) -> Dict[str, Any]:
    normalized = _normalize_route(route_name)
    if normalized in _LEGACY_OR_EXPERIMENTAL_ROUTES:
        info = dict(_LEGACY_OR_EXPERIMENTAL_ROUTES[normalized])
        return {
            "route": normalized,
            "status": str(info.get("status") or "quarantined"),
            "reason": str(info.get("reason") or "legacy_route"),
            "allowed_in_production_safe": False,
        }
    return {
        "route": normalized,
        "status": "allowed",
        "reason": "",
        "allowed_in_production_safe": True,
    }


def typewriter_sfx_disabled_by_default() -> bool:
    return _truthy(TYPEWRITER_SFX_ENV, default=True)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    ascii_text = re.sub(r"[^a-z0-9\s]", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip()


def build_hook_fallback_text(text: str, editorial_type: str = "", hook_type: str = "") -> str:
    normalized = _normalize(" ".join([text or "", editorial_type or "", hook_type or ""]))
    if any(term in normalized for term in ("cuidado", "riesgo", "peligro", "no avisa", "imprevisto", "problema")):
        return _HOOK_FALLBACK_PHRASES[1]
    if any(term in normalized for term in ("contratar", "cobertura", "poliza", "póliza", "antes de", "seguro")):
        return _HOOK_FALLBACK_PHRASES[2]
    if any(term in normalized for term in ("familia", "proteger", "proteccion", "protección", "tranquilidad", "salud", "hospital")):
        return _HOOK_FALLBACK_PHRASES[3]
    return _HOOK_FALLBACK_PHRASES[0]


def condense_hook_text(text: str, max_words: int = 9) -> str:
    words = [word for word in _normalize(text).split(" ") if word]
    if not words:
        return ""
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words])


def should_allow_high_confidence_broll(
    *,
    confidence: float,
    text: str,
    cue_text: str = "",
    editorial_type: str = "",
) -> Tuple[bool, str]:
    if not production_safe_edit_enabled():
        return True, "production_safe_edit_disabled"
    normalized = _normalize(" ".join([text or "", cue_text or "", editorial_type or ""]))
    explicit_match = any(term in normalized for term in _BROLL_SAFE_TERMS)
    if confidence >= 0.75 and explicit_match:
        return True, "high_confidence_explicit_match"
    return False, "low_relevance"


def max_visible_text_layers() -> int:
    return 2
