"""
Real-time Notifications System
WebSocket-based notifications for task updates and user alerts.
"""

import json
import logging
from typing import Dict, Any, List, Optional, Set, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import asyncio

logger = logging.getLogger(__name__)


class NotificationType(Enum):
    """Types of notifications."""
    TASK_STARTED = "task_started"
    TASK_PROGRESS = "task_progress"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    CLIP_READY = "clip_ready"
    EXPORT_COMPLETE = "export_complete"
    COLLABORATION_INVITE = "collab_invite"
    SYSTEM_MAINTENANCE = "system_maintenance"
    ACHIEVEMENT_UNLOCKED = "achievement_unlocked"


@dataclass
class Notification:
    """A notification message."""
    id: str
    type: NotificationType
    user_id: str
    title: str
    message: str
    timestamp: str
    data: Dict[str, Any]
    read: bool = False
    priority: str = "normal"  # low, normal, high, urgent


class NotificationManager:
    """
    Manages real-time notifications via WebSocket.
    """
    
    def __init__(self):
        # User ID -> Set of WebSocket connections
        self._connections: Dict[str, Set] = {}
        # User ID -> List of unread notifications
        self._unread_notifications: Dict[str, List[Notification]] = {}
        # Notification history
        self._history: List[Notification] = []
        # Callbacks for different notification types
        self._handlers: Dict[NotificationType, List[Callable]] = {}
    
    async def connect(self, user_id: str, websocket) -> None:
        """Connect a user's WebSocket."""
        if user_id not in self._connections:
            self._connections[user_id] = set()
        
        self._connections[user_id].add(websocket)
        
        # Send any unread notifications
        await self._send_unread(user_id, websocket)
        
        logger.info(f"User {user_id} connected to notifications")
    
    async def disconnect(self, user_id: str, websocket) -> None:
        """Disconnect a user's WebSocket."""
        if user_id in self._connections:
            self._connections[user_id].discard(websocket)
            
            if not self._connections[user_id]:
                del self._connections[user_id]
        
        logger.info(f"User {user_id} disconnected from notifications")
    
    async def send_notification(
        self,
        user_id: str,
        notification_type: NotificationType,
        title: str,
        message: str,
        data: Optional[Dict[str, Any]] = None,
        priority: str = "normal"
    ) -> Notification:
        """Send a notification to a user."""
        import uuid
        
        notification = Notification(
            id=str(uuid.uuid4()),
            type=notification_type,
            user_id=user_id,
            title=title,
            message=message,
            timestamp=datetime.now().isoformat(),
            data=data or {},
            priority=priority
        )
        
        # Store in unread if user not connected
        if user_id not in self._connections:
            if user_id not in self._unread_notifications:
                self._unread_notifications[user_id] = []
            self._unread_notifications[user_id].append(notification)
        else:
            # Send to all connected WebSockets
            await self._broadcast_to_user(user_id, notification)
        
        # Store in history
        self._history.append(notification)
        
        # Trigger handlers
        await self._trigger_handlers(notification)
        
        return notification
    
    async def broadcast_to_all(
        self,
        notification_type: NotificationType,
        title: str,
        message: str,
        data: Optional[Dict[str, Any]] = None,
        exclude_user: Optional[str] = None
    ) -> None:
        """Broadcast notification to all connected users."""
        for user_id in self._connections:
            if user_id != exclude_user:
                await self.send_notification(
                    user_id, notification_type, title, message, data
                )
    
    async def _broadcast_to_user(self, user_id: str, notification: Notification) -> None:
        """Send notification to all user's WebSocket connections."""
        if user_id not in self._connections:
            return
        
        message = {
            "type": "notification",
            "notification": {
                "id": notification.id,
                "type": notification.type.value,
                "title": notification.title,
                "message": notification.message,
                "timestamp": notification.timestamp,
                "data": notification.data,
                "priority": notification.priority
            }
        }
        
        # Send to all connections
        disconnected = []
        for ws in self._connections[user_id]:
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(ws)
        
        # Clean up disconnected
        for ws in disconnected:
            self._connections[user_id].discard(ws)
    
    async def _send_unread(self, user_id: str, websocket) -> None:
        """Send unread notifications to a newly connected user."""
        if user_id not in self._unread_notifications:
            return
        
        notifications = self._unread_notifications[user_id]
        
        for notification in notifications:
            message = {
                "type": "notification",
                "notification": {
                    "id": notification.id,
                    "type": notification.type.value,
                    "title": notification.title,
                    "message": notification.message,
                    "timestamp": notification.timestamp,
                    "data": notification.data,
                    "priority": notification.priority,
                    "unread": True
                }
            }
            
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send unread notification: {e}")
        
        # Clear unread after sending
        del self._unread_notifications[user_id]
    
    async def mark_as_read(self, user_id: str, notification_id: str) -> bool:
        """Mark a notification as read."""
        # Find in unread
        if user_id in self._unread_notifications:
            for notif in self._unread_notifications[user_id]:
                if notif.id == notification_id:
                    notif.read = True
                    return True
        
        # Find in history
        for notif in self._history:
            if notif.id == notification_id and notif.user_id == user_id:
                notif.read = True                
                # Notify client
                await self._send_read_receipt(user_id, notification_id)
                return True
        
        return False
    
    async def _send_read_receipt(self, user_id: str, notification_id: str) -> None:
        """Send read receipt to user's clients."""
        if user_id not in self._connections:
            return
        
        message = {
            "type": "read_receipt",
            "notification_id": notification_id
        }
        
        for ws in self._connections[user_id]:
            try:
                await ws.send_json(message)
            except Exception:
                pass
    
    def register_handler(
        self,
        notification_type: NotificationType,
        handler: Callable[[Notification], None]
    ) -> None:
        """Register a handler for a notification type."""
        if notification_type not in self._handlers:
            self._handlers[notification_type] = []
        self._handlers[notification_type].append(handler)
    
    async def _trigger_handlers(self, notification: Notification) -> None:
        """Trigger registered handlers for a notification."""
        handlers = self._handlers.get(notification.type, [])
        
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(notification)
                else:
                    handler(notification)
            except Exception as e:
                logger.error(f"Notification handler error: {e}")
    
    def get_user_notifications(
        self,
        user_id: str,
        include_read: bool = False,
        limit: int = 50
    ) -> List[Notification]:
        """Get notifications for a user."""
        notifications = []
        
        # Get from unread
        if user_id in self._unread_notifications:
            notifications.extend(self._unread_notifications[user_id])
        
        # Get from history
        for notif in reversed(self._history):
            if notif.user_id == user_id:
                if include_read or not notif.read:
                    notifications.append(notif)
            
            if len(notifications) >= limit:
                break
        
        return notifications[:limit]
    
    def get_unread_count(self, user_id: str) -> int:
        """Get count of unread notifications for a user."""
        count = 0
        
        if user_id in self._unread_notifications:
            count += len(self._unread_notifications[user_id])
        
        # Count unread in history
        for notif in self._history:
            if notif.user_id == user_id and not notif.read:
                count += 1
        
        return count


