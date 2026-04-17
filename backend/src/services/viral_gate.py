"""
Gate 1 — Viral Viability Filter with FAISS.

Runs AFTER Whisper transcription, BEFORE Groq/LLM analysis.
Embeds each transcribed segment with fastembed (BAAI/bge-small-en-v1.5),
builds a FAISS IndexFlatIP index, and scores segments against curated
high-engagement patterns. Keyword and emotional scores are computed by a
multilingüe zero-shot classifier (mDeBERTa-v3-base-mnli).
If no segment exceeds the configurable threshold the pipeline is cancelled
early — saving Groq tokens and GPU time.

Environment variables:
    VIRAL_GATE_THRESHOLD  – minimum cosine similarity score to pass (default 0.65)
    VIRAL_GATE_MODEL      – fastembed model name (default BAAI/bge-small-en-v1.5)
"""

import logging
import os
import re
from typing import Any, Dict, List, Optional

import numpy as np
from transformers import pipeline as hf_pipeline

logger = logging.getLogger(__name__)

# ─── Configurable threshold ─────────────────────────────────────────────────
_DEFAULT_THRESHOLD = 0.60
_ENV_THRESHOLD = "VIRAL_GATE_THRESHOLD"
_ENV_MODEL = "VIRAL_GATE_MODEL"
_DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"

# ─── High-engagement reference patterns ─────────────────────────────────────
# Each pattern is a short text that represents a known engagement trigger.
# The model computes cosine similarity between segment embeddings and these
# reference embeddings; the max similarity becomes the "viral affinity" score.

HOOK_PATTERNS: List[str] = [
    # Curiosity gaps
    "What nobody tells you about this",
    "The secret they don't want you to know",
    "Here's why everyone is wrong about",
    "You won't believe what happens next",
    "This changes everything you thought you knew",
    # Storytelling triggers
    "Let me tell you a story that changed my life",
    "I almost gave up until this happened",
    "The moment everything clicked for me",
    "Three years ago I made a decision that",
    # Authority / expertise
    "As someone who has spent 10 years doing this",
    "After analyzing hundreds of cases",
    "The data shows something surprising",
    "Scientists just discovered that",
    # Emotional peaks
    "This is the most important thing I've ever said",
    "I can't stop thinking about this",
    "This brought me to tears",
    "The most powerful lesson I've learned",
    # Controversy / debate
    "Unpopular opinion but hear me out",
    "Everyone is doing this wrong",
    "Stop doing this immediately",
    "This is a scam and here's proof",
    # Call to action / urgency
    "Watch this before it gets taken down",
    "Save this for later you'll need it",
    "If you only learn one thing today make it this",
    "This hack saves me hours every week",
]

EMOTIONAL_PATTERNS: List[str] = [
    "incredible transformation results",
    "heartbreaking moment of truth",
    "unbelievable plot twist nobody expected",
    "raw honest vulnerable confession",
    "explosive confrontation caught on camera",
    "mind blowing revelation shocked everyone",
    "inspiring comeback against all odds",
    "hilarious unexpected punchline",
]

# ─── Module-level singletons (lazy init) ────────────────────────────────────
_embedder = None
_classifier = None
_reference_embeddings: Optional[np.ndarray] = None
_reference_labels: Optional[List[str]] = None


def _get_classifier():
    """Lazy-load zero-shot classification model (mDeBERTa-v3-base-mnli on CPU)."""
    global _classifier
    if _classifier is not None:
        return _classifier
    try:
        _classifier = hf_pipeline(
            "text-classification",
            model="pysentimiento/robertuito-sentiment-analysis",
            device=-1,  # CPU; cambiar a 0 si hay GPU
        )
        logger.info("[ViralGate] Classifier loaded (robertuito-sentiment-analysis)")
        return _classifier
    except Exception as e:
        logger.error(f"[ViralGate] Failed to load zero-shot classifier: {e}")
        raise


def _get_viral_scores(text: str) -> Dict[str, float]:
    """Score text using zero-shot classification instead of heuristic keyword/emotional checks."""
    classifier = _get_classifier()
    result = classifier(text)[0]
    label = result["label"]   # "POS", "NEG", "NEU"
    score = result["score"]

    if label == "NEG":
        emotional_score = score
        keyword_score = score * 0.8
    elif label == "POS":
        emotional_score = score * 0.7
        keyword_score = score * 0.5
    else:  # NEU
        emotional_score = max(0.0, (1 - score) * 0.3)
        keyword_score = 0.0

    return {
        "keyword_score": round(keyword_score, 4),
        "emotional_score": round(emotional_score, 4),
    }


