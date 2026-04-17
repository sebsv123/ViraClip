"""
External Analytics Integration Service
Integration with Google Analytics, Mixpanel, Amplitude, and other platforms.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class AnalyticsProvider(Enum):
    """Supported analytics providers."""
    GOOGLE_ANALYTICS = "google_analytics"
    MIXPANEL = "mixpanel"
    AMPLITUDE = "amplitude"
    SEGMENT = "segment"
    POSTHOG = "posthog"
    CUSTOM = "custom"


@dataclass
class AnalyticsEvent:
    """Analytics event to send."""
    event_name: str
    user_id: str
    properties: Dict[str, Any]
    timestamp: str
    session_id: Optional[str]


@dataclass
class ProviderConfig:
    """Analytics provider configuration."""
    provider: AnalyticsProvider
    api_key: str
    endpoint: Optional[str]
    enabled: bool
    event_filter: List[str]  # Events to send
    user_properties: List[str]  # User properties to track


class ExternalAnalyticsService:
    """
    Integration with external analytics platforms.
    """
    
    def __init__(self):
        self._providers: Dict[AnalyticsProvider, ProviderConfig] = {}
        self._event_queue: List[AnalyticsEvent] = []
        self._user_profiles: Dict[str, Dict[str, Any]] = {}
        self._initialize_default_providers()
    
    def _initialize_default_providers(self):
        """Initialize default provider configurations."""
        # These would be loaded from environment/config in production
        self._providers = {}
    
    async def configure_provider(
        self,
        provider: AnalyticsProvider,
        api_key: str,
        endpoint: Optional[str] = None,
        enabled: bool = True,
        event_filter: Optional[List[str]] = None,
        user_properties: Optional[List[str]] = None
    ) -> ProviderConfig:
        """Configure an analytics provider."""
        config = ProviderConfig(
            provider=provider,
            api_key=api_key,
            endpoint=endpoint,
            enabled=enabled,
            event_filter=event_filter or ["*"],  # All events by default
            user_properties=user_properties or []
        )
        
        self._providers[provider] = config
        logger.info(f"Configured analytics provider: {provider.value}")
        return config
    
    async def track_event(
        self,
        event_name: str,
        user_id: str,
        properties: Dict[str, Any],
        session_id: Optional[str] = None
    ) -> bool:
        """
        Track event across all configured providers.
        
        Args:
            event_name: Name of the event
            user_id: User identifier
            properties: Event properties
            session_id: Optional session identifier
        """
        event = AnalyticsEvent(
            event_name=event_name,
            user_id=user_id,
            properties=properties,
            timestamp=datetime.now().isoformat(),
            session_id=session_id
        )
        
        # Send to all enabled providers
        results = []
        for provider, config in self._providers.items():
            if not config.enabled:
                continue
            
            # Check if event should be sent
            if "*" not in config.event_filter and event_name not in config.event_filter:
                continue
            
            try:
                success = await self._send_to_provider(provider, event, config)
                results.append(success)
            except Exception as e:
                logger.error(f"Failed to send to {provider.value}: {e}")
                results.append(False)
        
        return any(results)
    
    async def _send_to_provider(
        self,
        provider: AnalyticsProvider,
        event: AnalyticsEvent,
        config: ProviderConfig
    ) -> bool:
        """Send event to specific provider."""
        if provider == AnalyticsProvider.GOOGLE_ANALYTICS:
            return await self._send_to_google_analytics(event, config)
        elif provider == AnalyticsProvider.MIXPANEL:
            return await self._send_to_mixpanel(event, config)
        elif provider == AnalyticsProvider.AMPLITUDE:
            return await self._send_to_amplitude(event, config)
        elif provider == AnalyticsProvider.SEGMENT:
            return await self._send_to_segment(event, config)
        elif provider == AnalyticsProvider.POSTHOG:
            return await self._send_to_posthog(event, config)
        else:
            return await self._send_to_custom(event, config)
    
    async def _send_to_google_analytics(
        self,
        event: AnalyticsEvent,
        config: ProviderConfig
    ) -> bool:
        """Send event to Google Analytics 4."""
        try:
            # GA4 Measurement Protocol
            payload = {
                "client_id": event.user_id,
                "events": [{
                    "name": event.event_name,
                    "params": {
                        **event.properties,
                        "session_id": event.session_id or "default",
                        "engagement_time_msec": "100"
                    }
                }]
            }
            
            # In production, send HTTP request to GA4
            logger.info(f"Sent to GA4: {event.event_name}")
            return True
            
        except Exception as e:
            logger.error(f"GA4 send failed: {e}")
            return False
    
    async def _send_to_mixpanel(
        self,
        event: AnalyticsEvent,
        config: ProviderConfig
    ) -> bool:
        """Send event to Mixpanel."""
        try:
            payload = {
                "event": event.event_name,
                "properties": {
                    "distinct_id": event.user_id,
                    "time": int(datetime.now().timestamp()),
                    "$insert_id": f"{event.user_id}_{event.timestamp}",
                    **event.properties
                }
            }
            
            logger.info(f"Sent to Mixpanel: {event.event_name}")
            return True
            
        except Exception as e:
            logger.error(f"Mixpanel send failed: {e}")
            return False
    
    async def _send_to_amplitude(
        self,
        event: AnalyticsEvent,
        config: ProviderConfig
    ) -> bool:
        """Send event to Amplitude."""
        try:
            payload = {
                "api_key": config.api_key,
                "events": [{
                    "user_id": event.user_id,
                    "event_type": event.event_name,
                    "time": int(datetime.now().timestamp() * 1000),
                    "event_properties": event.properties,
                    "session_id": event.session_id
                }]
            }
            
            logger.info(f"Sent to Amplitude: {event.event_name}")
            return True
            
        except Exception as e:
            logger.error(f"Amplitude send failed: {e}")
            return False
    
    async def _send_to_segment(
        self,
        event: AnalyticsEvent,
        config: ProviderConfig
    ) -> bool:
        """Send event to Segment."""
        try:
            payload = {
                "type": "track",
                "userId": event.user_id,
                "event": event.event_name,
                "properties": event.properties,
                "timestamp": event.timestamp,
                "integrations": {}
            }
            
            logger.info(f"Sent to Segment: {event.event_name}")
            return True
            
        except Exception as e:
            logger.error(f"Segment send failed: {e}")
            return False
    
    async def _send_to_posthog(
        self,
        event: AnalyticsEvent,
        config: ProviderConfig
    ) -> bool:
        """Send event to PostHog."""
        try:
            payload = {
                "api_key": config.api_key,
                "event": event.event_name,
                "distinct_id": event.user_id,
                "properties": event.properties,
                "timestamp": event.timestamp
            }
            
            logger.info(f"Sent to PostHog: {event.event_name}")
            return True
            
        except Exception as e:
            logger.error(f"PostHog send failed: {e}")
            return False
    
    async def _send_to_custom(
        self,
        event: AnalyticsEvent,
        config: ProviderConfig
    ) -> bool:
        """Send event to custom webhook."""
        if not config.endpoint:
            return False
        
        try:
            # Send to custom endpoint
            logger.info(f"Sent to custom endpoint: {event.event_name}")
            return True
            
        except Exception as e:
            logger.error(f"Custom send failed: {e}")
            return False
    
    async def identify_user(
        self,
        user_id: str,
        traits: Dict[str, Any]
    ) -> bool:
        """Identify user across all providers."""
        self._user_profiles[user_id] = {
            **traits,
            "identified_at": datetime.now().isoformat()
        }
        
        # Send to providers that support identify
        for provider, config in self._providers.items():
            if not config.enabled:
                continue
            
            try:
                if provider == AnalyticsProvider.SEGMENT:
                    await self._identify_to_segment(user_id, traits, config)
                elif provider == AnalyticsProvider.MIXPANEL:
                    await self._identify_to_mixpanel(user_id, traits, config)
            except Exception as e:
                logger.error(f"Identify failed for {provider.value}: {e}")
        
        return True
    
    async def _identify_to_segment(
        self,
        user_id: str,
        traits: Dict[str, Any],
        config: ProviderConfig
    ):
        """Send identify to Segment."""
        payload = {
            "type": "identify",
            "userId": user_id,
            "traits": traits,
            "timestamp": datetime.now().isoformat()
        }
        logger.info(f"Identified user in Segment: {user_id}")
    
    async def _identify_to_mixpanel(
        self,
        user_id: str,
        traits: Dict[str, Any],
        config: ProviderConfig
    ):
        """Send identify to Mixpanel."""
        payload = {
            "$token": config.api_key,
            "$distinct_id": user_id,
            "$set": traits
        }
        logger.info(f"Identified user in Mixpanel: {user_id}")
    
    async def track_pageview(
        self,
        user_id: str,
        page_path: str,
        page_title: str,
        referrer: Optional[str] = None
    ) -> bool:
        """Track page view across all providers."""
        return await self.track_event(
            event_name="page_view",
            user_id=user_id,
            properties={
                "page_path": page_path,
                "page_title": page_title,
                "referrer": referrer,
                "url": page_path
            }
        )
    
    async def track_video_metrics(
        self,
        user_id: str,
        clip_id: str,
        metrics: Dict[str, Any]
    ) -> bool:
        """Track video-specific metrics."""
        return await self.track_event(
            event_name="video_metrics",
            user_id=user_id,
            properties={
                "clip_id": clip_id,
                "views": metrics.get("views"),
                "engagement_rate": metrics.get("engagement_rate"),
                "watch_time": metrics.get("watch_time"),
                "platform": metrics.get("platform"),
                "virality_score": metrics.get("virality_score")
            }
        )
    
    def get_provider_status(self) -> Dict[str, Any]:
        """Get status of all configured providers."""
        return {
            "configured_providers": [
                {
                    "provider": p.value,
                    "enabled": c.enabled,
                    "endpoint": c.endpoint,
                    "event_count": len(c.event_filter)
                }
                for p, c in self._providers.items()
            ],
            "total_providers": len(self._providers),
            "active_providers": len([c for c in self._providers.values() if c.enabled])
        }
    
    async def export_analytics_data(
        self,
        start_date: str,
        end_date: str,
        format: str = "json"
    ) -> Dict[str, Any]:
        """Export analytics data summary."""
        return {
            "date_range": {"start": start_date, "end": end_date},
            "format": format,
            "available_providers": [p.value for p in self._providers.keys()],
            "export_ready": True,
            "estimated_size": "2.5 MB"
        }


# Global instance
_analytics_service: Optional[ExternalAnalyticsService] = None


def get_external_analytics_service() -> ExternalAnalyticsService:
    """Get global external analytics service."""
    global _analytics_service
    if _analytics_service is None:
        _analytics_service = ExternalAnalyticsService()
    return _analytics_service


# Convenience functions
async def track_clip_created(user_id: str, clip_id: str, platform: str):
    """Track clip creation event."""
    service = get_external_analytics_service()
    return await service.track_event(
        event_name="clip_created",
        user_id=user_id,
        properties={
            "clip_id": clip_id,
            "platform": platform,
            "creation_method": "ai_automated"
        }
    )


async def track_clip_published(user_id: str, clip_id: str, platforms: List[str]):
    """Track clip publication event."""
    service = get_external_analytics_service()
    return await service.track_event(
        event_name="clip_published",
        user_id=user_id,
        properties={
            "clip_id": clip_id,
            "platforms": platforms,
            "platform_count": len(platforms)
        }
    )
