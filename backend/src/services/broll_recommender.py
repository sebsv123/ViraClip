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
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set

import httpx

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
_BROLL_REC_DEFAULT_MAX = 5
_LLM_TIMEOUT = 15.0
_PEXELS_TIMEOUT = 15.0
_PEXELS_PER_PAGE = 8
_RELEVANCE_WEIGHT = 0.7
_NOVELTY_WEIGHT = 0.3
_MAX_TRANSCRIPT_WORDS = 150
_MAX_CONCEPTS = 4
_MAX_KEYWORDS_PER_CONCEPT = 3

# ── Data types ─────────────────────────────────────────────────────────────────

@dataclass
class VisualConcept:
    """A visual concept extracted from the transcript, with search keywords."""
    concept: str
    keywords: List[str]

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

_LLM_CONCEPT_PROMPT = """You are a video editor selecting B-roll footage for a video segment.
Read the transcript and extract up to {max_concepts} VISUAL CONCEPTS that could be illustrated with stock footage.

For each concept, provide 2-3 specific English keywords that would return good results on Pexels stock video.

Rules:
- Concepts must be VISUAL and CONCRETE (things you can see on camera)
- Keywords must be searchable on Pexels stock video site
- NO generic motivational words (success, winner, achievement, determination)
- Each keyword set should target a DIFFERENT visual angle of the concept
- Prefer nouns and actions over abstract ideas

Respond with ONLY valid JSON in this exact format:
{{
  "concepts": [
    {{"concept": "short description", "keywords": ["keyword1", "keyword2", "keyword3"]}},
    ...
  ]
}}

Transcript: {transcript}"""


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
                    concepts.append(VisualConcept(
                        concept=str(c["concept"]).strip(),
                        keywords=kw[:_MAX_KEYWORDS_PER_CONCEPT],
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
    """Simple fallback: extract noun-like words as concepts when LLM is unavailable."""
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
) -> List[Dict[str, Any]]:
    """Search Pexels videos for a set of keywords. Returns raw video results."""
    query = " ".join(keywords)
    try:
        async with httpx.AsyncClient(timeout=_PEXELS_TIMEOUT) as client:
            resp = await client.get(
                "https://api.pexels.com/videos/search",
                headers={"Authorization": pexels_key},
                params={
                    "query": query,
                    "per_page": per_page,
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


# ── Main recommender ───────────────────────────────────────────────────────────

async def recommend_brolls(
    segment_transcript: str,
    segment_id: str,
    task_ctx: Dict[str, Any],
    max_results: int = _BROLL_REC_DEFAULT_MAX,
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

    Returns:
        List of BrollCandidate sorted by total_score descending.

    The function updates task_ctx in-place:
        - Adds chosen video IDs to task_ctx["used_broll_ids"]
        - Appends chosen video IDs to task_ctx["segment_broll_map"][segment_id]
    """
    # ── 1. Ensure task_ctx has required keys ──────────────────────────────────
    if "used_broll_ids" not in task_ctx:
        task_ctx["used_broll_ids"] = set()
    if "segment_broll_map" not in task_ctx:
        task_ctx["segment_broll_map"] = {}

    used_broll_ids: Set[int] = task_ctx["used_broll_ids"]
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

    logger.info(
        "[BrollRec] segment=%s, concepts=%s",
        segment_id,
        [c.concept for c in concepts],
    )

    # ── 3. Search Pexels for each concept's keywords ──────────────────────────
    all_candidates: List[BrollCandidate] = []
    seen_video_ids: Set[int] = set()

    for concept in concepts:
        # Try each keyword set independently for variety
        for kw_set in concept.keywords:
            kw_list = [kw_set] if isinstance(kw_set, str) else kw_set
            if isinstance(kw_set, str):
                kw_list = [kw_set]
            else:
                kw_list = list(kw_set)

            raw_results = await _search_pexels_for_keywords(kw_list, pexels_key)

            for raw in raw_results:
                vid = raw["video_id"]
                if vid in seen_video_ids:
                    continue  # avoid duplicate candidates
                seen_video_ids.add(vid)

                relevance = _compute_relevance(kw_list, concept.keywords)
                novelty = _compute_novelty(vid, used_broll_ids)
                total = _RELEVANCE_WEIGHT * relevance + _NOVELTY_WEIGHT * novelty

                candidate = BrollCandidate(
                    video_id=vid,
                    url=raw["url"],
                    duration=raw["duration"],
                    width=raw["width"],
                    height=raw["height"],
                    concept=concept.concept,
                    keywords=concept.keywords,
                    relevance_score=round(relevance, 3),
                    novelty_score=round(novelty, 3),
                    total_score=round(total, 3),
                )
                all_candidates.append(candidate)

    # ── 4. Sort by total_score descending, take top-N ─────────────────────────
    all_candidates.sort(key=lambda c: c.total_score, reverse=True)
    chosen = all_candidates[:max_results]

    # ── 5. Update task_ctx ────────────────────────────────────────────────────
    chosen_ids = [c.video_id for c in chosen]
    rejected_ids = [c.video_id for c in all_candidates[max_results:]]

    async def _update_ctx():
        nonlocal used_broll_ids
        for c in chosen:
            used_broll_ids.add(c.video_id)
        task_ctx["segment_broll_map"].setdefault(segment_id, []).extend(chosen_ids)

    if lock is not None:
        async with lock:
            await _update_ctx()
    else:
        await _update_ctx()

    # ── 6. Logging ────────────────────────────────────────────────────────────
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
