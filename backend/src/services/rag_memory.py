"""
RAG Memory for ViraClip.

Persistent VectorStore (ChromaDB) that stores successful clip decisions.
Used by EditDecisionAgent to query historical creative decisions that worked.

Index schema per document:
  - text: "{mood} | {hook_text} | {transcript_excerpt}"  (what to embed)
  - metadata: {
        mood, hook_text, transcript_excerpt,
        edit_decisions (JSON str), audio_decisions (JSON str),
        quality_score (float), stored_at (ISO datetime), task_id
    }

Usage:
    from .rag_memory import store_successful_clip, query_clip_memory
"""
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CHROMA_PERSIST_DIR = os.environ.get("VIRACLIP_CHROMA_DIR", "./data/chroma_db")
_COLLECTION_NAME = "viraclip_successful_clips"
_MIN_QUALITY_SCORE = float(os.environ.get("RAG_MIN_QUALITY_SCORE", "6.5"))

# ── Singletons ────────────────────────────────────────────────────────────────
_chroma_client = None
_collection = None
_embed_model = None


def _get_embed_model():
    global _embed_model
    if _embed_model is not None:
        return _embed_model
    try:
        from fastembed import TextEmbedding
        _embed_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
        logger.info("[RAGMemory] Embedding model loaded")
        return _embed_model
    except ImportError:
        logger.error("[RAGMemory] fastembed not installed")
        raise


def _get_collection():
    global _chroma_client, _collection
    if _collection is not None:
        return _collection
    try:
        import chromadb
        os.makedirs(_CHROMA_PERSIST_DIR, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=_CHROMA_PERSIST_DIR)
        _collection = _chroma_client.get_or_create_collection(
            name=_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "[RAGMemory] ChromaDB collection ready: %s (%d docs)",
            _COLLECTION_NAME,
            _collection.count(),
        )
        return _collection
    except ImportError:
        logger.error("[RAGMemory] chromadb not installed — pip install chromadb")
        raise
    except Exception as e:
        logger.error("[RAGMemory] Failed to init ChromaDB: %s", e)
        raise


# ── Public API ────────────────────────────────────────────────────────────────

def store_successful_clip(
    task_id: str,
    mood: str,
    hook_text: str,
    transcript_excerpt: str,
    edit_decisions: Dict[str, Any],
    audio_decisions: Dict[str, Any],
    quality_score: float,
) -> bool:
    """
    Store a successful clip's creative decisions in the RAG memory.
    Only stores if quality_score >= _MIN_QUALITY_SCORE.
    Returns True if stored, False if skipped or failed.
    """
    if quality_score < _MIN_QUALITY_SCORE:
        logger.info(
            "[RAGMemory] Skipping storage — quality_score %.1f < %.1f",
            quality_score, _MIN_QUALITY_SCORE,
        )
        return False

    try:
        collection = _get_collection()
        embed_model = _get_embed_model()

        # Build the text to embed: mood + hook + transcript excerpt
        text_to_embed = f"{mood} | {hook_text[:200]} | {transcript_excerpt[:300]}"
        embedding = list(embed_model.embed([text_to_embed]))[0].tolist()

        doc_id = f"{task_id}_{int(datetime.now(timezone.utc).timestamp())}"

        collection.add(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[text_to_embed],
            metadatas=[{
                "task_id": task_id,
                "mood": mood,
                "hook_text": hook_text[:500],
                "transcript_excerpt": transcript_excerpt[:500],
                "edit_decisions": json.dumps(edit_decisions),
                "audio_decisions": json.dumps(audio_decisions),
                "quality_score": quality_score,
                "stored_at": datetime.now(timezone.utc).isoformat(),
            }],
        )
        logger.info(
            "[RAGMemory] Stored clip %s (mood=%s, score=%.1f) — total: %d",
            doc_id, mood, quality_score, collection.count(),
        )
        return True

    except Exception as e:
        logger.warning("[RAGMemory] Failed to store clip: %s", e)
        return False


def query_clip_memory(
    query_text: str,
    mood: Optional[str] = None,
    n_results: int = 3,
) -> List[Dict[str, Any]]:
    """
    Query the RAG memory for similar successful clips.

    Args:
        query_text: The transcript/hook text to search with
        mood: Optional filter by mood
        n_results: Number of results to return

    Returns:
        List of dicts with edit_decisions, audio_decisions, quality_score, hook_text
    """
    try:
        collection = _get_collection()
        if collection.count() == 0:
            logger.info("[RAGMemory] Empty collection — no historical data yet")
            return []

        embed_model = _get_embed_model()
        query_embedding = list(embed_model.embed([query_text]))[0].tolist()

        where_filter = {"mood": mood} if mood else None

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(n_results, collection.count()),
            where=where_filter,
            include=["metadatas", "distances", "documents"],
        )

        output = []
        for i, metadata in enumerate(results["metadatas"][0]):
            try:
                edit_dec = json.loads(metadata.get("edit_decisions", "{}"))
                audio_dec = json.loads(metadata.get("audio_decisions", "{}"))
            except (json.JSONDecodeError, TypeError):
                edit_dec = {}
                audio_dec = {}

            similarity = 1 - results["distances"][0][i]  # cosine: 1 - distance

            output.append({
                "similarity": round(similarity, 4),
                "mood": metadata.get("mood", "unknown"),
                "hook_text": metadata.get("hook_text", ""),
                "quality_score": metadata.get("quality_score", 0),
                "edit_decisions": edit_dec,
                "audio_decisions": audio_dec,
                "stored_at": metadata.get("stored_at", ""),
            })

        logger.info(
            "[RAGMemory] Query returned %d results for mood=%s",
            len(output), mood,
        )
        return output

    except Exception as e:
        logger.warning("[RAGMemory] Query failed: %s", e)
        return []


def get_memory_stats() -> Dict[str, Any]:
    """Return basic stats about the RAG memory (total docs, mood breakdown)."""
    try:
        collection = _get_collection()
        total = collection.count()
        if total == 0:
            return {"total_clips": 0, "mood_breakdown": {}}

        results = collection.get(include=["metadatas"])
        mood_counts: Dict[str, int] = {}
        scores = []
        for meta in results["metadatas"]:
            m = meta.get("mood", "unknown")
            mood_counts[m] = mood_counts.get(m, 0) + 1
            scores.append(meta.get("quality_score", 0))

        return {
            "total_clips": total,
            "mood_breakdown": mood_counts,
            "avg_quality_score": round(sum(scores) / len(scores), 2) if scores else 0,
        }
    except Exception as e:
        logger.warning("[RAGMemory] Stats failed: %s", e)
        return {"total_clips": 0, "mood_breakdown": {}, "error": str(e)}
