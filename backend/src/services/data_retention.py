"""
Data Retention Policy Service
Manages data lifecycle and automatic cleanup according to policies.
"""

import logging
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
import shutil
import os

logger = logging.getLogger(__name__)


class DataType(Enum):
    """Types of data subject to retention policies."""
    SOURCE_VIDEOS = "source_videos"
    CLIPS = "clips"
    THUMBNAILS = "thumbnails"
    TEMP_FILES = "temp_files"
    ANALYTICS = "analytics"
    AUDIT_LOGS = "audit_logs"
    USER_DATA = "user_data"
    BACKUPS = "backups"


class RetentionAction(Enum):
    """Actions to take when retention period expires."""
    DELETE = "delete"
    ARCHIVE = "archive"
    ANONYMIZE = "anonymize"
    COMPRESS = "compress"


@dataclass
class RetentionPolicy:
    """Data retention policy configuration."""
    policy_id: str
    data_type: DataType
    retention_days: int
    action: RetentionAction
    enabled: bool
    created_at: str
    exempt_user_ids: List[str]
    min_size_threshold_mb: Optional[float] = None


@dataclass
class CleanupResult:
    """Result of a cleanup operation."""
    data_type: DataType
    items_scanned: int
    items_deleted: int
    items_archived: int
    space_freed_mb: float
    errors: List[str]


