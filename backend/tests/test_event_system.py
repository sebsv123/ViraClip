"""
Tests for the ViraClip Event System.

Coverage:
  - PipelineEvent: construction, serialisation, SSE name mapping, terminals
  - EventType constants and SSE_EVENT_NAME map completeness
  - SSE bridge: named event format, heartbeat, error helper
  - EventBus.publish: delegates to Redis publish
  - EventBus.subscribe: yields PipelineEvents from Redis pub/sub
  - EventBus.is_active: reads PUBSUB NUMSUB
  - ProgressTracker.update: writes setex + publishes via EventBus
  - ProgressTracker.clip_ready / complete / error
  - progress_emitter facade: all public functions delegate to EventBus
  - SSE route: StreamingResponse, named events, terminal closes stream
  - Legacy from_dict compat: old ProgressTracker format (no event_type)
"""
import asyncio
import json
import sys
import types
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Pre-stub heavy optional deps so imports below never fail in test env
# ---------------------------------------------------------------------------
for _stub in ["redis", "redis.asyncio"]:
    if _stub not in sys.modules:
        _m = types.ModuleType(_stub)
        sys.modules[_stub] = _m

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------
from src.events.types import EventType, PipelineEvent, SSE_EVENT_NAME
from src.events.sse_bridge import (
    event_to_sse,
    make_connected_sse,
    make_error_sse,
    make_heartbeat_sse,
)


# ===========================================================================
# Helpers
# ===========================================================================

def _make_event(**kwargs) -> PipelineEvent:
    defaults = dict(
        task_id="task-abc-12345678",
        event_type=EventType.ANALYSIS,
        stage="analysis",
        progress=30,
        message="Analysing…",
    )
    defaults.update(kwargs)
    return PipelineEvent(**defaults)


async def _one_shot_gen(events):
    """Async generator that yields the given events then stops."""
    for e in events:
        yield e


# ===========================================================================
# 1. PipelineEvent — construction & serialisation
# ===========================================================================

class TestPipelineEvent:

    def test_required_fields(self):
        ev = _make_event()
        assert ev.task_id == "task-abc-12345678"
        assert ev.event_type == EventType.ANALYSIS
        assert ev.stage == "analysis"
        assert ev.progress == 30
        assert ev.message == "Analysing…"

    def test_optional_fields_default_none(self):
        ev = _make_event()
        assert ev.clip_id is None
        assert ev.clip_index is None
        assert ev.total_clips is None
        assert ev.clip_data is None
        assert ev.error_code is None
        assert ev.metadata is None
        assert ev.status is None

    def test_to_dict_omits_none(self):
        ev = _make_event()
        d = ev.to_dict()
        assert "clip_id" not in d
        assert "clip_index" not in d
        assert d["task_id"] == "task-abc-12345678"
        assert d["progress"] == 30

    def test_to_dict_includes_non_none_optional(self):
        ev = _make_event(clip_id="c1", clip_index=0, total_clips=3)
        d = ev.to_dict()
        assert d["clip_id"] == "c1"
        assert d["clip_index"] == 0
        assert d["total_clips"] == 3

    def test_from_dict_roundtrip(self):
        ev = _make_event(clip_id="c1", status="processing")
        d = ev.to_dict()
        ev2 = PipelineEvent.from_dict(d)
        assert ev2.task_id == ev.task_id
        assert ev2.event_type == ev.event_type
        assert ev2.progress == ev.progress
        assert ev2.clip_id == "c1"

    def test_timestamp_auto_set(self):
        import time
        before = time.time()
        ev = _make_event()
        after = time.time()
        assert before <= ev.timestamp <= after


# ===========================================================================
# 2. EventType + SSE name mapping
# ===========================================================================

