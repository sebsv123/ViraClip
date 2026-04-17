"""
Edge Computing and Global CDN Service
Multi-region edge processing and global content delivery.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class Region(Enum):
    """Edge regions."""
    US_EAST = "us-east"
    US_WEST = "us-west"
    EU_WEST = "eu-west"
    EU_CENTRAL = "eu-central"
    ASIA_PACIFIC = "asia-pacific"
    ASIA_SOUTHEAST = "asia-southeast"
    SOUTH_AMERICA = "south-america"
    MIDDLE_EAST = "middle-east"
    AFRICA = "africa"


class EdgeNodeStatus(Enum):
    """Edge node status."""
    ACTIVE = "active"
    DEGRADED = "degraded"
    MAINTENANCE = "maintenance"
    OFFLINE = "offline"


@dataclass
class EdgeNode:
    """Edge processing node."""
    node_id: str
    region: Region
    location: str
    status: EdgeNodeStatus
    cpu_utilization: float
    memory_utilization: float
    bandwidth_mbps: float
    active_processes: int
    queue_depth: int
    latency_ms: float


@dataclass
class CDNEndpoint:
    """CDN endpoint configuration."""
    endpoint_id: str
    region: Region
    url: str
    provider: str  # cloudflare, aws, fastly, etc.
    cache_hit_ratio: float
    bandwidth_total: float
    requests_per_second: float
    error_rate: float


class EdgeCDNService:
    """
    Global edge computing and CDN distribution service.
    """
    
    def __init__(self):
        self._edge_nodes: Dict[str, EdgeNode] = {}
        self._cdn_endpoints: Dict[str, CDNEndpoint] = {}
        self._clip_distribution: Dict[str, List[str]] = {}  # clip_id -> [endpoint_ids]
        self._initialize_nodes()
    
    def _initialize_nodes(self):
        """Initialize edge node network."""
        regions_config = [
            (Region.US_EAST, "Virginia, USA"),
            (Region.US_WEST, "California, USA"),
            (Region.EU_WEST, "Dublin, Ireland"),
            (Region.EU_CENTRAL, "Frankfurt, Germany"),
            (Region.ASIA_PACIFIC, "Tokyo, Japan"),
            (Region.ASIA_SOUTHEAST, "Singapore"),
            (Region.SOUTH_AMERICA, "São Paulo, Brazil"),
            (Region.MIDDLE_EAST, "Dubai, UAE"),
        ]
        
        for i, (region, location) in enumerate(regions_config):
            import uuid
            node_id = f"edge-{region.value}-{uuid.uuid4().hex[:8]}"
            
            self._edge_nodes[node_id] = EdgeNode(
                node_id=node_id,
                region=region,
                location=location,
                status=EdgeNodeStatus.ACTIVE,
                cpu_utilization=30.0 + i * 5,
                memory_utilization=40.0 + i * 3,
                bandwidth_mbps=1000.0,
                active_processes=12 + i * 2,
                queue_depth=5 + i,
                latency_ms=20 + i * 5
            )
            
            # Create CDN endpoint for each region
            endpoint_id = f"cdn-{region.value}"
            self._cdn_endpoints[endpoint_id] = CDNEndpoint(
                endpoint_id=endpoint_id,
                region=region,
                url=f"https://cdn-{region.value}.viraclip.io",
                provider="cloudflare",
                cache_hit_ratio=0.85,
                bandwidth_total=1500.0 + i * 100,
                requests_per_second=250.0 + i * 10,
                error_rate=0.001
            )
    
    async def process_at_edge(
        self,
        clip_id: str,
        user_location: str,
        processing_task: str,
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process clip at nearest edge node.
        
        Args:
            clip_id: Clip identifier
            user_location: User geographic location
            processing_task: Type of processing task
            data: Processing data
        """
        # Find nearest edge node
        nearest_node = self._find_nearest_node(user_location)
        
        if not nearest_node:
            return {"error": "No edge node available"}
        
        # Check node capacity
        if nearest_node.queue_depth > 50:
            # Find alternative node
            nearest_node = self._find_least_loaded_node()
        
        # Simulate edge processing
        processing_time = await self._simulate_edge_processing(
            nearest_node, processing_task, data
        )
        
        return {
            "clip_id": clip_id,
            "processed_at": nearest_node.node_id,
            "region": nearest_node.region.value,
            "location": nearest_node.location,
            "processing_time_ms": processing_time,
            "task": processing_task,
            "edge_latency_ms": nearest_node.latency_ms
        }
    
    def _find_nearest_node(self, user_location: str) -> Optional[EdgeNode]:
        """Find nearest edge node to user location."""
        # In production, use geo-IP lookup
        # Simplified: find node with lowest latency
        active_nodes = [
            n for n in self._edge_nodes.values()
            if n.status == EdgeNodeStatus.ACTIVE
        ]
        
        if not active_nodes:
            return None
        
        return min(active_nodes, key=lambda n: n.latency_ms)
    
    def _find_least_loaded_node(self) -> Optional[EdgeNode]:
        """Find edge node with lowest load."""
        active_nodes = [
            n for n in self._edge_nodes.values()
            if n.status == EdgeNodeStatus.ACTIVE
        ]
        
        if not active_nodes:
            return None
        
        return min(active_nodes, key=lambda n: n.queue_depth)
    
    async def _simulate_edge_processing(
        self,
        node: EdgeNode,
        task: str,
        data: Dict[str, Any]
    ) -> int:
        """Simulate processing at edge node."""
        # Base processing time
        base_time = 100  # ms
        
        # Adjust for node load
        load_factor = 1 + (node.cpu_utilization / 100)
        
        # Task complexity
        task_complexity = {
            "thumbnail_generation": 1.0,
            "format_conversion": 1.5,
            "light_compression": 2.0,
            "metadata_extraction": 0.5,
            "viral_scoring": 3.0
        }
        
        complexity = task_complexity.get(task, 1.0)
        
        processing_time = int(base_time * load_factor * complexity)
        
        # Update node stats
        node.active_processes += 1
        node.cpu_utilization = min(95, node.cpu_utilization + 5)
        
        return processing_time
    
    async def distribute_to_cdn(
        self,
        clip_id: str,
        clip_url: str,
        regions: Optional[List[Region]] = None
    ) -> Dict[str, Any]:
        """Distribute clip to CDN endpoints."""
        target_regions = regions or list(Region)
        
        distributed_endpoints = []
        
        for region in target_regions:
            endpoint_id = f"cdn-{region.value}"
            
            if endpoint_id in self._cdn_endpoints:
                endpoint = self._cdn_endpoints[endpoint_id]
                
                # Simulate CDN push
                await self._push_to_cdn_endpoint(clip_id, clip_url, endpoint)
                
                distributed_endpoints.append({
                    "region": region.value,
                    "url": f"{endpoint.url}/clips/{clip_id}",
                    "provider": endpoint.provider,
                    "latency_ms": self._estimate_latency(region)
                })
        
        # Track distribution
        self._clip_distribution[clip_id] = [e["region"] for e in distributed_endpoints]
        
        return {
            "clip_id": clip_id,
            "distributed_to": len(distributed_endpoints),
            "endpoints": distributed_endpoints,
            "global_coverage": len(distributed_endpoints) / len(Region) * 100
        }
    
    async def _push_to_cdn_endpoint(
        self,
        clip_id: str,
        clip_url: str,
        endpoint: CDNEndpoint
    ) -> bool:
        """Push content to CDN endpoint."""
        # Simulated CDN push
        logger.info(f"Pushing clip {clip_id} to {endpoint.region.value}")
        return True
    
    def _estimate_latency(self, region: Region) -> int:
        """Estimate latency to region."""
        base_latencies = {
            Region.US_EAST: 15,
            Region.US_WEST: 45,
            Region.EU_WEST: 75,
            Region.EU_CENTRAL: 85,
            Region.ASIA_PACIFIC: 120,
            Region.ASIA_SOUTHEAST: 130,
            Region.SOUTH_AMERICA: 110,
            Region.MIDDLE_EAST: 100,
            Region.AFRICA: 150
        }
        return base_latencies.get(region, 100)
    
    async def get_optimal_endpoint(
        self,
        clip_id: str,
        user_location: str
    ) -> Optional[Dict[str, Any]]:
        """Get optimal CDN endpoint for user."""
        if clip_id not in self._clip_distribution:
            return None
        
        available_regions = self._clip_distribution[clip_id]
        
        # Find best region
        best_region = None
        best_latency = float('inf')
        
        for region_str in available_regions:
            try:
                region = Region(region_str)
                latency = self._estimate_latency(region)
                
                if latency < best_latency:
                    best_latency = latency
                    best_region = region
            except ValueError:
                continue
        
        if not best_region:
            return None
        
        endpoint_id = f"cdn-{best_region.value}"
        endpoint = self._cdn_endpoints.get(endpoint_id)
        
        if not endpoint:
            return None
        
        return {
            "clip_id": clip_id,
            "optimal_region": best_region.value,
            "url": f"{endpoint.url}/clips/{clip_id}",
            "estimated_latency_ms": best_latency,
            "provider": endpoint.provider,
            "cache_hit_ratio": endpoint.cache_hit_ratio
        }
    
    def get_edge_network_status(self) -> Dict[str, Any]:
        """Get edge network status."""
        total_nodes = len(self._edge_nodes)
        active_nodes = len([
            n for n in self._edge_nodes.values()
            if n.status == EdgeNodeStatus.ACTIVE
        ])
        
        avg_cpu = sum(n.cpu_utilization for n in self._edge_nodes.values()) / total_nodes if total_nodes else 0
        avg_memory = sum(n.memory_utilization for n in self._edge_nodes.values()) / total_nodes if total_nodes else 0
        total_bandwidth = sum(n.bandwidth_mbps for n in self._edge_nodes.values())
        
        return {
            "total_nodes": total_nodes,
            "active_nodes": active_nodes,
            "degraded_nodes": total_nodes - active_nodes,
            "avg_cpu_utilization": round(avg_cpu, 2),
            "avg_memory_utilization": round(avg_memory, 2),
            "total_bandwidth_mbps": round(total_bandwidth, 2),
            "total_active_processes": sum(n.active_processes for n in self._edge_nodes.values()),
            "global_queue_depth": sum(n.queue_depth for n in self._edge_nodes.values()),
            "regions_covered": len(set(n.region for n in self._edge_nodes.values()))
        }
    
    def get_cdn_stats(self) -> Dict[str, Any]:
        """Get CDN performance statistics."""
        total_requests = sum(e.requests_per_second for e in self._cdn_endpoints.values())
        total_bandwidth = sum(e.bandwidth_total for e in self._cdn_endpoints.values())
        avg_cache_hit = sum(e.cache_hit_ratio for e in self._cdn_endpoints.values()) / len(self._cdn_endpoints) if self._cdn_endpoints else 0
        avg_error_rate = sum(e.error_rate for e in self._cdn_endpoints.values()) / len(self._cdn_endpoints) if self._cdn_endpoints else 0
        
        return {
            "total_endpoints": len(self._cdn_endpoints),
            "total_requests_per_second": round(total_requests, 2),
            "total_bandwidth_mbps": round(total_bandwidth, 2),
            "average_cache_hit_ratio": round(avg_cache_hit, 3),
            "average_error_rate": round(avg_error_rate, 4),
            "clips_distributed": len(self._clip_distribution)
        }
    
    def get_region_details(self, region: Region) -> Optional[Dict[str, Any]]:
        """Get details for a specific region."""
        nodes_in_region = [
            n for n in self._edge_nodes.values()
            if n.region == region
        ]
        
        if not nodes_in_region:
            return None
        
        endpoint_id = f"cdn-{region.value}"
        endpoint = self._cdn_endpoints.get(endpoint_id)
        
        return {
            "region": region.value,
            "node_count": len(nodes_in_region),
            "total_active_processes": sum(n.active_processes for n in nodes_in_region),
            "avg_latency_ms": sum(n.latency_ms for n in nodes_in_region) / len(nodes_in_region),
            "cdn_endpoint": {
                "url": endpoint.url if endpoint else None,
                "provider": endpoint.provider if endpoint else None,
                "cache_hit_ratio": endpoint.cache_hit_ratio if endpoint else 0
            }
        }


# Global instance
_edge_service: Optional[EdgeCDNService] = None


def get_edge_cdn_service() -> EdgeCDNService:
    """Get global edge CDN service."""
    global _edge_service
    if _edge_service is None:
        _edge_service = EdgeCDNService()
    return _edge_service


# Convenience functions
async def process_clip_at_edge(
    clip_id: str,
    user_location: str,
    task: str
) -> Dict[str, Any]:
    """Process a clip at the nearest edge node."""
    service = get_edge_cdn_service()
    return await service.process_at_edge(clip_id, user_location, task, {})


async def get_clip_cdn_url(clip_id: str, user_location: str) -> Optional[str]:
    """Get optimal CDN URL for a clip."""
    service = get_edge_cdn_service()
    result = await service.get_optimal_endpoint(clip_id, user_location)
    return result.get("url") if result else None
