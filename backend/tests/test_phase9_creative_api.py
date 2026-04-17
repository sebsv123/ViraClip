"""
Tests for Phase 9.13 — creative analytics API endpoints.
Uses httpx AsyncClient via ASGI transport; task_manager is mocked.
"""

import pytest
from unittest.mock import patch

# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_clip(n=1, viral_score=72.0, hook_score=75.0, enhanced=True,
               broll=1, zoom=True, loudnorm=True, reorder=False, qa=True):
    return {
        "clip_id": n,
        "filename": f"clip_{n:03d}.mp4",
        "path": f"/app/temp/clips/clip_{n:03d}.mp4",
        "creative_enhanced": enhanced,
        "timeline_events": 4,
        "viral_score": viral_score,
        "hook_score": hook_score,
        "pacing_score": 65.0,
        "emotion_score": 70.0,
        "improvements": ["Add more hooks in the first 3s"],
        "preset_used": "tiktok_viral",
        "hook_reorder_applied": reorder,
        "hook_already_optimized": not reorder,
        "hook_reorder_suggested": reorder,
        "hook_text": "secreto",
        "broll_overlays": broll,
        "zoom_punch_applied": zoom,
        "color_grade_applied": True,
        "sfx_injected": 2,
        "loudnorm_applied": loudnorm,
        "qa_passed": qa,
        "qa_issues": [],
    }


TASK_RUNNING = {"status": "running", "result": None}
TASK_DONE_2  = {
    "status": "completed",
    "result": {"clips": [_make_clip(1), _make_clip(2, viral_score=80.0, reorder=True)]},
}
TASK_DONE_LIST = {
    "status": "completed",
    "result": [_make_clip(1), _make_clip(2)],  # coordinator returns a list directly
}
TASK_EMPTY = {"status": "completed", "result": {"clips": []}}


# ── Report endpoint ───────────────────────────────────────────────────────────

class TestGetTaskCreativeReport:
    def test_unknown_task_returns_404(self):
        from src.api.routes.creative import get_task_creative_report
        import asyncio
        from fastapi import HTTPException

        with patch("src.api.routes.creative.get_task_status", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(
                    get_task_creative_report("unknown-id")
                )
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_one_report_per_clip(self):
        from src.api.routes.creative import get_task_creative_report
        with patch("src.api.routes.creative.get_task_status", return_value=TASK_DONE_2):
            reports = await get_task_creative_report("task-1")
        assert len(reports) == 2

    @pytest.mark.asyncio
    async def test_report_contains_expected_fields(self):
        from src.api.routes.creative import get_task_creative_report
        with patch("src.api.routes.creative.get_task_status", return_value=TASK_DONE_2):
            reports = await get_task_creative_report("task-1")
        r = reports[0]
        assert r.creative_enhanced is True
        assert r.viral_score == 72.0
        assert r.preset_used == "tiktok_viral"
        assert r.broll_overlays == 1
        assert r.qa_passed is True

    @pytest.mark.asyncio
    async def test_works_when_result_is_list(self):
        """coordinator may return a bare list instead of {"clips": [...]}"""
        from src.api.routes.creative import get_task_creative_report
        with patch("src.api.routes.creative.get_task_status", return_value=TASK_DONE_LIST):
            reports = await get_task_creative_report("task-list")
        assert len(reports) == 2

    @pytest.mark.asyncio
    async def test_empty_clips_returns_empty_list(self):
        from src.api.routes.creative import get_task_creative_report
        with patch("src.api.routes.creative.get_task_status", return_value=TASK_EMPTY):
            reports = await get_task_creative_report("task-empty")
        assert reports == []


# ── Single clip endpoint ──────────────────────────────────────────────────────

class TestGetClipCreativeReport:
    @pytest.mark.asyncio
    async def test_valid_clip_number(self):
        from src.api.routes.creative import get_clip_creative_report
        with patch("src.api.routes.creative.get_task_status", return_value=TASK_DONE_2):
            report = await get_clip_creative_report("task-1", 2)
        assert report.clip_id == 2
        assert report.viral_score == 80.0
        assert report.hook_reorder_applied is True

    @pytest.mark.asyncio
    async def test_clip_number_zero_returns_404(self):
        from src.api.routes.creative import get_clip_creative_report
        from fastapi import HTTPException
        with patch("src.api.routes.creative.get_task_status", return_value=TASK_DONE_2):
            with pytest.raises(HTTPException) as exc_info:
                await get_clip_creative_report("task-1", 0)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_clip_number_too_large_returns_404(self):
        from src.api.routes.creative import get_clip_creative_report
        from fastapi import HTTPException
        with patch("src.api.routes.creative.get_task_status", return_value=TASK_DONE_2):
            with pytest.raises(HTTPException) as exc_info:
                await get_clip_creative_report("task-1", 99)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_missing_creative_keys_default_gracefully(self):
        """Clips without creative keys should use defaults (backward compat)."""
        from src.api.routes.creative import get_clip_creative_report
        bare_clip = {"clip_id": 1, "filename": "clip_001.mp4"}
        task = {"status": "completed", "result": {"clips": [bare_clip]}}
        with patch("src.api.routes.creative.get_task_status", return_value=task):
            report = await get_clip_creative_report("task-bare", 1)
        assert report.creative_enhanced is False
        assert report.viral_score is None
        assert report.improvements == []
        assert report.qa_issues == []


# ── Summary endpoint ──────────────────────────────────────────────────────────

class TestGetTaskCreativeSummary:
    @pytest.mark.asyncio
    async def test_empty_task_returns_zeros(self):
        from src.api.routes.creative import get_task_creative_summary
        with patch("src.api.routes.creative.get_task_status", return_value=TASK_EMPTY):
            summary = await get_task_creative_summary("task-empty")
        assert summary.total_clips == 0
        assert summary.avg_viral_score is None
        assert summary.top_improvements == []

    @pytest.mark.asyncio
    async def test_avg_viral_score(self):
        from src.api.routes.creative import get_task_creative_summary
        with patch("src.api.routes.creative.get_task_status", return_value=TASK_DONE_2):
            summary = await get_task_creative_summary("task-1")
        # clip 1: 72.0, clip 2: 80.0 → avg 76.0
        assert summary.avg_viral_score == 76.0

    @pytest.mark.asyncio
    async def test_counts_are_correct(self):
        from src.api.routes.creative import get_task_creative_summary
        with patch("src.api.routes.creative.get_task_status", return_value=TASK_DONE_2):
            summary = await get_task_creative_summary("task-1")
        assert summary.total_clips == 2
        assert summary.enhanced_clips == 2
        assert summary.clips_with_broll == 2
        assert summary.clips_with_loudnorm == 2
        assert summary.clips_qa_passed == 2
        assert summary.clips_hook_reordered == 1  # only clip 2

    @pytest.mark.asyncio
    async def test_top_improvements_deduped(self):
        """Same improvement suggestion across clips should appear once in top_improvements."""
        from src.api.routes.creative import get_task_creative_summary
        with patch("src.api.routes.creative.get_task_status", return_value=TASK_DONE_2):
            summary = await get_task_creative_summary("task-1")
        assert len(summary.top_improvements) <= 5
        # The same improvement "Add more hooks in the first 3s" from both clips
        # should appear exactly once
        assert len(set(summary.top_improvements)) == len(summary.top_improvements)

    @pytest.mark.asyncio
    async def test_unknown_task_returns_404(self):
        from src.api.routes.creative import get_task_creative_summary
        from fastapi import HTTPException
        with patch("src.api.routes.creative.get_task_status", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                await get_task_creative_summary("unknown")
        assert exc_info.value.status_code == 404
