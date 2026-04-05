# ViraClip Quick Start — 5 Minutos a Producción

## 🚀 Setup Ultra-Rápido

```bash
# 1. Clonar y configurar
git clone https://github.com/tu-usuario/ViraClip.git
cd ViraClip
cp backend/.env.example backend/.env

# 2. Editar .env - SOLO estas líneas son críticas:
nano backend/.env
# Añadir:
#   HF_TOKEN=hf_xxxxx                    (obtén en: https://huggingface.co/settings/tokens)
#   OPENAI_API_KEY=sk-xxxxx              (o usa Ollama local)

# 3. Setup automatizado (15-20 min)
chmod +x setup.sh
./setup.sh

# 4. Verificación (1 min)
./backend/scripts/health_check.sh
docker-compose run --rm backend python scripts/verify_setup.py --all

# 5. ¡Listo! Accede a:
# - Frontend: http://localhost:3000
# - Backend API: http://localhost:8000/docs
# - ComfyUI: http://localhost:8188
```

---

## 🎯 Crear Tu Primer Clip (30 segundos)

```bash
# Via API
curl -X POST http://localhost:8000/api/tasks \
  -H "Content-Type: application/json" \
  -H "user_id: demo_user" \
  -d '{
    "source": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "processing_mode": "fast",
    "add_subtitles": true,
    "target_platform": "tiktok"
  }'

# O via Frontend:
# 1. Abre http://localhost:3000
# 2. Pega URL de YouTube
# 3. Click "Generate Clips"
# 4. Espera 2-3 min
# 5. Descarga clips + variantes + SRT
```

---

## 📦 Qué Incluye Esta Build

### Fases Completadas (12/30+)

| Fase | Features | Status |
|------|----------|--------|
| **Phase 1** | Baseline pipeline (Whisper, scene detection, FFmpeg) | ✅ |
| **Phase 2.1** | YOLOv10 object detection | ✅ |
| **Phase 4.1** | Bitrate variants (high/med/low) + SRT export | ✅ |
| **Phase 4.3** | Viral trend scraping (TikTok/IG/YT) | ✅ |
| **Phase 5.1** | Milvus vector DB (multimodal search) | ✅ |
| **Phase 5.3** | Feedback loop + auto-retraining | ✅ |
| **Phase 6** | ComfyUI integration + 9 custom nodes | ✅ |
| **Phase 7** | TikTok dataset + training pipeline | ✅ |
| **Phase 8** | Quantum-inspired + Swarm evolution ML | ✅ |

### Features Clave

- ✅ **Multi-platform export**: TikTok (9:16), Reels, Shorts con bitrate ladders
- ✅ **Viral trends**: Auto-boost scores basado en trending hashtags
- ✅ **Vector search**: Busca clips por contenido semántico
- ✅ **Self-improving**: Reentrena modelo semanalmente con feedback real
- ✅ **ComfyUI workflows**: 5 workflows pre-built para editing avanzado
- ✅ **Datasets REALES**: TikTok 100k+ videos desde HuggingFace
- ✅ **Production-ready**: Docker, health checks, monitoring

---

## 🔧 Comandos Esenciales

### Gestión de Servicios
```bash
# Iniciar todo
docker-compose up -d

# Ver logs
docker-compose logs -f backend worker

# Reiniciar servicio
docker-compose restart backend

# Detener todo
docker-compose down

# Rebuild completo
docker-compose build --no-cache
docker-compose up -d
```

### Verificación
```bash
# Health check (30 seg)
./backend/scripts/health_check.sh

# Smoke tests (1 min)
docker-compose run --rm backend python scripts/verify_setup.py --all

# Ver datasets descargados
docker-compose run --rm backend python scripts/download_datasets.py --status
```

### Datasets
```bash
# Descargar TikTok dataset (2GB, ~10 min)
docker-compose run --rm backend python scripts/download_datasets.py --tiktok-only

# YouTube trending (opcional)
docker-compose run --rm backend python scripts/download_datasets.py --youtube-only
```

