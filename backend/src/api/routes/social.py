from fastapi import APIRouter, Depends, HTTPException, Request
from typing import List, Dict, Any
from pydantic import BaseModel
from pathlib import Path
from ...services.social_distribution_service import SocialDistributionService
from ...services.campaign_service import CampaignService
from ...services.elite_ai_service import EliteAIService
from ...config import get_config
from ...auth_headers import get_signed_user_id, USER_ID_HEADER

router = APIRouter(prefix="/social", tags=["social"])


def _get_user_id(request: Request) -> str:
    """Authenticate request — mirrors the pattern used across the rest of the API."""
    config = get_config()
    if config.monetization_enabled:
        return get_signed_user_id(request, config)
    user_id = request.headers.get("user_id") or request.headers.get(USER_ID_HEADER)
    if not user_id:
        raise HTTPException(status_code=401, detail="User authentication required")
    return user_id


class PublishRequest(BaseModel):
    video_id: str
    platform: str
    caption: str
    hashtags: List[str]
    auth_token: str


class ReplyRequest(BaseModel):
    clip_context: str
    comment_text: str


@router.post("/publish")
async def publish_clip(request: Request, body: PublishRequest):
    """
    Triggers the V4 Elite Social Distribution flow.
    """
    _get_user_id(request)  # auth guard
    try:
        config = get_config()
        # Clips are stored under TEMP_DIR/clips — not the legacy storage/clips path
        video_path = Path(config.temp_dir) / "clips" / f"{body.video_id}.mp4"

        result = await SocialDistributionService.publish_clip(
            video_path=video_path,
            platform=body.platform,
            caption=body.caption,
            hashtags=body.hashtags,
            user_auth_token=body.auth_token,
        )
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Clip '{body.video_id}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reply")
async def generate_reply(request: Request, body: ReplyRequest):
    """
    Generates an autonomous, context-aware reply to a social media comment.
    Body: { "clip_context": "...", "comment_text": "..." }
    """
    _get_user_id(request)  # auth guard
    try:
        elite_ai = EliteAIService()
        reply = await elite_ai.generate_social_reply(body.clip_context, body.comment_text)
        return {"reply": reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/campaigns/ab-test")
async def create_ab_test(request: Request, task_id: str, clip_id: str, styles: List[str] = ["anime", "cyberpunk"]):
    """
    Triggers an A/B split-testing campaign for a specific clip.
    """
    _get_user_id(request)  # auth guard
    try:
        result = await CampaignService.create_ab_test_campaign(task_id, clip_id, styles)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/campaigns")
async def get_all_campaigns(request: Request):
    """
    Returns all active A/B testing campaigns and their current metrics.
    """
    _get_user_id(request)  # auth guard
    from ...repositories.campaign_repository import CampaignRepository
    try:
        campaigns = CampaignRepository._load_campaigns()
        return campaigns
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trends")
async def get_latest_trends(request: Request):
    """
    Fetches AI-curated trend presets and hashtags.
    """
    _get_user_id(request)  # auth guard
    # P4: Logic to call TrendIntelligenceAgent via EliteAIService
    return {
        "presets": ["Retro VHS", "Neon Cyberpunk", "Low-Fi Minimalist"],
        "hashtags": ["#viraclip", "#elite", "#foryou", "#growth"],
    }


@router.get("/auth/{platform}")
async def get_social_auth_url(request: Request, platform: str):
    """
    Returns the OAuth2 redirect URL for social platform authorization.
    """
    _get_user_id(request)  # auth guard
    url = SocialDistributionService.get_oauth_url(platform)
    return {"url": url}
