"""
transition_selector — Intelligent transition selector for clip concatenation.

Provides a set of functions to select and apply transitions between video clips
based on content analysis (HSV histogram comparison, LLM semantic classification)
and random selection with configurable weights.

All functions degrade gracefully: if a transition fails, it logs the error and
returns a hard cut (simple concatenation) instead of raising an exception.

Usage:
    from transition_selector import select_and_apply_transition

    merged = select_and_apply_transition(
        clip_a_path, clip_b_path, output_dir,
        strategy="auto",  # "auto" | "match_cut" | "glitch" | "sweep_mask" | "mask_reveal" | "shape_morph" | "random"
        semantic_label="action",  # optional LLM-derived label
    )
"""

from __future__ import annotations

import logging
import random
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from .sfx_generator import generate_deep_boom

logger = logging.getLogger(__name__)

# ── LRU cache for frame extraction ────────────────────────────────────────────
# Caché para frames de vídeo en _compute_histogram_similarity.
# Cuando hay N clips, se llama N-1 veces y el frame del clip_b pasa a ser
# clip_a del siguiente par — la caché evita re-extraer frames repetidos.


@lru_cache(maxsize=64)
def _get_first_frame_cached(clip_path: str) -> Optional[np.ndarray]:
    """
    Caché LRU para el primer frame de un clip de archivo.

    Parameters
    ----------
    clip_path : str
        Ruta absoluta al archivo de vídeo.

    Returns
    -------
    np.ndarray | None
        Histograma HSV del primer frame, o None si falla.
    """
    try:
        cap = cv2.VideoCapture(clip_path)
        if not cap.isOpened():
            logger.warning("Cannot open %s for cached frame extraction", clip_path)
            cap.release()
            return None
        try:
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total_frames < 1:
                cap.release()
                return None
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = cap.read()
            if not ret or frame is None:
                return None
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            hist = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
            cv2.normalize(hist, hist)
            return hist
        finally:
            cap.release()
    except Exception as exc:
        logger.warning("Cached first frame extraction failed for %s: %s", clip_path, exc)
        return None


@lru_cache(maxsize=64)
def _get_last_frame_cached(clip_path: str) -> Optional[np.ndarray]:
    """
    Caché LRU para el último frame de un clip de archivo.

    Parameters
    ----------
    clip_path : str
        Ruta absoluta al archivo de vídeo.

    Returns
    -------
    np.ndarray | None
        Histograma HSV del último frame, o None si falla.
    """
    try:
        cap = cv2.VideoCapture(clip_path)
        if not cap.isOpened():
            logger.warning("Cannot open %s for cached frame extraction", clip_path)
            cap.release()
            return None
        try:
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total_frames < 1:
                cap.release()
                return None
            cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames - 1)
            ret, frame = cap.read()
            if not ret or frame is None:
                return None
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            hist = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
            cv2.normalize(hist, hist)
            return hist
        finally:
            cap.release()
    except Exception as exc:
        logger.warning("Cached last frame extraction failed for %s: %s", clip_path, exc)
        return None


# ── Deep boom injection ────────────────────────────────────────────────────────
# Shared counter to rotate boom variants across consecutive transitions.
_boom_counter: list[int] = [0]


