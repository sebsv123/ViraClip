"""
VPI Asset Library Service v1.1 — Local-first asset discovery with fallback taxonomy.

When no manifest is found, discovered files are classified by filename/path
heuristics so they can be used as verified local assets (not just unverified).
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
# In the Docker image the code is mounted at /app/src, so parents[3] resolves to
# "/" and every relative manifest path (assets/...) misses — zeroing out the whole
# local b-roll/icon/overlay library. Fall back to the first root that actually
# contains an assets/ directory.
if not (_REPO_ROOT / "assets").is_dir():
    for _root_candidate in (Path("/app"), Path(__file__).resolve().parents[2]):
        if (_root_candidate / "assets").is_dir():
            _REPO_ROOT = _root_candidate
            break

_ASSET_PATHS: Dict[str, Tuple[str, ...]] = {
    "broll": (
        "assets/broll",
        "backend/assets/broll",
        "/app/assets/broll",
    ),
    "sfx": (
        "assets/sounds/sfx",
        "backend/assets/sounds/sfx",
        "/app/assets/sounds/sfx",
    ),
    "bgm": (
        "assets/sounds/bgm",
        "backend/assets/sounds/bgm",
        "/app/assets/sounds/bgm",
    ),
    "icons": (
        "assets/icons",
        "backend/assets/icons",
        "/app/assets/icons",
    ),
    "fonts": (
        "assets/fonts",
        "backend/assets/fonts",
        "/app/assets/fonts",
    ),
    "motion_overlay": (
        "assets/overlays",
        "backend/assets/overlays",
        "/app/assets/overlays",
    ),
    "visual": (
        "assets/icons",
        "assets/overlays",
        "assets/brand",
        "backend/assets/icons",
        "backend/assets/overlays",
        "backend/assets/brand",
        "frontend/public",
        "/app/assets/icons",
        "/app/assets/overlays",
        "/app/assets/brand",
        "/app/frontend/public",
    ),
}

_MANIFEST_CANDIDATES: Tuple[str, ...] = (
    "/app/assets/vpi_asset_manifest.json",
    "assets/vpi_asset_manifest.json",
    "backend/assets/vpi_asset_manifest.json",
    "/app/assets/manifest.json",
    "assets/manifest.json",
    "backend/assets/manifest.json",
)

_TEMPLATE_CANDIDATES: Tuple[str, ...] = (
    "assets/vpi_asset_manifest.template.json",
    "backend/assets/vpi_asset_manifest.template.json",
    "/app/assets/vpi_asset_manifest.template.json",
)

_ASSET_EXTS: Dict[str, Tuple[str, ...]] = {
    "broll": (".mp4", ".mov", ".webm", ".m4v", ".jpg", ".jpeg", ".png", ".webp"),
    "sfx": (".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac"),
    "bgm": (".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac"),
    "icons": (".svg", ".png", ".webp"),
    "fonts": (".ttf", ".otf", ".woff", ".woff2"),
    "motion_overlay": (".mov", ".mp4", ".webm", ".png", ".apng", ".gif"),
    "visual": (".svg", ".png", ".webp", ".apng", ".gif", ".jpg", ".jpeg"),
}

_ASSET_TYPE_ALIASES: Dict[str, str] = {
    "icon": "icons",
    "icons": "icons",
    "font": "fonts",
    "fonts": "fonts",
    "broll": "broll",
    "sfx": "sfx",
    "bgm": "bgm",
    "overlay": "motion_overlay",
    "overlays": "motion_overlay",
    "motion_overlay": "motion_overlay",
    "motion_overlays": "motion_overlay",
    "visual": "visual",
    "visuals": "visual",
}

EDITORIAL_BROLL_INTENTS: Tuple[str, ...] = (
    "family_relief",
    "emotional_support",
    "health_access",
    "practical_explanation",
    "autonomous_work_stability",
    "risk_warning_context",
    "calm_lifestyle",
    "paperwork_support",
    "office_work",
    "medical_care",
    "family_home",
    "no_broll_needed",
)

EDITORIAL_SFX_FAMILIES: Tuple[str, ...] = (
    "dark_riser",
    "high_riser",
    "tension_riser",
    "magic_whoosh",
    "deep_boom",
    "soft_chime",
    "click_soft",
    "ambient_soft",
    "no_sfx_needed",
)

EDITORIAL_ICON_CONCEPTS: Tuple[str, ...] = (
    "family",
    "health",
    "shield",
    "heart",
    "warning",
    "briefcase",
    "document",
    "euro",
    "calendar",
    "phone",
    "support",
)

EDITORIAL_FONT_ROLES: Tuple[str, ...] = (
    "caption_primary",
    "caption_emphasis",
    "lower_third",
    "brand_title",
)

EDITORIAL_OVERLAY_CONCEPTS: Tuple[str, ...] = (
    "shield",
    "heart",
    "warning",
    "document",
    "checklist",
    "euro",
    "price_badge",
    "calendar",
    "timer",
    "phone",
    "message_bubble",
    "cta",
)

VISUAL_INTENT_TAXONOMY: Dict[str, Tuple[str, ...]] = {
    "protection": ("shield", "heart_shield", "family_home", "calm_check", "protect", "protection", "safe", "seguro"),
    "health": ("medical_cross", "health_card", "hospital", "doctor_safe", "health", "salud", "medical", "medico"),
    "risk_warning": ("warning_triangle", "alert_line", "risk_marker", "storm_cloud_risk", "warning", "alert", "risk", "aviso"),
    "coverage": ("document_policy", "coverage_umbrella", "contract", "checklist", "document", "coverage", "policy", "póliza", "poliza"),
    "money_saving": ("money_check", "coin", "receipt", "discount", "save", "ahorro", "euro", "money"),
    "myth_debunk": ("myth_break", "check_x", "revelation_spark", "debunk", "mito", "falso", "truth", "verific"),
    "objection": ("question", "answer", "advisor", "objection", "duda", "pregunta", "answer", "advisor"),
    "travel": ("suitcase", "plane", "travel_shield", "travel", "viaje", "avion", "plane", "bag"),
    "sensitive_sober": ("document", "soft_flower_abstract", "family_silhouette", "calm_check", "sober", "sobrio", "sensitive", "decesos", "funeral", "mourning"),
}

VISUAL_TYPE_HINTS: Dict[str, Tuple[str, ...]] = {
    "logo": ("logo", "brand", "identity", "marca"),
    "badge": ("badge", "sticker", "pill", "chip", "seal"),
    "callout": ("callout", "label", "arrow", "pointer", "card", "annotat"),
    "overlay": ("overlay", "motion", "frame", "panel", "banner"),
    "background": ("background", "bg", "texture", "pattern", "gradient"),
}

VISUAL_BLOCKED_TERMS: Tuple[str, ...] = (
    "3d",
    "experimental",
    "cartoon",
    "meme",
    "gaming",
    "neon",
    "glow",
    "aggressive_red",
    "blood",
    "gore",
    "morb",
    "pixel",
    "tiny",
    "external_logo",
    "unauthorized",
)

VISUAL_SENSITIVE_SAFETY_TERMS: Tuple[str, ...] = (
    "document",
    "family",
    "familia",
    "calm",
    "soft",
    "shield",
    "check",
    "heart",
    "policy",
)

# ── Fallback taxonomy from filename/path ──────────────────────────────────────

_BROLL_TAXONOMY_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "family_relief": ("family", "familia", "home", "hogar", "kids", "ninos", "children", "padres", "parents"),
    "emotional_support": ("support", "apoyo", "care", "cuidado", "help", "ayuda", "comfort", "consuelo"),
    "health_access": ("health", "salud", "medical", "medico", "doctor", "hospital", "clinic", "clinica"),
    "practical_explanation": ("explain", "explica", "tutorial", "guide", "guia", "howto", "office", "oficina"),
    "autonomous_work_stability": ("autonomo", "autonomous", "freelance", "business", "negocio", "work", "trabajo"),
    "risk_warning_context": ("risk", "riesgo", "warning", "aviso", "danger", "peligro", "alert", "alerta"),
    "calm_lifestyle": ("calm", "calma", "peace", "paz", "nature", "naturaleza", "relax", "relajacion"),
    "paperwork_support": ("paper", "papel", "document", "documento", "form", "formulario", "burocracia"),
    "office_work": ("office", "oficina", "desk", "escritorio", "computer", "computadora", "laptop"),
    "medical_care": ("medical", "medico", "nurse", "enfermera", "patient", "paciente", "medicine", "medicina"),
    "family_home": ("family", "familia", "home", "hogar", "house", "casa", "living", "salon"),
    # OUTPUT-BROLL-14: travel/student intake families
    "travel_assistance": ("travel", "viaje", "airport", "aeropuerto", "passport", "pasaporte", "boarding", "luggage", "equipaje", "maleta", "trip", "pasaje"),
    "student_abroad": ("student", "estudiante", "campus", "university", "universidad", "study", "estudios", "visa", "visado", "abroad", "extranjero", "estancia"),
}

_SFX_TAXONOMY_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "dark_riser": ("dark", "oscuro", "low", "bajo", "rumble", "retumbo", "riser", "tension_riser_short"),
    "dark_riser_short": ("dark", "oscuro", "low", "bajo", "rumble", "retumbo", "riser", "short"),
    "high_riser": ("high", "alto", "bright", "brillante", "rise", "subida", "tension", "tension"),
    "tension_riser": ("tension", "tension", "suspense", "suspenso", "drama", "riser"),
    "magic_whoosh": ("magic", "magia", "sparkle", "brillo", "whoosh", "shimmer", "destello", "glitch", "whoosh_fast"),
    "soft_whoosh": ("whoosh", "suave", "soft", "gentle"),
    "deep_boom": ("boom", "deep", "profundo", "hit", "golpe", "impact", "impacto", "sub", "bass", "punch"),
    "soft_impact": ("impact", "impacto", "hit", "golpe", "soft", "suave"),
    "deep_boom_light": ("boom", "deep", "profundo", "light", "soft", "sub", "bass"),
    "soft_chime": ("chime", "campana", "soft", "suave", "click", "tick", "notification", "notificacion", "ding"),
    "check_pop": ("check", "pop", "confirm", "confirmacion", "confirmation", "ding", "tick"),
    "myth_break": ("myth", "debunk", "break", "falso", "mito", "realidad"),
    "question_tap": ("question", "tap", "question_tap", "duda", "pregunta"),
    "warning_tap": ("warning", "tap", "alert", "alerta", "aviso"),
    "click_soft": ("click", "clic", "tap", "toque", "button", "boton", "ui"),
    "ambient_soft": ("ambient", "ambiente", "soft", "suave", "background", "fondo", "pad"),
}

_BGM_TAXONOMY_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "calm_trust": ("calm", "calma", "warm", "calido", "trust", "confianza", "family", "familia", "soft", "suave", "piano", "acoustic", "acustico"),
    "warm_trust": ("warm", "calido", "trust", "confianza", "family", "familia", "calm", "calma", "soft", "suave", "piano", "acoustic", "acustico"),
    "explanatory_clean": ("clean", "limpio", "corporate", "corporativo", "professional", "profesional", "minimal", "minimalista", "business", "negocio", "explain", "explicacion"),
    "clean_contrast": ("clean", "contrast", "contraste", "sharp", "clear", "contrastado"),
    "subtle_tension": ("subtle", "sutil", "tension", "tensión", "dark", "oscuro", "pulse", "pulso", "mystery", "misterio", "suspense"),
    "light_tension": ("light", "soft", "tension", "warning", "alert", "pulso"),
    "optimistic_clean": ("optimistic", "optimista", "bright", "positive", "clean", "upbeat", "energetic"),
    "sensitive_sober": ("sensitive", "sobrio", "sober", "mourning", "funeral", "decesos", "neutral"),
}

_CRITICAL_VPI_CATEGORIES: set[str] = {
    "risk_warning_context",
    "family_protection",
    "family_relief",
    "health_access",
    "paperwork_support",
    "documents_admin",
    "financial_planning",
    "practical_explanation",
    "autonomous_work_stability",
    "emotional_reassurance",
}

_AUDIO_EDITORIAL_PROFILE_RULES: Dict[str, Dict[str, Any]] = {
    "calm_trust": {
        "music_mood": "trust_warm",
        "music_energy": "low_warm",
        "sfx_allowed_families": ["soft_chime", "soft_whoosh"],
        "sfx_blocked_families": ["deep_boom", "dark_riser_short", "high_riser", "tension_riser"],
        "max_sfx_events": 1,
        "keywords": ("calma", "confianza", "tranquilidad", "proteccion", "protección", "familia", "peace", "trust", "support"),
        "reason": "calm_trust_alignment",
    },
    "emotional_protection": {
        "music_mood": "trust_warm",
        "music_energy": "low_warm",
        "sfx_allowed_families": ["soft_chime", "soft_whoosh"],
        "sfx_blocked_families": ["deep_boom", "dark_riser_short", "high_riser", "tension_riser"],
        "max_sfx_events": 1,
        "keywords": ("familia", "proteccion", "protección", "cuidar", "apoyo", "tranquilidad", "home", "support", "care"),
        "reason": "emotional_protection_alignment",
    },
    "risk_warning": {
        "music_mood": "subtle_tension",
        "music_energy": "medium_tension",
        "sfx_allowed_families": ["dark_riser_short", "soft_impact", "deep_boom_light"],
        "sfx_blocked_families": ["soft_chime", "question_tap"],
        "max_sfx_events": 2,
        "keywords": ("riesgo", "cuidado", "advertencia", "accidente", "warning", "alerta", "danger", "imprevisto"),
        "reason": "risk_warning_alignment",
    },
    "explanatory_clean": {
        "music_mood": "clean_corporate",
        "music_energy": "low_clean",
        "sfx_allowed_families": ["soft_whoosh", "subtle_tick_off"],
        "sfx_blocked_families": ["deep_boom", "dark_riser_short", "high_riser"],
        "max_sfx_events": 1,
        "keywords": ("explicacion", "explicación", "póliza", "poliza", "cobertura", "coverage", "documento", "proceso", "guide"),
        "reason": "explanatory_clean_alignment",
    },
    "myth_debunk": {
        "music_mood": "clean_corporate",
        "music_energy": "medium_clean",
        "sfx_allowed_families": ["soft_hit", "check_pop", "myth_break"],
        "sfx_blocked_families": ["deep_boom", "high_riser"],
        "max_sfx_events": 2,
        "keywords": ("mito", "falso", "error", "debunk", "desmentir", "realidad"),
        "reason": "myth_debunk_alignment",
    },
    "objection_tension": {
        "music_mood": "subtle_tension",
        "music_energy": "low_tension",
        "sfx_allowed_families": ["question_tap", "soft_whoosh"],
        "sfx_blocked_families": ["deep_boom", "high_riser"],
        "max_sfx_events": 1,
        "keywords": ("duda", "pregunta", "objecion", "objeción", "caro", "coste", "coste", "objeto"),
        "reason": "objection_tension_alignment",
    },
    "money_saving": {
        "music_mood": "light_optimistic",
        "music_energy": "medium_positive",
        "sfx_allowed_families": ["soft_chime", "check_pop"],
        "sfx_blocked_families": ["deep_boom", "high_riser"],
        "max_sfx_events": 1,
        "keywords": ("ahorro", "ahorrar", "descuento", "dinero", "save", "money", "euro", "barato"),
        "reason": "money_saving_alignment",
    },
    "sensitive_sober": {
        "music_mood": "cinematic_ambient",
        "music_energy": "very_low",
        "sfx_allowed_families": [],
        "sfx_blocked_families": ["deep_boom", "dark_riser_short", "high_riser", "tension_riser", "soft_chime", "soft_whoosh", "check_pop", "question_tap", "myth_break", "soft_hit"],
        "max_sfx_events": 0,
        "keywords": ("decesos", "funeral", "fallecimiento", "muerte", "sepelio", "velatorio", "luto", "sensitive", "mourning"),
        "reason": "sensitive_sober_alignment",
    },
    "no_extra_audio": {
        "music_mood": "cinematic_ambient",
        "music_energy": "none",
        "sfx_allowed_families": [],
        "sfx_blocked_families": [],
        "max_sfx_events": 0,
        "keywords": ("no_extra_audio", "silence", "silent", "none"),
        "reason": "no_extra_audio_alignment",
    },
}

_MUSIC_MOOD_SELECTION_MAP: Dict[str, str] = {
    "warm_trust": "trust_warm",
    "calm_trust": "trust_warm",
    "emotional_protection": "trust_warm",
    "risk_warning": "subtle_tension",
    "subtle_tension": "subtle_tension",
    "explanatory_clean": "clean_corporate",
    "clean_explainer": "clean_corporate",
    "myth_debunk": "clean_corporate",
    "objection_tension": "subtle_tension",
    "light_tension": "subtle_tension",
    "money_saving": "light_optimistic",
    "optimistic_clean": "light_optimistic",
    "sensitive_sober": "cinematic_ambient",
    "no_extra_audio": "cinematic_ambient",
}

MUSIC_AUDIO_MOODS: Tuple[str, ...] = (
    "calm_trust",
    "warm_trust",
    "explanatory_clean",
    "subtle_tension",
    "clean_contrast",
    "light_tension",
    "optimistic_clean",
    "sensitive_sober",
)

SFX_AUDIO_FAMILIES: Tuple[str, ...] = (
    "soft_whoosh",
    "soft_impact",
    "deep_boom_light",
    "dark_riser_short",
    "soft_chime",
    "check_pop",
    "myth_break",
    "question_tap",
    "warning_tap",
)

BLOCKED_AUDIO_IDENTITY_TERMS: Tuple[str, ...] = (
    "typewriter",
    "keyboard_click",
    "gaming_hit",
    "cartoon_pop",
    "aggressive_glitch",
    "long_riser",
    "horror_sting",
    "comedic_bell",
    "glitch_hit",
    "punch_impact",
    "whoosh_fast",
    "tension_riser_short",
    "ding_chime_soft",
)


def _audio_editorial_profile_keywords(profile: str) -> Tuple[str, ...]:
    return tuple(_AUDIO_EDITORIAL_PROFILE_RULES.get(profile, {}).get("keywords") or ())


def _normalize_music_mood_for_selection(mood: str) -> str:
    normalized = str(mood or "").strip().lower().replace(" ", "_")
    return _MUSIC_MOOD_SELECTION_MAP.get(normalized, normalized or "clean_corporate")


def choose_audio_editorial_profile(
    *,
    editorial_type: str = "",
    segment_text: str = "",
    hook_strategy_final: str = "",
    broll_intent: str = "",
    transition_strategy: str = "",
    final_audio_chain_state: Optional[Dict[str, Any]] = None,
    sensitive_topic: bool = False,
    clip_duration: float = 0.0,
) -> Dict[str, Any]:
    text = " ".join(
        [
            str(editorial_type or ""),
            str(segment_text or ""),
            str(hook_strategy_final or ""),
            str(broll_intent or ""),
            str(transition_strategy or ""),
        ]
    )
    normalized = set(_norm_tokens(text))
    sensitive_cues = {"decesos", "funeral", "fallecimiento", "muerte", "velatorio", "sepelio", "luto"}
    if sensitive_topic or bool(normalized & sensitive_cues):
        profile = "sensitive_sober"
    elif bool(normalized & {"riesgo", "cuidado", "advertencia", "accidente", "warning", "alerta", "peligro", "imprevisto"}):
        profile = "risk_warning"
    elif bool(normalized & {"mito", "falso", "error", "debunk", "desmentir"}):
        profile = "myth_debunk"
    elif bool(normalized & {"duda", "pregunta", "objecion", "objeción", "caro", "coste"}):
        profile = "objection_tension"
    elif bool(normalized & {"ahorro", "ahorrar", "descuento", "dinero", "save", "money", "barato", "euro"}):
        profile = "money_saving"
    elif bool(normalized & {"familia", "proteger", "proteccion", "protección", "tranquilidad", "apoyo", "support", "care"}):
        profile = "emotional_protection"
    elif bool(normalized & {"explicacion", "explicación", "cobertura", "póliza", "poliza", "proceso", "documento", "coverage"}):
        profile = "explanatory_clean"
    elif float(clip_duration or 0.0) <= 4.0 and not bool(isinstance(final_audio_chain_state, dict) and final_audio_chain_state.get("base_audio_detected")):
        profile = "no_extra_audio"
    else:
        profile = "calm_trust"

    rules = dict(_AUDIO_EDITORIAL_PROFILE_RULES.get(profile) or _AUDIO_EDITORIAL_PROFILE_RULES["calm_trust"])
    music_mood = str(rules.get("music_mood") or "trust_warm")
    if profile in {"sensitive_sober", "no_extra_audio"}:
        music_mood = profile
    reason = str(rules.get("reason") or "editorial_profile")
    if isinstance(final_audio_chain_state, dict) and not bool(final_audio_chain_state.get("base_audio_detected")) and profile != "no_extra_audio":
        reason = f"{reason}|base_audio_missing"

    result = {
        "audio_editorial_profile": profile,
        "audio_editorial_profile_reason": reason,
        "music_mood": music_mood,
        "sfx_allowed_families": list(rules.get("sfx_allowed_families") or []),
        "sfx_blocked_families": list(rules.get("sfx_blocked_families") or []),
        "max_sfx_events": int(rules.get("max_sfx_events") or 0),
        "music_energy": str(rules.get("music_energy") or "low"),
        "reason": reason,
        "sensitive_topic": bool(profile == "sensitive_sober"),
        "audio_asset_history_key": f"{profile}:{music_mood}",
    }
    logger.info(
        "AUDIO_EDITORIAL_PROFILE_SELECTED profile=%s mood=%s max_sfx=%d reason=%s",
        profile,
        music_mood,
        int(result["max_sfx_events"]),
        reason,
    )
    return result


def _audio_probe_duration(path: Path) -> Optional[float]:
    if not path.exists() or not path.is_file():
        return None
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=12,
        )
        if proc.returncode != 0:
            return None
        return max(0.0, float((proc.stdout or "").strip() or 0.0))
    except Exception:
        return None


def _audio_probe_format(path: Path) -> str:
    return str(path.suffix or "").lower().lstrip(".")


def _audio_identity_warnings(path: Path, asset_type: str, mood: str, family: str, tags: Sequence[str]) -> List[str]:
    warnings: List[str] = []
    blob = " ".join([str(path.stem or ""), str(path.parent or ""), mood, family, " ".join(str(tag) for tag in tags or [])]).lower()
    if any(term in blob for term in BLOCKED_AUDIO_IDENTITY_TERMS):
        warnings.append("blocked_audio_identity_term")
    if asset_type == "music" and mood == "sensitive_sober" and any(term in blob for term in ("boom", "impact", "whoosh", "riser", "chime", "click")):
        warnings.append("sensitive_music_mismatch")
    if asset_type == "sfx" and any(term in blob for term in ("comic", "cartoon", "gaming", "glitch")):
        warnings.append("non_vpi_sound_identity")
    return warnings


def _infer_audio_mood_from_path(path: Path) -> str:
    blob = " ".join([path.stem, str(path.parent)]).lower()
    for mood, keywords in _BGM_TAXONOMY_KEYWORDS.items():
        if any(kw in blob for kw in keywords):
            return mood
    if any(term in blob for term in ("family", "warm", "calm", "trust", "acoustic")):
        return "warm_trust"
    if any(term in blob for term in ("tension", "risk", "warning", "dark", "pulse")):
        return "subtle_tension"
    if any(term in blob for term in ("clean", "explain", "corporate", "business")):
        return "explanatory_clean"
    return "calm_trust"


def _infer_sfx_family_from_path(path: Path) -> str:
    blob = " ".join([path.stem, str(path.parent)]).lower()
    for family, keywords in _SFX_TAXONOMY_KEYWORDS.items():
        if any(kw in blob for kw in keywords):
            return family
    if "whoosh" in blob:
        return "soft_whoosh"
    if any(term in blob for term in ("impact", "hit", "boom", "punch")):
        return "soft_impact"
    if any(term in blob for term in ("riser", "rise", "tension")):
        return "dark_riser_short"
    if any(term in blob for term in ("chime", "ding", "tick", "pop", "check")):
        return "soft_chime"
    return "soft_whoosh"


def _candidate_audio_roots() -> List[Path]:
    roots = [
        _REPO_ROOT / "assets" / "sounds",
        _REPO_ROOT / "assets" / "sounds" / "bgm",
        _REPO_ROOT / "assets" / "sounds" / "sfx",
        _REPO_ROOT / "backend" / "assets" / "sounds",
        _REPO_ROOT / "backend" / "assets" / "sounds" / "bgm",
        _REPO_ROOT / "backend" / "assets" / "sounds" / "sfx",
        Path("/app/assets/sounds"),
        Path("/app/assets/sounds/bgm"),
        Path("/app/assets/sounds/sfx"),
        _REPO_ROOT / "storage",
        _REPO_ROOT / "media",
    ]
    deduped: List[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(root)
    return deduped


def build_local_audio_asset_inventory(
    *,
    root_candidates: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    roots = [Path(item) for item in (root_candidates or [])] if root_candidates else _candidate_audio_roots()
    present_roots: List[str] = []
    missing_roots: List[str] = []
    audio_assets: List[Dict[str, Any]] = []
    duplicates_by_name: Dict[str, List[str]] = {}
    duplicates_by_path: Dict[str, List[str]] = {}
    suspicious_assets: List[Dict[str, Any]] = []
    seen_paths: set[str] = set()
    seen_names: Dict[str, List[str]] = {}

    for root in roots:
        if not root.exists() or not root.is_dir():
            missing_roots.append(str(root))
            continue
        present_roots.append(str(root))
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}:
                continue
            resolved = str(path.resolve())
            if resolved in seen_paths:
                duplicates_by_path.setdefault(path.name.lower(), []).append(resolved)
                continue
            seen_paths.add(resolved)
            asset_type = "music" if "bgm" in {part.lower() for part in path.parts} or "music" in {part.lower() for part in path.parts} else "sfx"
            if str(path.parent).lower().endswith("bgm") or any(token in path.stem.lower() for token in ("warm", "trust", "calm", "clean", "tension", "optimistic", "sober")):
                asset_type = "music"
            elif str(path.parent).lower().endswith("sfx") or any(token in path.stem.lower() for token in ("whoosh", "boom", "riser", "chime", "click", "impact", "hit", "ding", "pop", "tap")):
                asset_type = "sfx"
            mood = _infer_audio_mood_from_path(path) if asset_type == "music" else ""
            family = _infer_sfx_family_from_path(path) if asset_type == "sfx" else ""
            duration = _audio_probe_duration(path)
            empty_file = bool(path.exists() and path.stat().st_size == 0)
            tags = list(dict.fromkeys(_norm_tokens(path.stem) + _norm_tokens(str(path.parent))))
            identity_warnings = _audio_identity_warnings(path, asset_type, mood, family, tags)
            usable_for_vpi = not empty_file and not identity_warnings
            sensitive_safe = bool(asset_type == "music" or not identity_warnings)
            if family in {"deep_boom", "tension_riser", "high_riser"} and any(term in path.stem.lower() for term in ("glitch", "punch", "cartoon", "comic")):
                identity_warnings.append("identity_mismatch")
                usable_for_vpi = False
                sensitive_safe = False
            if "sensitive" in path.stem.lower() and asset_type == "sfx":
                identity_warnings.append("sensitive_audio_asset_blocked")
                usable_for_vpi = False
                sensitive_safe = False
            if identity_warnings:
                logger.warning(
                    "SENSITIVE_AUDIO_ASSET_BLOCKED path=%s type=%s warnings=%s",
                    str(path),
                    asset_type,
                    "|".join(identity_warnings),
                )
            record = {
                "asset_id": f"{asset_type}:{path.stem}:{abs(hash(resolved)) % 100000}",
                "asset_path": resolved,
                "asset_type": asset_type,
                "mood": mood if asset_type == "music" else "",
                "family": family if asset_type == "sfx" else "",
                "duration": duration,
                "usable_for_vpi": bool(usable_for_vpi),
                "sensitive_safe": bool(sensitive_safe),
                "identity_warnings": list(dict.fromkeys(identity_warnings)),
                "tags": tags,
                "source": "local",
                "verified_local": bool(not empty_file),
                "format": _audio_probe_format(path),
                "exists": True,
                "empty_file": bool(empty_file),
                "duplicate_name": False,
                "duplicate_path": False,
            }
            audio_assets.append(record)
            seen_names.setdefault(path.name.lower(), []).append(resolved)

    for name, paths in seen_names.items():
        if len(paths) > 1:
            duplicates_by_name[name] = paths
            for asset in audio_assets:
                if str(asset.get("asset_path") or "").lower() in [p.lower() for p in paths]:
                    asset["duplicate_name"] = True
    for name, paths in duplicates_by_path.items():
        if len(paths) > 0:
            suspicious_assets.append({"reason": "duplicate_path", "name": name, "paths": paths})

    music_assets = [asset for asset in audio_assets if asset["asset_type"] == "music"]
    sfx_assets = [asset for asset in audio_assets if asset["asset_type"] == "sfx"]
    summary = {
        "audio_asset_count": len(audio_assets),
        "music_asset_count": len(music_assets),
        "sfx_asset_count": len(sfx_assets),
        "present_roots": present_roots,
        "missing_roots": missing_roots,
        "empty_files": [asset["asset_path"] for asset in audio_assets if asset.get("empty_file")],
        "duplicate_names": duplicates_by_name,
        "suspicious_assets": suspicious_assets,
        "blocked_identity_assets": [asset["asset_path"] for asset in audio_assets if asset.get("identity_warnings")],
        "music_moods": sorted({str(asset.get("mood") or "") for asset in music_assets if str(asset.get("mood") or "")}),
        "sfx_families": sorted({str(asset.get("family") or "") for asset in sfx_assets if str(asset.get("family") or "")}),
    }
    inventory = {
        "inventory_version": "a1",
        "roots": {"present": present_roots, "missing": missing_roots},
        "music_assets": music_assets,
        "sfx_assets": sfx_assets,
        "all_assets": audio_assets,
        "summary": summary,
    }
    logger.info(
        "AUDIO_ASSET_INVENTORY_BUILT music=%d sfx=%d missing_roots=%d empty=%d duplicates=%d",
        len(music_assets),
        len(sfx_assets),
        len(missing_roots),
        len(summary["empty_files"]),
        len(duplicates_by_name),
    )
    return inventory


def validate_audio_asset_coverage(inventory: Dict[str, Any]) -> Dict[str, Any]:
    inv = inventory if isinstance(inventory, dict) else {}
    music_assets = list(inv.get("music_assets") or [])
    sfx_assets = list(inv.get("sfx_assets") or [])
    music_counts: Dict[str, int] = {}
    for asset in music_assets:
        mood = str((asset or {}).get("mood") or "").strip()
        if mood:
            music_counts[mood] = music_counts.get(mood, 0) + 1
    sfx_counts: Dict[str, int] = {}
    for asset in sfx_assets:
        family = str((asset or {}).get("family") or "").strip()
        if family:
            sfx_counts[family] = sfx_counts.get(family, 0) + 1
    missing_music_moods = [mood for mood in ("calm_trust", "explanatory_clean", "subtle_tension", "sensitive_sober") if music_counts.get(mood, 0) == 0]
    weak_music_moods = [mood for mood in ("calm_trust", "explanatory_clean", "subtle_tension", "sensitive_sober") if 0 < music_counts.get(mood, 0) < (2 if mood == "calm_trust" else 1)]
    missing_sfx_families = [family for family in ("soft_whoosh", "soft_impact", "deep_boom_light", "dark_riser_short", "soft_chime", "check_pop", "myth_break", "question_tap", "warning_tap") if sfx_counts.get(family, 0) == 0]
    weak_sfx_families = [family for family in ("soft_whoosh", "soft_impact", "dark_riser_short", "soft_chime", "check_pop") if 0 < sfx_counts.get(family, 0) < (3 if family == "soft_whoosh" else 2)]
    sensitive_sober_available = not bool(missing_music_moods and "sensitive_sober" in missing_music_moods)
    audio_asset_coverage_ok = not missing_music_moods and not missing_sfx_families
    recommendations: List[str] = []
    if "calm_trust" in missing_music_moods or music_counts.get("calm_trust", 0) < 2:
        recommendations.append("add_at_least_two_calm_trust_tracks")
    if "explanatory_clean" in missing_music_moods:
        recommendations.append("add_one_explanatory_clean_track")
    if "subtle_tension" in missing_music_moods:
        recommendations.append("add_one_subtle_tension_track")
    if "sensitive_sober" in missing_music_moods:
        recommendations.append("add_one_sensitive_sober_track")
    if sfx_counts.get("soft_whoosh", 0) < 3:
        recommendations.append("add_three_soft_whoosh_variations")
    if sfx_counts.get("soft_impact", 0) < 2:
        recommendations.append("add_two_soft_impact_variations")
    if sfx_counts.get("dark_riser_short", 0) < 2:
        recommendations.append("add_two_short_riser_variations")
    if (sfx_counts.get("soft_chime", 0) + sfx_counts.get("check_pop", 0)) < 2:
        recommendations.append("add_two_soft_confirmation_sfx")
    if missing_music_moods or missing_sfx_families or weak_music_moods or weak_sfx_families:
        logger.warning(
            "AUDIO_ASSET_COVERAGE_WARNING missing_music=%s missing_sfx=%s weak_music=%s weak_sfx=%s",
            "|".join(missing_music_moods) or "none",
            "|".join(missing_sfx_families) or "none",
            "|".join(weak_music_moods) or "none",
            "|".join(weak_sfx_families) or "none",
        )
        for mood in missing_music_moods:
            logger.warning("MUSIC_MOOD_ASSET_MISSING mood=%s reason=coverage_gap", mood)
        for family in missing_sfx_families:
            logger.warning("SFX_FAMILY_ASSET_MISSING family=%s reason=coverage_gap", family)
    logger.info(
        "AUDIO_ASSET_COVERAGE_CHECKED ok=%s music_missing=%d sfx_missing=%d",
        str(audio_asset_coverage_ok).lower(),
        len(missing_music_moods),
        len(missing_sfx_families),
    )
    return {
        "audio_asset_coverage_ok": bool(audio_asset_coverage_ok),
        "missing_music_moods": missing_music_moods,
        "missing_sfx_families": missing_sfx_families,
        "weak_music_moods": weak_music_moods,
        "weak_sfx_families": weak_sfx_families,
        "sensitive_sober_available": bool(sensitive_sober_available),
        "minimum_pack_recommendations": recommendations,
    }


def _norm_tokens(value: str) -> List[str]:
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    return [part for part in text.split() if part]


def _normalize_vpi_category(asset: Dict[str, Any]) -> str:
    """Normalize category from explicit category/taxonomy/tags/topics/path hints."""
    raw = str(asset.get("category") or "").strip().lower().replace(" ", "_")
    if raw in _CRITICAL_VPI_CATEGORIES:
        return raw

    candidates: List[str] = []
    for field in ("taxonomy",):
        val = str(asset.get(field) or "").strip().lower().replace(" ", "_")
        if val:
            candidates.append(val)
    for seq_field in ("tags", "topics"):
        for item in list(asset.get(seq_field) or []):
            val = str(item or "").strip().lower().replace(" ", "_")
            if val:
                candidates.append(val)
    path_hint = str(asset.get("path") or "").strip().lower().replace("\\", "/")
    if path_hint:
        candidates.append(path_hint)

    alias_exact = {
        "risk_warning": "risk_warning_context",
        "documents": "documents_admin",
        "documentacion": "documents_admin",
        "paperwork": "paperwork_support",
        "finance": "financial_planning",
        "calm_lifestyle": "emotional_reassurance",
        "healthy_lifestyle": "health_access",
    }
    alias_contains = [
        ("risk_warning", "risk_warning_context"),
        ("family_relief", "family_relief"),
        ("family_protection", "family_protection"),
        ("health_access", "health_access"),
        ("paperwork_support", "paperwork_support"),
        ("documents_admin", "documents_admin"),
        ("financial_planning", "financial_planning"),
        ("practical_explanation", "practical_explanation"),
        ("autonomous_work_stability", "autonomous_work_stability"),
        ("emotional_reassurance", "emotional_reassurance"),
        ("calm_lifestyle", "emotional_reassurance"),
        ("document", "documents_admin"),
        ("paperwork", "paperwork_support"),
        ("tramite", "paperwork_support"),
        ("formulario", "documents_admin"),
        ("poliza", "documents_admin"),
        ("familia", "family_relief"),
        ("salud", "health_access"),
        ("autonom", "autonomous_work_stability"),
        ("financ", "financial_planning"),
    ]

    for cand in candidates:
        if cand in _CRITICAL_VPI_CATEGORIES:
            return cand
        if cand in alias_exact:
            return alias_exact[cand]
        for needle, mapped in alias_contains:
            if needle in cand:
                return mapped
    return raw


def _abs_path(candidate: str) -> Path:
    path = Path(candidate)
    return path if path.is_absolute() else (_REPO_ROOT / path)


def _normalize_asset_type(asset_type: str) -> str:
    return _ASSET_TYPE_ALIASES.get(str(asset_type or "").strip().lower(), "")


def _allowed_root_paths(asset_type: str) -> List[Path]:
    return [_abs_path(root).resolve() for root in _ASSET_PATHS.get(asset_type, tuple())]


def _path_within_allowed_roots(path: Path, asset_type: str) -> bool:
    try:
        resolved = path.resolve(strict=False)
    except Exception:
        return False
    for root in _allowed_root_paths(asset_type):
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _iter_asset_files(asset_type: str, roots: Iterable[str]) -> List[Path]:
    files: List[Path] = []
    exts = tuple(ext.lower() for ext in _ASSET_EXTS.get(asset_type, tuple()))
    seen: set[str] = set()
    for root in roots:
        root_path = _abs_path(root)
        if not root_path.exists() or not root_path.is_dir():
            continue
        for item in sorted(root_path.rglob("*")):
            if not item.is_file() or item.suffix.lower() not in exts:
                continue
            key = str(item.resolve())
            if key in seen:
                continue
            seen.add(key)
            files.append(item)
    return files


def discover_asset_library() -> Dict[str, Any]:
    discovered: Dict[str, Any] = {}
    summary: Dict[str, int] = {}
    for asset_type, roots in _ASSET_PATHS.items():
        files = _iter_asset_files(asset_type, roots)
        discovered[asset_type] = [str(path) for path in files]
        summary[asset_type] = len(files)
        logger.info("[asset-library] discovered type=%s count=%d", asset_type, len(files))
    discovered["summary"] = summary
    logger.info("[asset-library] taxonomy_loaded=true")
    return discovered


def load_asset_manifest() -> Dict[str, Any]:
    for candidate in _MANIFEST_CANDIDATES:
        manifest_path = _abs_path(candidate)
        if not manifest_path.exists():
            continue
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            logger.info("[asset-library] manifest_found=true path=%s", manifest_path)
            logger.info(
                "ASSET_MANIFEST_STATUS found=true path=%s template=false",
                manifest_path,
            )
            return {
                "manifest_found": True,
                "manifest_path": str(manifest_path),
                "version": str(payload.get("version") or "1.0"),
                "sources": dict(payload.get("sources") or {}),
                "assets": list(payload.get("assets") or []),
            }
        except Exception as exc:
            logger.warning("[asset-library] manifest_parse_error path=%s reason=%s", manifest_path, exc)
            continue

    # No real manifest found — check for template fallback
    for candidate in _TEMPLATE_CANDIDATES:
        template_path = _abs_path(candidate)
        if not template_path.exists():
            continue
        try:
            payload = json.loads(template_path.read_text(encoding="utf-8"))
            logger.info(
                "ASSET_MANIFEST_STATUS found=false template=true path=%s reason=template_fallback",
                template_path,
            )
            logger.info("[asset-library] manifest_template_used=true path=%s", template_path)
            return {
                "manifest_found": False,
                "manifest_template_used": True,
                "manifest_path": str(template_path),
                "version": str(payload.get("version") or "1.0"),
                "sources": dict(payload.get("sources") or {}),
                "assets": list(payload.get("assets") or []),
            }
        except Exception as exc:
            logger.warning("[asset-library] template_parse_error path=%s reason=%s", template_path, exc)
            continue

    logger.info("ASSET_MANIFEST_STATUS found=false template=false reason=no_manifest_or_template")
    logger.info("[asset-library] manifest_found=false path=")
    return {
        "manifest_found": False,
        "manifest_template_used": False,
        "manifest_path": "",
        "version": "1.0",
        "sources": {},
        "assets": [],
    }


def validate_asset_entry(asset: Dict[str, Any]) -> Dict[str, Any]:
    asset_type = _normalize_asset_type(str(asset.get("type") or ""))
    rel_path = str(asset.get("path") or "").strip()
    path = _abs_path(rel_path) if rel_path else Path("")
    exists = bool(rel_path and path.exists() and path.is_file())
    source_name = str(asset.get("source") or asset.get("source_name") or "").strip()
    license_name = str(asset.get("license_name") or "").strip()
    tags = list(asset.get("tags") or [])
    sensitive_tone = str(asset.get("sensitive_tone") or "safe")
    commercial_use_ok = bool(asset.get("commercial_use_ok", False))
    attribution_required = bool(asset.get("attribution_required", False))
    source_url = str(asset.get("source_url") or "")
    path_allowed = bool(asset_type in _ASSET_PATHS and rel_path and _path_within_allowed_roots(path, asset_type))
    ext = str(path.suffix or "").lower()

    reason = "ok"
    valid = True
    if asset_type not in _ASSET_PATHS:
        valid = False
        reason = "invalid_type"
    elif not rel_path:
        valid = False
        reason = "missing_path"
    elif not path_allowed:
        valid = False
        reason = "path_outside_assets"
    elif not exists:
        valid = False
        reason = "missing_file"
    elif ext and ext not in tuple(ext.lower() for ext in _ASSET_EXTS.get(asset_type, tuple())):
        valid = False
        reason = "invalid_extension"
    elif not source_name:
        valid = False
        reason = "source_missing"
    elif not license_name:
        valid = False
        reason = "license_missing"
    elif not tags:
        valid = False
        reason = "tags_missing"
    elif asset_type == "motion_overlay" and not sensitive_tone.strip():
        valid = False
        reason = "sensitive_tone_missing"
    elif not commercial_use_ok:
        valid = False
        reason = "commercial_use_not_ok"

    # Normalize editorial schema fields with safe defaults
    category = _normalize_vpi_category(asset) or str(asset.get("category") or asset.get("topics", [None])[0] or "").strip()
    taxonomy = str(asset.get("taxonomy") or category or "").strip()
    allowed_contexts = list(asset.get("allowed_contexts") or [])
    avoid_contexts = list(asset.get("avoid_contexts") or asset.get("avoid_for") or [])
    intensity = str(asset.get("intensity") or "medium").strip()
    brand_fit = bool(asset.get("brand_fit", True))

    result = {
        "id": str(asset.get("id") or ""),
        "type": asset_type,
        "path": str(path) if rel_path else "",
        "exists": exists,
        "path_allowed": path_allowed,
        "source_name": source_name,
        "source_url": source_url,
        "license_name": license_name,
        "tags": tags,
        "topics": list(asset.get("topics") or []),
        "sensitive_tone": sensitive_tone,
        "commercial_use_ok": commercial_use_ok,
        "attribution_required": attribution_required,
        "downloaded_at": str(asset.get("downloaded_at") or ""),
        "review_required": bool(asset.get("review_required", False)),
        "category": category,
        "taxonomy": taxonomy,
        "allowed_contexts": allowed_contexts,
        "avoid_contexts": avoid_contexts,
        "intensity": intensity,
        "brand_fit": brand_fit,
        "asset_valid": valid,
        "reason": reason,
    }
    logger.info("[asset-library] asset_valid=%s path=%s reason=%s", str(valid).lower(), result["path"] or rel_path, reason)
    return result


# ── Fallback taxonomy from filename/path ──────────────────────────────────────

def _classify_broll_by_filename(path: Path) -> Tuple[str, List[str]]:
    """Classify a B-roll file by its filename/path into an editorial intent + tags."""
    name = path.stem.lower()
    full_path = str(path).lower()
    tokens = _norm_tokens(name) + _norm_tokens(full_path)

    best_intent = "practical_explanation"
    best_score = 0
    for intent, keywords in _BROLL_TAXONOMY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in tokens or kw in name or kw in full_path)
        if score > best_score:
            best_score = score
            best_intent = intent

    tags = [best_intent]
    # Add additional tags from matched keywords
    for intent, keywords in _BROLL_TAXONOMY_KEYWORDS.items():
        for kw in keywords:
            if kw in tokens or kw in name:
                if kw not in tags:
                    tags.append(kw)

    return best_intent, tags


def _classify_sfx_by_filename(path: Path) -> Tuple[str, List[str]]:
    """Classify an SFX file by its filename/path into a family + tags."""
    name = path.stem.lower()
    full_path = str(path).lower()
    tokens = _norm_tokens(name) + _norm_tokens(full_path)

    best_family = "magic_whoosh"
    best_score = 0
    for family, keywords in _SFX_TAXONOMY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in tokens or kw in name or kw in full_path)
        if score > best_score:
            best_score = score
            best_family = family

    tags = [best_family]
    for family, keywords in _SFX_TAXONOMY_KEYWORDS.items():
        for kw in keywords:
            if kw in tokens or kw in name:
                if kw not in tags:
                    tags.append(kw)

    return best_family, tags


def _classify_bgm_by_filename(path: Path) -> Tuple[str, List[str]]:
    """Classify a BGM file by its filename/path into a profile + tags."""
    name = path.stem.lower()
    full_path = str(path).lower()
    tokens = _norm_tokens(name) + _norm_tokens(full_path)

    best_profile = "clean_corporate"
    best_score = 0
    for profile, keywords in _BGM_TAXONOMY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in tokens or kw in name or kw in full_path)
        if score > best_score:
            best_score = score
            best_profile = profile

    tags = [best_profile]
    for profile, keywords in _BGM_TAXONOMY_KEYWORDS.items():
        for kw in keywords:
            if kw in tokens or kw in name:
                if kw not in tags:
                    tags.append(kw)

    return best_profile, tags


def _candidate_visual_roots() -> List[Path]:
    roots = []
    for candidate in _ASSET_PATHS.get("visual", ()):
        roots.append(_abs_path(candidate))
    return roots


def _probe_image_dimensions(path: Path) -> Dict[str, int]:
    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=12,
        )
        if proc.returncode != 0 or not (proc.stdout or "").strip():
            return {"width": 0, "height": 0}
        parts = [part.strip() for part in (proc.stdout or "").strip().split(",")]
        if len(parts) >= 2:
            return {"width": int(float(parts[0] or 0)), "height": int(float(parts[1] or 0))}
    except Exception:
        return {"width": 0, "height": 0}
    return {"width": 0, "height": 0}


def _classify_visual_intent(path: Path) -> Tuple[str, List[str]]:
    blob = " ".join([path.stem, str(path.parent)]).lower()
    tokens = _norm_tokens(blob)
    best_intent = "coverage"
    best_score = 0
    for intent, keywords in VISUAL_INTENT_TAXONOMY.items():
        score = sum(1 for kw in keywords if kw in blob or kw in tokens)
        if score > best_score:
            best_score = score
            best_intent = intent
    tags = [best_intent]
    for intent, keywords in VISUAL_INTENT_TAXONOMY.items():
        for kw in keywords:
            if kw in blob and kw not in tags:
                tags.append(kw)
    return best_intent, tags


def _classify_visual_type(path: Path) -> str:
    blob = " ".join([path.stem, str(path.parent)]).lower()
    for visual_type, keywords in VISUAL_TYPE_HINTS.items():
        if any(kw in blob for kw in keywords):
            return visual_type
    suffix = path.suffix.lower()
    if suffix in {".svg"}:
        return "icon"
    if suffix in {".png", ".webp", ".jpg", ".jpeg"}:
        return "badge"
    if suffix in {".gif", ".apng", ".mp4", ".mov", ".webm"}:
        return "overlay"
    return "callout"


def _visual_identity_warnings(path: Path, visual_type: str, intent: str, dims: Dict[str, int], tags: Sequence[str]) -> List[str]:
    blob = " ".join([path.stem, str(path.parent), intent, visual_type, " ".join(tags or [])]).lower()
    warnings: List[str] = []
    if any(term in blob for term in VISUAL_BLOCKED_TERMS):
        warnings.append("blocked_visual_identity_term")
    if any(term in blob for term in ("meme", "gaming", "cartoon", "neon", "gore", "blood")):
        warnings.append("prohibited_visual_identity")
    width = int(dims.get("width") or 0)
    height = int(dims.get("height") or 0)
    if width and height and (width < 96 or height < 96):
        warnings.append("too_small")
    if width and height and max(width, height) < 192:
        warnings.append("small_asset")
    if visual_type == "logo" and ("external" in blob or "unauthorized" in blob):
        warnings.append("external_logo_not_authorized")
    if intent == "sensitive_sober" and not any(term in blob for term in VISUAL_SENSITIVE_SAFETY_TERMS):
        warnings.append("sensitive_visual_mismatch")
    return warnings


def build_local_visual_asset_inventory(
    *,
    root_candidates: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    roots = [Path(item) for item in (root_candidates or [])] if root_candidates else _candidate_visual_roots()
    present_roots: List[str] = []
    missing_roots: List[str] = []
    visual_assets: List[Dict[str, Any]] = []
    seen_paths: set[str] = set()
    duplicate_names: Dict[str, List[str]] = {}
    seen_names: Dict[str, List[str]] = {}
    suspicious_assets: List[Dict[str, Any]] = []

    supported_exts = {".svg", ".png", ".webp", ".apng", ".gif", ".jpg", ".jpeg"}
    for root in roots:
        if not root.exists() or not root.is_dir():
            missing_roots.append(str(root))
            continue
        present_roots.append(str(root))
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in supported_exts:
                continue
            resolved = str(path.resolve())
            if resolved in seen_paths:
                continue
            seen_paths.add(resolved)
            size = path.stat().st_size if path.exists() else 0
            dims = _probe_image_dimensions(path)
            visual_type = _classify_visual_type(path)
            intent, tags = _classify_visual_intent(path)
            identity_warnings = _visual_identity_warnings(path, visual_type, intent, dims, tags)
            empty_file = bool(size == 0)
            usable_for_vpi = not empty_file and not identity_warnings
            sensitive_safe = bool(usable_for_vpi and intent in {"protection", "health", "coverage", "money_saving", "myth_debunk", "objection", "sensitive_sober", "travel", "risk_warning"})
            if identity_warnings:
                logger.warning(
                    "SENSITIVE_VISUAL_ASSET_BLOCKED path=%s type=%s warnings=%s",
                    str(path),
                    visual_type,
                    "|".join(identity_warnings),
                )
            asset_record = {
                "visual_asset_id": f"{visual_type}:{path.stem}:{abs(hash(resolved)) % 100000}",
                "visual_asset_path": resolved,
                "visual_asset_type": visual_type,
                "visual_intent": intent,
                "visual_family": intent,
                "usable_for_vpi": bool(usable_for_vpi),
                "sensitive_safe": bool(sensitive_safe),
                "dimensions": dims,
                "tags": list(dict.fromkeys(tags + _norm_tokens(path.stem))),
                "identity_warnings": list(dict.fromkeys(identity_warnings)),
                "verified_local": bool(not empty_file),
                "source": "local",
                "empty_file": bool(empty_file),
                "duplicate_name": False,
            }
            visual_assets.append(asset_record)
            seen_names.setdefault(path.name.lower(), []).append(resolved)

    for name, paths in seen_names.items():
        if len(paths) > 1:
            duplicate_names[name] = paths
            for asset in visual_assets:
                if str(asset.get("visual_asset_path") or "").lower() in [p.lower() for p in paths]:
                    asset["duplicate_name"] = True

    summary = {
        "visual_asset_count": len(visual_assets),
        "present_roots": present_roots,
        "missing_roots": missing_roots,
        "duplicate_names": duplicate_names,
        "blocked_identity_assets": [asset["visual_asset_path"] for asset in visual_assets if asset.get("identity_warnings")],
        "visual_types": sorted({str(asset.get("visual_asset_type") or "") for asset in visual_assets if asset.get("visual_asset_type")}),
        "visual_intents": sorted({str(asset.get("visual_intent") or "") for asset in visual_assets if asset.get("visual_intent")}),
    }
    logger.info(
        "VISUAL_ASSET_INVENTORY_BUILT total=%d missing_roots=%d duplicates=%d",
        len(visual_assets),
        len(missing_roots),
        len(duplicate_names),
    )
    return {
        "inventory_version": "a1",
        "roots": {"present": present_roots, "missing": missing_roots},
        "all_assets": visual_assets,
        "summary": summary,
    }


def validate_visual_asset_coverage(inventory: Dict[str, Any]) -> Dict[str, Any]:
    inv = inventory if isinstance(inventory, dict) else {}
    assets = list(inv.get("all_assets") or [])
    counts: Dict[str, int] = {}
    family_counts: Dict[str, int] = {}
    for asset in assets:
        intent = str((asset or {}).get("visual_intent") or "").strip()
        family = str((asset or {}).get("visual_family") or "").strip()
        if intent:
            counts[intent] = counts.get(intent, 0) + 1
        if family:
            family_counts[family] = family_counts.get(family, 0) + 1

    intent_thresholds = {
        "protection": 3,
        "health": 2,
        "risk_warning": 2,
        "coverage": 2,
        "money_saving": 1,
        "myth_debunk": 2,
        "objection": 1,
        "sensitive_sober": 1,
    }
    missing_visual_intents = [intent for intent, minimum in intent_thresholds.items() if counts.get(intent, 0) == 0]
    weak_visual_intents = [intent for intent, minimum in intent_thresholds.items() if 0 < counts.get(intent, 0) < minimum]
    missing_visual_families = list(missing_visual_intents)
    weak_visual_families = list(weak_visual_intents)
    sensitive_visual_available = bool(counts.get("sensitive_sober", 0) >= 1)
    visual_asset_coverage_ok = not missing_visual_intents and not missing_visual_families
    visual_pack_recommendations: List[str] = []
    if counts.get("protection", 0) < 3:
        visual_pack_recommendations.append("add_three_protection_visuals")
    if counts.get("health", 0) < 2:
        visual_pack_recommendations.append("add_two_health_visuals")
    if counts.get("risk_warning", 0) < 2:
        visual_pack_recommendations.append("add_two_risk_warning_visuals")
    if counts.get("coverage", 0) < 2:
        visual_pack_recommendations.append("add_two_coverage_visuals")
    if counts.get("money_saving", 0) < 1:
        visual_pack_recommendations.append("add_one_money_saving_visual")
    if counts.get("myth_debunk", 0) < 2:
        visual_pack_recommendations.append("add_two_myth_debunk_visuals")
    if counts.get("objection", 0) < 1:
        visual_pack_recommendations.append("add_one_objection_visual")
    if counts.get("sensitive_sober", 0) < 1:
        visual_pack_recommendations.append("add_one_sensitive_sober_visual")
    if missing_visual_intents or weak_visual_intents:
        logger.warning(
            "VISUAL_ASSET_COVERAGE_WARNING missing=%s weak=%s",
            "|".join(missing_visual_intents) or "none",
            "|".join(weak_visual_intents) or "none",
        )
        for intent in missing_visual_intents:
            logger.warning("VISUAL_ASSET_MISSING_FOR_INTENT intent=%s reason=coverage_gap", intent)
    logger.info(
        "VISUAL_ASSET_COVERAGE_CHECKED ok=%s missing=%d weak=%d",
        str(visual_asset_coverage_ok).lower(),
        len(missing_visual_intents),
        len(weak_visual_intents),
    )
    return {
        "visual_asset_coverage_ok": bool(visual_asset_coverage_ok),
        "missing_visual_intents": missing_visual_intents,
        "weak_visual_intents": weak_visual_intents,
        "missing_visual_families": missing_visual_families,
        "weak_visual_families": weak_visual_families,
        "sensitive_visual_available": bool(sensitive_visual_available),
        "visual_pack_recommendations": visual_pack_recommendations,
    }


def _build_fallback_verified_asset(
    path_str: str,
    asset_type: str,
) -> Dict[str, Any]:
    """Build a verified-like asset entry from a discovered file using fallback taxonomy."""
    path = Path(path_str)
    name = path.stem.lower()
    tags: List[str] = []
    topics: List[str] = []
    source_name = "local_fallback"
    license_name = "local_fallback"

    if asset_type == "broll":
        intent, tags = _classify_broll_by_filename(path)
        topics = [intent]
    elif asset_type == "sfx":
        family, tags = _classify_sfx_by_filename(path)
        topics = [family]
    elif asset_type == "bgm":
        profile, tags = _classify_bgm_by_filename(path)
        topics = [profile]
    elif asset_type == "icons":
        tags = _norm_tokens(name)
        topics = tags[:]
    elif asset_type == "fonts":
        tags = ["font"]
        topics = ["typography"]
    elif asset_type == "motion_overlay":
        tags = _norm_tokens(name)
        topics = tags[:]

    # Derive editorial schema fields from fallback taxonomy
    category = topics[0] if topics else ""
    taxonomy = category
    allowed_contexts = [category] if category else []
    avoid_contexts: List[str] = []
    intensity = "medium"
    brand_fit = True

    return {
        "id": f"local_{asset_type}_{len(tags)}",
        "type": asset_type,
        "path": path_str,
        "exists": True,
        "path_allowed": True,
        "source_name": source_name,
        "source_url": "",
        "license_name": license_name,
        "tags": tags,
        "topics": topics,
        "sensitive_tone": "safe",
        "commercial_use_ok": True,
        "attribution_required": False,
        "downloaded_at": "",
        "review_required": False,
        "category": category,
        "taxonomy": taxonomy,
        "allowed_contexts": allowed_contexts,
        "avoid_contexts": avoid_contexts,
        "intensity": intensity,
        "brand_fit": brand_fit,
        "asset_valid": True,
        "reason": "local_fallback_taxonomy",
    }


def build_asset_index() -> Dict[str, Any]:
    discovered = discover_asset_library()
    manifest = load_asset_manifest()
    audio_inventory = build_local_audio_asset_inventory()
    audio_coverage = validate_audio_asset_coverage(audio_inventory)
    visual_inventory = build_local_visual_asset_inventory()
    visual_coverage = validate_visual_asset_coverage(visual_inventory)
    validated_assets: List[Dict[str, Any]] = []
    for entry in manifest.get("assets", []):
        if isinstance(entry, dict):
            validated_assets.append(validate_asset_entry(entry))

    by_type_verified: Dict[str, List[Dict[str, Any]]] = {key: [] for key in _ASSET_PATHS}
    by_type_unverified: Dict[str, List[Dict[str, Any]]] = {key: [] for key in _ASSET_PATHS}
    invalid_assets: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for item in validated_assets:
        asset_type = str(item.get("type") or "")
        if asset_type not in by_type_verified:
            continue
        if item.get("asset_valid"):
            by_type_verified[asset_type].append(item)
        else:
            invalid_assets.append(item)
            warnings.append(f"{asset_type}:{item.get('reason')}:{item.get('path')}")

    manifest_found = bool(manifest.get("manifest_found"))

    if manifest_found:
        # Normal path: use manifest-verified assets
        verified_paths = {str(item.get("path")) for item in validated_assets if item.get("asset_valid")}
        for asset_type in _ASSET_PATHS:
            for path in discovered.get(asset_type, []):
                if path in verified_paths:
                    continue
                by_type_unverified[asset_type].append(
                    {
                        "id": "",
                        "type": asset_type,
                        "path": path,
                        "exists": True,
                        "source_name": "unverified_local",
                        "source_url": "",
                        "license_name": "",
                        "tags": [],
                        "topics": [],
                        "sensitive_tone": "unknown",
                        "commercial_use_ok": False,
                        "attribution_required": False,
                        "downloaded_at": "",
                        "asset_valid": False,
                        "reason": "unverified_local",
                    }
                )
    else:
        # FALLBACK PATH: No manifest found — classify discovered files by filename/path
        # and promote them to verified status so local assets are usable.
        logger.info("[asset-library] manifest_found=false — using fallback taxonomy for discovered assets")
        for asset_type in _ASSET_PATHS:
            for path_str in discovered.get(asset_type, []):
                fallback_entry = _build_fallback_verified_asset(path_str, asset_type)
                by_type_verified[asset_type].append(fallback_entry)
                logger.info(
                    "[asset-library] ASSET_VERIFIED type=%s path=%s taxonomy=%s",
                    asset_type,
                    path_str,
                    "|".join(fallback_entry.get("tags") or []),
                )

    index = {
        "manifest_found": manifest_found,
        "manifest_path": str(manifest.get("manifest_path") or ""),
        "manifest_version": str(manifest.get("version") or "1.0"),
        "sources": dict(manifest.get("sources") or {}),
        "taxonomy": {
            "broll_intents": list(EDITORIAL_BROLL_INTENTS),
            "sfx_families": list(EDITORIAL_SFX_FAMILIES),
            "icon_concepts": list(EDITORIAL_ICON_CONCEPTS),
            "font_roles": list(EDITORIAL_FONT_ROLES),
            "overlay_concepts": list(EDITORIAL_OVERLAY_CONCEPTS),
        },
        "verified": by_type_verified,
        "unverified_local": by_type_unverified,
        "invalid_assets": invalid_assets,
        "warnings": warnings,
        "all_discovered": discovered,
        "audio_asset_inventory": audio_inventory,
        "audio_asset_inventory_summary": dict(audio_inventory.get("summary") or {}),
        "audio_asset_coverage": dict(audio_coverage),
        "audio_asset_inventory_version": str(audio_inventory.get("inventory_version") or "a1"),
        "visual_asset_inventory": visual_inventory,
        "visual_asset_inventory_summary": dict(visual_inventory.get("summary") or {}),
        "visual_asset_coverage": dict(visual_coverage),
        "visual_asset_inventory_version": str(visual_inventory.get("inventory_version") or "a1"),
    }
    logger.info(
        "[asset-library] index_ready=true broll=%d sfx=%d bgm=%d icons=%d fonts=%d overlays=%d",
        len(by_type_verified["broll"]),
        len(by_type_verified["sfx"]),
        len(by_type_verified["bgm"]),
        len(by_type_verified["icons"]),
        len(by_type_verified["fonts"]),
        len(by_type_verified["motion_overlay"]),
    )
    logger.info(
        "[asset-library] visual_index_ready=true assets=%d missing_roots=%d",
        len((visual_inventory.get("all_assets") or [])),
        len((visual_inventory.get("roots") or {}).get("missing") or []),
    )
    return index


def build_asset_library_qc_report(index: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    idx = index or {}
    verified = dict(idx.get("verified") or {})
    unverified = dict(idx.get("unverified_local") or {})
    invalid_assets = list(idx.get("invalid_assets") or [])
    manifest_found = bool(idx.get("manifest_found"))
    counts = {
        "broll": len(verified.get("broll") or []),
        "sfx": len(verified.get("sfx") or []),
        "bgm": len(verified.get("bgm") or []),
        "icons": len(verified.get("icons") or []),
        "fonts": len(verified.get("fonts") or []),
        "motion_overlay": len(verified.get("motion_overlay") or []),
    }
    unverified_counts = {
        "broll": len(unverified.get("broll") or []),
        "sfx": len(unverified.get("sfx") or []),
        "bgm": len(unverified.get("bgm") or []),
        "icons": len(unverified.get("icons") or []),
        "fonts": len(unverified.get("fonts") or []),
        "motion_overlay": len(unverified.get("motion_overlay") or []),
    }
    core_required = ("broll", "sfx", "bgm", "icons", "fonts")
    missing = [key for key in core_required if counts.get(key, 0) == 0]
    license_warnings: List[str] = []
    recommendations: List[str] = []

    invalid_manifest_assets = [str(item.get("path") or "") for item in invalid_assets]
    for asset_type, assets in verified.items():
        for item in assets:
            if not item.get("commercial_use_ok"):
                invalid_manifest_assets.append(str(item.get("path") or ""))
                license_warnings.append(f"{asset_type}:commercial_use_not_ok:{item.get('path')}")
    for item in invalid_assets:
        license_warnings.append(f"{item.get('type')}:{item.get('reason')}:{item.get('path')}")

    if not manifest_found:
        # When using fallback taxonomy, consider the library ready if we have at least
        # 1 asset per core category (since they're all classified from disk).
        if counts["broll"] >= 1 and counts["sfx"] >= 1 and counts["bgm"] >= 1 and counts["icons"] >= 1 and counts["fonts"] >= 1:
            status = "READY_FALLBACK"
        elif sum(counts.values()) == 0:
            status = "EMPTY"
            recommendations.append("add_assets_to_disk")
        else:
            status = "PARTIAL_FALLBACK"
            recommendations.append("add_more_assets_to_disk_for_missing_categories")
    else:
        if counts["broll"] >= 10 and counts["sfx"] >= 10 and counts["icons"] >= 10 and counts["bgm"] >= 3 and counts["fonts"] >= 1:
            status = "READY"
        elif sum(counts.values()) == 0:
            status = "EMPTY"
            recommendations.append("add_verified_assets_with_manifest")
        else:
            status = "PARTIAL"
            recommendations.append("increase_verified_assets_for_missing_categories")

    if counts.get("motion_overlay", 0) == 0:
        recommendations.append("add_motion_overlay_assets_for_overlay_pack")

    if invalid_manifest_assets:
        status = "INVALID"

    logger.info("[asset-library-qc] status=%s manifest_found=%s", status, str(manifest_found).lower())
    logger.info("[asset-library-qc] missing=%s", "|".join(missing) or "none")
    for warning in license_warnings:
        logger.info("[asset-library-qc] warning=%s", warning)
    return {
        "asset_library_status": status,
        "counts": counts,
        "unverified_counts": unverified_counts,
        "missing_categories": missing,
        "license_warnings": license_warnings,
        "recommendations": recommendations,
        "invalid_assets": invalid_manifest_assets,
        "manifest_found": manifest_found,
    }


# OUTPUT-AUDIO-BROLL-51B: a BGM slot must hold real background music. A short SFX/riser
# (e.g. tension_riser_short.mp3, 3.59s) chosen as BGM is looped to clip length by the music
# path (audio.py aloop=loop=-1) -> a repeating riser + no perceptible music. Disqualify
# riser/impact/chime/whoosh/short-SFX assets and tracks under the minimum BGM duration.
_BGM_MIN_DURATION_S = 8.0
_NON_BGM_AUDIO_KEYWORDS = (
    "riser", "impact", "chime", "whoosh", "swoosh", "stinger", "boom", "glitch",
    "ding", "clap", "_hit", "sfx", "sweep_up", "transition_",
)


def _bgm_asset_disqualified(asset: Dict[str, Any]) -> Tuple[bool, str]:
    """Return (disqualified, reason) for the BGM slot. Excludes non-music SFX families and
    tracks shorter than the minimum BGM duration. Real BGM (subtle_tension/warm_trust/
    clean_corporate/...) is never matched by these keywords."""
    path = str(asset.get("asset_path") or asset.get("path") or "")
    name = Path(path).name.lower()
    fam = str(asset.get("family") or asset.get("mood") or "").lower()
    tags = " ".join(str(t).lower() for t in (asset.get("tags") or []))
    hay = f"{name} {fam} {tags}"
    for kw in _NON_BGM_AUDIO_KEYWORDS:
        if kw in hay:
            return True, f"non_bgm_audio_family:{kw}"
    try:
        dur = float(asset.get("duration") or 0.0)
    except (TypeError, ValueError):
        dur = 0.0
    if 0.0 < dur < _BGM_MIN_DURATION_S:
        return True, f"bgm_too_short:{dur:.2f}s"
    return False, ""


def select_verified_bgm_candidate(
    *,
    editorial_type: str = "",
    hook_intent: str = "",
    segment_text: str = "",
    index: Optional[Dict[str, Any]] = None,
    music_mood: str = "",
    audio_editorial_profile: str = "",
    recent_music_asset_ids: Optional[Sequence[str]] = None,
    audio_variation_index: int = 0,
    task_id: Optional[str] = None,
    audio_inventory: Optional[Dict[str, Any]] = None,
    audio_coverage: Optional[Dict[str, Any]] = None,
    sensitive_topic: bool = False,
) -> Dict[str, Any]:
    idx = index or build_asset_index()
    verified_bgm = list((idx.get("verified") or {}).get("bgm") or [])
    inventory_music_assets = list((audio_inventory or {}).get("music_assets") or [])
    coverage = audio_coverage or {}
    # OUTPUT-AUDIO-BROLL-51B: keep only real background-music candidates in the BGM slot.
    _bgm_excluded_non_music: List[Tuple[str, str]] = []

    def _keep_bgm(_a: Dict[str, Any]) -> bool:
        _bad, _why = _bgm_asset_disqualified(_a)
        if _bad:
            _bgm_excluded_non_music.append((str(_a.get("asset_path") or _a.get("path") or ""), _why))
        return not _bad

    verified_bgm = [a for a in verified_bgm if _keep_bgm(a)]
    inventory_music_assets = [a for a in inventory_music_assets if _keep_bgm(a)]
    if _bgm_excluded_non_music:
        logger.info(
            "BGM_NON_MUSIC_CANDIDATES_EXCLUDED count=%d sample=%s",
            len(_bgm_excluded_non_music), _bgm_excluded_non_music[:4],
        )
    if inventory_music_assets:
        logger.info(
            "MUSIC_EDITORIAL_PROFILE_SELECTED profile=%s mood=%s inventory_assets=%d coverage_ok=%s",
            str(audio_editorial_profile or "calm_trust"),
            str(music_mood or ""),
            len(inventory_music_assets),
            str(bool(coverage.get("audio_asset_coverage_ok", True))).lower(),
        )
        profile = str(audio_editorial_profile or "").strip().lower() or "calm_trust"
        requested_mood = _normalize_music_mood_for_selection(music_mood or _AUDIO_EDITORIAL_PROFILE_RULES.get(profile, {}).get("music_mood") or "clean_corporate")
        if profile == "sensitive_sober":
            requested_mood = "sensitive_sober"
        elif profile == "no_extra_audio":
            requested_mood = "no_extra_audio"
        mood_order = [requested_mood]
        if requested_mood != "calm_trust":
            mood_order.append("calm_trust")
        if requested_mood != "explanatory_clean":
            mood_order.append("explanatory_clean")
        if requested_mood != "warm_trust":
            mood_order.append("warm_trust")
        if requested_mood != "subtle_tension":
            mood_order.append("subtle_tension")
        if requested_mood != "sensitive_sober":
            mood_order.append("sensitive_sober")
        if sensitive_topic:
            mood_order = [mood for mood in mood_order if mood in {"sensitive_sober", "calm_trust", "no_extra_audio", "explanatory_clean"}]

        recent_ids = {str(item) for item in (recent_music_asset_ids or []) if str(item)}
        best_inventory_entry: Optional[Dict[str, Any]] = None
        best_inventory_score = -999.0
        for item in inventory_music_assets:
            asset_path = str(item.get("asset_path") or item.get("path") or "")
            if not asset_path:
                continue
            if not bool(item.get("usable_for_vpi", True)) and not bool(item.get("verified_local", False)):
                continue
            if sensitive_topic and not bool(item.get("sensitive_safe", False)):
                continue
            mood = str(item.get("mood") or _infer_audio_mood_from_path(Path(asset_path)))
            if mood not in mood_order:
                continue
            asset_id = str(item.get("asset_id") or Path(asset_path).stem)
            score = 10.0 if mood == requested_mood else 4.0
            score += 1.5 if asset_id not in recent_ids else -2.0
            if not item.get("identity_warnings"):
                score += 1.0
            if float(item.get("duration") or 0.0) > 0.0:
                score += 0.25
            if score > best_inventory_score:
                best_inventory_score = score
                best_inventory_entry = item
        if best_inventory_entry:
            asset_path = str(best_inventory_entry.get("asset_path") or best_inventory_entry.get("path") or "")
            asset_id = str(best_inventory_entry.get("asset_id") or Path(asset_path).stem)
            reuse_reason = ""
            if asset_id in recent_ids:
                reuse_reason = "recently_used_reuse"
            selection_reason = "inventory_taxonomy_match"
            fallback_used = bool(str(best_inventory_entry.get("mood") or "") != requested_mood)
            if not bool(best_inventory_entry.get("usable_for_vpi", True)):
                fallback_used = True
                selection_reason = "inventory_not_preferred"
            if fallback_used:
                logger.info("MUSIC_ASSET_FALLBACK_USED reason=%s mood=%s", "no_asset_for_mood" if str(best_inventory_entry.get("mood") or "") != requested_mood else "inventory_not_preferred", requested_mood)
            logger.info(
                "MUSIC_ASSET_SELECTED asset=%s asset_id=%s mood=%s score=%.2f reuse=%s",
                Path(asset_path).name if asset_path else "",
                asset_id,
                requested_mood,
                best_inventory_score,
                reuse_reason or "none",
            )
            return {
                "matched": True,
                "reason": selection_reason,
                "path": asset_path,
                "asset_id": asset_id,
                "source_name": str(best_inventory_entry.get("source") or "local"),
                "license_name": "local",
                "commercial_use_ok": True,
                "manifest_verified": True,
                "bgm_profile": requested_mood,
                "music_mood_selected": requested_mood,
                "music_selection_reason": selection_reason if not fallback_used else "no_asset_for_mood",
                "music_fallback_used": bool(fallback_used),
                "music_reuse_reason": reuse_reason or ("no_alternative_available" if asset_id in recent_ids else ""),
                "audio_asset_history_key": f"{audio_editorial_profile or profile}:{requested_mood}",
                "audio_asset_recently_used": list(dict.fromkeys([str(item) for item in (recent_music_asset_ids or []) if str(item)]))[-5:],
                "audio_variation_index": int(audio_variation_index or 0),
                "total_verified_bgm": len(inventory_music_assets),
                "tags": list(best_inventory_entry.get("tags") or []),
                "topics": [requested_mood],
                "music_asset_taxonomy_used": "inventory",
            }
        logger.warning(
            "MUSIC_MOOD_ASSET_MISSING mood=%s profile=%s reason=no_inventory_candidate",
            requested_mood,
            profile,
        )
    if not verified_bgm:
        # Fallback: try unverified local BGM
        unverified_bgm = list((idx.get("unverified_local") or {}).get("bgm") or [])
        if unverified_bgm:
            # Use first unverified BGM as fallback
            fallback = unverified_bgm[0]
            logger.info("[bgm-asset] matched=true (unverified fallback) asset=%s", str(fallback.get("path") or ""))
            return {
                "matched": True,
                "reason": "unverified_local_fallback",
                "path": str(fallback.get("path") or ""),
                "asset_id": "",
                "source_name": "unverified_local",
                "license_name": "",
                "commercial_use_ok": False,
                "manifest_verified": False,
                "bgm_profile": "clean_corporate",
                "music_mood_selected": "clean_corporate",
                "music_selection_reason": "unverified_local_fallback",
                "music_fallback_used": True,
                "music_reuse_reason": "no_verified_bgm",
                "audio_asset_history_key": f"{audio_editorial_profile or 'calm_trust'}:clean_corporate",
                "audio_asset_recently_used": list(dict.fromkeys([str(item) for item in (recent_music_asset_ids or []) if str(item)]))[-5:],
                "audio_variation_index": int(audio_variation_index or 0),
                "music_asset_taxonomy_used": "fallback_taxonomy",
                "total_verified_bgm": 0,
                "tags": [],
                "topics": [],
            }
        return {
            "matched": False,
            "reason": "no_verified_bgm",
            "path": None,
            "asset_id": "",
            "source_name": "",
            "license_name": "",
            "commercial_use_ok": False,
            "manifest_verified": False,
            "bgm_profile": "",
            "music_mood_selected": str(music_mood or "clean_corporate"),
            "music_selection_reason": "no_verified_bgm",
            "music_fallback_used": True,
            "music_reuse_reason": "no_verified_bgm",
            "audio_asset_history_key": f"{audio_editorial_profile or 'calm_trust'}:{music_mood or 'clean_corporate'}",
            "audio_asset_recently_used": list(dict.fromkeys([str(item) for item in (recent_music_asset_ids or []) if str(item)]))[-5:],
            "audio_variation_index": int(audio_variation_index or 0),
            "music_asset_taxonomy_used": "fallback_taxonomy",
            "total_verified_bgm": 0,
        }

    editorial_tokens = set(_norm_tokens(editorial_type) + _norm_tokens(hook_intent) + _norm_tokens(segment_text))
    profile = str(audio_editorial_profile or "").strip().lower() or "calm_trust"
    mood_requested = _normalize_music_mood_for_selection(music_mood or _AUDIO_EDITORIAL_PROFILE_RULES.get(profile, {}).get("music_mood") or "clean_corporate")
    if profile == "sensitive_sober":
        mood_requested = "sensitive_sober"
    elif profile == "no_extra_audio":
        mood_requested = "no_extra_audio"
    profile_terms = set(_audio_editorial_profile_keywords(profile))
    desired_terms = set(_norm_tokens(mood_requested)) | profile_terms | set(_norm_tokens(editorial_type)) | set(_norm_tokens(hook_intent)) | set(_norm_tokens(segment_text))
    recent_ids = {str(item) for item in (recent_music_asset_ids or []) if str(item)}
    logger.info("MUSIC_EDITORIAL_PROFILE_SELECTED profile=%s mood=%s", profile, mood_requested)
    if profile == "no_extra_audio":
        return {
            "matched": False,
            "reason": "profile_no_extra_audio",
            "path": None,
            "asset_id": "",
            "source_name": "",
            "license_name": "",
            "commercial_use_ok": False,
            "manifest_verified": True,
            "bgm_profile": profile,
            "music_mood_selected": mood_requested,
            "music_selection_reason": "profile_no_extra_audio",
            "music_fallback_used": True,
            "music_reuse_reason": "profile_no_extra_audio",
            "audio_asset_history_key": f"{audio_editorial_profile or profile}:{mood_requested}",
            "audio_asset_recently_used": list(dict.fromkeys([str(item) for item in (recent_music_asset_ids or []) if str(item)]))[-5:],
            "audio_variation_index": int(audio_variation_index or 0),
            "music_asset_taxonomy_used": "inventory",
            "total_verified_bgm": len(verified_bgm),
        }

    scored_candidates: List[Dict[str, Any]] = []
    for item in verified_bgm:
        if not bool(item.get("commercial_use_ok")):
            continue
        path = Path(str(item.get("path") or ""))
        if not path.exists() or not path.is_file():
            continue
        asset_id = str(item.get("id") or path.stem or path.name)
        blob_tokens = set(
            _norm_tokens(path.name)
            + _norm_tokens(" ".join(str(t) for t in (item.get("tags") or [])))
            + _norm_tokens(" ".join(str(t) for t in (item.get("topics") or [])))
        )
        score = len(blob_tokens & desired_terms) * 3
        score += len(blob_tokens & editorial_tokens)
        reuse_hit = asset_id in recent_ids or str(path) in recent_ids
        if reuse_hit:
            score -= 2.5
        scored_candidates.append({
            "item": item,
            "path": path,
            "asset_id": asset_id,
            "score": score,
            "reuse_hit": reuse_hit,
        })

    if not scored_candidates:
        first = next(
            (
                item
                for item in verified_bgm
                if bool(item.get("commercial_use_ok"))
                and Path(str(item.get("path") or "")).exists()
                and Path(str(item.get("path") or "")).is_file()
            ),
            None,
        )
        if not first:
            return {
                "matched": False,
                "reason": "no_usable_verified_bgm",
                "path": None,
                "asset_id": "",
                "source_name": "",
                "license_name": "",
                "commercial_use_ok": False,
                "manifest_verified": False,
                "bgm_profile": profile,
                "music_mood_selected": mood_requested,
                "music_selection_reason": "no_usable_verified_bgm",
                "music_fallback_used": True,
                "music_reuse_reason": "no_usable_verified_bgm",
                "audio_asset_history_key": f"{audio_editorial_profile or profile}:{mood_requested}",
                "audio_asset_recently_used": list(dict.fromkeys([str(item) for item in (recent_music_asset_ids or []) if str(item)]))[-5:],
                "audio_variation_index": int(audio_variation_index or 0),
                "music_asset_taxonomy_used": "fallback_taxonomy",
                "total_verified_bgm": len(verified_bgm),
            }
        scored_candidates = [{
            "item": first,
            "path": Path(str(first.get("path") or "")),
            "asset_id": str(first.get("id") or ""),
            "score": 0.0,
            "reuse_hit": False,
        }]

    scored_candidates.sort(key=lambda entry: (float(entry["score"]), not bool(entry["reuse_hit"])), reverse=True)
    non_recent_candidates = [entry for entry in scored_candidates if not bool(entry["reuse_hit"])]
    selected_entry = non_recent_candidates[0] if non_recent_candidates else scored_candidates[0]
    reuse_reason = ""
    if selected_entry["reuse_hit"]:
        reuse_reason = "recently_used_reuse" if len(scored_candidates) == 1 else "no_alternative_available"
    if int(audio_variation_index or 0) > 0 and len(scored_candidates) > 1:
        rotation_pool = non_recent_candidates or scored_candidates
        selected_entry = rotation_pool[int(audio_variation_index or 0) % len(rotation_pool)]
        if selected_entry["reuse_hit"]:
            reuse_reason = reuse_reason or "recently_used_rotation"

    best = selected_entry["item"]
    selected_path = str(selected_entry["path"] or best.get("path") or "")
    selected_asset_id = str(selected_entry["asset_id"] or best.get("id") or "")
    selection_reason = "manifest_verified_match" if float(selected_entry["score"]) > 0 else "fallback_scored_match"
    fallback_used = bool(selection_reason != "manifest_verified_match")
    logger.info(
        "MUSIC_ASSET_SELECTED asset=%s asset_id=%s mood=%s score=%.2f reuse=%s",
        Path(selected_path).name if selected_path else "",
        selected_asset_id,
        mood_requested,
        float(selected_entry["score"]),
        reuse_reason or "none",
    )
    if fallback_used or reuse_reason:
        logger.info("MUSIC_ASSET_FALLBACK_USED reason=%s mood=%s", reuse_reason or selection_reason, mood_requested)

    logger.info(
        "[bgm-asset] matched=true profile=%s asset=%s verified=true source=%s license=%s",
        profile,
        selected_path,
        str(best.get("source_name") or ""),
        str(best.get("license_name") or ""),
    )
    return {
        "matched": True,
        "reason": selection_reason,
        "path": selected_path,
        "asset_id": selected_asset_id,
        "source_name": str(best.get("source_name") or ""),
        "license_name": str(best.get("license_name") or ""),
        "commercial_use_ok": bool(best.get("commercial_use_ok")),
        "manifest_verified": True,
        "bgm_profile": profile,
        "music_mood_selected": mood_requested,
        "music_selection_reason": selection_reason,
        "music_fallback_used": bool(fallback_used),
        "music_reuse_reason": reuse_reason,
        "audio_asset_history_key": f"{audio_editorial_profile or profile}:{mood_requested}",
        "audio_asset_recently_used": list(dict.fromkeys([str(item) for item in (recent_music_asset_ids or []) if str(item)]))[-5:],
        "audio_variation_index": int(audio_variation_index or 0),
        "music_asset_taxonomy_used": "filename" if not inventory_music_assets else "inventory",
        "total_verified_bgm": len(verified_bgm),
        "tags": list(best.get("tags") or []),
        "topics": list(best.get("topics") or []),
    }
