"""
Real-time Collaboration Editing Service
WebSocket-based collaborative editing for video projects.
"""

import json
import logging
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import asyncio

logger = logging.getLogger(__name__)


class EditOperationType(Enum):
    """Types of collaborative edit operations."""
    CURSOR_MOVE = "cursor_move"
    SELECTION_CHANGE = "selection_change"
    CLIP_ADD = "clip_add"
    CLIP_REMOVE = "clip_remove"
    CLIP_UPDATE = "clip_update"
    TIMELINE_SCROLL = "timeline_scroll"
    PLAYHEAD_MOVE = "playhead_move"
    COMMENT_ADD = "comment_add"
    TEXT_EDIT = "text_edit"


@dataclass
class UserPresence:
    """User presence in collaborative session."""
    user_id: str
    username: str
    color: str  # Cursor color
    cursor_position: Optional[Dict[str, float]] = None
    current_clip: Optional[str] = None
    is_active: bool = True
    joined_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_activity: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class EditOperation:
    """A collaborative editing operation."""
    operation_id: str
    user_id: str
    project_id: str
    operation_type: EditOperationType
    data: Dict[str, Any]
    timestamp: str
    version: int  # For conflict resolution


@dataclass
class CollaborationSession:
    """Active collaboration session."""
    session_id: str
    project_id: str
    created_by: str
    created_at: str
    participants: Dict[str, UserPresence]
    operations: List[EditOperation]
    current_version: int
    is_active: bool = True