def _add_deep_boom_at_start(clip_path: Path, output_dir: Path) -> Optional[Path]:
    """
    Genera un deep_boom y lo mezcla en t=0 del clip dado.

    La variante rota (0→1→2→3→0…) para evitar repeticiones en transiciones
    consecutivas. El boom se coloca en t=0 con adelay=0 y se mezcla con el
    audio original mediante amix.

    Returns
    -------
    Path | None
        Ruta al clip con boom incrustado, o None si falla (degradación silenciosa).
    """
    try:
        variant = _boom_counter[0] % 4
        _boom_counter[0] += 1

        boom_path = generate_deep_boom(variant=variant)
        if not boom_path:
            logger.debug("  [BOOM] generate_deep_boom devolvió vacío — saltando")
            return None

        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"boom_{clip_path.stem}_{random.randint(100000, 999999)}.mp4"

        cmd = [
            "ffmpeg", "-y",
            "-i", str(clip_path.resolve()),
            "-i", boom_path,
            "-filter_complex",
            "[0:a]acopy[a0];"
            "[1:a]adelay=0|0[a1];"
            "[a0][a1]amix=inputs=2:duration=first[aout]",
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(out_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True, timeout=60)

        # Limpiar SFX temporal
        Path(boom_path).unlink(missing_ok=True)

        if out_path.exists():
            logger.info("  [BOOM] deep_boom(variant=%d) inyectado en t=0 de %s", variant, clip_path.name)
            return out_path

        logger.warning("  [BOOM] archivo de salida no encontrado tras mezcla")
        return None

    except Exception as exc:
        logger.warning("  [BOOM] fallo al inyectar deep_boom: %s", exc)
        return None

# ── Transition weight table ──────────────────────────────────────────────────
# Each transition type has a base weight and optional semantic multipliers.
# Higher weight = more likely to be chosen in "auto" or "random" mode.

TRANSITION_WEIGHTS: dict[str, float] = {
    "match_cut": 1.0,
    "glitch": 1.5,
    "sweep_mask": 1.2,
    "mask_reveal": 1.0,
    "shape_morph": 0.6,  # expensive, lower default weight
}

# Semantic labels that boost certain transitions
SEMANTIC_BOOST: dict[str, dict[str, float]] = {
    "action": {"glitch": 2.0, "match_cut": 0.5},
    "dramatic": {"mask_reveal": 2.0, "glitch": 1.5},
    "educational": {"sweep_mask": 1.5, "match_cut": 1.5},
    "comedy": {"glitch": 2.0, "shape_morph": 1.5},
    "storytelling": {"mask_reveal": 1.5, "sweep_mask": 1.3},
    "music": {"match_cut": 2.0, "sweep_mask": 1.2},
    "tutorial": {"sweep_mask": 1.5, "match_cut": 1.5},
    "review": {"match_cut": 1.5, "mask_reveal": 1.2},
    "vlog": {"sweep_mask": 1.3, "match_cut": 1.3},
    "gaming": {"glitch": 2.5, "shape_morph": 1.2},
}


def _compute_histogram_similarity(clip_a_path: Path, clip_b_path: Path) -> float:
    """
    Compute HSV histogram similarity between the last frame of clip_a
    and the first frame of clip_b.

    Returns a score in [0.0, 1.0] where 1.0 = identical histograms.
    On any error, returns 0.0 and logs a warning.
    """
    try:
        def _get_frame_histogram(video_path: Path, frame_index: int = 0) -> Optional[np.ndarray]:
            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                logger.warning("Cannot open %s for histogram extraction", video_path)
                cap.release()
                return None
            try:
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                if total_frames < 1:
                    cap.release()
                    return None
                target = min(frame_index, total_frames - 1)
                cap.set(cv2.CAP_PROP_POS_FRAMES, target)
                ret, frame = cap.read()
                if not ret or frame is None:
                    return None
                hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                hist = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
                cv2.normalize(hist, hist)
                return hist
            finally:
                cap.release()

        hist_a = _get_frame_histogram(clip_a_path, frame_index=-1)  # last frame
        hist_b = _get_frame_histogram(clip_b_path, frame_index=0)   # first frame

        if hist_a is None or hist_b is None:
            logger.debug("Histogram comparison unavailable — one or both frames missing")
            return 0.0

        similarity = cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_CORREL)
        # Normalize from [-1, 1] to [0, 1]
        similarity = max(0.0, min(1.0, (similarity + 1.0) / 2.0))
        logger.debug("Histogram similarity: %.3f", similarity)
        return similarity

    except Exception as exc:
        logger.warning("Histogram similarity computation failed: %s", exc)
        return 0.0


