"""
Tests for Videofy integration: schemas_v2, asset_analysis, project_store, timeline_builder, timeline_renderer.
"""

import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

from src.schemas_v2 import (
    TextLine, SegmentAsset, Segment, ClipTimeline,
    DEFAULT_CAMERA_MOVEMENTS, VALID_CAMERA_MOVEMENTS
)
from src.project_store import ProjectStore
from src.asset_analysis import extract_frames_from_clip, describe_frame, assign_frames_to_segments
from src.services.timeline_builder import build_clip_timeline
from src.services.timeline_renderer import (
    build_ass_subtitles, build_camera_filter, apply_timeline_to_clip,
    get_segment_at_time, _sec_to_ass
)


# ── Schemas ──────────────────────────────────────────────────────────────────


class TestSchemas:
    
    def test_text_line_creation(self):
        tl = TextLine(line_id=0, text="hello world", start=1.0, end=2.0)
        assert tl.line_id == 0
        assert tl.text == "hello world"
        assert tl.start == 1.0
        assert tl.end == 2.0
        assert tl.who == "default"
    
    def test_segment_asset_types(self):
        asset1 = SegmentAsset(type="frame", path="/path/to/frame.jpg")
        assert asset1.type == "frame"
        
        asset2 = SegmentAsset(type="broll", path="/path/to/broll.mp4", url="https://pexels.com/video/123")
        assert asset2.url == "https://pexels.com/video/123"
    
    def test_segment_defaults(self):
        seg = Segment(
            id=0,
            texts=[TextLine(line_id=0, text="test", start=0.0, end=1.0)],
            start=0.0,
            end=1.0
        )
        assert seg.virality_score == 0.0
        assert seg.hook_type == "none"
        assert seg.mood == "neutral"
        assert seg.camera_movement == "none"
        assert seg.style == "bottom"
    
    def test_clip_timeline_duration(self):
        timeline = ClipTimeline(
            clip_id="test-clip",
            task_id="task-123",
            source_url="",
            segments=[
                Segment(id=0, texts=[], start=0.0, end=3.0),
                Segment(id=1, texts=[], start=3.0, end=6.0),
            ],
            total_duration=6.0
        )
        assert timeline.total_duration == 6.0
        assert len(timeline.segments) == 2
    
    def test_valid_camera_movements(self):
        assert "zoom-in" in VALID_CAMERA_MOVEMENTS
        assert "pan-left" in VALID_CAMERA_MOVEMENTS
        assert len(DEFAULT_CAMERA_MOVEMENTS) == 6


# ── ProjectStore ─────────────────────────────────────────────────────────────


class TestProjectStore:
    
    def test_project_paths(self, tmp_path):
        store = ProjectStore(base_dir=str(tmp_path))
        task_id = "test-task-123"
        
        assert store.project_path(task_id) == tmp_path / task_id
        assert store.input_path(task_id) == tmp_path / task_id / "input"
        assert store.working_path(task_id) == tmp_path / task_id / "working"
        assert store.output_path(task_id) == tmp_path / task_id / "output"
        assert store.analysis_path(task_id) == tmp_path / task_id / "working" / "analysis"
        assert store.frames_path(task_id) == tmp_path / task_id / "working" / "analysis" / "frames"
    
    def test_save_and_load_json(self, tmp_path):
        store = ProjectStore(base_dir=str(tmp_path))
        task_id = "test-123"
        
        data = {"key": "value", "count": 42}
        store.save_json(task_id, "test.json", data)
        
        loaded = store.load_json(task_id, "test.json")
        assert loaded == data
    
    def test_save_json_in_analysis(self, tmp_path):
        store = ProjectStore(base_dir=str(tmp_path))
        task_id = "test-123"
        
        data = {"frames": [{"id": "f001"}]}
        store.save_json(task_id, "frames.json", data, folder="analysis")
        
        loaded = store.load_json(task_id, "frames.json", folder="analysis")
        assert loaded == data
    
    def test_is_step_done(self, tmp_path):
        store = ProjectStore(base_dir=str(tmp_path))
        task_id = "test-123"
        
        assert not store.is_step_done(task_id, "transcript")
        
        store.save_json(task_id, "transcript.json", {"text": "hello"})
        assert store.is_step_done(task_id, "transcript")
    
    def test_cleanup_working(self, tmp_path):
        store = ProjectStore(base_dir=str(tmp_path))
        task_id = "test-123"
        
        store.save_json(task_id, "temp.json", {})
        working = store.working_path(task_id)
        assert working.exists()
        
        store.cleanup_working(task_id)
        assert not working.exists()
    
    def test_cleanup_project(self, tmp_path):
        store = ProjectStore(base_dir=str(tmp_path))
        task_id = "test-123"
        
        store.save_json(task_id, "data.json", {})
        project = store.project_path(task_id)
        assert project.exists()
        
        store.cleanup_project(task_id)
        assert not project.exists()


