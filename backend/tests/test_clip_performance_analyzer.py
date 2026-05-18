"""Tests for ClipPerformanceAnalyzer and ClipFeaturesRepository."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.clip_features import (
    ClipFeatures,
    ClipFeaturesRepository,
    CreativeHint,
    PerformanceMetrics,
    extract_clip_features_from_meta,
)
from src.services.clip_performance_analyzer import (
    MIN_SAMPLE_SIZE,
    AggregateStat,
    ClipPerformanceAnalyzer,
    JoinedClipData,
    PatternAnalysis,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_db():
    """Create a mock AsyncSession."""
    return AsyncMock()


@pytest.fixture
def sample_features():
    """Create a sample ClipFeatures dataclass."""
    return ClipFeatures(
        clip_id="clip_1",
        duration_s=30.0,
        fps=30.0,
        num_cuts=5,
        num_brolls=3,
        talking_head_ratio=0.6,
        cut_density=0.17,
        broll_ratio_first_10s=0.5,
        has_visual_hook=True,
        hook_type="question",
        hook_duration_s=3.0,
        caption_style="dynamic",
        caption_word_count=45,
        lut_used="warm",
        color_grade_applied=True,
        zoom_punch_applied=True,
        slowmo_applied=False,
        music_present=True,
        sfx_count=2,
        voice_enhancement_applied=True,
        creative_quality_score=85.0,
        extraction_version="1.0",
    )


@pytest.fixture
def sample_metrics():
    """Create a sample PerformanceMetrics dataclass."""
    return PerformanceMetrics(
        clip_id="clip_1",
        platform="tiktok",
        views=10000,
        likes=500,
        comments=50,
        shares=200,
        saves=150,
        watch_time_s=450.0,
        avg_watch_pct=0.65,
        avg_watch_duration_s=19.5,
        like_rate=0.05,
        comment_rate=0.005,
        share_rate=0.02,
        engagement_rate=0.09,
        ctr=0.12,
        posted_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        recorded_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
        external_post_id="tiktok_12345",
    )


@pytest.fixture
def sample_joined(sample_features, sample_metrics):
    """Create a sample JoinedClipData."""
    return JoinedClipData(
        clip_id="clip_1",
        features=sample_features,
        metrics=sample_metrics,
    )


# ── ClipFeaturesRepository tests ─────────────────────────────────────────────────


class TestClipFeaturesRepository:
    """Tests for ClipFeaturesRepository static methods."""

    @pytest.mark.asyncio
    async def test_upsert_features(self, mock_db, sample_features):
        """upsert_features executes SQL and returns the row ID."""
        mock_result = MagicMock()
        mock_result.scalar.return_value = "row_1"
        mock_db.execute = AsyncMock(return_value=mock_result)

        row_id = await ClipFeaturesRepository.upsert_features(mock_db, sample_features)

        assert row_id == "row_1"
        mock_db.execute.assert_awaited_once()
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_features_found(self, mock_db, sample_features):
        """get_features returns ClipFeatures when row exists."""
        mock_row = MagicMock()
        mock_row.clip_id = "clip_1"
        mock_row.duration_s = 30.0
        mock_row.fps = 30.0
        mock_row.num_cuts = 5
        mock_row.num_brolls = 3
        mock_row.talking_head_ratio = 0.6
        mock_row.cut_density = 0.17
        mock_row.broll_ratio_first_10s = 0.5
        mock_row.has_visual_hook = True
        mock_row.hook_type = "question"
        mock_row.hook_duration_s = 3.0
        mock_row.caption_style = "dynamic"
        mock_row.caption_word_count = 45
        mock_row.lut_used = "warm"
        mock_row.color_grade_applied = True
        mock_row.zoom_punch_applied = True
        mock_row.slowmo_applied = False
        mock_row.music_present = True
        mock_row.sfx_count = 2
        mock_row.voice_enhancement_applied = True
        mock_row.creative_quality_score = 85.0
        mock_row.extraction_version = "1.0"
        mock_row.extracted_at = None
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await ClipFeaturesRepository.get_features(mock_db, "clip_1")

        assert result is not None
        assert result.clip_id == "clip_1"
        assert result.duration_s == 30.0
        assert result.hook_type == "question"
        assert result.caption_style == "dynamic"
        assert result.music_present is True
        assert result.zoom_punch_applied is True

    @pytest.mark.asyncio
    async def test_get_features_not_found(self, mock_db):
        """get_features returns None when no row exists."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await ClipFeaturesRepository.get_features(mock_db, "nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_upsert_metrics(self, mock_db, sample_metrics):
        """upsert_metrics executes SQL and returns the row ID."""
        mock_result = MagicMock()
        mock_result.scalar.return_value = "row_1"
        mock_db.execute = AsyncMock(return_value=mock_result)

        row_id = await ClipFeaturesRepository.upsert_metrics(mock_db, sample_metrics)

        assert row_id == "row_1"
        mock_db.execute.assert_awaited_once()
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_metrics_found(self, mock_db, sample_metrics):
        """get_metrics returns PerformanceMetrics when row exists."""
        mock_row = MagicMock()
        mock_row.clip_id = "clip_1"
        mock_row.platform = "tiktok"
        mock_row.external_post_id = "tiktok_12345"
        mock_row.views = 10000
        mock_row.likes = 500
        mock_row.comments = 50
        mock_row.shares = 200
        mock_row.saves = 150
        mock_row.watch_time_s = 450.0
        mock_row.avg_watch_pct = 0.65
        mock_row.avg_watch_duration_s = 19.5
        mock_row.like_rate = 0.05
        mock_row.comment_rate = 0.005
        mock_row.share_rate = 0.02
        mock_row.engagement_rate = 0.09
        mock_row.ctr = 0.12
        mock_row.posted_at = datetime(2026, 5, 1, tzinfo=timezone.utc)
        mock_row.recorded_at = datetime(2026, 5, 10, tzinfo=timezone.utc)
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await ClipFeaturesRepository.get_metrics(mock_db, "clip_1", "tiktok")

        assert result is not None
        assert result.clip_id == "clip_1"
        assert result.platform == "tiktok"
        assert result.views == 10000
        assert result.avg_watch_pct == 0.65

    @pytest.mark.asyncio
    async def test_get_metrics_not_found(self, mock_db):
        """get_metrics returns None when no row exists."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await ClipFeaturesRepository.get_metrics(mock_db, "nonexistent", "tiktok")

        assert result is None

    @pytest.mark.asyncio
    async def test_upsert_hint(self, mock_db):
        """upsert_hint executes SQL and returns the row ID."""
        hint = CreativeHint(
            workspace_id="ws_1",
            hint_type="hook",
            pattern="Questions outperform statements",
            metric="avg_watch_pct",
            delta=0.15,
            confidence="high",
            sample_size=25,
            payload={"pct_change": 0.23},
            active=True,
        )
        mock_result = MagicMock()
        mock_result.scalar.return_value = "hint_1"
        mock_db.execute = AsyncMock(return_value=mock_result)

        row_id = await ClipFeaturesRepository.upsert_hint(mock_db, hint)

        assert row_id == "hint_1"
        mock_db.execute.assert_awaited_once()
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_active_hints(self, mock_db):
        """get_active_hints returns list of CreativeHint."""
        mock_row = MagicMock()
        mock_row.id = "hint_1"
        mock_row.workspace_id = "ws_1"
        mock_row.hint_type = "hook"
        mock_row.pattern = "Questions outperform statements"
        mock_row.metric = "avg_watch_pct"
        mock_row.delta = 0.15
        mock_row.confidence = "high"
        mock_row.sample_size = 25
        mock_row.payload = '{"pct_change": 0.23}'
        mock_row.active = True
        mock_row.created_at = datetime(2026, 5, 15, tzinfo=timezone.utc)
        mock_row.updated_at = datetime(2026, 5, 15, tzinfo=timezone.utc)
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_row]
        mock_db.execute = AsyncMock(return_value=mock_result)

        hints = await ClipFeaturesRepository.get_active_hints(mock_db, "ws_1")

        assert len(hints) == 1
        assert hints[0].hint_type == "hook"
        assert hints[0].delta == 0.15
        assert hints[0].active is True

    @pytest.mark.asyncio
    async def test_get_active_hints_filtered_by_type(self, mock_db):
        """get_active_hints filters by hint_type when provided."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        hints = await ClipFeaturesRepository.get_active_hints(mock_db, "ws_1", hint_type="broll")

        assert len(hints) == 0
        # Verify the SQL was called with hint_type filter
        call_kwargs = mock_db.execute.call_args[0][1]
        assert call_kwargs["hint_type"] == "broll"

    @pytest.mark.asyncio
    async def test_deactivate_hint(self, mock_db):
        """deactivate_hint returns True when row is updated."""
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await ClipFeaturesRepository.deactivate_hint(mock_db, "hint_1")

        assert result is True
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_deactivate_hint_not_found(self, mock_db):
        """deactivate_hint returns False when no row matches."""
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await ClipFeaturesRepository.deactivate_hint(mock_db, "nonexistent")

        assert result is False

    @pytest.mark.asyncio
    async def test_delete_hints_for_workspace(self, mock_db):
        """delete_hints_for_workspace returns count of deleted rows."""
        mock_result = MagicMock()
        mock_result.rowcount = 3
        mock_db.execute = AsyncMock(return_value=mock_result)

        count = await ClipFeaturesRepository.delete_hints_for_workspace(mock_db, "ws_1")

        assert count == 3
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_hints_for_workspace_filtered(self, mock_db):
        """delete_hints_for_workspace filters by hint_type when provided."""
        mock_result = MagicMock()
        mock_result.rowcount = 2
        mock_db.execute = AsyncMock(return_value=mock_result)

        count = await ClipFeaturesRepository.delete_hints_for_workspace(
            mock_db, "ws_1", hint_type="hook"
        )

        assert count == 2

    @pytest.mark.asyncio
    async def test_get_features_batch(self, mock_db, sample_features):
        """get_features_batch returns dict of clip_id -> ClipFeatures."""
        mock_row = MagicMock()
        mock_row.clip_id = "clip_1"
        mock_row.duration_s = 30.0
        mock_row.fps = 30.0
        mock_row.num_cuts = 5
        mock_row.num_brolls = 3
        mock_row.talking_head_ratio = 0.6
        mock_row.cut_density = 0.17
        mock_row.broll_ratio_first_10s = 0.5
        mock_row.has_visual_hook = True
        mock_row.hook_type = "question"
        mock_row.hook_duration_s = 3.0
        mock_row.caption_style = "dynamic"
        mock_row.caption_word_count = 45
        mock_row.lut_used = "warm"
        mock_row.color_grade_applied = True
        mock_row.zoom_punch_applied = True
        mock_row.slowmo_applied = False
        mock_row.music_present = True
        mock_row.sfx_count = 2
        mock_row.voice_enhancement_applied = True
        mock_row.creative_quality_score = 85.0
        mock_row.extraction_version = "1.0"
        mock_row.extracted_at = None
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_row]
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await ClipFeaturesRepository.get_features_batch(mock_db, ["clip_1"])

        assert "clip_1" in result
        assert result["clip_1"].hook_type == "question"

    @pytest.mark.asyncio
    async def test_get_features_batch_empty(self, mock_db):
        """get_features_batch returns empty dict for empty input."""
        result = await ClipFeaturesRepository.get_features_batch(mock_db, [])
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_all_metrics_for_clip(self, mock_db, sample_metrics):
        """get_all_metrics_for_clip returns list of PerformanceMetrics."""
        mock_row = MagicMock()
        mock_row.clip_id = "clip_1"
        mock_row.platform = "tiktok"
        mock_row.external_post_id = "tiktok_12345"
        mock_row.views = 10000
        mock_row.likes = 500
        mock_row.comments = 50
        mock_row.shares = 200
        mock_row.saves = 150
        mock_row.watch_time_s = 450.0
        mock_row.avg_watch_pct = 0.65
        mock_row.avg_watch_duration_s = 19.5
        mock_row.like_rate = 0.05
        mock_row.comment_rate = 0.005
        mock_row.share_rate = 0.02
        mock_row.engagement_rate = 0.09
        mock_row.ctr = 0.12
        mock_row.posted_at = datetime(2026, 5, 1, tzinfo=timezone.utc)
        mock_row.recorded_at = datetime(2026, 5, 10, tzinfo=timezone.utc)
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [mock_row]
        mock_db.execute = AsyncMock(return_value=mock_result)

        metrics = await ClipFeaturesRepository.get_all_metrics_for_clip(mock_db, "clip_1")

        assert len(metrics) == 1
        assert metrics[0].platform == "tiktok"
        assert metrics[0].views == 10000


