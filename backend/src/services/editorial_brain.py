"""
Editorial Brain — Content-Specialized Video Editing Intelligence
================================================================
A professional editor doesn't apply the same settings to every clip.
A fitness clip is edited differently from a finance tutorial, which is
edited differently from a comedy skit.

This module encodes that expert knowledge:
  1. CATEGORY_RULES  — 15+ content categories, each with precise
                        editing conventions (LUT, rhythm, caption, music,
                        B-roll themes, grain, zoom style, flash policy).
  2. categorize_clip  — identifies content category from text.
  3. NarrativeStructure — maps hook / build / payoff / CTA across the clip.
  4. apply_category_rules — merges category expertise into a ClipProfile.

The output drives EVERY downstream effect: colour grade, music, B-roll
keyword selection, zoom aggressiveness, caption style, SFX timing.
"""
from __future__ import annotations

import logging
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# 1. CONTENT CATEGORY KNOWLEDGE BASE
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class CategoryRule:
    """Expert editing conventions for one content category."""
    name:            str
    lut:             str            # FFmpeg LUT preset
    caption_style:   str            # ASS style
    bgm_category:    str            # BeatSyncService category
    zoom_intensity:  str            # off | subtle | medium | strong
    saturation:      float          # 1.0 – 1.5
    contrast:        float          # 1.0 – 1.3
    grain:           int            # film grain 0-30
    cut_rhythm:      str            # fast | medium | slow
    flash_allowed:   bool
    hook_zoom:       bool           # extra punch at t=0
    broll_themes:    List[str]      # B-roll visual search terms
    mood:            str            # energetic | dramatic | warm | chill | educational | inspirational
    sfx_emphasis:    str


