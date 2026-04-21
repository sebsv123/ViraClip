# Aplicación de Fixes — Arq Queue Bug + Observabilidad

## 🎯 Resumen de Problema
El worker de arq no procesaba jobs porque la configuración tenía `max_jobs=1` (muy restrictivo) y `max_tries=3` (demasiado alto), causando que jobs quedaran en retry sin procesar.

---

## 📋 Archivos Modificados/Creados

### 1. FIX CRÍTICO — `backend/src/workers/tasks.py`

**Cambios en `WorkerSettings` (líneas ~380-404):**
```python
# ANTES (problemático):
max_tries = 3              # Demasiados reintentos
job_timeout = 3600
max_jobs = 1               # Solo 1 job concurrente (bloqueante)

# DESPUÉS (fix aplicado):
max_tries = 2              # Fail faster
job_timeout = 3600         # 1 hora mínimo
keep_result = 3600         # NUEVO: mantener resultados
max_jobs = 4               # 4 jobs concurrentes por worker
```

**Cambios en `process_video_task` (líneas ~40-230):**
- ✅ Structured logging al inicio del job con task_id, user_id, url, parámetros
- ✅ Log completo del traceback antes del re-raise para debugging
- ✅ Timestamp de inicio para medir duración

### 2. VERIFICACIÓN — `backend/src/workers/job_queue.py`

✅ **Queue name match confirmado:**
- `job_queue.py`: `DEFAULT_QUEUE_NAME = "viraclip_cpu_tasks"`
- `tasks.py`: `queue_name = "viraclip_cpu_tasks"`
- **Resultado:** Las queues coinciden, no hay mismatch.

### 3. SCRIPT NUEVO — `dev-status.sh`

Script ejecutable que muestra en un solo comando:
- Estado de contenedores (healthy/unhealthy)
- ARQ queue depth (ZCARD arq:queue)
- Jobs in-progress, retry, dead-letter
- Últimos 20 logs filtrados del worker
- Errores del backend (últimos 5 min)
- Tasks en PostgreSQL por status
- Uso de GPU (nvidia-smi)
- Espacio en disco

**Uso:** `./dev-status.sh`

### 4. Makefile — Targets nuevos añadidos

```makefile
make status              # Ejecuta dev-status.sh
make logs-worker         # Tail -f logs del worker
make logs-backend        # Tail -f logs del backend
make worker-restart      # Reinicia el worker
make flush-queue         # Limpia arq:queue (con confirmación)
make task-status TASK_ID=<uuid>  # Estado de task específico
make test-task URL=<url> # Crea task y hace polling automático
```

### 5. Docker Compose — Mejoras de observabilidad

Añadido a servicios críticos:
```yaml
logging:
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"

restart: unless-stopped

labels:
  - "service.description=..."
  - "service.group=..."
```

---

## 🚀 Instrucciones de Aplicación (en orden)

### Paso 1: Aplicar fixes de código (no requiere reinicio)
```bash
cd ~/CascadeProjects/ViraClip
# Los cambios ya están aplicados a:
# - backend/src/workers/tasks.py
# - backend/src/workers/job_queue.py (verificado)
```

### Paso 2: Reiniciar workers para cargar nueva config
```bash
# Opción A: Reinicio suave (recomendado)
make worker-restart

# Opción B: Reinicio completo del stack
docker compose restart backend worker worker-2 worker-3
```

### Paso 3: Verificar configuración cargada
```bash
# En los logs del worker debe aparecer:
docker logs viraclip-worker --tail 50 | grep -E "max_jobs|max_tries"
# Esperado: max_jobs=4, max_tries=2
```

### Paso 4: Monitorear estado
```bash
make status
# Debe mostrar:
# - Contenedores healthy
# - Queue depth = 0 (si no hay jobs pendientes)
# - Jobs in-progress = 0
# - No errores críticos
```

### Paso 5: Test end-to-end
```bash
# Crear task de prueba con polling automático
make test-task URL="https://www.youtube.com/watch?v=3wgwaxIfUJQ"

# O manualmente:
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"url":"https://www.youtube.com/watch?v=3wgwaxIfUJQ","num_clips":1}'

# Monitorear logs
make logs-worker
```

---

## ✅ Cómo Verificar que el Fix Funcionó

### Indicadores de éxito:
1. **En logs del worker aparece:**
   ```
   [arq:job:start] task_id=... user_id=... source_type=... url=... params=...
   ```

2. **El job progresa por fases:**
   ```
   [Phase 1/13] transcription
   [Phase 2/13] beat_analysis_stage
   ...
   ```

3. **Task termina con status "completed":**
   ```bash
   curl http://localhost:8000/tasks/<task_id>
   # "status": "completed"
   # "progress": 1.0
   ```

4. **Clip exportado existe:**
   ```bash
   docker exec viraclip-worker ls /app/exports/clips/
   # *.mp4 files present
   ```

### Indicadores de fallo (requieren debugging):
- Job queda en "processing" con progress=0.0 por >5 minutos
- Logs del worker no muestran "[arq:job:start]"
- Redis arq:retry:<job_id> existe y crece
- arq:queue depth no baja (ZCARD arq:queue > 0)

---

## 🔧 Troubleshooting

### Si el worker no procesa jobs después del reinicio:
```bash
# 1. Verificar que arq:queue tiene jobs
docker exec viraclip-redis redis-cli ZCARD arq:queue

# 2. Verificar queue name en worker
docker logs viraclip-worker --tail 20 | grep queue_name

# 3. Forzar flush y re-encolar
make flush-queue
# Luego crear nuevo task

# 4. Verificar conectividad Redis
docker exec viraclip-worker redis-cli -h viraclip-redis ping
```

### Si hay jobs stuck in-progress:
```bash
# Limpiar jobs zombis
docker exec viraclip-redis redis-cli KEYS 'arq:in-progress:*'
docker exec viraclip-redis redis-cli DEL arq:in-progress:<job_id>
```

---

## 📊 Dashboard de Salud Post-Fix

Ejecuta periódicamente:
```bash
watch -n 30 ./dev-status.sh
```

Métricas esperadas en estado saludable:
- Queue depth: 0-2 (fluctuación normal)
- Jobs in-progress: 0-4 (max_jobs limit)
- Jobs retrying: 0 (raro, solo si hay errores)
- Dead letter: 0
- Backend/Worker: healthy
- GPU: disponible (si aplica)

---

## 📝 Notas
- Los cambios en `tasks.py` son quirúrgicos y compatibles con arq >= 0.25
- `max_jobs=4` permite throughput adecuado sin saturar recursos
- `max_tries=2` (fail faster) detecta problemas más rápido
- `keep_result=3600` permite consultar resultados de jobs completados