def _classify_semantic_label(clip_a_path: Path, clip_b_path: Path) -> str:
    """
    Attempt to classify the semantic relationship between two clips using
    the LLM (via ai.py). Falls back to "general" on any error.

    This is a lightweight heuristic — it uses the filenames and a brief
    description rather than decoding the full video.
    """
    try:
        from src.ai import get_most_relevant_parts_by_transcript
        # Use filenames as a proxy for content description
        label_a = clip_a_path.stem.replace("_", " ")[:50]
        label_b = clip_b_path.stem.replace("_", " ")[:50]
        prompt_text = (
            f"Classify the transition between two video segments. "
            f"Segment A: '{label_a}'. Segment B: '{label_b}'. "
            f"Choose one word: action, dramatic, educational, comedy, "
            f"storytelling, music, tutorial, review, vlog, gaming, general."
        )
        # We use a simplified call — just get a single label
        result = get_most_relevant_parts_by_transcript(
            transcript=prompt_text,
            video_duration=10.0,
            include_broll=False,
        )
        if result and hasattr(result, "most_relevant_segments") and result.most_relevant_segments:
            # Extract label from the first segment's reasoning
            first = result.most_relevant_segments[0]
            reasoning = str(getattr(first, "reasoning", "") or "")
            for label in ("action", "dramatic", "educational", "comedy",
                          "storytelling", "music", "tutorial", "review",
                          "vlog", "gaming"):
                if label in reasoning.lower():
                    logger.debug("Semantic label classified as '%s'", label)
                    return label
        return "general"
    except Exception as exc:
        logger.debug("Semantic classification unavailable, using 'general': %s", exc)
        return "general"


def _pick_transition_type(
    strategy: str,
    similarity: float,
    semantic_label: str,
) -> str:
    """
    Pick a transition type based on strategy, histogram similarity, and semantic label.

    Strategies:
      - "auto": Use similarity + semantic label to pick the best transition.
      - "match_cut", "glitch", "sweep_mask", "mask_reveal", "shape_morph": Force that type.
      - "random": Weighted random selection.
    """
    if strategy in ("match_cut", "glitch", "sweep_mask", "mask_reveal", "shape_morph"):
        logger.debug("Transition type forced to '%s' by strategy", strategy)
        return strategy

    if strategy == "random":
        weights = dict(TRANSITION_WEIGHTS)
        # Apply semantic boost if available
        boosts = SEMANTIC_BOOST.get(semantic_label, {})
        for ttype, boost in boosts.items():
            if ttype in weights:
                weights[ttype] *= boost
        candidates = list(weights.keys())
        probs = [weights[t] for t in candidates]
        total = sum(probs)
        if total > 0:
            probs = [p / total for p in probs]
        chosen = random.choices(candidates, weights=probs, k=1)[0]
        logger.debug("Random transition selected: '%s' (label=%s)", chosen, semantic_label)
        return chosen

    # "auto" — intelligent selection based on content
    if similarity > 0.7:
        # High similarity → match cut works well (smooth transition)
        logger.debug("Auto-selected 'match_cut' (similarity=%.2f)", similarity)
        return "match_cut"
    elif similarity > 0.4:
        # Medium similarity → sweep_mask or mask_reveal
        if semantic_label in ("action", "gaming", "comedy"):
            chosen = "glitch"
        elif semantic_label in ("dramatic", "storytelling"):
            chosen = "mask_reveal"
        else:
            chosen = "sweep_mask"
        logger.debug("Auto-selected '%s' (similarity=%.2f, label=%s)", chosen, similarity, semantic_label)
        return chosen
    else:
        # Low similarity → more dramatic transitions
        if semantic_label in ("action", "gaming"):
            chosen = "glitch"
        elif semantic_label in ("dramatic", "storytelling"):
            chosen = "mask_reveal"
        else:
            chosen = random.choices(
                ["glitch", "sweep_mask", "mask_reveal"],
                weights=[1.5, 1.2, 1.0],
                k=1,
            )[0]
        logger.debug("Auto-selected '%s' (similarity=%.2f, label=%s)", chosen, similarity, semantic_label)
        return chosen


