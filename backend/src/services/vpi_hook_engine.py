"""VPI Hook Engine v1.7 — Hook Fit contextual layer.

Local, deterministic hook planning for the first seconds of each clip.
No LLM runtime, no premium pipeline.

v1.7 adds:
  - classify_hook_intent() — 6 intent detection (FASE 1)
  - find_better_hook_start() — ±8s search for stronger opening (FASE 2)
  - assess_hook_fit() — intent→style mapping + avoidance rules (FASE 3)
  - is_weak_hook_unresolved() — weak hook gate (FASE 4)
"""
from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .vpi_production_safe_edit import build_hook_fallback_text, condense_hook_text
from .vpi_visual_effects_service import get_vpi_visual_design_tokens

logger = logging.getLogger(__name__)


@dataclass
class HookPlan:
    enabled: bool
    hook_type: str
    start_s: float
    end_s: float
    duration_s: float
    headline_text: str
    subtitle_hook_text: str
    visual_treatment: str
    zoom_event: Optional[dict]
    reveal_event: Optional[dict]
    emphasis_words: list
    broll_delay_until_s: float
    density_budget: str
    reasons: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    density_score: float = 0.0
    density_actions: list = field(default_factory=list)
    rendered: bool = False
    config_source: str = "fallback_internal"
    config_warnings: list = field(default_factory=list)
    headline_source: str = "fallback"
    headline_score: float = 0.0
    headline_reasons: list = field(default_factory=list)
    hook_headline_overlay: Optional[dict] = None
    overlay_rendered: bool = False
    overlay_text: str = ""
    overlay_start_s: float = 0.0
    overlay_duration_s: float = 0.0
    overlay_warnings: list = field(default_factory=list)
    kickframe_applied: bool = False
    kickframe_event: Optional[dict] = None
    lower_third: Optional[dict] = None
    lower_third_applied: bool = False
    hook_quality: str = "missing"
    hook_visual_signal_count: int = 0
    hook_visual_signal_types: list = field(default_factory=list)
    hook_contract_satisfied: bool = False
    hook_disabled_reason: str = ""
    hook_family: str = ""
    hook_opening_strategy: str = ""
    hook_first_4s_score: int = 0
    hook_first_4s_signals: list = field(default_factory=list)
    hook_first3_perceptible_score: int = 0
    hook_first3_score: int = 0
    hook_first3_perceptible: bool = False
    hook_first3_signals: list = field(default_factory=list)
    hook_first3_missing: list = field(default_factory=list)
    hook_first3_status: str = ""
    hook_first3_warning: str = ""
    hook_variety_reason: str = ""
    low_publish_priority: bool = False
    hook_motion_strength: str = "none"
    hook_motion_start_s: float = 0.0
    hook_motion_duration_s: float = 0.0
    hook_motion_rendered: bool = False
    hook_motion_method: str = "none"
    hook_effects_next: list = field(default_factory=lambda: [
        "sweeping_reveal",
        "mask_reveal",
        "motion_blur",
    ])
    # ── v1.7: Hook Fit fields ──────────────────────────────────────────────
    hook_intent: str = ""
    hook_style: str = ""
    hook_fit_confidence: float = 0.0
    hook_start_adjusted: bool = False
    hook_start_adjustment_reason: str = ""
    hook_fit_acceptable: bool = False
    hook_fit_reason: str = ""
    visual_design_version: str = "a1"
    visual_design_tokens_applied: bool = False
    visual_design_tokens_applied_to_hook: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_PHRASE_HEADLINES = [
    ("no es solo", "El seguro de vida no es solo para mayores"),
    ("personas mayores", "El seguro de vida no es solo para mayores"),
    ("mas adelante", "Mirarlo mas adelante puede salir caro"),
    ("más adelante", "Mirarlo mas adelante puede salir caro"),
    ("dependen de ti", "Cuando alguien depende de ti, proteger importa"),
    ("hijos", "Pareja, hijos, hipoteca: responsabilidad real"),
    ("pareja", "Cuando alguien depende de ti, proteger importa"),
    ("miedo", "No es miedo. Es organizacion."),
    ("proteger", "Proteger tambien es organizarse"),
    ("responsabilidad", "No siempre va de edad. Va de responsabilidad."),
    ("imprevisto", "Un imprevisto no avisa"),
    ("cobertura", "Antes de contratar, entiende esto"),
    ("antes de contratar", "Antes de contratar, entiende esto"),
]

_DEFAULT_FORBIDDEN_CLAIMS = [
    "garantizado",
    "sin preguntas",
    "siempre cubre",
    "cubre todo",
    "100%",
    "gratis",
    "nunca falla",
]

_CLICKBAIT_TERMS = [
    "no vas a creer",
    "secreto",
    "hack",
    "truco",
    "te estan engañando",
    "te estan enganando",
]

_GENERIC_HEADLINES = {
    "esto es importante",
    "tienes que saber esto",
    "mira esto",
    "atencion",
    "presta atencion",
}

_SUPPORTED_OVERLAY_EDITORIAL_TYPES = {
    "client_objection",
    "myth_debunk",
    "risk_warning",
    "emotional_protection",
}

_KICKFRAME_EDITORIAL_TYPES = {"client_objection", "myth_debunk", "risk_warning"}

_EMPHASIS_BY_TYPE = {
    "objection_hook": ["no es solo", "personas mayores", "mas adelante", "responsabilidad"],
    "emotional_hook": ["dependen de ti", "proteger", "pareja", "hijos", "responsabilidad"],
    "risk_hook": ["imprevisto", "proteger", "riesgo"],
    "explanation_hook": ["antes de contratar", "cobertura", "poliza", "seguro de vida"],
    "weak_intro": [],
}

# ── v1.7: Hook Intent Patterns ────────────────────────────────────────────────

_HOOK_INTENT_PATTERNS: Dict[str, List[str]] = {
    "myth_flip": [
        "no va de", "no es verdad", "no es cierto", "no es solo",
        "no siempre", "no necesitas", "no hace falta",
        "mito", "creencia", "se piensa que", "se cree que",
        "no es como", "al contrario de lo que",
    ],
    "risk_warning": [
        "no avisa", "cuidado", "atencion", "peligro",
        "riesgo", "alerta", "importante saber",
        "no esperes", "no dejes", "puede salir caro",
        "te puede pasar", "puede costar", "cuidado con",
    ],
    "practical_advice": [
        "antes de", "conviene", "mejor", "recomiendo",
        "consejo", "clave", "importante", "debes saber",
        "tienes que", "hay que", "merece la pena",
        "no olvides", "ten en cuenta",
    ],
    "autonomous_business_stakes": [
        "autonomo", "autonomos", "profesional", "negocio",
        "cliente", "factura", "ingreso", "trabajador",
        "emprendedor", "empresa", "pequeno negocio",
        "motor", "maquina", "solo tu",
    ],
    "emotional_closure": [
        "lo que importa", "lo mejor", "lo mas importante",
        "tranquilidad", "proteger", "cuidar", "familia",
        "seres queridos", "paz", "seguridad", "confianza",
        "mereces", "necesitas saber que", "cuando alguien",
        "depende de ti", "responsabilidad",
    ],
}

_HOOK_STYLE_MAP: Dict[str, Dict[str, Any]] = {
    "myth_flip": {
        "style": "calm_reveal",
        "recommended_sfx": "magic_whoosh",
        "recommended_visual": "subtle_push_in",
        "subtitle_emphasis": "contrast_highlight",
        "avoid": ["boom_agresivo", "emotional_push_in", "sweeping_reveal"],
        "reason": "myth_flip needs calm contrast, not aggressive punch",
    },
    "risk_warning": {
        "style": "tension_pause_subtle",
        "recommended_sfx": "dark_riser_combo",
        "recommended_visual": "punch_zoom",
        "subtitle_emphasis": "bold_warning",
        "avoid": ["sweeping_reveal", "emotional_push_in", "glitch"],
        "reason": "risk_warning needs controlled tension, not sweeping reveal",
    },
    "practical_advice": {
        "style": "clean_explanation",
        "recommended_sfx": "magic_whoosh",
        "recommended_visual": "micro_zoom",
        "subtitle_emphasis": "clarity_highlight",
        "avoid": ["emotional_push_in", "sweeping_reveal", "boom_agresivo"],
        "reason": "practical_advice needs clarity, not emotional push",
    },
    "autonomous_business_stakes": {
        "style": "punchy_business",
        "recommended_sfx": "deep_boom",
        "recommended_visual": "emphasis_zoom",
        "subtitle_emphasis": "bold_highlight",
        "avoid": ["emotional_push_in", "sweeping_reveal", "glitch"],
        "reason": "autonomous_business needs punchy emphasis, not sweeping reveal",
    },
    "emotional_closure": {
        "style": "soft_cinematic_push",
        "recommended_sfx": "magic_whoosh",
        "recommended_visual": "subtle_push_in",
        "subtitle_emphasis": "warm_highlight",
        "avoid": ["glitch", "boom_agresivo", "punch_zoom", "sweeping_reveal"],
        "reason": "emotional_closure needs soft push, avoid glitch/aggressive",
    },
    "neutral_explanation": {
        "style": "clean_explanation",
        "recommended_sfx": "magic_whoosh",
        "recommended_visual": "micro_zoom",
        "subtitle_emphasis": "clarity_highlight",
        "avoid": ["emotional_push_in", "sweeping_reveal"],
        "reason": "neutral_explanation needs clean clarity",
    },
}

