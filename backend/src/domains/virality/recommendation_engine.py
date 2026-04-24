"""
Personalized Recommendations System
AI-powered recommendations for content optimization and user engagement.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class UserProfile:
    """User preferences and behavior profile."""
    user_id: str
    preferred_niches: List[str]
    preferred_duration: int  # seconds
    favorite_effects: List[str]
    top_platforms: List[str]
    avg_virality_threshold: float
    content_style: str  # educational, entertaining, promotional
    posting_schedule: Optional[str] = None
    language_preference: str = "en"


@dataclass
class ContentRecommendation:
    """A content recommendation."""
    recommendation_id: str
    type: str  # niche, style, effect, time, music
    title: str
    description: str
    confidence: float  # 0-1
    action: str
    metadata: Dict[str, Any]


class RecommendationEngine:
    """
    AI-powered recommendation engine for content optimization.
    """
    
    # Trending content patterns
    TRENDING_PATTERNS = {
        "educational": {
            "optimal_duration": (60, 180),
            "best_effects": ["text_highlight", "zoom_on_key", "ken_burns"],
            "best_times": ["08:00-10:00", "14:00-16:00", "19:00-21:00"],
            "music_genres": ["ambient", "focus", "lo-fi"],
            "caption_style": "clean_professional"
        },
        "entertaining": {
            "optimal_duration": (15, 60),
            "best_effects": ["fast_cuts", "zoom_pulse", "glitch", "shake"],
            "best_times": ["12:00-14:00", "18:00-22:00", "20:00-23:00"],
            "music_genres": ["trending", "electronic", "pop"],
            "caption_style": "energetic_bold"
        },
        "promotional": {
            "optimal_duration": (30, 90),
            "best_effects": ["product_zoom", "text_pop", "transition_swipe"],
            "best_times": ["09:00-11:00", "15:00-17:00", "20:00-22:00"],
            "music_genres": ["upbeat", "corporate", "modern"],
            "caption_style": "sales_focused"
        }
    }
    
    # Niche-specific recommendations
    NICHE_RECOMMENDATIONS = {
        "gaming": {
            "hooks": ["Epic clutch moment", "You won't believe this play", "Secret strategy revealed"],
            "effects": ["zoom_on_action", "slow_motion", "replay"],
            "hashtags": ["#gaming", "#gamer", "#gameplay", "#twitch", "#viral"]
        },
        "finance": {
            "hooks": ["This changed my financial life", "The truth about money", "Stop doing this today"],
            "effects": ["text_highlight", "data_viz", "zoom_on_numbers"],
            "hashtags": ["#finance", "#money", "#investing", "#wealth", "#financialfreedom"]
        },
        "fitness": {
            "hooks": ["Transform your body", "No gym needed", "Results in 30 days"],
            "effects": ["before_after", "text_overlay", "motivational_zoom"],
            "hashtags": ["#fitness", "#workout", "#gym", "#health", "#motivation"]
        },
        "tech": {
            "hooks": ["This tech is game-changing", "Hidden features you didn't know", "Review: honest opinion"],
            "effects": ["screen_record", "cursor_highlight", "split_screen"],
            "hashtags": ["#tech", "#technology", "#review", "#gadgets", "#innovation"]
        },
        "cooking": {
            "hooks": ["Restaurant quality at home", "Quick 5-minute recipe", "Secret ingredient revealed"],
            "effects": ["food_zoom", "text_steps", "satisfying_closeup"],
            "hashtags": ["#cooking", "#food", "#recipe", "#foodie", "#delicious"]
        }
    }
    
    def __init__(self):
        self._user_profiles: Dict[str, UserProfile] = {}
        self._recommendation_history: Dict[str, List[ContentRecommendation]] = defaultdict(list)
    
    def create_user_profile(
        self,
        user_id: str,
        initial_data: Optional[Dict[str, Any]] = None
    ) -> UserProfile:
        """Create or update user profile."""
        if initial_data is None:
            initial_data = {}
        
        profile = UserProfile(
            user_id=user_id,
            preferred_niches=initial_data.get("niches", ["entertaining"]),
            preferred_duration=initial_data.get("duration", 60),
            favorite_effects=initial_data.get("effects", []),
            top_platforms=initial_data.get("platforms", ["tiktok"]),
            avg_virality_threshold=initial_data.get("threshold", 70.0),
            content_style=initial_data.get("style", "entertaining"),
            language_preference=initial_data.get("language", "en")
        )
        
        self._user_profiles[user_id] = profile
        return profile
    
    def update_profile_from_behavior(
        self,
        user_id: str,
        action: str,
        metadata: Dict[str, Any]
    ) -> None:
        """Update profile based on user behavior."""
        if user_id not in self._user_profiles:
            self.create_user_profile(user_id)
        
        profile = self._user_profiles[user_id]
        
        if action == "clip_exported":
            # Track preferred niches
            niche = metadata.get("niche")
            if niche and niche not in profile.preferred_niches:
                profile.preferred_niches.append(niche)
            
            # Track duration preference
            duration = metadata.get("duration", 0)
            if duration > 0:
                # Update preferred duration (moving average)
                profile.preferred_duration = int(
                    (profile.preferred_duration * 0.7) + (duration * 0.3)
                )
        
        elif action == "effect_used":
            effect = metadata.get("effect")
            if effect and effect not in profile.favorite_effects:
                profile.favorite_effects.append(effect)
                # Keep only top 10
                profile.favorite_effects = profile.favorite_effects[-10:]
        
        elif action == "platform_selected":
            platform = metadata.get("platform")
            if platform and platform not in profile.top_platforms:
                profile.top_platforms.insert(0, platform)
                profile.top_platforms = profile.top_platforms[:3]
    
    def get_recommendations(
        self,
        user_id: str,
        context: Optional[Dict[str, Any]] = None
    ) -> List[ContentRecommendation]:
        """Get personalized recommendations for a user."""
        if user_id not in self._user_profiles:
            self.create_user_profile(user_id)
        
        profile = self._user_profiles[user_id]
        recommendations = []
        
        # 1. Niche recommendations
        niche_recs = self._get_niche_recommendations(profile, context)
        recommendations.extend(niche_recs)
        
        # 2. Style recommendations
        style_recs = self._get_style_recommendations(profile, context)
        recommendations.extend(style_recs)
        
        # 3. Effect recommendations
        effect_recs = self._get_effect_recommendations(profile, context)
        recommendations.extend(effect_recs)
        
        # 4. Timing recommendations
        time_recs = self._get_timing_recommendations(profile, context)
        recommendations.extend(time_recs)
        
        # 5. Music recommendations
        music_recs = self._get_music_recommendations(profile, context)
        recommendations.extend(music_recs)
        
        # Sort by confidence
        recommendations.sort(key=lambda x: x.confidence, reverse=True)
        
        # Store in history
        self._recommendation_history[user_id].extend(recommendations[:5])
        
        return recommendations[:5]  # Top 5
    
    def _get_niche_recommendations(
        self,
        profile: UserProfile,
        context: Optional[Dict[str, Any]]
    ) -> List[ContentRecommendation]:
        """Get niche-based recommendations."""
        import uuid
        
        recommendations = []
        current_niche = context.get("current_niche") if context else None
        
        # Suggest trending niches not yet tried
        all_niches = list(self.NICHE_RECOMMENDATIONS.keys())
        untried = [n for n in all_niches if n not in profile.preferred_niches]
        
        if untried and len(profile.preferred_niches) < 3:
            niche = untried[0]
            data = self.NICHE_RECOMMENDATIONS[niche]
            
            recommendations.append(ContentRecommendation(
                recommendation_id=str(uuid.uuid4()),
                type="niche",
                title=f"Try {niche.title()} Content",
                description=f"Trending hooks: {', '.join(data['hooks'][:2])}",
                confidence=0.75,
                action="explore_niche",
                metadata={"niche": niche, "hooks": data["hooks"], "hashtags": data["hashtags"]}
            ))
        
        # Suggest hooks for current niche
        if current_niche and current_niche in self.NICHE_RECOMMENDATIONS:
            data = self.NICHE_RECOMMENDATIONS[current_niche]
            recommendations.append(ContentRecommendation(
                recommendation_id=str(uuid.uuid4()),
                type="hook",
                title="Trending Hook Ideas",
                description=f"Try: '{data['hooks'][0]}'",
                confidence=0.85,
                action="use_hook",
                metadata={"hooks": data["hooks"][:3]}
            ))
        
        return recommendations
    
    def _get_style_recommendations(
        self,
        profile: UserProfile,
        context: Optional[Dict[str, Any]]
    ) -> List[ContentRecommendation]:
        """Get style-based recommendations."""
        import uuid
        
        recommendations = []
        
        # Check if current style matches content
        if profile.content_style in self.TRENDING_PATTERNS:
            pattern = self.TRENDING_PATTERNS[profile.content_style]
            
            # Suggest optimal duration
            min_dur, max_dur = pattern["optimal_duration"]
            if not (min_dur <= profile.preferred_duration <= max_dur):
                recommendations.append(ContentRecommendation(
                    recommendation_id=str(uuid.uuid4()),
                    type="style",
                    title="Optimize Duration",
                    description=f"For {profile.content_style} content, aim for {min_dur}-{max_dur} seconds",
                    confidence=0.80,
                    action="adjust_duration",
                    metadata={"optimal_min": min_dur, "optimal_max": max_dur}
                ))
            
            # Suggest caption style
            recommendations.append(ContentRecommendation(
                recommendation_id=str(uuid.uuid4()),
                type="caption",
                title="Caption Style",
                description=f"Use '{pattern['caption_style']}' captions for better engagement",
                confidence=0.75,
                action="apply_caption_style",
                metadata={"style": pattern["caption_style"]}
            ))
        
        return recommendations
    
    def _get_effect_recommendations(
        self,
        profile: UserProfile,
        context: Optional[Dict[str, Any]]
    ) -> List[ContentRecommendation]:
        """Get effect recommendations."""
        import uuid
        
        recommendations = []
        
        # Get trending effects for style
        if profile.content_style in self.TRENDING_PATTERNS:
            pattern = self.TRENDING_PATTERNS[profile.content_style]
            
            unused_effects = [
                e for e in pattern["best_effects"]
                if e not in profile.favorite_effects
            ]
            
            if unused_effects:
                recommendations.append(ContentRecommendation(
                    recommendation_id=str(uuid.uuid4()),
                    type="effect",
                    title="Try These Effects",
                    description=f"Effects trending for {profile.content_style}: {', '.join(unused_effects[:3])}",
                    confidence=0.70,
                    action="apply_effects",
                    metadata={"effects": unused_effects[:3]}
                ))
        
        return recommendations
    
    def _get_timing_recommendations(
        self,
        profile: UserProfile,
        context: Optional[Dict[str, Any]]
    ) -> List[ContentRecommendation]:
        """Get posting time recommendations."""
        import uuid
        
        recommendations = []
        
        if profile.content_style in self.TRENDING_PATTERNS:
            pattern = self.TRENDING_PATTERNS[profile.content_style]
            best_times = pattern["best_times"]
            
            recommendations.append(ContentRecommendation(
                recommendation_id=str(uuid.uuid4()),
                type="time",
                title="Best Posting Times",
                description=f"Post during: {', '.join(best_times[:2])}",
                confidence=0.78,
                action="schedule_post",
                metadata={"best_times": best_times}
            ))
        
        return recommendations
    
    def _get_music_recommendations(
        self,
        profile: UserProfile,
        context: Optional[Dict[str, Any]]
    ) -> List[ContentRecommendation]:
        """Get music recommendations."""
        import uuid
        
        recommendations = []
        
        if profile.content_style in self.TRENDING_PATTERNS:
            pattern = self.TRENDING_PATTERNS[profile.content_style]
            genres = pattern["music_genres"]
            
            recommendations.append(ContentRecommendation(
                recommendation_id=str(uuid.uuid4()),
                type="music",
                title="Trending Music Genres",
                description=f"Try {', '.join(genres)} music for your {profile.content_style} content",
                confidence=0.72,
                action="browse_music",
                metadata={"genres": genres}
            ))
        
        return recommendations
    
    def get_virality_optimization_tips(
        self,
        user_id: str,
        clip_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Get specific tips to improve clip virality."""
        tips = []
        
        virality_score = clip_data.get("virality_score", 0)
        current_niche = clip_data.get("niche", "general")
        duration = clip_data.get("duration", 0)
        
        # Score-based tips
        if virality_score < 60:
            tips.append({
                "priority": "high",
                "category": "hook",
                "tip": "Add a stronger hook in the first 3 seconds",
                "action": "Add text overlay with curiosity gap"
            })
        
        if virality_score < 70:
            tips.append({
                "priority": "medium",
                "category": "pacing",
                "tip": "Consider removing pauses or slow sections",
                "action": "Apply auto-edit to tighten pacing"
            })
        
        # Niche-specific tips
        if current_niche in self.NICHE_RECOMMENDATIONS:
            niche_data = self.NICHE_RECOMMENDATIONS[current_niche]
            tips.append({
                "priority": "medium",
                "category": "hashtags",
                "tip": f"Use trending hashtags: {', '.join(niche_data['hashtags'][:3])}",
                "action": "Add recommended hashtags"
            })
        
        # Duration tips
        if duration > 90:
            tips.append({
                "priority": "medium",
                "category": "length",
                "tip": "Clip is long. Consider splitting or trimming",
                "action": "Split into multiple shorter clips"
            })
        elif duration < 10:
            tips.append({
                "priority": "low",
                "category": "length",
                "tip": "Very short clip. May lack context",
                "action": "Extend slightly or add more context"
            })
        
        return sorted(tips, key=lambda x: x["priority"] == "high", reverse=True)
    
    def predict_performance(
        self,
        clip_features: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Predict performance based on clip features."""
        score = clip_features.get("virality_score", 50)
        niche = clip_features.get("niche", "general")
        has_hook = clip_features.get("has_hook", False)
        duration = clip_features.get("duration", 60)
        
        # Base prediction
        predicted_views = score * 100  # Very rough estimate
        
        # Adjustments
        if has_hook:
            predicted_views *= 1.3
            score = min(100, score * 1.1)
        
        if niche in ["gaming", "comedy"]:
            predicted_views *= 1.2  # Higher viral potential
        
        if 15 <= duration <= 60:
            predicted_views *= 1.15  # Optimal duration
        
        return {
            "predicted_views_range": (int(predicted_views * 0.7), int(predicted_views * 1.3)),
            "confidence": min(100, score) / 100,
            "virality_tier": "high" if score > 75 else "medium" if score > 50 else "low",
            "optimization_potential": max(0, 100 - score),
            "estimated_engagement_rate": min(15, score / 5)  # Rough estimate
        }


# Global instance
_recommendation_engine: Optional[RecommendationEngine] = None


def get_recommendation_engine() -> RecommendationEngine:
    """Get global recommendation engine instance."""
    global _recommendation_engine
    if _recommendation_engine is None:
        _recommendation_engine = RecommendationEngine()
    return _recommendation_engine


def get_personalized_recommendations(
    user_id: str,
    context: Optional[Dict[str, Any]] = None
) -> List[ContentRecommendation]:
    """Convenience function to get recommendations."""
    return get_recommendation_engine().get_recommendations(user_id, context)


def get_virality_tips(
    clip_data: Dict[str, Any],
    user_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get virality optimization tips."""
    return get_recommendation_engine().get_virality_optimization_tips(
        user_id or "anonymous",
        clip_data
    )