class TestEventTypeMapping:

    def test_all_event_types_have_sse_name(self):
        for attr in vars(EventType):
            if attr.startswith("_") or attr == "TERMINAL":
                continue
            val = getattr(EventType, attr)
            if isinstance(val, str):
                assert val in SSE_EVENT_NAME, f"{val!r} missing from SSE_EVENT_NAME"

    def test_sse_event_name_property(self):
        assert _make_event(event_type=EventType.CONNECTED).sse_event_name == "status"
        assert _make_event(event_type=EventType.ANALYSIS).sse_event_name == "progress"
        assert _make_event(event_type=EventType.TRANSCRIPTION).sse_event_name == "progress"
        assert _make_event(event_type=EventType.SCORING).sse_event_name == "progress"
        assert _make_event(event_type=EventType.RENDER).sse_event_name == "progress"
        assert _make_event(event_type=EventType.CLIP_READY).sse_event_name == "clip_ready"
        assert _make_event(event_type=EventType.DONE).sse_event_name == "close"
        assert _make_event(event_type=EventType.ERROR).sse_event_name == "error"
        assert _make_event(event_type=EventType.CACHE_HIT).sse_event_name == "close"

    def test_unknown_event_type_defaults_to_progress(self):
        ev = _make_event(event_type="some_future_type")
        assert ev.sse_event_name == "progress"

    def test_terminal_events(self):
        assert _make_event(event_type=EventType.DONE).is_terminal is True
        assert _make_event(event_type=EventType.ERROR).is_terminal is True
        assert _make_event(event_type=EventType.CACHE_HIT).is_terminal is True

    def test_non_terminal_events(self):
        for et in [EventType.ANALYSIS, EventType.SCORING, EventType.RENDER, EventType.CLIP_READY]:
            assert _make_event(event_type=et).is_terminal is False


# ===========================================================================
# 3. Legacy from_dict compatibility (old ProgressTracker format)
# ===========================================================================

class TestFromDictLegacy:

    def test_legacy_processing_status(self):
        old = {"task_id": "t1", "progress": 45, "message": "Going…", "status": "processing"}
        ev = PipelineEvent.from_dict(old)
        assert ev.event_type == EventType.ANALYSIS
        assert ev.progress == 45
        assert ev.stage == EventType.ANALYSIS

    def test_legacy_completed_status(self):
        old = {"task_id": "t1", "progress": 100, "message": "Done", "status": "completed"}
        ev = PipelineEvent.from_dict(old)
        assert ev.event_type == EventType.DONE
        assert ev.is_terminal is True

    def test_legacy_error_status(self):
        old = {"task_id": "t1", "progress": 0, "message": "Boom", "status": "error"}
        ev = PipelineEvent.from_dict(old)
        assert ev.event_type == EventType.ERROR
        assert ev.is_terminal is True

    def test_legacy_missing_message(self):
        old = {"task_id": "t1", "progress": 20, "status": "processing"}
        ev = PipelineEvent.from_dict(old)
        assert ev.message == ""

    def test_legacy_missing_progress(self):
        old = {"task_id": "t1", "message": "hi", "status": "processing"}
        ev = PipelineEvent.from_dict(old)
        assert ev.progress == 0

    def test_extra_keys_ignored(self):
        data = {
            "task_id": "t1", "event_type": "scoring", "stage": "scoring",
            "progress": 55, "message": "ok",
            "unknown_future_field": "value",
        }
        ev = PipelineEvent.from_dict(data)
        assert ev.event_type == "scoring"


# ===========================================================================
# 4. SSE bridge
# ===========================================================================

class TestSseBridge:

    def test_event_to_sse_has_event_line(self):
        ev = _make_event(event_type=EventType.SCORING, progress=55)
        sse = event_to_sse(ev)
        assert sse.startswith("event: progress\n")
        assert "data: " in sse
        assert sse.endswith("\n\n")

    def test_event_to_sse_data_is_valid_json(self):
        ev = _make_event(event_type=EventType.CLIP_READY, clip_index=0, total_clips=3)
        sse = event_to_sse(ev)
        data_line = [l for l in sse.split("\n") if l.startswith("data: ")][0]
        payload = json.loads(data_line[6:])
        assert payload["event_type"] == EventType.CLIP_READY
        assert payload["clip_index"] == 0

    def test_clip_ready_sse_event_name(self):
        ev = _make_event(event_type=EventType.CLIP_READY)
        sse = event_to_sse(ev)
        assert sse.startswith("event: clip_ready\n")

    def test_done_sse_event_name(self):
        ev = _make_event(event_type=EventType.DONE, progress=100)
        sse = event_to_sse(ev)
        assert sse.startswith("event: close\n")

    def test_error_sse_event_name(self):
        ev = _make_event(event_type=EventType.ERROR, progress=0)
        sse = event_to_sse(ev)
        assert sse.startswith("event: error\n")

    def test_make_connected_sse(self):
        sse = make_connected_sse("task-xyz")
        assert "event: status\n" in sse
        data = json.loads(sse.split("data: ")[1].strip())
        assert data["task_id"] == "task-xyz"
        assert data["progress"] == 0

    def test_make_error_sse(self):
        sse = make_error_sse("task-xyz", "boom!")
        assert "event: error\n" in sse
        data = json.loads(sse.split("data: ")[1].strip())
        assert data["error"] == "boom!"

    def test_make_heartbeat_sse(self):
        hb = make_heartbeat_sse()
        assert hb.startswith(": ")
        assert hb.endswith("\n\n")


