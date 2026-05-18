"""
Tests for the Editlist Service — declarative JSON editlist for video editing.

Tests cover:
  - Editlist serialization/deserialization (to_json / from_json)
  - get_safe_editlist() — cuts/concat only filtering
  - generate_from_segments() — creating editlists from segment data
  - Feature flag filtering in EditlistService
  - EditOperation and Editlist dataclass behavior
  - count_by_type() operation counting
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
from datetime import datetime, timezone


# =============================================================================
# Editlist Data Model Tests
# =============================================================================

class TestEditlistDataModel:
    """Tests for Editlist and EditOperation dataclasses."""

    def test_edit_operation_auto_generates_id(self):
        """EditOperation must auto-generate an operation_id if not provided."""
        from src.services.editlist_service import EditOperation, EditOpType

        op = EditOperation(op_type=EditOpType.CUT, params={"source_path": "/tmp/video.mp4"})

        assert op.operation_id.startswith("cut_"), \
            f"operation_id should start with 'cut_', got '{op.operation_id}'"
        assert len(op.operation_id) > 4, "operation_id should have a UUID suffix"

    def test_edit_operation_with_custom_id(self):
        """EditOperation must accept a custom operation_id."""
        from src.services.editlist_service import EditOperation, EditOpType

        op = EditOperation(
            op_type=EditOpType.CONCAT,
            params={"segment_paths": []},
            operation_id="my-custom-id",
        )

        assert op.operation_id == "my-custom-id"

    def test_edit_operation_default_enabled(self):
        """EditOperation must default to enabled=True."""
        from src.services.editlist_service import EditOperation, EditOpType

        op = EditOperation(op_type=EditOpType.CUT)

        assert op.enabled is True

    def test_editlist_default_version(self):
        """Editlist must default to version '1.0'."""
        from src.services.editlist_service import Editlist

        editlist = Editlist()

        assert editlist.version == "1.0"

    def test_editlist_auto_created_at(self):
        """Editlist must auto-generate created_at if not provided."""
        from src.services.editlist_service import Editlist

        editlist = Editlist()

        assert editlist.created_at != "", "created_at should be auto-generated"
        # Verify it's a valid ISO format
        datetime.fromisoformat(editlist.created_at)

    def test_editlist_default_safe_mode(self):
        """Editlist must default to safe_mode=False."""
        from src.services.editlist_service import Editlist

        editlist = Editlist()

        assert editlist.safe_mode is False


# =============================================================================
# Editlist Serialization Tests
# =============================================================================

class TestEditlistSerialization:
    """Tests for Editlist.to_json() and Editlist.from_json()."""

    def test_to_json_roundtrip(self):
        """Serializing and deserializing must produce an identical editlist."""
        from src.services.editlist_service import (
            Editlist, EditOperation, EditOpType, OverlayStyle, TransitionType,
        )

        original = Editlist(
            clip_id="clip-123",
            task_id="task-456",
            source_path="/tmp/source.mp4",
            operations=[
                EditOperation(
                    op_type=EditOpType.CUT,
                    params={"source_path": "/tmp/source.mp4", "start_offset": 0.0, "end_offset": 10.0},
                    operation_id="cut_001",
                ),
                EditOperation(
                    op_type=EditOpType.CONCAT,
                    params={"segment_paths": ["/tmp/seg1.mp4", "/tmp/seg2.mp4"]},
                    operation_id="concat_001",
                ),
                EditOperation(
                    op_type=EditOpType.OVERLAY,
                    params={
                        "overlay_path": "/tmp/overlay.png",
                        "style": OverlayStyle.PICTURE_IN_PICTURE.value,
                        "start_time": 0.0,
                        "duration": 5.0,
                    },
                    operation_id="overlay_001",
                ),
                EditOperation(
                    op_type=EditOpType.TRANSITION,
                    params={
                        "transition_type": TransitionType.CROSSFADE.value,
                        "duration": 0.5,
                        "from_segment_index": 0,
                        "to_segment_index": 1,
                    },
                    operation_id="trans_001",
                ),
            ],
        )

        # Serialize
        json_str = original.to_json()
        assert isinstance(json_str, str), "to_json must return a string"

        # Deserialize
        restored = Editlist.from_json(json_str)

        # Verify fields
        assert restored.clip_id == original.clip_id
        assert restored.task_id == original.task_id
        assert restored.source_path == original.source_path
        assert restored.version == original.version
        assert len(restored.operations) == len(original.operations)

        # Verify operations
        for i, op in enumerate(restored.operations):
            assert op.op_type == original.operations[i].op_type
            assert op.operation_id == original.operations[i].operation_id
            assert op.enabled == original.operations[i].enabled
            assert op.params == original.operations[i].params

    def test_from_json_with_dict(self):
        """from_json must accept a dict as well as a string."""
        from src.services.editlist_service import Editlist, EditOpType

        data = {
            "version": "1.0",
            "created_at": "2026-05-16T00:00:00+00:00",
            "clip_id": "clip-789",
            "task_id": "task-789",
            "source_path": "/tmp/video.mp4",
            "safe_mode": False,
            "operations": [
                {
                    "op_type": "cut",
                    "params": {"source_path": "/tmp/video.mp4", "start_offset": 0.0, "end_offset": 5.0},
                    "operation_id": "cut_abc",
                    "enabled": True,
                },
            ],
        }

        editlist = Editlist.from_json(data)
        assert editlist.clip_id == "clip-789"
        assert len(editlist.operations) == 1
        assert editlist.operations[0].op_type == EditOpType.CUT
        assert editlist.operations[0].params["start_offset"] == 0.0

    def test_to_json_contains_all_fields(self):
        """to_json must include all expected fields."""
        from src.services.editlist_service import Editlist, EditOperation, EditOpType

        editlist = Editlist(
            clip_id="clip-xyz",
            task_id="task-xyz",
            source_path="/tmp/vid.mp4",
            operations=[
                EditOperation(op_type=EditOpType.CUT, params={}, operation_id="cut_1"),
            ],
        )

        parsed = json.loads(editlist.to_json())
        assert "version" in parsed
        assert "created_at" in parsed
        assert "clip_id" in parsed
        assert "task_id" in parsed
        assert "source_path" in parsed
        assert "safe_mode" in parsed
        assert "operations" in parsed
        assert len(parsed["operations"]) == 1
        assert parsed["operations"][0]["op_type"] == "cut"
        assert parsed["operations"][0]["operation_id"] == "cut_1"


# =============================================================================
# get_safe_editlist Tests
# =============================================================================

class TestGetSafeEditlist:
    """Tests for Editlist.get_safe_editlist()."""

    def test_removes_overlays_and_transitions(self):
        """get_safe_editlist must remove OVERLAY and TRANSITION operations."""
        from src.services.editlist_service import (
            Editlist, EditOperation, EditOpType,
        )

        editlist = Editlist(
            operations=[
                EditOperation(op_type=EditOpType.CUT, params={}, operation_id="cut_1"),
                EditOperation(op_type=EditOpType.CONCAT, params={}, operation_id="concat_1"),
                EditOperation(op_type=EditOpType.OVERLAY, params={}, operation_id="overlay_1"),
                EditOperation(op_type=EditOpType.TRANSITION, params={}, operation_id="trans_1"),
            ],
        )

        safe = editlist.get_safe_editlist()

        assert len(safe.operations) == 2, "Safe editlist should have 2 ops (cut + concat)"
        assert safe.operations[0].op_type == EditOpType.CUT
        assert safe.operations[1].op_type == EditOpType.CONCAT
        assert safe.safe_mode is True

    def test_preserves_cuts_and_concat(self):
        """get_safe_editlist must preserve all CUT and CONCAT operations."""
        from src.services.editlist_service import (
            Editlist, EditOperation, EditOpType,
        )

        editlist = Editlist(
            operations=[
                EditOperation(op_type=EditOpType.CUT, params={}, operation_id="cut_1"),
                EditOperation(op_type=EditOpType.CUT, params={}, operation_id="cut_2"),
                EditOperation(op_type=EditOpType.CONCAT, params={}, operation_id="concat_1"),
            ],
        )

        safe = editlist.get_safe_editlist()

        assert len(safe.operations) == 3
        assert safe.operations[0].operation_id == "cut_1"
        assert safe.operations[1].operation_id == "cut_2"
        assert safe.operations[2].operation_id == "concat_1"

    def test_empty_editlist_returns_empty(self):
        """get_safe_editlist on an empty editlist must return an empty editlist."""
        from src.services.editlist_service import Editlist

        editlist = Editlist()
        safe = editlist.get_safe_editlist()

        assert len(safe.operations) == 0
        assert safe.safe_mode is True

    def test_only_overlays_returns_empty(self):
        """get_safe_editlist on an editlist with only overlays must return empty."""
        from src.services.editlist_service import (
            Editlist, EditOperation, EditOpType,
        )

        editlist = Editlist(
            operations=[
                EditOperation(op_type=EditOpType.OVERLAY, params={}, operation_id="overlay_1"),
                EditOperation(op_type=EditOpType.TRANSITION, params={}, operation_id="trans_1"),
            ],
        )

        safe = editlist.get_safe_editlist()
        assert len(safe.operations) == 0


# =============================================================================
# count_by_type Tests
# =============================================================================

class TestCountByType:
    """Tests for Editlist.count_by_type()."""

    def test_counts_operations_by_type(self):
        """count_by_type must return correct counts per operation type."""
        from src.services.editlist_service import (
            Editlist, EditOperation, EditOpType,
        )

        editlist = Editlist(
            operations=[
                EditOperation(op_type=EditOpType.CUT, params={}),
                EditOperation(op_type=EditOpType.CUT, params={}),
                EditOperation(op_type=EditOpType.CONCAT, params={}),
                EditOperation(op_type=EditOpType.OVERLAY, params={}),
                EditOperation(op_type=EditOpType.TRANSITION, params={}),
            ],
        )

        counts = editlist.count_by_type()
        assert counts["cut"] == 2
        assert counts["concat"] == 1
        assert counts["overlay"] == 1
        assert counts["transition"] == 1

    def test_counts_only_enabled_operations(self):
        """count_by_type must only count enabled operations."""
        from src.services.editlist_service import (
            Editlist, EditOperation, EditOpType,
        )

        editlist = Editlist(
            operations=[
                EditOperation(op_type=EditOpType.CUT, params={}, enabled=True),
                EditOperation(op_type=EditOpType.CUT, params={}, enabled=False),
                EditOperation(op_type=EditOpType.CONCAT, params={}, enabled=True),
                EditOperation(op_type=EditOpType.OVERLAY, params={}, enabled=False),
            ],
        )

        counts = editlist.count_by_type()
        assert counts["cut"] == 1  # only the enabled one
        assert counts["concat"] == 1
        assert "overlay" not in counts  # disabled, not counted

    def test_empty_editlist_returns_empty_counts(self):
        """count_by_type on an empty editlist must return empty dict."""
        from src.services.editlist_service import Editlist

        editlist = Editlist()
        counts = editlist.count_by_type()
        assert counts == {}


# =============================================================================
# generate_from_segments Tests
# =============================================================================

class TestGenerateFromSegments:
    """Tests for EditlistService.generate_from_segments()."""

    @pytest.fixture
    def service_with_all_enabled(self):
        """Create an EditlistService with all feature flags enabled."""
        from src.services.editlist_service import EditlistService

        mock_config = MagicMock()
        mock_config.editlist_enable_cuts = True
        mock_config.editlist_enable_overlays = True
        mock_config.editlist_enable_transitions = True
        mock_config.editlist_enabled = True

        return EditlistService(config=mock_config)

    @pytest.fixture
    def service_with_cuts_only(self):
        """Create an EditlistService with only cuts enabled."""
        from src.services.editlist_service import EditlistService

        mock_config = MagicMock()
        mock_config.editlist_enable_cuts = True
        mock_config.editlist_enable_overlays = False
        mock_config.editlist_enable_transitions = False
        mock_config.editlist_enabled = True

        return EditlistService(config=mock_config)

    def test_generates_cuts_for_each_segment(self, service_with_cuts_only):
        """generate_from_segments must create a CUT operation per segment."""
        segments = [
            {"source_path": "/tmp/video.mp4", "start_offset": 0.0, "end_offset": 10.0},
            {"source_path": "/tmp/video.mp4", "start_offset": 10.0, "end_offset": 20.0},
            {"source_path": "/tmp/video.mp4", "start_offset": 20.0, "end_offset": 30.0},
        ]

        editlist = service_with_cuts_only.generate_from_segments(
            segments, clip_id="clip-1", task_id="task-1", source_path="/tmp/video.mp4",
        )

        cuts = [op for op in editlist.operations if op.op_type.value == "cut"]
        assert len(cuts) == 3, "Should create 3 CUT operations for 3 segments"

        for i, cut in enumerate(cuts):
            assert cut.params["segment_index"] == i
            assert cut.params["start_offset"] == segments[i]["start_offset"]
            assert cut.params["end_offset"] == segments[i]["end_offset"]

    def test_generates_concat_for_multiple_segments(self, service_with_cuts_only):
        """generate_from_segments must create a CONCAT operation for >1 segments."""
        segments = [
            {"source_path": "/tmp/video.mp4", "start_offset": 0.0, "end_offset": 10.0},
            {"source_path": "/tmp/video.mp4", "start_offset": 10.0, "end_offset": 20.0},
        ]

        editlist = service_with_cuts_only.generate_from_segments(
            segments, clip_id="clip-2", task_id="task-2",
        )

        concats = [op for op in editlist.operations if op.op_type.value == "concat"]
        assert len(concats) == 1, "Should create 1 CONCAT operation"
        assert concats[0].params["segment_count"] == 2

    def test_no_concat_for_single_segment(self, service_with_cuts_only):
        """generate_from_segments must NOT create CONCAT for a single segment."""
        segments = [
            {"source_path": "/tmp/video.mp4", "start_offset": 0.0, "end_offset": 10.0},
        ]

        editlist = service_with_cuts_only.generate_from_segments(
            segments, clip_id="clip-3", task_id="task-3",
        )

        concats = [op for op in editlist.operations if op.op_type.value == "concat"]
        assert len(concats) == 0, "Should NOT create CONCAT for single segment"

    def test_generates_overlays_when_enabled(self, service_with_all_enabled):
        """generate_from_segments must create OVERLAY operations when enabled."""
        segments = [
            {
                "source_path": "/tmp/video.mp4",
                "start_offset": 0.0,
                "end_offset": 10.0,
                "overlay": {
                    "path": "/tmp/overlay.png",
                    "style": "picture_in_picture",
                    "start_time": 2.0,
                    "duration": 5.0,
                },
            },
        ]

        editlist = service_with_all_enabled.generate_from_segments(
            segments, clip_id="clip-4", task_id="task-4",
        )

        overlays = [op for op in editlist.operations if op.op_type.value == "overlay"]
        assert len(overlays) == 1
        assert overlays[0].params["overlay_path"] == "/tmp/overlay.png"
        assert overlays[0].params["style"] == "picture_in_picture"

    def test_skips_overlays_when_disabled(self, service_with_cuts_only):
        """generate_from_segments must skip OVERLAY operations when disabled."""
        segments = [
            {
                "source_path": "/tmp/video.mp4",
                "start_offset": 0.0,
                "end_offset": 10.0,
                "overlay": {
                    "path": "/tmp/overlay.png",
                    "style": "picture_in_picture",
                },
            },
        ]

        editlist = service_with_cuts_only.generate_from_segments(
            segments, clip_id="clip-5", task_id="task-5",
        )

        overlays = [op for op in editlist.operations if op.op_type.value == "overlay"]
        assert len(overlays) == 0, "Overlays should be skipped when disabled"

    def test_generates_transitions_when_enabled(self, service_with_all_enabled):
        """generate_from_segments must create TRANSITION operations when enabled."""
        segments = [
            {
                "source_path": "/tmp/video.mp4",
                "start_offset": 0.0,
                "end_offset": 10.0,
                "transition": {"type": "crossfade", "duration": 0.5},
            },
            {
                "source_path": "/tmp/video.mp4",
                "start_offset": 10.0,
                "end_offset": 20.0,
            },
        ]

        editlist = service_with_all_enabled.generate_from_segments(
            segments, clip_id="clip-6", task_id="task-6",
        )

        transitions = [op for op in editlist.operations if op.op_type.value == "transition"]
        assert len(transitions) == 1
        assert transitions[0].params["transition_type"] == "crossfade"
        assert transitions[0].params["duration"] == 0.5

    def test_skips_transitions_when_disabled(self, service_with_cuts_only):
        """generate_from_segments must skip TRANSITION operations when disabled."""
        segments = [
            {
                "source_path": "/tmp/video.mp4",
                "start_offset": 0.0,
                "end_offset": 10.0,
                "transition": {"type": "crossfade", "duration": 0.5},
            },
            {
                "source_path": "/tmp/video.mp4",
                "start_offset": 10.0,
                "end_offset": 20.0,
            },
        ]

        editlist = service_with_cuts_only.generate_from_segments(
            segments, clip_id="clip-7", task_id="task-7",
        )

        transitions = [op for op in editlist.operations if op.op_type.value == "transition"]
        assert len(transitions) == 0, "Transitions should be skipped when disabled"

    def test_sets_clip_and_task_ids(self, service_with_cuts_only):
        """generate_from_segments must set clip_id and task_id on the editlist."""
        segments = [
            {"source_path": "/tmp/video.mp4", "start_offset": 0.0, "end_offset": 10.0},
        ]

        editlist = service_with_cuts_only.generate_from_segments(
            segments, clip_id="my-clip", task_id="my-task", source_path="/tmp/video.mp4",
        )

        assert editlist.clip_id == "my-clip"
        assert editlist.task_id == "my-task"
        assert editlist.source_path == "/tmp/video.mp4"


# =============================================================================
# Feature Flag Filtering Tests
# =============================================================================

class TestFeatureFlagFiltering:
    """Tests for EditlistService._filter_enabled_ops()."""

    @pytest.fixture
    def service(self):
        """Create an EditlistService with specific feature flags."""
        from src.services.editlist_service import EditlistService

        mock_config = MagicMock()
        mock_config.editlist_enable_cuts = True
        mock_config.editlist_enable_overlays = False
        mock_config.editlist_enable_transitions = False
        mock_config.editlist_enabled = True

        return EditlistService(config=mock_config)

    def test_filters_disabled_overlays(self, service):
        """_filter_enabled_ops must remove OVERLAY operations when disabled."""
        from src.services.editlist_service import Editlist, EditOperation, EditOpType

        editlist = Editlist(operations=[
            EditOperation(op_type=EditOpType.CUT, params={}),
            EditOperation(op_type=EditOpType.OVERLAY, params={}),
            EditOperation(op_type=EditOpType.CONCAT, params={}),
        ])

        filtered = service._filter_enabled_ops(editlist)
        assert len(filtered) == 2
        assert all(op.op_type != EditOpType.OVERLAY for op in filtered)

    def test_filters_disabled_transitions(self, service):
        """_filter_enabled_ops must remove TRANSITION operations when disabled."""
        from src.services.editlist_service import Editlist, EditOperation, EditOpType

        editlist = Editlist(operations=[
            EditOperation(op_type=EditOpType.CUT, params={}),
            EditOperation(op_type=EditOpType.TRANSITION, params={}),
        ])

        filtered = service._filter_enabled_ops(editlist)
        assert len(filtered) == 1
        assert filtered[0].op_type == EditOpType.CUT

    def test_preserves_enabled_cuts_and_concat(self, service):
        """_filter_enabled_ops must preserve CUT and CONCAT when enabled."""
        from src.services.editlist_service import Editlist, EditOperation, EditOpType

        editlist = Editlist(operations=[
            EditOperation(op_type=EditOpType.CUT, params={}),
            EditOperation(op_type=EditOpType.CONCAT, params={}),
        ])

        filtered = service._filter_enabled_ops(editlist)
        assert len(filtered) == 2

    def test_skips_disabled_operations(self, service):
        """_filter_enabled_ops must skip operations with enabled=False."""
        from src.services.editlist_service import Editlist, EditOperation, EditOpType

        editlist = Editlist(operations=[
            EditOperation(op_type=EditOpType.CUT, params={}, enabled=True),
            EditOperation(op_type=EditOpType.CUT, params={}, enabled=False),
        ])

        filtered = service._filter_enabled_ops(editlist)
        assert len(filtered) == 1

    def test_feature_flag_properties(self):
        """EditlistService feature flag properties must reflect config."""
        from src.services.editlist_service import EditlistService

        mock_config = MagicMock()
        mock_config.editlist_enable_cuts = True
        mock_config.editlist_enable_overlays = False
        mock_config.editlist_enable_transitions = True
        mock_config.editlist_enabled = True

        service = EditlistService(config=mock_config)
        assert service.cuts_enabled is True
        assert service.overlays_enabled is False
        assert service.transitions_enabled is True
        assert service.editlist_enabled is True


# =============================================================================
# Persistence Tests
# =============================================================================

class TestEditlistPersistence:
    """Tests for EditlistService.save_editlist() and load_editlist()."""

    @pytest.mark.asyncio
    async def test_save_and_load_editlist(self, tmp_path):
        """save_editlist and load_editlist must roundtrip correctly."""
        from src.services.editlist_service import (
            EditlistService, Editlist, EditOperation, EditOpType,
        )

        original = Editlist(
            clip_id="clip-persist",
            task_id="task-persist",
            source_path="/tmp/video.mp4",
            operations=[
                EditOperation(op_type=EditOpType.CUT, params={"start_offset": 0.0}),
                EditOperation(op_type=EditOpType.CONCAT, params={}),
            ],
        )

        file_path = tmp_path / "test_editlist.json"
        await EditlistService.save_editlist(original, file_path)

        assert file_path.exists(), "Editlist file must exist after save"

        loaded = await EditlistService.load_editlist(file_path)
        assert loaded.clip_id == original.clip_id
        assert loaded.task_id == original.task_id
        assert len(loaded.operations) == len(original.operations)
        assert loaded.operations[0].op_type == EditOpType.CUT
        assert loaded.operations[1].op_type == EditOpType.CONCAT

    @pytest.mark.asyncio
    async def test_save_creates_parent_dirs(self, tmp_path):
        """save_editlist must create parent directories if they don't exist."""
        from src.services.editlist_service import (
            EditlistService, Editlist, EditOperation, EditOpType,
        )

        editlist = Editlist(
            operations=[EditOperation(op_type=EditOpType.CUT, params={})],
        )

        deep_path = tmp_path / "subdir" / "nested" / "editlist.json"
        await EditlistService.save_editlist(editlist, deep_path)

        assert deep_path.exists(), "File must be created in nested directories"

    @pytest.mark.asyncio
    async def test_save_and_load_from_redis(self):
        """save_editlist_to_redis and load_editlist_from_redis must roundtrip."""
        from src.services.editlist_service import (
            EditlistService, Editlist, EditOperation, EditOpType,
        )

        original = Editlist(
            clip_id="clip-redis",
            task_id="task-redis-1",
            source_path="/tmp/video.mp4",
            operations=[
                EditOperation(op_type=EditOpType.CUT, params={"start_offset": 0.0}),
            ],
        )

        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock(return_value=True)
        mock_redis.get = AsyncMock(return_value=original.to_json())
        mock_redis.aclose = AsyncMock()

        # from_url is a coroutine function, so we need to return an awaitable
        async def mock_from_url(*args, **kwargs):
            return mock_redis

        with patch("redis.asyncio.from_url", side_effect=mock_from_url):
            # Save to Redis
            await EditlistService.save_editlist_to_redis(original, "task-redis-1")
            mock_redis.setex.assert_called_once()

            # Load from Redis
            loaded = await EditlistService.load_editlist_from_redis("task-redis-1")
            assert loaded is not None
            assert loaded.clip_id == original.clip_id
            assert loaded.task_id == original.task_id
            assert len(loaded.operations) == 1
            assert loaded.operations[0].op_type == EditOpType.CUT

    @pytest.mark.asyncio
    async def test_load_from_redis_returns_none_if_not_found(self):
        """load_editlist_from_redis must return None if key doesn't exist."""
        from src.services.editlist_service import EditlistService

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.aclose = AsyncMock()

        async def mock_from_url(*args, **kwargs):
            return mock_redis

        with patch("redis.asyncio.from_url", side_effect=mock_from_url):
            result = await EditlistService.load_editlist_from_redis("nonexistent-task")
            assert result is None


