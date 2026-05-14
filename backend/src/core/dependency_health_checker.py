"""
DependencyHealthChecker — Capa 0 del sistema de self-healing.

Se ejecuta UNA SOLA VEZ al arrancar el worker, antes de registrar las ARQ tasks.
Verifica 8 dependencias críticas y ajusta FEATURE_FLAGS según disponibilidad.

Si FFmpeg no está disponible o no hay ningún LLM configurado, lanza RuntimeError
fatal que detiene el arranque del worker.
"""

import asyncio
import logging
import os
import subprocess
import sys
import time
from typing import Dict, List, Optional, Tuple

from src.core.feature_flags import FEATURE_FLAGS, FALLBACK_MAP

logger = logging.getLogger(__name__)

# Timeout individual por check (segundos)
CHECK_TIMEOUT = 3

# Features que requieren al menos un LLM
LLM_FEATURES = {"llm_groq", "llm_deepseek"}


def _check_numpy() -> Tuple[bool, str]:
    """Check 1: NumPy version compatible con Numba (<= 2.2)."""
    try:
        import numpy as np
        major, minor = np.__version__.split(".")[:2]
        major, minor = int(major), int(minor)
        if major > 2 or (major == 2 and minor > 2):
            return False, f"NumPy {np.__version__} incompatible con Numba"
        return True, f"NumPy {np.__version__}"
    except Exception as exc:
        return False, f"NumPy import failed: {exc}"


def _check_torchcodec() -> Tuple[bool, str]:
    """Check 2: TorchCodec disponible (para narrative cut detection)."""
    try:
        from torchcodec.decoders import VideoDecoder  # noqa: F401
        return True, "TorchCodec OK"
    except (ImportError, OSError, RuntimeError) as exc:
        return False, f"TorchCodec no disponible: {exc}"
    except Exception as exc:
        return False, f"TorchCodec error inesperado: {exc}"


def _check_mediapipe() -> Tuple[bool, str]:
    """Check 3: MediaPipe mp.solutions disponible (face tracking)."""
    try:
        import mediapipe as mp
        _ = mp.solutions.face_mesh
        return True, "MediaPipe mp.solutions OK"
    except (ImportError, AttributeError) as exc:
        return False, f"MediaPipe mp.solutions no disponible: {exc}"
    except Exception as exc:
        return False, f"MediaPipe error inesperado: {exc}"


def _check_nvenc() -> Tuple[bool, str]:
    """Check 4: NVENC GPU encoder disponible."""
    try:
        from src.gpu_utils import nvenc_available
        ok = nvenc_available()
        return ok, "NVENC OK" if ok else "NVENC no disponible"
    except Exception as exc:
        return False, f"NVENC check failed: {exc}"


def _check_librosa() -> Tuple[bool, str]:
    """Check 5: librosa / numba disponible (beat sync)."""
    try:
        import librosa  # noqa: F401
        return True, "librosa OK"
    except ImportError as exc:
        return False, f"librosa no disponible: {exc}"
    except Exception as exc:
        return False, f"librosa error inesperado: {exc}"


