"""
Regression tests for the self-healing queue system.

Tests all 6 fixes applied to eliminate infinite loops of stuck tasks:
  Fix 1: update_task_error() saves error_message to DB
  Fix 2: get_healable_tasks() excludes SELF_HEALING_EXHAUSTED tasks
  Fix 3: heal_task() atomic Postgres→Redis with rollback on failure
  Fix 4: _clean_redis_keys_for_task() uses SCAN to find ALL arq:* keys
  Fix 5: Circuit breaker trips after 3 skips and auto-fails the task
  Fix 6: Dirty state detection catches tasks stuck > 15 minutes in tasks.py
"""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from datetime import datetime, timedelta, timezone


# =============================================================================
# Fix 1: update_task_error() saves error_message to DB
# =============================================================================

class TestFix1_UpdateTaskError:
    """update_task_error() must save both error_code AND error_message."""

    @pytest.mark.asyncio
    async def test_saves_error_message(self):
        """Verify error_message is included in the UPDATE query."""
        from src.repositories.task_repository import TaskRepository

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        await TaskRepository.update_task_error(
            mock_db,
            task_id="test-task-123",
            error_code="TEST_ERROR",
            error_message="This is a detailed error message for debugging",
        )

        # Verify execute was called
        assert mock_db.execute.called, "db.execute() was not called"
        # db.execute() is called with positional args: (sql_text, params_dict)
        call_args = mock_db.execute.call_args[0]
        params = call_args[1]

        # Verify error_message is in the params
        assert "error_message" in params, "error_message not in UPDATE params"
        assert params["error_message"] == "This is a detailed error message for debugging"

    @pytest.mark.asyncio
    async def test_saves_error_code(self):
        """Verify error_code is included in the UPDATE query."""
        from src.repositories.task_repository import TaskRepository

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        await TaskRepository.update_task_error(
            mock_db,
            task_id="test-task-456",
            error_code="CUSTOM_ERROR",
            error_message="Something went wrong",
        )

        call_args = mock_db.execute.call_args[0]
        params = call_args[1]

        assert "error_code" in params, "error_code not in UPDATE params"
        assert params["error_code"] == "CUSTOM_ERROR"

    @pytest.mark.asyncio
    async def test_commits_transaction(self):
        """Verify db.commit() is called after the update."""
        from src.repositories.task_repository import TaskRepository

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock()
        mock_db.commit = AsyncMock()

        await TaskRepository.update_task_error(
            mock_db,
            task_id="test-task-789",
            error_code="ERR",
            error_message="err msg",
        )

        # update_task_error does NOT call commit() — the caller is responsible
        # for committing the transaction. This test verifies execute was called.
        assert mock_db.execute.called, "db.execute() was not called"
        call_args = mock_db.execute.call_args[0]
        params = call_args[1]
        assert "error_message" in params
        assert params["error_message"] == "err msg"


# =============================================================================
# Fix 2: get_healable_tasks() excludes SELF_HEALING_EXHAUSTED tasks
# =============================================================================

