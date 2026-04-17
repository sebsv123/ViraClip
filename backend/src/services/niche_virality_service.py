"""
Niche-Aware Virality Scorer — per-niche weighting on top of the base scorer.

Uses real performance data from the analytics_importer / performance_webhook
store to learn which signal weights matter for each niche, then blends with
the base virality score to produce a niche-calibrated score.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# Model weights store path (JSON; upgradeable to DB)
_WEIGHTS_STORE = Path(
    os.environ.get("NICHE_WEIGHTS_PATH", "/app/data/niche_weights.json")
)

# Default feature weights per niche (tuned from industry benchmarks)
_DEFAULT_WEIGHTS: Dict[str, Dict[str, float]] = {
    "fitness": {
        "hook_score": 0.35, "pacing_score": 0.30, "emotion_score": 0.15,
        "audio_energy": 0.15, "duration_penalty": 0.05,
    },
    "finance": {
        "hook_score": 0.40, "pacing_score": 0.15, "emotion_score": 0.20,
        "audio_energy": 0.05, "duration_penalty": 0.20,
    },
    "food": {
        "hook_score": 0.25, "pacing_score": 0.25, "emotion_score": 0.25,
        "audio_energy": 0.10, "duration_penalty": 0.15,
    },
    "comedy": {
        "hook_score": 0.30, "pacing_score": 0.35, "emotion_score": 0.25,
        "audio_energy": 0.05, "duration_penalty": 0.05,
    },
    "education": {
        "hook_score": 0.35, "pacing_score": 0.20, "emotion_score": 0.15,
        "audio_energy": 0.05, "duration_penalty": 0.25,
    },
    "lifestyle": {
        "hook_score": 0.30, "pacing_score": 0.25, "emotion_score": 0.25,
        "audio_energy": 0.10, "duration_penalty": 0.10,
    },
    "tech": {
        "hook_score": 0.35, "pacing_score": 0.20, "emotion_score": 0.15,
        "audio_energy": 0.05, "duration_penalty": 0.25,
    },
    "beauty": {
        "hook_score": 0.25, "pacing_score": 0.30, "emotion_score": 0.30,
        "audio_energy": 0.10, "duration_penalty": 0.05,
    },
    "travel": {
        "hook_score": 0.25, "pacing_score": 0.30, "emotion_score": 0.30,
        "audio_energy": 0.10, "duration_penalty": 0.05,
    },
    "default": {
        "hook_score": 0.30, "pacing_score": 0.25, "emotion_score": 0.20,
        "audio_energy": 0.10, "duration_penalty": 0.15,
    },
}

# Duration sweet spots per niche (seconds): clips outside this range get penalised
_DURATION_SWEET_SPOTS: Dict[str, tuple] = {
    "fitness":   (30, 60),
    "finance":   (45, 90),
    "food":      (20, 45),
    "comedy":    (15, 30),
    "education": (45, 90),
    "lifestyle": (30, 60),
    "tech":      (45, 90),
    "beauty":    (30, 60),
    "travel":    (30, 75),
    "default":   (20, 75),
}


@dataclass
class NicheScoreResult:
    niche_score: float          # 0–100 niche-calibrated score
    base_score: float           # original base virality score
    niche: str
    weights_used: Dict[str, float]
    feature_contributions: Dict[str, float]
    duration_ok: bool
    recommended_duration_range: tuple
    retrained_from_data: bool = False


def _load_learned_weights() -> Dict[str, Dict[str, float]]:
    """Load any learned per-niche weights from disk."""
    if not _WEIGHTS_STORE.exists():
        return {}
    try:
        return json.loads(_WEIGHTS_STORE.read_text())
    except Exception:
        return {}


def _save_learned_weights(weights: Dict[str, Dict[str, float]]) -> None:
    """Persist learned weights to disk."""
    _WEIGHTS_STORE.parent.mkdir(parents=True, exist_ok=True)
    _WEIGHTS_STORE.write_text(json.dumps(weights, indent=2))


def get_weights_for_niche(niche: str) -> Dict[str, float]:
    """Return feature weights for a niche, merging learned over defaults."""
    learned = _load_learned_weights()
    default = _DEFAULT_WEIGHTS.get(niche.lower(), _DEFAULT_WEIGHTS["default"])
    override = learned.get(niche.lower(), {})
    return {**default, **override}


def score_for_niche(
    niche: str,
    base_virality_score: float,
    hook_score: float = 50.0,
    pacing_score: float = 50.0,
    emotion_score: float = 50.0,
    audio_energy: float = 0.5,
    clip_duration: float = 45.0,
) -> NicheScoreResult:
    """
    Compute a niche-calibrated virality score.

    Args:
        niche: Creator niche category (fitness, finance, food, etc.)
        base_virality_score: Raw virality score from the base scorer (0–100)
        hook_score: Hook quality score (0–100)
        pacing_score: Edit pacing score (0–100)
        emotion_score: Emotional resonance score (0–100)
        audio_energy: Audio RMS energy level (0–1)
        clip_duration: Clip length in seconds
    """
    niche_lower = niche.lower()
    weights = get_weights_for_niche(niche_lower)
    sweet_min, sweet_max = _DURATION_SWEET_SPOTS.get(niche_lower, _DURATION_SWEET_SPOTS["default"])

    # Duration penalty (0–1 multiplier)
    if sweet_min <= clip_duration <= sweet_max:
        duration_mult = 1.0
        duration_ok = True
    elif clip_duration < sweet_min:
        duration_mult = max(0.7, clip_duration / sweet_min)
        duration_ok = False
    else:
        overshoot = (clip_duration - sweet_max) / sweet_max
        duration_mult = max(0.7, 1.0 - overshoot * 0.3)
        duration_ok = False

    # Weighted feature score (0–100)
    feature_contributions = {
        "hook_score":     hook_score * weights.get("hook_score", 0.30),
        "pacing_score":   pacing_score * weights.get("pacing_score", 0.25),
        "emotion_score":  emotion_score * weights.get("emotion_score", 0.20),
        "audio_energy":   audio_energy * 100 * weights.get("audio_energy", 0.10),
        "duration_penalty": 0.0,  # computed below
    }
    raw_weighted = sum(feature_contributions[k] for k in feature_contributions if k != "duration_penalty")

    # Blend weighted features (60%) with base score (40%)
    blended = 0.6 * raw_weighted + 0.4 * base_virality_score

    # Apply duration multiplier
    niche_score = min(100.0, max(0.0, blended * duration_mult))

    duration_contribution = (1.0 - duration_mult) * blended * weights.get("duration_penalty", 0.1)
    feature_contributions["duration_penalty"] = -duration_contribution

    logger.debug(
        "[niche_virality] niche=%s base=%.1f niche=%.1f dur_ok=%s",
        niche, base_virality_score, niche_score, duration_ok,
    )

    return NicheScoreResult(
        niche_score=round(niche_score, 1),
        base_score=base_virality_score,
        niche=niche,
        weights_used=weights,
        feature_contributions={k: round(v, 2) for k, v in feature_contributions.items()},
        duration_ok=duration_ok,
        recommended_duration_range=(sweet_min, sweet_max),
        retrained_from_data=bool(_load_learned_weights().get(niche_lower)),
    )


def retrain_niche_weights(niche: str, performance_events: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    Simple gradient-free weight optimisation using correlation with views.

    For each feature, compute its Pearson correlation with view count across
    all performance events that have the required fields, then normalise
    correlations to valid weight vector.

    Returns the updated weights for the niche.
    """
    if len(performance_events) < 10:
        logger.info("[niche_virality] Not enough data to retrain (%d < 10 events)", len(performance_events))
        return get_weights_for_niche(niche)

    features = ["hook_score", "pacing_score", "emotion_score", "audio_energy"]
    views_list = []
    feature_vecs: Dict[str, List[float]] = {f: [] for f in features}

    for event in performance_events:
        v = event.get("views", 0)
        if v <= 0:
            continue
        has_all = all(f in event for f in features)
        if not has_all:
            continue
        views_list.append(float(v))
        for f in features:
            feature_vecs[f].append(float(event[f]))

    if len(views_list) < 10:
        logger.info("[niche_virality] Not enough events with full features (%d)", len(views_list))
        return get_weights_for_niche(niche)

    # Pearson correlation
    import statistics
    mean_v = statistics.mean(views_list)
    std_v = statistics.stdev(views_list) or 1e-9

    correlations: Dict[str, float] = {}
    for f in features:
        vals = feature_vecs[f]
        mean_f = statistics.mean(vals)
        std_f = statistics.stdev(vals) or 1e-9
        cov = sum((vals[i] - mean_f) * (views_list[i] - mean_v) for i in range(len(vals))) / len(vals)
        correlations[f] = max(0.0, cov / (std_f * std_v))

    total_corr = sum(correlations.values()) or 1e-9
    # Add duration_penalty as fixed 0.05 weight; normalise the rest
    new_weights: Dict[str, float] = {
        f: round((correlations[f] / total_corr) * 0.95, 3) for f in features
    }
    new_weights["duration_penalty"] = 0.05

    learned = _load_learned_weights()
    learned[niche.lower()] = new_weights
    _save_learned_weights(learned)

    logger.info("[niche_virality] Retrained weights for '%s': %s", niche, new_weights)
    return new_weights


def get_niche_recommendations(niche: str, score_result: NicheScoreResult) -> List[str]:
    """Generate actionable improvement recommendations based on score breakdown."""
    recs = []
    features = score_result.feature_contributions
    weights = score_result.weights_used

    # Find the highest-weight feature with lowest contribution
    scored = sorted(
        [(k, features.get(k, 0), weights.get(k, 0)) for k in weights if k != "duration_penalty"],
        key=lambda x: -x[2],
    )
    if scored:
        weakest = min(scored, key=lambda x: x[1] / max(weights.get(x[0], 0.01), 0.01))
        recs.append(f"Improve your {weakest[0].replace('_', ' ')} — it has the highest impact for {niche} content")

    if not score_result.duration_ok:
        lo, hi = score_result.recommended_duration_range
        recs.append(f"Aim for {lo}–{hi}s clip duration (optimal for {niche} content)")

    if score_result.niche_score < 60:
        recs.append("Consider a stronger hook in the first 3 seconds")
    if score_result.niche_score >= 80:
        recs.append("This clip is well-optimised for your niche — great work!")

    return recs
