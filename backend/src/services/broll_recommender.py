"""
B-roll Recommender — Intelligent B-roll selection with LLM + Pexels.

Pipeline:
  1. LLM extracts visual concepts/keywords from segment transcript.
  2. For each concept, queries Pexels for candidate clips.
  3. Scores candidates by relevance (semantic similarity to concept) and
     novelty (whether the video_id has already been used in this task).
  4. Returns top-N candidates sorted by total_score = 0.7 * relevance + 0.3 * novelty.
  5. Updates task_ctx with used_broll_ids and segment→broll_id mapping.

Thread/async safety: task_ctx is expected to be a dict with asyncio.Lock
protection when shared across concurrent clip processing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set

import httpx


logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
_BROLL_REC_DEFAULT_MAX = 5
_LLM_TIMEOUT = 15.0
_PEXELS_TIMEOUT = 15.0
_PEXELS_PER_PAGE = 20  # increased from 8 to get a larger candidate pool
_QUALITY_WEIGHT = 0.2
_RELEVANCE_WEIGHT = 0.55
_NOVELTY_WEIGHT = 0.25
_MAX_TRANSCRIPT_WORDS = 400
_MAX_CONCEPTS = 4
_MAX_KEYWORDS_PER_CONCEPT = 3
_RANDOM_SAMPLE_TOP_N = 15  # randomly sample from top N candidates for variety
_FALLBACK_MIN_ASSETS = 2   # minimum unique unused assets before fallback retry

# Semantic expansion: visual context words for query diversification
_VISUAL_CONTEXTS = [
    "person", "team", "city", "technology", "nature",
    "office", "hands", "screen", "crowd", "light",
]

# ── Insurance content detection keywords (Spanish) ────────────────────────────
# Matches the same pattern used in broll_service.py and confidence_subtitle_service.py
_INSURANCE_TRIGGER_WORDS: List[str] = [
    "seguro", "seguros", "aseguradora", "póliza", "cobertura",
    "prima", "siniestro", "indemnización", "reclamación",
    "vida", "coche", "hogar", "mutua", "protección",
    "ahorro", "tranquilidad", "contrato", "fallecimiento",
    "accidente", "precio", "presupuesto", "asegurado",
    "beneficiario", "deducible", "franquicia", "renovación",
    "cancelación", "asistencia", "defensa jurídica",
    "responsabilidad civil", "todo riesgo", "daños",
    "robo", "incendio", "inundación", "desempleo",
    "enfermedad", "hospitalización", "cirugía",
    "medicamentos", "reembolso", "copago",
    "pensión", "jubilación", "inversión",
    "hipoteca", "préstamo", "crédito",
]

# ── Insurance-native b-roll concepts ──────────────────────────────────────────
# These are the ONLY acceptable b-roll concepts for insurance/finance content.
# Each concept is a concrete, visual, insurance-domain idea that can be searched
# on stock video sites. Generic motivational or unrelated concepts are rejected.
_INSURANCE_NATIVE_CONCEPTS: List[str] = [
    "policy", "claim", "coverage", "premium", "protection",
    "family", "savings", "risk", "responsibility",
    "payments", "approval", "documents", "contracts",
    "advisor", "customer", "office", "calculator",
    "forms", "phone call", "consultation",
    # Additional concrete insurance visuals
    "insurance", "life insurance", "health insurance",
    "car insurance", "home insurance", "insurance agent",
    "insurance broker", "insurance document", "insurance policy",
    "claim form", "claim approval", "coverage plan",
    "financial advisor", "financial planning", "retirement planning",
    "family protection", "safety concept", "peace of mind",
    "signing contract", "agreement handshake", "handshake deal",
    "doctor consultation", "medical support", "hospital",
    "car accident", "road accident", "accident scene",
    "budget planning", "money savings", "piggy bank",
    "modern family home", "family home", "house",
    "office desk", "office meeting", "business meeting",
    "professional", "businessman", "businesswoman",
    "customer service", "help desk", "support",
    "paperwork", "filing documents", "document signing",
    "calculator counting", "counting money", "finance graph",
    "chart", "graph", "statistics", "data analysis",
    "approval stamp", "approved", "signature",
    "phone consultation", "phone call", "calling",
    "online banking", "laptop finance", "digital insurance",
]

# ── Generic concepts REJECTED for insurance content ──────────────────────────
# These concepts are never acceptable when the transcript is about insurance.
_GENERIC_REJECTED_CONCEPTS: List[str] = [
    "success", "achievement", "determination", "winner", "champion",
    "sunrise", "mountains", "nature", "landscape", "people",
    "ocean", "beach", "sunset", "forest", "waterfall",
    "meditation", "yoga", "fitness", "workout", "gym",
    "party", "celebration", "fireworks", "confetti",
    "travel", "vacation", "holiday", "adventure",
    "space", "globe", "earth", "universe", "stars",
    "abstract", "colorful", "animation", "background",
    "motivation", "inspiration", "dream", "goal",
    "team building", "leadership", "seminar", "training",
    "podcast", "microphone", "recording studio",
    "dance", "music", "concert", "festival",
    "food", "cooking", "restaurant", "kitchen",
    "fashion", "shopping", "clothes", "model",
    "sports", "running", "cycling", "swimming",
    "gaming", "video game", "esports",
    "pets", "dogs", "cats", "animals",
    "wedding", "romance", "dating", "love",
    "technology abstract", "circuit board", "coding",
    "city skyline", "night city", "street photography",
]


def _is_insurance_content(transcript: str) -> bool:
    """Detect if the transcript is about insurance content using trigger words."""
    if not transcript:
        return False
    transcript_lower = transcript.lower()
    for trigger in _INSURANCE_TRIGGER_WORDS:
        if trigger.lower() in transcript_lower:
            logger.info("[BrollRec] Insurance content detected via trigger word '%s'", trigger)
            return True
    return False


def _filter_insurance_keywords(keywords: List[str], is_insurance: bool) -> List[str]:
    """
    Harden keyword selection for insurance content.
    
    When *is_insurance* is True:
    1. Prefer keywords matching _INSURANCE_NATIVE_CONCEPTS.
    2. Reject keywords matching _GENERIC_REJECTED_CONCEPTS.
    3. If ALL keywords rejected, return empty list (no b-roll > irrelevant b-roll).
    
    When *is_insurance* is False, returns keywords unchanged.
    """
    if not is_insurance or not keywords:
        return keywords

    _native_lower = [c.lower() for c in _INSURANCE_NATIVE_CONCEPTS]
    _rejected_lower = [c.lower() for c in _GENERIC_REJECTED_CONCEPTS]

    kept: List[str] = []
    rejected: List[str] = []

    for kw in keywords:
        kw_lower = kw.lower().strip()

        # Check if keyword matches any rejected concept (substring match)
        _is_rejected = False
        for _rej in _rejected_lower:
            if _rej in kw_lower or kw_lower in _rej:
                _is_rejected = True
                rejected.append(kw)
                logger.info(
                    "[BrollRec/InsuranceFilter] ⛔ REJECTED keyword '%s' — "
                    "matches generic rejected concept '%s'. "
                    "Insurance content requires insurance-native visuals.",
                    kw, _rej,
                )
                break

        if _is_rejected:
            continue

        # Check if keyword matches any native concept (substring match)
        _is_native = False
        for _nat in _native_lower:
            if _nat in kw_lower or kw_lower in _nat:
                _is_native = True
                break

        if _is_native:
            kept.append(kw)
        else:
            # Borderline — not rejected, not native, but keep as it may support the message
            logger.info(
                "[BrollRec/InsuranceFilter] ⚠️ BORDERLINE keyword '%s' — "
                "not in insurance-native concepts list, but not rejected either. "
                "Keeping it as it may still support the insurance message.",
                kw,
            )
            kept.append(kw)

    if rejected:
        logger.info(
            "[BrollRec/InsuranceFilter] Filtered %d/%d keywords for insurance content: "
            "kept=%s, rejected=%s",
            len(rejected), len(keywords), kept, rejected,
        )

    if not kept:
        logger.warning(
            "[BrollRec/InsuranceFilter] ⛔ ALL %d keywords rejected for insurance content. "
            "Returning empty list — no b-roll is better than irrelevant b-roll.",
            len(keywords),
        )

    return kept



# ── Data types ─────────────────────────────────────────────────────────────────

@dataclass
class VisualConcept:
    """A visual concept extracted from the transcript, with search keywords."""
    concept: str
    keywords: List[str]
    start_time: float = 0.0      # when in the clip this concept should appear
    duration_s: float = 6.0      # how long it should stay on screen
    reason: str = ""             # why this concept fits at this moment

@dataclass
class BrollCandidate:
    """A scored B-roll candidate from Pexels."""
    video_id: int
    url: str
    duration: float
    width: int
    height: int
    concept: str
    keywords: List[str]
    relevance_score: float = 0.0
    novelty_score: float = 1.0
    total_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── LLM concept extraction ─────────────────────────────────────────────────────

_LLM_CONCEPT_PROMPT = """You are a professional video editor selecting B-roll 
footage for a vertical short-form video (TikTok/Reels/Shorts).