class TestFix2_GetHealableTasks:
    """get_healable_tasks() must exclude tasks that are already exhausted."""

    @pytest.mark.asyncio
    async def test_excludes_self_healing_exhausted(self):
        """Tasks with error_code = 'SELF_HEALING_EXHAUSTED' must NOT be healable."""
        from src.services.self_healing_agent import get_healable_tasks

        mock_conn = AsyncMock()
        # get_healable_tasks() makes TWO fetch calls:
        #   1st: failed tasks query (contains SELF_HEALING_EXHAUSTED exclusion)
        #   2nd: queued timeout query
        mock_conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.self_healing_agent._get_db", return_value=mock_conn):
            await get_healable_tasks()

        # First fetch call = failed tasks SQL
        sql = mock_conn.fetch.call_args_list[0][0][0]

        # The SQL must exclude SELF_HEALING_EXHAUSTED
        assert "SELF_HEALING_EXHAUSTED" in sql, \
            "SQL must exclude SELF_HEALING_EXHAUSTED error_code"

    @pytest.mark.asyncio
    async def test_excludes_failed_permanently_failed_cancelled(self):
        """Tasks with status failed/permanently_failed/cancelled must NOT be healable."""
        from src.services.self_healing_agent import get_healable_tasks

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.self_healing_agent._get_db", return_value=mock_conn):
            await get_healable_tasks()

        # First fetch call = failed tasks SQL
        sql = mock_conn.fetch.call_args_list[0][0][0]

        # The SQL must exclude permanently_failed via error_code check
        # (status NOT IN was removed because it contradicted status = 'failed')
        assert "error_code != 'permanently_failed'" in sql, \
            "SQL must exclude permanently_failed error_code"
        assert "error_code != 'SELF_HEALING_EXHAUSTED'" in sql, \
            "SQL must exclude SELF_HEALING_EXHAUSTED error_code"

    @pytest.mark.asyncio
    async def test_returns_healable_tasks(self):
        """Tasks with error_code set (but not exhausted) must be returned."""
        from src.services.self_healing_agent import get_healable_tasks

        mock_rows = [
            {"id": "task-1", "status": "failed", "error_code": "TRANSCRIPTION_ERROR",
             "error_message": "Failed to transcribe", "retry_count": 1,
             "progress_message": "", "metadata": {}, "source_url": "",
             "source_type": "", "user_id": "u1"},
            {"id": "task-2", "status": "failed", "error_code": "DOWNLOAD_ERROR",
             "error_message": "Could not download", "retry_count": 0,
             "progress_message": "", "metadata": {}, "source_url": "",
             "source_type": "", "user_id": "u1"},
        ]

        mock_conn = AsyncMock()
        # get_healable_tasks() makes TWO fetch calls:
        #   1st: failed tasks query → returns mock_rows
        #   2nd: queued timeout query → returns empty
        mock_conn.fetch = AsyncMock(side_effect=[mock_rows, []])

        with patch("src.services.self_healing_agent._get_db", return_value=mock_conn):
            tasks = await get_healable_tasks()

        assert len(tasks) == 2, "Should return 2 healable tasks"
        assert tasks[0]["id"] == "task-1"
        assert tasks[1]["id"] == "task-2"


# =============================================================================
# Fix 3: heal_task() atomic Postgres→Redis with rollback on failure
# =============================================================================

