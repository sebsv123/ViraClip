"""
Validation Statistics Service

Tracks and analyzes clip validation metrics to identify failure patterns
and provide insights for improving clip quality.
"""

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ValidationStats:
    """Aggregated validation statistics."""
    total_validations: int
    passed: int
    failed: int
    success_rate: float
    common_issues: Dict[str, int]
    common_warnings: Dict[str, int]
    avg_duration_diff: float
    avg_file_size_mb: float


@dataclass
class ValidationFailurePattern:
    """Pattern of validation failures."""
    issue_type: str
    count: int
    percentage: float
    first_seen: str
    last_seen: str
    example_metadata: Dict[str, Any]


class ValidationStatsService:
    """Service for tracking and analyzing validation metrics."""

    def __init__(self, manifest_dir: Optional[Path] = None):
        """
        Initialize validation stats service.
        
        Args:
            manifest_dir: Directory containing validation manifests
                         (defaults to learning_loop manifest directory)
        """
        if manifest_dir is None:
            import os
            dataset_dir = Path(os.getenv("DATASET_DIR", "/app/datasets"))
            self.manifest_dir = dataset_dir / "render_feedback"
        else:
            self.manifest_dir = manifest_dir

    async def get_validation_stats(
        self,
        days: int = 7,
        task_id: Optional[str] = None,
    ) -> ValidationStats:
        """
        Get aggregated validation statistics.
        
        Args:
            days: Number of days to look back
            task_id: Filter by specific task ID
            
        Returns:
            ValidationStats with aggregated metrics
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)
        manifests = await self._load_manifests(since, task_id)
        
        if not manifests:
            return ValidationStats(
                total_validations=0,
                passed=0,
                failed=0,
                success_rate=0.0,
                common_issues={},
                common_warnings={},
                avg_duration_diff=0.0,
                avg_file_size_mb=0.0,
            )
        
        passed = sum(1 for m in manifests if m.get("qa_passed", False))
        failed = len(manifests) - passed
        
        # Aggregate issues
        issue_counts: Dict[str, int] = {}
        warning_counts: Dict[str, int] = {}
        duration_diffs: List[float] = []
        file_sizes: List[float] = []
        
        for manifest in manifests:
            # Count issues
            for issue in manifest.get("qa_issues", []):
                issue_counts[issue] = issue_counts.get(issue, 0) + 1
            
            # Extract metadata if present
            if "validation_warnings" in manifest:
                for warning in manifest["validation_warnings"]:
                    # Normalize warning (extract key part)
                    warning_key = self._normalize_warning(warning)
                    warning_counts[warning_key] = warning_counts.get(warning_key, 0) + 1
            
            # Track duration differences
            if "duration_diff" in manifest:
                duration_diffs.append(manifest["duration_diff"])
            
            # Track file sizes
            if "output_size_bytes" in manifest:
                file_sizes.append(manifest["output_size_bytes"] / (1024 * 1024))  # Convert to MB
        
        # Sort by frequency
        common_issues = dict(sorted(issue_counts.items(), key=lambda x: -x[1])[:10])
        common_warnings = dict(sorted(warning_counts.items(), key=lambda x: -x[1])[:10])
        
        avg_duration_diff = sum(duration_diffs) / len(duration_diffs) if duration_diffs else 0.0
        avg_file_size = sum(file_sizes) / len(file_sizes) if file_sizes else 0.0
        
        return ValidationStats(
            total_validations=len(manifests),
            passed=passed,
            failed=failed,
            success_rate=round(passed / len(manifests) * 100, 2),
            common_issues=common_issues,
            common_warnings=common_warnings,
            avg_duration_diff=round(avg_duration_diff, 3),
            avg_file_size_mb=round(avg_file_size, 2),
        )

    async def get_failure_patterns(
        self,
        days: int = 30,
        min_occurrences: int = 2,
    ) -> List[ValidationFailurePattern]:
        """
        Identify patterns in validation failures.
        
        Args:
            days: Number of days to analyze
            min_occurrences: Minimum occurrences to be considered a pattern
            
        Returns:
            List of failure patterns sorted by frequency
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)
        manifests = await self._load_manifests(since)
        
        # Track issue occurrences with timestamps
        issue_tracker: Dict[str, Dict[str, Any]] = {}
        
        for manifest in manifests:
            if not manifest.get("qa_passed", True):
                timestamp = manifest.get("timestamp", datetime.now(timezone.utc).timestamp())
                timestamp_str = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
                
                for issue in manifest.get("qa_issues", []):
                    if issue not in issue_tracker:
                        issue_tracker[issue] = {
                            "count": 0,
                            "first_seen": timestamp_str,
                            "last_seen": timestamp_str,
                            "example_metadata": {},
                        }
                    
                    issue_tracker[issue]["count"] += 1
                    issue_tracker[issue]["last_seen"] = timestamp_str
                    
                    # Store example metadata
                    if not issue_tracker[issue]["example_metadata"]:
                        issue_tracker[issue]["example_metadata"] = {
                            "task_id": manifest.get("task_id"),
                            "clip_index": manifest.get("clip_index"),
                            "duration": manifest.get("duration_s"),
                            "file_size_bytes": manifest.get("output_size_bytes"),
                        }
        
        # Filter and create patterns
        total_failures = sum(1 for m in manifests if not m.get("qa_passed", True))
        patterns = []
        
        for issue, data in issue_tracker.items():
            if data["count"] >= min_occurrences:
                percentage = round(data["count"] / total_failures * 100, 2) if total_failures > 0 else 0.0
                patterns.append(ValidationFailurePattern(
                    issue_type=issue,
                    count=data["count"],
                    percentage=percentage,
                    first_seen=data["first_seen"],
                    last_seen=data["last_seen"],
                    example_metadata=data["example_metadata"],
                ))
        
        # Sort by count descending
        patterns.sort(key=lambda p: p.count, reverse=True)
        return patterns

    async def get_validation_trend(
        self,
        days: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        Get daily validation success rate trend.
        
        Args:
            days: Number of days to analyze
            
        Returns:
            List of daily stats with date, total, passed, failed, success_rate
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)
        manifests = await self._load_manifests(since)
        
        # Group by day
        daily_stats: Dict[str, Dict[str, int]] = {}
        
        for manifest in manifests:
            timestamp = manifest.get("timestamp", datetime.now(timezone.utc).timestamp())
            date_str = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
            
            if date_str not in daily_stats:
                daily_stats[date_str] = {"total": 0, "passed": 0, "failed": 0}
            
            daily_stats[date_str]["total"] += 1
            if manifest.get("qa_passed", False):
                daily_stats[date_str]["passed"] += 1
            else:
                daily_stats[date_str]["failed"] += 1
        
        # Convert to list and add success rate
        trend = []
        for date_str in sorted(daily_stats.keys()):
            stats = daily_stats[date_str]
            success_rate = round(stats["passed"] / stats["total"] * 100, 2) if stats["total"] > 0 else 0.0
            trend.append({
                "date": date_str,
                "total": stats["total"],
                "passed": stats["passed"],
                "failed": stats["failed"],
                "success_rate": success_rate,
            })
        
        return trend

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _load_manifests(
        self,
        since: datetime,
        task_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Load manifests from filesystem."""
        if not self.manifest_dir.exists():
            return []
        
        manifests = []
        since_ts = since.timestamp()
        
        try:
            for manifest_file in self.manifest_dir.glob("*.json"):
                try:
                    data = json.loads(manifest_file.read_text())
                    
                    # Filter by timestamp
                    if data.get("timestamp", 0) < since_ts:
                        continue
                    
                    # Filter by task_id if specified
                    if task_id and data.get("task_id") != task_id:
                        continue
                    
                    manifests.append(data)
                    
                except Exception as exc:
                    logger.debug(f"Failed to load manifest {manifest_file}: {exc}")
                    continue
        except Exception as exc:
            logger.warning(f"Failed to load manifests from {self.manifest_dir}: {exc}")
        
        return manifests

    def _normalize_warning(self, warning: str) -> str:
        """Normalize warning message to extract key part."""
        # Extract key patterns
        if "bitrate" in warning.lower():
            if "audio" in warning.lower():
                return "Low audio bitrate"
            elif "video" in warning.lower():
                return "Low video bitrate"
        
        if "duration" in warning.lower():
            if "long" in warning.lower():
                return "Duration too long"
            elif "short" in warning.lower():
                return "Duration too short"
        
        if "size" in warning.lower() and "source" in warning.lower():
            return "Output size matches source"
        
        if "audio" in warning.lower() and "stream" in warning.lower():
            return "No audio stream"
        
        # Return first 50 chars if no pattern matched
        return warning[:50]


# ── Singleton ─────────────────────────────────────────────────────────────────

_stats_service: Optional[ValidationStatsService] = None


def get_validation_stats_service() -> ValidationStatsService:
    """Get singleton ValidationStatsService instance."""
    global _stats_service
    if _stats_service is None:
        _stats_service = ValidationStatsService()
    return _stats_service
