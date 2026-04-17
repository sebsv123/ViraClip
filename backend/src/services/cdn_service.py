"""
CDN Integration Service
Manages clip distribution through CDN for fast global delivery.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
import hashlib

logger = logging.getLogger(__name__)


class CDNProvider(Enum):
    """Supported CDN providers."""
    CLOUDFLARE = "cloudflare"
    AWS_CLOUDFRONT = "cloudfront"
    FASTLY = "fastly"
    AKAMAI = "akamai"
    BUNNYCDN = "bunnycdn"
    LOCAL = "local"  # Fallback


@dataclass
class CDNAsset:
    """CDN asset information."""
    asset_id: str
    original_path: Path
    cdn_url: str
    provider: CDNProvider
    created_at: str
    expires_at: Optional[str]
    size_bytes: int
    content_type: str
    etag: str
    metadata: Dict[str, Any]


class CDNManager:
    """
    Manages CDN operations for clip distribution.
    """
    
    def __init__(self, provider: CDNProvider = CDNProvider.LOCAL):
        self.provider = provider
        self._assets: Dict[str, CDNAsset] = {}
        self._config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load CDN configuration."""
        configs = {
            CDNProvider.CLOUDFLARE: {
                "base_url": "https://clips.viraclip.com",
                "api_token": None,  # From env
                "zone_id": None
            },
            CDNProvider.AWS_CLOUDFRONT: {
                "distribution_domain": "clips.viraclip.com",
                "key_pair_id": None,
                "private_key": None
            },
            CDNProvider.LOCAL: {
                "base_url": "/api/clips",
                "storage_path": "/app/temp/clips"
            }
        }
        
        return configs.get(self.provider, configs[CDNProvider.LOCAL])
    
    async def upload_clip(
        self,
        clip_path: Path,
        clip_id: str,
        ttl_days: int = 30
    ) -> CDNAsset:
        """
        Upload a clip to CDN.
        
        Args:
            clip_path: Path to clip file
            clip_id: Unique clip identifier
            ttl_days: Time to live in CDN (days)
        """
        if not clip_path.exists():
            raise FileNotFoundError(f"Clip not found: {clip_path}")
        
        # Generate asset info
        asset_id = self._generate_asset_id(clip_id)
        size = clip_path.stat().st_size
        etag = self._calculate_etag(clip_path)
        
        # Upload based on provider
        if self.provider == CDNProvider.LOCAL:
            cdn_url = f"{self._config['base_url']}/{clip_id}.mp4"
        else:
            cdn_url = await self._upload_to_provider(clip_path, asset_id)
        
        # Calculate expiration
        expires = None
        if ttl_days > 0:
            expires = (datetime.now() + timedelta(days=ttl_days)).isoformat()
        
        asset = CDNAsset(
            asset_id=asset_id,
            original_path=clip_path,
            cdn_url=cdn_url,
            provider=self.provider,
            created_at=datetime.now().isoformat(),
            expires_at=expires,
            size_bytes=size,
            content_type="video/mp4",
            etag=etag,
            metadata={
                "clip_id": clip_id,
                "ttl_days": ttl_days
            }
        )
        
        self._assets[asset_id] = asset
        
        logger.info(f"Uploaded clip to CDN: {asset_id} ({size} bytes)")
        return asset
    
    async def _upload_to_provider(
        self,
        clip_path: Path,
        asset_id: str
    ) -> str:
        """Upload to specific CDN provider."""
        # Implementation would use provider-specific SDK
        # For now, return a mock URL
        
        if self.provider == CDNProvider.CLOUDFLARE:
            return f"https://clips.viraclip.com/{asset_id}.mp4"
        
        elif self.provider == CDNProvider.AWS_CLOUDFRONT:
            return f"https://clips.viraclip.com/{asset_id}.mp4"
        
        elif self.provider == CDNProvider.BUNNYCDN:
            return f"https://viraclip.b-cdn.net/{asset_id}.mp4"
        
        return f"{self._config.get('base_url', '/clips')}/{asset_id}.mp4"
    
    def get_clip_url(
        self,
        clip_id: str,
        signed: bool = True,
        expiry_hours: int = 24
    ) -> Optional[str]:
        """
        Get CDN URL for a clip.
        
        Args:
            clip_id: Clip identifier
            signed: Whether to generate signed URL
            expiry_hours: Signed URL expiry time
        """
        asset_id = self._generate_asset_id(clip_id)
        
        if asset_id not in self._assets:
            # Try to create URL anyway
            return self._generate_url(asset_id, signed, expiry_hours)
        
        asset = self._assets[asset_id]
        
        if signed and self.provider != CDNProvider.LOCAL:
            return self._generate_signed_url(asset, expiry_hours)
        
        return asset.cdn_url
    
    def _generate_asset_id(self, clip_id: str) -> str:
        """Generate CDN asset ID from clip ID."""
        return hashlib.sha256(clip_id.encode()).hexdigest()[:16]
    
    def _calculate_etag(self, file_path: Path) -> str:
        """Calculate ETag for file."""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    
    def _generate_url(
        self,
        asset_id: str,
        signed: bool,
        expiry_hours: int
    ) -> str:
        """Generate CDN URL."""
        base = self._config.get('base_url', '/clips')
        return f"{base}/{asset_id}.mp4"
    
    def _generate_signed_url(
        self,
        asset: CDNAsset,
        expiry_hours: int
    ) -> str:
        """Generate signed URL for secure access."""
        # Implementation would use provider-specific signing
        # For CloudFront: https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/PrivateContent.html
        # For Cloudflare: https://developers.cloudflare.com/stream/viewing-videos/securing-your-stream/
        
        expiry = datetime.now() + timedelta(hours=expiry_hours)
        
        # Simple token generation (production would use proper signing)
        token = hashlib.sha256(
            f"{asset.asset_id}:{expiry.isoformat()}:secret".encode()
        ).hexdigest()[:16]
        
        return f"{asset.cdn_url}?token={token}&expires={int(expiry.timestamp())}"
    
    async def invalidate_cache(
        self,
        clip_id: Optional[str] = None,
        pattern: Optional[str] = None
    ) -> bool:
        """
        Invalidate CDN cache.
        
        Args:
            clip_id: Specific clip to invalidate
            pattern: Wildcard pattern to invalidate
        """
        if self.provider == CDNProvider.LOCAL:
            return True  # No cache to invalidate
        
        # Build invalidation paths
        paths = []
        
        if clip_id:
            asset_id = self._generate_asset_id(clip_id)
            paths.append(f"/{asset_id}.mp4")
        
        if pattern:
            paths.append(pattern)
        
        if not paths:
            return False
        
        # Call provider invalidation API
        logger.info(f"Invalidating CDN cache: {paths}")
        
        # Implementation would call provider API
        return True
    
    async def delete_asset(self, clip_id: str) -> bool:
        """Delete clip from CDN."""
        asset_id = self._generate_asset_id(clip_id)
        
        if asset_id not in self._assets:
            return False
        
        # Delete from provider
        if self.provider != CDNProvider.LOCAL:
            await self._delete_from_provider(asset_id)
        
        # Remove from tracking
        del self._assets[asset_id]
        
        logger.info(f"Deleted CDN asset: {asset_id}")
        return True
    
    async def _delete_from_provider(self, asset_id: str) -> None:
        """Delete from specific CDN provider."""
        # Implementation would use provider API
        pass
    
    def get_asset_stats(self, clip_id: str) -> Optional[Dict[str, Any]]:
        """Get CDN statistics for a clip."""
        asset_id = self._generate_asset_id(clip_id)
        
        if asset_id not in self._assets:
            return None
        
        asset = self._assets[asset_id]
        
        # In production, this would fetch real stats from CDN provider
        return {
            "asset_id": asset_id,
            "cdn_url": asset.cdn_url,
            "provider": asset.provider.value,
            "size_mb": asset.size_bytes / (1024 * 1024),
            "created_at": asset.created_at,
            "expires_at": asset.expires_at,
            "estimated_requests": 0,  # From CDN analytics
            "estimated_bandwidth_gb": 0.0
        }
    
    def get_cdn_health(self) -> Dict[str, Any]:
        """Get CDN health status."""
        return {
            "provider": self.provider.value,
            "status": "healthy",
            "total_assets": len(self._assets),
            "total_size_gb": sum(a.size_bytes for a in self._assets.values()) / (1024**3),
            "avg_response_time_ms": 50,  # Estimated
            "cache_hit_ratio": 0.95,  # Estimated
            "edge_locations": self._get_edge_locations()
        }
    
    def _get_edge_locations(self) -> List[str]:
        """Get CDN edge locations."""
        locations = {
            CDNProvider.CLOUDFLARE: [
                "US-East", "US-West", "EU-West", "EU-Central",
                "Asia-Pacific", "South America", "Australia"
            ],
            CDNProvider.AWS_CLOUDFRONT: [
                "US-East", "US-West", "EU", "Asia", "Australia", "South America"
            ],
            CDNProvider.LOCAL: ["Local"]
        }
        
        return locations.get(self.provider, ["Unknown"])