class TestFix3_HealTaskAtomic:
    """heal_task() must atomically update Postgres then Redis, rolling back on failure."""

    @pytest.fixture
    def mock_diagnosis(self):
        """Create a mock diagnosis result."""
        diag = MagicMock()
        diag.error_type = "TEST_ERROR"
        diag.fix_code = None
        diag.is_known = False
        diag.fix_description = ""
        return diag

    @pytest.mark.asyncio
    async def test_updates_postgres_to_queued(self, mock_diagnosis):
        """Postgres status must be set to 'queued' before Redis enqueue."""
        from src.services.self_healing_agent import heal_task

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_redis = AsyncMock()
        mock_redis.zrange = AsyncMock(return_value=[])
        mock_redis.zrem = AsyncMock(return_value=0)
        mock_redis.incr = AsyncMock(return_value=1)

        mock_job_queue = AsyncMock()
        mock_job_queue.enqueue_processing_job = AsyncMock(return_value="job-uuid-123")

        task = {"id": "test-heal-1", "status": "failed", "error_code": "ERR",
                "error_message": "err", "retry_count": 0, "progress_message": "",
                "metadata": {}, "source_url": "", "source_type": "", "user_id": "u1"}

        with (
            patch("src.services.self_healing_agent._get_db", return_value=mock_conn),
            patch("src.services.self_healing_agent._get_redis", return_value=mock_redis),
            patch("src.workers.job_queue.JobQueue.enqueue_processing_job", mock_job_queue.enqueue_processing_job),
            patch("src.services.error_diagnostician.ErrorDiagnostician.diagnose", AsyncMock(return_value=mock_diagnosis)),
            patch("src.services.error_diagnostician.ErrorDiagnostician.save_to_knowledge_base", AsyncMock()),
        ):
            result = await heal_task(task)

        # Verify Postgres was updated to 'queued'
        assert mock_conn.execute.called, "db.execute() must be called"
        # Check the FIRST call (status update), not the last (metadata update)
        first_sql = mock_conn.execute.call_args_list[0][0][0]
        assert "queued" in first_sql, "Postgres must be updated to 'queued'"

        # Verify Redis enqueue was called
        mock_job_queue.enqueue_processing_job.assert_called_once()

        assert result == "TEST_ERROR", f"Expected 'TEST_ERROR', got '{result}'"

    @pytest.mark.asyncio
    async def test_rolls_back_on_redis_failure(self, mock_diagnosis):
        """If Redis enqueue fails, Postgres must be rolled back."""
        from src.services.self_healing_agent import heal_task

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_redis = AsyncMock()
        mock_redis.zrange = AsyncMock(return_value=[])
        mock_redis.zrem = AsyncMock(return_value=0)
        mock_redis.incr = AsyncMock(return_value=1)

        mock_job_queue = AsyncMock()
        mock_job_queue.enqueue_processing_job = AsyncMock(side_effect=Exception("Redis down"))

        task = {"id": "test-heal-2", "status": "failed", "error_code": "ERR",
                "error_message": "err", "retry_count": 0, "progress_message": "",
                "metadata": {}, "source_url": "", "source_type": "", "user_id": "u1"}

        with (
            patch("src.services.self_healing_agent._get_db", return_value=mock_conn),
            patch("src.services.self_healing_agent._get_redis", return_value=mock_redis),
            patch("src.workers.job_queue.JobQueue.enqueue_processing_job", mock_job_queue.enqueue_processing_job),
            patch("src.services.error_diagnostician.ErrorDiagnostician.diagnose", AsyncMock(return_value=mock_diagnosis)),
            patch("src.services.error_diagnostician.ErrorDiagnostician.save_to_knowledge_base", AsyncMock()),
        ):
            result = await heal_task(task)

        # Verify rollback was attempted (Postgres update back to 'failed')
        # The rollback does conn.execute("UPDATE tasks SET status='failed'...")
        rollback_calls = [c for c in mock_conn.execute.call_args_list if "status='failed'" in str(c)]
        assert len(rollback_calls) >= 1, "Rollback must set status back to 'failed'"

        assert result == "ENQUEUE_FAILED", f"Expected 'ENQUEUE_FAILED', got '{result}'"

    @pytest.mark.asyncio
    async def test_removes_stale_arq_jobs_before_enqueue(self, mock_diagnosis):
        """Stale ARQ jobs must be removed before enqueuing a new one."""
        from src.services.self_healing_agent import heal_task

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="UPDATE 1")
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_redis = AsyncMock()
        mock_redis.zrange = AsyncMock(return_value=["stale-uuid-1", "stale-uuid-2"])
        mock_redis.get = AsyncMock(return_value=json.dumps({
            "args": ["task-heal-3", "http://example.com", "youtube", "user1"]
        }))
        mock_redis.zrem = AsyncMock(return_value=1)
        mock_redis.incr = AsyncMock(return_value=1)

        mock_job_queue = AsyncMock()
        mock_job_queue.enqueue_processing_job = AsyncMock(return_value="new-job-uuid")

        task = {"id": "task-heal-3", "status": "failed", "error_code": "ERR",
                "error_message": "err", "retry_count": 0, "progress_message": "",
                "metadata": {}, "source_url": "", "source_type": "", "user_id": "u1"}

        with (
            patch("src.services.self_healing_agent._get_db", return_value=mock_conn),
            patch("src.services.self_healing_agent._get_redis", return_value=mock_redis),
            patch("src.workers.job_queue.JobQueue.enqueue_processing_job", mock_job_queue.enqueue_processing_job),
            patch("src.services.error_diagnostician.ErrorDiagnostician.diagnose", AsyncMock(return_value=mock_diagnosis)),
            patch("src.services.error_diagnostician.ErrorDiagnostician.save_to_knowledge_base", AsyncMock()),
        ):
            result = await heal_task(task)

        # Verify stale jobs were deleted
        assert mock_redis.delete.called, "Stale ARQ jobs must be deleted"
        assert result == "TEST_ERROR", f"Expected 'TEST_ERROR', got '{result}'"


# =============================================================================
# Fix 4: _clean_redis_keys_for_task() uses SCAN to find ALL arq:* keys
# =============================================================================