CATEGORY_RULES: Dict[str, CategoryRule] = {

    "fitness_workout": CategoryRule(
        name="Fitness / Workout",
        lut="warm_film", caption_style="tiktok", bgm_category="hype",
        zoom_intensity="strong", saturation=1.42, contrast=1.22, grain=8,
        cut_rhythm="fast", flash_allowed=True, hook_zoom=True,
        broll_themes=["gym workout", "running athlete", "weight training",
                      "fitness motivation", "muscles", "sweat"],
        mood="energetic", sfx_emphasis="scroll_stop",
    ),

    "finance_investing": CategoryRule(
        name="Finance / Investing",
        lut="cold_blue", caption_style="minimal", bgm_category="midtempo",
        zoom_intensity="subtle", saturation=1.08, contrast=1.06, grain=3,
        cut_rhythm="medium", flash_allowed=False, hook_zoom=False,
        broll_themes=["stock market chart", "money cash", "laptop office",
                      "financial data", "investment portfolio", "bank"],
        mood="educational", sfx_emphasis="insight_reveal",
    ),

    "comedy_entertainment": CategoryRule(
        name="Comedy / Entertainment",
        lut="vintage", caption_style="neon", bgm_category="upbeat",
        zoom_intensity="strong", saturation=1.38, contrast=1.18, grain=12,
        cut_rhythm="fast", flash_allowed=True, hook_zoom=True,
        broll_themes=["laughter funny", "comedy reaction", "entertainment",
                      "surprised face", "meme culture"],
        mood="energetic", sfx_emphasis="pattern_interrupt",
    ),

    "education_tutorial": CategoryRule(
        name="Education / Tutorial",
        lut="flat", caption_style="karaoke", bgm_category="midtempo",
        zoom_intensity="subtle", saturation=1.12, contrast=1.05, grain=2,
        cut_rhythm="medium", flash_allowed=False, hook_zoom=False,
        broll_themes=["learning study", "classroom whiteboard", "books knowledge",
                      "computer screen", "tutorial step by step"],
        mood="educational", sfx_emphasis="curiosity_gap",
    ),

    "motivation_mindset": CategoryRule(
        name="Motivation / Mindset",
        lut="warm_film", caption_style="tiktok", bgm_category="upbeat",
        zoom_intensity="medium", saturation=1.30, contrast=1.12, grain=6,
        cut_rhythm="medium", flash_allowed=True, hook_zoom=True,
        broll_themes=["success achievement", "sunrise mountains", "determination",
                      "goal setting", "winner champion", "positive mindset"],
        mood="inspirational", sfx_emphasis="scroll_stop",
    ),

    "lifestyle_vlog": CategoryRule(
        name="Lifestyle / Vlog",
        lut="warm_film", caption_style="tiktok", bgm_category="upbeat",
        zoom_intensity="subtle", saturation=1.22, contrast=1.08, grain=5,
        cut_rhythm="medium", flash_allowed=False, hook_zoom=False,
        broll_themes=["daily life routine", "coffee morning", "city lifestyle",
                      "friends social", "aesthetic interior"],
        mood="warm", sfx_emphasis="transition",
    ),

    "cooking_food": CategoryRule(
        name="Cooking / Food",
        lut="warm_film", caption_style="karaoke", bgm_category="upbeat",
        zoom_intensity="subtle", saturation=1.35, contrast=1.10, grain=4,
        cut_rhythm="medium", flash_allowed=False, hook_zoom=False,
        broll_themes=["food cooking", "ingredients recipe", "restaurant kitchen",
                      "delicious meal", "chef cooking"],
        mood="warm", sfx_emphasis="insight_reveal",
    ),

    "travel_adventure": CategoryRule(
        name="Travel / Adventure",
        lut="teal_orange", caption_style="tiktok", bgm_category="upbeat",
        zoom_intensity="medium", saturation=1.38, contrast=1.15, grain=6,
        cut_rhythm="medium", flash_allowed=True, hook_zoom=True,
        broll_themes=["landscape nature", "travel destination", "adventure outdoor",
                      "airplane flight", "exotic location", "backpacker"],
        mood="energetic", sfx_emphasis="scroll_stop",
    ),

    "tech_review": CategoryRule(
        name="Tech / Review",
        lut="cold_blue", caption_style="minimal", bgm_category="midtempo",
        zoom_intensity="subtle", saturation=1.10, contrast=1.07, grain=2,
        cut_rhythm="medium", flash_allowed=False, hook_zoom=False,
        broll_themes=["smartphone technology", "laptop gadget", "tech product",
                      "innovation future", "coding programming", "AI robot"],
        mood="educational", sfx_emphasis="insight_reveal",
    ),

    "drama_storytelling": CategoryRule(
        name="Drama / Storytelling",
        lut="cold_blue", caption_style="highlight", bgm_category="midtempo",
        zoom_intensity="medium", saturation=1.05, contrast=1.18, grain=18,
        cut_rhythm="slow", flash_allowed=False, hook_zoom=False,
        broll_themes=["cinematic drama", "emotional moment", "conflict tension",
                      "storytelling narrative", "dramatic scene"],
        mood="dramatic", sfx_emphasis="cliffhanger",
    ),

    "beauty_fashion": CategoryRule(
        name="Beauty / Fashion",
        lut="warm_film", caption_style="neon", bgm_category="upbeat",
        zoom_intensity="subtle", saturation=1.32, contrast=1.08, grain=4,
        cut_rhythm="medium", flash_allowed=True, hook_zoom=False,
        broll_themes=["fashion style makeup", "beauty products", "glamour",
                      "aesthetic outfit", "skincare routine"],
        mood="warm", sfx_emphasis="transition",
    ),

    "business_entrepreneur": CategoryRule(
        name="Business / Entrepreneur",
        lut="cold_blue", caption_style="minimal", bgm_category="midtempo",
        zoom_intensity="subtle", saturation=1.12, contrast=1.08, grain=3,
        cut_rhythm="medium", flash_allowed=False, hook_zoom=False,
        broll_themes=["business meeting office", "entrepreneur startup",
                      "success corporate", "strategy planning", "leadership"],
        mood="educational", sfx_emphasis="insight_reveal",
    ),

    "health_wellness": CategoryRule(
        name="Health / Wellness",
        lut="vintage", caption_style="minimal", bgm_category="slow",
        zoom_intensity="off", saturation=1.18, contrast=1.05, grain=5,
        cut_rhythm="slow", flash_allowed=False, hook_zoom=False,
        broll_themes=["meditation yoga", "healthy food", "nature wellness",
                      "mental health calm", "sleep rest", "mindfulness"],
        mood="chill", sfx_emphasis="transition",
    ),

    "gaming": CategoryRule(
        name="Gaming",
        lut="high_contrast", caption_style="neon", bgm_category="hype",
        zoom_intensity="strong", saturation=1.45, contrast=1.25, grain=6,
        cut_rhythm="fast", flash_allowed=True, hook_zoom=True,
        broll_themes=["video game gameplay", "gaming setup", "esports",
                      "controller console", "streaming gamer"],
        mood="energetic", sfx_emphasis="pattern_interrupt",
    ),

    "news_commentary": CategoryRule(
        name="News / Commentary",
        lut="flat", caption_style="highlight", bgm_category="midtempo",
        zoom_intensity="off", saturation=1.05, contrast=1.05, grain=1,
        cut_rhythm="medium", flash_allowed=False, hook_zoom=False,
        broll_themes=["news broadcast", "commentary opinion", "current events",
                      "political debate", "media journalism"],
        mood="educational", sfx_emphasis="curiosity_gap",
    ),

    "relationship_social": CategoryRule(
        name="Relationship / Social",
        lut="warm_film", caption_style="tiktok", bgm_category="upbeat",
        zoom_intensity="medium", saturation=1.28, contrast=1.10, grain=5,
        cut_rhythm="medium", flash_allowed=False, hook_zoom=False,
        broll_themes=["couple relationship", "friends social", "dating advice",
                      "communication people", "emotions feelings"],
        mood="warm", sfx_emphasis="insight_reveal",
    ),
}

