"""
A/B Testing System for UI/UX
Experiment framework for testing UI variations and measuring user engagement.
"""

import logging
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
import json
import hashlib

logger = logging.getLogger(__name__)


class ExperimentStatus(Enum):
    """Experiment lifecycle states."""
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ExperimentType(Enum):
    """Types of experiments."""
    UI_VARIANT = "ui_variant"           # Different UI layouts
    FEATURE_FLAG = "feature_flag"     # Feature on/off
    ALGORITHM = "algorithm"            # Algorithm changes
    CONTENT = "content"                # Content variations
    PRICING = "pricing"              # Pricing tests


@dataclass
class ExperimentVariant:
    """A single experiment variant."""
    variant_id: str
    name: str
    description: str
    config: Dict[str, Any]
    traffic_percentage: float  # 0-100
    user_count: int = 0
    conversion_count: int = 0
    engagement_score: float = 0.0


@dataclass
class ExperimentMetric:
    """Metric definition for experiments."""
    metric_id: str
    name: str
    metric_type: str  # conversion, engagement, retention, revenue
    description: str
    success_criteria: str  # e.g., "> 5%"
    baseline_value: float


@dataclass
class Experiment:
    """A/B experiment definition."""
    experiment_id: str
    name: str
    description: str
    experiment_type: ExperimentType
    status: ExperimentStatus
    created_by: str
    created_at: str
    start_date: Optional[str]
    end_date: Optional[str]
    variants: List[ExperimentVariant]
    metrics: List[ExperimentMetric]
    target_audience: Dict[str, Any]
    traffic_allocation: float  # Percentage of total traffic
    min_sample_size: int
    confidence_level: float