The speaker's transcript below includes timestamps in [MM:SS] format.
Your job is to decide:
1. WHAT visual concept best illustrates what is being said
2. EXACTLY WHEN it should appear (start_time)
3. HOW LONG it should stay on screen (duration_s, minimum 5 seconds)

Rules:
- B-roll must appear ONLY when it visually reinforces what the speaker says
- Place b-roll on CONCRETE moments (when speaker mentions a specific thing, 
  not during transition phrases like "and also" or "what I mean is")
- NEVER place b-roll during the first 2 seconds of the clip (hook moment)
- NEVER place two b-roll cues within 5 seconds of each other
- Minimum duration: 5 seconds. Maximum: 10 seconds.
- If the transcript has no clear visual moment, return empty concepts array
- Keywords must be in English for Pexels search
- NO generic keywords: hands, people, camera, office, man, woman, person

INSURANCE CONTENT RULES (apply when transcript is about insurance/finance):
- If the transcript mentions insurance, finance, policies, claims, coverage,
  premiums, protection, savings, or related topics, you MUST select concepts
  that are INSURANCE-NATIVE and CONCRETE.
- ACCEPTABLE insurance-native concepts: policy, claim, coverage, premium,
  protection, family, savings, risk, responsibility, payments, approval,
  documents, contracts, advisor, customer, office, calculator, forms,
  phone call, consultation, insurance agent, handshake, signing contract,
  financial planning, family protection, safety concept, peace of mind,
  doctor consultation, car accident, budget planning, piggy bank,
  modern family home, office meeting, business meeting, professional,
  customer service, paperwork, filing documents, document signing,
  counting money, finance graph, chart, graph, statistics, data analysis,
  approval stamp, signature, phone consultation, online banking.
