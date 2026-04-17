"""
Productivity Integrations API — ViraClip

Connect Slack, Notion, Trello, Asana and create automation rules
that fire on clip events (created, published, etc.).
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.productivity_integrations import (
    get_productivity_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/productivity", tags=["productivity"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class ConnectToolRequest(BaseModel):
    user_id: str
    tool_type: str          # ToolType value
    access_token: str
    workspace_id: Optional[str] = None


class CreateRuleRequest(BaseModel):
    user_id: str
    tool_type: str
    event_type: str             # EventType value
    target_location: str        # Channel ID, Database ID, Board ID, etc.
    message_template: str
    action: str = "post_message"


class HandleEventRequest(BaseModel):
    user_id: str
    event_type: str
    event_data: Dict[str, Any]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_tool_type(value: str):
    from ...services.productivity_integrations import ToolType
    try:
        return ToolType(value.lower())
    except ValueError:
        from ...services.productivity_integrations import ToolType
        raise HTTPException(
            status_code=400,
            detail=f"Unknown tool_type '{value}'. Valid: {[t.value for t in ToolType]}",
        )


def _parse_event_type(value: str):
    from ...services.productivity_integrations import EventType
    try:
        return EventType(value.lower())
    except ValueError:
        from ...services.productivity_integrations import EventType
        raise HTTPException(
            status_code=400,
            detail=f"Unknown event_type '{value}'. Valid: {[e.value for e in EventType]}",
        )


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/tools/connect")
async def connect_tool(body: ConnectToolRequest):
    """
    Connect a productivity tool for a user.

    `tool_type`: `slack` | `notion` | `trello` | `asana`
    Returns the new `ToolConnection` record.
    """
    tool_type = _parse_tool_type(body.tool_type)
    svc = get_productivity_service()
    try:
        connection = await svc.connect_tool(
            body.user_id, tool_type, body.access_token, body.workspace_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "connected",
        "connection": {
            "connection_id": connection.connection_id,
            "user_id": connection.user_id,
            "tool_type": connection.tool_type.value,
            "workspace_name": connection.workspace_name,
            "is_active": connection.is_active,
        },
    }


@router.get("/tools/{user_id}")
def list_connections(user_id: str):
    """List all active tool connections for a user."""
    svc = get_productivity_service()
    connections = svc.get_user_connections(user_id)
    return {"count": len(connections), "connections": connections}


@router.delete("/tools/{connection_id}")
async def disconnect_tool(connection_id: str):
    """Disconnect a productivity tool."""
    svc = get_productivity_service()
    success = await svc.disconnect_tool(connection_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Connection '{connection_id}' not found")
    return {"status": "disconnected", "connection_id": connection_id}


@router.post("/rules")
async def create_automation_rule(body: CreateRuleRequest):
    """
    Create an automation rule that fires on a clip event.

    `event_type`: `clip_created` | `clip_published` | `clip_viral` | `task_completed`
    `action_config` keys depend on the tool (e.g. `channel_id` for Slack).
    """
    tool_type = _parse_tool_type(body.tool_type)
    event_type = _parse_event_type(body.event_type)
    svc = get_productivity_service()
    try:
        rule = await svc.create_automation_rule(
            body.user_id, tool_type, event_type,
            body.target_location, body.message_template, body.action
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "created",
        "rule": {
            "rule_id": rule.rule_id,
            "user_id": rule.user_id,
            "tool_type": rule.tool_type.value,
            "event_type": rule.event_type.value,
            "action": rule.action,
            "is_active": rule.is_active,
        },
    }


@router.get("/rules/{user_id}")
def list_rules(user_id: str):
    """List all automation rules for a user."""
    svc = get_productivity_service()
    rules = svc.get_user_automations(user_id)
    return {"count": len(rules), "rules": rules}


@router.post("/events/handle")
async def handle_event(body: HandleEventRequest):
    """
    Trigger automation rules for a clip event.

    Fires all matching active rules for the user and event type.
    Returns per-rule action results.
    """
    event_type = _parse_event_type(body.event_type)
    svc = get_productivity_service()
    try:
        results = await svc.handle_event(body.user_id, event_type, body.event_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "handled", "results": results}


@router.get("/stats")
def activity_stats():
    """Get productivity automation activity statistics."""
    svc = get_productivity_service()
    return {"status": "success", "stats": svc.get_activity_stats()}


@router.get("/tool-types")
def list_tool_types():
    """List supported productivity tool types and event types."""
    from ...services.productivity_integrations import ToolType, EventType
    return {
        "tool_types": [t.value for t in ToolType],
        "event_types": [e.value for e in EventType],
    }
