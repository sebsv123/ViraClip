"""
Tests for Editlist Self-Healing Integration.

Tests cover:
  - ErrorDiagnostician._is_editlist_error() detection
  - ErrorDiagnostician._diagnose_editlist_error() diagnosis
  - heal_task() EDITLIST_ERROR handling (safe editlist fallback, health_report, logging)
  - Original editlist preservation in Redis
  - Logging format ([Editlist], [SelfHealing] tags)
  - Error is NOT silenced — remains visible in logs and health_report
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from datetime import datetime, timezone


# =============================================================================
# ErrorDiagnostician: _is_editlist_error detection
# =============================================================================

class TestIsEditlistError:
    """Tests for ErrorDiagnostician._is_editlist_error()."""

    def test_detects_editlist_in_error_message(self):
        """Must detect 'editlist' keyword in the error message."""
        from src.services.error_diagnostician import ErrorDiagnostician

        combined = "FFmpeg process exited with code 1: editlist operation failed"
        traceback = "  File '/app/src/services/editlist_service.py', line 123, in _apply_overlay"

        result = ErrorDiagnostician._is_editlist_error(combined, traceback)
        assert result is True, "Should detect 'editlist' in error message"

    def test_detects_ffmpeg_error_in_editlist_context(self):
        """Must detect FFmpeg errors when traceback mentions editlist_service."""
        from src.services.error_diagnostician import ErrorDiagnostician

        combined = "FFmpeg process exited with code 1: Non-zero exit code"
        traceback = (
            "  File '/app/src/services/editlist_service.py', line 150, in _apply_transition\n"
            "    result = await apply_transition(...)"
        )

        result = ErrorDiagnostician._is_editlist_error(combined, traceback)
        assert result is True, "Should detect FFmpeg error in editlist context"

    def test_detects_editlist_keywords_with_ffmpeg(self):
        """Must detect editlist-related keywords combined with FFmpeg errors."""
        from src.services.error_diagnostician import ErrorDiagnostician

        test_cases = [
            # (combined, traceback, keyword_used)
            ("ffmpeg error: pipe: Broken pipe", "File 'editlist_service.py'", "ffmpeg + editlist_service"),
            ("non-zero exit code 1", "File '_apply_overlay'", "exit code + _apply_overlay"),
            ("exit code 255", "File '_apply_transition'", "exit code + _apply_transition"),
            ("FFmpeg error", "File 'apply_safe'", "FFmpeg + apply_safe"),
        ]

        for combined, traceback, desc in test_cases:
            result = ErrorDiagnostician._is_editlist_error(combined, traceback)
            assert result is True, f"Should detect editlist error: {desc}"

    def test_ignores_non_editlist_errors(self):
        """Must NOT detect errors unrelated to editlist."""
        from src.services.error_diagnostician import ErrorDiagnostician

        combined = "FFmpeg process exited with code 1"
        traceback = "  File '/app/src/video_processing/editing_pipeline.py', line 200"

        result = ErrorDiagnostician._is_editlist_error(combined, traceback)
        assert result is False, "Should NOT detect non-editlist errors"

    def test_ignores_editlist_without_ffmpeg(self):
        """Must NOT detect editlist references without FFmpeg errors."""
        from src.services.error_diagnostician import ErrorDiagnostician

        combined = "ValueError: invalid literal for int()"
        traceback = "  File '/app/src/services/editlist_service.py', line 50"

        result = ErrorDiagnostician._is_editlist_error(combined, traceback)
        assert result is False, "Should NOT detect non-FFmpeg errors in editlist"

    def test_case_insensitive_detection(self):
        """Must detect editlist errors case-insensitively."""
        from src.services.error_diagnostician import ErrorDiagnostician

        combined = "FFMPEG ERROR: EditList operation failed"
        traceback = "  File '/app/src/services/Editlist_Service.py', line 100"

        result = ErrorDiagnostician._is_editlist_error(combined, traceback)
        assert result is True, "Should detect case-insensitive editlist errors"


# =============================================================================
# ErrorDiagnostician: _diagnose_editlist_error diagnosis
# =============================================================================

class TestDiagnoseEditlistError:
    """Tests for ErrorDiagnostician._diagnose_editlist_error()."""

    def test_diagnoses_overlay_failure(self):
        """Must identify overlay as the failed operation."""
        from src.services.error_diagnostician import ErrorDiagnostician

        traceback = (
            "  File '/app/src/services/editlist_service.py', line 150, in _apply_overlay\n"
            "    result = await renderer.render_overlays(...)"
        )

        diagnosis = ErrorDiagnostician._diagnose_editlist_error(traceback)

        assert diagnosis.error_type == "EDITLIST_ERROR"
        assert "overlay" in diagnosis.fix_description.lower()
        assert "simplify editlist to cuts-only" in diagnosis.fix_description.lower()
        assert diagnosis.can_fix_in_runtime is True

    def test_diagnoses_transition_failure(self):
        """Must identify transition as the failed operation."""
        from src.services.error_diagnostician import ErrorDiagnostician

        traceback = (
            "  File '/app/src/services/editlist_service.py', line 180, in _apply_transition\n"
            "    apply_transition(...)"
        )

        diagnosis = ErrorDiagnostician._diagnose_editlist_error(traceback)

        assert diagnosis.error_type == "EDITLIST_ERROR"
        assert "transition" in diagnosis.fix_description.lower()

    def test_diagnoses_cut_failure(self):
        """Must identify cut as the failed operation."""
        from src.services.error_diagnostician import ErrorDiagnostician

        traceback = (
            "  File '/app/src/services/editlist_service.py', line 100, in _apply_cut\n"
            "    result = trim_clip_file(...)"
        )

        diagnosis = ErrorDiagnostician._diagnose_editlist_error(traceback)

        assert diagnosis.error_type == "EDITLIST_ERROR"
        assert "cut" in diagnosis.fix_description.lower()

    def test_diagnoses_concat_failure(self):
        """Must identify concat as the failed operation."""
        from src.services.error_diagnostician import ErrorDiagnostician

        traceback = (
            "  File '/app/src/services/editlist_service.py', line 130, in _apply_concat\n"
            "    result = merge_clip_files(...)"
        )

        diagnosis = ErrorDiagnostician._diagnose_editlist_error(traceback)

        assert diagnosis.error_type == "EDITLIST_ERROR"
        assert "concat" in diagnosis.fix_description.lower()

    def test_diagnoses_unknown_operation(self):
        """Must handle unknown operation gracefully."""
        from src.services.error_diagnostician import ErrorDiagnostician

        traceback = (
            "  File '/app/src/services/editlist_service.py', line 200, in apply\n"
            "    raise RuntimeError('Something went wrong')"
        )

        diagnosis = ErrorDiagnostician._diagnose_editlist_error(traceback)

        assert diagnosis.error_type == "EDITLIST_ERROR"
        assert "unknown" in diagnosis.fix_description.lower()

    def test_diagnosis_has_correct_error_type(self):
        """Diagnosis must have error_type='EDITLIST_ERROR'."""
        from src.services.error_diagnostician import ErrorDiagnostician

        traceback = "  File '/app/src/services/editlist_service.py', line 150, in _apply_overlay"
        diagnosis = ErrorDiagnostician._diagnose_editlist_error(traceback)

        assert diagnosis.error_type == "EDITLIST_ERROR"
        assert diagnosis.can_fix_in_runtime is True


# =============================================================================
# ErrorDiagnostician: diagnose() integration with editlist rules
# =============================================================================

class TestDiagnoseIntegration:
    """Tests for ErrorDiagnostician.diagnose() with editlist errors."""

    @pytest.mark.asyncio
    async def test_diagnose_returns_editlist_error(self):
        """diagnose() must return EDITLIST_ERROR for editlist FFmpeg failures."""
        from src.services.error_diagnostician import ErrorDiagnostician

        error = "FFmpeg process exited with code 1"
        traceback = (
            "  File '/app/src/services/editlist_service.py', line 150, in _apply_overlay\n"
            "    result = await renderer.render_overlays(...)"
        )

        with patch.object(ErrorDiagnostician, '_check_knowledge_base', AsyncMock(return_value=None)):
            diagnosis = await ErrorDiagnostician.diagnose(error, traceback)

        assert diagnosis.error_type == "EDITLIST_ERROR"
        assert diagnosis.can_fix_in_runtime is True

    @pytest.mark.asyncio
    async def test_diagnose_prioritizes_known_rules_over_editlist(self):
        """Known rules (LLM_JSON_WRAPPER, etc.) must take priority over editlist."""
        from src.services.error_diagnostician import ErrorDiagnostician

        # Even though traceback mentions editlist, the error is an LLM wrapper issue
        error = "function=final_result"
        traceback = (
            "  File '/app/src/services/editlist_service.py', line 50\n"
            "    result = await agent.run(user_prompt)"
        )

        with patch.object(ErrorDiagnostician, '_check_knowledge_base', AsyncMock(return_value=None)):
            diagnosis = await ErrorDiagnostician.diagnose(error, traceback)

        # Rule 1 (LLM_JSON_WRAPPER) must take priority over Rule 5 (EDITLIST_ERROR)
        assert diagnosis.error_type == "LLM_JSON_WRAPPER", \
            "Known rules must take priority over editlist detection"

    @pytest.mark.asyncio
    async def test_diagnose_returns_unknown_for_non_editlist_ffmpeg(self):
        """Non-editlist FFmpeg errors must return UNKNOWN."""
        from src.services.error_diagnostician import ErrorDiagnostician

        error = "FFmpeg process exited with code 1"
        traceback = "  File '/app/src/video_processing/editing_pipeline.py', line 200"

        with patch.object(ErrorDiagnostician, '_check_knowledge_base', AsyncMock(return_value=None)):
            diagnosis = await ErrorDiagnostician.diagnose(error, traceback)

        assert diagnosis.error_type != "EDITLIST_ERROR", \
            "Non-editlist FFmpeg errors must NOT be classified as EDITLIST_ERROR"


# =============================================================================
# heal_task: EDITLIST_ERROR handling
# =============================================================================

class TestHealTaskEditlistError:
    """Tests for heal_task() with EDITLIST_ERROR diagnosis."""

    @pytest.fixture
    def editlist_diagnosis(self):
        """Create an EDITLIST_ERROR diagnosis."""
        diag = MagicMock()
        diag.error_type = "EDITLIST_ERROR"
        diag.fix_code = None
        diag.is_known = False
        diag.fix_description = "Editlist FFmpeg failure in overlay operation — simplify editlist to cuts-only and retry"
        diag.can_fix_in_runtime = True
        return diag

    @pytest.fixture
    def mock_editlist(self):
        """Create a mock editlist with overlay and transition operations."""
        from src.services.editlist_service import (
            Editlist, EditOperation, EditOpType,
        )
        editlist = Editlist(
            clip_id="clip-editlist-heal",
            task_id="task-editlist-heal",
            source_path="/tmp/video.mp4",
            operations=[
                EditOperation(op_type=EditOpType.CUT, params={"source_path": "/tmp/video.mp4"}),
                EditOperation(op_type=EditOpType.CONCAT, params={}),
                EditOperation(op_type=EditOpType.OVERLAY, params={}),
                EditOperation(op_type=EditOpType.TRANSITION, params={}),
            ],
        )
        return editlist

    @pytest.mark.asyncio
    async def test_logs_editlist_failure(self, editlist_diagnosis, mock_editlist, caplog):
        """Must log '[Editlist] Render failed for clip ...' when EDITLIST_ERROR."""
        from src.services.self_healing_agent import heal_task
        import logging

        caplog.set_level(logging.INFO)

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_redis = AsyncMock()
        mock_redis.zrange = AsyncMock(return_value=[])
        mock_redis.zrem = AsyncMock(return_value=0)
        mock_redis.incr = AsyncMock(return_value=1)

        mock_job_queue = AsyncMock()
        mock_job_queue.enqueue_processing_job = AsyncMock(return_value="job-uuid")

        task = {
            "id": "task-editlist-log",
            "status": "failed",
            "error_code": "EDITLIST_ERROR",
            "error_message": "FFmpeg failed on overlay",
            "retry_count": 0,
            "progress_message": "",
            "metadata": {},
            "source_url": "",
            "source_type": "",
            "user_id": "u1",
        }

        with (
            patch("src.services.self_healing_agent._get_db", return_value=mock_conn),
            patch("src.services.self_healing_agent._get_redis", return_value=mock_redis),
            patch("src.workers.job_queue.JobQueue.enqueue_processing_job", mock_job_queue.enqueue_processing_job),
            patch("src.services.error_diagnostician.ErrorDiagnostician.diagnose", AsyncMock(return_value=editlist_diagnosis)),
            patch("src.services.error_diagnostician.ErrorDiagnostician.save_to_knowledge_base", AsyncMock()),
            patch("src.services.editlist_service.EditlistService.load_editlist_from_redis", AsyncMock(return_value=mock_editlist)),
            patch("src.services.editlist_service.EditlistService.save_editlist_to_redis", AsyncMock()),
        ):
            await heal_task(task)

        # Check for [Editlist] log message
        editlist_logs = [r for r in caplog.records if "[Editlist]" in r.getMessage()]
        assert len(editlist_logs) >= 1, "Must log [Editlist] message"
        assert any("Render failed for clip" in r.getMessage() for r in editlist_logs), \
            "Must log 'Render failed for clip'"

    @pytest.mark.asyncio
    async def test_logs_self_healing_safe_editlist(self, editlist_diagnosis, mock_editlist, caplog):
        """Must log '[SelfHealing] Applying safe editlist (cuts only) for clip ...'."""
        from src.services.self_healing_agent import heal_task
        import logging

        caplog.set_level(logging.INFO)

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_redis = AsyncMock()
        mock_redis.zrange = AsyncMock(return_value=[])
        mock_redis.zrem = AsyncMock(return_value=0)
        mock_redis.incr = AsyncMock(return_value=1)

        mock_job_queue = AsyncMock()
        mock_job_queue.enqueue_processing_job = AsyncMock(return_value="job-uuid")

        task = {
            "id": "task-editlist-safe",
            "status": "failed",
            "error_code": "EDITLIST_ERROR",
            "error_message": "FFmpeg failed on overlay",
            "retry_count": 0,
            "progress_message": "",
            "metadata": {},
            "source_url": "",
            "source_type": "",
            "user_id": "u1",
        }

        with (
            patch("src.services.self_healing_agent._get_db", return_value=mock_conn),
            patch("src.services.self_healing_agent._get_redis", return_value=mock_redis),
            patch("src.workers.job_queue.JobQueue.enqueue_processing_job", mock_job_queue.enqueue_processing_job),
            patch("src.services.error_diagnostician.ErrorDiagnostician.diagnose", AsyncMock(return_value=editlist_diagnosis)),
            patch("src.services.error_diagnostician.ErrorDiagnostician.save_to_knowledge_base", AsyncMock()),
            patch("src.services.editlist_service.EditlistService.load_editlist_from_redis", AsyncMock(return_value=mock_editlist)),
            patch("src.services.editlist_service.EditlistService.save_editlist_to_redis", AsyncMock()),
        ):
            await heal_task(task)

        # Check for [SelfHealing] log message
        sh_logs = [r for r in caplog.records if "[SelfHealing]" in r.getMessage()]
        assert len(sh_logs) >= 1, "Must log [SelfHealing] message"
        assert any("Applying safe editlist" in r.getMessage() for r in sh_logs), \
            "Must log 'Applying safe editlist (cuts only)'"

    @pytest.mark.asyncio
    async def test_preserves_original_editlist_in_redis(self, editlist_diagnosis, mock_editlist):
        """Must save the original editlist to Redis for post-mortem analysis."""
        from src.services.self_healing_agent import heal_task

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_redis = AsyncMock()
        mock_redis.zrange = AsyncMock(return_value=[])
        mock_redis.zrem = AsyncMock(return_value=0)
        mock_redis.incr = AsyncMock(return_value=1)

        mock_job_queue = AsyncMock()
        mock_job_queue.enqueue_processing_job = AsyncMock(return_value="job-uuid")

        mock_save_to_redis = AsyncMock()

        task = {
            "id": "task-editlist-preserve",
            "status": "failed",
            "error_code": "EDITLIST_ERROR",
            "error_message": "FFmpeg failed on overlay",
            "retry_count": 0,
            "progress_message": "",
            "metadata": {},
            "source_url": "",
            "source_type": "",
            "user_id": "u1",
        }

        with (
            patch("src.services.self_healing_agent._get_db", return_value=mock_conn),
            patch("src.services.self_healing_agent._get_redis", return_value=mock_redis),
            patch("src.workers.job_queue.JobQueue.enqueue_processing_job", mock_job_queue.enqueue_processing_job),
            patch("src.services.error_diagnostician.ErrorDiagnostician.diagnose", AsyncMock(return_value=editlist_diagnosis)),
            patch("src.services.error_diagnostician.ErrorDiagnostician.save_to_knowledge_base", AsyncMock()),
            patch("src.services.editlist_service.EditlistService.load_editlist_from_redis", AsyncMock(return_value=mock_editlist)),
            patch("src.services.editlist_service.EditlistService.save_editlist_to_redis", mock_save_to_redis),
        ):
            await heal_task(task)

        # Verify original editlist was saved to Redis
        mock_save_to_redis.assert_called_once()
        saved_editlist = mock_save_to_redis.call_args[0][0]
        assert saved_editlist is mock_editlist, "Must save the original editlist"
        # Verify it was saved with the task_id
        assert mock_save_to_redis.call_args[0][1] == "task-editlist-preserve"

    @pytest.mark.asyncio
    async def test_updates_health_report_with_editlist_error(self, editlist_diagnosis, mock_editlist):
        """Must update metadata with health_report containing editlist error info."""
        from src.services.self_healing_agent import heal_task

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_redis = AsyncMock()
        mock_redis.zrange = AsyncMock(return_value=[])
        mock_redis.zrem = AsyncMock(return_value=0)
        mock_redis.incr = AsyncMock(return_value=1)

        mock_job_queue = AsyncMock()
        mock_job_queue.enqueue_processing_job = AsyncMock(return_value="job-uuid")

        mock_update_metadata = AsyncMock()

        task = {
            "id": "task-editlist-health",
            "status": "failed",
            "error_code": "EDITLIST_ERROR",
            "error_message": "FFmpeg failed on overlay",
            "retry_count": 0,
            "progress_message": "",
            "metadata": {},
            "source_url": "",
            "source_type": "",
            "user_id": "u1",
        }

        with (
            patch("src.services.self_healing_agent._get_db", return_value=mock_conn),
            patch("src.services.self_healing_agent._get_redis", return_value=mock_redis),
            patch("src.workers.job_queue.JobQueue.enqueue_processing_job", mock_job_queue.enqueue_processing_job),
            patch("src.services.error_diagnostician.ErrorDiagnostician.diagnose", AsyncMock(return_value=editlist_diagnosis)),
            patch("src.services.error_diagnostician.ErrorDiagnostician.save_to_knowledge_base", AsyncMock()),
            patch("src.services.editlist_service.EditlistService.load_editlist_from_redis", AsyncMock(return_value=mock_editlist)),
            patch("src.services.editlist_service.EditlistService.save_editlist_to_redis", AsyncMock()),
            patch("src.services.self_healing_agent.update_task_metadata", mock_update_metadata),
        ):
            await heal_task(task)

        # Find the call that updates health_report
        health_report_calls = []
        for c in mock_update_metadata.call_args_list:
            args = c[0]
            if len(args) >= 2 and "health_report" in args[1]:
                health_report_calls.append(args[1])

        assert len(health_report_calls) >= 1, "Must update metadata with health_report"

        health_report = health_report_calls[0]["health_report"]
        assert health_report["editlist_error"] is True
        assert health_report["safe_mode_applied"] is True
        assert health_report["original_editlist_preserved"] is True
        assert "original_editlist_redis_key" in health_report
        assert "healing_timestamp" in health_report
        assert "failed_operation" in health_report

    @pytest.mark.asyncio
    async def test_sets_editlist_safe_mode_in_metadata(self, editlist_diagnosis, mock_editlist):
        """Must set editlist_safe_mode=True in metadata."""
        from src.services.self_healing_agent import heal_task

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_redis = AsyncMock()
        mock_redis.zrange = AsyncMock(return_value=[])
        mock_redis.zrem = AsyncMock(return_value=0)
        mock_redis.incr = AsyncMock(return_value=1)

        mock_job_queue = AsyncMock()
        mock_job_queue.enqueue_processing_job = AsyncMock(return_value="job-uuid")

        mock_update_metadata = AsyncMock()

        task = {
            "id": "task-editlist-safe-mode",
            "status": "failed",
            "error_code": "EDITLIST_ERROR",
            "error_message": "FFmpeg failed on overlay",
            "retry_count": 0,
            "progress_message": "",
            "metadata": {},
            "source_url": "",
            "source_type": "",
            "user_id": "u1",
        }

        with (
            patch("src.services.self_healing_agent._get_db", return_value=mock_conn),
            patch("src.services.self_healing_agent._get_redis", return_value=mock_redis),
            patch("src.workers.job_queue.JobQueue.enqueue_processing_job", mock_job_queue.enqueue_processing_job),
            patch("src.services.error_diagnostician.ErrorDiagnostician.diagnose", AsyncMock(return_value=editlist_diagnosis)),
            patch("src.services.error_diagnostician.ErrorDiagnostician.save_to_knowledge_base", AsyncMock()),
            patch("src.services.editlist_service.EditlistService.load_editlist_from_redis", AsyncMock(return_value=mock_editlist)),
            patch("src.services.editlist_service.EditlistService.save_editlist_to_redis", AsyncMock()),
            patch("src.services.self_healing_agent.update_task_metadata", mock_update_metadata),
        ):
            await heal_task(task)

        # Find the call that sets editlist_safe_mode
        safe_mode_calls = []
        for c in mock_update_metadata.call_args_list:
            args = c[0]
            if len(args) >= 2 and "editlist_safe_mode" in args[1]:
                safe_mode_calls.append(args[1])

        assert len(safe_mode_calls) >= 1, "Must set editlist_safe_mode in metadata"
        assert safe_mode_calls[0]["editlist_safe_mode"] is True

    @pytest.mark.asyncio
    async def test_handles_missing_editlist_gracefully(self, editlist_diagnosis):
        """Must handle case where no original editlist is found in Redis."""
        from src.services.self_healing_agent import heal_task

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_redis = AsyncMock()
        mock_redis.zrange = AsyncMock(return_value=[])
        mock_redis.zrem = AsyncMock(return_value=0)
        mock_redis.incr = AsyncMock(return_value=1)

        mock_job_queue = AsyncMock()
        mock_job_queue.enqueue_processing_job = AsyncMock(return_value="job-uuid")

        mock_update_metadata = AsyncMock()

        task = {
            "id": "task-editlist-missing",
            "status": "failed",
            "error_code": "EDITLIST_ERROR",
            "error_message": "FFmpeg failed on overlay",
            "retry_count": 0,
            "progress_message": "",
            "metadata": {},
            "source_url": "",
            "source_type": "",
            "user_id": "u1",
        }

        with (
            patch("src.services.self_healing_agent._get_db", return_value=mock_conn),
            patch("src.services.self_healing_agent._get_redis", return_value=mock_redis),
            patch("src.workers.job_queue.JobQueue.enqueue_processing_job", mock_job_queue.enqueue_processing_job),
            patch("src.services.error_diagnostician.ErrorDiagnostician.diagnose", AsyncMock(return_value=editlist_diagnosis)),
            patch("src.services.error_diagnostician.ErrorDiagnostician.save_to_knowledge_base", AsyncMock()),
            patch("src.services.editlist_service.EditlistService.load_editlist_from_redis", AsyncMock(return_value=None)),
            patch("src.services.self_healing_agent.update_task_metadata", mock_update_metadata),
        ):
            await heal_task(task)

        # Must still update metadata with health_report indicating safe_mode_applied=False
        health_report_calls = []
        for c in mock_update_metadata.call_args_list:
            args = c[0]
            if len(args) >= 2 and "health_report" in args[1]:
                health_report_calls.append(args[1])

        assert len(health_report_calls) >= 1, "Must update metadata even without editlist"
        health_report = health_report_calls[0]["health_report"]
        assert health_report["editlist_error"] is True
        assert health_report["safe_mode_applied"] is False
        assert "No original editlist found" in health_report.get("note", "")

    @pytest.mark.asyncio
    async def test_error_not_silenced(self, editlist_diagnosis, mock_editlist, caplog):
        """Error must remain visible in logs — it must NOT be silenced."""
        from src.services.self_healing_agent import heal_task
        import logging

        caplog.set_level(logging.INFO)

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_redis = AsyncMock()
        mock_redis.zrange = AsyncMock(return_value=[])
        mock_redis.zrem = AsyncMock(return_value=0)
        mock_redis.incr = AsyncMock(return_value=1)

        mock_job_queue = AsyncMock()
        mock_job_queue.enqueue_processing_job = AsyncMock(return_value="job-uuid")

        task = {
            "id": "task-editlist-not-silenced",
            "status": "failed",
            "error_code": "EDITLIST_ERROR",
            "error_message": "FFmpeg failed on overlay",
            "retry_count": 0,
            "progress_message": "",
            "metadata": {},
            "source_url": "",
            "source_type": "",
            "user_id": "u1",
        }

        with (
            patch("src.services.self_healing_agent._get_db", return_value=mock_conn),
            patch("src.services.self_healing_agent._get_redis", return_value=mock_redis),
            patch("src.workers.job_queue.JobQueue.enqueue_processing_job", mock_job_queue.enqueue_processing_job),
            patch("src.services.error_diagnostician.ErrorDiagnostician.diagnose", AsyncMock(return_value=editlist_diagnosis)),
            patch("src.services.error_diagnostician.ErrorDiagnostician.save_to_knowledge_base", AsyncMock()),
            patch("src.services.editlist_service.EditlistService.load_editlist_from_redis", AsyncMock(return_value=mock_editlist)),
            patch("src.services.editlist_service.EditlistService.save_editlist_to_redis", AsyncMock()),
        ):
            await heal_task(task)

        # Error must be logged, not hidden
        all_logs = [r.getMessage() for r in caplog.records]
        error_logs = [r for r in caplog.records if r.levelno >= logging.WARNING]

        # The editlist error must be visible in logs
        assert any("[Editlist]" in msg for msg in all_logs), \
            "Editlist error must be visible in logs (not silenced)"

    @pytest.mark.asyncio
    async def test_handles_editlist_service_import_error(self, editlist_diagnosis):
        """Must handle ImportError gracefully when EditlistService is not available."""
        from src.services.self_healing_agent import heal_task

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_redis = AsyncMock()
        mock_redis.zrange = AsyncMock(return_value=[])
        mock_redis.zrem = AsyncMock(return_value=0)
        mock_redis.incr = AsyncMock(return_value=1)

        mock_job_queue = AsyncMock()
        mock_job_queue.enqueue_processing_job = AsyncMock(return_value="job-uuid")

        task = {
            "id": "task-editlist-import-err",
            "status": "failed",
            "error_code": "EDITLIST_ERROR",
            "error_message": "FFmpeg failed on overlay",
            "retry_count": 0,
            "progress_message": "",
            "metadata": {},
            "source_url": "",
            "source_type": "",
            "user_id": "u1",
        }

        # Simulate ImportError by making the import inside heal_task fail
        original_import = __import__

        def mock_import(name, *args, **kwargs):
            if name == "src.services.editlist_service":
                raise ImportError("EditlistService not available")
            return original_import(name, *args, **kwargs)

        with (
            patch("src.services.self_healing_agent._get_db", return_value=mock_conn),
            patch("src.services.self_healing_agent._get_redis", return_value=mock_redis),
            patch("src.workers.job_queue.JobQueue.enqueue_processing_job", mock_job_queue.enqueue_processing_job),
            patch("src.services.error_diagnostician.ErrorDiagnostician.diagnose", AsyncMock(return_value=editlist_diagnosis)),
            patch("src.services.error_diagnostician.ErrorDiagnostician.save_to_knowledge_base", AsyncMock()),
            patch("builtins.__import__", side_effect=mock_import),
        ):
            # Should not raise — must handle ImportError gracefully
            result = await heal_task(task)
            assert result is not None, "Must return a result even on ImportError"

    @pytest.mark.asyncio
    async def test_handles_editlist_exception_gracefully(self, editlist_diagnosis):
        """Must handle unexpected exceptions in editlist healing gracefully."""
        from src.services.self_healing_agent import heal_task

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_redis = AsyncMock()
        mock_redis.zrange = AsyncMock(return_value=[])
        mock_redis.zrem = AsyncMock(return_value=0)
        mock_redis.incr = AsyncMock(return_value=1)

        mock_job_queue = AsyncMock()
        mock_job_queue.enqueue_processing_job = AsyncMock(return_value="job-uuid")

        task = {
            "id": "task-editlist-exc",
            "status": "failed",
            "error_code": "EDITLIST_ERROR",
            "error_message": "FFmpeg failed on overlay",
            "retry_count": 0,
            "progress_message": "",
            "metadata": {},
            "source_url": "",
            "source_type": "",
            "user_id": "u1",
        }

        with (
            patch("src.services.self_healing_agent._get_db", return_value=mock_conn),
            patch("src.services.self_healing_agent._get_redis", return_value=mock_redis),
            patch("src.workers.job_queue.JobQueue.enqueue_processing_job", mock_job_queue.enqueue_processing_job),
            patch("src.services.error_diagnostician.ErrorDiagnostician.diagnose", AsyncMock(return_value=editlist_diagnosis)),
            patch("src.services.error_diagnostician.ErrorDiagnostician.save_to_knowledge_base", AsyncMock()),
            patch("src.services.editlist_service.EditlistService.load_editlist_from_redis",
                  AsyncMock(side_effect=Exception("Redis connection error"))),
        ):
            # Should not raise — must handle exception gracefully
            result = await heal_task(task)
            assert result is not None, "Must return a result even on exception"


# (TestHealthReportExposure removed — health_report exposure is tested
#  implicitly in TestHealTaskEditlistError tests above.)
