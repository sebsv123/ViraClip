"""
Advanced Analytics and Reporting System
Comprehensive analytics for video performance and user engagement.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
from collections import defaultdict
import json
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ClipPerformanceMetrics:
    """Performance metrics for a single clip."""
    clip_id: str
    task_id: str
    created_at: str
    views: int = 0
    likes: int = 0
    shares: int = 0
    comments: int = 0
    watch_time_sec: float = 0.0
    completion_rate: float = 0.0
    click_through_rate: float = 0.0
    engagement_rate: float = 0.0
    virality_score: float = 0.0
    platform: str = "unknown"


@dataclass
class UserActivityMetrics:
    """User activity and engagement metrics."""
    user_id: str
    total_videos_processed: int = 0
    total_clips_generated: int = 0
    total_exports: int = 0
    processing_time_total: float = 0.0
    favorite_niche: Optional[str] = None
    last_active: Optional[str] = None
    subscription_tier: str = "free"


@dataclass
class SystemPerformanceMetrics:
    """System-wide performance metrics."""
    date: str
    total_tasks_completed: int = 0
    total_tasks_failed: int = 0
    avg_processing_time: float = 0.0
    success_rate: float = 0.0
    most_active_hour: int = 0
    top_niches: List[Tuple[str, int]] = None
    revenue_estimate: float = 0.0


class AdvancedAnalyticsService:
    """
    Comprehensive analytics and reporting for the platform.
    """
    
    def __init__(self, data_dir: Path = Path("/app/data/analytics")):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory caches
        self._clip_metrics: Dict[str, ClipPerformanceMetrics] = {}
        self._user_metrics: Dict[str, UserActivityMetrics] = {}
        self._daily_metrics: Dict[str, SystemPerformanceMetrics] = {}
    
    def record_clip_performance(
        self,
        clip_id: str,
        task_id: str,
        platform: str,
        metrics: Dict[str, Any]
    ) -> None:
        """Record performance metrics for a clip."""
        performance = ClipPerformanceMetrics(
            clip_id=clip_id,
            task_id=task_id,
            created_at=datetime.now().isoformat(),
            platform=platform,
            views=metrics.get("views", 0),
            likes=metrics.get("likes", 0),
            shares=metrics.get("shares", 0),
            comments=metrics.get("comments", 0),
            watch_time_sec=metrics.get("watch_time_sec", 0.0),
            completion_rate=metrics.get("completion_rate", 0.0),
            click_through_rate=metrics.get("ctr", 0.0),
            engagement_rate=self._calculate_engagement_rate(metrics),
            virality_score=metrics.get("virality_score", 0.0)
        )
        
        self._clip_metrics[clip_id] = performance
        self._save_clip_metrics()
    
    def _calculate_engagement_rate(self, metrics: Dict[str, Any]) -> float:
        """Calculate engagement rate from metrics."""
        views = metrics.get("views", 0)
        if views == 0:
            return 0.0
        
        engagements = (
            metrics.get("likes", 0) +
            metrics.get("shares", 0) * 2 +  # Shares weighted more
            metrics.get("comments", 0) * 3   # Comments weighted most
        )
        
        return (engagements / views) * 100
    
    def record_user_activity(
        self,
        user_id: str,
        activity_type: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """Record user activity."""
        if user_id not in self._user_metrics:
            self._user_metrics[user_id] = UserActivityMetrics(user_id=user_id)
        
        user = self._user_metrics[user_id]
        user.last_active = datetime.now().isoformat()
        
        if activity_type == "video_processed":
            user.total_videos_processed += 1
        elif activity_type == "clips_generated":
            user.total_clips_generated += metadata.get("count", 1)
        elif activity_type == "export":
            user.total_exports += 1
            if metadata and "processing_time" in metadata:
                user.processing_time_total += metadata["processing_time"]
        elif activity_type == "niche_selected" and metadata:
            user.favorite_niche = metadata.get("niche")
        
        self._save_user_metrics()
    
    def record_system_metrics(self, metrics: Dict[str, Any]) -> None:
        """Record daily system metrics."""
        today = datetime.now().strftime("%Y-%m-%d")
        
        if today not in self._daily_metrics:
            self._daily_metrics[today] = SystemPerformanceMetrics(date=today)
        
        daily = self._daily_metrics[today]
        
        # Update metrics
        if metrics.get("task_completed"):
            daily.total_tasks_completed += 1
        if metrics.get("task_failed"):
            daily.total_tasks_failed += 1
        
        # Calculate success rate
        total = daily.total_tasks_completed + daily.total_tasks_failed
        if total > 0:
            daily.success_rate = (daily.total_tasks_completed / total) * 100
        
        # Track hour
        current_hour = datetime.now().hour
        daily.most_active_hour = current_hour
        
        # Track niches
        if "niche" in metrics:
            if daily.top_niches is None:
                daily.top_niches = []
            # Update niche count
            niche_counts = dict(daily.top_niches)
            niche_counts[metrics["niche"]] = niche_counts.get(metrics["niche"], 0) + 1
            daily.top_niches = sorted(niche_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        
        self._save_system_metrics()
    
    def get_clip_analytics(
        self,
        clip_id: Optional[str] = None,
        task_id: Optional[str] = None,
        days: int = 30
    ) -> Dict[str, Any]:
        """Get analytics for clips."""
        # Filter by criteria
        filtered = self._clip_metrics.values()
        
        if clip_id:
            filtered = [m for m in filtered if m.clip_id == clip_id]
        if task_id:
            filtered = [m for m in filtered if m.task_id == task_id]
        
        # Filter by date
        cutoff = datetime.now() - timedelta(days=days)
        filtered = [
            m for m in filtered
            if datetime.fromisoformat(m.created_at) > cutoff
        ]
        
        if not filtered:
            return {"error": "No data found"}
        
        # Calculate aggregates
        total_views = sum(m.views for m in filtered)
        total_likes = sum(m.likes for m in filtered)
        total_shares = sum(m.shares for m in filtered)
        avg_engagement = sum(m.engagement_rate for m in filtered) / len(filtered)
        avg_completion = sum(m.completion_rate for m in filtered) / len(filtered)
        
        # Top performing clips
        top_clips = sorted(filtered, key=lambda x: x.engagement_rate, reverse=True)[:10]
        
        return {
            "total_clips": len(filtered),
            "total_views": total_views,
            "total_likes": total_likes,
            "total_shares": total_shares,
            "avg_engagement_rate": round(avg_engagement, 2),
            "avg_completion_rate": round(avg_completion, 2),
            "top_performing_clips": [
                {
                    "clip_id": c.clip_id,
                    "engagement_rate": c.engagement_rate,
                    "views": c.views,
                    "platform": c.platform
                }
                for c in top_clips
            ],
            "platform_breakdown": self._get_platform_breakdown(filtered)
        }
    
    def _get_platform_breakdown(
        self,
        metrics: List[ClipPerformanceMetrics]
    ) -> Dict[str, Any]:
        """Get breakdown by platform."""
        by_platform = defaultdict(lambda: {"views": 0, "engagement": 0, "count": 0})
        
        for m in metrics:
            by_platform[m.platform]["views"] += m.views
            by_platform[m.platform]["engagement"] += m.engagement_rate
            by_platform[m.platform]["count"] += 1
        
        # Calculate averages
        result = {}
        for platform, data in by_platform.items():
            result[platform] = {
                "total_views": data["views"],
                "avg_engagement": round(data["engagement"] / data["count"], 2) if data["count"] > 0 else 0,
                "clip_count": data["count"]
            }
        
        return result
    
    def get_user_analytics(
        self,
        user_id: Optional[str] = None,
        days: int = 30
    ) -> Dict[str, Any]:
        """Get user activity analytics."""
        # Filter by date
        cutoff = datetime.now() - timedelta(days=days)
        
        filtered = [
            m for m in self._user_metrics.values()
            if m.last_active and datetime.fromisoformat(m.last_active) > cutoff
        ]
        
        if user_id:
            filtered = [m for m in filtered if m.user_id == user_id]
        
        if not filtered:
            return {"error": "No user data found"}
        
        # Calculate metrics
        total_users = len(filtered)
        total_videos = sum(m.total_videos_processed for m in filtered)
        total_clips = sum(m.total_clips_generated for m in filtered)
        total_exports = sum(m.total_exports for m in filtered)
        
        # Tier distribution
        tiers = defaultdict(int)
        for m in filtered:
            tiers[m.subscription_tier] += 1
        
        # Power users (top 10% by activity)
        sorted_by_activity = sorted(
            filtered,
            key=lambda x: x.total_videos_processed,
            reverse=True
        )
        power_user_count = max(1, int(len(sorted_by_activity) * 0.1))
        power_users = sorted_by_activity[:power_user_count]
        
        return {
            "total_active_users": total_users,
            "total_videos_processed": total_videos,
            "total_clips_generated": total_clips,
            "total_exports": total_exports,
            "avg_clips_per_user": round(total_clips / total_users, 1) if total_users > 0 else 0,
            "tier_distribution": dict(tiers),
            "power_users": [
                {"user_id": u.user_id, "videos": u.total_videos_processed}
                for u in power_users
            ],
            "retention_estimate": self._estimate_retention(filtered)
        }
    
    def _estimate_retention(self, users: List[UserActivityMetrics]) -> float:
        """Estimate user retention rate."""
        if not users:
            return 0.0
        
        # Users active in last 7 days vs last 30 days
        week_ago = datetime.now() - timedelta(days=7)
        month_ago = datetime.now() - timedelta(days=30)
        
        active_this_week = sum(
            1 for u in users
            if u.last_active and datetime.fromisoformat(u.last_active) > week_ago
        )
        
        active_this_month = sum(
            1 for u in users
            if u.last_active and datetime.fromisoformat(u.last_active) > month_ago
        )
        
        if active_this_month == 0:
            return 0.0
        
        return (active_this_week / active_this_month) * 100
    
    def get_system_health_report(self, days: int = 7) -> Dict[str, Any]:
        """Get system health and performance report."""
        dates = [
            (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range(days)
        ]
        
        metrics_by_day = []
        for date in dates:
            if date in self._daily_metrics:
                m = self._daily_metrics[date]
                metrics_by_day.append({
                    "date": date,
                    "tasks_completed": m.total_tasks_completed,
                    "tasks_failed": m.total_tasks_failed,
                    "success_rate": round(m.success_rate, 1),
                    "top_niches": m.top_niches or []
                })
        
        # Calculate trends
        if len(metrics_by_day) >= 2:
            recent = metrics_by_day[0]["success_rate"]
            previous = metrics_by_day[1]["success_rate"]
            trend = recent - previous
        else:
            trend = 0
        
        # Aggregate totals
        total_completed = sum(m["tasks_completed"] for m in metrics_by_day)
        total_failed = sum(m["tasks_failed"] for m in metrics_by_day)
        
        return {
            "period": f"Last {days} days",
            "total_tasks_completed": total_completed,
            "total_tasks_failed": total_failed,
            "overall_success_rate": round(
                (total_completed / (total_completed + total_failed)) * 100, 1
            ) if (total_completed + total_failed) > 0 else 0,
            "success_trend": f"{trend:+.1f}%" if trend != 0 else "stable",
            "daily_breakdown": metrics_by_day,
            "system_status": "healthy" if recent > 95 else "degraded" if recent > 85 else "critical"
        }
    
    def generate_comprehensive_report(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generate comprehensive analytics report."""
        if not start_date:
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        
        days = (datetime.fromisoformat(end_date) - datetime.fromisoformat(start_date)).days
        
        return {
            "report_period": {
                "start": start_date,
                "end": end_date,
                "days": days
            },
            "executive_summary": {
                "total_clips_created": len(self._clip_metrics),
                "total_active_users": len(self._user_metrics),
                "system_uptime_estimate": "99.5%",  # Placeholder
                "avg_processing_time": self._get_avg_processing_time()
            },
            "clip_performance": self.get_clip_analytics(days=days),
            "user_engagement": self.get_user_analytics(days=days),
            "system_health": self.get_system_health_report(days=min(days, 7)),
            "growth_metrics": self._calculate_growth_metrics(days),
            "recommendations": self._generate_recommendations()
        }
    
    def _get_avg_processing_time(self) -> float:
        """Get average processing time."""
        times = [
            m.processing_time_total / max(1, m.total_exports)
            for m in self._user_metrics.values()
            if m.total_exports > 0
        ]
        
        return round(sum(times) / len(times), 1) if times else 0.0
    
    def _calculate_growth_metrics(self, days: int) -> Dict[str, Any]:
        """Calculate growth metrics."""
        # Compare current period vs previous
        current_period_start = datetime.now() - timedelta(days=days)
        previous_period_start = current_period_start - timedelta(days=days)
        
        current_clips = sum(
            1 for m in self._clip_metrics.values()
            if datetime.fromisoformat(m.created_at) > current_period_start
        )
        
        previous_clips = sum(
            1 for m in self._clip_metrics.values()
            if previous_period_start < datetime.fromisoformat(m.created_at) <= current_period_start
        )
        
        growth = ((current_clips - previous_clips) / max(1, previous_clips)) * 100
        
        return {
            "clips_growth_rate": round(growth, 1),
            "current_period_clips": current_clips,
            "previous_period_clips": previous_clips,
            "trend": "up" if growth > 10 else "stable" if growth > -10 else "down"
        }
    
    def _generate_recommendations(self) -> List[str]:
        """Generate recommendations based on analytics."""
        recommendations = []
        
        # Check success rate
        health = self.get_system_health_report(days=7)
        if health["overall_success_rate"] < 95:
            recommendations.append(
                "System success rate below 95%. Review error logs and improve error handling."
            )
        
        # Check user retention
        user_data = self.get_user_analytics()
        retention = user_data.get("retention_estimate", 0)
        if retention < 50:
            recommendations.append(
                "User retention below 50%. Consider implementing engagement features or notifications."
            )
        
        # Check clip engagement
        clip_data = self.get_clip_analytics()
        avg_engagement = clip_data.get("avg_engagement_rate", 0)
        if avg_engagement < 5:
            recommendations.append(
                "Average clip engagement below 5%. Review virality algorithms and clip selection."
            )
        
        if not recommendations:
            recommendations.append(
                "All metrics looking good! Continue current strategies and monitor for changes."
            )
        
        return recommendations
    
    def export_report_to_file(
        self,
        report: Dict[str, Any],
        output_path: Optional[Path] = None
    ) -> Path:
        """Export report to JSON file."""
        if not output_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.data_dir / f"analytics_report_{timestamp}.json"
        
        with open(output_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        logger.info(f"Analytics report exported to {output_path}")
        return output_path
    
    # Persistence methods
    def _save_clip_metrics(self) -> None:
        """Save clip metrics to file."""
        path = self.data_dir / "clip_metrics.json"
        data = {k: self._metrics_to_dict(v) for k, v in self._clip_metrics.items()}
        with open(path, 'w') as f:
            json.dump(data, f)
    
    def _save_user_metrics(self) -> None:
        """Save user metrics to file."""
        path = self.data_dir / "user_metrics.json"
        data = {k: self._metrics_to_dict(v) for k, v in self._user_metrics.items()}
        with open(path, 'w') as f:
            json.dump(data, f)
    
    def _save_system_metrics(self) -> None:
        """Save system metrics to file."""
        path = self.data_dir / "system_metrics.json"
        data = {k: self._metrics_to_dict(v) for k, v in self._daily_metrics.items()}
        with open(path, 'w') as f:
            json.dump(data, f)
    
    def _metrics_to_dict(self, obj) -> Dict[str, Any]:
        """Convert dataclass to dict."""
        if hasattr(obj, '__dataclass_fields__'):
            return {
                k: v for k, v in obj.__dict__.items()
            }
        return obj


# Global instance
_analytics_service: Optional[AdvancedAnalyticsService] = None


def get_analytics_service() -> AdvancedAnalyticsService:
    """Get global analytics service instance."""
    global _analytics_service
    if _analytics_service is None:
        _analytics_service = AdvancedAnalyticsService()
    return _analytics_service