def _apply_hard_cut(clip_a_path: Path, clip_b_path: Path, output_dir: Path) -> Optional[Path]:
    """
    Fallback: simple concatenation (hard cut) using FFmpeg concat demuxer.
    Returns the output path, or None on failure.
    """
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"hard_cut_{random.randint(100000, 999999)}.mp4"

        # Create concat file list
        concat_file = output_dir / f"concat_{random.randint(100000, 999999)}.txt"
        concat_file.write_text(
            f"file '{clip_a_path.resolve()}'\n"
            f"file '{clip_b_path.resolve()}'\n"
        )

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-c", "copy",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        concat_file.unlink(missing_ok=True)

        if result.returncode != 0 or not output_path.exists():
            logger.error("Hard cut FFmpeg concat failed: %s", result.stderr[:500])
            return None

        logger.info("Hard cut applied: %s", output_path.name)
        return output_path

    except Exception as exc:
        logger.error("Hard cut fallback failed: %s", exc)
        return None


def _apply_match_cut(clip_a_path: Path, clip_b_path: Path, output_dir: Path) -> Optional[Path]:
    """
    Apply a match cut transition using clip_editor.match_cut_transition.
    Injects a deep_boom at t=0 of clip_a before the transition.
    Falls back to hard cut on failure.
    """
    try:
        from src.clip_editor import match_cut_transition
        output_dir.mkdir(parents=True, exist_ok=True)

        # Deep boom at t=0 of clip_a
        boommed = _add_deep_boom_at_start(clip_a_path, output_dir)
        effective_a = boommed if boommed else clip_a_path

        output_path = output_dir / f"match_cut_{random.randint(100000, 999999)}.mp4"
        result = match_cut_transition(effective_a, clip_b_path, output_path)
        if result and Path(result).exists():
            logger.info("Match cut applied: %s", Path(result).name)
            return Path(result)
        logger.warning("Match cut returned no valid path, falling back to hard cut")
        return _apply_hard_cut(clip_a_path, clip_b_path, output_dir)
    except Exception as exc:
        logger.warning("Match cut failed (%s), falling back to hard cut", exc)
        return _apply_hard_cut(clip_a_path, clip_b_path, output_dir)


def _apply_glitch(clip_a_path: Path, clip_b_path: Path, output_dir: Path) -> Optional[Path]:
    """
    Apply a glitch transition using clip_editor.glitch_transition.
    Injects a deep_boom at t=0 of clip_a before the transition.
    Falls back to hard cut on failure.
    """
    try:
        from src.clip_editor import glitch_transition
        output_dir.mkdir(parents=True, exist_ok=True)

        # Deep boom at t=0 of clip_a
        boommed = _add_deep_boom_at_start(clip_a_path, output_dir)
        effective_a = boommed if boommed else clip_a_path

        output_path = output_dir / f"glitch_{random.randint(100000, 999999)}.mp4"
        result = glitch_transition(effective_a, clip_b_path, output_path)
        if result and Path(result).exists():
            logger.info("Glitch transition applied: %s", Path(result).name)
            return Path(result)
        logger.warning("Glitch returned no valid path, falling back to hard cut")
        return _apply_hard_cut(clip_a_path, clip_b_path, output_dir)
    except Exception as exc:
        logger.warning("Glitch transition failed (%s), falling back to hard cut", exc)
        return _apply_hard_cut(clip_a_path, clip_b_path, output_dir)


