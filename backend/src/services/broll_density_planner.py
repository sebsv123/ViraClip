"""
B-Roll Density Planner — Ola B Creative Engine

The 'brain' that decides WHEN, WHERE, and WHAT TYPE of B-roll to insert.
Consumes the timeline from multimodal_detector (Step 1) and produces a
prioritised list of BrollSlot objects that the B-roll pipeline then fulfils.

Design:
  - Reads timeline events (keyword, audio_peak, silence) that are already
    computed — never re-analyses audio or transcript.
  - Classifies each slot by priority (high/med/low) and visual_mode
    (literal/conceptual/mood/abstract).
  - Fills gaps ≥8s with low-priority mood B-roll.
  - Respects a target coverage percentage that adapts to clip energy.
  - Editorial anchors: B-roll slots are anchored to speech meaning rather
    than static gap-fill.  No B-roll in first 0.5s unless hook context
    demands it.  No B-roll over dense explanation where face/captions
    matter more.  Max 3 B-roll slots per clip.  Minimum gap between slots.
    Prefer 1 strong B-roll over 3 weak ones.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────────
_MIN_SPACING_S      = float(os.environ.get("BROLL_MIN_SPACING_SEC", "3.0"))
_GAP_THRESHOLD_S    = float(os.environ.get("BROLL_GAP_THRESHOLD_SEC", "8.0"))
_AVG_BROLL_DUR_S    = float(os.environ.get("BROLL_AVG_DURATION_SEC", "4.0"))
_LTXV_MAX_PER_CLIP  = int(os.environ.get("LTXV_BROLL_MAX_PER_CLIP", "2"))
_LTXV_THRESHOLD     = float(os.environ.get("LTXV_BROLL_PRIORITY_THRESHOLD", "0.7"))

# Coverage targets by clip energy classification
_COVERAGE_NARRATIVE  = 0.55   # 55% for narrative/emotional clips
_COVERAGE_ACTION     = 0.25   # 25% for action/high-energy clips
_COVERAGE_DEFAULT    = 0.40   # 40% default

# ── Editorial anchor constants (Part B) ─────────────────────────────────────
# Editorial moments that justify B-roll insertion (speech meaning anchors)
_EDITORIAL_ANCHOR_CATEGORIES = {
    "risk_warning_context",
    "family_relief",
    "family_protection",
    "paperwork_support",
    "documents_admin",
    "practical_explanation",
    "financial_planning",
    "emotional_reassurance",
    "health_access",
    "autonomous_work_stability",
}

# Transcript phrases that indicate dense explanation — avoid B-roll here
_DENSE_EXPLANATION_PHRASES = {
    "es decir", "o sea", "quiero decir", "esto significa", "lo que pasa es que",
    "básicamente", "en otras palabras", "dicho de otra forma", "dicho de otro modo",
    "lo explico", "te explico", "vamos a ver", "fijate", "mira", "escucha",
    "presta atención", "importante entender", "hay que tener en cuenta",
    "ten en cuenta", "no olvides", "recuerda que", "lo importante es",
}

# Hook context phrases — allow B-roll in first 0.5s
_HOOK_CONTEXT_PHRASES = {
    "te voy a contar", "sabías que", "imagínate", "piensa en esto",
    "qué pasaría si", "alguna vez te has preguntado", "esto te va a sorprender",
    "no te lo vas a creer", "te tengo una noticia", "escucha esto",
    "mira esto", "atención", "alerta", "importante",
}

# Max B-roll slots per clip
_MAX_BROLL_SLOTS_PER_CLIP = 3

# Minimum gap between B-roll slots (seconds)
_MIN_GAP_BETWEEN_SLOTS = 3.0

# ── Static fallback: Spanish/English trigger word → English visual search term ─
_TRIGGER_TO_VISUAL = {
    "peor": "mistake warning sign", "mejor": "success achievement",
    "increíble": "amazing discovery", "increible": "amazing discovery",
    "nunca": "person saying no", "secreto": "mystery reveal",
    "sorprendente": "surprised reaction", "imposible": "impossible challenge",
    "top": "ranking list podium", "número": "number statistics",
    "numero": "number statistics", "primer": "first place winner",
    "primero": "first place winner", "viral": "social media phone",
    "wow": "amazed person", "dios": "shocked reaction",
    "espera": "hand stop gesture", "mira": "person pointing looking",
    "escucha": "person listening", "dinero": "money cash currency",
    "gratis": "free gift present", "peligroso": "danger warning",
    "nuevo": "new product launch", "importante": "important document",
    "urgente": "urgent alarm clock", "millones": "millions dollars wealth",
    "error": "mistake failure", "hack": "technology shortcut",
    "truco": "clever trick", "clave": "key unlock",
    "ahora": "clock time now", "exclusivo": "exclusive vip",
    # English equivalents
    "worst": "mistake warning sign", "best": "success trophy",
    "incredible": "amazing discovery", "never": "person refusing",
    "secret": "mystery reveal", "surprising": "surprised reaction",
    "impossible": "impossible challenge", "number": "statistics chart",
    "first": "first place winner", "wait": "hand stop gesture",
    "look": "person pointing", "listen": "person listening carefully",
    "amazing": "amazed reaction", "seriously": "serious conversation",
    "finally": "celebration finish line", "actually": "fact reveal",
}

_LOW_SIGNAL_STOPWORDS = {
    "de", "la", "el", "los", "las", "que", "sea", "o", "y", "les", "me", "te",
    "un", "una", "es", "en", "por", "para", "con", "como", "esto", "este",
    "esta", "momento", "pues", "hola",
}


async def _translate_keyword_llm(word: str, transcript_ctx: str) -> str:
    """Use Groq LLM to translate a trigger word + context into a visual search term."""
    import httpx
    groq_key = os.getenv("GROQ_API_KEY", "")
    if not groq_key:
        w = word.lower().strip()
        # Stopword guard: the caller (plan_broll_density) already skips stopwords
        # with continue, so this is dead code for stopwords. Return the word
        # itself as a safe fallback rather than a generic mood term.
        if w in _LOW_SIGNAL_STOPWORDS or len(w) <= 2:
            return w
        return _TRIGGER_TO_VISUAL.get(w, w)

    prompt = (
        "You are a stock-video editor. Given a transcript excerpt and a trigger word, "
        "return 2-4 SPECIFIC English search terms for stock video that visually "
        "illustrate what the speaker means in context.\n"
        "Rules: concrete nouns/actions only, no abstract concepts, no emotions.\n"
        "Reply with ONLY a JSON array, e.g. [\"office meeting\", \"handshake deal\"]\n\n"
        f"Transcript: ...{transcript_ctx[-200:]}...\n"
        f"Trigger word: {word}\n"
    )
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {groq_key}"},
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 40,
                    "temperature": 0.15,
                },
            )
            if resp.status_code == 429:
                logger.info("BROLL_LLM_FALLBACK reason=429")
                return _TRIGGER_TO_VISUAL.get(word.lower().strip(), word)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
            terms = json.loads(content)
            if isinstance(terms, list) and terms:
                result = " ".join(str(t) for t in terms[:2])
                logger.info("[BrollPlanner] LLM translated '%s' → '%s'", word, result)
                return result
    except Exception as exc:
        logger.debug("[BrollPlanner] LLM translation failed for '%s': %s", word, exc)

    return _TRIGGER_TO_VISUAL.get(word.lower().strip(), word)


def _translate_keyword_sync(word: str) -> str:
    """Synchronous fallback: static mapping only."""
    w = word.lower().strip()
    # ── Stopword guard: the caller (plan_broll_density) already skips stopwords
    # with continue, so this is dead code for stopwords. Return the word
    # itself as a safe fallback rather than a generic mood term.
    if w in _LOW_SIGNAL_STOPWORDS or len(w) <= 2:
        return w
    return _TRIGGER_TO_VISUAL.get(w, w)


# ── Visual-mode classification dictionaries ──────────────────────────────────

_LITERAL_TERMS = {
    "familia", "family", "ciudad", "city", "computadora", "computer", "phone",
    "laptop", "car", "ocean", "mountain", "forest", "office", "food", "house",
    "home", "children", "kids", "money", "cash", "street", "building", "airport",
    "gym", "sport", "athlete", "crowd", "restaurant", "coffee", "hotel",
    "person", "people", "woman", "man", "dog", "cat", "nature", "sky", "sunset",
}

_CONCEPTUAL_TERMS = {
    "disciplina", "discipline", "crecimiento", "growth", "éxito", "success",
    "fracaso", "failure", "libertad", "freedom", "poder", "power", "riesgo",
    "risk", "cambio", "change", "futuro", "future", "decisión", "decision",
    "oportunidad", "opportunity", "sacrificio", "sacrifice", "estrategia",
    "strategy", "resultado", "result", "progreso", "progress", "meta", "goal",
}

_MOOD_TERMS = {
    "inspiración", "inspiration", "motivación", "motivation", "miedo", "fear",
    "felicidad", "happiness", "tristeza", "sadness", "energía", "energy",
    "pasión", "passion", "calma", "calm", "paz", "peace", "fuerza", "strength",
    "determinación", "determination", "soledad", "loneliness", "esperanza", "hope",
}


@dataclass
class BrollSlot:
    """A planned B-roll insertion point."""
    t: float                    # timestamp of insertion (relative to clip start)
    duration: float             # target B-roll duration
    keyword: str                # search term for asset lookup
    priority: str               # "high" | "med" | "low"
    source_hint: str            # "video" | "image_kenburns" | "ltxv"
    visual_mode: str            # "literal" | "conceptual" | "mood" | "abstract"
    source_event_type: str = "" # original timeline event type
    timing_anchor: str = ""     # editorial anchor category (Part B)


@dataclass
class DensityPlan:
    """Full B-roll plan for a single clip."""
    slots: List[BrollSlot] = field(default_factory=list)
    clip_duration: float = 0.0
    energy_class: str = "default"    # "narrative" | "action" | "default"
    target_coverage: float = 0.40
    planned_coverage: float = 0.0
    ltxv_slots: int = 0


# ── Public API ───────────────────────────────────────────────────────────────

async def plan_broll_density(
    timeline_events: list,
    clip_duration: float,
    transcript: str = "",
    audio_energy: float = 0.5,
    preset_name: str = "",
) -> DensityPlan:
    """
    Produce a prioritised list of BrollSlots from an existing timeline.

    Args:
        timeline_events: list of TimelineEvent from multimodal_detector.
        clip_duration:   total clip duration in seconds.
        transcript:      full clip transcript (used for mood fallback).
        audio_energy:    0.0–1.0 average energy from audio analysis.
        preset_name:     template preset name (for energy classification).

    Returns:
        DensityPlan with ordered slots.
    """
    plan = DensityPlan(clip_duration=clip_duration)

    # ── 1. Classify clip energy ──────────────────────────────────────────
    plan.energy_class = _classify_energy(audio_energy, preset_name)
    if plan.energy_class == "narrative":
        plan.target_coverage = _COVERAGE_NARRATIVE
    elif plan.energy_class == "action":
        plan.target_coverage = _COVERAGE_ACTION
    else:
        plan.target_coverage = _COVERAGE_DEFAULT

    max_slots = max(1, int(clip_duration * plan.target_coverage / _AVG_BROLL_DUR_S))
    # Cap at editorial max (Part B)
    max_slots = min(max_slots, _MAX_BROLL_SLOTS_PER_CLIP)

    # ── 2. Convert timeline events → candidate slots ─────────────────────
    raw_slots: list[BrollSlot] = []
    llm_calls_used = 0
    llm_call_budget = 3

    # Detect editorial anchors from transcript (Part B)
    editorial_anchors = _detect_editorial_anchors(transcript)

    # Detect dense explanation regions (Part B)
    dense_regions = _detect_dense_explanation_regions(transcript)

    # Detect hook context (Part B)
    is_hook_context = _detect_hook_context(transcript)

    for ev in timeline_events:
        if ev.type == "keyword":
            cat = ev.payload.get("category", "")
            word = str(ev.payload.get("word", "")).strip()
            vm = _classify_visual_mode(word)
            normalized_word = word.lower()
            if cat in ("hook",) and getattr(ev, "strength", 0.0) >= 0.8:
                prio = "high"
                hint = "ltxv" if vm in ("conceptual", "mood") else "video"
            elif cat in ("impact", "energy"):
                prio = "med"
                hint = "image_kenburns" if vm in ("conceptual", "mood", "abstract") else "video"
            else:
                prio = "low"
                hint = "image_kenburns"

            # ── Part B: No B-roll in first 0.5s unless hook context ──
            if ev.t < 0.5 and not is_hook_context:
                if normalized_word in _LOW_SIGNAL_STOPWORDS or len(normalized_word) <= 2:
                    logger.info(
                        "BROLL_SKIPPED reason=stopword_or_low_signal t=%.1f keyword=%r",
                        ev.t, word,
                    )
                    continue
                rescheduled_t = min(3.0, max(1.5, float(ev.t) + 1.8))
                logger.info(
                    "BROLL_RESCHEDULED reason=too_early_for_broll original_t=%.1f new_t=%.1f keyword=%r",
                    ev.t, rescheduled_t, word,
                )
                ev = BrollSlot(
                    t=rescheduled_t,
                    duration=ev.duration,
                    keyword=word,
                    priority=prio,
                    source_hint=hint,
                    visual_mode=vm,
                    source_event_type="keyword",
                    timing_anchor="rescheduled_from_opening",
                )

            # ── Part B: No B-roll over dense explanation ──
            if _is_in_dense_region(ev.t, dense_regions):
                logger.info(
                    "BROLL_SKIPPED reason=dense_explanation t=%.1f keyword=%r",
                    ev.t, word,
                )
                continue

            if (not normalized_word) or normalized_word in _LOW_SIGNAL_STOPWORDS or len(normalized_word) <= 2:
                logger.info("BROLL_LLM_SKIPPED reason=stopword_or_low_signal keyword=%r", word)
                # ── Stopword/low-signal: produce NO BrollSlot at all ──
                continue
            elif normalized_word in _TRIGGER_TO_VISUAL:
                logger.info("BROLL_LLM_SKIPPED reason=local_editorial_match keyword=%r", word)
                translated = _translate_keyword_sync(word)
            elif llm_calls_used >= llm_call_budget:
                logger.info("BROLL_LLM_SKIPPED reason=rate_limit_budget keyword=%r", word)
                translated = _translate_keyword_sync(word)
            else:
                translated = await _translate_keyword_llm(word, transcript)
                llm_calls_used += 1

            # ── Part B: Find editorial anchor for this slot ──
            anchor = _find_anchor_for_timestamp(ev.t, editorial_anchors)

            raw_slots.append(BrollSlot(
                t=ev.t,
                duration=min(max(ev.duration, 1.5), 3.0),
                keyword=translated,
                priority=prio,
                source_hint=hint,
                visual_mode=vm,
                source_event_type="keyword",
                timing_anchor=anchor,
            ))

        elif ev.type == "silence" and ev.duration >= 2.0:
            # ── Part B: No B-roll in first 0.5s unless hook context ──
            if ev.t < 0.5 and not is_hook_context:
                continue

            # ── Part B: No B-roll over dense explanation ──
            if _is_in_dense_region(ev.t, dense_regions):
                continue

            anchor = _find_anchor_for_timestamp(ev.t, editorial_anchors)
            raw_slots.append(BrollSlot(
                t=ev.t,
                duration=min(ev.duration, 5.0),
                keyword="",  # will be filled by mood fallback
                priority="med",
                source_hint="image_kenburns",
                visual_mode="mood",
                source_event_type="silence",
                timing_anchor=anchor,
            ))

    # ── 3. Fill large gaps (≥8s without any event) — but only if there's
    #       an editorial anchor nearby (Part B: avoid static gap-fill) ────
    raw_slots.sort(key=lambda s: s.t)
    gap_slots = _fill_gaps(raw_slots, clip_duration, editorial_anchors)
    raw_slots.extend(gap_slots)
    raw_slots.sort(key=lambda s: s.t)

    # ── 4. Enforce minimum spacing ───────────────────────────────────────
    filtered = _enforce_spacing(raw_slots, _MIN_SPACING_S)

    # ── 5. Trim to max_slots, prioritising high > med > low ─────────────
    #       Part B: Prefer 1 strong B-roll over 3 weak ones
    prio_order = {"high": 0, "med": 1, "low": 2}
    filtered.sort(key=lambda s: (prio_order.get(s.priority, 3), s.t))
    selected = filtered[:max_slots]
    selected.sort(key=lambda s: s.t)  # restore chronological order

    # ── 6. Cap LTXV slots ────────────────────────────────────────────────
    ltxv_count = 0
    for slot in selected:
        if slot.source_hint == "ltxv":
            ltxv_count += 1
            if ltxv_count > _LTXV_MAX_PER_CLIP:
                # Downgrade excess LTXV slots to image_kenburns
                slot.source_hint = "image_kenburns"

    # ── 7. Mood fallback for slots without keywords ──────────────────────
    _apply_mood_fallback(selected, transcript, preset_name)

    plan.slots = selected
    plan.planned_coverage = sum(s.duration for s in selected) / max(clip_duration, 1.0)
    plan.ltxv_slots = sum(1 for s in selected if s.source_hint == "ltxv")

    logger.info(
        "[BrollPlanner] %s: %d slots, coverage=%.0f%% (target=%.0f%%), ltxv=%d, energy=%s",
        "Plan ready", len(selected),
        plan.planned_coverage * 100, plan.target_coverage * 100,
        plan.ltxv_slots, plan.energy_class,
    )
    return plan


# ── Helpers ──────────────────────────────────────────────────────────────────

def _classify_energy(audio_energy: float, preset_name: str) -> str:
    """Classify clip as narrative, action, or default based on energy + preset."""
    preset_lower = preset_name.lower()
    if any(kw in preset_lower for kw in ("calm", "story", "narrat", "podcast", "interview")):
        return "narrative"
    if any(kw in preset_lower for kw in ("hype", "action", "energy", "sport", "gaming")):
        return "action"
    if audio_energy < 0.35:
        return "narrative"
    if audio_energy > 0.7:
        return "action"
    return "default"


def _classify_visual_mode(word: str) -> str:
    """Classify a keyword into literal/conceptual/mood/abstract."""
    w = word.lower().strip()
    if w in _LITERAL_TERMS:
        return "literal"
    if w in _CONCEPTUAL_TERMS:
        return "conceptual"
    if w in _MOOD_TERMS:
        return "mood"
    # Heuristic: if the word is short and common, try literal; otherwise abstract
    if len(w) <= 6:
        return "literal"
    return "abstract"


def _fill_gaps(
    slots: list[BrollSlot],
    clip_duration: float,
    editorial_anchors: Optional[List[dict]] = None,
) -> list[BrollSlot]:
    """
    Insert low-priority mood slots for gaps ≥ _GAP_THRESHOLD_S.
    Part B: Only insert gap-fill if there's an editorial anchor nearby.
    Avoid static gap-fill just because coverage target says so.
    """
    gap_slots: list[BrollSlot] = []
    prev_end = 0.0

    for slot in slots:
        gap = slot.t - prev_end
        if gap >= _GAP_THRESHOLD_S:
            mid = prev_end + gap / 2
            # Part B: Only insert if there's an editorial anchor near this gap
            if editorial_anchors and not _has_anchor_nearby(mid, editorial_anchors, threshold=3.0):
                logger.info(
                    "BROLL_GAP_SKIPPED reason=no_editorial_anchor_nearby gap_start=%.1f gap_end=%.1f",
                    prev_end, slot.t,
                )
            else:
                gap_slots.append(BrollSlot(
                    t=mid,
                    duration=min(4.0, gap * 0.4),
                    keyword="",
                    priority="low",
                    source_hint="image_kenburns",
                    visual_mode="mood",
                    source_event_type="gap_fill",
                ))
        prev_end = slot.t + slot.duration

    # Check trailing gap
    trailing = clip_duration - prev_end
    if trailing >= _GAP_THRESHOLD_S:
        mid = prev_end + trailing / 2
        if editorial_anchors and not _has_anchor_nearby(mid, editorial_anchors, threshold=3.0):
            logger.info(
                "BROLL_GAP_SKIPPED reason=no_editorial_anchor_nearby_trailing gap_start=%.1f clip_end=%.1f",
                prev_end, clip_duration,
            )
        else:
            gap_slots.append(BrollSlot(
                t=mid,
                duration=min(4.0, trailing * 0.4),
                keyword="",
                priority="low",
                source_hint="image_kenburns",
                visual_mode="mood",
                source_event_type="gap_fill",
            ))

    return gap_slots


def _enforce_spacing(slots: list[BrollSlot], min_spacing: float) -> list[BrollSlot]:
    """Remove slots that are too close together, keeping the higher priority."""
    if not slots:
        return []
    prio_rank = {"high": 0, "med": 1, "low": 2}
    result: list[BrollSlot] = [slots[0]]
    for slot in slots[1:]:
        prev = result[-1]
        if slot.t - (prev.t + prev.duration) < min_spacing:
            # Keep the one with higher priority
            if prio_rank.get(slot.priority, 3) < prio_rank.get(prev.priority, 3):
                result[-1] = slot
            # else: keep prev, skip slot
        else:
            result.append(slot)
    return result


def _apply_mood_fallback(
    slots: list[BrollSlot],
    transcript: str,
    preset_name: str,
) -> None:
    """Fill empty keywords with mood-appropriate search terms."""
    # Build a simple mood keyword from the transcript or preset
    _mood_words = ["cinematic atmosphere", "inspiration", "motivation", "abstract"]
    preset_lower = preset_name.lower()
    if "motivat" in preset_lower or "inspir" in preset_lower:
        default_kw = "motivation inspiration"
    elif "tech" in preset_lower or "business" in preset_lower:
        default_kw = "technology innovation"
    elif "calm" in preset_lower or "story" in preset_lower:
        default_kw = "peaceful cinematic"
    else:
        # Part B: Avoid "cinematic abstract" for VPI insurance — use domain-specific
        default_kw = _domain_specific_fallback(transcript)

    for slot in slots:
        if not slot.keyword:
            slot.keyword = default_kw


def _domain_specific_fallback(transcript: str) -> str:
    """
    Part B: Return a domain-specific fallback keyword instead of 'cinematic abstract'.
    For VPI insurance/finance content, use concrete terms.
    """
    transcript_lower = transcript.lower()
    if any(term in transcript_lower for term in ("seguro", "seguros", "poliza", "cobertura", "prima", "hipoteca")):
        return "financial planning documents"
    if any(term in transcript_lower for term in ("familia", "hijos", "pareja", "proteccion")):
        return "family protection home"
    if any(term in transcript_lower for term in ("riesgo", "imprevisto", "peligro")):
        return "risk management planning"
    if any(term in transcript_lower for term in ("documentos", "papeleo", "tramites", "contrato")):
        return "office paperwork documents"
    if any(term in transcript_lower for term in ("salud", "medico", "hospital", "clinica")):
        return "health consultation clinic"
    return "cinematic abstract"  # safe fallback for non-VPI content


# ── Part B: Editorial anchor detection helpers ───────────────────────────────

def _detect_editorial_anchors(transcript: str) -> List[dict]:
    """
    Detect editorial anchor moments from transcript.
    Returns list of dicts with 'category' and approximate 'timestamp' (word index based).
    """
    if not transcript:
        return []
    anchors: List[dict] = []
    words = transcript.lower().split()
    total_words = len(words)
    if total_words == 0:
        return []

    # Map trigger phrases to editorial categories
    trigger_map = {
        "riesgo": "risk_warning_context",
        "imprevisto": "risk_warning_context",
        "peligro": "risk_warning_context",
        "desprotegido": "risk_warning_context",
        "familia": "family_relief",
        "hijos": "family_relief",
        "pareja": "family_relief",
        "proteccion": "family_protection",
        "dependen": "family_protection",
        "sostener": "family_protection",
        "papeleo": "paperwork_support",
        "tramites": "paperwork_support",
        "documentos": "documents_admin",
        "poliza": "documents_admin",
        "contrato": "documents_admin",
        "formulario": "paperwork_support",
        "explicar": "practical_explanation",
        "significa": "practical_explanation",
        "funciona": "practical_explanation",
        "hipoteca": "financial_planning",
        "capital": "financial_planning",
        "prima": "financial_planning",
        "ahorro": "financial_planning",
        "presupuesto": "financial_planning",
        "tranquilo": "emotional_reassurance",
        "confianza": "emotional_reassurance",
        "seguridad": "emotional_reassurance",
        "salud": "health_access",
        "medico": "health_access",
        "independencia": "autonomous_work_stability",
        "trabajo": "autonomous_work_stability",
    }

    for i, word in enumerate(words):
        if word in trigger_map:
            # Estimate timestamp as fraction of clip (will be refined by caller)
            rel_pos = i / max(total_words - 1, 1)
            anchors.append({
                "category": trigger_map[word],
                "word": word,
                "relative_position": rel_pos,
                "word_index": i,
            })

    return anchors


def _find_anchor_for_timestamp(t: float, anchors: List[dict]) -> str:
    """
    Find the closest editorial anchor category for a given timestamp.
    Returns empty string if no anchor is nearby.
    """
    if not anchors:
        return ""
    # For now, return the category of the closest anchor by word_index
    # (timestamps are approximated from word positions)
    return anchors[0].get("category", "") if anchors else ""


def _detect_dense_explanation_regions(transcript: str) -> List[dict]:
    """
    Detect regions of dense explanation where B-roll should be avoided.
    Returns list of dicts with 'start' and 'end' relative positions.
    """
    if not transcript:
        return []
    regions: List[dict] = []
    words = transcript.lower().split()
    total_words = len(words)
    if total_words == 0:
        return []

    for i, word in enumerate(words):
        # Check if this word starts a dense explanation phrase
        for phrase in _DENSE_EXPLANATION_PHRASES:
            phrase_words = phrase.split()
            if word == phrase_words[0]:
                # Check if the full phrase matches
                if i + len(phrase_words) <= total_words:
                    match = True
                    for j, pw in enumerate(phrase_words):
                        if words[i + j] != pw:
                            match = False
                            break
                    if match:
                        start_pos = i / max(total_words - 1, 1)
                        end_pos = min((i + len(phrase_words) + 5) / max(total_words - 1, 1), 1.0)
                        regions.append({
                            "start": start_pos,
                            "end": end_pos,
                            "phrase": phrase,
                        })
                        break

    return regions


def _is_in_dense_region(t: float, dense_regions: List[dict]) -> bool:
    """
    Check if a timestamp falls within a dense explanation region.
    Uses relative position (0.0-1.0) as approximation.
    """
    if not dense_regions:
        return False
    # Approximate: use relative position within clip
    for region in dense_regions:
        if region["start"] <= t / 30.0 <= region["end"]:  # assume ~30s clip
            return True
    return False


def _detect_hook_context(transcript: str) -> bool:
    """
    Detect if the transcript starts with a hook context phrase.
    If so, B-roll is allowed in the first 0.5s.
    """
    if not transcript:
        return False
    transcript_lower = transcript.lower()[:200]  # check first ~200 chars
    for phrase in _HOOK_CONTEXT_PHRASES:
        if phrase in transcript_lower:
            return True
    return False


def _has_anchor_nearby(t: float, anchors: List[dict], threshold: float = 3.0) -> bool:
    """
    Check if there's an editorial anchor near a given timestamp.
    Uses relative position approximation.
    """
    if not anchors:
        return False
    # Approximate: check if any anchor's relative position is close to t
    for anchor in anchors:
        anchor_t = anchor.get("relative_position", 0.0) * 30.0  # assume ~30s clip
        if abs(anchor_t - t) <= threshold:
            return True
    return False
