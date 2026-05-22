"""
Clip Intelligence — Context-Aware Effect Selection
====================================================
Analyzes each clip's text, energy, virality and hook-type to produce a
ClipProfile that drives intelligent selection of ALL post-processing
effects: LUT colour grade, caption style, B-roll density/duration,
BGM category, SFX selection, zoom intensity, and editing parameters.

Called once per clip in video_service.create_single_clip and passed
through to every feature that supports per-clip configuration.
"""
from __future__ import annotations

import json
import logging
import os

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Sentiment / energy word sets ──────────────────────────────────────────────

_HIGH_ENERGY = {
    "fire", "insane", "crazy", "amazing", "unbelievable", "shocking",
    "explosive", "epic", "massive", "huge", "incredible", "wild",
    "viral", "secret", "exposed", "reveal", "truth", "never", "always",
    "stop", "wait", "listen", "watch", "now", "today", "free", "money",
    "hack", "trick", "cheat", "fastest", "easiest", "biggest", "best",
}
_CALM = {
    "peaceful", "simple", "easy", "gentle", "calm", "slow", "relax",
    "breathe", "focus", "mindful", "quiet", "soft", "natural", "organic",
    "meditat", "breathe", "sleep", "rest", "balance",
}
_DRAMATIC = {
    "dead", "kill", "wrong", "fail", "mistake", "disaster", "crisis",
    "danger", "warning", "critical", "urgent", "breaking", "alert",
    "scam", "fraud", "banned", "illegal", "toxic", "abuse", "scary",
}
_INSPIRATIONAL = {
    "inspir", "motivat", "success", "dream", "goal", "achiev", "possible",
    "believe", "mindset", "growth", "potential", "journey", "purpose",
}

# ── Mood → LUT options (cycle within mood across clips) ───────────────────────

_MOOD_LUTS: Dict[str, List[str]] = {
    "energetic":     ["high_contrast", "teal_orange", "warm_film", "high_contrast"],
    "dramatic":      ["cold_blue", "teal_orange", "high_contrast", "cold_blue"],
    "warm":          ["warm_film", "vintage", "teal_orange", "warm_film"],
    "chill":         ["vintage", "warm_film", "cold_blue", "vintage"],
    "educational":   ["flat", "cold_blue", "minimal_clean", "warm_film"],
    "inspirational": ["warm_film", "vintage", "teal_orange", "warm_film"],
}
# LUT fallback if named preset file is missing
_LUT_FALLBACK = "teal_orange"

# ── Mood → caption style options ─────────────────────────────────────────────

_MOOD_CAPTIONS: Dict[str, List[str]] = {
    "energetic":     ["tiktok", "highlight", "neon", "tiktok"],
    "dramatic":      ["highlight", "neon", "tiktok", "highlight"],
    "warm":          ["karaoke", "tiktok", "karaoke", "tiktok"],
    "chill":         ["tiktok", "karaoke", "tiktok", "karaoke"],
    "educational":   ["tiktok", "karaoke", "highlight", "tiktok"],
    "inspirational": ["tiktok", "karaoke", "highlight", "tiktok"],
}

# ── Mood → BGM category ───────────────────────────────────────────────────────

_MOOD_BGM: Dict[str, str] = {
    "energetic":     "hype",
    "dramatic":      "midtempo",
    "warm":          "upbeat",
    "chill":         "slow",
    "educational":   "midtempo",
    "inspirational": "upbeat",
}

# ── Adaptive B-roll density ──────────────────────────────────────────────────

def calculate_max_broll(clip_duration: float, virality_score: float, hook_type: str) -> int:
    """
    Determine the number of B-roll overlays for a clip based on virality and hook type.

    - High-virality clips (>=80) get only 1 B-roll to let the content breathe.
    - Otherwise the hook type determines the base interval (seconds between inserts):
        statistic=12, contrast=15, question=18, story=25, statement=20, default=18.
    - Result is clamped to [1, 4].
    """
    if virality_score >= 80:
        return 1
    base_interval = {
        "statistic": 12,
        "contrast": 15,
        "question": 18,
        "story": 25,
        "statement": 20,
        "none": 18,
    }.get(hook_type, 18)
    return max(1, min(4, int(clip_duration / base_interval)))


# ── Template explicit overrides ───────────────────────────────────────────────

_TEMPLATE_CAPTION: Dict[str, str] = {
    "tutorial":   "tiktok",
    "interview":  "karaoke",
    "education":  "tiktok",
    "neon":       "neon",
    "highlight":  "highlight",
    "karaoke":    "karaoke",
}


# ── ClipProfile dataclass ─────────────────────────────────────────────────────

