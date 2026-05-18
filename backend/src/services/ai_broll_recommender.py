"""
AiBrollRecommender — AI-powered B-roll suggestion engine.

Inspired by the AI-Broll project (https://github.com/Anil-matcha/AI-B-roll)
by Anil Matcha (MIT license).

Pipeline:
  1. Receives a transcript segment.
  2. Uses an LLM (Groq/OpenAI) to extract visual keywords per segment,
     following the AI-Broll approach: transcript → keyword → Pexels search.
  3. If LLM is unavailable, falls back to TF-IDF keyword extraction.
  4. Returns a list of BrollCandidate with keywords, shot type, preferred duration.
  5. Integrates with task_ctx for diversity (penalizes repeated concepts/topics).

No external Vadoo API dependency — only internal LLM + transcript.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from collections import Counter
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)
from src.services.metrics_aggregator import record_event

# ── Constants ──────────────────────────────────────────────────────────────────
_LLM_TIMEOUT = 20.0
_MAX_SEGMENT_WORDS = 200
_MAX_KEYWORDS_PER_SEGMENT = 3
_DEFAULT_DURATION_S = 4.5
_TFIDF_FALLBACK_TOP_K = 5

# ── Data types ─────────────────────────────────────────────────────────────────

@dataclass
class BrollCandidate:
    """A B-roll suggestion for a transcript segment."""
    keywords: List[str]
    tipo_plano: str = "medium"          # "wide", "medium", "closeup"
    prefered_duration_s: float = _DEFAULT_DURATION_S
    mood: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    concept: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── LLM prompt (inspired by AI-Broll) ──────────────────────────────────────────

_AI_BROLL_PROMPT = """You are a video editor selecting B-roll footage for a video segment.
Read the transcript and extract up to {max_keywords} search keywords that would return
relevant stock footage on Pexels.

Rules:
- Keywords must be VISUAL and CONCRETE (things you can see on camera).
- Each keyword should target a DIFFERENT visual angle of the topic.
- Prefer nouns and actions over abstract ideas.
- Keywords must be in English for Pexels search compatibility.
- Suggest a shot type for each keyword: "wide", "medium", or "closeup".
- Optionally suggest a mood (e.g., "serious", "uplifting", "dramatic", "neutral").

Respond with ONLY valid JSON in this exact format:
{{
  "concept": "one-line summary of the visual theme",
  "suggestions": [
    {{"keyword": "keyword1", "shot_type": "medium", "mood": "neutral"}},
    {{"keyword": "keyword2", "shot_type": "wide", "mood": "uplifting"}}
  ]
}}

