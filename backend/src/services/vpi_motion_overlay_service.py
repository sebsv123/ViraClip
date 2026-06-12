from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .vpi_asset_library_service import build_asset_index

logger = logging.getLogger(__name__)

_CONCEPT_RULES: Dict[str, Dict[str, Sequence[str]]] = {
    # ── Original VPI concepts ──────────────────────────────────
    "shield": {
        "topics": ("vida", "decesos", "proteccion", "protección", "cobertura"),
        "triggers": ("protegido", "protección", "proteger", "cubrir", "respaldo", "tranquilidad"),
    },
    "heart": {
        "topics": ("salud", "vida", "familia"),
        "triggers": ("cuidado", "familia", "tuyos", "tranquilidad", "salud"),
    },
    "warning": {
        "topics": ("risk_warning", "advertencia", "riesgo"),
        "triggers": ("ojo", "cuidado", "importante", "riesgo", "si mañana", "problema"),
    },
    "document": {
        "topics": ("practical_advice", "cobertura", "poliza", "póliza"),
        "triggers": ("pasos", "trámite", "poliza", "póliza", "condiciones", "revisar", "documento"),
    },
    "checklist": {
        "topics": ("practical_advice", "cobertura", "poliza", "póliza"),
        "triggers": ("pasos", "trámite", "poliza", "póliza", "condiciones", "revisar", "checklist"),
    },
    "euro": {
        "topics": ("ahorro", "precio", "promocion", "promoción"),
        "triggers": ("descuento", "gratis", "ahorro", "prima", "euros", "precio"),
    },
    "price_badge": {
        "topics": ("ahorro", "precio", "promocion", "promoción"),
        "triggers": ("descuento", "gratis", "ahorro", "prima", "euros", "precio"),
    },
    "calendar": {
        "topics": ("urgencia", "vencimiento"),
        "triggers": ("hoy", "este mes", "plazo", "vence", "espera", "fecha"),
    },
    "timer": {
        "topics": ("urgencia", "vencimiento"),
        "triggers": ("hoy", "este mes", "plazo", "vence", "espera", "fecha"),
    },
    "phone": {
        "topics": ("contacto", "whatsapp", "cita"),
        "triggers": ("llámanos", "llamanos", "escríbenos", "escribenos", "whatsapp", "hablamos", "cita"),
    },
    "message_bubble": {
        "topics": ("contacto", "whatsapp", "cita"),
        "triggers": ("llámanos", "llamanos", "escríbenos", "escribenos", "whatsapp", "hablamos", "cita"),
    },
    "cta": {
        "topics": ("contacto", "whatsapp", "cita"),
        "triggers": ("llámanos", "llamanos", "escríbenos", "escribenos", "whatsapp", "hablamos", "cita"),
    },
    # ── Swishy Template Families (v1) ─────────────────────────
    "notification_card": {
        "topics": ("contacto", "whatsapp", "cita", "alerta"),
        "triggers": ("llámanos", "escríbenos", "whatsapp", "hablamos", "cita", "avísanos", "notificación"),
    },
    "glow_text": {
        "topics": ("hook_driven", "myth_flip", "keyword_emphasis"),
        "triggers": ("esto es", "así que", "porque", "imagina", "clave", "importante", "secreto"),
    },
    "time_passage": {
        "topics": ("urgencia", "vencimiento", "plazo"),
        "triggers": ("hoy", "este mes", "plazo", "vence", "espera", "fecha", "tiempo", "días", "semanas"),
    },
    "finance_chart": {
        "topics": ("ahorro", "precio", "promocion", "finanzas"),
        "triggers": ("descuento", "gratis", "ahorro", "prima", "euros", "precio", "dinero", "coste"),
    },
    "stat_card": {
        "topics": ("practical_advice", "dato", "estadística"),
        "triggers": ("estadística", "dato", "porcentaje", "cifra", "número", "estudio", "según"),
    },
    "timeline_card": {
        "topics": ("practical_advice", "pasos", "proceso"),
        "triggers": ("pasos", "proceso", "fases", "etapas", "primero", "después", "finalmente", "secuencia"),
    },
    "toggle_card": {
        "topics": ("comparativa", "opciones", "decisión"),
        "triggers": ("opción", "alternativa", "comparar", "elegir", "decidir", "diferencia", "versus"),
    },
    "folder_gallery": {
        "topics": ("practical_advice", "documentos", "cobertura"),
        "triggers": ("documentos", "papeles", "trámite", "gestión", "carpeta", "archivo", "requisitos"),
    },
    "typewriter_text": {
        "topics": ("hook_driven", "cita", "testimonio"),
        "triggers": ("cita textual", "testimonio", "palabras de", "dijo", "afirmó", "declaró"),
    },
    "location_popup": {
        "topics": ("contacto", "ubicación", "oficina"),
        "triggers": ("cerca de ti", "ubicación", "oficina", "dónde", "localidad", "provincia", "dirección"),
    },
    "keyword_spin": {
        "topics": ("keyword_emphasis", "hook_driven", "myth_flip"),
        "triggers": ("clave", "importante", "recuerda", "no olvides", "atención", "destacar"),
    },
}