# ===========================================================================
# 5. EventBus
# ===========================================================================

class TestEventBus:

    @pytest.mark.asyncio
    async def test_publish_calls_redis_publish(self):
        from src.events.bus import EventBus

        mock_redis = MagicMock()
        mock_redis.publish = AsyncMock(return_value=1)

        with patch("src.events.bus._get_redis", AsyncMock(return_value=mock_redis)):
            ev = _make_event(event_type=EventType.SCORING, progress=50)
            await EventBus.publish(ev)

        mock_redis.publish.assert_awaited_once()
        channel, payload = mock_redis.publish.call_args[0]
        assert channel == f"progress:{ev.task_id}"
        data = json.loads(payload)
        assert data["event_type"] == EventType.SCORING
        assert data["progress"] == 50

    @pytest.mark.asyncio
    async def test_publish_does_not_raise_on_redis_error(self):
        from src.events.bus import EventBus

        mock_redis = MagicMock()
        mock_redis.publish = AsyncMock(side_effect=ConnectionError("Redis down"))

        with patch("src.events.bus._get_redis", AsyncMock(return_value=mock_redis)):
            ev = _make_event()
            await EventBus.publish(ev)  # should not raise

    @pytest.mark.asyncio
    async def test_subscribe_yields_pipeline_events(self):
        from src.events.bus import EventBus

        events_to_emit = [
            _make_event(event_type=EventType.ANALYSIS, progress=10),
            _make_event(event_type=EventType.SCORING, progress=50),
            _make_event(event_type=EventType.DONE, progress=100),
        ]

        messages = [
            {"type": "message", "data": json.dumps(e.to_dict())}
            for e in events_to_emit
        ]
        messages.insert(0, {"type": "subscribe", "data": 1})

        async def fake_listen():
            for m in messages:
                yield m

        pubsub_mock = MagicMock()
        pubsub_mock.subscribe = AsyncMock()
        pubsub_mock.unsubscribe = AsyncMock()
        pubsub_mock.close = AsyncMock()
        pubsub_mock.listen = MagicMock(return_value=fake_listen())

        mock_redis = MagicMock()
        mock_redis.pubsub = MagicMock(return_value=pubsub_mock)

        received = []
        with patch("src.events.bus._get_redis", AsyncMock(return_value=mock_redis)):
            async for event in EventBus.subscribe("task-abc-12345678"):
                received.append(event)

        assert len(received) == 3
        assert received[0].event_type == EventType.ANALYSIS
        assert received[1].event_type == EventType.SCORING
        assert received[2].event_type == EventType.DONE

    @pytest.mark.asyncio
    async def test_is_active_true_when_subscribers(self):
        from src.events.bus import EventBus

        mock_redis = MagicMock()
        mock_redis.execute_command = AsyncMock(return_value=["progress:t", 2])

        with patch("src.events.bus._get_redis", AsyncMock(return_value=mock_redis)):
            assert await EventBus.is_active("t") is True

    @pytest.mark.asyncio
    async def test_is_active_false_when_no_subscribers(self):
        from src.events.bus import EventBus

        mock_redis = MagicMock()
        mock_redis.execute_command = AsyncMock(return_value=["progress:t", 0])

        with patch("src.events.bus._get_redis", AsyncMock(return_value=mock_redis)):
            assert await EventBus.is_active("t") is False

    @pytest.mark.asyncio
    async def test_is_active_false_on_error(self):
        from src.events.bus import EventBus

        mock_redis = MagicMock()
        mock_redis.execute_command = AsyncMock(side_effect=RuntimeError("boom"))

        with patch("src.events.bus._get_redis", AsyncMock(return_value=mock_redis)):
            assert await EventBus.is_active("t") is False


# ===========================================================================
# 6. ProgressTracker
# ===========================================================================