def _apply_sweep_mask(clip_a_path: Path, clip_b_path: Path, output_dir: Path) -> Optional[Path]:
    """
    Apply a sweep mask transition using clip_editor.sweep_mask_transition.
    Injects a deep_boom at t=0 of clip_a before the transition.
    Falls back to hard cut on failure.
    """
    try:
        from src.clip_editor import sweep_mask_transition
        output_dir.mkdir(parents=True, exist_ok=True)

        # Deep boom at t=0 of clip_a
        boommed = _add_deep_boom_at_start(clip_a_path, output_dir)
        effective_a = boommed if boommed else clip_a_path

        output_path = output_dir / f"sweep_mask_{random.randint(100000, 999999)}.mp4"
        result = sweep_mask_transition(effective_a, clip_b_path, output_path)
        if result and Path(result).exists():
            logger.info("Sweep mask transition applied: %s", Path(result).name)
            return Path(result)
        logger.warning("Sweep mask returned no valid path, falling back to hard cut")
        return _apply_hard_cut(clip_a_path, clip_b_path, output_dir)
    except Exception as exc:
        logger.warning("Sweep mask transition failed (%s), falling back to hard cut", exc)
        return _apply_hard_cut(clip_a_path, clip_b_path, output_dir)


def _apply_mask_reveal(clip_a_path: Path, clip_b_path: Path, output_dir: Path) -> Optional[Path]:
    """
    Apply a mask reveal transition using clip_editor.mask_reveal_transition.
    Injects a deep_boom at t=0 of clip_a before the transition.
    Falls back to hard cut on failure.
    """
    try:
        from src.clip_editor import mask_reveal_transition
        output_dir.mkdir(parents=True, exist_ok=True)

        # Deep boom at t=0 of clip_a
        boommed = _add_deep_boom_at_start(clip_a_path, output_dir)
        effective_a = boommed if boommed else clip_a_path

        output_path = output_dir / f"mask_reveal_{random.randint(100000, 999999)}.mp4"
        result = mask_reveal_transition(effective_a, clip_b_path, output_path)
        if result and Path(result).exists():
            logger.info("Mask reveal transition applied: %s", Path(result).name)
            return Path(result)
        logger.warning("Mask reveal returned no valid path, falling back to hard cut")
        return _apply_hard_cut(clip_a_path, clip_b_path, output_dir)
    except Exception as exc:
        logger.warning("Mask reveal transition failed (%s), falling back to hard cut", exc)
        return _apply_hard_cut(clip_a_path, clip_b_path, output_dir)


def _apply_shape_morph(clip_a_path: Path, clip_b_path: Path, output_dir: Path) -> Optional[Path]:
    """
    Apply a shape morph transition using clip_editor.shape_morph_transition.
    Injects a deep_boom at t=0 of clip_a before the transition.
    Falls back to hard cut on failure.
    """
    try:
        from src.clip_editor import shape_morph_transition
        output_dir.mkdir(parents=True, exist_ok=True)

        # Deep boom at t=0 of clip_a
        boommed = _add_deep_boom_at_start(clip_a_path, output_dir)
        effective_a = boommed if boommed else clip_a_path

        output_path = output_dir / f"shape_morph_{random.randint(100000, 999999)}.mp4"
        result = shape_morph_transition(effective_a, clip_b_path, output_path)
        if result and Path(result).exists():
            logger.info("Shape morph transition applied: %s", Path(result).name)
            return Path(result)
        logger.warning("Shape morph returned no valid path, falling back to hard cut")
        return _apply_hard_cut(clip_a_path, clip_b_path, output_dir)
    except Exception as exc:
        logger.warning("Shape morph transition failed (%s), falling back to hard cut", exc)
        return _apply_hard_cut(clip_a_path, clip_b_path, output_dir)


# ── Transition dispatch map ──────────────────────────────────────────────────

TRANSITION_DISPATCH: dict[str, callable] = {
    "match_cut": _apply_match_cut,
    "glitch": _apply_glitch,
    "sweep_mask": _apply_sweep_mask,
    "mask_reveal": _apply_mask_reveal,
    "shape_morph": _apply_shape_morph,
}


# ── Public API ───────────────────────────────────────────────────────────────

