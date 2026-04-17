"""
Smart Notifications Service
ML-powered notification system with intelligent delivery optimization.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import random

logger = logging.getLogger(__name__)


class NotificationChannel(Enum):
    """Notification delivery channels."""
    EMAIL = "email"
    PUSH = "push"
    SMS = "sms"
    SLACK = "slack"
    DISCORD = "discord"
    IN_APP = "in_app"


class NotificationPriority(Enum):
    """Notification priority levels."""
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class NotificationType(Enum):
    """Types of notifications."""
    CLIP_READY = "clip_ready"
    VIRAL_MILESTONE = "viral_milestone"
    TASK_COMPLETED = "task_completed"
    SYSTEM_ALERT = "system_alert"
    COLLABORATION = "collaboration"
    MARKETING = "marketing"
    SECURITY = "security"


@dataclass
class UserPreferences:
    """User notification preferences."""
    user_id: str
    channels: List[NotificationChannel]
    quiet_hours_start: int  # 0-23
    quiet_hours_end: int  # 0-23
    timezone: str
    max_per_hour: int
    priority_threshold: NotificationPriority
    ml_optimized: bool


@dataclass
class Notification:
    """Notification message."""
    notification_id: str
    user_id: str
    type: NotificationType
    priority: NotificationPriority
    title: str
    message: str
    channels: List[NotificationChannel]
    data: Dict[str, Any]
    created_at: str
    scheduled_for: Optional[str]
    delivered_at: Optional[str]
    read_at: Optional[str]
    engagement_score: float


@dataclass
class EngagementHistory:
    """User engagement with notifications."""
    user_id: str
    notification_type: NotificationType
    channel: NotificationChannel
    sent_at: str
    opened_at: Optional[str]
    clicked: bool
    dismissed: bool


class SmartNotificationService:
    """
    ML-powered smart notification system.
    """
    
    def __init__(self):
        self._user_preferences: Dict[str, UserPreferences] = {}
        self._notifications: Dict[str, Notification] = {}
        self._engagement_history: List[EngagementHistory] = []
        self._ml_models: Dict[str, Any] = {}
        
        # Default preferences
        self._default_prefs = UserPreferences(
            user_id="",
            channels=[NotificationChannel.EMAIL, NotificationChannel.IN_APP],
            quiet_hours_start=22,
            quiet_hours_end=8,
            timezone="UTC",
            max_per_hour=10,
            priority_threshold=NotificationPriority.NORMAL,
            ml_optimized=True
        )
    
    async def set_user_preferences(
        self,
        user_id: str,
        channels: List[NotificationChannel],
        quiet_hours: tuple = (22, 8),
        timezone: str = "UTC",
        max_per_hour: int = 10,
        ml_optimized: bool = True
    ) -> UserPreferences:
        """Set user notification preferences."""
        prefs = UserPreferences(
            user_id=user_id,
            channels=channels,
            quiet_hours_start=quiet_hours[0],
            quiet_hours_end=quiet_hours[1],
            timezone=timezone,
            max_per_hour=max_per_hour,
            priority_threshold=NotificationPriority.NORMAL,
            ml_optimized=ml_optimized
        )
        
        self._user_preferences[user_id] = prefs
        logger.info(f"Set notification preferences for user {user_id}")
        return prefs
    
    async def send_notification(
        self,
        user_id: str,
        notification_type: NotificationType,
        priority: NotificationPriority,
        title: str,
        message: str,
        data: Dict[str, Any] = None,
        channels: Optional[List[NotificationChannel]] = None
    ) -> Notification:
        """Send smart notification optimized by ML."""
        import uuid
        
        notification_id = str(uuid.uuid4())
        
        # Get user preferences
        prefs = self._user_preferences.get(user_id, self._default_prefs)
        
        # Determine optimal channels
        if not channels:
            channels = await self._optimize_channels(user_id, notification_type, priority, prefs)
        
        # Calculate optimal delivery time
        scheduled_for = await self._optimize_delivery_time(user_id, prefs)
        
        # Predict engagement score
        engagement_score = await self._predict_engagement(
            user_id, notification_type, channels, scheduled_for
        )
        
        notification = Notification(
            notification_id=notification_id,
            user_id=user_id,
            type=notification_type,
            priority=priority,
            title=title,
            message=message,
            channels=channels,
            data=data or {},
            created_at=datetime.now().isoformat(),
            scheduled_for=scheduled_for,
            delivered_at=None,
            read_at=None,
            engagement_score=engagement_score
        )
        
        self._notifications[notification_id] = notification
        
        # Deliver immediately if scheduled for now
        if not scheduled_for or scheduled_for <= datetime.now().isoformat():
            await self._deliver_notification(notification)
        
        logger.info(
            f"Created notification {notification_id} for user {user_id} "
            f"(engagement score: {engagement_score:.2f})"
        )
        
        return notification
    
    async def _optimize_channels(
        self,
        user_id: str,
        notification_type: NotificationType,
        priority: NotificationPriority,
        prefs: UserPreferences
    ) -> List[NotificationChannel]:
        """ML-optimized channel selection."""
        # Get historical engagement by channel
        channel_performance = self._get_channel_performance(user_id, notification_type)
        
        # Select best performing channels
        sorted_channels = sorted(
            channel_performance.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        # Take top 2 channels that user has enabled
        selected = [
            ch for ch, _ in sorted_channels[:2]
            if ch in prefs.channels
        ]
        
        # For critical, add all available channels
        if priority == NotificationPriority.CRITICAL:
            selected = list(prefs.channels)
        
        return selected if selected else prefs.channels[:1]
    
    def _get_channel_performance(
        self,
        user_id: str,
        notification_type: NotificationType
    ) -> Dict[NotificationChannel, float]:
        """Get historical performance of channels for user."""
        # Filter engagement history
        relevant = [
            e for e in self._engagement_history
            if e.user_id == user_id and e.notification_type == notification_type
        ]
        
        if not relevant:
            # Default performance
            return {
                NotificationChannel.EMAIL: 0.7,
                NotificationChannel.PUSH: 0.8,
                NotificationChannel.SLACK: 0.6,
                NotificationChannel.IN_APP: 0.75
            }
        
        # Calculate open rates by channel
        performance = {}
        for channel in NotificationChannel:
            channel_events = [e for e in relevant if e.channel == channel]
            if channel_events:
                opens = len([e for e in channel_events if e.opened_at])
                performance[channel] = opens / len(channel_events)
            else:
                performance[channel] = 0.5
        
        return performance
    
    async def _optimize_delivery_time(
        self,
        user_id: str,
        prefs: UserPreferences
    ) -> Optional[str]:
        """ML-optimized delivery time prediction."""
        if not prefs.ml_optimized:
            return None
        
        # Get user's engagement pattern
        pattern = self._get_user_engagement_pattern(user_id)
        
        # Find best time in next 24 hours
        now = datetime.now()
        best_time = now
        best_score = 0
        
        for hour in range(24):
            test_time = now + timedelta(hours=hour)
            
            # Skip quiet hours
            if prefs.quiet_hours_start <= test_time.hour <= prefs.quiet_hours_end:
                continue
            
            # Calculate engagement score for this hour
            score = pattern.get(test_time.hour, 0.5)
            
            # Add recency boost (prefer sooner)
            score *= (1 - hour / 48)
            
            if score > best_score:
                best_score = score
                best_time = test_time
        
        return best_time.isoformat()
    
    def _get_user_engagement_pattern(self, user_id: str) -> Dict[int, float]:
        """Get hourly engagement pattern for user."""
        relevant = [e for e in self._engagement_history if e.user_id == user_id]
        
        if not relevant:
            return {h: 0.5 for h in range(24)}
        
        hourly_engagement = {h: [] for h in range(24)}
        
        for event in relevant:
            hour = datetime.fromisoformat(event.sent_at).hour
            engaged = 1 if event.opened_at else 0
            hourly_engagement[hour].append(engaged)
        
        return {
            hour: sum(scores) / len(scores) if scores else 0.5
            for hour, scores in hourly_engagement.items()
        }
    
    async def _predict_engagement(
        self,
        user_id: str,
        notification_type: NotificationType,
        channels: List[NotificationChannel],
        scheduled_time: Optional[str]
    ) -> float:
        """Predict engagement score using ML model."""
        # Simplified prediction
        base_score = 0.6
        
        # Channel boost
        channel_boost = {
            NotificationChannel.PUSH: 0.15,
            NotificationChannel.SMS: 0.1,
            NotificationChannel.EMAIL: 0.05,
            NotificationChannel.IN_APP: 0.08
        }
        
        for ch in channels:
            base_score += channel_boost.get(ch, 0)
        
        # Type adjustment
        type_multipliers = {
            NotificationType.CLIP_READY: 1.2,
            NotificationType.VIRAL_MILESTONE: 1.3,
            NotificationType.TASK_COMPLETED: 1.0,
            NotificationType.MARKETING: 0.7
        }
        
        base_score *= type_multipliers.get(notification_type, 1.0)
        
        return min(1.0, base_score)
    
    async def _deliver_notification(self, notification: Notification) -> bool:
        """Deliver notification through selected channels."""
        success = True
        
        for channel in notification.channels:
            try:
                if channel == NotificationChannel.EMAIL:
                    await self._send_email(notification)
                elif channel == NotificationChannel.PUSH:
                    await self._send_push(notification)
                elif channel == NotificationChannel.SLACK:
                    await self._send_slack(notification)
                elif channel == NotificationChannel.IN_APP:
                    await self._send_in_app(notification)
                
                # Track engagement
                history = EngagementHistory(
                    user_id=notification.user_id,
                    notification_type=notification.type,
                    channel=channel,
                    sent_at=datetime.now().isoformat(),
                    opened_at=None,
                    clicked=False,
                    dismissed=False
                )
                self._engagement_history.append(history)
                
            except Exception as e:
                logger.error(f"Failed to deliver to {channel.value}: {e}")
                success = False
        
        notification.delivered_at = datetime.now().isoformat()
        return success
    
    async def _send_email(self, notification: Notification) -> bool:
        """Send email notification."""
        logger.info(f"Sending email to {notification.user_id}: {notification.title}")
        return True
    
    async def _send_push(self, notification: Notification) -> bool:
        """Send push notification."""
        logger.info(f"Sending push to {notification.user_id}: {notification.title}")
        return True
    
    async def _send_slack(self, notification: Notification) -> bool:
        """Send Slack notification."""
        logger.info(f"Sending Slack to {notification.user_id}: {notification.title}")
        return True
    
    async def _send_in_app(self, notification: Notification) -> bool:
        """Send in-app notification."""
        logger.info(f"Sending in-app to {notification.user_id}: {notification.title}")
        return True
    
    async def mark_as_read(self, notification_id: str) -> bool:
        """Mark notification as read."""
        if notification_id not in self._notifications:
            return False
        
        notification = self._notifications[notification_id]
        notification.read_at = datetime.now().isoformat()
        
        # Update engagement history
        for history in self._engagement_history:
            if history.sent_at <= notification.created_at:
                history.opened_at = datetime.now().isoformat()
                break
        
        return True
    
    def get_user_notifications(
        self,
        user_id: str,
        unread_only: bool = False,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get notifications for user."""
        notifications = [
            n for n in self._notifications.values()
            if n.user_id == user_id
        ]
        
        if unread_only:
            notifications = [n for n in notifications if not n.read_at]
        
        notifications.sort(key=lambda x: x.created_at, reverse=True)
        
        return [
            {
                "notification_id": n.notification_id,
                "type": n.type.value,
                "priority": n.priority.value,
                "title": n.title,
                "message": n.message,
                "channels": [c.value for c in n.channels],
                "created_at": n.created_at,
                "delivered_at": n.delivered_at,
                "read_at": n.read_at,
                "engagement_score": n.engagement_score,
                "data": n.data
            }
            for n in notifications[:limit]
        ]
    
    def get_notification_stats(self, user_id: str) -> Dict[str, Any]:
        """Get notification statistics for user."""
        user_notifications = [n for n in self._notifications.values() if n.user_id == user_id]
        user_history = [e for e in self._engagement_history if e.user_id == user_id]
        
        total_sent = len(user_notifications)
        total_read = len([n for n in user_notifications if n.read_at])
        total_delivered = len([n for n in user_notifications if n.delivered_at])
        
        # Engagement rate by type
        type_engagement = {}
        for n in user_notifications:
            if n.type not in type_engagement:
                type_engagement[n.type.value] = {"sent": 0, "read": 0}
            type_engagement[n.type.value]["sent"] += 1
            if n.read_at:
                type_engagement[n.type.value]["read"] += 1
        
        return {
            "total_sent": total_sent,
            "total_delivered": total_delivered,
            "total_read": total_read,
            "delivery_rate": total_delivered / total_sent if total_sent > 0 else 0,
            "read_rate": total_read / total_delivered if total_delivered > 0 else 0,
            "avg_engagement_score": sum(n.engagement_score for n in user_notifications) / len(user_notifications) if user_notifications else 0,
            "by_type": type_engagement
        }
    
    async def batch_send(
        self,
        user_ids: List[str],
        notification_type: NotificationType,
        priority: NotificationPriority,
        title: str,
        message: str,
        data: Dict[str, Any] = None
    ) -> List[Notification]:
        """Send notification to multiple users."""
        notifications = []
        
        for user_id in user_ids:
            notification = await self.send_notification(
                user_id, notification_type, priority, title, message, data
            )
            notifications.append(notification)
        
        return notifications


# Global instance
_notification_service: Optional[SmartNotificationService] = None


def get_notification_service() -> SmartNotificationService:
    """Get global smart notification service."""
    global _notification_service
    if _notification_service is None:
        _notification_service = SmartNotificationService()
    return _notification_service