def _get_embedder():
    """Lazy-load fastembed model (downloads on first use)."""
    global _embedder
    if _embedder is not None:
        return _embedder
    try:
        from fastembed import TextEmbedding
        model_name = os.environ.get(_ENV_MODEL, _DEFAULT_MODEL)
        logger.info(f"[ViralGate] Loading embedding model: {model_name}")
        _embedder = TextEmbedding(model_name=model_name)
        logger.info(f"[ViralGate] Embedding model loaded ({model_name})")
        return _embedder
    except ImportError:
        logger.error("[ViralGate] fastembed not installed")
        raise
    except Exception as e:
        logger.error(f"[ViralGate] Failed to load embedding model: {e}")
        raise


def _get_reference_embeddings() -> tuple[np.ndarray, List[str]]:
    """Build and cache normalized reference embeddings from patterns."""
    global _reference_embeddings, _reference_labels
    if _reference_embeddings is not None and _reference_labels is not None:
        return _reference_embeddings, _reference_labels

    try:
        import faiss
    except ImportError:
        logger.error("[ViralGate] faiss not installed — pip install faiss-cpu")
        raise

    embedder = _get_embedder()
    all_patterns = HOOK_PATTERNS + EMOTIONAL_PATTERNS
    labels = (["hook"] * len(HOOK_PATTERNS)) + (["emotional"] * len(EMOTIONAL_PATTERNS))

    vecs = np.array(list(embedder.embed(all_patterns)), dtype=np.float32)
    faiss.normalize_L2(vecs)

    _reference_embeddings = vecs
    _reference_labels = labels
    logger.info(
        f"[ViralGate] Reference index built: {len(all_patterns)} patterns "
        f"(dim={vecs.shape[1]})"
    )
    return _reference_embeddings, _reference_labels


# ─── Scoring helpers ────────────────────────────────────────────────────────

def _score_segment(
    text: str,
    embedding: np.ndarray,
    ref_embeddings: np.ndarray,
    ref_labels: List[str],
) -> Dict[str, Any]:
    """
    Score a single segment against reference patterns.

    Returns dict with:
        semantic_score: max cosine similarity to any reference pattern (0..1)
        keyword_score:  CTR keyword density (0..1)
        emotional_score: emotional density heuristic (0..1)
        composite_score: weighted combination (0..1)
        best_match_type: "hook" or "emotional"
    """
    try:
        import faiss
    except ImportError:
        return {
            "semantic_score": 0.0,
            "keyword_score": 0.0,
            "emotional_score": 0.0,
            "composite_score": 0.0,
            "best_match_type": "unknown",
        }

    # Build temp FAISS index for this query
    dim = ref_embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(ref_embeddings)

    query = embedding.reshape(1, -1).astype(np.float32)
    faiss.normalize_L2(query)

    k = min(5, ref_embeddings.shape[0])
    distances, indices = index.search(query, k)

    # distances are inner products (cosine similarity for normalized vectors)
    top_score = float(distances[0][0])
    best_idx = int(indices[0][0])
    best_match_type = ref_labels[best_idx] if best_idx < len(ref_labels) else "unknown"

    # Average of top-k for robustness
    avg_top_k = float(np.mean(distances[0][:k]))

    semantic_score = 0.6 * top_score + 0.4 * avg_top_k

    viral_scores = _get_viral_scores(text)
    keyword_score = viral_scores["keyword_score"]
    emotional_score = viral_scores["emotional_score"]

    # Weighted composite: semantic similarity is the strongest signal
    composite = (
        0.35 * semantic_score
        + 0.30 * keyword_score
        + 0.35 * emotional_score
    )

    return {
        "semantic_score": round(semantic_score, 4),
        "keyword_score": round(keyword_score, 4),
        "emotional_score": round(emotional_score, 4),
        "composite_score": round(composite, 4),
        "best_match_type": best_match_type,
    }


# ─── Diagnosis helpers ──────────────────────────────────────────────────────

