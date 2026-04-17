"""
Gamification System for User Engagement
Achievements, points, levels, and rewards to motivate users.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class AchievementType(Enum):
    """Types of achievements users can earn."""
    FIRST_CLIP = "first_clip"
    VIRAL_CREATOR = "viral_creator"
    POWER_USER = "power_user"
    CONSISTENT_CREATOR = "consistent_creator"
    QUALITY_MASTER = "quality_master"
    PLATFORM_MASTER = "platform_master"
    COLLABORATION_KING = "collaboration_king"
    TREND_SETTER = "trend_setter"
    EARLY_ADOPTER = "early_adopter"
    FEEDBACK_HERO = "feedback_hero"


class RewardType(Enum):
    """Types of rewards."""
    POINTS = "points"
    BADGE = "badge"
    FEATURE_UNLOCK = "feature_unlock"
    DISCOUNT = "discount"
    PREMIUM_DAYS = "premium_days"


@dataclass
class Achievement:
    """Achievement definition."""
    achievement_id: str
    type: AchievementType
    name: str
    description: str
    icon: str
    points: int
    criteria: Dict[str, Any]
    rarity: str  # common, rare, epic, legendary


@dataclass
class UserGamificationProfile:
    """User's gamification state."""
    user_id: str
    total_points: int
    current_level: int
    achievements: List[str]  # achievement_ids earned
    streak_days: int
    last_activity: str
    badges: List[str]
    unlocked_features: List[str]
    rank: str  # bronze, silver, gold, platinum, diamond


