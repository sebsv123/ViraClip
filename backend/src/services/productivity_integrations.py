"""
Productivity Tools Integration Service
Connects with Notion, Slack, Trello, Asana, and other productivity tools.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class ToolType(Enum):
    """Supported productivity tools."""
    NOTION = "notion"
    SLACK = "slack"
    TRELLO = "trello"
    ASANA = "asana"
    MONDAY = "monday"
    CLICKUP = "clickup"
    LINEAR = "linear"


class EventType(Enum):
    """Events that can trigger productivity tool actions."""
    CLIP_CREATED = "clip_created"
    CLIP_READY = "clip_ready"
    CLIP_PUBLISHED = "clip_published"
    TASK_COMPLETED = "task_completed"
    VIRAL_MILESTONE = "viral_milestone"
    PROJECT_CREATED = "project_created"


@dataclass
class ToolConnection:
    """Connection to a productivity tool."""
    connection_id: str
    user_id: str
    tool_type: ToolType
    access_token: str
    workspace_id: Optional[str]
    workspace_name: str
    is_active: bool
    created_at: str
    last_used: Optional[str]


@dataclass
class AutomationRule:
    """Automation rule for tool integration."""
    rule_id: str
    user_id: str
    tool_type: ToolType
    connection_id: str
    event_type: EventType
    action: str
    target_location: str  # Channel ID, Database ID, Board ID, etc.
    message_template: str
    is_active: bool


class ProductivityIntegrationService:
    """
    Integrates with productivity tools for workflow automation.
    """
    
    def __init__(self):
        self._connections: Dict[str, ToolConnection] = {}
        self._automation_rules: Dict[str, AutomationRule] = {}
        self._action_history: List[Dict[str, Any]] = []
    
    async def connect_tool(
        self,
        user_id: str,
        tool_type: ToolType,
        access_token: str,
        workspace_id: Optional[str] = None
    ) -> ToolConnection:
        """Connect a productivity tool."""
        import uuid
        
        # Validate token by fetching workspace info
        workspace_name = await self._validate_and_get_workspace(tool_type, access_token, workspace_id)
        
        connection = ToolConnection(
            connection_id=str(uuid.uuid4()),
            user_id=user_id,
            tool_type=tool_type,
            access_token=access_token,
            workspace_id=workspace_id,
            workspace_name=workspace_name,
            is_active=True,
            created_at=datetime.now().isoformat(),
            last_used=None
        )
        
        self._connections[connection.connection_id] = connection
        
        logger.info(f"Connected {tool_type.value} for user {user_id}")
        return connection
    
    async def _validate_and_get_workspace(
        self,
        tool_type: ToolType,
        access_token: str,
        workspace_id: Optional[str]
    ) -> str:
        """Validate token and get workspace name."""
        # In production, this would make API calls to validate
        tool_names = {
            ToolType.NOTION: "Notion Workspace",
            ToolType.SLACK: "Slack Workspace",
            ToolType.TRELLO: "Trello Board",
            ToolType.ASANA: "Asana Project",
            ToolType.MONDAY: "Monday.com",
            ToolType.CLICKUP: "ClickUp Space",
            ToolType.LINEAR: "Linear Team"
        }
        return tool_names.get(tool_type, "Unknown Workspace")
    
    async def create_automation_rule(
        self,
        user_id: str,
        tool_type: ToolType,
        event_type: EventType,
        target_location: str,
        message_template: str,
        action: str = "post_message"
    ) -> AutomationRule:
        """Create an automation rule."""
        import uuid
        
        # Find connection
        connection = self._find_connection(user_id, tool_type)
        if not connection:
            raise ValueError(f"No {tool_type.value} connection found for user")
        
        rule = AutomationRule(
            rule_id=str(uuid.uuid4()),
            user_id=user_id,
            tool_type=tool_type,
            connection_id=connection.connection_id,
            event_type=event_type,
            action=action,
            target_location=target_location,
            message_template=message_template,
            is_active=True
        )
        
        self._automation_rules[rule.rule_id] = rule
        
        logger.info(f"Created automation rule {rule.rule_id} for {tool_type.value}")
        return rule
    
    def _find_connection(
        self,
        user_id: str,
        tool_type: ToolType
    ) -> Optional[ToolConnection]:
        """Find active connection for user and tool."""
        for conn in self._connections.values():
            if conn.user_id == user_id and conn.tool_type == tool_type and conn.is_active:
                return conn
        return None
    
    async def handle_event(
        self,
        user_id: str,
        event_type: EventType,
        event_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Handle an event and trigger automations."""
        results = []
        
        # Find matching rules
        matching_rules = [
            rule for rule in self._automation_rules.values()
            if rule.user_id == user_id
            and rule.event_type == event_type
            and rule.is_active
        ]
        
        for rule in matching_rules:
            try:
                result = await self._execute_automation(rule, event_data)
                results.append(result)
                
                # Log action
                self._action_history.append({
                    "timestamp": datetime.now().isoformat(),
                    "rule_id": rule.rule_id,
                    "event_type": event_type.value,
                    "tool": rule.tool_type.value,
                    "success": result.get("success", False)
                })
                
            except Exception as e:
                logger.error(f"Automation failed for rule {rule.rule_id}: {e}")
                results.append({
                    "rule_id": rule.rule_id,
                    "success": False,
                    "error": str(e)
                })
        
        return results
    
    async def _execute_automation(
        self,
        rule: AutomationRule,
        event_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute an automation rule."""
        connection = self._connections.get(rule.connection_id)
        if not connection:
            return {"success": False, "error": "Connection not found"}
        
        # Format message
        message = self._format_message(rule.message_template, event_data)
        
        # Execute based on tool type
        if rule.tool_type == ToolType.SLACK:
            return await self._send_to_slack(connection, rule.target_location, message, event_data)
        elif rule.tool_type == ToolType.NOTION:
            return await self._send_to_notion(connection, rule.target_location, message, event_data)
        elif rule.tool_type == ToolType.TRELLO:
            return await self._send_to_trello(connection, rule.target_location, message, event_data)
        elif rule.tool_type == ToolType.ASANA:
            return await self._send_to_asana(connection, rule.target_location, message, event_data)
        else:
            return {"success": False, "error": "Tool not implemented"}
    
    def _format_message(self, template: str, data: Dict[str, Any]) -> str:
        """Format message template with event data."""
        message = template
        for key, value in data.items():
            placeholder = f"{{{key}}}"
            if placeholder in message:
                message = message.replace(placeholder, str(value))
        return message
    
    async def _send_to_slack(
        self,
        connection: ToolConnection,
        channel_id: str,
        message: str,
        event_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Send message to Slack."""
        import aiohttp
        
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "channel": channel_id,
                    "text": message,
                    "blocks": [
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": message
                            }
                        }
                    ]
                }
                
                # Add clip thumbnail if available
                if event_data.get("thumbnail_url"):
                    payload["blocks"].append({
                        "type": "image",
                        "image_url": event_data["thumbnail_url"],
                        "alt_text": "Clip thumbnail"
                    })
                
                async with session.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={"Authorization": f"Bearer {connection.access_token}"},
                    json=payload
                ) as response:
                    result = await response.json()
                    
                    if result.get("ok"):
                        return {"success": True, "message_ts": result.get("ts")}
                    else:
                        return {"success": False, "error": result.get("error")}
                        
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _send_to_notion(
        self,
        connection: ToolConnection,
        database_id: str,
        message: str,
        event_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create entry in Notion database."""
        import aiohttp
        
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "parent": {"database_id": database_id},
                    "properties": {
                        "Name": {
                            "title": [{"text": {"content": event_data.get("clip_title", "New Clip")}}]
                        },
                        "Status": {
                            "select": {"name": event_data.get("status", "Draft")}
                        },
                        "Platform": {
                            "select": {"name": event_data.get("platform", "YouTube")}
                        },
                        "Virality Score": {
                            "number": event_data.get("virality_score", 0)
                        },
                        "Created": {
                            "date": {"start": datetime.now().isoformat()}
                        }
                    }
                }
                
                async with session.post(
                    "https://api.notion.com/v1/pages",
                    headers={
                        "Authorization": f"Bearer {connection.access_token}",
                        "Notion-Version": "2022-06-28",
                        "Content-Type": "application/json"
                    },
                    json=payload
                ) as response:
                    result = await response.json()
                    
                    if response.status == 200:
                        return {"success": True, "page_id": result.get("id")}
                    else:
                        return {"success": False, "error": result.get("message")}
                        
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _send_to_trello(
        self,
        connection: ToolConnection,
        list_id: str,
        message: str,
        event_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create Trello card."""
        import aiohttp
        
        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    "key": connection.access_token,  # In reality, these are separate
                    "token": connection.access_token,
                    "idList": list_id,
                    "name": event_data.get("clip_title", "New Clip"),
                    "desc": message
                }
                
                async with session.post(
                    "https://api.trello.com/1/cards",
                    params=params
                ) as response:
                    result = await response.json()
                    
                    if response.status == 200:
                        return {"success": True, "card_id": result.get("id")}
                    else:
                        return {"success": False, "error": result.get("message")}
                        
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _send_to_asana(
        self,
        connection: ToolConnection,
        project_id: str,
        message: str,
        event_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create Asana task."""
        import aiohttp
        
        try:
            async with aiohttp.ClientSession() as session:
                payload = {
                    "data": {
                        "name": event_data.get("clip_title", "New Clip"),
                        "notes": message,
                        "projects": [project_id]
                    }
                }
                
                async with session.post(
                    "https://app.asana.com/api/1.0/tasks",
                    headers={"Authorization": f"Bearer {connection.access_token}"},
                    json=payload
                ) as response:
                    result = await response.json()
                    
                    if response.status == 201:
                        return {"success": True, "task_id": result.get("data", {}).get("gid")}
                    else:
                        return {"success": False, "error": result.get("errors", [{}])[0].get("message")}
                        
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_user_connections(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all tool connections for a user."""
        return [
            {
                "connection_id": conn.connection_id,
                "tool": conn.tool_type.value,
                "workspace": conn.workspace_name,
                "is_active": conn.is_active,
                "created_at": conn.created_at
            }
            for conn in self._connections.values()
            if conn.user_id == user_id
        ]
    
    def get_user_automations(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all automation rules for a user."""
        return [
            {
                "rule_id": rule.rule_id,
                "tool": rule.tool_type.value,
                "event": rule.event_type.value,
                "action": rule.action,
                "is_active": rule.is_active
            }
            for rule in self._automation_rules.values()
            if rule.user_id == user_id
        ]
    
    async def disconnect_tool(self, connection_id: str) -> bool:
        """Disconnect a tool."""
        if connection_id not in self._connections:
            return False
        
        self._connections[connection_id].is_active = False
        
        # Disable related automations
        for rule in self._automation_rules.values():
            if rule.connection_id == connection_id:
                rule.is_active = False
        
        return True
    
    def get_activity_stats(self) -> Dict[str, Any]:
        """Get automation activity statistics."""
        total = len(self._action_history)
        successful = sum(1 for a in self._action_history if a["success"])
        
        # By tool
        by_tool = {}
        for action in self._action_history:
            tool = action["tool"]
            by_tool[tool] = by_tool.get(tool, 0) + 1
        
        return {
            "total_actions": total,
            "successful": successful,
            "failed": total - successful,
            "by_tool": by_tool,
            "active_connections": sum(1 for c in self._connections.values() if c.is_active),
            "active_automations": sum(1 for r in self._automation_rules.values() if r.is_active)
        }


# Global instance
_productivity_service: Optional[ProductivityIntegrationService] = None


def get_productivity_service() -> ProductivityIntegrationService:
    """Get global productivity integration service."""
    global _productivity_service
    if _productivity_service is None:
        _productivity_service = ProductivityIntegrationService()
    return _productivity_service


# Convenience functions
async def notify_slack(
    user_id: str,
    channel: str,
    message: str,
    event_data: Dict[str, Any]
) -> bool:
    """Send notification to Slack."""
    service = get_productivity_service()
    
    # Find or use existing connection
    connection = service._find_connection(user_id, ToolType.SLACK)
    
    if not connection:
        return False
    
    result = await service._send_to_slack(connection, channel, message, event_data)
    return result.get("success", False)


async def add_to_notion(
    user_id: str,
    database_id: str,
    clip_data: Dict[str, Any]
) -> bool:
    """Add clip to Notion database."""
    service = get_productivity_service()
    
    connection = service._find_connection(user_id, ToolType.NOTION)
    
    if not connection:
        return False
    
    result = await service._send_to_notion(
        connection,
        database_id,
        f"New clip: {clip_data.get('title', '')}",
        clip_data
    )
    return result.get("success", False)