class TestProgressTracker:

    def _tracker(self, task_id="task-abc-12345678"):
        from src.workers.progress import ProgressTracker
        redis_mock = MagicMock()
        redis_mock.setex = AsyncMock(return_value=True)
        redis_mock.get = AsyncMock(return_value=None)
        return ProgressTracker(redis_mock, task_id), redis_mock

    @pytest.mark.asyncio
    async def test_update_writes_setex(self):
        tracker, redis_mock = self._tracker()
        with patch("src.events.bus.EventBus.publish", AsyncMock()):
            await tracker.update(55, "half way", "processing")
        redis_mock.setex.assert_awaited_once()
        key, ttl, raw = redis_mock.setex.call_args[0]
        assert key == f"progress:{tracker.task_id}"
        assert ttl == 3600
        snapshot = json.loads(raw)
        assert snapshot["progress"] == 55
        assert snapshot["status"] == "processing"

    @pytest.mark.asyncio
    async def test_update_publishes_via_event_bus(self):
        tracker, _ = self._tracker()
        with patch("src.events.bus.EventBus.publish", AsyncMock()) as mock_pub:
            await tracker.update(75, "almost done", "processing")
        mock_pub.assert_awaited_once()
        event = mock_pub.call_args[0][0]
        assert isinstance(event, PipelineEvent)
        assert event.progress == 75
        assert event.event_type == EventType.ANALYSIS

    @pytest.mark.asyncio
    async def test_update_completed_emits_done_event(self):
        tracker, _ = self._tracker()
        with patch("src.events.bus.EventBus.publish", AsyncMock()) as mock_pub:
            await tracker.update(100, "done!", "completed")
        event = mock_pub.call_args[0][0]
        assert event.event_type == EventType.DONE
        assert event.is_terminal is True

    @pytest.mark.asyncio
    async def test_update_error_status_emits_error_event(self):
        tracker, _ = self._tracker()
        with patch("src.events.bus.EventBus.publish", AsyncMock()) as mock_pub:
            await tracker.update(0, "kaboom", "error")
        event = mock_pub.call_args[0][0]
        assert event.event_type == EventType.ERROR

    @pytest.mark.asyncio
    async def test_clip_ready_emits_clip_ready_event(self):
        tracker, _ = self._tracker()
        clip_data = {"id": "clip-1", "path": "/app/temp/clip_001.mp4"}
        with patch("src.events.bus.EventBus.publish", AsyncMock()) as mock_pub:
            await tracker.clip_ready(0, 3, clip_data)
        event = mock_pub.call_args[0][0]
        assert event.event_type == EventType.CLIP_READY
        assert event.clip_index == 0
        assert event.total_clips == 3
        assert event.clip_data == clip_data
        assert event.sse_event_name == "clip_ready"

    @pytest.mark.asyncio
    async def test_complete_emits_done(self):
        tracker, _ = self._tracker()
        with patch("src.events.bus.EventBus.publish", AsyncMock()) as mock_pub:
            await tracker.complete("All done!")
        event = mock_pub.call_args[0][0]
        assert event.event_type == EventType.DONE
        assert event.progress == 100

    @pytest.mark.asyncio
    async def test_error_emits_error(self):
        tracker, _ = self._tracker()
        with patch("src.events.bus.EventBus.publish", AsyncMock()) as mock_pub:
            await tracker.error("Something went wrong")
        event = mock_pub.call_args[0][0]
        assert event.event_type == EventType.ERROR
        assert event.progress == 0

    @pytest.mark.asyncio
    async def test_get_returns_none_when_key_missing(self):
        tracker, redis_mock = self._tracker()
        redis_mock.get = AsyncMock(return_value=None)
        result = await tracker.get()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_returns_snapshot_when_key_exists(self):
        tracker, redis_mock = self._tracker()
        snap = {"progress": 42, "message": "hi", "status": "processing", "task_id": tracker.task_id}
        redis_mock.get = AsyncMock(return_value=json.dumps(snap))
        result = await tracker.get()
        assert result["progress"] == 42


# ===========================================================================
# 7. progress_emitter facade
# ===========================================================================

