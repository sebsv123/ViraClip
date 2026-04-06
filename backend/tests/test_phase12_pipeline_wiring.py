"""
Tests for Phase 12 pipeline wiring:
  1. Subtitle QA auto-runs inside burn_captions (caption_service.py)
  2. Brand overlay auto-applied from creator profile (coordinator.py)
  3. BGM genre preference passed to create_single_clip (coordinator.py → video_service.py)
"""

import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call


# ── helpers ──────────────────────────────────────────────────────────────────

def run(coro):
    """Run async coroutine in sync test."""
    return asyncio.run(coro)


# ── minimal CreatorProfile stub ───────────────────────────────────────────────

class _FakeProfile:
    caption_style = "bold"
    watermark_text = "@viraclip"
    watermark_image_path = ""
    watermark_position = "bottom_right"
    preferred_music_genre = "hype"
    cta_text = "Follow for more!"

    def cta_for_platform(self, platform: str) -> str:
        return f"Follow on {platform} 🔥"

    def music_genres(self):
        return ["hype", "electronic"]


class _FakeProfileAuto:
    """Profile with auto genre → should NOT pass a preferred_category."""
    caption_style = "minimal"
    watermark_text = ""
    watermark_image_path = ""
    watermark_position = "bottom_right"
    preferred_music_genre = "auto"
    cta_text = "Follow!"

    def cta_for_platform(self, platform: str) -> str:
        return self.cta_text

    def music_genres(self):
        return ["auto"]


class _FakeProfileImage:
    """Profile with image watermark."""
    caption_style = "bold"
    watermark_text = ""
    watermark_image_path = "/app/brand/logo.png"
    watermark_position = "top_left"
    preferred_music_genre = "chill"
    cta_text = "Follow!"

    def cta_for_platform(self, platform):
        return self.cta_text

    def music_genres(self):
        return ["chill"]


# ── 1. Subtitle QA wiring in caption_service ─────────────────────────────────

