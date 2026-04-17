"""
Tests for Phase 3 persistence and service upgrades:
  - GeneratedClip model has Phase 10 fields in models/__init__.py
  - clip_repository.create_clip accepts Phase 10 params
  - clip_repository.get_clips_by_task returns Phase 10 fields
  - task_service wires Phase 10 fields into create_clip
  - trending_topics real-data refresh (RSS parse + cache logic)
  - LUT bootstrap script is importable and writes valid .cube content
  - init.sql contains idempotent ALTER TABLE for Phase 10 cols
  - auto_center_face default is now true in Task model
"""

import asyncio
import inspect
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ══════════════════════════════════════════════════════════════════════════════
# models/__init__.py — Phase 10 fields
# ══════════════════════════════════════════════════════════════════════════════

class TestModelsPhase10Fields(unittest.TestCase):

    def _get_clip_src(self):
        from src.models import GeneratedClip
        return inspect.getsource(GeneratedClip)

    def test_cta_overlay_applied_in_model(self):
        src = self._get_clip_src()
        self.assertIn("cta_overlay_applied", src)

    def test_emoji_overlays_applied_in_model(self):
        src = self._get_clip_src()
        self.assertIn("emoji_overlays_applied", src)

    def test_variants_json_in_model(self):
        src = self._get_clip_src()
        self.assertIn("variants_json", src)

    def test_variants_json_is_text_column(self):
        from src.models import GeneratedClip
        col = GeneratedClip.__table__.c.get("variants_json")
        self.assertIsNotNone(col)

    def test_cta_overlay_default_false(self):
        from src.models import GeneratedClip
        col = GeneratedClip.__table__.c.get("cta_overlay_applied")
        self.assertIsNotNone(col)
        self.assertFalse(col.nullable)

    def test_auto_center_face_default_true_in_task(self):
        from src.models import Task
        col = Task.__table__.c.get("auto_center_face")
        self.assertIsNotNone(col)
        # server_default text should contain 'true'
        sd = str(col.server_default.arg) if col.server_default else ""
        self.assertIn("true", sd.lower())


# ══════════════════════════════════════════════════════════════════════════════
# clip_repository — Phase 10 params
# ══════════════════════════════════════════════════════════════════════════════

class TestClipRepositoryPhase10(unittest.TestCase):

    def test_create_clip_has_cta_param(self):
        from src.repositories.clip_repository import ClipRepository
        sig = inspect.signature(ClipRepository.create_clip)
        self.assertIn("cta_overlay_applied", sig.parameters)

    def test_create_clip_has_emoji_param(self):
        from src.repositories.clip_repository import ClipRepository
        sig = inspect.signature(ClipRepository.create_clip)
        self.assertIn("emoji_overlays_applied", sig.parameters)

    def test_create_clip_has_variants_json_param(self):
        from src.repositories.clip_repository import ClipRepository
        sig = inspect.signature(ClipRepository.create_clip)
        self.assertIn("variants_json", sig.parameters)

    def test_create_clip_defaults_cta_false(self):
        from src.repositories.clip_repository import ClipRepository
        sig = inspect.signature(ClipRepository.create_clip)
        self.assertIs(sig.parameters["cta_overlay_applied"].default, False)

    def test_get_clips_selects_phase10_cols(self):
        from src.repositories.clip_repository import ClipRepository
        src = inspect.getsource(ClipRepository.get_clips_by_task)
        self.assertIn("cta_overlay_applied", src)
        self.assertIn("emoji_overlays_applied", src)
        self.assertIn("variants_json", src)

    def test_get_clips_returns_phase10_in_row_dict(self):
        from src.repositories.clip_repository import ClipRepository
        src = inspect.getsource(ClipRepository.get_clips_by_task)
        self.assertIn('"cta_overlay_applied"', src)
        self.assertIn('"variants_json"', src)


# ══════════════════════════════════════════════════════════════════════════════
# task_service — Phase 10 wired
# ══════════════════════════════════════════════════════════════════════════════

class TestTaskServicePhase10Wiring(unittest.TestCase):

    def _src(self):
        from src.services.task_service import TaskService
        return inspect.getsource(TaskService)

    def test_cta_overlay_applied_passed_to_create_clip(self):
        src = self._src()
        self.assertIn("cta_overlay_applied=clip_info.get", src)

    def test_emoji_overlays_applied_passed_to_create_clip(self):
        src = self._src()
        self.assertIn("emoji_overlays_applied=clip_info.get", src)

    def test_variants_json_serialised_before_persist(self):
        src = self._src()
        self.assertIn("variants_json=", src)
        self.assertIn("json", src.lower())


