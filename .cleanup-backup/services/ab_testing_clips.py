"""
A/B Testing System for Clips
Automated A/B testing framework to optimize clip performance.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
import random

logger = logging.getLogger(__name__)


class ABTestStatus(Enum):
    """A/B test lifecycle states."""
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class VariantType(Enum):
    """Types of clip variants for testing."""
    DIFFERENT_HOOK = "different_hook"
    DIFFERENT_THUMBNAIL = "different_thumbnail"
    DIFFERENT_DURATION = "different_duration"
    DIFFERENT_EFFECTS = "different_effects"
    DIFFERENT_CAPTIONS = "different_captions"


@dataclass
class ClipVariant:
    """A variant of a clip for A/B testing."""
    variant_id: str
    clip_id: str
    name: str
    type: VariantType
    changes_description: str
    file_path: Path
    traffic_percentage: float
    metrics: Dict[str, float]


@dataclass
class ABTest:
    """A/B test definition."""
    test_id: str
    user_id: str
    original_clip_id: str
    name: str
    description: str
    status: ABTestStatus
    variants: List[ClipVariant]
    target_platform: str
    target_metric: str  # views, engagement, completion_rate
    sample_size: int
    confidence_level: float
    start_date: Optional[str]
    end_date: Optional[str]
    winning_variant_id: Optional[str]
    created_at: str


class ABTestingService:
    """
    Automated A/B testing service for clip optimization.
    """
    
    def __init__(self):
        self._tests: Dict[str, ABTest] = {}
        self._results: Dict[str, Dict[str, Any]] = {}
        self._engagement_tracker: Dict[str, Dict[str, int]] = {}
    
    async def create_test(
        self,
        user_id: str,
        original_clip_id: str,
        name: str,
        description: str,
        variants_config: List[Dict[str, Any]],
        target_platform: str = "youtube",
        target_metric: str = "engagement",
        sample_size: int = 1000,
        confidence_level: float = 0.95
    ) -> ABTest:
        """Create a new A/B test for clips."""
        import uuid
        
        test_id = str(uuid.uuid4())
        
        # Create variants
        variants = []
        total_percentage = 0
        
        for i, config in enumerate(variants_config):
            variant = ClipVariant(
                variant_id=str(uuid.uuid4()),
                clip_id=config.get("clip_id", original_clip_id),
                name=config.get("name", f"Variant {i+1}"),
                type=VariantType(config.get("type", "different_hook")),
                changes_description=config.get("changes", ""),
                file_path=Path(config.get("file_path", "")),
                traffic_percentage=config.get("traffic_percentage", 100.0 / len(variants_config)),
                metrics={
                    "views": 0,
                    "engagement": 0.0,
                    "completion_rate": 0.0,
                    "click_through_rate": 0.0
                }
            )
            variants.append(variant)
            total_percentage += variant.traffic_percentage
        
        # Normalize percentages
        if total_percentage != 100:
            factor = 100 / total_percentage
            for variant in variants:
                variant.traffic_percentage *= factor
        
        test = ABTest(
            test_id=test_id,
            user_id=user_id,
            original_clip_id=original_clip_id,
            name=name,
            description=description,
            status=ABTestStatus.DRAFT,
            variants=variants,
            target_platform=target_platform,
            target_metric=target_metric,
            sample_size=sample_size,
            confidence_level=confidence_level,
            start_date=None,
            end_date=None,
            winning_variant_id=None,
            created_at=datetime.now().isoformat()
        )
        
        self._tests[test_id] = test
        logger.info(f"Created A/B test {test_id} for clip {original_clip_id}")
        return test
    
    async def start_test(self, test_id: str) -> bool:
        """Start an A/B test."""
        if test_id not in self._tests:
            return False
        
        test = self._tests[test_id]
        
        if test.status != ABTestStatus.DRAFT:
            logger.warning(f"Test {test_id} is not in draft status")
            return False
        
        test.status = ABTestStatus.RUNNING
        test.start_date = datetime.now().isoformat()
        
        # Calculate end date based on sample size estimation
        # Assuming 100 views per day per variant on average
        days_needed = test.sample_size / (100 * len(test.variants))
        test.end_date = (datetime.now() + timedelta(days=max(7, int(days_needed)))).isoformat()
        
        logger.info(f"Started A/B test {test_id}")
        return True
    
    def get_variant_for_user(
        self,
        test_id: str,
        user_id: str
    ) -> Optional[ClipVariant]:
        """Get which variant to show to a specific user."""
        if test_id not in self._tests:
        return None
        
        test = self._tests[test_id]
        
        if test.status != ABTestStatus.RUNNING:
            return None
        
        # Deterministic assignment based on user_id hash
        hash_value = hash(f"{test_id}:{user_id}")
        assignment = hash_value % 100
        
        cumulative = 0
        for variant in test.variants:
            cumulative += variant.traffic_percentage
            if assignment < cumulative:
                return variant
        
        return test.variants[0] if test.variants else None
    
    async def record_metric(
        self,
        test_id: str,
        variant_id: str,
        metric_name: str,
        value: float
    ) -> None:
        """Record a metric for a variant."""
        if test_id not in self._tests:
            return
        
        test = self._tests[test_id]
        
        for variant in test.variants:
            if variant.variant_id == variant_id:
                if metric_name in variant.metrics:
                    # Update running average for engagement metrics
                    if metric_name in ["engagement", "completion_rate", "click_through_rate"]:
                        old_value = variant.metrics[metric_name]
                        views = variant.metrics.get("views", 1)
                        variant.metrics[metric_name] = ((old_value * (views - 1)) + value) / views
                    else:
                        variant.metrics[metric_name] += value
                break
    
    async def record_view(self, test_id: str, variant_id: str) -> None:
        """Record a view for a variant."""
        await self.record_metric(test_id, variant_id, "views", 1)
    
    async def record_engagement(
        self,
        test_id: str,
        variant_id: str,
        engagement_score: float
    ) -> None:
        """Record engagement for a variant."""
        await self.record_metric(test_id, variant_id, "engagement", engagement_score)
    
    async def analyze_results(self, test_id: str) -> Optional[Dict[str, Any]]:
        """Analyze A/B test results."""
        if test_id not in self._tests:
            return None
        
        test = self._tests[test_id]
        
        if test.status != ABTestStatus.RUNNING and test.status != ABTestStatus.COMPLETED:
            return None
        
        # Calculate statistics for each variant
        variant_stats = []
        
        for variant in test.variants:
            views = variant.metrics.get("views", 0)
            if views == 0:
                continue
            
            engagement = variant.metrics.get("engagement", 0)
            completion_rate = variant.metrics.get("completion_rate", 0)
            ctr = variant.metrics.get("click_through_rate", 0)
            
            # Calculate composite score based on target metric
            if test.target_metric == "engagement":
                score = engagement
            elif test.target_metric == "completion_rate":
                score = completion_rate
            elif test.target_metric == "views":
                score = views
            else:
                score = (engagement + completion_rate + ctr) / 3
            
            variant_stats.append({
                "variant_id": variant.variant_id,
                "name": variant.name,
                "type": variant.type.value,
                "views": views,
                "engagement": engagement,
                "completion_rate": completion_rate,
                "click_through_rate": ctr,
                "score": score,
                "traffic_percentage": variant.traffic_percentage
            })
        
        if not variant_stats:
            return None
        
        # Determine winner
        winner = max(variant_stats, key=lambda x: x["score"])
        
        # Calculate confidence
        total_views = sum(v["views"] for v in variant_stats)
        confidence = min(0.99, total_views / test.sample_size) if test.sample_size > 0 else 0
        
        results = {
            "test_id": test_id,
            "test_name": test.name,
            "status": test.status.value,
            "target_metric": test.target_metric,
            "total_views": total_views,
            "target_sample_size": test.sample_size,
            "confidence": confidence,
            "is_statistically_significant": confidence >= test.confidence_level,
            "variants": variant_stats,
            "winner": winner if confidence >= test.confidence_level else None,
            "recommendation": self._generate_recommendation(variant_stats, test.target_metric, confidence >= test.confidence_level)
        }
        
        self._results[test_id] = results
        return results
    
    def _generate_recommendation(
        self,
        variant_stats: List[Dict],
        target_metric: str,
        is_significant: bool
    ) -> str:
        """Generate a recommendation based on test results."""
        if not is_significant:
            return f"Need more data to determine winner. Continue running the test to reach statistical significance."
        
        winner = max(variant_stats, key=lambda x: x["score"])
        
        improvement = 0
        if len(variant_stats) > 1:
            runner_up = sorted(variant_stats, key=lambda x: x["score"], reverse=True)[1]
            if runner_up["score"] > 0:
                improvement = ((winner["score"] - runner_up["score"]) / runner_up["score"]) * 100
        
        return f"Variant '{winner['name']}' ({winner['type']}) performs best with {winner[target_metric]:.1f} {target_metric}. Estimated improvement: {improvement:.1f}%"
    
    async def complete_test(self, test_id: str) -> bool:
        """Complete an A/B test and select winner."""
        if test_id not in self._tests:
            return False
        
        test = self._tests[test_id]
        
        if test.status != ABTestStatus.RUNNING:
            return False
        
        # Analyze final results
        results = await self.analyze_results(test_id)
        
        if results and results["winner"]:
            test.winning_variant_id = results["winner"]["variant_id"]
        
        test.status = ABTestStatus.COMPLETED
        test.end_date = datetime.now().isoformat()
        
        logger.info(f"Completed A/B test {test_id}. Winner: {test.winning_variant_id}")
        return True
    
    def get_test_status(self, test_id: str) -> Optional[Dict[str, Any]]:
        """Get current status of an A/B test."""
        if test_id not in self._tests:
            return None
        
        test = self._tests[test_id]
        
        total_views = sum(v.metrics.get("views", 0) for v in test.variants)
        progress = min(100, (total_views / test.sample_size) * 100) if test.sample_size > 0 else 0
        
        return {
            "test_id": test.test_id,
            "name": test.name,
            "status": test.status.value,
            "target_platform": test.target_platform,
            "target_metric": test.target_metric,
            "variants_count": len(test.variants),
            "total_views": total_views,
            "target_sample_size": test.sample_size,
            "progress_percentage": progress,
            "start_date": test.start_date,
            "estimated_end": test.end_date,
            "winning_variant": test.winning_variant_id
        }
    
    def list_user_tests(
        self,
        user_id: str,
        status: Optional[ABTestStatus] = None
    ) -> List[Dict[str, Any]]:
        """List A/B tests for a user."""
        tests = [
            test for test in self._tests.values()
            if test.user_id == user_id
        ]
        
        if status:
            tests = [t for t in tests if t.status == status]
        
        return [
            {
                "test_id": t.test_id,
                "name": t.name,
                "status": t.status.value,
                "target_platform": t.target_platform,
                "variants": len(t.variants),
                "created_at": t.created_at
            }
            for t in sorted(tests, key=lambda x: x.created_at, reverse=True)
        ]
    
    async def auto_generate_variants(
        self,
        clip_id: str,
        clip_path: Path,
        num_variants: int = 3
    ) -> List[Dict[str, Any]]:
        """Automatically generate test variants for a clip."""
        variants = []
        
        variant_configs = [
            {
                "type": "different_hook",
                "name": "Alternative Hook",
                "changes": "Different opening 3 seconds"
            },
            {
                "type": "different_duration", 
                "name": "Shorter Version",
                "changes": "15 seconds shorter"
            },
            {
                "type": "different_effects",
                "name": "More Effects",
                "changes": "Added viral effects"
            },
            {
                "type": "different_captions",
                "name": "With Captions",
                "changes": "Added animated captions"
            },
            {
                "type": "different_thumbnail",
                "name": "AI Thumbnail",
                "changes": "AI-generated thumbnail"
            }
        ]
        
        for i in range(min(num_variants, len(variant_configs))):
            config = variant_configs[i]
            variants.append({
                "clip_id": f"{clip_id}_variant_{i+1}",
                "type": config["type"],
                "name": config["name"],
                "changes": config["changes"],
                "file_path": str(clip_path),
                "traffic_percentage": 100.0 / num_variants
            })
        
        return variants


# Global instance
_ab_testing_service: Optional[ABTestingService] = None


def get_ab_testing_service() -> ABTestingService:
    """Get global A/B testing service."""
    global _ab_testing_service
    if _ab_testing_service is None:
        _ab_testing_service = ABTestingService()
    return _ab_testing_service


# Convenience functions
async def create_clip_ab_test(
    user_id: str,
    clip_id: str,
    variants: List[Dict[str, Any]],
    target_platform: str = "youtube"
) -> str:
    """Create an A/B test for a clip."""
    service = get_ab_testing_service()
    test = await service.create_test(
        user_id=user_id,
        original_clip_id=clip_id,
        name=f"A/B Test for {clip_id}",
        description="Automated A/B test",
        variants_config=variants,
        target_platform=target_platform
    )
    return test.test_id


def get_clip_variant_for_user(test_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Get variant assignment for a user."""
    service = get_ab_testing_service()
    variant = service.get_variant_for_user(test_id, user_id)
    
    if variant:
        return {
            "variant_id": variant.variant_id,
            "name": variant.name,
            "file_path": str(variant.file_path)
        }
    return None
