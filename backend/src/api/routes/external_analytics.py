"""
External Analytics API Routes (GA4, Mixpanel, Amplitude, Segment, PostHog)
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ...services.external_analytics import (
    AnalyticsProvider,
    get_external_analytics_service,
)

router = APIRouter(prefix="/external-analytics", tags=["External Analytics"])


class ConfigureProviderRequest(BaseModel):
    provider: str
    api_key: str
    enabled: bool = True
    custom_endpoint: Optional[str] = None


class TrackEventRequest(BaseModel):
    event_name: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)
    properties: Optional[Dict[str, Any]] = None


class IdentifyUserRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    traits: Dict[str, Any]


class TrackVideoRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    clip_id: str = Field(..., min_length=1)
    metrics: Dict[str, Any]


class ExportRequest(BaseModel):
    start_date: str = Field(..., min_length=8)
    end_date: str = Field(..., min_length=8)
    providers: Optional[list] = None


@router.get("/providers/status")
async def get_provider_status() -> Dict[str, Any]:
    """Get status of all configured external analytics providers."""
    svc = get_external_analytics_service()
    try:
        return svc.get_provider_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/providers/configure")
async def configure_provider(body: ConfigureProviderRequest) -> Dict[str, Any]:
    """Configure an external analytics provider (GA4, Mixpanel, Amplitude, Segment, PostHog)."""
    svc = get_external_analytics_service()
    try:
        provider = AnalyticsProvider(body.provider)
    except ValueError:
        valid = [p.value for p in AnalyticsProvider]
        raise HTTPException(status_code=422, detail=f"provider must be one of {valid}")
    try:
        config = await svc.configure_provider(
            provider=provider,
            api_key=body.api_key,
            enabled=body.enabled,
            custom_endpoint=body.custom_endpoint,
        )
        return {
            "provider": body.provider,
            "enabled": config.enabled,
            "configured": True,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/events/track")
async def track_event(body: TrackEventRequest) -> Dict[str, Any]:
    """Send a custom event to all configured analytics providers."""
    svc = get_external_analytics_service()
    try:
        success = await svc.track_event(
            event_name=body.event_name,
            user_id=body.user_id,
            properties=body.properties or {},
        )
        return {
            "event_name": body.event_name,
            "user_id": body.user_id,
            "sent": success,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/users/identify")
async def identify_user(body: IdentifyUserRequest) -> Dict[str, Any]:
    """Identify a user with traits across all configured analytics providers."""
    svc = get_external_analytics_service()
    try:
        success = await svc.identify_user(user_id=body.user_id, traits=body.traits)
        return {"user_id": body.user_id, "identified": success}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/video/track")
async def track_video_metrics(body: TrackVideoRequest) -> Dict[str, Any]:
    """Track video performance metrics to all configured analytics providers."""
    svc = get_external_analytics_service()
    try:
        await svc.track_video_metrics(
            user_id=body.user_id,
            clip_id=body.clip_id,
            **body.metrics,
        )
        return {"user_id": body.user_id, "clip_id": body.clip_id, "tracked": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/export")
async def export_analytics_data(body: ExportRequest) -> Dict[str, Any]:
    """Export aggregated analytics data for a date range."""
    svc = get_external_analytics_service()
    try:
        result = await svc.export_analytics_data(
            start_date=body.start_date,
            end_date=body.end_date,
            providers=body.providers,
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
