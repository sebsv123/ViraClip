# ViraClip Performance Optimization Guide

## Overview
Esta guía cubre profiling, caching, y optimizaciones específicas para cada subsistema de ViraClip.

---

## 1. Testing & Profiling

### Ejecutar Test Suite Completo
```powershell
# Todos los tests
docker-compose exec backend python /app/scripts/run_all_tests.py

# Con coverage report
docker-compose exec backend python /app/scripts/run_all_tests.py --coverage

# Tests rápidos (sin integration)
docker-compose exec backend python /app/scripts/run_all_tests.py --fast

# Solo una phase
docker-compose exec backend python /app/scripts/run_all_tests.py --phase 8.3
```

### Profiling de Performance
```python
# Agregar al inicio de funciones críticas:
import cProfile
import pstats
from io import StringIO

profiler = cProfile.Profile()
profiler.enable()

# ... tu código ...

profiler.disable()
s = StringIO()
ps = pstats.Stats(profiler, stream=s).sort_stats('cumulative')
ps.print_stats(20)
print(s.getvalue())
```

---

## 2. Subsistema: Transcripción (Whisper)

### Bottlenecks Actuales
- Whisper large-v3: ~10-15s por minuto de audio en CPU
- Sin GPU: 3-5× más lento

### Optimizaciones
```python
# 1. Cache de transcripciones (ya implementado en advanced_cache.py)
from caching.advanced_cache import TranscriptCache
cache = TranscriptCache()

# 2. Batch processing para múltiples videos
# Usar faster-whisper batch_size parameter
model = WhisperModel("large-v3", compute_type="int8")  # int8 = 2× faster

# 3. Pre-download del modelo al build time (Dockerfile)
# Ya implementado en backend/Dockerfile
```

**Ganancia esperada**: 40-50% más rápido con int8 + caching

---

## 3. Subsistema: Virality Scoring

### MLP Scorer (Phase 2.2)
```bash
# Entrenar con datos reales
docker-compose exec backend python /app/scripts/train_viral_scorer.py --source both --epochs 100

# Monitorear performance
# Model inference: ~1-2ms por segmento (muy rápido)
```

### ONNX Export (Phase 8.4)
```bash
# Exportar a ONNX para 3-5× speedup
docker-compose exec backend python /app/scripts/export_to_onnx.py --verify

# Usar ONNX en producción (auto-fallback si no existe)
# OnnxInferenceService detecta automáticamente .onnx files
```

**Ganancia esperada**: 300-500% faster con ONNX vs sklearn

---

## 4. Subsistema: Video Processing (FFmpeg)

### Bottlenecks
- Clip rendering: 5-10s por clip de 30s
- Transitions (RAFT optical flow): +2-4s por transición
- Hook slow-motion: +1-2s cuando enabled

### Optimizaciones

#### A. FFmpeg Hardware Acceleration
```python
# NVIDIA GPU (requiere GPU worker)
ffmpeg_cmd = [
    "ffmpeg", "-hwaccel", "cuda", "-i", input_path,
    "-c:v", "h264_nvenc",  # Hardware encoder
    # ...
]

# Intel QSV (CPU integrado)
ffmpeg_cmd = [
    "ffmpeg", "-hwaccel", "qsv", "-i", input_path,
    "-c:v", "h264_qsv",
    # ...
]
```

#### B. Parallel Clip Generation
```python
# En video_service.py — ya usa asyncio.gather()
clips = await asyncio.gather(
    *[create_clip(seg, i) for i, seg in enumerate(segments)]
)
# Ganancia: 3-4× speedup vs secuencial
```

#### C. Reduce minterpolate overhead
```bash
# .env.example — desactivar slow-mo para clips de baja virality
HOOK_SLOWMO_ENABLED=false
HOOK_SLOWMO_MIN_SCORE=80  # Solo aplicar a top clips
```

**Ganancia esperada**: 2-3× con GPU encoding; 30-40% con config tuning

---

## 5. Subsistema: Database & Caching

### Redis Caching Strategy
```python
# Transcript cache hit rate target: >80%
# Video metadata cache TTL: 1 hora
# Virality score cache TTL: 24 horas

# Monitorear hit rate
redis-cli INFO stats | grep keyspace_hits
```

### PostgreSQL Query Optimization
```sql
-- Índices críticos (ya implementados en init.sql)
CREATE INDEX idx_tasks_user_status ON tasks(user_id, status);
CREATE INDEX idx_clips_task_created ON clips(task_id, created_at);

-- Vacuum regular para evitar bloat
VACUUM ANALYZE tasks;
VACUUM ANALYZE clips;
```

