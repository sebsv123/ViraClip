"""
A/B Testing System for Virality Algorithms
Compares different virality scoring approaches and optimizes based on results.
"""

import random
import json
import logging
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)


class AlgorithmVariant(Enum):
    """Different algorithm variants for testing."""
    CONTROL = "control"           # Current algorithm
    HOOK_HEAVY = "hook_heavy"     # Weight hooks more heavily
    EMOTION_FOCUS = "emotion_focus"  # Focus on emotional content
    PATTERN_BOOST = "pattern_boost"  # Boost pattern detection
    HYBRID_V2 = "hybrid_v2"       # New hybrid approach


@dataclass
class ABTestConfig:
    """Configuration for an A/B test."""
    test_id: str
    variant: AlgorithmVariant
    weights: Dict[str, float]
    start_date: str
    end_date: Optional[str] = None
    traffic_percentage: float = 0.2  # 20% of traffic
    min_samples: int = 100


@dataclass
class ABTestResult:
    """Results from an A/B test variant."""
    test_id: str
    variant: AlgorithmVariant
    total_clips: int
    avg_virality_score: float
    user_satisfaction: float  # 1-10
    actual_performance: Dict[str, int]  # Count by performance tier
    conversion_rate: float  # % clips that went viral
    confidence_score: float  # Statistical confidence


