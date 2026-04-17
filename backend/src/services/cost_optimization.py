"""
Cloud Cost Optimization Service
Monitor and optimize cloud infrastructure costs.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class ResourceType(Enum):
    """Types of cloud resources."""
    COMPUTE = "compute"
    STORAGE = "storage"
    BANDWIDTH = "bandwidth"
    AI_INFERENCE = "ai_inference"
    TRANSCODING = "transcoding"
    DATABASE = "database"
    CACHE = "cache"


class CostAlertSeverity(Enum):
    """Cost alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class ResourceUsage:
    """Resource usage metrics."""
    resource_id: str
    resource_type: ResourceType
    usage_amount: float
    unit: str
    cost_usd: float
    timestamp: str
    efficiency_score: float


@dataclass
class CostAlert:
    """Cost optimization alert."""
    alert_id: str
    severity: CostAlertSeverity
    resource_type: ResourceType
    message: str
    current_cost: float
    projected_cost: float
    potential_savings: float
    recommendations: List[str]
    created_at: str


class CostOptimizationService:
    """
    Cloud cost monitoring and optimization.
    """
    
    def __init__(self):
        self._usage_history: List[ResourceUsage] = []
        self._alerts: List[CostAlert] = []
        self._budget_limit: float = 1000.0  # Monthly budget USD
        self._alert_thresholds = {
            "daily": 50.0,
            "weekly": 200.0,
            "monthly": 800.0
        }
        self._resource_rates = {
            ResourceType.COMPUTE: 0.05,      # $0.05 per minute
            ResourceType.STORAGE: 0.023,     # $0.023 per GB/month
            ResourceType.BANDWIDTH: 0.09,  # $0.09 per GB
            ResourceType.AI_INFERENCE: 0.002, # $0.002 per request
            ResourceType.TRANSCODING: 0.015,  # $0.015 per minute
            ResourceType.DATABASE: 0.10,      # $0.10 per hour
            ResourceType.CACHE: 0.05          # $0.05 per GB/month
        }
    
    async def track_usage(
        self,
        resource_type: ResourceType,
        usage_amount: float,
        unit: str,
        resource_id: str = "default"
    ) -> ResourceUsage:
        """Track resource usage and calculate cost."""
        # Calculate cost based on resource type
        rate = self._resource_rates.get(resource_type, 0.01)
        cost = usage_amount * rate
        
        # Calculate efficiency score
        efficiency = await self._calculate_efficiency(resource_type, usage_amount, cost)
        
        usage = ResourceUsage(
            resource_id=resource_id,
            resource_type=resource_type,
            usage_amount=usage_amount,
            unit=unit,
            cost_usd=cost,
            timestamp=datetime.now().isoformat(),
            efficiency_score=efficiency
        )
        
        self._usage_history.append(usage)
        
        # Check for cost alerts
        await self._check_cost_thresholds()
        
        return usage
    
    async def _calculate_efficiency(
        self,
        resource_type: ResourceType,
        usage: float,
        cost: float
    ) -> float:
        """Calculate resource efficiency score."""
        # Base efficiency on utilization vs cost
        if resource_type == ResourceType.COMPUTE:
            # Higher efficiency for higher utilization
            return min(1.0, usage / 100)  # Assuming 100 units is full utilization
        elif resource_type == ResourceType.STORAGE:
            # Check for old/unused files
            return 0.8 if usage < 1000 else 0.6  # Penalize large storage
        else:
            return 0.75  # Default efficiency
    
    async def _check_cost_thresholds(self):
        """Check if cost thresholds are exceeded."""
        now = datetime.now()
        
        # Check daily spend
        daily_spend = self._calculate_period_cost(timedelta(days=1))
        if daily_spend > self._alert_thresholds["daily"]:
            await self._create_alert(
                CostAlertSeverity.WARNING,
                ResourceType.COMPUTE,
                f"Daily spend (${daily_spend:.2f}) exceeds threshold",
                daily_spend,
                daily_spend * 30  # Projected monthly
            )
        
        # Check monthly projection
        monthly_spend = self._calculate_period_cost(timedelta(days=30))
        if monthly_spend > self._budget_limit * 0.8:
            await self._create_alert(
                CostAlertSeverity.CRITICAL if monthly_spend > self._budget_limit else CostAlertSeverity.WARNING,
                ResourceType.COMPUTE,
                f"Monthly spend approaching budget limit",
                monthly_spend,
                monthly_spend
            )
    
    def _calculate_period_cost(self, period: timedelta) -> float:
        """Calculate total cost for a time period."""
        cutoff = datetime.now() - period
        total = sum(
            u.cost_usd for u in self._usage_history
            if datetime.fromisoformat(u.timestamp) > cutoff
        )
        return total
    
    async def _create_alert(
        self,
        severity: CostAlertSeverity,
        resource_type: ResourceType,
        message: str,
        current_cost: float,
        projected_cost: float
    ):
        """Create cost optimization alert."""
        import uuid
        
        # Generate recommendations
        recommendations = await self._generate_recommendations(resource_type)
        
        potential_savings = projected_cost - current_cost
        
        alert = CostAlert(
            alert_id=str(uuid.uuid4()),
            severity=severity,
            resource_type=resource_type,
            message=message,
            current_cost=current_cost,
            projected_cost=projected_cost,
            potential_savings=potential_savings,
            recommendations=recommendations,
            created_at=datetime.now().isoformat()
        )
        
        self._alerts.append(alert)
        logger.warning(f"Cost alert: {message} (Severity: {severity.value})")
    
    async def _generate_recommendations(
        self,
        resource_type: ResourceType
    ) -> List[str]:
        """Generate cost optimization recommendations."""
        recommendations = []
        
        if resource_type == ResourceType.COMPUTE:
            recommendations.extend([
                "Consider using spot instances for non-critical workloads",
                "Enable auto-scaling to match demand",
                "Review idle instances and terminate if not needed"
            ])
        elif resource_type == ResourceType.STORAGE:
            recommendations.extend([
                "Move infrequently accessed data to cold storage",
                "Enable lifecycle policies for automatic tiering",
                "Delete old temporary files and logs"
            ])
        elif resource_type == ResourceType.BANDWIDTH:
            recommendations.extend([
                "Enable CDN caching to reduce origin requests",
                "Compress assets before transfer",
                "Use regional storage for frequently accessed content"
            ])
        elif resource_type == ResourceType.AI_INFERENCE:
            recommendations.extend([
                "Batch requests to improve throughput",
                "Use model quantization to reduce compute",
                "Cache frequent inference results"
            ])
        
        return recommendations
    
    def get_cost_summary(self, days: int = 30) -> Dict[str, Any]:
        """Get cost summary for period."""
        cutoff = datetime.now() - timedelta(days=days)
        period_usage = [
            u for u in self._usage_history
            if datetime.fromisoformat(u.timestamp) > cutoff
        ]
        
        if not period_usage:
            return {"total_cost": 0, "by_resource": {}}
        
        total_cost = sum(u.cost_usd for u in period_usage)
        
        by_resource = {}
        for usage in period_usage:
            rt = usage.resource_type.value
            if rt not in by_resource:
                by_resource[rt] = {"cost": 0, "usage": 0}
            by_resource[rt]["cost"] += usage.cost_usd
            by_resource[rt]["usage"] += usage.usage_amount
        
        # Calculate trends
        daily_costs = {}
        for usage in period_usage:
            day = datetime.fromisoformat(usage.timestamp).strftime("%Y-%m-%d")
            daily_costs[day] = daily_costs.get(day, 0) + usage.cost_usd
        
        avg_daily = sum(daily_costs.values()) / len(daily_costs) if daily_costs else 0
        projected_monthly = avg_daily * 30
        
        return {
            "period_days": days,
            "total_cost_usd": round(total_cost, 2),
            "by_resource": by_resource,
            "average_daily_cost": round(avg_daily, 2),
            "projected_monthly_cost": round(projected_monthly, 2),
            "budget_limit": self._budget_limit,
            "budget_utilization": (projected_monthly / self._budget_limit * 100) if self._budget_limit else 0,
            "alerts_count": len(self._alerts)
        }
    
    def get_alerts(
        self,
        severity: Optional[CostAlertSeverity] = None,
        resource_type: Optional[ResourceType] = None
    ) -> List[Dict[str, Any]]:
        """Get cost alerts with optional filtering."""
        alerts = self._alerts
        
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        
        if resource_type:
            alerts = [a for a in alerts if a.resource_type == resource_type]
        
        return [
            {
                "alert_id": a.alert_id,
                "severity": a.severity.value,
                "resource_type": a.resource_type.value,
                "message": a.message,
                "current_cost": a.current_cost,
                "projected_cost": a.projected_cost,
                "potential_savings": a.potential_savings,
                "recommendations": a.recommendations,
                "created_at": a.created_at
            }
            for a in sorted(alerts, key=lambda x: x.created_at, reverse=True)
        ]
    
    async def optimize_resources(self) -> Dict[str, Any]:
        """Run resource optimization analysis."""
        optimizations = []
        
        # Analyze storage
        storage_usage = [
            u for u in self._usage_history
            if u.resource_type == ResourceType.STORAGE
        ]
        if storage_usage:
            total_storage = sum(u.usage_amount for u in storage_usage)
            if total_storage > 1000:  # More than 1TB
                optimizations.append({
                    "resource_type": "storage",
                    "action": "archive_old_files",
                    "potential_savings": total_storage * 0.023 * 0.5,  # 50% savings
                    "description": f"Archive {total_storage * 0.3:.0f} GB of old data"
                })
        
        # Analyze compute
        compute_usage = [
            u for u in self._usage_history
            if u.resource_type == ResourceType.COMPUTE
        ]
        if compute_usage:
            avg_efficiency = sum(u.efficiency_score for u in compute_usage) / len(compute_usage)
            if avg_efficiency < 0.5:
                optimizations.append({
                    "resource_type": "compute",
                    "action": "rightsize_instances",
                    "potential_savings": sum(u.cost_usd for u in compute_usage) * 0.3,
                    "description": "Downsize underutilized instances"
                })
        
        total_savings = sum(opt["potential_savings"] for opt in optimizations)
        
        return {
            "optimizations_found": len(optimizations),
            "total_potential_savings_usd": round(total_savings, 2),
            "recommendations": optimizations,
            "timestamp": datetime.now().isoformat()
        }
    
    def set_budget(self, monthly_budget_usd: float):
        """Set monthly budget limit."""
        self._budget_limit = monthly_budget_usd
        logger.info(f"Budget set to ${monthly_budget_usd:.2f}/month")


# Global instance
_cost_service: Optional[CostOptimizationService] = None


def get_cost_optimization_service() -> CostOptimizationService:
    """Get global cost optimization service."""
    global _cost_service
    if _cost_service is None:
        _cost_service = CostOptimizationService()
    return _cost_service