class TestProgressEmitterFacade:

    @pytest.mark.asyncio
    async def test_emit_progress_delegates_to_event_bus(self):
        from src.services.progress_emitter import emit_progress

        with patch("src.events.bus.EventBus.publish", AsyncMock()) as mock_pub:
            await emit_progress("task-1", "scoring", 60, "Scoring…")

        mock_pub.assert_awaited_once()
        event = mock_pub.call_args[0][0]
        assert event.task_id == "task-1"
        assert event.stage == "scoring"
        assert event.progress == 60
        assert event.event_type == "scoring"

    @pytest.mark.asyncio
    async def test_emit_progress_clamps_percent(self):
        from src.services.progress_emitter import emit_progress

        with patch("src.events.bus.EventBus.publish", AsyncMock()) as mock_pub:
            await emit_progress("t", "render", 150, "over 100")
        assert mock_pub.call_args[0][0].progress == 100

        with patch("src.events.bus.EventBus.publish", AsyncMock()) as mock_pub:
            await emit_progress("t", "render", -5, "negative")
        assert mock_pub.call_args[0][0].progress == 0

    @pytest.mark.asyncio
    async def test_emit_clip_generated(self):
        from src.services.progress_emitter import emit_clip_generated

        with patch("src.events.bus.EventBus.publish", AsyncMock()) as mock_pub:
            await emit_clip_generated("t", "clip-1", "/path.mp4", 1, 3)

        event = mock_pub.call_args[0][0]
        assert event.event_type == EventType.CLIP_READY
        assert event.clip_id == "clip-1"
        assert event.metadata["clip_number"] == 1

    @pytest.mark.asyncio
    async def test_emit_error(self):
        from src.services.progress_emitter import emit_error

        with patch("src.events.bus.EventBus.publish", AsyncMock()) as mock_pub:
            await emit_error("t", "Transcription failed", stage="transcription")

        event = mock_pub.call_args[0][0]
        assert event.event_type == EventType.ERROR
        assert event.progress == 0
        assert "Transcription failed" in event.message

    @pytest.mark.asyncio
    async def test_emit_completion(self):
        from src.services.progress_emitter import emit_completion

        with patch("src.events.bus.EventBus.publish", AsyncMock()) as mock_pub:
            await emit_completion("t", 5)

        event = mock_pub.call_args[0][0]
        assert event.event_type == EventType.DONE
        assert event.progress == 100
        assert "5 clips" in event.message

    @pytest.mark.asyncio
    async def test_check_channel_active_delegates_to_event_bus(self):
        from src.services.progress_emitter import check_channel_active

        with patch("src.events.bus.EventBus.is_active", AsyncMock(return_value=True)):
            result = await check_channel_active("t")
        assert result is True


# ===========================================================================
# 8. SSE route — pipeline_event_generator
# ===========================================================================

class TestSseRoute:

    @pytest.mark.asyncio
    async def test_generator_yields_connected_first(self):
        from src.api.routes.progress import pipeline_event_generator

        async def empty_subscribe(task_id):
            return
            yield  # empty async gen

        with patch("src.events.bus.EventBus.subscribe", empty_subscribe):
            gen = pipeline_event_generator("task-abc-12345678")
            first = await gen.__anext__()

        assert "event: status\n" in first
        data = json.loads(first.split("data: ")[1].strip())
        assert data["task_id"] == "task-abc-12345678"

    @pytest.mark.asyncio
    async def test_generator_stops_on_terminal_event(self):
        from src.api.routes.progress import pipeline_event_generator

        events = [
            _make_event(event_type=EventType.ANALYSIS, progress=20),
            _make_event(event_type=EventType.DONE, progress=100),
        ]

        async def fake_subscribe(task_id):
            for e in events:
                yield e

        collected = []
        with patch("src.events.bus.EventBus.subscribe", fake_subscribe):
            async for chunk in pipeline_event_generator("task-abc-12345678"):
                collected.append(chunk)

        event_lines = [c for c in collected if c.startswith("event:")]
        assert any("event: status" in c for c in event_lines)
        assert any("event: progress" in c for c in event_lines)
        assert any("event: close" in c for c in event_lines)

    @pytest.mark.asyncio
    async def test_generator_emits_error_sse_on_exception(self):
        from src.api.routes.progress import pipeline_event_generator

        async def boom_subscribe(task_id):
            raise RuntimeError("Redis exploded")
            yield  # make it a generator

        collected = []
        with patch("src.events.bus.EventBus.subscribe", boom_subscribe):
            try:
                async for chunk in pipeline_event_generator("task-abc-12345678"):
                    collected.append(chunk)
            except Exception:
                pass

        all_text = "\n".join(collected)
        assert "event: error" in all_text

    @pytest.mark.asyncio
    async def test_stream_endpoint_returns_streaming_response(self):
        from fastapi.responses import StreamingResponse
        from src.api.routes.progress import stream_progress

        async def empty_subscribe(task_id):
            return
            yield

        with patch("src.events.bus.EventBus.subscribe", empty_subscribe):
            response = await stream_progress("task-abc-12345678")

        assert isinstance(response, StreamingResponse)
        assert response.media_type == "text/event-stream"

    @pytest.mark.asyncio
    async def test_stream_endpoint_rejects_short_task_id(self):
        from fastapi import HTTPException
        from src.api.routes.progress import stream_progress

        with pytest.raises(HTTPException) as exc_info:
            await stream_progress("short")
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_stream_health_returns_active_status(self):
        from src.api.routes.progress import stream_health

        with patch("src.events.bus.EventBus.is_active", AsyncMock(return_value=True)):
            result = await stream_health("task-abc-12345678")

        assert result["stream_active"] is True
        assert result["channel"] == "progress:task-abc-12345678"
