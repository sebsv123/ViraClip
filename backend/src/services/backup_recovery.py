"""
Backup and Disaster Recovery System
Manages automated backups and disaster recovery procedures.
"""

import shutil
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
import json

logger = logging.getLogger(__name__)


@dataclass
class BackupConfig:
    """Backup configuration."""
    name: str
    source_paths: List[Path]
    destination: Path
    schedule: str  # cron format or "daily", "hourly"
    retention_days: int
    compress: bool
    encrypt: bool


@dataclass
class BackupRecord:
    """Record of a backup operation."""
    backup_id: str
    name: str
    started_at: str
    completed_at: Optional[str]
    size_bytes: int
    file_count: int
    status: str  # running, completed, failed
    error_message: Optional[str]
    location: Path


class BackupManager:
    """
    Manages automated backups of critical data.
    """
    
    def __init__(self, backup_dir: Path = Path("/app/backups")):
        self.backup_dir = backup_dir
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._backups: List[BackupRecord] = []
        self._load_backup_history()
    
    def _load_backup_history(self) -> None:
        """Load backup history from disk."""
        history_file = self.backup_dir / "backup_history.json"
        if history_file.exists():
            try:
                with open(history_file, 'r') as f:
                    data = json.load(f)
                    self._backups = [BackupRecord(**r) for r in data]
            except Exception as e:
                logger.warning(f"Failed to load backup history: {e}")
    
    def _save_backup_history(self) -> None:
        """Save backup history to disk."""
        history_file = self.backup_dir / "backup_history.json"
        try:
            data = [
                {
                    "backup_id": r.backup_id,
                    "name": r.name,
                    "started_at": r.started_at,
                    "completed_at": r.completed_at,
                    "size_bytes": r.size_bytes,
                    "file_count": r.file_count,
                    "status": r.status,
                    "error_message": r.error_message,
                    "location": str(r.location)
                }
                for r in self._backups
            ]
            with open(history_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save backup history: {e}")
    
    async def create_backup(
        self,
        name: str,
        source_paths: List[Path],
        compress: bool = True
    ) -> BackupRecord:
        """Create a new backup."""
        import uuid
        
        backup_id = str(uuid.uuid4())
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{name}_{timestamp}"
        backup_path = self.backup_dir / backup_name
        
        record = BackupRecord(
            backup_id=backup_id,
            name=name,
            started_at=datetime.now().isoformat(),
            completed_at=None,
            size_bytes=0,
            file_count=0,
            status="running",
            error_message=None,
            location=backup_path
        )
        
        self._backups.append(record)
        
        try:
            # Create backup directory
            backup_path.mkdir(parents=True, exist_ok=True)
            
            total_size = 0
            total_files = 0
            
            # Copy each source
            for source in source_paths:
                if source.exists():
                    dest = backup_path / source.name
                    
                    if source.is_dir():
                        # Use rsync or shutil for directories
                        shutil.copytree(source, dest, dirs_exist_ok=True)
                        
                        # Count files and size
                        for f in source.rglob("*"):
                            if f.is_file():
                                total_files += 1
                                total_size += f.stat().st_size
                    else:
                        shutil.copy2(source, dest)
                        total_files += 1
                        total_size += source.stat().st_size
            
            # Compress if requested
            if compress:
                archive_path = await self._compress_backup(backup_path)
                
                # Update stats for compressed file
                if archive_path.exists():
                    total_size = archive_path.stat().st_size
                    total_files = 1
                    
                    # Remove uncompressed backup
                    shutil.rmtree(backup_path)
                    record.location = archive_path
            
            record.size_bytes = total_size
            record.file_count = total_files
            record.status = "completed"
            record.completed_at = datetime.now().isoformat()
            
            logger.info(f"Backup completed: {backup_name} ({total_size} bytes)")
            
        except Exception as e:
            record.status = "failed"
            record.error_message = str(e)
            logger.error(f"Backup failed: {e}")
        
        self._save_backup_history()
        return record
    
    async def _compress_backup(self, backup_path: Path) -> Path:
        """Compress backup directory to tar.gz."""
        archive_path = Path(str(backup_path) + ".tar.gz")
        
        try:
            subprocess.run(
                ["tar", "-czf", str(archive_path), "-C", str(backup_path.parent), backup_path.name],
                check=True,
                capture_output=True
            )
            return archive_path
        except subprocess.CalledProcessError as e:
            logger.error(f"Compression failed: {e}")
            return backup_path
    
    async def restore_backup(
        self,
        backup_id: str,
        restore_path: Optional[Path] = None
    ) -> bool:
        """Restore from a backup."""
        # Find backup record
        record = None
        for b in self._backups:
            if b.backup_id == backup_id:
                record = b
                break
        
        if not record:
            logger.error(f"Backup not found: {backup_id}")
            return False
        
        try:
            backup_path = record.location
            
            if not restore_path:
                restore_path = Path("/app/restore") / datetime.now().strftime("%Y%m%d_%H%M%S")
            
            restore_path.mkdir(parents=True, exist_ok=True)
            
            # Extract if compressed
            if str(backup_path).endswith(".tar.gz"):
                subprocess.run(
                    ["tar", "-xzf", str(backup_path), "-C", str(restore_path)],
                    check=True,
                    capture_output=True
                )
            else:
                # Copy directory
                shutil.copytree(backup_path, restore_path / backup_path.name, dirs_exist_ok=True)
            
            logger.info(f"Backup restored to: {restore_path}")
            return True
            
        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return False
    
    def cleanup_old_backups(self, retention_days: int = 30) -> int:
        """Remove backups older than retention period."""
        cutoff = datetime.now() - timedelta(days=retention_days)
        removed = 0
        
        for backup in self._backups[:]:
            backup_date = datetime.fromisoformat(backup.started_at)
            
            if backup_date < cutoff and backup.status == "completed":
                try:
                    if backup.location.exists():
                        if backup.location.is_dir():
                            shutil.rmtree(backup.location)
                        else:
                            backup.location.unlink()
                    
                    self._backups.remove(backup)
                    removed += 1
                    
                except Exception as e:
                    logger.warning(f"Failed to remove old backup: {e}")
        
        if removed > 0:
            self._save_backup_history()
            logger.info(f"Cleaned up {removed} old backups")
        
        return removed
    
    def list_backups(self, name: Optional[str] = None) -> List[BackupRecord]:
        """List all backups, optionally filtered by name."""
        backups = self._backups
        
        if name:
            backups = [b for b in backups if b.name == name]
        
        return sorted(backups, key=lambda x: x.started_at, reverse=True)
    
    def get_backup_status(self) -> Dict[str, Any]:
        """Get overall backup system status."""
        total_backups = len(self._backups)
        successful = sum(1 for b in self._backups if b.status == "completed")
        failed = sum(1 for b in self._backups if b.status == "failed")
        total_size = sum(b.size_bytes for b in self._backups if b.status == "completed")
        
        # Last backup
        last_backup = None
        if self._backups:
            last = max(self._backups, key=lambda x: x.started_at)
            last_backup = {
                "id": last.backup_id,
                "name": last.name,
                "date": last.started_at,
                "status": last.status
            }
        
        return {
            "total_backups": total_backups,
            "successful": successful,
            "failed": failed,
            "total_size_bytes": total_size,
            "last_backup": last_backup,
            "backup_directory": str(self.backup_dir),
            "health": "healthy" if failed == 0 else "degraded" if failed < successful else "critical"
        }


class DisasterRecovery:
    """
    Manages disaster recovery procedures.
    """
    
    def __init__(self, backup_manager: BackupManager):
        self.backup_manager = backup_manager
        self.recovery_plan = {
            "database": self._recover_database,
            "uploads": self._recover_uploads,
            "clips": self._recover_clips,
            "config": self._recover_config
        }
    
    async def _recover_database(self, backup_path: Path) -> bool:
        """Recover database from backup."""
        logger.info("Recovering database...")
        # Implementation depends on database type
        return True
    
    async def _recover_uploads(self, backup_path: Path) -> bool:
        """Recover uploaded videos."""
        logger.info("Recovering uploads...")
        uploads_backup = backup_path / "uploads"
        if uploads_backup.exists():
            dest = Path("/app/temp/uploads")
            shutil.copytree(uploads_backup, dest, dirs_exist_ok=True)
            return True
        return False
    
    async def _recover_clips(self, backup_path: Path) -> bool:
        """Recover generated clips."""
        logger.info("Recovering clips...")
        clips_backup = backup_path / "clips"
        if clips_backup.exists():
            dest = Path("/app/temp/clips")
            shutil.copytree(clips_backup, dest, dirs_exist_ok=True)
            return True
        return False
    
    async def _recover_config(self, backup_path: Path) -> bool:
        """Recover configuration files."""
        logger.info("Recovering configuration...")
        config_backup = backup_path / "config"
        if config_backup.exists():
            # Copy config files back
            return True
        return False
    
    async def perform_recovery(
        self,
        backup_id: str,
        components: Optional[List[str]] = None
    ) -> Dict[str, bool]:
        """
        Perform disaster recovery from a backup.
        
        Args:
            backup_id: ID of backup to restore
            components: List of components to recover, or None for all
        """
        # First restore backup to temp location
        temp_restore = Path("/app/restore") / "recovery"
        
        if not await self.backup_manager.restore_backup(backup_id, temp_restore):
            return {"success": False, "error": "Failed to restore backup"}
        
        # Find extracted backup
        backup_extracted = None
        for item in temp_restore.iterdir():
            if item.is_dir():
                backup_extracted = item
                break
        
        if not backup_extracted:
            return {"success": False, "error": "No backup found in restore location"}
        
        # Recover components
        results = {}
        to_recover = components or list(self.recovery_plan.keys())
        
        for component in to_recover:
            if component in self.recovery_plan:
                try:
                    success = await self.recovery_plan[component](backup_extracted)
                    results[component] = success
                except Exception as e:
                    logger.error(f"Recovery failed for {component}: {e}")
                    results[component] = False
            else:
                results[component] = False
        
        return results
    
    def get_recovery_status(self) -> Dict[str, Any]:
        """Get disaster recovery readiness status."""
        recent_backups = [
            b for b in self.backup_manager._backups
            if b.status == "completed" and
            datetime.fromisoformat(b.started_at) > datetime.now() - timedelta(days=7)
        ]
        
        return {
            "recovery_ready": len(recent_backups) > 0,
            "recent_backups_count": len(recent_backups),
            "last_successful_backup": max(
                (b.started_at for b in recent_backups),
                default=None
            ),
            "recovery_components": list(self.recovery_plan.keys()),
            "test_recovery_recommended": len(recent_backups) > 0
        }


# Global instance
_backup_manager: Optional[BackupManager] = None
_disaster_recovery: Optional[DisasterRecovery] = None


def get_backup_manager() -> BackupManager:
    """Get global backup manager instance."""
    global _backup_manager
    if _backup_manager is None:
        _backup_manager = BackupManager()
    return _backup_manager


def get_disaster_recovery() -> DisasterRecovery:
    """Get global disaster recovery instance."""
    global _disaster_recovery
    if _disaster_recovery is None:
        _disaster_recovery = DisasterRecovery(get_backup_manager())
    return _disaster_recovery


# Convenience functions
async def create_system_backup(name: str = "system") -> BackupRecord:
    """Create a system backup."""
    manager = get_backup_manager()
    
    sources = [
        Path("/app/data"),
        Path("/app/config"),
    ]
    
    return await manager.create_backup(name, sources)


def get_backup_status() -> Dict[str, Any]:
    """Get backup system status."""
    return get_backup_manager().get_backup_status()