class ABTestManager:
    """
    A/B testing system for UI/UX experiments.
    """
    
    def __init__(self, storage_path: Path = Path("/app/data/ab_tests")):
        self.storage_path = storage_path
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        self._experiments: Dict[str, Experiment] = {}
        self._user_assignments: Dict[str, Dict[str, str]] = {}  # user_id -> {experiment_id: variant_id}
        self._events: List[Dict[str, Any]] = []
        
        # Load existing experiments
        self._load_experiments()
    
    def _load_experiments(self) -> None:
        """Load experiments from storage."""
        try:
            experiments_file = self.storage_path / "experiments.json"
            if experiments_file.exists():
                with open(experiments_file, 'r') as f:
                    data = json.load(f)
                    for exp_data in data:
                        experiment = self._dict_to_experiment(exp_data)
                        self._experiments[experiment.experiment_id] = experiment
        except Exception as e:
            logger.warning(f"Failed to load experiments: {e}")
    
    def _save_experiments(self) -> None:
        """Save experiments to storage."""
        try:
            experiments_file = self.storage_path / "experiments.json"
            data = [self._experiment_to_dict(exp) for exp in self._experiments.values()]
            with open(experiments_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save experiments: {e}")
    
    def create_experiment(
        self,
        name: str,
        description: str,
        experiment_type: ExperimentType,
        created_by: str,
        variants: List[Dict[str, Any]],
        metrics: List[Dict[str, Any]],
        traffic_allocation: float = 100.0,
        target_audience: Optional[Dict[str, Any]] = None
    ) -> Experiment:
        """Create a new A/B experiment."""
        import uuid
        
        experiment_id = str(uuid.uuid4())
        
        # Create variants
        experiment_variants = []
        total_traffic = 0
        
        for i, var_data in enumerate(variants):
            variant = ExperimentVariant(
                variant_id=str(uuid.uuid4()),
                name=var_data.get("name", f"Variant {i+1}"),
                description=var_data.get("description", ""),
                config=var_data.get("config", {}),
                traffic_percentage=var_data.get("traffic_percentage", 100.0 / len(variants))
            )
            experiment_variants.append(variant)
            total_traffic += variant.traffic_percentage
        
        # Normalize traffic percentages
        if total_traffic != 100:
            factor = 100 / total_traffic
            for variant in experiment_variants:
                variant.traffic_percentage *= factor
        
        # Create metrics
        experiment_metrics = []
        for met_data in metrics:
            metric = ExperimentMetric(
                metric_id=str(uuid.uuid4()),
                name=met_data.get("name", "Untitled Metric"),
                metric_type=met_data.get("type", "conversion"),
                description=met_data.get("description", ""),
                success_criteria=met_data.get("success_criteria", "> 0%"),
                baseline_value=met_data.get("baseline", 0.0)
            )
            experiment_metrics.append(metric)
        
        experiment = Experiment(
            experiment_id=experiment_id,
            name=name,
            description=description,
            experiment_type=experiment_type,
            status=ExperimentStatus.DRAFT,
            created_by=created_by,
            created_at=datetime.now().isoformat(),
            start_date=None,
            end_date=None,
            variants=experiment_variants,
            metrics=experiment_metrics,
            target_audience=target_audience or {},
            traffic_allocation=traffic_allocation,
            min_sample_size=100,
            confidence_level=0.95
        )
        
        self._experiments[experiment_id] = experiment
        self._save_experiments()
        
        logger.info(f"Created experiment: {name} ({experiment_id})")
        return experiment
    
    def start_experiment(self, experiment_id: str) -> bool:
        """Start a draft experiment."""
        if experiment_id not in self._experiments:
            return False
        
        experiment = self._experiments[experiment_id]
        
        if experiment.status != ExperimentStatus.DRAFT:
            return False
        
        experiment.status = ExperimentStatus.RUNNING
        experiment.start_date = datetime.now().isoformat()
        
        # Calculate end date (default 2 weeks)
        end = datetime.now() + timedelta(weeks=2)
        experiment.end_date = end.isoformat()
        
        self._save_experiments()
        
        logger.info(f"Started experiment: {experiment.name}")
        return True
    
    def assign_variant(self, experiment_id: str, user_id: str) -> Optional[str]:
        """Assign a user to a variant in an experiment."""
        if experiment_id not in self._experiments:
            return None
        
        experiment = self._experiments[experiment_id]
        
        if experiment.status != ExperimentStatus.RUNNING:
            return None
        
        # Check if user already assigned
        if user_id in self._user_assignments:
            if experiment_id in self._user_assignments[user_id]:
                return self._user_assignments[user_id][experiment_id]
        
        # Assign based on hash for consistency
        hash_input = f"{experiment_id}:{user_id}"
        hash_value = int(hashlib.md5(hash_input.encode()).hexdigest(), 16)
        
        # Determine variant based on traffic percentages
        assignment = hash_value % 100
        cumulative = 0
        
        for variant in experiment.variants:
            cumulative += variant.traffic_percentage
            if assignment < cumulative:
                # Assign user
                if user_id not in self._user_assignments:
                    self._user_assignments[user_id] = {}
                
                self._user_assignments[user_id][experiment_id] = variant.variant_id
                variant.user_count += 1
                
                return variant.variant_id
        
        # Default to first variant
        return experiment.variants[0].variant_id if experiment.variants else None
    
    def get_variant_config(
        self,
        experiment_id: str,
        user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get configuration for user's assigned variant."""
        variant_id = self.assign_variant(experiment_id, user_id)
        
        if not variant_id:
            return None
        
        experiment = self._experiments.get(experiment_id)
        if not experiment:
            return None
        
        # Find variant
        for variant in experiment.variants:
            if variant.variant_id == variant_id:
                return variant.config
        
        return None
    
    def record_event(
        self,
        experiment_id: str,
        user_id: str,
        event_type: str,
        event_data: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Record an event for experiment analysis."""
        if experiment_id not in self._experiments:
            return False
        
        experiment = self._experiments[experiment_id]
        
        if experiment.status != ExperimentStatus.RUNNING:
            return False
        
        # Get user's variant
        variant_id = None
        if user_id in self._user_assignments:
            variant_id = self._user_assignments[user_id].get(experiment_id)
        
        event = {
            "timestamp": datetime.now().isoformat(),
            "experiment_id": experiment_id,
            "variant_id": variant_id,
            "user_id": user_id,
            "event_type": event_type,
            "event_data": event_data or {}
        }
        
        self._events.append(event)
        
        # Update variant metrics if conversion
        if variant_id and event_type == "conversion":
            for variant in experiment.variants:
                if variant.variant_id == variant_id:
                    variant.conversion_count += 1
                    break
        
        return True
    
    def get_experiment_results(self, experiment_id: str) -> Optional[Dict[str, Any]]:
        """Get results and statistics for an experiment."""
        if experiment_id not in self._experiments:
            return None
        
        experiment = self._experiments[experiment_id]
        
        # Calculate statistics for each variant
        variant_stats = []
        
        for variant in experiment.variants:
            if variant.user_count > 0:
                conversion_rate = variant.conversion_count / variant.user_count
            else:
                conversion_rate = 0
            
            stats = {
                "variant_id": variant.variant_id,
                "name": variant.name,
                "users": variant.user_count,
                "conversions": variant.conversion_count,
                "conversion_rate": conversion_rate,
                "engagement_score": variant.engagement_score
            }
            variant_stats.append(stats)
        
        # Determine winner
        winner = None
        if len(variant_stats) >= 2:
            winner = max(variant_stats, key=lambda x: x["conversion_rate"])
        
        return {
            "experiment_id": experiment_id,
            "name": experiment.name,
            "status": experiment.status.value,
            "started_at": experiment.start_date,
            "ended_at": experiment.end_date,
            "total_users": sum(v.user_count for v in experiment.variants),
            "variants": variant_stats,
            "winner": winner,
            "events_recorded": len([e for e in self._events if e["experiment_id"] == experiment_id])
        }
    
    def pause_experiment(self, experiment_id: str) -> bool:
        """Pause a running experiment."""
        if experiment_id not in self._experiments:
            return False
        
        experiment = self._experiments[experiment_id]
        
        if experiment.status != ExperimentStatus.RUNNING:
            return False
        
        experiment.status = ExperimentStatus.PAUSED
        self._save_experiments()
        
        logger.info(f"Paused experiment: {experiment.name}")
        return True
    
    def complete_experiment(self, experiment_id: str) -> bool:
        """Mark experiment as completed."""
        if experiment_id not in self._experiments:
            return False
        
        experiment = self._experiments[experiment_id]
        
        experiment.status = ExperimentStatus.COMPLETED
        experiment.end_date = datetime.now().isoformat()
        
        self._save_experiments()
        
        logger.info(f"Completed experiment: {experiment.name}")
        return True
    
    def list_experiments(
        self,
        status: Optional[ExperimentStatus] = None,
        experiment_type: Optional[ExperimentType] = None
    ) -> List[Dict[str, Any]]:
        """List experiments with optional filtering."""
        experiments = self._experiments.values()
        
        if status:
            experiments = [e for e in experiments if e.status == status]
        
        if experiment_type:
            experiments = [e for e in experiments if e.experiment_type == experiment_type]
        
        return [
            {
                "experiment_id": e.experiment_id,
                "name": e.name,
                "type": e.experiment_type.value,
                "status": e.status.value,
                "variants_count": len(e.variants),
                "traffic_allocation": e.traffic_allocation,
                "created_at": e.created_at
            }
            for e in sorted(experiments, key=lambda x: x.created_at, reverse=True)
        ]
    
    def get_active_experiments_for_user(
        self,
        user_id: str,
        experiment_type: Optional[ExperimentType] = None
    ) -> List[Dict[str, Any]]:
        """Get active experiments and user's assigned variants."""
        active = [
            e for e in self._experiments.values()
            if e.status == ExperimentStatus.RUNNING
        ]
        
        if experiment_type:
            active = [e for e in active if e.experiment_type == experiment_type]
        
        result = []
        for exp in active:
            variant_id = self.assign_variant(exp.experiment_id, user_id)
            config = None
            
            if variant_id:
                for var in exp.variants:
                    if var.variant_id == variant_id:
                        config = var.config
                        break
            
            result.append({
                "experiment_id": exp.experiment_id,
                "name": exp.name,
                "variant_id": variant_id,
                "config": config
            })
        
        return result
    
    def _experiment_to_dict(self, experiment: Experiment) -> Dict[str, Any]:
        """Convert experiment to dictionary."""
        return {
            "experiment_id": experiment.experiment_id,
            "name": experiment.name,
            "description": experiment.description,
            "experiment_type": experiment.experiment_type.value,
            "status": experiment.status.value,
            "created_by": experiment.created_by,
            "created_at": experiment.created_at,
            "start_date": experiment.start_date,
            "end_date": experiment.end_date,
            "variants": [
                {
                    "variant_id": v.variant_id,
                    "name": v.name,
                    "description": v.description,
                    "config": v.config,
                    "traffic_percentage": v.traffic_percentage
                }
                for v in experiment.variants
            ],
            "metrics": [
                {
                    "metric_id": m.metric_id,
                    "name": m.name,
                    "type": m.metric_type,
                    "description": m.description,
                    "success_criteria": m.success_criteria,
                    "baseline": m.baseline_value
                }
                for m in experiment.metrics
            ],
            "target_audience": experiment.target_audience,
            "traffic_allocation": experiment.traffic_allocation,
            "min_sample_size": experiment.min_sample_size,
            "confidence_level": experiment.confidence_level
        }
    
    def _dict_to_experiment(self, data: Dict[str, Any]) -> Experiment:
        """Convert dictionary to experiment."""
        return Experiment(
            experiment_id=data["experiment_id"],
            name=data["name"],
            description=data.get("description", ""),
            experiment_type=ExperimentType(data["experiment_type"]),
            status=ExperimentStatus(data["status"]),
            created_by=data["created_by"],
            created_at=data["created_at"],
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
            variants=[
                ExperimentVariant(
                    variant_id=v["variant_id"],
                    name=v["name"],
                    description=v.get("description", ""),
                    config=v.get("config", {}),
                    traffic_percentage=v["traffic_percentage"]
                )
                for v in data.get("variants", [])
            ],
            metrics=[
                ExperimentMetric(
                    metric_id=m["metric_id"],
                    name=m["name"],
                    metric_type=m["type"],
                    description=m.get("description", ""),
                    success_criteria=m.get("success_criteria", "> 0%"),
                    baseline_value=m.get("baseline", 0.0)
                )
                for m in data.get("metrics", [])
            ],
            target_audience=data.get("target_audience", {}),
            traffic_allocation=data.get("traffic_allocation", 100.0),
            min_sample_size=data.get("min_sample_size", 100),
            confidence_level=data.get("confidence_level", 0.95)
        )


# Global instance
_ab_test_manager: Optional[ABTestManager] = None


def get_ab_test_manager() -> ABTestManager:
    """Get global A/B test manager."""
    global _ab_test_manager
    if _ab_test_manager is None:
        _ab_test_manager = ABTestManager()
    return _ab_test_manager


# Convenience functions
def get_user_experiments(user_id: str) -> List[Dict[str, Any]]:
    """Get active experiments for a user."""
    return get_ab_test_manager().get_active_experiments_for_user(user_id)


def track_experiment_event(experiment_id: str, user_id: str, event_type: str) -> bool:
    """Track an event for an experiment."""
    return get_ab_test_manager().record_event(experiment_id, user_id, event_type)