### Milvus Vector Search
```python
# Batch vector insertion (>100 vectores)
from services.milvus_service import get_milvus_service
svc = get_milvus_service()
svc.batch_insert(vectors, metadata)  # 10× faster que inserts individuales

# Search optimization
results = svc.search(
    query_vector,
    top_k=5,  # Reducir si solo necesitas top-3
    nprobe=8,  # Balance precision/speed
)
```

**Ganancia esperada**: 50-70% faster queries con índices + Redis cache

---

## 6. Subsistema: ML Model Inference

### Engagement Predictor (Phase 8.3)
```bash
# Entrenar modelo
docker-compose exec backend python /app/scripts/train_engagement_predictor.py --epochs 50

# Exportar a ONNX
docker-compose exec backend python /app/scripts/export_to_onnx.py --model engagement --verify

# Inference con ONNX
# OnnxInferenceService.predict_engagement() — 3× faster
```

### Drift Detection
```python
# Monitoring: revisar logs cada semana
grep "Drift detected" /app/logs/*.log

# Si drift > threshold → retrain
docker-compose exec backend python /app/scripts/train_engagement_predictor.py --source both
```

---

## 7. Resource Limits & Scaling

### Docker Resource Allocation
```yaml
# docker-compose.yml — ajustar según hardware
services:
  backend:
    deploy:
      resources:
        limits:
          cpus: '4.0'
          memory: 8G
        reservations:
          memory: 4G
```

### Worker Queue (Arq)
```python
# Tune worker concurrency en src/workers/tasks.py
class WorkerSettings:
    max_jobs = 4  # Parallelismo de tasks
    job_timeout = 600  # 10 min timeout
```

### Horizontal Scaling (futuro)
```bash
# Multiple backend replicas
docker-compose up -d --scale backend=3

# Load balancer (nginx) → backend:8000
```

---

## 8. Monitoring & Metrics

### Logs Centralizados
```bash
# Ver todos los logs
docker-compose logs -f --tail=100

# Filtrar por servicio
docker-compose logs -f backend | grep ERROR
```

### Métricas Clave
```python
# Track en Prometheus / Grafana (futuro):
# - Clip generation time (target: <8s por clip de 30s)
# - Transcription speed (target: 1.5× realtime en CPU)
# - Cache hit rate (target: >75%)
# - Model inference latency (target: <50ms)
# - Queue depth (target: <10 pending tasks)
```

---

## 9. Quick Wins Checklist

- [x] Redis caching habilitado (TranscriptCache, MilvusCache)
- [x] Async clip processing (asyncio.gather)
- [ ] **Train models con datos reales** (`train_viral_scorer.py`, `train_engagement_predictor.py`)
- [ ] **Export to ONNX** (`export_to_onnx.py --verify`)
- [ ] Configurar HOOK_SLOWMO_MIN_SCORE alto (>75) para reducir overhead
- [ ] Vacuum PostgreSQL semanalmente
- [ ] Monitor Redis memory usage (`redis-cli INFO memory`)
- [ ] Profile clip generation con cProfile (identificar bottlenecks específicos)

---

## 10. Roadmap de Optimización (Post-CPU Phase)

### Con GPU (Phase 3.1+)
- Whisper large-v3 en GPU: 5-10× speedup
- FFmpeg h264_nvenc: 2-3× speedup
- ESRGAN upscaling: GPU only
- Total expected: **6-8× faster pipeline**

### Sin GPU (optimizaciones CPU restantes)
- ONNX inference: +300% viral scorer, +200% engagement
- int8 quantization Whisper: +40%
- Parallel processing tuning: +20-30%
- Total expected: **2-3× faster pipeline**

---

## Testing Recommendations

1. **Benchmark baseline** antes de cada optimización:
   ```bash
   time docker-compose exec backend python -c "from services.video_service import VideoService; import asyncio; asyncio.run(VideoService.process_video(...))"
   ```

2. **A/B testing** de configuraciones:
   - HOOK_SLOWMO_ENABLED=true vs false
   - Whisper compute_type="float16" vs "int8"
   - Redis cache TTL variations

3. **Load testing** con Artillery/k6 (futuro):
   ```bash
   # Simular 10 users concurrentes
   k6 run --vus 10 --duration 60s loadtest.js
   ```

---

## Support & Further Reading

- FFmpeg optimization: https://trac.ffmpeg.org/wiki/HWAccelIntro
- ONNX Runtime perf: https://onnxruntime.ai/docs/performance/
- Redis best practices: https://redis.io/docs/manual/optimization/
- Whisper benchmarks: https://github.com/openai/whisper/discussions/