_DELICATE_HINTS = ("decesos", "emocional", "emotional_closure", "duelo", "fallecimiento")
_DELICATE_ALLOWED = {"heart", "shield"}
_GENERATED_ICON_PRIORITY = {
    "warning": 60,
    "document_check": 50,
    "euro": 40,
    "chat_bubble": 35,
    "phone": 32,
    "shield": 30,
    "heart": 28,
    "medical_cross": 26,
    "calendar": 18,
    "briefcase": 16,
    "checkmark": 10,
}
_GENERATED_ICON_KEYWORDS: Dict[str, Sequence[str]] = {
    "warning": (
        "no todos",
        "cuidado",
        "ojo",
        "revisa",
        "antes de contratar",
        "riesgo",
        "problema",
        "error",
        "sorpresa",
        "sorpresas",
        "no cubren",
        "letra pequeña",
        "exclusiones",
    ),
    "shield": (
        "protección",
        "protegido",
        "seguridad",
        "cobertura",
        "respaldo",
        "tranquilidad",
        "familia protegida",
        "si pasa algo serio",
    ),
    "heart": (
        "salud",
        "médico",
        "acceso médico",
        "familia",
        "cuidado",
        "bienestar",
        "hospital",
        "consulta",
    ),
    "medical_cross": (
        "salud",
        "médico",
        "hospital",
        "consulta",
        "asistencia médica",
        "atención médica",
    ),
    "document_check": (
        "extranjería",
        "póliza",
        "poliza",
        "documentación",
        "documento",
        "trámite",
        "presentar",
        "visado",
        "residencia",
        "requisitos",
    ),
    "euro": (
        "precio",
        "descuento",
        "gratis",
        "prima",
        "ahorro",
        "pagar",
        "coste",
        "condiciones",
        "mensual",
        "anual",
    ),
    "chat_bubble": (
        "whatsapp",
        "escríbenos",
        "escribenos",
        "mensaje",
        "te explicamos",
        "consulta",
        "contacto",
        "hablamos",
    ),
    "phone": ("llama", "llamada", "teléfono", "telefono", "contacto", "atención personalizada"),
    "calendar": ("vence", "renovación", "renovacion", "cita", "plazo", "fecha", "este mes"),
    "briefcase": ("autónomo", "autonomo", "negocio", "empresa", "trabajo", "profesional"),
    "map_pin": ("ubicación", "oficina", "dirección", "direccion", "localidad", "provincia"),
    "checkmark": ("correcto", "listo", "aprobado", "cumple", "válido", "valido", "confirmado"),
}

