"""
Unit tests for BUG 4 fix: atomic status transitions and idempotency in task processing.

BUG 4: Multiple workers can race to process the same task, causing duplicate
processing. The fix adds:
1. update_task_status_atomic() — only updates if status matches expected_current_status
2. find_task_by_user_and_url() — idempotency check to prevent duplicate submissions
"""

from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
import pytest
from sqlalchemy.ext.asyncio import AsyncSession


class TestUpdateTaskStatusAtomic:
    """Tests for the update_task_status_atomic method."""

    @pytest.fixture
    def repo(self):
        from src.repositories.task_repository import TaskRepository
        return TaskRepository()

    @pytest.fixture
    def mock_db(self):
        db = AsyncMock(spec=AsyncSession)
        # Mock execute to return a result with rowcount
        mock_result = MagicMock()
        mock_result.rowcount = 1
        db.execute.return_value = mock_result
        return db

    @pytest.mark.asyncio
    async def test_atomic_update_success(self, repo, mock_db):
        """Atomic update should return True when status matches expected."""
        result = await repo.update_task_status_atomic(
            db=mock_db,
            task_id="task-123",
            new_status="processing",
            expected_current_status="queued",
            progress=0,
            progress_message="Starting...",
        )
        assert result is True
        # Verify the SQL had a WHERE clause checking expected status
        call_sql = mock_db.execute.call_args[0][0].text
        assert "WHERE id = :task_id AND status = :expected_status" in call_sql

    @pytest.mark.asyncio
    async def test_atomic_update_failure(self, repo):
        """Atomic update should return False when status doesn't match."""
        db = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.rowcount = 0  # No rows updated
        db.execute.return_value = mock_result

        result = await repo.update_task_status_atomic(
            db=db,
            task_id="task-123",
            new_status="processing",
            expected_current_status="queued",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_atomic_update_with_progress(self, repo, mock_db):
        """Atomic update should include progress in the SET clause."""
        await repo.update_task_status_atomic(
            db=mock_db,
            task_id="task-123",
            new_status="processing",
            expected_current_status="queued",
            progress=50,
            progress_message="Halfway there",
        )
        call_sql = mock_db.execute.call_args[0][0].text
        assert "progress = :progress" in call_sql
        assert "progress_message = :progress_message" in call_sql

    @pytest.mark.asyncio
    async def test_atomic_update_without_progress(self, repo, mock_db):
        """Atomic update should work without progress params."""
        await repo.update_task_status_atomic(
            db=mock_db,
            task_id="task-123",
            new_status="completed",
            expected_current_status="processing",
        )
        call_sql = mock_db.execute.call_args[0][0].text
        assert "progress = :progress" not in call_sql
        assert "progress_message = :progress_message" not in call_sql

    @pytest.mark.asyncio
    async def test_atomic_update_commits(self, repo, mock_db):
        """Atomic update should call db.commit()."""
        await repo.update_task_status_atomic(
            db=mock_db,
            task_id="task-123",
            new_status="processing",
            expected_current_status="queued",
        )
        mock_db.commit.assert_called_once()


class TestFindTaskByUserAndUrl:
    """Tests for the find_task_by_user_and_url method."""

    @pytest.fixture
    def repo(self):
        from src.repositories.task_repository import TaskRepository
        return TaskRepository()

    @pytest.mark.asyncio
    async def test_finds_existing_task(self, repo):
        """Should return task dict when a matching task exists."""
        db = AsyncMock(spec=AsyncSession)
        mock_row = MagicMock()
        mock_row.id = "task-123"
        mock_row.status = "queued"
        mock_row.user_id = "user-456"
        mock_row.created_at = "2026-01-01T00:00:00"
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        db.execute.return_value = mock_result

        result = await repo.find_task_by_user_and_url(
            db=db, user_id="user-456", url="https://youtube.com/watch?v=abc123"
        )
        assert result is not None
        assert result["id"] == "task-123"
        assert result["status"] == "queued"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_task(self, repo):
        """Should return None when no matching task exists."""
        db = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        db.execute.return_value = mock_result

        result = await repo.find_task_by_user_and_url(
            db=db, user_id="user-456", url="https://youtube.com/watch?v=abc123"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_db_error(self, repo):
        """Should return None gracefully when DB query fails."""
        db = AsyncMock(spec=AsyncSession)
        db.execute.side_effect = Exception("DB connection error")

        result = await repo.find_task_by_user_and_url(
            db=db, user_id="user-456", url="https://youtube.com/watch?v=abc123"
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_rollback_on_error(self, repo):
        """Should call db.rollback() when DB query fails."""
        db = AsyncMock(spec=AsyncSession)
        db.execute.side_effect = Exception("DB connection error")

        await repo.find_task_by_user_and_url(
            db=db, user_id="user-456", url="https://youtube.com/watch?v=abc123"
        )
        db.rollback.assert_called_once()

    @pytest.mark.asyncio
    async def test_queries_only_queued_or_processing(self, repo):
        """Should only find tasks with status 'queued' or 'processing'."""
        db = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        db.execute.return_value = mock_result

        await repo.find_task_by_user_and_url(
            db=db, user_id="user-456", url="https://youtube.com/watch?v=abc123"
        )
        call_sql = db.execute.call_args[0][0].text
        assert "queued" in call_sql
        assert "processing" in call_sql
        # Should NOT include completed/failed tasks
        assert "completed" not in call_sql or "AND t.status NOT IN" in call_sql


class TestProcessVideoTaskAtomicGuard:
    """Tests for the atomic status guard in process_video_task."""

    @patch("src.repositories.task_repository.TaskRepository")
    @patch("src.database.AsyncSessionLocal")
    @pytest.mark.asyncio
    async def test_guard_skips_when_not_queued(self, mock_session_local, mock_repo_class):
        """When task status is not 'queued', the guard should skip processing."""
        from src.workers.tasks import process_video_task

        # Mock the async context manager
        mock_db = AsyncMock()
        mock_session_local.return_value.__aenter__.return_value = mock_db

        # Mock repo to return False (status didn't match)
        mock_repo = AsyncMock()
        mock_repo.update_task_status_atomic.return_value = False
        mock_repo_class.return_value = mock_repo

        ctx = {"redis": MagicMock()}
        result = await process_video_task(ctx, task_id="task-123", url="https://example.com/video.mp4", source_type="youtube", user_id="user-1")

        assert result["status"] == "skipped"
        assert result["reason"] == "already_processing"

    @patch("src.domains.autopilot.task_service.TaskService.process_task")
    @patch("src.repositories.task_repository.TaskRepository")
    @patch("src.database.AsyncSessionLocal")
    @pytest.mark.asyncio
    async def test_guard_proceeds_when_queued(self, mock_session_local, mock_repo_class, mock_process_task):
        """When task status is 'queued', the guard should allow processing."""
        from src.workers.tasks import process_video_task

        mock_db = AsyncMock()
        mock_session_local.return_value.__aenter__.return_value = mock_db

        # Mock repo to return True (status matched)
        mock_repo = AsyncMock()
        mock_repo.update_task_status_atomic.return_value = True
        mock_repo_class.return_value = mock_repo

        # Mock process_task to return a success result
        mock_process_task.return_value = {"status": "completed", "task_id": "task-123"}

        ctx = {"redis": MagicMock()}
        result = await process_video_task(ctx, task_id="task-123", url="https://example.com/video.mp4", source_type="youtube", user_id="user-1")

        # Should not be skipped (will proceed to actual processing)
        assert result.get("status") != "skipped"
