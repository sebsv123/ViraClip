"""
VPI Editorial Contract — single shared evaluator for pre-render editorial gates.

Replaces scattered inline logic in task_service.py, vpi_fast_preflight_task.py,
vpi_validate_failed_task_contract.py, and verify_vpi_operational_task.py with
one deterministic, local-only function::

    evaluate_editorial_contract(segment, *, task_id, profile, ...) -> dict

Key design decisions
--------------------
* Repair-or-reject ladder: instead of immediate rejection, try to repair with
  fallbacks (extend_boundary, hook_card, semantic_card).
* Renderability score: composite score that penalises weak dimensions but does
  not hard-reject unless the score is below the profile threshold.
* Editorial policy profiles: beta_clean, vpi_publishable, premium, dev_debug.
* Penalty/threshold logic: avoid brittle single-rule death; use penalties
  instead of hard rejections where repair is possible.
* All logic is deterministic, local-only, no LLM runtime, no external APIs.
"""

from __future__ import annotations

import html
import json
import hashlib
import logging
import re
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)
_CLIP_RESCUE_FAILED_SUMMARIES: Dict[Tuple[str, str, Tuple[str, ...]], int] = {}

# ---------------------------------------------------------------------------
# Flexibility Engine — Severity Matrix
# ---------------------------------------------------------------------------

SEVERITY_BLOCKER = "BLOCKER"
SEVERITY_REPAIRABLE = "REPAIRABLE"
SEVERITY_PENALTY = "PENALTY"
SEVERITY_INFO = "INFO"

SEVERITY_ORDER = {SEVERITY_BLOCKER: 0, SEVERITY_REPAIRABLE: 1, SEVERITY_PENALTY: 2, SEVERITY_INFO: 3}

# ---------------------------------------------------------------------------
# Flexibility Engine — Brand Voice Pack (VPI constants)
# ---------------------------------------------------------------------------

VPI_BRAND_VOICE = {
    "tone": "clear, close, professional, practical, trust-building, non-alarmist",
    "preferred_words": [
        "tranquilidad", "protección", "proteger", "claridad",
        "cobertura", "planificación", "planificar", "familia",
        "salud", "cuidado", "cuidar", "comparar", "revisar",
        "entender", "acompañar", "confianza", "seguridad",
    ],
    "avoid_words": [
        "desgracia", "tragedia", "catástrofe", "horror",
        "pánico", "miedo", "terrible", "espantoso",
        "estafa", "timar", "engañar",
    ],
    "cta_style": "short, non-aggressive, informative, never urgent",
}

# ---------------------------------------------------------------------------
# Flexibility Engine — Publishing Intent Inference
# ---------------------------------------------------------------------------

PUBLISHING_INTENTS = [
    "educate",
    "warn",
    "debunk",
    "resolve_objection",
    "build_trust",
    "soft_sell",
    "humanize",
    "explain_coverage",
    "drive_consultation",
]

_INTENT_PATTERNS: Dict[str, List[str]] = {
    "educate": [
        "es importante", "hay que saber", "debes saber", "tienes que saber",
        "funciona", "significa", "consiste en", "se trata de",
        "te explicamos", "vamos a explicar", "la clave es",
    ],
    "warn": [
        "cuidado", "ojo", "atención", "ten cuidado", "mucho cuidado",
        "riesgo", "peligro", "problema", "sorpresa", "no te confíes",
    ],
    "debunk": [
        "mito", "falso", "no es cierto", "no es verdad", "mentira",
        "te han contado", "lo que nadie te cuenta", "no te dicen",
        "no es como crees", "no funciona así",
    ],
    "resolve_objection": [
        "pero", "sin embargo", "no obstante", "aunque parezca",
        "mucha gente piensa", "algunos creen", "se suele pensar",
        "contrario a lo que", "objeción", "pero es que",
    ],
    "build_trust": [
        "tranquilidad", "confianza", "seguridad", "protección",
        "acompañamos", "estamos contigo", "te ayudamos",
        "cuenta con nosotros", "asesoramiento",
    ],
    "soft_sell": [
        "contratar", "póliza", "poliza", "seguro", "cobertura",
        "producto", "servicio", "oferta", "ventaja", "beneficio",
        "te ofrecemos", "ponemos a tu disposición",
    ],
    "humanize": [
        "familia", "hijos", "padres", "ser querido", "personas",
        "vida real", "día a día", "día a día", "cotidiano",
        "experiencia", "historia", "caso real",
    ],
    "explain_coverage": [
        "cubre", "cubrir", "incluye", "incluido", "ampara",
        "protege", "proteger", "indemnización", "indemnizacion",
        "capital", "prestación", "prestacion",
    ],
    "drive_consultation": [
        "revisa", "revisión", "revision", "consulta", "consultar",
        "asesor", "gestor", "profesional", "especialista",
        "habla con", "pregunta a", "infórmate", "informate",
        "comparar", "valorar", "analizar",
    ],
}

# ---------------------------------------------------------------------------
# Flexibility Engine — Smart CTA Suggestions
# ---------------------------------------------------------------------------

_CTA_SUGGESTIONS: Dict[str, List[str]] = {
    "educate": [
        "Consulta con tu asesor",
        "Infórmate bien antes",
        "Conoce todos los detalles",
    ],
    "warn": [
        "Revisa tu póliza",
        "No dejes esto al azar",
        "Mejor prevenir",
    ],
    "debunk": [
        "Contrasta la información",
        "Pregunta a un profesional",
        "No te quedes con la duda",
    ],
    "resolve_objection": [
        "Compáralo tú mismo",
        "Pide una segunda opinión",
        "Valora todas las opciones",
    ],
    "build_trust": [
        "Tu tranquilidad es lo primero",
        "Confía en quien te asesora",
        "Estamos para ayudarte",
    ],
    "soft_sell": [
        "Conoce nuestra propuesta",
        "Te explicamos sin compromiso",
        "Descubre cómo protegerte",
    ],
    "humanize": [
        "Piensa en los tuyos",
        "Cuida de tu familia",
        "Planifica su futuro",
    ],
    "explain_coverage": [
        "Aclara todas tus dudas",
        "Pregunta qué incluye",
        "Revisa los detalles",
    ],
    "drive_consultation": [
        "Habla con un asesor",
        "Pide cita informativa",
        "Consulta sin compromiso",
    ],
}

# ---------------------------------------------------------------------------
# Flexibility Engine — Commercial Usefulness Scoring
# ---------------------------------------------------------------------------

_COMMERCIAL_INCREASE_TERMS = [
    "objeción", "objeccion", "mito", "falso", "riesgo", "peligro",
    "cuidado", "aviso", "advertencia", "consejo", "recomendación",
    "recomendacion", "cobertura", "cubre", "indemnización", "indemnizacion",
    "exclusión", "exclusion", "condiciones", "letra pequeña",
    "prima", "precio", "coste", "ahorro", "descuento",
    "comparar", "diferencias", "elegir", "contratar",
    "protección", "proteccion", "tranquilidad", "seguridad",
    "planificar", "futuro", "familia", "salud",
]

_COMMERCIAL_DECREASE_TERMS = [
    "bueno", "pues", "entonces", "básicamente", "basicamente",
    "en plan", "como quien dice", "vamos", "osea", "o sea",
    "introducción", "introduccion", "empezar", "comenzar",
    "meta", "detrás", "detras", "bambalinas",
    "sin más", "sin mas", "para nada",
]

_META_PRODUCTION_TERMS = (
    "detras de camaras", "detrás de cámaras", "grabando", "camara", "cámara",
    "microfono", "micrófono", "toma", "corte", "espera", "repetimos",
    "sale mal", "risas internas", "fuera de camara", "fuera de cámara",
)

_INSURANCE_ANCHOR_TERMS = (
    "seguro", "seguros", "poliza", "póliza", "cobertura", "cubre", "cubrir",
    "decesos", "salud", "vida", "familia", "hipoteca", "prima", "capital",
    "proteccion", "protección", "riesgo", "mito", "objecion", "objeción",
    "problema", "imprevisto", "tranquilidad", "extranjería", "extranjeria",
)

# ---------------------------------------------------------------------------
# Editorial Policy Profiles
# ---------------------------------------------------------------------------

EDITORIAL_PROFILES: Dict[str, Dict[str, Any]] = {
    "beta_clean": {
        "label": "Beta Clean — full local premium stack, GPU-safe, no external APIs",
        "min_complete_idea_score": 0.70,
        "min_hook_executable": True,
        "min_visual_executable": True,
        "min_renderability_score": 0.55,
        "min_editorial_value_score": 0.50,
        "min_brand_fit_score": 0.40,
        "min_final_contract_score": 0.55,
        "allow_repair": True,
        "allow_hook_card_fallback": True,
        "allow_semantic_card_fallback": True,
        "allow_extend_boundary": True,
        "bts_penalty_threshold": 0.22,
        "bts_penalty_weight": 0.70,
        "audio_caption_fit_penalty_threshold": 0.50,
        "audio_caption_fit_penalty_weight": 0.85,
        "duration_min_s": 6.0,
        "duration_max_s": 120.0,
        "duration_fit_penalty_weight": 0.90,
    },
    "vpi_publishable": {
        "label": "VPI Publishable — higher bar for published content",
        "min_complete_idea_score": 0.75,
        "min_hook_executable": True,
        "min_visual_executable": True,
        "min_renderability_score": 0.60,
        "min_editorial_value_score": 0.55,
        "min_brand_fit_score": 0.45,
        "min_final_contract_score": 0.55,
        "allow_repair": True,
        "allow_hook_card_fallback": True,
        "allow_semantic_card_fallback": True,
        "allow_extend_boundary": True,
        "bts_penalty_threshold": 0.18,
        "bts_penalty_weight": 0.60,
        "audio_caption_fit_penalty_threshold": 0.60,
        "audio_caption_fit_penalty_weight": 0.80,
        "duration_min_s": 8.0,
        "duration_max_s": 90.0,
        "duration_fit_penalty_weight": 0.85,
    },
    "premium": {
        "label": "Premium — highest bar, full pipeline",
        "min_complete_idea_score": 0.85,
        "min_hook_executable": True,
        "min_visual_executable": True,
        "min_renderability_score": 0.75,
        "min_editorial_value_score": 0.70,
        "min_brand_fit_score": 0.60,
        "min_final_contract_score": 0.70,
        "allow_repair": True,
        "allow_hook_card_fallback": True,
        "allow_semantic_card_fallback": True,
        "allow_extend_boundary": True,
        "bts_penalty_threshold": 0.15,
        "bts_penalty_weight": 0.50,
        "audio_caption_fit_penalty_threshold": 0.70,
        "audio_caption_fit_penalty_weight": 0.75,
        "duration_min_s": 10.0,
        "duration_max_s": 75.0,
        "duration_fit_penalty_weight": 0.80,
    },
    "dev_debug": {
        "label": "Dev Debug — permissive, logs all dimensions",
        "min_complete_idea_score": 0.30,
        "min_hook_executable": False,
        "min_visual_executable": False,
        "min_renderability_score": 0.20,
        "min_editorial_value_score": 0.20,
        "min_brand_fit_score": 0.10,
        "min_final_contract_score": 0.15,
        "allow_repair": True,
        "allow_hook_card_fallback": True,
        "allow_semantic_card_fallback": True,
        "allow_extend_boundary": True,
        "bts_penalty_threshold": 0.35,
        "bts_penalty_weight": 0.90,
        "audio_caption_fit_penalty_threshold": 0.30,
        "audio_caption_fit_penalty_weight": 0.95,
        "duration_min_s": 3.0,
        "duration_max_s": 300.0,
        "duration_fit_penalty_weight": 0.95,
    },
}

DEFAULT_PROFILE = "beta_clean"

# ---------------------------------------------------------------------------
# Text helpers (mirrored from task_service.py for standalone use)
# ---------------------------------------------------------------------------

_SETUP_PREFIXES = (
    "bueno", "pues", "entonces", "osea", "o sea", "eh", "ah", "este",
    "es que", "la verdad es que", "lo que pasa es que", "a ver",
    "mira", "oye", "vamos a ver", "a ver si", "si te digo",
    "yo creo que", "yo pienso que", "yo diria", "yo diría",
    "hay que tener en cuenta", "lo primero", "lo siguiente",
    "antes de nada", "antes que nada", "para empezar",
)

_CONTENT_TERMS = (
    "seguro", "cobertura", "poliza", "póliza", "cubre", "cubrir",
    "protege", "proteger", "proteccion", "protección",
    "familia", "tranquilidad", "contratar", "firmar",
    "condiciones", "revisa", "revisión", "revision",
    "prima", "precio", "coste", "descuento", "ahorro",
    "riesgo", "problema", "sorpresa", "ojo", "cuidado",
    "salud", "medico", "médico", "hospital", "consulta",
    "fallecimiento", "decesos", "duelo",
    "asesor", "gestor", "tramite", "trámite", "papeles",
    "indemnizacion", "indemnización", "capital",
    "vida", "futuro", "planificar", "organizar",
    "herencia", "herederos", "testamento",
    "invalidez", "dependencia", "accidente",
)

_CONNECTOR_ENDINGS = (
    "y", "e", "ni", "o", "u", "pero", "sino", "mas", "sin embargo",
    "no obstante", "aunque", "si bien", "a pesar de",
    "porque", "ya que", "puesto que", "dado que",
    "para que", "a fin de que", "con el fin de",
    "si", "como", "cuando", "mientras", "antes de que",
    "despues de que", "después de que", "en cuanto",
    "ademas", "además", "tambien", "también",
    "incluso", "es mas", "es más", "por otro lado",
    "por otra parte", "en primer lugar", "por ultimo", "por último",
)

_PRE_RENDER_HOOK_TERMS = (
    "sabes", "sabéis", "saben", "sabe", "sabemos",
    "imagina", "imagínate", "imaginate", "piensa", "piénsalo",
    "te has preguntado", "te has parado", "te has planteado",
    "alguna vez", "nunca te", "cuantas veces", "cuántas veces",
    "lo que nadie te cuenta", "lo que no te dicen",
    "esto es clave", "esto es importante", "esto es lo que",
    "atencion", "atención", "cuidado", "ojo",
    "si pasa", "y si", "nadie te cuenta",
    "la clave", "el secreto", "lo mas importante", "lo más importante",
    "vamos a ver", "vamos a hablar", "hoy te voy a contar",
    "te voy a explicar", "te voy a decir",
    "lo primero que", "lo siguiente que",
    "hay algo que", "hay una cosa",
    "sabias que", "sabías que",
)

_PRE_RENDER_FILLER_PREFIXES = _SETUP_PREFIXES


