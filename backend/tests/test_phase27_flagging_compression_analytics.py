"""
Phase 27 — Flagging, Smart Compression & Analytics Aggregation Tests

Covers:
  - clip_flagging_service: submit_report, get_reports, resolve, has_reported
  - smart_compression_service: analyze_complexity, recommend_compression
  - clip_analytics_aggregation_service: record_view, get_daily/weekly/range
  - flagging_compression_analytics API routes
"""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient


def run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════
# 1. CLIP FLAGGING SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestClipFlaggingService(unittest.TestCase):
    def _mock_redis(self, llen=0, hgetall=None, sismember=0, lrange=None):
        r = MagicMock()
        r.sismember = AsyncMock(return_value=sismember)
        r.lpush = AsyncMock(return_value=1)
        r.sadd = AsyncMock(return_value=1)
        r.llen = AsyncMock(return_value=llen)
        r.hset = AsyncMock(return_value=1)
        r.hgetall = AsyncMock(return_value=hgetall or {})
        r.lrange = AsyncMock(return_value=lrange or [])
        r.pipeline = MagicMock(return_value=r)
        r.execute = AsyncMock(return_value=[])
        return r

    def test_submit_report_creates_record(self):
        from src.services.clip_flagging_service import submit_report
        r = self._mock_redis(llen=1)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(submit_report("c1", "u1", "spam"))
        self.assertEqual(result["reason"], "spam")
        self.assertIn("report_id", result)

    def test_submit_report_raises_if_already_reported(self):
        from src.services.clip_flagging_service import submit_report
        r = self._mock_redis(sismember=1)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            with self.assertRaises(ValueError):
                run(submit_report("c1", "u1", "spam"))

    def test_submit_report_escalates_on_keyword(self):
        from src.services.clip_flagging_service import submit_report
        r = self._mock_redis(llen=1)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(submit_report("c1", "u1", "csam content"))
        self.assertEqual(result["action_taken"], "escalated")

    def test_get_clip_reports(self):
        from src.services.clip_flagging_service import get_clip_reports
        raw = [json.dumps({"report_id": "r1", "reason": "spam"}).encode()]
        r = self._mock_redis(lrange=raw)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_clip_reports("c1"))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["reason"], "spam")

    def test_resolve_reports(self):
        from src.services.clip_flagging_service import resolve_reports
        r = self._mock_redis()
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(resolve_reports("c1", "mod1", "dismissed"))
        self.assertTrue(result["resolved"])

    def test_has_user_reported_true(self):
        from src.services.clip_flagging_service import has_user_reported
        r = self._mock_redis(sismember=1)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(has_user_reported("u1", "c1"))
        self.assertTrue(result)


# ═══════════════════════════════════════════════════════════════════════════
# 2. SMART COMPRESSION SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestSmartCompressionService(unittest.TestCase):
    def test_analyze_content_complexity_low(self):
        from src.services.smart_compression_service import analyze_content_complexity
        result = analyze_content_complexity(motion_score=20, detail_score=30)
        self.assertEqual(result, "low")

    def test_analyze_content_complexity_high(self):
        from src.services.smart_compression_service import analyze_content_complexity
        result = analyze_content_complexity(motion_score=80, detail_score=90)
        self.assertEqual(result, "high")

    def test_recommend_compression_low_complexity(self):
        from src.services.smart_compression_service import recommend_compression
        result = recommend_compression("low")
        self.assertGreaterEqual(result["crf"], 23)

    def test_recommend_compression_high_complexity(self):
        from src.services.smart_compression_service import recommend_compression
        result = recommend_compression("high")
        self.assertLessEqual(result["crf"], 20)

    def test_recommend_compression_with_size_constraint(self):
        from src.services.smart_compression_service import recommend_compression
        result = recommend_compression("medium", target_size_mb=5, duration=300)
        self.assertLessEqual(result["video_bitrate_kbps"], 150)

    def test_get_compression_profile_uses_cache(self):
        from src.services.smart_compression_service import get_compression_profile
        cached = {"clip_id": "c1", "cached": True, "complexity": "low",
                  "recommendation": {}, "generated_at": "t"}
        with patch("src.services.smart_compression_service._redis") as mock_redis:
            mock_redis.return_value.get = AsyncMock(
                return_value=json.dumps({k: v for k, v in cached.items() if k != "cached"}).encode()
            )
            result = run(get_compression_profile("c1"))
        self.assertTrue(result.get("cached", False))

    def test_build_ffmpeg_args(self):
        from src.services.smart_compression_service import build_ffmpeg_args
        profile = {"recommendation": {"crf": 23, "video_bitrate_kbps": 3000,
                                     "audio_bitrate_kbps": 128, "preset": "medium"}}
        args = build_ffmpeg_args(profile, "/in.mp4", "/out.mp4")
        self.assertIn("-crf", args)
        self.assertIn("23", args)
        self.assertIn("/out.mp4", args)