# ── Swishy Template Metadata (v1) ─────────────────────────────
# Metadata recommendations for each Swishy template family.
# Fields:
#   swishy_template_family  – canonical family name
#   overlay_concept         – concept key in _CONCEPT_RULES
#   overlay_role            – narrative role (strong_card | micro_overlay | decorative)
#   overlay_intensity       – visual intensity (high | medium | low)
#   recommended_duration    – ideal on-screen duration in seconds
#   recommended_position    – preferred screen position
#   recommended_start       – recommended start offset relative to segment (s)
#   recommended_sfx_family  – SFX family that pairs naturally
#   needs_claim_review      – True if overlay could imply a claim requiring legal review
SWISHY_TEMPLATE_METADATA: Dict[str, Dict[str, Any]] = {
    "notification_card": {
        "swishy_template_family": "notification_card",
        "overlay_concept": "notification_card",
        "overlay_role": "micro_overlay",
        "overlay_intensity": "medium",
        "recommended_duration": 1.8,
        "recommended_position": "top_right",
        "recommended_start": 0.5,
        "recommended_sfx_family": "soft_chime",
        "needs_claim_review": False,
    },
    "glow_text": {
        "swishy_template_family": "glow_text",
        "overlay_concept": "glow_text",
        "overlay_role": "strong_card",
        "overlay_intensity": "high",
        "recommended_duration": 2.5,
        "recommended_position": "center",
        "recommended_start": 0.3,
        "recommended_sfx_family": "magic_whoosh",
        "needs_claim_review": False,
    },
    "time_passage": {
        "swishy_template_family": "time_passage",
        "overlay_concept": "time_passage",
        "overlay_role": "micro_overlay",
        "overlay_intensity": "medium",
        "recommended_duration": 1.5,
        "recommended_position": "bottom_center",
        "recommended_start": 0.6,
        "recommended_sfx_family": "deep_boom",
        "needs_claim_review": False,
    },
    "finance_chart": {
        "swishy_template_family": "finance_chart",
        "overlay_concept": "finance_chart",
        "overlay_role": "strong_card",
        "overlay_intensity": "high",
        "recommended_duration": 2.8,
        "recommended_position": "center",
        "recommended_start": 0.4,
        "recommended_sfx_family": "magic_whoosh",
        "needs_claim_review": True,
    },
    "stat_card": {
        "swishy_template_family": "stat_card",
        "overlay_concept": "stat_card",
        "overlay_role": "strong_card",
        "overlay_intensity": "high",
        "recommended_duration": 2.5,
        "recommended_position": "center",
        "recommended_start": 0.4,
        "recommended_sfx_family": "magic_whoosh",
        "needs_claim_review": True,
    },
    "timeline_card": {
        "swishy_template_family": "timeline_card",
        "overlay_concept": "timeline_card",
        "overlay_role": "strong_card",
        "overlay_intensity": "medium",
        "recommended_duration": 2.8,
        "recommended_position": "center",
        "recommended_start": 0.5,
        "recommended_sfx_family": "soft_chime",
        "needs_claim_review": False,
    },
    "toggle_card": {
        "swishy_template_family": "toggle_card",
        "overlay_concept": "toggle_card",
        "overlay_role": "strong_card",
        "overlay_intensity": "medium",
        "recommended_duration": 2.5,
        "recommended_position": "center",
        "recommended_start": 0.5,
        "recommended_sfx_family": "soft_chime",
        "needs_claim_review": False,
    },
    "folder_gallery": {
        "swishy_template_family": "folder_gallery",
        "overlay_concept": "folder_gallery",
        "overlay_role": "micro_overlay",
        "overlay_intensity": "low",
        "recommended_duration": 2.0,
        "recommended_position": "bottom_left",
        "recommended_start": 0.7,
        "recommended_sfx_family": "click_soft",
        "needs_claim_review": False,
    },
    "typewriter_text": {
        "swishy_template_family": "typewriter_text",
        "overlay_concept": "typewriter_text",
        "overlay_role": "micro_overlay",
        "overlay_intensity": "low",
        "recommended_duration": 2.2,
        "recommended_position": "bottom_center",
        "recommended_start": 0.6,
        "recommended_sfx_family": "no_sfx_needed",
        "needs_claim_review": False,
    },
    "location_popup": {
        "swishy_template_family": "location_popup",
        "overlay_concept": "location_popup",
        "overlay_role": "micro_overlay",
        "overlay_intensity": "low",
        "recommended_duration": 1.8,
        "recommended_position": "bottom_left",
        "recommended_start": 0.8,
        "recommended_sfx_family": "soft_chime",
        "needs_claim_review": False,
    },
    "keyword_spin": {
        "swishy_template_family": "keyword_spin",
        "overlay_concept": "keyword_spin",
        "overlay_role": "micro_overlay",
        "overlay_intensity": "medium",
        "recommended_duration": 1.5,
        "recommended_position": "center",
        "recommended_start": 0.3,
        "recommended_sfx_family": "magic_whoosh",
        "needs_claim_review": False,
    },
}



# ── Swishy Editorial Rules (v1) ───────────────────────────────
# Rules enforced at the clip level to prevent visual overload and
# ensure claim-review safeguards for Swishy strong cards.
_SWISHY_EDITORIAL_RULES: Dict[str, Any] = {
    "max_strong_cards_per_clip": 1,
    "max_micro_overlays_per_clip": 2,
    "claim_review_concepts": ("finance_chart", "stat_card"),
    "claim_review_required_fields": ("review_required", "needs_claim_review"),
}


