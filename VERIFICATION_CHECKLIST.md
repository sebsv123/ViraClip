# ViraClip Setup Verification Checklist

## ✅ Pre-Deploy Checklist

Use esta lista para verificar que todo está configurado correctamente antes de producción.

### 1. Configuración Básica

- [ ] Copiar `.env.example` a `.env`
  ```bash
  cp backend/.env.example backend/.env
  ```

- [ ] Configurar tokens requeridos en `.env`:
  - [ ] `HF_TOKEN` (HuggingFace) — **REQUERIDO** para datasets
  - [ ] `OPENAI_API_KEY` o `GOOGLE_API_KEY` (LLM)
  - [ ] `KAGGLE_USERNAME` + `KAGGLE_KEY` (opcional)
  - [ ] `YOUTUBE_API_KEY` (opcional)

- [ ] Configurar secrets de seguridad:
  - [ ] Cambiar `POSTGRES_PASSWORD`
  - [ ] Cambiar `BACKEND_AUTH_SECRET`
  - [ ] Cambiar `ADMIN_SECRET`

### 2. Build & Deploy

- [ ] Construir containers
  ```bash
  docker-compose build --no-cache
  ```

- [ ] Iniciar servicios
  ```bash
  docker-compose up -d
  ```

- [ ] Verificar servicios corriendo
  ```bash
  docker-compose ps
  # Todos deben mostrar "running"
  ```

### 3. Health Checks

- [ ] Ejecutar health check automático
  ```bash
  chmod +x backend/scripts/health_check.sh
  ./backend/scripts/health_check.sh
  ```
  **Esperado:** Todos ✅ OK

- [ ] Verificar endpoints manualmente:
  - [ ] Backend: http://localhost:8000/health → `{"status":"ok"}`
  - [ ] Frontend: http://localhost:3000 → Página carga
  - [ ] ComfyUI: http://localhost:8188 → Interface carga
  - [ ] Swagger: http://localhost:8000/docs → API docs

### 4. Verificación de Fases Implementadas

- [ ] **Phase 4.1: Export Variants**
  ```bash
  docker-compose run --rm backend python scripts/verify_setup.py --phase 4.1
  ```
  **Esperado:** 4/4 tests passing

- [ ] **Phase 4.3: Viral Trends**
  ```bash
  docker-compose run --rm backend python scripts/verify_setup.py --phase 4.3
  ```
  **Esperado:** 4/4 tests passing

- [ ] **Phase 5.1: Milvus Vector DB**
  ```bash
  docker-compose run --rm backend python scripts/verify_setup.py --phase 5.1
  ```
  **Esperado:** 5/5 tests passing

- [ ] **Phase 5.3: Feedback Loop**
  ```bash
  docker-compose run --rm backend python scripts/verify_setup.py --phase 5.3
  ```
  **Esperado:** 6/6 tests passing

### 5. Dataset Integration

- [ ] Descargar TikTok dataset
  ```bash
  docker-compose run --rm backend python scripts/download_datasets.py --tiktok-only
  ```
  **Esperado:** ~2GB descargado, guardado en `/app/datasets/tiktok_videos.parquet`

- [ ] Verificar datasets
  ```bash
  docker-compose run --rm backend python scripts/download_datasets.py --status
  ```
  **Esperado:** ✅ TikTok-Videos (HF) mostrando tamaño

- [ ] (Opcional) Descargar YouTube trending
  ```bash
  docker-compose run --rm backend python scripts/download_datasets.py --youtube-only
  ```

### 6. ComfyUI Setup

- [ ] Inicializar workflows
  ```bash
  docker-compose run --rm backend python scripts/init_comfyui_workflows.py
  ```
  **Esperado:** 5 workflows copiados, custom nodes verificados

- [ ] Verificar ComfyUI nodes
  ```bash
  curl http://localhost:8188/object_info | grep -i viraclip
  ```
  **Esperado:** Múltiples resultados con "ViraClip"

- [ ] Test workflow en UI:
  - [ ] Abrir http://localhost:8188
  - [ ] Click "Load" → `viral_clip_basic.json`
  - [ ] Verificar nodos "ViraClip" aparecen en lista
  - [ ] (No ejecutar aún si no tienes video de prueba)

### 7. Smoke Test End-to-End

- [ ] Crear clip de prueba
  ```bash
  curl -X POST http://localhost:8000/api/tasks \
    -H "Content-Type: application/json" \
    -H "user_id: test_user" \
    -d '{
      "source": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
      "processing_mode": "fast",
      "add_subtitles": true,
      "target_platform": "tiktok"
    }'
  ```
  **Guardar task_id**

- [ ] Monitorear progreso
  ```bash
  curl http://localhost:8000/api/tasks/{task_id}
  # Verificar status cambia: queued → processing → completed
  ```

- [ ] Verificar clip generado
  ```bash
  # Cuando status = "completed"
  curl http://localhost:8000/api/tasks/{task_id}/clips/0/download -o test_clip.mp4
  
  # Verificar variantes
  docker-compose exec backend ls -lh /app/clips/
  # Debe mostrar: clip.mp4, clip_mq.mp4, clip_lq.mp4, clip.srt
  ```

### 8. Feedback Loop Test

