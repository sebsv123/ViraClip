"""
Multi-User Collaboration System
Supports team collaboration on video projects with roles and permissions.
"""

import logging
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass
from enum import Enum
from datetime import datetime
from uuid import uuid4

logger = logging.getLogger(__name__)


class UserRole(Enum):
    """User roles in collaboration."""
    OWNER = "owner"           # Full control
    ADMIN = "admin"           # Can manage members
    EDITOR = "editor"         # Can edit and comment
    VIEWER = "viewer"         # Read-only with comments
    REVIEWER = "reviewer"     # Can only comment/approve


class Permission(Enum):
    """Specific permissions."""
    VIEW = "view"
    EDIT = "edit"
    DELETE = "delete"
    COMMENT = "comment"
    SHARE = "share"
    EXPORT = "export"
    MANAGE_MEMBERS = "manage_members"
    APPROVE = "approve"


@dataclass
class Collaborator:
    """A project collaborator."""
    user_id: str
    role: UserRole
    joined_at: str
    added_by: str
    permissions: Set[Permission]
    last_active: Optional[str] = None


@dataclass
class CollaborationProject:
    """A collaborative project."""
    project_id: str
    name: str
    owner_id: str
    created_at: str
    collaborators: Dict[str, Collaborator]
    task_ids: List[str]
    settings: Dict[str, Any]


@dataclass
class Comment:
    """A comment on a clip or project."""
    comment_id: str
    project_id: str
    task_id: Optional[str]
    clip_id: Optional[str]
    user_id: str
    content: str
    timestamp: str
    resolved: bool
    replies: List[Dict[str, Any]]
    position: Optional[Dict[str, float]] = None  # For video annotations


