"""Tests for dry_run mode — ContextVar isolation."""
import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.core.dry_run import (
    set_dry_run,
    is_dry_run,
    dry_run_skip,
    get_dry_run_report,
)


@pytest.fixture(autouse=True)
def reset_dry_run():
    set_dry_run(False)
    yield


def test_is_dry_run_default_false():
    """Default → False."""
    assert is_dry_run() is False


def test_set_dry_run_true():
    """set_dry_run(True) → is_dry_run() returns True."""
    set_dry_run(True)
    assert is_dry_run() is True


@pytest.mark.asyncio
async def test_dry_run_context_isolation():
    """Two coroutines see their own dry_run values."""
    async def check(val):
        set_dry_run(val)
        await asyncio.sleep(0.01)
        return is_dry_run()

    r1, r2 = await asyncio.gather(check(True), check(False))
    assert r1 is True
    assert r2 is False


def test_dry_run_skip_logs_info():
    """dry_run_skip logs with DRY RUN prefix."""
    set_dry_run(True)
    with patch("src.core.dry_run.logging.getLogger") as mock_logger:
        logger = MagicMock()
        mock_logger.return_value = logger
        dry_run_skip("transcription", url="https://youtube.com/test")
        logger.info.assert_called_once()
        msg = logger.info.call_args[0]
        assert "DRY RUN" in str(msg)
        assert "transcription" in str(msg)


def test_dry_run_report_contains_actions():
    """get_dry_run_report returns accumulated actions."""
    set_dry_run(True)
    dry_run_skip("llm_scoring", provider="deepseek")
    dry_run_skip("render_clip", segment=0)
    report = get_dry_run_report()
    assert len(report["actions_skipped"]) == 2
    assert "llm_scoring" in report["actions_skipped"][0]
    assert "render_clip" in report["actions_skipped"][1]