### Feedback Loop
```bash
# Ver stats del modelo actual
curl http://localhost:8000/api/feedback/stats

# Trigger retraining manual
curl -X POST http://localhost:8000/api/feedback/retrain/sync

# Predict con modelo entrenado
curl -X POST http://localhost:8000/api/feedback/predict \
  -H "Content-Type: application/json" \
  -d '{"duration": 30, "hook_strength": 85, "engagement_score": 72, "has_captions": 1, "has_broll": 0}'
```

---

## 📊 Performance Esperado

| Métrica | Valor (CPU-only) |
|---------|------------------|
| Tiempo generación clip 60s | ~2-3 min |
| Whisper transcription | ~30s (large-v3) |
| Scene detection | ~15s |
| FFmpeg rendering | ~45s |
| Viral score calculation | <1s |
| Bitrate variants (3x) | +30s |
| SRT export | <1s |
| **Total end-to-end** | **~3-4 min** |

**RAM Usage:**
- Backend: ~2-4GB
- Worker (Whisper large-v3): ~6-8GB por worker
- Total recomendado: **16GB RAM**

---

## 🎨 ComfyUI Workflows

### Acceso
```bash
# Abrir ComfyUI
open http://localhost:8188

# Workflows disponibles:
# - viral_clip_basic.json           (CPU-only)
# - viral_clip_with_broll.json      (CPU + YOLO)
# - viral_clip_generative.json      (GPU required)
# - viral_clip_quantum_inspired.json (Phase 8)
# - viral_clip_swarm_evolution.json (Phase 8)
```

### Custom Nodes Incluidos
- `ViraClipWhisperNode` - Transcripción
- `ViraClipYOLONode` - Object detection
- `ViraClipSilenceRemovalNode` - Jump cuts
- `ViraClipThumbnailNode` - Smart thumbnails
- `ViraClipMetadataNode` - SEO titles + hashtags
- `ViraClipLoRATrainerNode` - LoRA training (GPU)
- `QuantumInspiredViralityNode` - Quantum simulation
- `SwarmEvolutionViralityNode` - Genetic optimization

---

## 🔐 Tokens Requeridos

| Token | Dónde Obtener | Uso |
|-------|---------------|-----|
| `HF_TOKEN` | [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) | **CRÍTICO** - Datasets |
| `OPENAI_API_KEY` | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | LLM (o usa Ollama) |
| `KAGGLE_USERNAME` + `KEY` | [kaggle.com/settings](https://www.kaggle.com/settings) | Opcional |
| `YOUTUBE_API_KEY` | [console.cloud.google.com](https://console.cloud.google.com/apis/credentials) | Opcional |

---

## 🐛 Troubleshooting Rápido

| Problema | Solución |
|----------|----------|
| Service won't start | `docker-compose logs [service]` |
| Out of memory | Reducir workers: `docker-compose up -d --scale worker=1` |
| Dataset download fails | Verificar `HF_TOKEN` en `.env` |
| ComfyUI nodes missing | `docker-compose restart comfyui` |
| Slow processing | Usar Whisper medium: `WHISPER_MODEL_SIZE=medium` |

---

## 📚 Documentación Completa

- **[DEPLOY_GUIDE.md](DEPLOY_GUIDE.md)** - Guía completa de deployment
- **[VERIFICATION_CHECKLIST.md](VERIFICATION_CHECKLIST.md)** - Checklist paso a paso
- **[ROADMAP.md](ROADMAP.md)** - Todas las fases y features
- **[IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md)** - Detalles técnicos

---

## 🎯 Próximos Pasos

1. ✅ **Verificar setup** - Ejecuta checklist completo
2. 📊 **Crear clips de prueba** - Valida pipeline completo
3. 🎨 **Explorar ComfyUI** - Prueba workflows avanzados
4. 📈 **Monitor performance** - 24h con tráfico real
5. 🚀 **Deploy a producción** - Nginx + SSL + monitoring

---

**¿Listo? Ejecuta:**
```bash
./setup.sh && ./backend/scripts/health_check.sh
```

**¡Y estás en producción! 🎉**