# =============================================================================
# apply_safe Tests
# =============================================================================

class TestApplySafe:
    """Tests for EditlistService.apply_safe()."""

    @pytest.mark.asyncio
    async def test_apply_safe_creates_safe_editlist(self, tmp_path):
        """apply_safe must create a safe editlist (cuts/concat only)."""
        from src.services.editlist_service import (
            EditlistService, Editlist, EditOperation, EditOpType,
        )

        mock_config = MagicMock()
        mock_config.editlist_enable_cuts = True
        mock_config.editlist_enable_overlays = False
        mock_config.editlist_enable_transitions = False
        mock_config.editlist_enabled = True

        service = EditlistService(config=mock_config)

        editlist = Editlist(
            clip_id="clip-safe",
            task_id="task-safe",
            source_path="/tmp/video.mp4",
            operations=[
                EditOperation(op_type=EditOpType.CUT, params={"source_path": "/tmp/video.mp4"}),
                EditOperation(op_type=EditOpType.OVERLAY, params={}),
                EditOperation(op_type=EditOpType.TRANSITION, params={}),
            ],
        )

        # Mock the apply method to avoid actual video processing
        with patch.object(service, 'apply', new_callable=AsyncMock) as mock_apply:
            mock_apply.return_value = tmp_path / "safe_output.mp4"

            result = await service.apply_safe(editlist, tmp_path)

            # Verify apply was called with a safe editlist
            call_args = mock_apply.call_args[0]
            safe_editlist = call_args[0]
            assert safe_editlist.safe_mode is True
            assert len(safe_editlist.operations) == 1  # only CUT
            assert safe_editlist.operations[0].op_type == EditOpType.CUT

    @pytest.mark.asyncio
    async def test_apply_safe_preserves_original(self, tmp_path):
        """apply_safe must not modify the original editlist."""
        from src.services.editlist_service import (
            EditlistService, Editlist, EditOperation, EditOpType,
        )

        mock_config = MagicMock()
        mock_config.editlist_enable_cuts = True
        mock_config.editlist_enable_overlays = False
        mock_config.editlist_enable_transitions = False
        mock_config.editlist_enabled = True

        service = EditlistService(config=mock_config)

        original_ops_count = 3
        editlist = Editlist(
            clip_id="clip-orig",
            operations=[
                EditOperation(op_type=EditOpType.CUT, params={}),
                EditOperation(op_type=EditOpType.OVERLAY, params={}),
                EditOperation(op_type=EditOpType.TRANSITION, params={}),
            ],
        )

        with patch.object(service, 'apply', new_callable=AsyncMock) as mock_apply:
            mock_apply.return_value = tmp_path / "safe_output.mp4"
            await service.apply_safe(editlist, tmp_path)

            # Original must be unchanged
            assert len(editlist.operations) == original_ops_count
            assert editlist.safe_mode is False
