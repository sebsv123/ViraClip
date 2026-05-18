"""
Editlist Service — declarative JSON editlist for video editing operations.

Provides a structured format to describe video edits (cuts, concat, overlays,
transitions) and applies them via the appropriate pipeline (clip_editor.py for
cuts/concat, overlay_renderer.py for overlays, transitions_service.py for
transitions).

Feature flags in Config control which operations are enabled:
  - EDITLIST_ENABLE_CUTS (default True): trim, split, concat
  - EDITLIST_ENABLE_OVERLAYS (default False): PiP, split-screen, bubble
  - EDITLIST_ENABLE_TRANSITIONS (default False): crossfade, slide, fade_black

Phase 1: Only cuts/concat are enabled. B-roll, LUTs, zoom, etc. remain in the
current pipeline (EditingPipeline.apply()).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ── Operation Types ──────────────────────────────────────────────────────────

class EditOpType(str, Enum):
    """Types of edit operations supported by the editlist."""
    CUT = "cut"               # Trim a segment from source
    CONCAT = "concat"         # Concatenate multiple segments
    OVERLAY = "overlay"       # Picture-in-picture, split-screen, bubble
    TRANSITION = "transition" # Crossfade, slide, fade_black between segments


class OverlayStyle(str, Enum):
    """Overlay visual styles."""
    FULL_SCREEN_BUBBLE = "full_screen_bubble"
    SPLIT_SCREEN = "split_screen"
    PICTURE_IN_PICTURE = "picture_in_picture"


class TransitionType(str, Enum):
    """Transition types between clips."""
    CROSSFADE = "crossfade"
    FADE_BLACK = "fade_black"
    SLIDE_LEFT = "slide_left"
    HARD_CUT = "hard_cut"  # fallback


# ── Data Models ──────────────────────────────────────────────────────────────

@dataclass
class CutParams:
    """Parameters for a CUT operation."""
    source_path: str
    start_offset: float = 0.0
    end_offset: float = 0.0
    segment_index: int = 0  # which segment in the source


@dataclass
class ConcatParams:
    """Parameters for a CONCAT operation."""
    segment_paths: list[str] = field(default_factory=list)


@dataclass
class OverlayParams:
    """Parameters for an OVERLAY operation."""
    overlay_path: str
    style: OverlayStyle = OverlayStyle.PICTURE_IN_PICTURE
    start_time: float = 0.0
    duration: float = 5.0
    x: Optional[int] = None  # position override
    y: Optional[int] = None
    scale: float = 0.3  # relative scale for PiP


@dataclass
class TransitionParams:
    """Parameters for a TRANSITION operation."""
    transition_type: TransitionType = TransitionType.CROSSFADE
    duration: float = 0.5
    from_segment_index: int = 0
    to_segment_index: int = 1


@dataclass
class EditOperation:
    """A single edit operation in the editlist."""
    op_type: EditOpType
    params: dict[str, Any] = field(default_factory=dict)
    operation_id: str = ""
    enabled: bool = True

    def __post_init__(self):
        if not self.operation_id:
            import uuid
            self.operation_id = f"{self.op_type.value}_{uuid.uuid4().hex[:8]}"


@dataclass
class Editlist:
    """A complete editlist — ordered list of operations + metadata."""
    operations: list[EditOperation] = field(default_factory=list)
    version: str = "1.0"
    created_at: str = ""
    clip_id: str = ""
    task_id: str = ""
    source_path: str = ""
    safe_mode: bool = False  # True = cuts/concat only

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self._to_dict(), indent=indent)

    def _to_dict(self) -> dict:
        return {
            "version": self.version,
            "created_at": self.created_at,
            "clip_id": self.clip_id,
            "task_id": self.task_id,
            "source_path": self.source_path,
            "safe_mode": self.safe_mode,
            "operations": [
                {
                    "op_type": op.op_type.value,
                    "params": op.params,
                    "operation_id": op.operation_id,
                    "enabled": op.enabled,
                }
                for op in self.operations
            ],
        }

    @classmethod
    def from_json(cls, raw: str | dict) -> "Editlist":
        """Deserialize from JSON string or dict."""
        if isinstance(raw, str):
            data = json.loads(raw)
        else:
            data = raw
        ops = []
        for op_data in data.get("operations", []):
            ops.append(EditOperation(
                op_type=EditOpType(op_data["op_type"]),
                params=op_data.get("params", {}),
                operation_id=op_data.get("operation_id", ""),
                enabled=op_data.get("enabled", True),
            ))
        return cls(
            operations=ops,
            version=data.get("version", "1.0"),
            created_at=data.get("created_at", ""),
            clip_id=data.get("clip_id", ""),
            task_id=data.get("task_id", ""),
            source_path=data.get("source_path", ""),
            safe_mode=data.get("safe_mode", False),
        )

    def get_safe_editlist(self) -> "Editlist":
        """Return a new editlist with only cuts and concat operations."""
        safe_ops = [
            op for op in self.operations
            if op.op_type in (EditOpType.CUT, EditOpType.CONCAT)
        ]
        return Editlist(
            operations=safe_ops,
            version=self.version,
            created_at=self.created_at,
            clip_id=self.clip_id,
            task_id=self.task_id,
            source_path=self.source_path,
            safe_mode=True,
        )

    def count_by_type(self) -> dict[str, int]:
        """Count operations by type."""
        counts: dict[str, int] = {}
        for op in self.operations:
            if op.enabled:
                counts[op.op_type.value] = counts.get(op.op_type.value, 0) + 1
        return counts


# ── Service ──────────────────────────────────────────────────────────────────

class EditlistService:
    """Service to generate, serialize, and apply editlists."""

    def __init__(self, config: Any = None):
        self._config = config
        self._load_config()

    def _load_config(self):
        """Load feature flags from config."""
        if self._config is None:
            try:
                from src.config import get_config
                self._config = get_config()
            except ImportError:
                self._config = None

    @property
    def cuts_enabled(self) -> bool:
        return bool(getattr(self._config, "editlist_enable_cuts", True))

    @property
    def overlays_enabled(self) -> bool:
        return bool(getattr(self._config, "editlist_enable_overlays", False))

    @property
    def transitions_enabled(self) -> bool:
        return bool(getattr(self._config, "editlist_enable_transitions", False))

    @property
    def editlist_enabled(self) -> bool:
        return bool(getattr(self._config, "editlist_enabled", True))

    # ── Generation ───────────────────────────────────────────────────────

    def generate_from_segments(
        self,
        segments: list[dict],
        clip_id: str = "",
        task_id: str = "",
        source_path: str = "",
    ) -> Editlist:
        """Generate an editlist from segment data.

        Segments is a list of dicts with keys:
          - source_path: str
          - start_offset: float
          - end_offset: float
          - overlay: Optional[dict] with style, path, timing
          - transition: Optional[dict] with type, duration
        """
        editlist = Editlist(
            clip_id=clip_id,
            task_id=task_id,
            source_path=source_path,
        )

        # Phase 1: CUT operations for each segment
        if self.cuts_enabled:
            for i, seg in enumerate(segments):
                cut_op = EditOperation(
                    op_type=EditOpType.CUT,
                    params={
                        "source_path": seg.get("source_path", source_path),
                        "start_offset": seg.get("start_offset", 0.0),
                        "end_offset": seg.get("end_offset", 0.0),
                        "segment_index": i,
                    },
                )
                editlist.operations.append(cut_op)

        # CONCAT: merge all segments
        if self.cuts_enabled and len(segments) > 1:
            concat_op = EditOperation(
                op_type=EditOpType.CONCAT,
                params={
                    "segment_paths": [],  # filled at apply time
                    "segment_count": len(segments),
                },
            )
            editlist.operations.append(concat_op)

        # Phase 2: OVERLAY operations (disabled by default)
        if self.overlays_enabled:
            for i, seg in enumerate(segments):
                overlay = seg.get("overlay")
                if overlay:
                    overlay_op = EditOperation(
                        op_type=EditOpType.OVERLAY,
                        params={
                            "overlay_path": overlay.get("path", ""),
                            "style": overlay.get("style", OverlayStyle.PICTURE_IN_PICTURE.value),
                            "start_time": overlay.get("start_time", 0.0),
                            "duration": overlay.get("duration", 5.0),
                            "scale": overlay.get("scale", 0.3),
                            "segment_index": i,
                        },
                    )
                    editlist.operations.append(overlay_op)

        # Phase 3: TRANSITION operations (disabled by default)
        if self.transitions_enabled:
            for i, seg in enumerate(segments):
                transition = seg.get("transition")
                if transition and i < len(segments) - 1:
                    trans_op = EditOperation(
                        op_type=EditOpType.TRANSITION,
                        params={
                            "transition_type": transition.get("type", TransitionType.CROSSFADE.value),
                            "duration": transition.get("duration", 0.5),
                            "from_segment_index": i,
                            "to_segment_index": i + 1,
                        },
                    )
                    editlist.operations.append(trans_op)

        return editlist

    # ── Application ───────────────────────────────────────────────────────

    async def apply(
        self,
        editlist: Editlist,
        output_dir: Path,
        temp_dir: Optional[Path] = None,
    ) -> Path:
        """Apply an editlist and produce the final video.

        Respects feature flags: operations of disabled types are skipped.
        Falls back to safe mode (cuts/concat only) if complex ops fail.
        """
        if not self.editlist_enabled:
            logger.info("[Editlist] Editlist disabled — skipping")
            raise RuntimeError("Editlist pipeline is disabled")

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        temp_dir = Path(temp_dir) if temp_dir else output_dir / "temp_editlist"
        temp_dir.mkdir(parents=True, exist_ok=True)

        # Filter operations by feature flags
        enabled_ops = self._filter_enabled_ops(editlist)
        if not enabled_ops:
            raise ValueError("No enabled operations in editlist")

        logger.info(
            "[Editlist] Applying editlist for clip %s: %d ops (%s)",
            editlist.clip_id[:12] if editlist.clip_id else "?",
            len(enabled_ops),
            editlist.count_by_type(),
        )

        # Phase 1: Apply CUT operations → produce trimmed segments
        segment_paths: list[Path] = []
        for op in enabled_ops:
            if op.op_type == EditOpType.CUT:
                seg_path = await self._apply_cut(op, temp_dir)
                if seg_path:
                    segment_paths.append(seg_path)

        if not segment_paths:
            raise RuntimeError("No segments produced from CUT operations")

        # Phase 2: Apply CONCAT → merge segments
        if len(segment_paths) > 1:
            merged = await self._apply_concat(segment_paths, temp_dir)
        else:
            merged = segment_paths[0]

        # Phase 3: Apply OVERLAY operations (if enabled)
        current = merged
        for op in enabled_ops:
            if op.op_type == EditOpType.OVERLAY:
                current = await self._apply_overlay(current, op, temp_dir)

        # Phase 4: Apply TRANSITION operations (if enabled)
        for op in enabled_ops:
            if op.op_type == EditOpType.TRANSITION:
                current = await self._apply_transition(current, op, temp_dir, segment_paths)

        # Move to final output
        import shutil
        import uuid
        final_path = output_dir / f"editlist_{uuid.uuid4().hex[:12]}.mp4"
        shutil.copy2(str(current), str(final_path))

        logger.info(
            "[Editlist] Applied editlist for clip %s → %s",
            editlist.clip_id[:12] if editlist.clip_id else "?",
            final_path,
        )
        return final_path

    def _filter_enabled_ops(self, editlist: Editlist) -> list[EditOperation]:
        """Filter operations based on feature flags."""
        enabled = []
        for op in editlist.operations:
            if not op.enabled:
                continue
            if op.op_type == EditOpType.CUT and not self.cuts_enabled:
                continue
            if op.op_type == EditOpType.CONCAT and not self.cuts_enabled:
                continue
            if op.op_type == EditOpType.OVERLAY and not self.overlays_enabled:
                continue
            if op.op_type == EditOpType.TRANSITION and not self.transitions_enabled:
                continue
            enabled.append(op)
        return enabled

    async def _apply_cut(self, op: EditOperation, temp_dir: Path) -> Optional[Path]:
        """Apply a CUT operation using clip_editor.trim_clip_file."""
        try:
            from src.clip_editor import trim_clip_file

            source = Path(op.params.get("source_path", ""))
            if not source.exists():
                logger.warning("[Editlist] Source not found: %s", source)
                return None

            start = float(op.params.get("start_offset", 0.0))
            end = float(op.params.get("end_offset", 0.0))
            result = trim_clip_file(source, temp_dir, start, end)
            logger.debug("[Editlist] CUT %s → %s", source.name, result.name)
            return result
        except Exception as exc:
            logger.error("[Editlist] CUT failed: %s", exc)
            raise

    async def _apply_concat(self, segment_paths: list[Path], temp_dir: Path) -> Path:
        """Apply a CONCAT operation using clip_editor.merge_clip_files."""
        try:
            from src.clip_editor import merge_clip_files

            result = merge_clip_files(segment_paths, temp_dir)
            logger.debug("[Editlist] CONCAT %d segments → %s", len(segment_paths), result.name)
            return result
        except Exception as exc:
            logger.error("[Editlist] CONCAT failed: %s", exc)
            raise

    async def _apply_overlay(
        self, current: Path, op: EditOperation, temp_dir: Path
    ) -> Path:
        """Apply an OVERLAY operation using overlay_renderer."""
        try:
            from src.video_processing.overlay_renderer import OverlayRenderer, OverlayEvent, OverlayStyle

            style_str = op.params.get("style", "picture_in_picture")
            style_map = {
                "full_screen_bubble": OverlayStyle.FULL_SCREEN_BUBBLE,
                "split_screen": OverlayStyle.SPLIT_SCREEN,
                "picture_in_picture": OverlayStyle.PICTURE_IN_PICTURE,
            }
            style = style_map.get(style_str, OverlayStyle.PICTURE_IN_PICTURE)

            event = OverlayEvent(
                overlay_path=op.params.get("overlay_path", ""),
                start_time=float(op.params.get("start_time", 0.0)),
                duration=float(op.params.get("duration", 5.0)),
                style=style,
            )

            renderer = OverlayRenderer()
            result = temp_dir / f"overlay_{op.operation_id}.mp4"
            await renderer.render_overlays(str(current), str(result), [event])
            logger.debug("[Editlist] OVERLAY %s → %s", current.name, result.name)
            return result
        except Exception as exc:
            logger.error("[Editlist] OVERLAY failed: %s", exc)
            raise

    async def _apply_transition(
        self, current: Path, op: EditOperation, temp_dir: Path, segment_paths: list[Path]
    ) -> Path:
        """Apply a TRANSITION operation using transitions_service."""
        try:
            from src.services.transitions_service import apply_transition

            trans_type = op.params.get("transition_type", "crossfade")
            duration = float(op.params.get("duration", 0.5))
            from_idx = int(op.params.get("from_segment_index", 0))
            to_idx = int(op.params.get("to_segment_index", 1))

            if from_idx >= len(segment_paths) or to_idx >= len(segment_paths):
                logger.warning("[Editlist] Transition indices out of range, skipping")
                return current

            result = temp_dir / f"transition_{op.operation_id}.mp4"
            apply_transition(
                str(segment_paths[from_idx]),
                str(segment_paths[to_idx]),
                str(result),
                trans_type,
                duration,
            )
            logger.debug("[Editlist] TRANSITION %s → %s", current.name, result.name)
            return result
        except Exception as exc:
            logger.error("[Editlist] TRANSITION failed: %s", exc)
            raise

    # ── Safe fallback ─────────────────────────────────────────────────────

    async def apply_safe(
        self,
        editlist: Editlist,
        output_dir: Path,
        temp_dir: Optional[Path] = None,
    ) -> Path:
        """Apply a safe (cuts/concat only) version of the editlist.

        This is used by the self-healing agent when complex operations fail.
        The original editlist is preserved for post-mortem analysis.
        """
        safe = editlist.get_safe_editlist()
        logger.info(
            "[Editlist] Applying safe editlist (cuts only) for clip %s",
            editlist.clip_id[:12] if editlist.clip_id else "?",
        )
        return await self.apply(safe, output_dir, temp_dir)

    # ── Persistence ───────────────────────────────────────────────────────

    @staticmethod
    async def save_editlist(editlist: Editlist, path: Path) -> None:
        """Save editlist to a JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(editlist.to_json())
        logger.debug("[Editlist] Saved editlist to %s", path)

    @staticmethod
    async def load_editlist(path: Path) -> Editlist:
        """Load editlist from a JSON file."""
        path = Path(path)
        raw = path.read_text()
        return Editlist.from_json(raw)

    @staticmethod
    async def save_editlist_to_redis(editlist: Editlist, task_id: str) -> None:
        """Save editlist to Redis for post-mortem analysis."""
        try:
            import redis.asyncio as aioredis
            import os
            r = await aioredis.from_url(
                f"redis://{os.getenv('REDIS_HOST', 'redis')}:{os.getenv('REDIS_PORT', '6379')}",
                decode_responses=True,
            )
            key = f"editlist:original:{task_id}"
            await r.setex(key, 86400 * 7, editlist.to_json())  # 7 day TTL
            await r.aclose()
            logger.info("[Editlist] Saved original editlist to Redis: %s", key)
        except Exception as exc:
            logger.warning("[Editlist] Failed to save editlist to Redis: %s", exc)

    @staticmethod
    async def load_editlist_from_redis(task_id: str) -> Optional["Editlist"]:
        """Load editlist from Redis."""
        try:
            import redis.asyncio as aioredis
            import os
            r = await aioredis.from_url(
                f"redis://{os.getenv('REDIS_HOST', 'redis')}:{os.getenv('REDIS_PORT', '6379')}",
                decode_responses=True,
            )
            key = f"editlist:original:{task_id}"
            raw = await r.get(key)
            await r.aclose()
            if raw:
                return Editlist.from_json(raw)
        except Exception as exc:
            logger.warning("[Editlist] Failed to load editlist from Redis: %s", exc)
        return None
