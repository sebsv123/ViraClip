"""
Webhook System for Third-Party Integrations
Manages webhook delivery, retries, and endpoint management.
"""

import json
import hmac
import hashlib
import logging
import asyncio
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class WebhookEventType(Enum):
    """Types of webhook events."""
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    CLIP_READY = "clip.ready"
    EXPORT_COMPLETE = "export.complete"
    CLIP_PUBLISHED = "clip.published"
    ANALYTICS_READY = "analytics.ready"


@dataclass
class WebhookEndpoint:
    """A webhook endpoint configuration."""
    endpoint_id: str
    url: str
    secret: str
    events: List[WebhookEventType]
    is_active: bool
    created_at: str
    retry_count: int = 3
    timeout_seconds: int = 30
    headers: Optional[Dict[str, str]] = None


@dataclass
class WebhookDelivery:
    """Record of a webhook delivery attempt."""
    delivery_id: str
    endpoint_id: str
    event_type: WebhookEventType
    payload: Dict[str, Any]
    status: str  # pending, delivered, failed
    attempts: int
    created_at: str
    delivered_at: Optional[str] = None
    error_message: Optional[str] = None
    http_status: Optional[int] = None


class WebhookManager:
    """
    Manages webhook endpoints and delivery.
    """
    
    def __init__(self):
        self._endpoints: Dict[str, WebhookEndpoint] = {}
        self._deliveries: Dict[str, List[WebhookDelivery]] = {}
        self._http_client = None
    
    def register_endpoint(
        self,
        user_id: str,
        url: str,
        secret: str,
        events: List[WebhookEventType],
        headers: Optional[Dict[str, str]] = None
    ) -> WebhookEndpoint:
        """Register a new webhook endpoint."""
        import uuid
        
        endpoint_id = str(uuid.uuid4())
        
        endpoint = WebhookEndpoint(
            endpoint_id=endpoint_id,
            url=url,
            secret=secret,
            events=events,
            is_active=True,
            created_at=datetime.now().isoformat(),
            headers=headers or {}
        )
        
        # Store under user_id namespace
        if user_id not in self._endpoints:
            self._endpoints[user_id] = {}
        
        self._endpoints[user_id][endpoint_id] = endpoint
        
        logger.info(f"Registered webhook endpoint {endpoint_id} for user {user_id}")
        return endpoint
    
    def delete_endpoint(self, user_id: str, endpoint_id: str) -> bool:
        """Delete a webhook endpoint."""
        if user_id in self._endpoints and endpoint_id in self._endpoints[user_id]:
            del self._endpoints[user_id][endpoint_id]
            return True
        return False
    
    def get_user_endpoints(self, user_id: str) -> List[WebhookEndpoint]:
        """Get all endpoints for a user."""
        return list(self._endpoints.get(user_id, {}).values())
    
    async def trigger_event(
        self,
        user_id: str,
        event_type: WebhookEventType,
        payload: Dict[str, Any]
    ) -> List[WebhookDelivery]:
        """Trigger webhook event for all matching endpoints."""
        endpoints = self.get_user_endpoints(user_id)
        deliveries = []
        
        for endpoint in endpoints:
            if not endpoint.is_active:
                continue
            
            if event_type not in endpoint.events:
                continue
            
            delivery = await self._send_webhook(endpoint, event_type, payload)
            deliveries.append(delivery)
        
        return deliveries
    
    async def _send_webhook(
        self,
        endpoint: WebhookEndpoint,
        event_type: WebhookEventType,
        payload: Dict[str, Any]
    ) -> WebhookDelivery:
        """Send webhook to endpoint with retries."""
        import uuid
        import aiohttp
        
        delivery_id = str(uuid.uuid4())
        
        delivery = WebhookDelivery(
            delivery_id=delivery_id,
            endpoint_id=endpoint.endpoint_id,
            event_type=event_type,
            payload=payload,
            status="pending",
            attempts=0,
            created_at=datetime.now().isoformat()
        )
        
        # Build payload
        webhook_payload = {
            "event_id": delivery_id,
            "event_type": event_type.value,
            "timestamp": datetime.now().isoformat(),
            "data": payload
        }
        
        # Generate signature
        signature = self._generate_signature(endpoint.secret, webhook_payload)
        
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": signature,
            "X-Webhook-Event": event_type.value,
            "X-Webhook-ID": delivery_id,
            "User-Agent": "ViraClip-Webhook/1.0"
        }
        
        # Add custom headers
        if endpoint.headers:
            headers.update(endpoint.headers)
        
        # Attempt delivery with retries
        for attempt in range(endpoint.retry_count):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        endpoint.url,
                        json=webhook_payload,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=endpoint.timeout_seconds)
                    ) as response:
                        delivery.http_status = response.status
                        delivery.attempts = attempt + 1
                        
                        if response.status in [200, 201, 202, 204]:
                            delivery.status = "delivered"
                            delivery.delivered_at = datetime.now().isoformat()
                            logger.info(f"Webhook delivered: {delivery_id} -> {endpoint.url}")
                            break
                        else:
                            delivery.error_message = f"HTTP {response.status}"
                            if attempt < endpoint.retry_count - 1:
                                await asyncio.sleep(2 ** attempt)  # Exponential backoff
                
            except asyncio.TimeoutError:
                delivery.error_message = "Timeout"
                delivery.attempts = attempt + 1
                if attempt < endpoint.retry_count - 1:
                    await asyncio.sleep(2 ** attempt)
            
            except Exception as e:
                delivery.error_message = str(e)
                delivery.attempts = attempt + 1
                if attempt < endpoint.retry_count - 1:
                    await asyncio.sleep(2 ** attempt)
        
        if delivery.status != "delivered":
            delivery.status = "failed"
            logger.warning(
                f"Webhook delivery failed: {delivery_id} after {delivery.attempts} attempts"
            )
        
        # Store delivery record
        if endpoint.endpoint_id not in self._deliveries:
            self._deliveries[endpoint.endpoint_id] = []
        self._deliveries[endpoint.endpoint_id].append(delivery)
        
        return delivery
    
    def _generate_signature(self, secret: str, payload: Dict[str, Any]) -> str:
        """Generate HMAC signature for webhook payload."""
        payload_json = json.dumps(payload, separators=(',', ':'))
        signature = hmac.new(
            secret.encode('utf-8'),
            payload_json.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return f"sha256={signature}"
    
    def verify_signature(
        self,
        secret: str,
        payload: bytes,
        signature: str
    ) -> bool:
        """Verify webhook signature."""
        expected = self._generate_signature(secret, json.loads(payload))
        return hmac.compare_digest(signature, expected)
    
    def get_delivery_history(
        self,
        endpoint_id: str,
        limit: int = 100
    ) -> List[WebhookDelivery]:
        """Get delivery history for an endpoint."""
        deliveries = self._deliveries.get(endpoint_id, [])
        return sorted(
            deliveries,
            key=lambda x: x.created_at,
            reverse=True
        )[:limit]
    
    async def retry_failed_deliveries(self, endpoint_id: str) -> int:
        """Retry failed webhook deliveries."""
        deliveries = self._deliveries.get(endpoint_id, [])
        failed = [d for d in deliveries if d.status == "failed"]
        
        retried = 0
        for delivery in failed:
            # Find endpoint
            endpoint = None
            for user_endpoints in self._endpoints.values():
                if endpoint_id in user_endpoints:
                    endpoint = user_endpoints[endpoint_id]
                    break
            
            if endpoint:
                await self._send_webhook(endpoint, delivery.event_type, delivery.payload)
                retried += 1
        
        return retried


class WebhookEventBuilder:
    """Helper class to build webhook event payloads."""
    
    @staticmethod
    def task_started(task_id: str, video_url: str, user_id: str) -> Dict[str, Any]:
        """Build task.started event payload."""
        return {
            "task_id": task_id,
            "video_url": video_url,
            "user_id": user_id,
            "status": "processing",
            "started_at": datetime.now().isoformat()
        }
    
    @staticmethod
    def task_completed(
        task_id: str,
        clip_count: int,
        clips: List[Dict[str, Any]],
        processing_time_seconds: float
    ) -> Dict[str, Any]:
        """Build task.completed event payload."""
        return {
            "task_id": task_id,
            "status": "completed",
            "clip_count": clip_count,
            "clips": clips,
            "processing_time_seconds": processing_time_seconds,
            "completed_at": datetime.now().isoformat()
        }
    
    @staticmethod
    def task_failed(task_id: str, error: str, stage: str) -> Dict[str, Any]:
        """Build task.failed event payload."""
        return {
            "task_id": task_id,
            "status": "failed",
            "error": error,
            "failed_stage": stage,
            "failed_at": datetime.now().isoformat()
        }
    
    @staticmethod
    def clip_ready(
        clip_id: str,
        task_id: str,
        virality_score: float,
        download_url: str,
        platform_optimized_urls: Dict[str, str]
    ) -> Dict[str, Any]:
        """Build clip.ready event payload."""
        return {
            "clip_id": clip_id,
            "task_id": task_id,
            "virality_score": virality_score,
            "download_url": download_url,
            "platform_urls": platform_optimized_urls,
            "ready_at": datetime.now().isoformat()
        }
    
    @staticmethod
    def export_complete(
        export_id: str,
        clip_id: str,
        platform: str,
        format_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build export.complete event payload."""
        return {
            "export_id": export_id,
            "clip_id": clip_id,
            "platform": platform,
            "format": format_info,
            "exported_at": datetime.now().isoformat()
        }


# Global instance
_webhook_manager: Optional[WebhookManager] = None


def get_webhook_manager() -> WebhookManager:
    """Get global webhook manager instance."""
    global _webhook_manager
    if _webhook_manager is None:
        _webhook_manager = WebhookManager()
    return _webhook_manager


def get_event_builder() -> WebhookEventBuilder:
    """Get webhook event builder."""
    return WebhookEventBuilder()


# Convenience functions
async def notify_task_started(user_id: str, task_id: str, video_url: str) -> None:
    """Send task.started webhook."""
    manager = get_webhook_manager()
    payload = get_event_builder().task_started(task_id, video_url, user_id)
    await manager.trigger_event(user_id, WebhookEventType.TASK_STARTED, payload)


async def notify_task_completed(
    user_id: str,
    task_id: str,
    clip_count: int,
    clips: List[Dict[str, Any]],
    processing_time: float
) -> None:
    """Send task.completed webhook."""
    manager = get_webhook_manager()
    payload = get_event_builder().task_completed(task_id, clip_count, clips, processing_time)
    await manager.trigger_event(user_id, WebhookEventType.TASK_COMPLETED, payload)


async def notify_task_failed(user_id: str, task_id: str, error: str, stage: str) -> None:
    """Send task.failed webhook."""
    manager = get_webhook_manager()
    payload = get_event_builder().task_failed(task_id, error, stage)
    await manager.trigger_event(user_id, WebhookEventType.TASK_FAILED, payload)