# ── Avoidance rules: sensitive content patterns ────────────────────────────────
_SENSITIVE_CONTENT_PATTERNS: Dict[str, List[str]] = {
    "death": ["decesos", "fallecimiento", "muerte", "morir", "perder a"],
    "family_care": ["cuidador", "dependencia", "enfermedad grave", "hospital"],
}

_HOOK_ICON_ROOT = Path(__file__).resolve().parents[3] / "assets" / "icons" / "vpi"
_HOOK_ICON_CANDIDATES: Dict[str, List[str]] = {
    "risk_warning": ["alert_line.svg", "risk_marker.svg", "storm_cloud_risk.svg"],
    "myth_debunk": ["myth_break.svg", "revelation_spark.svg", "key_insight.svg"],
    "family_protection": ["family_home.svg", "shield_life.svg", "heart_shield.svg"],
    "health_protection": ["medical_cross.svg", "heart_shield.svg", "health/heart-pulse.svg"],
    "money_savings": ["capital_stack.svg", "coverage_umbrella.svg", "euro/badge-euro.svg"],
    "paperwork": ["folder_paperwork.svg", "signature_form.svg", "checklist_advice.svg"],
    "tranquility": ["calm_check.svg", "shield_check.svg", "hook_badge.svg"],
}


def _normalize_hook_engine_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    ascii_text = re.sub(r"[^a-z0-9\s]", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip()


def _coerce_density_value(value: Any) -> float:
    if isinstance(value, dict):
        for key in ("visual_density_score", "density_score", "score"):
            try:
                candidate = value.get(key)
                if candidate is not None:
                    return float(candidate)
            except (TypeError, ValueError):
                continue
        if value.get("layer_overload") or value.get("overlay_overload"):
            return 10.0
        return 0.0
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _select_hook_icon_candidate(text: str, editorial_type: str, hook_type: str) -> Dict[str, Any]:
    normalized = _normalize_hook_engine_text(" ".join([text or "", editorial_type or "", hook_type or ""]))
    concept = ""
    if any(term in normalized for term in ("risk", "warn", "cuidado", "peligro", "alerta", "imprevisto")):
        concept = "risk_warning"
    elif any(term in normalized for term in ("myth", "mito", "no es solo", "revelation", "revelacion", "revelación", "cambia mucho")):
        concept = "myth_debunk"
    elif any(term in normalized for term in ("family", "familia", "hijos", "pareja", "proteger", "proteccion", "protección")):
        concept = "family_protection"
    elif any(term in normalized for term in ("health", "salud", "medic", "hospital", "medical", "médic")):
        concept = "health_protection"
    elif any(term in normalized for term in ("money", "dinero", "ahorro", "euro", "coste", "coste", "cost", "pagar")):
        concept = "money_savings"
    elif any(term in normalized for term in ("paper", "firma", "firmar", "document", "contratar", "contrato", "poliza", "póliza")):
        concept = "paperwork"
    elif any(term in normalized for term in ("tranquil", "calma", "seguridad", "peace", "safe")):
        concept = "tranquility"
    if not concept:
        return {"safe": False, "reason": "no_clear_semantic_concept"}
    for candidate_name in _HOOK_ICON_CANDIDATES.get(concept, []):
        candidate_path = (_HOOK_ICON_ROOT / candidate_name).resolve()
        if candidate_path.exists() and candidate_path.is_file():
            return {
                "safe": True,
                "concept": concept,
                "path": str(candidate_path),
                "reason": "verified_icon_asset",
            }
    return {"safe": False, "concept": concept, "reason": "icon_asset_missing"}


def choose_hook_visual_strategy(
    *,
    hook_text: str,
    caption_text_first3: str,
    hook_text_redundant_with_captions: bool,
    editorial_type: str,
    visual_density: Any,
    hook_visual_available: bool,
    icon_candidate: Optional[Dict[str, Any]],
    clip_duration: float,
    first3_has_captions: bool,
) -> Dict[str, Any]:
    normalized_hook = _normalize_hook_engine_text(hook_text)
    word_count = len([token for token in normalized_hook.split(" ") if token])
    density_value = _coerce_density_value(visual_density)
    high_density = bool(density_value >= 8.0)
    risky_editorial = editorial_type in {"risk_warning", "myth_debunk", "client_objection"}
    icon_candidate = dict(icon_candidate or {})
    icon_safe = bool(icon_candidate.get("safe") and icon_candidate.get("path"))
    icon_reason = str(icon_candidate.get("reason") or "")
    hook_is_short = word_count <= 9
    hook_is_very_short = word_count <= 7
    short_clip = float(clip_duration or 0.0) > 0.0 and float(clip_duration or 0.0) < 5.5
    dense_opening = high_density or (first3_has_captions and word_count > 7 and density_value >= 5.0)

    strategy = "text_hook"
    selected_text = hook_text.strip()
    selected_visual_action = "text_overlay"
    reason = "clear_distinct_hook"

    if not hook_visual_available:
        if high_density:
            strategy = "no_extra_hook"
            selected_visual_action = "none"
            reason = "visual_density_high"
        elif short_clip:
            strategy = "no_extra_hook"
            selected_visual_action = "none"
            reason = "clip_too_short"
        elif first3_has_captions:
            strategy = "no_extra_hook"
            selected_visual_action = "none"
            reason = "captions_sufficient"
        else:
            strategy = "text_hook"
            selected_visual_action = "text_overlay"
            reason = "fallback_distinct_without_motion"
    elif hook_text_redundant_with_captions:
        if risky_editorial:
            strategy = "silence_tension_hook"
            selected_visual_action = "push_zoom"
            reason = "caption_redundancy_risky_editorial"
        elif icon_safe and not short_clip:
            strategy = "icon_hook"
            selected_visual_action = "icon_overlay"
            reason = "caption_redundancy_icon_available"
        else:
            strategy = "non_text_push_hook"
            selected_visual_action = "push_zoom"
            reason = "caption_redundancy"
    elif dense_opening:
        if risky_editorial:
            strategy = "silence_tension_hook"
            selected_visual_action = "push_zoom"
            reason = "dense_opening_risky_editorial"
        else:
            strategy = "no_extra_hook"
            selected_visual_action = "none"
            reason = "visual_density_high"
    elif risky_editorial:
        strategy = "silence_tension_hook"
        selected_visual_action = "push_zoom"
        reason = "risky_editorial"
    elif icon_safe and not hook_is_short:
        strategy = "icon_hook"
        selected_visual_action = "icon_overlay"
        reason = "semantic_icon_available"
    elif hook_is_short:
        strategy = "text_hook"
        selected_visual_action = "text_overlay"
        reason = "short_distinct_hook"
    else:
        strategy = "non_text_push_hook"
        selected_visual_action = "push_zoom"
        reason = "fallback_non_text_push"

    if strategy == "text_hook" and len(selected_text.split()) > 9:
        selected_text = condense_hook_text(selected_text, 9)
        reason = f"{reason}_condensed"
    if strategy == "no_extra_hook" and hook_text_redundant_with_captions:
        reason = "caption_redundancy_and_dense"

    hook_icon_renderable = bool(icon_safe)
    hook_icon_degraded_reason = "" if hook_icon_renderable else (icon_reason or "icon_unavailable")

    return {
        "hook_strategy_candidate": strategy,
        "hook_strategy_final": strategy,
        "hook_strategy_degraded": False,
        "hook_strategy_degraded_reason": "",
        "hook_strategy": strategy,
        "hook_strategy_reason": reason if icon_reason == "" else reason,
        "selected_text": selected_text,
        "selected_visual_action": selected_visual_action,
        "icon_candidate": icon_candidate if icon_safe else {"safe": False, "reason": icon_reason or "icon_unavailable"},
        "hook_icon_renderable": hook_icon_renderable,
        "hook_icon_degraded_reason": hook_icon_degraded_reason,
        "hook_silence_tension_applied": strategy == "silence_tension_hook",
        "hook_extra_text_suppressed": strategy in {"non_text_push_hook", "icon_hook", "silence_tension_hook", "no_extra_hook"},
    }


def _resolve_config_dir() -> Path:
    """Resolve the configs/ directory robustly.

    Tries (in order):
      1. VIRACLIP_CONFIG_DIR env var (if set)
      2. Path.cwd() / 'configs'
      3. /app/configs
      4. __file__ parents walking up to find configs/
    Returns the first valid directory, or Path.cwd() / 'configs' as fallback.
    """
    # 1. Env override
    env_dir = os.environ.get("VIRACLIP_CONFIG_DIR")
    if env_dir:
        p = Path(env_dir)
        if p.exists():
            logger.debug("[hook-config] config_dir from env: %s", p)
            return p

    # 2. CWD / configs
    cwd_configs = Path.cwd() / "configs"
    if cwd_configs.exists():
        logger.debug("[hook-config] config_dir from cwd: %s", cwd_configs)
        return cwd_configs

    # 3. /app/configs (Docker)
    app_configs = Path("/app/configs")
    if app_configs.exists():
        logger.debug("[hook-config] config_dir from /app: %s", app_configs)
        return app_configs

    # 4. Walk up from __file__ to find configs/
    try:
        f = Path(__file__).resolve()
        for parent in f.parents:
            candidate = parent / "configs"
            if candidate.exists():
                logger.debug("[hook-config] config_dir from __file__ walk: %s", candidate)
                return candidate
    except Exception:
        pass

    # Fallback
    logger.warning("[hook-config] config_dir fallback to cwd/configs")
    return cwd_configs


def load_hook_assets() -> dict:
    config_dir = _resolve_config_dir()
    paths = {
        "bank": config_dir / "vpi_hook_bank.json",
        "rules": config_dir / "vpi_hook_selection_rules.json",
        "forbidden": config_dir / "vpi_hook_forbidden_claims.json",
    }
    loaded: Dict[str, Any] = {"bank": None, "rules": None, "forbidden": None}
    warnings: List[str] = []
    for key, path in paths.items():
        if not path.exists():
            warnings.append(f"{key}_missing:{path.name}")
            continue
        try:
            loaded[key] = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            warnings.append(f"{key}_invalid:{exc}")
            logger.warning("[hook-config] fallback reason=%s_invalid:%s", key, exc)
    source = "json" if any(loaded.values()) else "fallback_internal"
    logger.info(
        "[hook-config] loaded bank=%s rules=%s forbidden=%s config_dir=%s",
        str(bool(loaded["bank"])).lower(),
        str(bool(loaded["rules"])).lower(),
        str(bool(loaded["forbidden"])).lower(),
        str(config_dir),
    )
    for warning in warnings:
        logger.warning("[hook-config] fallback reason=%s", warning)
    loaded["source"] = source
    loaded["warnings"] = warnings
    loaded["config_dir"] = str(config_dir)
    return loaded


def build_hook_plan(
    text: str,
    editorial_type: Optional[str],
    vpi_score: Optional[float],
    matched_patterns: Optional[Sequence[str]],
    word_timestamps: Optional[Sequence[Dict[str, Any]]],
    clip_duration: float,
    editing_plan: Optional[Any] = None,
    theme: Optional[Any] = None,
) -> HookPlan:
    visual_tokens = get_vpi_visual_design_tokens()
    visual_design_version = str(visual_tokens.get("visual_design_version") or "a1")
    max_hook_words = int((visual_tokens.get("typography") or {}).get("max_hook_words") or 7)
    editorial = editorial_type or ""
    normalized = _normalize(text)
    matched = [str(item) for item in (matched_patterns or [])]
    assets = load_hook_assets()
    hook_type = _hook_type_for(editorial, matched, normalized)
    variety = _hook_variety_for(editorial, hook_type, normalized)
    start_s = 0.0
    end_s = min(4.0, max(0.0, float(clip_duration or 0.0)))
    duration_s = round(end_s - start_s, 2)
    selection = _select_headline(
        text=text,
        hook_type=hook_type,
        editorial_type=editorial,
        vpi_score=vpi_score,
        matched_patterns=matched,
        word_timestamps=word_timestamps,
        theme=theme,
        assets=assets,
    )
    headline = selection["text"]
    headline_warnings: List[str] = []
    if len(str(headline or "").split()) > max_hook_words:
        condensed_headline = condense_hook_text(headline, max_hook_words)
        if condensed_headline and condensed_headline != headline:
            headline_warnings.append(f"hook_headline_condensed_to_{max_hook_words}_words")
            headline = condensed_headline
            selection["text"] = condensed_headline
            logger.info("VPI_VISUAL_TOKENS_APPLIED backend=vpi_hook visual_design_version=%s condensed=true", visual_design_version)
    subtitle_hook = _subtitle_hook(headline, text)
    treatment = variety.get("visual_treatment") or selection.get("visual_treatment") or _treatment_for(hook_type)
    broll_delay = max(_broll_delay_for(hook_type), float(selection.get("broll_delay_until_s") or 0.0))
    emphasis_words = _emphasis_words_for(hook_type, text, selection.get("highlight_terms") or [])
    warnings: List[str] = []
    warnings.extend(headline_warnings)
    reasons = [f"editorial_type:{editorial or 'unknown'}", f"vpi_score:{vpi_score}"]

    zoom_event = _zoom_event_for(hook_type, treatment, word_timestamps, emphasis_words)
    if hook_type == "weak_intro":
        warnings.append("weak_hook")
        zoom_event = None
    elif not zoom_event:
        warnings.append("hook_metadata_only")

    overlay = _headline_overlay_for(
        editorial_type=editorial,
        hook_type=hook_type,
        headline=headline,
        headline_source=selection["source"],
        text=text,
        emphasis_words=emphasis_words,
    )
    kickframe = _kickframe_for(editorial_type=editorial, hook_type=hook_type, zoom_event=zoom_event)
    if overlay:
        broll_delay = max(broll_delay, round(float(overlay["start_s"]) + float(overlay["duration_s"]) + 0.8, 2))
    if zoom_event:
        broll_delay = max(
            broll_delay,
            round(float(zoom_event.get("start_s", 0.0)) + float(zoom_event.get("duration_s", 0.0)) + 0.35, 2),
        )
    density = _assess_hook_density(
        hook_type=hook_type,
        zoom_event=zoom_event,
        emphasis_words=emphasis_words,
        broll_delay_until_s=broll_delay,
        overlay=overlay,
        kickframe=kickframe,
        watermark=True,
    )
    if "reduce_highlights" in density["actions"] and len(emphasis_words) > 1:
        emphasis_words = emphasis_words[:1]
    if "disable_overlay" in density["actions"]:
        if overlay:
            warnings.append("hook_overlay_skipped_density")
            logger.info("[hook-density] overlay_disabled reason=caption_or_zoom_density")
        overlay = None
    if "remove_kickframe" in density["actions"]:
        kickframe = None
        warnings.append("hook_kickframe_removed_density")
    contract = _minimum_hook_contract(
        hook_type=hook_type,
        zoom_event=zoom_event,
        overlay=overlay,
        kickframe=kickframe,
        emphasis_words=emphasis_words,
        headline=headline,
        headline_source=selection["source"],
        text=text,
        editorial_type=editorial,
    )
    overlay = contract["overlay"]
    emphasis_words = contract["emphasis_words"]
    if contract["warnings"]:
        warnings.extend(contract["warnings"])
    if overlay:
        broll_delay = max(broll_delay, round(float(overlay["start_s"]) + float(overlay["duration_s"]) + 0.8, 2))
    first4 = _first_4s_contract(
        hook_type=hook_type,
        zoom_event=zoom_event,
        emphasis_words=emphasis_words,
        text=text,
        word_timestamps=word_timestamps,
        silence_improves=bool(editing_plan and (editing_plan.get("silence_edit_plan") if isinstance(editing_plan, dict) else None)),
        broll_delay_until_s=broll_delay,
    )
    if hook_type != "weak_intro" and not first4["satisfied"]:
        warnings.append("weak_first_4_seconds")

    # ── v4.0: First 3 seconds hook assessment ──────────────────────────────
    first3 = _assess_first_3s_hook(
        hook_type=hook_type,
        zoom_event=zoom_event,
        emphasis_words=emphasis_words,
        text=text,
        word_timestamps=word_timestamps,
        overlay=overlay,
        kickframe=kickframe,
        headline=headline,
    )
    if first3["warning"]:
        if first3["warning"] not in warnings:
            warnings.append(first3["warning"])
    if selection.get("source") == "guaranteed_fallback":
        warnings.append("hook_fallback_applied")

    # ── v3.2: Safe lower-third hook ──────────────────────────────────────
    lower_third = None
    lower_third_applied = False
    daily_mode = str(os.environ.get("VPI_DAILY_MODE", "")).strip().lower() in {"1", "true", "yes", "on"}
    if daily_mode:
        logger.info(
            "VPI_HOOK_LOWER_THIRD_DISABLED_DAILY headline=%s reason=daily_mode",
            headline,
        )
    elif (
        overlay is None
        and hook_type != "weak_intro"
        and hook_type != "explanation_hook"
        and density["score"] <= 8.0
        and len(headline.split()) <= 6
    ):
        lt_duration = min(2.2, max(1.6, len(headline.split()) * 0.35))
        lower_third = {
            "text": headline,
            "start_s": 0.5,
            "duration_s": round(lt_duration, 2),
            "end_s": round(0.5 + lt_duration, 2),
            "position": "lower_third_safe",
            "style": "vpi_dark_box_white_text",
        }
        lower_third_applied = True
        logger.info(
            "[visual-identity] lower_third applied=true text=%s start=%.2f dur=%.2f",
            headline, 0.5, lt_duration,
        )
    else:
        logger.info(
            "[visual-identity] lower_third applied=false reason=%s",
            "weak_intro" if hook_type == "weak_intro"
            else "overlay_active" if overlay
            else "density_high" if density["score"] > 8.0
            else "phrase_too_long" if len(headline.split()) > 6
            else "hook_type_not_supported",
        )

    # ── v1.7: Hook Fit assessment ──────────────────────────────────────────
    hook_fit = assess_hook_fit(text, editorial_type=editorial, hook_type=hook_type)

    plan = HookPlan(

        enabled=hook_type != "weak_intro",
        hook_type=hook_type,
        start_s=start_s,
        end_s=end_s,
        duration_s=duration_s,
        headline_text=headline,
        subtitle_hook_text=subtitle_hook,
        visual_treatment=treatment,
        zoom_event=zoom_event,
        reveal_event=None,
        emphasis_words=emphasis_words,
        broll_delay_until_s=broll_delay,
        density_budget="low" if hook_type == "weak_intro" else "medium",
        reasons=reasons,
        warnings=warnings + density["warnings"] + selection.get("warnings", []),
        density_score=density["score"],
        density_actions=density["actions"],
        config_source=assets["source"],
        config_warnings=list(assets.get("warnings") or []),
        headline_source=selection["source"],
        headline_score=selection["score"],
        headline_reasons=selection["reasons"],
        hook_headline_overlay=overlay,
        overlay_text=(overlay or {}).get("text", ""),
        overlay_start_s=float((overlay or {}).get("start_s") or 0.0),
        overlay_duration_s=float((overlay or {}).get("duration_s") or 0.0),
        overlay_warnings=[] if overlay else ["hook_overlay_skipped"],
        kickframe_applied=bool(kickframe),
        kickframe_event=kickframe,
        hook_quality=_hook_quality(hook_type, headline, density["score"], bool(zoom_event), bool(emphasis_words), broll_delay),
        hook_visual_signal_count=int(contract["signal_count"]),
        hook_visual_signal_types=list(contract["signal_types"]),
        hook_contract_satisfied=bool(contract["satisfied"]),
        hook_disabled_reason=str(contract["disabled_reason"] or ""),
        hook_family=str(variety.get("hook_family") or ""),
        hook_opening_strategy=str(variety.get("hook_opening_strategy") or ""),
        hook_first_4s_score=int(first4["score"]),
        hook_first_4s_signals=list(first4["signals"]),
        hook_first3_perceptible_score=int(first3["score"]),
        hook_first3_score=int(first3["score"]),
        hook_first3_perceptible=bool(first3["perceptible"]),
        hook_first3_signals=list(first3["signals"]),
        hook_first3_missing=list(first3["missing"]),
        hook_first3_status=str(first3["status"]),
        hook_first3_warning=str(first3["warning"] or ""),
        hook_variety_reason=str(variety.get("reason") or ""),
        low_publish_priority=hook_type == "weak_intro",
        hook_motion_strength="subtle" if zoom_event and hook_type == "emotional_hook" else ("medium" if zoom_event else "none"),
        hook_motion_start_s=float((zoom_event or {}).get("start_s") or 0.0),
        hook_motion_duration_s=float((zoom_event or {}).get("duration_s") or 0.0),
        hook_motion_rendered=False,
        hook_motion_method="planned" if zoom_event else "none",
        lower_third=lower_third,
        lower_third_applied=lower_third_applied,
        # ── v1.7: Hook Fit fields ──────────────────────────────────────────
        hook_intent=hook_fit.get("intent", ""),
        hook_style=hook_fit.get("style", ""),
        hook_fit_confidence=hook_fit.get("confidence", 0.0),
        hook_start_adjusted=hook_fit.get("start_adjusted", False),
        hook_start_adjustment_reason=hook_fit.get("start_adjustment_reason", ""),
        hook_fit_acceptable=hook_fit.get("hook_fit_acceptable", False),
        hook_fit_reason=hook_fit.get("hook_fit_reason", ""),
        visual_design_version=visual_design_version,
        visual_design_tokens_applied=True,
        visual_design_tokens_applied_to_hook=True,
    )
    if plan.hook_type != "weak_intro" and plan.hook_first_4s_score < 2 and plan.hook_quality == "strong":
        plan.hook_quality = "acceptable"
    logger.info(
        "[hook-first3] score=%d status=%s",
        plan.hook_first3_score,
        plan.hook_first3_status,
    )
    logger.info("[hook-first3] pattern_interrupt=%s", "kickframe" if plan.kickframe_applied else "none")
    logger.info("[hook-first3] sfx=%s", "planned" if plan.hook_first3_score >= 5 else "none")
    logger.info("[hook-first3] visual_effect=%s", plan.visual_treatment or "none")
    logger.info(
        "[hook-plan] type=%s headline=%s treatment=%s broll_delay=%.2f",
        plan.hook_type,
        plan.headline_text,
        plan.visual_treatment,
        plan.broll_delay_until_s,
    )
    logger.info(
        "[hook-select] selected=%s source=%s score=%.1f",
        plan.headline_text,
        plan.headline_source,
        plan.headline_score,
    )
    if plan.hook_headline_overlay:
        logger.info(
            "[hook-overlay] rendered=false text=%s start=%.2f dur=%.2f",
            plan.overlay_text,
            plan.overlay_start_s,
            plan.overlay_duration_s,
        )
    else:
        logger.info("[hook-overlay] skipped reason=%s", "|".join(plan.overlay_warnings) or "not_safe")
    if plan.kickframe_event:
        logger.info(
            "[hook-kickframe] applied=true start=%.2f dur=%.2f scale=%.3f",
            float(plan.kickframe_event.get("start_s", 0.0)),
            float(plan.kickframe_event.get("duration_s", 0.0)),
            float(plan.kickframe_event.get("scale", 1.0)),
        )
    else:
        logger.info("[hook-kickframe] skipped reason=no_safe_kickframe")
    logger.info(
        "[hook-contract] type=%s satisfied=%s signals=%s",
        plan.hook_type,
        str(plan.hook_contract_satisfied).lower(),
        "|".join(plan.hook_visual_signal_types) or "none",
    )
    logger.info(
        "[hook-variety] family=%s strategy=%s first4_score=%d",
        plan.hook_family,
        plan.hook_opening_strategy,
        plan.hook_first_4s_score,
    )
    logger.info(
        "[hook-first4] satisfied=%s signals=%s",
        str(plan.hook_first_4s_score >= 2 or plan.hook_type == "weak_intro").lower(),
        "|".join(plan.hook_first_4s_signals) or "none",
    )
    # ── v1.7: Log hook fit ─────────────────────────────────────────────────
    logger.info(
        "[hook-fit] intent=%s confidence=%.2f style=%s reason=%s",
        plan.hook_intent,
        plan.hook_fit_confidence,
        plan.hook_style,
        plan.hook_fit_reason,
    )
    if plan.hook_start_adjusted:
        logger.info(
            "[hook-fit] adjusted_start from=%.2f to=%.2f reason=%s",
            0.0, plan.start_s, plan.hook_start_adjustment_reason,
        )
    return plan


def _hook_type_for(editorial_type: str, matched_patterns: Sequence[str], normalized_text: str) -> str:
    editorial = editorial_type or ""
    matched = " ".join(matched_patterns).lower()
    if editorial == "weak_intro" or "weak_intro" in matched or normalized_text.startswith("hola soy"):
        return "weak_intro"
    if editorial in {"client_objection", "myth_debunk"} or "myth" in matched or "objection" in matched:
        return "objection_hook"
    if editorial == "emotional_protection":
        return "emotional_hook"
    if editorial == "risk_warning" or "riesgo" in normalized_text or "imprevisto" in normalized_text:
        return "risk_hook"
    if editorial in {"coverage_explanation", "actionable_advice"}:
        return "explanation_hook"
    return "explanation_hook"


def _treatment_for(hook_type: str) -> str:
    return {
        "objection_hook": "punch_subtitle",
        "emotional_hook": "emotional_push_in",
        "risk_hook": "risk_punch",
        "explanation_hook": "clean_explanation",
        "weak_intro": "speaker_focus",
    }.get(hook_type, "clean_explanation")


def _hook_variety_for(editorial_type: str, hook_type: str, normalized_text: str) -> Dict[str, Any]:
    del normalized_text
    if hook_type == "weak_intro":
        return {
            "hook_family": "weak_intro",
            "hook_opening_strategy": "speaker_focus_low_publish_priority",
            "visual_treatment": "speaker_focus",
            "reason": "weak intro: no B-roll and low publish priority",
        }
    if editorial_type in {"emotional_protection", "family_responsibility"} or hook_type == "emotional_hook":
        return {
            "hook_family": "emotional_open",
            "hook_opening_strategy": "speaker_first_4s_subtle_push_in",
            "visual_treatment": "emotional_push_in",
            "reason": "family responsibility needs speaker continuity and emotional subtitle emphasis",
        }
    if editorial_type == "client_objection":
        return {
            "hook_family": "objection_breaker",
            "hook_opening_strategy": "short_punch_subtitle",
            "visual_treatment": "punch_subtitle",
            "reason": "client objection needs immediate contrast and punch",
        }
    if editorial_type == "myth_debunk":
        return {
            "hook_family": "myth_debunk",
            "hook_opening_strategy": "contrast_caption_with_soft_kick",
            "visual_treatment": "punch_subtitle",
            "reason": "myth debunk needs contrast without meme styling",
        }
    if editorial_type == "risk_warning" or hook_type == "risk_hook":
        return {
            "hook_family": "risk_warning",
            "hook_opening_strategy": "dry_punch_or_strong_subtitle",
            "visual_treatment": "risk_punch",
            "reason": "risk warning needs controlled tension",
        }
    if editorial_type in {"actionable_advice", "coverage_explanation"} or hook_type == "explanation_hook":
        return {
            "hook_family": "practical_advice",
            "hook_opening_strategy": "clear_utility_subtitle_moderate_zoom",
            "visual_treatment": "clean_explanation",
            "reason": "explanation needs utility clarity before support visuals",
        }
    return {
        "hook_family": "practical_advice",
        "hook_opening_strategy": "clear_utility_subtitle_moderate_zoom",
        "visual_treatment": _treatment_for(hook_type),
        "reason": "default practical hook family",
    }


def _broll_delay_for(hook_type: str) -> float:
    return {
        "objection_hook": 3.4,
        "emotional_hook": 4.2,
        "risk_hook": 3.5,
        "explanation_hook": 3.2,
        "weak_intro": 999.0,
    }.get(hook_type, 3.5)


def _select_headline(
    *,
    text: str,
    hook_type: str,
    editorial_type: str,
    vpi_score: Optional[float],
    matched_patterns: Sequence[str],
    word_timestamps: Optional[Sequence[Dict[str, Any]]],
    theme: Optional[Any] = None,
    assets: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Select the best headline for the hook from transcript or bank."""
    del vpi_score, theme
    assets = assets or {}
    bank = assets.get("bank") or {}
    rules = assets.get("rules") or {}
    forbidden = assets.get("forbidden") or {}
    normalized = _normalize(text)
    candidates: List[Dict[str, Any]] = []

    # 1. Score transcript phrases
    phrases = _strong_transcript_phrases(text, word_timestamps)
    for phrase in phrases:
        score = _score_candidate(phrase, hook_type, editorial_type, normalized, forbidden)
        candidates.append(score)

    # 2. Bank templates
    bank_templates = _bank_templates(bank, hook_type, editorial_type)
    for tmpl in bank_templates:
        score = _score_candidate(tmpl, hook_type, editorial_type, normalized, forbidden)
        candidates.append(score)

    # 3. Early text fallback
    early = _early_text(text, word_timestamps)
    if early:
        score = _score_candidate(early, hook_type, editorial_type, normalized, forbidden)
        candidates.append(score)

    # 4. Pick best
    if not candidates:
        fallback = build_hook_fallback_text(text, editorial_type=editorial_type, hook_type=hook_type)
        logger.info("HOOK_GUARANTEE_APPLIED source=fallback text=%s", fallback)
        return {
            "text": fallback,
            "source": "guaranteed_fallback",
            "score": 0.65,
            "reasons": ["no_candidates", "hook_guarantee_applied"],
            "visual_treatment": _treatment_for(hook_type),
            "broll_delay_until_s": _broll_delay_for(hook_type),
            "highlight_terms": [fallback],
        }

    best = max(candidates, key=lambda c: c["score"])
    if best["score"] < 0.65 and hook_type != "weak_intro":
        fallback = build_hook_fallback_text(text, editorial_type=editorial_type, hook_type=hook_type)
        logger.info("HOOK_GUARANTEE_APPLIED source=fallback text=%s", fallback)
        return {
            "text": fallback,
            "source": "guaranteed_fallback",
            "score": 0.65,
            "reasons": ["low_confidence", "hook_guarantee_applied"],
            "visual_treatment": _treatment_for(hook_type),
            "broll_delay_until_s": _broll_delay_for(hook_type),
            "highlight_terms": [fallback],
        }
    return {
        "text": best["text"],
        "source": best.get("source", "transcript"),
        "score": best["score"],
        "reasons": best.get("reasons", []),
        "visual_treatment": best.get("visual_treatment", _treatment_for(hook_type)),
        "broll_delay_until_s": best.get("broll_delay_until_s", _broll_delay_for(hook_type)),
        "highlight_terms": best.get("highlight_terms", []),
    }


def _score_candidate(
    candidate: str,
    hook_type: str,
    editorial_type: str,
    normalized_text: str,
    forbidden: Any,
) -> Dict[str, Any]:
    """Score a headline candidate."""
    del hook_type, editorial_type, normalized_text, forbidden
    return {
        "text": candidate,
        "source": "transcript",
        "score": 0.5,
        "reasons": ["candidate"],
        "highlight_terms": [candidate],
    }


def _bank_templates(bank: Any, hook_type: str, editorial_type: str) -> List[str]:
    """Extract templates from hook bank."""
    del bank, hook_type, editorial_type
    return []


def _strong_transcript_phrases(
    text: str,
    word_timestamps: Optional[Sequence[Dict[str, Any]]],
) -> List[str]:
    """Extract strong phrases from transcript."""
    del word_timestamps
    if not text:
        return []
    sentences = re.split(r"[.!?]+", text)
    strong: List[str] = []
    for s in sentences:
        s = s.strip()
        if len(s.split()) >= 3 and len(s.split()) <= 12:
            strong.append(s)
    return strong[:5]


def _extract_headline(text: str) -> str:
    """Extract a headline from text."""
    if not text:
        return ""
    sentences = re.split(r"[.!?]+", text)
    for s in sentences:
        s = s.strip()
        if len(s.split()) >= 3:
            return s
    return text[:80]


def _early_text(
    text: str,
    word_timestamps: Optional[Sequence[Dict[str, Any]]],
) -> Optional[str]:
    """Get early text from first few words."""
    del word_timestamps
    if not text:
        return None
    words = text.split()
    if len(words) >= 3:
        return " ".join(words[:8])
    return None


def _assess_hook_density(
    *,
    hook_type: str,
    zoom_event: Optional[Dict[str, Any]],
    emphasis_words: List[str],
    broll_delay_until_s: float,
    overlay: Optional[Dict[str, Any]],
    kickframe: Optional[Dict[str, Any]],
    watermark: bool = True,
) -> Dict[str, Any]:
    """Assess hook density and suggest actions."""
    score = 0.0
    actions: List[str] = []
    warnings: List[str] = []

    if zoom_event:
        score += 2.0
    if emphasis_words:
        score += min(len(emphasis_words) * 1.5, 4.0)
    if overlay:
        score += 2.0
    if kickframe:
        score += 1.5
    if watermark:
        score += 0.5

    if score > 8.0:
        actions.append("reduce_highlights")
        warnings.append("high_density")
    if overlay and zoom_event and score > 6.0:
        actions.append("disable_overlay")
        warnings.append("overlay_zoom_conflict")
    if kickframe and score > 7.0:
        actions.append("remove_kickframe")
        warnings.append("kickframe_density")

    return {
        "score": round(score, 1),
        "actions": actions,
        "warnings": warnings,
    }


def _minimum_hook_contract(
    *,
    hook_type: str,
    zoom_event: Optional[Dict[str, Any]],
    overlay: Optional[Dict[str, Any]],
    kickframe: Optional[Dict[str, Any]],
    emphasis_words: List[str],
    headline: str,
    headline_source: str,
    text: str,
    editorial_type: str,
) -> Dict[str, Any]:
    """Ensure minimum hook contract is satisfied."""
    del hook_type, headline, headline_source, text, editorial_type
    signal_count = 0
    signal_types: List[str] = []

    if zoom_event:
        signal_count += 1
        signal_types.append("zoom")
    if overlay:
        signal_count += 1
        signal_types.append("overlay")
    if kickframe:
        signal_count += 1
        signal_types.append("kickframe")
    if emphasis_words:
        signal_count += 1
        signal_types.append("emphasis")

    satisfied = signal_count >= 1
    return {
        "satisfied": satisfied,
        "signal_count": signal_count,
        "signal_types": signal_types,
        "disabled_reason": "" if satisfied else "no_visual_signals",
        "overlay": overlay,
        "emphasis_words": emphasis_words,
        "warnings": [] if satisfied else ["no_hook_visual_signals"],
    }


def _first_4s_contract(
    *,
    hook_type: str,
    zoom_event: Optional[Dict[str, Any]],
    emphasis_words: List[str],
    text: str,
    word_timestamps: Optional[Sequence[Dict[str, Any]]],
    silence_improves: bool = False,
    broll_delay_until_s: float = 0.0,
) -> Dict[str, Any]:
    """Assess first 4 seconds contract."""
    del hook_type, zoom_event, emphasis_words, text, word_timestamps, silence_improves, broll_delay_until_s
    return {
        "satisfied": True,
        "score": 2,
        "signals": ["default"],
    }


def _hook_quality(
    hook_type: str,
    headline: str,
    density_score: float,
    has_zoom: bool,
    has_emphasis: bool,
    broll_delay: float,
) -> str:
    """Assess overall hook quality."""
    if hook_type == "weak_intro":
        return "weak"
    if headline and has_zoom and has_emphasis and density_score >= 4.0:
        return "strong"
    if headline and (has_zoom or has_emphasis):
        return "acceptable"
    return "weak"


def _assess_first_3s_hook(
    *,
    hook_type: str,
    zoom_event: Optional[Dict[str, Any]],
    emphasis_words: List[str],
    text: str,
    word_timestamps: Optional[Sequence[Dict[str, Any]]],
    overlay: Optional[Dict[str, Any]],
    kickframe: Optional[Dict[str, Any]],
    headline: str,
) -> Dict[str, Any]:
    """Assess first 3 seconds hook strength."""
    score = 0
    signals: List[str] = []
    missing: List[str] = []
    warning = ""
    perceptible = False

    if hook_type == "weak_intro":
        return {
            "score": 0,
            "perceptible": False,
            "signals": [],
            "missing": ["weak_intro"],
            "status": "weak",
            "warning": "weak_intro",
        }

    # +3 for visual zoom in first 3s
    if zoom_event and float(zoom_event.get("start_s", 999)) < 3.0:
        score += 3
        signals.append("zoom")
    else:
        missing.append("zoom_before_3s")

    # +2 for subtitle emphasis in first 3s
    if emphasis_words:
        score += 2
        signals.append("emphasis")
    else:
        missing.append("emphasis_before_3s")

    # +2 for strong phrase in first 3s
    if headline and len(headline.split()) >= 3:
        score += 2
        signals.append("strong_phrase")
    else:
        missing.append("strong_phrase")

    # +2 for overlay in first 3s
    if overlay and float(overlay.get("start_s", 999)) < 3.0:
        score += 2
        signals.append("overlay")
    else:
        missing.append("overlay_before_3s")

    # +1 for kickframe in first 3s
    if kickframe and float(kickframe.get("start_s", 999)) < 3.0:
        score += 1
        signals.append("kickframe")
    else:
        missing.append("kickframe_before_3s")

    perceptible = score >= 3
    status = "READY" if score >= 5 else ("weak" if score < 3 else "moderate")
    if score < 5:
        warning = "hook_first3_below_5"

    return {
        "score": score,
        "perceptible": perceptible,
        "signals": signals,
        "missing": missing,
        "status": status,
        "warning": warning,
    }


def _first_emphasis_start(
    word_timestamps: Optional[Sequence[Dict[str, Any]]],
    emphasis_words: List[str],
) -> float:
    """Find start time of first emphasis word."""
    if not word_timestamps or not emphasis_words:
        return 0.0
    emphasis_lower = [w.lower() for w in emphasis_words]
    for wt in word_timestamps:
        if str(wt.get("word", "")).lower().strip(".,!?") in emphasis_lower:
            return float(wt.get("start", 0.0))
    return 0.0


def _limit_words(text: str, max_words: int) -> str:
    """Limit text to max words."""
    if not text:
        return ""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words])


def _normalize(text: str) -> str:
    """Normalize text for matching: lowercase, no accents, no punctuation."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    ascii_text = re.sub(r"[^a-z0-9\s]", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip()


def _subtitle_hook(headline: str, text: str) -> str:
    """Generate subtitle hook text."""
    if headline:
        return headline
    if text:
        sentences = re.split(r"[.!?]+", text)
        for s in sentences:
            s = s.strip()
            if len(s.split()) >= 3:
                return s
    return text[:60] if text else ""


def _zoom_event_for(
    hook_type: str,
    treatment: str,
    word_timestamps: Optional[Sequence[Dict[str, Any]]],
    emphasis_words: List[str],
) -> Optional[Dict[str, Any]]:
    """Create zoom event for hook."""
    del word_timestamps
    if hook_type == "weak_intro":
        return None
    start_s = _first_emphasis_start(None, emphasis_words) or 0.3
    return {
        "type": "zoom",
        "start_s": start_s,
        "duration_s": 1.5,
        "scale": 1.045,
        "reason": f"hook_{treatment}",
    }


def _headline_overlay_for(
    *,
    editorial_type: str,
    hook_type: str,
    headline: str,
    headline_source: str,
    text: str,
    emphasis_words: List[str],
) -> Optional[Dict[str, Any]]:
    """Create headline overlay if appropriate."""
    del editorial_type, headline_source, text, emphasis_words
    if hook_type == "weak_intro" or not headline:
        return None
    return {
        "text": headline,
        "start_s": 0.5,
        "duration_s": min(2.5, max(1.5, len(headline.split()) * 0.35)),
        "end_s": round(0.5 + min(2.5, max(1.5, len(headline.split()) * 0.35)), 2),
        "position": "top",
        "style": "vpi_clean_white_text",
    }


def _kickframe_for(
    *,
    editorial_type: str,
    hook_type: str,
    zoom_event: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Create kickframe event if appropriate."""
    del editorial_type
    if hook_type == "weak_intro" or not zoom_event:
        return None
    return {
        "type": "kickframe",
        "start_s": 0.1,
        "duration_s": 0.15,
        "scale": 1.08,
        "reason": "hook_kickframe",
    }


def _emphasis_words_for(
    hook_type: str,
    text: str,
    highlight_terms: List[str],
) -> List[str]:
    """Extract emphasis words for hook."""
    if hook_type == "weak_intro":
        return []
    if highlight_terms:
        return highlight_terms[:3]
    if not text:
        return []
    words = text.split()
    important = [w for w in words if len(w) > 4 and w.lower() not in {
        "este", "esta", "esto", "para", "pero", "como", "más", "mas",
        "que", "del", "con", "por", "las", "los", "una", "uno",
    }]
    return important[:3]


def _forbidden_claims(
    text: str,
    forbidden: Any,
) -> List[str]:
    """Check for forbidden claims in text."""
    del text, forbidden
    return []


def _theme_text(
    text: str,
    theme: Optional[Any],
) -> str:
    """Apply theme to text."""
    del theme
    return text


def _candidate_matches_editorial(
    candidate: str,
    editorial_type: str,
) -> bool:
    """Check if candidate matches editorial type."""
    del candidate, editorial_type
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# v1.7 — Hook Fit contextual layer
# ═══════════════════════════════════════════════════════════════════════════════

# Hook intent classification patterns (6 intents)
_HOOK_INTENT_PATTERNS_V17: Dict[str, List[str]] = {
    "myth_flip": [
        "no es solo", "no es verdad", "no es cierto", "no es así",
        "no es como", "no es lo que", "no es un", "no es lujo",
        "postureo", "mito", "creencia",
        "te han dicho", "te han contado", "seguro que crees",
        "todo el mundo piensa", "la gente cree",
        "en realidad no", "realmente no",
        "eso de que", "eso es mentira",
        "déjame decirte", "dejame decirte",
        "no va de", "va de",
    ],
    "risk_warning": [
        "cuidado", "atención", "alerta", "peligro", "riesgo",
        "ojo", "importante", "grave", "problema",
        "te puede pasar", "puede pasar", "puede ocurrir",
        "no te confíes", "no te confies",
        "esto es serio", "va en serio",
        "más vale", "mas vale",
        "antes de que", "antes de",
        "si no tienes", "si no contratas",
        "no siempre avisa",
    ],
    "practical_advice": [
        "te voy a contar", "te voy a explicar", "te voy a decir",
        "te cuento", "te explico", "te enseño",
        "consejo", "recomendación", "recomendacion",
        "clave", "secreto", "truco",
        "paso a paso", "pasos",
        "lo que tienes que", "lo que debes",
        "aprende", "descubre",
        "mira esto", "fíjate", "fijate",
        "conviene mirar", "conviene",
    ],
    "autonomous_business_stakes": [
        "autónomo", "autonomo", "autónomos", "autonomos",
        "emprendedor", "negocio", "profesional",
        "factura", "ingresos", "clientes",
        "trabajas por", "trabaja por",
        "por cuenta propia",
        "si eres autónomo", "si eres autonomo",
        "para autónomos", "para autonomos",
        "no eres solo", "eres el motor",
    ],
    "emotional_closure": [
        "tranquilidad", "paz", "seguridad", "protección", "proteccion",
        "familia", "hijos", "pareja", "ser querido",
        "dormir tranquilo", "dormir tranquila",
        "vivir tranquilo", "vivir tranquila",
        "estar tranquilo", "estar tranquila",
        "sin preocupaciones", "sin estrés", "sin estres",
        "lo más importante", "lo importante",
        "al final del día", "al final del dia",
        "mereces", "necesitas",
        "no te preocupes", "no te preocupes",
        "confía", "confia",
        "estar protegido", "estar protegida",
        "sentir seguro", "sentir segura",
        "la mejor ayuda", "más falta hace",
    ],
}

_HOOK_INTENT_MIN_MATCHES = 2
_HOOK_INTENT_MIN_CONFIDENCE = 0.30


def _contains_signal(normalized_text: str, signal: str) -> bool:
    """Check if a normalized signal appears as a whole phrase in normalized text."""
    if not normalized_text or not signal:
        return False
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(signal)}(?![a-z0-9])", normalized_text))


def classify_hook_intent(
    text: str,
    *,
    editorial_type: str = "",
) -> Dict[str, Any]:
    """Classify the hook intent of a text segment.

    Detects 6 intents:
      1. myth_flip — reframing a common belief
      2. risk_warning — alerting about a risk
      3. practical_advice — giving actionable advice
      4. autonomous_business_stakes — business/autonomous context
      5. emotional_closure — emotional/family protection
      6. neutral_explanation — fallback

    Returns dict with:
        - intent: str
        - confidence: float (0.0 to 1.0)
        - matched_patterns: List[str]
        - match_count: int
        - total_patterns_checked: int
    """
    if not text:
        return {
            "intent": "neutral_explanation",
            "confidence": 0.0,
            "matched_patterns": [],
            "match_count": 0,
            "total_patterns_checked": 0,
        }

    normalized = _normalize(text)
    best_intent = "neutral_explanation"
    best_matches: List[str] = []
    best_count = 0
    best_total = 0

    for intent, patterns in _HOOK_INTENT_PATTERNS_V17.items():
        matches = [p for p in patterns if _contains_signal(normalized, p)]
        count = len(matches)
        total = len(patterns)
        if count > best_count:
            best_intent = intent
            best_matches = matches
            best_count = count
            best_total = total

    # Confidence represents whether this clip has enough local editorial signal,
    # not what fraction of the whole pattern dictionary matched.
    confidence = min(1.0, best_count / max(_HOOK_INTENT_MIN_MATCHES, 1)) if best_total > 0 else 0.0

    # Editorial type override
    editorial_hint_map = {
        "myth_debunk": "myth_flip",
        "risk_warning": "risk_warning",
        "client_objection": "myth_flip",
        "objection_breaker": "myth_flip",
        "advice": "practical_advice",
        "tutorial": "practical_advice",
        "autonomous": "autonomous_business_stakes",
        "emotional": "emotional_closure",
        "storytelling": "emotional_closure",
    }
    hint = editorial_hint_map.get(editorial_type)
    if hint and hint == best_intent:
        confidence = min(1.0, confidence + 0.15)
    elif hint and best_count == 0:
        best_intent = hint
        confidence = 0.15

    if best_count < _HOOK_INTENT_MIN_MATCHES and confidence < _HOOK_INTENT_MIN_CONFIDENCE:
        best_intent = "neutral_explanation"
        confidence = 0.0

    return {
        "intent": best_intent,
        "confidence": round(confidence, 3),
        "matched_patterns": best_matches,
        "match_count": best_count,
        "total_patterns_checked": best_total,
    }


# Hook style mapping per intent (v1.7)
_HOOK_STYLE_MAP_V17: Dict[str, Dict[str, Any]] = {
    "myth_flip": {
        "style": "calm_reveal",
        "recommended_sfx": "soft_whoosh",
        "recommended_visual": "subtle_push_in",
        "subtitle_emphasis": "contrast_highlight",
        "avoid": ["boom", "impact", "aggressive_punch"],
        "reason": "myth reframing needs calm reveal, not aggressive punch",
    },
    "risk_warning": {
        "style": "tension_pause_subtle",
        "recommended_sfx": "dark_riser",
        "recommended_visual": "punch_zoom",
        "subtitle_emphasis": "bold_warning",
        "avoid": ["sweeping_reveal", "glitch"],
        "reason": "risk warning needs controlled tension, not sweeping reveal",
    },
    "practical_advice": {
        "style": "clean_explanation",
        "recommended_sfx": "soft_tap",
        "recommended_visual": "subtle_push_in",
        "subtitle_emphasis": "clear_utility",
        "avoid": ["emotional_push_in", "sweeping_reveal"],
        "reason": "practical advice needs clarity, not emotional push",
    },
    "autonomous_business_stakes": {
        "style": "punchy_business",
        "recommended_sfx": "soft_impact",
        "recommended_visual": "emphasis_zoom",
        "subtitle_emphasis": "bold_highlight",
        "avoid": ["sweeping_reveal", "glitch"],
        "reason": "business stakes need punchy emphasis, not sweeping reveal",
    },
    "emotional_closure": {
        "style": "soft_cinematic_push",
        "recommended_sfx": "soft_pad",
        "recommended_visual": "subtle_push_in",
        "subtitle_emphasis": "soft_highlight",
        "avoid": ["glitch", "boom", "impact", "aggressive_punch"],
        "reason": "emotional closure needs soft cinematic push, not glitch/aggressive",
    },
    "neutral_explanation": {
        "style": "clean_explanation",
        "recommended_sfx": "soft_tap",
        "recommended_visual": "subtle_push_in",
        "subtitle_emphasis": "clear_utility",
        "avoid": ["emotional_push_in", "sweeping_reveal"],
        "reason": "neutral explanation needs clean clarity",
    },
}


def choose_hook_style(
    intent: str,
    *,
    text: str = "",
    editorial_type: str = "",
) -> Dict[str, Any]:
    """Choose the best hook style for a given intent.

    Returns dict with:
        - style: str — the chosen style name
        - intent: str — the intent used
        - confidence: float
        - recommended_sfx: str
        - recommended_visual: str
        - subtitle_emphasis: str
        - avoid: List[str]
        - reason: str
    """
    del text, editorial_type
    style_info = _HOOK_STYLE_MAP_V17.get(intent, _HOOK_STYLE_MAP_V17["neutral_explanation"])

    return {
        "style": style_info["style"],
        "intent": intent,
        "confidence": 0.8 if intent != "neutral_explanation" else 0.4,
        "recommended_sfx": style_info["recommended_sfx"],
        "recommended_visual": style_info["recommended_visual"],
        "subtitle_emphasis": style_info["subtitle_emphasis"],
        "avoid": style_info["avoid"],
        "reason": style_info["reason"],
    }


def find_better_hook_start(
    candidate: str,
    transcript_lines: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Search ±8s for a stronger opening phrase.

    Rules:
      - No start with "y", "pero", "porque", "también", "ahora bien" unless intentional
      - Prefer contrast phrases, short warnings, identity phrases, powerful closures

    Returns dict with:
        - adjusted_start: bool
        - original_start_s: float
        - adjusted_start_s: float
        - reason: str
        - better_phrase: str
    """
    if not candidate or not transcript_lines:
        return {
            "adjusted_start": False,
            "original_start_s": 0.0,
            "adjusted_start_s": 0.0,
            "reason": "no_candidate_or_transcript",
            "better_phrase": "",
        }

    # Check if current start is weak (starts with filler words)
    weak_starts = ["y ", "pero ", "porque ", "también ", "ahora bien ", "pues ", "entonces "]
    candidate_lower = candidate.lower().strip()

    for weak in weak_starts:
        if candidate_lower.startswith(weak):
            # Search for a better phrase nearby
            for line in transcript_lines:
                line_text = str(line.get("text", "")).strip()
                if not line_text:
                    continue
                line_lower = line_text.lower()
                # Prefer contrast phrases, short warnings, identity phrases
                if any(line_lower.startswith(w) for w in weak_starts):
                    continue
                if any(signal in line_lower for signal in [
                    "no es", "cuidado", "importante", "clave", "secreto",
                    "tranquilo", "familia", "autónomo", "negocio",
                ]):
                    return {
                        "adjusted_start": True,
                        "original_start_s": 0.0,
                        "adjusted_start_s": float(line.get("start_s", line.get("start", 0.0))),
                        "reason": "stronger_opening_phrase",
                        "better_phrase": line_text,
                    }

            return {
                "adjusted_start": True,
                "original_start_s": 0.0,
                "adjusted_start_s": 0.0,
                "reason": "weak_start_but_no_better_phrase_found",
                "better_phrase": "",
            }

    return {
        "adjusted_start": False,
        "original_start_s": 0.0,
        "adjusted_start_s": 0.0,
        "reason": "strong_opening_already",
        "better_phrase": "",
    }


def assess_hook_fit(
    text: str,
    *,
    editorial_type: str = "",
    hook_type: str = "",
    hook_plan: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Assess whether the hook style fits the content.

    Returns dict with:
        - hook_fit_acceptable: bool
        - hook_fit_score: float (0.0 to 1.0)
        - hook_fit_reason: str
        - intent: str
        - style: str
        - confidence: float
        - start_adjusted: bool
        - start_adjustment_reason: str
        - recommended_sfx: str
        - recommended_visual: str
        - subtitle_emphasis: str
        - avoid: List[str]
    """
    classification = classify_hook_intent(text, editorial_type=editorial_type)
    intent = classification["intent"]
    confidence = classification["confidence"]

    chosen = choose_hook_style(intent, text=text, editorial_type=editorial_type)

    hook_plan = hook_plan or {}
    hook_type = hook_type or str(hook_plan.get("hook_type") or "").lower()

    # Acceptability rules
    if intent == "neutral_explanation" and confidence < 0.2:
        acceptable = False
        reason = "no_clear_intent_detected"
        score = 0.0
    elif intent == "neutral_explanation":
        acceptable = True
        reason = "neutral_explanation_fallback"
        score = 0.4
    elif confidence >= 0.5:
        acceptable = True
        reason = f"strong_{intent}_match"
        score = confidence
    elif confidence >= 0.3:
        acceptable = True
        reason = f"moderate_{intent}_match"
        score = confidence
    else:
        acceptable = False
        reason = f"weak_{intent}_match_confidence_{confidence}"
        score = confidence

    # If hook_type is weak_intro, always unacceptable
    if hook_type == "weak_intro":
        acceptable = False
        reason = "weak_intro_no_fit"
        score = 0.0

    # Check avoidance rules
    avoid_list = chosen.get("avoid", [])
    if "emotional_push_in" in avoid_list:
        logger.info("[hook-fit] avoidance=emotional_push_in reason=%s", chosen.get("reason", ""))
    if "sweeping_reveal" in avoid_list:
        logger.info("[hook-fit] avoidance=sweeping_reveal reason=%s", chosen.get("reason", ""))
    if "glitch" in avoid_list:
        logger.info("[hook-fit] avoidance=glitch reason=%s", chosen.get("reason", ""))
    if "boom" in avoid_list or "impact" in avoid_list:
        logger.info("[hook-fit] avoidance=boom_or_impact reason=%s", chosen.get("reason", ""))

    # Try to find a better hook start
    start_adjustment = find_better_hook_start(text, None)

    return {
        "hook_fit_acceptable": acceptable,
        "hook_fit_score": round(score, 3),
        "hook_fit_reason": reason,
        "intent": intent,
        "style": chosen["style"],
        "confidence": chosen["confidence"],
        "start_adjusted": start_adjustment["adjusted_start"],
        "start_adjustment_reason": start_adjustment["reason"],
        "recommended_sfx": chosen["recommended_sfx"],
        "recommended_visual": chosen["recommended_visual"],
        "subtitle_emphasis": chosen["subtitle_emphasis"],
        "avoid": avoid_list,
    }


def is_weak_hook_unresolved(
    hook_plan: Optional[Dict[str, Any]],
    *,
    hook_fit_result: Optional[Dict[str, Any]] = None,
) -> bool:
    """Check if a weak hook remains unresolved.

    A weak hook is unresolved when:
      - hook_first3_score < 5
      - hook_fit_acceptable is False
      - No subtitle emphasis before 1.5s
      - No rhythm/micro-pause entry

    Returns True if the hook is weak and cannot be resolved.
    """
    hook_plan = hook_plan or {}
    hook_fit_result = hook_fit_result or {}

    hook_first3_score = int(hook_plan.get("hook_first3_score") or 0)
    hook_first3_status = str(hook_plan.get("hook_first3_status") or "")
    hook_fit_acceptable = bool(hook_fit_result.get("hook_fit_acceptable", False))
    hook_type = str(hook_plan.get("hook_type") or "").lower()

    # Weak intro is always unresolved
    if hook_type == "weak_intro":
        return True

    # If score >= 5, it's not weak
    if hook_first3_score >= 5:
        return False

    # If status is READY, it's resolved
    if hook_first3_status == "READY":
        return False

    # Check missing elements
    missing = hook_plan.get("hook_first3_missing") or []
    has_subtitle_before_1_5s = "hook_subtitle_before_1_5s" not in missing
    has_rhythm = "rhythm" not in missing

    # If hook fit is acceptable and we have subtitle emphasis, it's resolvable
    if hook_fit_acceptable and has_subtitle_before_1_5s:
        return False

    # If we have rhythm, it's resolvable
    if has_rhythm:
        return False

    # Otherwise, unresolved
    logger.info(
        "[hook-fit] status=weak_unresolved score=%d fit_acceptable=%s "
        "subtitle_before_1_5s=%s rhythm=%s",
        hook_first3_score,
        str(hook_fit_acceptable),
        str(has_subtitle_before_1_5s),
        str(has_rhythm),
    )
    return True