class RealtimeCollaborationService:
    """
    Manages real-time collaborative editing sessions.
    """
    
    def __init__(self):
        self._sessions: Dict[str, CollaborationSession] = {}
        self._user_connections: Dict[str, Set] = {}  # user_id -> WebSocket connections
        self._project_sessions: Dict[str, str] = {}   # project_id -> session_id
    
    async def create_session(
        self,
        project_id: str,
        created_by: str,
        username: str
    ) -> CollaborationSession:
        """Create a new collaboration session."""
        import uuid
        
        session_id = str(uuid.uuid4())
        
        # Create creator presence
        creator_presence = UserPresence(
            user_id=created_by,
            username=username,
            color=self._assign_user_color(0)
        )
        
        session = CollaborationSession(
            session_id=session_id,
            project_id=project_id,
            created_by=created_by,
            created_at=datetime.now().isoformat(),
            participants={created_by: creator_presence},
            operations=[],
            current_version=1
        )
        
        self._sessions[session_id] = session
        self._project_sessions[project_id] = session_id
        
        logger.info(f"Created collaboration session {session_id} for project {project_id}")
        return session
    
    async def join_session(
        self,
        session_id: str,
        user_id: str,
        username: str,
        websocket
    ) -> bool:
        """User joins a collaboration session."""
        if session_id not in self._sessions:
            return False
        
        session = self._sessions[session_id]
        
        if not session.is_active:
            return False
        
        # Assign color based on participant count
        color = self._assign_user_color(len(session.participants))
        
        # Add or update user presence
        presence = UserPresence(
            user_id=user_id,
            username=username,
            color=color
        )
        
        session.participants[user_id] = presence
        
        # Track WebSocket connection
        if user_id not in self._user_connections:
            self._user_connections[user_id] = set()
        self._user_connections[user_id].add(websocket)
        
        # Notify other participants
        await self._broadcast_presence_update(session_id, user_id, "joined")
        
        logger.info(f"User {user_id} joined session {session_id}")
        return True
    
    async def leave_session(
        self,
        session_id: str,
        user_id: str,
        websocket
    ) -> bool:
        """User leaves a collaboration session."""
        if session_id not in self._sessions:
            return False
        
        session = self._sessions[session_id]
        
        # Remove WebSocket connection
        if user_id in self._user_connections:
            self._user_connections[user_id].discard(websocket)
            if not self._user_connections[user_id]:
                del self._user_connections[user_id]
        
        # Mark user as inactive in session
        if user_id in session.participants:
            session.participants[user_id].is_active = False
            session.participants[user_id].last_activity = datetime.now().isoformat()
        
        # Notify other participants
        await self._broadcast_presence_update(session_id, user_id, "left")
        
        logger.info(f"User {user_id} left session {session_id}")
        return True
    
    async def handle_operation(
        self,
        session_id: str,
        user_id: str,
        operation_type: EditOperationType,
        data: Dict[str, Any]
    ) -> Optional[EditOperation]:
        """Handle an edit operation from a user."""
        if session_id not in self._sessions:
            return None
        
        session = self._sessions[session_id]
        
        if user_id not in session.participants:
            return None
        
        import uuid
        
        # Create operation
        operation = EditOperation(
            operation_id=str(uuid.uuid4()),
            user_id=user_id,
            project_id=session.project_id,
            operation_type=operation_type,
            data=data,
            timestamp=datetime.now().isoformat(),
            version=session.current_version + 1
        )
        
        # Add to session history
        session.operations.append(operation)
        session.current_version = operation.version
        
        # Update user activity
        session.participants[user_id].last_activity = datetime.now().isoformat()
        
        # Broadcast to other participants
        await self._broadcast_operation(session_id, operation, exclude_user=user_id)
        
        return operation
    
    async def update_cursor_position(
        self,
        session_id: str,
        user_id: str,
        position: Dict[str, float],
        current_clip: Optional[str] = None
    ) -> None:
        """Update user's cursor position."""
        if session_id not in self._sessions:
            return
        
        session = self._sessions[session_id]
        
        if user_id not in session.participants:
            return
        
        # Update presence
        presence = session.participants[user_id]
        presence.cursor_position = position
        presence.current_clip = current_clip
        presence.last_activity = datetime.now().isoformat()
        
        # Broadcast to others
        await self._broadcast_cursor_update(session_id, user_id, position, current_clip)
    
    def get_session_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get current state of collaboration session."""
        if session_id not in self._sessions:
            return None
        
        session = self._sessions[session_id]
        
        return {
            "session_id": session_id,
            "project_id": session.project_id,
            "created_at": session.created_at,
            "current_version": session.current_version,
            "participants": [
                {
                    "user_id": p.user_id,
                    "username": p.username,
                    "color": p.color,
                    "cursor_position": p.cursor_position,
                    "current_clip": p.current_clip,
                    "is_active": p.is_active
                }
                for p in session.participants.values()
            ],
            "active_participants": sum(1 for p in session.participants.values() if p.is_active),
            "total_operations": len(session.operations)
        }
    
    def get_user_active_sessions(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all active sessions for a user."""
        sessions = []
        
        for session in self._sessions.values():
            if user_id in session.participants and session.participants[user_id].is_active:
                sessions.append({
                    "session_id": session.session_id,
                    "project_id": session.project_id,
                    "participant_count": sum(1 for p in session.participants.values() if p.is_active)
                })
        
        return sessions
    
    async def _broadcast_operation(
        self,
        session_id: str,
        operation: EditOperation,
        exclude_user: Optional[str] = None
    ) -> None:
        """Broadcast operation to all session participants."""
        if session_id not in self._sessions:
            return
        
        session = self._sessions[session_id]
        
        message = {
            "type": "operation",
            "operation": {
                "operation_id": operation.operation_id,
                "user_id": operation.user_id,
                "operation_type": operation.operation_type.value,
                "data": operation.data,
                "timestamp": operation.timestamp,
                "version": operation.version
            }
        }
        
        # Send to all active participants except excluded
        for user_id, presence in session.participants.items():
            if user_id == exclude_user or not presence.is_active:
                continue
            
            if user_id in self._user_connections:
                for ws in self._user_connections[user_id]:
                    try:
                        await ws.send_json(message)
                    except:
                        pass
    
    async def _broadcast_presence_update(
        self,
        session_id: str,
        user_id: str,
        event: str
    ) -> None:
        """Broadcast presence update to session."""
        if session_id not in self._sessions:
            return
        
        session = self._sessions[session_id]
        
        if user_id not in session.participants:
            return
        
        presence = session.participants[user_id]
        
        message = {
            "type": "presence",
            "event": event,
            "user": {
                "user_id": user_id,
                "username": presence.username,
                "color": presence.color
            }
        }
        
        # Broadcast to all participants
        for uid, p in session.participants.items():
            if uid in self._user_connections:
                for ws in self._user_connections[uid]:
                    try:
                        await ws.send_json(message)
                    except:
                        pass
    
    async def _broadcast_cursor_update(
        self,
        session_id: str,
        user_id: str,
        position: Dict[str, float],
        current_clip: Optional[str]
    ) -> None:
        """Broadcast cursor position update."""
        if session_id not in self._sessions:
            return
        
        session = self._sessions[session_id]
        
        if user_id not in session.participants:
            return
        
        presence = session.participants[user_id]
        
        message = {
            "type": "cursor",
            "user_id": user_id,
            "username": presence.username,
            "color": presence.color,
            "position": position,
            "current_clip": current_clip
        }
        
        # Send to all other participants
        for uid, p in session.participants.items():
            if uid == user_id or not p.is_active:
                continue
            
            if uid in self._user_connections:
                for ws in self._user_connections[uid]:
                    try:
                        await ws.send_json(message)
                    except:
                        pass
    
    def _assign_user_color(self, index: int) -> str:
        """Assign a color to a user based on index."""
        colors = [
            "#FF6B6B", "#4ECDC4", "#45B7D1", "#FFA07A",
            "#98D8C8", "#F7DC6F", "#BB8FCE", "#85C1E2"
        ]
        return colors[index % len(colors)]
    
    async def end_session(self, session_id: str) -> bool:
        """End a collaboration session."""
        if session_id not in self._sessions:
            return False
        
        session = self._sessions[session_id]
        session.is_active = False
        
        # Notify all participants
        message = {"type": "session_ended", "session_id": session_id}
        
        for user_id in session.participants:
            if user_id in self._user_connections:
                for ws in self._user_connections[user_id]:
                    try:
                        await ws.send_json(message)
                    except:
                        pass
        
        # Clean up
        if session.project_id in self._project_sessions:
            del self._project_sessions[session.project_id]
        
        logger.info(f"Ended collaboration session {session_id}")
        return True
    
    def get_operation_history(
        self,
        session_id: str,
        since_version: int = 0
    ) -> List[Dict[str, Any]]:
        """Get operation history for replay/sync."""
        if session_id not in self._sessions:
            return []
        
        session = self._sessions[session_id]
        
        return [
            {
                "operation_id": op.operation_id,
                "user_id": op.user_id,
                "operation_type": op.operation_type.value,
                "data": op.data,
                "timestamp": op.timestamp,
                "version": op.version
            }
            for op in session.operations
            if op.version > since_version
        ]


# Global instance
_collab_service: Optional[RealtimeCollaborationService] = None


def get_collaboration_service() -> RealtimeCollaborationService:
    """Get global collaboration service."""
    global _collab_service
    if _collab_service is None:
        _collab_service = RealtimeCollaborationService()
    return _collab_service


# Convenience functions
async def create_collaboration_session(project_id: str, user_id: str, username: str) -> str:
    """Create a new collaboration session."""
    service = get_collaboration_service()
    session = await service.create_session(project_id, user_id, username)
    return session.session_id


async def broadcast_edit(session_id: str, user_id: str, operation_type: str, data: Dict[str, Any]) -> None:
    """Broadcast an edit operation to session."""
    service = get_collaboration_service()
    op_type = EditOperationType(operation_type) if operation_type in [t.value for t in EditOperationType] else EditOperationType.CLIP_UPDATE
    await service.handle_operation(session_id, user_id, op_type, data)