class MultiCDNManager:
    """
    Manages multiple CDN providers for optimal delivery.
    """
    
    def __init__(self):
        self._cdns: Dict[CDNProvider, CDNManager] = {}
        self._primary: CDNProvider = CDNProvider.LOCAL
    
    def add_cdn(
        self,
        provider: CDNProvider,
        manager: CDNManager,
        is_primary: bool = False
    ) -> None:
        """Add a CDN provider."""
        self._cdns[provider] = manager
        
        if is_primary:
            self._primary = provider
    
    async def upload_to_optimal(
        self,
        clip_path: Path,
        clip_id: str,
        target_regions: Optional[List[str]] = None
    ) -> CDNAsset:
        """
        Upload to optimal CDN based on target regions.
        
        Args:
            clip_path: Clip file path
            clip_id: Clip identifier
            target_regions: Target geographic regions
        """
        # Select best CDN based on regions
        provider = self._select_cdn_for_regions(target_regions)
        
        cdn = self._cdns.get(provider)
        if not cdn:
            cdn = self._cdns.get(self._primary)
        
        return await cdn.upload_clip(clip_path, clip_id)
    
    def _select_cdn_for_regions(
        self,
        regions: Optional[List[str]]
    ) -> CDNProvider:
        """Select best CDN for target regions."""
        if not regions:
            return self._primary
        
        # Simple region-based selection
        # Asia-Pacific -> Cloudflare
        # Europe -> BunnyCDN
        # Americas -> CloudFront
        
        region = regions[0].lower()
        
        if any(r in region for r in ['asia', 'pacific', 'japan', 'singapore']):
            return CDNProvider.CLOUDFLARE
        
        if any(r in region for r in ['europe', 'eu', 'germany', 'france']):
            return CDNProvider.BUNNYCDN
        
        return self._primary
    
    def get_url_with_fallback(
        self,
        clip_id: str,
        preferred_cdn: Optional[CDNProvider] = None
    ) -> Optional[str]:
        """Get URL with fallback to available CDNs."""
        # Try preferred CDN first
        if preferred_cdn and preferred_cdn in self._cdns:
            url = self._cdns[preferred_cdn].get_clip_url(clip_id, signed=False)
            if url:
                return url
        
        # Try primary CDN
        if self._primary in self._cdns:
            url = self._cdns[self._primary].get_clip_url(clip_id, signed=False)
            if url:
                return url
        
        # Try any available CDN
        for cdn in self._cdns.values():
            url = cdn.get_clip_url(clip_id, signed=False)
            if url:
                return url
        
        return None


# Global instance
_cdn_manager: Optional[CDNManager] = None


def get_cdn_manager() -> CDNManager:
    """Get global CDN manager."""
    global _cdn_manager
    if _cdn_manager is None:
        # Detect provider from config
        provider = CDNProvider.LOCAL
        _cdn_manager = CDNManager(provider)
    return _cdn_manager


# Convenience functions
async def upload_clip_to_cdn(clip_path: Path, clip_id: str) -> CDNAsset:
    """Upload clip to CDN."""
    return await get_cdn_manager().upload_clip(clip_path, clip_id)


def get_clip_cdn_url(clip_id: str, signed: bool = True) -> Optional[str]:
    """Get CDN URL for clip."""
    return get_cdn_manager().get_clip_url(clip_id, signed)
