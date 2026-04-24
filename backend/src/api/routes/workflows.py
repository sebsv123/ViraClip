"""
Workflow Automation API — ViraClip

Endpoints for creating, managing, and executing visual automation
workflows that chain video-processing steps together.
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...domains.autopilot.workflow_automation import (
    WorkflowNodeType,
    get_workflow_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workflows", tags=["workflows"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class CreateWorkflowRequest(BaseModel):
    user_id: str
    name: str
    description: str
    template_id: Optional[str] = None   # e.g. "viral_shorts" | "tutorial"


class AddNodeRequest(BaseModel):
    node_type: str          # WorkflowNodeType value
    name: str
    config: Dict[str, Any]
    position: Dict[str, float]          # {"x": 100, "y": 200}
    connect_to: Optional[List[str]] = None


class ExecuteRequest(BaseModel):
    input_data: Dict[str, Any]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_node_type(value: str) -> WorkflowNodeType:
    try:
        return WorkflowNodeType(value.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown node_type '{value}'. Valid: {[n.value for n in WorkflowNodeType]}",
        )


def _fmt_workflow(w) -> Dict[str, Any]:
    return {
        "workflow_id": w.workflow_id,
        "user_id": w.user_id,
        "name": w.name,
        "description": w.description,
        "status": w.status.value,
        "nodes": [
            {
                "node_id": n.node_id,
                "type": n.type.value,
                "name": n.name,
                "config": n.config,
                "position": n.position,
                "inputs": n.inputs,
                "outputs": n.outputs,
            }
            for n in w.nodes
        ],
        "connections": w.connections,
        "run_count": w.run_count,
        "last_run": w.last_run,
        "created_at": w.created_at,
        "updated_at": w.updated_at,
    }


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.get("/templates")
def list_templates():
    """List all built-in workflow templates (e.g. viral_shorts, tutorial)."""
    svc = get_workflow_service()
    return {"count": len(svc.get_templates()), "templates": svc.get_templates()}


@router.post("")
async def create_workflow(body: CreateWorkflowRequest):
    """
    Create a new workflow.

    Pass `template_id` to clone a built-in template
    (`viral_shorts` or `tutorial`), or leave it empty to start blank.
    """
    svc = get_workflow_service()
    workflow = await svc.create_workflow(
        body.user_id, body.name, body.description, body.template_id
    )
    return {"status": "created", "workflow": _fmt_workflow(workflow)}


@router.get("/user/{user_id}")
def list_user_workflows(user_id: str):
    """List all workflows belonging to a user."""
    svc = get_workflow_service()
    workflows = svc.get_user_workflows(user_id)
    return {"count": len(workflows), "workflows": workflows}


@router.get("/{workflow_id}")
def get_workflow(workflow_id: str):
    """Get full workflow definition including nodes and connections."""
    svc = get_workflow_service()
    workflow = svc.get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found")
    return {"status": "success", "workflow": _fmt_workflow(workflow)}


@router.post("/{workflow_id}/nodes")
async def add_node(workflow_id: str, body: AddNodeRequest):
    """
    Add a processing node to a workflow.

    `node_type` must be one of the supported types:
    trigger, extract_video, ai_analyze, generate_clips, apply_effects,
    add_music, export, publish, condition, delay, webhook, notification.
    """
    node_type = _parse_node_type(body.node_type)
    svc = get_workflow_service()
    try:
        node = await svc.add_node(
            workflow_id, node_type, body.name, body.config,
            body.position, body.connect_to,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {
        "status": "added",
        "node": {
            "node_id": node.node_id,
            "type": node.type.value,
            "name": node.name,
            "config": node.config,
            "position": node.position,
        },
    }


@router.post("/{workflow_id}/activate")
async def activate_workflow(workflow_id: str):
    """Activate a workflow so it responds to trigger events."""
    svc = get_workflow_service()
    success = await svc.activate_workflow(workflow_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not found")
    return {"status": "activated", "workflow_id": workflow_id}


@router.post("/{workflow_id}/execute")
async def execute_workflow(workflow_id: str, body: ExecuteRequest):
    """
    Manually execute a workflow with the provided input data.

    Returns a `WorkflowRun` with node results and execution logs.
    """
    svc = get_workflow_service()
    try:
        run = await svc.execute_workflow(workflow_id, body.input_data)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "executed", "run": svc.get_run_status(run.run_id)}


@router.get("/runs/{run_id}")
def get_run_status(run_id: str):
    """Get the status and results of a specific workflow run."""
    svc = get_workflow_service()
    run = svc.get_run_status(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return {"status": "success", "run": run}


@router.get("/node-types/list")
def list_node_types():
    """List all supported workflow node types."""
    return {"node_types": [n.value for n in WorkflowNodeType]}