- REJECTED concepts for insurance content: success, achievement, determination,
  winner, champion, sunrise, mountains, nature, landscape, ocean, beach,
  sunset, forest, meditation, yoga, fitness, party, celebration, fireworks,
  travel, vacation, adventure, space, abstract, motivation, inspiration,
  dream, goal, team building, leadership, seminar, training, podcast,
  microphone, dance, music, concert, food, cooking, fashion, shopping,
  sports, running, gaming, pets, animals, wedding, romance, dating, love,
  technology abstract, circuit board, coding, city skyline.
- If the transcript is about insurance, EVERY concept MUST be insurance-native.
  Do NOT suggest generic motivational or unrelated stock concepts.
- Use concrete visual ideas, not abstract themes.

Respond with ONLY valid JSON:
{{
  "concepts": [
    {{
      "concept": "short description of what viewer will see",
      "keywords": ["keyword1", "keyword2"],
      "start_time": 8.5,
      "duration_s": 6.0,
      "reason": "speaker says X at this moment"
    }}
  ]
}}

Transcript with timestamps:
{transcript}"""


async def _extract_concepts_llm(
    transcript: str,
    groq_key: str,
    max_concepts: int = _MAX_CONCEPTS,
) -> List[VisualConcept]:
    """Call Groq (llama-3.1-8b-instant) to extract visual concepts from transcript."""
    # Truncate transcript to avoid token overflow
    words = transcript.split()
    if len(words) > _MAX_TRANSCRIPT_WORDS:
        transcript = " ".join(words[:_MAX_TRANSCRIPT_WORDS])

    prompt = _LLM_CONCEPT_PROMPT.format(
        max_concepts=max_concepts,
        transcript=transcript,
    )

    try:
        async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {groq_key}"},
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 300,
                    "temperature": 0.3,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()

            # Try to parse JSON — handle markdown code fences
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            data = json.loads(content)
            concepts_raw = data.get("concepts", [])
            concepts: List[VisualConcept] = []
            for c in concepts_raw[:max_concepts]:
                kw = [str(k).strip() for k in c.get("keywords", []) if k]
                if c.get("concept") and kw:
                    # Parse start_time, duration_s, reason from LLM response
                    start_time = float(c.get("start_time", 0.0))
                    duration_s = float(c.get("duration_s", 6.0))
                    # Clamp duration to [5, 10]
                    duration_s = max(5.0, min(10.0, duration_s))
                    reason = str(c.get("reason", "")).strip()
                    concepts.append(VisualConcept(
                        concept=str(c["concept"]).strip(),
                        keywords=kw[:_MAX_KEYWORDS_PER_CONCEPT],
                        start_time=start_time,
                        duration_s=duration_s,
                        reason=reason,
                    ))
            if concepts:
                logger.info(
                    "[BrollRec] LLM extracted %d concepts: %s",
                    len(concepts),
                    [c.concept for c in concepts],
                )
                return concepts
    except Exception as e:
        logger.warning("[BrollRec] LLM concept extraction failed: %s", e)

    return []


def _fallback_concepts(transcript: str) -> List[VisualConcept]:
    """Simple fallback: extract noun-like words as concepts when LLM is unavailable.

    When insurance content is detected, returns insurance-native fallback concepts
    instead of generic ones. This ensures that even when the LLM is unavailable,
    insurance content gets appropriate b-roll visuals.
    """
    is_insurance = _is_insurance_content(transcript)

    if is_insurance:
        # Insurance-native fallback — concrete, domain-specific visuals
        fallback = [
            VisualConcept(concept="insurance policy", keywords=["insurance", "policy", "document"]),
            VisualConcept(concept="family protection", keywords=["family", "protection", "home"]),
            VisualConcept(concept="office meeting", keywords=["office", "meeting", "professional"]),
            VisualConcept(concept="financial planning", keywords=["finance", "planning", "calculator"]),
            VisualConcept(concept="customer service", keywords=["customer", "service", "support"]),
        ]
        logger.info("[BrollRec] Using insurance-native fallback concepts (LLM unavailable)")
        return fallback

    # Return safe generic concepts — never raw transcript words in other languages
    fallback = [
        VisualConcept(concept="nature", keywords=["nature", "landscape", "outdoor"]),
        VisualConcept(concept="people", keywords=["people", "crowd", "urban"]),
        VisualConcept(concept="technology", keywords=["technology", "office", "digital"]),
    ]
    logger.info("[BrollRec] Using fallback concepts (LLM unavailable)")
    return fallback


# ── Pexels search ──────────────────────────────────────────────────────────────

async def _search_pexels_for_keywords(
    keywords: List[str],
    pexels_key: str,
    per_page: int = _PEXELS_PER_PAGE,
    page: int = 1,
) -> List[Dict[str, Any]]:
    """Search Pexels videos for a set of keywords. Returns raw video results.

    Args:
        keywords: Search keywords.
        pexels_key: Pexels API key.
        per_page: Results per page (default 20 for larger candidate pool).
        page: Page number for pagination rotation (default 1).
    """
    query = " ".join(keywords)
    try:
        async with httpx.AsyncClient(timeout=_PEXELS_TIMEOUT) as client:
            resp = await client.get(
                "https://api.pexels.com/videos/search",
                headers={"Authorization": pexels_key},
                params={
                    "query": query,
                    "per_page": per_page,
                    "page": page,
                    "orientation": "portrait",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            videos = data.get("videos", [])
            results = []
            for v in videos:
                best_file = _pick_best_video_file(v.get("video_files", []))
                if best_file:
                    results.append({
                        "video_id": v["id"],
                        "url": best_file["link"],
                        "duration": v.get("duration", 0),
                        "width": best_file.get("width", 0),
                        "height": best_file.get("height", 0),
                    })
            return results
    except Exception as e:
        logger.warning("[BrollRec] Pexels search failed for '%s': %s", query, e)
        return []



def _pick_best_video_file(video_files: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Pick the best quality portrait or landscape HD file from Pexels video_files."""
    portrait = [
        f for f in video_files
        if f.get("height", 0) > f.get("width", 0) and f.get("file_type") == "video/mp4"
    ]
    if portrait:
        return sorted(portrait, key=lambda f: f.get("height", 0), reverse=True)[0]
    hd = [
        f for f in video_files
        if f.get("quality") in ("hd", "sd") and f.get("file_type") == "video/mp4"
    ]
    if hd:
        return hd[0]
    return video_files[0] if video_files else None


