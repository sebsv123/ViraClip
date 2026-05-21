"""
Export Gate — strict quality gate that weak clips cannot pass.

Blocks export if any critical dimension fails. Scoring is fully explainable.
Override allowed only via explicit `force=true` query parameter.

Thresholds (env-configurable):
  HOOK_MIN         5.0  — hook score 0-10
  VIRALITY_MIN     5.0  — virality score 0-10
  PACING_MIN       4.0  — pacing score 0-10
  READABILITY_MIN  5.0  — subtitle readability 0-10
  AUDIO_MIN        5.0  — audio balance score 0-10
  BROLL_MIN        1    — minimum B-roll count (0 = no B-roll required)
  ENDING_MIN       4.0  — ending quality score 0-10
  INSURANCE_MIN    1    — minimum insurance-native keywords kept (0 = not insurance content)

Each dimension returns: pass/fail, score, reason, fix.
Overall: PASS only if ALL dimensions pass. Override via force=true.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Configurable thresholds (env overrides) ──────────────────────────────────
HOOK_MIN        = float(os.getenv("EXPORT_GATE_HOOK_MIN", "5.0"))
VIRALITY_MIN    = float(os.getenv("EXPORT_GATE_VIRALITY_MIN", "5.0"))
PACING_MIN      = float(os.getenv("EXPORT_GATE_PACING_MIN", "4.0"))
READABILITY_MIN = float(os.getenv("EXPORT_GATE_READABILITY_MIN", "5.0"))
AUDIO_MIN       = float(os.getenv("EXPORT_GATE_AUDIO_MIN", "5.0"))
BROLL_MIN       = int(os.getenv("EXPORT_GATE_BROLL_MIN", "1"))
ENDING_MIN      = float(os.getenv("EXPORT_GATE_ENDING_MIN", "4.0"))
INSURANCE_MIN   = int(os.getenv("EXPORT_GATE_INSURANCE_MIN", "1"))


@dataclass
class DimensionScore:
    """Score for one quality dimension."""
    name: str
    score: float       # 0-10
    threshold: float   # minimum to pass
    passed: bool
    reason: str        # human-readable explanation
    fix: str = ""      # actionable fix if failed


@dataclass
class ExportGateResult:
    """Result of the export gate check."""
    passed: bool
    overall_score: float   # 0-10
    dimensions: List[DimensionScore] = field(default_factory=list)
    blocked_by: List[str] = field(default_factory=list)  # dimension names that failed
    forced: bool = False   # true if override was used

    def to_dict(self) -> Dict[str, Any]:
        return {
            "export_allowed": self.passed,
            "overall_score": round(self.overall_score, 1),
            "forced": self.forced,
            "dimensions": [
                {
                    "name": d.name,
                    "score": round(d.score, 1),
                    "threshold": d.threshold,
                    "passed": d.passed,
                    "reason": d.reason,
                    "fix": d.fix,
                }
                for d in self.dimensions
            ],
            "blocked_by": self.blocked_by,
        }


def _score_hook(clip_data: Dict[str, Any]) -> DimensionScore:
    """Hook strength: first 3s must grab attention."""
    raw = float(clip_data.get("hook_score", 0) or 0)
    score = min(10.0, max(0.0, raw))
    hook_type = clip_data.get("hook_type", "") or ""
    passed = score >= HOOK_MIN
    reason = (
        f"Hook score {score:.1f}/10, type={hook_type}"
        if hook_type
        else f"Hook score {score:.1f}/10"
    )
    fix = "Add a question, bold claim, or surprising stat in the first 3 seconds." if not passed else ""
    return DimensionScore("Hook Strength", score, HOOK_MIN, passed, reason, fix)


def _score_virality(clip_data: Dict[str, Any]) -> DimensionScore:
    """Overall virality score."""
    raw = float(clip_data.get("virality_score", 0) or 0)
    score = min(10.0, max(0.0, raw))
    passed = score >= VIRALITY_MIN
    reason = f"Virality score {score:.1f}/10"
    fix = "Strengthen hook, add B-roll at energy peaks, boost audio to -14 LUFS." if not passed else ""
    return DimensionScore("Virality", score, VIRALITY_MIN, passed, reason, fix)


def _score_pacing(clip_data: Dict[str, Any]) -> DimensionScore:
    """Pacing consistency: words-per-second or B-roll spacing."""
    # Try words-per-second first
    words = clip_data.get("words", [])
    duration = float(clip_data.get("duration", 30) or 30)
    if words and duration > 0:
        wps = len(words) / duration
        # Optimal 2.5-3.5 wps; score 10 at 3.0, drops linearly
        score = max(0.0, 10.0 - abs(wps - 3.0) * 4.0)
        reason = f"Speech rate {wps:.1f} wps (optimal 2.5-3.5)"
    else:
        # Fallback: B-roll density as pacing proxy
        broll_count = int(clip_data.get("broll_count", 0) or 0)
        if broll_count >= 2:
            score = 7.0
            reason = f"{broll_count} B-roll overlays provide visual pacing"
        elif broll_count == 1:
            score = 5.0
            reason = "Only 1 B-roll overlay — pacing may feel slow"
        else:
            score = 3.0
            reason = "No B-roll — pacing likely too static"
    score = max(0.0, min(10.0, score))
    passed = score >= PACING_MIN
    fix = "Add jump cuts or B-roll every 5-8s to maintain visual pacing." if not passed else ""
    return DimensionScore("Pacing Consistency", score, PACING_MIN, passed, reason, fix)


def _score_readability(clip_data: Dict[str, Any]) -> DimensionScore:
    """Subtitle readability: captions present, emphasis ratio reasonable."""
    has_captions = bool(clip_data.get("words"))
    if not has_captions:
        return DimensionScore(
            "Subtitle Readability", 0.0, READABILITY_MIN, False,
            "No captions — 85% of TikTok is watched without sound",
            "Generate word-level karaoke captions before publishing.",
        )
    # Check emphasis ratio (too many emphasized words = hard to read)
    words = clip_data.get("words", [])
    if words:
        emph_count = sum(1 for w in words if w.get("is_emphasis") or str(w.get("word", "")).isupper())
        emph_ratio = emph_count / len(words)
        if emph_ratio > 0.15:
            score = max(0.0, 10.0 - (emph_ratio - 0.15) * 50.0)
            reason = f"Emphasis ratio {emph_ratio:.0%} > 15% — too many highlighted words"
        else:
            score = 8.0
            reason = f"Captions present, emphasis ratio {emph_ratio:.0%}"
    else:
        score = 7.0
        reason = "Captions present"
    passed = score >= READABILITY_MIN
    fix = "Reduce emphasized words to ≤15% of total for better readability." if not passed else ""
    return DimensionScore("Subtitle Readability", score, READABILITY_MIN, passed, reason, fix)


def _score_audio(clip_data: Dict[str, Any]) -> DimensionScore:
    """Audio balance: loudnorm applied, no clipping, ducking active."""
    loudnorm = bool(clip_data.get("loudnorm_applied", False))
    ducking = bool(clip_data.get("audio_ducking_applied", False))
    score = 5.0  # baseline
    reasons = []
    if loudnorm:
        score += 2.5
        reasons.append("loudnorm applied")
    if ducking:
        score += 2.5
        reasons.append("ducking active")
    reason = ", ".join(reasons) if reasons else "No audio processing detected"
    passed = score >= AUDIO_MIN
    fix = "Apply EBU R128 loudnorm (target -14 LUFS) and enable audio ducking." if not passed else ""
    return DimensionScore("Audio Balance", score, AUDIO_MIN, passed, reason, fix)


def _score_broll(clip_data: Dict[str, Any]) -> DimensionScore:
    """B-roll relevance: at least some B-roll present."""
    broll_count = int(clip_data.get("broll_count", 0) or 0)
    score = min(10.0, broll_count * 2.0)
    passed = broll_count >= BROLL_MIN
    reason = f"{broll_count} B-roll overlay(s)" if broll_count else "No B-roll"
    fix = "Add contextual B-roll every 5-8s to maintain visual interest." if not passed else ""
    return DimensionScore("B-Roll Relevance", score, float(BROLL_MIN), passed, reason, fix)


def _score_ending(clip_data: Dict[str, Any]) -> DimensionScore:
    """Ending quality: CTA presence, closing strength."""
    has_cta = bool(clip_data.get("has_cta", False))
    closing_score = float(clip_data.get("closing_score", 0) or 0)
    if has_cta:
        score = 8.0
        reason = "CTA detected in closing"
    elif closing_score > 0:
        score = min(10.0, closing_score)
        reason = f"Closing strength {closing_score:.1f}/10"
    else:
        score = 3.0
        reason = "No CTA or strong closing detected"
    passed = score >= ENDING_MIN
    fix = "Add a call-to-action in the last 3 seconds (subscribe, follow, comment)." if not passed else ""
    return DimensionScore("Ending Quality", score, ENDING_MIN, passed, reason, fix)


def _score_insurance(clip_data: Dict[str, Any]) -> DimensionScore:
    """Insurance-native relevance: keywords match insurance domain."""
    is_insurance = bool(clip_data.get("is_insurance_content", False))
    if not is_insurance:
        return DimensionScore(
            "Insurance Relevance", 10.0, float(INSURANCE_MIN), True,
            "Not insurance content — no check needed",
        )
    kept_keywords = clip_data.get("insurance_keywords_kept", [])
    kept_count = len(kept_keywords) if isinstance(kept_keywords, list) else 0
    score = min(10.0, kept_count * 3.0)
    passed = kept_count >= INSURANCE_MIN
    reason = f"{kept_count} insurance-native keyword(s) kept" if kept_count else "All keywords rejected — no insurance-native visuals"
    fix = "Ensure B-roll keywords match insurance-native concepts (policy, claim, family, advisor, etc.)." if not passed else ""
    return DimensionScore("Insurance Relevance", score, float(INSURANCE_MIN), passed, reason, fix)


# ── Dimension registry ──────────────────────────────────────────────────────
_DIMENSION_CHECKS = [
    _score_hook,
    _score_virality,
    _score_pacing,
    _score_readability,
    _score_audio,
    _score_broll,
    _score_ending,
    _score_insurance,
]


def check_export_readiness(
    clip_data: Dict[str, Any],
    force: bool = False,
) -> ExportGateResult:
    """
    Run all dimension checks and return an ExportGateResult.

    Args:
        clip_data: Dict with keys: hook_score, virality_score, words, duration,
                   broll_count, loudnorm_applied, audio_ducking_applied, has_cta,
                   closing_score, is_insurance_content, insurance_keywords_kept.
        force: If True, allow export even if checks fail (requires explicit approval).

    Returns:
        ExportGateResult with per-dimension scores and overall pass/fail.
    """
    dimensions = [check(clip_data) for check in _DIMENSION_CHECKS]
    failed = [d for d in dimensions if not d.passed]
    blocked_by = [d.name for d in failed]

    if dimensions:
        overall_score = sum(d.score for d in dimensions) / len(dimensions)
    else:
        overall_score = 0.0

    passed = len(failed) == 0 or force

    if force and failed:
        logger.warning(
            "[ExportGate] ⚠️ FORCE OVERRIDE — %d dimension(s) failed but export allowed: %s",
            len(failed), [d.name for d in failed],
        )

    if not passed and not force:
        logger.info(
            "[ExportGate] ❌ BLOCKED — %d dimension(s) below threshold: %s",
            len(failed), [d.name for d in failed],
        )

    return ExportGateResult(
        passed=passed,
        overall_score=overall_score,
        dimensions=dimensions,
        blocked_by=blocked_by,
        forced=force,
    )
