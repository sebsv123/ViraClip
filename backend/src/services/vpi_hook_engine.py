"""VPI Hook Engine v1.6.

Local, deterministic hook planning for the first seconds of each clip.
No LLM runtime, no premium pipeline.
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
    subtitle_hook = _subtitle_hook(headline, text)
    treatment = variety.get("visual_treatment") or selection.get("visual_treatment") or _treatment_for(hook_type)
    broll_delay = max(_broll_delay_for(hook_type), float(selection.get("broll_delay_until_s") or 0.0))
    emphasis_words = _emphasis_words_for(hook_type, text, selection.get("highlight_terms") or [])
    warnings: List[str] = []
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

    # ── v3.2: Safe lower-third hook ──────────────────────────────────────
    # Micro lower-third for strong hooks when overlay not used.
    # Max 2.2s, short phrase, not if density > 8, not in weak_intro.
    lower_third = None
    lower_third_applied = False
    if (
        overlay is None
        and hook_type != "weak_intro"
        and hook_type != "explanation_hook"
        and density["score"] <= 8.0
        and len(headline.split()) <= 6
    ):
        # Strong hooks (objection, emotional, risk) get a micro lower-third
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
    theme: Optional[Any],
    assets: Dict[str, Any],
) -> Dict[str, Any]:
    early_text = _early_text(text, word_timestamps, max_s=8.0)
    full_norm = _normalize(text)
    early_norm = _normalize(early_text)
    candidates: List[Dict[str, Any]] = []

    for phrase in _strong_transcript_phrases(early_text):
        candidates.append({"text": phrase, "source": "transcript", "visual_treatment": _treatment_for(hook_type)})
    for phrase, headline in _PHRASE_HEADLINES:
        if _normalize(phrase) in early_norm:
            candidates.append({"text": headline, "source": "transcript", "visual_treatment": _treatment_for(hook_type)})
    for template in _bank_templates(assets.get("bank"), editorial_type, hook_type):
        candidates.append(template)
    candidates.append({
        "text": _extract_headline(text, hook_type, word_timestamps),
        "source": "fallback",
        "visual_treatment": _treatment_for(hook_type),
    })

    forbidden = _forbidden_claims(assets.get("forbidden"))
    theme_text = _theme_text(theme)
    best: Optional[Dict[str, Any]] = None
    for raw in candidates:
        scored = _score_candidate(
            raw,
            editorial_type=editorial_type,
            hook_type=hook_type,
            vpi_score=vpi_score,
            matched_patterns=matched_patterns,
            early_norm=early_norm,
            full_norm=full_norm,
            theme_text=theme_text,
            forbidden=forbidden,
        )
        logger.info(
            "[hook-select] candidate=%s score=%.1f reasons=%s",
            scored["text"],
            scored["score"],
            "|".join(scored["reasons"]),
        )
        if best is None or scored["score"] > best["score"]:
            best = scored
    assert best is not None
    if best["source"] != "transcript":
        transcript_candidates = [
            _score_candidate(
                c,
                editorial_type=editorial_type,
                hook_type=hook_type,
                vpi_score=vpi_score,
                matched_patterns=matched_patterns,
                early_norm=early_norm,
                full_norm=full_norm,
                theme_text=theme_text,
                forbidden=forbidden,
            )
            for c in candidates
            if c["source"] == "transcript"
        ]
        best_transcript = max(transcript_candidates, key=lambda item: item["score"]) if transcript_candidates else None
        if best_transcript and best_transcript["score"] >= 35 and best_transcript["score"] >= best["score"] - 20:
            best = best_transcript
    if hook_type == "weak_intro":
        best["source"] = "fallback"
        best["text"] = _limit_words((text or "").strip(), 10) or "Valentin Proteccion Integral"
        best["score"] = min(best["score"], 20.0)
        best.setdefault("warnings", []).append("weak_hook")
    best["text"] = _limit_words(best["text"], 10)
    return best


def _score_candidate(
    candidate: Dict[str, Any],
    *,
    editorial_type: str,
    hook_type: str,
    vpi_score: Optional[float],
    matched_patterns: Sequence[str],
    early_norm: str,
    full_norm: str,
    theme_text: str,
    forbidden: Sequence[str],
) -> Dict[str, Any]:
    text = str(candidate.get("text") or "").strip()
    norm = _normalize(text)
    source = str(candidate.get("source") or "template")
    score = 0.0
    reasons: List[str] = []
    warnings: List[str] = []
    if norm and (norm in early_norm or any(_normalize(part) in early_norm for part in text.split(".") if part.strip())):
        score += 35
        source = "transcript"
        reasons.append("transcript_phrase_match:+35")
    if _candidate_matches_editorial(candidate, editorial_type, hook_type, matched_patterns):
        score += 25
        reasons.append("editorial_type_match:+25")
    if theme_text and any(token in norm for token in _normalize(theme_text).split() if len(token) > 4):
        score += 20
        reasons.append("theme_match:+20")
    words = text.split()
    if 3 <= len(words) <= 10:
        score += 15
        reasons.append("short_and_clear:+15")
    if any(_normalize(item) in norm for item in forbidden):
        score -= 100
        warnings.append("contains_forbidden_claim")
        reasons.append("contains_forbidden_claim:-100")
    if any(_normalize(item) in norm for item in _CLICKBAIT_TERMS):
        score -= 40
        warnings.append("too_clickbait")
        reasons.append("too_clickbait:-40")
    if norm in _GENERIC_HEADLINES or len(words) < 3:
        score -= 30
        warnings.append("too_generic")
        reasons.append("too_generic:-30")
    if source != "transcript" and norm and norm not in full_norm:
        score -= 35
        warnings.append("not_supported_by_transcript")
        reasons.append("not_supported_by_transcript:-35")
    if vpi_score is not None and float(vpi_score or 0.0) >= 85:
        score += 5
        reasons.append("high_vpi:+5")
    return {
        **candidate,
        "text": text,
        "source": source,
        "score": round(score, 1),
        "reasons": reasons or ["fallback"],
        "warnings": warnings,
        "broll_delay_until_s": candidate.get("broll_delay_until_s") or candidate.get("recommended_broll_delay"),
        "highlight_terms": candidate.get("highlight_terms") or [],
    }


def _bank_templates(bank: Any, editorial_type: str, hook_type: str) -> List[Dict[str, Any]]:
    if not isinstance(bank, dict):
        return []
    keys = [editorial_type]
    if hook_type == "objection_hook":
        keys.extend(["client_objection", "myth_debunk"])
    elif hook_type == "risk_hook":
        keys.append("risk_warning")
    elif hook_type == "emotional_hook":
        keys.append("emotional_protection")
    elif hook_type == "explanation_hook":
        keys.extend(["coverage_explanation", "actionable_advice"])
    out: List[Dict[str, Any]] = []
    for key in dict.fromkeys(keys):
        value = bank.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and item.get("text"):
                    out.append({
                        "text": str(item.get("text")),
                        "source": "template",
                        "editorial_type": key,
                        "visual_treatment": item.get("visual_treatment") or _treatment_for(hook_type),
                        "recommended_broll_delay": item.get("recommended_broll_delay"),
                        "highlight_terms": item.get("highlight_terms") or [],
                    })
    return out


def _strong_transcript_phrases(text: str) -> List[str]:
    chunks = re.split(r"[.!?\n]+", text or "")
    out: List[str] = []
    for chunk in chunks:
        cleaned = " ".join(chunk.strip(" ,;:").split())
        words = cleaned.split()
        norm = _normalize(cleaned)
        if 4 <= len(words) <= 10 and any(_normalize(term) in norm for term, _ in _PHRASE_HEADLINES):
            out.append(cleaned)
    return out[:3]


def _extract_headline(text: str, hook_type: str, word_timestamps: Optional[Sequence[Dict[str, Any]]]) -> str:
    early_text = _early_text(text, word_timestamps, max_s=8.0)
    normalized = _normalize(early_text)
    for phrase, headline in _PHRASE_HEADLINES:
        if _normalize(phrase) in normalized:
            return _limit_words(headline, 12)
    defaults = {
        "objection_hook": "No siempre va de edad. Va de responsabilidad.",
        "emotional_hook": "Cuando alguien depende de ti, proteger importa",
        "risk_hook": "Un imprevisto no avisa",
        "explanation_hook": "Antes de contratar, entiende esto",
        "weak_intro": _limit_words((text or "").strip(), 10) or "Valentin Proteccion Integral",
    }
    return defaults.get(hook_type, "Antes de contratar, entiende esto")


def _subtitle_hook(headline: str, text: str) -> str:
    normalized_text = _normalize(text)
    normalized_headline = _normalize(headline)
    if normalized_headline and normalized_headline in normalized_text:
        return headline
    for phrase, _ in _PHRASE_HEADLINES:
        if _normalize(phrase) in normalized_text:
            return phrase
    return headline


def _candidate_matches_editorial(
    candidate: Dict[str, Any],
    editorial_type: str,
    hook_type: str,
    matched_patterns: Sequence[str],
) -> bool:
    candidate_editorial = str(candidate.get("editorial_type") or "")
    if candidate_editorial and candidate_editorial == editorial_type:
        return True
    matched = " ".join(matched_patterns).lower()
    return (
        (hook_type == "objection_hook" and editorial_type in {"client_objection", "myth_debunk"})
        or (hook_type == "emotional_hook" and editorial_type == "emotional_protection")
        or (hook_type == "risk_hook" and editorial_type == "risk_warning")
        or (hook_type == "explanation_hook" and editorial_type in {"coverage_explanation", "actionable_advice"})
        or ("myth" in matched and candidate_editorial == "myth_debunk")
    )


def _forbidden_claims(raw: Any) -> List[str]:
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item).strip()] or list(_DEFAULT_FORBIDDEN_CLAIMS)
    if isinstance(raw, dict):
        for key in ("forbidden_claims", "claims", "terms"):
            value = raw.get(key)
            if isinstance(value, list):
                return [str(item) for item in value if str(item).strip()] or list(_DEFAULT_FORBIDDEN_CLAIMS)
    return list(_DEFAULT_FORBIDDEN_CLAIMS)


def _theme_text(theme: Optional[Any]) -> str:
    if theme is None:
        return ""
    if isinstance(theme, dict):
        return " ".join(str(theme.get(key) or "") for key in ("central_topic", "domain", "topic"))
    return " ".join(
        str(getattr(theme, key, "") or "")
        for key in ("central_topic", "domain", "topic")
    )


def _emphasis_words_for(hook_type: str, text: str, extra_terms: Optional[Sequence[str]] = None) -> List[str]:
    normalized = _normalize(text)
    selected: List[str] = []
    for term in list(extra_terms or []) + _EMPHASIS_BY_TYPE.get(hook_type, []):
        if _normalize(term) in normalized:
            selected.append(term)
    deduped: List[str] = []
    for term in selected:
        if term not in deduped:
            deduped.append(term)
    return deduped[:3]


def _headline_overlay_for(
    *,
    editorial_type: str,
    hook_type: str,
    headline: str,
    headline_source: str,
    text: str,
    emphasis_words: Sequence[str],
) -> Optional[Dict[str, Any]]:
    words = (headline or "").split()
    if hook_type == "weak_intro" or editorial_type not in _SUPPORTED_OVERLAY_EDITORIAL_TYPES:
        return None
    if editorial_type == "emotional_protection" and len(words) > 7:
        return None
    if not 3 <= len(words) <= 10:
        return None
    normalized_headline = _normalize(headline)
    if normalized_headline and normalized_headline in _normalize(text) and emphasis_words:
        # Captions can carry the exact hook; density guard may still keep overlay if safe.
        pass
    if headline_source not in {"transcript", "template"}:
        return None
    duration = 1.8 if len(words) <= 7 else 2.1
    return {
        "text": headline,
        "start_s": 0.35,
        "duration_s": round(min(2.2, max(1.6, duration)), 2),
        "end_s": round(min(2.65, 0.35 + duration), 2),
        "position": "upper_mid_safe",
        "style": "vpi_blue_dark_box_orange_accent",
        "source": headline_source,
    }


def _kickframe_for(
    *,
    editorial_type: str,
    hook_type: str,
    zoom_event: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if editorial_type not in _KICKFRAME_EDITORIAL_TYPES or hook_type == "weak_intro":
        return None
    start = 0.45
    if zoom_event:
        start = float(zoom_event.get("start_s", start) or start)
    return {
        "start_s": round(min(0.8, max(0.25, start)), 2),
        "duration_s": 0.22,
        "scale": 1.04,
        "brightness": 0.018,
        "contrast": 1.025,
        "integrated_with_zoom": bool(zoom_event),
        "reason": f"hook_kickframe:{editorial_type}",
    }


def _zoom_event_for(
    hook_type: str,
    treatment: str,
    word_timestamps: Optional[Sequence[Dict[str, Any]]],
    emphasis_words: Sequence[str],
) -> Optional[Dict[str, Any]]:
    if hook_type == "weak_intro":
        return None
    start = _first_emphasis_start(word_timestamps, emphasis_words)
    if start is None:
        start = 0.45
    start = min(0.8, max(0.25, start))
    if treatment == "emotional_push_in":
        duration = 1.7
        scale = 1.035
    elif treatment == "clean_explanation":
        duration = 1.0
        scale = 1.015
    else:
        duration = 0.55
        scale = 1.05
    return {
        "start_s": round(start, 2),
        "duration_s": duration,
        "scale": scale,
        "reason": f"hook:{hook_type}",
        "hook": True,
    }


def _strong_phrase_starts_before_2s(
    word_timestamps: Optional[Sequence[Dict[str, Any]]],
    emphasis_words: Sequence[str],
    text: str,
) -> bool:
    if not word_timestamps:
        return bool(_strong_transcript_phrases(" ".join((text or "").split()[:16])))
    wanted = [_normalize(item) for item in emphasis_words if item]
    for item in word_timestamps:
        try:
            start = float(item.get("start", item.get("start_s", 99.0)) or 99.0)
        except (TypeError, ValueError):
            continue
        if start > 2.0:
            continue
        word = _normalize(str(item.get("word") or item.get("text") or ""))
        if any(word and word in phrase for phrase in wanted):
            return True
    return False


def _first_4s_contract(
    *,
    hook_type: str,
    zoom_event: Optional[Dict[str, Any]],
    emphasis_words: Sequence[str],
    text: str,
    word_timestamps: Optional[Sequence[Dict[str, Any]]],
    silence_improves: bool,
    broll_delay_until_s: float,
) -> Dict[str, Any]:
    signals: List[str] = []
    if zoom_event and float(zoom_event.get("start_s", 99.0) or 99.0) < 4.0:
        signals.append("hook_zoom_or_punch")
    if emphasis_words:
        signals.append("subtitle_hook")
    if silence_improves:
        signals.append("silence_cut")
    if _strong_phrase_starts_before_2s(word_timestamps, emphasis_words, text):
        signals.append("strong_phrase_before_2s")
    if emphasis_words or zoom_event:
        signals.append("visual_emphasis_event")
    if broll_delay_until_s >= 3.8:
        signals.append("safe_speaker_focus")
    if hook_type == "weak_intro":
        signals.append("weak_intro_speaker_focus")
    deduped = list(dict.fromkeys(signals))
    score = len(deduped)
    return {"score": score, "signals": deduped, "satisfied": hook_type == "weak_intro" or score >= 2}


def _assess_hook_density(
    *,
    hook_type: str,
    zoom_event: Optional[Dict[str, Any]],
    emphasis_words: Sequence[str],
    broll_delay_until_s: float,
    overlay: Optional[Dict[str, Any]] = None,
    kickframe: Optional[Dict[str, Any]] = None,
    watermark: bool = True,
) -> Dict[str, Any]:
    score = 0.0
    actions: List[str] = []
    warnings: List[str] = []
    if overlay:
        score += 3.0
    if zoom_event:
        score += 3.0
    if emphasis_words:
        score += 2.0
    if watermark:
        score += 1.0
    if broll_delay_until_s < 4.0:
        score += 4.0
    if score > 6.0:
        if len(emphasis_words) > 1:
            actions.append("reduce_highlights")
        if overlay and emphasis_words and zoom_event and score > 8.0:
            actions.append("disable_overlay")
            score -= 3.0
        if score > 8.0 and kickframe and zoom_event:
            actions.append("remove_kickframe")
        warnings.append("hook_density_high")
    logger.info("[hook-density] score=%.1f action=%s", score, "|".join(actions) or "none")
    return {"score": round(score, 2), "actions": actions, "warnings": warnings}


def _minimum_hook_contract(
    *,
    hook_type: str,
    zoom_event: Optional[Dict[str, Any]],
    overlay: Optional[Dict[str, Any]],
    kickframe: Optional[Dict[str, Any]],
    emphasis_words: Sequence[str],
    headline: str,
    headline_source: str,
    text: str,
    editorial_type: str,
) -> Dict[str, Any]:
    warnings: List[str] = []
    signal_types: List[str] = []
    final_overlay = overlay
    final_emphasis = list(emphasis_words or [])
    if zoom_event:
        signal_types.append("hook_zoom")
    if kickframe:
        signal_types.append("kickframe")
    if final_overlay:
        signal_types.append("headline_overlay")
    if final_emphasis:
        signal_types.append("subtitle_highlight")

    if hook_type == "weak_intro":
        return {
            "satisfied": True,
            "signal_count": 1,
            "signal_types": ["speaker_focus"],
            "overlay": final_overlay,
            "emphasis_words": final_emphasis,
            "warnings": warnings,
            "disabled_reason": "",
        }

    if not signal_types:
        fallback_terms = _emphasis_words_for(hook_type, text, [])
        if fallback_terms:
            final_emphasis = fallback_terms[:1]
            signal_types.append("subtitle_highlight")
            warnings.append("hook_contract_subtitle_fallback")
            logger.info("[hook-contract] fallback=subtitle_highlight reason=no_visual_signal")
        else:
            final_overlay = _headline_overlay_for(
                editorial_type=editorial_type,
                hook_type=hook_type,
                headline=headline,
                headline_source=headline_source if headline_source in {"transcript", "template"} else "transcript",
                text=text,
                emphasis_words=final_emphasis,
            )
            if final_overlay:
                signal_types.append("headline_overlay")
                warnings.append("hook_contract_overlay_fallback")
                logger.info("[hook-contract] fallback=headline_overlay reason=no_visual_signal")

    if hook_type == "emotional_hook" and not any(item in signal_types for item in ("hook_zoom", "subtitle_highlight", "headline_overlay")):
        warnings.append("hook_contract_unsatisfied")
    if hook_type == "objection_hook" and not any(item in signal_types for item in ("hook_zoom", "kickframe", "subtitle_highlight")):
        warnings.append("hook_contract_unsatisfied")
    if hook_type == "risk_hook" and not any(item in signal_types for item in ("hook_zoom", "kickframe", "subtitle_highlight")):
        warnings.append("hook_contract_unsatisfied")

    satisfied = "hook_contract_unsatisfied" not in warnings and bool(signal_types)
    return {
        "satisfied": satisfied,
        "signal_count": len(signal_types),
        "signal_types": signal_types,
        "overlay": final_overlay,
        "emphasis_words": final_emphasis,
        "warnings": warnings,
        "disabled_reason": "" if satisfied else "minimum_hook_contract_unsatisfied",
    }


def _hook_quality(
    hook_type: str,
    headline: str,
    density_score: float,
    zoom_render_expected: bool,
    subtitle_highlight_expected: bool,
    broll_delay_until_s: float,
) -> str:
    if hook_type == "weak_intro" or not headline:
        return "weak"
    if density_score > 6.0 or broll_delay_until_s < 3.2:
        return "acceptable"
    if zoom_render_expected or subtitle_highlight_expected:
        return "strong"
    return "acceptable"


def _assess_first_3s_hook(
    *,
    hook_type: str,
    zoom_event: Optional[Dict[str, Any]],
    emphasis_words: Sequence[str],
    text: str,
    word_timestamps: Optional[Sequence[Dict[str, Any]]],
    overlay: Optional[Dict[str, Any]],
    kickframe: Optional[Dict[str, Any]],
    headline: str,
) -> Dict[str, Any]:
    """Evaluate the first 3 seconds for hook strength (v4.0 retention).

    Scoring (0-10 scale):
      +3  Visual zoom/punch in first 3s
      +2  Subtitle emphasis in first 3s
      +2  Strong phrase in first 2s
      +2  Overlay/headline in first 3s
      +1  Kickframe in first 3s

    Minimum 5 for READY status.
    weak_intro never READY.
    Subtitle-only (no visual) not enough for READY.
    """
    signals: List[str] = []
    missing: List[str] = []
    score = 0

    # 1. Visual zoom/punch in first 3s (+3)
    has_visual_zoom = bool(
        zoom_event
        and float(zoom_event.get("start_s", 99.0) or 99.0) < 3.0
    )
    if has_visual_zoom:
        score += 3
        signals.append("visual_zoom_first3s")
    else:
        missing.append("visual_zoom_first3s")

    # 2. Subtitle emphasis in first 3s (+2)
    has_subtitle_emphasis = bool(emphasis_words)
    if has_subtitle_emphasis:
        score += 2
        signals.append("subtitle_emphasis_first3s")
    else:
        missing.append("subtitle_emphasis_first3s")

    # 3. Strong phrase in first 2s (+2)
    has_strong_phrase = _strong_phrase_starts_before_2s(
        word_timestamps, emphasis_words, text
    )
    if has_strong_phrase:
        score += 2
        signals.append("strong_phrase_first2s")
    else:
        missing.append("strong_phrase_first2s")

    # 4. Overlay/headline in first 3s (+2)
    has_overlay = bool(
        overlay
        and float(overlay.get("start_s", 99.0) or 99.0) < 3.0
    )
    if has_overlay:
        score += 2
        signals.append("overlay_headline_first3s")
    else:
        missing.append("overlay_headline_first3s")

    # 5. Kickframe in first 3s (+1)
    has_kickframe = bool(
        kickframe
        and float(kickframe.get("start_s", 99.0) or 99.0) < 3.0
    )
    if has_kickframe:
        score += 1
        signals.append("kickframe_first3s")
    else:
        missing.append("kickframe_first3s")

    # Determine status
    warning = ""
    perceptible = False

    if hook_type == "weak_intro":
        status = "weak_intro"
        warning = "weak_intro_never_ready"
    elif score >= 7:
        status = "strong"
        perceptible = True
    elif score >= 5:
        status = "acceptable"
        perceptible = True
    elif score >= 3:
        status = "weak"
        perceptible = False
        warning = "hook_first3s_below_5"
    else:
        status = "weak"
        warning = "hook_first3s_too_weak"

    # Subtitle-only (no visual) not enough for READY
    if (
        status == "strong"
        and not has_visual_zoom
        and not has_overlay
        and not has_kickframe
    ):
        status = "acceptable"
        perceptible = True
        warning = "subtitle_only_not_enough_for_ready"
        missing.append("visual_signal_required")

    logger.info(
        "[hook-first3] score=%d status=%s perceptible=%s signals=%s missing=%s",
        score,
        status,
        str(perceptible).lower(),
        "|".join(signals) or "none",
        "|".join(missing) or "none",
    )

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
    emphasis_words: Sequence[str],
) -> Optional[float]:
    if not word_timestamps or not emphasis_words:
        return None
    wanted = {_normalize(item) for item in emphasis_words}
    for item in word_timestamps:
        word = _normalize(str(item.get("word") or item.get("text") or ""))
        if word in wanted:
            try:
                return float(item.get("start", 0.0) or 0.0)
            except (TypeError, ValueError):
                return None
    return None


def _early_text(text: str, word_timestamps: Optional[Sequence[Dict[str, Any]]], max_s: float) -> str:
    if not word_timestamps:
        return " ".join((text or "").split()[:45])
    words: List[str] = []
    for item in word_timestamps:
        try:
            start = float(item.get("start", 0.0) or 0.0)
        except (TypeError, ValueError):
            start = 0.0
        if start <= max_s:
            words.append(str(item.get("word") or item.get("text") or ""))
    return " ".join(words) if words else " ".join((text or "").split()[:45])


def _limit_words(text: str, max_words: int) -> str:
    words = (text or "").strip().split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words])


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    ascii_text = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    ascii_text = re.sub(r"[^a-z0-9\s]", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip()