# Default fallback category
_DEFAULT_CATEGORY = "motivation_mindset"


# ══════════════════════════════════════════════════════════════════════════════
# 2. KEYWORD-BASED CATEGORIZER (instant, no API needed)
# ══════════════════════════════════════════════════════════════════════════════

_CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "fitness_workout":     ["workout", "gym", "exercise", "fitness", "training",
                             "muscle", "cardio", "lifting", "squat", "run", "athlete"],
    "finance_investing":   ["invest", "stock", "money", "finance", "crypto", "trade",
                             "portfolio", "dividend", "market", "rich", "wealth", "bank"],
    "comedy_entertainment":["funny", "laugh", "joke", "comedy", "hilarious", "lol",
                             "meme", "skit", "prank", "entertain", "viral"],
    "education_tutorial":  ["learn", "tutorial", "how to", "explain", "step", "guide",
                             "teach", "understand", "lesson", "course", "study"],
    "motivation_mindset":  ["motivat", "mindset", "success", "goal", "dream", "believe",
                             "inspir", "achiev", "discipline", "grind", "hustle"],
    "lifestyle_vlog":      ["vlog", "lifestyle", "daily", "routine", "morning", "coffee",
                             "aesthetic", "day in", "apartment", "home"],
    "cooking_food":        ["cook", "recipe", "food", "ingredient", "eat", "chef",
                             "kitchen", "meal", "delicious", "taste", "restaurant"],
    "travel_adventure":    ["travel", "trip", "adventure", "destination", "explore",
                             "vacation", "country", "flight", "backpack", "tourist"],
    "tech_review":         ["tech", "iphone", "android", "laptop", "software", "app",
                             "gadget", "review", "coding", "program", "ai", "robot"],
    "drama_storytelling":  ["story", "drama", "emotional", "cried", "painful", "struggle",
                             "overcome", "truth", "confess", "experience"],
    "beauty_fashion":      ["beauty", "makeup", "skincare", "fashion", "outfit", "style",
                             "glam", "aesthetic", "look", "dress", "lipstick"],
    "business_entrepreneur":["business", "entrepreneur", "startup", "brand", "marketing",
                              "client", "product", "sales", "revenue", "company"],
    "health_wellness":     ["health", "wellness", "mental health", "anxiety", "meditation",
                             "yoga", "breathe", "stress", "therapy", "heal"],
    "gaming":              ["game", "gaming", "play", "console", "ps5", "xbox", "stream",
                             "gamer", "esport", "twitch", "minecraft", "fortnite"],
    "news_commentary":     ["news", "politics", "opinion", "commentary", "government",
                             "society", "issue", "problem", "debate", "media"],
    "relationship_social": ["relationship", "dating", "love", "couple", "friend",
                             "social", "toxic", "boundary", "partner", "marriage"],
}