class ViralityABTestManager:
    """
    Manages A/B testing for virality algorithms.
    """
    
    # Predefined weight configurations for each variant
    VARIANT_CONFIGS = {
        AlgorithmVariant.CONTROL: {
            "hook_weight": 1.0,
            "engagement_weight": 1.0,
            "value_weight": 1.0,
            "shareability_weight": 1.0,
            "pattern_weight": 1.0,
        },
        AlgorithmVariant.HOOK_HEAVY: {
            "hook_weight": 1.5,
            "engagement_weight": 0.9,
            "value_weight": 0.8,
            "shareability_weight": 1.0,
            "pattern_weight": 1.2,
        },
        AlgorithmVariant.EMOTION_FOCUS: {
            "hook_weight": 1.2,
            "engagement_weight": 1.3,
            "value_weight": 1.1,
            "shareability_weight": 1.4,
            "pattern_weight": 0.9,
        },
        AlgorithmVariant.PATTERN_BOOST: {
            "hook_weight": 1.0,
            "engagement_weight": 1.1,
            "value_weight": 1.0,
            "shareability_weight": 1.0,
            "pattern_weight": 1.6,
        },
        AlgorithmVariant.HYBRID_V2: {
            "hook_weight": 1.3,
            "engagement_weight": 1.2,
            "value_weight": 1.1,
            "shareability_weight": 1.3,
            "pattern_weight": 1.4,
        },
    }
    
    def __init__(self, storage_path: Optional[Path] = None):
        if storage_path is None:
            storage_path = Path("/app/data/ab_tests.json")
        
        self.storage_path = storage_path
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._active_tests: Dict[str, ABTestConfig] = {}
        self._results: Dict[str, List[ABTestResult]] = {}
        
        self._load_state()
    
    def _load_state(self) -> None:
        """Load test state from storage."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, 'r') as f:
                    data = json.load(f)
                
                for test_data in data.get("tests", []):
                    config = ABTestConfig(**test_data["config"])
                    self._active_tests[config.test_id] = config
                    self._results[config.test_id] = [
                        ABTestResult(**r) for r in test_data.get("results", [])
                    ]
                
                logger.info(f"Loaded {len(self._active_tests)} A/B tests")
            except Exception as e:
                logger.error(f"Failed to load A/B tests: {e}")
    
    def _save_state(self) -> None:
        """Save test state to storage."""
        try:
            data = {
                "tests": [
                    {
                        "config": asdict(config),
                        "results": [asdict(r) for r in self._results.get(test_id, [])]
                    }
                    for test_id, config in self._active_tests.items()
                ]
            }
            
            with open(self.storage_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save A/B tests: {e}")
    
    def create_test(
        self,
        variant: AlgorithmVariant,
        traffic_percentage: float = 0.2,
        duration_days: int = 14
    ) -> ABTestConfig:
        """
        Create a new A/B test.
        
        Args:
            variant: Algorithm variant to test
            traffic_percentage: % of traffic to use for test (0-1)
            duration_days: How long to run the test
        """
        from datetime import timedelta
        
        test_id = f"ab_{variant.value}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        end_date = (datetime.now() + timedelta(days=duration_days)).isoformat()
        
        config = ABTestConfig(
            test_id=test_id,
            variant=variant,
            weights=self.VARIANT_CONFIGS[variant],
            start_date=datetime.now().isoformat(),
            end_date=end_date,
            traffic_percentage=traffic_percentage,
            min_samples=100
        )
        
        self._active_tests[test_id] = config
        self._results[test_id] = []
        self._save_state()
        
        logger.info(f"Created A/B test: {test_id} for variant {variant.value}")
        return config
    
    def should_use_variant(self, user_id: Optional[str] = None) -> Optional[AlgorithmVariant]:
        """
        Determine if the current request should use a test variant.
        
        Returns None if should use control, or the variant to use.
        """
        # Check for active tests
        active = [
            t for t in self._active_tests.values()
            if t.end_date is None or datetime.fromisoformat(t.end_date) > datetime.now()
        ]
        
        if not active:
            return None
        
        # Hash user_id to consistently assign to same variant
        if user_id:
            user_hash = hash(user_id) % 100
        else:
            user_hash = random.randint(0, 99)
        
        # Assign to variant based on traffic percentage
        cumulative = 0
        for test in active:
            cumulative += int(test.traffic_percentage * 100)
            if user_hash < cumulative:
                return test.variant
        
        return None
    
    def get_weights(self, variant: Optional[AlgorithmVariant] = None) -> Dict[str, float]:
        """Get scoring weights for a variant."""
        if variant is None or variant == AlgorithmVariant.CONTROL:
            return self.VARIANT_CONFIGS[AlgorithmVariant.CONTROL]
        
        return self.VARIANT_CONFIGS.get(variant, self.VARIANT_CONFIGS[AlgorithmVariant.CONTROL])
    
    def record_result(
        self,
        test_id: str,
        clip_data: Dict[str, Any],
        user_rating: Optional[float] = None,
        actual_performance: Optional[str] = None
    ) -> None:
        """Record a result for a test."""
        if test_id not in self._active_tests:
            return
        
        # Calculate metrics
        virality_score = clip_data.get("virality_score", 0)
        
        # Create or update result
        result = ABTestResult(
            test_id=test_id,
            variant=self._active_tests[test_id].variant,
            total_clips=1,
            avg_virality_score=virality_score,
            user_satisfaction=user_rating or 0,
            actual_performance={actual_performance: 1} if actual_performance else {},
            conversion_rate=0,
            confidence_score=0
        )
        
        self._results[test_id].append(result)
        self._save_state()
    
    def analyze_results(self, test_id: str) -> Dict[str, Any]:
        """Analyze results for a test."""
        if test_id not in self._results:
            return {"error": "Test not found"}
        
        results = self._results[test_id]
        config = self._active_tests[test_id]
        
        if len(results) < config.min_samples:
            return {
                "status": "insufficient_data",
                "samples": len(results),
                "needed": config.min_samples
            }
        
        # Calculate metrics
        avg_virality = sum(r.avg_virality_score for r in results) / len(results)
        avg_satisfaction = sum(r.user_satisfaction for r in results) / len(results)
        
        # Aggregate performance
        performance_counts = {}
        for r in results:
            for perf, count in r.actual_performance.items():
                performance_counts[perf] = performance_counts.get(perf, 0) + count
        
        # Calculate viral rate
        viral_count = performance_counts.get("viral", 0) + performance_counts.get("high", 0)
        viral_rate = (viral_count / len(results)) * 100 if results else 0
        
        # Compare to control (if we have control data)
        control_results = [
            r for r in self._results.get("control", [])
            if datetime.fromisoformat(r.test_id.split("_")[-1]) >= datetime.fromisoformat(config.start_date)
        ]
        
        comparison = None
        if control_results:
            control_avg = sum(r.avg_virality_score for r in control_results) / len(control_results)
            improvement = ((avg_virality - control_avg) / control_avg) * 100
            
            comparison = {
                "control_avg": control_avg,
                "variant_avg": avg_virality,
                "improvement_percent": improvement,
                "is_better": improvement > 5  # 5% threshold
            }
        
        return {
            "test_id": test_id,
            "variant": config.variant.value,
            "samples": len(results),
            "metrics": {
                "avg_virality_score": avg_virality,
                "avg_user_satisfaction": avg_satisfaction,
                "viral_rate": viral_rate,
                "performance_distribution": performance_counts
            },
            "comparison_to_control": comparison,
            "recommendation": self._generate_recommendation(comparison, avg_satisfaction)
        }
    
    def _generate_recommendation(
        self,
        comparison: Optional[Dict[str, Any]],
        satisfaction: float
    ) -> str:
        """Generate a recommendation based on results."""
        if comparison is None:
            return "Need more data for comparison"
        
        if comparison["is_better"] and satisfaction >= 7:
            return f"Variant shows {comparison['improvement_percent']:.1f}% improvement. Consider rolling out."
        elif comparison["is_better"]:
            return f"Good improvement ({comparison['improvement_percent']:.1f}%) but low user satisfaction ({satisfaction:.1f}). Review."
        elif comparison["improvement_percent"] < -10:
            return f"Variant underperforming ({comparison['improvement_percent']:.1f}%). Consider ending test."
        else:
            return "Results inconclusive. Continue testing or adjust variant."
    
    def get_best_variant(self) -> AlgorithmVariant:
        """Determine the best performing variant from completed tests."""
        variant_scores = {}
        
        for test_id, results in self._results.items():
            if not results:
                continue
            
            config = self._active_tests.get(test_id)
            if not config:
                continue
            
            # Only consider completed tests with enough samples
            if len(results) < config.min_samples:
                continue
            
            # Calculate average score
            avg_score = sum(r.avg_virality_score for r in results) / len(results)
            avg_satisfaction = sum(r.user_satisfaction for r in results) / len(results)
            
            # Combined score (weighted)
            combined = (avg_score * 0.6) + (avg_satisfaction * 10 * 0.4)
            
            variant_scores[config.variant] = variant_scores.get(config.variant, []) + [combined]
        
        # Average by variant
        avg_by_variant = {
            v: sum(scores) / len(scores)
            for v, scores in variant_scores.items()
        }
        
        if not avg_by_variant:
            return AlgorithmVariant.CONTROL
        
        return max(avg_by_variant, key=avg_by_variant.get)
    
    def end_test(self, test_id: str) -> Dict[str, Any]:
        """End an A/B test and return final analysis."""
        if test_id not in self._active_tests:
            return {"error": "Test not found"}
        
        # Mark as ended
        self._active_tests[test_id].end_date = datetime.now().isoformat()
        self._save_state()
        
        # Return analysis
        analysis = self.analyze_results(test_id)
        analysis["status"] = "completed"
        
        logger.info(f"A/B test {test_id} ended. Results: {analysis.get('recommendation', 'N/A')}")
        
        return analysis
    
    def get_active_tests(self) -> List[Dict[str, Any]]:
        """Get list of currently active tests."""
        now = datetime.now()
        active = []
        
        for test_id, config in self._active_tests.items():
            if config.end_date is None or datetime.fromisoformat(config.end_date) > now:
                results = self._results.get(test_id, [])
                active.append({
                    "test_id": test_id,
                    "variant": config.variant.value,
                    "start_date": config.start_date,
                    "end_date": config.end_date,
                    "traffic_percentage": config.traffic_percentage,
                    "samples_collected": len(results),
                    "min_samples_needed": config.min_samples
                })
        
        return active


# Global instance
_ab_test_manager: Optional[ViralityABTestManager] = None


def get_ab_test_manager() -> ViralityABTestManager:
    """Get global A/B test manager instance."""
    global _ab_test_manager
    if _ab_test_manager is None:
        _ab_test_manager = ViralityABTestManager()
    return _ab_test_manager


def get_virality_weights(user_id: Optional[str] = None) -> Dict[str, float]:
    """
    Get the appropriate virality weights for a request.
    
    This checks for active A/B tests and returns variant weights if assigned.
    """
    manager = get_ab_test_manager()
    variant = manager.should_use_variant(user_id)
    return manager.get_weights(variant)