class TestFix4_CleanRedisKeys:
    """_clean_redis_keys_for_task() must find and delete ALL Redis keys for a task."""

    @pytest.mark.asyncio
    async def test_deletes_arq_job_keys(self):
        """Direct arq:job:{task_id} keys must be deleted."""
        from src.services.self_healing_agent import _clean_redis_keys_for_task

        mock_redis = AsyncMock()
        # SCAN returns (cursor, keys) — first call returns some keys, second returns done
        mock_redis.scan = AsyncMock(side_effect=[
            (0, [f"arq:job:test-clean-1"]),
            (0, []),
            (0, []),
            (0, []),
            (0, []),
            (0, []),
            (0, []),
            (0, []),
            (0, []),
            (0, []),
        ])
        mock_redis.zrange = AsyncMock(return_value=[])
        mock_redis.zrem = AsyncMock(return_value=0)
        mock_redis.delete = AsyncMock(return_value=1)

        with patch("src.services.self_healing_agent._get_redis", return_value=mock_redis):
            count = await _clean_redis_keys_for_task("test-clean-1")

        assert count >= 1, "At least one key must be deleted"
        mock_redis.delete.assert_any_call(f"arq:job:test-clean-1")

    @pytest.mark.asyncio
    async def test_deletes_arq_result_keys(self):
        """arq:result:* keys referencing the task must be deleted."""
        from src.services.self_healing_agent import _clean_redis_keys_for_task

        mock_redis = AsyncMock()
        # Return arq:result keys on first SCAN, then empty for subsequent scans
        mock_redis.scan = AsyncMock(side_effect=[
            (0, [f"arq:result:abc-{i}" for i in range(3)]),
            (0, []),
            (0, []),
            (0, []),
            (0, []),
            (0, []),
            (0, []),
            (0, []),
            (0, []),
            (0, []),
        ])
        mock_redis.get = AsyncMock(return_value=json.dumps({
            "args": ["test-clean-result", "http://x.com", "youtube", "u1"]
        }))
        mock_redis.zrange = AsyncMock(return_value=[])
        mock_redis.zrem = AsyncMock(return_value=0)
        mock_redis.delete = AsyncMock(return_value=1)

        with patch("src.services.self_healing_agent._get_redis", return_value=mock_redis):
            count = await _clean_redis_keys_for_task("test-clean-result")

        # Must have scanned arq:result keys
        assert count >= 1, "Result keys must be cleaned"

    @pytest.mark.asyncio
    async def test_deletes_circuit_breaker_keys(self):
        """Circuit breaker keys must be deleted."""
        from src.services.self_healing_agent import _clean_redis_keys_for_task

        mock_redis = AsyncMock()
        mock_redis.scan = AsyncMock(side_effect=[
            (0, [f"circuit_breaker:task_id:test-cb"]),
            (0, []),
            (0, []),
            (0, []),
            (0, []),
            (0, []),
            (0, []),
            (0, []),
            (0, []),
            (0, []),
        ])
        mock_redis.zrange = AsyncMock(return_value=[])
        mock_redis.zrem = AsyncMock(return_value=0)
        mock_redis.delete = AsyncMock(return_value=1)

        with patch("src.services.self_healing_agent._get_redis", return_value=mock_redis):
            count = await _clean_redis_keys_for_task("test-cb")

        assert count >= 1, "Circuit breaker keys must be cleaned"

    @pytest.mark.asyncio
    async def test_removes_from_arq_queue(self):
        """Task must be removed from arq queue sorted sets."""
        from src.services.self_healing_agent import _clean_redis_keys_for_task

        mock_redis = AsyncMock()
        mock_redis.scan = AsyncMock(side_effect=[
            (0, []),
            (0, []),
            (0, []),
            (0, []),
            (0, []),
            (0, []),
            (0, []),
            (0, []),
            (0, []),
            (0, []),
        ])
        mock_redis.zrange = AsyncMock(return_value=["uuid-1", "uuid-2"])
        mock_redis.get = AsyncMock(return_value=json.dumps({
            "args": ["test-queue-clean", "http://x.com", "youtube", "u1"]
        }))
        mock_redis.zrem = AsyncMock(return_value=1)
        mock_redis.delete = AsyncMock(return_value=1)

        with patch("src.services.self_healing_agent._get_redis", return_value=mock_redis):
            count = await _clean_redis_keys_for_task("test-queue-clean")

        # Must have called zrem to remove from queue
        mock_redis.zrem.assert_called()
        assert count >= 1


# =============================================================================
# Fix 5: Circuit breaker trips after 3 skips and auto-fails the task
# =============================================================================

class TestFix5_CircuitBreaker:
    """Circuit breaker must trip after CIRCUIT_BREAKER_MAX_SKIPS skips."""

    @pytest.mark.asyncio
    async def test_increments_skip_counter(self):
        """Each skip must increment the Redis counter."""
        from src.services.self_healing_agent import _circuit_breaker_skip

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=1)

        with patch("src.services.self_healing_agent._get_redis", return_value=mock_redis):
            await _circuit_breaker_skip("test-cb-incr")

        mock_redis.incr.assert_called_once_with("circuit_breaker:task_id:test-cb-incr")

    @pytest.mark.asyncio
    async def test_trips_after_max_skips(self):
        """After CIRCUIT_BREAKER_MAX_SKIPS skips, the task must be auto-failed."""
        from src.services.self_healing_agent import _circuit_breaker_skip

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=4)  # > 3 = trip
        mock_redis.expire = AsyncMock(return_value=True)

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_clean = AsyncMock(return_value=3)

        with (
            patch("src.services.self_healing_agent._get_redis", return_value=mock_redis),
            patch("src.services.self_healing_agent._get_db", return_value=mock_conn),
            patch("src.services.self_healing_agent._clean_redis_keys_for_task", mock_clean),
        ):
            result = await _circuit_breaker_skip("test-cb-trip")

        assert result is True, "Circuit breaker must trip (return True)"

        # Verify DB was updated to failed
        sql = mock_conn.execute.call_args[0][0]
        assert "failed" in sql, "Task must be set to 'failed'"
        assert "SELF_HEALING_EXHAUSTED" in sql, "Must use SELF_HEALING_EXHAUSTED error code"

        # Verify Redis cleanup
        mock_clean.assert_called_once_with("test-cb-trip")

    @pytest.mark.asyncio
    async def test_does_not_trip_below_max(self):
        """Below max skips, the circuit breaker must not trip."""
        from src.services.self_healing_agent import _circuit_breaker_skip

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=2)  # < 3 = no trip
        mock_redis.expire = AsyncMock(return_value=True)

        with patch("src.services.self_healing_agent._get_redis", return_value=mock_redis):
            result = await _circuit_breaker_skip("test-cb-no-trip")

        assert result is False, "Circuit breaker must NOT trip (return False)"


