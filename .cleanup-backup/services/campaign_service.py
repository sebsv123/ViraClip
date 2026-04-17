import logging
from typing import List, Dict, Any, Optional
from pathlib import Path
from .video_service import VideoService
from .vfx_service import VFXService
from ..repositories.campaign_repository import CampaignRepository
from ..config import get_config

logger = logging.getLogger(__name__)

class CampaignService:
    """
    V4 Elite Campaign & Growth Hub.
    Orchestrates A/B testing and performance tracking for clips.
    """

    @staticmethod
    async def create_ab_test_campaign(
        task_id: str,
        clip_id: str,
        test_styles: List[str] = ["anime", "cyberpunk"]
    ) -> Dict[str, Any]:
        """
        Triggers an A/B split-testing campaign for a specific clip.
        Renders the same source segment in multiple generative aesthetics.
        """
        logger.info(f"📊 Campaign: Initializing A/B test for clip {clip_id} with styles {test_styles}")
        
        # 1. Create campaign record
        campaign = CampaignRepository.create_campaign(task_id, clip_id, test_styles)
        
        # 2. Source path resolution — clips live under TEMP_DIR/clips/
        cfg = get_config()
        source_path = Path(cfg.temp_dir) / "clips" / f"{clip_id}.mp4"
        
        # 3. Trigger multi-style rendering (Phase 5 core)
        variations = []
        vfx_hub = VFXService()
        
        for style in test_styles:
            try:
                styled_path = await vfx_hub.apply_generative_style(
                    source_path, style_references=[], output_format=style, task_id=task_id
                )
                variations.append(str(styled_path))
                logger.info(f"✅ Variation '{style}' rendered at {styled_path}")
            except Exception as e:
                logger.error(f"Failed to render variation '{style}': {e}")

        # 4. Update campaign status
        CampaignRepository.update_campaign_status(
            campaign["campaign_id"], 
            status="active" if variations else "failed",
            variations=variations
        )
        
        return {
            "campaign_id": campaign["campaign_id"],
            "variations_count": len(variations),
            "status": "active"
        }

    @staticmethod
    async def analyze_performance(campaign_id: str) -> Dict[str, Any]:
        """
        Simulates performance analysis for a campaign's variants.
        """
        logger.info(f"📈 Campaign: Analyzing performance for {campaign_id}")
        return {
            "top_variant": "anime",
            "improvement_score": 1.25,
            "recommendation": "Use high-contrast styles for similar source content."
        }
