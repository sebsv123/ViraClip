"""
LTXVIntroService - Prepone una intro generada con LTX-Video al clip final.

Flujo:
  1. Extrae el primer frame del clip ya renderizado.
  2. Invoca `ComfyUIBridge.generate_ltxv_intro(first_frame, theme, intro_path)`
     que genera un vídeo corto (LTX-Video img2vid) que termina exactamente en
     ese frame para garantizar continuidad visual.
  3. Concatena intro + clip con FFmpeg (xfade corto opcional).
  4. Devuelve la ruta del clip resultante o None si algún paso falla; el
     caller usa el clip original como fallback.

Activación:
  - `LTXV_INTRO_ENABLED=true`  (gating global)
  - `LTXV_INTRO_MIN_VIRALITY`  (sólo se aplica cuando virality >= N; default 0)
  - `LTXV_INTRO_THEME_FALLBACK` (default "cinematic dramatic")
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class LTXVIntroService:
    @staticmethod
    def enabled() -> bool:
        return os.environ.get("LTXV_INTRO_ENABLED", "false").lower() == "true"

    @staticmethod
    async def maybe_prepend_intro(
        clip_path: Path,
        theme: Optional[str],
        virality_score: float = 0.0,
        timeout: float = 300.0,
    ) -> Optional[Path]:
        """Prepend an LTXV intro to *clip_path*. Returns the NEW path or None."""
        if not LTXVIntroService.enabled():
            return None

        try:
            min_vir = float(os.environ.get("LTXV_INTRO_MIN_VIRALITY", "0"))
        except ValueError:
            min_vir = 0.0
        if virality_score < min_vir:
            logger.debug(
                "[LTXVIntro] score=%.1f < min=%.1f → skip", virality_score, min_vir
            )
            return None

        clip_path = Path(clip_path)
        if not clip_path.exists():
            logger.warning("[LTXVIntro] clip no existe: %s", clip_path)
            return None

        theme = (theme or os.environ.get("LTXV_INTRO_THEME_FALLBACK")
                 or "cinematic dramatic").strip()

        work_dir = clip_path.parent
        first_frame = work_dir / f"{clip_path.stem}_firstframe.png"
        intro_path = work_dir / f"{clip_path.stem}_ltxintro.mp4"
        merged_path = work_dir / f"{clip_path.stem}_with_intro.mp4"

        # 1) Extraer primer frame
        if not await _ffmpeg_first_frame(clip_path, first_frame):
            logger.warning("[LTXVIntro] no pude extraer first frame de %s", clip_path)
            return None

        # 2) Generar intro
        try:
            from ..comfyui_bridge import ComfyUIBridge
            bridge = ComfyUIBridge()
            try:
                ok = await bridge.generate_ltxv_intro(
                    first_frame_path=first_frame,
                    theme=theme,
                    output_path=intro_path,
                    timeout=timeout,
                )
            finally:
                await bridge.close()
        except Exception as exc:
            logger.warning("[LTXVIntro] bridge error: %s", exc)
            return None

        if not ok or not intro_path.exists() or intro_path.stat().st_size < 1024:
            logger.warning("[LTXVIntro] intro no generada")
            return None

        # 3) Concat intro + clip (re-encode para unificar codec/fps/timebase)
        concat_duration = float(os.environ.get("LTXV_INTRO_CROSSFADE", "0.4"))
        if not await _ffmpeg_concat_with_xfade(
            intro_path, clip_path, merged_path, xfade_d=concat_duration
        ):
            logger.warning("[LTXVIntro] concat failed")
            return None

        logger.info("[LTXVIntro] ✅ intro prepended → %s", merged_path)
        return merged_path


# ─── helpers ──────────────────────────────────────────────────────────────────

async def _ffmpeg_first_frame(src: Path, dst: Path) -> bool:
    cmd = [
        "ffmpeg", "-y", "-ss", "0", "-i", str(src),
        "-frames:v", "1", "-q:v", "2", str(dst),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _o, _e = await proc.communicate()
    return proc.returncode == 0 and dst.exists()


async def _ffmpeg_concat_with_xfade(
    intro: Path, main: Path, out: Path, xfade_d: float = 0.4
) -> bool:
    # Usa un concat con xfade cortito; si falla por incompatibilidad cae a
    # concat demuxer con streams normalizados.
    try:
        import subprocess
        dur_out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(intro)],
            capture_output=True, text=True, timeout=10,
        )
        intro_dur = float((dur_out.stdout or "0").strip() or 0.0)
    except Exception:
        intro_dur = 0.0
    offset = max(0.0, intro_dur - xfade_d)

    cmd = [
        "ffmpeg", "-y",
        "-i", str(intro),
        "-i", str(main),
        "-filter_complex",
        (
            f"[0:v][1:v]xfade=transition=fade:duration={xfade_d}:offset={offset}[v];"
            f"[0:a][1:a]acrossfade=d={xfade_d}[a]"
        ),
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        str(out),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _o, stderr = await proc.communicate()
    if proc.returncode == 0 and out.exists():
        return True

    # Fallback: re-encode ambos y concat demuxer (sin crossfade)
    logger.debug("[LTXVIntro] xfade falló, reintentando con concat demuxer")
    list_path = out.with_suffix(".txt")
    list_path.write_text(f"file '{intro.resolve()}'\nfile '{main.resolve()}'\n")
    cmd2 = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        str(out),
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd2, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    await proc.communicate()
    list_path.unlink(missing_ok=True)
    return proc.returncode == 0 and out.exists()


ltxv_intro_service = LTXVIntroService()