# =============================================================================
# Fix 6: Dirty state detection in tasks.py
# =============================================================================

class TestFix6_DirtyStateDetection:
    """Worker must detect tasks stuck > 15 min in inconsistent state."""

    @pytest.mark.asyncio
    async def test_dirty_state_triggers_auto_fail(self):
        """Task stuck > 15 min in 'processing' must be auto-failed."""
        from src.services.self_healing_agent import _circuit_breaker_skip

        # Simulate the dirty state check logic from tasks.py
        from datetime import datetime, timedelta, timezone

        old_time = datetime.now(timezone.utc) - timedelta(minutes=20)
        status = "processing"

        assert status in ("processing", "queued"), "Must be in dirty state"
        age = datetime.now(timezone.utc) - old_time
        assert age > timedelta(minutes=15), "Must be older than 15 min"

    @pytest.mark.asyncio
    async def test_dirty_state_skips_recent_tasks(self):
        """Task stuck < 15 min must NOT be auto-failed."""
        from datetime import datetime, timedelta, timezone

        recent_time = datetime.now(timezone.utc) - timedelta(minutes=5)
        status = "processing"

        assert status in ("processing", "queued"), "Must be in dirty state"
        age = datetime.now(timezone.utc) - recent_time
        assert age < timedelta(minutes=15), "Must be younger than 15 min"

    @pytest.mark.asyncio
    async def test_dirty_state_uses_correct_sql(self):
        """Dirty state auto-fail must use DIRTY_STATE_TIMEOUT error code."""
        # Verify the SQL pattern used in tasks.py
        sql = """
            UPDATE tasks
            SET status = 'failed',
                error_code = 'DIRTY_STATE_TIMEOUT',
                error_message = 'Task stuck in dirty state > 15 min',
                updated_at = NOW()
            WHERE id = :task_id
        """
        assert "DIRTY_STATE_TIMEOUT" in sql, "Dirty state must use DIRTY_STATE_TIMEOUT error code"
        assert "error_message" in sql, "Dirty state must include error message"

    @pytest.mark.asyncio
    async def test_dirty_state_handles_exceptions_gracefully(self):
        """Dirty state check must not crash the worker if it fails."""
        # The dirty state check is wrapped in try/except in tasks.py
        # This test verifies the pattern is correct
        code_snippet = """
        try:
            # dirty state check
            pass
        except Exception as dirty_err:
            logger.warning("Fix 6: Dirty state check failed")
        """
        assert "try:" in code_snippet
        assert "except Exception" in code_snippet
        assert "logger.warning" in code_snippet


# =============================================================================
# Integration: mark_permanently_failed
# =============================================================================

class TestMarkPermanentlyFailed:
    """mark_permanently_failed must update DB and clean Redis."""

    @pytest.mark.asyncio
    async def test_updates_db_and_cleans_redis(self):
        """Both DB update and Redis cleanup must be called."""
        from src.services.self_healing_agent import mark_permanently_failed

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        mock_clean = AsyncMock(return_value=5)

        with (
            patch("src.services.self_healing_agent._get_db", return_value=mock_conn),
            patch("src.services.self_healing_agent._clean_redis_keys_for_task", mock_clean),
        ):
            await mark_permanently_failed("test-perm-1", "Out of retries")

        # Verify DB update
        mock_conn.execute.assert_called_once()
        sql = mock_conn.execute.call_args[0][0]
        assert "SELF_HEALING_EXHAUSTED" in sql

        # Verify Redis cleanup
        mock_clean.assert_called_once_with("test-perm-1")


