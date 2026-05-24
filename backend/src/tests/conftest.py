"""
pytest conftest — shared fixtures for transition regression tests.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Iterator

import numpy as np
import pytest
from moviepy import ColorClip


@pytest.fixture(scope="function")
def tmp_output_dir() -> Iterator[Path]:
    """Provide a temporary directory for test outputs and clean it up after."""
    tmpdir = Path(tempfile.mkdtemp(prefix="viraclip_test_"))
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


def make_test_clip(
    width: int = 640,
    height: int = 480,
    duration: float = 2.0,
    fps: float = 24,
    color: tuple[int, int, int] = (30, 80, 180),
) -> ColorClip:
    """
    Create a simple solid-color ColorClip for testing transitions.

    Parameters
    ----------
    width : int
        Frame width (default 640).
    height : int
        Frame height (default 480).
    duration : float
        Clip duration in seconds (default 2.0).
    fps : float
        Frames per second (default 24).
    color : tuple[int, int, int]
        RGB color tuple (default blue-ish).

    Returns
    -------
    ColorClip
        A MoviePy ColorClip ready for transition testing.
    """
    clip = ColorClip(size=(width, height), color=color, duration=duration)
    clip = clip.with_fps(fps)
    return clip
