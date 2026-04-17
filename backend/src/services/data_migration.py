"""
Data Import/Export Migration Service
Complete data portability system for backup and migration.
"""

import json
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
import zipfile

logger = logging.getLogger(__name__)


class ExportFormat(Enum):
    """Supported export formats."""
    JSON = "json"
    CSV = "csv"
    ZIP = "zip"


class DataType(Enum):
    """Types of data for export."""
    CLIPS = "clips"
    PROJECTS = "projects"
    ANALYTICS = "analytics"
    USER_SETTINGS = "user_settings"
    TEMPLATES = "templates"
    FULL_BACKUP = "full_backup"


@dataclass
class ExportJob:
    """Export job definition."""
    job_id: str
    user_id: str
    data_types: List[DataType]
    format: ExportFormat
    created_at: str
    status: str  # pending, processing, completed, failed
    file_path: Optional[Path]
    file_size: int
    error_message: Optional[str]


@dataclass
class ImportJob:
    """Import job definition."""
    job_id: str
    user_id: str
    source_file: Path
    created_at: str
    status: str
    records_processed: int
    records_failed: int
    error_log: List[str]


class DataMigrationService:
    """
    Service for importing and exporting user data.
    """
    
    def __init__(self, export_dir: Path = Path("/app/exports")):
        self.export_dir = export_dir
        self.export_dir.mkdir(parents=True, exist_ok=True)
        
        self._export_jobs: Dict[str, ExportJob] = {}
        self._import_jobs: Dict[str, ImportJob] = {}
    
    async def create_export(
        self,
        user_id: str,
        data_types: List[DataType],
        format: ExportFormat = ExportFormat.ZIP
    ) -> ExportJob:
        """Create a data export job."""
        import uuid
        
        job_id = str(uuid.uuid4())
        
        job = ExportJob(
            job_id=job_id,
            user_id=user_id,
            data_types=data_types,
            format=format,
            created_at=datetime.now().isoformat(),
            status="pending",
            file_path=None,
            file_size=0,
            error_message=None
        )
        
        self._export_jobs[job_id] = job
        
        # Start export process
        asyncio.create_task(self._process_export(job_id))
        
        logger.info(f"Created export job {job_id} for user {user_id}")
        return job
    
    async def _process_export(self, job_id: str) -> None:
        """Process export job."""
        job = self._export_jobs[job_id]
        job.status = "processing"
        
        try:
            # Collect data
            export_data = {}
            
            for data_type in job.data_types:
                if data_type == DataType.CLIPS:
                    export_data["clips"] = await self._export_clips(job.user_id)
                elif data_type == DataType.PROJECTS:
                    export_data["projects"] = await self._export_projects(job.user_id)
                elif data_type == DataType.ANALYTICS:
                    export_data["analytics"] = await self._export_analytics(job.user_id)
                elif data_type == DataType.USER_SETTINGS:
                    export_data["settings"] = await self._export_settings(job.user_id)
                elif data_type == DataType.TEMPLATES:
                    export_data["templates"] = await self._export_templates(job.user_id)
            
            # Generate file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"export_{job.user_id}_{timestamp}"
            
            if job.format == ExportFormat.JSON:
                file_path = self.export_dir / f"{filename}.json"
                with open(file_path, 'w') as f:
                    json.dump(export_data, f, indent=2)
            
            elif job.format == ExportFormat.ZIP:
                file_path = self.export_dir / f"{filename}.zip"
                with zipfile.ZipFile(file_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                    # Add JSON data
                    zf.writestr(
                        f"{filename}.json",
                        json.dumps(export_data, indent=2)
                    )
                    
                    # Add media files if clips exported
                    if "clips" in export_data:
                        for clip in export_data["clips"]:
                            clip_path = Path(clip.get("file_path", ""))
                            if clip_path.exists():
                                zf.write(clip_path, f"clips/{clip_path.name}")
            
            # Update job
            job.file_path = file_path
            job.file_size = file_path.stat().st_size
            job.status = "completed"
            
            logger.info(f"Export job {job_id} completed: {file_path}")
            
        except Exception as e:
            job.status = "failed"
            job.error_message = str(e)
            logger.error(f"Export job {job_id} failed: {e}")
    
    async def _export_clips(self, user_id: str) -> List[Dict[str, Any]]:
        """Export user's clips."""
        # In production, query database
        return []
    
    async def _export_projects(self, user_id: str) -> List[Dict[str, Any]]:
        """Export user's projects."""
        return []
    
    async def _export_analytics(self, user_id: str) -> Dict[str, Any]:
        """Export user's analytics data."""
        return {}
    
    async def _export_settings(self, user_id: str) -> Dict[str, Any]:
        """Export user settings."""
        return {}
    
    async def _export_templates(self, user_id: str) -> List[Dict[str, Any]]:
        """Export user's custom templates."""
        return []
    
    async def create_import(
        self,
        user_id: str,
        source_file: Path
    ) -> ImportJob:
        """Create data import job."""
        import uuid
        
        job_id = str(uuid.uuid4())
        
        job = ImportJob(
            job_id=job_id,
            user_id=user_id,
            source_file=source_file,
            created_at=datetime.now().isoformat(),
            status="pending",
            records_processed=0,
            records_failed=0,
            error_log=[]
        )
        
        self._import_jobs[job_id] = job
        
        # Start import process
        asyncio.create_task(self._process_import(job_id))
        
        logger.info(f"Created import job {job_id} for user {user_id}")
        return job
    
    async def _process_import(self, job_id: str) -> None:
        """Process import job."""
        job = self._import_jobs[job_id]
        job.status = "processing"
        
        try:
            # Read source file
            data = await self._read_import_file(job.source_file)
            
            # Import each data type
            for data_type, records in data.items():
                if isinstance(records, list):
                    for record in records:
                        try:
                            await self._import_record(job.user_id, data_type, record)
                            job.records_processed += 1
                        except Exception as e:
                            job.records_failed += 1
                            job.error_log.append(f"{data_type}: {str(e)}")
                elif isinstance(records, dict):
                    try:
                        await self._import_record(job.user_id, data_type, records)
                        job.records_processed += 1
                    except Exception as e:
                        job.records_failed += 1
                        job.error_log.append(f"{data_type}: {str(e)}")
            
            job.status = "completed"
            logger.info(f"Import job {job_id} completed: {job.records_processed} records")
            
        except Exception as e:
            job.status = "failed"
            job.error_log.append(str(e))
            logger.error(f"Import job {job_id} failed: {e}")
    
    async def _read_import_file(self, file_path: Path) -> Dict[str, Any]:
        """Read import file."""
        if file_path.suffix == '.zip':
            with zipfile.ZipFile(file_path, 'r') as zf:
                json_file = [f for f in zf.namelist() if f.endswith('.json')][0]
                with zf.open(json_file) as f:
                    return json.loads(f.read())
        else:
            with open(file_path, 'r') as f:
                return json.load(f)
    
    async def _import_record(
        self,
        user_id: str,
        data_type: str,
        record: Dict[str, Any]
    ) -> None:
        """Import single record."""
        # In production, save to database
        logger.debug(f"Importing {data_type} record for user {user_id}")
    
    def get_export_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get export job status."""
        if job_id not in self._export_jobs:
            return None
        
        job = self._export_jobs[job_id]
        
        return {
            "job_id": job.job_id,
            "status": job.status,
            "data_types": [dt.value for dt in job.data_types],
            "format": job.format.value,
            "file_size": job.file_size,
            "created_at": job.created_at,
            "error": job.error_message
        }
    
    def get_import_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get import job status."""
        if job_id not in self._import_jobs:
            return None
        
        job = self._import_jobs[job_id]
        
        return {
            "job_id": job.job_id,
            "status": job.status,
            "records_processed": job.records_processed,
            "records_failed": job.records_failed,
            "created_at": job.created_at,
            "error_log": job.error_log[:10]  # First 10 errors
        }
    
    def list_user_exports(self, user_id: str) -> List[Dict[str, Any]]:
        """List all exports for a user."""
        exports = [
            {
                "job_id": job.job_id,
                "status": job.status,
                "data_types": [dt.value for dt in job.data_types],
                "format": job.format.value,
                "file_size": job.file_size,
                "created_at": job.created_at
            }
            for job in self._export_jobs.values()
            if job.user_id == user_id
        ]
        
        return sorted(exports, key=lambda x: x["created_at"], reverse=True)


# Global instance
_migration_service: Optional[DataMigrationService] = None


def get_migration_service() -> DataMigrationService:
    """Get global migration service."""
    global _migration_service
    if _migration_service is None:
        _migration_service = DataMigrationService()
    return _migration_service


# Convenience functions
async def export_user_data(user_id: str, data_types: List[str], format: str = "zip") -> str:
    """Export user data."""
    types_enum = [DataType(dt) for dt in data_types if dt in [t.value for t in DataType]]
    format_enum = ExportFormat(format) if format in [f.value for f in ExportFormat] else ExportFormat.ZIP
    
    job = await get_migration_service().create_export(user_id, types_enum, format_enum)
    return job.job_id


async def import_user_data(user_id: str, file_path: Path) -> str:
    """Import user data."""
    job = await get_migration_service().create_import(user_id, file_path)
    return job.job_id