- [ ] Verificar feedback stats
  ```bash
  curl http://localhost:8000/api/feedback/stats
  ```
  **Esperado:** JSON con model_exists, version, etc.

- [ ] Test predicción
  ```bash
  curl -X POST http://localhost:8000/api/feedback/predict \
    -H "Content-Type: application/json" \
    -d '{
      "duration": 30.0,
      "hook_strength": 85.0,
      "engagement_score": 72.0,
      "has_captions": 1,
      "has_broll": 0
    }'
  ```
  **Esperado:** `{"predicted_score": XX.X, "model_version": "..."}`

- [ ] (Opcional) Trigger retraining
  ```bash
  curl -X POST http://localhost:8000/api/feedback/retrain/sync
  ```
  **Esperado:** Training metrics, deployed: true/false

### 9. Performance Checks

- [ ] Verificar uso de memoria
  ```bash
  docker stats --no-stream
  ```
  **Esperado:** backend < 4GB, worker < 8GB cada uno (con Whisper large-v3)

- [ ] Verificar logs sin errores críticos
  ```bash
  docker-compose logs backend worker | grep -i error | grep -v "No error"
  ```
  **Esperado:** Sin errores bloqueantes

- [ ] Benchmark generación de clip
  ```bash
  time docker-compose run --rm backend python -c "
  from workers.tasks import process_video_task
  import asyncio
  asyncio.run(process_video_task({
      'task_id': 'bench',
      'source': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
      'processing_mode': 'fast'
  }))
  "
  ```
  **Esperado:** ~2-3 min para video de 60s (CPU-only)

### 10. Security Checklist (Producción)

- [ ] Todos los secrets cambiados de valores default
- [ ] `SELF_HOST=false` si usas monetización
- [ ] CORS configurado correctamente para frontend domain
- [ ] Firewall: Solo puertos 80, 443 expuestos (detrás de reverse proxy)
- [ ] SSL/TLS habilitado (nginx/Caddy con Let's Encrypt)
- [ ] Database backups configurados (pg_dump cron)
- [ ] Redis persistence habilitado (AOF + RDB)
- [ ] Rate limiting configurado en nginx/API
- [ ] Monitoring setup (Prometheus + Grafana o similar)

---

## 🎯 Quick Verification Command

Ejecuta TODOS los tests de una vez:

```bash
# All-in-one verification
docker-compose run --rm backend python scripts/verify_setup.py --all && \
  ./backend/scripts/health_check.sh && \
  docker-compose run --rm backend python scripts/download_datasets.py --status

echo "✅ All verifications complete!"
```

---

## 📊 Expected Results Summary

| Component | Test | Expected Result |
|-----------|------|-----------------|
| Backend | Health check | `{"status":"ok"}` |
| Frontend | Page load | 200 OK |
| ComfyUI | System stats | JSON response |
| Postgres | pg_isready | Success |
| Redis | PING | PONG |
| Workers | docker-compose ps | 3 running |
| Phase 4.1 | Smoke test | 4/4 passing |
| Phase 4.3 | Smoke test | 4/4 passing |
| Phase 5.1 | Smoke test | 5/5 passing |
| Phase 5.3 | Smoke test | 6/6 passing |
| Datasets | TikTok HF | ~2GB downloaded |
| ComfyUI | Workflows | 5 JSON files |
| ComfyUI | Custom nodes | 9+ nodes registered |

---

## 🐛 Troubleshooting

### Service won't start
```bash
# View logs
docker-compose logs -f [service]

# Restart service
docker-compose restart [service]

# Rebuild from scratch
docker-compose build --no-cache [service]
docker-compose up -d [service]
```

### Out of memory
```bash
# Reduce workers
docker-compose up -d --scale worker=1

# Or use smaller Whisper model
# Edit .env: WHISPER_MODEL_SIZE=medium
docker-compose restart backend worker
```

### Dataset download fails
```bash
# Verify token
grep HF_TOKEN backend/.env

# Test token manually
docker-compose run --rm backend python -c "
from huggingface_hub import login
login(token='YOUR_HF_TOKEN')
print('Token valid!')
"
```

### ComfyUI nodes not loading
```bash
# Verify mount
docker-compose exec comfyui ls -la /ComfyUI/custom_nodes/viraclip_nodes/

# Restart ComfyUI
docker-compose restart comfyui

# Check logs
docker-compose logs comfyui | grep -i viraclip
```

---

## 📝 Post-Verification Steps

Una vez que todos los checks pasen:

1. **Document your configuration**
   - Guarda copia de `.env` (sin secrets) como `.env.template`
   - Documenta cualquier customización en `DEPLOYMENT_NOTES.md`

2. **Setup monitoring**
   - Configura alertas para servicios down
   - Configura métricas de performance
   - Setup log aggregation

3. **Create backups**
   - Database: `pg_dump` diario
   - User data: `/app/uploads`, `/app/clips`
   - Models: `/app/models`

4. **Performance tuning**
   - Ajusta workers según CPU cores
   - Ajusta Whisper model según RAM
   - Configura Redis max memory

5. **Production hardening**
   - Setup reverse proxy (nginx/Caddy)
   - Enable SSL/TLS
   - Configure rate limiting
   - Setup firewall rules

---

**Ready for production when all boxes are checked! ✅**