# ── extract_clip_features_from_meta tests ────────────────────────────────────────


class TestExtractClipFeaturesFromMeta:
    """Tests for the extract_clip_features_from_meta helper."""

    def test_extracts_all_fields(self):
        """All fields are extracted from creative_meta dict."""
        meta = {
            "duration_s": 45.0,
            "fps": 30.0,
            "num_cuts": 8,
            "broll_overlays": 5,
            "talking_head_ratio": 0.7,
            "cut_density": 0.18,
            "broll_ratio_first_10s": 0.6,
            "hook_reorder_applied": True,
            "hook_type": "statement",
            "hook_duration_s": 4.0,
            "caption_style": "static",
            "caption_word_count": 60,
            "lut_used": "cool",
            "color_grade_applied": True,
            "zoom_punch_applied": False,
            "speed_control_applied": True,
            "music_present": True,
            "sfx_injected": 3,
            "loudnorm_applied": True,
            "viral_score": 92.0,
        }
        features = extract_clip_features_from_meta("clip_2", meta, duration_s=45.0)

        assert features.clip_id == "clip_2"
        assert features.duration_s == 45.0
        assert features.fps == 30.0
        assert features.num_cuts == 8
        assert features.num_brolls == 5
        assert features.talking_head_ratio == 0.7
        assert features.has_visual_hook is True
        assert features.hook_type == "statement"
        assert features.caption_style == "static"
        assert features.lut_used == "cool"
        assert features.color_grade_applied is True
        assert features.zoom_punch_applied is False
        assert features.slowmo_applied is True
        assert features.music_present is True
        assert features.sfx_count == 3
        assert features.voice_enhancement_applied is True
        assert features.creative_quality_score == 92.0

    def test_handles_missing_fields(self):
        """Missing fields default to sensible values."""
        features = extract_clip_features_from_meta("clip_3", {})

        assert features.clip_id == "clip_3"
        assert features.duration_s == 0.0
        assert features.num_cuts == 0
        assert features.num_brolls == 0
        assert features.has_visual_hook is False
        assert features.music_present is False
        assert features.sfx_count == 0
        assert features.voice_enhancement_applied is False

    def test_hook_detected_via_hook_text(self):
        """has_visual_hook is True when hook_text is present."""
        meta = {"hook_text": "You won't believe this!"}
        features = extract_clip_features_from_meta("clip_4", meta)
        assert features.has_visual_hook is True


