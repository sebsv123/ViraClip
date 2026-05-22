"""
Clip Health Service — actionable health report beyond a single virality score.

Produces a structured report with emoji status icons and specific fixes:
  ❌ Critical issues that will hurt performance
  ⚠️  Warnings that reduce virality
  ✅  Passing checks
  💡 Suggestions for improvement

Checks run purely from clip metadata — no video re-processing required.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ── Thresholds ─────────────────────────────────────────────────────────────────
HOOK_WINDOW_S = 3.0          # hook should appear in first N seconds
MIN_VIRALITY = 5.0           # below this = needs optimisation
MIN_AUDIO_ENERGY = 0.3       # normalised energy 0-1
MIN_DURATION_TIKTOK = 7.0    # seconds
MAX_DURATION_TIKTOK = 60.0
MIN_BROLL_COVERAGE = 0.2     # fraction of clip covered by B-roll
MIN_HOOK_SCORE = 5.0
MIN_ENGAGEMENT_SCORE = 5.0
LOUD_NORM_TARGET = -14.0     # LUFS
from ...domains.broll.broll_config import MIN_OVERLAY_DURATION_S

MIN_BROLL_DURATION_S = MIN_OVERLAY_DURATION_S  # minimum B-roll overlay duration
MAX_BROLL_PER_10S = 4        # max B-roll overlays per 10s of clip
MIN_VOICE_RMS_DB = -24.0     # minimum voice RMS level in dB
BGM_EXPECTED = True          # whether BGM is expected by default


@dataclass
class HealthCheck:
    name: str
    status: str          # "pass" | "warn" | "fail" | "info"
    icon: str            # ✅ | ⚠️ | ❌ | 💡
    message: str
    fix: str = ""        # actionable one-liner


@dataclass
class ClipHealthReport:
    clip_id: str
    overall_score: float   # 0-100
    grade: str             # A | B | C | D | F
    checks: list[HealthCheck] = field(default_factory=list)
    summary: str = ""
    top_fix: str = ""      # single most impactful fix

    def to_dict(self) -> dict:
        return {
            "clip_id": self.clip_id,
            "overall_score": self.overall_score,
            "grade": self.grade,
            "summary": self.summary,
            "top_fix": self.top_fix,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status,
                    "icon": c.icon,
                    "message": c.message,
                    "fix": c.fix,
                }
                for c in self.checks
            ],
        }


def _icon(status: str) -> str:
    return {"pass": "✅", "warn": "⚠️", "fail": "❌", "info": "💡"}.get(status, "ℹ️")


def _score_from_checks(checks: list[HealthCheck]) -> float:
    """Compute 0-100 health score: each fail -15, each warn -5."""
    score = 100.0
    for c in checks:
        if c.status == "fail":
            score -= 15
        elif c.status == "warn":
            score -= 5
    return max(0.0, round(score, 1))


def _grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 45:
        return "D"
    return "F"


# ── Individual check functions ────────────────────────────────────────────────

def check_hook_presence(
    hook_score: Optional[float],
    hook_start: Optional[float],
    hook_type: Optional[str],
) -> HealthCheck:
    if hook_score is None or hook_score == 0:
        return HealthCheck(
            name="Hook Presence",
            status="fail",
            icon="❌",
            message="No hook detected in the clip.",
            fix="Add a compelling opening line in the first 3 seconds (question, bold claim, or stat).",
        )
    if hook_start is not None and hook_start > HOOK_WINDOW_S:
        return HealthCheck(
            name="Hook Timing",
            status="warn",
            icon="⚠️",
            message=f"Hook detected at {hook_start:.1f}s — too late (should be ≤ {HOOK_WINDOW_S}s).",
            fix="Move the strongest statement to the very start of the clip.",
        )
    type_desc = f" ({hook_type.replace('_', ' ')})" if hook_type and hook_type != "none" else ""
    return HealthCheck(
        name="Hook Presence",
        status="pass",
        icon="✅",
        message=f"Strong hook{type_desc} detected in first {HOOK_WINDOW_S}s.",
    )


def check_duration(duration: float, platform: str = "tiktok") -> HealthCheck:
    if platform == "tiktok":
        mn, mx = MIN_DURATION_TIKTOK, MAX_DURATION_TIKTOK
    elif platform == "reels":
        mn, mx = 7.0, 90.0
    elif platform == "shorts":
        mn, mx = 7.0, 60.0
    else:
        mn, mx = 7.0, 90.0

    if duration < mn:
        return HealthCheck(
            name="Duration",
            status="fail",
            icon="❌",
            message=f"Clip is {duration:.1f}s — too short (min {mn}s for {platform}).",
            fix="Extend clip or merge with adjacent segment.",
        )
    if duration > mx:
        return HealthCheck(
            name="Duration",
            status="warn",
            icon="⚠️",
            message=f"Clip is {duration:.1f}s — exceeds {platform} optimum of {mx}s.",
            fix=f"Trim to ≤{int(mx)}s for maximum algorithmic reach.",
        )
    return HealthCheck(
        name="Duration",
        status="pass",
        icon="✅",
        message=f"Duration {duration:.1f}s is optimal for {platform}.",
    )


def check_virality_score(score: float) -> HealthCheck:
    if score < MIN_VIRALITY:
        return HealthCheck(
            name="Virality Score",
            status="fail",
            icon="❌",
            message=f"Virality score {score:.1f}/10 — needs optimisation.",
            fix="Strengthen hook, add B-roll at energy peaks, boost audio to -14 LUFS.",
        )
    if score < 7.0:
        return HealthCheck(
            name="Virality Score",
            status="warn",
            icon="⚠️",
            message=f"Virality score {score:.1f}/10 — good but improvable.",
            fix="Consider adding pattern-interrupt at 3s and a stronger CTA.",
        )
    return HealthCheck(
        name="Virality Score",
        status="pass",
        icon="✅",
        message=f"Virality score {score:.1f}/10 — strong viral potential.",
    )


def check_audio_quality(
    loudnorm_applied: bool,
    sfx_injected: bool,
    audio_energy: Optional[float] = None,
) -> HealthCheck:
    issues = []
    if not loudnorm_applied:
        issues.append("loudnorm not applied")
    if audio_energy is not None and audio_energy < MIN_AUDIO_ENERGY:
        issues.append(f"audio energy low ({audio_energy:.2f})")
    if issues:
        return HealthCheck(
            name="Audio Quality",
            status="warn",
            icon="⚠️",
            message=f"Audio issues: {', '.join(issues)}.",
            fix="Apply EBU R128 loudnorm (target -14 LUFS) and boost by 3dB.",
        )
    return HealthCheck(
        name="Audio Quality",
        status="pass",
        icon="✅",
        message="Audio is loudnorm-compliant." + (" SFX injected." if sfx_injected else ""),
    )


def check_broll_coverage(broll_count: int, duration: float) -> HealthCheck:
    coverage = broll_count / max(duration / 5, 1)   # rough: 1 B-roll per 5s = good
    if broll_count == 0:
        return HealthCheck(
            name="B-Roll Coverage",
            status="warn",
            icon="⚠️",
            message="No B-roll detected — talking head only.",
            fix="Add contextual B-roll every 5-8s to maintain visual interest.",
        )
    if coverage < MIN_BROLL_COVERAGE:
        return HealthCheck(
            name="B-Roll Coverage",
            status="info",
            icon="💡",
            message=f"B-roll coverage light ({broll_count} overlays).",
            fix="Consider adding 1-2 more B-roll clips for better visual pacing.",
        )
    return HealthCheck(
        name="B-Roll Coverage",
        status="pass",
        icon="✅",
        message=f"Good B-roll coverage ({broll_count} overlays).",
    )


def check_captions(has_subtitles: bool) -> HealthCheck:
    if not has_subtitles:
        return HealthCheck(
            name="Captions",
            status="fail",
            icon="❌",
            message="No captions detected — 85% of TikTok is watched without sound.",
            fix="Generate word-level karaoke captions before publishing.",
        )
    return HealthCheck(
        name="Captions",
        status="pass",
        icon="✅",
        message="Captions present — viewers can follow without sound.",
    )


def check_hashtags(hashtag_count: int) -> HealthCheck:
    if hashtag_count == 0:
        return HealthCheck(
            name="Hashtags",
            status="warn",
            icon="⚠️",
            message="No hashtags generated.",
            fix="Add 5-10 niche + trending hashtags to help the algorithm distribute the clip.",
        )
    if hashtag_count < 5:
        return HealthCheck(
            name="Hashtags",
            status="info",
            icon="💡",
            message=f"Only {hashtag_count} hashtag(s) — add more for wider reach.",
            fix="Target 8-12 hashtags: 3 niche-specific, 3 trending, 2 broad.",
        )
    return HealthCheck(
        name="Hashtags",
        status="pass",
        icon="✅",
        message=f"{hashtag_count} hashtags ready.",
    )


def check_thumbnail(thumbnail_path: Optional[str]) -> HealthCheck:
    if not thumbnail_path:
        return HealthCheck(
            name="Thumbnail",
            status="warn",
            icon="⚠️",
            message="No thumbnail selected.",
            fix="Generate a hook-text thumbnail with bold callout text for higher CTR.",
        )
    return HealthCheck(
        name="Thumbnail",
        status="pass",
        icon="✅",
        message="Thumbnail selected.",
    )


# ── New checks: B-roll duration, B-roll density, voice RMS, BGM presence ─────

def check_broll_min_duration(
    broll_durations: Optional[list[float]] = None,
) -> HealthCheck:
    """Check that all B-roll overlays meet the minimum duration threshold."""
    if not broll_durations:
        return HealthCheck(
            name="B-Roll Min Duration",
            status="info",
            icon="💡",
            message="No B-roll durations provided — skipping check.",
        )
    short = [d for d in broll_durations if d < MIN_BROLL_DURATION_S]
    if short:
        return HealthCheck(
            name="B-Roll Min Duration",
            status="fail",
            icon="❌",
            message=f"{len(short)} B-roll overlay(s) shorter than {MIN_BROLL_DURATION_S}s minimum.",
            fix="Increase B-roll overlay duration to at least 1.5s for viewer comprehension.",
        )
    return HealthCheck(
        name="B-Roll Min Duration",
        status="pass",
        icon="✅",
        message=f"All {len(broll_durations)} B-roll overlays meet minimum duration ({MIN_BROLL_DURATION_S}s).",
    )


def check_broll_density(broll_count: int, duration: float) -> HealthCheck:
    """Check that B-roll density is not absurd (max per 10s)."""
    if broll_count == 0:
        return HealthCheck(
            name="B-Roll Density",
            status="info",
            icon="💡",
            message="No B-roll to check density.",
        )
    max_allowed = max(1, int(duration / 10.0) * MAX_BROLL_PER_10S)
    if broll_count > max_allowed:
        return HealthCheck(
            name="B-Roll Density",
            status="warn",
            icon="⚠️",
            message=f"{broll_count} B-roll overlays in {duration:.0f}s clip (max {max_allowed} recommended).",
            fix=f"Reduce to ≤{max_allowed} B-roll overlays to avoid visual clutter.",
        )
    return HealthCheck(
        name="B-Roll Density",
        status="pass",
        icon="✅",
        message=f"B-roll density ({broll_count} in {duration:.0f}s) within limits.",
    )


def check_voice_presence(voice_rms_db: Optional[float] = None) -> HealthCheck:
    """Check that voice track is present and above minimum RMS threshold."""
    if voice_rms_db is None:
        return HealthCheck(
            name="Voice Presence",
            status="info",
            icon="💡",
            message="Voice RMS not measured — skipping check.",
        )
    if voice_rms_db < MIN_VOICE_RMS_DB:
        return HealthCheck(
            name="Voice Presence",
            status="fail",
            icon="❌",
            message=f"Voice RMS at {voice_rms_db:.1f}dB — too quiet (min {MIN_VOICE_RMS_DB}dB).",
            fix="Apply voice normalization (target -16 LUFS) and boost by 3-6dB.",
        )
    return HealthCheck(
        name="Voice Presence",
        status="pass",
        icon="✅",
        message=f"Voice track present at {voice_rms_db:.1f}dB RMS — good level.",
    )


def check_bgm_presence(
    bgm_applied: bool,
    bgm_enabled_flag: bool = True,
) -> HealthCheck:
    """Check that BGM was applied when expected."""
    if not bgm_enabled_flag:
        return HealthCheck(
            name="BGM Presence",
            status="info",
            icon="💡",
            message="BGM disabled by flag — skipping check.",
        )
    if not bgm_applied:
        return HealthCheck(
            name="BGM Presence",
            status="warn",
            icon="⚠️",
            message="No background music applied — clip may feel flat.",
            fix="Enable BGM_ENABLED=true and ensure a music track is available.",
        )
    return HealthCheck(
        name="BGM Presence",
        status="pass",
        icon="✅",
        message="Background music applied — enhances viewer retention.",
    )


# ── Main entry ────────────────────────────────────────────────────────────────

def generate_health_report(
    clip_id: str,
    virality_score: float = 0.0,
    hook_score: Optional[float] = None,
    hook_start: Optional[float] = None,
    hook_type: Optional[str] = None,
    duration: float = 30.0,
    platform: str = "tiktok",
    loudnorm_applied: bool = False,
    sfx_injected: bool = False,
    audio_energy: Optional[float] = None,
    broll_count: int = 0,
    has_subtitles: bool = False,
    hashtag_count: int = 0,
    thumbnail_path: Optional[str] = None,
    zoom_punch_applied: bool = False,
    # ── New QA params ────────────────────────────────────────────────────
    broll_durations: Optional[list[float]] = None,
    voice_rms_db: Optional[float] = None,
    bgm_applied: bool = False,
    bgm_enabled_flag: bool = True,
    # ── Sanity check flags (from QA module) ──────────────────────────────
    sanity_subtitles_ok: Optional[bool] = None,
    sanity_broll_diversity_ok: Optional[bool] = None,
    sanity_framing_ok: Optional[bool] = None,
    sanity_audio_ok: Optional[bool] = None,
    # ── Source subtitle detection flags ──────────────────────────────────
    source_burned_subtitles_detected: Optional[bool] = None,
    source_subtitles_band: Optional[str] = None,
) -> ClipHealthReport:
    checks: list[HealthCheck] = [
        check_hook_presence(hook_score, hook_start, hook_type),
        check_duration(duration, platform),
        check_virality_score(virality_score),
        check_audio_quality(loudnorm_applied, sfx_injected, audio_energy),
        check_broll_coverage(broll_count, duration),
        check_captions(has_subtitles),
        check_hashtags(hashtag_count),
        check_thumbnail(thumbnail_path),
        check_broll_min_duration(broll_durations),
        check_broll_density(broll_count, duration),
        check_voice_presence(voice_rms_db),
        check_bgm_presence(bgm_applied, bgm_enabled_flag),
    ]

    # Zoom punch bonus info
    if zoom_punch_applied:
        checks.append(HealthCheck(
            name="Visual Effects",
            status="pass",
            icon="✅",
            message="Zoom punch applied at audio peaks — boosts perceived energy.",
        ))

    # ── Sanity check flags ────────────────────────────────────────────────
    if sanity_subtitles_ok is not None:
        checks.append(HealthCheck(
            name="QA: Triple Subtitles",
            status="pass" if sanity_subtitles_ok else "fail",
            icon="✅" if sanity_subtitles_ok else "❌",
            message="No triple-subtitle issue detected." if sanity_subtitles_ok
            else "Triple-subtitle risk detected — check embedded streams and burned-in overlays.",
            fix="Ensure only one subtitle stream is embedded; disable burned-in subtitles if embedded streams exist.",
        ))

    if sanity_broll_diversity_ok is not None:
        checks.append(HealthCheck(
            name="QA: B-Roll Diversity",
            status="pass" if sanity_broll_diversity_ok else "warn",
            icon="✅" if sanity_broll_diversity_ok else "⚠️",
            message="Good B-roll source diversity." if sanity_broll_diversity_ok
            else "Low B-roll diversity — consider adding more unique sources.",
            fix="Increase B-roll source variety from Pexels or AI generation.",
        ))

    if sanity_framing_ok is not None:
        checks.append(HealthCheck(
            name="QA: Stable Framing",
            status="pass" if sanity_framing_ok else "fail",
            icon="✅" if sanity_framing_ok else "❌",
            message="Framing is stable." if sanity_framing_ok
            else "Excessive jitter detected — camera shake or unstable framing.",
            fix="Apply video stabilization or reduce impact zoom aggressiveness.",
        ))

    if sanity_audio_ok is not None:
        checks.append(HealthCheck(
            name="QA: Audio Sync & Loudness",
            status="pass" if sanity_audio_ok else "fail",
            icon="✅" if sanity_audio_ok else "❌",
            message="Audio sync and loudness within acceptable range." if sanity_audio_ok
            else "Audio issues detected — desync >100ms or loudness outside [-15, -13] LUFS.",
            fix="Verify loudnorm is applied (target -14 LUFS) and check audio-video sync in rendering pipeline.",
        ))

    # ── Source subtitle detection ─────────────────────────────────────────
    if source_burned_subtitles_detected is not None:
        if source_burned_subtitles_detected:
            band_desc = f" in {source_subtitles_band}" if source_subtitles_band else ""
            checks.append(HealthCheck(
                name="Source: Burned-in Subtitles",
                status="warn",
                icon="⚠️",
                message=f"Burned-in subtitles detected{band_desc} — may clash with ViraClip captions.",
                fix="Captions will be shifted upward or disabled to avoid double-subtitle clutter.",
            ))
        else:
            checks.append(HealthCheck(
                name="Source: Burned-in Subtitles",
                status="pass",
                icon="✅",
                message="No significant burned-in subtitles detected in source video.",
            ))

    score = _score_from_checks(checks)
    grade = _grade(score)

    # Find top fix (first fail, then first warn)
    top_fix = ""
    for status in ("fail", "warn"):
        for c in checks:
            if c.status == status and c.fix:
                top_fix = c.fix
                break
        if top_fix:
            break

    fails = sum(1 for c in checks if c.status == "fail")
    warns = sum(1 for c in checks if c.status == "warn")
    passes = sum(1 for c in checks if c.status == "pass")

    summary = (
        f"Grade {grade} ({score:.0f}/100) — "
        f"{passes} passing, {warns} warnings, {fails} critical issues."
    )

    return ClipHealthReport(
        clip_id=clip_id,
        overall_score=score,
        grade=grade,
        checks=checks,
        summary=summary,
        top_fix=top_fix,
    )
