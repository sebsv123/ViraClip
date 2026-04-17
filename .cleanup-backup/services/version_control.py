"""
Version Control and Change Management Service
Git-like version control for clips with branching, diffing, and history.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
import hashlib
import json

logger = logging.getLogger(__name__)


class ChangeType(Enum):
    """Types of changes in version control."""
    CREATE = "create"
    MODIFY = "modify"
    DELETE = "delete"
    RENAME = "rename"
    MERGE = "merge"


@dataclass
class ClipVersion:
    """A version of a clip."""
    version_id: str
    clip_id: str
    version_number: int
    parent_version_id: Optional[str]
    author_id: str
    author_name: str
    change_type: ChangeType
    change_summary: str
    file_path: Path
    file_hash: str
    file_size: int
    metadata: Dict[str, Any]
    created_at: str
    tags: List[str]


@dataclass
class Branch:
    """A branch in version control."""
    branch_id: str
    clip_id: str
    name: str
    description: str
    head_version_id: str
    is_main: bool
    created_by: str
    created_at: str
    is_active: bool


@dataclass
class ChangeDiff:
    """Difference between two versions."""
    from_version_id: str
    to_version_id: str
    added_effects: List[str]
    removed_effects: List[str]
    duration_change: float
    metadata_changes: Dict[str, Any]
    thumbnail_changed: bool


class VersionControlService:
    """
    Version control system for clips.
    """
    
    def __init__(self, storage_path: Path = Path("/app/data/versions")):
        self.storage_path = storage_path
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        self._versions: Dict[str, ClipVersion] = {}
        self._branches: Dict[str, Branch] = {}
        self._clip_versions: Dict[str, List[str]] = {}  # clip_id -> [version_ids]
    
    async def create_initial_version(
        self,
        clip_id: str,
        file_path: Path,
        author_id: str,
        author_name: str,
        metadata: Dict[str, Any]
    ) -> ClipVersion:
        """Create the initial version of a clip."""
        import uuid
        
        version_id = str(uuid.uuid4())
        
        # Calculate file hash
        file_hash = self._calculate_file_hash(file_path)
        file_size = file_path.stat().st_size
        
        # Store file in version storage
        version_file_path = self._store_version_file(file_path, clip_id, version_id)
        
        version = ClipVersion(
            version_id=version_id,
            clip_id=clip_id,
            version_number=1,
            parent_version_id=None,
            author_id=author_id,
            author_name=author_name,
            change_type=ChangeType.CREATE,
            change_summary="Initial version created",
            file_path=version_file_path,
            file_hash=file_hash,
            file_size=file_size,
            metadata=metadata,
            created_at=datetime.now().isoformat(),
            tags=[]
        )
        
        self._versions[version_id] = version
        
        if clip_id not in self._clip_versions:
            self._clip_versions[clip_id] = []
        self._clip_versions[clip_id].append(version_id)
        
        # Create main branch
        await self.create_branch(
            clip_id=clip_id,
            name="main",
            description="Main branch",
            head_version_id=version_id,
            created_by=author_id,
            is_main=True
        )
        
        logger.info(f"Created initial version {version_id} for clip {clip_id}")
        return version
    
    async def create_version(
        self,
        clip_id: str,
        file_path: Path,
        parent_version_id: str,
        author_id: str,
        author_name: str,
        change_summary: str,
        change_type: ChangeType = ChangeType.MODIFY,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ClipVersion:
        """Create a new version of a clip."""
        import uuid
        
        # Get parent version
        parent = self._versions.get(parent_version_id)
        if not parent:
            raise ValueError(f"Parent version {parent_version_id} not found")
        
        # Calculate new version number
        existing_versions = self._clip_versions.get(clip_id, [])
        version_number = len(existing_versions) + 1
        
        version_id = str(uuid.uuid4())
        file_hash = self._calculate_file_hash(file_path)
        file_size = file_path.stat().st_size
        
        # Store file
        version_file_path = self._store_version_file(file_path, clip_id, version_id)
        
        version = ClipVersion(
            version_id=version_id,
            clip_id=clip_id,
            version_number=version_number,
            parent_version_id=parent_version_id,
            author_id=author_id,
            author_name=author_name,
            change_type=change_type,
            change_summary=change_summary,
            file_path=version_file_path,
            file_hash=file_hash,
            file_size=file_size,
            metadata=metadata or {},
            created_at=datetime.now().isoformat(),
            tags=[]
        )
        
        self._versions[version_id] = version
        self._clip_versions[clip_id].append(version_id)
        
        # Update branch head if on main branch
        for branch in self._branches.values():
            if branch.clip_id == clip_id and branch.head_version_id == parent_version_id:
                branch.head_version_id = version_id
                break
        
        logger.info(f"Created version {version_number} for clip {clip_id}")
        return version
    
    async def create_branch(
        self,
        clip_id: str,
        name: str,
        description: str,
        head_version_id: str,
        created_by: str,
        is_main: bool = False
    ) -> Branch:
        """Create a new branch for a clip."""
        import uuid
        
        # Check if version exists
        if head_version_id not in self._versions:
            raise ValueError(f"Version {head_version_id} not found")
        
        branch_id = str(uuid.uuid4())
        
        branch = Branch(
            branch_id=branch_id,
            clip_id=clip_id,
            name=name,
            description=description,
            head_version_id=head_version_id,
            is_main=is_main,
            created_by=created_by,
            created_at=datetime.now().isoformat(),
            is_active=True
        )
        
        self._branches[branch_id] = branch
        
        logger.info(f"Created branch '{name}' for clip {clip_id}")
        return branch
    
    def _calculate_file_hash(self, file_path: Path) -> str:
        """Calculate SHA-256 hash of file."""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    
    def _store_version_file(
        self,
        source_path: Path,
        clip_id: str,
        version_id: str
    ) -> Path:
        """Store a version file in storage."""
        clip_dir = self.storage_path / clip_id
        clip_dir.mkdir(exist_ok=True)
        
        dest_path = clip_dir / f"{version_id}.mp4"
        
        # Copy file
        import shutil
        shutil.copy2(source_path, dest_path)
        
        return dest_path
    
    async def get_version_history(
        self,
        clip_id: str,
        branch_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get version history for a clip."""
        version_ids = self._clip_versions.get(clip_id, [])
        
        if branch_id:
            # Filter by branch (simplified - in real implementation would traverse branch)
            branch = self._branches.get(branch_id)
            if branch:
                # Get versions from branch head backwards
                version_ids = self._get_branch_versions(branch.head_version_id)
        
        versions = []
        for vid in version_ids:
            v = self._versions.get(vid)
            if v:
                versions.append({
                    "version_id": v.version_id,
                    "version_number": v.version_number,
                    "author": v.author_name,
                    "change_type": v.change_type.value,
                    "change_summary": v.change_summary,
                    "created_at": v.created_at,
                    "file_size": v.file_size,
                    "tags": v.tags
                })
        
        return sorted(versions, key=lambda x: x["version_number"], reverse=True)
    
    def _get_branch_versions(self, head_version_id: str) -> List[str]:
        """Get all version IDs in a branch (from head backwards)."""
        version_ids = []
        current_id = head_version_id
        
        while current_id:
            version_ids.append(current_id)
            version = self._versions.get(current_id)
            if not version:
                break
            current_id = version.parent_version_id
        
        return version_ids
    
    async def compare_versions(
        self,
        from_version_id: str,
        to_version_id: str
    ) -> Optional[ChangeDiff]:
        """Compare two versions and return differences."""
        from_version = self._versions.get(from_version_id)
        to_version = self._versions.get(to_version_id)
        
        if not from_version or not to_version:
            return None
        
        # Compare metadata
        metadata_changes = {}
        all_keys = set(from_version.metadata.keys()) | set(to_version.metadata.keys())
        
        for key in all_keys:
            old_val = from_version.metadata.get(key)
            new_val = to_version.metadata.get(key)
            if old_val != new_val:
                metadata_changes[key] = {
                    "from": old_val,
                    "to": new_val
                }
        
        # Calculate duration change
        duration_change = (
            to_version.metadata.get("duration", 0) - 
            from_version.metadata.get("duration", 0)
        )
        
        # Check effects changes
        old_effects = set(from_version.metadata.get("effects", []))
        new_effects = set(to_version.metadata.get("effects", []))
        
        added_effects = list(new_effects - old_effects)
        removed_effects = list(old_effects - new_effects)
        
        return ChangeDiff(
            from_version_id=from_version_id,
            to_version_id=to_version_id,
            added_effects=added_effects,
            removed_effects=removed_effects,
            duration_change=duration_change,
            metadata_changes=metadata_changes,
            thumbnail_changed=from_version.metadata.get("thumbnail") != to_version.metadata.get("thumbnail")
        )
    
    async def revert_to_version(
        self,
        clip_id: str,
        version_id: str,
        author_id: str,
        author_name: str
    ) -> Optional[ClipVersion]:
        """Revert clip to a specific version."""
        target_version = self._versions.get(version_id)
        if not target_version or target_version.clip_id != clip_id:
            return None
        
        # Create new version based on old one
        new_version = await self.create_version(
            clip_id=clip_id,
            file_path=target_version.file_path,
            parent_version_id=version_id,
            author_id=author_id,
            author_name=author_name,
            change_summary=f"Reverted to version {target_version.version_number}",
            change_type=ChangeType.MODIFY,
            metadata=target_version.metadata.copy()
        )
        
        return new_version
    
    async def tag_version(
        self,
        version_id: str,
        tag: str,
        author_id: str
    ) -> bool:
        """Add a tag to a version."""
        version = self._versions.get(version_id)
        if not version:
            return False
        
        if tag not in version.tags:
            version.tags.append(tag)
        
        return True
    
    async def merge_branches(
        self,
        source_branch_id: str,
        target_branch_id: str,
        author_id: str,
        author_name: str
    ) -> Optional[ClipVersion]:
        """Merge two branches."""
        source_branch = self._branches.get(source_branch_id)
        target_branch = self._branches.get(target_branch_id)
        
        if not source_branch or not target_branch:
            return None
        
        if source_branch.clip_id != target_branch.clip_id:
            raise ValueError("Cannot merge branches from different clips")
        
        # Get source version
        source_version = self._versions.get(source_branch.head_version_id)
        
        # Create merge version
        new_version = await self.create_version(
            clip_id=source_branch.clip_id,
            file_path=source_version.file_path,
            parent_version_id=target_branch.head_version_id,
            author_id=author_id,
            author_name=author_name,
            change_summary=f"Merged branch '{source_branch.name}' into '{target_branch.name}'",
            change_type=ChangeType.MERGE,
            metadata=source_version.metadata.copy()
        )
        
        # Update target branch head
        target_branch.head_version_id = new_version.version_id
        
        return new_version
    
    def get_branches(self, clip_id: str) -> List[Dict[str, Any]]:
        """Get all branches for a clip."""
        return [
            {
                "branch_id": b.branch_id,
                "name": b.name,
                "description": b.description,
                "is_main": b.is_main,
                "head_version": b.head_version_id,
                "created_by": b.created_by,
                "created_at": b.created_at
            }
            for b in self._branches.values()
            if b.clip_id == clip_id and b.is_active
        ]
    
    async def delete_branch(self, branch_id: str) -> bool:
        """Delete a branch (soft delete)."""
        if branch_id not in self._branches:
            return False
        
        branch = self._branches[branch_id]
        if branch.is_main:
            raise ValueError("Cannot delete main branch")
        
        branch.is_active = False
        return True
    
    def get_version_stats(self) -> Dict[str, Any]:
        """Get version control statistics."""
        total_versions = len(self._versions)
        total_branches = sum(1 for b in self._branches.values() if b.is_active)
        total_clips = len(self._clip_versions)
        
        # Calculate storage used
        total_storage = sum(
            v.file_size for v in self._versions.values()
        )
        
        return {
            "total_versions": total_versions,
            "total_branches": total_branches,
            "total_clips_with_versions": total_clips,
            "total_storage_bytes": total_storage,
            "total_storage_gb": total_storage / (1024**3),
            "average_versions_per_clip": total_versions / total_clips if total_clips > 0 else 0
        }


# Global instance
_version_service: Optional[VersionControlService] = None


def get_version_control_service() -> VersionControlService:
    """Get global version control service."""
    global _version_service
    if _version_service is None:
        _version_service = VersionControlService()
    return _version_service


# Convenience functions
async def create_clip_version(
    clip_id: str,
    file_path: Path,
    author_id: str,
    author_name: str,
    change_summary: str
) -> ClipVersion:
    """Create a new clip version."""
    service = get_version_control_service()
    
    # Get latest version as parent
    versions = service._clip_versions.get(clip_id, [])
    parent_id = versions[-1] if versions else None
    
    if not parent_id:
        return await service.create_initial_version(
            clip_id, file_path, author_id, author_name, {}
        )
    
    return await service.create_version(
        clip_id, file_path, parent_id, author_id, author_name, change_summary
    )


async def get_clip_history(clip_id: str) -> List[Dict[str, Any]]:
    """Get version history for a clip."""
    return await get_version_control_service().get_version_history(clip_id)