class GamificationService:
    """
    Manages user gamification, achievements, and rewards.
    """
    
    # Achievement definitions
    ACHIEVEMENTS = {
        AchievementType.FIRST_CLIP: Achievement(
            achievement_id="first_clip",
            type=AchievementType.FIRST_CLIP,
            name="Clip Pioneer",
            description="Create your first viral clip",
            icon="🎬",
            points=100,
            criteria={"clips_created": 1},
            rarity="common"
        ),
        AchievementType.VIRAL_CREATOR: Achievement(
            achievement_id="viral_creator",
            type=AchievementType.VIRAL_CREATOR,
            name="Viral Creator",
            description="Create 10 clips with 80%+ virality score",
            icon="🔥",
            points=500,
            criteria={"high_virality_clips": 10},
            rarity="rare"
        ),
        AchievementType.POWER_USER: Achievement(
            achievement_id="power_user",
            type=AchievementType.POWER_USER,
            name="Power User",
            description="Process 50 videos",
            icon="⚡",
            points=1000,
            criteria={"videos_processed": 50},
            rarity="epic"
        ),
        AchievementType.CONSISTENT_CREATOR: Achievement(
            achievement_id="consistent_creator",
            type=AchievementType.CONSISTENT_CREATOR,
            name="Consistent Creator",
            description="Maintain a 7-day creation streak",
            icon="📅",
            points=300,
            criteria={"streak_days": 7},
            rarity="rare"
        ),
        AchievementType.QUALITY_MASTER: Achievement(
            achievement_id="quality_master",
            type=AchievementType.QUALITY_MASTER,
            name="Quality Master",
            description="Achieve 95% average quality score on 20 clips",
            icon="✨",
            points=750,
            criteria={"high_quality_clips": 20},
            rarity="epic"
        ),
        AchievementType.PLATFORM_MASTER: Achievement(
            achievement_id="platform_master",
            type=AchievementType.PLATFORM_MASTER,
            name="Platform Master",
            description="Export clips to 5 different platforms",
            icon="🌐",
            points=400,
            criteria={"platforms_used": 5},
            rarity="rare"
        ),
        AchievementType.COLLABORATION_KING: Achievement(
            achievement_id="collaboration_king",
            type=AchievementType.COLLABORATION_KING,
            name="Collaboration King",
            description="Collaborate on 10 projects",
            icon="🤝",
            points=600,
            criteria={"collaborations": 10},
            rarity="epic"
        ),
        AchievementType.TREND_SETTER: Achievement(
            achievement_id="trend_setter",
            type=AchievementType.TREND_SETTER,
            name="Trend Setter",
            description="Create clips in 5 different trending niches",
            icon="📈",
            points=350,
            criteria={"niches_explored": 5},
            rarity="rare"
        ),
        AchievementType.EARLY_ADOPTER: Achievement(
            achievement_id="early_adopter",
            type=AchievementType.EARLY_ADOPTER,
            name="Early Adopter",
            description="Join during beta phase",
            icon="🚀",
            points=200,
            criteria={"joined_beta": True},
            rarity="legendary"
        ),
        AchievementType.FEEDBACK_HERO: Achievement(
            achievement_id="feedback_hero",
            type=AchievementType.FEEDBACK_HERO,
            name="Feedback Hero",
            description="Provide feedback on 25 clips",
            icon="💬",
            points=250,
            criteria={"feedback_count": 25},
            rarity="common"
        )
    }
    
    # Level thresholds
    LEVEL_THRESHOLDS = [0, 500, 1500, 3000, 5000, 8000, 12000, 17000, 23000, 30000]
    
    # Rank thresholds
    RANKS = [
        (0, "bronze"),
        (1000, "silver"),
        (3000, "gold"),
        (7000, "platinum"),
        (15000, "diamond")
    ]
    
    def __init__(self):
        self._user_profiles: Dict[str, UserGamificationProfile] = {}
        self._activity_log: Dict[str, List[Dict[str, Any]]] = {}
    
    def get_or_create_profile(self, user_id: str) -> UserGamificationProfile:
        """Get or create user gamification profile."""
        if user_id not in self._user_profiles:
            self._user_profiles[user_id] = UserGamificationProfile(
                user_id=user_id,
                total_points=0,
                current_level=1,
                achievements=[],
                streak_days=0,
                last_activity=datetime.now().isoformat(),
                badges=[],
                unlocked_features=[],
                rank="bronze"
            )
        
        return self._user_profiles[user_id]
    
    async def record_activity(
        self,
        user_id: str,
        activity_type: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> List[Achievement]:
        """
        Record user activity and check for achievements.
        
        Returns:
            List of newly earned achievements
        """
        profile = self.get_or_create_profile(user_id)
        
        # Log activity
        if user_id not in self._activity_log:
            self._activity_log[user_id] = []
        
        self._activity_log[user_id].append({
            "type": activity_type,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {}
        })
        
        # Update streak
        self._update_streak(profile)
        
        # Check for new achievements
        new_achievements = self._check_achievements(user_id)
        
        # Award points
        points_earned = sum(a.points for a in new_achievements)
        if points_earned > 0:
            await self._award_points(user_id, points_earned)
        
        return new_achievements
    
    def _update_streak(self, profile: UserGamificationProfile) -> None:
        """Update user's activity streak."""
        last_activity = datetime.fromisoformat(profile.last_activity)
        now = datetime.now()
        
        # Check if activity is on consecutive day
        days_diff = (now.date() - last_activity.date()).days
        
        if days_diff == 1:
            # Consecutive day
            profile.streak_days += 1
        elif days_diff > 1:
            # Streak broken
            profile.streak_days = 1
        elif days_diff == 0:
            # Same day, don't increment
            pass
        
        profile.last_activity = now.isoformat()
    
    def _check_achievements(self, user_id: str) -> List[Achievement]:
        """Check if user has earned new achievements."""
        profile = self.get_or_create_profile(user_id)
        
        # Get activity stats
        stats = self._get_user_stats(user_id)
        
        new_achievements = []
        
        for achievement in self.ACHIEVEMENTS.values():
            # Skip already earned
            if achievement.achievement_id in profile.achievements:
                continue
            
            # Check criteria
            if self._meets_criteria(stats, achievement.criteria):
                profile.achievements.append(achievement.achievement_id)
                new_achievements.append(achievement)
                
                # Add badge for rare+ achievements
                if achievement.rarity in ["rare", "epic", "legendary"]:
                    profile.badges.append(achievement.icon)
                
                logger.info(f"User {user_id} earned achievement: {achievement.name}")
        
        return new_achievements
    
    def _get_user_stats(self, user_id: str) -> Dict[str, Any]:
        """Calculate user statistics from activity log."""
        activities = self._activity_log.get(user_id, [])
        
        stats = {
            "clips_created": 0,
            "videos_processed": 0,
            "high_virality_clips": 0,
            "high_quality_clips": 0,
            "platforms_used": set(),
            "collaborations": 0,
            "niches_explored": set(),
            "feedback_count": 0,
            "streak_days": self._user_profiles[user_id].streak_days if user_id in self._user_profiles else 0
        }
        
        for activity in activities:
            metadata = activity.get("metadata", {})
            
            if activity["type"] == "clip_created":
                stats["clips_created"] += 1
                
                if metadata.get("virality_score", 0) >= 80:
                    stats["high_virality_clips"] += 1
                
                if metadata.get("quality_score", 0) >= 95:
                    stats["high_quality_clips"] += 1
                
                if metadata.get("niche"):
                    stats["niches_explored"].add(metadata["niche"])
            
            elif activity["type"] == "video_processed":
                stats["videos_processed"] += 1
            
            elif activity["type"] == "clip_exported":
                if metadata.get("platform"):
                    stats["platforms_used"].add(metadata["platform"])
            
            elif activity["type"] == "collaboration":
                stats["collaborations"] += 1
            
            elif activity["type"] == "feedback_submitted":
                stats["feedback_count"] += 1
        
        # Convert sets to counts
        stats["platforms_used"] = len(stats["platforms_used"])
        stats["niches_explored"] = len(stats["niches_explored"])
        
        return stats
    
    def _meets_criteria(self, stats: Dict[str, Any], criteria: Dict[str, Any]) -> bool:
        """Check if user stats meet achievement criteria."""
        for key, required_value in criteria.items():
            actual_value = stats.get(key, 0)
            
            if isinstance(required_value, bool):
                if actual_value != required_value:
                    return False
            elif actual_value < required_value:
                return False
        
        return True
    
    async def _award_points(self, user_id: str, points: int) -> None:
        """Award points to user and check for level up."""
        profile = self.get_or_create_profile(user_id)
        
        old_level = profile.current_level
        profile.total_points += points
        
        # Check for level up
        for i, threshold in enumerate(self.LEVEL_THRESHOLDS):
            if profile.total_points >= threshold:
                profile.current_level = i + 1
        
        # Check for rank up
        for threshold, rank in self.RANKS:
            if profile.total_points >= threshold:
                profile.rank = rank
        
        # Unlock features based on level
        self._unlock_features(profile)
        
        if profile.current_level > old_level:
            logger.info(f"User {user_id} leveled up to {profile.current_level}!")
    
    def _unlock_features(self, profile: UserGamificationProfile) -> None:
        """Unlock features based on user level."""
        feature_unlocks = {
            3: "advanced_effects",
            5: "batch_processing",
            7: "priority_rendering",
            10: "custom_templates"
        }
        
        for level, feature in feature_unlocks.items():
            if profile.current_level >= level and feature not in profile.unlocked_features:
                profile.unlocked_features.append(feature)
                logger.info(f"User {profile.user_id} unlocked feature: {feature}")
    
    def get_profile(self, user_id: str) -> Dict[str, Any]:
        """Get user gamification profile."""
        profile = self.get_or_create_profile(user_id)
        
        # Calculate progress to next level
        next_level = min(profile.current_level, len(self.LEVEL_THRESHOLDS) - 1)
        next_threshold = self.LEVEL_THRESHOLDS[next_level] if next_level < len(self.LEVEL_THRESHOLDS) else profile.total_points * 2
        
        if next_level > 0:
            current_threshold = self.LEVEL_THRESHOLDS[next_level - 1]
            progress = (profile.total_points - current_threshold) / (next_threshold - current_threshold)
        else:
            progress = profile.total_points / next_threshold if next_threshold > 0 else 1
        
        return {
            "user_id": profile.user_id,
            "total_points": profile.total_points,
            "current_level": profile.current_level,
            "rank": profile.rank,
            "achievements_earned": len(profile.achievements),
            "achievements_total": len(self.ACHIEVEMENTS),
            "badges": profile.badges,
            "streak_days": profile.streak_days,
            "unlocked_features": profile.unlocked_features,
            "level_progress": min(1.0, max(0.0, progress)),
            "next_level_points": next_threshold
        }
    
    def get_achievements(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all achievements with earned status."""
        profile = self.get_or_create_profile(user_id)
        
        return [
            {
                "id": a.achievement_id,
                "name": a.name,
                "description": a.description,
                "icon": a.icon,
                "points": a.points,
                "rarity": a.rarity,
                "earned": a.achievement_id in profile.achievements,
                "criteria": a.criteria
            }
            for a in self.ACHIEVEMENTS.values()
        ]
    
    def get_leaderboard(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get top users by points."""
        sorted_users = sorted(
            self._user_profiles.values(),
            key=lambda x: x.total_points,
            reverse=True
        )[:limit]
        
        return [
            {
                "rank": i + 1,
                "user_id": p.user_id,
                "total_points": p.total_points,
                "level": p.current_level,
                "rank_tier": p.rank,
                "achievements_count": len(p.achievements)
            }
            for i, p in enumerate(sorted_users)
        ]


# Global instance
_gamification_service: Optional[GamificationService] = None


def get_gamification_service() -> GamificationService:
    """Get global gamification service."""
    global _gamification_service
    if _gamification_service is None:
        _gamification_service = GamificationService()
    return _gamification_service


# Convenience functions
async def record_user_activity(user_id: str, activity_type: str, metadata: Optional[Dict] = None) -> List[Achievement]:
    """Record user activity and check for achievements."""
    return await get_gamification_service().record_activity(user_id, activity_type, metadata)


def get_user_gamification_profile(user_id: str) -> Dict[str, Any]:
    """Get user's gamification profile."""
    return get_gamification_service().get_profile(user_id)


def get_achievement_list(user_id: str) -> List[Dict[str, Any]]:
    """Get achievements list for user."""
    return get_gamification_service().get_achievements(user_id)
