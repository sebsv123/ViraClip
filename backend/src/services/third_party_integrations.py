"""
Third-Party Integrations Service
Connects with Zapier, Make, and other automation platforms.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class IntegrationType(Enum):
    """Supported integration platforms."""
    ZAPIER = "zapier"
    MAKE = "make"
    SLACK = "slack"
    DISCORD = "discord"
    NOTION = "notion"
    TRELLO = "trello"
    ASANA = "asana"
    GOOGLE_SHEETS = "google_sheets"


class TriggerEvent(Enum):
    """Events that can trigger integrations."""
    CLIP_CREATED = "clip_created"
    CLIP_READY = "clip_ready"
    CLIP_PUBLISHED = "clip_published"
    TASK_COMPLETED = "task_completed"
    VIRAL_MILESTONE = "viral_milestone"
    EXPORT_COMPLETE = "export_complete"


@dataclass
class IntegrationWebhook:
    """Webhook configuration for integration."""
    webhook_id: str
    user_id: str
    integration_type: IntegrationType
    trigger_event: TriggerEvent
    webhook_url: str
    is_active: bool
    headers: Dict[str, str]
    created_at: str
    last_triggered: Optional[str]
    trigger_count: int


class ThirdPartyIntegrationService:
    """
    Manages third-party integrations and webhooks.
    """
    
    def __init__(self):
        self._webhooks: Dict[str, IntegrationWebhook] = {}
        self._integration_history: List[Dict[str, Any]] = []
    
    async def register_webhook(
        self,
        user_id: str,
        integration_type: IntegrationType,
        trigger_event: TriggerEvent,
        webhook_url: str,
        headers: Optional[Dict[str, str]] = None
    ) -> IntegrationWebhook:
        """Register a new integration webhook."""
        import uuid
        
        webhook = IntegrationWebhook(
            webhook_id=str(uuid.uuid4()),
            user_id=user_id,
            integration_type=integration_type,
            trigger_event=trigger_event,
            webhook_url=webhook_url,
            is_active=True,
            headers=headers or {},
            created_at=datetime.now().isoformat(),
            last_triggered=None,
            trigger_count=0
        )
        
        self._webhooks[webhook.webhook_id] = webhook
        
        logger.info(
            f"Registered {integration_type.value} webhook for {trigger_event.value}"
        )
        return webhook
    
    async def trigger_integration(
        self,
        user_id: str,
        event: TriggerEvent,
        payload: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Trigger all integrations for an event."""
        results = []
        
        # Find matching webhooks
        matching = [
            w for w in self._webhooks.values()
            if w.user_id == user_id
            and w.trigger_event == event
            and w.is_active
        ]
        
        for webhook in matching:
            try:
                result = await self._send_webhook(webhook, payload)
                results.append(result)
                
                # Update webhook stats
                webhook.last_triggered = datetime.now().isoformat()
                webhook.trigger_count += 1
                
                # Log integration
                self._integration_history.append({
                    "timestamp": datetime.now().isoformat(),
                    "webhook_id": webhook.webhook_id,
                    "event": event.value,
                    "success": result["success"],
                    "response_code": result.get("status_code")
                })
                
            except Exception as e:
                logger.error(f"Integration trigger failed: {e}")
                results.append({
                    "webhook_id": webhook.webhook_id,
                    "success": False,
                    "error": str(e)
                })
        
        return results
    
    async def _send_webhook(
        self,
        webhook: IntegrationWebhook,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Send webhook to third-party service."""
        import aiohttp
        
        # Format payload for specific integration
        formatted_payload = self._format_payload(
            webhook.integration_type,
            webhook.trigger_event,
            payload
        )
        
        headers = {
            "Content-Type": "application/json",
            **webhook.headers
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    webhook.webhook_url,
                    json=formatted_payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    return {
                        "webhook_id": webhook.webhook_id,
                        "success": response.status in [200, 201, 202, 204],
                        "status_code": response.status,
                        "integration": webhook.integration_type.value
                    }
        
        except Exception as e:
            return {
                "webhook_id": webhook.webhook_id,
                "success": False,
                "error": str(e)
            }
    
    def _format_payload(
        self,
        integration_type: IntegrationType,
        event: TriggerEvent,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Format payload for specific integration."""
        base_payload = {
            "event": event.value,
            "timestamp": datetime.now().isoformat(),
            "data": payload
        }
        
        # Integration-specific formatting
        if integration_type == IntegrationType.ZAPIER:
            # Zapier expects specific format
            return {
                "event": event.value,
                "payload": payload,
                "source": "viraclip"
            }
        
        elif integration_type == IntegrationType.SLACK:
            # Slack message format
            return {
                "text": f"🎬 *ViraClip Update*: {event.value}",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Event:* {event.value}\n*Details:* {payload.get('message', 'Update available')}"
                        }
                    }
                ]
            }
        
        elif integration_type == IntegrationType.DISCORD:
            # Discord webhook format
            return {
                "content": f"ViraClip: {event.value}",
                "embeds": [
                    {
                        "title": event.value.replace("_", " ").title(),
                        "description": payload.get("message", ""),
                        "timestamp": datetime.now().isoformat(),
                        "color": 0x6C5CE7
                    }
                ]
            }
        
        return base_payload
    
    def get_user_integrations(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all integrations for a user."""
        user_webhooks = [
            w for w in self._webhooks.values()
            if w.user_id == user_id
        ]
        
        return [
            {
                "webhook_id": w.webhook_id,
                "integration": w.integration_type.value,
                "trigger": w.trigger_event.value,
                "is_active": w.is_active,
                "trigger_count": w.trigger_count,
                "last_triggered": w.last_triggered,
                "created_at": w.created_at
            }
            for w in sorted(user_webhooks, key=lambda x: x.created_at, reverse=True)
        ]
    
    async def toggle_integration(
        self,
        webhook_id: str,
        active: bool
    ) -> bool:
        """Enable or disable an integration."""
        if webhook_id not in self._webhooks:
            return False
        
        self._webhooks[webhook_id].is_active = active
        return True
    
    async def delete_integration(self, webhook_id: str) -> bool:
        """Delete an integration."""
        if webhook_id not in self._webhooks:
            return False
        
        del self._webhooks[webhook_id]
        return True
    
    def get_integration_stats(self) -> Dict[str, Any]:
        """Get integration usage statistics."""
        total = len(self._webhooks)
        active = sum(1 for w in self._webhooks.values() if w.is_active)
        
        # Count by type
        by_type = {}
        for w in self._webhooks.values():
            itype = w.integration_type.value
            by_type[itype] = by_type.get(itype, 0) + 1
        
        # Recent triggers
        recent = [
            h for h in self._integration_history
            if datetime.fromisoformat(h["timestamp"]) > datetime.now() - timedelta(hours=24)
        ]
        
        success_rate = (
            sum(1 for r in recent if r["success"]) / len(recent) * 100
            if recent else 0
        )
        
        return {
            "total_integrations": total,
            "active_integrations": active,
            "by_type": by_type,
            "triggers_24h": len(recent),
            "success_rate_24h": round(success_rate, 1)
        }


# Global instance
_integration_service: Optional[ThirdPartyIntegrationService] = None


def get_integration_service() -> ThirdPartyIntegrationService:
    """Get global integration service."""
    global _integration_service
    if _integration_service is None:
        _integration_service = ThirdPartyIntegrationService()
    return _integration_service


# Convenience functions
async def send_to_slack(user_id: str, message: str, clip_data: Dict[str, Any]) -> bool:
    """Send clip notification to Slack."""
    service = get_integration_service()
    
    # Find or create Slack webhook
    webhooks = service.get_user_integrations(user_id)
    slack_hooks = [w for w in webhooks if w["integration"] == "slack"]
    
    if slack_hooks:
        results = await service.trigger_integration(
            user_id,
            TriggerEvent.CLIP_READY,
            {"message": message, **clip_data}
        )
        return any(r["success"] for r in results)
    
    return False


async def notify_zapier(user_id: str, event: str, data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Send event to Zapier."""
    service = get_integration_service()
    trigger = TriggerEvent(event) if event in [t.value for t in TriggerEvent] else TriggerEvent.CLIP_CREATED
    return await service.trigger_integration(user_id, trigger, data)