# ── Scoring ────────────────────────────────────────────────────────────────────

def _compute_relevance(
    candidate_keywords: List[str],
    concept_keywords: List[str],
) -> float:
    """
    Compute relevance score (0–1) between candidate keywords and concept keywords.
    Uses simple keyword overlap + Jaccard similarity as a lightweight semantic proxy.
    """
    ck_set = set(k.lower().strip() for k in candidate_keywords)
    pk_set = set(k.lower().strip() for k in concept_keywords)

    if not ck_set or not pk_set:
        return 0.5  # neutral score when no keywords to compare

    # Jaccard similarity on keyword sets
    intersection = ck_set & pk_set
    union = ck_set | pk_set
    jaccard = len(intersection) / len(union) if union else 0.0

    # Bonus for exact matches
    exact_matches = sum(1 for ck in ck_set for pk in pk_set if ck == pk)
    exact_bonus = min(0.3, exact_matches * 0.15)

    # Bonus for partial word overlap
    partial_matches = 0
    for ck in ck_set:
        for pk in pk_set:
            if ck != pk and (ck in pk or pk in ck):
                partial_matches += 1
    partial_bonus = min(0.2, partial_matches * 0.1)

    return min(1.0, jaccard + exact_bonus + partial_bonus)


def _compute_novelty(
    video_id: int,
    used_broll_ids: Set[int],
) -> float:
    """
    Compute novelty score (0–1).
    1.0 = never used before, 0.0 = already used.
    """
    if video_id in used_broll_ids:
        return 0.0
    return 1.0