@dataclass
class ClipProfile:
    mood:           str    # energetic | dramatic | warm | chill | educational | inspirational
    energy:         float  # 0.0 – 1.0
    pace:           str    # fast | medium | slow
    virality:       float  # 0 – 100

    lut:            str    # LUT preset id for colour grade
    caption_style:  str    # ASS caption style id
    broll_count:    int    # number of B-roll overlays to insert
    broll_duration: float  # seconds per overlay
    bgm_category:   str    # BGM category hint for BeatSyncService

    zoom_intensity: str    # off | subtle | medium | strong
    sfx_emphasis:   str    # primary SFX hook type

    saturation:      float  # EditingPipeline saturation override
    contrast:        float  # EditingPipeline contrast override
    ai_keywords:     List[str] = field(default_factory=list)  # AI-chosen B-roll keywords
    content_category: str   = field(default="unknown")        # Editorial Brain category
    narrative:        Any   = field(default=None)              # NarrativeStructure | None
    broll_fade_s:     float = field(default=0.25)              # B-roll fade duration (category-specific)
    grain:            int   = field(default=0)                 # Film grain override (0 = compute from energy)

    def describe(self) -> str:
        return (
            f"mood={self.mood} energy={self.energy:.2f} pace={self.pace} "
            f"lut={self.lut} caption={self.caption_style} "
            f"broll={self.broll_count}x{self.broll_duration:.1f}s "
            f"bgm={self.bgm_category} zoom={self.zoom_intensity}"
        )


# ── Main builder ─────────────────────────────────────────────────────────────

def build_clip_profile(
    segment: Dict[str, Any],
    duration: float,
    clip_index: int,
    caption_template: str = "viral",
) -> ClipProfile:
    """
    Derive a ClipProfile for a single clip segment.

    Args:
        segment:          The segment dict (text, virality_score, hook_type, theme).
        duration:         Clip duration in seconds.
        clip_index:       0-based index within the task (for variety cycling).
        caption_template: Template name from the render request.

    Returns:
        ClipProfile — all effect decisions for this clip.
    """
    text      = (segment.get("text") or "").lower()
    virality  = float(segment.get("virality_score", 50))
    hook_type = (segment.get("hook_type") or "insight_reveal").lower()
    words     = text.split()
    wcount    = len(words)

    # ── 1. Energy score ───────────────────────────────────────────────────────
    energy_hits   = sum(1 for w in words if any(e in w for e in _HIGH_ENERGY))
    calm_hits     = sum(1 for w in words if any(c in w for c in _CALM))
    dramatic_hits = sum(1 for w in words if any(d in w for d in _DRAMATIC))
    inspir_hits   = sum(1 for w in words if any(i in w for i in _INSPIRATIONAL))
    excl          = text.count("!")
    ques          = text.count("?")
    caps_ratio    = sum(1 for c in text if c.isupper()) / max(1, len(text))

    raw_energy = (
        energy_hits   * 0.12
        + excl        * 0.07
        + ques        * 0.03
        + caps_ratio  * 0.30
        + virality / 100.0 * 0.45
        - calm_hits   * 0.08
    )
    energy = max(0.0, min(1.0, raw_energy))

    # ── 2. Speech pace ────────────────────────────────────────────────────────
    wps  = wcount / max(1.0, duration)
    if wps > 3.5:   pace = "fast"
    elif wps > 2.0: pace = "medium"
    else:           pace = "slow"

    # ── 3. Mood classification ────────────────────────────────────────────────
    if dramatic_hits >= 2 or hook_type in ("cliffhanger", "pattern_interrupt"):
        mood = "dramatic"
    elif inspir_hits >= 2 or hook_type in ("motivation",):
        mood = "inspirational"
    elif energy >= 0.65 or hook_type in ("scroll_stop",):
        mood = "energetic"
    elif calm_hits >= 2 or pace == "slow":
        mood = "chill"
    elif hook_type in ("insight_reveal", "curiosity_gap") and energy < 0.45:
        mood = "educational"
    else:
        mood = "warm"

    # ── 4. LUT selection — varied within mood by clip_index ──────────────────
    lut_list = _MOOD_LUTS.get(mood, ["teal_orange", "warm_film", "cold_blue", "vintage"])
    lut = lut_list[clip_index % len(lut_list)]

    # ── 5. Caption style — template takes priority, then mood ─────────────────
    caption_style = (
        _TEMPLATE_CAPTION.get(caption_template)
        or _MOOD_CAPTIONS.get(mood, ["tiktok", "minimal", "karaoke", "neon"])[
            clip_index % 4
        ]
    )

    # ── 6. B-roll density ─────────────────────────────────────────────────────
    broll_count   = calculate_max_broll(duration, virality, hook_type)
    broll_dur     = 3.5 if energy < 0.4 else (2.8 if energy < 0.7 else 2.2)
    # HARD PLANNING-STAGE GATE: reject any b-roll cue under 2.5s
    if broll_dur < 2.5:
        logger.info(
            "[ClipIntel/DurationGate] clip=%d rejecting short b-roll cue: "
            "planned=%.1fs (energy=%.2f) → clamped to 2.5s",
            clip_index + 1, broll_dur, energy,
        )
        broll_dur = 2.5

    # ── 7. BGM category ───────────────────────────────────────────────────────
    bgm_category = _MOOD_BGM.get(mood, "upbeat")

    # ── 8. Zoom intensity ─────────────────────────────────────────────────────
    if energy >= 0.75:    zoom_intensity = "strong"
    elif energy >= 0.45:  zoom_intensity = "medium"
    elif energy >= 0.20:  zoom_intensity = "subtle"
    else:                 zoom_intensity = "off"

    # ── 9. Primary SFX type ───────────────────────────────────────────────────
    _hook_sfx = {
        "curiosity_gap":    "curiosity_gap",
        "cliffhanger":      "cliffhanger",
        "pattern_interrupt": "pattern_interrupt",
        "scroll_stop":      "scroll_stop",
        "insight_reveal":   "insight_reveal",
    }
    sfx_emphasis = _hook_sfx.get(hook_type, "transition")

    # ── 10. Editing pipeline adjustments ──────────────────────────────────────
    saturation = round(1.10 + energy * 0.30, 3)   # 1.10–1.40
    contrast   = round(1.03 + energy * 0.22, 3)   # 1.03–1.25

    # Basic grain/fade heuristics for fallback path
    _h_grain = int(5 + energy * 12)   # 5 (chill) → 17 (high energy)
    _h_fade  = 0.35 - energy * 0.20   # 0.35 (chill) → 0.15 (energetic)

    profile = ClipProfile(
        mood=mood, energy=energy, pace=pace, virality=virality,
        lut=lut, caption_style=caption_style,
        broll_count=broll_count, broll_duration=broll_dur,
        bgm_category=bgm_category, zoom_intensity=zoom_intensity,
        sfx_emphasis=sfx_emphasis, saturation=saturation, contrast=contrast,
        grain=_h_grain, broll_fade_s=round(_h_fade, 2),
    )
    logger.info("[ClipIntel] clip=%d %s", clip_index + 1, profile.describe())
    return profile