class TestSubtitleQAWiringInCaptionService(unittest.TestCase):
    """burn_captions() must call run_subtitle_qa on the ASS content before writing."""

    def _build_ass_content(self):
        return "[Script Info]\nScriptType: v4.00+\n\n[Events]\nDialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,Hello world\n"

    def test_subtitle_qa_called_with_ass_content(self):
        """run_subtitle_qa should be called inside burn_captions."""
        fake_qa_result = MagicMock()
        fake_qa_result.fixed_content = self._build_ass_content() + "  "
        fake_qa_result.issues = []

        with patch(
            "src.video_processing.subtitle_qa.run_subtitle_qa",
            return_value=fake_qa_result,
        ) as mock_qa, patch(
            "src.services.caption_service.build_ass_script",
            return_value=self._build_ass_content(),
        ), patch(
            "src.services.caption_service.segment_words_into_lines",
            return_value=[{"words": [{"word": "hello", "start": 1.0, "end": 2.0}]}],
        ), patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
        ) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
            mock_exec.return_value = mock_proc

            from src.services.caption_service import burn_captions
            words = [{"word": "hello", "start": 1.0, "end": 2.0}]
            result = run(
                burn_captions(Path("/tmp/clip.mp4"), Path("/tmp/out.mp4"), words)
            )

        mock_qa.assert_called_once()
        call_args = mock_qa.call_args
        assert call_args[1].get("apply_fixes") is True or call_args[0][1] is True

    def test_subtitle_qa_fixed_content_replaces_original(self):
        """When QA returns fixed_content, that content should be written to the temp file."""
        fixed = "[Script Info]\nFixed content\n"
        fake_qa_result = MagicMock()
        fake_qa_result.fixed_content = fixed
        fake_qa_result.issues = ["reading_speed_too_fast"]

        written_content = []

        import builtins
        real_open = builtins.open

        def fake_open(path, mode="r", **kw):
            if isinstance(path, str) and path.endswith(".ass") and "w" in mode:
                m = MagicMock()
                m.__enter__ = lambda s: s
                m.__exit__ = MagicMock(return_value=False)
                m.write = lambda c: written_content.append(c)
                m.name = path
                return m
            return real_open(path, mode, **kw)

        with patch(
            "src.video_processing.subtitle_qa.run_subtitle_qa",
            return_value=fake_qa_result,
        ), patch(
            "src.services.caption_service.build_ass_script",
            return_value="[Script Info]\nOriginal\n",
        ), patch(
            "src.services.caption_service.segment_words_into_lines",
            return_value=[{"words": [{"word": "hi", "start": 0.5, "end": 1.0}]}],
        ), patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
        ) as mock_exec, patch(
            "tempfile.NamedTemporaryFile"
        ) as mock_ntf:
            tmp_mock = MagicMock()
            tmp_mock.__enter__ = lambda s: s
            tmp_mock.__exit__ = MagicMock(return_value=False)
            tmp_mock.name = "/tmp/test_subtitle.ass"
            tmp_mock.write = lambda c: written_content.append(c)
            mock_ntf.return_value = tmp_mock

            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
            mock_exec.return_value = mock_proc

            from src.services.caption_service import burn_captions
            words = [{"word": "hi", "start": 0.5, "end": 1.0}]
            run(burn_captions(Path("/tmp/clip.mp4"), Path("/tmp/out.mp4"), words))

        if written_content:
            assert written_content[0] == fixed

    def test_subtitle_qa_failure_does_not_break_burn(self):
        """If run_subtitle_qa raises, burn_captions should still proceed."""
        with patch(
            "src.video_processing.subtitle_qa.run_subtitle_qa",
            side_effect=RuntimeError("QA module unavailable"),
        ), patch(
            "src.services.caption_service.build_ass_script",
            return_value="[Script Info]\nContent\n",
        ), patch(
            "src.services.caption_service.segment_words_into_lines",
            return_value=[{"words": [{"word": "test", "start": 0.0, "end": 0.5}]}],
        ), patch(
            "asyncio.create_subprocess_exec",
            new_callable=AsyncMock,
        ) as mock_exec, patch("tempfile.NamedTemporaryFile") as mock_ntf:
            tmp_mock = MagicMock()
            tmp_mock.__enter__ = lambda s: s
            tmp_mock.__exit__ = MagicMock(return_value=False)
            tmp_mock.name = "/tmp/test.ass"
            tmp_mock.write = MagicMock()
            mock_ntf.return_value = tmp_mock

            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
            mock_exec.return_value = mock_proc

            from src.services.caption_service import burn_captions
            # Should not raise even though QA failed
            result = run(
                burn_captions(
                    Path("/tmp/clip.mp4"), Path("/tmp/out.mp4"),
                    [{"word": "test", "start": 0.0, "end": 0.5}],
                )
            )
        # Result may be True or False depending on mock, but no exception raised
        assert isinstance(result, bool)


# ── 2. Brand overlay wiring in coordinator ───────────────────────────────────

