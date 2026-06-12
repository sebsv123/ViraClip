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
import json
import os
import re
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)


def _is_vpi_productive_minimum() -> bool:
    """Check if VPI productive minimum mode is active (env or config)."""
    val = os.environ.get("VPI_PRODUCTIVE_MINIMUM", "")
    if val:
        return val.lower() in ("1", "true", "yes")
    # Fallback: check if beta_clean is active (productive minimum defaults True in beta_clean)
    beta = os.environ.get("VIRACLIP_BETA_CLEAN", "")
    if beta.lower() in ("1", "true", "yes"):
        return True
    return False

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
_SFX_ROTATION_DIR = Path(os.environ.get("VIRACLIP_SFX_ROTATION_DIR") or "/tmp")

_RETENTION_KEYWORDS = {
    "risk_warning": ("no siempre avisa", "riesgo", "imprevisto", "advertencia", "urgente"),
    "myth_flip": ("no va de", "no es", "va de", "mito", "error comun"),
    "practical_advice": ("antes de", "conviene", "recomendacion", "paso", "organizacion"),
    "autonomous_business_stakes": ("autonomo", "autónomo", "motor", "ingresos", "negocio", "estabilidad"),
    "emotional_closure": ("cuando mas falta hace", "cuando más falta hace", "familia", "apoyo", "tranquilidad"),
}

_SFX_FAMILY_TO_ASSET_KEYS: Dict[str, tuple[str, ...]] = {
    "tension_riser": ("high_riser",),
    "high_riser": ("high_riser",),
    "dark_riser": ("low_riser", "high_riser"),
    "magic_whoosh": ("magic_whoosh",),
    "deep_boom": ("deep_boom",),
    "soft_chime": ("magic_whoosh", "high_riser"),
    "soft_whoosh": ("magic_whoosh",),
    "soft_impact": ("deep_boom",),
    "deep_boom_light": ("deep_boom",),
    "dark_riser_short": ("low_riser",),
    "subtle_tick_off": ("magic_whoosh", "high_riser"),
    "check_pop": ("magic_whoosh", "high_riser"),
    "myth_break": ("magic_whoosh",),
    "question_tap": ("magic_whoosh", "high_riser"),
    "soft_hit": ("deep_boom",),
}

_AGGRESSIVE_FAMILIES = {"deep_boom", "glitch_hit", "sfx_hit"}
_BAD_SILENCE_REASONS = ("bts", "false_start", "awkward", "dead_air", "weak_intro", "filler", "stumble", "traba")
_REVELATION_CUES = ("esto mucha gente no lo sabe", "la realidad es", "lo importante")
_RISK_CUES = ("miedo", "riesgo", "problema", "cuidado", "error", "imprevisto", "no es vender miedo")
_MYTH_CUES = ("mito", "no es asi", "falso", "mucha gente piensa")
_OBJECTION_CUES = ("es muy caro", "yo ya tengo", "no me hace falta")
_ADVICE_CUES = ("consejo", "haz esto", "lo mejor es", "revisa")
_EMOTIONAL_CUES = ("familia", "proteger", "tranquilidad", "calma", "tuyos")
_BLOCKED_SFX_TERMS = (
    "typewriter",
    "typing",
    "keyboard",
    "click",
    "clicks",
    "tick",
    "ticker",
    "mechanical_click",
    "keypress",
)
_ALLOWED_SFX_FAMILIES = {
    "magic_whoosh",
    "whoosh",
    "impact",
    "soft_impact",
    "deep_boom",
    "boom",
    "dark_riser",
    "tension_riser",
    "high_riser",
    "soft_chime",
    "soft_whoosh",
    "deep_boom_light",
    "dark_riser_short",
    "subtle_tick_off",
    "check_pop",
    "myth_break",
    "question_tap",
    "soft_hit",
}

_SFX_FAMILY_ALIASES = {
    "soft_whoosh": "magic_whoosh",
    "soft_impact": "deep_boom",
    "deep_boom_light": "deep_boom",
    "dark_riser_short": "dark_riser",
    "subtle_tick_off": "soft_chime",
    "check_pop": "soft_chime",
    "myth_break": "magic_whoosh",
    "question_tap": "soft_chime",
    "soft_hit": "deep_boom",
}

