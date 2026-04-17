"""
CLAP SFX Service — Phase 2.5
==============================
Semantic sound-effect matching using CLAP (Contrastive Language-Audio Pretraining).
Replaces the hard-coded VIRAL_SOUND_MAP dict with nearest-neighbor search over
a local library of CC0 SFX files.

Architecture:
  Offline (build_cache):
    Local SFX files → CLAP audio encoder → L2-normalised embeddings → JSON cache

  Online (find_best_sfx):
    keyword string → CLAP text encoder → cosine similarity vs. cache → best SFX path

Model: laion/larger_clap_general (~900 MB, CPU-capable)
Fallback: keyword substring matching against filenames (zero-dep, no model needed)

References:
  https://github.com/LAION-AI/CLAP
  pip install msclap
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional, Dict, List
from functools import lru_cache

logger = logging.getLogger(__name__)

SFX_LIBRARY_PATH = Path(os.getenv("SFX_LIBRARY_PATH", "/app/assets/sounds"))
EMBEDDINGS_CACHE_FILE = SFX_LIBRARY_PATH / "embeddings_cache.json"

# Similarity threshold — below this we return None (no confident match)
MIN_SIMILARITY = 0.20

# ─────────────────────────────────────────────────────────────────────────────
#  CLAP model (lazy-loaded, cached)
# ─────────────────────────────────────────────────────────────────────────────

_clap_model = None
_clap_available: Optional[bool] = None


def _get_clap_model():
    """Lazy-load CLAP model. Returns None if msclap is not installed."""
    global _clap_model, _clap_available

    if _clap_available is not None:
        return _clap_model

    try:
        from msclap import CLAP
        _clap_model = CLAP(version="2023", use_cuda=False)
        _clap_available = True
        logger.info("[clap] CLAP model loaded (laion/larger_clap_general)")
    except ImportError:
        _clap_available = False
        logger.info("[clap] msclap not installed — using keyword fallback")
    except Exception as e:
        _clap_available = False
        logger.warning(f"[clap] Failed to load CLAP model: {e} — using keyword fallback")

    return _clap_model


# ─────────────────────────────────────────────────────────────────────────────
#  Embedding cache
# ─────────────────────────────────────────────────────────────────────────────

def _load_embeddings_cache() -> Dict[str, List[float]]:
    """Load pre-computed audio embeddings from JSON cache."""
    if not EMBEDDINGS_CACHE_FILE.exists():
        return {}
    try:
        return json.loads(EMBEDDINGS_CACHE_FILE.read_text())
    except Exception as e:
        logger.warning(f"[clap] Could not load embeddings cache: {e}")
        return {}


def _save_embeddings_cache(cache: Dict[str, List[float]]) -> None:
    EMBEDDINGS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    EMBEDDINGS_CACHE_FILE.write_text(json.dumps(cache, indent=2))
    logger.info(f"[clap] Saved embeddings cache ({len(cache)} entries)")


def build_cache(sfx_dir: Optional[Path] = None) -> int:
    """
    Pre-compute CLAP audio embeddings for all SFX files in the library.
    Run once after downloading new sounds (or call build_cache() from a script).

    Returns:
        Number of files successfully embedded.
    """
    sfx_dir = sfx_dir or SFX_LIBRARY_PATH
    model = _get_clap_model()
    if model is None:
        logger.warning("[clap] Cannot build cache — CLAP model unavailable")
        return 0

    sound_files = sorted(sfx_dir.glob("*.mp3")) + sorted(sfx_dir.glob("*.wav"))
    if not sound_files:
        logger.warning(f"[clap] No sound files found in {sfx_dir}")
        return 0

    cache = _load_embeddings_cache()
    new_count = 0

    for fp in sound_files:
        key = fp.name
        if key in cache:
            continue
        try:
            embeddings = model.get_audio_embeddings([str(fp)], resample=True)
            # embeddings is a tensor, shape (1, D) — convert to list
            vec = embeddings[0].tolist()
            cache[key] = vec
            new_count += 1
            logger.debug(f"[clap] Embedded: {key}")
        except Exception as e:
            logger.warning(f"[clap] Failed to embed {fp.name}: {e}")

    if new_count > 0:
        _save_embeddings_cache(cache)
        logger.info(f"[clap] Cache updated: {new_count} new embeddings ({len(cache)} total)")

    return new_count


# ─────────────────────────────────────────────────────────────────────────────
#  Main API: find_best_sfx
# ─────────────────────────────────────────────────────────────────────────────

def find_best_sfx(
    keyword: str,
    sfx_dir: Optional[Path] = None,
    top_k: int = 1,
) -> Optional[Path]:
    """
    Find the best matching SFX file for a transcript keyword using CLAP.
    Falls back to filename substring matching if CLAP is unavailable.

    Args:
        keyword:  Transcript keyword or phrase to match (e.g. "whoosh", "explosion")
        sfx_dir:  Override SFX library directory
        top_k:    Return best match (top_k=1) — reserved for future ranked results

    Returns:
        Path to best matching SFX file, or None if no confident match.

    Example:
        path = find_best_sfx("dramatic reveal")
        # → /app/assets/sfx_library/tension_riser_02_539239.mp3
    """
    sfx_dir = sfx_dir or SFX_LIBRARY_PATH
    model = _get_clap_model()

    if model is not None:
        return _find_by_clap(keyword, sfx_dir, model)
    else:
        return _find_by_filename(keyword, sfx_dir)


def find_best_sfx_batch(
    keywords: List[str],
    sfx_dir: Optional[Path] = None,
) -> Dict[str, Optional[Path]]:
    """
    Find best SFX for each keyword in a batch (more efficient with CLAP).

    Returns:
        Dict mapping keyword → best SFX path (or None)
    """
    sfx_dir = sfx_dir or SFX_LIBRARY_PATH
    model = _get_clap_model()
    results: Dict[str, Optional[Path]] = {}

    if model is None:
        for kw in keywords:
            results[kw] = _find_by_filename(kw, sfx_dir)
        return results

    # Batch CLAP text embeddings for efficiency
    try:
        import numpy as np

        text_embeddings = model.get_text_embeddings(keywords)  # (N, D) tensor
        cache = _load_embeddings_cache()

        if not cache:
            for kw in keywords:
                results[kw] = _find_by_filename(kw, sfx_dir)
            return results

        sfx_names = list(cache.keys())
        sfx_vecs = np.array([cache[n] for n in sfx_names], dtype=np.float32)
        # L2 normalise
        sfx_norms = np.linalg.norm(sfx_vecs, axis=1, keepdims=True)
        sfx_vecs = sfx_vecs / np.where(sfx_norms > 0, sfx_norms, 1)

        for i, kw in enumerate(keywords):
            text_vec = text_embeddings[i].numpy().astype(np.float32)
            norm = np.linalg.norm(text_vec)
            if norm > 0:
                text_vec /= norm
            sims = sfx_vecs @ text_vec
            best_idx = int(sims.argmax())
            best_sim = float(sims[best_idx])

            if best_sim >= MIN_SIMILARITY:
                path = sfx_dir / sfx_names[best_idx]
                results[kw] = path if path.exists() else None
            else:
                results[kw] = _find_by_filename(kw, sfx_dir)

    except Exception as e:
        logger.warning(f"[clap] Batch match failed: {e} — using keyword fallback")
        for kw in keywords:
            results[kw] = _find_by_filename(kw, sfx_dir)

    return results


# ─────────────────────────────────────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _find_by_clap(keyword: str, sfx_dir: Path, model) -> Optional[Path]:
    """Cosine similarity between CLAP text embedding and pre-computed audio embeddings."""
    try:
        import numpy as np

        cache = _load_embeddings_cache()
        if not cache:
            logger.debug("[clap] Cache empty — rebuilding...")
            build_cache(sfx_dir)
            cache = _load_embeddings_cache()
            if not cache:
                return _find_by_filename(keyword, sfx_dir)

        # Text embedding for the keyword
        text_emb = model.get_text_embeddings([keyword])[0].numpy().astype(np.float32)
        norm = np.linalg.norm(text_emb)
        if norm > 0:
            text_emb /= norm

        sfx_names = list(cache.keys())
        sfx_vecs = np.array([cache[n] for n in sfx_names], dtype=np.float32)
        sfx_norms = np.linalg.norm(sfx_vecs, axis=1, keepdims=True)
        sfx_vecs /= np.where(sfx_norms > 0, sfx_norms, 1)

        sims = sfx_vecs @ text_emb
        best_idx = int(sims.argmax())
        best_sim = float(sims[best_idx])

        logger.debug(
            f"[clap] '{keyword}' → {sfx_names[best_idx]} (sim={best_sim:.3f})"
        )

        if best_sim >= MIN_SIMILARITY:
            path = sfx_dir / sfx_names[best_idx]
            return path if path.exists() else None

    except Exception as e:
        logger.warning(f"[clap] CLAP match failed for '{keyword}': {e}")

    return _find_by_filename(keyword, sfx_dir)


# Keyword → filename fragment synonyms for fallback matching
_KEYWORD_SYNONYMS: Dict[str, List[str]] = {
    "whoosh": ["whoosh", "swipe", "swoosh", "fast"],
    "impact": ["impact", "hit", "punch", "boom", "bass"],
    "tension": ["tension", "riser", "build", "rise"],
    "chime": ["chime", "ding", "bell", "notify"],
    "glitch": ["glitch", "distort", "error", "digital"],
    "dramatic": ["dramatic", "bass_boom", "boom"],
    "transition": ["whoosh", "swipe"],
    "emphasis": ["punch", "hit", "impact"],
    "reveal": ["chime", "ding", "tension"],
    "scroll_stop": ["whoosh_heavy", "bass", "impact"],
}


def _find_by_filename(keyword: str, sfx_dir: Path) -> Optional[Path]:
    """Keyword substring match against SFX filenames (CPU-only fallback)."""
    if not sfx_dir.exists():
        return None

    sound_files = list(sfx_dir.glob("*.mp3")) + list(sfx_dir.glob("*.wav"))
    if not sound_files:
        return None

    keyword_lower = keyword.lower()

    # Direct substring match
    for fp in sound_files:
        if keyword_lower in fp.stem.lower():
            logger.debug(f"[clap/fallback] '{keyword}' → {fp.name} (direct match)")
            return fp

    # Synonym match
    synonyms = _KEYWORD_SYNONYMS.get(keyword_lower, [])
    for syn in synonyms:
        for fp in sound_files:
            if syn in fp.stem.lower():
                logger.debug(f"[clap/fallback] '{keyword}' → {fp.name} (via synonym '{syn}')")
                return fp

    # Return first available if nothing matches
    logger.debug(f"[clap/fallback] No match for '{keyword}' — returning first available")
    return sound_files[0] if sound_files else None


# ─────────────────────────────────────────────────────────────────────────────
#  Library stats
# ─────────────────────────────────────────────────────────────────────────────

def get_library_stats(sfx_dir: Optional[Path] = None) -> dict:
    """Return statistics about the local SFX library."""
    sfx_dir = sfx_dir or SFX_LIBRARY_PATH
    sounds = list(sfx_dir.glob("*.mp3")) + list(sfx_dir.glob("*.wav"))
    cache = _load_embeddings_cache()

    return {
        "sfx_dir": str(sfx_dir),
        "total_files": len(sounds),
        "total_size_mb": sum(f.stat().st_size for f in sounds) // (1024 * 1024),
        "cached_embeddings": len(cache),
        "clap_available": _clap_available,
        "cache_coverage": (
            f"{len(cache)}/{len(sounds)}"
            if sounds else "0/0"
        ),
    }