# ── Asset Analysis ───────────────────────────────────────────────────────────


class TestAssetAnalysis:
    
    @pytest.mark.asyncio
    async def test_extract_frames_from_clip(self, tmp_path):
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake video")
        output_dir = tmp_path / "frames"
        
        with patch("subprocess.run") as mock_run:
            # Mock ffprobe duration
            mock_run.return_value = MagicMock(stdout="10.0", returncode=0)
            
            # Mock successful ffmpeg frame extraction
            def side_effect(cmd, *args, **kwargs):
                if "ffmpeg" in cmd[0]:
                    # Create fake frame file
                    frame_path = Path(cmd[-1])
                    frame_path.write_bytes(b"fake frame")
                return MagicMock(returncode=0)
            
            mock_run.side_effect = side_effect
            
            frames = extract_frames_from_clip(video, output_dir, "clip-1", n_frames=4)
            
            assert len(frames) == 4
            assert all("id" in f for f in frames)
            assert all("time_seconds" in f for f in frames)
    
    def test_describe_frame_with_openai(self, tmp_path):
        frame = tmp_path / "frame.jpg"
        frame.write_bytes(b"\xff\xd8\xff\xe0" + b"fake jpeg")
        
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "A person speaking enthusiastically"
        mock_client.chat.completions.create.return_value = mock_response
        
        description = describe_frame(frame, mock_client)
        
        assert description == "A person speaking enthusiastically"
        assert mock_client.chat.completions.create.called
    
    def test_describe_frame_failure(self, tmp_path):
        frame = tmp_path / "nonexistent.jpg"
        mock_client = MagicMock()
        
        description = describe_frame(frame, mock_client)
        assert description == ""
    
    def test_assign_frames_cyclic_fallback(self):
        segments = ["intro", "main point", "conclusion"]
        frames = [
            {"id": "f001", "description": "frame 1"},
            {"id": "f002", "description": "frame 2"},
        ]
        
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API error")
        
        assignments = assign_frames_to_segments(segments, frames, mock_client)
        
        assert len(assignments) == 3
        assert assignments == ["f001", "f002", "f001"]  # cyclic


# ── Timeline Builder ─────────────────────────────────────────────────────────


class TestTimelineBuilder:
    
    @pytest.mark.asyncio
    async def test_build_clip_timeline_basic(self, tmp_path):
        store = ProjectStore(base_dir=str(tmp_path))
        task_id = "test-123"
        
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")
        
        whisper_words = [
            {"word": "hello", "start": 0.0, "end": 0.5},
            {"word": "world", "start": 0.6, "end": 1.0},
        ]
        
        ai_segments = [
            {
                "text": "hello world",
                "start_time": 0.0,
                "end_time": 1.0,
                "virality_score": 85.0,
                "hook_score": 20.0,
                "hook_type": "question",
                "mood": "hype",
            }
        ]
        
        timeline = await build_clip_timeline(
            task_id=task_id,
            video_path=video,
            whisper_words=whisper_words,
            ai_segments=ai_segments,
            store=store,
            openai_client=None,  # Skip Vision AI
            skip_vision=True,
        )
        
        assert timeline.task_id == task_id
        assert len(timeline.segments) == 1
        assert timeline.segments[0].virality_score == 85.0
        assert timeline.segments[0].hook_type == "question"
        assert timeline.segments[0].mood == "hype"
        assert timeline.segments[0].camera_movement in DEFAULT_CAMERA_MOVEMENTS
    
    @pytest.mark.asyncio
    async def test_build_timeline_groups_words_into_lines(self, tmp_path):
        store = ProjectStore(base_dir=str(tmp_path))
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")
        
        # 8 words should create 2 text lines (4 words each)
        whisper_words = [
            {"word": f"word{i}", "start": float(i), "end": float(i+0.5)}
            for i in range(8)
        ]
        
        ai_segments = [{"text": "segment", "start_time": 0.0, "end_time": 8.0}]
        
        timeline = await build_clip_timeline(
            task_id="test",
            video_path=video,
            whisper_words=whisper_words,
            ai_segments=ai_segments,
            store=store,
            openai_client=None,
            skip_vision=True,
        )
        
        assert len(timeline.segments[0].texts) >= 2