# ═══════════════════════════════════════════════════════════════════════════
# 3. CLIP ANALYTICS AGGREGATION SERVICE
# ═══════════════════════════════════════════════════════════════════════════

class TestClipAnalyticsAggregationService(unittest.TestCase):
    def _mock_redis(self, hgetall=None, scard=0, smembers=None):
        r = MagicMock()
        r.pipeline = MagicMock(return_value=r)
        r.execute = AsyncMock(return_value=[])
        r.hgetall = AsyncMock(return_value=hgetall or {})
        r.scard = AsyncMock(return_value=scard)
        r.smembers = AsyncMock(return_value=smembers or set())
        return r

    def test_record_view_updates_daily(self):
        from src.services.clip_analytics_aggregation_service import record_view
        r = self._mock_redis()
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(record_view("c1", "v1", 30.0, completed=True))
        self.assertEqual(result["watch_seconds"], 30.0)

    def test_get_daily_stats_with_data(self):
        from src.services.clip_analytics_aggregation_service import get_daily_stats
        r = self._mock_redis(
            hgetall={b"views": b"10", b"completions": b"5", b"watch_seconds_total": b"300"},
            scard=8,
        )
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_daily_stats("c1", "2026-01-01"))
        self.assertEqual(result["views"], 10)
        self.assertEqual(result["avg_watch_seconds"], 30.0)

    def test_get_weekly_stats_empty(self):
        from src.services.clip_analytics_aggregation_service import get_weekly_stats
        r = self._mock_redis(hgetall={}, scard=0)
        with patch("src.workers.job_queue.JobQueue") as jq:
            jq.get_pool = AsyncMock(return_value=r)
            result = run(get_weekly_stats("c1"))
        self.assertEqual(result["views"], 0)


# ═══════════════════════════════════════════════════════════════════════════
# 4. API ROUTES
# ═══════════════════════════════════════════════════════════════════════════

def _make_p27_app():
    from fastapi import FastAPI
    from src.api.routes.flagging_compression_analytics import router
    app = FastAPI()
    app.include_router(router)
    return app


class TestFlaggingCompressionAnalyticsApiRoutes(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_make_p27_app())

    def test_submit_report_200(self):
        report = {"report_id": "r1", "clip_id": "c1", "reporter_id": "u1",
                  "reason": "spam", "details": "", "created_at": "t",
                  "flags_count": 1, "action_taken": None}
        with patch("src.services.clip_flagging_service.submit_report",
                   new=AsyncMock(return_value=report)), \
             patch("src.services.clip_flagging_service.has_user_reported",
                   new=AsyncMock(return_value=False)):
            resp = self.client.post("/clips/c1/report",
                                    json={"reporter_id": "u1", "reason": "spam"})
        self.assertEqual(resp.status_code, 200)

    def test_submit_report_409_already_reported(self):
        with patch("src.services.clip_flagging_service.has_user_reported",
                   new=AsyncMock(return_value=True)):
            resp = self.client.post("/clips/c1/report",
                                    json={"reporter_id": "u1", "reason": "spam"})
        self.assertEqual(resp.status_code, 409)

    def test_get_flag_meta(self):
        with patch("src.services.clip_flagging_service.get_clip_flag_meta",
                   new=AsyncMock(return_value={"flags_count": "2", "auto_action": "hidden"})):
            resp = self.client.get("/clips/c1/flag-meta")
        self.assertEqual(resp.status_code, 200)

    def test_record_view_200(self):
        with patch("src.services.clip_analytics_aggregation_service.record_view",
                   new=AsyncMock(return_value={"clip_id": "c1", "watch_seconds": 45.0})):
            resp = self.client.post("/clips/c1/analytics/view",
                                    json={"viewer_id": "v1", "watch_seconds": 45.0})
        self.assertEqual(resp.status_code, 200)

    def test_get_compression_profile(self):
        profile = {"clip_id": "c1", "complexity": "medium",
                   "recommendation": {"crf": 23}}
        with patch("src.services.smart_compression_service.get_compression_profile",
                   new=AsyncMock(return_value=profile)):
            resp = self.client.get("/clips/c1/compression")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["complexity"], "medium")


if __name__ == "__main__":
    unittest.main()