# ── ClipPerformanceAnalyzer tests ────────────────────────────────────────────────


class TestClipPerformanceAnalyzer:
    """Tests for ClipPerformanceAnalyzer static methods."""

    @pytest.mark.asyncio
    async def test_get_joined_clip_data_with_data(self, mock_db, sample_features, sample_metrics):
        """get_joined_clip_data returns JoinedClipData with features and metrics."""
        with (
            patch.object(
                ClipFeaturesRepository, "get_features", return_value=sample_features
            ) as mock_get_features,
            patch.object(
                ClipFeaturesRepository,
                "get_all_metrics_for_clip",
                return_value=[sample_metrics],
            ) as mock_get_metrics,
        ):
            result = await ClipPerformanceAnalyzer.get_joined_clip_data(mock_db, "clip_1")

        assert result.clip_id == "clip_1"
        assert result.features is not None
        assert result.features.hook_type == "question"
        assert result.metrics is not None
        assert result.metrics.avg_watch_pct == 0.65
        mock_get_features.assert_awaited_once_with(mock_db, "clip_1")
        mock_get_metrics.assert_awaited_once_with(mock_db, "clip_1")

    @pytest.mark.asyncio
    async def test_get_joined_clip_data_no_metrics(self, mock_db, sample_features):
        """get_joined_clip_data returns JoinedClipData with features but no metrics."""
        with (
            patch.object(
                ClipFeaturesRepository, "get_features", return_value=sample_features
            ),
            patch.object(
                ClipFeaturesRepository,
                "get_all_metrics_for_clip",
                return_value=[],
            ),
        ):
            result = await ClipPerformanceAnalyzer.get_joined_clip_data(mock_db, "clip_1")

        assert result.clip_id == "clip_1"
        assert result.features is not None
        assert result.metrics is None

    @pytest.mark.asyncio
    async def test_get_joined_clip_data_no_features(self, mock_db, sample_metrics):
        """get_joined_clip_data returns JoinedClipData with metrics but no features."""
        with (
            patch.object(
                ClipFeaturesRepository, "get_features", return_value=None
            ),
            patch.object(
                ClipFeaturesRepository,
                "get_all_metrics_for_clip",
                return_value=[sample_metrics],
            ),
        ):
            result = await ClipPerformanceAnalyzer.get_joined_clip_data(mock_db, "clip_1")

        assert result.clip_id == "clip_1"
        assert result.features is None
        assert result.metrics is not None

    @pytest.mark.asyncio
    async def test_get_joined_data_for_workspace(self, mock_db, sample_features, sample_metrics):
        """get_joined_data_for_workspace returns all joined data."""
        with (
            patch.object(
                ClipFeaturesRepository,
                "get_all_features_for_workspace",
                return_value=[sample_features],
            ),
            patch.object(
                ClipFeaturesRepository,
                "get_all_metrics_for_workspace",
                return_value=[sample_metrics],
            ),
        ):
            results = await ClipPerformanceAnalyzer.get_joined_data_for_workspace(
                mock_db, "ws_1"
            )

        assert len(results) == 1
        assert results[0].clip_id == "clip_1"
        assert results[0].features is not None
        assert results[0].metrics is not None

    @pytest.mark.asyncio
    async def test_get_joined_data_for_workspace_empty(self, mock_db):
        """get_joined_data_for_workspace returns empty list when no data."""
        with (
            patch.object(
                ClipFeaturesRepository,
                "get_all_features_for_workspace",
                return_value=[],
            ),
            patch.object(
                ClipFeaturesRepository,
                "get_all_metrics_for_workspace",
                return_value=[],
            ),
        ):
            results = await ClipPerformanceAnalyzer.get_joined_data_for_workspace(
                mock_db, "ws_empty"
            )

        assert len(results) == 0

    # ── compute_aggregates tests ─────────────────────────────────────────────

    def test_compute_aggregates_empty(self):
        """compute_aggregates returns empty stats for empty input."""
        result = ClipPerformanceAnalyzer.compute_aggregates([])
        assert result["total_clips"] == 0

    def test_compute_aggregates_no_metrics(self, sample_features):
        """compute_aggregates handles clips without metrics."""
        joined = [
            JoinedClipData(clip_id="clip_1", features=sample_features, metrics=None),
        ]
        result = ClipPerformanceAnalyzer.compute_aggregates(joined)
        assert result["total_clips"] == 1
        assert result["clips_with_data"] == 0

    def test_compute_aggregates_full(self, sample_joined):
        """compute_aggregates computes all stats correctly."""
        result = ClipPerformanceAnalyzer.compute_aggregates([sample_joined])

        assert result["total_clips"] == 1
        assert result["clips_with_data"] == 1
        assert result["avg_duration_s"] == 30.0
        assert "hook_type_distribution" in result
        assert result["hook_type_distribution"]["question"] == 1
        assert "avg_watch_pct_by_hook_type" in result
        assert result["avg_watch_pct_by_hook_type"]["question"] == 0.65
        assert "caption_style_distribution" in result
        assert result["caption_style_distribution"]["dynamic"] == 1

    def test_compute_aggregates_multiple_clips(self):
        """compute_aggregates handles multiple clips with different characteristics."""
        clips = []
        for i in range(3):
            f = ClipFeatures(
                clip_id=f"clip_{i}",
                duration_s=30.0 + i * 10,
                num_brolls=i,
                has_visual_hook=(i % 2 == 0),
                hook_type="question" if i % 2 == 0 else "statement",
                caption_style="dynamic",
                music_present=(i < 2),
                zoom_punch_applied=(i == 0),
                sfx_count=i,
                talking_head_ratio=0.5,
            )
            m = PerformanceMetrics(
                clip_id=f"clip_{i}",
                platform="tiktok",
                views=1000 * (i + 1),
                avg_watch_pct=0.5 + i * 0.1,
                engagement_rate=0.05 + i * 0.02,
            )
            clips.append(JoinedClipData(clip_id=f"clip_{i}", features=f, metrics=m))

        result = ClipPerformanceAnalyzer.compute_aggregates(clips)

        assert result["total_clips"] == 3
        assert result["clips_with_data"] == 3
        assert result["avg_duration_s"] == 40.0  # (30+40+50)/3
        assert result["hook_type_distribution"]["question"] == 2
        assert result["hook_type_distribution"]["statement"] == 1
        # question avg_watch_pct = (0.5+0.7)/2 = 0.6
        assert result["avg_watch_pct_by_hook_type"]["question"] == 0.6
        # statement avg_watch_pct = 0.6
        assert result["avg_watch_pct_by_hook_type"]["statement"] == 0.6

    # ── _compute_confidence tests ────────────────────────────────────────────

    def test_compute_confidence_high(self):
        """_compute_confidence returns 'high' for >= 30 samples."""
        assert ClipPerformanceAnalyzer._compute_confidence(30) == "high"
        assert ClipPerformanceAnalyzer._compute_confidence(50) == "high"

    def test_compute_confidence_medium(self):
        """_compute_confidence returns 'medium' for 15-29 samples."""
        assert ClipPerformanceAnalyzer._compute_confidence(15) == "medium"
        assert ClipPerformanceAnalyzer._compute_confidence(20) == "medium"

    def test_compute_confidence_low(self):
        """_compute_confidence returns 'low' for < 15 samples."""
        assert ClipPerformanceAnalyzer._compute_confidence(5) == "low"
        assert ClipPerformanceAnalyzer._compute_confidence(14) == "low"

    # ── _analyze_binary_pattern tests ────────────────────────────────────────

    def test_analyze_binary_pattern_significant(self):
        """_analyze_binary_pattern returns PatternAnalysis when delta >= MIN_DELTA."""
        variant = [
            JoinedClipData(
                clip_id=f"v_{i}",
                features=ClipFeatures(clip_id=f"v_{i}", num_brolls=3),
                metrics=PerformanceMetrics(
                    clip_id=f"v_{i}", platform="tiktok", avg_watch_pct=0.7
                ),
            )
            for i in range(6)
        ]
        baseline = [
            JoinedClipData(
                clip_id=f"b_{i}",
                features=ClipFeatures(clip_id=f"b_{i}", num_brolls=0),
                metrics=PerformanceMetrics(
                    clip_id=f"b_{i}", platform="tiktok", avg_watch_pct=0.5
                ),
            )
            for i in range(6)
        ]

        result = ClipPerformanceAnalyzer._analyze_binary_pattern(
            label="Test pattern",
            hint_type="test",
            metric_key="avg_watch_pct",
            variant_group=variant,
            baseline_group=baseline,
            metric_extractor=lambda j: j.metrics.avg_watch_pct,
        )

        assert result is not None
        assert result.pattern == "Test pattern"
        assert result.hint_type == "test"
        assert result.delta == pytest.approx(0.2)  # 0.7 - 0.5
        assert result.pct_change == pytest.approx(0.4)  # 0.2 / 0.5
        assert result.sample_size == 12
        assert result.confidence == "low"  # 12 < 15

    def test_analyze_binary_pattern_insufficient_samples(self):
        """_analyze_binary_pattern returns None when total samples < MIN_SAMPLE_SIZE."""
        variant = [
            JoinedClipData(
                clip_id="v_1",
                features=ClipFeatures(clip_id="v_1"),
                metrics=PerformanceMetrics(clip_id="v_1", platform="tiktok", avg_watch_pct=0.7),
            )
        ]
        baseline = [
            JoinedClipData(
                clip_id="b_1",
                features=ClipFeatures(clip_id="b_1"),
                metrics=PerformanceMetrics(clip_id="b_1", platform="tiktok", avg_watch_pct=0.5),
            )
        ]

        result = ClipPerformanceAnalyzer._analyze_binary_pattern(
            label="Test",
            hint_type="test",
            metric_key="avg_watch_pct",
            variant_group=variant,
            baseline_group=baseline,
            metric_extractor=lambda j: j.metrics.avg_watch_pct,
        )

        assert result is None

    def test_analyze_binary_pattern_small_delta(self):
        """_analyze_binary_pattern returns None when delta < MIN_DELTA."""
        variant = [
            JoinedClipData(
                clip_id=f"v_{i}",
                features=ClipFeatures(clip_id=f"v_{i}"),
                metrics=PerformanceMetrics(
                    clip_id=f"v_{i}", platform="tiktok", avg_watch_pct=0.51
                ),
            )
            for i in range(6)
        ]
        baseline = [
            JoinedClipData(
                clip_id=f"b_{i}",
                features=ClipFeatures(clip_id=f"b_{i}"),
                metrics=PerformanceMetrics(
                    clip_id=f"b_{i}", platform="tiktok", avg_watch_pct=0.50
                ),
            )
            for i in range(6)
        ]

        result = ClipPerformanceAnalyzer._analyze_binary_pattern(
            label="Test",
            hint_type="test",
            metric_key="avg_watch_pct",
            variant_group=variant,
            baseline_group=baseline,
            metric_extractor=lambda j: j.metrics.avg_watch_pct,
        )

        assert result is None

    def test_analyze_binary_pattern_empty_group(self):
        """_analyze_binary_pattern returns None when one group is empty."""
        variant = [
            JoinedClipData(
                clip_id=f"v_{i}",
                features=ClipFeatures(clip_id=f"v_{i}"),
                metrics=PerformanceMetrics(
                    clip_id=f"v_{i}", platform="tiktok", avg_watch_pct=0.7
                ),
            )
            for i in range(6)
        ]

        result = ClipPerformanceAnalyzer._analyze_binary_pattern(
            label="Test",
            hint_type="test",
            metric_key="avg_watch_pct",
            variant_group=variant,
            baseline_group=[],
            metric_extractor=lambda j: j.metrics.avg_watch_pct,
        )

        assert result is None

    # ── _analyze_multi_category_pattern tests ────────────────────────────────

    def test_analyze_multi_category_pattern(self):
        """_analyze_multi_category_pattern returns patterns for categories with enough samples."""
        groups = {
            "type_a": [
                JoinedClipData(
                    clip_id=f"a_{i}",
                    features=ClipFeatures(clip_id=f"a_{i}"),
                    metrics=PerformanceMetrics(
                        clip_id=f"a_{i}", platform="tiktok", avg_watch_pct=0.8
                    ),
                )
                for i in range(6)
            ],
            "type_b": [
                JoinedClipData(
                    clip_id=f"b_{i}",
                    features=ClipFeatures(clip_id=f"b_{i}"),
                    metrics=PerformanceMetrics(
                        clip_id=f"b_{i}", platform="tiktok", avg_watch_pct=0.4
                    ),
                )
                for i in range(6)
            ],
        }

        results = ClipPerformanceAnalyzer._analyze_multi_category_pattern(
            label_template="Type '{category}' pattern",
            hint_type="test",
            metric_key="avg_watch_pct",
            groups=groups,
            metric_extractor=lambda j: j.metrics.avg_watch_pct,
        )

        # Overall avg = (0.8*6 + 0.4*6) / 12 = 0.6
        # type_a delta = 0.8 - 0.6 = 0.2 >= 0.05 ✓
        # type_b delta = 0.4 - 0.6 = -0.2, abs=0.2 >= 0.05 ✓
        assert len(results) == 2
        type_a = [r for r in results if "type_a" in r.pattern][0]
        type_b = [r for r in results if "type_b" in r.pattern][0]
        assert type_a.delta == pytest.approx(0.2)
        assert type_b.delta == pytest.approx(-0.2)

    def test_analyze_multi_category_pattern_insufficient(self):
        """_analyze_multi_category_pattern skips categories below MIN_SAMPLE_SIZE."""
        groups = {
            "small": [
                JoinedClipData(
                    clip_id=f"s_{i}",
                    features=ClipFeatures(clip_id=f"s_{i}"),
                    metrics=PerformanceMetrics(
                        clip_id=f"s_{i}", platform="tiktok", avg_watch_pct=0.9
                    ),
                )
                for i in range(3)  # Only 3 samples, below MIN_SAMPLE_SIZE
            ],
            "large": [
                JoinedClipData(
                    clip_id=f"l_{i}",
                    features=ClipFeatures(clip_id=f"l_{i}"),
                    metrics=PerformanceMetrics(
                        clip_id=f"l_{i}", platform="tiktok", avg_watch_pct=0.6
                    ),
                )
                for i in range(12)  # 12 samples, above MIN_SAMPLE_SIZE
            ],
        }

        results = ClipPerformanceAnalyzer._analyze_multi_category_pattern(
            label_template="Category '{category}' pattern",
            hint_type="test",
            metric_key="avg_watch_pct",
            groups=groups,
            metric_extractor=lambda j: j.metrics.avg_watch_pct,
        )

        # Only "large" should appear (12 >= 10), "small" should be skipped (3 < 10)
        assert len(results) == 1
        assert "large" in results[0].pattern
        assert "small" not in results[0].pattern

    # ── _run_all_pattern_analyses tests ──────────────────────────────────────

    def test_run_all_pattern_analyses_returns_multiple_patterns(self):
        """_run_all_pattern_analyses returns patterns for various dimensions."""
        clips = []
        for i in range(15):
            f = ClipFeatures(
                clip_id=f"c_{i}",
                duration_s=30.0,
                num_brolls=3 if i < 8 else 0,
                has_visual_hook=(i < 10),
                hook_type="question" if i < 8 else "statement",
                caption_style="dynamic" if i < 7 else "static",
                music_present=(i < 9),
                zoom_punch_applied=(i < 6),
                sfx_count=2 if i < 8 else 0,
                talking_head_ratio=0.6 if i < 8 else 0.2,
            )
            m = PerformanceMetrics(
                clip_id=f"c_{i}",
                platform="tiktok",
                avg_watch_pct=0.7 if i < 8 else 0.4,
            )
            clips.append(JoinedClipData(clip_id=f"c_{i}", features=f, metrics=m))

        patterns = ClipPerformanceAnalyzer._run_all_pattern_analyses(clips)

        # Should find patterns for hook_type, caption_style, broll, music, hook, zoom, duration, sfx, talking_head
        assert len(patterns) > 0
        hint_types = {p.hint_type for p in patterns}
        assert "hook" in hint_types
        assert "caption_style" in hint_types
        assert "broll" in hint_types
        assert "audio" in hint_types
        assert "pacing" in hint_types
        assert "duration" in hint_types

    def test_run_all_pattern_analyses_insufficient_data(self):
        """_run_all_pattern_analyses returns empty list when data is insufficient."""
        clips = [
            JoinedClipData(
                clip_id=f"c_{i}",
                features=ClipFeatures(clip_id=f"c_{i}", duration_s=30.0),
                metrics=PerformanceMetrics(clip_id=f"c_{i}", platform="tiktok", avg_watch_pct=0.5),
            )
            for i in range(3)  # Only 3 clips, below MIN_SAMPLE_SIZE for any pattern
        ]

        patterns = ClipPerformanceAnalyzer._run_all_pattern_analyses(clips)

        assert len(patterns) == 0

    # ── suggest_creative_adjustments tests ────────────────────────────────────

    @pytest.mark.asyncio
    async def test_suggest_creative_adjustments_generates_hints(self, mock_db):
        """suggest_creative_adjustments generates and persists CreativeHints."""
        clips = []
        for i in range(15):
            f = ClipFeatures(
                clip_id=f"c_{i}",
                duration_s=30.0,
                num_brolls=3 if i < 10 else 0,
                has_visual_hook=(i < 10),
                hook_type="question" if i < 10 else "statement",
                caption_style="dynamic",
                music_present=True,
                zoom_punch_applied=(i < 8),
                sfx_count=2,
                talking_head_ratio=0.6,
            )
            m = PerformanceMetrics(
                clip_id=f"c_{i}",
                platform="tiktok",
                avg_watch_pct=0.7 if i < 10 else 0.4,
            )
            clips.append(JoinedClipData(clip_id=f"c_{i}", features=f, metrics=m))

        with (
            patch.object(
                ClipPerformanceAnalyzer,
                "get_joined_data_for_workspace",
                return_value=clips,
            ),
            patch.object(
                ClipFeaturesRepository, "upsert_hint", return_value="hint_id"
            ) as mock_upsert,
        ):
            hints = await ClipPerformanceAnalyzer.suggest_creative_adjustments(
                mock_db, "ws_1"
            )

        assert len(hints) > 0
        assert mock_upsert.await_count == len(hints)
        for h in hints:
            assert h.workspace_id == "ws_1"
            assert h.active is True
            assert h.sample_size >= 10

    @pytest.mark.asyncio
    async def test_suggest_creative_adjustments_insufficient_data(self, mock_db):
        """suggest_creative_adjustments returns empty list when < MIN_SAMPLE_SIZE clips."""
        clips = [
            JoinedClipData(
                clip_id=f"c_{i}",
                features=ClipFeatures(clip_id=f"c_{i}"),
                metrics=PerformanceMetrics(clip_id=f"c_{i}", platform="tiktok", avg_watch_pct=0.5),
            )
            for i in range(3)
        ]

        with patch.object(
            ClipPerformanceAnalyzer,
            "get_joined_data_for_workspace",
            return_value=clips,
        ):
            hints = await ClipPerformanceAnalyzer.suggest_creative_adjustments(
                mock_db, "ws_1"
            )

        assert len(hints) == 0

    @pytest.mark.asyncio
    async def test_suggest_creative_adjustments_no_metrics(self, mock_db):
        """suggest_creative_adjustments returns empty when no clips have metrics."""
        clips = [
            JoinedClipData(
                clip_id=f"c_{i}",
                features=ClipFeatures(clip_id=f"c_{i}"),
                metrics=None,
            )
            for i in range(15)
        ]

        with patch.object(
            ClipPerformanceAnalyzer,
            "get_joined_data_for_workspace",
            return_value=clips,
        ):
            hints = await ClipPerformanceAnalyzer.suggest_creative_adjustments(
                mock_db, "ws_1"
            )

        assert len(hints) == 0

    # ── get_dashboard_data tests ─────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_dashboard_data_returns_all_sections(self, mock_db, sample_features, sample_metrics):
        """get_dashboard_data returns aggregates, hints, top_performers, recent_clips."""
        joined = JoinedClipData(
            clip_id="clip_1",
            features=sample_features,
            metrics=sample_metrics,
        )
        mock_hint = CreativeHint(
            workspace_id="ws_1",
            hint_type="hook",
            pattern="Questions outperform statements",
            metric="avg_watch_pct",
            delta=0.15,
            confidence="high",
            sample_size=25,
            payload={"pct_change": 0.23},
            active=True,
            id="hint_1",
        )

        with (
            patch.object(
                ClipPerformanceAnalyzer,
                "get_joined_data_for_workspace",
                return_value=[joined],
            ),
            patch.object(
                ClipFeaturesRepository,
                "get_active_hints",
                return_value=[mock_hint],
            ),
        ):
            data = await ClipPerformanceAnalyzer.get_dashboard_data(mock_db, "ws_1")

        assert "aggregates" in data
        assert data["aggregates"]["total_clips"] == 1
        assert "hints" in data
        assert len(data["hints"]) == 1
        assert data["hints"][0]["hint_type"] == "hook"
        assert "top_performers" in data
        assert len(data["top_performers"]) == 1
        assert data["top_performers"][0]["clip_id"] == "clip_1"
        assert "recent_clips" in data
        assert len(data["recent_clips"]) == 1

    @pytest.mark.asyncio
    async def test_get_dashboard_data_empty_workspace(self, mock_db):
        """get_dashboard_data returns empty sections for workspace with no data."""
        with (
            patch.object(
                ClipPerformanceAnalyzer,
                "get_joined_data_for_workspace",
                return_value=[],
            ),
            patch.object(
                ClipFeaturesRepository,
                "get_active_hints",
                return_value=[],
            ),
        ):
            data = await ClipPerformanceAnalyzer.get_dashboard_data(mock_db, "ws_empty")

        assert data["aggregates"]["total_clips"] == 0
        assert len(data["hints"]) == 0
        assert len(data["top_performers"]) == 0
        assert len(data["recent_clips"]) == 0

    @pytest.mark.asyncio
    async def test_get_dashboard_data_top_performers_limited_to_10(self, mock_db):
        """get_dashboard_data limits top_performers to 10 entries."""
        clips = []
        for i in range(15):
            f = ClipFeatures(
                clip_id=f"c_{i}",
                duration_s=30.0,
                hook_type="question",
                caption_style="dynamic",
            )
            m = PerformanceMetrics(
                clip_id=f"c_{i}",
                platform="tiktok",
                avg_watch_pct=0.5 + i * 0.03,
                views=1000 * (i + 1),
                engagement_rate=0.05,
                recorded_at=datetime(2026, 5, i + 1, tzinfo=timezone.utc),
            )
            clips.append(JoinedClipData(clip_id=f"c_{i}", features=f, metrics=m))

        with (
            patch.object(
                ClipPerformanceAnalyzer,
                "get_joined_data_for_workspace",
                return_value=clips,
            ),
            patch.object(
                ClipFeaturesRepository,
                "get_active_hints",
                return_value=[],
            ),
        ):
            data = await ClipPerformanceAnalyzer.get_dashboard_data(mock_db, "ws_1")

        assert len(data["top_performers"]) == 10
        assert len(data["recent_clips"]) == 10
        # Verify sorted by avg_watch_pct descending
        watch_pcts = [p["avg_watch_pct"] for p in data["top_performers"]]
        assert watch_pcts == sorted(watch_pcts, reverse=True)