# ── AI Brain (Groq) ──────────────────────────────────────────────────────────

_VALID_LUTS      = {"teal_orange", "warm_film", "cold_blue", "vintage", "high_contrast", "flat"}
_VALID_CAPTIONS  = {"tiktok", "highlight", "neon", "minimal", "karaoke"}
_VALID_MOODS     = set(_MOOD_LUTS.keys())
_VALID_BGM       = {"hype", "upbeat", "midtempo", "slow"}
_VALID_ZOOM      = {"off", "subtle", "medium", "strong"}
_VALID_SFX       = {"curiosity_gap", "cliffhanger", "pattern_interrupt",
                    "scroll_stop", "insight_reveal", "transition", "emphasis_word"}

_AI_SYSTEM_PROMPT = """You are a professional viral video editor for TikTok, Reels, and YouTube Shorts.
You receive a video transcript and metadata, and you return a JSON object with precise editing decisions.
Your decisions must match the TONE and CONTENT of the clip — not just generic settings.
Return ONLY a valid JSON object, no markdown, no explanation."""

_AI_USER_TEMPLATE = """Analyze this video clip and decide how to edit it.

Transcript: \"{text}\"
Duration: {duration:.0f}s
Virality score: {virality:.0f}/100
Hook type: {hook_type}

Return a JSON object with EXACTLY these fields:
{{
  "mood": "energetic|dramatic|chill|warm|educational|inspirational",
  "energy": <float 0.0-1.0>,
  "lut": "teal_orange|warm_film|cold_blue|vintage|high_contrast|flat",
  "caption_style": "tiktok|highlight|neon|minimal|karaoke",
  "broll_keywords": [<3-5 specific visual concepts to illustrate the speech>],
  "bgm_category": "hype|upbeat|midtempo|slow",
  "zoom_intensity": "off|subtle|medium|strong",
  "sfx_emphasis": "curiosity_gap|cliffhanger|pattern_interrupt|scroll_stop|insight_reveal|transition",
  "saturation": <float 1.0-1.5>,
  "contrast": <float 1.0-1.3>
}}"""


