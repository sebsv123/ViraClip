"""Clip editing mixin — trim/split/merge/update operations."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import redis.asyncio as redis

from ...clip_editor import (
    merge_clip_files,
    overlay_custom_captions,
    split_clip_file,
    trim_clip_file,
)
from ...video_processing.utils import parse_timestamp_to_seconds

logger = logging.getLogger(__name__)

class _EditorMixin:
    """Mixin providing EditorMixin methods."""

    @staticmethod
    def _segment_field(segment: Any, field: str, default: Any = None) -> Any:
        if isinstance(segment, dict):
            return segment.get(field, default)
        return getattr(segment, field, default)

    async def _get_render_source_settings(self, task_id: str) -> tuple[str, bool]:
        output_format = "vertical"
        add_subtitles = True

        redis_client = redis.Redis(
            host=self.config.redis_host,
            port=self.config.redis_port,
            password=self.config.redis_password,
            decode_responses=True,
        )
        try:
            source_payload = await redis_client.get(f"task_source:{task_id}")
            if source_payload:
                parsed = json.loads(source_payload)
                of = parsed.get("output_format", output_format)
                if of in ("vertical", "original"):
                    output_format = of
                asub = parsed.get("add_subtitles", add_subtitles)
                if isinstance(asub, bool):
                    add_subtitles = asub
        finally:
            await redis_client.aclose()

        return output_format, add_subtitles

    async def _resolve_source_video_path(self, task: Dict[str, Any]) -> Path:
        source_url = task.get("source_url")
        source_type = task.get("source_type")
        if not source_url or not source_type:
            raise ValueError("Task source is missing; cannot regenerate clip")

        if source_type == "youtube":
            downloaded = await self.video_service.download_video(source_url)
            if not downloaded:
                raise ValueError("Failed to download source video for regeneration")
            return Path(downloaded)

        video_path = self.video_service.resolve_local_video_path(source_url)
        if not video_path.exists():
            raise ValueError("Source video file no longer exists")
        return video_path

    async def regenerate_clip_with_strategy_c(
        self,
        task_id: str,
        clip_id: str,
        start_offset: float = 0.0,
        end_offset: float = 0.0,
        reject_reason: str | None = None,
    ) -> Dict[str, Any]:
        clip = await self.clip_repo.get_clip_by_id(self.db, clip_id)
        if not clip or clip["task_id"] != task_id:
            raise ValueError("Clip not found")

        if start_offset > 0 or end_offset > 0:
            trimmed = await self.trim_clip(task_id, clip_id, start_offset, end_offset)
            return {
                "clip": trimmed,
                "strategy": "trim_offsets",
                "fallback_used": False,
            }

        task = await self.task_repo.get_task_by_id(self.db, task_id)
        if not task:
            raise ValueError("Task not found")

        video_path = await self._resolve_source_video_path(task)
        output_format, add_subtitles = await self._get_render_source_settings(task_id)

        current_start = str(clip.get("start_time") or "00:00")
        current_end = str(clip.get("end_time") or "00:00")
        current_start_s = parse_timestamp_to_seconds(current_start)
        current_end_s = parse_timestamp_to_seconds(current_end)

        base_reasoning = "Regenerated from same time range"
        if reject_reason:
            base_reasoning = f"{base_reasoning} (reason: {reject_reason})"

        base_segment: Dict[str, Any] = {
            "start_time": current_start,
            "end_time": current_end,
            "text": clip.get("text") or "",
            "relevance_score": clip.get("relevance_score", 0.5),
            "reasoning": base_reasoning,
            "virality_score": clip.get("virality_score", 0),
            "hook_score": clip.get("hook_score", 0),
            "engagement_score": clip.get("engagement_score", 0),
            "value_score": clip.get("value_score", 0),
            "shareability_score": clip.get("shareability_score", 0),
            "hook_type": clip.get("hook_type"),
        }

        candidate_segments: List[Dict[str, Any]] = [base_segment]

        try:
            video_duration = float(self.video_service._get_file_duration(video_path))
            transcript = await self.video_service.generate_transcript(
                str(video_path),
                processing_mode=str(task.get("processing_mode") or "balanced"),
            )
            analysis = await self.video_service.analyze_transcript(
                transcript,
                video_duration=video_duration,
                include_broll=bool(task.get("include_broll", False)),
            )
            all_segments = list(getattr(analysis, "most_relevant_segments", []) or [])

            same_range: List[tuple[float, Dict[str, Any]]] = []
            full_video: List[tuple[float, Dict[str, Any]]] = []
            for segment in all_segments:
                start_time = str(self._segment_field(segment, "start_time", "00:00"))
                end_time = str(self._segment_field(segment, "end_time", "00:00"))
                start_s = parse_timestamp_to_seconds(start_time)
                end_s = parse_timestamp_to_seconds(end_time)
                overlap = max(0.0, min(current_end_s, end_s) - max(current_start_s, start_s))
                center_distance = abs(((start_s + end_s) / 2.0) - ((current_start_s + current_end_s) / 2.0))

                candidate = {
                    "start_time": start_time,
                    "end_time": end_time,
                    "text": self._segment_field(segment, "text", "") or "",
                    "relevance_score": float(self._segment_field(segment, "relevance_score", 0.5) or 0.5),
                    "reasoning": self._segment_field(segment, "reasoning", "Regenerated from fallback segment")
                    or "Regenerated from fallback segment",
                    "virality_score": int(self._segment_field(segment, "virality_score", 0) or 0),
                    "hook_score": int(self._segment_field(segment, "hook_score", 0) or 0),
                    "engagement_score": int(self._segment_field(segment, "engagement_score", 0) or 0),
                    "value_score": int(self._segment_field(segment, "value_score", 0) or 0),
                    "shareability_score": int(self._segment_field(segment, "shareability_score", 0) or 0),
                    "hook_type": self._segment_field(segment, "hook_type", None),
                }

                if overlap > 0 or center_distance <= 12.0:
                    same_range.append((center_distance, candidate))
                else:
                    full_video.append((center_distance, candidate))

            same_range.sort(key=lambda it: it[0])
            full_video.sort(key=lambda it: it[0])
            candidate_segments.extend([seg for _, seg in same_range])
            candidate_segments.extend([seg for _, seg in full_video])
        except Exception as e:
            logger.warning("Regenerate fallback analysis failed for clip %s: %s", clip_id, e)

        seen_ranges: set[tuple[str, str]] = set()
        deduped_candidates: List[Dict[str, Any]] = []
        for segment in candidate_segments:
            key = (str(segment.get("start_time", "")), str(segment.get("end_time", "")))
            if key in seen_ranges:
                continue
            seen_ranges.add(key)
            deduped_candidates.append(segment)

        font_family = str(task.get("font_family") or "TikTokSans-Regular")
        font_size = int(task.get("font_size") or 24)
        font_color = str(task.get("font_color") or "#FFFFFF")
        caption_template = str(task.get("caption_template") or "default")

        last_error: Optional[Exception] = None
        for idx, segment in enumerate(deduped_candidates):
            try:
                clips_info = await self.video_service.create_video_clips(
                    video_path,
                    [segment],
                    font_family,
                    font_size,
                    font_color,
                    caption_template,
                    output_format,
                    add_subtitles,
                    task_id=task_id,
                )
                if not clips_info:
                    continue

                clip_info = clips_info[0]
                await self.clip_repo.update_clip(
                    self.db,
                    clip_id,
                    clip_info["filename"],
                    clip_info["path"],
                    clip_info["start_time"],
                    clip_info["end_time"],
                    clip_info["duration"],
                    clip_info.get("text") or segment.get("text") or "",
                )
                updated_clip = await self.clip_repo.get_clip_by_id(self.db, clip_id)
                return {
                    "clip": updated_clip or {},
                    "strategy": "same_range" if idx == 0 else "full_video_fallback",
                    "fallback_used": idx > 0,
                }
            except Exception as e:
                last_error = e

        if last_error:
            raise ValueError(f"Could not regenerate clip: {last_error}")
        raise ValueError("Could not regenerate clip")

    async def trim_clip(
        self,
        task_id: str,
        clip_id: str,
        start_offset: float,
        end_offset: float,
    ) -> Dict[str, Any]:
        clip = await self.clip_repo.get_clip_by_id(self.db, clip_id)
        if not clip or clip["task_id"] != task_id:
            raise ValueError("Clip not found")

        input_path = Path(clip["file_path"])
        if not input_path.exists():
            raise ValueError("Clip file not found")

        output_path = trim_clip_file(
            input_path, Path(self.config.temp_dir) / "clips", start_offset, end_offset
        )
        clip_duration = max(0.1, clip["duration"] - start_offset - end_offset)

        start_seconds = parse_timestamp_to_seconds(clip["start_time"]) + start_offset
        end_seconds = start_seconds + clip_duration

        new_start = self._seconds_to_mmss(start_seconds)
        new_end = self._seconds_to_mmss(end_seconds)

        await self.clip_repo.update_clip(
            self.db,
            clip_id,
            output_path.name,
            str(output_path),
            new_start,
            new_end,
            clip_duration,
            clip.get("text") or "",
        )
        return (await self.clip_repo.get_clip_by_id(self.db, clip_id)) or {}


    async def split_clip(
        self, task_id: str, clip_id: str, split_time: float
    ) -> Dict[str, Any]:
        clip = await self.clip_repo.get_clip_by_id(self.db, clip_id)
        if not clip or clip["task_id"] != task_id:
            raise ValueError("Clip not found")

        input_path = Path(clip["file_path"])
        if not input_path.exists():
            raise ValueError("Clip file not found")

        first_path, second_path = split_clip_file(
            input_path, Path(self.config.temp_dir) / "clips", split_time
        )

        start_seconds = parse_timestamp_to_seconds(clip["start_time"])
        clamped_split = max(0.2, min(split_time, float(clip["duration"]) - 0.2))
        split_abs = start_seconds + clamped_split
        end_seconds = parse_timestamp_to_seconds(clip["end_time"])

        await self.clip_repo.update_clip(
            self.db,
            clip_id,
            first_path.name,
            str(first_path),
            clip["start_time"],
            self._seconds_to_mmss(split_abs),
            clamped_split,
            clip.get("text") or "",
        )

        await self.clip_repo.create_clip(
            self.db,
            task_id=task_id,
            filename=second_path.name,
            file_path=str(second_path),
            start_time=self._seconds_to_mmss(split_abs),
            end_time=self._seconds_to_mmss(end_seconds),
            duration=max(0.1, end_seconds - split_abs),
            text=clip.get("text") or "",
            relevance_score=clip.get("relevance_score", 0.5),
            reasoning=clip.get("reasoning") or "Split from original clip",
            clip_order=clip.get("clip_order", 1) + 1,
            virality_score=clip.get("virality_score", 0),
            hook_score=clip.get("hook_score", 0),
            engagement_score=clip.get("engagement_score", 0),
            value_score=clip.get("value_score", 0),
            shareability_score=clip.get("shareability_score", 0),
            hook_type=clip.get("hook_type"),
        )

        await self.clip_repo.reorder_task_clips(self.db, task_id)
        return {"message": "Clip split successfully"}


    async def merge_clips(self, task_id: str, clip_ids: list[str]) -> Dict[str, Any]:
        if len(clip_ids) < 2:
            raise ValueError("At least two clips are required to merge")

        clips = []
        for clip_id in clip_ids:
            clip = await self.clip_repo.get_clip_by_id(self.db, clip_id)
            if not clip or clip["task_id"] != task_id:
                raise ValueError("One or more clips not found")
            clips.append(clip)

        ordered = sorted(clips, key=lambda c: c.get("clip_order", 0))
        merged_path = merge_clip_files(
            [Path(c["file_path"]) for c in ordered],
            Path(self.config.temp_dir) / "clips",
        )

        start_time = ordered[0]["start_time"]
        end_time = ordered[-1]["end_time"]
        duration = sum(float(c.get("duration", 0.0)) for c in ordered)
        text = " ".join((c.get("text") or "").strip() for c in ordered if c.get("text"))

        first = ordered[0]
        await self.clip_repo.update_clip(
            self.db,
            first["id"],
            merged_path.name,
            str(merged_path),
            start_time,
            end_time,
            duration,
            text,
        )

        for clip in ordered[1:]:
            await self.clip_repo.delete_clip(self.db, clip["id"])

        await self.clip_repo.reorder_task_clips(self.db, task_id)
        return {"message": "Clips merged successfully", "clip_id": first["id"]}


    async def update_clip_captions(
        self,
        task_id: str,
        clip_id: str,
        caption_text: str,
        position: str,
        highlight_words: list[str],
    ) -> Dict[str, Any]:
        clip = await self.clip_repo.get_clip_by_id(self.db, clip_id)
        if not clip or clip["task_id"] != task_id:
            raise ValueError("Clip not found")

        input_path = Path(clip["file_path"])
        if not input_path.exists():
            raise ValueError("Clip file not found")

        output_path = overlay_custom_captions(
            input_path,
            Path(self.config.temp_dir) / "clips",
            caption_text,
            position,
            highlight_words,
        )

        await self.clip_repo.update_clip(
            self.db,
            clip_id,
            output_path.name,
            str(output_path),
            clip["start_time"],
            clip["end_time"],
            clip["duration"],
            caption_text,
        )
        return (await self.clip_repo.get_clip_by_id(self.db, clip_id)) or {}