def categorize_clip_from_keywords(text: str) -> str:
    """
    Fast keyword-based content categorization.
    Returns the category key with the most keyword hits.
    """
    low = text.lower()
    scores: Dict[str, int] = {}
    for cat, kws in _CATEGORY_KEYWORDS.items():
        scores[cat] = sum(1 for kw in kws if kw in low)

    best = max(scores, key=lambda c: scores[c])
    return best if scores[best] > 0 else _DEFAULT_CATEGORY


async def categorize_clip_with_ai(text: str, hook_type: str) -> Optional[str]:
    """
    Ask Groq to identify the content category for precise specialization.
    Returns None on failure — caller uses keyword fallback.
    """
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key or not text.strip():
        return None

    categories_list = " | ".join(CATEGORY_RULES.keys())
    prompt = (
        f"Identify the content category of this video transcript.\n"
        f"Transcript: \"{text[:400].replace(chr(34), chr(39))}\"\n"
        f"Hook type: {hook_type}\n\n"
        f"Return ONLY the category key from this list (nothing else):\n"
        f"{categories_list}"
    )

    try:
        import httpx
        async with httpx.AsyncClient(timeout=6.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}",
                          "Content-Type": "application/json"},
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 20,
                    "temperature": 0.1,
                },
            )
        if resp.status_code != 200:
            return None
        raw = resp.json()["choices"][0]["message"]["content"].strip().lower()
        # Extract the first matching category key
        for cat_key in CATEGORY_RULES:
            if cat_key in raw:
                return cat_key
        return None
    except Exception as exc:
        logger.debug("[EditorialBrain] category AI failed: %s", exc)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 3. NARRATIVE STRUCTURE ANALYZER
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class NarrativeStructure:
    """
    Temporal map of the clip's editorial arc.
    All values are seconds from clip start.
    """
    hook_end:      float       # End of opening hook (first ~15%)
    build_end:     float       # End of tension/build section (~65%)
    payoff_start:  float       # When the key insight/reveal lands (~65%)
    cta_start:     float       # Start of outro/call-to-action (~90%)
    duration:      float

    # Strategic effect timestamps derived from structure
    zoom_moments:  List[float] = field(default_factory=list)
    flash_moments: List[float] = field(default_factory=list)

    def describe(self) -> str:
        return (
            f"hook=0-{self.hook_end:.1f}s "
            f"build={self.hook_end:.1f}-{self.build_end:.1f}s "
            f"payoff={self.payoff_start:.1f}s "
            f"cta={self.cta_start:.1f}s"
        )


def analyze_narrative_structure(
    duration: float,
    words: Optional[List[Dict[str, Any]]] = None,
    text: str = "",
) -> NarrativeStructure:
    """
    Map the editorial arc of a clip.

    Uses word timestamps to find natural section boundaries.
    Falls back to duration-proportional split if no timestamps available.

    Sections:
      Hook    (0   → 15%): opening grab — applies hook zoom at 0s
      Build   (15% → 65%): context/tension — sustain interest
      Payoff  (65% → 90%): key insight/reveal — strategic zoom + flash
      CTA     (90% → end): outro — ease out, no flash
    """
    hook_end     = round(duration * 0.15, 2)
    build_end    = round(duration * 0.65, 2)
    payoff_start = build_end
    cta_start    = round(duration * 0.90, 2)

    # Refine payoff using high-impact words if timestamps are available
    _IMPACT_WORDS = {
        "secret", "reveal", "truth", "never", "always", "actually", "wrong",
        "mistake", "key", "reason", "because", "that's why", "finally",
        "real", "exposed", "shocking", "discovered", "changed", "proof",
    }
    if words:
        for w in words:
            w_text = (w.get("word") or w.get("text") or "").lower().strip(".,!?")
            if w_text in _IMPACT_WORDS:
                ts = float(w.get("start", payoff_start))
                # Only accept a payoff in the 40-90% window
                if duration * 0.40 <= ts <= duration * 0.90:
                    payoff_start = ts
                    break

    # Strategic zoom moments: hook open + payoff delivery
    zoom_moments = [0.2]  # hook zoom always at opening
    if payoff_start > hook_end + 2.0:
        zoom_moments.append(payoff_start)

    # Flash moments: only at payoff (if flash_allowed by category)
    # The caller (apply_category_rules) will check flash_allowed
    flash_moments: List[float] = [payoff_start] if payoff_start > 2.0 else []

    ns = NarrativeStructure(
        hook_end=hook_end,
        build_end=build_end,
        payoff_start=payoff_start,
        cta_start=cta_start,
        duration=duration,
        zoom_moments=zoom_moments,
        flash_moments=flash_moments,
    )
    logger.info("[EditorialBrain] narrative: %s", ns.describe())
    return ns


