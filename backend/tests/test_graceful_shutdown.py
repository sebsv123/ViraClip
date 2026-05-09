"""Tests for graceful shutdown — active task tracking."""
from src.worker_main import register_active_task, unregister_active_task, _active_tasks


def setup_method():
    _active_tasks.clear()


def test_register_adds_task_id():
    """register_active_task adds task to set."""
    register_active_task("task_abc")
    assert "task_abc" in _active_tasks


def test_unregister_removes_task_id():
    """unregister_active_task removes task from set."""
    register_active_task("task_abc")
    unregister_active_task("task_abc")
    assert "task_abc" not in _active_tasks


def test_unregister_nonexistent_no_error():
    """unregister_active_task with nonexistent id → no error."""
    unregister_active_task("nonexistent_task")
    assert True  # No exception
