"""
Stub for CampaignService (A/B testing campaigns).

Original implementation missing — this stub allows the backend to boot while the
full campaign feature is not yet wired. Replace with real implementation when
A/B testing is needed.
"""
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class CampaignService:
    """Minimal stub — returns a placeholder response for A/B testing endpoints."""

    @staticmethod
    async def create_ab_test_campaign(
        task_id: str,
        clip_id: str,
        styles: List[str],
    ) -> Dict[str, Any]:
        logger.warning(
            "[CampaignService] Stub invoked (task=%s clip=%s styles=%s) — not implemented",
            task_id, clip_id, styles,
        )
        return {
            "status": "stub",
            "task_id": task_id,
            "clip_id": clip_id,
            "styles": styles,
            "message": "CampaignService is a stub — A/B testing feature not implemented",
        }
