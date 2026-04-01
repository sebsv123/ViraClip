"""
Niche & Trends Analysis Module
Analyzes content niche and trending patterns for viral optimization.
Helps tailor clips to specific platform and audience preferences.
"""

import re
from typing import List, Dict, Any, Optional, Set
from dataclasses import dataclass
from collections import Counter


@dataclass
class NicheAnalysis:
    """Results of niche analysis for a video."""
    primary_niche: str
    secondary_niches: List[str]
    confidence: float
    trending_keywords: List[str]
    platform_optimization: Dict[str, Any]
    content_archetype: str
    audience_demographics: Dict[str, Any]


# Niche definitions with keywords and characteristics
NICHE_DEFINITIONS = {
    "gaming": {
        "keywords": [
            "game", "gaming", "gameplay", "player", "win", "lose", "level",
            "mission", "character", "weapon", "strategy", "walkthrough",
            "minecraft", "fortnite", "valorant", "call of duty", "gta",
            "streamer", "esports", "competitive", "ranked", "squad"
        ],
        "optimal_duration": (30, 60),
        "best_platforms": ["tiktok", "youtube_shorts", "twitch"],
        "peak_times": ["18:00-23:00", "weekends"],
        "archetypes": ["highlights", "fails", "wins", "tips", "funny_moments"],
    },
    "finance": {
        "keywords": [
            "money", "invest", "stock", "crypto", "bitcoin", "trading",
            "finance", "wealth", "rich", "passive income", "savings",
            "budget", "debt", "credit", "financial freedom", "dividend",
            "portfolio", "market", "economy", "recession", "inflation"
        ],
        "optimal_duration": (45, 90),
        "best_platforms": ["youtube_shorts", "tiktok", "instagram_reels"],
        "peak_times": ["07:00-09:00", "12:00-14:00", "17:00-19:00"],
        "archetypes": ["tips", "myth_busting", "success_stories", "warnings"],
    },
    "fitness": {
        "keywords": [
            "workout", "gym", "exercise", "fitness", "muscle", "weight loss",
            "diet", "nutrition", "protein", "cardio", "strength", "training",
            "abs", "six pack", "transformation", "body", "health", "wellness",
            "yoga", "pilates", "crossfit", "running", "marathon"
        ],
        "optimal_duration": (30, 75),
        "best_platforms": ["instagram_reels", "tiktok", "youtube_shorts"],
        "peak_times": ["06:00-09:00", "17:00-20:00"],
        "archetypes": ["transformation", "tutorial", "motivation", "results"],
    },
    "cooking": {
        "keywords": [
            "recipe", "cook", "food", "meal", "kitchen", "ingredient",
            "restaurant", "chef", "delicious", "tasty", "easy recipe",
            "quick meal", "healthy food", "dessert", "breakfast", "dinner",
            "vegan", "keto", "diet", "cuisine", "baking", "grilling"
        ],
        "optimal_duration": (30, 90),
        "best_platforms": ["tiktok", "instagram_reels", "youtube_shorts"],
        "peak_times": ["11:00-13:00", "17:00-19:00"],
        "archetypes": ["quick_recipe", "satisfying", "hack", "reaction"],
    },
    "technology": {
        "keywords": [
            "tech", "technology", "ai", "artificial intelligence", "software",
            "app", "iphone", "android", "review", "unboxing", "gadget",
            "device", "computer", "laptop", "smartphone", "code",
            "programming", "developer", "startup", "innovation", "future"
        ],
        "optimal_duration": (45, 120),
        "best_platforms": ["youtube_shorts", "tiktok", "twitter"],
        "peak_times": ["12:00-14:00", "19:00-22:00"],
        "archetypes": ["review", "tutorial", "news", "prediction"],
    },
    "motivation": {
        "keywords": [
            "motivation", "inspiration", "success", "mindset", "grind",
            "hustle", "discipline", "goals", "dream", "achieve", "overcome",
            "failure", "never give up", "hard work", "dedication",
            "entrepreneur", "self improvement", "personal growth", "confident"
        ],
        "optimal_duration": (30, 90),
        "best_platforms": ["tiktok", "instagram_reels", "youtube_shorts"],
        "peak_times": ["06:00-09:00", "20:00-23:00"],
        "archetypes": ["speech", "story", "advice", "quote"],
    },
    "comedy": {
        "keywords": [
            "funny", "comedy", "joke", "laugh", "hilarious", "prank",
            "sketch", "stand up", "humor", "meme", "reaction", "fail",
            "compilation", "funny moments", "tiktok", "viral", "trend"
        ],
        "optimal_duration": (15, 60),
        "best_platforms": ["tiktok", "youtube_shorts", "instagram_reels"],
        "peak_times": ["12:00-14:00", "18:00-23:00"],
        "archetypes": ["prank", "sketch", "reaction", "compilation"],
    },
    "beauty": {
        "keywords": [
            "makeup", "skincare", "beauty", "fashion", "style", "tutorial",
            "glow up", "transformation", "review", "product", "routine",
            "hair", "nails", "outfit", "aesthetic", "grwm", "get ready"
        ],
        "optimal_duration": (30, 90),
        "best_platforms": ["instagram_reels", "tiktok", "youtube_shorts"],
        "peak_times": ["08:00-10:00", "19:00-22:00"],
        "archetypes": ["tutorial", "transformation", "review", "routine"],
    },
    "education": {
        "keywords": [
            "learn", "education", "tutorial", "how to", "guide", "explain",
            "science", "history", "fact", "did you know", "interesting",
            "knowledge", "study", "student", "school", "university",
            "psychology", "philosophy", "math", "chemistry", "physics"
        ],
        "optimal_duration": (45, 120),
        "best_platforms": ["youtube_shorts", "tiktok", "instagram_reels"],
        "peak_times": ["12:00-14:00", "19:00-22:00"],
        "archetypes": ["explainer", "fact", "tutorial", "story"],
    },
    "travel": {
        "keywords": [
            "travel", "adventure", "explore", "vacation", "destination",
            "hotel", "resort", "beach", "mountain", "city", "country",
            "culture", "food tour", "road trip", "backpacking", "vlog"
        ],
        "optimal_duration": (30, 90),
        "best_platforms": ["instagram_reels", "tiktok", "youtube_shorts"],
        "peak_times": ["12:00-14:00", "19:00-23:00"],
        "archetypes": ["vlog", "recommendation", "transformation", "views"],
    },
}