def _diagnose_failure(scores: List[Dict[str, Any]]) -> tuple[str, str]:
    """
    Analyze why no segment passed the gate.
    Returns (reason, recommendation).
    """
    if not scores:
        return (
            "No transcribed segments to analyze",
            "Ensure the video has audible speech and Whisper produced segments",
        )

    avg_semantic = np.mean([s["semantic_score"] for s in scores])
    avg_keyword = np.mean([s["keyword_score"] for s in scores])
    avg_emotional = np.mean([s["emotional_score"] for s in scores])
    best_composite = max(s["composite_score"] for s in scores)

    reasons = []
    recommendations = []

    if avg_semantic < 0.35:
        reasons.append("content lacks recognizable engagement hooks")
        recommendations.append(
            "Add curiosity gaps, storytelling triggers, or authority statements"
        )

    if avg_keyword < 0.10:
        reasons.append("no high-CTR keywords detected")
        recommendations.append(
            "Include words like 'secret', 'hack', 'truth', 'mistake', 'proven'"
        )

    if avg_emotional < 0.05:
        reasons.append("flat emotional tone (no emphasis, no urgency)")
        recommendations.append(
            "Add emotional peaks: rhetorical questions, exclamations, personal stories"
        )

    if best_composite > 0.50:
        reasons.append(
            f"best segment scored {best_composite:.2f} — close but below threshold"
        )
        recommendations.append(
            "The content has potential; try a shorter video or stronger opening hook"
        )

    reason = "; ".join(reasons) if reasons else "Content is too generic for viral clips"
    recommendation = ". ".join(recommendations) if recommendations else (
        "Try content with stronger hooks, emotional peaks, or controversial takes"
    )

    return reason, recommendation


# ─── Transcript parsing ─────────────────────────────────────────────────────

_TIMESTAMP_RE = re.compile(
    r"\[(\d{2}:\d{2}:\d{2}\.\d+)\s*-\s*(\d{2}:\d{2}:\d{2}\.\d+)\]\s*(.*)"
)


def _ts_to_seconds(ts: str) -> float:
    """Convert 'HH:MM:SS.ms' to seconds."""
    parts = ts.split(":")
    if len(parts) == 3:
        h, m, rest = parts
        s = rest.split(".")[0]
        ms = rest.split(".")[1] if "." in rest else "0"
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / (10 ** len(ms))
    return 0.0


def parse_transcript_to_segments(transcript: str) -> List[Dict[str, Any]]:
    """
    Parse a Whisper-formatted transcript string into segment dicts.

    Input format (one per line):
        [00:00:01.000 - 00:00:05.000] Some text here

    Returns:
        List of {"text": str, "start": float, "end": float}
    """
    segments = []
    for line in transcript.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        m = _TIMESTAMP_RE.match(line)
        if m:
            start = _ts_to_seconds(m.group(1))
            end = _ts_to_seconds(m.group(2))
            text = m.group(3).strip()
            if text:
                segments.append({"text": text, "start": start, "end": end})
        elif line:
            # Line without timestamps — treat as single segment
            segments.append({"text": line, "start": 0.0, "end": 0.0})
    return segments


# ─── Public API ─────────────────────────────────────────────────────────────