def _apply_swishy_editorial_rules(
    selected_concepts: List[str],
    editorial_signal: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Apply Swishy editorial rules to a list of selected overlay concepts.

    Returns a dict with:
      - allowed: list of concepts that pass editorial rules
      - blocked: list of concepts that were blocked
      - reasons: dict mapping blocked concept -> reason string
      - strong_card_count: int
      - micro_overlay_count: int
    """
    signal = editorial_signal or {}
    rules = _SWISHY_EDITORIAL_RULES
    max_strong = int(rules["max_strong_cards_per_clip"])
    max_micro = int(rules["max_micro_overlays_per_clip"])
    claim_concepts = set(rules["claim_review_concepts"])

    allowed: List[str] = []
    blocked: List[str] = []
    reasons: Dict[str, str] = {}
    strong_count = 0
    micro_count = 0

    for concept in selected_concepts:
        meta = SWISHY_TEMPLATE_METADATA.get(concept, {})
        role = str(meta.get("overlay_role") or "micro_overlay")
        needs_claim = bool(meta.get("needs_claim_review", False))

        # ── Claim review gate ──────────────────────────────
        if needs_claim and concept in claim_concepts:
            if not bool(signal.get("claim_review_cleared", False)):
                blocked.append(concept)
                reasons[concept] = "claim_review_not_cleared"
                continue

        # ── Strong card limit ──────────────────────────────
        if role == "strong_card":
            if strong_count >= max_strong:
                blocked.append(concept)
                reasons[concept] = f"max_strong_cards_exceeded ({max_strong})"
                continue
            strong_count += 1

        # ── Micro overlay limit ────────────────────────────
        if role == "micro_overlay":
            if micro_count >= max_micro:
                blocked.append(concept)
                reasons[concept] = f"max_micro_overlays_exceeded ({max_micro})"
                continue
            micro_count += 1

        allowed.append(concept)

    return {
        "allowed": allowed,
        "blocked": blocked,
        "reasons": reasons,
        "strong_card_count": strong_count,
        "micro_overlay_count": micro_count,
    }


def _norm_tokens(values: Iterable[str]) -> List[str]:

    blob = " ".join(str(v or "") for v in values).lower()
    blob = re.sub(r"[^a-z0-9áéíóúñü]+", " ", blob)
    return [piece for piece in blob.split() if piece]


def _has_any(haystack: set[str], needles: Sequence[str]) -> bool:
    for value in needles:
        if any(token in haystack for token in _norm_tokens([value])):
            return True
    return False


def _asset_concept(item: Dict[str, Any]) -> str:
    direct_concept = str(item.get("concept") or "").strip()
    if direct_concept:
        return direct_concept
    aid = str(item.get("id") or "").strip()
    path_txt = str(item.get("path") or "").strip()
    if aid.startswith("generated_icon_"):
        tail = aid.removeprefix("generated_icon_")
        for concept in sorted(_GENERATED_ICON_KEYWORDS.keys(), key=len, reverse=True):
            if tail == concept or tail.startswith(f"{concept}_"):
                return concept
    if "/generated_icons/" in path_txt.replace("\\", "/"):
        norm = path_txt.replace("\\", "/")
        family = norm.split("/generated_icons/", 1)[1].split("/", 1)[0].strip()
        if family in _GENERATED_ICON_KEYWORDS:
            return family
    raw_sources = (
        list(item.get("tags") or [])
        + list(item.get("topics") or [])
        + [str(item.get("id") or ""), Path(str(item.get("path") or "")).stem]
    )
    tokens = set(_norm_tokens(raw_sources))
    # Also check raw (un-split) source strings so multi-word concept names
    # like "notification_card" can match tags/topics/id/path that contain them.
    raw_set = set(raw_sources)
    for concept in list(_CONCEPT_RULES.keys()) + list(_GENERATED_ICON_KEYWORDS.keys()):
        if concept in tokens or concept in raw_set:
            return concept
    return ""


def _is_generated_icon_asset(item: Dict[str, Any]) -> bool:
    aid = str(item.get("id") or "")
    source = str(item.get("source") or item.get("source_name") or "")
    return (
        str(item.get("type") or "") == "motion_overlay"
        and aid.startswith("generated_icon_")
        and source == "local_svg_synthesizer"
        and bool(item.get("manifest_verified")) is True
        and bool(item.get("commercial_use_ok")) is True
        and bool(item.get("review_required")) is False
    )


def _keyword_hits(text_blob: str, keywords: Sequence[str]) -> List[str]:
    hits: List[str] = []
    for keyword in keywords:
        needle = str(keyword or "").strip().lower()
        if needle and needle in text_blob:
            hits.append(needle)
    return hits


def select_motion_overlay_candidate(
    text: str,
    topics: List[str],
    tags: List[str],
    editorial_signal: Dict[str, Any] | None = None,
    asset_index: Dict[str, Any] | None = None,
) -> Dict[str, Any] | None:
    signal = editorial_signal or {}
    overload = bool(signal.get("layer_overload") or signal.get("first3_overload"))
    if overload:
        logger.info("[motion-overlay] skipped reason=visual_overload")
        return None

    composition_mode = str(signal.get("composition_mode") or "")
    if composition_mode == "minimal_safe":
        logger.info("[motion-overlay] skipped reason=minimal_safe_mode")
        return None

    all_tokens = set(_norm_tokens([text] + list(topics or []) + list(tags or [])))
    delicate = any(hint in all_tokens for hint in _norm_tokens(_DELICATE_HINTS))

    index = asset_index or build_asset_index()
    verified = list((index.get("verified") or {}).get("motion_overlay") or [])
    if not verified:
        logger.info("[motion-overlay] skipped reason=no_verified_asset")
        return None

    text_blob = " ".join([str(text or ""), " ".join(topics or []), " ".join(tags or [])]).lower()
    raw_hints = {str(v or "").strip().lower() for v in (list(topics or []) + list(tags or [])) if str(v or "").strip()}
    preferred_concepts = set(_norm_tokens(list(topics or []) + list(tags or [])))
    generated_icon_mode = bool(
        signal.get("prefer_generated_icons")
        or any("generated_icon" in hint for hint in raw_hints)
        or any(hint in _GENERATED_ICON_KEYWORDS for hint in raw_hints)
    )
    concept_score: Dict[str, int] = {}
    for concept, rules in _CONCEPT_RULES.items():
        score = 0
        topic_matches = sum(1 for t in (rules.get("topics") or []) if _has_any(all_tokens, [t]))
        trigger_matches = sum(1 for t in (rules.get("triggers") or []) if _has_any(all_tokens, [t]))
        if topic_matches:
            score += 3 + topic_matches - 1  # base 3 + extra for each additional topic match
        if trigger_matches:
            score += 4 + trigger_matches - 1  # base 4 + extra for each additional trigger match
        if score > 0:
            concept_score[concept] = score

    # Generated icon semantic scoring (preferred in Beta Clean generated icon paths).
    generated_concept_score: Dict[str, int] = {}
    generated_keyword_hits: Dict[str, List[str]] = {}
    if generated_icon_mode:
        for concept, keywords in _GENERATED_ICON_KEYWORDS.items():
            hits = _keyword_hits(text_blob, keywords)
            if not hits:
                continue
            base = len(hits) * 5
            priority = int(_GENERATED_ICON_PRIORITY.get(concept, 0))
            topic_boost = 40 if concept in preferred_concepts else 0
            generated_concept_score[concept] = base + priority + topic_boost
            generated_keyword_hits[concept] = hits

    if not concept_score and not generated_concept_score:
        logger.info("[motion-overlay] skipped reason=no_editorial_match")
        return None

    if generated_concept_score:
        desired_concept = sorted(generated_concept_score.items(), key=lambda item: item[1], reverse=True)[0][0]
    else:
        desired_concept = sorted(concept_score.items(), key=lambda item: item[1], reverse=True)[0][0]
    if delicate and desired_concept not in _DELICATE_ALLOWED:
        logger.info("[motion-overlay] skipped reason=sensitive_tone")
        return None

    candidates: List[Dict[str, Any]] = []
    generated_candidates: List[Dict[str, Any]] = []
    for item in verified:
        if not bool(item.get("commercial_use_ok")):
            continue
        path = Path(str(item.get("path") or ""))
        if not path.exists() or not path.is_file():
            continue
        concept = _asset_concept(item)
        if concept and concept != desired_concept:
            continue
        tone = str(item.get("sensitive_tone") or "safe").lower().strip()
        if delicate and tone not in {"safe", "soft", "gentle", "mild"}:
            continue
        candidates.append(item)
        if _is_generated_icon_asset(item):
            generated_candidates.append(item)

    if generated_concept_score:
        generated_matches = [item for item in generated_candidates if _asset_concept(item) == desired_concept]
        if generated_matches:
            best_generated = generated_matches[0]
            hits = generated_keyword_hits.get(desired_concept, [])
            score = int(generated_concept_score.get(desired_concept, 0))
            logger.info(
                "[motion-overlay] selected=true generated_icon=true concept=%s asset=%s score=%s hits=%s",
                desired_concept,
                str(best_generated.get("path") or ""),
                score,
                ",".join(hits),
            )
            return {
                "selected": True,
                "planned": True,
                "rendered": False,
                "dropped_by_budget": False,
                "budget_drop_reason": "",
                "overlay_concept": desired_concept,
                "overlay_role": "semantic_icon",
                "overlay_intensity": "subtle",
                "recommended_position": str(signal.get("overlay_position") or "bottom_right"),
                "recommended_start": "keyword",
                "recommended_duration": float(best_generated.get("duration_hint") or 1.5),
                "motion_overlay_asset_id": str(best_generated.get("id") or ""),
                "motion_overlay_asset_path": str(best_generated.get("path") or ""),
                "motion_overlay_source": str(best_generated.get("source_name") or best_generated.get("source") or ""),
                "motion_overlay_license": str(best_generated.get("license_name") or ""),
                "motion_overlay_tags": list(best_generated.get("tags") or []),
                "motion_overlay_topics": list(best_generated.get("topics") or []),
                "motion_overlay_manifest_verified": True,
                "motion_overlay_applied": False,
                "final_output_uses_motion_overlay": False,
                "review_required": bool(best_generated.get("review_required", False)),
                "reason": "semantic_generated_icon_match",
                "selection_reason": {
                    "matcher": "generated_icon_semantic_v1",
                    "concept_score": score,
                    "matched_keywords": hits,
                    "desired_concept": desired_concept,
                },
                "matched_keywords": hits,
                "selector_score": score,
                "duration_hint": float(best_generated.get("duration_hint") or 1.5),
                "start_hint_s": float(signal.get("overlay_start_hint_s") or 0.9),
                "position": str(signal.get("overlay_position") or "bottom_right"),
            }

    if not candidates:
        logger.info("[motion-overlay] skipped reason=no_verified_match")
        return None

    best = candidates[0]
    logger.info(
        "[motion-overlay] selected=true concept=%s asset=%s source=%s verified=true",
        desired_concept,
        str(best.get("path") or ""),
        str(best.get("source_name") or ""),
    )
    _swishy_meta = dict(SWISHY_TEMPLATE_METADATA.get(desired_concept) or {})
    _overlay_role = str(_swishy_meta.get("overlay_role") or "semantic_icon")
    _overlay_intensity = str(_swishy_meta.get("overlay_intensity") or "subtle")
    _recommended_position = str(_swishy_meta.get("recommended_position") or signal.get("overlay_position") or "bottom_right")
    _recommended_start = "hook" if float(_swishy_meta.get("recommended_start") or signal.get("overlay_start_hint_s") or 0.9) <= 0.8 else "keyword"
    _recommended_duration = float(_swishy_meta.get("recommended_duration") or best.get("duration_hint") or 1.2)
    return {
        "selected": True,
        "planned": True,
        "rendered": False,
        "dropped_by_budget": False,
        "budget_drop_reason": "",
        "overlay_concept": desired_concept,
        "overlay_role": _overlay_role,
        "overlay_intensity": _overlay_intensity,
        "recommended_position": _recommended_position,
        "recommended_start": _recommended_start,
        "recommended_duration": _recommended_duration,
        "motion_overlay_asset_id": str(best.get("id") or ""),
        "motion_overlay_asset_path": str(best.get("path") or ""),
        "motion_overlay_source": str(best.get("source_name") or ""),
        "motion_overlay_license": str(best.get("license_name") or ""),
        "motion_overlay_tags": list(best.get("tags") or []),
        "motion_overlay_topics": list(best.get("topics") or []),
        "motion_overlay_manifest_verified": True,
        "motion_overlay_applied": False,
        "final_output_uses_motion_overlay": False,
        "review_required": bool(best.get("review_required", False)),
        "reason": "manifest_verified_candidate",
        "selection_reason": {
            "matcher": "legacy_editorial_rules",
            "desired_concept": desired_concept,
            "concept_score": int(concept_score.get(desired_concept, 0)),
            "matched_keywords": generated_keyword_hits.get(desired_concept, []),
        },
        "matched_keywords": generated_keyword_hits.get(desired_concept, []),
        "selector_score": int(concept_score.get(desired_concept, 0)),
        "duration_hint": _recommended_duration,
        "start_hint_s": float(signal.get("overlay_start_hint_s") or 0.9),
        "position": str(signal.get("overlay_position") or "bottom_right"),
    }
