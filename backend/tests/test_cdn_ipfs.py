"""
Tests for:
  1. CDN Management API (/cdn/*)
  2. IPFS Storage API (/ipfs/*)
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cdn_asset(clip_id="clip_001"):
    from src.services.cdn_service import CDNAsset, CDNProvider
    import hashlib
    asset_id = hashlib.sha256(clip_id.encode()).hexdigest()[:16]
    return CDNAsset(
        asset_id=asset_id,
        original_path=Path("/app/data/clip.mp4"),
        cdn_url=f"https://clips.viraclip.com/{asset_id}.mp4",
        provider=CDNProvider.LOCAL,
        created_at="2026-01-01T00:00:00",
        expires_at="2026-02-01T00:00:00",
        size_bytes=52_428_800,   # 50 MB
        content_type="video/mp4",
        etag="abc123def456",
        metadata={"clip_id": clip_id, "ttl_days": 30},
    )


def _make_ipfs_content(content_id="video_001"):
    from src.services.ipfs_storage import IPFSContent, IPFSStatus, ContentType
    return IPFSContent(
        content_id=content_id,
        local_path=Path("/app/data/clip.mp4"),
        ipfs_hash="QmXyZ1234567890abc",
        content_type=ContentType.VIDEO,
        size_bytes=52_428_800,
        status=IPFSStatus.REPLICATED,
        pinned_at="2026-01-01T00:00:00",
        gateways=[
            "https://ipfs.io/ipfs/QmXyZ1234567890abc",
            "https://cloudflare-ipfs.com/ipfs/QmXyZ1234567890abc",
        ],
        metadata={"filename": "clip.mp4", "uploaded_at": "2026-01-01T00:00:00"},
    )


# ===========================================================================
# 1. CDN Management API
# ===========================================================================

class TestCDNAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.cdn import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_upload_clip(self):
        client = self._get_client()
        asset = _make_cdn_asset()
        with patch(
            "src.services.cdn_service.CDNManager.upload_clip",
            new_callable=AsyncMock,
            return_value=asset,
        ):
            resp = client.post("/cdn/upload", json={
                "clip_path": "/app/data/clip.mp4",
                "clip_id": "clip_001",
                "ttl_days": 30,
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "uploaded")
        self.assertIn("cdn_url", data["asset"])
        self.assertEqual(data["asset"]["size_mb"], 50.0)

    def test_upload_clip_file_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.cdn_service.CDNManager.upload_clip",
            new_callable=AsyncMock,
            side_effect=FileNotFoundError("Clip not found"),
        ):
            resp = client.post("/cdn/upload", json={
                "clip_path": "/missing/clip.mp4",
                "clip_id": "missing",
                "ttl_days": 30,
            })
        self.assertEqual(resp.status_code, 404)

    def test_upload_negative_ttl(self):
        client = self._get_client()
        resp = client.post("/cdn/upload", json={
            "clip_path": "/app/data/clip.mp4",
            "clip_id": "clip_001",
            "ttl_days": -1,
        })
        self.assertEqual(resp.status_code, 400)

    def test_get_clip_url(self):
        client = self._get_client()
        with patch(
            "src.services.cdn_service.CDNManager.get_clip_url",
            return_value="https://clips.viraclip.com/abc123.mp4?token=xyz&expires=999",
        ):
            resp = client.get("/cdn/url/clip_001?signed=true&expiry_hours=48")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("url", data)
        self.assertTrue(data["signed"])

    def test_get_clip_url_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.cdn_service.CDNManager.get_clip_url",
            return_value=None,
        ):
            resp = client.get("/cdn/url/missing")
        self.assertEqual(resp.status_code, 404)

    def test_asset_stats(self):
        client = self._get_client()
        stats = {
            "asset_id": "abc123",
            "cdn_url": "https://clips.viraclip.com/abc123.mp4",
            "provider": "local",
            "size_mb": 50.0,
            "created_at": "2026-01-01T00:00:00",
            "expires_at": "2026-02-01T00:00:00",
            "estimated_requests": 0,
            "estimated_bandwidth_gb": 0.0,
        }
        with patch(
            "src.services.cdn_service.CDNManager.get_asset_stats",
            return_value=stats,
        ):
            resp = client.get("/cdn/stats/clip_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["stats"]["provider"], "local")

    def test_asset_stats_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.cdn_service.CDNManager.get_asset_stats",
            return_value=None,
        ):
            resp = client.get("/cdn/stats/missing")
        self.assertEqual(resp.status_code, 404)

    def test_invalidate_cache_by_clip(self):
        client = self._get_client()
        with patch(
            "src.services.cdn_service.CDNManager.invalidate_cache",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.post("/cdn/invalidate", json={"clip_id": "clip_001"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "invalidated")

    def test_invalidate_cache_by_pattern(self):
        client = self._get_client()
        with patch(
            "src.services.cdn_service.CDNManager.invalidate_cache",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.post("/cdn/invalidate", json={"pattern": "/clips/user_001/*"})
        self.assertEqual(resp.status_code, 200)

    def test_invalidate_cache_no_params(self):
        client = self._get_client()
        resp = client.post("/cdn/invalidate", json={})
        self.assertEqual(resp.status_code, 400)

    def test_invalidate_cache_failure(self):
        client = self._get_client()
        with patch(
            "src.services.cdn_service.CDNManager.invalidate_cache",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.post("/cdn/invalidate", json={"pattern": "/no-match/*"})
        self.assertEqual(resp.status_code, 400)

    def test_delete_asset(self):
        client = self._get_client()
        with patch(
            "src.services.cdn_service.CDNManager.delete_asset",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.delete("/cdn/assets/clip_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "deleted")

    def test_delete_asset_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.cdn_service.CDNManager.delete_asset",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.delete("/cdn/assets/missing")
        self.assertEqual(resp.status_code, 404)

    def test_cdn_health(self):
        client = self._get_client()
        health = {
            "provider": "local",
            "status": "healthy",
            "total_assets": 42,
            "total_size_gb": 2.1,
            "avg_response_time_ms": 50,
            "cache_hit_ratio": 0.95,
            "edge_locations": ["Local"],
        }
        with patch(
            "src.services.cdn_service.CDNManager.get_cdn_health",
            return_value=health,
        ):
            resp = client.get("/cdn/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["health"]["status"], "healthy")

    def test_list_providers(self):
        client = self._get_client()
        resp = client.get("/cdn/providers")
        self.assertEqual(resp.status_code, 200)
        providers = resp.json()["providers"]
        self.assertIn("cloudflare", providers)
        self.assertIn("local", providers)


# ===========================================================================
# 2. IPFS Storage API
# ===========================================================================

class TestIPFSAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.ipfs import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_upload_content(self):
        client = self._get_client()
        content = _make_ipfs_content()
        with patch(
            "src.services.ipfs_storage.IPFSService.upload_content",
            new_callable=AsyncMock,
            return_value=content,
        ):
            resp = client.post("/ipfs/upload", json={
                "content_id": "video_001",
                "local_path": "/app/data/clip.mp4",
                "content_type": "video",
                "pin": True,
                "replicate": True,
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()["content"]
        self.assertEqual(data["ipfs_hash"], "QmXyZ1234567890abc")
        self.assertEqual(data["status"], "replicated")
        self.assertEqual(len(data["gateways"]), 2)

    def test_upload_content_file_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.ipfs_storage.IPFSService.upload_content",
            new_callable=AsyncMock,
            side_effect=FileNotFoundError("File not found"),
        ):
            resp = client.post("/ipfs/upload", json={
                "content_id": "x",
                "local_path": "/missing/file.mp4",
            })
        self.assertEqual(resp.status_code, 404)

    def test_upload_invalid_content_type(self):
        client = self._get_client()
        resp = client.post("/ipfs/upload", json={
            "content_id": "x",
            "local_path": "/app/data/file.mp4",
            "content_type": "nft_magic",
        })
        self.assertEqual(resp.status_code, 400)

    def test_retrieve_content(self):
        client = self._get_client()
        with patch(
            "src.services.ipfs_storage.IPFSService.retrieve_content",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.post("/ipfs/retrieve", json={
                "ipfs_hash": "QmXyZ1234567890abc",
                "output_path": "/app/data/retrieved.mp4",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "retrieved")

    def test_retrieve_content_failure(self):
        client = self._get_client()
        with patch(
            "src.services.ipfs_storage.IPFSService.retrieve_content",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.post("/ipfs/retrieve", json={
                "ipfs_hash": "QmInvalid",
                "output_path": "/app/data/out.mp4",
            })
        self.assertEqual(resp.status_code, 502)

    def test_get_content(self):
        client = self._get_client()
        content = _make_ipfs_content()
        with patch(
            "src.services.ipfs_storage.IPFSService.get_content_info",
            return_value=content,
        ):
            resp = client.get("/ipfs/content/video_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["content"]["content_type"], "video")

    def test_get_content_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.ipfs_storage.IPFSService.get_content_info",
            return_value=None,
        ):
            resp = client.get("/ipfs/content/missing")
        self.assertEqual(resp.status_code, 404)

    def test_unpin_content(self):
        client = self._get_client()
        with patch(
            "src.services.ipfs_storage.IPFSService.unpin_content",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.delete("/ipfs/pin/QmXyZ1234567890abc")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "unpinned")

    def test_unpin_failure(self):
        client = self._get_client()
        with patch(
            "src.services.ipfs_storage.IPFSService.unpin_content",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.delete("/ipfs/pin/QmInvalid")
        self.assertEqual(resp.status_code, 500)

    def test_gateway_status(self):
        client = self._get_client()
        gateways = [
            {"gateway_id": "cloudflare", "url": "https://cloudflare-ipfs.com/ipfs/",
             "region": "global", "is_active": True, "latency_ms": 45, "reliability_score": 0.98},
        ]
        with patch(
            "src.services.ipfs_storage.IPFSService.get_gateway_status",
            return_value=gateways,
        ):
            resp = client.get("/ipfs/gateways")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["gateways"]), 1)

    def test_test_latency(self):
        client = self._get_client()
        latencies = {"cloudflare": 45, "ipfs_io": 120}
        with patch(
            "src.services.ipfs_storage.IPFSService.test_gateway_latency",
            new_callable=AsyncMock,
            return_value=latencies,
        ):
            resp = client.post("/ipfs/gateways/latency")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["latency_ms"]["cloudflare"], 45)

    def test_test_latency_single_gateway(self):
        client = self._get_client()
        with patch(
            "src.services.ipfs_storage.IPFSService.test_gateway_latency",
            new_callable=AsyncMock,
            return_value={"cloudflare": 45},
        ):
            resp = client.post("/ipfs/gateways/latency?gateway_id=cloudflare")
        self.assertEqual(resp.status_code, 200)

    def test_storage_stats(self):
        client = self._get_client()
        stats = {
            "total_content": 25,
            "total_size_gb": 12.5,
            "pinned_count": 20,
            "active_gateways": 4,
            "by_type": {"video": {"count": 20, "size": 1_000_000_000}},
        }
        with patch(
            "src.services.ipfs_storage.IPFSService.get_storage_stats",
            return_value=stats,
        ):
            resp = client.get("/ipfs/stats")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["stats"]["total_content"], 25)

    def test_create_archive(self):
        client = self._get_client()
        archive = _make_ipfs_content("archive_batch_1")
        with patch(
            "src.services.ipfs_storage.IPFSService.create_content_archive",
            new_callable=AsyncMock,
            return_value=archive,
        ):
            resp = client.post("/ipfs/archive", json={
                "content_ids": ["video_001", "video_002"],
                "archive_name": "batch_1",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "archived")

    def test_create_archive_empty_ids(self):
        client = self._get_client()
        resp = client.post("/ipfs/archive", json={
            "content_ids": [],
            "archive_name": "empty",
        })
        self.assertEqual(resp.status_code, 400)

    def test_list_content_types(self):
        client = self._get_client()
        resp = client.get("/ipfs/content-types")
        self.assertEqual(resp.status_code, 200)
        types = resp.json()["content_types"]
        self.assertIn("video", types)
        self.assertIn("thumbnail", types)
        self.assertIn("metadata", types)
        self.assertIn("archive", types)


if __name__ == "__main__":
    unittest.main()
