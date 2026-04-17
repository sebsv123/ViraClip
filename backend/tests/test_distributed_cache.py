"""
Tests for Distributed Cache API (/cache/*)
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_stats():
    from src.services.distributed_cache import CacheStats
    return CacheStats(
        hits=870,
        misses=130,
        evictions=42,
        total_size_bytes=157286400,
        entry_count=1200,
        hit_rate=0.87,
        avg_access_time_ms=2.3,
    )


class TestDistributedCacheAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.distributed_cache import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_cache_get_found(self):
        client = self._get_client()
        with patch(
            "src.services.distributed_cache.DistributedCacheManager.get",
            new_callable=AsyncMock,
            return_value={"clip_id": "clip_001", "score": 87},
        ):
            resp = client.get("/cache/get/clip_001")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["key"], "clip_001")
        self.assertEqual(data["value"]["score"], 87)

    def test_cache_get_miss(self):
        client = self._get_client()
        with patch(
            "src.services.distributed_cache.DistributedCacheManager.get",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get("/cache/get/missing_key")
        self.assertEqual(resp.status_code, 404)

    def test_cache_set(self):
        client = self._get_client()
        with patch(
            "src.services.distributed_cache.DistributedCacheManager.set",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.post("/cache/set", json={
                "key": "clip_001",
                "value": {"score": 87},
                "ttl": 3600,
                "priority": "normal",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "stored")

    def test_cache_set_with_tags(self):
        client = self._get_client()
        with patch(
            "src.services.distributed_cache.DistributedCacheManager.set",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.post("/cache/set", json={
                "key": "clip_002",
                "value": "some_value",
                "ttl": 7200,
                "priority": "high",
                "tags": ["clips", "user_001"],
            })
        self.assertEqual(resp.status_code, 200)

    def test_cache_set_invalid_priority(self):
        client = self._get_client()
        resp = client.post("/cache/set", json={
            "key": "k",
            "value": "v",
            "priority": "godmode",
        })
        self.assertEqual(resp.status_code, 400)

    def test_cache_set_failure(self):
        client = self._get_client()
        with patch(
            "src.services.distributed_cache.DistributedCacheManager.set",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.post("/cache/set", json={"key": "k", "value": "v"})
        self.assertEqual(resp.status_code, 500)

    def test_cache_delete(self):
        client = self._get_client()
        with patch(
            "src.services.distributed_cache.DistributedCacheManager.delete",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.delete("/cache/keys/clip_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "deleted")

    def test_cache_delete_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.distributed_cache.DistributedCacheManager.delete",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.delete("/cache/keys/ghost_key")
        self.assertEqual(resp.status_code, 404)

    def test_invalidate_by_tag(self):
        client = self._get_client()
        with patch(
            "src.services.distributed_cache.DistributedCacheManager.invalidate_by_tag",
            new_callable=AsyncMock,
            return_value=17,
        ):
            resp = client.post("/cache/invalidate/tag", json={"tag": "user_001"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["entries_removed"], 17)

    def test_invalidate_by_pattern(self):
        client = self._get_client()
        with patch(
            "src.services.distributed_cache.DistributedCacheManager.invalidate_pattern",
            new_callable=AsyncMock,
            return_value=5,
        ):
            resp = client.post("/cache/invalidate/pattern", json={"pattern": "clip_*"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["entries_removed"], 5)

    def test_warm_cache(self):
        client = self._get_client()
        with patch(
            "src.services.distributed_cache.DistributedCacheManager.warm_cache",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.post("/cache/warm", json={
                "entries": [
                    {"key": "clip_001", "value": {"score": 90}},
                    {"key": "clip_002", "value": {"score": 75}},
                ],
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["entries_loaded"], 2)

    def test_warm_cache_empty(self):
        client = self._get_client()
        resp = client.post("/cache/warm", json={"entries": []})
        self.assertEqual(resp.status_code, 400)

    def test_cache_stats(self):
        client = self._get_client()
        stats = _make_stats()
        with patch(
            "src.services.distributed_cache.DistributedCacheManager.get_stats",
            return_value=stats,
        ):
            resp = client.get("/cache/stats")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertAlmostEqual(data["stats"]["hit_rate"], 0.87)
        self.assertEqual(data["stats"]["entry_count"], 1200)

    def test_list_priorities(self):
        client = self._get_client()
        resp = client.get("/cache/priorities")
        self.assertEqual(resp.status_code, 200)
        priorities = resp.json()["priorities"]
        self.assertIn("normal", priorities)
        self.assertIn("high", priorities)


if __name__ == "__main__":
    unittest.main()