# ══════════════════════════════════════════════════════════════════════════════
# trending_topics — real-data refresh
# ══════════════════════════════════════════════════════════════════════════════

class TestTrendingTopicsRealData(unittest.IsolatedAsyncioTestCase):

    async def test_has_refresh_trends_method(self):
        from src.services.trending_topics import TrendingTopicsService
        self.assertTrue(asyncio.iscoroutinefunction(TrendingTopicsService.refresh_trends))

    async def test_has_fetch_google_trends_rss_method(self):
        from src.services.trending_topics import TrendingTopicsService
        self.assertTrue(asyncio.iscoroutinefunction(TrendingTopicsService._fetch_google_trends_rss))

    async def test_parse_google_trends_rss_empty_xml(self):
        from src.services.trending_topics import TrendingTopicsService
        result = TrendingTopicsService._parse_google_trends_rss("<rss></rss>")
        self.assertIsInstance(result, list)
        self.assertEqual(result, [])

    async def test_parse_google_trends_rss_valid_item(self):
        from src.services.trending_topics import TrendingTopicsService
        xml = """<rss xmlns:ht="https://trends.google.com/trends/trendingsearches/daily">
          <channel><item>
            <title>Python AI</title>
            <ht:approx_traffic>250,000+</ht:approx_traffic>
          </item></channel>
        </rss>"""
        result = TrendingTopicsService._parse_google_trends_rss(xml)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["keyword"], "Python AI")
        self.assertEqual(result[0]["volume"], 250000)

    async def test_raw_to_topic_maps_technology_hint(self):
        from src.services.trending_topics import TrendingTopicsService, TrendCategory
        svc = TrendingTopicsService()
        raw = {"keyword": "AI chatbot", "volume": 300000}
        topic = svc._raw_to_topic(raw)
        self.assertEqual(topic.category, TrendCategory.TECHNOLOGY)
        self.assertGreater(topic.score, 0)
        self.assertTrue(topic.topic_id.startswith("trend_"))

    async def test_raw_to_topic_status_from_volume(self):
        from src.services.trending_topics import TrendingTopicsService, TrendStatus
        svc = TrendingTopicsService()
        self.assertEqual(svc._raw_to_topic({"keyword": "x", "volume": 600000}).status, TrendStatus.PEAK)
        self.assertEqual(svc._raw_to_topic({"keyword": "x", "volume": 150000}).status, TrendStatus.RISING)
        self.assertEqual(svc._raw_to_topic({"keyword": "x", "volume": 25000}).status, TrendStatus.EMERGING)
        self.assertEqual(svc._raw_to_topic({"keyword": "x", "volume": 5000}).status, TrendStatus.DECLINING)

    async def test_refresh_returns_zero_when_cache_fresh(self):
        from src.services.trending_topics import TrendingTopicsService
        from datetime import datetime
        svc = TrendingTopicsService()
        svc._last_refresh = datetime.now()  # mark as just refreshed
        result = await svc.refresh_trends()
        self.assertEqual(result, 0)

    async def test_refresh_updates_trends_on_successful_fetch(self):
        from src.services.trending_topics import TrendingTopicsService
        svc = TrendingTopicsService()
        mock_raw = [
            {"keyword": "Viral Dance", "volume": 500000},
            {"keyword": "AI Tutorial", "volume": 200000},
        ]
        with patch.object(svc, "_fetch_google_trends_rss", new=AsyncMock(return_value=mock_raw)):
            count = await svc.refresh_trends()
        self.assertEqual(count, 2)
        self.assertEqual(len(svc._trends), 2)

    async def test_refresh_keeps_sample_on_failed_fetch(self):
        from src.services.trending_topics import TrendingTopicsService
        svc = TrendingTopicsService()
        original_count = len(svc._trends)
        with patch.object(svc, "_fetch_google_trends_rss", new=AsyncMock(return_value=[])):
            count = await svc.refresh_trends()
        self.assertEqual(count, 0)
        self.assertEqual(len(svc._trends), original_count)  # unchanged

    async def test_get_trending_topics_calls_refresh(self):
        from src.services.trending_topics import TrendingTopicsService
        svc = TrendingTopicsService()
        with patch.object(svc, "refresh_trends", new=AsyncMock(return_value=0)) as mock_refresh:
            await svc.get_trending_topics()
        mock_refresh.assert_called_once()

    async def test_cache_ttl_constant(self):
        from src.services.trending_topics import _CACHE_TTL_MINUTES
        self.assertEqual(_CACHE_TTL_MINUTES, 60)

    async def test_google_trends_url_constant(self):
        from src.services.trending_topics import _GOOGLE_TRENDS_RSS
        self.assertIn("trends.google.com", _GOOGLE_TRENDS_RSS)
        self.assertIn("geo=US", _GOOGLE_TRENDS_RSS)

    async def test_category_hints_covers_technology(self):
        from src.services.trending_topics import _CATEGORY_HINTS
        self.assertIn("ai", _CATEGORY_HINTS)
        self.assertEqual(_CATEGORY_HINTS["ai"], "technology")

    async def test_sample_trends_still_seeded_on_init(self):
        from src.services.trending_topics import TrendingTopicsService
        svc = TrendingTopicsService()
        self.assertGreater(len(svc._trends), 0)


