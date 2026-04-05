"""
Tests for:
  1. Live Streaming API (/livestream/*)
  2. Multi-Language API (/languages/*)
"""

from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_live_clip(clip_id="live_s1_abc12345", stream_id="stream_001"):
    from src.services.live_streaming import ClipTriggerType, LiveClip
    return LiveClip(
        clip_id=clip_id,
        stream_id=stream_id,
        start_time=datetime.now(),
        end_time=datetime.now(),
        duration_seconds=30.0,
        trigger_type=ClipTriggerType.MANUAL,
        viral_score=72.5,
        preview_url=None,
        status="processing",
        chat_reaction_count=15,
        peak_viewer_count=200,
    )


def _make_detection_result(lang_code="en", confidence=0.92, reliable=True):
    from src.services.multilanguage_service import (
        LanguageDetectionResult,
        SupportedLanguage,
    )
    lang = SupportedLanguage.from_code(lang_code) or SupportedLanguage.ENGLISH
    return LanguageDetectionResult(
        detected_language=lang,
        confidence=confidence,
        is_reliable=reliable,
        alternative_languages=[],
    )


def _make_transcription_config(lang_code="en"):
    from src.services.multilanguage_service import SupportedLanguage, TranscriptionConfig
    lang = SupportedLanguage.from_code(lang_code) or SupportedLanguage.ENGLISH
    return TranscriptionConfig(
        language=lang,
        model_size="medium",
        use_vad=True,
        word_timestamps=True,
    )


# ===========================================================================
# 1. Live Streaming API
# ===========================================================================

class TestLiveStreamAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.livestream import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_start_monitoring_success(self):
        client = self._get_client()
        with patch(
            "src.services.live_streaming.LiveStreamService.start_stream_monitoring",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.post("/livestream/start", json={
                "stream_url": "https://stream.youtube.com/live/abc123",
                "platform": "youtube",
                "auto_clip": True,
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "monitoring")
        self.assertIn("stream_id", data)

    def test_start_monitoring_custom_id(self):
        client = self._get_client()
        with patch(
            "src.services.live_streaming.LiveStreamService.start_stream_monitoring",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.post("/livestream/start", json={
                "stream_id": "my_custom_stream",
                "stream_url": "https://twitch.tv/live/xyz",
                "platform": "twitch",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["stream_id"], "my_custom_stream")

    def test_start_monitoring_duplicate(self):
        client = self._get_client()
        with patch(
            "src.services.live_streaming.LiveStreamService.start_stream_monitoring",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.post("/livestream/start", json={
                "stream_id": "dup_stream",
                "stream_url": "https://example.com/live",
                "platform": "youtube",
            })
        self.assertEqual(resp.status_code, 409)

    def test_stop_monitoring(self):
        client = self._get_client()
        with patch(
            "src.services.live_streaming.LiveStreamService.stop_stream_monitoring",
            new_callable=AsyncMock,
            return_value=True,
        ):
            resp = client.delete("/livestream/stream_001/stop")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "stopped")

    def test_stop_monitoring_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.live_streaming.LiveStreamService.stop_stream_monitoring",
            new_callable=AsyncMock,
            return_value=False,
        ):
            resp = client.delete("/livestream/missing/stop")
        self.assertEqual(resp.status_code, 404)

    def test_list_active_streams(self):
        client = self._get_client()
        mock_streams = [
            {"stream_id": "s1", "platform": "youtube", "status": "streaming", "clips_count": 3},
            {"stream_id": "s2", "platform": "twitch", "status": "streaming", "clips_count": 1},
        ]
        with patch(
            "src.services.live_streaming.LiveStreamService.get_active_streams",
            return_value=mock_streams,
        ):
            resp = client.get("/livestream")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 2)

    def test_get_stream_status(self):
        client = self._get_client()
        mock_status = {
            "stream_id": "stream_001",
            "status": "streaming",
            "config": {"platform": "youtube", "auto_clip_enabled": True, "viral_threshold": 75.0},
            "clips_extracted": 5,
            "clips_ready": 3,
            "total_duration": 150.0,
        }
        with patch(
            "src.services.live_streaming.LiveStreamService.get_stream_status",
            return_value=mock_status,
        ):
            resp = client.get("/livestream/stream_001")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["stream"]["clips_extracted"], 5)

    def test_get_stream_status_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.live_streaming.LiveStreamService.get_stream_status",
            return_value=None,
        ):
            resp = client.get("/livestream/missing_stream")
        self.assertEqual(resp.status_code, 404)

    def test_extract_clip_success(self):
        client = self._get_client()
        clip = _make_live_clip()
        with patch(
            "src.services.live_streaming.LiveStreamService.extract_clip",
            new_callable=AsyncMock,
            return_value=clip,
        ):
            resp = client.post("/livestream/stream_001/clip", json={
                "duration": 30,
                "trigger": "manual",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "extracting")
        self.assertIn("clip_id", data)

    def test_extract_clip_auto_viral(self):
        client = self._get_client()
        clip = _make_live_clip()
        with patch(
            "src.services.live_streaming.LiveStreamService.extract_clip",
            new_callable=AsyncMock,
            return_value=clip,
        ):
            resp = client.post("/livestream/stream_001/clip", json={
                "duration": 60,
                "trigger": "auto_viral",
            })
        self.assertEqual(resp.status_code, 200)

    def test_extract_clip_invalid_trigger(self):
        client = self._get_client()
        resp = client.post("/livestream/stream_001/clip", json={
            "trigger": "moonphase",
        })
        self.assertEqual(resp.status_code, 400)

    def test_extract_clip_stream_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.live_streaming.LiveStreamService.extract_clip",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.post("/livestream/missing/clip", json={"duration": 30})
        self.assertEqual(resp.status_code, 404)

    def test_get_stream_clips(self):
        client = self._get_client()
        mock_clips = [
            {"clip_id": "c1", "duration": 30, "trigger": "manual", "viral_score": 72.5, "status": "ready", "chat_reactions": 15},
            {"clip_id": "c2", "duration": 30, "trigger": "auto_viral", "viral_score": 85.0, "status": "ready", "chat_reactions": 40},
        ]
        with patch(
            "src.services.live_streaming.LiveStreamService.get_stream_clips",
            return_value=mock_clips,
        ):
            resp = client.get("/livestream/stream_001/clips")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 2)

    def test_get_stream_clips_filtered(self):
        client = self._get_client()
        with patch(
            "src.services.live_streaming.LiveStreamService.get_stream_clips",
            return_value=[],
        ):
            resp = client.get("/livestream/stream_001/clips?status=ready")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 0)

    def test_publish_clip_success(self):
        client = self._get_client()
        mock_result = {
            "clip_id": "live_s1_abc12345",
            "published_to": {
                "tiktok": {"status": "published", "url": "https://tiktok.com/clip/live_s1_abc12345"},
                "instagram": {"status": "published", "url": "https://instagram.com/clip/live_s1_abc12345"},
            },
            "viral_score": 72.5,
        }
        with patch(
            "src.services.live_streaming.LiveStreamService.publish_clip",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            resp = client.post("/livestream/clips/live_s1_abc12345/publish", json={
                "platforms": ["tiktok", "instagram"],
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "published")

    def test_publish_clip_empty_platforms(self):
        client = self._get_client()
        resp = client.post("/livestream/clips/c1/publish", json={"platforms": []})
        self.assertEqual(resp.status_code, 400)

    def test_publish_clip_not_found(self):
        client = self._get_client()
        with patch(
            "src.services.live_streaming.LiveStreamService.publish_clip",
            new_callable=AsyncMock,
            return_value={"error": "Clip not found"},
        ):
            resp = client.post("/livestream/clips/missing/publish", json={"platforms": ["tiktok"]})
        self.assertEqual(resp.status_code, 404)

    def test_list_statuses(self):
        client = self._get_client()
        resp = client.get("/livestream/statuses/list")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("streaming", data["stream_statuses"])
        self.assertIn("manual", data["clip_triggers"])


# ===========================================================================
# 2. Multi-Language API
# ===========================================================================

class TestMultiLanguageAPI(unittest.TestCase):
    def _get_client(self):
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from src.api.routes.multilanguage import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_detect_from_text(self):
        client = self._get_client()
        result = _make_detection_result("es", 0.78, True)
        with patch(
            "src.services.multilanguage_service.MultiLanguageService.detect_language",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = client.post("/languages/detect", json={
                "text_sample": "el la los muy estar siendo muy interesante",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["detected_language"], "es")
        self.assertTrue(data["is_reliable"])

    def test_detect_no_input(self):
        client = self._get_client()
        resp = client.post("/languages/detect", json={})
        self.assertEqual(resp.status_code, 400)

    def test_detect_audio_path(self):
        client = self._get_client()
        result = _make_detection_result("fr", 0.91, True)
        with patch(
            "src.services.multilanguage_service.MultiLanguageService.detect_language",
            new_callable=AsyncMock,
            return_value=result,
        ):
            resp = client.post("/languages/detect", json={
                "audio_path": "/app/temp/audio.wav",
            })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["detected_language"], "fr")

    def test_transcription_config_english(self):
        client = self._get_client()
        cfg = _make_transcription_config("en")
        style = {"font_size": 24, "position": "bottom", "max_width": 80, "word_highlight": True}
        with patch(
            "src.services.multilanguage_service.MultiLanguageService.get_transcription_config",
            return_value=cfg,
        ), patch(
            "src.services.multilanguage_service.MultiLanguageService.get_font_for_language",
            return_value="TikTokSans-Regular",
        ), patch(
            "src.services.multilanguage_service.MultiLanguageService.get_subtitle_style",
            return_value=style,
        ):
            resp = client.post("/languages/transcription-config", json={
                "language_code": "en",
                "processing_mode": "balanced",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["language_code"], "en")
        self.assertEqual(data["model_size"], "medium")
        self.assertTrue(data["word_timestamps"])

    def test_transcription_config_invalid_language(self):
        client = self._get_client()
        resp = client.post("/languages/transcription-config", json={
            "language_code": "klingon",
        })
        self.assertEqual(resp.status_code, 400)

    def test_subtitle_style_arabic(self):
        client = self._get_client()
        style = {
            "font_size": 24,
            "position": "bottom",
            "max_width": 80,
            "word_highlight": True,
            "rtl": True,
            "text_align": "right",
        }
        with patch(
            "src.services.multilanguage_service.MultiLanguageService.get_subtitle_style",
            return_value=style,
        ), patch(
            "src.services.multilanguage_service.MultiLanguageService.get_font_for_language",
            return_value="Noto Sans Arabic",
        ):
            resp = client.post("/languages/subtitle-style", json={"language_code": "ar"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["style"].get("rtl"))

    def test_subtitle_style_invalid_language(self):
        client = self._get_client()
        resp = client.post("/languages/subtitle-style", json={"language_code": "xyz"})
        self.assertEqual(resp.status_code, 400)

    def test_translate_keywords(self):
        client = self._get_client()
        translations = {"viral": "viral", "trend": "tendencia", "hook": "gancho"}
        with patch(
            "src.services.multilanguage_service.MultiLanguageService.translate_keywords",
            return_value=translations,
        ):
            resp = client.post("/languages/translate-keywords", json={
                "keywords": ["viral", "trend", "hook"],
                "source_language": "en",
                "target_language": "es",
            })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["target_language"], "es")
        self.assertEqual(data["translations"]["trend"], "tendencia")

    def test_translate_keywords_empty(self):
        client = self._get_client()
        resp = client.post("/languages/translate-keywords", json={
            "keywords": [],
            "target_language": "es",
        })
        self.assertEqual(resp.status_code, 400)

    def test_translate_keywords_invalid_target(self):
        client = self._get_client()
        resp = client.post("/languages/translate-keywords", json={
            "keywords": ["viral"],
            "target_language": "martian",
        })
        self.assertEqual(resp.status_code, 400)

    def test_get_font(self):
        client = self._get_client()
        with patch(
            "src.services.multilanguage_service.MultiLanguageService.get_font_for_language",
            return_value="Noto Sans CJK JP",
        ):
            resp = client.get("/languages/font?language_code=ja&preference=modern")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["font"], "Noto Sans CJK JP")

    def test_get_font_invalid_language(self):
        client = self._get_client()
        resp = client.get("/languages/font?language_code=xyz")
        self.assertEqual(resp.status_code, 400)

    def test_list_languages(self):
        client = self._get_client()
        resp = client.get("/languages")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["count"], 15)
        codes = [lang["code"] for lang in data["languages"]]
        self.assertIn("en", codes)
        self.assertIn("zh", codes)
        self.assertIn("ar", codes)
        self.assertIn("ko", codes)


if __name__ == "__main__":
    unittest.main()
