# ViraClip Testing Guide

## Quick Start

### Run All Tests
```powershell
# Ejecutar suite completa
docker-compose exec backend python /app/scripts/run_all_tests.py

# Con coverage report
docker-compose exec backend python /app/scripts/run_all_tests.py --coverage

# Tests rápidos (sin integration)
docker-compose exec backend python /app/scripts/run_all_tests.py --fast
```

### Smoke Test (End-to-End)
```powershell
# Test completo del pipeline
docker-compose exec backend python /app/scripts/smoke_test.py

# Test rápido (solo imports + servicios)
docker-compose exec backend python /app/scripts/smoke_test.py --quick

# Test con video de YouTube
docker-compose exec backend python /app/scripts/smoke_test.py --url "https://youtube.com/watch?v=..."
```

---

## Test Suite por Phase

### Phase 2.2 — MLP Virality Scorer
```powershell
docker-compose exec backend python /app/scripts/run_all_tests.py --phase 2.2
```

**Tests incluidos:**
- ✅ Feature extraction (transcript + audio)
- ✅ MLP training con samples sintéticos
- ✅ Blending con Phi-3 score
- ✅ Modelo guardado/cargado correctamente
- ✅ Heuristic fallback sin modelo entrenado

**Coverage objetivo:** >80%

---

### Phase 2.3 — RAFT Optical Flow Transitions
```powershell
docker-compose exec backend python /app/scripts/run_all_tests.py --phase 2.3
```

**Tests incluidos:**
- ✅ RAFT model download/loading
- ✅ Optical flow extraction
- ✅ Transition generation con FFmpeg xfade fallback
- ✅ GPU/CPU capability detection

---

### Phase 3.5 — Hook Slow-Motion
```powershell
docker-compose exec backend python /app/scripts/run_all_tests.py --phase 3.5
```

**Tests incluidos:**
- ✅ `maybe_apply_hook_slowmo()` gating logic
- ✅ FFmpeg setpts + minterpolate command construction
- ✅ Video duration probing
- ✅ Env var configuration (HOOK_SLOWMO_ENABLED, etc.)
- ✅ Integration con video_service.py

---

### Phase 8.3 — LSTM/CNN Engagement Prediction
```powershell
docker-compose exec backend python /app/scripts/run_all_tests.py --phase 8.3
```

**Tests incluidos:**
- ✅ Time-series feature extraction (10-dim features)
- ✅ LSTM/CNN model training
- ✅ Heuristic sigmoid curve fallback
- ✅ Drop-off point detection
- ✅ Hook insertion point finding
- ✅ Drift detection (retrain flag)
- ✅ Model save/load (state_dict serialization)

**Synthetic data:** 300 samples generados automáticamente

---

### Phase 8.4 — ONNX Export
```powershell
docker-compose exec backend python /app/scripts/run_all_tests.py --phase 8.4
```

**Tests incluidos:**
- ✅ Viral scorer export (sklearn → ONNX via skl2onnx)
- ✅ Engagement predictor export (PyTorch → ONNX)
- ✅ ONNX Runtime inference session
- ✅ Fallback to sklearn/PyTorch cuando ONNX no disponible
- ✅ Round-trip verification

---

## Training & Model Management

### Entrenar Todos los Modelos
```powershell
# Con datos de feedback DB + sintéticos
docker-compose exec backend python /app/scripts/train_all_models.py

# Solo datos sintéticos (bootstrap)
docker-compose exec backend python /app/scripts/train_all_models.py --synthetic-only

# Con más epochs
docker-compose exec backend python /app/scripts/train_all_models.py --epochs 100

# Entrenar + exportar a ONNX
docker-compose exec backend python /app/scripts/train_all_models.py --export-onnx
```

### Entrenar Modelos Individuales
```powershell
# Viral scorer
docker-compose exec backend python /app/scripts/train_viral_scorer.py --source both --epochs 50

# Engagement predictor
docker-compose exec backend python /app/scripts/train_engagement_predictor.py --source both --epochs 50

# Ver estado de modelos
docker-compose exec backend python /app/scripts/train_viral_scorer.py --status
docker-compose exec backend python /app/scripts/train_engagement_predictor.py --status
```

### Exportar a ONNX
```powershell
# Exportar todos los modelos
docker-compose exec backend python /app/scripts/export_to_onnx.py --verify

# Solo viral scorer
docker-compose exec backend python /app/scripts/export_to_onnx.py --model viral_scorer --verify

# Solo engagement predictor
docker-compose exec backend python /app/scripts/export_to_onnx.py --model engagement --verify

# Ver estado ONNX
docker-compose exec backend python /app/scripts/export_to_onnx.py --status
```

---

## Manual Testing

### Test Individual de Servicios

#### Viral Scorer
```python
from services.viral_scorer_service import get_viral_scorer

scorer = get_viral_scorer()
score = scorer.score_segment(
    transcript="This is an amazing shocking secret nobody knows!",
    duration=22.0,
)
print(f"Virality score: {score}/100")  # Expected: 70-85
```

#### Engagement Predictor
```python
from services.engagement_prediction_service import get_engagement_predictor

predictor = get_engagement_predictor()
result = predictor.predict_engagement_curve(
    words=[
        {"text": "amazing", "start": 0, "end": 500, "confidence": 0.9},
        {"text": "content", "start": 500, "end": 1000, "confidence": 0.85},
    ],
    duration=15.0,
)
print(f"Retention score: {result['retention_score']}%")
print(f"Drop-off points: {result['drop_off_points']}")
print(f"Hook points: {result['hook_points']}")
```