class CollaborationService:
    """
    Service for managing multi-user collaboration.
    """
    
    # Role to permissions mapping
    ROLE_PERMISSIONS = {
        UserRole.OWNER: {
            Permission.VIEW, Permission.EDIT, Permission.DELETE,
            Permission.COMMENT, Permission.SHARE, Permission.EXPORT,
            Permission.MANAGE_MEMBERS, Permission.APPROVE
        },
        UserRole.ADMIN: {
            Permission.VIEW, Permission.EDIT, Permission.COMMENT,
            Permission.SHARE, Permission.EXPORT, Permission.MANAGE_MEMBERS,
            Permission.APPROVE
        },
        UserRole.EDITOR: {
            Permission.VIEW, Permission.EDIT, Permission.COMMENT,
            Permission.EXPORT, Permission.APPROVE
        },
        UserRole.REVIEWER: {
            Permission.VIEW, Permission.COMMENT, Permission.APPROVE
        },
        UserRole.VIEWER: {
            Permission.VIEW, Permission.COMMENT
        }
    }
    
    def __init__(self):
        self._projects: Dict[str, CollaborationProject] = {}
        self._comments: Dict[str, List[Comment]] = {}  # project_id -> comments
        self._user_projects: Dict[str, Set[str]] = {}  # user_id -> project_ids
    
    def create_project(
        self,
        name: str,
        owner_id: str,
        settings: Optional[Dict[str, Any]] = None
    ) -> CollaborationProject:
        """Create a new collaboration project."""
        project_id = str(uuid4())
        
        project = CollaborationProject(
            project_id=project_id,
            name=name,
            owner_id=owner_id,
            created_at=datetime.now().isoformat(),
            collaborators={
                owner_id: Collaborator(
                    user_id=owner_id,
                    role=UserRole.OWNER,
                    joined_at=datetime.now().isoformat(),
                    added_by=owner_id,
                    permissions=self.ROLE_PERMISSIONS[UserRole.OWNER]
                )
            },
            task_ids=[],
            settings=settings or {}
        )
        
        self._projects[project_id] = project
        
        # Update user's project list
        if owner_id not in self._user_projects:
            self._user_projects[owner_id] = set()
        self._user_projects[owner_id].add(project_id)
        
        logger.info(f"Created collaboration project: {project_id} by {owner_id}")
        return project
    
    def add_collaborator(
        self,
        project_id: str,
        user_id: str,
        role: UserRole,
        added_by: str
    ) -> bool:
        """Add a collaborator to a project."""
        project = self._projects.get(project_id)
        if not project:
            return False
        
        # Check if adder has permission
        if not self.has_permission(project_id, added_by, Permission.MANAGE_MEMBERS):
            logger.warning(f"User {added_by} cannot add members to {project_id}")
            return False
        
        # Cannot add if already a member
        if user_id in project.collaborators:
            return False
        
        collaborator = Collaborator(
            user_id=user_id,
            role=role,
            joined_at=datetime.now().isoformat(),
            added_by=added_by,
            permissions=self.ROLE_PERMISSIONS[role]
        )
        
        project.collaborators[user_id] = collaborator
        
        # Update user's project list
        if user_id not in self._user_projects:
            self._user_projects[user_id] = set()
        self._user_projects[user_id].add(project_id)
        
        logger.info(f"Added {user_id} as {role.value} to project {project_id}")
        return True
    
    def remove_collaborator(
        self,
        project_id: str,
        user_id: str,
        removed_by: str
    ) -> bool:
        """Remove a collaborator from a project."""
        project = self._projects.get(project_id)
        if not project:
            return False
        
        # Check permissions
        if not self.has_permission(project_id, removed_by, Permission.MANAGE_MEMBERS):
            return False
        
        # Cannot remove owner
        if project.collaborators.get(user_id, {}).role == UserRole.OWNER:
            return False
        
        if user_id in project.collaborators:
            del project.collaborators[user_id]
            
            # Update user's project list
            if user_id in self._user_projects:
                self._user_projects[user_id].discard(project_id)
            
            logger.info(f"Removed {user_id} from project {project_id}")
            return True
        
        return False
    
    def has_permission(
        self,
        project_id: str,
        user_id: str,
        permission: Permission
    ) -> bool:
        """Check if a user has a specific permission."""
        project = self._projects.get(project_id)
        if not project:
            return False
        
        collaborator = project.collaborators.get(user_id)
        if not collaborator:
            return False
        
        return permission in collaborator.permissions
    
    def can_edit(self, project_id: str, user_id: str) -> bool:
        """Check if user can edit the project."""
        return self.has_permission(project_id, user_id, Permission.EDIT)
    
    def can_view(self, project_id: str, user_id: str) -> bool:
        """Check if user can view the project."""
        return self.has_permission(project_id, user_id, Permission.VIEW)
    
    def can_export(self, project_id: str, user_id: str) -> bool:
        """Check if user can export from the project."""
        return self.has_permission(project_id, user_id, Permission.EXPORT)
    
    def add_task_to_project(
        self,
        project_id: str,
        task_id: str,
        user_id: str
    ) -> bool:
        """Add a task to a project."""
        if not self.can_edit(project_id, user_id):
            return False
        
        project = self._projects.get(project_id)
        if not project:
            return False
        
        if task_id not in project.task_ids:
            project.task_ids.append(task_id)
        
        return True
    
    def add_comment(
        self,
        project_id: str,
        user_id: str,
        content: str,
        task_id: Optional[str] = None,
        clip_id: Optional[str] = None,
        position: Optional[Dict[str, float]] = None
    ) -> Optional[Comment]:
        """Add a comment to a project, task, or clip."""
        if not self.has_permission(project_id, user_id, Permission.COMMENT):
            return None
        
        comment = Comment(
            comment_id=str(uuid4()),
            project_id=project_id,
            task_id=task_id,
            clip_id=clip_id,
            user_id=user_id,
            content=content,
            timestamp=datetime.now().isoformat(),
            resolved=False,
            replies=[],
            position=position
        )
        
        if project_id not in self._comments:
            self._comments[project_id] = []
        
        self._comments[project_id].append(comment)
        
        logger.info(f"Comment added by {user_id} to {project_id}")
        return comment
    
    def resolve_comment(
        self,
        project_id: str,
        comment_id: str,
        user_id: str
    ) -> bool:
        """Mark a comment as resolved."""
        if project_id not in self._comments:
            return False
        
        for comment in self._comments[project_id]:
            if comment.comment_id == comment_id:
                # Can resolve if commenter or editor
                if comment.user_id == user_id or self.can_edit(project_id, user_id):
                    comment.resolved = True
                    return True
        
        return False
    
    def get_comments(
        self,
        project_id: str,
        task_id: Optional[str] = None,
        clip_id: Optional[str] = None,
        include_resolved: bool = False
    ) -> List[Comment]:
        """Get comments for a project, optionally filtered."""
        if project_id not in self._comments:
            return []
        
        comments = self._comments[project_id]
        
        # Filter by task/clip if specified
        if task_id:
            comments = [c for c in comments if c.task_id == task_id]
        if clip_id:
            comments = [c for c in comments if c.clip_id == clip_id]
        
        # Filter out resolved unless requested
        if not include_resolved:
            comments = [c for c in comments if not c.resolved]
        
        return sorted(comments, key=lambda x: x.timestamp)
    
    def get_project_collaborators(
        self,
        project_id: str,
        user_id: str
    ) -> Optional[List[Dict[str, Any]]]:
        """Get list of collaborators if user has access."""
        if not self.can_view(project_id, user_id):
            return None
        
        project = self._projects.get(project_id)
        if not project:
            return None
        
        return [
            {
                "user_id": c.user_id,
                "role": c.role.value,
                "joined_at": c.joined_at,
                "permissions": [p.value for p in c.permissions]
            }
            for c in project.collaborators.values()
        ]
    
    def get_user_projects(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all projects a user is part of."""
        project_ids = self._user_projects.get(user_id, set())
        
        projects = []
        for pid in project_ids:
            project = self._projects.get(pid)
            if project:
                user_role = project.collaborators.get(user_id, {}).role.value
                projects.append({
                    "project_id": project.project_id,
                    "name": project.name,
                    "role": user_role,
                    "created_at": project.created_at,
                    "collaborator_count": len(project.collaborators),
                    "task_count": len(project.task_ids)
                })
        
        return sorted(projects, key=lambda x: x["created_at"], reverse=True)
    
    def update_project_settings(
        self,
        project_id: str,
        user_id: str,
        settings: Dict[str, Any]
    ) -> bool:
        """Update project settings."""
        if not self.can_edit(project_id, user_id):
            return False
        
        project = self._projects.get(project_id)
        if not project:
            return False
        
        project.settings.update(settings)
        return True
    
    def get_project_activity(
        self,
        project_id: str,
        user_id: str,
        limit: int = 50
    ) -> Optional[List[Dict[str, Any]]]:
        """Get recent activity for a project."""
        if not self.can_view(project_id, user_id):
            return None
        
        project = self._projects.get(project_id)
        if not project:
            return None
        
        # Build activity feed from comments and collaborator joins
        activities = []
        
        # Add comment activities
        for comment in self._comments.get(project_id, []):
            activities.append({
                "type": "comment",
                "user_id": comment.user_id,
                "timestamp": comment.timestamp,
                "content": comment.content[:100] + "..." if len(comment.content) > 100 else comment.content,
                "task_id": comment.task_id,
                "clip_id": comment.clip_id
            })
        
        # Add collaborator activities
        for collab in project.collaborators.values():
            activities.append({
                "type": "joined",
                "user_id": collab.user_id,
                "timestamp": collab.joined_at,
                "role": collab.role.value
            })
        
        # Sort by timestamp and limit
        activities.sort(key=lambda x: x["timestamp"], reverse=True)
        return activities[:limit]


# Global instance
_collaboration_service: Optional[CollaborationService] = None


def get_collaboration_service() -> CollaborationService:
    """Get global collaboration service instance."""
    global _collaboration_service
    if _collaboration_service is None:
        _collaboration_service = CollaborationService()
    return _collaboration_service


# Convenience functions
def create_collaboration_project(
    name: str,
    owner_id: str
) -> CollaborationProject:
    """Create a new collaboration project."""
    return get_collaboration_service().create_project(name, owner_id)


def add_project_collaborator(
    project_id: str,
    user_id: str,
    role: UserRole,
    added_by: str
) -> bool:
    """Add a collaborator to a project."""
    return get_collaboration_service().add_collaborator(
        project_id, user_id, role, added_by
    )


def check_project_permission(
    project_id: str,
    user_id: str,
    permission: Permission
) -> bool:
    """Check if a user has a permission on a project."""
    return get_collaboration_service().has_permission(project_id, user_id, permission)