async def _build_clip_profile_ai(
    segment: Dict[str, Any],
    duration: float,
    clip_index: int,
) -> Optional[ClipProfile]:
    """
    Ask Groq (llama-3.1-8b-instant) for semantic editing decisions.
    Returns None on any failure — caller falls back to heuristics.
    """
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        return None

    text      = (segment.get("text") or "")[:600].strip()
    virality  = float(segment.get("virality_score", 50))
    hook_type = (segment.get("hook_type") or "insight_reveal").lower()

    if not text:
        return None

    user_msg = _AI_USER_TEMPLATE.format(
        text=text.replace('"', "'"),
        duration=duration,
        virality=virality,
        hook_type=hook_type,
    )

    try:
        import httpx
        _groq_model = os.environ.get("GROQ_EDIT_MODEL",
            os.environ.get("LLM", "llama-3.3-70b-versatile").replace("groq:", ""))
        async with httpx.AsyncClient(timeout=9.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}",
                          "Content-Type": "application/json"},
                json={
                    "model": _groq_model,
                    "messages": [
                        {"role": "system", "content": _AI_SYSTEM_PROMPT},
                        {"role": "user",   "content": user_msg},
                    ],
                    "max_tokens": 320,
                    "temperature": 0.25,
                    "response_format": {"type": "json_object"},
                },
            )
        if resp.status_code != 200:
            logger.debug("[ClipIntel/AI] Groq HTTP %d", resp.status_code)
            return None

        parsed: Dict[str, Any] = resp.json()["choices"][0]["message"]["content"]
        if isinstance(parsed, str):
            parsed = json.loads(parsed)

        # ── Validate & clamp every field ─────────────────────────────────────
        mood          = parsed.get("mood", "warm")
        if mood not in _VALID_MOODS: mood = "warm"

        energy        = max(0.0, min(1.0, float(parsed.get("energy", 0.5))))

        lut           = parsed.get("lut", "teal_orange")
        if lut not in _VALID_LUTS: lut = _MOOD_LUTS.get(mood, ["teal_orange"])[0]

        caption_style = parsed.get("caption_style", "tiktok")
        if caption_style not in _VALID_CAPTIONS: caption_style = "tiktok"

        bgm_category  = parsed.get("bgm_category", "upbeat")
        if bgm_category not in _VALID_BGM: bgm_category = _MOOD_BGM.get(mood, "upbeat")

        zoom_intensity = parsed.get("zoom_intensity", "medium")
        if zoom_intensity not in _VALID_ZOOM: zoom_intensity = "medium"

        sfx_emphasis  = parsed.get("sfx_emphasis", "insight_reveal")
        if sfx_emphasis not in _VALID_SFX: sfx_emphasis = "insight_reveal"

        saturation    = max(1.0, min(1.5, float(parsed.get("saturation", 1.25))))
        contrast      = max(1.0, min(1.3, float(parsed.get("contrast",   1.10))))

        ai_keywords   = [str(k) for k in (parsed.get("broll_keywords") or []) if k][:5]

        # ── HARDENED DOMAIN FILTER ──────────────────────────────────────────────
        # Reject generic/motivational keywords that don't tie to the transcript topic.
        # For insurance/finance content, only allow concrete concepts from the whitelist.
        # If ALL keywords are rejected, clear ai_keywords so the semantic planner
        # cues (which are more specific) are used instead.
        _INSURANCE_KW = {
            "insurance", "seguro", "póliza", "poliza", "claim", "reclamo",
            "coverage", "cobertura", "prima", "premium", "deductible",
            "deducible", "indemnización", "indemnizacion", "siniestro",
            "riesgo", "riesgos", "aseguradora", "asegurado", "asegurada",
            "financial", "financiero", "inversión", "inversion", "invertir",
            "investment", "policy", "contrato", "contract", "protección",
            "proteccion", "protection", "beneficios", "benefits", "pago",
            "payment", "cuota", "fee", "monthly", "mensual", "anual",
            "annual", "accidente", "accident", "emergencia", "emergency",
            "hospital", "médico", "medico", "medical", "salud", "health",
            "vida", "life", "hogar", "home", "auto", "car", "vehicle",
            "vehículo", "vehiculo", "responsabilidad", "liability",
            "civil", "daños", "danos", "damage", "property", "propiedad",
            "bienes", "assets", "patrimonio", "wealth", "ahorro",
            "savings", "jubilación", "jubilacion", "retirement", "pensión",
            "pension", "fondo", "fund", "futuro", "future", "familia",
            "family", "hijos", "children", "conyuge", "spouse",
            "herederos", "heirs", "sucesión", "sucesion", "succession",
            "testamento", "will", "trust", "fideicomiso", "documentos",
            "documents", "papeles", "paperwork", "firma", "signature",
            "firmar", "sign", "aplicación", "aplicacion", "application",
            "formulario", "form", "solicitud", "request", "aprobación",
            "aprobacion", "approval", "rechazo", "rejection", "denegado",
            "denied", "reembolso", "reimbursement", "devolución",
            "devolucion", "refund", "cancelación", "cancelacion",
            "cancellation", "renovación", "renovacion", "renewal",
            "vencimiento", "expiration", "vigencia", "validity", "plazo",
            "term", "condiciones", "conditions", "términos", "terminos",
            "terms", "cláusula", "clausula", "clause", "exclusión",
            "exclusion", "exclusiones", "excepciones", "exceptions",
            "carencia", "waiting", "periodo", "period", "espera", "wait",
            "suma", "sum", "asegurada", "insured", "límite", "limite",
            "limit", "máximo", "maximo", "maximum", "mínimo", "minimo",
            "minimum", "franquicia", "copago", "coinsurance", "cosseguro",
            "co-pay", "red", "network", "proveedor", "provider", "doctor",
            "clínica", "clinica", "clinic", "farmacia", "pharmacy",
            "receta", "prescription", "medicamento", "medication",
            "tratamiento", "treatment", "terapia", "therapy", "cirugía",
            "cirugia", "surgery", "operación", "operacion", "operation",
            "diagnóstico", "diagnostico", "diagnosis", "examen", "exam",
            "prueba", "test", "análisis", "analisis", "analysis",
            "laboratorio", "laboratory", "lab", "rayos", "xray", "x-ray",
            "ultrasonido", "ultrasound", "resonancia", "mri",
            "tomografía", "tomografia", "ct", "scan", "especialista",
            "specialist", "consulta", "consultation", "cita",
            "appointment", "visita", "visit", "urgencia", "emergency",
            "ambulancia", "ambulance", "hospitalización",
            "hospitalizacion", "hospitalization", "internación",
            "internacion", "admission", "alta", "discharge",
            "recuperación", "recuperacion", "recovery", "rehabilitación",
            "rehabilitacion", "rehabilitation", "fisioterapia",
            "physical therapy", "terapia física", "terapia fisica",
            "ocupacional", "occupational", "habla", "speech", "lenguaje",
            "language", "mental", "psicológico", "psicologico",
            "psychological", "psiquiátrico", "psiquiatrico",
            "psychiatric", "consejería", "consejeria", "counseling",
            "adicción", "adiccion", "addiction", "sustancias",
            "substances", "alcohol", "drogas", "drugs", "prevención",
            "prevencion", "prevention", "bienestar", "wellness",
            "well-being", "nutrición", "nutricion", "nutrition",
            "dieta", "diet", "ejercicio", "exercise",
            "actividad física", "actividad fisica", "physical activity",
            "vacuna", "vaccine", "vacunación", "vacunacion",
            "vaccination", "inmunización", "inmunizacion",
            "immunization", "epidemia", "pandemia", "crónico", "cronico",
            "chronic", "agudo", "acute", "enfermedad", "illness",
            "disease", "condición", "condicion", "condition",
            "preexistente", "preexisting", "congénito", "congenito",
            "congenital", "hereditario", "hereditary", "genético",
            "genetico", "genetic", "historial", "history",
            "antecedentes", "background", "familiar", "family",
            "embarazo", "pregnancy", "maternidad", "maternity",
            "paternidad", "paternity", "parto", "birth",
            "recién nacido", "recien nacido", "newborn", "pediatría",
            "pediatria", "pediatric", "niño", "nino", "child",
            "infantil", "children", "adolescente", "adolescent",
            "joven", "young", "adulto", "adult", "mayor", "elderly",
            "senior", "tercera edad", "old age", "vejez",
            "discapacidad", "disability", "incapacidad", "incapacity",
            "invalidez", "invalidity", "dependencia", "dependency",
            "cuidado", "care", "cuidador", "caregiver", "asistencia",
            "assistance", "ayuda", "help", "apoyo", "support",
            "orientación", "orientacion", "guidance", "asesoría",
            "asesoria", "advisory", "consultoría", "consultoria",
            "consulting", "corredor", "broker", "agente", "agent",
            "intermediario", "intermediary", "productor", "producer",
            "vendedor", "seller", "distribuidor", "distributor",
            "sucursal", "branch", "oficina", "office", "agencia",
            "agency", "central", "call center", "llamada", "call",
            "teléfono", "telefono", "phone", "whatsapp", "email",
            "correo", "mail", "web", "sitio", "site", "portal",
            "online", "digital", "app", "plataforma", "platform",
            "sistema", "system", "software", "programa", "program",
            "módulo", "modulo", "module", "herramienta", "tool",
            "recurso", "resource", "servicio", "service", "producto",
            "product", "solución", "solucion", "solution", "paquete",
            "package", "plan", "tarifa", "rate", "precio", "price",
            "costo", "cost", "valor", "value", "calidad", "quality",
            "garantía", "garantia", "guarantee", "warranty",
            "confianza", "trust", "tranquilidad", "peace of mind",
            "seguridad", "security", "safety", "protección",
            "proteccion", "protection", "respaldo", "backing",
            "solidez", "solidity", "estabilidad", "stability",
            "solvencia", "solvency", "liquidez", "liquidity",
            "capital", "reserva", "reserve", "rentabilidad",
            "profitability", "rendimiento", "performance", "ganancia",
            "gain", "ganancias", "profits", "pérdida", "perdida",
            "loss", "balance", "estado", "statement", "cuenta",
            "account", "reporte", "report", "informe", "report",
            "auditoría", "auditoria", "audit", "fiscal", "tax",
            "impuesto", "tax", "tributo", "tribute", "declaración",
            "declaracion", "declaration", "renta", "income",
            "ingreso", "income", "egreso", "expense", "gasto",
            "expense", "presupuesto", "budget", "proyección",
            "proyeccion", "projection", "estimación", "estimacion",
            "estimation", "cálculo", "calculo", "calculation",
            "cotización", "cotizacion", "quote", "quotation",
            "estimado", "estimate", "factura", "invoice", "recibo",
            "receipt", "comprobante", "voucher", "cobro",
            "collection", "debito", "debit", "crédito", "credito",
            "credit", "tarjeta", "card", "efectivo", "cash",
            "transferencia", "transfer", "depósito", "deposito",
            "deposit", "retiro", "withdrawal", "cheque", "check",
            "giro", "money order", "domiciliación", "domiciliacion",
            "direct debit", "automático", "automatico", "automatic",
            "recurrente", "recurring", "periódico", "periodico",
            "periodic", "mensualidad", "monthly payment", "anualidad",
            "annuity", "prima única", "prima unica", "single premium",
            "prima nivelada", "level premium", "prima creciente",
            "increasing premium", "prima decreciente",
            "decreasing premium", "sobreprima", "extra premium",
            "recargo", "surcharge", "descuento", "discount",
            "bonificación", "bonificacion", "bonus", "beneficio",
            "benefit", "ventaja", "advantage", "promoción",
            "promocion", "promotion", "oferta", "offer", "gratis",
            "free", "sin costo", "no cost", "adicional", "additional",
            "extra", "incluido", "included", "incluye", "includes",
            "complementario", "complementary", "opcional", "optional",
            "suplementario", "supplementary", "ampliación",
            "ampliacion", "extension", "mejora", "improvement",
            "actualización", "actualizacion", "update", "upgrade",
            "suspensión", "suspension", "terminación", "terminacion",
            "termination", "resciliación", "resciliacion",
            "rescission", "anulación", "anulacion", "annulment",
            "nulidad", "nullity", "caducidad", "expiry",
            "prescripción", "prescripcion", "prescription",
            "statute", "limitaciones", "limitations",
            "restricciones", "restrictions", "carencias",
            "waiting periods", "períodos", "periodos", "periods",
            "eliminación", "eliminacion", "elimination",
            "reducción", "reduccion", "reduction", "aumento",
            "increase", "incremento", "increment", "variación",
            "variacion", "variation", "cambio", "change",
            "modificación", "modificacion", "modification",
            "ajuste", "adjustment", "revisión", "revision",
            "review", "indexación", "indexacion", "indexation",
            "revalorización", "revalorizacion", "revaluation",
            "inflación", "inflacion", "inflation", "deflación",
            "deflacion", "deflation", "IPC", "CPI", "índice",
            "indice", "index", "tasa", "rate", "porcentaje",
            "percentage", "interés", "interes", "interest",
            "rendimiento", "yield", "retorno", "return",
            "plusvalía", "plusvalia", "capital gain",
            "minusvalía", "minusvalia", "capital loss",
            "amortización", "amortizacion", "amortization",
            "depreciación", "depreciacion", "depreciation",
            "provisión", "provision", "acciones", "shares",
            "stock", "bonos", "bonds", "obligaciones",
            "obligations", "deuda", "debt", "préstamo",
            "prestamo", "loan", "hipoteca", "mortgage",
            "leasing", "renting", "arrendamiento", "rental",
            "alquiler", "rent", "comisión", "comision",
            "commission", "honorarios", "fees", "cargo",
            "charge", "coste", "margen", "margin",
            "diferencial", "spread", "penalización",
            "penalizacion", "penalty", "sanción", "sancion",
            "sanction", "multa", "fine", "interés moratorio",
            "interes moratorio", "default interest", "demora",
            "delay", "mora", "default", "incumplimiento",
            "non-compliance", "reclamación", "reclamacion",
            "queja", "complaint", "disputa", "dispute",
            "conflicto", "conflict", "litigio", "litigation",
            "demanda", "lawsuit", "juicio", "trial",
            "arbitraje", "arbitration", "mediación",
            "mediacion", "mediation", "conciliación",
            "conciliacion", "conciliation", "defensa",
            "defense", "abogado", "lawyer", "letrado",
            "attorney", "procurador", "solicitor",
            "tribunal", "court", "juez", "judge",
            "sentencia", "sentence", "fallo", "ruling",
            "laudo", "award", "resolución", "resolucion",
            "resolution", "decisión", "decision",
            "determinación", "determinacion", "determination",
            "dictamen", "opinion", "peritaje", "expertise",
            "perito", "expert", "testigo", "witness",
            "evidencia", "evidence", "hecho", "fact",
            "circunstancia", "circumstance", "causa",
            "cause", "motivo", "reason", "origen", "origin",
            "procedencia", "source", "naturaleza", "nature",
            "características", "caracteristicas",
            "characteristics", "particularidades",
            "particularities", "especificaciones",
            "specifications", "detalles", "details",
            "información", "informacion", "information",
            "dato", "data", "registro", "record",
            "expediente", "file", "archivo", "archive",
            "carpeta", "folder", "documento", "document",
            "cuestionario", "questionnaire", "encuesta",
            "survey", "evaluación", "evaluacion",
            "evaluation", "valoración", "valoracion",
            "valuation", "calificación", "calificacion",
            "rating", "clasificación", "clasificacion",
            "classification", "categoría", "categoria",
            "category", "tipo", "type", "clase", "class",
            "modalidad", "modality", "variante", "variant",
            "versión", "version", "modelo", "model",
            "prestación", "prestacion", "benefit",
            "amparo", "alcance", "scope", "extensión",
            "extension", "extent", "tope", "cap",
            "coaseguro", "co-insurance", "subsidio",
            "subsidy", "prestación económica",
            "prestacion economica", "economic benefit",
            "viudedad", "widowhood", "orfandad",
            "orphanhood", "muerte", "death",
            "fallecimiento", "supervivencia", "survival",
            "sobrevivencia", "desempleo", "unemployment",
            "paro", "cesantía", "cesantia", "despido",
            "dismissal", "layoff", "indemnización",
            "indemnizacion", "severance", "finiquito",
            "settlement", "liquidación", "liquidacion",
            "liquidation", "vacaciones", "vacation",
            "holidays", "días", "dias", "days", "permiso",
            "permission", "leave", "licencia", "license",
            "baja", "maternidad", "parental",
            "excedencia", "leave of absence",
            "jornada", "working day", "horario",
            "schedule", "turno", "shift", "flexible",
            "teletrabajo", "telework", "remoto",
            "remote", "presencial", "in-person",
            "híbrido", "hibrido", "hybrid", "nómina",
            "nomina", "payroll", "salario", "salary",
            "sueldo", "wage", "remuneración",
            "remuneracion", "remuneration",
            "compensación", "compensacion",
            "compensation", "bono", "bonus",
            "incentivos", "incentives", "comisiones",
            "commissions", "variables", "variable pay",
            "fijo", "fixed", "base", "bruto", "gross",
            "neto", "net", "retención", "retencion",
            "withholding", "IRPF", "income tax",
            "seguridad social", "social security",
            "cotización", "cotizacion", "contribution",
            "aportación", "aportacion", "exento",
            "exempt", "exención", "exencion",
            "exemption", "deducción", "deduccion",
            "deduction", "bonificación",
            "bonificacion", "bonification",
            "subvención", "subvencion", "subsidy",
            "beca", "scholarship", "aval",
            "guarantee", "fianza", "bond",
            "embargo", "seizure", "confiscación",
            "confiscacion", "confiscation",
            "decomiso", "forfeiture", "incautación",
            "incautacion", "impago",
            "non-payment", "morosidad",
            "delinquency", "impagado", "unpaid",
            "pendiente", "pending", "vencido",
            "overdue", "fecha", "date", "día", "day",
            "mes", "month", "año", "ano", "year",
            "semestre", "semester", "trimestre",
            "quarter", "bimestre", "two-month",
            "trimestral", "quarterly", "semestral",
            "semi-annual", "bianual", "bi-annual",
            "plurianual", "multi-year", "período",
            "periodo", "duración", "duracion",
            "duration", "inicio", "start",
            "comienzo", "beginning", "final", "end",
            "extinción", "extincion", "extinction",
            "rescisión", "rescicion", "rescission",
            "revocación", "revocacion", "revocation",
            "prórroga", "prorroga", "extension",
            "novación", "novacion", "novation",
            "alteración", "alteracion", "alteration",
            "rectificación", "rectificacion",
            "rectification", "corrección",
            "correccion", "correction",
            "subsanación", "subsanacion",
            "enmienda", "amendment", "adenda",
            "addendum", "anexo", "annex",
            "apéndice", "apendice", "appendix",
            "artículo", "articulo", "article",
            "apartado", "section", "párrafo",
            "parrafo", "paragraph", "inciso",
            "subsection", "numeral", "literal",
            "punto", "point", "letra", "letter",
            "número", "numero", "number",
            "ordinal", "romano", "roman",
            "arábigo", "arabigo", "arabic",
            "mayúscula", "mayuscula", "uppercase",
            "minúscula", "minuscula", "lowercase",
            "negrita", "bold", "cursiva", "italic",
            "subrayado", "underlined",
            "tachado", "strikethrough",
            "mayor", "greater", "menor", "lesser",
            "igual", "equal", "diferente",
            "different", "distinto", "distinct",
            "similar", "equivalente",
            "equivalent", "idéntico", "identico",
            "identical", "mismo", "same",
            "análogo", "analogo", "analogous",
            "parecido", "semejante",
            "comparable", "proporcional",
            "proportional", "directamente",
            "directly", "inversamente", "inversely",
            "lineal", "linear", "exponencial",
            "exponential", "logarítmico",
            "logaritmico", "logarithmic",
            "geométrico", "geometrico", "geometric",
            "aritmético", "aritmetico", "arithmetic",
            "simple", "compuesto",
            "compound", "acumulado", "accumulated",
            "devengado", "accrued", "percibido",
            "received", "pagadero", "payable",
            "cobrable", "collectible",
            "exigible", "enforceable",
            "demandable", "reclamable",
            "claimable", "impugnable",
            "contestable", "apelable",
            "appealable", "recurrible",
            "firme", "final",
            "definitivo", "definitive",
            "ejecutivo", "executive",
            "ejecutable", "obligatorio",
            "mandatory", "voluntario",
            "voluntary", "potestativo",
            "optional", "facultativo",
            "discretionary", "discrecional",
            "imperativo", "imperative",
            "prohibitivo", "prohibitive",
            "permisivo", "permissive",
            "restrictivo", "restrictive",
            "limitado", "limited", "ilimitado",
            "unlimited", "absoluto", "absolute",
            "relativo", "relative", "parcial",
            "partial", "total", "completo",
            "complete", "íntegro", "integro",
            "entire", "entero", "whole",
            "global", "mundial", "worldwide",
            "nacional", "national", "regional",
            "local", "provincial",
            "municipal", "estatal", "state",
            "federal", "gubernamental",
            "government", "público", "publico",
            "public", "privado", "private",
            "mixto", "mixed", "cooperativo",
            "cooperative", "mutual",
            "solidario", "solidarity",
            "comunitario", "community",
            "social", "laboral", "labor",
            "sindical", "union", "empresarial",
            "business", "corporativo",
            "corporate", "institucional",
            "institutional", "profesional",
            "professional", "técnico",
            "tecnico", "technical",
            "especializado", "specialized",
            "certificado", "certified",
            "acreditado", "accredited",
            "autorizado", "authorized",
            "registrado", "registered",
            "licenciado", "licensed",
            "habilitado", "enabled",
            "capacitado", "trained",
            "calificado", "qualified",
            "competente", "competent",
            "idóneo", "idoneo", "suitable",
            "apto", "apt", "capaz", "capable",
            "hábil", "habil", "skillful",
            "experto", "expert",
            "consultor", "consultant",
            "asesor", "advisor", "consejero",
            "counselor", "gestor", "manager",
            "administrador", "administrator",
            "directivo", "gerente",
            "supervisor", "coordinador",
            "coordinator", "responsable",
            "responsible", "encargado",
            "in charge", "delegado",
            "delegate", "representante",
            "representative", "apoderado",
            "attorney-in-fact", "mandatario",
            "mandatary", "fiduciario",
            "fiduciary", "albacea",
            "executor", "tutor",
            "curador", "curator",
            "protector", "defensor",
        }
        _GENERIC_REJECT = {
            "success", "achievement", "motivation", "inspiration",
            "determination", "perseverance", "winner", "champion",
            "sunrise", "mountains", "sunset", "beach", "ocean",
            "nature", "landscape", "beautiful", "amazing",
            "incredible", "awesome", "great", "wonderful",
            "goal setting", "dream big", "never give up",
            "keep going", "stay strong", "believe",
            "positive thinking", "mindset", "growth mindset",
            "leadership", "teamwork", "success story",
            "happy", "joy", "celebration", "party",
            "confetti", "fireworks", "stars", "galaxy",
            "abstract", "colorful", "vibrant", "dynamic",
            "energy", "power", "strength", "courage",
            "bravery", "hope", "faith", "love",
            "passion", "excellence", "perfection",
            "freedom", "adventure", "explore", "discover",
            "journey", "path", "road", "way",
            "light", "darkness", "shadow", "silhouette",
        }
        _transcript_lower = text.lower()
        _is_insurance = any(kw in _transcript_lower for kw in _INSURANCE_KW)
        if _is_insurance:
            _before = len(ai_keywords)
            ai_keywords = [kw for kw in ai_keywords if kw.lower() in _INSURANCE_KW]
            _rejected = _before - len(ai_keywords)
            if _rejected:
                logger.warning(
                    "[ClipIntel/DomainFilter] clip=%d insurance content: "
                    "rejected %d/%d generic keywords (kept=%s)",
                    clip_index + 1, _rejected, _before, ai_keywords,
                )
            if not ai_keywords:
                logger.warning(
                    "[ClipIntel/DomainFilter] clip=%d ALL %d keywords rejected "
                    "for insurance content — falling back to semantic planner cues",
                    clip_index + 1, _before,
                )
        else:
            # Non-insurance content: still reject obviously generic concepts
            _before = len(ai_keywords)
            ai_keywords = [kw for kw in ai_keywords if kw.lower() not in _GENERIC_REJECT]
            _rejected = _before - len(ai_keywords)
            if _rejected:
                logger.info(
                    "[ClipIntel/DomainFilter] clip=%d rejected %d generic keywords",
                    clip_index + 1, _rejected,
                )

        broll_count = calculate_max_broll(duration, virality, hook_type)
        broll_dur   = 3.5 if energy < 0.4 else (2.8 if energy < 0.7 else 2.2)
        # HARD PLANNING-STAGE GATE: reject any b-roll cue under 2.5s
        if broll_dur < 2.5:
            logger.info(
                "[ClipIntel/AI/DurationGate] clip=%d rejecting short b-roll cue: "
                "planned=%.1fs (energy=%.2f) → clamped to 2.5s",
                clip_index + 1, broll_dur, energy,
            )
            broll_dur = 2.5

        wps         = len(text.split()) / max(1.0, duration)
        pace        = "fast" if wps > 3.5 else ("medium" if wps > 2.0 else "slow")

        profile = ClipProfile(
            mood=mood, energy=energy, pace=pace, virality=virality,
            lut=lut, caption_style=caption_style,
            broll_count=broll_count, broll_duration=broll_dur,
            bgm_category=bgm_category, zoom_intensity=zoom_intensity,
            sfx_emphasis=sfx_emphasis, saturation=saturation, contrast=contrast,
            ai_keywords=ai_keywords,
        )
        logger.info(
            "[ClipIntel/AI] clip=%d %s | broll_kw=%s",
            clip_index + 1, profile.describe(), ai_keywords,
        )
        return profile

    except Exception as exc:
        logger.debug("[ClipIntel/AI] Groq failed: %s", exc)
        return None