def _compute_quality(duration: float, width: int, height: int) -> float:
    """
    Compute quality score (0–1) based on technical attributes.
    Returns 0.0 for videos under 5s (skip entirely).
    """
    score = 0.0
    # Duration quality: ideal is 8-15s
    if duration >= 8:
        score += 0.4
    elif duration >= 5:
        score += 0.2
    else:
        return 0.0  # skip videos under 5s entirely

    # Resolution quality: prefer HD portrait
    is_portrait = height > width
    is_hd = min(width, height) >= 720
    if is_portrait and is_hd:
        score += 0.4
    elif is_hd:
        score += 0.2
    elif is_portrait:
        score += 0.1

    # Aspect ratio quality: ideal for vertical is 9:16
    if width > 0:
        ratio = height / width
        if 1.6 <= ratio <= 1.85:  # near 9:16
            score += 0.2

    return min(1.0, score)


# ── B-roll hard-limit post-filter ─────────────────────────────────────────────
# Enforces five rules on the final candidate list before returning:
#   1. Minimum 15s gap between consecutive broll insertions.
#   2. Maximum 25% total clip duration covered by broll in aggregate.
#   3. Minimum individual broll duration: 4s (discard shorter).
#   4. Maximum individual broll duration: 8s (cap longer).
#   5. If total clip duration < 30s, return zero brolls.

_MIN_BROLL_GAP_S = 15.0
_MAX_BROLL_COVERAGE = 0.25
_MIN_BROLL_DUR_S = 4.0
_MAX_BROLL_DUR_S = 8.0
_MIN_CLIP_DUR_FOR_BROLL = 30.0


def _post_filter_broll_candidates(
    candidates: List[BrollCandidate],
    clip_duration: float,
) -> List[BrollCandidate]:
    """
    Post-filter pass that enforces hard limits on broll candidates.

    Rules applied at the asset-recommendation level:
      3. Minimum individual broll duration: 4s (discard shorter).
      4. Maximum individual broll duration: 8s (cap longer).
      5. If total clip duration < 30s, return zero brolls.

    Rules 1 (15s gap) and 2 (25% coverage) are enforced downstream in
    broll_service._sanitize_broll_timeline() where insertion timestamps
    are known.
    """
    if clip_duration < _MIN_CLIP_DUR_FOR_BROLL:
        logger.info(
            "[BrollRec] Clip duration %.1fs < %.1fs — returning zero brolls (rule 5)",
            clip_duration, _MIN_CLIP_DUR_FOR_BROLL,
        )
        return []

    filtered: List[BrollCandidate] = []

    for c in candidates:
        # Rule 3: minimum individual duration
        if c.duration < _MIN_BROLL_DUR_S:
            logger.debug(
                "[BrollRec] Dropping candidate id=%d (dur=%.1fs < min=%.1fs, rule 3)",
                c.video_id, c.duration, _MIN_BROLL_DUR_S,
            )
            continue

        # Rule 4: cap maximum individual duration
        capped_dur = min(c.duration, _MAX_BROLL_DUR_S)

        # Apply capped duration
        if capped_dur != c.duration:
            c = BrollCandidate(
                video_id=c.video_id,
                url=c.url,
                duration=capped_dur,
                width=c.width,
                height=c.height,
                concept=c.concept,
                keywords=c.keywords,
                relevance_score=c.relevance_score,
                novelty_score=c.novelty_score,
                total_score=c.total_score,
            )

        filtered.append(c)

    return filtered