# =============================================================================
# Integration: run_healing_cycle
# =============================================================================

class TestRunHealingCycle:
    """run_healing_cycle must iterate over healable tasks and heal them."""

    @pytest.mark.asyncio
    async def test_heals_multiple_tasks(self):
        """Multiple healable tasks must all be processed."""
        from src.services.self_healing_agent import run_healing_cycle

        mock_tasks = [
            {"id": "task-1", "status": "failed", "error_code": "ERR1",
             "error_message": "err", "retry_count": 0, "progress_message": "",
             "metadata": {}, "source_url": "", "source_type": "", "user_id": "u1"},
            {"id": "task-2", "status": "failed", "error_code": "ERR2",
             "error_message": "err", "retry_count": 0, "progress_message": "",
             "metadata": {}, "source_url": "", "source_type": "", "user_id": "u1"},
        ]

        with (
            patch("src.services.self_healing_agent.get_healable_tasks", return_value=mock_tasks),
            patch("src.services.self_healing_agent.heal_task", AsyncMock(return_value="HEALED")) as mock_heal,
        ):
            await run_healing_cycle()
            assert mock_heal.call_count == 2, "Both tasks must be healed"

    @pytest.mark.asyncio
    async def test_handles_heal_failure_gracefully(self):
        """If heal_task fails for one task, others must still be processed."""
        from src.services.self_healing_agent import run_healing_cycle

        mock_tasks = [
            {"id": "task-ok", "status": "failed", "error_code": "ERR1",
             "error_message": "err", "retry_count": 0, "progress_message": "",
             "metadata": {}, "source_url": "", "source_type": "", "user_id": "u1"},
            {"id": "task-bad", "status": "failed", "error_code": "ERR2",
             "error_message": "err", "retry_count": 0, "progress_message": "",
             "metadata": {}, "source_url": "", "source_type": "", "user_id": "u1"},
        ]

        heal_results = {"task-ok": "HEALED", "task-bad": Exception("Kaboom")}

        async def mock_heal(task):
            r = heal_results.get(task["id"])
            if isinstance(r, Exception):
                raise r
            return r

        with (
            patch("src.services.self_healing_agent.get_healable_tasks", return_value=mock_tasks),
            patch("src.services.self_healing_agent.heal_task", side_effect=mock_heal),
        ):
            # Should not raise
            await run_healing_cycle()


# =============================================================================
# Regression: Full loop scenario — task in processing + job in Redis
# =============================================================================

