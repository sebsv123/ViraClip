"""
Tests para el pipeline de audio SFX: sfx_generator, audio_placement y
la integración en transition_selector.

Requiere ffmpeg en el PATH. Los tests generan archivos temporales en
/tmp/ que se limpian automáticamente.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from ..sfx_generator import (
    generate_dark_riser,
    generate_deep_boom,
    generate_magic_whoosh,
    generate_silence,
    generate_tension_riser,
)
from ..audio_placement import (
    _extract_timestamp,
    _merge_nearby_events,
    _parse_timestamp_sec,
    boom_variant_counter,
    detect_audio_events,
    apply_audio_events,
)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _ffmpeg_available() -> bool:
    """Check if ffmpeg is installed."""
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _create_silent_test_video(path: Path, duration: float = 3.0) -> Path:
    """Create a silent test video with a color frame using ffmpeg."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=blue:s=640x480:d={duration}",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac",
        "-shortest",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=30)
    return path


# ── Tests ──────────────────────────────────────────────────────────────────────


class TestSfxGenerator:
    """Tests para sfx_generator.py — generación de assets de audio con FFmpeg."""

    @pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg no instalado")
    def test_generate_dark_riser_creates_wav(self):
        """generate_dark_riser debe crear un archivo WAV válido."""
        path = generate_dark_riser(duration=1.0)
        assert path, "No se generó el riser"
        assert Path(path).exists(), f"Archivo no encontrado: {path}"
        assert path.endswith(".wav"), f"Extensión incorrecta: {path}"
        # Verificar que es un WAV válido
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"ffprobe falló: {result.stderr}"
        dur = float(result.stdout.strip())
        assert 0.8 <= dur <= 1.2, f"Duración inesperada: {dur}"
        Path(path).unlink(missing_ok=True)

    @pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg no instalado")
    def test_generate_magic_whoosh_variants(self):
        """generate_magic_whoosh debe generar variantes de distinta duración."""
        durations = []
        for v in range(3):
            path = generate_magic_whoosh(variant=v)
            assert path, f"Variant {v} no generó archivo"
            assert Path(path).exists()
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", path],
                capture_output=True, text=True, timeout=10,
            )
            dur = float(result.stdout.strip())
            durations.append(dur)
            Path(path).unlink(missing_ok=True)
        # Las duraciones deben ser distintas (0.3, 0.45, 0.6)
        assert len(set(round(d, 1) for d in durations)) >= 2, \
            f"Las variantes deberían tener distinta duración: {durations}"

    @pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg no instalado")
    def test_generate_deep_boom_all_variants(self):
        """generate_deep_boom debe generar las 4 variantes sin error."""
        for v in range(4):
            path = generate_deep_boom(variant=v)
            assert path, f"Variant {v} no generó archivo"
            assert Path(path).exists()
            Path(path).unlink(missing_ok=True)

    @pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg no instalado")
    def test_generate_tension_riser_creates_wav(self):
        """generate_tension_riser debe crear un archivo WAV válido."""
        path = generate_tension_riser(duration=2.0)
        assert path, "No se generó el tension riser"
        assert Path(path).exists()
        assert path.endswith(".wav")
        Path(path).unlink(missing_ok=True)

    @pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg no instalado")
    def test_generate_silence_creates_wav(self):
        """generate_silence debe crear un archivo de silencio."""
        path = generate_silence(duration_ms=500)
        assert path, "No se generó el silencio"
        assert Path(path).exists()
        # Verificar duración ~0.5s
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=10,
        )
        dur = float(result.stdout.strip())
        assert 0.4 <= dur <= 0.6, f"Duración inesperada: {dur}"
        Path(path).unlink(missing_ok=True)

    def test_generate_deep_boom_invalid_variant_falls_back(self):
        """Variante inválida debe fallback a variant=0."""
        path = generate_deep_boom(variant=99)
        assert path, "Variante inválida debería generar archivo (fallback a 0)"
        if path:
            Path(path).unlink(missing_ok=True)


class TestAudioPlacementUtils:
    """Tests para funciones auxiliares de audio_placement.py."""

    def test_extract_timestamp_bracket_format(self):
        """_extract_timestamp debe parsear formato [MM:SS]."""
        assert _extract_timestamp("[01:30] texto") == 90.0
        assert _extract_timestamp("[00:05] hola") == 5.0

    def test_extract_timestamp_bare_format(self):
        """_extract_timestamp debe parsear formato MM:SS sin corchetes."""
        assert _extract_timestamp("02:15 texto") == 135.0

    def test_extract_timestamp_seconds(self):
        """_extract_timestamp debe parsear segundos sueltos."""
        assert _extract_timestamp("42.5 texto") == 42.5

    def test_extract_timestamp_no_match(self):
        """_extract_timestamp debe devolver None si no hay timestamp."""
        assert _extract_timestamp("texto sin timestamp") is None

    def test_parse_timestamp_sec_float(self):
        """_parse_timestamp_sec debe aceptar float directamente."""
        assert _parse_timestamp_sec(42.5) == 42.5

    def test_parse_timestamp_sec_mmss(self):
        """_parse_timestamp_sec debe parsear MM:SS."""
        assert _parse_timestamp_sec("01:30") == 90.0

    def test_merge_nearby_events(self):
        """_merge_nearby_events debe fusionar eventos cercanos."""
        events = [
            {"timestamp": 1.0, "duration": 0.5, "type": "deep_boom"},
            {"timestamp": 1.3, "duration": 0.8, "type": "deep_boom"},  # gap 0.3 < 0.5
            {"timestamp": 3.0, "duration": 0.5, "type": "magic_whoosh"},
        ]
        merged = _merge_nearby_events(events, gap=0.5)
        assert len(merged) == 2, f"Esperaba 2 eventos, obtuve {len(merged)}"
        # El segundo evento tiene mayor duración (0.8 > 0.5), debe quedarse
        assert merged[0]["duration"] == 0.8

    def test_merge_nearby_events_empty(self):
        """_merge_nearby_events con lista vacía debe devolver vacío."""
        assert _merge_nearby_events([]) == []


