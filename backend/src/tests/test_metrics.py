"""
Tests para metrics.py y feedback_store.py.

Usa mocks para Redis y verifica estadísticas de percentiles,
logs de timeout, registro de feedback y matriz de correcciones.
"""

from __future__ import annotations

import json
import logging

import pytest

from ..metrics import (
    record_effect_timing,
    get_effect_stats,
    get_all_effects_stats,
    TIMEOUT_THRESHOLDS,
)
from ..feedback_store import (
    record_transition_feedback,
    get_transition_feedback_stats,
    adjust_selector_weights,
    _transcript_hash,
)


# ── Mock Redis ─────────────────────────────────────────────────────────────────


class MockRedis:
    """Mock de Redis que almacena listas en memoria."""

    def __init__(self):
        self._lists: dict[str, list[str]] = {}

    async def lpush(self, key: str, value: str) -> int:
        if key not in self._lists:
            self._lists[key] = []
        self._lists[key].insert(0, value)
        return 1

    async def ltrim(self, key: str, start: int, end: int) -> None:
        if key in self._lists:
            self._lists[key] = self._lists[key][start:end + 1] if end >= 0 else self._lists[key][start:]

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        if key not in self._lists:
            return []
        if end == -1:
            return self._lists[key][start:]
        return self._lists[key][start:end + 1]


# ── Tests: metrics ─────────────────────────────────────────────────────────────


class TestMetrics:
    """Tests para metrics.py."""

    def test_record_and_get_stats(self):
        """Registrar 10 tiempos y verificar p50, p95, p99 correctos."""
        # Limpiar estado global
        import backend.src.metrics as metrics_mod
        metrics_mod._metrics.clear()

        # Registrar 10 tiempos: 0.1, 0.2, ..., 1.0
        for i in range(1, 11):
            record_effect_timing("match_cut", i * 0.1)

        stats = get_effect_stats("match_cut")
        assert stats["count"] == 10, f"Esperaba 10, obtuve {stats['count']}"
        # avg = (0.1+0.2+...+1.0)/10 = 0.55 → 550ms
        assert 500 <= stats["avg_ms"] <= 600, f"avg_ms inesperado: {stats['avg_ms']}"
        # p50 = 0.55 * 1000 = 550ms (entre 5º y 6º)
        assert 400 <= stats["p50_ms"] <= 700, f"p50_ms inesperado: {stats['p50_ms']}"
        # p95 = 0.95 * 1000 = 950ms
        assert 800 <= stats["p95_ms"] <= 1050, f"p95_ms inesperado: {stats['p95_ms']}"
        # p99 = 0.99 * 1000 = 990ms
        assert 900 <= stats["p99_ms"] <= 1050, f"p99_ms inesperado: {stats['p99_ms']}"

    def test_timeout_warning_logged(self, caplog):
        """Registrar tiempo > umbral debe loggear 'SLOW_EFFECT'."""
        import backend.src.metrics as metrics_mod
        metrics_mod._metrics.clear()

        threshold = TIMEOUT_THRESHOLDS.get("match_cut", 5.0)

        with caplog.at_level(logging.WARNING):
            record_effect_timing("match_cut", threshold + 1.0)

        assert any("SLOW_EFFECT" in record.message for record in caplog.records), \
            "Debe haber un log con SLOW_EFFECT"

    def test_get_all_effects_stats(self):
        """get_all_effects_stats debe devolver todos los efectos registrados."""
        import backend.src.metrics as metrics_mod
        metrics_mod._metrics.clear()

        record_effect_timing("match_cut", 0.5)
        record_effect_timing("glitch", 0.3)

        all_stats = get_all_effects_stats()
        assert "match_cut" in all_stats
        assert "glitch" in all_stats
        assert all_stats["match_cut"]["count"] == 1
        assert all_stats["glitch"]["count"] == 1

    def test_empty_effect_stats(self):
        """Efecto sin datos debe devolver stats vacíos."""
        stats = get_effect_stats("nonexistent_effect")
        assert stats["count"] == 0
        assert stats["p50_ms"] == 0.0
        assert stats["p95_ms"] == 0.0
        assert stats["avg_ms"] == 0.0


# ── Tests: feedback_store ──────────────────────────────────────────────────────


