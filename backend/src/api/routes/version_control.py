"""
Version Control API — ViraClip

Git-like versioning for clips: create versions, branches, diffs,
reverts, merges and history traversal.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.version_control import (
    ChangeType,
    get_version_control_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/version-control", tags=["version-control"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class CreateVersionRequest(BaseModel):
    clip_id: str
    file_path: str
    parent_version_id: str
    author_id: str
    author_name: str
    change_summary: str
    change_type: str = "modify"
    metadata: Optional[Dict[str, Any]] = None


class CreateBranchRequest(BaseModel):
    clip_id: str
    name: str
    description: str
    head_version_id: str
    created_by: str


class RevertRequest(BaseModel):
    clip_id: str
    version_id: str
    author_id: str
    author_name: str


class MergeRequest(BaseModel):
    source_branch_id: str
    target_branch_id: str
    author_id: str
    author_name: str


class TagRequest(BaseModel):
    version_id: str
    tag: str
    author_id: str


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_change_type(value: str) -> ChangeType:
    try:
        return ChangeType(value.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown change_type '{value}'. Valid: {[c.value for c in ChangeType]}",
        )


def _fmt_version(v) -> Dict[str, Any]:
    return {
        "version_id": v.version_id,
        "clip_id": v.clip_id,
        "version_number": v.version_number,
        "parent_version_id": v.parent_version_id,
        "author_id": v.author_id,
        "author_name": v.author_name,
        "change_type": v.change_type.value,
        "change_summary": v.change_summary,
        "file_hash": v.file_hash,
        "file_size": v.file_size,
        "metadata": v.metadata,
        "created_at": v.created_at,
        "tags": v.tags,
    }


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.get("/clips/{clip_id}/history")
async def get_history(clip_id: str, branch_id: Optional[str] = None):
    """
    Get version history for a clip, newest first.
    Optionally filter to a specific branch with `branch_id`.
    """
    svc = get_version_control_service()
    history = await svc.get_version_history(clip_id, branch_id)
    return {"clip_id": clip_id, "count": len(history), "history": history}


@router.post("/clips/{clip_id}/versions")
async def create_version(clip_id: str, body: CreateVersionRequest):
    """
    Create a new version for a clip.
    `parent_version_id` must reference an existing version.
    """
    change_type = _parse_change_type(body.change_type)
    svc = get_version_control_service()
    try:
        version = await svc.create_version(
            clip_id=clip_id,
            file_path=Path(body.file_path),
            parent_version_id=body.parent_version_id,
            author_id=body.author_id,
            author_name=body.author_name,
            change_summary=body.change_summary,
            change_type=change_type,
            metadata=body.metadata,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "created", "version": _fmt_version(version)}


@router.get("/versions/{version_id}/compare/{other_version_id}")
async def compare_versions(version_id: str, other_version_id: str):
    """
    Compare two versions and return a diff:
    added/removed effects, duration delta, metadata changes, thumbnail change flag.
    """
    svc = get_version_control_service()
    diff = await svc.compare_versions(version_id, other_version_id)
    if diff is None:
        raise HTTPException(status_code=404, detail="One or both versions not found")
    return {
        "status": "success",
        "diff": {
            "from_version_id": diff.from_version_id,
            "to_version_id": diff.to_version_id,
            "added_effects": diff.added_effects,
            "removed_effects": diff.removed_effects,
            "duration_change": diff.duration_change,
            "metadata_changes": diff.metadata_changes,
            "thumbnail_changed": diff.thumbnail_changed,
        },
    }


@router.post("/clips/{clip_id}/revert")
async def revert_to_version(clip_id: str, body: RevertRequest):
    """
    Revert a clip to a previous version by creating a new version
    that mirrors the target version's content.
    """
    svc = get_version_control_service()
    version = await svc.revert_to_version(
        clip_id, body.version_id, body.author_id, body.author_name
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Target version not found for this clip")
    return {"status": "reverted", "new_version": _fmt_version(version)}


@router.post("/versions/{version_id}/tag")
async def tag_version(version_id: str, body: TagRequest):
    """Add a tag label to a specific version."""
    svc = get_version_control_service()
    success = await svc.tag_version(version_id, body.tag, body.author_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Version '{version_id}' not found")
    return {"status": "tagged", "version_id": version_id, "tag": body.tag}


@router.get("/clips/{clip_id}/branches")
def list_branches(clip_id: str):
    """List all active branches for a clip."""
    svc = get_version_control_service()
    branches = svc.get_branches(clip_id)
    return {"clip_id": clip_id, "count": len(branches), "branches": branches}


@router.post("/branches")
async def create_branch(body: CreateBranchRequest):
    """Create a new branch for a clip from a specific version."""
    svc = get_version_control_service()
    try:
        branch = await svc.create_branch(
            clip_id=body.clip_id,
            name=body.name,
            description=body.description,
            head_version_id=body.head_version_id,
            created_by=body.created_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {
        "status": "created",
        "branch": {
            "branch_id": branch.branch_id,
            "clip_id": branch.clip_id,
            "name": branch.name,
            "description": branch.description,
            "head_version_id": branch.head_version_id,
            "created_by": branch.created_by,
            "created_at": branch.created_at,
        },
    }


@router.post("/branches/merge")
async def merge_branches(body: MergeRequest):
    """
    Merge source branch into target branch.
    Both branches must belong to the same clip.
    """
    svc = get_version_control_service()
    try:
        version = await svc.merge_branches(
            body.source_branch_id,
            body.target_branch_id,
            body.author_id,
            body.author_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if version is None:
        raise HTTPException(status_code=404, detail="One or both branches not found")
    return {"status": "merged", "merge_version": _fmt_version(version)}


@router.delete("/branches/{branch_id}")
async def delete_branch(branch_id: str):
    """Soft-delete a branch. The main branch cannot be deleted."""
    svc = get_version_control_service()
    try:
        deleted = await svc.delete_branch(branch_id)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Branch '{branch_id}' not found")
    return {"status": "deleted", "branch_id": branch_id}


@router.get("/stats")
def get_stats():
    """Version control storage statistics."""
    svc = get_version_control_service()
    return {"status": "success", "stats": svc.get_version_stats()}


@router.get("/change-types")
def list_change_types():
    """List all supported change types."""
    return {"change_types": [c.value for c in ChangeType]}