# Trending patterns that boost virality
TRENDING_PATTERNS = {
    "ai_revolution": ["ai", "artificial intelligence", "chatgpt", "midjourney", "automation"],
    "sustainability": ["eco", "sustainable", "green", "climate", "zero waste"],
    "mental_health": ["mental health", "anxiety", "depression", "self care", "therapy"],
    "remote_work": ["remote", "work from home", "digital nomad", "freelance"],
    "side_hustle": ["side hustle", "passive income", "extra income", "small business"],
}


def analyze_content_niche(transcript_text: str, video_title: str = "") -> NicheAnalysis:
    """
    Analyze content to determine its niche and viral potential.
    
    Args:
        transcript_text: Video transcript
        video_title: Video title (optional)
        
    Returns:
        NicheAnalysis with optimization recommendations
    """
    text_lower = (transcript_text + " " + video_title).lower()
    
    # Score each niche
    niche_scores = {}
    for niche, config in NICHE_DEFINITIONS.items():
        score = sum(1 for keyword in config["keywords"] if keyword in text_lower)
        niche_scores[niche] = score
    
    # Determine primary and secondary niches
    sorted_niches = sorted(niche_scores.items(), key=lambda x: x[1], reverse=True)
    
    primary_niche = sorted_niches[0][0] if sorted_niches[0][1] > 0 else "general"
    secondary_niches = [
        niche for niche, score in sorted_niches[1:3] 
        if score > 0 and niche != primary_niche
    ]
    
    # Calculate confidence
    total_keywords = sum(niche_scores.values())
    confidence = min(1.0, sorted_niches[0][1] / max(3, total_keywords * 0.3))
    
    # Find trending keywords
    trending_found = []
    for trend, keywords in TRENDING_PATTERNS.items():
        if any(kw in text_lower for kw in keywords):
            trending_found.append(trend)
    
    # Get niche config
    niche_config = NICHE_DEFINITIONS.get(primary_niche, {})
    
    # Determine content archetype
    archetype = determine_content_archetype(text_lower, primary_niche)
    
    # Build platform optimization
    platform_opt = {
        "primary": niche_config.get("best_platforms", ["tiktok"])[0],
        "all": niche_config.get("best_platforms", ["tiktok", "youtube_shorts"]),
        "optimal_duration": niche_config.get("optimal_duration", (30, 90)),
        "peak_times": niche_config.get("peak_times", ["12:00-14:00", "18:00-22:00"]),
    }
    
    # Estimate audience demographics
    demographics = estimate_demographics(primary_niche, text_lower)
    
    return NicheAnalysis(
        primary_niche=primary_niche,
        secondary_niches=secondary_niches,
        confidence=confidence,
        trending_keywords=trending_found,
        platform_optimization=platform_opt,
        content_archetype=archetype,
        audience_demographics=demographics,
    )