async def build_clip_profile_async(
    segment: Dict[str, Any],
    duration: float,
    clip_index: int,
    caption_template: str = "viral",
    words: Optional[List[Dict[str, Any]]] = None,
) -> ClipProfile:
    """
    Full intelligence pipeline:
      1. Groq AI brain → semantic editing decisions (fast, ~300 tokens)
      2. Editorial Brain → content-category specialization + narrative structure
      3. Heuristic fallback if either AI step fails
    Always returns a valid ClipProfile — never raises.
    """
    # Step 1: AI or heuristic base profile
    profile = await _build_clip_profile_ai(segment, duration, clip_index)
    ai_was_used = profile is not None
    if profile is None:
        profile = build_clip_profile(segment, duration, clip_index, caption_template)

    # Step 2: Editorial Brain — category identification + narrative structure
    try:
        from ...domains.ai.editorial_brain import analyze_clip, apply_category_rules
        category, narrative = await analyze_clip(
            segment=segment,
            duration=duration,
            clip_index=clip_index,
            words=words,
        )
        profile = apply_category_rules(
            profile=profile,
            category_key=category,
            narrative=narrative,
            trust_ai_values=ai_was_used,
        )
    except Exception as _eb_e:
        logger.debug("[ClipIntel] EditorialBrain skipped: %s", _eb_e)

    logger.info(
        "[BRAIN] clip=%d | cat=%s | mood=%s | energy=%.2f | lut=%s | "
        "caption=%s | bgm=%s | zoom=%s | grain=%d | broll=%dx%.1fs | "
        "broll_fade=%.2fs | sat=%.2f | con=%.2f | kw=%s",
        clip_index + 1,
        getattr(profile, "content_category", "?"),
        profile.mood, profile.energy,
        profile.lut, profile.caption_style,
        profile.bgm_category, profile.zoom_intensity,
        getattr(profile, "grain", 0),
        profile.broll_count, profile.broll_duration,
        getattr(profile, "broll_fade_s", 0.25),
        profile.saturation, profile.contrast,
        getattr(profile, "ai_keywords", [])[:3],
    )
    return profile