# ── Timeline Renderer ────────────────────────────────────────────────────────


class TestTimelineRenderer:
    
    def test_sec_to_ass(self):
        assert _sec_to_ass(0.0) == "0:00:00.00"
        assert _sec_to_ass(65.5) == "0:01:05.50"
        assert _sec_to_ass(3661.25) == "1:01:01.25"
    
    def test_build_ass_subtitles(self):
        timeline = ClipTimeline(
            clip_id="test",
            task_id="task",
            source_url="",
            segments=[
                Segment(
                    id=0,
                    texts=[
                        TextLine(line_id=0, text="hello", start=1.0, end=2.0),
                        TextLine(line_id=1, text="world", start=2.0, end=3.0),
                    ],
                    start=1.0,
                    end=3.0,
                )
            ],
            total_duration=2.0,
        )
        
        ass = build_ass_subtitles(timeline)
        
        assert "[Script Info]" in ass
        assert "[V4+ Styles]" in ass
        assert "[Events]" in ass
        assert "HELLO" in ass
        assert "WORLD" in ass
        assert "0:00:01.00" in ass
    
    def test_build_camera_filter_zoom_in(self):
        timeline = ClipTimeline(
            clip_id="test",
            task_id="task",
            source_url="",
            segments=[
                Segment(
                    id=0,
                    camera_movement="zoom-in",
                    texts=[],
                    start=0.0,
                    end=3.0,
                )
            ],
            total_duration=3.0,
        )
        
        filter_str = build_camera_filter(timeline, fps=25)
        
        assert filter_str is not None
        assert "zoompan" in filter_str
        assert "d=75" in filter_str  # 3s * 25fps
    
    def test_build_camera_filter_none_movement(self):
        timeline = ClipTimeline(
            clip_id="test",
            task_id="task",
            source_url="",
            segments=[
                Segment(
                    id=0,
                    camera_movement="none",
                    texts=[],
                    start=0.0,
                    end=3.0,
                )
            ],
            total_duration=3.0,
        )
        
        filter_str = build_camera_filter(timeline)
        assert filter_str is None
    
    @pytest.mark.asyncio
    async def test_apply_timeline_to_clip(self, tmp_path):
        timeline = ClipTimeline(
            clip_id="test",
            task_id="task",
            source_url="",
            segments=[
                Segment(
                    id=0,
                    camera_movement="zoom-in",
                    texts=[TextLine(line_id=0, text="test", start=0.0, end=1.0)],
                    start=0.0,
                    end=1.0,
                )
            ],
            total_duration=1.0,
        )
        
        source = tmp_path / "source.mp4"
        source.write_bytes(b"fake video")
        output = tmp_path / "output.mp4"
        
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            # Create fake output
            output.write_bytes(b"rendered video")
            
            result = await apply_timeline_to_clip(timeline, source, output)
            
            assert result == output
            assert output.exists()
    
    def test_get_segment_at_time(self):
        timeline = ClipTimeline(
            clip_id="test",
            task_id="task",
            source_url="",
            segments=[
                Segment(id=0, texts=[], start=0.0, end=3.0),
                Segment(id=1, texts=[], start=3.0, end=6.0),
                Segment(id=2, texts=[], start=6.0, end=9.0),
            ],
            total_duration=9.0,
        )
        
        assert get_segment_at_time(timeline, 1.5) == 0
        assert get_segment_at_time(timeline, 4.0) == 1
        assert get_segment_at_time(timeline, 7.5) == 2
        assert get_segment_at_time(timeline, 10.0) is None