# ══════════════════════════════════════════════════════════════════════════════
# 4. CATEGORY RULES → CLIP PROFILE MERGER
# ══════════════════════════════════════════════════════════════════════════════

def apply_category_rules(
    profile: "ClipProfile",
    category_key: str,
    narrative: NarrativeStructure,
    trust_ai_values: bool = False,
) -> "ClipProfile":
    """
    Merge content-category expert rules into a ClipProfile.

    Category rules are the specialization layer — they encode decades of
    editorial convention for each content type.  AI-generated values from
    Groq are used ONLY when trust_ai_values=True (i.e. Groq produced them),
    otherwise category defaults apply for colour/zoom/music.

    The narrative structure injects strategic timing for zoom/flash moments.
    """
    from .clip_intelligence import ClipProfile  # avoid circular at module level

    rule = CATEGORY_RULES.get(category_key, CATEGORY_RULES[_DEFAULT_CATEGORY])

    # Colour grade & energy: category wins unless AI was trusted AND values differ significantly
    lut        = profile.lut if trust_ai_values else rule.lut
    caption    = profile.caption_style if trust_ai_values else rule.caption_style
    bgm        = profile.bgm_category if trust_ai_values else rule.bgm_category
    zoom       = profile.zoom_intensity if trust_ai_values else rule.zoom_intensity
    saturation = profile.saturation if trust_ai_values else rule.saturation
    contrast   = profile.contrast   if trust_ai_values else rule.contrast
    mood       = profile.mood if trust_ai_values else rule.mood
    sfx        = profile.sfx_emphasis if trust_ai_values else rule.sfx_emphasis

    # Always take AI B-roll keywords if available; supplement with category themes
    ai_kw    = list(profile.ai_keywords) if profile.ai_keywords else []
    cat_kw   = rule.broll_themes[:max(0, 5 - len(ai_kw))]
    merged_kw = (ai_kw + cat_kw)[:5]

    return ClipProfile(
        mood=mood,
        energy=profile.energy,
        pace=profile.pace,
        virality=profile.virality,
        lut=lut,
        caption_style=caption,
        broll_count=profile.broll_count,
        broll_duration=profile.broll_duration,
        bgm_category=bgm,
        zoom_intensity=zoom,
        sfx_emphasis=sfx,
        saturation=saturation,
        contrast=contrast,
        ai_keywords=merged_kw,
        content_category=category_key,
        narrative=narrative,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 5. FULL ANALYSIS ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

async def analyze_clip(
    segment: Dict[str, Any],
    duration: float,
    clip_index: int,
    words: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[str, NarrativeStructure]:
    """
    Identify content category and narrative structure for a clip segment.

    Returns (category_key, NarrativeStructure).
    Always succeeds — falls back to keyword matching on any error.
    """
    text      = (segment.get("text") or "").strip()
    hook_type = (segment.get("hook_type") or "insight_reveal").lower()

    # 1. Try AI categorization
    category = await categorize_clip_with_ai(text, hook_type)

    # 2. Fallback to keyword matching
    if category is None:
        category = categorize_clip_from_keywords(text)

    # 3. Narrative structure from word timestamps
    narrative = analyze_narrative_structure(duration, words=words, text=text)

    logger.info(
        "[EditorialBrain] clip=%d category=%s (%s)",
        clip_index + 1,
        category,
        CATEGORY_RULES.get(category, CATEGORY_RULES[_DEFAULT_CATEGORY]).name,
    )
    return category, narrative