#### ONNX Inference
```python
from services.onnx_inference_service import get_onnx_service

svc = get_onnx_service()
caps = svc.get_capabilities()
print(f"ONNX models loaded: {caps}")

# Test virality prediction
score = svc.predict_virality("Amazing secret revealed!", duration=20.0)
print(f"ONNX virality score: {score}/100")
```

---

## Performance Benchmarking

### Viral Scorer Performance
```python
import time
from services.viral_scorer_service import get_viral_scorer
from services.onnx_inference_service import get_onnx_service

transcript = "This is a test transcript with some viral keywords like shocking and amazing."

# Sklearn baseline
scorer = get_viral_scorer()
t0 = time.perf_counter()
for _ in range(100):
    scorer.score_segment(transcript, 20.0)
sklearn_time = time.perf_counter() - t0
print(f"Sklearn: {sklearn_time:.3f}s for 100 predictions ({sklearn_time*10:.1f}ms/pred)")

# ONNX
onnx_svc = get_onnx_service()
t0 = time.perf_counter()
for _ in range(100):
    onnx_svc.predict_virality(transcript, 20.0)
onnx_time = time.perf_counter() - t0
print(f"ONNX:    {onnx_time:.3f}s for 100 predictions ({onnx_time*10:.1f}ms/pred)")

speedup = sklearn_time / onnx_time
print(f"\nSpeedup: {speedup:.1f}×")
```

**Expected results:**
- Sklearn: ~150-200ms/prediction
- ONNX: ~30-50ms/prediction
- Speedup: 3-5×

---

## Integration Testing

### Test Task Creation → Clip Generation
```python
import asyncio
from services.video_service import VideoService
from models import Platform

async def test_pipeline():
    result = await VideoService.process_video(
        video_path="/path/to/test_video.mp4",
        task_id=123,
        target_platform=Platform.TIKTOK,
        num_clips=3,
    )
    
    print(f"Generated {len(result['clips'])} clips")
    for i, clip in enumerate(result['clips'], 1):
        print(f"\nClip {i}:")
        print(f"  Duration: {clip['duration']:.1f}s")
        print(f"  Virality: {clip['virality_score']}/100")
        print(f"  Retention: {clip.get('retention_score', 'N/A')}%")
        print(f"  Method: {clip.get('engagement_method', 'N/A')}")

asyncio.run(test_pipeline())
```

---

## CI/CD Integration

### GitHub Actions Example
```yaml
name: ViraClip Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Build containers
        run: docker-compose build
      
      - name: Run tests
        run: |
          docker-compose up -d
          docker-compose exec -T backend python /app/scripts/run_all_tests.py --fast
      
      - name: Smoke test
        run: docker-compose exec -T backend python /app/scripts/smoke_test.py --quick --skip-db
```

---

## Test Data Management

### Crear Dataset de Test
```python
# backend/tests/fixtures/test_data.py
TEST_TRANSCRIPTS = [
    {
        "text": "Amazing shocking secret nobody knows!",
        "duration": 15.0,
        "expected_virality": 80,
    },
    {
        "text": "Um so like basically uh you know...",
        "duration": 20.0,
        "expected_virality": 25,
    },
]
```

### Mock de Servicios Externos
```python
from unittest.mock import patch, MagicMock

# Mock Whisper transcription
@patch("services.transcription_service.WhisperModel")
def test_with_mock_whisper(mock_whisper):
    mock_whisper.return_value.transcribe.return_value = (
        [{"text": "test transcript"}],
        {"language": "en"},
    )
    # ... test code ...
```

---

## Debugging Failed Tests

### Ver logs detallados
```powershell
docker-compose exec backend python /app/scripts/run_all_tests.py --phase 8.3 -vv
```

### Ejecutar un test específico
```powershell
docker-compose exec backend pytest /app/tests/test_phase_8_3_engagement.py::TestExtractTimeSeriesFeatures::test_returns_correct_shape -v
```

### Inspeccionar coverage
```powershell
docker-compose exec backend python /app/scripts/run_all_tests.py --coverage
# Abrir htmlcov/index.html en browser
```

---

## Test Checklist Pre-Deploy

- [ ] `run_all_tests.py` — todos pasan
- [ ] `smoke_test.py` — E2E funciona
- [ ] Modelos entrenados: `train_all_models.py`
- [ ] ONNX exportado: `export_to_onnx.py --verify`
- [ ] Database migrations aplicadas
- [ ] Redis functional
- [ ] FFmpeg funcional
- [ ] Logs sin errores críticos

---

## Known Issues & Workarounds

### PyTorch LSTM pickle bug
**Fixed** — ahora usamos `state_dict` en lugar de pickle directo del `nn.Module`

### ONNX Runtime no encuentra modelos
```bash
# Verificar que /app/models/onnx/ tiene los archivos .onnx
docker-compose exec backend ls -lh /app/models/onnx/

# Re-exportar si faltan
docker-compose exec backend python /app/scripts/export_to_onnx.py
```

### Tests fallan por falta de GPU
Normal — muchos tests tienen fallback CPU automático. Revisar warnings, no errors.

---

## Further Reading

- pytest docs: https://docs.pytest.org/
- Coverage.py: https://coverage.readthedocs.io/
- Docker testing: https://docs.docker.com/compose/