def check_viral_gate_from_transcript(
    transcript: str,
    threshold: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Convenience wrapper: parse a Whisper-formatted transcript string, then
    run check_viral_gate on the resulting segments.
    """
    segments = parse_transcript_to_segments(transcript)
    if not segments:
        logger.warning("[ViralGate] Transcript parsed to 0 segments")
        return {
            "passed": False,
            "reason": "Transcript is empty or could not be parsed into segments",
            "best_score": 0.0,
            "recommendation": "Ensure the video has audible speech",
            "scores": [],
        }
    logger.info(f"[ViralGate] Parsed transcript into {len(segments)} segments")
    return check_viral_gate(segments, threshold=threshold)


def check_viral_gate(
    segments: List[Dict[str, Any]],
    threshold: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Gate 1: Viral viability check using FAISS semantic similarity.

    Args:
        segments: List of dicts with at least 'text', 'start', 'end'.
        threshold: Minimum composite score to pass (default from env or 0.65).

    Returns:
        On pass:
            {"passed": True, "viable_segments": [...], "scores": [...]}
        On fail:
            {"passed": False, "reason": str, "best_score": float,
             "recommendation": str, "scores": [...]}
    """
    if threshold is None:
        threshold = float(os.environ.get(_ENV_THRESHOLD, str(_DEFAULT_THRESHOLD)))

    logger.info(
        f"[ViralGate] Checking {len(segments)} segments (threshold={threshold:.2f})"
    )

    # ── Graceful fallback if FAISS or sentence-transformers are unavailable ──
    try:
        ref_embeddings, ref_labels = _get_reference_embeddings()
        embedder = _get_embedder()
    except Exception as e:
        logger.warning(
            f"[ViralGate] FAISS/embedder unavailable ({e}). "
            "Letting pipeline continue (fallback pass)."
        )
        return {
            "passed": True,
            "viable_segments": segments,
            "scores": [],
            "fallback": True,
            "fallback_reason": str(e),
        }

    # ── Extract texts and embed ──────────────────────────────────────────────
    texts = [
        (seg.get("text") or "").strip()
        for seg in segments
    ]
    non_empty_mask = [bool(t) for t in texts]

    if not any(non_empty_mask):
        logger.warning("[ViralGate] All segments have empty text — failing gate")
        return {
            "passed": False,
            "reason": "All transcribed segments are empty (no speech detected)",
            "best_score": 0.0,
            "recommendation": "Check that the video has audible speech",
            "scores": [],
        }

    # Encode only non-empty segments
    non_empty_texts = [t for t, m in zip(texts, non_empty_mask) if m]
    embeddings = np.array(list(embedder.embed(non_empty_texts)), dtype=np.float32)

    import faiss
    faiss.normalize_L2(embeddings)

    # ── Score each segment ───────────────────────────────────────────────────
    all_scores: List[Dict[str, Any]] = []
    emb_idx = 0
    for i, seg in enumerate(segments):
        if not non_empty_mask[i]:
            all_scores.append({
                "segment_index": i,
                "text": "",
                "semantic_score": 0.0,
                "keyword_score": 0.0,
                "emotional_score": 0.0,
                "composite_score": 0.0,
                "best_match_type": "empty",
            })
            continue

        score_info = _score_segment(
            text=texts[i],
            embedding=embeddings[emb_idx],
            ref_embeddings=ref_embeddings,
            ref_labels=ref_labels,
        )
        score_info["segment_index"] = i
        score_info["text"] = texts[i][:120]
        all_scores.append(score_info)
        emb_idx += 1

    # ── Determine pass/fail ──────────────────────────────────────────────────
    viable = [
        (segments[s["segment_index"]], s)
        for s in all_scores
        if s["composite_score"] >= threshold
    ]

    best_score = max(s["composite_score"] for s in all_scores) if all_scores else 0.0

    # Always log top score
    logger.info(f"[ViralGate] Best composite score: {best_score:.4f} (threshold={threshold:.2f})")

    # ── Quality tier ──────────────────────────────────────────────────────────
    if best_score >= 0.75:
        quality_tier = "strong hook"
    elif best_score >= 0.60:
        quality_tier = "decent hook"
    else:
        quality_tier = "needs work"

    if viable:
        viable_segments = [seg for seg, _ in viable]
        logger.info(
            f"[ViralGate] ✅ PASSED — {len(viable)}/{len(segments)} segments "
            f"above threshold (best={best_score:.4f}, tier={quality_tier})"
        )
        for seg, sc in viable[:5]:
            logger.info(
                f"  #{sc['segment_index']} score={sc['composite_score']:.3f} "
                f"({sc['best_match_type']}) \"{sc['text'][:60]}...\""
            )
        return {
            "passed": True,
            "viable_segments": viable_segments,
            "best_score": best_score,
            "quality_tier": quality_tier,
            "scores": all_scores,
        }

    # ── Failed: diagnose why ─────────────────────────────────────────────────
    reason, recommendation = _diagnose_failure(all_scores)
    logger.warning(
        f"[ViralGate] ❌ FAILED — best score {best_score:.4f} < {threshold:.2f}. "
        f"Reason: {reason}"
    )
    return {
        "passed": False,
        "reason": reason,
        "best_score": best_score,
        "quality_tier": quality_tier,
        "recommendation": recommendation,
        "scores": all_scores,
    }