def select_and_apply_transition(
    clip_a_path: Path,
    clip_b_path: Path,
    output_dir: Path,
    strategy: str = "auto",
    semantic_label: str = "",
    force_transition: str = "",
) -> Optional[Path]:
    """
    Select and apply a transition between two clips.

    Parameters
    ----------
    clip_a_path : Path
        Path to the first (left) clip.
    clip_b_path : Path
        Path to the second (right) clip.
    output_dir : Path
        Directory where the merged output will be written.
    strategy : str
        Selection strategy: "auto" (default), "match_cut", "glitch",
        "sweep_mask", "mask_reveal", "shape_morph", or "random".
    semantic_label : str
        Optional semantic label (e.g., "action", "dramatic"). If empty,
        it will be auto-classified via LLM when strategy is "auto".
    force_transition : str
        If non-empty, overrides strategy and forces this specific transition type.

    Returns
    -------
    Path | None
        Path to the merged video file, or None if all attempts failed.
    """
    logger.info(
        "select_and_apply_transition — %s → %s (strategy=%s, label=%s)",
        clip_a_path.name, clip_b_path.name, strategy, semantic_label,
    )

    # Determine transition type
    transition_type = force_transition or strategy

    if transition_type not in ("match_cut", "glitch", "sweep_mask", "mask_reveal",
                                "shape_morph", "auto", "random"):
        logger.warning("Unknown transition type '%s', falling back to 'auto'", transition_type)
        transition_type = "auto"

    if transition_type in ("auto", "random"):
        # Compute histogram similarity
        similarity = _compute_histogram_similarity(clip_a_path, clip_b_path)

        # Classify semantic label if not provided
        if not semantic_label:
            semantic_label = _classify_semantic_label(clip_a_path, clip_b_path)

        transition_type = _pick_transition_type(transition_type, similarity, semantic_label)

    # Apply the selected transition
    dispatch = TRANSITION_DISPATCH.get(transition_type)
    if dispatch:
        result = dispatch(clip_a_path, clip_b_path, output_dir)
        if result:
            return result
        logger.warning("Transition '%s' returned no result, falling back to hard cut", transition_type)
    else:
        logger.warning("No dispatch for transition '%s', falling back to hard cut", transition_type)

    return _apply_hard_cut(clip_a_path, clip_b_path, output_dir)


def merge_with_transitions(
    clip_paths: list[Path],
    output_dir: Path,
    strategy: str = "auto",
) -> Optional[Path]:
    """
    Merge multiple clips applying transitions between each pair.

    This is the high-level entry point that replaces simple concatenation.
    It merges clips sequentially, applying a transition between each pair.

    Parameters
    ----------
    clip_paths : list[Path]
        Ordered list of clip paths to merge.
    output_dir : Path
        Directory for intermediate and final outputs.
    strategy : str
        Transition selection strategy (passed to select_and_apply_transition).

    Returns
    -------
    Path | None
        Path to the final merged video, or None if merging failed entirely.
    """
    if not clip_paths:
        logger.warning("merge_with_transitions called with empty clip list")
        return None

    if len(clip_paths) == 1:
        logger.info("Only one clip, returning as-is: %s", clip_paths[0].name)
        return clip_paths[0]

    logger.info(
        "merge_with_transitions — merging %d clips (strategy=%s)",
        len(clip_paths), strategy,
    )

    current = clip_paths[0]
    for i in range(1, len(clip_paths)):
        logger.debug("Merging clip %d/%d with transition", i + 1, len(clip_paths))
        result = select_and_apply_transition(
            clip_a_path=current,
            clip_b_path=clip_paths[i],
            output_dir=output_dir,
            strategy=strategy,
        )
        if result is None:
            logger.error(
                "Merge failed at clip %d/%d — all transitions including hard cut failed",
                i + 1, len(clip_paths),
            )
            return None
        current = result

    logger.info("Merge complete: %s", current.name)
    return current