def _check_ffmpeg() -> Tuple[bool, str]:
    """Check 6: FFmpeg binario funcional."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, text=True, timeout=CHECK_TIMEOUT,
        )
        if result.returncode == 0:
            version_line = result.stdout.split("\n")[0] if result.stdout else "unknown"
            return True, version_line
        return False, f"ffmpeg returncode={result.returncode}"
    except FileNotFoundError:
        return False, "ffmpeg binary not found"
    except subprocess.TimeoutExpired:
        return False, "ffmpeg timeout"
    except Exception as exc:
        return False, f"ffmpeg check failed: {exc}"


def _check_groq_api_key() -> Tuple[bool, str]:
    """Check 7: Groq API key configurada."""
    key = os.environ.get("GROQ_API_KEY", "")
    if key and len(key) > 20:
        return True, "Groq API key OK"
    return False, "Groq API key no configurada"


def _check_deepseek_api_key() -> Tuple[bool, str]:
    """Check 8: DeepSeek API key configurada."""
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key and len(key) > 10:
        return True, "DeepSeek API key OK"
    return False, "DeepSeek API key no configurada"


# Mapa de checks: (nombre_feature, función_check, flag_a_desactivar)
CHECKS: List[Tuple[str, callable, str, str]] = [
    ("numpy", _check_numpy, "audio_spectral_analysis",
     "[HealthCheck] NumPy {msg} — audio spectral analysis desactivado"),
    ("torchcodec", _check_torchcodec, "narrative_cut_detection",
     "[HealthCheck] TorchCodec no disponible — narrative cut detection desactivado"),
    ("mediapipe", _check_mediapipe, "face_tracking_mediapipe",
     "[HealthCheck] MediaPipe mp.solutions no disponible — usando Haar cascade"),
    ("nvenc", _check_nvenc, "gpu_encode",
     "[HealthCheck] NVENC no disponible — usando libx264 (más lento)"),
    ("librosa", _check_librosa, "beat_sync_librosa",
     "[HealthCheck] librosa no disponible — beat sync usará estimación FFmpeg"),
    ("ffmpeg", _check_ffmpeg, "ffmpeg",
     "[HealthCheck] FFmpeg no disponible — {msg}"),
    ("groq_api_key", _check_groq_api_key, "llm_groq",
     "[HealthCheck] Groq API key no configurada — LLMRouter usará DeepSeek"),
    ("deepseek_api_key", _check_deepseek_api_key, "llm_deepseek",
     "[HealthCheck] DeepSeek API key no configurada — LLMRouter usará Groq"),
]


def _build_status_table(results: Dict[str, Tuple[bool, str]]) -> str:
    """Build ASCII status table."""
    lines = [
        "┌─────────────────────────────┬──────────┬────────────────────────────┐",
        "│ Feature                     │ Status   │ Fallback                   │",
        "├─────────────────────────────┼──────────┼────────────────────────────┤",
    ]
    for name, (ok, _) in results.items():
        flag = name  # name is the feature flag key
        status = "✅ ON " if ok else "❌ OFF"
        fallback = FALLBACK_MAP.get(flag, "—")
        lines.append(
            f"│ {flag:<27} │ {status:<8} │ {fallback:<26} │"
        )
    lines.append(
        "└─────────────────────────────┴──────────┴────────────────────────────┘"
    )
    return "\n".join(lines)


class DependencyHealthChecker:
    """
    Verifica dependencias del sistema al arrancar el worker.
    Ajusta FEATURE_FLAGS según disponibilidad.
    """

    def __init__(self) -> None:
        self.results: Dict[str, Tuple[bool, str]] = {}

    def run_checks(self) -> Dict[str, bool]:
        """
        Ejecuta todos los checks de forma síncrona (el worker aún no tiene event loop).
        Retorna el dict de flags actualizado.
        """
        logger.info("=" * 60)
        logger.info("🔍 Dependency Health Check — iniciando...")
        logger.info("=" * 60)

        for name, check_fn, flag, log_msg_template in CHECKS:
            ok, msg = check_fn()
            self.results[name] = (ok, msg)

            if not ok:
                FEATURE_FLAGS.set(flag, False)
                log_msg = log_msg_template.format(msg=msg)
                logger.warning(log_msg)
            else:
                FEATURE_FLAGS.set(flag, True)
                logger.info("[HealthCheck] %s: %s", name, msg)

        # ── Validaciones fatales ──────────────────────────────────────────
        ffmpeg_ok = self.results.get("ffmpeg", (False, ""))[0]
        if not ffmpeg_ok:
            msg = self.results["ffmpeg"][1]
            logger.critical(
                "❌ FATAL: FFmpeg no disponible — no hay pipeline posible.\n"
                "   Detalle: %s\n"
                "   El worker NO se iniciará.",
                msg,
            )
            print(
                f"\n❌ FATAL: FFmpeg no disponible — no hay pipeline posible.\n"
                f"   Detalle: {msg}\n"
                f"   El worker NO se iniciará.\n",
                file=sys.stderr,
            )
            raise RuntimeError(f"FFmpeg not available: {msg}")

        groq_ok = self.results.get("groq_api_key", (False, ""))[0]
        deepseek_ok = self.results.get("deepseek_api_key", (False, ""))[0]
        if not groq_ok and not deepseek_ok:
            logger.critical(
                "❌ FATAL: Ningún LLM configurado — se necesita al menos GROQ_API_KEY "
                "o DEEPSEEK_API_KEY.\n"
                "   El worker NO se iniciará.",
            )
            print(
                "\n❌ FATAL: Ningún LLM configurado.\n"
                "   Se necesita al menos GROQ_API_KEY o DEEPSEEK_API_KEY.\n"
                "   El worker NO se iniciará.\n",
                file=sys.stderr,
            )
            raise RuntimeError(
                "No LLM configured: set GROQ_API_KEY or DEEPSEEK_API_KEY"
            )

        # ── Tabla resumen ─────────────────────────────────────────────────
        table = _build_status_table(self.results)
        logger.info("📊 Resumen de features:\n%s", table)
        print(f"\n📊 Resumen de features:\n{table}\n")

        return FEATURE_FLAGS.get_all()

    def recheck(self, feature_names: List[str]) -> List[str]:
        """
        Re-ejecuta checks solo para las features indicadas.
        Retorna lista de features que se recuperaron (pasaron de False a True).
        """
        recovered = []
        for name, check_fn, flag, log_msg_template in CHECKS:
            if flag not in feature_names:
                continue
            ok, msg = check_fn()
            if ok and not FEATURE_FLAGS.get(flag, True):
                FEATURE_FLAGS.set(flag, True)
                recovered.append(flag)
                logger.info(
                    "[SelfHealer] ✅ Feature recuperada: %s — %s", flag, msg
                )
            elif not ok:
                logger.info(
                    "[SelfHealer] ⏳ Feature sigue desactivada: %s — %s", flag, msg
                )
        return recovered


async def run_health_check_and_start_loop() -> None:
    """
    Punto de entrada único: ejecuta health check y arranca el loop de
    self-healing como background task.
    """
    checker = DependencyHealthChecker()
    flags = checker.run_checks()

    # Guardar en Redis con TTL 1h
    try:
        import redis.asyncio as aioredis
        r = aioredis.Redis(
            host=os.getenv("REDIS_HOST", "redis"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            decode_responses=True,
        )
        await r.set("worker:feature_flags", json.dumps(flags), ex=3600)
        await r.aclose()
    except Exception as exc:
        logger.warning("[HealthCheck] No se pudo guardar en Redis: %s", exc)

    # Arrancar loop de self-healing como background task
    asyncio.create_task(_self_heal_loop())


async def _self_heal_loop() -> None:
    """
    Background task que corre cada 15 minutos y re-ejecuta los checks
    de las dependencias que estaban OFF, por si el entorno cambió.
    """
    import json
    import redis.asyncio as aioredis

    while True:
        await asyncio.sleep(900)  # 15 minutos
        disabled = [
            k for k, v in FEATURE_FLAGS.get_all().items()
            if not v and k != "ffmpeg"  # FFmpeg es fatal, no se recupera solo
        ]
        if not disabled:
            continue

        logger.info(
            "[SelfHealer] Re-checking %d disabled features...", len(disabled)
        )
        checker = DependencyHealthChecker()
        recovered = checker.recheck(disabled)
        if recovered:
            logger.info("[SelfHealer] ✅ Recovered features: %s", recovered)
            # Actualizar Redis
            try:
                r = aioredis.Redis(
                    host=os.getenv("REDIS_HOST", "redis"),
                    port=int(os.getenv("REDIS_PORT", "6379")),
                    decode_responses=True,
                )
                await r.set(
                    "worker:feature_flags",
                    json.dumps(FEATURE_FLAGS.get_all()),
                    ex=3600,
                )
                await r.aclose()
            except Exception as exc:
                logger.warning(
                    "[SelfHealer] No se pudo actualizar Redis: %s", exc
                )
