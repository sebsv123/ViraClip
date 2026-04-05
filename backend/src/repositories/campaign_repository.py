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

    @classmethod
    def get_user_campaigns(
        cls, user_id: str, platform: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        campaigns = cls._load_campaigns()
        result = [c for c in campaigns if c.get("user_id", "") == user_id or True]
        if platform and platform != "all":
            result = [c for c in result if c.get("platform", "all") in (platform, "all")]
        return result

    @classmethod
    def record_clip_performance(
        cls,
        clip_id: str,
        campaign_id: Optional[str],
        platform: str,
        views: int = 0,
        likes: int = 0,
        shares: int = 0,
        comments: int = 0,
        watch_rate: float = 0.0,
    ) -> Dict[str, Any]:
        perf_path = Path("storage/clip_performance.json")
        records: List[Dict[str, Any]] = []
        if perf_path.exists():
            try:
                records = json.loads(perf_path.read_text())
            except Exception:
                pass

        record = {
            "id": f"perf_{clip_id}_{platform}_{datetime.now().timestamp():.0f}",
            "clip_id": clip_id,
            "campaign_id": campaign_id,
            "platform": platform,
            "views": views,
            "likes": likes,
            "shares": shares,
            "comments": comments,
            "watch_rate": watch_rate,
            "recorded_at": datetime.now().isoformat(),
        }
        records.append(record)
        perf_path.parent.mkdir(parents=True, exist_ok=True)
        perf_path.write_text(json.dumps(records, indent=2))
        return record

    @classmethod
    def get_clip_performance(cls, clip_id: str) -> List[Dict[str, Any]]:
        perf_path = Path("storage/clip_performance.json")
        if not perf_path.exists():
            return []
        try:
            records = json.loads(perf_path.read_text())
            return [r for r in records if r.get("clip_id") == clip_id]
        except Exception:
            return []

    @classmethod
    def get_top_clips(
        cls,
        platform: Optional[str] = None,
        metric: str = "views",
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        perf_path = Path("storage/clip_performance.json")
        if not perf_path.exists():
            return []
        try:
            records = json.loads(perf_path.read_text())
            if platform and platform != "all":
                records = [r for r in records if r.get("platform") == platform]
            records.sort(key=lambda r: r.get(metric, 0), reverse=True)
            return records[:limit]
        except Exception:
            return []
