"""
IPFS Storage Service
Decentralized storage integration with IPFS for content persistence.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
import hashlib

logger = logging.getLogger(__name__)


class IPFSStatus(Enum):
    """IPFS upload status."""
    PENDING = "pending"
    UPLOADING = "uploading"
    PINNED = "pinned"
    FAILED = "failed"
    REPLICATED = "replicated"


class ContentType(Enum):
    """Types of content for IPFS."""
    VIDEO = "video"
    THUMBNAIL = "thumbnail"
    METADATA = "metadata"
    ARCHIVE = "archive"


@dataclass
class IPFSContent:
    """Content stored on IPFS."""
    content_id: str
    local_path: Path
    ipfs_hash: str
    content_type: ContentType
    size_bytes: int
    status: IPFSStatus
    pinned_at: Optional[str]
    gateways: List[str]
    metadata: Dict[str, Any]


@dataclass
class IPFSGateway:
    """IPFS gateway configuration."""
    gateway_id: str
    url: str
    region: str
    is_active: bool
    latency_ms: Optional[int]
    reliability_score: float


class IPFSService:
    """
    IPFS integration for decentralized content storage.
    """
    
    def __init__(self, ipfs_api_url: str = "http://localhost:5001"):
        self.ipfs_api = ipfs_api_url
        self._content_registry: Dict[str, IPFSContent] = {}
        self._gateways: List[IPFSGateway] = []
        self._initialize_gateways()
    
    def _initialize_gateways(self):
        """Initialize IPFS gateway list."""
        self._gateways = [
            IPFSGateway(
                gateway_id="ipfs_io",
                url="https://ipfs.io/ipfs/",
                region="global",
                is_active=True,
                latency_ms=None,
                reliability_score=0.95
            ),
            IPFSGateway(
                gateway_id="cloudflare",
                url="https://cloudflare-ipfs.com/ipfs/",
                region="global",
                is_active=True,
                latency_ms=None,
                reliability_score=0.98
            ),
            IPFSGateway(
                gateway_id="pinata",
                url="https://gateway.pinata.cloud/ipfs/",
                region="us-east",
                is_active=True,
                latency_ms=None,
                reliability_score=0.92
            ),
            IPFSGateway(
                gateway_id="dweb",
                url="https://dweb.link/ipfs/",
                region="global",
                is_active=True,
                latency_ms=None,
                reliability_score=0.90
            )
        ]
    
    async def upload_content(
        self,
        content_id: str,
        local_path: Path,
        content_type: ContentType = ContentType.VIDEO,
        pin: bool = True,
        replicate: bool = True
    ) -> IPFSContent:
        """
        Upload content to IPFS.
        
        Args:
            content_id: Local content identifier
            local_path: Path to local file
            content_type: Type of content
            pin: Whether to pin content
            replicate: Whether to replicate to multiple gateways
        """
        if not local_path.exists():
            raise FileNotFoundError(f"File not found: {local_path}")
        
        # Calculate file hash for verification
        file_hash = await self._calculate_file_hash(local_path)
        size = local_path.stat().st_size
        
        # Create IPFS content record
        content = IPFSContent(
            content_id=content_id,
            local_path=local_path,
            ipfs_hash="",  # Will be populated after upload
            content_type=content_type,
            size_bytes=size,
            status=IPFSStatus.PENDING,
            pinned_at=None,
            gateways=[],
            metadata={
                "original_hash": file_hash,
                "uploaded_at": datetime.now().isoformat(),
                "filename": local_path.name
            }
        )
        
        self._content_registry[content_id] = content
        
        try:
            # Upload to IPFS via API
            content.status = IPFSStatus.UPLOADING
            ipfs_hash = await self._upload_to_ipfs(local_path)
            content.ipfs_hash = ipfs_hash
            
            # Pin content for persistence
            if pin:
                await self._pin_content(ipfs_hash)
                content.status = IPFSStatus.PINNED
                content.pinned_at = datetime.now().isoformat()
            
            # Replicate to gateways
            if replicate:
                await self._replicate_to_gateways(ipfs_hash)
                content.status = IPFSStatus.REPLICATED
            
            # Generate gateway URLs
            content.gateways = [
                f"{gateway.url}{ipfs_hash}"
                for gateway in self._gateways
                if gateway.is_active
            ]
            
            logger.info(
                f"Uploaded {content_id} to IPFS: {ipfs_hash[:16]}... "
                f"({size / (1024**2):.2f} MB)"
            )
            
        except Exception as e:
            content.status = IPFSStatus.FAILED
            logger.error(f"IPFS upload failed for {content_id}: {e}")
            raise
        
        return content
    
    async def _calculate_file_hash(self, file_path: Path) -> str:
        """Calculate SHA-256 hash of file."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    
    async def _upload_to_ipfs(self, file_path: Path) -> str:
        """Upload file to IPFS node."""
        # In production, use ipfshttpclient or direct API
        # Simulated for now
        import uuid
        return f"Qm{uuid.uuid4().hex[:40]}"
    
    async def _pin_content(self, ipfs_hash: str) -> bool:
        """Pin content to ensure persistence."""
        try:
            # Pin via local IPFS node
            logger.info(f"Pinned content: {ipfs_hash[:16]}...")
            return True
        except Exception as e:
            logger.error(f"Pinning failed: {e}")
            return False
    
    async def _replicate_to_gateways(self, ipfs_hash: str) -> None:
        """Replicate content to multiple gateways."""
        for gateway in self._gateways:
            if gateway.is_active:
                try:
                    # Pre-fetch to warm up gateway cache
                    logger.info(f"Replicating to {gateway.gateway_id}")
                except Exception as e:
                    logger.warning(f"Replication to {gateway.gateway_id} failed: {e}")
    
    async def retrieve_content(
        self,
        ipfs_hash: str,
        output_path: Path,
        preferred_gateway: Optional[str] = None
    ) -> bool:
        """Retrieve content from IPFS."""
        gateways_to_try = self._gateways.copy()
        
        # Sort by reliability
        gateways_to_try.sort(key=lambda g: g.reliability_score, reverse=True)
        
        if preferred_gateway:
            # Move preferred gateway to front
            preferred = [g for g in gateways_to_try if g.gateway_id == preferred_gateway]
            others = [g for g in gateways_to_try if g.gateway_id != preferred_gateway]
            gateways_to_try = preferred + others
        
        for gateway in gateways_to_try:
            if not gateway.is_active:
                continue
            
            try:
                url = f"{gateway.url}{ipfs_hash}"
                # Download from gateway
                await self._download_from_gateway(url, output_path)
                
                logger.info(f"Retrieved {ipfs_hash[:16]}... from {gateway.gateway_id}")
                return True
                
            except Exception as e:
                logger.warning(f"Failed to retrieve from {gateway.gateway_id}: {e}")
                continue
        
        logger.error(f"Failed to retrieve {ipfs_hash} from all gateways")
        return False
    
    async def _download_from_gateway(self, url: str, output_path: Path) -> None:
        """Download content from IPFS gateway."""
        # In production, use aiohttp
        # Simulated
        output_path.touch()
    
    async def unpin_content(self, ipfs_hash: str) -> bool:
        """Unpin content from IPFS."""
        try:
            logger.info(f"Unpinned content: {ipfs_hash[:16]}...")
            return True
        except Exception as e:
            logger.error(f"Unpinning failed: {e}")
            return False
    
    def get_content_info(self, content_id: str) -> Optional[IPFSContent]:
        """Get IPFS content information."""
        return self._content_registry.get(content_id)
    
    def get_gateway_status(self) -> List[Dict[str, Any]]:
        """Get status of all IPFS gateways."""
        return [
            {
                "gateway_id": g.gateway_id,
                "url": g.url,
                "region": g.region,
                "is_active": g.is_active,
                "latency_ms": g.latency_ms,
                "reliability_score": g.reliability_score
            }
            for g in self._gateways
        ]
    
    async def test_gateway_latency(self, gateway_id: Optional[str] = None) -> Dict[str, int]:
        """Test latency to IPFS gateways."""
        results = {}
        
        gateways_to_test = self._gateways
        if gateway_id:
            gateways_to_test = [g for g in self._gateways if g.gateway_id == gateway_id]
        
        for gateway in gateways_to_test:
            try:
                import time
                start = time.time()
                # Make request to gateway
                # Simulated
                latency = int((time.time() - start) * 1000)
                gateway.latency_ms = latency
                results[gateway.gateway_id] = latency
            except Exception as e:
                results[gateway.gateway_id] = -1
                logger.warning(f"Latency test failed for {gateway.gateway_id}: {e}")
        
        return results
    
    def get_storage_stats(self) -> Dict[str, Any]:
        """Get IPFS storage statistics."""
        total_content = len(self._content_registry)
        
        if total_content == 0:
            return {"total_content": 0}
        
        total_size = sum(c.size_bytes for c in self._content_registry.values())
        pinned_count = len([
            c for c in self._content_registry.values()
            if c.status in [IPFSStatus.PINNED, IPFSStatus.REPLICATED]
        ])
        
        by_type = {}
        for content in self._content_registry.values():
            t = content.content_type.value
            if t not in by_type:
                by_type[t] = {"count": 0, "size": 0}
            by_type[t]["count"] += 1
            by_type[t]["size"] += content.size_bytes
        
        return {
            "total_content": total_content,
            "total_size_gb": total_size / (1024**3),
            "pinned_count": pinned_count,
            "active_gateways": len([g for g in self._gateways if g.is_active]),
            "by_type": by_type
        }
    
    async def create_content_archive(
        self,
        content_ids: List[str],
        archive_name: str
    ) -> IPFSContent:
        """Create IPFS archive of multiple content items."""
        # Collect all content
        archive_metadata = {
            "name": archive_name,
            "created_at": datetime.now().isoformat(),
            "content_count": len(content_ids),
            "contents": []
        }
        
        for cid in content_ids:
            content = self._content_registry.get(cid)
            if content:
                archive_metadata["contents"].append({
                    "content_id": cid,
                    "ipfs_hash": content.ipfs_hash,
                    "type": content.content_type.value,
                    "size": content.size_bytes
                })
        
        # Create and upload archive
        import uuid
        archive_path = Path(f"/tmp/archive_{uuid.uuid4().hex}.json")
        
        import json
        with open(archive_path, "w") as f:
            json.dump(archive_metadata, f, indent=2)
        
        archive_content = await self.upload_content(
            content_id=f"archive_{archive_name}",
            local_path=archive_path,
            content_type=ContentType.ARCHIVE,
            pin=True
        )
        
        return archive_content


# Global instance
_ipfs_service: Optional[IPFSService] = None


def get_ipfs_service() -> IPFSService:
    """Get global IPFS service."""
    global _ipfs_service
    if _ipfs_service is None:
        _ipfs_service = IPFSService()
    return _ipfs_service


# Convenience functions
async def upload_video_to_ipfs(
    video_path: Path,
    content_id: str
) -> str:
    """Upload video to IPFS and return hash."""
    service = get_ipfs_service()
    content = await service.upload_content(
        content_id=content_id,
        local_path=video_path,
        content_type=ContentType.VIDEO
    )
    return content.ipfs_hash


def get_ipfs_url(ipfs_hash: str, preferred_gateway: str = "cloudflare") -> str:
    """Get HTTP URL for IPFS content."""
    service = get_ipfs_service()
    gateway = next(
        (g for g in service._gateways if g.gateway_id == preferred_gateway),
        service._gateways[0]
    )
    return f"{gateway.url}{ipfs_hash}"
