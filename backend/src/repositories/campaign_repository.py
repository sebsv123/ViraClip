import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
import json
from pathlib import Path

logger = logging.getLogger(__name__)

class CampaignRepository:
    """
    Persistence layer for ViraClip V4 Elite Campaigns (A/B Tests).
    For now, uses JSON-based storage for simplicity in the 'Elite' sprint.
    """
    STORAGE_PATH = Path("storage/campaigns.json")

    @classmethod
    def _load_campaigns(cls) -> List[Dict[str, Any]]:
        if not cls.STORAGE_PATH.exists():
            cls.STORAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(cls.STORAGE_PATH, 'w') as f:
                json.dump([], f)
            return []
        
        try:
            with open(cls.STORAGE_PATH, 'r') as f:
                return json.load(f)
        except Exception:
            return []

    @classmethod
    def _save_campaigns(cls, campaigns: List[Dict[str, Any]]):
        with open(cls.STORAGE_PATH, 'w') as f:
            json.dump(campaigns, f, indent=2)

    @classmethod
    def create_campaign(cls, task_id: str, clip_id: str, styles: List[str]) -> Dict[str, Any]:
        campaigns = cls._load_campaigns()
        new_campaign = {
            "campaign_id": f"CAMP_{task_id}_{clip_id}",
            "task_id": task_id,
            "source_clip_id": clip_id,
            "styles": styles,
            "status": "initializing",
            "variations": [],
            "created_at": datetime.now().isoformat(),
            "performance_metrics": {}
        }
        campaigns.append(new_campaign)
        cls._save_campaigns(campaigns)
        logger.info(f"📊 Campaign: Created A/B test campaign {new_campaign['campaign_id']}")
        return new_campaign

    @classmethod
    def update_campaign_status(cls, campaign_id: str, status: str, variations: Optional[List[str]] = None):
        campaigns = cls._load_campaigns()
        for c in campaigns:
            if c["campaign_id"] == campaign_id:
                c["status"] = status
                if variations:
                    c["variations"] = variations
                break
        cls._save_campaigns(campaigns)

    @classmethod
    def get_campaign(cls, campaign_id: str) -> Optional[Dict[str, Any]]:
        campaigns = cls._load_campaigns()
        return next((c for c in campaigns if c["campaign_id"] == campaign_id), None)
