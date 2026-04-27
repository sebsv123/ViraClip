"""
Master Director — Top-level intelligent edit orchestrator.

Produces a single `RenderDecisionPlan` per clip that drives EVERY downstream
effect with section-aware precision.

Where the existing systems decide things at clip-level (one zoom intensity,
one LUT, one BGM track for the whole clip), the Director slices the clip into
4 narrative sections (hook / build / payoff / cta) and assigns DIFFERENT
treatment to each — so the hook punches, the build sustains, the payoff
delivers, and the CTA fades cleanly.

It REUSES (does not replace):
  - EditorialBrain.analyze_clip → category + NarrativeStructure
  - clip_intelligence.build_clip_profile → ClipProfile
  - SemanticEditPlanner.plan       → BrollCue + SfxCue + ZoomCue (word-level)

It ADDS:
  - SectionDecision per section with overrides for visual / captions / cuts /
    SFX / B-roll
  - Hook reorder flag (consumed by hook_reorder service)
  - BGM energy curve (consumed by BGM service)
  - Platform overrides (TikTok / Reels / Shorts)

The renderer reads `RenderDecisionPlan.sections` and applies the per-section
overrides at every relevant pipeline step.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class SectionDecision:
    """Editing decisions for one narrative section of a clip."""
    name:    str            # "hook" | "build" | "payoff" | "cta"
    t_start: float          # seconds, inclusive
    t_end:   float          # seconds, exclusive

    # ── Visual look (multipliers on top of ClipProfile base values) ──────────
    saturation_mult: float = 1.00   # 0.80–1.30
    contrast_mult:   float = 1.00   # 0.80–1.30
    vignette:        float = 0.20   # 0.00–0.45
    grain_mult:      float = 1.00   # 0.50–1.50

    # ── Captions ────────────────────────────────────────────────────────────
    caption_color:     str   = "white"        # white | yellow | neon_pink | red
    caption_animation: str   = "static"       # static | bounce | shake | scale_in
    caption_size_mult: float = 1.00           # 0.85–1.20

    # ── Cuts & motion ───────────────────────────────────────────────────────
    zoom_factor_max: float = 1.10   # cap on zoom intensity in this section
    cut_rhythm:      str   = "medium"  # fast | medium | slow
    flash_allowed:   bool  = False
    flash_intensity: float = 0.15   # 0.05–0.30 (when allowed)

    # ── SFX ────────────────────────────────────────────────────────────────
    sfx_volume_mult: float        = 1.00      # 0.0–1.5
    allowed_sfx:     List[str]    = field(default_factory=list)
    forbidden_sfx:   List[str]    = field(default_factory=list)

    # ── B-roll ──────────────────────────────────────────────────────────────
    broll_allowed:   bool  = True
    broll_max:       int   = 1
    broll_intensity: float = 0.95   # opacity of overlay

    # ── Trazabilidad ────────────────────────────────────────────────────────
    rationale: str = ""


@dataclass
class RenderDecisionPlan:
    """Complete edit plan for a clip — drives every render step."""
    # Foundation (reused from existing systems)
    category:      str
    duration:      float
    profile:       Any                              # ClipProfile (avoid circular import)
    narrative:     Any                              # NarrativeStructure
    semantic_plan: Any                              # SemanticEditPlan

    # Section-aware decisions
    sections: List[SectionDecision] = field(default_factory=list)

    # Hook reorder
    hook_reorder:   bool  = False
    hook_source_t:  float = 0.0
    hook_target_t:  float = 0.0

    # BGM curve
    bgm_track_id:     str          = ""
    bgm_energy_curve: List[float]  = field(default_factory=list)
    bgm_volume_curve: List[float]  = field(default_factory=list)

    # Platform
    platform:           str            = "universal"
    platform_overrides: Dict[str, Any] = field(default_factory=dict)

    # Audit
    director_source:     str       = "rules"        # rules | groq | hybrid
    director_latency_ms: int       = 0
    decision_log:        List[str] = field(default_factory=list)

    # ── Helpers consumed by the renderer ────────────────────────────────────
    def section_at(self, t: float) -> Optional[SectionDecision]:
        """Return the section that contains timestamp `t` (or None)."""
        for s in self.sections:
            if s.t_start <= t < s.t_end:
                return s
        return self.sections[-1] if self.sections else None

    def sfx_volume_at(self, t: float) -> float:
        """Volume multiplier for an SFX cue at timestamp `t`."""
        sec = self.section_at(t)
        return sec.sfx_volume_mult if sec else 1.0

    def is_sfx_allowed_at(self, sfx_type: str, t: float) -> bool:
        """Whether a given SFX type may fire at this timestamp."""
        sec = self.section_at(t)
        if not sec:
            return True
        if sfx_type in sec.forbidden_sfx:
            return False
        if sec.allowed_sfx and sfx_type not in sec.allowed_sfx:
            return False
        return True

    def is_broll_allowed_at(self, t: float) -> bool:
        sec = self.section_at(t)
        return bool(sec and sec.broll_allowed)


# ── Category × Section rule matrix ───────────────────────────────────────────
#
# Each entry is keyed by (category_key, section_name). Missing entries fall back
# to the universal defaults defined in `_UNIVERSAL_*`.
#
# Categories grouped to keep the table readable:
#   • HIGH_ENERGY: comedy, fitness, gaming, motivation, travel
#   • EDUCATIONAL: finance, tech, education, business
#   • CALM:        drama, health, news, lifestyle, beauty, cooking, relationship

_HIGH_ENERGY  = {"comedy_entertainment", "fitness_workout", "gaming",
                 "motivation_mindset", "travel_adventure"}
_EDUCATIONAL  = {"finance_investing", "tech_review", "education_tutorial",
                 "business_entrepreneur"}
_CALM         = {"drama_storytelling", "health_wellness", "news_commentary",
                 "lifestyle_vlog", "beauty_fashion", "cooking_food",
                 "relationship_social"}


# Universal fallbacks per section — the absolute defaults
_UNIVERSAL_HOOK = SectionDecision(
    name="hook", t_start=0.0, t_end=0.0,
    saturation_mult=1.10, contrast_mult=1.05, vignette=0.15, grain_mult=1.00,
    caption_color="yellow", caption_animation="scale_in", caption_size_mult=1.10,
    zoom_factor_max=1.15, cut_rhythm="fast", flash_allowed=True, flash_intensity=0.18,
    sfx_volume_mult=1.20,
    allowed_sfx=["scroll_stop", "curiosity_gap", "pattern_interrupt",
                 "whoosh_zoom", "magic_reveal", "glitch_burst"],
    forbidden_sfx=["bass_drop", "camera_shutter"],
    broll_allowed=False, broll_max=0, broll_intensity=0.0,
    rationale="Hook must grab attention — bright captions, zoom punch, no B-roll",
)

_UNIVERSAL_BUILD = SectionDecision(
    name="build", t_start=0.0, t_end=0.0,
    saturation_mult=1.00, contrast_mult=1.00, vignette=0.20, grain_mult=1.00,
    caption_color="white", caption_animation="static", caption_size_mult=1.00,
    zoom_factor_max=1.10, cut_rhythm="medium", flash_allowed=False, flash_intensity=0.10,
    sfx_volume_mult=0.85,
    allowed_sfx=["camera_shutter", "pop_broll", "transition", "emphasis_word",
                 "notification", "whoosh_zoom"],
    forbidden_sfx=["bass_drop", "magic_reveal"],
    broll_allowed=True, broll_max=2, broll_intensity=0.95,
    rationale="Build sustains attention — neutral look, B-roll for visual relief",
)

_UNIVERSAL_PAYOFF = SectionDecision(
    name="payoff", t_start=0.0, t_end=0.0,
    saturation_mult=1.20, contrast_mult=1.10, vignette=0.10, grain_mult=1.10,
    caption_color="neon_pink", caption_animation="bounce", caption_size_mult=1.15,
    zoom_factor_max=1.18, cut_rhythm="medium", flash_allowed=True, flash_intensity=0.20,
    sfx_volume_mult=1.35,
    allowed_sfx=["magic_reveal", "insight_reveal", "riser_pre_reveal",
                 "bass_drop", "cliffhanger", "whoosh_zoom", "emphasis_word"],
    forbidden_sfx=[],
    broll_allowed=True, broll_max=1, broll_intensity=0.90,
    rationale="Payoff delivers max impact — zoom, flash, riser+drop combo",
)

_UNIVERSAL_CTA = SectionDecision(
    name="cta", t_start=0.0, t_end=0.0,
    saturation_mult=0.95, contrast_mult=0.95, vignette=0.30, grain_mult=0.90,
    caption_color="white", caption_animation="static", caption_size_mult=0.95,
    zoom_factor_max=1.00, cut_rhythm="medium", flash_allowed=False, flash_intensity=0.10,
    sfx_volume_mult=0.50,
    allowed_sfx=["transition", "whoosh_zoom"],
    forbidden_sfx=["scroll_stop", "pattern_interrupt", "bass_drop", "magic_reveal",
                   "insight_reveal", "riser_pre_reveal", "cliffhanger", "glitch_burst"],
    broll_allowed=False, broll_max=0, broll_intensity=0.0,
    rationale="CTA fades clean — minimal SFX, no new B-roll, no flash",
)


def _category_overrides(category: str, section_name: str) -> Dict[str, Any]:
    """Per-(category, section) overrides on top of the universal default."""
    if section_name == "hook":
        if category in _HIGH_ENERGY:
            return dict(saturation_mult=1.20, zoom_factor_max=1.18,
                        flash_intensity=0.22, sfx_volume_mult=1.30,
                        caption_animation="bounce")
        if category in _EDUCATIONAL:
            return dict(saturation_mult=1.05, zoom_factor_max=1.10,
                        flash_allowed=False, sfx_volume_mult=1.10,
                        caption_animation="static", caption_color="white")
        if category in _CALM:
            return dict(saturation_mult=1.00, zoom_factor_max=1.08,
                        flash_allowed=False, sfx_volume_mult=1.05,
                        caption_animation="static", caption_color="white",
                        cut_rhythm="slow")
    elif section_name == "payoff":
        if category in _HIGH_ENERGY:
            return dict(saturation_mult=1.30, zoom_factor_max=1.20,
                        flash_intensity=0.22, sfx_volume_mult=1.40,
                        caption_animation="shake")
        if category in _EDUCATIONAL:
            return dict(saturation_mult=1.10, zoom_factor_max=1.12,
                        flash_intensity=0.12, sfx_volume_mult=1.20,
                        caption_animation="bounce")
        if category in _CALM:
            return dict(saturation_mult=1.05, zoom_factor_max=1.10,
                        flash_allowed=False, sfx_volume_mult=1.15,
                        caption_animation="static")
    elif section_name == "cta":
        # CTA is universally clean — no category override needed
        return {}
    elif section_name == "build":
        if category in _HIGH_ENERGY:
            return dict(cut_rhythm="fast", sfx_volume_mult=0.95)
        if category in _CALM:
            return dict(cut_rhythm="slow", sfx_volume_mult=0.75)
    return {}


# ── Section builder ──────────────────────────────────────────────────────────

def _build_sections(
    duration:  float,
    narrative: Any,
    category:  str,
) -> List[SectionDecision]:
    """
    Slice the clip into 4 sections using NarrativeStructure boundaries and
    apply (category × section) rule overrides.

    For very short clips (<8s) we collapse to 2 sections (hook + payoff).
    """
    # Boundaries
    if duration < 8.0:
        # Two-section mode for tiny clips
        hook_end = round(duration * 0.40, 2)
        boundaries = [
            ("hook",    0.0,        hook_end),
            ("payoff",  hook_end,   duration),
        ]
    else:
        h_end = float(getattr(narrative, "hook_end",     duration * 0.15))
        b_end = float(getattr(narrative, "build_end",    duration * 0.65))
        c_st  = float(getattr(narrative, "cta_start",    duration * 0.90))
        # Guard rails
        h_end = max(1.0, min(h_end, duration * 0.30))
        b_end = max(h_end + 1.0, min(b_end, duration * 0.85))
        c_st  = max(b_end + 0.5, min(c_st, duration - 0.5))
        boundaries = [
            ("hook",    0.0,    h_end),
            ("build",   h_end,  b_end),
            ("payoff",  b_end,  c_st),
            ("cta",     c_st,   duration),
        ]

    # Build SectionDecision list with universal defaults + category overrides
    universal_map = {
        "hook":   _UNIVERSAL_HOOK,
        "build":  _UNIVERSAL_BUILD,
        "payoff": _UNIVERSAL_PAYOFF,
        "cta":    _UNIVERSAL_CTA,
    }
    sections: List[SectionDecision] = []
    for name, t0, t1 in boundaries:
        base    = universal_map[name]
        overrides = _category_overrides(category, name)
        sections.append(SectionDecision(
            name=name, t_start=round(t0, 2), t_end=round(t1, 2),
            saturation_mult   = overrides.get("saturation_mult",   base.saturation_mult),
            contrast_mult     = overrides.get("contrast_mult",     base.contrast_mult),
            vignette          = overrides.get("vignette",          base.vignette),
            grain_mult        = overrides.get("grain_mult",        base.grain_mult),
            caption_color     = overrides.get("caption_color",     base.caption_color),
            caption_animation = overrides.get("caption_animation", base.caption_animation),
            caption_size_mult = overrides.get("caption_size_mult", base.caption_size_mult),
            zoom_factor_max   = overrides.get("zoom_factor_max",   base.zoom_factor_max),
            cut_rhythm        = overrides.get("cut_rhythm",        base.cut_rhythm),
            flash_allowed     = overrides.get("flash_allowed",     base.flash_allowed),
            flash_intensity   = overrides.get("flash_intensity",   base.flash_intensity),
            sfx_volume_mult   = overrides.get("sfx_volume_mult",   base.sfx_volume_mult),
            allowed_sfx       = list(base.allowed_sfx),
            forbidden_sfx     = list(base.forbidden_sfx),
            broll_allowed     = overrides.get("broll_allowed",     base.broll_allowed),
            broll_max         = overrides.get("broll_max",         base.broll_max),
            broll_intensity   = overrides.get("broll_intensity",   base.broll_intensity),
            rationale         = f"{category}/{name}: {base.rationale}",
        ))
    return sections


# ── BGM energy curve ─────────────────────────────────────────────────────────

def _build_bgm_curve(sections: List[SectionDecision]) -> Tuple[List[float], List[float]]:
    """
    Produce two 5-point curves (at 0/25/50/75/100% of clip):
      energy_curve  → conceptual energy (used by BGM track selector)
      volume_curve  → BGM volume automation (ducked under voice in hook+CTA)
    """
    if not sections:
        return [0.5, 0.5, 0.5, 0.5, 0.5], [0.6, 0.6, 0.6, 0.6, 0.6]

    duration  = sections[-1].t_end
    samples_t = [duration * f for f in (0.0, 0.25, 0.50, 0.75, 1.0)]

    energy: List[float] = []
    volume: List[float] = []
    for t in samples_t:
        # Find the section at this timestamp
        sec = next((s for s in sections if s.t_start <= t < s.t_end), sections[-1])
        # Energy proxy: derived from sat_mult + sfx_vol_mult
        e = (sec.saturation_mult - 0.95) * 1.5 + (sec.sfx_volume_mult - 0.5) * 0.5
        energy.append(round(max(0.1, min(1.0, e)), 2))
        # Volume: duck under voice in hook (0.35) and cta (0.45), normal in build (0.55), peak in payoff (0.65)
        vol_table = {"hook": 0.40, "build": 0.55, "payoff": 0.65, "cta": 0.45}
        volume.append(vol_table.get(sec.name, 0.55))
    return energy, volume


# ── Hook reorder evaluation ──────────────────────────────────────────────────

def _evaluate_hook_reorder(
    duration: float,
    segment:  Dict[str, Any],
    words:    Optional[List[Dict[str, Any]]],
) -> Tuple[bool, float, float]:
    """
    Decide whether to reorder the hook. Uses HookEngine when available.
    Returns (should_reorder, source_t, target_t).
    """
    if not words or duration < 10.0:
        return False, 0.0, 0.0
    try:
        from ..domains.virality.hook_engine import get_hook_engine
        result = get_hook_engine().find_best_hook(words=words, segment_duration=duration)
        if result.reorder and result.hook_score >= 0.85:
            # Cap how far we move (don't reorder >8s of content)
            if 3.0 <= result.hook_start <= 8.0:
                return True, float(result.hook_start), 0.5
    except Exception as exc:
        logger.debug("[Director] hook reorder evaluation failed: %s", exc)
    return False, 0.0, 0.0


# ── Platform overrides ───────────────────────────────────────────────────────

_PLATFORM_PROFILES: Dict[str, Dict[str, float]] = {
    "tiktok": {
        "saturation_global":   1.05,   # extra saturation everywhere
        "cut_rhythm_bias":     1.10,   # faster cuts
        "sfx_volume_global":   1.05,
        "caption_size_global": 1.05,
    },
    "reels": {
        "saturation_global":   1.00,
        "cut_rhythm_bias":     1.00,
        "sfx_volume_global":   1.00,
        "caption_size_global": 1.00,
    },
    "shorts": {
        "saturation_global":   0.97,   # slightly cleaner look
        "cut_rhythm_bias":     0.95,   # slightly less aggressive
        "sfx_volume_global":   0.95,
        "caption_size_global": 0.97,
    },
    "universal": {
        "saturation_global":   1.00,
        "cut_rhythm_bias":     1.00,
        "sfx_volume_global":   1.00,
        "caption_size_global": 1.00,
    },
}


def _apply_platform_overrides(
    sections: List[SectionDecision], platform: str,
) -> Dict[str, Any]:
    """Apply platform-specific multipliers to all sections in-place."""
    overrides = _PLATFORM_PROFILES.get(platform, _PLATFORM_PROFILES["universal"])
    for s in sections:
        s.saturation_mult   = round(s.saturation_mult   * overrides["saturation_global"],   3)
        s.sfx_volume_mult   = round(s.sfx_volume_mult   * overrides["sfx_volume_global"],   3)
        s.caption_size_mult = round(s.caption_size_mult * overrides["caption_size_global"], 3)
    return overrides


# ── Master Director orchestrator ─────────────────────────────────────────────

class MasterDirector:
    """
    Top-level intelligent edit orchestrator.

    Usage:
        plan = await MasterDirector().direct(
            segment, words, duration, category, narrative, profile,
            semantic_plan, platform="tiktok",
        )
    """

    async def direct(
        self,
        segment:       Dict[str, Any],
        words:         Optional[List[Dict[str, Any]]],
        duration:      float,
        category:      str,
        narrative:     Any,
        profile:       Any,
        semantic_plan: Any,
        platform:      str = "universal",
    ) -> RenderDecisionPlan:
        """
        Build a complete RenderDecisionPlan.

        Never raises — always returns a valid plan (rule-based fallback).
        """
        t0 = time.monotonic()
        decision_log: List[str] = []

        # 1. Section breakdown with category × section rules
        sections = _build_sections(duration, narrative, category)
        decision_log.append(
            f"Sections: " + " | ".join(
                f"{s.name}@{s.t_start:.1f}-{s.t_end:.1f}s" for s in sections
            )
        )

        # 2. Platform overrides
        platform_overrides = _apply_platform_overrides(sections, platform)
        if platform != "universal":
            decision_log.append(f"Platform={platform} overrides applied")

        # 3. BGM energy curve
        energy_curve, volume_curve = _build_bgm_curve(sections)
        decision_log.append(
            f"BGM curve: e={energy_curve} v={volume_curve}"
        )

        # 4. Hook reorder evaluation
        reorder, source_t, target_t = _evaluate_hook_reorder(duration, segment, words)
        if reorder:
            decision_log.append(
                f"Hook reorder: move t={source_t:.1f}s → t={target_t:.1f}s"
            )

        # 5. Optional Groq refinement (skipped for now, keeps director sub-50ms)
        director_source = "rules"

        latency_ms = int((time.monotonic() - t0) * 1000)
        plan = RenderDecisionPlan(
            category=category,
            duration=duration,
            profile=profile,
            narrative=narrative,
            semantic_plan=semantic_plan,
            sections=sections,
            hook_reorder=reorder,
            hook_source_t=source_t,
            hook_target_t=target_t,
            bgm_track_id="",
            bgm_energy_curve=energy_curve,
            bgm_volume_curve=volume_curve,
            platform=platform,
            platform_overrides=platform_overrides,
            director_source=director_source,
            director_latency_ms=latency_ms,
            decision_log=decision_log,
        )
        logger.info(
            "[Director] category=%s platform=%s sections=%d hook_reorder=%s "
            "latency=%dms",
            category, platform, len(sections), reorder, latency_ms,
        )
        return plan