def determine_content_archetype(text_lower: str, niche: str) -> str:
    """
    Determine the content archetype based on text patterns.
    """
    # Archetype detection patterns
    archetype_patterns = {
        "tutorial": ["how to", "tutorial", "guide", "step by step", "learn"],
        "story": ["story time", "let me tell you", "when i", "my experience"],
        "review": ["review", "honest opinion", "pros and cons", "worth it"],
        "transformation": ["before", "after", "then vs now", "glow up"],
        "reaction": ["reaction", "responding to", "let's watch", "unbelievable"],
        "compilation": ["best moments", "top 10", "compilation", "highlights"],
        "motivation": ["motivation", "inspiration", "never give up", "you can"],
        "comedy": ["funny", "hilarious", "joke", "prank", "comedy"],
        "news": ["breaking", "just announced", "new update", "recent"],
    }
    
    scores = {}
    for archetype, patterns in archetype_patterns.items():
        score = sum(1 for pattern in patterns if pattern in text_lower)
        scores[archetype] = score
    
    best = max(scores.items(), key=lambda x: x[1])
    return best[0] if best[1] > 0 else "general"


def estimate_demographics(niche: str, text_lower: str) -> Dict[str, Any]:
    """
    Estimate target audience demographics based on niche and content.
    """
    # Base demographics by niche
    niche_demographics = {
        "gaming": {"age_range": "13-25", "gender_split": "75/25", "primary_interests": ["esports", "streaming"]},
        "finance": {"age_range": "25-45", "gender_split": "60/40", "primary_interests": ["investing", "wealth_building"]},
        "fitness": {"age_range": "18-35", "gender_split": "50/50", "primary_interests": ["health", "wellness"]},
        "beauty": {"age_range": "16-35", "gender_split": "20/80", "primary_interests": ["fashion", "skincare"]},
        "technology": {"age_range": "20-40", "gender_split": "70/30", "primary_interests": ["gadgets", "innovation"]},
        "comedy": {"age_range": "16-30", "gender_split": "50/50", "primary_interests": ["entertainment", "memes"]},
        "motivation": {"age_range": "20-35", "gender_split": "50/50", "primary_interests": ["self_improvement", "career"]},
        "education": {"age_range": "18-45", "gender_split": "50/50", "primary_interests": ["learning", "knowledge"]},
    }
    
    base = niche_demographics.get(niche, {
        "age_range": "18-45", 
        "gender_split": "50/50", 
        "primary_interests": ["general"]
    })
    
    # Adjust based on content sophistication
    advanced_terms = ["algorithm", "analysis", "framework", "strategy", "optimization"]
    sophistication = sum(1 for term in advanced_terms if term in text_lower)
    
    if sophistication >= 2:
        # Likely older, more educated audience
        base["age_range"] = adjust_age_range(base["age_range"], +5)
    
    return base


