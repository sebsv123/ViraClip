# VPI Daily Production Runbook

## 1. Activar B-roll editorial (temporal)

Solo para tasks que necesiten B-roll editorial. Desactivar después.

```bash
# Activar
sed -i 's/VIRACLIP_ENABLE_EDITORIAL_BROLL=false/VIRACLIP_ENABLE_EDITORIAL_BROLL=true/' .env

# Recrear backend/worker
docker compose up -d --force-recreate backend worker

# Verificar
grep VIRACLIP_ENABLE_EDITORIAL .env
# Debe mostrar: VIRACLIP_ENABLE_EDITORIAL_BROLL=true
```

## 2. Lanzar task desde frontend

1. Abrir `http://localhost:3000`
2. Iniciar sesión
3. Pegar URL de YouTube: `https://youtu.be/3wgwaxIfUJQ?si=1CUCuVBFWhxOMRqs`
4. Opciones recomendadas:
   - `num_clips`: 1-2
   - `subtitles`: true
   - `include_broll`: true
   - `processing_mode`: quality

## 3. Validar output

### Estado de task
```bash
curl -s http://localhost:8000/tasks/<TASK_ID> -H "user_id: DA9ZDUPfVfSUL9Ra9vLKM64Xnbb0NK3Q" | python3 -m json.tool
```

### Logs task-scoped
```bash
docker compose logs worker | grep "<TASK_ID>"
```

### Verificaciones clave
```bash
# Caption cache
docker compose logs worker | grep "caption-cache.*hit"

# Caption timestamps reales
docker compose logs worker | grep "caption-timeline.*using cached word timestamps"

# Caption layout VPI
docker compose logs worker | grep "vpi-preset"

# B-roll local
docker compose logs worker | grep "local-broll.*selected asset"

# mark_used
docker compose logs worker | grep "local-broll.*marked used"

# B-roll duration
docker compose logs worker | grep "broll-duration"

# PIP disabled
docker compose logs worker | grep "broll PIP disabled"

# Sin texto fantasma
docker compose logs worker | grep "HookVisualService skipped"
docker compose logs worker | grep "top text overlay skipped"
```

## 4. Dónde encontrar outputs

### Output principal (frontend)
```
/app/temp/uploads/clips/<TASK_ID>/
```

### Output organizado VPI
```
/app/outputs/vpi/YYYY-MM-DD/task_<short_id>/
  clip_01.mp4
  clip_01_metadata.json
  clip_01_transcript.txt
  clip_01_captions.ass
  clip_02.mp4
  clip_02_metadata.json
  clip_02_transcript.txt
  clip_02_captions.ass
  source_info.json
  task_summary.json
  task_summary.md
```

### ASS debug
```
/app/temp/caption_debug/
```

## 5. Dónde encontrar task_summary

```bash
# Listar outputs del día
ls -lah /app/outputs/vpi/$(date +%Y-%m-%d)/

# Ver task_summary
cat /app/outputs/vpi/$(date +%Y-%m-%d)/task_*/task_summary.json | python3 -m json.tool

# Ver task_summary en Markdown
cat /app/outputs/vpi/$(date +%Y-%m-%d)/task_*/task_summary.md
```

## 6. Cómo auditar asset bank

```bash
# Auditor completo
docker compose exec worker python /app/scripts/audit_broll_asset_bank.py

# Ver assets por categoría
find /app/assets/broll -maxdepth 2 -type f | sort

# Ver usage history
cat /app/assets/broll/.usage_history.json | python3 -m json.tool
```

## 7. Cómo restaurar defaults seguros

```bash
# Desactivar B-roll editorial
sed -i 's/VIRACLIP_ENABLE_EDITORIAL_BROLL=true/VIRACLIP_ENABLE_EDITORIAL_BROLL=false/' .env

# Recrear backend/worker
docker compose up -d --force-recreate backend worker

# Verificar
grep VIRACLIP_ENABLE_EDITORIAL .env
# Debe mostrar: VIRACLIP_ENABLE_EDITORIAL_BROLL=false
```

## 8. Flags de producción (defaults seguros)

```
VIRACLIP_BETA_CLEAN=true
VIRACLIP_ENABLE_EDITORIAL_BROLL=false
VIRACLIP_ENABLE_LOCAL_BROLL_BANK=true
WHISPER_DEVICE=cpu
VIRACLIP_ENABLE_TORCH_CUDA=false
VIRACLIP_ENABLE_NVENC=false
BROLL_FORCE_CPU=true
T2V_ENABLED=false
COMFYUI_ENABLED=false
```

## 9. Troubleshooting rápido

| Problema | Comando |
|---|---|
| Task stuck en queued | `docker compose logs worker` |
| No hay captions | `docker compose logs worker \| grep "caption-timeline"` |
| B-roll no aparece | `docker compose logs worker \| grep "editorial-broll"` |
| Asset bank vacío | `docker compose exec worker python /app/scripts/audit_broll_asset_bank.py` |
| Output no encontrado | `find /app/outputs/vpi -name "task_summary.json"` |
| Contenedores caídos | `docker compose ps` |