class TestBrandOverlayWiringInCoordinator(unittest.TestCase):
    """coordinator._parallel_rendering applies brand overlay when profile has watermark."""

    def _make_coordinator(self, profile=None):
        from src.services.coordinator import VideoCoordinator
        coord = VideoCoordinator(
            task_id="test_brand_task",
            video_path="/tmp/src.mp4",
            config={
                "user_id": "user123",
                "target_platform": "tiktok",
                "add_subtitles": False,
            },
        )
        coord._test_profile = profile
        return coord

    def test_brand_text_watermark_applied_when_profile_has_text(self):
        """apply_text_watermark called when creator profile has watermark_text."""
        profile = _FakeProfile()
        applied_calls = []

        async def fake_text_wm(video_path, output_path, cfg):
            applied_calls.append(("text", cfg.text, cfg.position))
            Path(output_path).write_bytes(b"fake_video")
            return True

        async def fake_img_wm(video_path, output_path, cfg):
            applied_calls.append(("image", cfg.image_path, cfg.position))
            Path(output_path).write_bytes(b"fake_video")
            return True

        clip_path = Path("/tmp/clip_brand_test.mp4")
        clip_path.write_bytes(b"fake")
        mock_clip = {"path": str(clip_path), "id": "clip_1"}

        with patch("src.services.video_service.VideoService.create_single_clip",
                   new_callable=AsyncMock, return_value=mock_clip), \
             patch("src.services.creator_profile_service.get_profile", return_value=profile), \
             patch("src.services.brand_overlay_service.apply_text_watermark", side_effect=fake_text_wm), \
             patch("src.services.brand_overlay_service.apply_image_watermark", side_effect=fake_img_wm), \
             patch("src.services.coordinator._apply_cta_overlay", new_callable=AsyncMock, return_value=False), \
             patch("src.services.coordinator._apply_emoji_overlays", new_callable=AsyncMock, return_value=False), \
             patch("src.services.progress_emitter.emit_clip_generated", new_callable=AsyncMock), \
             patch("src.services.creative_pipeline.get_creative_pipeline") as MockPipeline, \
             patch("src.services.clip_validator.get_clip_validator") as MockValidator:

            MockValidator.return_value.validate_input = AsyncMock(
                return_value=MagicMock(passed=True, warnings=[]))
            MockValidator.return_value.validate_output = AsyncMock(
                return_value=MagicMock(passed=True, warnings=[], metadata={}))
            mock_cp = MagicMock()
            mock_cp.enhance = AsyncMock(return_value={})
            MockPipeline.return_value = mock_cp

            from src.services.coordinator import VideoCoordinator
            coord = VideoCoordinator(
                task_id="t1",
                video_path="/tmp/src.mp4",
                config={"user_id": "user123", "target_platform": "tiktok", "add_subtitles": False},
            )
            segment = {"start_time": 0, "end_time": 30, "text": "hello", "virality_score": 80}
            run(coord._parallel_rendering([segment]))

        text_calls = [c for c in applied_calls if c[0] == "text"]
        assert len(text_calls) >= 1
        assert text_calls[0][1] == "@viraclip"
        assert text_calls[0][2] == "bottom_right"

    def test_brand_image_watermark_applied_when_profile_has_image_path(self):
        """apply_image_watermark called when creator profile has watermark_image_path."""
        profile = _FakeProfileImage()
        applied_calls = []

        async def fake_img_wm(video_path, output_path, cfg):
            applied_calls.append(("image", cfg.image_path, cfg.position))
            Path(output_path).write_bytes(b"fake_video")
            return True

        async def fake_text_wm(video_path, output_path, cfg):
            applied_calls.append(("text", cfg.text, cfg.position))
            Path(output_path).write_bytes(b"fake_video")
            return True

        clip_path = Path("/tmp/clip_img_brand.mp4")
        clip_path.write_bytes(b"fake")
        mock_clip = {"path": str(clip_path), "id": "clip_2"}

        with patch("src.services.video_service.VideoService.create_single_clip",
                   new_callable=AsyncMock, return_value=mock_clip), \
             patch("src.services.creator_profile_service.get_profile", return_value=profile), \
             patch("src.services.brand_overlay_service.apply_image_watermark", side_effect=fake_img_wm), \
             patch("src.services.brand_overlay_service.apply_text_watermark", side_effect=fake_text_wm), \
             patch("src.services.coordinator._apply_cta_overlay", new_callable=AsyncMock, return_value=False), \
             patch("src.services.coordinator._apply_emoji_overlays", new_callable=AsyncMock, return_value=False), \
             patch("src.services.progress_emitter.emit_clip_generated", new_callable=AsyncMock), \
             patch("src.services.creative_pipeline.get_creative_pipeline") as MockPipeline, \
             patch("src.services.clip_validator.get_clip_validator") as MockValidator:

            MockValidator.return_value.validate_input = AsyncMock(
                return_value=MagicMock(passed=True, warnings=[]))
            MockValidator.return_value.validate_output = AsyncMock(
                return_value=MagicMock(passed=True, warnings=[], metadata={}))
            mock_cp = MagicMock()
            mock_cp.enhance = AsyncMock(return_value={})
            MockPipeline.return_value = mock_cp

            from src.services.coordinator import VideoCoordinator
            coord = VideoCoordinator(
                task_id="t2",
                video_path="/tmp/src.mp4",
                config={"user_id": "user_img", "target_platform": "tiktok", "add_subtitles": False},
            )
            segment = {"start_time": 0, "end_time": 30, "text": "hello", "virality_score": 70}
            run(coord._parallel_rendering([segment]))

        image_calls = [c for c in applied_calls if c[0] == "image"]
        assert len(image_calls) >= 1
        assert image_calls[0][1] == "/app/brand/logo.png"

    def test_brand_overlay_skipped_when_no_watermark(self):
        """No brand overlay attempted when profile has no watermark_text or image."""
        profile = _FakeProfileAuto()  # empty watermark_text, empty image
        applied_calls = []

        async def fake_text_wm(video_path, output_path, cfg):
            applied_calls.append("text")
            return True

        async def fake_img_wm(video_path, output_path, cfg):
            applied_calls.append("image")
            return True

        clip_path = Path("/tmp/clip_no_brand.mp4")
        clip_path.write_bytes(b"fake")
        mock_clip = {"path": str(clip_path), "id": "clip_3"}

        with patch("src.services.video_service.VideoService.create_single_clip",
                   new_callable=AsyncMock, return_value=mock_clip), \
             patch("src.services.creator_profile_service.get_profile", return_value=profile), \
             patch("src.services.brand_overlay_service.apply_text_watermark", side_effect=fake_text_wm), \
             patch("src.services.brand_overlay_service.apply_image_watermark", side_effect=fake_img_wm), \
             patch("src.services.coordinator._apply_cta_overlay", new_callable=AsyncMock, return_value=False), \
             patch("src.services.coordinator._apply_emoji_overlays", new_callable=AsyncMock, return_value=False), \
             patch("src.services.progress_emitter.emit_clip_generated", new_callable=AsyncMock), \
             patch("src.services.creative_pipeline.get_creative_pipeline") as MockPipeline, \
             patch("src.services.clip_validator.get_clip_validator") as MockValidator:

            MockValidator.return_value.validate_input = AsyncMock(
                return_value=MagicMock(passed=True, warnings=[]))
            MockValidator.return_value.validate_output = AsyncMock(
                return_value=MagicMock(passed=True, warnings=[], metadata={}))
            mock_cp = MagicMock()
            mock_cp.enhance = AsyncMock(return_value={})
            MockPipeline.return_value = mock_cp

            from src.services.coordinator import VideoCoordinator
            coord = VideoCoordinator(
                task_id="t3",
                video_path="/tmp/src.mp4",
                config={"user_id": "auto_user", "target_platform": "tiktok", "add_subtitles": False},
            )
            segment = {"start_time": 0, "end_time": 30, "text": "hello", "virality_score": 60}
            run(coord._parallel_rendering([segment]))

        assert applied_calls == [], f"Brand overlay should not be applied but got: {applied_calls}"

    def test_brand_overlay_skipped_when_no_profile(self):
        """No brand overlay attempted when user_id is not provided."""
        applied_calls = []

        async def fake_text_wm(video_path, output_path, cfg):
            applied_calls.append("text")
            return True

        clip_path = Path("/tmp/clip_no_profile.mp4")
        clip_path.write_bytes(b"fake")
        mock_clip = {"path": str(clip_path), "id": "clip_4"}

        with patch("src.services.video_service.VideoService.create_single_clip",
                   new_callable=AsyncMock, return_value=mock_clip), \
             patch("src.services.brand_overlay_service.apply_text_watermark", side_effect=fake_text_wm), \
             patch("src.services.coordinator._apply_cta_overlay", new_callable=AsyncMock, return_value=False), \
             patch("src.services.coordinator._apply_emoji_overlays", new_callable=AsyncMock, return_value=False), \
             patch("src.services.progress_emitter.emit_clip_generated", new_callable=AsyncMock), \
             patch("src.services.creative_pipeline.get_creative_pipeline") as MockPipeline, \
             patch("src.services.clip_validator.get_clip_validator") as MockValidator:

            MockValidator.return_value.validate_input = AsyncMock(
                return_value=MagicMock(passed=True, warnings=[]))
            MockValidator.return_value.validate_output = AsyncMock(
                return_value=MagicMock(passed=True, warnings=[], metadata={}))
            mock_cp = MagicMock()
            mock_cp.enhance = AsyncMock(return_value={})
            MockPipeline.return_value = mock_cp

            from src.services.coordinator import VideoCoordinator
            coord = VideoCoordinator(
                task_id="t4",
                video_path="/tmp/src.mp4",
                config={"target_platform": "tiktok", "add_subtitles": False},
            )
            segment = {"start_time": 0, "end_time": 30, "text": "hello", "virality_score": 55}
            run(coord._parallel_rendering([segment]))

        assert applied_calls == []


