"""
SemanticEditPlanner — Word-level B-roll and SFX cue generation.

Two-layer pipeline:
  Layer 1: Instant keyword heuristic (no API, <10ms, always runs)
  Layer 2: Groq semantic pass (one batch request per clip, ~1.5s)

Output: SemanticEditPlan with precise timestamps for B-roll insertion
and SFX placement tied to the exact word that triggered them.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class BrollCue:
    timestamp: float        # seconds from clip start — when to begin overlay
    keyword: str            # Pexels/Pixabay search term (English)
    duration: float         # overlay length in seconds (2-5s)
    trigger_phrase: str     # the spoken text that triggered this cue
    confidence: float       # 0-1


@dataclass
class SfxCue:
    timestamp: float        # seconds from clip start — when to fire SFX
    sfx_type: str           # key from SoundDesignService.VIRAL_SOUND_MAP
    trigger_word: str       # the word that triggered this cue
    intensity: float        # 0.3-1.0


@dataclass
class SemanticEditPlan:
    broll_cues: List[BrollCue] = field(default_factory=list)  # max 3 per clip
    sfx_cues:   List[SfxCue]   = field(default_factory=list)  # max 4 per clip
    source: str = "heuristic"                                  # "groq" | "heuristic"


# ── Heuristic lookup tables (ES + EN) ────────────────────────────────────────

_MONEY_RE   = re.compile(r"(?:\$|€|£|\d+[kKmM]|\d{3,})", re.IGNORECASE)
_NUMBER_BIG = re.compile(r"\b\d{3,}\b")

_PLACE_MAP: Dict[str, str] = {
    "ciudad": "modern city skyline", "city": "modern city skyline",
    "casa": "home interior", "home": "home interior", "house": "home interior",
    "oficina": "office workspace", "office": "office workspace",
    "playa": "beach ocean", "beach": "beach ocean",
    "montaña": "mountain landscape", "mountain": "mountain landscape",
    "calle": "street urban", "street": "street urban",
    "restaurante": "restaurant dining", "restaurant": "restaurant dining",
    "aeropuerto": "airport travel", "airport": "airport travel",
    "gimnasio": "gym workout", "gym": "gym workout",
    "hospital": "hospital medical", "escuela": "classroom school",
    "school": "classroom school", "universidad": "university campus",
    "university": "university campus",
}

_ACTION_MAP: Dict[str, str] = {
    "corr": "running athlete", "run": "running athlete",
    "construi": "construction building", "build": "construction building",
    "cocin": "cooking food", "cook": "cooking food",
    "entrenam": "workout training", "train": "workout training",
    "escrib": "writing desk", "write": "writing desk",
    "viaj": "travel adventure", "travel": "travel adventure",
    "vend": "sales deal", "sell": "sales deal",
    "invert": "investment chart", "invest": "investment chart",
    "programar": "coding laptop", "coding": "coding laptop",
    "diseñ": "graphic design", "design": "graphic design",
    "meditar": "meditation calm", "meditat": "meditation calm",
}

_ROLE_MAP: Dict[str, str] = {
    "médico": "doctor hospital", "doctor": "doctor hospital",
    "ceo": "business executive", "executive": "business executive",
    "atleta": "athlete sport", "athlete": "athlete sport",
    "empresario": "entrepreneur startup", "entrepreneur": "entrepreneur startup",
    "programador": "programmer coding", "developer": "programmer coding",
    "chef": "chef cooking kitchen",
    "abogado": "lawyer courtroom", "lawyer": "lawyer courtroom",
    "profesor": "teacher classroom", "teacher": "teacher classroom",
    "músico": "musician performance", "musician": "musician performance",
    "artista": "artist studio", "artist": "artist studio",
}

_OBJECT_MAP: Dict[str, str] = {
    "coche": "luxury car", "car": "luxury car", "auto": "luxury car",
    "ordenador": "laptop computer", "laptop": "laptop computer",
    "teléfono": "smartphone", "phone": "smartphone",
    "dinero": "cash money", "money": "cash money", "cash": "cash money",
    "libro": "book reading", "book": "book reading",
    "avión": "airplane flight", "plane": "airplane flight",
    "comida": "food meal", "food": "food meal",
    "café": "coffee cup", "coffee": "coffee cup",
    "música": "music studio", "music": "music studio",
}

_VISUAL_LOOKUPS = [_PLACE_MAP, _ACTION_MAP, _ROLE_MAP, _OBJECT_MAP]

# SFX trigger sets: (fragment_set, sfx_type, intensity)
_SFX_TRIGGERS: List[tuple] = [
    (
        {"secreto", "secret", "verdad", "truth", "real", "descubrí", "discovered",
         "nunca", "never", "jamás", "revelación", "reveal", "expuesto", "exposed",
         "clave", "key", "razón", "reason"},
        "insight_reveal", 0.85,
    ),
    (
        {"por qué", "why", "sabes", "knew", "sabías", "imagina", "imagine",
         "qué pasaría", "what if", "cómo", "how", "cuál", "which"},
        "curiosity_gap", 0.75,
    ),
    (
        {"espera", "wait", "para", "stop", "mentira", "lie", "falso", "wrong",
         "error", "mistake", "equivocado", "sorpresa", "surprise", "increíble",
         "incredible", "imposible", "impossible"},
        "pattern_interrupt", 0.80,
    ),
    (
        {"pero", "sin embargo", "however", "aunque", "though",
         "hay más", "more", "además", "also", "todavía", "still",
         "lo que nadie", "nobody", "nadie sabe"},
        "cliffhanger", 0.55,
    ),
    (
        {"entonces", "así que", "so", "por eso", "that's why",
         "finalmente", "finally", "ahora", "now", "resultado", "result"},
        "transition", 0.60,
    ),
]

_VALID_SFX = {
    "insight_reveal", "curiosity_gap", "pattern_interrupt",
    "cliffhanger", "emphasis_word", "scroll_stop", "transition",
}

# Timing constants
_BROLL_HOOK_GUARD = 2.0     # no B-roll in first 2s (protect hook)
_BROLL_CTA_GUARD  = 2.0     # no B-roll in last 2s
_BROLL_MIN_GAP    = 4.0     # minimum gap between B-rolls
_BROLL_MAX        = 3       # max B-rolls per clip
_SFX_MIN_GAP      = 1.5     # minimum gap between SFX
_SFX_MAX          = 4       # max SFX per clip
_WINDOW_S         = 5.0     # Groq analysis window size


# ── Layer 1: Heuristic scanner ────────────────────────────────────────────────

def _scan_heuristic(words: List[Dict[str, Any]], duration: float) -> SemanticEditPlan:
    """
    Instant keyword scan. No API call. Returns SemanticEditPlan from
    visual noun detection (B-roll) and impact word detection (SFX).
    """
    broll_cues: List[BrollCue] = []
    sfx_cues:   List[SfxCue]   = []

    for w in words:
        raw   = (w.get("word") or w.get("text") or "").strip()
        word  = raw.lower().rstrip(".,!?¿¡\"'")
        ts    = float(w.get("start", 0))

        if not word or ts < 0:
            continue

        # ── B-roll trigger ────────────────────────────────────────────────────
        kw: Optional[str] = None

        if _MONEY_RE.search(word) or _NUMBER_BIG.search(word):
            kw = "cash money"

        if kw is None:
            for lookup in _VISUAL_LOOKUPS:
                for fragment, search_term in lookup.items():
                    if fragment in word:
                        kw = search_term
                        break
                if kw:
                    break

        if kw and _BROLL_HOOK_GUARD <= ts <= duration - _BROLL_CTA_GUARD:
            if all(abs(ts - c.timestamp) >= _BROLL_MIN_GAP for c in broll_cues):
                if len(broll_cues) < _BROLL_MAX:
                    broll_cues.append(BrollCue(
                        timestamp=ts,
                        keyword=kw,
                        duration=min(3.5, max(2.0, duration - ts - 0.5)),
                        trigger_phrase=raw[:40],
                        confidence=0.70,
                    ))

        # ── SFX trigger ───────────────────────────────────────────────────────
        sfx_type: Optional[str]  = None
        sfx_int:  float           = 0.60

        if _MONEY_RE.search(word) or _NUMBER_BIG.search(word):
            sfx_type = "emphasis_word"
            sfx_int  = 0.90
        else:
            for trigger_set, stype, intensity in _SFX_TRIGGERS:
                if any(frag in word for frag in trigger_set):
                    sfx_type = stype
                    sfx_int  = intensity
                    break

        if sfx_type and ts > 0.5:
            if all(abs(ts - c.timestamp) >= _SFX_MIN_GAP for c in sfx_cues):
                if len(sfx_cues) < _SFX_MAX:
                    sfx_cues.append(SfxCue(
                        timestamp=ts,
                        sfx_type=sfx_type,
                        trigger_word=word[:30],
                        intensity=sfx_int,
                    ))

    return SemanticEditPlan(broll_cues=broll_cues, sfx_cues=sfx_cues, source="heuristic")


# ── Layer 2: Groq semantic batch pass ────────────────────────────────────────

def _build_windows(words: List[Dict[str, Any]], duration: float) -> List[Dict[str, Any]]:
    """Group word list into non-overlapping time windows of _WINDOW_S seconds."""
    windows: List[Dict[str, Any]] = []
    t = 0.0
    while t < duration:
        t_end = t + _WINDOW_S
        chunk = [w for w in words if t <= float(w.get("start", 0)) < t_end]
        if chunk:
            text = " ".join(
                (w.get("word") or w.get("text") or "") for w in chunk
            ).strip()
            windows.append({
                "t_start": round(t, 2),
                "t_end":   round(min(t_end, duration), 2),
                "text":    text,
                "words":   chunk,
            })
        t = t_end
    return windows


_GROQ_SYSTEM = (
    "You are a precise video editor. For each spoken text window decide:\n"
    "1. B-ROLL: Is there a visually concrete noun, action, place, or object? "
    "If yes, output a short English Pexels-style search keyword and the start timestamp.\n"
    "2. SFX: Is there a high-impact emotional word (revelation, big number, rhetorical "
    "question, transition)? If yes, output the SFX type and timestamp.\n\n"
    "Valid SFX types: insight_reveal | curiosity_gap | pattern_interrupt | "
    "cliffhanger | emphasis_word | transition\n\n"
    "Rules:\n"
    "- Only output broll/sfx when confidence >0.70\n"
    "- null means no cue for that category in that window\n"
    "- Return ONLY valid JSON: {\"results\": [{\"w\": <int>, "
    "\"broll\": {\"t\": <float>, \"kw\": \"<str>\"}|null, "
    "\"sfx\": {\"t\": <float>, \"type\": \"<str>\"}|null}]}"
)


async def _groq_semantic_pass(
    windows: List[Dict[str, Any]],
    duration: float,
) -> Optional[List[Dict[str, Any]]]:
    """
    Send all windows in a single Groq request.
    Returns list of per-window annotations or None on failure.
    """
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key or not windows:
        return None

    lines = [
        f"[{i}] T={win['t_start']:.1f}s–{win['t_end']:.1f}s: \"{win['text']}\""
        for i, win in enumerate(windows)
    ]
    user_msg = "\n".join(lines)

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [
                        {"role": "system", "content": _GROQ_SYSTEM},
                        {"role": "user",   "content": user_msg},
                    ],
                    "max_tokens": 700,
                    "temperature": 0.10,
                    "response_format": {"type": "json_object"},
                },
            )
        if resp.status_code != 200:
            logger.debug("[SemanticPlanner/Groq] HTTP %d", resp.status_code)
            return None

        raw = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(raw) if isinstance(raw, str) else raw

        # Unwrap envelope
        if isinstance(parsed, dict):
            for key in ("results", "data", "windows", "items"):
                if isinstance(parsed.get(key), list):
                    return parsed[key]
            return None
        if isinstance(parsed, list):
            return parsed
        return None

    except Exception as exc:
        logger.debug("[SemanticPlanner/Groq] failed: %s", exc)
        return None


def _merge_groq(
    plan: SemanticEditPlan,
    groq_results: List[Dict[str, Any]],
    windows: List[Dict[str, Any]],
    duration: float,
) -> SemanticEditPlan:
    """Merge Groq annotations (confidence=0.90) on top of the heuristic plan."""
    for item in groq_results:
        win_idx = item.get("w", -1)
        win     = windows[win_idx] if 0 <= win_idx < len(windows) else {}
        context = win.get("text", "")[:50]

        # B-roll
        broll = item.get("broll")
        if isinstance(broll, dict):
            t  = float(broll.get("t", -1))
            kw = str(broll.get("kw", "")).strip()
            if kw and _BROLL_HOOK_GUARD <= t <= duration - _BROLL_CTA_GUARD:
                if all(abs(t - c.timestamp) >= _BROLL_MIN_GAP for c in plan.broll_cues):
                    if len(plan.broll_cues) < _BROLL_MAX:
                        plan.broll_cues.append(BrollCue(
                            timestamp=t, keyword=kw,
                            duration=min(3.5, max(2.0, duration - t - 0.5)),
                            trigger_phrase=context, confidence=0.90,
                        ))
                    else:
                        # Replace lowest-confidence heuristic entry
                        lo = min(range(len(plan.broll_cues)),
                                 key=lambda i: plan.broll_cues[i].confidence)
                        if plan.broll_cues[lo].confidence < 0.90:
                            plan.broll_cues[lo] = BrollCue(
                                timestamp=t, keyword=kw,
                                duration=min(3.5, max(2.0, duration - t - 0.5)),
                                trigger_phrase=context, confidence=0.90,
                            )

        # SFX
        sfx = item.get("sfx")
        if isinstance(sfx, dict):
            t        = float(sfx.get("t", -1))
            sfx_type = str(sfx.get("type", "")).strip()
            if sfx_type in _VALID_SFX and t > 0.5:
                if all(abs(t - c.timestamp) >= _SFX_MIN_GAP for c in plan.sfx_cues):
                    if len(plan.sfx_cues) < _SFX_MAX:
                        plan.sfx_cues.append(SfxCue(
                            timestamp=t, sfx_type=sfx_type,
                            trigger_word=context[:25], intensity=0.85,
                        ))

    plan.broll_cues.sort(key=lambda c: c.timestamp)
    plan.sfx_cues.sort(key=lambda c: c.timestamp)
    plan.source = "groq"
    return plan


# ── Public entry point ────────────────────────────────────────────────────────

class SemanticEditPlanner:
    """
    Produces word-level B-roll and SFX cues from a word-timestamp transcript.

    plan = await SemanticEditPlanner().plan(words, duration, hook_type)
    plan.broll_cues  →  precise timestamps + search keywords for B-roll
    plan.sfx_cues    →  precise timestamps + SFX types
    """

    async def plan(
        self,
        words: List[Dict[str, Any]],
        duration: float,
        hook_type: str = "insight_reveal",
        category:  str = "unknown",
    ) -> SemanticEditPlan:
        """
        Build a SemanticEditPlan.
        Layer 1 (heuristic) always runs; Layer 2 (Groq) runs when API key available.
        Never raises — returns empty plan on any failure.
        """
        if not words or duration <= 0:
            return SemanticEditPlan()

        try:
            # Layer 1: heuristic
            plan = _scan_heuristic(words, duration)
            logger.info(
                "[SemanticPlanner] heuristic → %d B-roll, %d SFX cues",
                len(plan.broll_cues), len(plan.sfx_cues),
            )

            # Guarantee at least one opening SFX cue from hook_type
            if hook_type in _VALID_SFX:
                has_early = any(c.timestamp < 1.5 for c in plan.sfx_cues)
                if not has_early:
                    plan.sfx_cues.insert(0, SfxCue(
                        timestamp=0.30,
                        sfx_type=hook_type,
                        trigger_word="hook_open",
                        intensity=0.90,
                    ))

            # Layer 2: Groq semantic
            if os.environ.get("GROQ_API_KEY"):
                windows = _build_windows(words, duration)
                if windows:
                    groq_out = await _groq_semantic_pass(windows, duration)
                    if groq_out:
                        plan = _merge_groq(plan, groq_out, windows, duration)

            # Final caps + sort
            plan.broll_cues = sorted(plan.broll_cues, key=lambda c: c.timestamp)[:_BROLL_MAX]
            plan.sfx_cues   = sorted(plan.sfx_cues,   key=lambda c: c.timestamp)[:_SFX_MAX]

            logger.info(
                "[SemanticPlanner] final plan (source=%s): B-roll=[%s] SFX=[%s]",
                plan.source,
                ", ".join(f"{c.timestamp:.1f}s:{c.keyword}" for c in plan.broll_cues) or "—",
                ", ".join(f"{c.timestamp:.1f}s:{c.sfx_type}" for c in plan.sfx_cues) or "—",
            )
            return plan

        except Exception as exc:
            logger.warning("[SemanticPlanner] plan() failed: %s", exc)
            return SemanticEditPlan()