_SFX_FAMILY_FALLBACKS = {
    "soft_whoosh": ("magic_whoosh", "soft_chime"),
    "soft_impact": ("deep_boom", "deep_boom_light"),
    "deep_boom_light": ("deep_boom", "soft_impact"),
    "dark_riser_short": ("dark_riser", "tension_riser"),
    "soft_chime": ("soft_chime", "check_pop"),
    "check_pop": ("soft_chime", "soft_whoosh"),
    "myth_break": ("magic_whoosh", "soft_chime"),
    "question_tap": ("soft_chime", "soft_whoosh"),
    "warning_tap": ("soft_chime", "dark_riser_short"),
    "soft_hit": ("deep_boom", "soft_impact"),
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _candidate_sfx_dirs() -> Iterable[Path]:
    root = _repo_root()
    for item in _SFX_DIRS:
        path = Path(item)
        yield path if path.is_absolute() else root / path


def classify_sfx_asset(path: Path) -> Optional[str]:
    name = path.stem.lower()
    if _is_blocked_sfx_text(name):
        return None
    if any(term in name for term in ("magic", "sparkle", "shimmer", "whoosh", "glitch")):
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


def _normalize_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    ascii_text = re.sub(r"[^a-z0-9\s]", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip()


def _is_blocked_sfx_text(text: str) -> bool:
    normalized = _normalize_text(text)
    return any(term in normalized for term in _BLOCKED_SFX_TERMS)


def _is_allowed_sfx_family(family: str) -> bool:
    normalized = _normalize_text(family).replace(" ", "_")
    mapped = _SFX_FAMILY_ALIASES.get(normalized, normalized)
    return normalized in _ALLOWED_SFX_FAMILIES or mapped in _ALLOWED_SFX_FAMILIES


def _sfx_family_fallback_order(family: str) -> List[str]:
    normalized = _normalize_text(family).replace(" ", "_")
    mapped = _SFX_FAMILY_ALIASES.get(normalized, normalized)
    fallback_order = [mapped]
    fallback_order.extend(list(_SFX_FAMILY_FALLBACKS.get(mapped, ())))
    fallback_order.extend(list(_SFX_FAMILY_FALLBACKS.get(normalized, ())))
    fallback_order.append("soft_chime")
    fallback_order.append("magic_whoosh")
    fallback_order.append("deep_boom")
    return list(dict.fromkeys(item for item in fallback_order if item))


def _contains_any(text: str, keywords: Sequence[str]) -> bool:
    normalized = _normalize_text(text)
    return any(_normalize_text(word) in normalized for word in keywords if str(word).strip())


def _voice_dense_segment(segment_text: str) -> bool:
    words = [token for token in _normalize_text(segment_text).split(" ") if token]
    if len(words) >= 18:
        return True
    return len(" ".join(words)) >= 120


def _is_safe_silence_reason(reason: str) -> bool:
    normalized = _normalize_text(reason)
    return bool(normalized) and not any(flag in normalized for flag in _BAD_SILENCE_REASONS)


def _sfx_rotation_path(task_id: Optional[str]) -> Path:
    suffix = str(task_id or "global").replace("/", "_")
    return _SFX_ROTATION_DIR / f"viraclip_sfx_rotation_{suffix}.txt"


def _read_sfx_rotation_history(task_id: Optional[str]) -> List[str]:
    path = _sfx_rotation_path(task_id)
    if not path.exists():
        return []
    try:
        return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except Exception:
        return []


def _append_sfx_rotation_history(task_id: Optional[str], asset: str) -> None:
    if not asset:
        return
    _SFX_ROTATION_DIR.mkdir(parents=True, exist_ok=True)
    path = _sfx_rotation_path(task_id)
    history = _read_sfx_rotation_history(task_id)
    history.append(asset)
    history = history[-20:]
    try:
        path.write_text("\n".join(history) + "\n", encoding="utf-8")
    except Exception:
        pass


def build_sfx_retention_decision(
    *,
    hook_intent: str = "",
    visual_profile: str = "",
    composition_mode: str = "",
    broll_editorial_decision: Optional[Dict[str, Any]] = None,
    segment_text: str = "",
    private_premium_status: str = "",
    first3_visual_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    resolved_intent = str(hook_intent or "neutral_explanation")
    text = str(segment_text or "")
    comp_mode = str(composition_mode or "")
    normalized_text = _normalize_text(text)

    if str(private_premium_status or "") == "DO_NOT_UPLOAD":
        decision = {
            "should_apply_sfx": False,
            "sfx_intent": "no_sfx_needed",
            "sfx_family": "no_sfx_needed",
            "timing_offset": 0.0,
            "duration": 0.0,
            "volume_db": -28.0,
            "reason": "private_premium_do_not_upload",
            "confidence": 0.0,
            "fallback": "none",
            "skip_reason": "sensitive_tone",
        }
        logger.info("[sfx-retention] should_apply=false intent=no_sfx_needed family=no_sfx_needed confidence=0.00 reason=private_premium_do_not_upload")
        logger.info("[sfx-retention] skipped reason=sensitive_tone")
        return decision

    has_revelation = _contains_any(normalized_text, _REVELATION_CUES)
    has_risk = _contains_any(text, _RETENTION_KEYWORDS["risk_warning"]) or _contains_any(normalized_text, _RISK_CUES)
    has_myth = _contains_any(text, _RETENTION_KEYWORDS["myth_flip"]) or _contains_any(normalized_text, _MYTH_CUES)
    has_objection = _contains_any(normalized_text, _OBJECTION_CUES)
    has_practical = _contains_any(text, _RETENTION_KEYWORDS["practical_advice"]) or _contains_any(normalized_text, _ADVICE_CUES)
    has_business = _contains_any(text, _RETENTION_KEYWORDS["autonomous_business_stakes"])
    has_emotional = _contains_any(text, _RETENTION_KEYWORDS["emotional_closure"]) or _contains_any(normalized_text, _EMOTIONAL_CUES)
    has_broll_reveal = bool((broll_editorial_decision or {}).get("should_use_broll"))
    voice_dense = _voice_dense_segment(text)

    sfx_intent = "no_sfx_needed"
    sfx_family = "no_sfx_needed"
    reason = "no_retention_gain"
    confidence = 0.2
    timing_offset = 0.0
    duration = 0.0
    volume_db = -28.0
    fallback = "none"
    skip_reason = ""
    should_apply = False

    # Canonical editorial SFX intent model
    editorial_intent = "none"
    if resolved_intent in {"myth_flip", "revelation"} or has_revelation:
        editorial_intent = "revelation"
    elif resolved_intent == "risk_warning" or has_risk:
        editorial_intent = "risk_warning"
    elif has_myth:
        editorial_intent = "myth_debunk"
    elif has_objection:
        editorial_intent = "objection"
    elif resolved_intent in {"practical_advice", "actionable_advice"} or has_practical:
        editorial_intent = "actionable_advice"
    elif resolved_intent in {"emotional_closure", "emotional_protection"} or has_emotional:
        editorial_intent = "emotional_protection"

    if editorial_intent == "risk_warning" and (has_risk or has_broll_reveal or visual_profile == "tension_push"):
        sfx_intent = "tension_riser"
        sfx_family = "dark_riser"
        reason = "warning_emphasis_retention"
        confidence = 0.78
        timing_offset = -0.10
        duration = 1.0
        volume_db = -24.0
        should_apply = True
    elif editorial_intent in {"myth_debunk", "revelation"} and (has_myth or has_revelation or has_broll_reveal):
        sfx_intent = "magic_whoosh"
        sfx_family = "magic_whoosh"
        reason = "reveal_or_myth_contrast"
        confidence = 0.70
        timing_offset = 0.05
        duration = 0.5
        volume_db = -23.0
        should_apply = True
    elif editorial_intent == "objection":
        sfx_intent = "light_tension_riser"
        sfx_family = "high_riser"
        reason = "objection_tension_marker"
        confidence = 0.64
        timing_offset = -0.05
        duration = 0.45
        volume_db = -26.0
        should_apply = True
    elif editorial_intent == "actionable_advice":
        sfx_intent = "soft_chime"
        sfx_family = "soft_chime"
        reason = "clarity_marker"
        confidence = 0.62
        timing_offset = 0.10
        duration = 0.45
        volume_db = -26.0
        should_apply = True
    elif resolved_intent == "autonomous_business_stakes" and has_business:
        sfx_intent = "deep_boom"
        sfx_family = "deep_boom"
        reason = "business_stakes_emphasis"
        confidence = 0.74
        timing_offset = 0.08
        duration = 0.45
        volume_db = -25.0
        should_apply = True
    elif editorial_intent == "emotional_protection":
        sfx_intent = "soft_chime"
        sfx_family = "soft_chime"
        reason = "emotional_warmth_marker"
        confidence = 0.58
        timing_offset = 0.08
        duration = 0.40
        volume_db = -27.0
        should_apply = True
    elif resolved_intent == "neutral_explanation" or editorial_intent == "none":
        sfx_intent = "no_sfx_needed"
        sfx_family = "no_sfx_needed"
        reason = "neutral_explanation_no_sfx"
        confidence = 0.45

    # Productive minimum must not force SFX for layer count.
    if _is_vpi_productive_minimum() and not should_apply:
        skip_reason = "no_sfx_editorial_intent" if editorial_intent == "none" else (skip_reason or reason or "no_retention_gain")

    # composition / tone blocks
    blocked_by_tone = False
    blocked_reason = ""
    if comp_mode == "emotional_soft" and sfx_family in _AGGRESSIVE_FAMILIES:
        blocked_by_tone = True
        blocked_reason = "sensitive_tone"
    elif comp_mode == "minimal_safe" and sfx_family not in {"no_sfx_needed", "soft_chime"}:
        blocked_by_tone = True
        blocked_reason = "composition_block"
    elif voice_dense and sfx_family in {"deep_boom", "magic_whoosh", "high_riser"}:
        blocked_by_tone = True
        blocked_reason = "voice_conflict"

    if blocked_by_tone:
        should_apply = False
        skip_reason = "tone_too_sensitive" if blocked_reason == "sensitive_tone" else blocked_reason
        fallback = "caption_emphasis" if blocked_reason == "voice_conflict" else "silence_contrast"
        logger.info("[sfx-retention] blocked_by_tone=true reason=%s", blocked_reason)
    else:
        logger.info("[sfx-retention] blocked_by_tone=false reason=none")

    contract = first3_visual_contract or {}
    if str(contract.get("status") or "") == "review" and bool(contract.get("first3_visual_fail_count", 0)) >= 2:
        should_apply = False
        skip_reason = skip_reason or "composition_block"
        fallback = "caption_emphasis"

    if voice_dense and should_apply and editorial_intent in {"actionable_advice", "none"}:
        should_apply = False
        skip_reason = "no_retention_gain"

    decision = {
        "should_apply_sfx": bool(should_apply),
        "editorial_intent": editorial_intent,
        "sfx_intent": sfx_intent,
        "sfx_family": sfx_family,
        "timing_offset": round(float(timing_offset), 2),
        "duration": round(float(duration), 2),
        "volume_db": round(float(volume_db), 1),
        "reason": reason,
        "confidence": round(float(confidence), 3),
        "fallback": fallback,
        "skip_reason": skip_reason or ("no_retention_gain" if not should_apply and sfx_family != "silence_contrast" else ""),
        "voice_conflict": bool(voice_dense and blocked_reason == "voice_conflict"),
    }
    logger.info(
        "[sfx-retention] intent_mapping hook_intent=%s sfx_family=%s",
        resolved_intent,
        sfx_family,
    )
    logger.info(
        "[sfx-retention] should_apply=%s intent=%s family=%s confidence=%.2f reason=%s",
        str(bool(should_apply)).lower(),
        sfx_intent,
        sfx_family,
        float(confidence),
        reason,
    )
    if not should_apply and sfx_family != "silence_contrast":
        logger.info("[sfx-retention] skipped reason=%s", decision.get("skip_reason") or "no_retention_gain")
    return decision


def match_sfx_asset(
    *,
    sfx_family: str,
    hook_intent: str = "",
    recent_sfx_history: Optional[Sequence[str]] = None,
    assets: Optional[Dict[str, List[Path]]] = None,
    audio_inventory: Optional[Dict[str, Any]] = None,
    task_id: Optional[str] = None,
    audio_editorial_profile: str = "",
    sfx_allowed_families: Optional[Sequence[str]] = None,
    sfx_blocked_families: Optional[Sequence[str]] = None,
    music_mood: str = "",
    audio_variation_index: int = 0,
) -> Dict[str, Any]:
    family = str(sfx_family or "no_sfx_needed")
    if family in {"no_sfx_needed", "silence_contrast"}:
        return {"matched": False, "asset": None, "low_variation": False, "reason": "no_asset_needed"}
    allowed_set = {str(item).strip().lower().replace(" ", "_") for item in (sfx_allowed_families or []) if str(item).strip()}
    blocked_set = {str(item).strip().lower().replace(" ", "_") for item in (sfx_blocked_families or []) if str(item).strip()}
    normalized_family = _normalize_text(family).replace(" ", "_")
    mapped_family = _SFX_FAMILY_ALIASES.get(normalized_family, normalized_family)
    if blocked_set and (normalized_family in blocked_set or mapped_family in blocked_set):
        logger.info("SFX_FAMILY_BLOCKED_BY_PROFILE family=%s profile=%s reason=profile_blocked", family, audio_editorial_profile or "unknown")
        return {
            "matched": False,
            "asset": None,
            "low_variation": False,
            "reason": "family_blocked_by_profile",
            "family": family,
            "sfx_family_selected": family,
            "sfx_selection_reason": "family_blocked_by_profile",
            "sfx_reuse_reason": "profile_blocked",
            "sfx_asset_taxonomy_used": "inventory" if audio_editorial_profile else "filename",
        }
    if allowed_set and normalized_family not in allowed_set and mapped_family not in allowed_set:
        logger.info("SFX_FAMILY_BLOCKED_BY_PROFILE family=%s profile=%s reason=family_not_allowed", family, audio_editorial_profile or "unknown")
        return {
            "matched": False,
            "asset": None,
            "low_variation": False,
            "reason": "family_not_allowed",
            "family": family,
            "sfx_family_selected": family,
            "sfx_selection_reason": "family_not_allowed",
            "sfx_reuse_reason": "profile_family_not_allowed",
            "sfx_asset_taxonomy_used": "inventory" if audio_editorial_profile else "filename",
        }
    if not _is_allowed_sfx_family(family):
        logger.info("[sfx-asset] family=%s matched=false asset= low_variation=false", family)
        logger.info("[sfx-asset] skipped reason=family_not_allowed family=%s", family)
        return {
            "matched": False,
            "asset": None,
            "low_variation": False,
            "reason": "family_not_allowed",
            "family": family,
            "sfx_family_selected": family,
            "sfx_selection_reason": "family_not_allowed",
            "sfx_reuse_reason": "family_not_allowed",
            "sfx_asset_taxonomy_used": "inventory" if audio_editorial_profile else "filename",
        }

    try:
        from .vpi_asset_library_service import build_asset_index
        _asset_index = build_asset_index()
    except Exception as exc:
        logger.debug("[sfx-asset] asset_library_unavailable reason=%s", exc)
        _asset_index = {}
    _manifest_found = bool(_asset_index.get("manifest_found"))
    _verified_sfx = list((_asset_index.get("verified") or {}).get("sfx") or [])
    inventory_sfx_assets = list((audio_inventory or {}).get("sfx_assets") or [])

    assets = assets or discover_sfx_assets()
    candidate_keys = _SFX_FAMILY_TO_ASSET_KEYS.get(family, tuple())
    candidates: List[Path] = []
    for key in candidate_keys:
        candidates.extend(list(assets.get(key) or []))
    deduped: List[Path] = []
    seen: set[str] = set()
    for item in candidates:
        key = str(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    candidates = deduped
    candidates = [asset for asset in candidates if not _is_blocked_sfx_text(asset.stem)]
    if not candidates and inventory_sfx_assets:
        fallback_order = _sfx_family_fallback_order(family)
        inventory_candidates: List[Path] = []
        for item in inventory_sfx_assets:
            asset_path = str(item.get("asset_path") or item.get("path") or "")
            if not asset_path:
                continue
            item_family = str(item.get("family") or _infer_sfx_family_from_path(Path(asset_path)))
            if item_family in fallback_order and not _is_blocked_sfx_text(Path(asset_path).stem):
                inventory_candidates.append(Path(asset_path))
        if inventory_candidates:
            candidates = inventory_candidates
            logger.warning(
                "SFX_FAMILY_ASSET_MISSING family=%s reason=inventory_fallback selected=%s",
                family,
                "|".join(fallback_order),
            )
    if not candidates:
        logger.info("[sfx-asset] family=%s matched=false asset= low_variation=false", family)
        logger.info("[sfx-asset] skipped reason=no_local_asset")
        return {
            "matched": False,
            "asset": None,
            "low_variation": False,
            "reason": "no_local_asset",
            "family": family,
            "sfx_family_selected": family,
            "sfx_selection_reason": "no_local_asset",
            "sfx_reuse_reason": "no_local_asset",
            "sfx_asset_taxonomy_used": "inventory" if inventory_sfx_assets else "filename",
        }

    verified_by_path: Dict[str, Dict[str, Any]] = {
        str(item.get("path") or ""): item for item in _verified_sfx if isinstance(item, dict)
    }
    # FIX 4: When manifest not found, allow unverified local assets.
    # Only require verified candidates when manifest exists AND has verified entries.
    if _manifest_found:
        verified_candidates = [asset for asset in candidates if str(asset) in verified_by_path]
        if verified_candidates:
            candidates = verified_candidates
        else:
            # Manifest exists but no verified SFX — still allow unverified local assets
            # so local SFX can be used without a manifest.
            logger.info("[sfx-asset] manifest_found=true but no verified sfx; falling back to unverified local assets")
            logger.info("[sfx-asset] family=%s matched=fallback candidates=%d", family, len(candidates))
    else:
        # No manifest — all discovered local assets are usable.
        logger.info("[sfx-asset] manifest_found=false; using unverified local assets for family=%s", family)

    history = [str(item) for item in (recent_sfx_history or []) if str(item).strip()]
    if task_id:
        history.extend(_read_sfx_rotation_history(task_id))
    previous = history[-1] if history else ""
    selected = next((asset for asset in candidates if str(asset) != previous), candidates[0])
    low_variation = len(candidates) <= 1
    _entry = verified_by_path.get(str(selected), {})
    _verified = bool(_entry)
    _source = str((_entry or {}).get("source_name") or ("unverified_local" if not _manifest_found else ""))
    _license = str((_entry or {}).get("license_name") or "")
    _commercial_use_ok = bool((_entry or {}).get("commercial_use_ok"))
    _attribution_required = bool((_entry or {}).get("attribution_required"))
    if _verified and not _commercial_use_ok:
        logger.info("[sfx-asset] skipped reason=commercial_use_not_ok")
        return {
            "matched": False,
            "asset": None,
            "low_variation": False,
            "reason": "commercial_use_not_ok",
            "verified": False,
            "sfx_asset_verified": False,
            "sfx_asset_source": _source,
            "sfx_asset_license": _license,
            "sfx_attribution_needed": _attribution_required,
            "sfx_asset_taxonomy_used": "inventory" if inventory_sfx_assets else "filename",
        }
    if _verified and not _license:
        logger.info("[sfx-asset] skipped reason=license_missing")
        return {
            "matched": False,
            "asset": None,
            "low_variation": False,
            "reason": "license_missing",
            "verified": False,
            "sfx_asset_verified": False,
            "sfx_asset_source": _source,
            "sfx_asset_license": "",
            "sfx_attribution_needed": _attribution_required,
            "sfx_asset_taxonomy_used": "inventory" if inventory_sfx_assets else "filename",
        }
    # NOTE: The stale `if _manifest_found and not _verified:` block was removed here.
    # With FIX 4, unverified local assets are now allowed when manifest not found,
    # and the earlier logic already handles the verified/unverified distinction.
    logger.info("[sfx-asset] rotation selected=%s previous=%s", selected, previous or "none")
    logger.info(
        "[sfx-asset] family=%s matched=true asset=%s low_variation=%s",
        family,
        selected,
        str(low_variation).lower(),
    )
    logger.info("[sfx-asset] verified=%s source=%s license=%s", str(_verified).lower(), _source or "unverified_local", _license or "none")
    _append_sfx_rotation_history(task_id, str(selected))
    return {
        "matched": True,
        "asset": str(selected),
        "asset_path": selected,
        "low_variation": low_variation,
        "reason": "local_asset_match",
        "family": family,
        "verified": _verified,
        "sfx_asset_verified": _verified,
        "sfx_asset_source": _source or "unverified_local",
        "sfx_asset_license": _license,
        "sfx_attribution_needed": _attribution_required,
        "sfx_asset_commercial_use_ok": bool(_commercial_use_ok if _verified else False),
        "sfx_family_selected": family,
        "sfx_selection_reason": "local_asset_match",
        "sfx_reuse_reason": "recently_used_reuse" if str(previous or "") == str(selected or "") else "",
        "sfx_variation_id": Path(str(selected)).stem if str(selected) else "",
        "sfx_asset_taxonomy_used": "inventory" if inventory_sfx_assets else ("inventory" if _manifest_found else "filename"),
    }


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


def sync_sfx_with_motion(
    intent: str,
    visual_profile: str,
    *,
    transition_type: str = "",
    assets: Optional[Dict[str, List[Path]]] = None,
    low_value_moment: bool = False,
    composition_mode: str = "",
) -> Dict[str, Any]:
    resolved_intent = str(intent or "neutral_explanation")
    profile = str(visual_profile or "")
    transition = str(transition_type or "")
    comp_mode = str(composition_mode or "")
    assets = assets or {"low_riser": [], "high_riser": [], "magic_whoosh": [], "deep_boom": []}

    if low_value_moment:
        logger.info(
            "[sfx-motion-sync] intent=%s visual_profile=%s sfx=none applied=false reason=low_value_moment",
            resolved_intent,
            profile,
        )
        return {
            "sfx_motion_sync_applied": False,
            "sfx_motion_sync_type": "",
            "sfx_motion_sync_reason": "low_value_moment",
            "aggressive_impact_allowed": False,
        }

    sfx_type = ""
    asset_key = ""
    aggressive_allowed = False
    reason = "no_motion_sfx_needed"
    if transition in {"sweeping_reveal", "sweeping_object_reveal"}:
        sfx_type = "magic_whoosh"
        asset_key = "magic_whoosh"
        reason = "sweeping_reveal"
    elif resolved_intent == "risk_warning" and profile == "tension_push":
        sfx_type = "dark_riser"
        asset_key = "low_riser"
        reason = "risk_warning_tension_push"
    elif resolved_intent == "autonomous_business_stakes" and profile == "business_punch":
        sfx_type = "deep_boom"
        asset_key = "deep_boom"
        aggressive_allowed = True
        reason = "business_punch_soft_impact"
    elif resolved_intent == "emotional_closure":
        reason = "emotional_no_aggressive_impact"
    if comp_mode == "emotional_soft" and sfx_type == "deep_boom":
        sfx_type = ""
        asset_key = ""
        aggressive_allowed = False
        reason = "composition_blocked_deep_boom"
    if comp_mode == "minimal_safe" and sfx_type and resolved_intent == "neutral_explanation":
        sfx_type = ""
        asset_key = ""
        aggressive_allowed = False
        reason = "composition_blocked_minimal_safe"

    available = bool(asset_key and assets.get(asset_key))
    applied = bool(sfx_type and available)
    logger.info(
        "[sfx-motion-sync] intent=%s visual_profile=%s sfx=%s applied=%s reason=%s",
        resolved_intent,
        profile,
        sfx_type or "none",
        str(applied).lower(),
        reason,
    )
    logger.info("[sfx-motion-sync] composition_mode=%s applied=%s reason=%s", comp_mode or "none", str(applied).lower(), reason)
    return {
        "sfx_motion_sync_applied": applied,
        "sfx_motion_sync_type": sfx_type,
        "sfx_motion_sync_asset_type": asset_key,
        "sfx_motion_sync_reason": reason,
        "aggressive_impact_allowed": aggressive_allowed,
        "sfx_motion_sync_available": available,
        "composition_decision_applied": bool(comp_mode),
    }


def build_sfx_design_plan(
    *,
    hook_plan: Optional[Dict[str, Any]] = None,
    broll_events: Optional[List[Dict[str, Any]]] = None,
    transition_events: Optional[List[Dict[str, Any]]] = None,
    editorial_type: str = "",
    segment_text: str = "",
    audio_editorial_profile: str = "",
    sfx_allowed_families: Optional[List[str]] = None,
    sfx_blocked_families: Optional[List[str]] = None,
    max_sfx_events: int = 3,
    recent_sfx_family_history: Optional[Sequence[str]] = None,
    audio_variation_index: int = 0,
    audio_inventory: Optional[Dict[str, Any]] = None,
    clip_duration_s: float = 0.0,
    task_id: Optional[str] = None,
    assets: Optional[Dict[str, List[Path]]] = None,
    used_deep_boom_assets: Optional[Iterable[str]] = None,
    composition_decision: Optional[Dict[str, Any]] = None,
    broll_editorial_decision: Optional[Dict[str, Any]] = None,
    private_premium_status: str = "",
    first3_visual_contract: Optional[Dict[str, Any]] = None,
    silence_plan: Optional[Dict[str, Any]] = None,
    clip_order: int = 0,
) -> Dict[str, Any]:
    assets = assets or discover_sfx_assets()
    events: List[Dict[str, Any]] = []
    missing: List[str] = []

    decision = build_sfx_retention_decision(
        hook_intent=str((hook_plan or {}).get("hook_intent") or editorial_type or "neutral_explanation"),
        visual_profile=str((hook_plan or {}).get("visual_profile") or (hook_plan or {}).get("motion_pack_profile") or ""),
        composition_mode=str((composition_decision or {}).get("composition_mode") or ""),
        broll_editorial_decision=broll_editorial_decision or {},
        segment_text=segment_text,
        private_premium_status=str(private_premium_status or ""),
        first3_visual_contract=first3_visual_contract or {},
    )
    logger.info(
        "SFX_EDITORIAL_PROFILE_SELECTED profile=%s family=%s allowed=%s blocked=%s max_events=%d",
        audio_editorial_profile or "unknown",
        str(decision.get("sfx_family") or "none"),
        "|".join(sfx_allowed_families or []) or "none",
        "|".join(sfx_blocked_families or []) or "none",
        int(max_sfx_events or 0),
    )
    motion_sync = sync_sfx_with_motion(
        str((hook_plan or {}).get("hook_intent") or editorial_type or "neutral_explanation"),
        str((hook_plan or {}).get("visual_profile") or (hook_plan or {}).get("motion_pack_profile") or ""),
        transition_type=str(((transition_events or [{}])[0] or {}).get("transition_type") or ""),
        assets=assets,
        low_value_moment=False,
        composition_mode=str((composition_decision or {}).get("composition_mode") or ""),
    )

    comp_mode = str((composition_decision or {}).get("composition_mode") or "")
    voice_conflict = bool(decision.get("voice_conflict"))
    retention_pack = False
    opportunity = bool(decision.get("sfx_family") not in {"no_sfx_needed"} and not decision.get("should_apply_sfx"))

    normalized_allowed = [str(item).strip().lower().replace(" ", "_") for item in (sfx_allowed_families or []) if str(item).strip()]
    normalized_blocked = {str(item).strip().lower().replace(" ", "_") for item in (sfx_blocked_families or []) if str(item).strip()}
    recent_family_history = [str(item).strip().lower().replace(" ", "_") for item in (recent_sfx_family_history or []) if str(item).strip()]
    requested_family = str(decision.get("sfx_family") or "").strip()
    requested_family_norm = _normalize_text(requested_family).replace(" ", "_")
    requested_family_mapped = _SFX_FAMILY_ALIASES.get(requested_family_norm, requested_family_norm)
    family_streak = len(recent_family_history) >= 2 and recent_family_history[-1] == recent_family_history[-2] == requested_family_norm
    family_blocked = bool(
        (normalized_allowed and requested_family_norm not in normalized_allowed and requested_family_mapped not in normalized_allowed)
        or requested_family_norm in normalized_blocked
        or requested_family_mapped in normalized_blocked
    )
    if (family_blocked or family_streak) and normalized_allowed:
        candidates = [
            item
            for item in normalized_allowed
            if item not in normalized_blocked and item not in {"no_sfx_needed", "silence_contrast"}
        ]
        if family_streak:
            alternatives = [item for item in candidates if item != requested_family_norm]
            if alternatives:
                candidates = alternatives
        if candidates:
            rotated_family = candidates[int(audio_variation_index or 0) % len(candidates)]
            if rotated_family and rotated_family != requested_family_norm:
                logger.info(
                    "SFX_FAMILY_SELECTED family=%s profile=%s reason=editorial_profile_rotation",
                    rotated_family,
                    audio_editorial_profile or "unknown",
                )
                decision = dict(decision)
                decision["sfx_family"] = rotated_family
                decision["sfx_intent"] = f"{decision.get('sfx_intent') or ''}|profile_rotation".strip("|")
                decision["reason"] = "editorial_profile_rotation"
                requested_family = rotated_family
                requested_family_norm = rotated_family
                requested_family_mapped = _SFX_FAMILY_ALIASES.get(requested_family_norm, requested_family_norm)

    if decision.get("sfx_family") == "silence_contrast":
        # Silence contrast is a real retention action but not an audio asset.
        summary = (silence_plan or {}).get("summary") or {}
        retention_moments = [
            dict(moment)
            for moment in summary.get("silence_retention_moments") or []
            if _is_safe_silence_reason(str((moment or {}).get("reason") or ""))
        ]
        preserved = bool(
            summary.get("tension_silences_preserved")
            or summary.get("preserved_emphasis_pauses")
            or retention_moments
        )
        if preserved:
            logger.info("[silence-retention] preserved=true reason=emotional_closure")
            logger.info("[silence-retention] contrast_window=emotional_pause duration=%.2f", float(decision.get("duration") or 0.28))
            retention_pack = True
        else:
            logger.info("[silence-retention] skipped reason=no_safe_gap")
            opportunity = True

    match: Dict[str, Any] = {"matched": False, "asset": None, "low_variation": False, "reason": "not_requested"}
    composition_allowed = True
    composition_reason = "no_sfx_needed"
    layer_type = ""
    hook_type = str((hook_plan or {}).get("hook_type") or "")
    hook_visible = bool(hook_type and hook_type != "weak_intro")
    hook_overlay_active = bool((hook_plan or {}).get("overlay_rendered") or (hook_plan or {}).get("kickframe_applied"))
    if decision.get("should_apply_sfx"):
        match = match_sfx_asset(
            sfx_family=str(decision.get("sfx_family") or ""),
            hook_intent=str((hook_plan or {}).get("hook_intent") or editorial_type or ""),
            recent_sfx_history=[str(item) for item in used_deep_boom_assets or []],
            assets=assets,
            audio_inventory=audio_inventory,
            task_id=task_id,
            audio_editorial_profile=audio_editorial_profile,
            sfx_allowed_families=sfx_allowed_families,
            sfx_blocked_families=sfx_blocked_families,
            music_mood=str((hook_plan or {}).get("music_mood") or ""),
            audio_variation_index=audio_variation_index,
        )
        if not match.get("matched"):
            missing.append(str(decision.get("sfx_family") or "unknown"))
            logger.info("[sfx-retention] skipped reason=no_asset")
            opportunity = True
        else:
            try:
                from .vpi_visual_effects_service import resolve_visual_layer_conflicts

                family = str(decision.get("sfx_family") or "")
                layer_type = "sfx_chime"
                if family in {"dark_riser", "tension_riser", "high_riser"}:
                    layer_type = "sfx_riser"
                elif family == "magic_whoosh":
                    layer_type = "sfx_whoosh"
                elif family == "deep_boom":
                    layer_type = "sfx_hit"
                layers = [{"type": layer_type, "start_s": 0.35, "duration_s": float(decision.get("duration") or 0.45)}]
                if bool((hook_plan or {}).get("overlay_rendered")):
                    layers.insert(0, {"type": "hook_overlay", "start_s": 0.0, "duration_s": 1.1})
                resolved = resolve_visual_layer_conflicts(layers, composition_decision or {})
                composition_allowed = layer_type in list(resolved.get("layers_final") or [])
                composition_reason = "allowed" if composition_allowed else "composition_block"
                logger.info("[sfx-qc] composition_allowed=%s reason=%s", str(composition_allowed).lower(), composition_reason)
            except Exception as exc:
                logger.debug("[sfx-qc] composition_check_skipped reason=%s", exc)

            family = str(decision.get("sfx_family") or "")
            timing_offset = float(decision.get("timing_offset") or 0.0)
            main_start = 0.35
            if transition_events:
                main_start = max(0.0, float((transition_events[0] or {}).get("start_s") or (transition_events[0] or {}).get("start_time") or 0.5) + timing_offset)
            elif broll_events:
                main_start = max(0.0, float((broll_events[0] or {}).get("start_s") or 1.8) + timing_offset)
            else:
                main_start = max(0.0, 0.35 + timing_offset)

            def _append_editorial_event(
                *,
                family_name: str,
                moment: str,
                timestamp_s: float,
                duration_s: float,
                asset_path: Optional[str],
                volume_db: float,
                ducking: bool,
                reason: str,
                start_floor: float = 0.0,
            ) -> None:
                if len(events) >= 3:
                    return
                if not _is_allowed_sfx_family(family_name):
                    logger.info(
                        "EDITORIAL_SFX_SKIPPED_REASON task_id=%s clip_order=%s reason=family_not_allowed family=%s",
                        task_id or "",
                        clip_order,
                        family_name,
                    )
                    return
                if not asset_path:
                    logger.info(
                        "EDITORIAL_SFX_SKIPPED_REASON task_id=%s clip_order=%s family=%s reason=missing_asset",
                        task_id or "",
                        clip_order,
                        family_name,
                    )
                    return
                actual_start = max(start_floor, timestamp_s)
                events.append({
                    "event": "retention_moment",
                    "type": family_name,
                    "contextual": True,
                    "start_s": round(actual_start, 2),
                    "duration_s": round(float(duration_s), 2),
                    "volume": round(max(0.08, min(0.35, 10 ** (float(volume_db) / 20.0))), 3),
                    "volume_db": float(volume_db),
                    "ducking": bool(ducking),
                    "asset": str(asset_path or ""),
                    "reason": reason,
                    "sfx_family": family_name,
                    "moment": moment,
                })
                logger.info(
                    "EDITORIAL_SFX_APPLIED task_id=%s clip_order=%s family=%s moment=%s timestamp=%.2f",
                    task_id or "",
                    clip_order,
                    family_name,
                    moment,
                    actual_start,
                )

            hook_family = "magic_whoosh"
            hook_asset = ""
            hook_reason = "hook_entry"
            if hook_visible and not voice_conflict and hook_type not in {"", "weak_intro", "explanation_hook"}:
                hook_asset_match = match_sfx_asset(
                    sfx_family="magic_whoosh",
                    hook_intent=str((hook_plan or {}).get("hook_intent") or editorial_type or ""),
                    recent_sfx_history=[str(item) for item in used_deep_boom_assets or []],
                    assets=assets,
                    audio_inventory=audio_inventory,
                    task_id=task_id,
                )
                hook_asset = str(hook_asset_match.get("asset") or "")
                hook_start = 0.25 if not hook_overlay_active else 0.30
                _append_editorial_event(
                    family_name=hook_family,
                    moment="hook_entry",
                    timestamp_s=hook_start,
                    duration_s=0.35,
                    asset_path=hook_asset,
                    volume_db=-28.0,
                    ducking=False,
                    reason="hook_entry",
                    start_floor=0.20,
                )

            if composition_allowed and not voice_conflict:
                if family in {"dark_riser", "tension_riser", "high_riser", "deep_boom"}:
                    impact_asset = str(match.get("asset") or "")
                    _append_editorial_event(
                        family_name=family,
                        moment="warning_or_revelation",
                        timestamp_s=main_start,
                        duration_s=float(decision.get("duration") or 0.45),
                        asset_path=impact_asset,
                        volume_db=float(decision.get("volume_db") or -25.0),
                        ducking=bool(family in {"deep_boom", "dark_riser"}),
                        reason=str(decision.get("reason") or "retention"),
                        start_floor=0.30,
                    )
                elif family == "magic_whoosh" and not any(ev.get("moment") == "hook_entry" for ev in events):
                    impact_asset = str(match.get("asset") or "")
                    _append_editorial_event(
                        family_name=family,
                        moment="warning_or_revelation",
                        timestamp_s=main_start,
                        duration_s=float(decision.get("duration") or 0.45),
                        asset_path=impact_asset,
                        volume_db=float(decision.get("volume_db") or -25.0),
                        ducking=False,
                        reason=str(decision.get("reason") or "retention"),
                        start_floor=0.30,
                    )

            if clip_duration_s >= 12.0 and len(events) < 3 and transition_events:
                riser_asset = ""
                riser_match = match_sfx_asset(
                    sfx_family="dark_riser",
                    hook_intent=str((hook_plan or {}).get("hook_intent") or editorial_type or ""),
                    recent_sfx_history=[str(item) for item in used_deep_boom_assets or []],
                    assets=assets,
                    audio_inventory=audio_inventory,
                    task_id=task_id,
                )
                riser_asset = str(riser_match.get("asset") or "")
                if riser_asset:
                    riser_start = max(0.30, float((transition_events[0] or {}).get("start_s") or 0.5) + 0.05)
                    _append_editorial_event(
                        family_name="dark_riser",
                        moment="strong_turn",
                        timestamp_s=riser_start,
                        duration_s=0.45,
                        asset_path=riser_asset,
                        volume_db=-26.0,
                        ducking=True,
                        reason="strong_turn",
                        start_floor=0.30,
                    )

            if not events:
                if retention_pack:
                    logger.info(
                        "EDITORIAL_SFX_SKIPPED_REASON task_id=%s clip_order=%s reason=silence_preserved",
                        task_id or "",
                        clip_order,
                    )
                elif not composition_allowed:
                    logger.info(
                        "EDITORIAL_SFX_SKIPPED_REASON task_id=%s clip_order=%s reason=composition_block",
                        task_id or "",
                        clip_order,
                    )
                elif voice_conflict:
                    logger.info(
                        "EDITORIAL_SFX_SKIPPED_REASON task_id=%s clip_order=%s reason=voice_conflict",
                        task_id or "",
                        clip_order,
                    )
                else:
                    logger.info(
                        "EDITORIAL_SFX_SKIPPED_REASON task_id=%s clip_order=%s reason=no_editorial_moment",
                        task_id or "",
                        clip_order,
                    )
            retention_pack = bool(events) or retention_pack

    if missing:
        logger.info("[sfx-design] skipped reason=missing_asset_type types=%s", "|".join(sorted(set(missing))))
    # ── SFX Budget: cap at max_sfx_events_per_clip=3 ──────────────────────────
    max_sfx_events = int(max_sfx_events or 3)
    requested_count = len(events)
    if requested_count > max_sfx_events:
        # Keep strongest editorial moments (first events by priority)
        events = events[:max_sfx_events]
    logger.info(
        "EDITORIAL_SFX_BUDGET_APPLIED task_id=%s clip_order=%s count=%d",
        task_id or "",
        clip_order,
        len(events),
    )

    logger.info("[sfx-qc] contextual=%s reason=%s", str(bool(events)).lower(), "hook_or_editorial_moment" if events else "no_contextual_sfx_event")
    selected_variation_ids = list(
        dict.fromkeys(
            str((event or {}).get("asset") or (event or {}).get("sfx_family") or "")
            for event in events
            if str((event or {}).get("asset") or (event or {}).get("sfx_family") or "")
        )
    )
    if events:
        logger.info(
            "SFX_FAMILY_SELECTED family=%s profile=%s reason=%s",
            str(decision.get("sfx_family") or ""),
            audio_editorial_profile or "unknown",
            str(decision.get("reason") or "editorial_retention"),
        )
        logger.info(
            "SFX_VARIATION_SELECTED ids=%s",
            "|".join(selected_variation_ids) or "none",
        )
    return {
        "sfx_design_applied": bool(events),
        "sfx_design_events": events,
        "sfx_design_missing_assets": sorted(set(missing)),
        "sfx_assets_available": {
            "low_risers": len(assets.get("low_riser") or []),
            "high_risers": len(assets.get("high_riser") or []),
            "whooshes": len(assets.get("magic_whoosh") or []),
            "booms": len(assets.get("deep_boom") or []),
        },
        "sfx_repetition_guard": {"task_id": task_id, "deep_boom_guarded": any((item or {}).get("type") == "deep_boom" for item in events)},
        "sfx_contextual": bool(events),
        "sfx_retention_decision": decision,
        "sfx_asset_match": match,
        "sfx_editorial_opportunity": bool(opportunity),
        "sfx_low_variation": bool(match.get("low_variation")),
        "sfx_timing_safe": bool(bool(events) and not voice_conflict),
        "sfx_composition_allowed": bool(composition_allowed),
        "sfx_composition_reason": composition_reason,
        "sfx_retention_pack": bool(retention_pack),
        "composition_mode": comp_mode,
        "sfx_editorial_profile": audio_editorial_profile or "unknown",
        "sfx_allowed_families": list(sfx_allowed_families or []),
        "sfx_blocked_families": list(sfx_blocked_families or []),
        "sfx_family_selected": str(decision.get("sfx_family") or ""),
        "sfx_variation_ids": selected_variation_ids,
        "sfx_selection_reason": str(decision.get("reason") or ""),
        "sfx_reuse_reason": str(match.get("sfx_reuse_reason") or match.get("reason") or ""),
        "sfx_asset_taxonomy_used": str(match.get("sfx_asset_taxonomy_used") or ("inventory" if audio_inventory else "filename")),
        **motion_sync,
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

    # Resolve all SFX files from local assets only (no synthetic fallback).
    sfx_inputs: List[tuple[Dict[str, Any], Path, float]] = []
    for event in sfx_events:
        sfx_type = str(event.get("type", "magic_whoosh"))
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
        logger.info("[sfx-mix] skipped event=%s reason=no_local_asset", sfx_type)

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


def _verify_sfx_audio_mix(input_video: Path, output_video: Path) -> bool:
    """Verify that an output file contains a real mixed audio stream."""
    try:
        if not output_video.exists() or output_video.stat().st_size <= 0:
            return False
        if not input_video.exists():
            return False

        probe_cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_type,duration",
            "-of",
            "json",
            str(output_video),
        ]
        probe = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=20)
        if probe.returncode != 0:
            return False
        data = json.loads(probe.stdout or "{}")
        streams = list(data.get("streams") or [])
        if not streams:
            return False
        duration = 0.0
        try:
            duration = float(streams[0].get("duration") or 0.0)
        except Exception:
            duration = 0.0
        if duration <= 0.5:
            return False

        vol_cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(output_video),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ]
        vol = subprocess.run(vol_cmd, capture_output=True, text=True, timeout=30)
        if vol.returncode != 0:
            return False
        stderr = vol.stderr or ""
        if "mean_volume" not in stderr and "max_volume" not in stderr:
            return False
        return True
    except Exception as exc:
        logger.debug("[sfx-verify] failed reason=%s", exc)
        return False


def apply_sfx_bed(
    input_path: Path,
    output_path: Path,
    *,
    hook_plan: Optional[Dict[str, Any]] = None,
    broll_events: Optional[List[Dict[str, Any]]] = None,
    transition_events: Optional[List[Dict[str, Any]]] = None,
    editorial_type: str = "",
    segment_text: str = "",
    task_id: Optional[str] = None,
    composition_decision: Optional[Dict[str, Any]] = None,
    broll_editorial_decision: Optional[Dict[str, Any]] = None,
    private_premium_status: str = "",
    first3_visual_contract: Optional[Dict[str, Any]] = None,
    silence_plan: Optional[Dict[str, Any]] = None,
    clip_order: int = 0,
    segment_words: Optional[List[Dict[str, Any]]] = None,
    audio_editorial_profile: str = "",
    sfx_allowed_families: Optional[List[str]] = None,
    sfx_blocked_families: Optional[List[str]] = None,
    max_sfx_events: int = 3,
    recent_sfx_family_history: Optional[Sequence[str]] = None,
    audio_variation_index: int = 0,
    audio_inventory: Optional[Dict[str, Any]] = None,
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
        segment_text=segment_text,
        task_id=task_id,
        composition_decision=composition_decision,
        broll_editorial_decision=broll_editorial_decision,
        private_premium_status=private_premium_status,
        first3_visual_contract=first3_visual_contract,
        silence_plan=silence_plan,
        clip_order=clip_order,
        audio_editorial_profile=audio_editorial_profile,
        sfx_allowed_families=sfx_allowed_families,
        sfx_blocked_families=sfx_blocked_families,
        max_sfx_events=max_sfx_events,
        recent_sfx_family_history=recent_sfx_family_history,
        audio_variation_index=audio_variation_index,
        audio_inventory=audio_inventory,
    )
    events = list(design.get("sfx_design_events") or [])
    word_events = [word for word in (segment_words or []) if isinstance(word, dict)]
    sfx_word_collision_avoided = False
    sfx_events_shifted = 0
    sfx_events_dropped_for_voice = 0
    if events and word_events:
        safe_events: List[Dict[str, Any]] = []

        def _word_start(word: Dict[str, Any]) -> float:
            for key in ("start_s", "start", "timestamp_s", "timestamp", "begin", "time_s"):
                try:
                    val = float(word.get(key))
                    if val >= 0:
                        return val
                except Exception:
                    continue
            return 0.0

        def _word_end(word: Dict[str, Any], start: float) -> float:
            for key in ("end_s", "end", "stop", "finish"):
                try:
                    val = float(word.get(key))
                    if val > start:
                        return val
                except Exception:
                    continue
            try:
                duration = float(word.get("duration_s") or word.get("duration") or 0.22)
            except Exception:
                duration = 0.22
            return start + max(0.12, duration)

        def _word_is_important(word: Dict[str, Any]) -> bool:
            text = str(word.get("text") or word.get("word") or "").strip()
            confidence = 0.0
            for key in ("confidence", "score", "probability"):
                try:
                    confidence = max(confidence, float(word.get(key) or 0.0))
                except Exception:
                    continue
            return bool(text) and (confidence >= 0.7 or len(text) >= 4)

        for event in events:
            try:
                event_start = float(event.get("start_s") or event.get("start") or 0.0)
            except Exception:
                event_start = 0.0
            try:
                event_duration = float(event.get("duration_s") or event.get("duration") or 0.35)
            except Exception:
                event_duration = 0.35
            adjusted_event = dict(event)
            collided = False
            for word in word_events:
                if not _word_is_important(word):
                    continue
                word_start = _word_start(word)
                word_end = _word_end(word, word_start)
                window_start = event_start - 0.10
                window_end = event_start + event_duration + 0.10
                if word_start <= window_end and word_end >= window_start:
                    collided = True
                    break
            if collided:
                shifted = False
                for offset in (0.15, -0.15):
                    candidate_start = max(0.0, event_start + offset)
                    candidate_end = candidate_start + event_duration
                    if any(
                        (_word_start(word) <= candidate_end + 0.05 and _word_end(word, _word_start(word)) >= candidate_start - 0.05)
                        for word in word_events
                        if _word_is_important(word)
                    ):
                        continue
                    adjusted_event["start_s"] = round(candidate_start, 2)
                    adjusted_event["timestamp_s"] = round(candidate_start, 2)
                    safe_events.append(adjusted_event)
                    sfx_word_collision_avoided = True
                    sfx_events_shifted += 1
                    logger.info(
                        "SFX_WORD_COLLISION_AVOIDED event=%s old_start=%.2f new_start=%.2f",
                        str(event.get("type") or "sfx"),
                        event_start,
                        candidate_start,
                    )
                    shifted = True
                    break
                if not shifted:
                    sfx_word_collision_avoided = True
                    sfx_events_dropped_for_voice += 1
                    logger.warning(
                        "SFX_DROPPED_FOR_VOICE_CLARITY event=%s start=%.2f",
                        str(event.get("type") or "sfx"),
                        event_start,
                    )
                    continue
            else:
                safe_events.append(adjusted_event)
        events = safe_events
    if not events:
        warning = str(
            design.get("sfx_warning")
            or ("sfx_missing_worker_assets" if design.get("sfx_design_missing_assets") else "no_sfx_moment")
        )
        if bool(design.get("sfx_retention_pack")):
            warning = ""
        logger.info("SFX_DISABLED_REASON task_id=%s clip_order=%s reason=%s", task_id or "", clip_order, warning or "no_sfx_moment")
        return {
            "sfx_applied": False,
            "sfx_count": 0,
            "sfx_event_count": 0,
            "sfx_verified": False,
            "sfx_families": [],
            "sfx_warning": warning or None,
            "sfx_asset_applied_match": False,
            "sfx_voice_clarity_ok": True,
            "sfx_word_collision_avoided": False,
            "sfx_events_shifted": 0,
            "sfx_events_dropped_for_voice": 0,
            **design,
        }
    # The mixer now accepts only real local assets. No synthetic fallback.
    with tempfile.TemporaryDirectory(prefix="viraclip_sfx_") as tmp_dir:
        result = mix_sfx_into_audio(
            input_path,
            output_path,
            events,
            Path(tmp_dir),
        )
    applied = bool(result.get("rendered"))
    verified = bool(applied and _verify_sfx_audio_mix(input_path, output_path))
    event_assets = [str((event or {}).get("asset") or "") for event in events if str((event or {}).get("asset") or "").strip()]
    # Mixer only ingests local files from event assets, so rendered=true implies match.
    asset_applied_match = bool(verified and event_assets)
    if verified:
        logger.info("SFX_AUDIO_MIX_VERIFIED task_id=%s clip_order=%s", task_id or "", clip_order)
    else:
        logger.info("SFX_DISABLED_REASON task_id=%s clip_order=%s reason=%s", task_id or "", clip_order, result.get("reason", "sfx_mix_failed"))
    logger.info("[sfx-design] final_output_uses_sfx=%s", str(bool(verified and asset_applied_match)).lower())
    return {
        "sfx_applied": bool(verified and asset_applied_match),
        "sfx_count": len(events) if (verified and asset_applied_match) else 0,
        "sfx_event_count": len(events) if (verified and asset_applied_match) else 0,
        "sfx_events": events,
        "sfx_warning": None if (verified and asset_applied_match) else result.get("reason", "sfx_mix_failed"),
        "sfx_asset_applied_match": asset_applied_match,
        "sfx_verified": bool(verified and asset_applied_match),
        "sfx_families": sorted({str((event or {}).get("sfx_family") or (event or {}).get("type") or "") for event in events if str((event or {}).get("sfx_family") or (event or {}).get("type") or "")}),
        "sfx_voice_clarity_ok": bool(verified and asset_applied_match),
        "sfx_word_collision_avoided": bool(sfx_word_collision_avoided),
        "sfx_events_shifted": int(sfx_events_shifted),
        "sfx_events_dropped_for_voice": int(sfx_events_dropped_for_voice),
        **design,
        **result,
    }