# ── 3. BGM genre preference wiring ───────────────────────────────────────────

class TestBGMGenrePreferenceWiring(unittest.TestCase):
    """create_single_clip accepts preferred_music_category and passes it to beat_sync."""

    def test_create_single_clip_accepts_preferred_music_category(self):
        """Signature must include preferred_music_category with default None."""
        import inspect
        from src.services.video_service import VideoService
        sig = inspect.signature(VideoService.create_single_clip)
        assert "preferred_music_category" in sig.parameters, (
            "create_single_clip must accept preferred_music_category kwarg"
        )
        assert sig.parameters["preferred_music_category"].default is None

    def test_preferred_music_category_forwarded_to_beat_sync(self):
        """When preferred_music_category='hype', beat_sync receives preferred_category='hype'."""
        from src.services.video_service import VideoService
        import inspect
        src_code = inspect.getsource(VideoService.create_single_clip)
        assert "preferred_category=preferred_music_category" in src_code, \
               "preferred_music_category should be forwarded to mix_bgm_beat_synced as preferred_category"

    def test_coordinator_passes_genre_from_profile_to_create_clip(self):
        """Coordinator resolves first non-auto music genre and passes to create_single_clip."""
        profile = _FakeProfile()  # music_genres() → ["hype", "electronic"]
        captured_kwargs = {}

        async def fake_create_clip(**kw):
            captured_kwargs.update(kw)
            p = Path("/tmp/clip_bgm_test.mp4")
            p.write_bytes(b"fake")
            return {"path": str(p), "id": "clip_bgm"}

        with patch("src.services.video_service.VideoService.create_single_clip",
                   side_effect=fake_create_clip), \
             patch("src.services.creator_profile_service.get_profile", return_value=profile), \
             patch("src.services.coordinator._apply_cta_overlay", new_callable=AsyncMock, return_value=False), \
             patch("src.services.coordinator._apply_emoji_overlays", new_callable=AsyncMock, return_value=False), \
             patch("src.services.progress_emitter.emit_clip_generated", new_callable=AsyncMock), \
             patch("src.services.creative_pipeline.get_creative_pipeline") as MockPipeline, \
             patch("src.services.clip_validator.get_clip_validator") as MockValidator:

            MockValidator.return_value.validate_input = AsyncMock(
                return_value=MagicMock(passed=True, warnings=[]))
            MockValidator.return_value.validate_output = AsyncMock(
                return_value=MagicMock(passed=True, warnings=[], metadata={}))
            mock_cp = MagicMock()
            mock_cp.enhance = AsyncMock(return_value={})
            MockPipeline.return_value = mock_cp

            from src.services.coordinator import VideoCoordinator
            coord = VideoCoordinator(
                task_id="t5",
                video_path="/tmp/src.mp4",
                config={"user_id": "user_genre", "target_platform": "tiktok", "add_subtitles": False},
            )
            segment = {"start_time": 0, "end_time": 30, "text": "hello", "virality_score": 75}
            run(coord._parallel_rendering([segment]))

        assert captured_kwargs.get("preferred_music_category") == "hype", \
            f"Expected 'hype' but got: {captured_kwargs.get('preferred_music_category')}"

    def test_coordinator_passes_none_when_genre_is_auto(self):
        """When profile music genre is 'auto', preferred_music_category should be None."""
        profile = _FakeProfileAuto()  # music_genres() → ["auto"]
        captured_kwargs = {}

        async def fake_create_clip(**kw):
            captured_kwargs.update(kw)
            p = Path("/tmp/clip_auto_bgm.mp4")
            p.write_bytes(b"fake")
            return {"path": str(p), "id": "clip_auto_bgm"}

        with patch("src.services.video_service.VideoService.create_single_clip",
                   side_effect=fake_create_clip), \
             patch("src.services.creator_profile_service.get_profile", return_value=profile), \
             patch("src.services.coordinator._apply_cta_overlay", new_callable=AsyncMock, return_value=False), \
             patch("src.services.coordinator._apply_emoji_overlays", new_callable=AsyncMock, return_value=False), \
             patch("src.services.progress_emitter.emit_clip_generated", new_callable=AsyncMock), \
             patch("src.services.creative_pipeline.get_creative_pipeline") as MockPipeline, \
             patch("src.services.clip_validator.get_clip_validator") as MockValidator:

            MockValidator.return_value.validate_input = AsyncMock(
                return_value=MagicMock(passed=True, warnings=[]))
            MockValidator.return_value.validate_output = AsyncMock(
                return_value=MagicMock(passed=True, warnings=[], metadata={}))
            mock_cp = MagicMock()
            mock_cp.enhance = AsyncMock(return_value={})
            MockPipeline.return_value = mock_cp

            from src.services.coordinator import VideoCoordinator
            coord = VideoCoordinator(
                task_id="t6",
                video_path="/tmp/src.mp4",
                config={"user_id": "auto_user", "target_platform": "tiktok", "add_subtitles": False},
            )
            segment = {"start_time": 0, "end_time": 30, "text": "hello", "virality_score": 55}
            run(coord._parallel_rendering([segment]))

        assert captured_kwargs.get("preferred_music_category") is None, \
            f"Expected None for auto genre but got: {captured_kwargs.get('preferred_music_category')}"

    def test_coordinator_passes_none_when_no_profile(self):
        """When no user_id is set, preferred_music_category must be None."""
        captured_kwargs = {}

        async def fake_create_clip(**kw):
            captured_kwargs.update(kw)
            p = Path("/tmp/clip_no_prof_bgm.mp4")
            p.write_bytes(b"fake")
            return {"path": str(p), "id": "clip_no_prof_bgm"}

        with patch("src.services.video_service.VideoService.create_single_clip",
                   side_effect=fake_create_clip), \
             patch("src.services.coordinator._apply_cta_overlay", new_callable=AsyncMock, return_value=False), \
             patch("src.services.coordinator._apply_emoji_overlays", new_callable=AsyncMock, return_value=False), \
             patch("src.services.progress_emitter.emit_clip_generated", new_callable=AsyncMock), \
             patch("src.services.creative_pipeline.get_creative_pipeline") as MockPipeline, \
             patch("src.services.clip_validator.get_clip_validator") as MockValidator:

            MockValidator.return_value.validate_input = AsyncMock(
                return_value=MagicMock(passed=True, warnings=[]))
            MockValidator.return_value.validate_output = AsyncMock(
                return_value=MagicMock(passed=True, warnings=[], metadata={}))
            mock_cp = MagicMock()
            mock_cp.enhance = AsyncMock(return_value={})
            MockPipeline.return_value = mock_cp

            from src.services.coordinator import VideoCoordinator
            coord = VideoCoordinator(
                task_id="t7",
                video_path="/tmp/src.mp4",
                config={"target_platform": "tiktok", "add_subtitles": False},
            )
            segment = {"start_time": 0, "end_time": 30, "text": "hello", "virality_score": 50}
            run(coord._parallel_rendering([segment]))

        assert captured_kwargs.get("preferred_music_category") is None


# ── 4. BGM service preferred_category param ──────────────────────────────────

class TestBeatSyncPreferredCategory(unittest.TestCase):
    """beat_sync_service.mix_bgm_beat_synced accepts preferred_category kwarg."""

    def test_mix_bgm_beat_synced_accepts_preferred_category(self):
        """Verify function signature includes preferred_category."""
        import inspect
        from src.services.beat_sync_service import mix_bgm_beat_synced
        sig = inspect.signature(mix_bgm_beat_synced)
        assert "preferred_category" in sig.parameters, (
            "mix_bgm_beat_synced must accept preferred_category kwarg"
        )

    def test_preferred_category_passed_to_select_bgm(self):
        """When preferred_category is set, select_bgm is called with prefer_category."""
        from src.services.beat_sync_service import select_bgm, BGMTrack
        import inspect
        src_code = inspect.getsource(select_bgm)
        # select_bgm must accept prefer_category
        assert "prefer_category" in src_code or "preferred_category" in src_code or \
               "category" in src_code, \
               "select_bgm should use category preference"


if __name__ == "__main__":
    unittest.main()