class TaskNotificationHelper:
    """Helper class for sending task-related notifications."""
    
    def __init__(self, notification_manager: NotificationManager):
        self._notifications = notification_manager
    
    async def notify_task_started(self, user_id: str, task_id: str) -> None:
        """Notify user that task has started."""
        await self._notifications.send_notification(
            user_id=user_id,
            notification_type=NotificationType.TASK_STARTED,
            title="🎬 Processing Started",
            message="Your video is being processed. We'll notify you when clips are ready!",
            data={"task_id": task_id, "status": "processing"},
            priority="normal"
        )
    
    async def notify_task_progress(
        self,
        user_id: str,
        task_id: str,
        progress: int,
        stage: str
    ) -> None:
        """Send progress update."""
        await self._notifications.send_notification(
            user_id=user_id,
            notification_type=NotificationType.TASK_PROGRESS,
            title="⏳ Processing Update",
            message=f"{stage}... ({progress}% complete)",
            data={
                "task_id": task_id,
                "progress": progress,
                "stage": stage
            },
            priority="low"
        )
    
    async def notify_task_completed(
        self,
        user_id: str,
        task_id: str,
        clip_count: int
    ) -> None:
        """Notify user that task completed successfully."""
        await self._notifications.send_notification(
            user_id=user_id,
            notification_type=NotificationType.TASK_COMPLETED,
            title="✅ Clips Ready!",
            message=f"Your video has been processed into {clip_count} viral clips. Review them now!",
            data={
                "task_id": task_id,
                "clip_count": clip_count,
                "action": "view_clips"
            },
            priority="high"
        )
    
    async def notify_task_failed(
        self,
        user_id: str,
        task_id: str,
        error: str
    ) -> None:
        """Notify user of task failure."""
        await self._notifications.send_notification(
            user_id=user_id,
            notification_type=NotificationType.TASK_FAILED,
            title="❌ Processing Failed",
            message=f"We encountered an issue: {error[:100]}. Our team has been notified.",
            data={
                "task_id": task_id,
                "error": error,
                "action": "retry"
            },
            priority="urgent"
        )
    
    async def notify_clip_ready(
        self,
        user_id: str,
        clip_id: str,
        virality_score: float
    ) -> None:
        """Notify that a high-virality clip is ready."""
        if virality_score > 75:
            await self._notifications.send_notification(
                user_id=user_id,
                notification_type=NotificationType.CLIP_READY,
                title="🔥 High-Virality Clip Ready!",
                message=f"A clip with {virality_score:.0f}% virality score is ready for export!",
                data={
                    "clip_id": clip_id,
                    "virality_score": virality_score,
                    "action": "export_clip"
                },
                priority="high"
            )
    
    async def notify_export_complete(
        self,
        user_id: str,
        export_id: str,
        platform: str
    ) -> None:
        """Notify that export is complete."""
        await self._notifications.send_notification(
            user_id=user_id,
            notification_type=NotificationType.EXPORT_COMPLETE,
            title="📤 Export Complete",
            message=f"Your clip has been exported for {platform} and is ready to upload!",
            data={
                "export_id": export_id,
                "platform": platform,
                "action": "download"
            },
            priority="normal"
        )


# Global instance
_notification_manager: Optional[NotificationManager] = None


def get_notification_manager() -> NotificationManager:
    """Get global notification manager instance."""
    global _notification_manager
    if _notification_manager is None:
        _notification_manager = NotificationManager()
    return _notification_manager


def get_task_notifier() -> TaskNotificationHelper:
    """Get task notification helper."""
    return TaskNotificationHelper(get_notification_manager())