class TestFeedbackStore:
    """Tests para feedback_store.py."""

    @pytest.mark.asyncio
    async def test_record_feedback(self):
        """Llamar record_transition_feedback debe guardar en Redis."""
        redis = MockRedis()
        await record_transition_feedback(
            transcript="La familia es importante en un seguro.",
            auto_choice="match_cut",
            manual_choice="glitch",
            auto_scores={"match_cut": 0.71, "glitch": 0.45},
            redis_client=redis,
        )
        entries = await redis.lrange("feedback:transitions", 0, -1)
        assert len(entries) == 1, "Debe haber 1 entrada en Redis"
        data = json.loads(entries[0])
        assert data["auto"] == "match_cut"
        assert data["manual"] == "glitch"
        assert "transcript_hash" in data
        assert data["scores"]["match_cut"] == 0.71

    @pytest.mark.asyncio
    async def test_feedback_stats_empty(self):
        """Redis vacío debe devolver total_corrections=0."""
        redis = MockRedis()
        stats = await get_transition_feedback_stats(redis)
        assert stats["total_corrections"] == 0
        assert stats["total_saves"] == 0
        assert stats["most_corrected"] is None
        assert stats["correction_matrix"] == {}

    @pytest.mark.asyncio
    async def test_feedback_matrix(self):
        """3 entradas deben producir la matriz de correcciones correcta."""
        redis = MockRedis()
        # 2 correcciones: match_cut → glitch
        for _ in range(2):
            await record_transition_feedback(
                transcript="test transcript",
                auto_choice="match_cut",
                manual_choice="glitch",
                auto_scores={},
                redis_client=redis,
            )
        # 1 corrección: glitch → match_cut
        await record_transition_feedback(
            transcript="another transcript",
            auto_choice="glitch",
            manual_choice="match_cut",
            auto_scores={},
            redis_client=redis,
        )

        stats = await get_transition_feedback_stats(redis)
        assert stats["total_corrections"] == 3
        assert stats["total_saves"] == 3
        assert stats["most_corrected"]["auto_choice"] == "match_cut"
        assert stats["most_corrected"]["count"] == 2
        assert stats["correction_matrix"].get("match_cut→glitch") == 2
        assert stats["correction_matrix"].get("glitch→match_cut") == 1

    @pytest.mark.asyncio
    async def test_feedback_no_redis(self):
        """Sin Redis, record_transition_feedback no debe fallar."""
        # No debe lanzar excepción
        await record_transition_feedback(
            transcript="test",
            auto_choice="match_cut",
            manual_choice="glitch",
            auto_scores={},
            redis_client=None,
        )

    def test_adjust_selector_weights_no_autochange(self):
        """adjust_selector_weights NO debe modificar thresholds automáticamente."""
        feedback_stats = {
            "total_corrections": 6,
            "total_saves": 10,
            "most_corrected": {"auto_choice": "match_cut", "count": 6},
            "correction_matrix": {
                "match_cut→glitch": 6,
            },
            "override_rate": 0.6,
        }
        scores = {"match_cut": 0.65, "glitch": 0.50}

        result = adjust_selector_weights(scores, feedback_stats)
        assert result["auto_adjusted"] is False, "No debe hacer ajuste automático"
        assert len(result["recommendations"]) > 0, "Debe haber recomendaciones"
        # Verificar que la recomendación menciona el threshold
        assert "match_cut" in result["recommendations"][0]

    def test_adjust_selector_weights_few_corrections(self):
        """Con <5 correcciones, no debe recomendar ajustes."""
        feedback_stats = {
            "total_corrections": 3,
            "total_saves": 10,
            "most_corrected": {"auto_choice": "match_cut", "count": 3},
            "correction_matrix": {
                "match_cut→glitch": 3,
            },
            "override_rate": 0.3,
        }
        scores = {"match_cut": 0.65}

        result = adjust_selector_weights(scores, feedback_stats)
        assert len(result["recommendations"]) == 0, \
            "Con <5 correcciones no debe recomendar"

    def test_transcript_hash(self):
        """_transcript_hash debe producir un hash corto y consistente."""
        h1 = _transcript_hash("La familia es importante")
        h2 = _transcript_hash("La familia es importante")
        h3 = _transcript_hash("Otro texto diferente")
        assert h1 == h2, "Mismo texto debe producir mismo hash"
        assert h1 != h3, "Texto diferente debe producir hash diferente"
        assert len(h1) == 12, "Hash debe tener 12 caracteres"
