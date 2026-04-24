"""
SceneAnalyzer - Decide modo de edición por clip
Modo A: Composite SAM2 + LTX (talking-head premium)
Modo B: B-roll estándar overlay
Modo C: Clip limpio sin B-roll
"""

import os
import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class SceneAnalyzer:
    """Analiza escenas para decidir modo de edición óptimo."""

    async def analyze(
        self,
        clip_path: str,
        viral_score: float,
        duration: float
    ) -> dict:
        """
        Retorna {"mode": "A"|"B"|"C", "confidence": float, "reason": str}
        """
        # GATE 1 — Duración mínima
        if duration < 12.0:
            return {
                "mode": "C",
                "confidence": 1.0,
                "reason": "clip_too_short"
            }

        # GATE 2 — SAM2 habilitado
        if os.getenv("SAM2_ENABLED", "false").lower() != "true":
            return {
                "mode": "B",
                "confidence": 1.0,
                "reason": "sam2_disabled"
            }

        # GATE 3 — Score viral mínimo para Modo A
        min_score = float(os.getenv("SAM2_MIN_VIRAL_SCORE", "7.5"))
        if viral_score < min_score:
            return {
                "mode": "B",
                "confidence": 0.8,
                "reason": "score_below_threshold"
            }

        # GATE 4 — Análisis de contenido
        try:
            talking_head, variance, movement = await asyncio.gather(
                self._calc_talking_head_ratio(clip_path),
                self._calc_background_variance(clip_path),
                self._calc_movement_score(clip_path),
                return_exceptions=True
            )

            # Manejar excepciones en gather
            if isinstance(talking_head, Exception):
                logger.warning(f"Talking head calculation failed: {talking_head}")
                talking_head = 0.5
            if isinstance(variance, Exception):
                logger.warning(f"Background variance calculation failed: {variance}")
                variance = 25.0
            if isinstance(movement, Exception):
                logger.warning(f"Movement score calculation failed: {movement}")
                movement = 0.3

            # Modo A si cumple todas las condiciones
            if talking_head >= 0.35 and variance < 20.0 and movement < 0.65:
                return {
                    "mode": "A",
                    "confidence": 0.85,
                    "reason": "talking_head_suitable",
                    "metrics": {
                        "talking_head_ratio": talking_head,
                        "background_variance": variance,
                        "movement_score": movement
                    }
                }
            else:
                reason_parts = []
                if talking_head < 0.35:
                    reason_parts.append("low_talking_head")
                if variance >= 20.0:
                    reason_parts.append("dynamic_background")
                if movement >= 0.65:
                    reason_parts.append("high_movement")

                return {
                    "mode": "B",
                    "confidence": 0.7,
                    "reason": "|".join(reason_parts) if reason_parts else "not_optimal_for_composite",
                    "metrics": {
                        "talking_head_ratio": talking_head,
                        "background_variance": variance,
                        "movement_score": movement
                    }
                }

        except Exception as e:
            logger.warning(f"Scene analysis failed, defaulting to Mode B: {e}")
            return {
                "mode": "B",
                "confidence": 0.5,
                "reason": "analysis_error"
            }

    async def _calc_talking_head_ratio(self, clip_path: str) -> float:
        """Extrae 5 frames y detecta ratio de cara/área total."""
        try:
            import cv2
        except ImportError:
            logger.debug("cv2 not available, returning neutral talking head ratio")
            return 0.5

        tmp_dir = tempfile.mkdtemp()
        frame_paths = []

        try:
            # Extraer 5 frames con ffmpeg
            cmd = [
                "ffmpeg", "-i", clip_path, "-vf",
                "select='eq(n,0)+eq(n,floor(nb_frames*0.25))+eq(n,floor(nb_frames*0.5))+eq(n,floor(nb_frames*0.75))+eq(n,nb_frames-1)'",
                "-vsync", "0", f"{tmp_dir}/frame_%d.jpg"
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                await asyncio.wait_for(proc.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                proc.kill()
                logger.warning("FFmpeg timeout extracting frames")
                return 0.0

            # Buscar frames extraídos
            tmp_path = Path(tmp_dir)
            frame_paths = list(tmp_path.glob("frame_*.jpg"))

            if not frame_paths:
                logger.warning("No frames extracted for face detection")
                return 0.0

            # Cargar clasificador de caras
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            face_cascade = cv2.CascadeClassifier(cascade_path)

            ratios = []
            for frame_path in frame_paths:
                try:
                    img = cv2.imread(str(frame_path))
                    if img is None:
                        continue

                    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                    faces = face_cascade.detectMultiScale(
                        gray,
                        scaleFactor=1.1,
                        minNeighbors=5,
                        minSize=(30, 30)
                    )

                    if len(faces) > 0:
                        # Calcular ratio área cara / área total
                        img_area = img.shape[0] * img.shape[1]
                        face_area = sum(w * h for (x, y, w, h) in faces)
                        ratios.append(face_area / img_area)
                except Exception as e:
                    logger.debug(f"Face detection failed for frame {frame_path}: {e}")
                    continue

            return sum(ratios) / len(ratios) if ratios else 0.0

        except Exception as e:
            logger.warning(f"Talking head calculation error: {e}")
            return 0.0

        finally:
            # Limpiar archivos temporales
            try:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

    async def _calc_background_variance(self, clip_path: str) -> float:
        """Calcula varianza del fondo usando ffmpeg signalstats."""
        cmd = [
            "ffmpeg", "-i", clip_path,
            "-vf", "crop=iw:ih*0.4:0:ih*0.6,signalstats=stat=tout",
            "-f", "null", "-", "-t", "5"
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                _, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                proc.kill()
                logger.warning("Background variance calculation timeout")
                return 25.0

            stderr_str = stderr.decode('utf-8', errors='ignore')

            # Parsear YDIF o YAVG para obtener stddev
            import re
            ydif_match = re.search(r'YDIF:(\d+\.?\d*)', stderr_str)
            if ydif_match:
                return float(ydif_match.group(1))

            yavg_match = re.search(r'YAVG:(\d+\.?\d*)', stderr_str)
            if yavg_match:
                # YAVG es promedio, usamos como proxy de varianza baja
                avg = float(yavg_match.group(1))
                return abs(avg - 128) * 2  # Normalizar

            return 25.0  # Valor neutro

        except Exception as e:
            logger.warning(f"Background variance calculation error: {e}")
            return 25.0

    async def _calc_movement_score(self, clip_path: str) -> float:
        """Estima movimiento usando ffmpeg mestimate."""
        cmd = [
            "ffmpeg", "-i", clip_path,
            "-vf", "mestimate,metadata=print:file=-",
            "-f", "null", "-", "-t", "5"
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            try:
                stdout, _ = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                proc.kill()
                logger.warning("Movement score calculation timeout")
                return 0.3

            stdout_str = stdout.decode('utf-8', errors='ignore')

            # Parsear lavfi.mv.avg values
            import re
            mv_values = re.findall(r'lavfi\.mv\.avg=([\d\.]+)', stdout_str)

            if mv_values:
                avg_mv = sum(float(v) for v in mv_values) / len(mv_values)
                # Normalizar a 0.0-1.0 (valores típicos 0-100)
                return min(1.0, avg_mv / 100.0)

            return 0.3  # Valor neutro

        except Exception as e:
            logger.warning(f"Movement score calculation error: {e}")
            return 0.3


# ── Singleton ─────────────────────────────────────────────────────────────────
scene_analyzer = SceneAnalyzer()
