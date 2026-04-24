"""
CompositeEngine - Compone persona sobre fondo LTX usando FFmpeg puro.

Entrada:
  - original_clip: video original del sujeto (la persona)
  - mask_clip: video greyscale con la máscara SAM2 (blanco=persona, negro=fondo)
  - background_clip: fondo generado con LTX-Video (misma duración aprox.)

Filter_complex FFmpeg:
  [1:v][2:v] alphamerge [person_rgba];
  [0:v][person_rgba] overlay=shortest=1:format=auto [out]
"""

import os
import asyncio
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class CompositeEngine:
    """Compone persona segmentada sobre fondo generado vía FFmpeg."""

    async def composite(
        self,
        original_clip: str,
        mask_clip: str,
        background_clip: str,
        task_id: str,
    ) -> Optional[str]:
        """
        Compone original (persona) + mask + background con FFmpeg.
        Devuelve ruta del MP4 resultante o None si falla.
        """
        try:
            orig = Path(original_clip)
            mask = Path(mask_clip)
            bg = Path(background_clip)

            for p in (orig, mask, bg):
                if not p.exists():
                    logger.error(f"[Composite] Missing input: {p}")
                    return None

            # Output path: prefer explicit VIRA_OUTPUTS, else colocate with pipeline clips
            outputs_dir = Path(
                os.getenv("VIRA_OUTPUTS")
                or (Path(os.getenv("TEMP_DIR", "/app/temp/uploads")) / "clips")
            )
            outputs_dir.mkdir(parents=True, exist_ok=True)
            out_path = outputs_dir / f"{task_id}_composite.mp4"

            # Ajustamos el tamaño de mask y bg al del original para evitar offsets
            # y usamos scale2ref. El filtro final es:
            #   - Escalar bg y mask al mismo tamaño que el original
            #   - alphamerge: alpha del original tomado de la Y del mask
            #   - overlay: bg + persona_rgba
            filter_complex = (
                "[1:v][0:v]scale2ref=w=iw:h=ih[bg_s][orig];"      # bg_s match orig
                "[2:v][orig]scale2ref=w=iw:h=ih[mask_s][orig2];"    # mask_s match orig
                "[orig2][mask_s]alphamerge[person];"
                "[bg_s][person]overlay=0:0:shortest=1:format=auto[out]"
            )

            cmd = [
                "ffmpeg", "-y",
                "-i", str(orig),       # [0:v] + audio
                "-i", str(bg),         # [1:v]
                "-i", str(mask),       # [2:v]
                "-filter_complex", filter_complex,
                "-map", "[out]",
                "-map", "0:a?",        # audio original si existe
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "18",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                str(out_path),
            ]

            timeout = int(os.getenv("COMPOSITE_TIMEOUT", "300"))
            logger.info(f"[Composite] Running FFmpeg for {task_id} -> {out_path.name}")

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                logger.error(f"[Composite] ⏱️ Timeout after {timeout}s for {task_id}")
                return None

            if proc.returncode != 0:
                err_tail = (stderr or b"").decode(errors="ignore")[-500:]
                logger.warning(f"[Composite] FFmpeg failed (rc={proc.returncode}): {err_tail}")
                return None

            if not out_path.exists() or out_path.stat().st_size == 0:
                logger.warning(f"[Composite] Output missing or empty: {out_path}")
                return None

            logger.info(f"[Composite] ✅ Done: {out_path}")
            return str(out_path)

        except Exception as e:
            logger.error(f"[Composite] ❌ Error for {task_id}: {e}")
            return None


# ── Singleton ─────────────────────────────────────────────────────────────────
composite_engine = CompositeEngine()