def adjust_age_range(age_range: str, adjustment: int) -> str:
    """Adjust age range by given years."""
    parts = age_range.split("-")
    if len(parts) == 2:
        min_age = int(parts[0]) + adjustment
        max_age = int(parts[1]) + adjustment
        return f"{min_age}-{max_age}"
    return age_range


def get_niche_specific_tips(niche: str) -> List[str]:
    """
    Get niche-specific tips for viral optimization.
    """
    tips = {
        "gaming": [
            "Use fast-paced editing with jump cuts",
            "Show reaction to intense moments",
            "Include on-screen text for context",
            "Use gaming-specific hashtags and sounds",
        ],
        "finance": [
            "Lead with specific dollar amounts",
            "Use credibility indicators (charts, data)",
            "Keep jargon minimal but include key terms",
            "End with actionable advice",
        ],
        "fitness": [
            "Show before/after comparisons",
            "Use workout music and fast cuts",
            "Include form tips as text overlays",
            "Show real effort and sweat",
        ],
        "beauty": [
            "Use satisfying transformation reveals",
            "Close-ups of product application",
            "ASMR-style audio for satisfying sounds",
            "Before/after split screens",
        ],
        "comedy": [
            "Cut directly to the punchline",
            "Use reaction shots effectively",
            "Add sound effects for emphasis",
            "Keep pacing fast - no dead air",
        ],
        "education": [
            "Hook with the most surprising fact",
            "Use visual aids and graphics",
            "Break complex topics into digestible parts",
            "End with 'follow for more' CTA",
        ],
    }
    
    return tips.get(niche, [
        "Start with a strong hook in first 3 seconds",
        "Maintain high energy throughout",
        "Use trending sounds when relevant",
        "Include clear call-to-action",
    ])


def optimize_for_platform(
    niche_analysis: NicheAnalysis, 
    target_platform: str
) -> Dict[str, Any]:
    """
    Generate platform-specific optimization recommendations.
    
    Args:
        niche_analysis: Results from analyze_content_niche
        target_platform: Platform name (tiktok, youtube_shorts, instagram_reels)
        
    Returns:
        Optimization recommendations
    """
    platform_specs = {
        "tiktok": {
            "optimal_duration": (15, 60),
            "aspect_ratio": "9:16",
            "sound_required": True,
            "trending_importance": "high",
            "text_overlay": "recommended",
            "hashtag_count": (3, 5),
        },
        "youtube_shorts": {
            "optimal_duration": (30, 60),
            "aspect_ratio": "9:16",
            "sound_required": False,
            "trending_importance": "medium",
            "text_overlay": "optional",
            "hashtag_count": (3, 8),
        },
        "instagram_reels": {
            "optimal_duration": (15, 90),
            "aspect_ratio": "9:16",
            "sound_required": True,
            "trending_importance": "high",
            "text_overlay": "recommended",
            "hashtag_count": (5, 10),
        },
    }
    
    specs = platform_specs.get(target_platform, platform_specs["tiktok"])
    niche_opt = niche_analysis.platform_optimization
    
    # Calculate recommended duration
    niche_min, niche_max = niche_opt["optimal_duration"]
    plat_min, plat_max = specs["optimal_duration"]
    
    rec_duration = (
        max(niche_min, plat_min),
        min(niche_max, plat_max)
    )
    
    return {
        "platform": target_platform,
        "recommended_duration": rec_duration,
        "aspect_ratio": specs["aspect_ratio"],
        "sound_strategy": "trending_audio" if specs["sound_required"] else "original_or_trending",
        "text_overlay": specs["text_overlay"],
        "hashtag_strategy": {
            "count": specs["hashtag_count"],
            "mix": [niche_analysis.primary_niche] + niche_analysis.secondary_niches + ["viral", "trending"],
        },
        "posting_times": niche_opt["peak_times"],
        "niche_specific_tips": get_niche_specific_tips(niche_analysis.primary_niche),
    }