Transcript: {transcript}"""


# ── AiBrollRecommender ─────────────────────────────────────────────────────────

class AiBrollRecommender:
    """
    Recommends B-roll keywords for transcript segments using LLM + TF-IDF fallback.

    Supports optional feedback-based learning: when task_feedback is provided,
    B-roll concept types with historically low watch_pct are penalised, and
    those with high watch_pct are rewarded. This is a simple heuristic weighting
    — no complex model training required.

    Usage:
        recommender = AiBrollRecommender()
        candidates = await recommender.suggest_broll(
            transcript="...",
            segment_id="clip_0",
            task_ctx={"covered_topics": set(), "used_keywords": set()},
        )

        # With feedback-based weighting:
        recommender = AiBrollRecommender(
            task_feedback={
                "city_skyline": {"used": 12, "avg_watch_pct": 0.68},
                "office_meeting": {"used": 8, "avg_watch_pct": 0.54},
            },
        )
    """

    def __init__(
        self,
        llm_api_key: Optional[str] = None,
        llm_base_url: Optional[str] = None,
        llm_model: str = "llama-3.1-8b-instant",
        max_keywords: int = _MAX_KEYWORDS_PER_SEGMENT,
        task_feedback: Optional[Dict[str, Dict[str, float]]] = None,
    ):
        self.llm_api_key = llm_api_key if llm_api_key is not None else os.getenv("GROQ_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
        self.llm_base_url = llm_base_url or os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
        self.llm_model = llm_model
        self.max_keywords = max_keywords
        self.task_feedback = task_feedback or {}
        self._feedback_weights: Optional[Dict[str, float]] = None
        if self.task_feedback:
            self._feedback_weights = self._compute_feedback_weights()
            logger.info(
                "[AiBroll] Feedback-based weighting active: %d broll types, weights=%s",
                len(self.task_feedback),
                {k: round(v, 3) for k, v in self._feedback_weights.items()},
            )

    async def suggest_broll(
        self,
        transcript: str,
        segment_id: str,
        task_ctx: Optional[Dict[str, Any]] = None,
    ) -> List[BrollCandidate]:
        """
        Suggest B-roll candidates for a transcript segment.

        Args:
            transcript: The transcript text for this segment.
            segment_id: Unique identifier for the segment (e.g., "clip_0").
            task_ctx: Optional task-level context for diversity tracking.
                Expected keys:
                - "covered_topics": set[str] — topics already covered in this task.
                - "used_keywords": set[str] — keywords already used in this task.
                - "segment_count": int — total segments in the task (for duration scaling).

        Returns:
            List of BrollCandidate with keywords, shot type, and preferred duration.
        """
        if task_ctx is None:
            task_ctx = {}

        # Ensure diversity tracking keys exist
        if "covered_topics" not in task_ctx:
            task_ctx["covered_topics"] = set()
        if "used_keywords" not in task_ctx:
            task_ctx["used_keywords"] = set()

        covered_topics: Set[str] = task_ctx["covered_topics"]
        used_keywords: Set[str] = task_ctx["used_keywords"]

        # Truncate transcript to avoid token overflow
        words = transcript.split()
        if len(words) > _MAX_SEGMENT_WORDS:
            transcript = " ".join(words[:_MAX_SEGMENT_WORDS])

        # Step 1: Try LLM extraction
        candidates = await self._extract_via_llm(transcript)

        # Step 2: Fallback to TF-IDF if LLM fails
        if not candidates:
            logger.info("[AiBroll] segment=%s: LLM returned no candidates, using TF-IDF fallback", segment_id)
            candidates = self._fallback_tfidf(transcript)
            # [Metrics] broll_fallback
            record_event("broll_fallback", payload={"segment_id": segment_id, "engine": "tfidf"})
        else:
            # [Metrics] broll_ai_used
            record_event("broll_ai_used", payload={"segment_id": segment_id, "candidates": len(candidates)})

        # Step 3: Apply diversity penalty — filter out already-covered topics/keywords
        candidates = self._apply_diversity(candidates, covered_topics, used_keywords)

        # Step 3.5: Apply feedback-based weighting (re-rank based on historical performance)
        if self._feedback_weights:
            candidates = self._apply_feedback_weights(candidates)

        # Step 4: Compute preferred duration based on segment position
        segment_count = task_ctx.get("segment_count", 1)
        for cand in candidates:
            cand.prefered_duration_s = self._compute_duration(cand, segment_id, segment_count)

        # Step 5: Update task_ctx with new topics/keywords
        for cand in candidates:
            covered_topics.add(cand.concept.lower().strip() if cand.concept else "")
            for kw in cand.keywords:
                used_keywords.add(kw.lower().strip())

        logger.info(
            "[AiBroll] segment=%s: returning %d candidates: %s",
            segment_id,
            len(candidates),
            [c.keywords for c in candidates],
        )

        return candidates

    # ── LLM extraction ─────────────────────────────────────────────────────────

    async def _extract_via_llm(self, transcript: str) -> List[BrollCandidate]:
        """Call LLM to extract B-roll keywords from transcript."""
        if not self.llm_api_key:
            logger.debug("[AiBroll] No LLM API key configured, skipping LLM extraction")
            return []

        prompt = _AI_BROLL_PROMPT.format(
            max_keywords=self.max_keywords,
            transcript=transcript,
        )

        try:
            import httpx
            async with httpx.AsyncClient(timeout=_LLM_TIMEOUT) as client:
                resp = await client.post(
                    f"{self.llm_base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.llm_api_key}"},
                    json={
                        "model": self.llm_model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 300,
                        "temperature": 0.3,
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"].strip()

                # Parse JSON — handle markdown code fences
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()

                data = json.loads(content)
                concept = data.get("concept", "").strip()
                suggestions = data.get("suggestions", [])

                candidates: List[BrollCandidate] = []
                for s in suggestions[:self.max_keywords]:
                    kw = str(s.get("keyword", "")).strip()
                    if not kw:
                        continue
                    shot_type = str(s.get("shot_type", "medium")).strip().lower()
                    if shot_type not in ("wide", "medium", "closeup"):
                        shot_type = "medium"
                    mood = str(s.get("mood", "")).strip() or None
                    candidates.append(BrollCandidate(
                        keywords=[kw],
                        tipo_plano=shot_type,
                        mood=mood,
                        concept=concept,
                    ))

                if candidates:
                    logger.info(
                        "[AiBroll] LLM extracted concept='%s' with %d keywords",
                        concept, len(candidates),
                    )
                    return candidates

        except Exception as e:
            logger.warning("[AiBroll] LLM extraction failed: %s", e)

        return []

    # ── TF-IDF fallback ────────────────────────────────────────────────────────

    def _fallback_tfidf(self, transcript: str) -> List[BrollCandidate]:
        """
        Simple TF-IDF-like keyword extraction as fallback when LLM is unavailable.

        Extracts the most informative words from the transcript by:
        1. Tokenizing and removing stopwords.
        2. Scoring words by TF * IDF-like (where IDF is approximated by
           inverse frequency in the document itself).
        3. Returning top-K words as B-roll keywords.
        """
        # English stopwords
        _stopwords: Set[str] = {
            "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
            "of", "with", "by", "from", "up", "about", "into", "over", "after",
            "is", "are", "was", "were", "be", "been", "being", "have", "has",
            "had", "do", "does", "did", "will", "would", "could", "should",
            "may", "might", "shall", "can", "need", "dare", "ought", "used",
            "i", "you", "he", "she", "it", "we", "they", "me", "him", "her",
            "us", "them", "my", "your", "his", "its", "our", "their", "mine",
            "yours", "hers", "its", "ours", "theirs", "this", "that", "these",
            "those", "what", "which", "who", "whom", "whose", "why", "how",
            "not", "no", "nor", "so", "very", "just", "don", "doesn", "didn",
            "isn", "aren", "wasn", "weren", "hasn", "haven", "hadn", "won",
            "wouldn", "couldn", "shouldn", "mightn", "mustn", "also", "get",
            "got", "gotten", "like", "make", "made", "take", "took", "know",
            "think", "see", "want", "come", "go", "went", "say", "tell", "ask",
            "need", "feel", "try", "leave", "call", "let", "keep", "find",
            "give", "use", "put", "set", "mean", "seem", "help", "show",
            "hear", "play", "run", "move", "live", "believe", "hold", "bring",
            "happen", "write", "provide", "sit", "stand", "lose", "pay",
            "meet", "include", "continue", "set", "learn", "change", "lead",
            "understand", "watch", "follow", "stop", "create", "speak", "read",
            "allow", "add", "spend", "grow", "open", "walk", "win", "teach",
            "offer", "remember", "consider", "appear", "buy", "serve", "die",
            "send", "build", "stay", "fall", "cut", "reach", "kill", "raise",
            "remain", "produce", "less", "more", "much", "many", "some", "any",
            "each", "every", "both", "few", "several", "all", "no", "most",
            "enough", "own", "same", "such", "other", "another", "one", "two",
            "three", "first", "last", "next", "new", "old", "good", "bad",
            "big", "small", "long", "short", "high", "low", "great", "little",
            "right", "wrong", "important", "different", "large", "real",
            "sure", "able", "possible", "hard", "easy", "clear", "better",
            "best", "worst", "true", "false", "free", "full", "special",
            "clean", "strong", "simple", "certain", "early", "late", "fast",
            "slow", "hot", "cold", "warm", "cool", "dark", "bright", "deep",
            "wide", "narrow", "heavy", "light", "soft", "hard", "sweet",
            "bitter", "sharp", "dull", "rough", "smooth", "thin", "thick",
            "round", "flat", "dry", "wet", "clean", "dirty", "fresh", "stale",
            "whole", "half", "single", "double", "top", "bottom", "front",
            "back", "side", "left", "right", "middle", "center", "inside",
            "outside", "above", "below", "before", "after", "during", "since",
            "until", "while", "because", "although", "unless", "if", "when",
            "where", "whether", "than", "as", "though", "even", "still",
            "already", "yet", "once", "ever", "never", "always", "often",
            "sometimes", "usually", "well", "really", "actually", "probably",
            "maybe", "perhaps", "quite", "almost", "nearly", "hardly",
            "merely", "simply", "especially", "particularly", "specifically",
            "generally", "typically", "essentially", "basically", "exactly",
            "absolutely", "completely", "entirely", "totally", "fully",
            "partially", "largely", "mostly", "mainly", "primarily",
            "increasingly", "incredibly", "extremely", "highly", "deeply",
            "strongly", "closely", "directly", "immediately", "quickly",
            "slowly", "carefully", "easily", "simply", "finally", "eventually",
            "ultimately", "originally", "initially", "currently", "recently",
            "previously", "traditionally", "typically", "commonly", "widely",
            "well", "badly", "seriously", "significantly", "dramatically",
            "substantially", "slightly", "roughly", "approximately", "exactly",
            "precisely", "naturally", "obviously", "clearly", "apparently",
            "reportedly", "supposedly", "allegedly", "namely", "thus",
            "therefore", "however", "nevertheless", "nonetheless", "meanwhile",
            "furthermore", "moreover", "besides", "likewise", "similarly",
            "conversely", "instead", "otherwise", "rather", "indeed",
            "undoubtedly", "certainly", "surely", "definitely", "absolutely",
            "perhaps", "maybe", "hopefully", "luckily", "unfortunately",
            "thankfully", "regardless", "anyway", "anyhow", "somehow",
            "somewhat", "anywhere", "everywhere", "nowhere", "somewhere",
            "everything", "nothing", "anything", "something", "everyone",
            "noone", "anyone", "someone", "everybody", "nobody", "anybody",
            "somebody", "whatever", "whichever", "whoever", "whomever",
            "whenever", "wherever", "however", "whatever",
        }

        # Tokenize
        tokens = re.findall(r"[a-zA-Z]+", transcript.lower())
        tokens = [t for t in tokens if t not in _stopwords and len(t) > 2]

        if not tokens:
            return []

        # Term frequency
        tf = Counter(tokens)
        total_terms = len(tokens)

        # Approximate IDF: log(N / df) where N = total terms, df = term frequency
        # For a single document, we use a simple heuristic: less frequent = more informative
        max_tf = max(tf.values()) if tf else 1
        scored: List[Tuple[str, float]] = []
        for term, freq in tf.items():
            # TF: relative frequency
            tf_score = freq / total_terms
            # IDF-like: penalize very common terms, boost moderately rare ones
            idf_like = math.log((total_terms + 1) / (freq + 1)) + 1
            score = tf_score * idf_like
            scored.append((term, score))

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)

        # Take top-K
        top_keywords = [term for term, _ in scored[:_TFIDF_FALLBACK_TOP_K]]

        # Group into BrollCandidates (one per keyword, with generic concept)
        candidates: List[BrollCandidate] = []
        for kw in top_keywords:
            candidates.append(BrollCandidate(
                keywords=[kw],
                tipo_plano="medium",
                concept=f"visual representation of {kw}",
            ))

        logger.info(
            "[AiBroll] TF-IDF fallback extracted %d keywords: %s",
            len(candidates), top_keywords,
        )

        return candidates

    # ── Diversity ──────────────────────────────────────────────────────────────

    def _apply_diversity(
        self,
        candidates: List[BrollCandidate],
        covered_topics: Set[str],
        used_keywords: Set[str],
    ) -> List[BrollCandidate]:
        """
        Apply diversity penalty: filter out candidates whose concept or keywords
        overlap with already-covered topics/used keywords.

        If all candidates would be filtered, return the least-overlapping one
        to avoid returning empty results.
        """
        if not covered_topics and not used_keywords:
            return candidates

        scored: List[Tuple[BrollCandidate, float]] = []
        for cand in candidates:
            penalty = 0.0
            # Penalize if concept is already covered
            if cand.concept:
                concept_lower = cand.concept.lower().strip()
                for topic in covered_topics:
                    if topic and (topic in concept_lower or concept_lower in topic):
                        penalty += 1.0
                        break

            # Penalize if any keyword is already used
            for kw in cand.keywords:
                kw_lower = kw.lower().strip()
                if kw_lower in used_keywords:
                    penalty += 1.0

            # Penalize if keyword overlaps with any covered topic
            for kw in cand.keywords:
                kw_lower = kw.lower().strip()
                for topic in covered_topics:
                    if topic and (topic in kw_lower or kw_lower in topic):
                        penalty += 0.5
                        break

            scored.append((cand, penalty))

        # Sort by penalty ascending (least penalty first)
        scored.sort(key=lambda x: x[1])

        # Filter out candidates with penalty >= 1.0, but keep at least one
        filtered = [cand for cand, pen in scored if pen < 1.0]
        if not filtered and scored:
            # Keep the best (least penalized) candidate
            filtered = [scored[0][0]]
            logger.debug("[AiBroll] All candidates penalized, keeping best: %s", filtered[0].keywords)

        return filtered

    # ── Feedback-based weighting ───────────────────────────────────────────────

    def _compute_feedback_weights(self) -> Dict[str, float]:
        """
        Compute weight multipliers from historical feedback data.

        For each broll_type with avg_watch_pct:
        - watch_pct >= 0.65 (good retention): reward, weight = 1.0 + (watch_pct - 0.65) * 0.5
        - watch_pct < 0.50 (poor retention): penalty, weight = 1.0 - (0.50 - watch_pct) * 0.8
        - 0.50 <= watch_pct < 0.65: neutral, weight = 1.0

        Also considers "used" count: if used < 3, confidence is reduced (weight
        pulled closer to 1.0) to avoid overreacting to sparse data.
        """
        weights: Dict[str, float] = {}
        for broll_type, stats in self.task_feedback.items():
            watch_pct = stats.get("avg_watch_pct", 0.5)
            used = stats.get("used", 0)

            if watch_pct >= 0.65:
                weight = 1.0 + (watch_pct - 0.65) * 0.5
            elif watch_pct < 0.50:
                weight = 1.0 - (0.50 - watch_pct) * 0.8
            else:
                weight = 1.0

            # Reduce confidence for sparse data (fewer than 3 uses)
            if used < 3 and used > 0:
                confidence = used / 3.0
                weight = 1.0 + (weight - 1.0) * confidence

            weights[broll_type] = max(0.1, weight)  # floor at 0.1

        logger.debug("[AiBroll] Feedback weights computed: %s", weights)
        return weights

    def _apply_feedback_weights(
        self,
        candidates: List[BrollCandidate],
    ) -> List[BrollCandidate]:
        """
        Re-rank candidates using feedback-based weight multipliers.

        For each candidate, checks if any keyword matches a broll_type in
        _feedback_weights. If so, applies the weight multiplier to adjust
        the candidate's effective score. Candidates with higher weights
        (rewarded types) are promoted; those with lower weights (penalised)
        are demoted.

        Returns candidates sorted by adjusted score (descending).
        """
        if not self._feedback_weights:
            return candidates

        scored: List[Tuple[BrollCandidate, float]] = []
        for cand in candidates:
            # Compute base score from candidate's own attributes
            base_score = 1.0

            # Apply feedback weight if any keyword matches a known broll_type
            feedback_multiplier = 1.0
            for kw in cand.keywords:
                kw_lower = kw.lower().strip()
                if kw_lower in self._feedback_weights:
                    feedback_multiplier *= self._feedback_weights[kw_lower]

            # Also check concept match
            if cand.concept:
                concept_lower = cand.concept.lower().strip()
                if concept_lower in self._feedback_weights:
                    feedback_multiplier *= self._feedback_weights[concept_lower]

            adjusted_score = base_score * feedback_multiplier
            scored.append((cand, adjusted_score))

        # Sort by adjusted score descending (highest first)
        scored.sort(key=lambda x: x[1], reverse=True)

        reordered = [cand for cand, _ in scored]
        logger.debug(
            "[AiBroll] Feedback re-ranking: %s",
            [(c.keywords, round(s, 3)) for c, s in scored],
        )
        return reordered

    # ── Duration computation ───────────────────────────────────────────────────

    def _compute_duration(
        self,
        candidate: BrollCandidate,
        segment_id: str,
        segment_count: int,
    ) -> float:
        """
        Compute preferred duration based on shot type and segment position.

        - Closeups: shorter (2-3s)
        - Medium: default (3.5-4.5s)
        - Wide: longer (4-6s)
        - First/last segments get slightly longer durations.
        """
        base = _DEFAULT_DURATION_S

        if candidate.tipo_plano == "closeup":
            base = 3.0
        elif candidate.tipo_plano == "wide":
            base = 5.0

        # Extract segment index from segment_id (e.g., "clip_3" → 3)
        seg_idx = 0
        match = re.search(r"(\d+)", segment_id)
        if match:
            seg_idx = int(match.group(1))

        # First and last segments get +1s
        if seg_idx == 0 or seg_idx == segment_count - 1:
            base += 1.0

        return base


# ── Convenience factory ────────────────────────────────────────────────────────

def create_recommender(
    llm_api_key: Optional[str] = None,
    llm_base_url: Optional[str] = None,
    llm_model: str = "llama-3.1-8b-instant",
    max_keywords: int = _MAX_KEYWORDS_PER_SEGMENT,
) -> AiBrollRecommender:
    """Create an AiBrollRecommender with sensible defaults."""
    return AiBrollRecommender(
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        max_keywords=max_keywords,
    )


def make_task_ctx(
    covered_topics: Optional[Set[str]] = None,
    used_keywords: Optional[Set[str]] = None,
    segment_count: int = 1,
) -> Dict[str, Any]:
    """Create a fresh task_ctx dict for use with AiBrollRecommender."""
    return {
        "covered_topics": covered_topics or set(),
        "used_keywords": used_keywords or set(),
        "segment_count": segment_count,
    }