# ── Main recommender ───────────────────────────────────────────────────────────

async def recommend_brolls(
    segment_transcript: str,
    segment_id: str,
    task_ctx: Dict[str, Any],
    max_results: int = _BROLL_REC_DEFAULT_MAX,
    used_asset_ids: Optional[Set[int]] = None,
    clip_duration: float = 0.0,
    job_id: str = "",
    ctx: Any = None,  # JobContext
) -> List[BrollCandidate]:

    """
    Main entry point: recommend B-roll clips for a segment.

    Args:
        segment_transcript: Transcript text of the segment (≤150 words recommended).
        segment_id: Unique identifier for this segment (e.g., "clip_3").
        task_ctx: Task-level context dict. Must contain:
            - "used_broll_ids": set[int] — video IDs already used in this task.
            - "segment_broll_map": dict[str, list[int]] — mapping segment_id → [broll_ids].
            Optionally may contain an asyncio.Lock at "lock" for thread-safe access.
        max_results: Maximum number of candidates to return.
        used_asset_ids: Optional shared set tracking asset IDs already assigned
            across all clips in the same job. Prevents the same Pexels/Pixabay
            asset from being reused across clips.
        clip_duration: Total duration of the clip in seconds. Used to enforce
            hard limits on broll coverage, gaps, and minimum clip length.
        job_id: Unique job identifier. Used for pagination rotation so different
            jobs hit different pages of Pexels results for the same query.

    Returns:
        List of BrollCandidate sorted by total_score descending.

    The function updates task_ctx in-place:
        - Adds chosen video IDs to task_ctx["used_broll_ids"]
        - Appends chosen video IDs to task_ctx["segment_broll_map"][segment_id]
    """

    # ── 1. Ensure task_ctx has required keys ──────────────────────────────────
    if "used_broll_ids" not in task_ctx:
        task_ctx["used_broll_ids"] = set()
    if "used_broll_urls" not in task_ctx:
        task_ctx["used_broll_urls"] = set()
    if "segment_broll_map" not in task_ctx:
        task_ctx["segment_broll_map"] = {}

    used_broll_ids: Set[int] = task_ctx["used_broll_ids"]
    used_broll_urls: Set[str] = task_ctx["used_broll_urls"]
    lock: Optional[asyncio.Lock] = task_ctx.get("lock")


    # ── 2. Extract concepts via LLM (with fallback) ───────────────────────────
    groq_key = os.getenv("GROQ_API_KEY", "")
    pexels_key = os.getenv("PEXELS_API_KEY", "")

    if groq_key:
        concepts = await _extract_concepts_llm(segment_transcript, groq_key)
    else:
        concepts = []

    if not concepts:
        concepts = _fallback_concepts(segment_transcript)

    # ── 2b. Insurance keyword filtering ──────────────────────────────────────
    # When insurance content is detected, filter out generic/rejected concepts
    # and prefer insurance-native concepts.
    is_insurance = _is_insurance_content(segment_transcript)
    if is_insurance and concepts:
        filtered_concepts: List[VisualConcept] = []
        for concept in concepts:
            # Filter the concept's keywords through insurance filter
            filtered_kw = _filter_insurance_keywords(concept.keywords, is_insurance)
            if filtered_kw:
                filtered_concepts.append(VisualConcept(
                    concept=concept.concept,
                    keywords=filtered_kw,
                    start_time=concept.start_time,
                    duration_s=concept.duration_s,
                    reason=concept.reason,
                ))
            else:
                logger.info(
                    "[BrollRec] ⛔ Dropping concept '%s' — all keywords rejected for insurance content",
                    concept.concept,
                )
        if filtered_concepts:
            concepts = filtered_concepts
            logger.info(
                "[BrollRec] After insurance filtering: %d concepts remain: %s",
                len(concepts),
                [c.concept for c in concepts],
            )
        else:
            # All concepts rejected — return empty to signal no b-roll
            logger.warning(
                "[BrollRec] ⛔ ALL concepts rejected for insurance content. "
                "Returning empty — no b-roll is better than irrelevant b-roll.",
            )
            return []

    logger.info(
        "[BrollRec] segment=%s, concepts=%s",
        segment_id,
        [c.concept for c in concepts],
    )

    # ── 3. Semantic expansion: build 3 query variants per keyword ─────────────
    # Pagination rotation: different jobs hit different pages to avoid top-5 bias
    _page = 1
    if job_id:
        _page = (hash(job_id) % 5) + 1  # pages 1-5

    all_candidates: List[BrollCandidate] = []
    seen_video_ids: Set[int] = set()
    used_queries: Set[str] = set()

    # Collect all unique keywords from all concepts
    all_keywords: List[str] = []
    for concept in concepts:
        for kw in concept.keywords:
            if isinstance(kw, str):
                all_keywords.append(kw)
            elif isinstance(kw, (list, tuple)):
                all_keywords.extend(kw)

    # Build 4 query variants per keyword: iconic, contextual, detail, metaphorical
    _GENERIC_WORDS = {"hands", "people", "office", "camera", "man", "woman", "person"}
    queries_to_run: List[str] = []
    for kw in all_keywords:
        kw_str = kw.strip().lower()
        if not kw_str:
            continue

        # Skip generic queries unless the transcript explicitly mentions them
        if kw_str in _GENERIC_WORDS:
            _in_transcript = any(kw_str in t.lower() for t in [segment_transcript])
            if not _in_transcript:
                logger.info("[BROLL] Skipped generic query '%s' (not in transcript)", kw_str)
                continue

        # query_1: iconic — the keyword itself, most direct representation
        q1 = kw_str
        if q1 not in used_queries:
            used_queries.add(q1)
            queries_to_run.append(q1)

        # query_2: contextual — keyword + visual context word for scene setting
        _ctx_idx = hash(kw_str) % len(_VISUAL_CONTEXTS)
        q2 = f"{kw_str} {_VISUAL_CONTEXTS[_ctx_idx]}"
        if q2 not in used_queries:
            used_queries.add(q2)
            queries_to_run.append(q2)

        # query_3: detail — close-up or macro variant
        q3 = f"{kw_str} close up detail"
        if q3 not in used_queries:
            used_queries.add(q3)
            queries_to_run.append(q3)

        # query_4: metaphorical — broader conceptual variant
        # Skip if keyword is too short (≤5 chars) to avoid truncated queries
        if len(kw_str) <= 5:
            continue
        q4 = f"{kw_str} concept"
        if q4 not in used_queries:
            used_queries.add(q4)
            queries_to_run.append(q4)

    # Skip queries already used in this job session
    if ctx is not None:
        queries_to_run = [q for q in queries_to_run if q not in ctx.used_broll_queries]

    # Run all queries
    for query in queries_to_run:
        raw_results = await _search_pexels_for_keywords([query], pexels_key, page=_page)
        for raw in raw_results:
            vid = raw["video_id"]
            if vid in seen_video_ids:
                continue
            seen_video_ids.add(vid)
            if raw.get("url") and raw["url"] in used_broll_urls:
                continue
            # Skip if already used in this job session
            if ctx is not None and vid in ctx.used_asset_ids:
                continue

            relevance = _compute_relevance([query], all_keywords)
            novelty = _compute_novelty(vid, used_broll_ids)
            quality = _compute_quality(raw["duration"], raw["width"], raw["height"])
            if quality == 0.0:
                logger.info(
                    "[BROLL] Skipped Pexels video id=%d duration=%.1fs (too short/low quality)",
                    vid, raw["duration"],
                )
                continue  # skip this video entirely
            total = _RELEVANCE_WEIGHT * relevance + _NOVELTY_WEIGHT * novelty + _QUALITY_WEIGHT * quality

            logger.info(
                "[BROLL] video_id=%d quality=%.2f rel=%.2f → total=%.2f",
                vid, quality, relevance, total,
            )

            candidate = BrollCandidate(
                video_id=vid,
                url=raw["url"],
                duration=raw["duration"],
                width=raw["width"],
                height=raw["height"],
                concept=query,
                keywords=[query],
                relevance_score=round(relevance, 3),
                novelty_score=round(novelty, 3),
                total_score=round(total, 3),
            )
            all_candidates.append(candidate)

    # Record used queries in JobContext
    if ctx is not None:
        for q in queries_to_run:
            ctx.used_broll_queries.add(q)

    # ── 4. Sort by total_score descending ─────────────────────────────────────
    all_candidates.sort(key=lambda c: c.total_score, reverse=True)

    # Randomized selection: randomly sample from top N candidates for variety
    # instead of always picking the top result
    chosen: List[BrollCandidate] = []
    _pool = all_candidates[:_RANDOM_SAMPLE_TOP_N]
    random.shuffle(_pool)
    for c in _pool:
        if used_asset_ids is not None and c.video_id in used_asset_ids:
            continue
        if ctx is not None and c.video_id in ctx.used_asset_ids:
            continue
        chosen.append(c)
        if used_asset_ids is not None:
            used_asset_ids.add(c.video_id)
        if ctx is not None:
            ctx.used_asset_ids.add(c.video_id)
        if len(chosen) >= max_results:
            break

    # ── 4b. Fallback query: if fewer than FALLBACK_MIN_ASSETS unique unused
    # assets found, broaden the query to a single generic word from the
    # segment topic and retry once with page=1.
    if len(chosen) < _FALLBACK_MIN_ASSETS and all_keywords:
        # For insurance content, use insurance-native fallback instead of generic
        _is_insurance_fb = _is_insurance_content(segment_transcript)
        if _is_insurance_fb:
            _fallback_word = "insurance policy"
            logger.info(
                "[BrollRec] ⛔ Only %d assets found for insurance content — "
                "blocking generic fallback. Using insurance-native fallback '%s' (page=1) "
                "instead of generic keyword.",
                len(chosen), _fallback_word,
            )
        else:
            _fallback_word = all_keywords[0] if all_keywords else "nature"
            logger.info(
                "[BrollRec] Only %d assets found — broadening fallback query '%s' (page=1)",
                len(chosen), _fallback_word,
            )
        _fb_results = await _search_pexels_for_keywords([_fallback_word], pexels_key, page=1)
        for raw in _fb_results:
            vid = raw["video_id"]
            if vid in seen_video_ids:
                continue
            seen_video_ids.add(vid)
            if used_asset_ids is not None and vid in used_asset_ids:
                continue
            if ctx is not None and vid in ctx.used_asset_ids:
                continue
            if raw.get("url") and raw["url"] in used_broll_urls:
                continue
            candidate = BrollCandidate(
                video_id=vid,
                url=raw["url"],
                duration=raw["duration"],
                width=raw["width"],
                height=raw["height"],
                concept=_fallback_word,
                keywords=[_fallback_word],
                relevance_score=0.5,
                novelty_score=1.0,
                total_score=0.5,
            )
            chosen.append(candidate)
            if used_asset_ids is not None:
                used_asset_ids.add(vid)
            if ctx is not None:
                ctx.used_asset_ids.add(vid)
            if len(chosen) >= max_results:
                break


    # ── 5. Post-filter: enforce hard limits (rules 3, 4, 5) ──────────────────
    # Run BEFORE _update_ctx() so that filtered-out assets are never marked as used.
    chosen = _post_filter_broll_candidates(chosen, clip_duration)

    # ── 6. Update task_ctx ────────────────────────────────────────────────────
    # Only mark surviving candidates as used — assets filtered out by post-filter
    # (e.g. too short, clip too short for broll) are never inserted, so they
    # should NOT be added to used_broll_ids.
    chosen_ids = [c.video_id for c in chosen]

    async def _update_ctx():
        nonlocal used_broll_ids
        for c in chosen:
            used_broll_ids.add(c.video_id)
            if c.url:
                used_broll_urls.add(c.url)
        task_ctx["segment_broll_map"].setdefault(segment_id, []).extend(chosen_ids)


    if lock is not None:
        async with lock:
            await _update_ctx()
    else:
        await _update_ctx()

    # ── 7. Logging ────────────────────────────────────────────────────────────
    chosen_log = [
        f"id={c.video_id},score={c.total_score:.2f}(rel={c.relevance_score:.2f}+nov={c.novelty_score:.2f})"
        for c in chosen
    ]
    rejected_log = [
        f"id={c.video_id},score={c.total_score:.2f}"
        for c in all_candidates[max_results:]
    ]
    logger.info(
        "[BrollRec] segment=%s, keywords=%s, chosen=[%s], rejected=[%s]",
        segment_id,
        [c.concept for c in concepts],
        ", ".join(chosen_log),
        ", ".join(rejected_log[:10]),  # limit rejected log length
    )

    return chosen




# ── Convenience: build a fresh task_ctx ────────────────────────────────────────

def make_task_ctx(lock: Optional[asyncio.Lock] = None) -> Dict[str, Any]:
    """
    Create a fresh task_ctx dict for use with recommend_brolls.

    Args:
        lock: Optional asyncio.Lock for thread-safe access across concurrent clips.

    Returns:
        Dict with keys: used_broll_ids (set), segment_broll_map (dict), lock (optional).
    """
    ctx: Dict[str, Any] = {
        "used_broll_ids": set(),
        "segment_broll_map": {},
    }
    if lock is not None:
        ctx["lock"] = lock
    return ctx
