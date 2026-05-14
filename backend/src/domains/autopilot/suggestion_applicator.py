"""
SuggestionApplicator - Renders suggestions onto video clips.
This is the core service that materializes AI suggestions into actual video pixels.
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
import subprocess
import tempfile

from ...domains.broll.broll_compositor import _get_ffmpeg_exe as get_ffmpeg_exe
from ...config import get_config
from ... import gpu_utils

logger = logging.getLogger(__name__)


class SuggestionApplicator:
    """Applies clip suggestions to render enhanced video output."""

    async def apply_suggestions(
        self,
        input_path: Path,
        output_path: Path,
        suggestions: List[Dict[str, Any]],
        clip_info: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Apply multiple suggestions to a video clip.

        Returns:
            {"success": True, "output_path": str} on success
            {"success": False, "error": str} on failure
        """
        try:
            _video_filters = []
            _audio_filters = []
            _inputs = [str(input_path)]
            _input_labels = ["0:v"]
            _input_audio = ["0:a"]

            _sorted = self._sort_suggestions(suggestions)

            for suggestion in _sorted:
                _kind = suggestion.get("kind")
                _payload = suggestion.get("payload", {})

                if _kind in ("caption_template", "caption_style", "caption_animation"):
                    _vf = self._build_caption_filter(_payload, clip_info)
                    if _vf:
                        _video_filters.append(_vf)

                elif _kind == "zoom_punch":
                    _vf = self._build_zoom_filter(_payload, clip_info)
                    if _vf:
                        _video_filters.append(_vf)

                elif _kind == "vignette":
                    _vf = self._build_vignette_filter(_payload)
                    if _vf:
                        _video_filters.append(_vf)

                elif _kind == "color_grading":
                    _vf = self._build_color_filter(_payload)
                    if _vf:
                        _video_filters.append(_vf)

                elif _kind in ("broll_stock", "broll_ai", "contextual_overlay"):
                    _broll_result = await self._composite_broll(
                        _inputs, _input_labels, _payload, clip_info
                    )
                    if _broll_result:
                        _inputs, _input_labels, _broll_vf = _broll_result
                        if _broll_vf:
                            _video_filters.append(_broll_vf)

                elif _kind == "emoji_overlay":
                    _vf = self._build_emoji_overlay(_payload)
                    if _vf:
                        _video_filters.append(_vf)

                elif _kind == "cta_overlay":
                    _vf = self._build_cta_overlay(_payload)
                    if _vf:
                        _video_filters.append(_vf)

                elif _kind == "loudnorm":
                    _audio_filters.append("loudnorm=I=-16:LRA=11:TP=-1.5")

                elif _kind == "sfx_cues":
                    _sfx_result = await self._mix_sfx(
                        _inputs, _input_audio, _payload, clip_info
                    )
                    if _sfx_result:
                        _inputs, _input_audio = _sfx_result

            # Pre-check: verify input file exists before building FFmpeg command
            _input_path_str = str(input_path)
            if not os.path.exists(_input_path_str):
                logger.error(
                    "[SuggestionApplicator] Input file not found: %s",
                    _input_path_str,
                )
                return {"success": False, "error": f"Input file not found: {_input_path_str}"}

            _cmd = self._build_ffmpeg_command(
                inputs=_inputs,
                video_filters=_video_filters,
                audio_filters=_audio_filters,
                output=str(output_path),
                clip_info=clip_info,
            )

            logger.info("[SuggestionApplicator] Executing: %s", " ".join(_cmd))
            _result = await self._run_ffmpeg(_cmd)

            if _result.returncode == 0:
                return {"success": True, "output_path": str(output_path)}
            else:
                _stderr = _result.stderr.decode() if _result.stderr else "Unknown error"
                logger.error("[SuggestionApplicator] FFmpeg stderr:\n%s", _stderr)
                return {"success": False, "error": f"FFmpeg failed: {_stderr}"}

        except Exception as e:
            logger.exception("[SuggestionApplicator] Error applying suggestions")
            return {"success": False, "error": str(e)}

    def _sort_suggestions(self, suggestions: List[Dict]) -> List[Dict]:
        _priority = {
            "color_grading": 1,
            "broll_stock": 2,
            "broll_ai": 2,
            "contextual_overlay": 2,
            "caption_template": 3,
            "caption_style": 3,
            "caption_animation": 3,
            "emoji_overlay": 4,
            "cta_overlay": 4,
            "zoom_punch": 5,
            "vignette": 5,
            "loudnorm": 10,
            "sfx_cues": 10,
        }
        return sorted(suggestions, key=lambda s: _priority.get(s.get("kind"), 99))

    def _build_caption_filter(self, payload: Dict, clip_info: Dict) -> Optional[str]:
        _text = payload.get("text", "")
        if not _text:
            return None
        # Escape special chars for FFmpeg drawtext: backslash, single quote, colon
        _safe_text = _text.replace("\\", "\\\\").replace("'", "\u2019").replace(":", "\\:")
        _fontfile = "/app/fonts/TikTokSans-Regular.ttf"
        _fontsize = payload.get("font_size", 48)
        _color = payload.get("color", "white")
        _box = 1 if payload.get("background", True) else 0
        _boxcolor = "black@0.5" if _box else "black@0"
        _start = payload.get("start", 0)
        _end = payload.get("end", clip_info.get("duration", 30))
        return (
            f"drawtext=fontfile={_fontfile}:"
            f"text='{_safe_text}':"
            f"fontsize={_fontsize}:"
            f"fontcolor={_color}:"
            f"box={_box}:boxcolor={_boxcolor}:"
            f"x=(w-text_w)/2:y=h-text_h-100:"
            f"enable='between(t,{_start},{_end})'"
        )

    def _build_zoom_filter(self, payload: Dict, clip_info: Dict) -> Optional[str]:
        _zoom_type = payload.get("type", "punch_in")
        _start = payload.get("start_time", 0)
        _duration = payload.get("duration", 1.0)
        _end = _start + _duration
        if _zoom_type == "punch_in":
            # NOTE: FFmpeg's eval parser chokes on nested parens inside sin().
            # Using a temporary variable via the zoompan expression avoids the issue.
            # We compute the normalized progress (t-start)/dur first, then apply sin.
            # The expression: 1 + 0.3 * sin(PI * (t-start) / dur)
            # Putting PI * (t-start) / dur avoids nested parens inside sin().
            return (
                f"zoompan=z='if(lte(t,{_start}),1,"
                f"if(lte(t,{_end}),1+0.3*sin(PI*(t-{_start})/{_duration}),1))':"
                f"d={int(_duration * 30)}:s=1080x1920"
            )
        elif _zoom_type == "slow_push":
            return (
                f"zoompan=z='1+0.1*(t-{_start})/{_duration}':"
                f"d={int(_duration * 30)}:s=1080x1920"
            )
        return None

    def _build_vignette_filter(self, payload: Dict) -> Optional[str]:
        _strength = payload.get("strength", 0.3)
        return f"vignette=PI*{_strength}"

    def _build_color_filter(self, payload: Dict) -> Optional[str]:
        _preset = payload.get("preset", "viral")
        if _preset == "viral":
            return "eq=contrast=1.1:saturation=1.2:brightness=0.05"
        elif _preset == "cinematic":
            return "eq=contrast=1.05:saturation=0.9:brightness=-0.02,curves=preset=film"
        return None

    async def _composite_broll(
        self, inputs: List[str], input_labels: List[str],
        payload: Dict, clip_info: Dict,
    ) -> Optional[tuple]:
        _broll_path = payload.get("broll_path") or payload.get("video_url")
        if not _broll_path:
            return None
        _start = payload.get("start_time", 0)
        _duration = payload.get("duration", 5.0)
        _position = payload.get("position", "fullscreen")
        inputs.append(_broll_path)
        _broll_idx = len(inputs) - 1
        # Scale B-roll to main video dimensions before overlay to prevent
        # small picture-in-picture rendering in the corner
        _w = clip_info.get("width", 1080)
        _h = clip_info.get("height", 1920)
        if _position == "fullscreen":
            _overlay = (
                f"[{_broll_idx}:v]scale={_w}:{_h}:force_original_aspect_ratio=increase,"
                f"crop={_w}:{_h}[broll_scaled];"
                f"[{input_labels[0]}][broll_scaled]overlay="
                f"enable='between(t,{_start},{_start+_duration})':"
                f"x=0:y=0"
            )
            input_labels = ["[v]"]
        else:
            _x = 20 if "left" in _position else "main_w-overlay_w-20"
            _y = 20 if "top" in _position else "main_h-overlay_h-20"
            _overlay = (
                f"[{_broll_idx}:v]scale={_w//3}:{_h//3}[broll_scaled];"
                f"[{input_labels[0]}][broll_scaled]overlay="
                f"x={_x}:y={_y}:enable='between(t,{_start},{_start+_duration})'"
            )
            input_labels = ["[v]"]
        return inputs, input_labels, _overlay

    def _build_emoji_overlay(self, payload: Dict) -> Optional[str]:
        _emoji = payload.get("emoji", "🔥")
        _safe_emoji = _emoji.replace("\\", "\\\\").replace("'", "\u2019").replace(":", "\\:")
        _x = payload.get("x", "w-100")
        _y = payload.get("y", "50")
        _start = payload.get("start", 0)
        _end = payload.get("end", 3)
        return (
            f"drawtext=fontfile=/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf:"
            f"text='{_safe_emoji}':fontsize=60:x={_x}:y={_y}:"
            f"enable='between(t,{_start},{_end})'"
        )

    def _build_cta_overlay(self, payload: Dict) -> Optional[str]:
        _text = payload.get("text", "Subscribe!")
        _safe_text = _text.replace("\\", "\\\\").replace("'", "\u2019").replace(":", "\\:")
        _start = payload.get("start", 0)
        _end = payload.get("end", 5)
        return (
            f"drawtext=fontfile=/app/fonts/TikTokSans-Regular.ttf:"
            f"text='{_safe_text}':fontsize=36:fontcolor=white:"
            f"box=1:boxcolor=red@0.8:boxborderw=20:"
            f"x=(w-text_w)/2:y=h-text_h-200:"
            f"enable='between(t,{_start},{_end})'"
        )

    async def _mix_sfx(
        self, inputs: List[str], input_audio: List[str],
        payload: Dict, clip_info: Dict,
    ) -> Optional[tuple]:
        _sfx_path = payload.get("sfx_path")
        if not _sfx_path:
            return None
        _start = payload.get("start_time", 0)
        _volume = payload.get("volume", 0.3)
        inputs.append(_sfx_path)
        _sfx_idx = len(inputs) - 1
        _mixed = (
            f"[{input_audio[0]}][{_sfx_idx}:a]amix=inputs=2:duration=longest:"
            f"weights='1 {_volume}'[a]"
        )
        input_audio = ["[a]"]
        return inputs, input_audio

    def _build_ffmpeg_command(
        self, inputs: List[str], video_filters: List[str],
        audio_filters: List[str], output: str, clip_info: Dict,
    ) -> List[str]:
        _cmd = [get_ffmpeg_exe(), "-y"]
        for inp in inputs:
            _cmd.extend(["-i", inp])
        _filters = []
        if video_filters:
            _vf = ",".join(f for f in video_filters if f)
            _filters.extend(["-vf", _vf])
        if audio_filters:
            _af = ",".join(f for f in audio_filters if f)
            _filters.extend(["-af", _af])
        # Dynamic encoder detection: NVENC (GPU) → libx264 (CPU fallback)
        _cmd.extend(gpu_utils.ffmpeg_codec_flags("high"))
        _cmd.extend(["-pix_fmt", "yuv420p"])
        _cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        _cmd.extend(_filters)
        _cmd.append(output)
        return _cmd

    async def _run_ffmpeg(self, cmd: List[str]) -> subprocess.CompletedProcess:
        _proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _stdout, _stderr = await _proc.communicate()
        return subprocess.CompletedProcess(cmd, _proc.returncode, _stdout, _stderr)