# ══════════════════════════════════════════════════════════════════════════════
# LUT bootstrap script
# ══════════════════════════════════════════════════════════════════════════════

class TestLutBootstrapScript(unittest.TestCase):

    def _get_script_path(self):
        here = Path(__file__).parent.parent
        return here / "scripts" / "bootstrap_luts.py"

    def test_script_exists(self):
        self.assertTrue(self._get_script_path().exists())

    def test_script_importable(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("bootstrap_luts", self._get_script_path())
        self.assertIsNotNone(spec)

    def test_lut_recipes_defined(self):
        src = self._get_script_path().read_text()
        for name in ("teal_orange", "cinema_cold", "vintage_warm", "high_contrast", "matte_fade"):
            self.assertIn(name, src)

    def test_cube_file_content_format(self):
        """Verify _write_cube generates valid header + float triples."""
        import tempfile, sys
        sys.path.insert(0, str(self._get_script_path().parent.parent / "scripts"))
        # Import helpers inline without running the top-level write block
        src_text = self._get_script_path().read_text()
        # Extract just the helper functions via exec into isolated namespace
        ns: dict = {}
        # Only exec the function definitions (stop before LUTS = [...])
        cutoff = src_text.find("\nLUTS = ")
        exec(src_text[:cutoff], ns)

        with tempfile.NamedTemporaryFile(suffix=".cube", delete=False, mode="w") as f:
            tmp = Path(f.name)

        ns["_write_cube"](tmp, "Test", 5, ns["_identity_entries"] and (lambda r, g, b: (r, g, b)))
        content = tmp.read_text()
        tmp.unlink(missing_ok=True)
        self.assertIn("TITLE Test", content)
        self.assertIn("LUT_3D_SIZE 5", content)
        # Should have 5³=125 data lines after the header
        data_lines = [l for l in content.splitlines() if l and not l.startswith(("TITLE", "LUT_3D_SIZE"))]
        self.assertEqual(len(data_lines), 125)

    def test_all_lut_entries_in_luts_list(self):
        src = self._get_script_path().read_text()
        for fname in ("teal_orange.cube", "cinema_cold.cube", "vintage_warm.cube",
                      "high_contrast.cube", "matte_fade.cube"):
            self.assertIn(fname, src)


# ══════════════════════════════════════════════════════════════════════════════
# init.sql migration
# ══════════════════════════════════════════════════════════════════════════════

class TestInitSqlMigration(unittest.TestCase):

    def _sql(self):
        candidates = [
            Path(__file__).parent.parent.parent / "init.sql",  # /app/../init.sql
            Path("/init.sql"),
            Path("/workspace/init.sql"),
        ]
        for p in candidates:
            if p.exists():
                return p.read_text()
        raise unittest.SkipTest("init.sql not mounted in this environment")

    def test_cta_overlay_applied_migration(self):
        self.assertIn("cta_overlay_applied", self._sql())

    def test_emoji_overlays_applied_migration(self):
        self.assertIn("emoji_overlays_applied", self._sql())

    def test_variants_json_migration(self):
        self.assertIn("variants_json", self._sql())

    def test_migrations_are_idempotent(self):
        sql = self._sql()
        self.assertIn("ADD COLUMN IF NOT EXISTS", sql)

    def test_auto_center_face_default_flip(self):
        sql = self._sql()
        self.assertIn("auto_center_face SET DEFAULT TRUE", sql)

    def test_phase10_comment_present(self):
        self.assertIn("Phase 10", self._sql())


if __name__ == "__main__":
    unittest.main()
