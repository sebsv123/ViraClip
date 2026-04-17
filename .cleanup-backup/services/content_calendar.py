"""
Content Calendar and Intelligent Scheduling Service
Smart content scheduling with optimal timing prediction.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class ContentType(Enum):
    """Types of content."""
    SHORT_FORM = "short_form"
    LONG_FORM = "long_form"
    LIVE = "live"
    STORY = "story"
    REPOST = "repost"


class ScheduleStatus(Enum):
    """Scheduling status."""
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


@dataclass
class ScheduledContent:
    """Content scheduled for publication."""
    schedule_id: str
    user_id: str
    clip_id: str
    content_type: ContentType
    platforms: List[str]
    scheduled_time: str
    caption: str
    hashtags: List[str]
    thumbnail_url: str
    status: ScheduleStatus
    timezone: str
    optimal_score: float
    created_at: str
    published_at: Optional[str]


@dataclass
class TimeSlot:
    """Optimal posting time slot."""
    day_of_week: int  # 0-6
    hour: int  # 0-23
    score: float
    engagement_prediction: float
    competition_level: str
    reason: str


class ContentCalendarService:
    """
    Intelligent content scheduling and calendar management.
    """
    
    def __init__(self):
        self._scheduled_content: Dict[str, ScheduledContent] = {}
        self._user_calendars: Dict[str, List[str]] = {}
        self._optimal_slots_cache: Dict[str, List[TimeSlot]] = {}
        
        # Platform-specific best times (simplified)
        self._platform_best_times = {
            "youtube": [(14, 16), (18, 21)],  # 2-4pm, 6-9pm
            "tiktok": [(9, 11), (19, 21)],   # 9-11am, 7-9pm
            "instagram": [(11, 13), (19, 21)], # 11am-1pm, 7-9pm
            "twitter": [(9, 15)],             # 9am-3pm
            "facebook": [(13, 16)]            # 1-4pm
        }
    
    async def schedule_content(
        self,
        user_id: str,
        clip_id: str,
        platforms: List[str],
        preferred_time: Optional[datetime] = None,
        content_type: ContentType = ContentType.SHORT_FORM,
        caption: str = "",
        hashtags: List[str] = None,
        thumbnail_url: str = "",
        auto_optimize: bool = True
    ) -> ScheduledContent:
        """Schedule content for optimal publication."""
        import uuid
        
        schedule_id = str(uuid.uuid4())
        
        # Determine optimal time if not specified
        if auto_optimize or not preferred_time:
            optimal_time = await self._calculate_optimal_time(
                user_id, platforms, content_type
            )
        else:
            optimal_time = preferred_time
        
        # Calculate optimization score
        score = await self._calculate_optimization_score(
            optimal_time, platforms, user_id
        )
        
        scheduled = ScheduledContent(
            schedule_id=schedule_id,
            user_id=user_id,
            clip_id=clip_id,
            content_type=content_type,
            platforms=platforms,
            scheduled_time=optimal_time.isoformat(),
            caption=caption,
            hashtags=hashtags or [],
            thumbnail_url=thumbnail_url,
            status=ScheduleStatus.SCHEDULED,
            timezone="UTC",
            optimal_score=score,
            created_at=datetime.now().isoformat(),
            published_at=None
        )
        
        self._scheduled_content[schedule_id] = scheduled
        
        if user_id not in self._user_calendars:
            self._user_calendars[user_id] = []
        self._user_calendars[user_id].append(schedule_id)
        
        logger.info(
            f"Scheduled content {schedule_id} for {optimal_time} "
            f"(score: {score:.2f})"
        )
        
        return scheduled
    
    async def _calculate_optimal_time(
        self,
        user_id: str,
        platforms: List[str],
        content_type: ContentType
    ) -> datetime:
        """Calculate optimal publication time using ML."""
        now = datetime.now()
        
        # Get user's audience activity pattern
        audience_pattern = await self._get_audience_pattern(user_id)
        
        # Get platform best times
        platform_times = []
        for platform in platforms:
            if platform in self._platform_best_times:
                platform_times.extend(self._platform_best_times[platform])
        
        # Find intersection of audience activity and platform best times
        best_score = 0
        best_time = now + timedelta(hours=2)  # Default: 2 hours from now
        
        # Try next 7 days
        for day in range(7):
            test_date = now + timedelta(days=day)
            
            for hour in range(24):
                test_time = test_date.replace(hour=hour, minute=0, second=0, microsecond=0)
                
                if test_time < now:
                    continue
                
                # Calculate score
                score = audience_pattern.get(hour, 0.5)
                
                # Boost for platform best times
                for start, end in platform_times:
                    if start <= hour <= end:
                        score *= 1.3
                
                # Weekend bonus for entertainment content
                if content_type == ContentType.SHORT_FORM and test_date.weekday() >= 5:
                    score *= 1.1
                
                if score > best_score:
                    best_score = score
                    best_time = test_time
        
        return best_time
    
    async def _get_audience_pattern(self, user_id: str) -> Dict[int, float]:
        """Get hourly engagement pattern for user's audience."""
        # In production, would query analytics database
        # Simplified pattern: peaks at lunch and evening
        return {
            9: 0.6, 10: 0.7, 11: 0.8, 12: 0.85, 13: 0.9, 14: 0.85,
            15: 0.7, 16: 0.6, 17: 0.65, 18: 0.75, 19: 0.9, 20: 0.95,
            21: 0.9, 22: 0.8, 23: 0.6
        }
    
    async def _calculate_optimization_score(
        self,
        scheduled_time: datetime,
        platforms: List[str],
        user_id: str
    ) -> float:
        """Calculate how optimal the scheduled time is."""
        # Base score
        score = 0.7
        
        # Factor 1: Time of day (avoid 2-6am)
        hour = scheduled_time.hour
        if 2 <= hour <= 6:
            score -= 0.3
        elif 18 <= hour <= 21:
            score += 0.15
        
        # Factor 2: Day of week
        if scheduled_time.weekday() < 5:  # Weekday
            score += 0.05
        
        # Factor 3: Platform diversity
        if len(platforms) > 2:
            score += 0.05
        
        # Factor 4: Historical performance
        user_history = await self._get_user_performance_history(user_id)
        if user_history > 0.7:
            score += 0.1
        
        return min(1.0, max(0.0, score))
    
    async def _get_user_performance_history(self, user_id: str) -> float:
        """Get user's historical publishing performance."""
        # Simplified - would query actual metrics
        return 0.75
    
    async def get_calendar_view(
        self,
        user_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """Get calendar view for date range."""
        schedule_ids = self._user_calendars.get(user_id, [])
        
        events = []
        for sid in schedule_ids:
            content = self._scheduled_content.get(sid)
            if not content:
                continue
            
            content_time = datetime.fromisoformat(content.scheduled_time)
            
            if start_date <= content_time <= end_date:
                events.append({
                    "schedule_id": content.schedule_id,
                    "clip_id": content.clip_id,
                    "scheduled_time": content.scheduled_time,
                    "platforms": content.platforms,
                    "status": content.status.value,
                    "caption": content.caption[:50] + "..." if len(content.caption) > 50 else content.caption,
                    "thumbnail": content.thumbnail_url,
                    "optimal_score": content.optimal_score
                })
        
        # Get optimal slots for empty times
        optimal_slots = await self._suggest_optimal_slots(
            user_id, start_date, end_date
        )
        
        return {
            "user_id": user_id,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "events": sorted(events, key=lambda x: x["scheduled_time"]),
            "optimal_slots": optimal_slots,
            "total_scheduled": len(events),
            "publishing": len([e for e in events if e["status"] == "scheduled"])
        }
    
    async def _suggest_optimal_slots(
        self,
        user_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict[str, Any]]:
        """Suggest optimal posting slots."""
        slots = []
        
        audience_pattern = await self._get_audience_pattern(user_id)
        
        current = start_date
        while current <= end_date:
            for hour in [12, 19]:  # Suggest lunch and evening
                if audience_pattern.get(hour, 0) > 0.7:
                    slots.append({
                        "date": current.strftime("%Y-%m-%d"),
                        "hour": hour,
                        "score": audience_pattern[hour],
                        "reason": "High audience activity period"
                    })
            
            current += timedelta(days=1)
        
        return sorted(slots, key=lambda x: x["score"], reverse=True)[:5]
    
    async def reschedule_content(
        self,
        schedule_id: str,
        new_time: datetime,
        reason: str = ""
    ) -> bool:
        """Reschedule content to new time."""
        if schedule_id not in self._scheduled_content:
            return False
        
        content = self._scheduled_content[schedule_id]
        
        if content.status != ScheduleStatus.SCHEDULED:
            return False
        
        old_time = content.scheduled_time
        content.scheduled_time = new_time.isoformat()
        
        # Recalculate score
        content.optimal_score = await self._calculate_optimization_score(
            new_time, content.platforms, content.user_id
        )
        
        logger.info(
            f"Rescheduled {schedule_id} from {old_time} to {new_time}. "
            f"Reason: {reason}"
        )
        
        return True
    
    async def cancel_scheduled(self, schedule_id: str) -> bool:
        """Cancel scheduled content."""
        if schedule_id not in self._scheduled_content:
            return False
        
        content = self._scheduled_content[schedule_id]
        
        if content.status != ScheduleStatus.SCHEDULED:
            return False
        
        content.status = ScheduleStatus.DRAFT
        
        # Remove from calendar
        if content.user_id in self._user_calendars:
            self._user_calendars[content.user_id].remove(schedule_id)
        
        return True
    
    async def get_publishing_queue(
        self,
        user_id: str,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get upcoming publishing queue."""
        schedule_ids = self._user_calendars.get(user_id, [])
        
        upcoming = []
        now = datetime.now()
        
        for sid in schedule_ids:
            content = self._scheduled_content.get(sid)
            if not content or content.status != ScheduleStatus.SCHEDULED:
                continue
            
            content_time = datetime.fromisoformat(content.scheduled_time)
            if content_time >= now:
                upcoming.append({
                    "schedule_id": content.schedule_id,
                    "scheduled_time": content.scheduled_time,
                    "time_until": str(content_time - now),
                    "platforms": content.platforms,
                    "optimal_score": content.optimal_score,
                    "thumbnail": content.thumbnail_url
                })
        
        return sorted(upcoming, key=lambda x: x["scheduled_time"])[:limit]
    
    async def bulk_schedule(
        self,
        user_id: str,
        items: List[Dict[str, Any]],
        spacing_hours: int = 4
    ) -> List[ScheduledContent]:
        """Bulk schedule multiple items with intelligent spacing."""
        scheduled = []
        base_time = datetime.now() + timedelta(hours=2)
        
        for i, item in enumerate(items):
            scheduled_time = base_time + timedelta(hours=i * spacing_hours)
            
            content = await self.schedule_content(
                user_id=user_id,
                clip_id=item["clip_id"],
                platforms=item["platforms"],
                preferred_time=scheduled_time,
                content_type=item.get("content_type", ContentType.SHORT_FORM),
                caption=item.get("caption", ""),
                hashtags=item.get("hashtags", []),
                thumbnail_url=item.get("thumbnail_url", ""),
                auto_optimize=False
            )
            
            scheduled.append(content)
        
        return scheduled
    
    def get_scheduling_stats(self, user_id: str) -> Dict[str, Any]:
        """Get scheduling statistics."""
        schedule_ids = self._user_calendars.get(user_id, [])
        
        if not schedule_ids:
            return {
                "total_scheduled": 0,
                "published": 0,
                "failed": 0,
                "avg_optimal_score": 0
            }
        
        contents = [
            self._scheduled_content[sid]
            for sid in schedule_ids
            if sid in self._scheduled_content
        ]
        
        return {
            "total_scheduled": len(contents),
            "published": len([c for c in contents if c.status == ScheduleStatus.PUBLISHED]),
            "scheduled": len([c for c in contents if c.status == ScheduleStatus.SCHEDULED]),
            "failed": len([c for c in contents if c.status == ScheduleStatus.FAILED]),
            "avg_optimal_score": sum(c.optimal_score for c in contents) / len(contents),
            "platforms_used": list(set(
                p for c in contents for p in c.platforms
            ))
        }


# Global instance
_calendar_service: Optional[ContentCalendarService] = None


def get_calendar_service() -> ContentCalendarService:
    """Get global content calendar service."""
    global _calendar_service
    if _calendar_service is None:
        _calendar_service = ContentCalendarService()
    return _calendar_service
