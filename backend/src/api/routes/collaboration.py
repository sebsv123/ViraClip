"""
Collaboration API — ViraClip

Endpoints for multi-user projects: creation, member management,
comments/annotations, permission checks, and activity feeds.
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...services.collaboration_service import (
    CollaborationService,
    Permission,
    UserRole,
    get_collaboration_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/collaboration", tags=["collaboration"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class CreateProjectRequest(BaseModel):
    name: str
    settings: Dict[str, Any] = {}


class AddCollaboratorRequest(BaseModel):
    user_id: str
    role: str = "viewer"    # owner | admin | editor | reviewer | viewer


class CommentRequest(BaseModel):
    content: str
    task_id: Optional[str] = None
    clip_id: Optional[str] = None
    position: Optional[Dict[str, float]] = None


class AddTaskRequest(BaseModel):
    task_id: str


class UpdateSettingsRequest(BaseModel):
    settings: Dict[str, Any]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_role(value: str) -> UserRole:
    try:
        return UserRole(value)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid role '{value}'. Choose: {[r.value for r in UserRole]}",
        )


def _fmt_project(p) -> Dict[str, Any]:
    return {
        "project_id": p.project_id,
        "name": p.name,
        "owner_id": p.owner_id,
        "created_at": p.created_at,
        "collaborator_count": len(p.collaborators),
        "task_count": len(p.task_ids),
        "settings": p.settings,
    }


def _fmt_comment(c) -> Dict[str, Any]:
    return {
        "comment_id": c.comment_id,
        "project_id": c.project_id,
        "task_id": c.task_id,
        "clip_id": c.clip_id,
        "user_id": c.user_id,
        "content": c.content,
        "timestamp": c.timestamp,
        "resolved": c.resolved,
        "replies": c.replies,
        "position": c.position,
    }


# ------------------------------------------------------------------
# Projects
# ------------------------------------------------------------------

@router.post("/projects")
def create_project(request: Request, body: CreateProjectRequest):
    """Create a new collaboration project. The caller becomes the owner."""
    user = getattr(request.state, "user", None)
    owner_id = user.id if user else "anonymous"

    svc = get_collaboration_service()
    project = svc.create_project(name=body.name, owner_id=owner_id, settings=body.settings)
    return {"status": "created", "project": _fmt_project(project)}


@router.get("/projects")
def list_projects(request: Request):
    """List all projects the current user is part of."""
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_collaboration_service()
    projects = svc.get_user_projects(user_id)
    return {"status": "success", "count": len(projects), "projects": projects}


@router.get("/projects/{project_id}")
def get_project(project_id: str, request: Request):
    """Get full project details (requires view permission)."""
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_collaboration_service()
    project = svc._projects.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    if not svc.can_view(project_id, user_id):
        raise HTTPException(status_code=403, detail="No view permission on this project")
    return {"status": "success", "project": _fmt_project(project)}


@router.put("/projects/{project_id}/settings")
def update_settings(project_id: str, request: Request, body: UpdateSettingsRequest):
    """Update project settings (requires edit permission)."""
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_collaboration_service()
    success = svc.update_project_settings(project_id, user_id, body.settings)
    if not success:
        raise HTTPException(status_code=403, detail="Permission denied or project not found")
    return {"status": "updated", "project_id": project_id}


# ------------------------------------------------------------------
# Members
# ------------------------------------------------------------------

@router.get("/projects/{project_id}/members")
def list_members(project_id: str, request: Request):
    """List collaborators and their roles/permissions."""
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_collaboration_service()
    members = svc.get_project_collaborators(project_id, user_id)
    if members is None:
        raise HTTPException(status_code=403, detail="Permission denied or project not found")
    return {"status": "success", "count": len(members), "members": members}


@router.post("/projects/{project_id}/members")
def add_member(project_id: str, request: Request, body: AddCollaboratorRequest):
    """Add a new member to the project (requires manage_members permission)."""
    user = getattr(request.state, "user", None)
    added_by = user.id if user else "anonymous"

    svc = get_collaboration_service()
    success = svc.add_collaborator(
        project_id=project_id,
        user_id=body.user_id,
        role=_parse_role(body.role),
        added_by=added_by,
    )
    if not success:
        raise HTTPException(
            status_code=403,
            detail="Cannot add member: permission denied, user already a member, or project not found",
        )
    return {"status": "added", "user_id": body.user_id, "role": body.role}


@router.delete("/projects/{project_id}/members/{user_id}")
def remove_member(project_id: str, user_id: str, request: Request):
    """Remove a member from the project. Cannot remove the owner."""
    acting_user = getattr(request.state, "user", None)
    removed_by = acting_user.id if acting_user else "anonymous"

    svc = get_collaboration_service()
    success = svc.remove_collaborator(project_id, user_id, removed_by)
    if not success:
        raise HTTPException(
            status_code=403,
            detail="Cannot remove member: permission denied, user is owner, or not found",
        )
    return {"status": "removed", "user_id": user_id}


# ------------------------------------------------------------------
# Tasks
# ------------------------------------------------------------------

@router.post("/projects/{project_id}/tasks")
def add_task(project_id: str, request: Request, body: AddTaskRequest):
    """Link an existing processing task to this collaboration project."""
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_collaboration_service()
    success = svc.add_task_to_project(project_id, body.task_id, user_id)
    if not success:
        raise HTTPException(status_code=403, detail="Permission denied or project not found")
    return {"status": "linked", "task_id": body.task_id, "project_id": project_id}


# ------------------------------------------------------------------
# Comments
# ------------------------------------------------------------------

@router.post("/projects/{project_id}/comments")
def add_comment(project_id: str, request: Request, body: CommentRequest):
    """Add a comment or video annotation to a project/task/clip."""
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_collaboration_service()
    comment = svc.add_comment(
        project_id=project_id,
        user_id=user_id,
        content=body.content,
        task_id=body.task_id,
        clip_id=body.clip_id,
        position=body.position,
    )
    if comment is None:
        raise HTTPException(status_code=403, detail="Permission denied on this project")
    return {"status": "created", "comment": _fmt_comment(comment)}


@router.get("/projects/{project_id}/comments")
def get_comments(
    project_id: str,
    task_id: Optional[str] = None,
    clip_id: Optional[str] = None,
    include_resolved: bool = False,
):
    """Get comments for a project, optionally filtered by task or clip."""
    svc = get_collaboration_service()
    comments = svc.get_comments(
        project_id=project_id,
        task_id=task_id,
        clip_id=clip_id,
        include_resolved=include_resolved,
    )
    return {
        "status": "success",
        "count": len(comments),
        "comments": [_fmt_comment(c) for c in comments],
    }


@router.post("/projects/{project_id}/comments/{comment_id}/resolve")
def resolve_comment(project_id: str, comment_id: str, request: Request):
    """Mark a comment as resolved."""
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_collaboration_service()
    success = svc.resolve_comment(project_id, comment_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Comment not found or permission denied")
    return {"status": "resolved", "comment_id": comment_id}


# ------------------------------------------------------------------
# Activity feed
# ------------------------------------------------------------------

@router.get("/projects/{project_id}/activity")
def get_activity(project_id: str, request: Request, limit: int = 50):
    """Recent activity feed: comments, member joins, task links."""
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_collaboration_service()
    activities = svc.get_project_activity(project_id, user_id, limit=limit)
    if activities is None:
        raise HTTPException(status_code=403, detail="Permission denied or project not found")
    return {"status": "success", "count": len(activities), "activities": activities}


# ------------------------------------------------------------------
# Permissions
# ------------------------------------------------------------------

@router.get("/projects/{project_id}/permissions")
def check_permissions(project_id: str, request: Request):
    """Return the current user's effective permissions on a project."""
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_collaboration_service()
    perms = {p.value: svc.has_permission(project_id, user_id, p) for p in Permission}
    return {"status": "success", "user_id": user_id, "project_id": project_id, "permissions": perms}


@router.get("/roles")
def list_roles():
    """List all available roles and their typical permissions."""
    svc = get_collaboration_service()
    return {
        "roles": [r.value for r in UserRole],
        "permissions": [p.value for p in Permission],
        "role_permissions": {
            role.value: [p.value for p in perms]
            for role, perms in svc.ROLE_PERMISSIONS.items()
        },
    }
