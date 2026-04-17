"""
Trending Topics API — ViraClip

Endpoints for discovering trending topics, getting personalized content
recommendations, and analyzing how well existing content aligns with trends.
"""

import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ...services.trending_topics import (
    TrendCategory,
    TrendStatus,
    get_trending_topics_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/trending", tags=["trending"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class ContentAnalysisRequest(BaseModel):
    transcript: str = ""
    title: str = ""
    hashtags: List[str] = []


class RecommendationRequest(BaseModel):
    user_id: str = "anonymous"
    niche: str = "entertainment"
    limit: int = 5


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.get("")
async def get_trending_topics(
    category: Optional[str] = Query(None, description="Filter by category"),
    status: Optional[str] = Query(None, description="Filter by lifecycle status"),
    min_score: float = Query(0.0, ge=0, le=100),
    limit: int = Query(20, ge=1, le=100),
):
    """
    Get current trending topics, optionally filtered by category and lifecycle status.

    **Categories**: entertainment, education, technology, lifestyle, news, sports, gaming, music
    **Status**: emerging, rising, peak, declining
    """
    svc = get_trending_topics_service()

    cat = None
    if category:
        try:
            cat = TrendCategory(category)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid category '{category}'. Choose: {[c.value for c in TrendCategory]}",
            )

    stat = None
    if status:
        try:
            stat = TrendStatus(status)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status '{status}'. Choose: {[s.value for s in TrendStatus]}",
            )

    topics = await svc.get_trending_topics(
        category=cat, status=stat, min_score=min_score, limit=limit
    )

    return {
        "status": "success",
        "count": len(topics),
        "topics": [
            {
                "topic_id": t.topic_id,
                "keyword": t.keyword,
                "category": t.category.value,
                "status": t.status.value,
                "score": round(t.score, 1),
                "velocity": t.velocity,
                "volume": t.volume,
                "sentiment_score": t.sentiment_score,
                "related_hashtags": t.related_hashtags,
                "estimated_duration_hours": t.estimated_duration_hours,
            }
            for t in topics
        ],
    }


@router.get("/analytics")
def get_trend_analytics():
    """Get aggregate trend analytics: by-category breakdown, status distribution, top-10."""
    svc = get_trending_topics_service()
    analytics = svc.get_trend_analytics()
    return {"status": "success", **analytics}


@router.get("/categories")
def list_categories():
    """List all available trend categories and lifecycle statuses."""
    return {
        "categories": [c.value for c in TrendCategory],
        "statuses": [s.value for s in TrendStatus],
    }


@router.get("/{topic_id}/lifecycle")
async def predict_trend_lifecycle(topic_id: str):
    """
    Predict the lifecycle of a specific trend: time to peak, recommended posting window,
    and estimated duration remaining.
    """
    svc = get_trending_topics_service()
    result = await svc.predict_trend_lifecycle(topic_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return {"status": "success", **result}


@router.post("/analyze")
async def analyze_content_for_trends(body: ContentAnalysisRequest):
    """
    Analyze a piece of content (transcript + title + hashtags) against current trends.
    Returns alignment score, matching trends, trending potential, and improvement suggestions.
    """
    svc = get_trending_topics_service()
    try:
        result = await svc.analyze_content_for_trends(
            transcript=body.transcript,
            title=body.title,
            hashtags=body.hashtags,
        )
        return {"status": "success", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/recommendations")
async def get_personalized_recommendations(body: RecommendationRequest):
    """
    Get AI-generated content recommendations tailored to the user's niche and
    aligned with currently trending topics.
    Returns suggested hooks, optimal duration, and relevant hashtags per recommendation.
    """
    svc = get_trending_topics_service()
    try:
        recs = await svc.get_personalized_recommendations(
            user_id=body.user_id,
            user_niche=body.niche,
            limit=body.limit,
        )
        return {
            "status": "success",
            "count": len(recs),
            "recommendations": [
                {
                    "recommendation_id": r.recommendation_id,
                    "keyword": r.topic.keyword,
                    "category": r.topic.category.value,
                    "trend_score": round(r.topic.score, 1),
                    "trend_status": r.topic.status.value,
                    "content_type": r.content_type,
                    "suggested_hook": r.suggested_hook,
                    "suggested_duration_seconds": r.suggested_duration,
                    "suggested_hashtags": r.suggested_hashtags,
                    "confidence": round(r.confidence, 2),
                    "created_at": r.created_at,
                }
                for r in recs
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
