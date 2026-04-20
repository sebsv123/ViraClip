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


async def _translate_keyword_llm(word: str, transcript_ctx: str) -> str:
    """Use Groq LLM to translate a trigger word + context into a visual search term."""
    import httpx
    groq_key = os.getenv("GROQ_API_KEY", "")
    if not groq_key:
        return _TRIGGER_TO_VISUAL.get(word.lower().strip(), word)

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
    return _TRIGGER_TO_VISUAL.get(word.lower().strip(), word)


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

    # ── 2. Convert timeline events → candidate slots ─────────────────────
    raw_slots: list[BrollSlot] = []

    for ev in timeline_events:
        if ev.type == "keyword":
            cat = ev.payload.get("category", "")
            word = ev.payload.get("word", "")
            vm = _classify_visual_mode(word)

            if cat in ("hook",) and ev.strength >= 0.8:
                prio = "high"
                hint = "ltxv" if vm in ("conceptual", "mood") else "video"
            elif cat in ("impact", "energy"):
                prio = "med"
                hint = "image_kenburns" if vm in ("conceptual", "mood", "abstract") else "video"
            else:
                prio = "low"
                hint = "image_kenburns"

            # Use LLM translation with transcript context for better relevance
            translated = await _translate_keyword_llm(word, transcript)
            raw_slots.append(BrollSlot(
                t=ev.t,
                duration=min(max(ev.duration, 1.5), 3.0),
                keyword=translated,
                priority=prio,
                source_hint=hint,
                visual_mode=vm,
                source_event_type="keyword",
            ))

        elif ev.type == "silence" and ev.duration >= 2.0:
            raw_slots.append(BrollSlot(
                t=ev.t,
                duration=min(ev.duration, 5.0),
                keyword="",  # will be filled by mood fallback
                priority="med",
                source_hint="image_kenburns",
                visual_mode="mood",
                source_event_type="silence",
            ))

    # ── 3. Fill large gaps (≥8s without any event) ───────────────────────
    raw_slots.sort(key=lambda s: s.t)
    gap_slots = _fill_gaps(raw_slots, clip_duration)
    raw_slots.extend(gap_slots)
    raw_slots.sort(key=lambda s: s.t)

    # ── 4. Enforce minimum spacing ───────────────────────────────────────
    filtered = _enforce_spacing(raw_slots, _MIN_SPACING_S)

    # ── 5. Trim to max_slots, prioritising high > med > low ─────────────
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


def _fill_gaps(slots: list[BrollSlot], clip_duration: float) -> list[BrollSlot]:
    """Insert low-priority mood slots for gaps ≥ _GAP_THRESHOLD_S."""
    gap_slots: list[BrollSlot] = []
    prev_end = 0.0

    for slot in slots:
        gap = slot.t - prev_end
        if gap >= _GAP_THRESHOLD_S:
            mid = prev_end + gap / 2
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
        default_kw = "cinematic abstract"

    for slot in slots:
        if not slot.keyword:
            slot.keyword = default_kw
