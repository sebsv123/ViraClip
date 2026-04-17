"""
Sentiment Analysis API — ViraClip

Endpoints for analyzing transcript sentiment, emotion detection,
virality correlation, and historical sentiment trends.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.sentiment_analyzer import get_sentiment_analyzer

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sentiment", tags=["sentiment"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    transcript: str
    segments: Optional[List[List[Any]]] = None  # [[start, end, text], ...]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _fmt_result(result) -> Dict[str, Any]:
    return {
        "overall_sentiment": result.overall_sentiment,
        "overall_category": result.overall_category.value,
        "confidence": result.confidence,
        "sentiment_trend": result.sentiment_trend,
        "viral_correlation": result.viral_correlation,
        "dominant_emotions": [
            {"emotion": e.value, "weight": round(w, 3)}
            for e, w in result.dominant_emotions
        ],
        "segments": [
            {
                "start_time": s.start_time,
                "end_time": s.end_time,
                "text": s.text,
                "sentiment_score": round(s.sentiment_score, 3),
                "confidence": round(s.confidence, 3),
                "dominant_emotion": s.dominant_emotion.value,
                "keywords": s.keywords,
            }
            for s in result.segments
        ],
    }


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/analyze")
async def analyze_transcript(body: AnalyzeRequest):
    """
    Analyze sentiment and emotions of a video transcript.

    Optionally pass `segments` as `[[start_sec, end_sec, text], ...]`
    for time-aligned sentiment. Returns `overall_sentiment` (-1 to 1),
    `dominant_emotions`, `sentiment_trend`, and `viral_correlation`.
    """
    if not body.transcript.strip():
        raise HTTPException(status_code=400, detail="transcript must not be empty")

    segs: Optional[List[Tuple[float, float, str]]] = None
    if body.segments:
        try:
            segs = [(float(s[0]), float(s[1]), str(s[2])) for s in body.segments]
        except (IndexError, ValueError):
            raise HTTPException(
                status_code=400,
                detail="Each segment must be [start_sec, end_sec, text]",
            )

    analyzer = get_sentiment_analyzer()
    try:
        result = await analyzer.analyze_transcript(body.transcript, segs)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "success", "analysis": _fmt_result(result)}


@router.get("/trends")
def get_trends(days: int = 7):
    """
    Get aggregated sentiment trends from recent analysis history.

    Returns `average_sentiment`, `average_viral_correlation`,
    `category_distribution`, and `trend_direction`.
    """
    if days < 1 or days > 365:
        raise HTTPException(status_code=400, detail="days must be between 1 and 365")
    analyzer = get_sentiment_analyzer()
    trends = analyzer.get_historical_trends(days)
    return {"status": "success", "trends": trends}


@router.get("/categories")
def list_categories():
    """List all sentiment categories and emotion types."""
    from ...services.sentiment_analyzer import SentimentCategory, EmotionType
    return {
        "sentiment_categories": [c.value for c in SentimentCategory],
        "emotion_types": [e.value for e in EmotionType],
    }