def _normalize_text_loose(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _is_sentence_end(text: str) -> bool:
    stripped = (text or "").strip()
    return stripped.endswith((".", "!", "?", "…"))


def _has_content_terms(text: str) -> bool:
    normalized = _normalize_text_loose(text)
    return any(term in normalized for term in _CONTENT_TERMS)


def _segment_duration_seconds(segment: Dict[str, Any]) -> float:
    start_s = _parse_timestamp_to_seconds(str(segment.get("start_time") or "00:00"))
    end_s = _parse_timestamp_to_seconds(str(segment.get("end_time") or "00:00"))
    return max(0.0, end_s - start_s)


def _json_safe(value: Any, _seen: Optional[set] = None, _depth: int = 0, _max_depth: int = 24) -> Any:
    """Convert arbitrary values into JSON-safe primitives.

    Hardened (H12.9) against the manifest/summary RecursionError confirmed in
    H12.7/H12.8: telescoped `final_mp4_contract -> final_output_truth ->
    final_mp4_contract -> ...` structures could grow past Python's recursion
    limit with no true id()-cycle. We guard on both id()-based cycles AND
    raw depth, truncating gracefully instead of recursing forever or raising.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, (dict, list, tuple, set)):
        if _seen is None:
            _seen = set()
        obj_id = id(value)
        if obj_id in _seen:
            logger.warning(
                "VPI_JSON_SAFE_TRUNCATED_CYCLE depth=%d type=%s",
                _depth,
                type(value).__name__,
            )
            return {"_truncated": "circular_reference", "_type": type(value).__name__}
        if _depth > _max_depth:
            logger.warning(
                "VPI_JSON_SAFE_TRUNCATED_MAX_DEPTH depth=%d max_depth=%d type=%s",
                _depth,
                _max_depth,
                type(value).__name__,
            )
            return {"_truncated": "max_depth", "_type": type(value).__name__}

        _seen = _seen | {obj_id}
        if isinstance(value, dict):
            return {
                str(k): _json_safe(v, _seen=_seen, _depth=_depth + 1, _max_depth=_max_depth)
                for k, v in value.items()
            }
        if isinstance(value, set):
            return [
                _json_safe(item, _seen=_seen, _depth=_depth + 1, _max_depth=_max_depth)
                for item in sorted(value, key=lambda item: str(item))
            ]
        return [
            _json_safe(item, _seen=_seen, _depth=_depth + 1, _max_depth=_max_depth)
            for item in value
        ]

    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return {"_type": "bytes", "len": len(value)}
    if isinstance(value, BaseException):
        return {"_type": value.__class__.__name__, "message": str(value)}
    if hasattr(value, "isoformat") and not isinstance(value, (str, bytes)):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    try:
        return str(value)
    except Exception:
        return "<unserializable>"


def _safe_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _dedupe_strings(values: List[Any]) -> List[str]:
    return list(dict.fromkeys([str(value) for value in values if str(value)]))


def _normalize_manifest_path_truth(path_value: Any) -> Dict[str, Any]:
    raw_path = str(path_value or "").strip()
    if not raw_path:
        return {
            "container_path": "",
            "host_or_relative_path": "",
            "relative_path": "",
            "exists": False,
        }
    candidate = Path(raw_path)
    if raw_path.startswith("/app/"):
        relative = raw_path.removeprefix("/app/").lstrip("/")
        host_candidate = Path.cwd() / relative
        host_or_relative_path = str(host_candidate)
        relative_path = relative
        exists = bool(host_candidate.exists())
    elif candidate.is_absolute():
        host_candidate = candidate
        host_or_relative_path = str(host_candidate)
        try:
            relative_path = str(candidate.relative_to(Path.cwd()))
        except Exception:
            relative_path = str(candidate)
        exists = bool(candidate.exists())
    else:
        host_candidate = Path.cwd() / raw_path
        host_or_relative_path = str(host_candidate)
        relative_path = raw_path
        exists = bool(host_candidate.exists())
    return {
        "container_path": raw_path,
        "host_or_relative_path": host_or_relative_path,
        "relative_path": relative_path,
        "exists": exists,
    }


def _slugify_filename_part(value: Any, fallback: str = "na", max_length: int = 28) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", _normalize_text_loose(str(value or "")))
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        text = fallback
    return text[:max_length].strip("_") or fallback


def _time_token(value: Any) -> str:
    raw = str(value or "").strip()
    seconds = _parse_timestamp_to_seconds(raw) if raw else 0.0
    if seconds <= 0:
        if raw:
            cleaned = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")
            return cleaned[:18] or "0s"
        return "0s"
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    if minutes > 0:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def build_vpi_clip_filename(
    *,
    task_id: str,
    clip_id: Any,
    campaign_intent: str,
    clip_angle: str,
    confidence_label: str,
    start_time: Any,
    end_time: Any,
    existing_filenames: Optional[List[str]] = None,
) -> Dict[str, Any]:
    campaign_part = _slugify_filename_part(campaign_intent, fallback="general_vpi", max_length=22)
    angle_part = _slugify_filename_part(clip_angle, fallback="general_insight", max_length=24)
    confidence_part = _slugify_filename_part(confidence_label, fallback="medium", max_length=12)
    start_token = _time_token(start_time)
    end_token = _time_token(end_time)
    clip_seed = f"{task_id}|{clip_id}|{campaign_part}|{angle_part}|{confidence_part}|{start_token}|{end_token}"
    clip_hash = hashlib.sha1(clip_seed.encode("utf-8")).hexdigest()[:6]
    clip_token = _slugify_filename_part(clip_id, fallback="clip", max_length=18)
    base_stem = f"vpi_{campaign_part}_{angle_part}_{confidence_part}_{start_token}_{end_token}_{clip_token}_{clip_hash}"
    max_stem_length = 160
    sanitized_stem = re.sub(r"[^a-z0-9_]+", "_", base_stem.lower())
    sanitized_stem = re.sub(r"_+", "_", sanitized_stem).strip("_")
    collision_resolved = sanitized_stem != base_stem
    if len(sanitized_stem) > max_stem_length:
        sanitized_stem = sanitized_stem[:max_stem_length].rstrip("_")
        collision_resolved = True
    candidate = f"{sanitized_stem}.mp4"
    existing = {str(name) for name in (existing_filenames or []) if str(name)}
    if candidate in existing:
        collision_resolved = True
        candidate = f"{sanitized_stem}_{clip_hash}.mp4"
        if candidate in existing:
            candidate = f"{sanitized_stem}_{clip_hash}_r2.mp4"
    return {
        "filename": candidate,
        "output_filename_safe": True,
        "output_filename_strategy": "vpi_{campaign_intent}_{clip_angle}_{confidence}_{start}_{end}_{clip_id_hash}",
        "output_filename_collision_resolved": bool(collision_resolved),
        "output_filename_base": f"{sanitized_stem}.mp4",
        "output_filename_hash": clip_hash,
        "output_filename_stem": sanitized_stem,
    }


def build_vpi_output_manifest(
    *,
    task_id: str,
    clip_outputs: List[Dict[str, Any]],
    final_mp4_contract: Optional[Dict[str, Any]] = None,
    clip_brief: Optional[Dict[str, Any]] = None,
    campaign_metadata: Optional[Dict[str, Any]] = None,
    package_diversity_metadata: Optional[Dict[str, Any]] = None,
    audio_visual_qc_summary: Optional[Dict[str, Any]] = None,
    output_paths: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    final_contract = dict(final_mp4_contract or {})
    campaign_meta = dict(campaign_metadata or {})
    package_meta = dict(package_diversity_metadata or {})
    qc_meta = dict(audio_visual_qc_summary or {})
    paths = dict(output_paths or {})
    manifest_output_path = str(paths.get("manifest_output_path") or "")
    summary_output_path = str(paths.get("summary_output_path") or "")
    output_root = str(paths.get("output_root") or "")
    clips_output_dir = str(paths.get("clips_output_dir") or "")
    manifests_output_dir = str(paths.get("manifests_output_dir") or "")
    summaries_output_dir = str(paths.get("summaries_output_dir") or "")
    output_filename_strategy = str(paths.get("output_filename_strategy") or "vpi_{campaign_intent}_{clip_angle}_{confidence}_{start}_{end}_{clip_id_hash}")

    clips: List[Dict[str, Any]] = []
    warning_counter: Dict[str, int] = {}
    publishable_total = 0
    review_total = 0
    audio_ok_total = 0
    visual_ok_total = 0
    cta_ok_total = 0
    for idx, raw_clip in enumerate(clip_outputs or []):
        clip = dict(raw_clip or {})
        # H12.9: do NOT _json_safe-walk the carried-forward contract wholesale —
        # it can be telescoped (final_mp4_contract -> final_output_truth -> ...)
        # past Python's recursion limit (H12.8 RecursionError diagnosis). A shallow
        # dict() copy preserves every scalar field the loop below reads via .get()
        # without recursing into nested structures.
        _raw_final_contract = clip.get("final_mp4_contract") or final_contract
        final_contract_clip = dict(_raw_final_contract) if isinstance(_raw_final_contract, dict) else {}
        final_mp4_contract_summary = {
            "final_output_path": str(final_contract_clip.get("final_output_path") or clip.get("final_output_path") or ""),
            "final_output_exists": bool(final_contract_clip.get("final_output_exists") if final_contract_clip.get("final_output_exists") is not None else clip.get("final_output_exists", False)),
            "final_probe_ok": bool(final_contract_clip.get("final_probe_ok") if final_contract_clip.get("final_probe_ok") is not None else clip.get("final_probe_ok", False)),
            "final_output_verified": bool(final_contract_clip.get("final_output_verified") if final_contract_clip.get("final_output_verified") is not None else clip.get("final_output_verified", False)),
            "final_duration": float(final_contract_clip.get("final_duration") or clip.get("final_duration") or clip.get("duration") or 0.0),
            "final_file_size": int(final_contract_clip.get("final_file_size") or clip.get("final_file_size") or 0),
            "boundary_confidence": float(final_contract_clip.get("boundary_confidence") or clip.get("boundary_confidence") or 0.0),
            "complete_idea_score": float(final_contract_clip.get("complete_idea_score") or clip.get("complete_idea_score") or 0.0),
            "incomplete_viral_window_detected": bool(final_contract_clip.get("incomplete_viral_window_detected") or clip.get("incomplete_viral_window_detected") or False),
            "final_publishable": bool(final_contract_clip.get("final_publishable") if final_contract_clip.get("final_publishable") is not None else clip.get("final_publishable", False)),
            "final_needs_review": bool(final_contract_clip.get("final_needs_review") if final_contract_clip.get("final_needs_review") is not None else clip.get("final_needs_review", False)),
            "blocking": list(_safe_list(final_contract_clip.get("final_blocking_reasons") or clip.get("final_blocking_reasons"))),
            "warnings": list(_safe_list(final_contract_clip.get("final_warning_reasons") or clip.get("final_warning_reasons"))),
        }
        logger.info(
            "VPI_MANIFEST_FINAL_CONTRACT_LIGHTWEIGHT_PROJECTION_USED clip_id=%s idx=%d",
            clip.get("clip_id") or clip.get("clip_order") or (idx + 1),
            idx,
        )
        _clip_brief_json = _json_safe(clip.get("clip_brief") or clip_brief or {})
        clip_brief_local = dict(_clip_brief_json) if isinstance(_clip_brief_json, dict) else {}
        clip_output_path = str(
            clip.get("final_output_path")
            or final_contract_clip.get("final_output_path")
            or clip.get("organized_output_path")
            or clip.get("output_file_path")
            or clip.get("path")
            or ""
        )
        audio_status = {
            "final_audio_chain_ok": bool(clip.get("final_audio_chain_ok") if clip.get("final_audio_chain_ok") is not None else final_contract_clip.get("final_audio_chain_ok", True)),
            "final_audio_loudness_ok": bool(clip.get("final_audio_loudness_ok") if clip.get("final_audio_loudness_ok") is not None else final_contract_clip.get("final_audio_loudness_ok", True)),
            "final_audio_silence_likely": bool(clip.get("final_audio_silence_likely") if clip.get("final_audio_silence_likely") is not None else final_contract_clip.get("final_audio_silence_likely", False)),
            "bgm_final_status": str(clip.get("bgm_final_status") or final_contract_clip.get("bgm_final_status") or ""),
            "sfx_final_status": str(clip.get("sfx_final_status") or final_contract_clip.get("sfx_final_status") or ""),
            "audio_mastering_final_status": str(clip.get("audio_mastering_final_status") or final_contract_clip.get("audio_mastering_final_status") or ""),
        }
        visual_status = {
            "visual_identity_ok": bool(clip.get("visual_identity_ok") if clip.get("visual_identity_ok") is not None else final_contract_clip.get("visual_identity_ok", True)),
            "visual_layout_ok": bool(clip.get("visual_layout_ok") if clip.get("visual_layout_ok") is not None else final_contract_clip.get("visual_layout_ok", True)),
            "visual_style_consistency_ok": bool(clip.get("visual_style_consistency_ok") if clip.get("visual_style_consistency_ok") is not None else final_contract_clip.get("visual_style_consistency_ok", True)),
            "premium_restraint_mode": str(clip.get("premium_restraint_mode") or final_contract_clip.get("premium_restraint_mode") or ""),
        }
        cta_status = {
            "cta_rendered": bool(clip.get("cta_rendered") if clip.get("cta_rendered") is not None else final_contract_clip.get("cta_rendered", False)),
            "cta_verified": bool(clip.get("cta_verified") if clip.get("cta_verified") is not None else final_contract_clip.get("cta_verified", False)),
            "cta_safety_ok": bool(clip.get("cta_safety_ok") if clip.get("cta_safety_ok") is not None else final_contract_clip.get("cta_safety_ok", False)),
            "brand_final_verified": bool(clip.get("brand_final_verified") if clip.get("brand_final_verified") is not None else final_contract_clip.get("brand_final_verified", False)),
        }
        warnings = _dedupe_strings(
            list(_safe_list(clip.get("final_warning_reasons")))
            + list(_safe_list(clip.get("publishable_warnings")))
            + list(_safe_list(clip.get("clip_review_flags")))
            + list(_safe_list(clip.get("output_management_warnings")))
            + list(_safe_list(clip.get("metadata_consistency_warnings")))
            + list(_safe_list(clip.get("package_diversity_warnings")))
            + list(_safe_list(clip.get("visual_layout_warnings")))
            + list(_safe_list(clip.get("visual_identity_warnings")))
        )
        for warning in warnings:
            warning_counter[warning] = warning_counter.get(warning, 0) + 1
        if bool(clip.get("final_publishable") if clip.get("final_publishable") is not None else final_contract_clip.get("final_publishable", False)):
            publishable_total += 1
        if bool(clip.get("final_needs_review") if clip.get("final_needs_review") is not None else final_contract_clip.get("final_needs_review", False)):
            review_total += 1
        if bool(audio_status["final_audio_chain_ok"]) and bool(audio_status["final_audio_loudness_ok"]) and not bool(audio_status["final_audio_silence_likely"]):
            audio_ok_total += 1
        if bool(visual_status["visual_identity_ok"]) and bool(visual_status["visual_layout_ok"]) and bool(visual_status["visual_style_consistency_ok"]):
            visual_ok_total += 1
        if bool(cta_status["cta_rendered"]) and bool(cta_status["cta_verified"]) and bool(cta_status["cta_safety_ok"]):
            cta_ok_total += 1

        clip_entry = {
            "clip_id": clip.get("clip_id") or clip.get("clip_order") or idx + 1,
            "file_path": clip_output_path,
            "filename": str(Path(str(clip_output_path or clip.get("filename") or "")).name),
            "duration": float(clip.get("duration") or 0.0),
            "original_start_time": str(clip.get("original_start_time") or clip.get("start_time") or ""),
            "original_end_time": str(clip.get("original_end_time") or clip.get("end_time") or ""),
            "refined_start_time": str(clip.get("refined_start_time") or clip.get("start_time") or ""),
            "refined_end_time": str(clip.get("refined_end_time") or clip.get("end_time") or ""),
            "campaign_intent": str(clip.get("campaign_intent") or campaign_meta.get("campaign_intent") or "general_vpi"),
            "clip_angle": str(clip.get("clip_angle") or ""),
            "clip_value_proposition": str(clip.get("clip_value_proposition") or ""),
            "clip_confidence_label": str(clip.get("clip_confidence_label") or ""),
            "clip_recommended_cta": str(clip.get("clip_recommended_cta") or ""),
            "selected_for_reason": str(clip.get("selected_for_reason") or ""),
            "final_publishable": bool(clip.get("final_publishable") if clip.get("final_publishable") is not None else final_contract_clip.get("final_publishable", False)),
            "final_needs_review": bool(clip.get("final_needs_review") if clip.get("final_needs_review") is not None else final_contract_clip.get("final_needs_review", False)),
            "main_warnings": warnings,
            "audio_status": audio_status,
            "visual_status": visual_status,
            "cta_status": cta_status,
            "clip_brief": clip_brief_local,
            "final_warning_reasons": list(_safe_list(clip.get("final_warning_reasons"))),
            "final_blocking_reasons": list(_safe_list(clip.get("final_blocking_reasons"))),
            "publishable_warnings": list(_safe_list(clip.get("publishable_warnings"))),
            "clip_review_flags": list(_safe_list(clip.get("clip_review_flags"))),
            "output_management_warnings": list(_safe_list(clip.get("output_management_warnings"))),
            "final_output_path": str(clip.get("final_output_path") or final_contract_clip.get("final_output_path") or clip_output_path or ""),
            "final_output_path_container": str(clip.get("final_output_path_container") or final_contract_clip.get("final_output_path_container") or ""),
            "final_output_path_relative": str(clip.get("final_output_path_relative") or final_contract_clip.get("final_output_path_relative") or ""),
            "final_output_path_host_or_relative": str(clip.get("final_output_path_host_or_relative") or final_contract_clip.get("final_output_path_host_or_relative") or ""),
            "final_output_exists": bool(clip.get("final_output_exists") if clip.get("final_output_exists") is not None else final_contract_clip.get("final_output_exists", False)),
            "final_file_size": int(clip.get("final_file_size") or final_contract_clip.get("final_file_size") or 0),
            "final_duration": float(clip.get("final_duration") or final_contract_clip.get("final_duration") or clip.get("duration") or 0.0),
            "final_probe_ok": bool(clip.get("final_probe_ok") if clip.get("final_probe_ok") is not None else final_contract_clip.get("final_probe_ok", False)),
            "final_video_stream_ok": bool(clip.get("final_video_stream_ok") if clip.get("final_video_stream_ok") is not None else final_contract_clip.get("final_video_stream_ok", False)),
            "final_audio_stream_ok": bool(clip.get("final_audio_stream_ok") if clip.get("final_audio_stream_ok") is not None else final_contract_clip.get("final_audio_stream_ok", False)),
            "final_output_verified": bool(clip.get("final_output_verified") if clip.get("final_output_verified") is not None else final_contract_clip.get("final_output_verified", False)),
            "final_output_entity_relation": str(clip.get("final_output_entity_relation") or final_contract_clip.get("final_output_entity_relation") or final_contract.get("final_output_entity_relation") or ""),
            "final_mp4_contract_summary": final_mp4_contract_summary,
            "final_mp4_contract_truncated": True,
            "final_mp4_contract_summary_source": "lightweight_projection",
        }
        clips.append(_json_safe(clip_entry))

    package_summary = _json_safe({
        "campaign_intent": str(campaign_meta.get("campaign_intent") or final_contract.get("campaign_intent") or "general_vpi"),
        "campaign_intent_confidence": float(campaign_meta.get("campaign_intent_confidence") or final_contract.get("campaign_intent_confidence") or 0.0),
        "campaign_intent_source": str(campaign_meta.get("campaign_intent_source") or final_contract.get("campaign_intent_source") or "default_general"),
        "clip_count": len(clips),
        "package_diversity_score": float(package_meta.get("package_diversity_score") or final_contract.get("package_diversity_score") or 0.0),
        "package_diversity_reason": str(package_meta.get("package_diversity_reason") or final_contract.get("package_diversity_reason") or ""),
        "package_category_distribution": dict(package_meta.get("package_category_distribution") or final_contract.get("package_category_distribution") or {}),
        "package_theme_distribution": dict(package_meta.get("package_theme_distribution") or final_contract.get("package_theme_distribution") or {}),
        "package_duration_balance_ok": bool(package_meta.get("package_duration_balance_ok") if package_meta.get("package_duration_balance_ok") is not None else final_contract.get("package_duration_balance_ok", False)),
        "package_duration_warnings": list(_safe_list(package_meta.get("package_duration_warnings") or final_contract.get("package_duration_warnings") or [])),
        "high_confidence_clip_count": int(package_meta.get("high_confidence_clip_count") or final_contract.get("high_confidence_clip_count") or 0),
        "review_clip_count": int(package_meta.get("review_clip_count") or final_contract.get("review_clip_count") or review_total),
        "selected_clip_package_summary": dict(package_meta.get("selected_clip_package_summary") or final_contract.get("selected_clip_package_summary") or {}),
        "campaign_alignment_score": float(campaign_meta.get("campaign_alignment_score") or final_contract.get("campaign_alignment_score") or 0.0),
        "campaign_alignment_reason": str(campaign_meta.get("campaign_alignment_reason") or final_contract.get("campaign_alignment_reason") or ""),
        "selected_campaign_mix": dict(campaign_meta.get("selected_campaign_mix") or final_contract.get("selected_campaign_mix") or {}),
        "sensitive_handling_required": bool(campaign_meta.get("sensitive_handling_required") if campaign_meta.get("sensitive_handling_required") is not None else final_contract.get("sensitive_handling_required", False)),
    })
    publishable_summary = _json_safe({
        "total_clips": len(clips),
        "publishable_clip_count": publishable_total,
        "review_clip_count": review_total,
        "publishable_ratio": round(publishable_total / len(clips), 3) if clips else 0.0,
        "all_publishable": bool(clips) and publishable_total == len(clips),
        "all_review_free": review_total == 0,
    })
    top_warnings = sorted(warning_counter.items(), key=lambda item: (-item[1], item[0]))[:10]
    warnings_summary = _json_safe({
        "warning_count": sum(warning_counter.values()),
        "unique_warning_count": len(warning_counter),
        "top_warnings": [{"warning": warning, "count": count} for warning, count in top_warnings],
    })
    recommended_next_actions = [
        "Review clips with final_needs_review=true before publishing",
    ]
    if review_total > 0:
        recommended_next_actions.append("Prioritize clips flagged by review flags or low-confidence briefs")
    if top_warnings:
        recommended_next_actions.append(f"Address the most frequent warning: {top_warnings[0][0]}")
    if not clips:
        recommended_next_actions.append("No clips were selected for output")

    manifest_final_truth = _normalize_manifest_path_truth(
        final_contract.get("final_output_path")
        or (clips[0].get("final_output_path") if clips else "")
        or (clips[0].get("file_path") if clips else "")
        or final_contract.get("path")
        or ""
    )
    manifest_final_path = str(final_contract.get("final_output_path") or manifest_final_truth.get("host_or_relative_path") or manifest_final_truth.get("container_path") or "")
    manifest_final_path_container = str(final_contract.get("final_output_path_container") or manifest_final_truth.get("container_path") or "")
    manifest_final_path_relative = str(final_contract.get("final_output_path_relative") or manifest_final_truth.get("relative_path") or "")
    manifest_final_exists = bool(final_contract.get("final_output_exists") if final_contract.get("final_output_exists") is not None else manifest_final_truth.get("exists", False))
    manifest_final_file_size = int(final_contract.get("final_file_size") or 0)
    if not manifest_final_file_size and manifest_final_truth.get("exists"):
        try:
            manifest_final_file_size = int(Path(str(manifest_final_path or manifest_final_truth.get("host_or_relative_path") or manifest_final_truth.get("container_path"))).stat().st_size)
        except Exception:
            manifest_final_file_size = 0
    manifest_final_duration = float(final_contract.get("final_duration") or (clips[0].get("final_duration") if clips else 0.0) or 0.0)
    manifest_final_probe_ok = bool(final_contract.get("final_probe_ok") if final_contract.get("final_probe_ok") is not None else False)
    manifest_final_video_stream_ok = bool(final_contract.get("final_video_stream_ok") if final_contract.get("final_video_stream_ok") is not None else False)
    manifest_final_audio_stream_ok = bool(final_contract.get("final_audio_stream_ok") if final_contract.get("final_audio_stream_ok") is not None else False)
    manifest_final_output_verified = bool(final_contract.get("final_output_verified") if final_contract.get("final_output_verified") is not None else False)
    manifest_final_entity_relation = str(final_contract.get("final_output_entity_relation") or manifest_final_truth.get("entity_relation") or final_contract.get("final_output_truth", {}).get("final_output_entity_relation") or "unknown")
    logger.info(
        "VPI_OUTPUT_MANIFEST_FINAL_PATH_SET task_id=%s path=%s exists=%s",
        task_id,
        manifest_final_path,
        str(manifest_final_exists).lower(),
    )
    logger.info(
        "VPI_OUTPUT_MANIFEST_FINAL_TRUTH_ATTACHED task_id=%s relation=%s verified=%s",
        task_id,
        manifest_final_entity_relation,
        str(manifest_final_output_verified).lower(),
    )

    return {
        "manifest_version": "e1",
        "task_id": str(task_id or ""),
        "created_at": now,
        "output_root": output_root,
        "clips_output_dir": clips_output_dir,
        "manifests_output_dir": manifests_output_dir,
        "summaries_output_dir": summaries_output_dir,
        "manifest_output_path": manifest_output_path,
        "summary_output_path": summary_output_path,
        "output_filename_strategy": output_filename_strategy,
        "final_output_path": manifest_final_path,
        "final_output_path_container": manifest_final_path_container,
        "final_output_path_relative": manifest_final_path_relative,
        "final_output_exists": manifest_final_exists,
        "final_file_size": manifest_final_file_size,
        "final_duration": manifest_final_duration,
        "final_probe_ok": manifest_final_probe_ok,
        "final_video_stream_ok": manifest_final_video_stream_ok,
        "final_audio_stream_ok": manifest_final_audio_stream_ok,
        "final_output_verified": manifest_final_output_verified,
        "final_output_entity_relation": manifest_final_entity_relation,
        "clips": clips,
        "package_summary": package_summary,
        "publishable_summary": publishable_summary,
        "warnings_summary": warnings_summary,
        "recommended_next_actions": recommended_next_actions,
        "audio_visual_qc_summary": _json_safe(qc_meta),
        "campaign_metadata": _json_safe(campaign_meta),
        "package_diversity_metadata": _json_safe(package_meta),
        "final_mp4_contract": _json_safe(final_contract),
        "output_management_ok": bool(manifest_output_path),
    }


def build_vpi_local_review_bundle(
    *,
    output_manifest: Optional[Dict[str, Any]] = None,
    task_id: str,
    clips: List[Dict[str, Any]],
    clip_briefs: Optional[List[Dict[str, Any]]] = None,
    final_contracts: Optional[List[Dict[str, Any]]] = None,
    output_paths: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    manifest = dict(output_manifest or {})
    paths = dict(output_paths or {})
    review_bundle_dir = str(paths.get("review_bundle_dir") or "")
    review_index_path = str(paths.get("review_index_path") or "")
    review_json_path = str(paths.get("review_json_path") or "")
    bundle_version = "e1"
    warnings: List[str] = []
    review_ready = False

    def _safe_rel_path(path_value: Any) -> str:
        raw = str(path_value or "")
        if not raw:
            return ""
        try:
            return str(Path(raw).name if not raw.startswith("..") else Path(raw))
        except Exception:
            return raw

    bundle_clips: List[Dict[str, Any]] = []
    for idx, raw_clip in enumerate(clips or []):
        clip = dict(raw_clip or {})
        clip_brief = dict((clip_briefs or [{}])[idx] if idx < len(clip_briefs or []) and isinstance((clip_briefs or [{}])[idx], dict) else {})
        final_contract = dict((final_contracts or [{}])[idx] if idx < len(final_contracts or []) and isinstance((final_contracts or [{}])[idx], dict) else {})
        filename = str(clip.get("filename") or Path(str(clip.get("file_path") or "")).name or "")
        file_path = str(clip.get("file_path") or clip.get("organized_output_path") or clip.get("output_file_path") or "")
        relative_file_path = str(Path("..") / "clips" / filename) if filename else ""
        exists = bool(file_path and Path(file_path).exists())
        clip_warnings = _dedupe_strings(
            list(_safe_list(clip.get("main_warnings")))
            + list(_safe_list(clip.get("clip_review_flags")))
            + list(_safe_list(clip.get("final_warning_reasons")))
            + list(_safe_list(clip.get("publishable_warnings")))
        )
        if not exists:
            clip_warnings = _dedupe_strings(clip_warnings + ["missing_mp4"])
            warnings.append(f"missing_mp4:{filename or clip.get('clip_id') or idx + 1}")
        bundle_clips.append(_json_safe({
            "clip_id": clip.get("clip_id") or clip.get("clip_order") or idx + 1,
            "file_path": file_path,
            "relative_file_path": relative_file_path,
            "campaign_intent": str(clip.get("campaign_intent") or manifest.get("campaign_metadata", {}).get("campaign_intent") or ""),
            "clip_angle": str(clip.get("clip_angle") or ""),
            "clip_value_proposition": str(clip.get("clip_value_proposition") or clip_brief.get("clip_value_proposition") or ""),
            "clip_confidence_label": str(clip.get("clip_confidence_label") or clip_brief.get("clip_confidence_label") or ""),
            "clip_recommended_cta": str(clip.get("clip_recommended_cta") or clip_brief.get("clip_recommended_cta") or ""),
            "final_publishable": bool(clip.get("final_publishable") if clip.get("final_publishable") is not None else final_contract.get("final_publishable", False)),
            "final_needs_review": bool(clip.get("final_needs_review") if clip.get("final_needs_review") is not None else final_contract.get("final_needs_review", False)),
            "warnings": clip_warnings,
            "review_flags": list(_safe_list(clip.get("clip_review_flags"))),
            "duration": float(clip.get("duration") or 0.0),
            "refined_start_time": str(clip.get("refined_start_time") or clip.get("start_time") or ""),
            "refined_end_time": str(clip.get("refined_end_time") or clip.get("end_time") or ""),
        }))

    dominant_campaign = str((manifest.get("campaign_metadata") or {}).get("campaign_intent") or (manifest.get("package_summary") or {}).get("campaign_intent") or "general_vpi")
    publishable_total = sum(1 for clip in bundle_clips if bool(clip.get("final_publishable")))
    review_total = sum(1 for clip in bundle_clips if bool(clip.get("final_needs_review")))
    high_confidence_total = sum(1 for clip in clips or [] if str((clip or {}).get("clip_confidence_label") or "") == "high")
    bundle_json = _json_safe({
        "review_bundle_version": bundle_version,
        "task_id": str(task_id or ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "review_ready": False,
        "warnings": list(dict.fromkeys(warnings)),
        "dominant_campaign_intent": dominant_campaign,
        "summary": {
            "total_clips": len(bundle_clips),
            "publishable_clips": publishable_total,
            "review_clips": review_total,
            "high_confidence_clips": high_confidence_total,
        },
        "clips": bundle_clips,
        "manifest": _json_safe(manifest),
    })

    if review_json_path:
        try:
            Path(review_json_path).parent.mkdir(parents=True, exist_ok=True)
            Path(review_json_path).write_text(json.dumps(bundle_json, indent=2, ensure_ascii=False), encoding="utf-8")
            review_ready = True
            bundle_json["review_ready"] = True
            logger.info("VPI_REVIEW_BUNDLE_JSON_WRITTEN task_id=%s path=%s", task_id, review_json_path)
        except Exception as exc:
            warnings.append(f"review_json_write_failed:{exc}")
            logger.warning("VPI_REVIEW_BUNDLE_WARNING task_id=%s reason=review_json_failed error=%s", task_id, exc)
    else:
        warnings.append("review_json_path_missing")

    if review_index_path:
        try:
            Path(review_index_path).parent.mkdir(parents=True, exist_ok=True)
            cards: List[str] = []
            for clip in bundle_clips:
                filename = html.escape(str(Path(str(clip.get("relative_file_path") or clip.get("file_path") or "")).name))
                rel_src = html.escape(str(clip.get("relative_file_path") or ""))
                title = html.escape(str(clip.get("filename") or filename or "clip"))
                campaign = html.escape(str(clip.get("campaign_intent") or ""))
                angle = html.escape(str(clip.get("clip_angle") or ""))
                conf = html.escape(str(clip.get("clip_confidence_label") or ""))
                cta = html.escape(str(clip.get("clip_recommended_cta") or ""))
                value_prop = html.escape(str(clip.get("clip_value_proposition") or ""))
                warnings_text = html.escape(", ".join(clip.get("warnings") or []) or "none")
                review_flags_text = html.escape(", ".join(clip.get("review_flags") or []) or "none")
                publishable_text = "yes" if clip.get("final_publishable") else "no"
                cards.append(
                    f"""
                    <section class=\"clip-card\">
                      <div class=\"clip-media\">
                        <video controls preload=\"metadata\" src=\"{rel_src}\"></video>
                      </div>
                      <div class=\"clip-body\">
                        <h2>{title}</h2>
                        <div class=\"meta\"><strong>Campaign:</strong> {campaign} | <strong>Angle:</strong> {angle} | <strong>Confidence:</strong> {conf} | <strong>Publishable:</strong> {publishable_text}</div>
                        <div class=\"meta\"><strong>CTA:</strong> {cta}</div>
                        <div class=\"meta\"><strong>Value proposition:</strong> {value_prop}</div>
                        <div class=\"meta\"><strong>Warnings:</strong> {warnings_text}</div>
                        <div class=\"meta\"><strong>Review flags:</strong> {review_flags_text}</div>
                      </div>
                    </section>
                    """
                )
            html_doc = f"""<!doctype html>
            <html lang=\"es\">
            <head>
              <meta charset=\"utf-8\">
              <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
              <title>VPI Review Bundle — {html.escape(str(task_id or ''))}</title>
              <style>
                :root {{
                  color-scheme: dark;
                  --bg: #0f1115;
                  --panel: #171b22;
                  --panel-strong: #1d232d;
                  --text: #eef2f7;
                  --muted: #a9b3c2;
                  --accent: #7fb0ff;
                  --border: #293241;
                }}
                * {{ box-sizing: border-box; }}
                body {{ margin: 0; padding: 24px; background: linear-gradient(180deg, #0f1115, #0c0f14); color: var(--text); font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
                .wrap {{ max-width: 1280px; margin: 0 auto; }}
                .hero {{ background: var(--panel); border: 1px solid var(--border); border-radius: 18px; padding: 20px 22px; margin-bottom: 20px; }}
                h1 {{ margin: 0 0 8px; font-size: 28px; }}
                .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-top: 14px; }}
                .stat {{ background: var(--panel-strong); border: 1px solid var(--border); border-radius: 14px; padding: 12px; }}
                .stat .label {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }}
                .stat .value {{ font-size: 20px; margin-top: 4px; font-weight: 700; }}
                .clips {{ display: grid; gap: 18px; }}
                .clip-card {{ display: grid; grid-template-columns: minmax(320px, 420px) 1fr; gap: 16px; background: var(--panel); border: 1px solid var(--border); border-radius: 18px; padding: 16px; }}
                .clip-media video {{ width: 100%; border-radius: 14px; background: #000; aspect-ratio: 9 / 16; object-fit: cover; }}
                .clip-body h2 {{ margin: 0 0 8px; font-size: 18px; }}
                .meta {{ color: var(--muted); margin-top: 8px; line-height: 1.45; }}
                @media (max-width: 900px) {{
                  .clip-card {{ grid-template-columns: 1fr; }}
                }}
              </style>
            </head>
            <body>
              <div class=\"wrap\">
                <div class=\"hero\">
                  <h1>VPI Review Bundle</h1>
                  <div>Task <code>{html.escape(str(task_id or ''))}</code></div>
                  <div class=\"summary\">
                    <div class=\"stat\"><div class=\"label\">Total clips</div><div class=\"value\">{len(bundle_clips)}</div></div>
                    <div class=\"stat\"><div class=\"label\">Publishable</div><div class=\"value\">{publishable_total}</div></div>
                    <div class=\"stat\"><div class=\"label\">Review</div><div class=\"value\">{review_total}</div></div>
                    <div class=\"stat\"><div class=\"label\">High confidence</div><div class=\"value\">{high_confidence_total}</div></div>
                    <div class=\"stat\"><div class=\"label\">Dominant campaign</div><div class=\"value\">{html.escape(dominant_campaign)}</div></div>
                  </div>
                </div>
                <div class=\"clips\">
                  {''.join(cards)}
                </div>
              </div>
            </body>
            </html>"""
            Path(review_index_path).write_text(html_doc, encoding="utf-8")
            logger.info("VPI_REVIEW_INDEX_WRITTEN task_id=%s path=%s", task_id, review_index_path)
        except Exception as exc:
            warnings.append(f"review_index_write_failed:{exc}")
            review_ready = False
            logger.warning("VPI_REVIEW_BUNDLE_WARNING task_id=%s reason=review_index_failed error=%s", task_id, exc)
    else:
        warnings.append("review_index_path_missing")

    if warnings:
        logger.warning("VPI_REVIEW_BUNDLE_WARNING task_id=%s warnings=%s", task_id, warnings)
    logger.info(
        "VPI_REVIEW_BUNDLE_COMPLETE task_id=%s ready=%s clips=%d warnings=%d",
        task_id,
        str(review_ready).lower(),
        len(bundle_clips),
        len(warnings),
    )

    return {
        "review_bundle_version": bundle_version,
        "review_bundle_dir": review_bundle_dir,
        "review_index_path": review_index_path,
        "review_json_path": review_json_path,
        "review_ready": bool(review_ready),
        "review_warnings": list(dict.fromkeys(warnings)),
        "review_bundle_json": bundle_json,
    }


def _parse_timestamp_to_seconds(value: str) -> float:
    raw = str(value or "0").strip()
    parts = raw.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        return float(raw)
    except Exception:
        return 0.0


def _detect_verbal_hook(text: str) -> Tuple[bool, List[str]]:
    normalized = _normalize_text_loose(text)
    if not normalized:
        return False, []
    words = [w for w in normalized.split(" ") if w]
    first_window = " ".join(words[:16])
    hits = [term for term in _PRE_RENDER_HOOK_TERMS if term in first_window]
    question_or_tension = ("?" in text) or any(term in first_window for term in ("si pasa", "y si", "nadie te cuenta"))
    strong = bool(hits) or question_or_tension
    return strong, hits


def _derive_hook_card_text(segment: Dict[str, Any]) -> str:
    text = _normalize_text_loose(str(segment.get("text") or ""))
    editorial = _normalize_text_loose(str(segment.get("editorial_type") or ""))
    matched = _normalize_text_loose(" ".join(str(x or "") for x in (segment.get("matched_patterns") or [])))
    blob = f"{text} {editorial} {matched}".strip()
    if any(token in blob for token in ("cubre", "cobertura", "poliza", "póliza", "seguro")):
        return "No todos los seguros cubren igual"
    if any(token in blob for token in ("contratar", "firmar", "condiciones", "revisa")):
        return "Revisa esto antes de contratar"
    if any(token in blob for token in ("familia", "tranquilidad", "proteccion", "protección")):
        return "La tranquilidad también se planifica"
    return "Esto conviene revisarlo antes"


def _derive_semantic_card_concept(text: str, segment: Dict[str, Any]) -> str:
    blob = _normalize_text_loose(
        " ".join(
            [
                text or "",
                str(segment.get("editorial_type") or ""),
                " ".join(str(x or "") for x in (segment.get("matched_patterns") or [])),
                str(segment.get("clean_take_topic") or ""),
            ]
        )
    )
    concept_keywords = [
        ("salud", ("salud", "medic", "hospital", "consulta")),
        ("proteccion", ("proteccion", "proteg", "cobertura", "familia")),
        ("decesos", ("decesos", "fallecimiento", "duelo")),
        ("revision", ("revisa", "revisión", "condiciones", "antes de contratar")),
        ("cobertura", ("cobertura", "poliza", "póliza", "cubre")),
        ("riesgo", ("riesgo", "ojo", "cuidado", "problema", "sorpresa")),
        ("ahorro", ("ahorro", "precio", "prima", "descuento", "coste")),
    ]
    for concept, needles in concept_keywords:
        if any(needle in blob for needle in needles):
            return concept
    return "proteccion"


# ---------------------------------------------------------------------------
# Flexibility Engine — Helper Functions
# ---------------------------------------------------------------------------

def _infer_publishing_intent(segment: Dict[str, Any]) -> str:
    """Infer publishing intent from editorial_type, matched_patterns, and transcript text.

    Returns one of PUBLISHING_INTENTS or "educate" as default.
    """
    text = _normalize_text_loose(str(segment.get("text") or ""))
    editorial_type = _normalize_text_loose(str(segment.get("editorial_type") or ""))
    matched = [_normalize_text_loose(str(x or "")) for x in (segment.get("matched_patterns") or [])]
    blob = f"{text} {editorial_type} {' '.join(matched)}"

    # Score each intent by pattern matches
    scores: Dict[str, int] = {}
    for intent, patterns in _INTENT_PATTERNS.items():
        score = sum(1 for p in patterns if p in blob)
        if score > 0:
            scores[intent] = score

    if not scores:
        return "educate"

    # Return highest-scoring intent
    best = max(scores, key=scores.get)
    return best


def _generate_smart_cta(publishing_intent: str) -> str:
    """Generate a short, non-aggressive, VPI-safe CTA based on publishing intent.

    In beta_clean, CTA is metadata/suggestion only — never rendered as overlay.
    """
    suggestions = _CTA_SUGGESTIONS.get(publishing_intent, _CTA_SUGGESTIONS["educate"])
    # Return first suggestion as default (deterministic)
    return suggestions[0] if suggestions else "Consulta con tu asesor"


def _compute_commercial_usefulness_score(segment: Dict[str, Any]) -> float:
    """Score commercial usefulness of a segment.

    Increases for: client objection, myth/debunk, risk warning, actionable advice,
    coverage explanation, etc.
    Decreases for: generic motivational talk, meta/BTS setup, repeated idea,
    low specificity, no insurance relevance.

    Returns 0.0–1.0 score.
    """
    text = _normalize_text_loose(str(segment.get("text") or ""))
    editorial_type = _normalize_text_loose(str(segment.get("editorial_type") or ""))
    matched = [_normalize_text_loose(str(x or "")) for x in (segment.get("matched_patterns") or [])]
    blob = f"{text} {editorial_type} {' '.join(matched)}"

    # Base score
    score = 0.50

    # Increase factors
    increase_count = sum(1 for term in _COMMERCIAL_INCREASE_TERMS if term in blob)
    score += min(0.40, increase_count * 0.08)

    # Decrease factors
    decrease_count = sum(1 for term in _COMMERCIAL_DECREASE_TERMS if term in blob)
    score -= min(0.30, decrease_count * 0.06)

    # Editorial type bonus
    if editorial_type in {"objection", "myth_debunk", "risk_warning", "coverage_explain", "actionable_advice"}:
        score += 0.15
    elif editorial_type in {"weak_intro", "bts", "meta", "generic_motivation"}:
        score -= 0.15

    return round(max(0.0, min(1.0, score)), 4)


def _apply_brand_voice(text: str) -> str:
    """Sanitize text to align with VPI brand voice.

    Replaces avoid_words with preferred alternatives where possible.
    """
    if not text:
        return text
    normalized = text.lower()
    # Replace avoid words with safer alternatives
    replacements = {
        "desgracia": "situación",
        "tragedia": "imprevisto",
        "catástrofe": "situación grave",
        "catastrofe": "situación grave",
        "horror": "preocupación",
        "pánico": "preocupación",
        "panico": "preocupación",
        "miedo": "duda",
        "terrible": "complicado",
        "espantoso": "difícil",
        "estafa": "engaño",
        "timar": "confundir",
        "engañar": "confundir",
    }
    result = text
    for old, new in replacements.items():
        result = result.replace(old, new)
    return result


def _compute_severity(
    reject_reasons: List[str],
    repair_actions: List[Dict[str, Any]],
    would_runtime_reject: bool,
    approved: bool,
) -> Dict[str, Any]:
    """Classify each issue into BLOCKER / REPAIRABLE / PENALTY / INFO.

    Returns a dict with:
        severity_map: dict mapping reason -> severity level
        blockers: list of BLOCKER reasons
        repairable: list of REPAIRABLE reasons
        penalties: list of PENALTY reasons
        infos: list of INFO reasons
        max_severity: highest severity level present
    """
    severity_map: Dict[str, str] = {}

    for reason in reject_reasons:
        # Determine severity based on reason content
        if "complete_idea_score" in reason:
            if any(a.get("type") == "extend_boundary" for a in repair_actions):
                severity_map[reason] = SEVERITY_REPAIRABLE
            else:
                severity_map[reason] = SEVERITY_BLOCKER
        elif "hook_not_executable" in reason:
            if any(a.get("type") == "hook_card_fallback" for a in repair_actions):
                severity_map[reason] = SEVERITY_REPAIRABLE
            else:
                severity_map[reason] = SEVERITY_BLOCKER
        elif "visual_not_executable" in reason:
            if any(a.get("type") == "semantic_card_fallback" for a in repair_actions):
                severity_map[reason] = SEVERITY_REPAIRABLE
            else:
                severity_map[reason] = SEVERITY_BLOCKER
        elif "renderability_score" in reason:
            severity_map[reason] = SEVERITY_PENALTY
        elif "editorial_value_score" in reason:
            severity_map[reason] = SEVERITY_PENALTY
        elif "brand_fit_score" in reason:
            severity_map[reason] = SEVERITY_PENALTY
        elif "final_contract_score" in reason:
            severity_map[reason] = SEVERITY_PENALTY
        elif "rhythm_out_of_bounds" in reason:
            severity_map[reason] = SEVERITY_PENALTY
        elif "no_bgm_tracks_available" in reason:
            severity_map[reason] = SEVERITY_INFO
        elif "hook_fit_no_candidate_or_transcript" in reason:
            severity_map[reason] = SEVERITY_BLOCKER
        elif "visual_fit_no_candidate_or_transcript" in reason:
            severity_map[reason] = SEVERITY_BLOCKER
        else:
            severity_map[reason] = SEVERITY_INFO

    # Also classify repair actions as INFO
    for action in repair_actions:
        action_type = action.get("type", "")
        severity_map[f"repair:{action_type}"] = SEVERITY_INFO

    blockers = [k for k, v in severity_map.items() if v == SEVERITY_BLOCKER]
    repairable = [k for k, v in severity_map.items() if v == SEVERITY_REPAIRABLE]
    penalties = [k for k, v in severity_map.items() if v == SEVERITY_PENALTY]
    infos = [k for k, v in severity_map.items() if v == SEVERITY_INFO]

    max_severity = SEVERITY_INFO
    if blockers:
        max_severity = SEVERITY_BLOCKER
    elif repairable:
        max_severity = SEVERITY_REPAIRABLE
    elif penalties:
        max_severity = SEVERITY_PENALTY

    return {
        "severity_map": severity_map,
        "blockers": blockers,
        "repairable": repairable,
        "penalties": penalties,
        "infos": infos,
        "max_severity": max_severity,
    }


def _compute_diversity_key(segment: Dict[str, Any], publishing_intent: str) -> str:
    """Compute a diversity key for editorial diversity selection.

    Combines editorial_type, publishing_intent, and clean_take_topic.
    """
    editorial_type = str(segment.get("editorial_type") or "unknown")
    topic = str(segment.get("clean_take_topic") or "general")
    return f"{editorial_type}:{publishing_intent}:{topic}"


# ---------------------------------------------------------------------------
# Repair-or-Reject Ladder
# ---------------------------------------------------------------------------

def _repair_extend_boundary(
    segment: Dict[str, Any],
    *,
    task_id: str,
    profile: Dict[str, Any],
) -> Dict[str, Any]:
    """Attempt to repair a segment that fails complete_idea by extending its boundary.

    Returns a dict with keys:
        repaired: bool
        new_start_s: float
        new_end_s: float
        repair_action: str
        repair_reason: str
    """
    duration_s = _segment_duration_seconds(segment)
    text = str(segment.get("text") or "").strip()
    words = [w for w in re.split(r"\s+", text) if w]

    # If the segment is very short, try extending end by 20%
    if duration_s < profile.get("duration_min_s", 6.0) and len(words) < 12:
        new_end_s = _parse_timestamp_to_seconds(str(segment.get("end_time") or "00:00")) + (duration_s * 0.20)
        logger.info(
            "EXTEND_BOUNDARY_REPAIR task_id=%s action=extend_end original_duration=%.2f new_duration=%.2f",
            task_id,
            duration_s,
            new_end_s - _parse_timestamp_to_seconds(str(segment.get("start_time") or "00:00")),
        )
        return {
            "repaired": True,
            "new_start_s": _parse_timestamp_to_seconds(str(segment.get("start_time") or "00:00")),
            "new_end_s": new_end_s,
            "repair_action": "extend_end",
            "repair_reason": f"segment_too_short_duration={duration_s:.2f}_words={len(words)}",
        }

    # If the segment doesn't end with sentence-ending punctuation, try extending
    if not _is_sentence_end(text):
        new_end_s = _parse_timestamp_to_seconds(str(segment.get("end_time") or "00:00")) + min(3.0, duration_s * 0.15)
        logger.info(
            "EXTEND_BOUNDARY_REPAIR task_id=%s action=extend_end_to_complete_idea original_duration=%.2f",
            task_id,
            duration_s,
        )
        return {
            "repaired": True,
            "new_start_s": _parse_timestamp_to_seconds(str(segment.get("start_time") or "00:00")),
            "new_end_s": new_end_s,
            "repair_action": "extend_end_to_complete_idea",
            "repair_reason": "segment_ends_mid_sentence",
        }

    return {
        "repaired": False,
        "new_start_s": _parse_timestamp_to_seconds(str(segment.get("start_time") or "00:00")),
        "new_end_s": _parse_timestamp_to_seconds(str(segment.get("end_time") or "00:00")),
        "repair_action": "",
        "repair_reason": "cannot_repair_boundary",
    }


def _repair_hook_card(
    segment: Dict[str, Any],
    *,
    task_id: str,
    profile: Dict[str, Any],
) -> Dict[str, Any]:
    """Attempt to repair missing hook support with a hook_card fallback.

    Returns a dict with keys:
        repaired: bool
        hook_text: str
        hook_start_s: float
        hook_duration_s: float
        repair_action: str
        repair_reason: str
    """
    if not profile.get("allow_hook_card_fallback", True):
        return {
            "repaired": False,
            "hook_text": "",
            "hook_start_s": 0.0,
            "hook_duration_s": 0.0,
            "repair_action": "",
            "repair_reason": "hook_card_fallback_disabled_by_profile",
        }

    hook_text = _derive_hook_card_text(segment)
    if not hook_text:
        return {
            "repaired": False,
            "hook_text": "",
            "hook_start_s": 0.0,
            "hook_duration_s": 0.0,
            "repair_action": "",
            "repair_reason": "no_hook_card_text_derived",
        }

    duration_s = _segment_duration_seconds(segment)
    logger.info(
        "HOOK_CARD_REPAIR task_id=%s hook_text=%s",
        task_id,
        hook_text[:120],
    )
    return {
        "repaired": True,
        "hook_text": hook_text,
        "hook_start_s": 0.25,
        "hook_duration_s": min(1.8, duration_s * 0.15),
        "repair_action": "hook_card_fallback",
        "repair_reason": "no_verbal_hook_or_overlay_planned",
    }


def _repair_semantic_card(
    segment: Dict[str, Any],
    *,
    task_id: str,
    profile: Dict[str, Any],
) -> Dict[str, Any]:
    """Attempt to repair missing visual support with a semantic_card fallback.

    Returns a dict with keys:
        repaired: bool
        semantic_text: str
        semantic_concept: str
        visual_time_range: List[float]
        repair_action: str
        repair_reason: str
    """
    if not profile.get("allow_semantic_card_fallback", True):
        return {
            "repaired": False,
            "semantic_text": "",
            "semantic_concept": "",
            "visual_time_range": [0.0, 0.0],
            "repair_action": "",
            "repair_reason": "semantic_card_fallback_disabled_by_profile",
        }

    text = str(segment.get("text") or "").strip()
    words = [w for w in re.split(r"\s+", text) if w]
    semantic_text = " ".join(words[:9]).strip() if len(words) >= 9 else text[:80]
    if not semantic_text:
        return {
            "repaired": False,
            "semantic_text": "",
            "semantic_concept": "",
            "visual_time_range": [0.0, 0.0],
            "repair_action": "",
            "repair_reason": "no_semantic_text_derived",
        }

    semantic_concept = _derive_semantic_card_concept(text, segment)
    duration_s = _segment_duration_seconds(segment)
    logger.info(
        "SEMANTIC_CARD_REPAIR task_id=%s concept=%s text=%s",
        task_id,
        semantic_concept,
        semantic_text[:120],
    )
    return {
        "repaired": True,
        "semantic_text": semantic_text,
        "semantic_concept": semantic_concept,
        "visual_time_range": [0.25, min(duration_s, 2.4)],
        "repair_action": "semantic_card_fallback",
        "repair_reason": "no_motion_overlay_or_broll_available",
    }


def _repair_soft_trim_hint(
    segment: Dict[str, Any],
    *,
    task_id: str,
    profile: Dict[str, Any],
) -> Dict[str, Any]:
    """Attempt to repair a segment with poor rhythm by suggesting a soft trim hint.

    This does NOT modify the segment itself — it adds a metadata hint for the
    editing pipeline to apply a soft trim (e.g., remove filler words, tighten
    pauses). This is a non-destructive repair that improves words_per_second
    without changing the underlying audio.

    Returns a dict with keys:
        repaired: bool
        trim_hint: str
        repair_action: str
        repair_reason: str
    """
    if not profile.get("allow_soft_trim_hint", True):
        return {
            "repaired": False,
            "trim_hint": "",
            "repair_action": "",
            "repair_reason": "soft_trim_hint_disabled_by_profile",
        }

    text = str(segment.get("text") or "").strip()
    words = [w for w in re.split(r"\s+", text) if w]
    duration_s = _segment_duration_seconds(segment)
    if duration_s <= 0:
        return {
            "repaired": False,
            "trim_hint": "",
            "repair_action": "",
            "repair_reason": "zero_duration_segment",
        }

    words_per_second = len(words) / duration_s

    # Only repair if rhythm is too slow (too many pauses)
    if words_per_second >= 0.8:
        return {
            "repaired": False,
            "trim_hint": "",
            "repair_action": "",
            "repair_reason": f"rhythm_already_ok_wps={words_per_second:.2f}",
        }

    # Suggest trimming filler words and tightening pauses
    filler_words = [
        "eh", "em", "ah", "este", "pues", "bueno", "entonces",
        "o sea", "digamos", "como que", "es decir", "la verdad",
        "basicamente", "básicamente", "en realidad", "por así decirlo",
    ]
    normalized = text.lower()
    filler_count = sum(1 for fw in filler_words if fw in normalized)

    logger.info(
        "SOFT_TRIM_HINT task_id=%s wps=%.2f filler_count=%d",
        task_id,
        words_per_second,
        filler_count,
    )

    return {
        "repaired": True,
        "trim_hint": "soft_trim_filler_and_tighten_pauses",
        "repair_action": "soft_trim_hint",
        "repair_reason": f"rhythm_too_slow_wps={words_per_second:.2f}_fillers={filler_count}",
    }


def _repair_lower_requirements(
    segment: Dict[str, Any],
    *,
    task_id: str,
    profile: Dict[str, Any],
) -> Dict[str, Any]:
    """Attempt to repair by lowering non-blocking requirements.

    This is a last-resort repair that relaxes non-critical thresholds:
    - Reduces min_duration requirement
    - Relaxes BTS penalty threshold
    - Reduces min word count for complete_idea

    This does NOT modify the segment — it returns relaxed thresholds that
    the caller can apply to re-evaluate.

    Returns a dict with keys:
        repaired: bool
        relaxed_thresholds: dict
        repair_action: str
        repair_reason: str
    """
    if not profile.get("allow_lower_requirements", True):
        return {
            "repaired": False,
            "relaxed_thresholds": {},
            "repair_action": "",
            "repair_reason": "lower_requirements_disabled_by_profile",
        }

    relaxed_thresholds = {
        "min_duration_s": max(3.0, profile.get("duration_min_s", 6.0) * 0.75),
        "min_word_count": 8,
        "bts_penalty_threshold": min(0.35, profile.get("bts_penalty_threshold", 0.22) * 1.5),
        "min_complete_idea_score": max(0.30, profile.get("min_complete_idea_score", 0.60) * 0.60),
    }

    logger.info(
        "LOWER_REQUIREMENTS_REPAIR task_id=%s relaxed=%s",
        task_id,
        relaxed_thresholds,
    )

    return {
        "repaired": True,
        "relaxed_thresholds": relaxed_thresholds,
        "repair_action": "lower_requirements",
        "repair_reason": f"applied_relaxed_thresholds_duration={relaxed_thresholds['min_duration_s']:.1f}_words={relaxed_thresholds['min_word_count']}",
    }


def _repair_brand_overlay(
    segment: Dict[str, Any],
    *,
    task_id: str,
    profile: Dict[str, Any],
) -> Dict[str, Any]:
    """Attempt to repair missing visual support by applying a brand overlay.

    This is a minimal visual fallback that uses the VPI brand logo/name as
    a simple overlay card. It is less intrusive than a full semantic_card
    and works when no motion overlay or broll is available.

    Returns a dict with keys:
        repaired: bool
        brand_text: str
        visual_time_range: List[float]
        repair_action: str
        repair_reason: str
    """
    if not profile.get("allow_brand_overlay_fallback", True):
        return {
            "repaired": False,
            "brand_text": "",
            "visual_time_range": [0.0, 0.0],
            "repair_action": "",
            "repair_reason": "brand_overlay_fallback_disabled_by_profile",
        }

    duration_s = _segment_duration_seconds(segment)
    brand_text = "VPI — Protección y tranquilidad"

    logger.info(
        "BRAND_OVERLAY_REPAIR task_id=%s duration=%.2f",
        task_id,
        duration_s,
    )

    return {
        "repaired": True,
        "brand_text": brand_text,
        "visual_time_range": [0.5, min(duration_s, 2.0)],
        "repair_action": "brand_overlay_fallback",
        "repair_reason": "no_motion_overlay_broll_or_semantic_card_available",
    }


# ---------------------------------------------------------------------------
# Renderability Score
# ---------------------------------------------------------------------------


def _compute_renderability_score(
    *,
    complete_idea_score: float,
    hook_executable_score: float,
    visual_support_score: float,
    duration_fit_score: float,
    bts_penalty: float,
    audio_caption_fit_score: float,
    profile: Dict[str, Any],
) -> float:
    """Compute composite renderability score.

    Components (each 0.0–1.0):
        complete_idea_score: how complete the idea is
        hook_executable_score: how executable the hook plan is
        visual_support_score: how executable the visual support plan is
        duration_fit_score: how well the segment fits the duration constraints
        bts_penalty: penalty for BTS contamination (1.0 = no penalty, <1.0 = penalty)
        audio_caption_fit_score: how well audio and caption fit together

    The score is the product of all components, each raised to a profile-specific
    weight. This ensures that a single zero component brings the score to zero,
    but penalties are graduated.
    """
    # Weights from profile (default to 1.0 if not specified)
    w_complete = 1.0
    w_hook = 1.0
    w_visual = 1.0
    w_duration = profile.get("duration_fit_penalty_weight", 0.90)
    w_bts = profile.get("bts_penalty_weight", 0.70)
    w_audio = profile.get("audio_caption_fit_penalty_weight", 0.85)

    score = (
        (complete_idea_score ** w_complete)
        * (hook_executable_score ** w_hook)
        * (visual_support_score ** w_visual)
        * (duration_fit_score ** w_duration)
        * (bts_penalty ** w_bts)
        * (audio_caption_fit_score ** w_audio)
    )
    return round(max(0.0, min(1.0, score)), 4)


def _segment_rescue_key(segment: Dict[str, Any]) -> str:
    for key in ("segment_id", "id", "theme", "topic"):
        value = str(segment.get(key) or "").strip()
        if value:
            return value[:80]
    text = str(segment.get("text") or "").strip()
    if text:
        return "text:" + hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return "segment:unknown"


# ---------------------------------------------------------------------------
# Schema Normalizer
# ---------------------------------------------------------------------------

def normalize_contract_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a contract result dict to guarantee a consistent schema.

    Ensures all required paths exist with sensible defaults so that
    consumers (simulator, preflight, validator) never see missing keys.
    """
    normalized = dict(result)

    # Ensure hook_support has all required keys
    hook = dict(normalized.get("hook_support") or {})
    hook.setdefault("type", "none")
    hook.setdefault("executable", False)
    hook.setdefault("asset_or_template", hook.get("asset") or "")
    hook.pop("asset", None)  # remove legacy key after mapping
    hook.setdefault("text", "")
    hook.setdefault("start_s", 0.0)
    hook.setdefault("duration_s", 0.0)
    hook.setdefault("evidence", "")
    normalized["hook_support"] = hook

    # Ensure visual_support has all required keys
    visual = dict(normalized.get("visual_support") or {})
    visual.setdefault("type", "none")
    visual.setdefault("executable", False)
    visual.setdefault("asset_or_template", visual.get("asset") or "")
    visual.pop("asset", None)  # remove legacy key after mapping
    visual.setdefault("concept", "")
    visual.setdefault("text", "")
    visual.setdefault("time_range", [0.0, 0.0])
    normalized["visual_support"] = visual

    # Ensure scalar fields
    normalized.setdefault("approved", False)
    normalized.setdefault("complete_idea_pass", False)
    normalized.setdefault("complete_idea_score", 0.0)
    normalized.setdefault("would_runtime_reject", True)
    normalized.setdefault("would_runtime_reject_reason", None)
    normalized.setdefault("repair_actions", [])
    normalized.setdefault("reject_reasons", [])
    normalized.setdefault("severity", {})
    normalized.setdefault("renderability_score", 0.0)
    normalized.setdefault("final_contract_score", 0.0)
    normalized.setdefault("metadata_to_apply", {})
    normalized.setdefault("hookability_score", 0.0)
    normalized.setdefault("standalone_score", 0.0)
    normalized.setdefault("segment_selection_confidence", 0.0)
    normalized.setdefault("weak_segment_penalties", [])
    normalized.setdefault("weak_segment_reason", "")
    normalized.setdefault("selected_for_reason", "")
    normalized.setdefault("rejected_for_reason", "")
    normalized.setdefault("vpi_editorial_categories", [])
    normalized.setdefault("weak_editorial_segment", False)
    normalized.setdefault("original_start_time", "")
    normalized.setdefault("original_end_time", "")
    normalized.setdefault("refined_start_time", "")
    normalized.setdefault("refined_end_time", "")
    normalized.setdefault("boundary_adjustment_applied", False)
    normalized.setdefault("boundary_adjustment_reason", "")
    normalized.setdefault("start_trim_seconds", 0.0)
    normalized.setdefault("start_extend_seconds", 0.0)
    normalized.setdefault("end_extend_seconds", 0.0)
    normalized.setdefault("end_trim_seconds", 0.0)
    normalized.setdefault("payoff_preserved", False)
    normalized.setdefault("starts_cleanly", True)
    normalized.setdefault("ends_cleanly", True)
    normalized.setdefault("first_second_strength", 0.0)
    normalized.setdefault("first_second_reason", "")
    normalized.setdefault("boundary_confidence", 0.0)
    normalized.setdefault("standalone_after_boundary_score", 0.0)
    normalized.setdefault("standalone_after_boundary_reason", "")
    normalized.setdefault("start_filler_trimmed", False)
    normalized.setdefault("start_trim_reason", "")
    normalized.setdefault("start_context_extended", False)
    normalized.setdefault("start_context_reason", "")
    normalized.setdefault("payoff_extended", False)
    normalized.setdefault("payoff_extension_reason", "")
    normalized.setdefault("end_cleaned", False)
    normalized.setdefault("end_clean_reason", "")
    normalized.setdefault("boundary_reverted", False)
    normalized.setdefault("boundary_reverted_reason", "")

    return normalized


# ---------------------------------------------------------------------------
# Main Contract Evaluator
# ---------------------------------------------------------------------------

def evaluate_editorial_contract(
    segment: Dict[str, Any],
    *,
    task_id: str,
    profile: str = DEFAULT_PROFILE,
    include_broll: bool = False,
    bgm_tracks_available: int = 0,
    overlay_candidate: Optional[Dict[str, Any]] = None,
    broll_suggestions: Optional[List[Dict[str, Any]]] = None,
    music_tracks: Optional[List[Any]] = None,
    asset_index: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Evaluate a single segment against the editorial contract.

    Parameters
    ----------
    segment : dict
        A candidate segment with at least 'text', 'start_time', 'end_time'.
    task_id : str
        Task ID for logging.
    profile : str
        Editorial policy profile key (beta_clean, vpi_publishable, premium, dev_debug).
    include_broll : bool
        Whether broll is enabled for this task.
    bgm_tracks_available : int
        Number of BGM tracks available.
    overlay_candidate : dict or None
        Pre-computed overlay candidate (from select_motion_overlay_candidate).
    broll_suggestions : list or None
        Pre-computed broll suggestions for the segment.
    music_tracks : list or None
        Pre-computed music tracks list.
    asset_index : dict or None
        Pre-computed asset index.

    Returns
    -------
    dict with keys:
        approved: bool
        profile: str
        complete_idea_pass: bool
        complete_idea_score: float
        hook_support: dict
        visual_support: dict
        renderability_score: float
        editorial_value_score: float
        brand_fit_score: float
        final_contract_score: float
        would_runtime_reject: bool
        repair_actions: list
        reject_reasons: list
        metadata_to_apply: dict
        pre_render_edit_plan: dict
        pre_qc: dict
    """
    profile_config = EDITORIAL_PROFILES.get(profile, EDITORIAL_PROFILES[DEFAULT_PROFILE])
    text = str(segment.get("text") or "").strip()
    normalized = _normalize_text_loose(text)
    words = [w for w in re.split(r"\s+", text) if w]
    duration_s = _segment_duration_seconds(segment)
    bts_ratio = float(segment.get("bts_contamination_ratio") or 0.0)

    repair_actions: List[Dict[str, Any]] = []
    reject_reasons: List[str] = []
    metadata_to_apply: Dict[str, Any] = {}

    # -----------------------------------------------------------------------
    # FASE 1 — Complete Idea Evaluation + Repair
    # -----------------------------------------------------------------------
    complete_idea_pass = bool(
        len(words) >= 12
        and (_has_content_terms(text) or str(segment.get("editorial_type") or "") not in {"", "weak_intro"})
    )
    complete_idea_score = 1.0 if complete_idea_pass else 0.0

    # Try runtime complete_idea_score from segment metadata
    _runtime_complete_idea_score = float(segment.get("complete_idea_score") or 0.0)
    if _runtime_complete_idea_score > 0 and _runtime_complete_idea_score < profile_config.get("min_complete_idea_score", 0.60):
        complete_idea_pass = False
        complete_idea_score = _runtime_complete_idea_score

    # Try score_complete_idea from fluency service
    try:
        from .vpi_editorial_fluency_service import score_complete_idea as _score_complete_idea
        _idea_eval = _score_complete_idea(text)
        _eval_score = float((_idea_eval or {}).get("complete_idea_score") or 0.0)
        if _eval_score > 0 and _eval_score < profile_config.get("min_complete_idea_score", 0.60):
            complete_idea_pass = False
            complete_idea_score = min(complete_idea_score, _eval_score) if complete_idea_score > 0 else _eval_score
    except Exception:
        pass

    # Repair: extend boundary if complete_idea fails
    if not complete_idea_pass and profile_config.get("allow_extend_boundary", True):
        boundary_repair = _repair_extend_boundary(segment, task_id=task_id, profile=profile_config)
        if boundary_repair["repaired"]:
            repair_actions.append({
                "type": "extend_boundary",
                "detail": boundary_repair["repair_reason"],
                "new_start_s": boundary_repair["new_start_s"],
                "new_end_s": boundary_repair["new_end_s"],
            })
            complete_idea_pass = True
            complete_idea_score = max(complete_idea_score, 0.60)
            metadata_to_apply["boundary_extended"] = True
            metadata_to_apply["boundary_extend_reason"] = boundary_repair["repair_reason"]

    no_mid_sentence_cut = bool(
        _is_sentence_end(text)
        or (len(words) >= 24 and duration_s >= 18.0 and not normalized.endswith(_CONNECTOR_ENDINGS))
    )

    # -----------------------------------------------------------------------
    # FASE 2 — Hook Support Evaluation + Repair
    # -----------------------------------------------------------------------
    verbal_hook, hook_hits = _detect_verbal_hook(text)
    hook_overlay_text = str(segment.get("hook_overlay_text") or "").strip()
    if not hook_overlay_text:
        hook_overlay_text = " ".join(words[:8]).strip() if len(words) >= 8 else ""

    hook_status = "none"
    hook_text = ""
    hook_start_s = 0.0
    hook_duration_s = 0.0

    if verbal_hook and hook_overlay_text:
        hook_status = "hybrid"
        hook_text = hook_overlay_text
        hook_start_s = 0.0
        hook_duration_s = 2.0
    elif verbal_hook:
        hook_status = "verbal"
        hook_text = " ".join(words[:10]).strip()
        hook_start_s = 0.0
        hook_duration_s = min(3.0, max(1.8, duration_s * 0.18))
    elif hook_overlay_text:
        hook_status = "overlay_card"
        hook_text = hook_overlay_text
        hook_start_s = 0.25
        hook_duration_s = 1.8

    hook_support_type = "none"
    hook_support_executable = False
    if hook_status in {"overlay_card", "hybrid"} and hook_text:
        hook_support_type = "hook_card"
        hook_support_executable = True
    elif hook_status == "verbal" and hook_text and len(words) >= 10:
        hook_support_type = "verbal_hook"
        hook_support_executable = True

    # Repair: hook_card fallback
    if not hook_support_executable and profile_config.get("allow_hook_card_fallback", True):
        hook_repair = _repair_hook_card(segment, task_id=task_id, profile=profile_config)
        if hook_repair["repaired"]:
            repair_actions.append({
                "type": "hook_card_fallback",
                "detail": hook_repair["repair_reason"],
                "hook_text": hook_repair["hook_text"][:120],
            })
            hook_status = "overlay_card"
            hook_support_type = "hook_card"
            hook_text = hook_repair["hook_text"]
            hook_start_s = hook_repair["hook_start_s"]
            hook_duration_s = hook_repair["hook_duration_s"]
            hook_support_executable = True
            metadata_to_apply["hook_card_applied"] = True
            metadata_to_apply["final_output_uses_overlay"] = True

    hook_executable_score = 1.0 if hook_support_executable else 0.0

    if not hook_support_executable:
        reject_reasons.append("hook_fit_no_candidate_or_transcript")

    # -----------------------------------------------------------------------
    # FASE 3 — Visual Support Evaluation + Repair
    # -----------------------------------------------------------------------
    # Determine whether verified motion overlay assets exist in the asset index.
    # In beta_clean profile, if no verified motion overlay assets are available,
    # we skip motion_overlay entirely and fall back to semantic_card.
    _verified_motion_overlay_assets_exist = False
    if asset_index is not None and isinstance(asset_index, dict):
        _overlays_section = asset_index.get("overlays") or asset_index.get("motion_overlays") or {}
        if isinstance(_overlays_section, dict):
            _items = _overlays_section.get("items") or _overlays_section.get("assets") or []
            if isinstance(_items, list):
                for _item in _items:
                    if isinstance(_item, dict) and _item.get("verified", False):
                        _verified_motion_overlay_assets_exist = True
                        break
        # Also check top-level verified_overlays key
        if not _verified_motion_overlay_assets_exist:
            _verified_list = asset_index.get("verified_overlays") or []
            if isinstance(_verified_list, list) and len(_verified_list) > 0:
                _verified_motion_overlay_assets_exist = True

    # Use provided overlay_candidate or compute one
    _overlay_candidate = overlay_candidate
    if _overlay_candidate is None and asset_index is not None:
        try:
            from .vpi_motion_overlay_service import select_motion_overlay_candidate
            _overlay_candidate = select_motion_overlay_candidate(
                text=text,
                topics=[str(segment.get("editorial_type") or ""), str(segment.get("clean_take_topic") or "")],
                tags=list(segment.get("matched_patterns") or []),
                editorial_signal={
                    "prefer_generated_icons": True,
                    "layer_overload": False,
                    "composition_mode": "balanced",
                },
                asset_index=asset_index,
            )
        except Exception:
            _overlay_candidate = {}

    overlay_path = str((_overlay_candidate or {}).get("motion_overlay_asset_path") or "").strip()
    overlay_planned = bool(_overlay_candidate and overlay_path)
    overlay_score = int((_overlay_candidate or {}).get("selector_score") or 0)
    overlay_keywords = list((_overlay_candidate or {}).get("matched_keywords") or [])
    overlay_verified = bool(
        overlay_planned
        and Path(overlay_path).exists()
        and bool((_overlay_candidate or {}).get("motion_overlay_manifest_verified", False))
    )
    overlay_concrete = bool(overlay_verified and (overlay_score >= 45 or len(overlay_keywords) >= 2))

    # ── Stricter gate: in beta_clean, motion_overlay requires verified assets ──
    _profile_name = profile or DEFAULT_PROFILE
    if overlay_concrete and _profile_name == "beta_clean" and not _verified_motion_overlay_assets_exist:
        logger.info(
            "VISUAL_SUPPORT_PLAN_REJECTED type=motion_overlay reason=no_verified_asset_or_template "
            "task_id=%s profile=%s overlay_score=%d overlay_keywords=%d",
            task_id,
            _profile_name,
            overlay_score,
            len(overlay_keywords),
        )
        overlay_concrete = False
        overlay_verified = False
        overlay_planned = False
        _overlay_candidate = {}

    _broll_suggestions = broll_suggestions or [item for item in (segment.get("broll_suggestions") or []) if isinstance(item, dict)]
    suggested_broll_cue_type = str(segment.get("suggested_broll_cue_type") or "").strip()
    broll_concrete = False
    broll_asset_or_template = ""
    if include_broll and _broll_suggestions:
        for item in _broll_suggestions:
            _p = str(item.get("local_path") or item.get("asset_path") or item.get("asset_id") or "").strip()
            if _p:
                _p_path = Path(_p)
                if _p.startswith("http://") or _p.startswith("https://") or _p.startswith("asset:"):
                    broll_concrete = True
                    broll_asset_or_template = _p
                    break
                if _p_path.exists():
                    broll_concrete = True
                    broll_asset_or_template = _p
                    break

    visual_support_planned = bool(overlay_concrete or broll_concrete)
    visual_type = "none"
    visual_concept = ""
    visual_asset = ""
    visual_text = ""
    visual_support_executable = False
    visual_time_range = [0.35, min(duration_s, 2.2)]

    if overlay_concrete:
        visual_type = "motion_overlay"
        visual_concept = str((_overlay_candidate or {}).get("overlay_concept") or "")
        visual_asset = str((_overlay_candidate or {}).get("motion_overlay_asset_id") or (_overlay_candidate or {}).get("motion_overlay_asset_path") or "")
        visual_support_executable = bool(visual_asset)
    elif broll_concrete:
        visual_type = "broll"
        visual_concept = suggested_broll_cue_type or "contextual_cutaway"
        visual_asset = broll_asset_or_template
        visual_time_range = [1.2, min(duration_s, 3.6)]
        visual_support_executable = bool(visual_asset)
    else:
        # Repair: semantic_card fallback
        if profile_config.get("allow_semantic_card_fallback", True):
            semantic_repair = _repair_semantic_card(segment, task_id=task_id, profile=profile_config)
            if semantic_repair["repaired"]:
                repair_actions.append({
                    "type": "semantic_card_fallback",
                    "detail": semantic_repair["repair_reason"],
                    "semantic_text": semantic_repair["semantic_text"][:120],
                })
                visual_type = "semantic_card"
                visual_concept = semantic_repair["semantic_concept"]
                visual_asset = "ffmpeg_text_card"
                visual_text = semantic_repair["semantic_text"]
                visual_time_range = semantic_repair["visual_time_range"]
                visual_support_executable = True
                metadata_to_apply["semantic_card_applied"] = True
                metadata_to_apply["overlay_card_applied"] = True
                metadata_to_apply["final_output_uses_overlay"] = True
                logger.info(
                    "VISUAL_SUPPORT_PLAN_SELECTED type=semantic_card executable=true "
                    "asset_or_template=ffmpeg_text_card concept=%s task_id=%s profile=%s",
                    visual_concept,
                    task_id,
                    _profile_name,
                )

    visual_support_score = 1.0 if visual_support_executable else 0.0

    if not visual_support_executable:
        reject_reasons.append("visual_fit_no_candidate_or_transcript")

    # -----------------------------------------------------------------------
    # FASE 4 — BGM / Music Track Evaluation
    # -----------------------------------------------------------------------
    bgm_available = bool(bgm_tracks_available > 0 or (music_tracks and len(music_tracks) > 0))
    bgm_score = 1.0 if bgm_available else 0.60
    if not bgm_available:
        reject_reasons.append("no_bgm_tracks_available")

    # -----------------------------------------------------------------------
    # FASE 5 — Rhythm / Cleanup Evaluation
    # -----------------------------------------------------------------------
    # Check if the segment has a reasonable rhythm (not too many pauses, not too dense)
    words_per_second = len(words) / max(duration_s, 1.0)
    rhythm_ok = bool(0.8 <= words_per_second <= 4.5)
    rhythm_score = 1.0 if rhythm_ok else 0.50
    if not rhythm_ok:
        reject_reasons.append(f"rhythm_out_of_bounds_wps={words_per_second:.2f}")

    # -----------------------------------------------------------------------
    # FASE 6 — Retention Editing Plan Evaluation
    # -----------------------------------------------------------------------
    # Check if the segment has a pre_render_edit_plan or can derive one
    pre_render_edit_plan: Dict[str, Any] = {}
    _existing_plan = segment.get("pre_render_edit_plan") or segment.get("edit_plan") or {}
    if isinstance(_existing_plan, dict) and _existing_plan:
        pre_render_edit_plan = _existing_plan
    else:
        # Derive a minimal edit plan
        pre_render_edit_plan = {
            "has_hook": hook_support_executable,
            "has_visual": visual_support_executable,
            "has_bgm": bgm_available,
            "hook_type": hook_support_type,
            "visual_type": visual_type,
            "estimated_duration_s": duration_s,
            "words_per_second": round(words_per_second, 2),
            "requires_caption_overlay": True,
            "requires_hook_overlay": hook_support_type == "hook_card",
            "requires_semantic_card": visual_type == "semantic_card",
        }

    retention_plan_score = 1.0 if (hook_support_executable and visual_support_executable) else 0.40

    # -----------------------------------------------------------------------
    # FASE 7 — Renderability Score
    # -----------------------------------------------------------------------
    # Duration fit score
    duration_min_s = profile_config.get("duration_min_s", 6.0)
    duration_max_s = profile_config.get("duration_max_s", 120.0)
    if duration_min_s <= duration_s <= duration_max_s:
        duration_fit_score = 1.0
    elif duration_s < duration_min_s:
        duration_fit_score = max(0.0, duration_s / duration_min_s)
    else:
        duration_fit_score = max(0.0, (duration_max_s * 1.5 - duration_s) / (duration_max_s * 0.5))
    duration_fit_score = round(max(0.0, min(1.0, duration_fit_score)), 4)

    # BTS penalty
    bts_penalty_threshold = profile_config.get("bts_penalty_threshold", 0.22)
    bts_penalty = 1.0
    if bts_ratio > bts_penalty_threshold:
        normalized_text = _normalize_text_loose(text)
        strong_dialogue_anchor = (
            any(term in normalized_text for term in _INSURANCE_ANCHOR_TERMS)
            and complete_idea_score >= 0.55
            and words_per_second >= 1.15
        )
        meta_production = any(term in normalized_text for term in _META_PRODUCTION_TERMS)
        if strong_dialogue_anchor and not meta_production:
            bts_penalty = max(0.90, 1.0 - (bts_ratio - bts_penalty_threshold) * 0.35)
            metadata_to_apply["bts_override_used"] = True
            metadata_to_apply["bts_override_reason"] = "strong_vpi_dialogue_anchor"
        else:
            bts_penalty = max(0.0, 1.0 - (bts_ratio - bts_penalty_threshold))
            if meta_production:
                metadata_to_apply["meta_production_or_bts"] = True
    bts_penalty = round(max(0.0, min(1.0, bts_penalty)), 4)

    # Audio-caption fit score
    audio_caption_fit_score = 1.0
    _audio_caption_fit = float(segment.get("audio_caption_fit_score") or 0.0)
    if _audio_caption_fit > 0:
        audio_caption_fit_score = _audio_caption_fit
    audio_caption_fit_score = round(max(0.0, min(1.0, audio_caption_fit_score)), 4)

    renderability_score = _compute_renderability_score(
        complete_idea_score=complete_idea_score,
        hook_executable_score=hook_executable_score,
        visual_support_score=visual_support_score,
        duration_fit_score=duration_fit_score,
        bts_penalty=bts_penalty,
        audio_caption_fit_score=audio_caption_fit_score,
        profile=profile_config,
    )

    # -----------------------------------------------------------------------
    # FASE 8 — Editorial Value Score
    # -----------------------------------------------------------------------
    editorial_value_score = round(
        (complete_idea_score * 0.30)
        + (hook_executable_score * 0.25)
        + (visual_support_score * 0.20)
        + (rhythm_score * 0.10)
        + (retention_plan_score * 0.15),
        4,
    )

    # -----------------------------------------------------------------------
    # FASE 9 — Brand Fit Score
    # -----------------------------------------------------------------------
    brand_fit_score = 1.0
    _brand_fit = float(segment.get("brand_fit_score") or 0.0)
    if _brand_fit > 0:
        brand_fit_score = _brand_fit
    else:
        # Derive from content terms and editorial type
        if _has_content_terms(text):
            brand_fit_score = 0.85
        elif str(segment.get("editorial_type") or "") not in {"", "weak_intro"}:
            brand_fit_score = 0.70
        else:
            brand_fit_score = 0.50
    brand_fit_score = round(max(0.0, min(1.0, brand_fit_score)), 4)

    # -----------------------------------------------------------------------
    # FASE 10 — Flexibility Engine: Publishing Intent, Commercial Usefulness, CTA, Brand Voice, Severity, Diversity
    # -----------------------------------------------------------------------
    publishing_intent = _infer_publishing_intent(segment)
    commercial_usefulness_score = _compute_commercial_usefulness_score(segment)
    cta_suggestion = _generate_smart_cta(publishing_intent)
    diversity_key = _compute_diversity_key(segment, publishing_intent)
    hookability_score = float(segment.get("hookability_score") or 0.0)
    standalone_score = float(segment.get("standalone_score") or 0.0)
    segment_selection_confidence = float(segment.get("segment_selection_confidence") or 0.0)
    weak_segment_penalties = list(segment.get("weak_segment_penalties") or [])
    weak_segment_reason = str(segment.get("weak_segment_reason") or "")
    selected_for_reason = str(segment.get("selected_for_reason") or "")
    rejected_for_reason = str(segment.get("rejected_for_reason") or "")
    vpi_editorial_categories = list(segment.get("vpi_editorial_categories") or [])
    boundary_confidence = float(segment.get("boundary_confidence") or 0.0)
    first_second_strength = float(segment.get("first_second_strength") or 0.0)
    payoff_preserved = bool(segment.get("payoff_preserved"))
    starts_cleanly = bool(segment.get("starts_cleanly"))
    ends_cleanly = bool(segment.get("ends_cleanly"))
    standalone_after_boundary_score = float(segment.get("standalone_after_boundary_score") or 0.0)
    boundary_adjustment_applied = bool(segment.get("boundary_adjustment_applied"))
    weak_editorial_segment = bool(
        hookability_score < 45.0
        or standalone_score < 45.0
        or (commercial_usefulness_score * 100.0 if commercial_usefulness_score <= 1.0 else commercial_usefulness_score) < 40.0
        or float(segment.get("vpi_score") or 0.0) < 35.0
    )
    if weak_editorial_segment:
        metadata_to_apply["weak_editorial_segment"] = True
        metadata_to_apply["weak_editorial_segment_reason"] = weak_segment_reason or "weak editorial segment"
        metadata_to_apply["weak_segment_penalties"] = weak_segment_penalties
    if boundary_confidence and boundary_confidence < 0.55:
        metadata_to_apply["boundary_confidence"] = boundary_confidence
        metadata_to_apply["boundary_warning"] = "low_boundary_confidence"
    if not starts_cleanly:
        metadata_to_apply["starts_cleanly"] = False
    if not payoff_preserved:
        metadata_to_apply["payoff_preserved"] = False
    selected_window_before = f"{segment.get('original_start_time') or segment.get('start_time') or ''} -> {segment.get('original_end_time') or segment.get('end_time') or ''}".strip()
    selected_window_after = f"{segment.get('refined_start_time') or segment.get('start_time') or ''} -> {segment.get('refined_end_time') or segment.get('end_time') or ''}".strip()
    setup_context_shift_seconds = float(segment.get("setup_context_shift_seconds") or segment.get("start_extend_seconds") or 0.0)
    trailing_low_value_seconds = float(segment.get("trailing_low_value_seconds") or segment.get("end_trim_seconds") or segment.get("bts_tail_trimmed_seconds") or 0.0)
    incomplete_viral_window_detected = bool(
        segment.get("incomplete_viral_window_detected")
        or segment.get("bts_tail_detected")
        or not payoff_preserved
        or not ends_cleanly
        or complete_idea_score < 0.70
        or (boundary_confidence >= 0.75 and complete_idea_score < 0.80)
    )
    if incomplete_viral_window_detected and setup_context_shift_seconds <= 0.0:
        setup_context_shift_seconds = max(0.0, min(12.0, trailing_low_value_seconds if trailing_low_value_seconds > 0.0 else 6.0))
    metadata_to_apply["selected_window_before"] = selected_window_before
    metadata_to_apply["selected_window_after"] = selected_window_after
    metadata_to_apply["setup_context_shift_seconds"] = setup_context_shift_seconds
    metadata_to_apply["trailing_low_value_seconds"] = trailing_low_value_seconds
    metadata_to_apply["incomplete_viral_window_detected"] = bool(incomplete_viral_window_detected)
    metadata_to_apply["forced_shift_back_applied"] = bool(segment.get("forced_shift_back_applied") or setup_context_shift_seconds > 0.0)
    metadata_to_apply["selected_alternative_for_complete_idea"] = bool(segment.get("selected_alternative_for_complete_idea"))
    metadata_to_apply["incomplete_window_uncorrectable"] = bool(segment.get("incomplete_window_uncorrectable"))
    metadata_to_apply["viral_window_shifted_back"] = bool(segment.get("viral_window_shifted_back") or setup_context_shift_seconds > 0.0)
    metadata_to_apply["viral_window_shift_reason"] = str(segment.get("viral_window_shift_reason") or ("incomplete_idea_shift_back" if setup_context_shift_seconds > 0.0 else ""))
    normalized_text = _normalize_text_loose(text)
    strong_dialogue_anchor = (
        any(term in normalized_text for term in _INSURANCE_ANCHOR_TERMS)
        and complete_idea_score >= 0.55
        and words_per_second >= 1.15
    )
    meta_production = any(term in normalized_text for term in _META_PRODUCTION_TERMS)

    # Apply brand voice to hook_text and semantic_text
    brand_voice_applied = False
    if hook_text:
        sanitized_hook = _apply_brand_voice(hook_text)
        if sanitized_hook != hook_text:
            hook_text = sanitized_hook
            brand_voice_applied = True
    if visual_text:
        sanitized_visual = _apply_brand_voice(visual_text)
        if sanitized_visual != visual_text:
            visual_text = sanitized_visual
            brand_voice_applied = True
    # Apply brand voice to CTA
    cta_suggestion = _apply_brand_voice(cta_suggestion)

    # -----------------------------------------------------------------------
    # FASE 11 — Final Contract Score (updated with commercial_usefulness_score)
    # -----------------------------------------------------------------------
    final_contract_score = round(
        (renderability_score * 0.35)
        + (editorial_value_score * 0.25)
        + (brand_fit_score * 0.15)
        + (retention_plan_score * 0.10)
        + (commercial_usefulness_score * 0.15),
        4,
    )

    # -----------------------------------------------------------------------
    # FASE 12 — would_runtime_reject Determination
    # -----------------------------------------------------------------------
    would_runtime_reject = False
    runtime_reject_reasons: List[str] = []

    # Check each dimension against profile thresholds
    if complete_idea_score < profile_config.get("min_complete_idea_score", 0.60):
        runtime_reject_reasons.append(
            f"complete_idea_score={complete_idea_score:.4f} < min={profile_config.get('min_complete_idea_score', 0.60)}"
        )

    if profile_config.get("min_hook_executable", True) and not hook_support_executable:
        runtime_reject_reasons.append("hook_not_executable")

    if profile_config.get("min_visual_executable", True) and not visual_support_executable:
        runtime_reject_reasons.append("visual_not_executable")

    if renderability_score < profile_config.get("min_renderability_score", 0.45):
        runtime_reject_reasons.append(
            f"renderability_score={renderability_score:.4f} < min={profile_config.get('min_renderability_score', 0.45)}"
        )

    if editorial_value_score < profile_config.get("min_editorial_value_score", 0.40):
        runtime_reject_reasons.append(
            f"editorial_value_score={editorial_value_score:.4f} < min={profile_config.get('min_editorial_value_score', 0.40)}"
        )

    if brand_fit_score < profile_config.get("min_brand_fit_score", 0.30):
        runtime_reject_reasons.append(
            f"brand_fit_score={brand_fit_score:.4f} < min={profile_config.get('min_brand_fit_score', 0.30)}"
        )

    if final_contract_score < profile_config.get("min_final_contract_score", 0.40):
        runtime_reject_reasons.append(
            f"final_contract_score={final_contract_score:.4f} < min={profile_config.get('min_final_contract_score', 0.40)}"
        )

    if meta_production and not strong_dialogue_anchor and bts_ratio > 0.15:
        runtime_reject_reasons.append("meta_production_or_bts")

    if runtime_reject_reasons:
        would_runtime_reject = True
        reject_reasons.extend(runtime_reject_reasons)

    # -----------------------------------------------------------------------
    # CLIP RESCUE MODE — Attempt deterministic repairs before final rejection
    # -----------------------------------------------------------------------
    # The rescue ladder runs only if would_runtime_reject is True and the
    # profile allows repairs. Each step tries a different repair strategy.
    # If any repair succeeds, we re-evaluate the relevant dimensions and
    # potentially flip would_runtime_reject back to False.
    # -----------------------------------------------------------------------
    rescue_attempted = False
    rescue_succeeded = False
    rescue_actions: List[str] = []

    if would_runtime_reject and profile_config.get("allow_repair", True):
        rescue_attempted = True

        # Step 1: try_extend_boundary (already attempted in FASE 1, but check if it helped)
        # If complete_idea_score is still too low and we haven't already extended, try again
        if not rescue_succeeded and complete_idea_score < profile_config.get("min_complete_idea_score", 0.60):
            if not any(a.get("type") == "extend_boundary" for a in repair_actions):
                boundary_repair = _repair_extend_boundary(segment, task_id=task_id, profile=profile_config)
                if boundary_repair["repaired"]:
                    repair_actions.append({
                        "type": "extend_boundary",
                        "detail": boundary_repair["repair_reason"],
                        "new_start_s": boundary_repair["new_start_s"],
                        "new_end_s": boundary_repair["new_end_s"],
                    })
                    complete_idea_score = max(complete_idea_score, 0.60)
                    rescue_actions.append("extend_boundary")
                    # Re-check if this resolves the rejection
                    if complete_idea_score >= profile_config.get("min_complete_idea_score", 0.60):
                        # Remove complete_idea_score from reject_reasons
                        reject_reasons[:] = [r for r in reject_reasons if "complete_idea_score" not in r]
                        if not any(
                            "hook_not_executable" in r
                            or "visual_not_executable" in r
                            or "renderability_score" in r
                            or "editorial_value_score" in r
                            or "brand_fit_score" in r
                            or "final_contract_score" in r
                            for r in reject_reasons
                        ):
                            rescue_succeeded = True

        # Step 2: try_hook_card (already attempted in FASE 2, but check if it helped)
        if not rescue_succeeded and not hook_support_executable:
            if not any(a.get("type") == "hook_card_fallback" for a in repair_actions):
                hook_repair = _repair_hook_card(segment, task_id=task_id, profile=profile_config)
                if hook_repair["repaired"]:
                    repair_actions.append({
                        "type": "hook_card_fallback",
                        "detail": hook_repair["repair_reason"],
                        "hook_text": hook_repair["hook_text"][:120],
                    })
                    hook_support_executable = True
                    hook_executable_score = 1.0
                    hook_support_type = "hook_card"
                    hook_text = hook_repair["hook_text"]
                    hook_start_s = hook_repair["hook_start_s"]
                    hook_duration_s = hook_repair["hook_duration_s"]
                    rescue_actions.append("hook_card_fallback")
                    # Re-check if this resolves the rejection
                    reject_reasons[:] = [r for r in reject_reasons if "hook_not_executable" not in r and "hook_fit_no_candidate" not in r]
                    if not any(
                        "visual_not_executable" in r
                        or "renderability_score" in r
                        or "editorial_value_score" in r
                        or "brand_fit_score" in r
                        or "final_contract_score" in r
                        for r in reject_reasons
                    ):
                        rescue_succeeded = True

        # Step 3: try_semantic_card (already attempted in FASE 3, but check if it helped)
        if not rescue_succeeded and not visual_support_executable:
            if not any(a.get("type") == "semantic_card_fallback" for a in repair_actions):
                semantic_repair = _repair_semantic_card(segment, task_id=task_id, profile=profile_config)
                if semantic_repair["repaired"]:
                    repair_actions.append({
                        "type": "semantic_card_fallback",
                        "detail": semantic_repair["repair_reason"],
                        "semantic_text": semantic_repair["semantic_text"][:120],
                    })
                    visual_support_executable = True
                    visual_support_score = 1.0
                    visual_type = "semantic_card"
                    visual_concept = semantic_repair["semantic_concept"]
                    visual_asset = "ffmpeg_text_card"
                    visual_text = semantic_repair["semantic_text"]
                    visual_time_range = semantic_repair["visual_time_range"]
                    rescue_actions.append("semantic_card_fallback")
                    # Re-check if this resolves the rejection
                    reject_reasons[:] = [r for r in reject_reasons if "visual_not_executable" not in r and "visual_fit_no_candidate" not in r]
                    if not any(
                        "renderability_score" in r
                        or "editorial_value_score" in r
                        or "brand_fit_score" in r
                        or "final_contract_score" in r
                        for r in reject_reasons
                    ):
                        rescue_succeeded = True

        # Step 4: try_soft_trim_hint — improve rhythm by suggesting filler removal
        if not rescue_succeeded:
            trim_repair = _repair_soft_trim_hint(segment, task_id=task_id, profile=profile_config)
            if trim_repair["repaired"]:
                repair_actions.append({
                    "type": "soft_trim_hint",
                    "detail": trim_repair["repair_reason"],
                    "trim_hint": trim_repair["trim_hint"],
                })
                metadata_to_apply["soft_trim_hint"] = trim_repair["trim_hint"]
                rescue_actions.append("soft_trim_hint")
                # Soft trim improves rhythm, so bump rhythm score
                rhythm_score = max(rhythm_score, 0.70)
                reject_reasons[:] = [r for r in reject_reasons if "rhythm_out_of_bounds" not in r]
                # Recompute editorial_value_score with improved rhythm
                editorial_value_score = round(
                    (complete_idea_score * 0.30)
                    + (hook_executable_score * 0.25)
                    + (visual_support_score * 0.20)
                    + (rhythm_score * 0.10)
                    + (retention_plan_score * 0.15),
                    4,
                )
                # Recompute final_contract_score
                final_contract_score = round(
                    (renderability_score * 0.35)
                    + (editorial_value_score * 0.25)
                    + (brand_fit_score * 0.15)
                    + (retention_plan_score * 0.10)
                    + (commercial_usefulness_score * 0.15),
                    4,
                )
                # Re-check thresholds
                if (editorial_value_score >= profile_config.get("min_editorial_value_score", 0.40)
                        and final_contract_score >= profile_config.get("min_final_contract_score", 0.40)):
                    reject_reasons[:] = [r for r in reject_reasons
                                         if "editorial_value_score" not in r and "final_contract_score" not in r]
                    if not any(
                        "renderability_score" in r
                        or "brand_fit_score" in r
                        for r in reject_reasons
                    ):
                        rescue_succeeded = True

        # Step 5: try_lower_non_blocking_requirements — relax non-critical thresholds
        if not rescue_succeeded:
            lower_repair = _repair_lower_requirements(segment, task_id=task_id, profile=profile_config)
            if lower_repair["repaired"]:
                repair_actions.append({
                    "type": "lower_requirements",
                    "detail": lower_repair["repair_reason"],
                    "relaxed_thresholds": lower_repair["relaxed_thresholds"],
                })
                metadata_to_apply["relaxed_thresholds"] = lower_repair["relaxed_thresholds"]
                rescue_actions.append("lower_requirements")
                # Apply relaxed thresholds and re-check
                relaxed = lower_repair["relaxed_thresholds"]
                # Re-check complete_idea with relaxed min word count
                if not complete_idea_pass and len(words) >= relaxed.get("min_word_count", 8):
                    complete_idea_pass = True
                    complete_idea_score = max(complete_idea_score, 0.50)
                # Re-check duration fit with relaxed min duration
                if duration_s >= relaxed.get("min_duration_s", 3.0) and duration_s < profile_config.get("duration_min_s", 6.0):
                    duration_fit_score = max(duration_fit_score, 0.60)
                # Re-check BTS with relaxed threshold
                if bts_ratio <= relaxed.get("bts_penalty_threshold", 0.35) and bts_ratio > profile_config.get("bts_penalty_threshold", 0.22):
                    bts_penalty = 1.0
                # Recompute renderability_score
                renderability_score = _compute_renderability_score(
                    complete_idea_score=complete_idea_score,
                    hook_executable_score=hook_executable_score,
                    visual_support_score=visual_support_score,
                    duration_fit_score=duration_fit_score,
                    bts_penalty=bts_penalty,
                    audio_caption_fit_score=audio_caption_fit_score,
                    profile=profile_config,
                )
                # Recompute editorial_value_score
                editorial_value_score = round(
                    (complete_idea_score * 0.30)
                    + (hook_executable_score * 0.25)
                    + (visual_support_score * 0.20)
                    + (rhythm_score * 0.10)
                    + (retention_plan_score * 0.15),
                    4,
                )
                # Recompute final_contract_score
                final_contract_score = round(
                    (renderability_score * 0.35)
                    + (editorial_value_score * 0.25)
                    + (brand_fit_score * 0.15)
                    + (retention_plan_score * 0.10)
                    + (commercial_usefulness_score * 0.15),
                    4,
                )
                # Re-check all thresholds with relaxed values
                still_rejected = False
                new_reject_reasons: List[str] = []
                if complete_idea_score < profile_config.get("min_complete_idea_score", 0.60):
                    still_rejected = True
                    new_reject_reasons.append(f"complete_idea_score={complete_idea_score:.4f}")
                if profile_config.get("min_hook_executable", True) and not hook_support_executable:
                    still_rejected = True
                    new_reject_reasons.append("hook_not_executable")
                if profile_config.get("min_visual_executable", True) and not visual_support_executable:
                    still_rejected = True
                    new_reject_reasons.append("visual_not_executable")
                if renderability_score < profile_config.get("min_renderability_score", 0.45):
                    still_rejected = True
                    new_reject_reasons.append(f"renderability_score={renderability_score:.4f}")
                if editorial_value_score < profile_config.get("min_editorial_value_score", 0.40):
                    still_rejected = True
                    new_reject_reasons.append(f"editorial_value_score={editorial_value_score:.4f}")
                if brand_fit_score < profile_config.get("min_brand_fit_score", 0.30):
                    still_rejected = True
                    new_reject_reasons.append(f"brand_fit_score={brand_fit_score:.4f}")
                if final_contract_score < profile_config.get("min_final_contract_score", 0.40):
                    still_rejected = True
                    new_reject_reasons.append(f"final_contract_score={final_contract_score:.4f}")
                if not still_rejected:
                    rescue_succeeded = True
                    # Remove all runtime reject reasons and add only the new ones
                    reject_reasons[:] = [r for r in reject_reasons if not any(
                        x in r for x in ["complete_idea_score", "hook_not_executable",
                                          "visual_not_executable", "renderability_score",
                                          "editorial_value_score", "brand_fit_score",
                                          "final_contract_score"]
                    )]
                    reject_reasons.extend(new_reject_reasons)

        # Step 6: try_brand_overlay — last-resort visual fallback
        if not rescue_succeeded and not visual_support_executable:
            brand_repair = _repair_brand_overlay(segment, task_id=task_id, profile=profile_config)
            if brand_repair["repaired"]:
                repair_actions.append({
                    "type": "brand_overlay_fallback",
                    "detail": brand_repair["repair_reason"],
                    "brand_text": brand_repair["brand_text"],
                })
                visual_support_executable = True
                visual_support_score = 1.0
                visual_type = "brand_overlay"
                visual_concept = "branding"
                visual_asset = "brand_overlay"
                visual_text = brand_repair["brand_text"]
                visual_time_range = brand_repair["visual_time_range"]
                metadata_to_apply["brand_overlay_applied"] = True
                metadata_to_apply["final_output_uses_overlay"] = True
                rescue_actions.append("brand_overlay_fallback")
                # Re-check if this resolves the rejection
                reject_reasons[:] = [r for r in reject_reasons if "visual_not_executable" not in r and "visual_fit_no_candidate" not in r]
                if not any(
                    "renderability_score" in r
                    or "editorial_value_score" in r
                    or "brand_fit_score" in r
                    or "final_contract_score" in r
                    for r in reject_reasons
                ):
                    rescue_succeeded = True

        # If rescue succeeded, flip would_runtime_reject
        if rescue_succeeded:
            would_runtime_reject = False
            logger.info(
                "CLIP_RESCUE_SUCCEEDED task_id=%s actions=%s",
                task_id,
                rescue_actions,
            )
        else:
            rescue_key = (
                str(task_id or "unknown"),
                _segment_rescue_key(segment),
                tuple(rescue_actions),
            )
            _CLIP_RESCUE_FAILED_SUMMARIES[rescue_key] = _CLIP_RESCUE_FAILED_SUMMARIES.get(rescue_key, 0) + 1
            if _CLIP_RESCUE_FAILED_SUMMARIES[rescue_key] == 1:
                logger.warning(
                    "CLIP_RESCUE_FAILED_SUMMARY task_id=%s segment_key=%s count=%d unique_reasons=%s actions_attempted=%s",
                    task_id,
                    rescue_key[1],
                    _CLIP_RESCUE_FAILED_SUMMARIES[rescue_key],
                    sorted(set(rescue_actions)),
                    rescue_actions,
                )

    # Record rescue info in metadata
    if rescue_attempted:
        metadata_to_apply["rescue_attempted"] = True
        metadata_to_apply["rescue_succeeded"] = rescue_succeeded
        metadata_to_apply["rescue_actions"] = rescue_actions

    # Dialogue fallback override: keep BTS/meta-production rejected, but allow
    # clean main-dialogue fallback candidates to proceed when they have an
    # actual insurance anchor and no BTS contamination.
    fallback_dialogue_override = bool(segment.get("fallback_candidate_selected")) and strong_dialogue_anchor and not meta_production
    if would_runtime_reject and fallback_dialogue_override:
        would_runtime_reject = False
        reject_reasons = [
            reason
            for reason in reject_reasons
            if "meta_production_or_bts" not in reason
            and "complete_idea_score" not in reason
            and "renderability_score" not in reason
            and "editorial_value_score" not in reason
            and "final_contract_score" not in reason
        ]
        metadata_to_apply["dialogue_fallback_override"] = True
        metadata_to_apply["dialogue_fallback_reason"] = "strong_main_dialogue_no_bts"
        logger.info(
            "CLIP_DIALOGUE_FALLBACK_APPROVED task_id=%s reason=strong_main_dialogue_no_bts",
            task_id,
        )

    # -----------------------------------------------------------------------
    # FASE 13 — Approval Decision
    # -----------------------------------------------------------------------
    approved = not would_runtime_reject


    # Compute severity AFTER would_runtime_reject and approved are defined
    severity = _compute_severity(reject_reasons, repair_actions, would_runtime_reject, approved)

    # -----------------------------------------------------------------------
    # Build Hook Support Dict
    # -----------------------------------------------------------------------
    hook_support: Dict[str, Any] = {
        "type": hook_support_type,
        "executable": hook_support_executable,
        "text": hook_text[:200] if hook_text else "",
        "start_s": hook_start_s,
        "duration_s": hook_duration_s,
    }

    # -----------------------------------------------------------------------
    # Build Visual Support Dict
    # -----------------------------------------------------------------------
    visual_support: Dict[str, Any] = {
        "type": visual_type,
        "executable": visual_support_executable,
        "concept": visual_concept,
        "asset_or_template": visual_asset,
        "text": visual_text[:200] if visual_text else "",
        "time_range": visual_time_range,
    }

    # -----------------------------------------------------------------------
    # Build Pre-QC Dict
    # -----------------------------------------------------------------------
    pre_qc: Dict[str, Any] = {
        "words": len(words),
        "duration_s": round(duration_s, 2),
        "words_per_second": round(words_per_second, 2),
        "bts_ratio": round(bts_ratio, 4),
        "no_mid_sentence_cut": no_mid_sentence_cut,
        "rhythm_ok": rhythm_ok,
        "bgm_available": bgm_available,
        "overlay_planned": overlay_planned,
        "overlay_verified": overlay_verified,
        "overlay_concrete": overlay_concrete,
        "broll_concrete": broll_concrete,
        "verbal_hook_detected": bool(verbal_hook),
        "hook_hits": hook_hits[:5],
    }

    # -----------------------------------------------------------------------
    # Build Return Dict
    # -----------------------------------------------------------------------
    result: Dict[str, Any] = {
        "approved": approved,
        "profile": profile,
        "complete_idea_pass": complete_idea_pass,
        "complete_idea_score": complete_idea_score,
        "hook_support": hook_support,
        "visual_support": visual_support,
        "renderability_score": renderability_score,
        "editorial_value_score": editorial_value_score,
        "brand_fit_score": brand_fit_score,
        "final_contract_score": final_contract_score,
        "would_runtime_reject": would_runtime_reject,
        "repair_actions": repair_actions,
        "reject_reasons": reject_reasons,
        "metadata_to_apply": metadata_to_apply,
        "pre_render_edit_plan": pre_render_edit_plan,
        "pre_qc": pre_qc,
        # Flexibility Engine fields
        "publishing_intent": publishing_intent,
        "commercial_usefulness_score": commercial_usefulness_score,
        "hookability_score": hookability_score,
        "standalone_score": standalone_score,
        "segment_selection_confidence": segment_selection_confidence,
        "weak_segment_penalties": weak_segment_penalties,
        "weak_segment_reason": weak_segment_reason,
        "selected_for_reason": selected_for_reason,
        "rejected_for_reason": rejected_for_reason,
        "vpi_editorial_categories": vpi_editorial_categories,
        "weak_editorial_segment": weak_editorial_segment,
        "original_start_time": str(segment.get("original_start_time") or ""),
        "original_end_time": str(segment.get("original_end_time") or ""),
        "refined_start_time": str(segment.get("refined_start_time") or ""),
        "refined_end_time": str(segment.get("refined_end_time") or ""),
        "boundary_adjustment_applied": boundary_adjustment_applied,
        "boundary_adjustment_reason": str(segment.get("boundary_adjustment_reason") or ""),
        "start_trim_seconds": float(segment.get("start_trim_seconds") or 0.0),
        "start_extend_seconds": float(segment.get("start_extend_seconds") or 0.0),
        "end_extend_seconds": float(segment.get("end_extend_seconds") or 0.0),
        "end_trim_seconds": float(segment.get("end_trim_seconds") or 0.0),
        "payoff_preserved": payoff_preserved,
        "starts_cleanly": starts_cleanly,
        "ends_cleanly": ends_cleanly,
        "first_second_strength": first_second_strength,
        "first_second_reason": str(segment.get("first_second_reason") or ""),
        "boundary_confidence": boundary_confidence,
        "selected_window_before": selected_window_before,
        "selected_window_after": selected_window_after,
        "setup_context_shift_seconds": setup_context_shift_seconds,
        "trailing_low_value_seconds": trailing_low_value_seconds,
        "incomplete_viral_window_detected": bool(incomplete_viral_window_detected),
        "forced_shift_back_applied": bool(segment.get("forced_shift_back_applied") or setup_context_shift_seconds > 0.0),
        "selected_alternative_for_complete_idea": bool(segment.get("selected_alternative_for_complete_idea")),
        "incomplete_window_uncorrectable": bool(segment.get("incomplete_window_uncorrectable")),
        "viral_window_shifted_back": bool(segment.get("viral_window_shifted_back") or setup_context_shift_seconds > 0.0),
        "viral_window_shift_reason": str(segment.get("viral_window_shift_reason") or ("incomplete_idea_shift_back" if setup_context_shift_seconds > 0.0 else "")),
        "standalone_after_boundary_score": standalone_after_boundary_score,
        "standalone_after_boundary_reason": str(segment.get("standalone_after_boundary_reason") or ""),
        "start_filler_trimmed": bool(segment.get("start_filler_trimmed")),
        "start_trim_reason": str(segment.get("start_trim_reason") or ""),
        "start_context_extended": bool(segment.get("start_context_extended")),
        "start_context_reason": str(segment.get("start_context_reason") or ""),
        "payoff_extended": bool(segment.get("payoff_extended")),
        "payoff_extension_reason": str(segment.get("payoff_extension_reason") or ""),
        "end_cleaned": bool(segment.get("end_cleaned")),
        "end_clean_reason": str(segment.get("end_clean_reason") or ""),
        "boundary_reverted": bool(segment.get("boundary_reverted")),
        "boundary_reverted_reason": str(segment.get("boundary_reverted_reason") or ""),
        "cta_suggestion": cta_suggestion,
        "brand_voice_applied": brand_voice_applied,
        "severity": severity,
        "diversity_key": diversity_key,
    }

    logger.info(
        "EDITORIAL_CONTRACT task_id=%s profile=%s approved=%s "
        "complete_idea_score=%.4f hook=%s visual=%s "
        "renderability=%.4f editorial_value=%.4f brand_fit=%.4f final=%.4f "
        "would_runtime_reject=%s repairs=%d rejections=%d",
        task_id,
        profile,
        approved,
        complete_idea_score,
        hook_support_type,
        visual_type,
        renderability_score,
        editorial_value_score,
        brand_fit_score,
        final_contract_score,
        would_runtime_reject,
        len(repair_actions),
        len(reject_reasons),
    )

    # Normalize result to guarantee consistent schema for all consumers
    result = normalize_contract_result(result)

    return result


# ---------------------------------------------------------------------------
# Batch Evaluator
# ---------------------------------------------------------------------------

def evaluate_editorial_contract_batch(
    segments: List[Dict[str, Any]],
    *,
    task_id: str,
    profile: str = DEFAULT_PROFILE,
    include_broll: bool = False,
    bgm_tracks_available: int = 0,
    asset_index: Optional[Dict[str, Any]] = None,
    max_workers: int = 1,
    music_tracks: Optional[List[Any]] = None,
    **kwargs: Any,
) -> List[Dict[str, Any]]:
    """Evaluate multiple segments against the editorial contract.

    Parameters
    ----------
    segments : list of dict
        Candidate segments to evaluate.
    task_id : str
        Task ID for logging.
    profile : str
        Editorial policy profile key.
    include_broll : bool
        Whether broll is enabled.
    bgm_tracks_available : int
        Number of BGM tracks available.
    asset_index : dict or None
        Pre-computed asset index.
    max_workers : int
        Number of parallel workers (default 1 for deterministic local-only).
    music_tracks : list or None
        Pre-computed music tracks list. If provided, overrides bgm_tracks_available.
    **kwargs
        Additional keyword arguments forwarded to evaluate_editorial_contract().
        Unknown kwargs are logged as a warning.

    Returns
    -------
    list of dict
        One result dict per segment, in the same order as input.
    """
    # Derive bgm_tracks_available from music_tracks if provided
    if music_tracks is not None:
        bgm_tracks_available = len(music_tracks)

    # Log any unexpected kwargs for debugging
    if kwargs:
        logger.warning(
            "EDITORIAL_CONTRACT_BATCH_UNEXPECTED_KWARGS task_id=%s kwargs=%s",
            task_id,
            kwargs,
        )

    results: List[Dict[str, Any]] = []
    for idx, segment in enumerate(segments):
        try:
            result = evaluate_editorial_contract(
                segment,
                task_id=task_id,
                profile=profile,
                include_broll=include_broll,
                bgm_tracks_available=bgm_tracks_available,
                asset_index=asset_index,
                music_tracks=music_tracks,
            )
            results.append(result)
        except Exception as exc:
            logger.error(
                "EDITORIAL_CONTRACT_BATCH_ERROR task_id=%s idx=%d error=%s",
                task_id,
                idx,
                exc,
            )
            error_result = {
                "approved": False,
                "profile": profile,
                "complete_idea_pass": False,
                "complete_idea_score": 0.0,
                "hook_support": {"type": "none", "executable": False, "text": "", "start_s": 0.0, "duration_s": 0.0},
                "visual_support": {"type": "none", "executable": False, "concept": "", "asset": "", "text": "", "time_range": [0.0, 0.0]},
                "renderability_score": 0.0,
                "editorial_value_score": 0.0,
                "brand_fit_score": 0.0,
                "final_contract_score": 0.0,
                "would_runtime_reject": True,
                "repair_actions": [],
                "reject_reasons": [f"evaluation_error:{exc}"],
                "metadata_to_apply": {},
                "pre_render_edit_plan": {},
                "pre_qc": {},
                # Flexibility Engine fields (error fallback)
                "publishing_intent": "unknown",
                "commercial_usefulness_score": 0.0,
                "cta_suggestion": "",
                "brand_voice_applied": False,
                "severity": SEVERITY_BLOCKER,
                "diversity_key": "error",
            }
            results.append(normalize_contract_result(error_result))
    return results


# ---------------------------------------------------------------------------
# Snapshot Builder
# ---------------------------------------------------------------------------

def build_editorial_snapshots(
    candidates: List[Dict[str, Any]],
    *,
    task_id: str,
    profile: str = DEFAULT_PROFILE,
    include_broll: bool = False,
    bgm_tracks_available: int = 0,
    asset_index: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build editorial snapshots for persistence in stage_timings_json.

    Returns a dict with keys:
        candidate_pool_snapshot: list of candidate summaries (before evaluation)
        pre_render_pool_snapshot: list of evaluated results (after contract)
        approved_candidates_snapshot: list of approved results only
        rejected_candidates_summary: dict with counts and top reasons
    """
    # Candidate pool snapshot (before evaluation)
    candidate_pool_snapshot: List[Dict[str, Any]] = []
    for idx, c in enumerate(candidates):
        candidate_pool_snapshot.append({
            "idx": idx,
            "text_preview": str(c.get("text") or "")[:120],
            "duration_s": _segment_duration_seconds(c),
            "editorial_type": str(c.get("editorial_type") or ""),
            "clean_take_topic": str(c.get("clean_take_topic") or ""),
            "bts_contamination_ratio": float(c.get("bts_contamination_ratio") or 0.0),
        })

    # Evaluate all candidates
    evaluated = evaluate_editorial_contract_batch(
        candidates,
        task_id=task_id,
        profile=profile,
        include_broll=include_broll,
        bgm_tracks_available=bgm_tracks_available,
        asset_index=asset_index,
    )

    # Pre-render pool snapshot (after evaluation)
    pre_render_pool_snapshot: List[Dict[str, Any]] = []
    approved_candidates_snapshot: List[Dict[str, Any]] = []
    rejected_reasons_counter: Dict[str, int] = {}

    for idx, (c, r) in enumerate(zip(candidates, evaluated)):
        snapshot_entry = {
            "idx": idx,
            "text_preview": str(c.get("text") or "")[:120],
            "approved": r["approved"],
            "complete_idea_score": r["complete_idea_score"],
            "hook_support_type": r["hook_support"]["type"],
            "hook_executable": r["hook_support"]["executable"],
            "visual_support_type": r["visual_support"]["type"],
            "visual_executable": r["visual_support"]["executable"],
            "renderability_score": r["renderability_score"],
            "editorial_value_score": r["editorial_value_score"],
            "brand_fit_score": r["brand_fit_score"],
            "final_contract_score": r["final_contract_score"],
            "would_runtime_reject": r["would_runtime_reject"],
            "repair_actions": [a["type"] for a in r["repair_actions"]],
            "reject_reasons": r["reject_reasons"],
            # Flexibility Engine fields
            "publishing_intent": r.get("publishing_intent", "unknown"),
            "commercial_usefulness_score": r.get("commercial_usefulness_score", 0.0),
            "cta_suggestion": r.get("cta_suggestion", ""),
            "brand_voice_applied": r.get("brand_voice_applied", False),
            "severity_max": r.get("severity", {}).get("max_severity", "INFO"),
            "severity_blockers": len(r.get("severity", {}).get("blockers", [])),
            "severity_repairable": len(r.get("severity", {}).get("repairable", [])),
            "severity_penalties": len(r.get("severity", {}).get("penalties", [])),
            "diversity_key": r.get("diversity_key", ""),
        }
        pre_render_pool_snapshot.append(snapshot_entry)

        if r["approved"]:
            approved_candidates_snapshot.append(snapshot_entry)

        for reason in r["reject_reasons"]:
            # Normalize reason to a category
            category = reason.split("=")[0].split(":")[0].strip()
            rejected_reasons_counter[category] = rejected_reasons_counter.get(category, 0) + 1

    # Sort rejected reasons by count descending
    sorted_reasons = sorted(rejected_reasons_counter.items(), key=lambda x: -x[1])

    rejected_candidates_summary: Dict[str, Any] = {
        "total_rejected": len(candidates) - len(approved_candidates_snapshot),
        "total_evaluated": len(candidates),
        "top_reject_reasons": [{"reason": k, "count": v} for k, v in sorted_reasons[:10]],
    }

    return {
        "candidate_pool_snapshot": candidate_pool_snapshot,
        "pre_render_pool_snapshot": pre_render_pool_snapshot,
        "approved_candidates_snapshot": approved_candidates_snapshot,
        "rejected_candidates_summary": rejected_candidates_summary,
    }