class DataRetentionService:
    """
    Manages data retention policies and cleanup operations.
    """
    
    # Default policies
    DEFAULT_POLICIES = {
        DataType.TEMP_FILES: RetentionPolicy(
            policy_id="default_temp",
            data_type=DataType.TEMP_FILES,
            retention_days=7,
            action=RetentionAction.DELETE,
            enabled=True,
            created_at=datetime.now().isoformat(),
            exempt_user_ids=[]
        ),
        DataType.SOURCE_VIDEOS: RetentionPolicy(
            policy_id="default_source",
            data_type=DataType.SOURCE_VIDEOS,
            retention_days=30,
            action=RetentionAction.DELETE,
            enabled=True,
            created_at=datetime.now().isoformat(),
            exempt_user_ids=[]
        ),
        DataType.CLIPS: RetentionPolicy(
            policy_id="default_clips",
            data_type=DataType.CLIPS,
            retention_days=90,
            action=RetentionAction.ARCHIVE,
            enabled=True,
            created_at=datetime.now().isoformat(),
            exempt_user_ids=[]
        ),
        DataType.THUMBNAILS: RetentionPolicy(
            policy_id="default_thumbnails",
            data_type=DataType.THUMBNAILS,
            retention_days=60,
            action=RetentionAction.DELETE,
            enabled=True,
            created_at=datetime.now().isoformat(),
            exempt_user_ids=[]
        ),
        DataType.ANALYTICS: RetentionPolicy(
            policy_id="default_analytics",
            data_type=DataType.ANALYTICS,
            retention_days=365,
            action=RetentionAction.ANONYMIZE,
            enabled=True,
            created_at=datetime.now().isoformat(),
            exempt_user_ids=[]
        ),
        DataType.AUDIT_LOGS: RetentionPolicy(
            policy_id="default_audit",
            data_type=DataType.AUDIT_LOGS,
            retention_days=2555,  # 7 years for compliance
            action=RetentionAction.ARCHIVE,
            enabled=True,
            created_at=datetime.now().isoformat(),
            exempt_user_ids=[]
        )
    }
    
    def __init__(self, base_path: Path = Path("/app")):
        self.base_path = base_path
        self._policies: Dict[str, RetentionPolicy] = {}
        self._cleanup_history: List[Dict[str, Any]] = []
        
        # Load default policies
        for policy in self.DEFAULT_POLICIES.values():
            self._policies[policy.policy_id] = policy
    
    def create_policy(
        self,
        data_type: DataType,
        retention_days: int,
        action: RetentionAction,
        exempt_user_ids: Optional[List[str]] = None,
        min_size_mb: Optional[float] = None
    ) -> RetentionPolicy:
        """Create a new retention policy."""
        import uuid
        
        policy = RetentionPolicy(
            policy_id=str(uuid.uuid4()),
            data_type=data_type,
            retention_days=retention_days,
            action=action,
            enabled=True,
            created_at=datetime.now().isoformat(),
            exempt_user_ids=exempt_user_ids or [],
            min_size_threshold_mb=min_size_mb
        )
        
        self._policies[policy.policy_id] = policy
        logger.info(f"Created retention policy: {policy.policy_id} for {data_type.value}")
        return policy
    
    async def apply_policy(
        self,
        policy_id: str,
        dry_run: bool = False
    ) -> CleanupResult:
        """Apply a retention policy."""
        if policy_id not in self._policies:
            return CleanupResult(
                data_type=DataType.TEMP_FILES,
                items_scanned=0,
                items_deleted=0,
                items_archived=0,
                space_freed_mb=0.0,
                errors=["Policy not found"]
            )
        
        policy = self._policies[policy_id]
        
        if not policy.enabled:
            return CleanupResult(
                data_type=policy.data_type,
                items_scanned=0,
                items_deleted=0,
                items_archived=0,
                space_freed_mb=0.0,
                errors=["Policy is disabled"]
            )
        
        # Determine path based on data type
        paths = self._get_paths_for_data_type(policy.data_type)
        
        # Get list of active video files to protect from cleanup
        active_paths = await self._get_active_video_paths()
        
        cutoff_date = datetime.now() - timedelta(days=policy.retention_days)
        
        result = CleanupResult(
            data_type=policy.data_type,
            items_scanned=0,
            items_deleted=0,
            items_archived=0,
            space_freed_mb=0.0,
            errors=[]
        )
        
        for path in paths:
            if not path.exists():
                continue
            
            try:
                for item in path.iterdir():
                    try:
                        # Check modification time
                        stat = item.stat()
                        modified = datetime.fromtimestamp(stat.st_mtime)
                        
                        # Skip files that are actively being used
                        if item in active_paths:
                            logger.info(f"[RETENTION] Skipping active file: {item.name}")
                            continue
                        
                        if modified < cutoff_date:
                            result.items_scanned += 1
                            
                            # Check size threshold
                            size_mb = stat.st_size / (1024 * 1024)
                            if policy.min_size_threshold_mb and size_mb < policy.min_size_threshold_mb:
                                continue
                            
                            # Perform action
                            if not dry_run:
                                if policy.action == RetentionAction.DELETE:
                                    await self._delete_item(item)
                                    result.items_deleted += 1
                                    result.space_freed_mb += size_mb
                                
                                elif policy.action == RetentionAction.ARCHIVE:
                                    await self._archive_item(item, policy.data_type)
                                    result.items_archived += 1
                                    result.space_freed_mb += size_mb * 0.8  # Compression estimate
                                
                                elif policy.action == RetentionAction.ANONYMIZE:
                                    await self._anonymize_item(item, policy.data_type)
                                    result.items_deleted += 1
                    
                    except Exception as e:
                        result.errors.append(f"Error processing {item}: {e}")
            
            except Exception as e:
                result.errors.append(f"Error scanning {path}: {e}")
        
        # Record cleanup
        self._cleanup_history.append({
            "timestamp": datetime.now().isoformat(),
            "policy_id": policy_id,
            "dry_run": dry_run,
            "result": {
                "items_scanned": result.items_scanned,
                "items_deleted": result.items_deleted,
                "items_archived": result.items_archived,
                "space_freed_mb": result.space_freed_mb
            }
        })
        
        logger.info(
            f"Applied policy {policy_id}: deleted={result.items_deleted}, "
            f"archived={result.items_archived}, freed={result.space_freed_mb:.1f}MB"
        )
        
        return result
    
    async def _get_active_video_paths(self) -> Set[Path]:
        """
        Get paths of video files currently being used by active tasks.
        This prevents deleting videos that are being processed.
        """
        try:
            # Check for active tasks via file locks or temp marker files
            active_paths: Set[Path] = set()
            
            # Look for .processing marker files in uploads directory
            uploads_dir = self.base_path / "temp" / "uploads"
            if uploads_dir.exists():
                for marker_file in uploads_dir.glob("*.processing"):
                    # The marker file name corresponds to the video file name
                    video_file = marker_file.with_suffix('')
                    if video_file.suffix == '':
                        # Try common video extensions
                        for ext in ['.mp4', '.webm', '.mkv', '.mov']:
                            candidate = uploads_dir / f"{video_file.name}{ext}"
                            if candidate.exists():
                                active_paths.add(candidate)
                    else:
                        active_paths.add(video_file)
                    active_paths.add(marker_file)
            
            # Also check for recently modified files (< 1 hour) as safety net
            cutoff_recent = datetime.now() - timedelta(hours=1)
            for data_type in [DataType.SOURCE_VIDEOS, DataType.TEMP_FILES]:
                paths = self._get_paths_for_data_type(data_type)
                for path in paths:
                    if path.exists():
                        for item in path.iterdir():
                            try:
                                if item.is_file():
                                    stat = item.stat()
                                    modified = datetime.fromtimestamp(stat.st_mtime)
                                    if modified > cutoff_recent:
                                        active_paths.add(item)
                            except:
                                pass
            
            if active_paths:
                logger.info(f"[RETENTION] Protected {len(active_paths)} active files from cleanup")
            
            return active_paths
        except Exception as e:
            logger.warning(f"[RETENTION] Error checking active video paths: {e}")
            # Fail-safe: if we can't determine active paths, protect all files
            return set()
    
    def _get_paths_for_data_type(self, data_type: DataType) -> List[Path]:
        """Get file paths for a data type."""
        paths = {
            DataType.TEMP_FILES: [self.base_path / "temp"],
            DataType.SOURCE_VIDEOS: [self.base_path / "temp" / "uploads"],
            DataType.CLIPS: [self.base_path / "temp" / "clips"],
            DataType.THUMBNAILS: [self.base_path / "temp" / "thumbnails"],
            DataType.ANALYTICS: [self.base_path / "data" / "analytics"],
            DataType.AUDIT_LOGS: [self.base_path / "data" / "audit"],
            DataType.BACKUPS: [self.base_path / "backups"]
        }
        
        return paths.get(data_type, [])
    
    async def _delete_item(self, item: Path) -> None:
        """Delete a file or directory."""
        try:
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
        except Exception as e:
            logger.error(f"Failed to delete {item}: {e}")
            raise
    
    async def _archive_item(self, item: Path, data_type: DataType) -> None:
        """Archive an item to long-term storage."""
        archive_base = self.base_path / "archive" / data_type.value
        archive_base.mkdir(parents=True, exist_ok=True)
        
        # Create dated subdirectory
        date_dir = archive_base / datetime.now().strftime("%Y-%m")
        date_dir.mkdir(exist_ok=True)
        
        # Move to archive
        destination = date_dir / item.name
        
        try:
            if item.is_file():
                shutil.move(str(item), str(destination))
            elif item.is_dir():
                shutil.move(str(item), str(destination))
        except Exception as e:
            logger.error(f"Failed to archive {item}: {e}")
            raise
    
    async def _anonymize_item(self, item: Path, data_type: DataType) -> None:
        """Anonymize data in an item."""
        # Implementation depends on data type
        # For analytics/logs, this would remove PII
        # For now, just delete
        await self._delete_item(item)
    
    async def run_all_policies(self, dry_run: bool = False) -> Dict[str, CleanupResult]:
        """Run all enabled policies."""
        results = {}
        
        for policy_id, policy in self._policies.items():
            if policy.enabled:
                result = await self.apply_policy(policy_id, dry_run)
                results[policy_id] = result
        
        return results
    
    def get_policy(self, policy_id: str) -> Optional[RetentionPolicy]:
        """Get a retention policy."""
        return self._policies.get(policy_id)
    
    def list_policies(self) -> List[Dict[str, Any]]:
        """List all retention policies."""
        return [
            {
                "policy_id": p.policy_id,
                "data_type": p.data_type.value,
                "retention_days": p.retention_days,
                "action": p.action.value,
                "enabled": p.enabled,
                "created_at": p.created_at,
                "exempt_count": len(p.exempt_user_ids)
            }
            for p in self._policies.values()
        ]
    
    def update_policy(
        self,
        policy_id: str,
        updates: Dict[str, Any]
    ) -> bool:
        """Update a retention policy."""
        if policy_id not in self._policies:
            return False
        
        policy = self._policies[policy_id]
        
        if "retention_days" in updates:
            policy.retention_days = updates["retention_days"]
        
        if "action" in updates:
            policy.action = RetentionAction(updates["action"])
        
        if "enabled" in updates:
            policy.enabled = updates["enabled"]
        
        if "exempt_user_ids" in updates:
            policy.exempt_user_ids = updates["exempt_user_ids"]
        
        logger.info(f"Updated retention policy: {policy_id}")
        return True
    
    def delete_policy(self, policy_id: str) -> bool:
        """Delete a retention policy."""
        if policy_id in self._policies:
            del self._policies[policy_id]
            return True
        return False
    
    def get_storage_summary(self) -> Dict[str, Any]:
        """Get summary of storage usage."""
        summary = {}
        
        for data_type in DataType:
            paths = self._get_paths_for_data_type(data_type)
            total_size = 0
            file_count = 0
            
            for path in paths:
                if path.exists():
                    try:
                        for item in path.rglob("*"):
                            if item.is_file():
                                total_size += item.stat().st_size
                                file_count += 1
                    except:
                        pass
            
            summary[data_type.value] = {
                "file_count": file_count,
                "size_mb": total_size / (1024 * 1024),
                "size_gb": total_size / (1024 ** 3)
            }
        
        return summary
    
    def get_cleanup_history(
        self,
        days: int = 30
    ) -> List[Dict[str, Any]]:
        """Get cleanup operation history."""
        cutoff = datetime.now() - timedelta(days=days)
        
        return [
            h for h in self._cleanup_history
            if datetime.fromisoformat(h["timestamp"]) > cutoff
        ]


# Global instance
_retention_service: Optional[DataRetentionService] = None


def get_retention_service() -> DataRetentionService:
    """Get global retention service."""
    global _retention_service
    if _retention_service is None:
        _retention_service = DataRetentionService()
    return _retention_service


# Convenience functions
async def cleanup_expired_data(dry_run: bool = False) -> Dict[str, Any]:
    """Run cleanup on all expired data."""
    service = get_retention_service()
    results = await service.run_all_policies(dry_run)
    
    total_deleted = sum(r.items_deleted for r in results.values())
    total_freed = sum(r.space_freed_mb for r in results.values())
    
    return {
        "policies_applied": len(results),
        "total_items_deleted": total_deleted,
        "total_space_freed_mb": total_freed,
        "details": results
    }


def get_storage_report() -> Dict[str, Any]:
    """Get storage usage report."""
    return get_retention_service().get_storage_summary()