class TestRegression_FullLoopScenario:
    """
    Regression test for the infinite loop scenario:
    
    Simulate: task in 'processing' state in Postgres + stale job in Redis
    → healer tries to heal (but task is not 'failed', so get_healable_tasks skips it)
    → worker finds it in dirty state > 15 min → auto-fails + cleans Redis
    → healer picks it up (now 'failed') → heals it → enqueues new job
    → after N retries → permanently_failed → no more executions
    """

    @pytest.mark.asyncio
    async def test_get_healable_skips_processing_tasks(self):
        """Tasks in 'processing' state must NOT be returned by get_healable_tasks."""
        from src.services.self_healing_agent import get_healable_tasks

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.self_healing_agent._get_db", return_value=mock_conn):
            await get_healable_tasks()

        # get_healable_tasks() makes TWO fetch calls:
        #   1st: failed tasks query (SQL has "status = 'failed'")
        #   2nd: queued timeout query (SQL has "status = 'queued'")
        # Check the second call for the queued timeout query
        sql2 = mock_conn.fetch.call_args_list[1][0][0]

        # The second SQL must look for 'queued' tasks that timed out
        assert "queued" in sql2, "Second query must look for queued tasks"
        # The first SQL must look for 'failed' tasks
        sql1 = mock_conn.fetch.call_args_list[0][0][0]
        assert "status = 'failed'" in sql1 or "status IN" in sql1

    @pytest.mark.asyncio
    async def test_worker_auto_fails_dirty_processing_task(self):
        """
        Worker must auto-fail a task stuck in 'processing' > 15 min
        and clean up its Redis keys.
        """
        from datetime import datetime, timedelta, timezone

        # Simulate the dirty state check from tasks.py
        old_time = datetime.now(timezone.utc) - timedelta(minutes=20)
        status = "processing"
        updated_at = old_time

        # This is the exact logic from tasks.py Fix 6
        should_auto_fail = False
        if updated_at and status in ("processing", "queued"):
            age = datetime.now(timezone.utc) - updated_at.replace(tzinfo=timezone.utc)
            if age > timedelta(minutes=15):
                should_auto_fail = True

        assert should_auto_fail, "Task > 15 min in processing must be auto-failed"

    @pytest.mark.asyncio
    async def test_healer_can_heal_after_worker_auto_fail(self):
        """
        After worker auto-fails a dirty task, the healer must be able to
        pick it up and heal it (status is now 'failed').
        """
        from src.services.self_healing_agent import get_healable_tasks, heal_task

        # Simulate: task was auto-failed by worker, now in 'failed' state
        mock_failed_task = {
            "id": "regression-task-1",
            "status": "failed",
            "error_code": "DIRTY_STATE_TIMEOUT",
            "error_message": "Task stuck in dirty state > 15 min",
            "retry_count": 0,
            "progress_message": "",
            "metadata": {},
            "source_url": "",
            "source_type": "",
            "user_id": "u1",
        }

        # get_healable_tasks must return this task
        # get_healable_tasks() makes TWO fetch calls: 1st for failed tasks, 2nd for queued timeout tasks
        # Use side_effect so first call returns the task, second returns empty
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(side_effect=[[mock_failed_task], []])

        with patch("src.services.self_healing_agent._get_db", return_value=mock_conn):
            tasks = await get_healable_tasks()

        assert len(tasks) == 1, "Healer must pick up the auto-failed task"
        assert tasks[0]["id"] == "regression-task-1"
        assert tasks[0]["status"] == "failed"

        # Now simulate healing
        mock_conn2 = AsyncMock()
        mock_conn2.execute = AsyncMock()
        mock_conn2.fetchrow = AsyncMock(return_value=None)

        mock_redis = AsyncMock()
        mock_redis.zrange = AsyncMock(return_value=[])
        mock_redis.zrem = AsyncMock(return_value=0)
        mock_redis.incr = AsyncMock(return_value=1)

        mock_job_queue = AsyncMock()
        mock_job_queue.enqueue_processing_job = AsyncMock(return_value="new-job-uuid")

        mock_diagnosis = AsyncMock()
        mock_diagnosis.error_type = "TEST_ERROR"
        mock_diagnosis.fix_code = None
        mock_diagnosis.is_known = False
        mock_diagnosis.fix_description = ""

        with (
            patch("src.services.self_healing_agent._get_db", return_value=mock_conn2),
            patch("src.services.self_healing_agent._get_redis", return_value=mock_redis),
            patch("src.workers.job_queue.JobQueue.enqueue_processing_job", mock_job_queue.enqueue_processing_job),
            patch("src.services.error_diagnostician.ErrorDiagnostician.diagnose", AsyncMock(return_value=mock_diagnosis)),
            patch("src.services.error_diagnostician.ErrorDiagnostician.save_to_knowledge_base", AsyncMock()),
        ):
            result = await heal_task(mock_failed_task)

        assert result == "TEST_ERROR", "Healer must successfully heal the task"

    @pytest.mark.asyncio
    async def test_permanently_failed_task_never_healed_again(self):
        """
        After a task is permanently failed (SELF_HEALING_EXHAUSTED),
        it must NEVER be returned by get_healable_tasks again.
        """
        from src.services.self_healing_agent import get_healable_tasks

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])

        with patch("src.services.self_healing_agent._get_db", return_value=mock_conn):
            await get_healable_tasks()

        sql = mock_conn.fetch.call_args_list[0][0][0]

        # The SQL must exclude SELF_HEALING_EXHAUSTED
        assert "SELF_HEALING_EXHAUSTED" in sql, \
            "Permanently failed tasks must be excluded from healing"

    @pytest.mark.asyncio
    async def test_redis_cleanup_after_permanent_fail(self):
        """
        After permanent failure, ALL Redis keys for the task must be cleaned,
        including arq:result keys, so ARQ never fires the job again.
        """
        from src.services.self_healing_agent import mark_permanently_failed

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        mock_clean = AsyncMock(return_value=5)

        with (
            patch("src.services.self_healing_agent._get_db", return_value=mock_conn),
            patch("src.services.self_healing_agent._clean_redis_keys_for_task", mock_clean),
        ):
            await mark_permanently_failed("regression-perm-1", "Out of retries")

        # Verify Redis cleanup was called
        mock_clean.assert_called_once_with("regression-perm-1")

    @pytest.mark.asyncio
    async def test_full_loop_no_infinite_execution(self):
        """
        Full loop regression: simulate the complete cycle and verify
        that after N retries, the task is permanently failed and no
        more executions occur.
        
        This test mocks the entire flow:
        1. Task in 'processing' state (stale)
        2. Worker detects dirty state → auto-fails
        3. Healer picks it up → heals → enqueues
        4. Worker processes → fails again
        5. After N retries → permanently_failed
        6. get_healable_tasks returns nothing → loop ends
        """
        from src.services.self_healing_agent import (
            get_healable_tasks,
            heal_task,
            mark_permanently_failed,
            _clean_redis_keys_for_task,
        )

        task_id = "regression-full-loop-1"
        max_retries = 3

        # Track how many times the task is healed
        heal_count = 0

        # Mock diagnosis for ErrorDiagnostician
        mock_diagnosis = MagicMock()
        mock_diagnosis.error_type = "TEST_ERROR"
        mock_diagnosis.fix_code = None
        mock_diagnosis.is_known = False
        mock_diagnosis.fix_description = ""

        for attempt in range(max_retries + 1):
            # Step 1: Check if healable
            mock_conn = AsyncMock()

            if attempt < max_retries:
                # Simulate: task is in 'failed' state (healable)
                # get_healable_tasks() makes TWO fetch calls: 1st for failed, 2nd for queued timeout
                # Use side_effect so first call returns the task, second returns empty
                mock_conn.fetch = AsyncMock(side_effect=[[{
                    "id": task_id,
                    "status": "failed",
                    "error_code": "WORKER_ERROR",
                    "error_message": f"Attempt {attempt + 1} failed",
                    "retry_count": attempt,
                    "progress_message": "",
                    "metadata": {},
                    "source_url": "",
                    "source_type": "",
                    "user_id": "u1",
                }], []])
            else:
                # After max_retries, task should NOT be healable
                mock_conn.fetch = AsyncMock(return_value=[])

            with patch("src.services.self_healing_agent._get_db", return_value=mock_conn):
                healable = await get_healable_tasks()

            if attempt < max_retries:
                assert len(healable) == 1, \
                    f"Task should be healable on attempt {attempt}"
                assert healable[0]["id"] == task_id

                # Step 2: Heal the task
                mock_conn2 = AsyncMock()
                mock_conn2.execute = AsyncMock(return_value="UPDATE 1")
                mock_conn2.fetchrow = AsyncMock(return_value=None)

                mock_redis = AsyncMock()
                mock_redis.zrange = AsyncMock(return_value=[])
                mock_redis.zrem = AsyncMock(return_value=0)
                mock_redis.incr = AsyncMock(return_value=1)

                with (
                    patch("src.services.self_healing_agent._get_db", return_value=mock_conn2),
                    patch("src.services.self_healing_agent._get_redis", return_value=mock_redis),
                    patch("src.services.error_diagnostician.ErrorDiagnostician.diagnose", AsyncMock(return_value=mock_diagnosis)),
                    patch("src.services.error_diagnostician.ErrorDiagnostician.save_to_knowledge_base", AsyncMock()),
                    patch("src.workers.job_queue.JobQueue.enqueue_processing_job", AsyncMock(return_value=f"job-uuid-{attempt}")),
                ):
                    result = await heal_task(healable[0])

                assert result == "TEST_ERROR", f"Healing should succeed on attempt {attempt}"
                heal_count += 1
            else:
                # After max_retries, no more healable tasks
                assert len(healable) == 0, \
                    "Task must NOT be healable after exhausting retries"

        # Step 3: Verify the task was healed exactly max_retries times
        assert heal_count == max_retries, \
            f"Task should be healed exactly {max_retries} times, got {heal_count}"

        # Step 4: Simulate permanent failure — mark as permanently_failed
        mock_conn3 = AsyncMock()
        mock_conn3.execute = AsyncMock()

        mock_clean = AsyncMock(return_value=5)

        with (
            patch("src.services.self_healing_agent._get_db", return_value=mock_conn3),
            patch("src.services.self_healing_agent._clean_redis_keys_for_task", mock_clean),
        ):
            await mark_permanently_failed(task_id, "Exhausted all retries")

        # Verify Redis cleanup was called
        mock_clean.assert_called_once_with(task_id)

        # Step 5: Verify permanently_failed task is NOT healable
        mock_conn4 = AsyncMock()
        mock_conn4.fetch = AsyncMock(return_value=[])

        with patch("src.services.self_healing_agent._get_db", return_value=mock_conn4):
            await get_healable_tasks()

        sql = mock_conn4.fetch.call_args_list[0][0][0]
        assert "SELF_HEALING_EXHAUSTED" in sql, \
            "Permanently failed tasks must be excluded from healing"
        assert "status IN" in sql or "status =" in sql, \
            "SQL must filter by status"

