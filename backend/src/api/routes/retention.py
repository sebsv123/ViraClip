"""
Data Retention API — ViraClip

Endpoints for managing data lifecycle policies: creating, listing,
updating, and applying retention policies; storage summaries and cleanup history.
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.data_retention import (
    DataType,
    RetentionAction,
    get_retention_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/retention", tags=["retention"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class CreatePolicyRequest(BaseModel):
    data_type: str          # DataType value
    retention_days: int
    action: str             # RetentionAction value
    exempt_user_ids: Optional[List[str]] = None
    min_size_mb: Optional[float] = None


class UpdatePolicyRequest(BaseModel):
    retention_days: Optional[int] = None
    action: Optional[str] = None
    enabled: Optional[bool] = None
    exempt_user_ids: Optional[List[str]] = None


class ApplyPolicyRequest(BaseModel):
    dry_run: bool = False


class RunAllRequest(BaseModel):
    dry_run: bool = False


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_data_type(value: str) -> DataType:
    try:
        return DataType(value.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown data_type '{value}'. Valid: {[d.value for d in DataType]}",
        )


def _parse_action(value: str) -> RetentionAction:
    try:
        return RetentionAction(value.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action '{value}'. Valid: {[a.value for a in RetentionAction]}",
        )


def _fmt_result(r) -> Dict[str, Any]:
    return {
        "data_type": r.data_type.value,
        "items_scanned": r.items_scanned,
        "items_deleted": r.items_deleted,
        "items_archived": r.items_archived,
        "space_freed_mb": r.space_freed_mb,
        "errors": r.errors,
    }


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.get("/policies")
def list_policies():
    """List all configured data retention policies."""
    svc = get_retention_service()
    policies = svc.list_policies()
    return {"count": len(policies), "policies": policies}


@router.get("/policies/{policy_id}")
def get_policy(policy_id: str):
    """Get a single retention policy by ID."""
    svc = get_retention_service()
    policy = svc.get_policy(policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail=f"Policy '{policy_id}' not found")
    return {
        "policy_id": policy.policy_id,
        "data_type": policy.data_type.value,
        "retention_days": policy.retention_days,
        "action": policy.action.value,
        "enabled": policy.enabled,
        "created_at": policy.created_at,
        "exempt_user_ids": policy.exempt_user_ids,
        "min_size_threshold_mb": policy.min_size_threshold_mb,
    }


@router.post("/policies")
def create_policy(body: CreatePolicyRequest):
    """
    Create a new data retention policy.

    `data_type`: `source_videos` | `clips` | `thumbnails` | `temp_files`
                 | `analytics` | `audit_logs` | `user_data` | `backups`
    `action`: `delete` | `archive` | `anonymize` | `compress`
    """
    if body.retention_days < 1:
        raise HTTPException(status_code=400, detail="retention_days must be >= 1")
    data_type = _parse_data_type(body.data_type)
    action = _parse_action(body.action)
    svc = get_retention_service()
    policy = svc.create_policy(
        data_type, body.retention_days, action,
        body.exempt_user_ids, body.min_size_mb,
    )
    return {
        "status": "created",
        "policy": {
            "policy_id": policy.policy_id,
            "data_type": policy.data_type.value,
            "retention_days": policy.retention_days,
            "action": policy.action.value,
            "enabled": policy.enabled,
        },
    }


@router.patch("/policies/{policy_id}")
def update_policy(policy_id: str, body: UpdatePolicyRequest):
    """Update fields of an existing retention policy."""
    updates: Dict[str, Any] = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No update fields provided")
    svc = get_retention_service()
    success = svc.update_policy(policy_id, updates)
    if not success:
        raise HTTPException(status_code=404, detail=f"Policy '{policy_id}' not found")
    return {"status": "updated", "policy_id": policy_id}


@router.delete("/policies/{policy_id}")
def delete_policy(policy_id: str):
    """Delete a retention policy."""
    svc = get_retention_service()
    success = svc.delete_policy(policy_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Policy '{policy_id}' not found")
    return {"status": "deleted", "policy_id": policy_id}


@router.post("/policies/{policy_id}/apply")
async def apply_policy(policy_id: str, body: ApplyPolicyRequest):
    """
    Apply a single retention policy.

    Pass `dry_run=true` to simulate the cleanup without deleting anything.
    Returns items_scanned, items_deleted, items_archived, and space_freed_mb.
    """
    svc = get_retention_service()
    try:
        result = await svc.apply_policy(policy_id, body.dry_run)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "dry_run" if body.dry_run else "applied",
        "result": _fmt_result(result),
    }


@router.post("/run-all")
async def run_all_policies(body: RunAllRequest):
    """
    Run all enabled retention policies.

    Pass `dry_run=true` to simulate without making changes.
    Returns per-policy results plus totals.
    """
    svc = get_retention_service()
    try:
        results = await svc.run_all_policies(body.dry_run)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    total_deleted = sum(r.items_deleted for r in results.values())
    total_freed = sum(r.space_freed_mb for r in results.values())

    return {
        "status": "dry_run" if body.dry_run else "completed",
        "policies_applied": len(results),
        "total_items_deleted": total_deleted,
        "total_space_freed_mb": round(total_freed, 2),
        "details": {pid: _fmt_result(r) for pid, r in results.items()},
    }


@router.get("/storage")
def storage_summary():
    """Get current storage usage summary broken down by data type."""
    svc = get_retention_service()
    return {"status": "success", "storage": svc.get_storage_summary()}


@router.get("/history")
def cleanup_history(days: int = 30):
    """Get cleanup operation history for the past `days` days."""
    if days < 1:
        raise HTTPException(status_code=400, detail="days must be >= 1")
    svc = get_retention_service()
    history = svc.get_cleanup_history(days)
    return {"count": len(history), "history": history}


@router.get("/data-types")
def list_data_types():
    """List all supported data types and retention actions."""
    return {
        "data_types": [d.value for d in DataType],
        "retention_actions": [a.value for a in RetentionAction],
    }
