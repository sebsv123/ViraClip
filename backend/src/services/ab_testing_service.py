"""
A/B Testing Framework — Viral Variant Optimization
==================================================

Automatically creates and tests multiple variants of clips
to find the most viral version.

Usage:
    from services.ab_testing_service import ABTestingService
    
    ab = ABTestingService()
    test = await ab.create_ab_test(clip_id="clip_123", variants=3)
    winner = await ab.get_winner(test_id=test.id, after_hours=24)
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional
import json
import hashlib

logger = logging.getLogger(__name__)


class VariantStyle(Enum):
    """Style variations for A/B testing."""
    FAST_CUTS = "fast_cuts"           # High energy, quick cuts
    SLOW_EDUCATIONAL = "slow_edu"     # Slower, more informative
    BALANCED = "balanced"             # Middle ground
    MUSIC_HEAVY = "music_heavy"       # Strong music emphasis
    HOOK_FIRST = "hook_first"         # Hook in first 1 second
    CAPTION_HEAVY = "caption_heavy"   # More text overlays
    MINIMAL = "minimal"               # Clean, simple


@dataclass
class Variant:
    """A variant in an A/B test."""
    variant_id: str
    style: VariantStyle
    clip_id: str  # GeneratedClip.id
    
    # Processing parameters that differ
    cut_speed: str  # fast, normal, slow
    music_intensity: float  # 0-1
    caption_style: str
    hook_timing: float  # seconds to hook
    
    # Results
    status: str = "pending"  # pending, published, running, completed
    youtube_video_id: Optional[str] = None
    tiktok_video_id: Optional[str] = None
    instagram_media_id: Optional[str] = None
    
    # Metrics (populated after test)
    views: int = 0
    engagement_rate: float = 0.0
    virality_score: float = 0.0
    
    published_at: Optional[datetime] = None


@dataclass
class ABTest:
    """An A/B test configuration."""
    test_id: str
    user_id: str
    original_clip_id: str
    name: str
    
    variants: List[Variant] = field(default_factory=list)
    
    status: str = "created"  # created, running, completed, cancelled
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    test_duration_hours: int = 24
    winner_variant_id: Optional[str] = None
    confidence_level: float = 0.0
    
    # Platform accounts for testing
    test_accounts: Dict[str, str] = field(default_factory=dict)  # platform -> account_id


class ABTestingService:
    """
    Service for creating and managing A/B tests of clip variants.
    """
    
    # Processing configurations for each style
    STYLE_CONFIGS = {
        VariantStyle.FAST_CUTS: {
            "cut_speed": "fast",
            "music_intensity": 0.9,
            "caption_style": "energetic",
            "hook_timing": 0.0,
            "subtitle_duration": 1.5,
        },
        VariantStyle.SLOW_EDUCATIONAL: {
            "cut_speed": "slow",
            "music_intensity": 0.4,
            "caption_style": "clean",
            "hook_timing": 3.0,
            "subtitle_duration": 3.0,
        },
        VariantStyle.BALANCED: {
            "cut_speed": "normal",
            "music_intensity": 0.6,
            "caption_style": "modern",
            "hook_timing": 1.0,
            "subtitle_duration": 2.0,
        },
        VariantStyle.MUSIC_HEAVY: {
            "cut_speed": "normal",
            "music_intensity": 1.0,
            "caption_style": "minimal",
            "hook_timing": 0.5,
            "subtitle_duration": 2.0,
        },
        VariantStyle.HOOK_FIRST: {
            "cut_speed": "fast",
            "music_intensity": 0.8,
            "caption_style": "bold",
            "hook_timing": 0.0,
            "subtitle_duration": 1.8,
        },
        VariantStyle.CAPTION_HEAVY: {
            "cut_speed": "normal",
            "music_intensity": 0.5,
            "caption_style": "word_by_word",
            "hook_timing": 1.0,
            "subtitle_duration": 1.5,
        },
        VariantStyle.MINIMAL: {
            "cut_speed": "normal",
            "music_intensity": 0.5,
            "caption_style": "minimal",
            "hook_timing": 2.0,
            "subtitle_duration": 2.5,
        },
    }
    
    def __init__(self):
        self.redis = None
    
    async def _get_redis(self):
        """Get Redis connection."""
        if self.redis is None:
            from ...workers.job_queue import JobQueue
            self.redis = await JobQueue.get_pool()
        return self.redis
    
    def _generate_test_id(self, user_id: str, clip_id: str) -> str:
        """Generate unique test ID."""
        hash_input = f"{user_id}:{clip_id}:{datetime.utcnow().isoformat()}"
        return f"ab_{hashlib.sha256(hash_input.encode()).hexdigest()[:12]}"
    
    async def create_ab_test(
        self,
        user_id: str,
        original_clip_id: str,
        num_variants: int = 3,
        test_duration_hours: int = 24,
        test_accounts: Optional[Dict[str, str]] = None,
    ) -> ABTest:
        """
        Create an A/B test with multiple variants of a clip.
        
        Args:
            user_id: User ID
            original_clip_id: Base clip to create variants from
            num_variants: Number of variants (2-5 recommended)
            test_duration_hours: How long to run test
            test_accounts: Platform test accounts {platform: account_id}
        """
        from ...database import get_db
        from sqlalchemy import select
        from ...models import GeneratedClip
        
        # Get original clip
        async for db in get_db():
            result = await db.execute(
                select(GeneratedClip).where(GeneratedClip.id == original_clip_id)
            )
            original = result.scalar_one_or_none()
            
            if not original:
                raise ValueError(f"Clip not found: {original_clip_id}")
            
            # Select variant styles
            available_styles = list(VariantStyle)
            selected_styles = random.sample(available_styles, min(num_variants, len(available_styles)))
            
            # Always include balanced as baseline
            if VariantStyle.BALANCED not in selected_styles:
                selected_styles[0] = VariantStyle.BALANCED
            
            variants = []
            for i, style in enumerate(selected_styles):
                config = self.STYLE_CONFIGS[style]
                
                # Create variant clip
                variant_clip = await self._create_variant_clip(
                    db, original, style, config
                )
                
                variant = Variant(
                    variant_id=f"{original_clip_id}_v{i}",
                    style=style,
                    clip_id=variant_clip.id,
                    cut_speed=config["cut_speed"],
                    music_intensity=config["music_intensity"],
                    caption_style=config["caption_style"],
                    hook_timing=config["hook_timing"],
                )
                variants.append(variant)
            
            # Create test
            test = ABTest(
                test_id=self._generate_test_id(user_id, original_clip_id),
                user_id=user_id,
                original_clip_id=original_clip_id,
                name=f"A/B Test: {original_clip_id}",
                variants=variants,
                test_duration_hours=test_duration_hours,
                test_accounts=test_accounts or {},
            )
            
            # Store in Redis
            redis = await self._get_redis()
            await redis.hset(
                f"ab_tests:{user_id}",
                test.test_id,
                json.dumps(self._test_to_dict(test))
            )
            
            logger.info(f"[ABTest] Created test {test.test_id} with {len(variants)} variants")
            return test
    
    async def _create_variant_clip(
        self,
        db,
        original: Any,
        style: VariantStyle,
        config: Dict[str, Any],
    ) -> Any:
        """Create a variant clip with different processing."""
        from ...models import GeneratedClip
        import copy
        
        # Create new clip with variant settings
        variant = copy.deepcopy(original)
        variant.id = None  # Will generate new ID
        variant.clip_order = original.clip_order + 100  # Separate order
        variant.file_path = original.file_path.replace(".mp4", f"_{style.value}.mp4")
        variant.reasoning = f"A/B variant: {style.value}"
        
        # Store variant config in metadata
        metadata = {
            "ab_variant": style.value,
            "cut_speed": config["cut_speed"],
            "music_intensity": config["music_intensity"],
            "subtitle_duration": config["subtitle_duration"],
            "original_clip_id": original.id,
        }
        
        variant.clip_metadata = json.dumps(metadata)
        
        db.add(variant)
        await db.flush()
        await db.refresh(variant)
        
        return variant
    
    async def start_test(self, user_id: str, test_id: str) -> bool:
        """
        Start the A/B test by publishing all variants.
        """
        from ...services.youtube_upload_service import YouTubeAutoPublisher
        from ...services.tiktok_upload_service import TikTokAutoPublisher
        from ...services.instagram_upload_service import InstagramAutoPublisher
        
        test = await self._load_test(user_id, test_id)
        if not test:
            return False
        
        test.started_at = datetime.utcnow()
        test.status = "running"
        
        # Publish each variant to test accounts
        for variant in test.variants:
            try:
                # Publish to platforms
                if "youtube" in test.test_accounts:
                    yt_pub = YouTubeAutoPublisher()
                    result = await yt_pub.publish_clip(
                        variant.clip_id,
                        credentials=None,  # Would load from test account
                        publish_options={"privacy": "unlisted"}  # Unlisted for testing
                    )
                    if result.success:
                        variant.youtube_video_id = result.video_id
                
                if "tiktok" in test.test_accounts:
                    tt_pub = TikTokAutoPublisher()
                    result = await tt_pub.publish_clip(
                        variant.clip_id,
                        credentials=None,
                        publish_options={"privacy": "private"}
                    )
                    if result.success:
                        variant.tiktok_video_id = result.video_id
                
                variant.status = "published"
                variant.published_at = datetime.utcnow()
                
            except Exception as e:
                logger.error(f"[ABTest] Failed to publish variant {variant.variant_id}: {e}")
                variant.status = "failed"
        
        # Schedule analysis job
        await self._schedule_analysis(user_id, test_id, test.test_duration_hours)
        
        # Save updated test
        await self._save_test(user_id, test)
        
        logger.info(f"[ABTest] Started test {test_id}")
        return True
    
    async def _schedule_analysis(self, user_id: str, test_id: str, hours: int):
        """Schedule the analysis job to run after test duration."""
        redis = await self._get_redis()
        
        # Use ARQ to schedule
        await redis.enqueue_job(
            "analyze_ab_test",
            user_id=user_id,
            test_id=test_id,
            _defer_by_seconds=hours * 3600,
        )
    
    async def analyze_test(self, user_id: str, test_id: str) -> Optional[Variant]:
        """
        Analyze A/B test results and determine winner.
        
        Returns:
            Winning variant or None if no clear winner
        """
        from ...services.analytics_feedback import AnalyticsFeedbackService
        
        test = await self._load_test(user_id, test_id)
        if not test:
            return None
        
        feedback = AnalyticsFeedbackService()
        
        # Fetch metrics for all variants
        for variant in test.variants:
            # Load clip and compute actual virality
            from ...database import get_db
            from sqlalchemy import select
            from ...models import GeneratedClip
            
            async for db in get_db():
                result = await db.execute(
                    select(GeneratedClip).where(GeneratedClip.id == variant.clip_id)
                )
                clip = result.scalar_one_or_none()
                
                if clip:
                    variant.virality_score = await feedback.compute_actual_virality(clip)
                    
                    # Get raw metrics
                    total_views = (
                        (clip.youtube_views or 0) +
                        (clip.tiktok_views or 0) +
                        (clip.instagram_impressions or 0)
                    )
                    variant.views = total_views
                    
                    # Average engagement
                    eng_rates = []
                    if clip.youtube_engagement_rate:
                        eng_rates.append(clip.youtube_engagement_rate)
                    if clip.tiktok_engagement_rate:
                        eng_rates.append(clip.tiktok_engagement_rate)
                    if clip.instagram_engagement_rate:
                        eng_rates.append(clip.instagram_engagement_rate)
                    
                    variant.engagement_rate = sum(eng_rates) / len(eng_rates) if eng_rates else 0
                
                break
        
        # Determine winner
        winner = self._determine_winner(test.variants)
        
        if winner:
            test.winner_variant_id = winner.variant_id
            test.confidence_level = self._calculate_confidence(test.variants, winner)
            test.status = "completed"
            test.completed_at = datetime.utcnow()
            
            logger.info(
                f"[ABTest] Winner for {test_id}: {winner.style.value} "
                f"(score: {winner.virality_score:.1f}, confidence: {test.confidence_level:.1%})"
            )
        else:
            test.status = "completed_inconclusive"
            logger.info(f"[ABTest] No clear winner for {test_id}")
        
        await self._save_test(user_id, test)
        return winner
    
    def _determine_winner(self, variants: List[Variant]) -> Optional[Variant]:
        """Determine winning variant using statistical significance."""
        if len(variants) < 2:
            return variants[0] if variants else None
        
        # Sort by virality score
        sorted_variants = sorted(variants, key=lambda v: v.virality_score, reverse=True)
        winner = sorted_variants[0]
        runner_up = sorted_variants[1]
        
        # Check if difference is significant (>10% better)
        if runner_up.virality_score > 0:
            improvement = (winner.virality_score - runner_up.virality_score) / runner_up.virality_score
            if improvement < 0.10:  # Less than 10% improvement
                return None  # Inconclusive
        
        # Also check view counts
        if winner.views < 100:  # Not enough data
            return None
        
        return winner
    
    def _calculate_confidence(self, variants: List[Variant], winner: Variant) -> float:
        """Calculate confidence level in the winner."""
        if len(variants) < 2:
            return 0.5
        
        # Simple confidence based on sample size and margin
        total_views = sum(v.views for v in variants)
        
        if total_views < 500:
            return 0.6
        elif total_views < 2000:
            return 0.75
        elif total_views < 10000:
            return 0.85
        else:
            return 0.95
    
    def _test_to_dict(self, test: ABTest) -> Dict:
        """Convert test to dict for storage."""
        return {
            "test_id": test.test_id,
            "user_id": test.user_id,
            "original_clip_id": test.original_clip_id,
            "name": test.name,
            "variants": [
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
            ],
            "status": test.status,
            "created_at": test.created_at.isoformat(),
            "test_duration_hours": test.test_duration_hours,
            "winner_variant_id": test.winner_variant_id,
            "confidence_level": test.confidence_level,
        }
    
    async def _load_test(self, user_id: str, test_id: str) -> Optional[ABTest]:
        """Load test from Redis."""
        redis = await self._get_redis()
        data = await redis.hget(f"ab_tests:{user_id}", test_id)
        
        if not data:
            return None
        
        test_dict = json.loads(data)
        # Reconstruct (simplified)
        return ABTest(**test_dict)
    
    async def _save_test(self, user_id: str, test: ABTest):
        """Save test to Redis."""
        redis = await self._get_redis()
        await redis.hset(
            f"ab_tests:{user_id}",
            test.test_id,
            json.dumps(self._test_to_dict(test))
        )
    
    async def get_user_tests(self, user_id: str) -> List[ABTest]:
        """Get all A/B tests for a user."""
        redis = await self._get_redis()
        tests_data = await redis.hgetall(f"ab_tests:{user_id}")
        
        tests = []
        for test_id, test_json in tests_data.items():
            test_dict = json.loads(test_json)
            tests.append(ABTest(**test_dict))
        
        return tests


# ARQ worker function
async def analyze_ab_test(ctx, user_id: str, test_id: str):
    """Worker function to analyze A/B test after duration."""
    ab_service = ABTestingService()
    await ab_service.analyze_test(user_id, test_id)


__all__ = [
    "ABTestingService",
    "ABTest",
    "Variant",
    "VariantStyle",
    "analyze_ab_test",
]