class TestAudioPlacementIntegration:
    """Tests de integración para audio_placement.py."""

    @pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg no instalado")
    @pytest.mark.asyncio
    async def test_detect_audio_events_keyword_spanish(self, tmp_path):
        """detect_audio_events debe detectar eventos por palabra clave en español."""
        transcript = (
            "[00:00] Hola a todos\n"
            "[00:05] Esto es un impacto increíble\n"
            "[00:10] El misterio se revela\n"
        )
        events = await detect_audio_events(
            transcript=transcript,
            language="es",
            video_duration=20.0,
        )
        # Debe detectar al menos "impacto" → deep_boom e "increíble" → magic_whoosh
        assert len(events) >= 2, f"Esperaba al menos 2 eventos, obtuve {len(events)}: {events}"
        types = [e["type"] for e in events]
        assert "deep_boom" in types, f"Debe contener deep_boom: {types}"
        assert "magic_whoosh" in types, f"Debe contener magic_whoosh: {types}"

    @pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg no instalado")
    @pytest.mark.asyncio
    async def test_detect_audio_events_keyword_english(self, tmp_path):
        """detect_audio_events debe detectar eventos por palabra clave en inglés."""
        transcript = (
            "[00:00] Hello everyone\n"
            "[00:03] This is an amazing surprise\n"
            "[00:08] The secret is revealed\n"
        )
        events = await detect_audio_events(
            transcript=transcript,
            language="en",
            video_duration=15.0,
        )
        assert len(events) >= 2, f"Esperaba al menos 2 eventos, obtuve {len(events)}"
        types = [e["type"] for e in events]
        assert "magic_whoosh" in types, f"Debe contener magic_whoosh: {types}"
        assert "tension_riser" in types or "dark_riser" in types, \
            f"Debe contener tension_riser o dark_riser: {types}"

    @pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg no instalado")
    @pytest.mark.asyncio
    async def test_apply_audio_events_no_events_returns_original(self, tmp_path):
        """apply_audio_events con lista vacía debe devolver el path original."""
        video_path = tmp_path / "test_video.mp4"
        _create_silent_test_video(video_path)
        result = await apply_audio_events(
            clip_path=str(video_path),
            events=[],
            output_path=str(tmp_path / "output.mp4"),
        )
        assert result == str(video_path), \
            f"Sin eventos debe devolver el path original: {result}"

    @pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg no instalado")
    @pytest.mark.asyncio
    async def test_apply_audio_events_with_boom(self, tmp_path):
        """apply_audio_events debe mezclar un deep_boom en el video."""
        video_path = tmp_path / "test_video.mp4"
        _create_silent_test_video(video_path, duration=3.0)
        output_path = tmp_path / "output_with_sfx.mp4"
        events = [
            {"timestamp": 0.5, "type": "deep_boom", "duration": 0.8},
        ]
        result = await apply_audio_events(
            clip_path=str(video_path),
            events=events,
            output_path=str(output_path),
        )
        assert result == str(output_path), f"Esperaba output path: {result}"
        assert output_path.exists(), "El archivo de salida no existe"
        # Verificar que tiene audio (no debe ser el mismo que el original silencioso)
        result_probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
             "-of", "csv=p=0", str(output_path)],
            capture_output=True, text=True, timeout=10,
        )
        assert "audio" in result_probe.stdout, "El output debe tener stream de audio"

    @pytest.mark.skipif(not _ffmpeg_available(), reason="ffmpeg no instalado")
    @pytest.mark.asyncio
    async def test_boom_variant_counter_rotates(self, tmp_path):
        """El contador de variantes de boom debe rotar entre llamadas."""
        initial = boom_variant_counter[0]
        # Llamar a detect_audio_events con un transcript que tenga "impacto"
        transcript = "[00:00] Esto es un gran impacto\n"
        events = await detect_audio_events(
            transcript=transcript,
            language="es",
            video_duration=10.0,
        )
        # Verificar que el contador avanzó (cada deep_boom incrementa el contador)
        assert boom_variant_counter[0] > initial, \
            "El contador de variantes debería haber avanzado"
