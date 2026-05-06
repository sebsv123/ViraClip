# DIAGNÓSTICO COMPLETO - ViraClip Pipeline

**Fecha:** 2026-05-06 09:05 UTC  
**GPU:** NVIDIA RTX 5070 Laptop (8GB VRAM)

---

## 🔴 PROBLEMAS CRÍTICOS ENCONTRADOS

### 1. NVENC No Funciona (CRÍTICO)

**Problema:** FFmpeg en contenedor expone `nvenc_h264` pero el código prueba `h264_nvenc`

**Evidencia:**
```bash
$ docker exec viraclip-worker ffmpeg -encoders | grep nvenc
V..... nvenc_h264           NVIDIA NVENC H.264 encoder
V..... hevc_nvenc           NVIDIA NVENC hevc encoder

# Código en clip_creation.py:34
["-c:v", "h264_nvenc"]  # ← Este nombre NO existe
```

**Impacto:**
- GPU util: 0% (debería ser 80-95%)
- Encoding: libx264 CPU (22s/clip vs 3s esperados)
- Rendimiento: 5-10x más lento

**Fix:** Cambiar `h264_nvenc` → `nvenc_h264` en clip_creation.py

---

### 2. OpenCV VideoWriter Falla (CRÍTICO)

**Problema:** `cv2.VideoWriter` no encuentra encoder H.264

**Errores:**
```
[ERROR] Could not find encoder for codec_id=27
[ERROR] VIDEOIO/FFMPEG: Failed to initialize VideoWriter
```

**Archivos:** video_polish_service.py:350,726

**Fix:** Usar FFmpeg directamente en lugar de OpenCV

---

### 3. Tasa Fallo 22% (ALTO)

**DB Status:**
```
completed: 35
failed: 13     ← 22% fallo
processing: 2
queued: 10
```

**Causa probable:** Problemas #1 y #2 combinados

---

### 4. Librosa No Instalado (MEDIA)

**Log:** `[beat_sync] librosa not available — using FFmpeg`

**Fix:** `pip install librosa`

---

## 📊 MÉTRICAS ACTUALES

| Métrica | Valor | Estado |
|---------|-------|--------|
| GPU util | 0% | 🔴 Crítico |
| VRAM usada | 375 MiB | 🔴 Bajo |
| Power draw | 6.7W | 🔴 Idle |
| Tiempo/clip | 22s | 🔴 7x lento |
| Cache hit ratio | 99.8% | ✅ Excelente |
| Frontend lint | 0 errors | ✅ OK |

---

## 🔧 FIXES REQUERIDOS

### 1. NVENC (clip_creation.py:29-39)
```python
codecs_to_test = ["h264_nvenc", "nvenc_h264"]  # Probar ambos
```

### 2. OpenCV → FFmpeg (video_polish_service.py)
Reemplazar `cv2.VideoWriter` con FFmpeg subprocess

### 3. Librosa
```bash
docker-compose exec worker pip install librosa
```

---

## 📈 COMPARATIVA RENDIMIENTO

| Modo | Tiempo/clip | Throughput |
|------|-------------|------------|
| CPU (actual) | 22s | 2.7 clips/min |
| GPU (esperado) | 3s | 15 clips/min |

**Pérdida:** 80-85% del potencial RTX 5070

---

## ✅ COMPONENTES FUNCIONANDO

- Frontend lint/build: ✅
- Redis cache: ✅ (99.8% hit)
- Backend API: ✅
- AssemblyAI transcription: ✅
- Groq LLM analysis: ✅
- Semantic Edit Planner: ✅
- Master Director: ✅
- Suggestion Studio: ✅
- SmartAudio pipeline: ✅

---

**Conclusión:** El sistema es funcional pero el encoding por CPU limita severamente el rendimiento. El fix de NVENC es prioridad crítica.
