"""
A/B Testing API endpoints.

Create and manage A/B tests of clip variants to find the most viral version.
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ab-testing", tags=["ab-testing"])


class CreateABTestRequest(BaseModel):
    original_clip_id: str
    num_variants: int = 3
    test_duration_hours: int = 24
    test_accounts: Optional[dict] = None  # {platform: account_id}


@router.post("/tests")
async def create_ab_test(request: Request, body: CreateABTestRequest):
    """
    Create an A/B test with multiple style variants of a clip.

    Variants include: FAST_CUTS, SLOW_EDUCATIONAL, BALANCED, MUSIC_HEAVY,
    HOOK_FIRST, CAPTION_HEAVY, MINIMAL.
    """
    from ...services.ab_testing_service import ABTestingService

    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    try:
        svc = ABTestingService()
        test = await svc.create_ab_test(
            user_id=user_id,
            original_clip_id=body.original_clip_id,
            num_variants=body.num_variants,
            test_duration_hours=body.test_duration_hours,
            test_accounts=body.test_accounts,
        )
        return {"status": "created", "test": _test_summary(test)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"[ABTest] create failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tests/{test_id}/start")
async def start_ab_test(request: Request, test_id: str):
    """
    Start an A/B test by publishing all variants to configured platforms.
    """
    from ...services.ab_testing_service import ABTestingService

    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = ABTestingService()
    started = await svc.start_test(user_id=user_id, test_id=test_id)

    if not started:
        raise HTTPException(status_code=404, detail=f"Test {test_id} not found")

    return {"status": "started", "test_id": test_id}


@router.post("/tests/{test_id}/analyze")
async def analyze_ab_test(request: Request, test_id: str):
    """
    Manually trigger A/B test analysis and determine winner.
    (Normally triggered automatically after test_duration_hours.)
    """
    from ...services.ab_testing_service import ABTestingService

    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = ABTestingService()
    winner = await svc.analyze_test(user_id=user_id, test_id=test_id)

    return {
        "status": "analyzed",
        "test_id": test_id,
        "winner": {
            "variant_id": winner.variant_id,
            "style": winner.style.value,
            "virality_score": winner.virality_score,
            "views": winner.views,
            "engagement_rate": winner.engagement_rate,
        } if winner else None,
        "inconclusive": winner is None,
    }


@router.get("/tests")
async def list_ab_tests(request: Request):
    """
    List all A/B tests for the current user.
    """
    from ...services.ab_testing_service import ABTestingService

    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = ABTestingService()
    tests = await svc.get_user_tests(user_id=user_id)

    return {
        "status": "success",
        "count": len(tests),
        "tests": [_test_summary(t) for t in tests],
    }


@router.get("/tests/{test_id}")
async def get_ab_test(request: Request, test_id: str):
    """
    Get details of a specific A/B test.
    """
    from ...services.ab_testing_service import ABTestingService

    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = ABTestingService()
    test = await svc._load_test(user_id=user_id, test_id=test_id)

    if not test:
        raise HTTPException(status_code=404, detail=f"Test {test_id} not found")

    return {"status": "success", "test": _test_summary(test, detail=True)}


@router.get("/styles")
async def list_variant_styles():
    """
    List all available A/B testing variant styles with their configurations.
    """
    from ...services.ab_testing_service import ABTestingService, VariantStyle

    svc = ABTestingService()
    return {
        "styles": [
            {
                "name": style.value,
                "config": svc.STYLE_CONFIGS[style],
            }
            for style in VariantStyle
        ]
    }


def _test_summary(test, detail: bool = False) -> dict:
    """Serialize an ABTest to a dict."""
    base = {
        "test_id": test.test_id,
        "name": test.name,
        "original_clip_id": test.original_clip_id,
        "status": test.status,
        "variant_count": len(test.variants),
        "test_duration_hours": test.test_duration_hours,
        "winner_variant_id": test.winner_variant_id,
        "confidence_level": test.confidence_level,
        "created_at": test.created_at.isoformat() if test.created_at else None,
    }
    if detail:
        base["variants"] = [
            {
                "variant_id": v.variant_id,
                "style": v.style.value,
                "clip_id": v.clip_id,
                "status": v.status,
                "views": v.views,
                "engagement_rate": v.engagement_rate,
                "virality_score": v.virality_score,
            }
            for v in test.variants
        ]
    return base
