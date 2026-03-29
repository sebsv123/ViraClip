# SupoClip — Plan de Mejora V2
### Roadmap detallado por fases para superar a OpusClip y Quso AI
*Actualizado: 2026-03-27 | Versión: post bug-fix completo*

---

## ESTADO ACTUAL (post correcciones)

Todos los bugs B-1 a B-7 + bugs críticos anteriores corregidos. El sistema es estable.
Próximo objetivo: **calidad profesional consistente + velocidad competitiva + features diferenciadores**.

---

## ANÁLISIS COMPARATIVO DETALLADO

### Velocidad de render
| Herramienta | Vídeo 30 min | Vídeo 60 min | Paralelismo |
|-------------|-------------|-------------|-------------|
| OpusClip | 2-4 min | 4-8 min | Cloud paralelo |
| Quso AI | 3-6 min | 6-12 min | Cloud paralelo |
| **SupoClip actual** | **8-20 min** | **15-40 min** | **Secuencial** |
| **SupoClip objetivo** | **3-6 min** | **6-12 min** | **Paralelo local** |

La causa: el render de clips es secuencial en `task_service.py`. Con 3 workers y render paralelo se puede reducir el tiempo 3x.

### Calidad de clips
| Aspecto | OpusClip | Quso | SupoClip | Causa del gap |
|---------|----------|------|----------|---------------|
| Face tracking | Suave, sin saltos | Bueno | Saltos bruscos | `np.interp` en gaps sin cara |
| Subtítulos timing | Perfecto | Muy bueno | Bueno | OK tras B-5 fix |
| B-roll relevancia | Excelente | Bueno | Básico (Pexels genérico) | Sin mood matching |
| Música automática | Integrada + mood | Integrada | Manual (carpeta) | Sin API |
| Thumbnails de clips | Automático | Automático | ❌ No existe | — |
| Título/descripción para RRSS | IA automático | IA automático | ❌ No existe | — |

---

## FASE 1 — Rendimiento y calidad base (ESTA SESIÓN)
*Objetivo: clips 3x más rápidos y sin los defectos visuales más obvios*

### ✅ P1.1: Render paralelo de clips
**Impacto: MÁXIMO — 3x speedup**

El bucle secuencial en `task_service.py:300` se reemplaza con `asyncio.gather()` + semáforo.
- Semáforo de 2 renders simultáneos para evitar OOM
- DB commits y SSE notifications fire as-each-clip-completes
- Sin cambios en la API ni en el frontend

**Resultado**: 5 clips que tardaban 15 min → tardan ~5 min

### ✅ P1.2: Face tracking sin saltos de cámara
**Impacto: ALTO — elimina shakycam en 70% de casos**

En `detect_face_trajectory()`, cuando no hay cara en un frame, actualmente se omite el punto. Cuando hay gaps largos, `np.interp` crea movimientos bruscos entre puntos distantes.

Fix: propagación "hold last known" — si no hay cara en un frame, se repite el último punto conocido. La interpolación queda plana (sin movimiento) en lugar de interpolar con un salto.

**Resultado**: cámara queda fija cuando no hay cara, en lugar de hacer zoom-pan brusco

### ✅ P1.3: Generación automática de título + descripción para RRSS
**Impacto: ALTO — feature que OpusClip cobra como premium**

Añadir al resultado de análisis IA (`ai.py`) campos:
- `social_title`: título optimizado para la plataforma (<60 chars)
- `social_description`: descripción con hashtags (<150 chars)
- `suggested_hashtags`: lista de 5-8 hashtags relevantes al nicho

Se muestra en el frontend junto al clip. Copy-paste directo a TikTok/Reels/Shorts.

### ✅ P1.4: Thumbnails automáticos por clip
**Impacto: MEDIO — mejora UX enormemente en el panel de clips**

Generar un thumbnail .jpg (frame en t=1s) para cada clip generado.
Se sirve como `/clips/{task_id}/{clip_id}_thumb.jpg`.
Frontend muestra thumbnails en la lista de clips en lugar de fondo gris.

---

## FASE 2 — Features diferenciadores (próximas sesiones)
*Objetivo: tener algo que la competencia NO tiene o hace peor*

### P2.1: Traducción funcional vía subtitle-burn
**Reemplaza el SeamlessM4T roto (10GB, nunca arranca)**

Flujo nuevo:
1. Coger la transcripción existente (ya tenemos palabras con timestamps)
2. Traducir el texto con Google Translate API libre (o LibreTranslate local)
3. Generar un fichero SRT con el texto traducido
4. Quemarlo en el vídeo con ffmpeg `-vf subtitles=file.srt`

Esto hace la función de traducción 100% fiable sin modelos enormes.

### P2.2: Música royalty-free vía Pixabay API
**Pixabay ofrece API gratuita con +100k pistas libres de derechos**

- Detectar mood del clip según `niche` + `virality_score`
- Mood map: `{finance: "corporate", fitness: "energetic", motivation: "inspiring", ...}`
- Descargar track MP3 de Pixabay y cachear en `/tmp/supoclip_music_cache/`
- Mezclar al 12% de volumen (ya existe `mix_background_music()`)

### P2.3: Multi-speaker detection y reencuadre inteligente
**El gap más grande con OpusClip — crítico para podcasts/entrevistas**

Cuando se detectan 2+ caras en el mismo frame:
- Identificar al speaker activo (el que está hablando) usando análisis de movimiento labial (simplificado: cara con mayor movimiento en zona boca)
- Mantener ese speaker centrado, pero hacer un suave pan cuando cambia

Tecnología: `MediaPipe FaceMesh` ya instalado + análisis de landmarks de boca.

### P2.4: Preview de hook (primeros 3 segundos)
**Feature premium de OpusClip**

Mostrar en el frontend un indicador del "potencial de hook" basado en:
- Los primeros 3s del clip
- Si el primer frame tiene cara mirando a cámara
- Si el texto empieza con pregunta, cifra o afirmación controversial

Esto ayuda al usuario a priorizar qué clips subir primero.

---

## FASE 3 — Paridad total con líderes del mercado (1-2 meses)

### P3.1: AI Chat de refinamiento de clips
"Este clip empieza demasiado tarde, recórtalo 2 segundos" → IA lo ejecuta.
Requiere: endpoint `/tasks/{id}/clips/{clip_id}/refine` + LLM que parsee instrucciones de edición.

### P3.2: Publicación directa a plataformas
- **TikTok Content API**: subir vídeo con título/hashtags directamente
- **Instagram Graph API**: publicar Reels
- **YouTube Data API**: subir Shorts
- **Buffer/Make.com webhook**: programar publicación

### P3.3: Analytics loop (feedback de virality)
- Tras publicar, conectar con las APIs de cada plataforma para obtener views/likes/shares
- Comparar con el virality_score predicho por la IA
- Ajustar los pesos del scoring automáticamente (reinforcement)

### P3.4: Batch processing (Modo "Clip Masivo")
- Procesar 5-20 vídeos en una sola tarea
- Cola con prioridad por virality score esperado
- Webhook/email cuando termina el batch

---

## VENTAJAS COMPETITIVAS ÚNICAS (no replicables por la competencia)

1. **Privacidad total**: 100% local, nunca sale de tu máquina
2. **Sin límites**: procesa lo que quieras sin pagar por minuto
3. **Prompt customizable**: edita el system prompt de IA para tu nicho
4. **Integración con tus modelos**: fine-tuned locales vía Ollama
5. **Open source**: adapta cualquier feature a tus necesidades exactas

---

## MÉTRICAS DE ÉXITO

| Métrica | Actual | Objetivo Fase 1 | Objetivo Final |
|---------|--------|-----------------|----------------|
| Tiempo render (5 clips) | 10-20 min | 3-7 min | <3 min |
| Clips exitosos / total | ~80% | >95% | >98% |
| Face detected % | ~60% | >80% | >90% |
| Virality score medio | ~45/100 | >55/100 | >65/100 |
| Clips con audio correcto | ~90% | >99% | 100% |
| Clips con thumbnail | 0% | 100% | 100% |

---

## IMPLEMENTACIÓN FASE 1 (status)

| Feature | Estado | Archivos modificados |
|---------|--------|---------------------|
| P1.1 Render paralelo | ✅ Implementado | `task_service.py` — `asyncio.gather()` + `Semaphore(2)` |
| P1.2 Face tracking sin saltos | ✅ Implementado | `video_utils.py` — gap-fill + smoothing window 5→9 |
| P1.3 Título/descripción RRSS | ✅ Implementado | `ai.py`, `video_service.py`, `clip_repository.py`, `tasks/[id]/page.tsx` |
| P1.4 Thumbnails automáticos | ✅ Implementado | `video_utils.py` + `video_service.py` + `clip_repository.py` + frontend |

## IMPLEMENTACIÓN FASE 2 (status)

| Feature | Estado | Archivos modificados |
|---------|--------|---------------------|
| P2.1 Traducción subtitle-burn | ✅ Implementado | `translation_service.py` — reescrito con Google Translate + ffmpeg SRT burn |
| P2.2 Música Pixabay API | ✅ Implementado | `video_utils.py` — `fetch_pixabay_music()`, `get_background_music_for_niche()` |
| P2.3 Multi-speaker detection | ✅ Implementado | `video_utils.py detect_active_speaker_trajectory()` — FaceMesh boca |
| P2.4 Hook preview score (0-100) | ✅ Implementado | `ai.py compute_hook_preview_score()` + repo + frontend badge 🎣 |
| P2.5 Auto silence trim | ✅ Implementado (nuevo) | `video_service.py _auto_trim_silence()` — ffmpeg silencedetect |
| P2.6 Caption estilo por plataforma | ✅ Implementado (nuevo) | `task_service.py _pick_caption_template()` — TikTok/Reels/Shorts |

## MIGRACIÓN DB requerida

Ejecutar antes del próximo deploy (aplica todo — Fase 1 + Fase 2):
```sql
-- migrations/sql/20260327_0001_social_copy_and_thumbnails.sql
ALTER TABLE generated_clips
    ADD COLUMN IF NOT EXISTS social_title        VARCHAR(120),
    ADD COLUMN IF NOT EXISTS social_description  VARCHAR(300),
    ADD COLUMN IF NOT EXISTS suggested_hashtags  TEXT[],
    ADD COLUMN IF NOT EXISTS thumbnail_filename  VARCHAR(255),
    ADD COLUMN IF NOT EXISTS face_detected       BOOLEAN,
    ADD COLUMN IF NOT EXISTS hook_preview_score  SMALLINT DEFAULT 0;
```

## IMPLEMENTACIÓN FASE 3 (status)

| Feature | Estado | Archivos modificados |
|---------|--------|---------------------|
| P3.1 AI Chat de refinamiento | ✅ Implementado | `ai.py ClipEditAction + parse_clip_edit_instruction()`, `tasks.py POST /refine`, frontend panel "AI Refine" |
| P3.2 Publicación directa social | ✅ Skeleton | `social_distribution_service.py`, `social.py` router (en `/social/publish`) |
| P3.3 Batch processing | ✅ Implementado | `tasks.py POST /batch-start + GET /batch/{id}/status`, frontend tab "Batch URLs" |
| P3.4 DB migration batch_id | ✅ Implementado | `20260327_0002_batch_features.sql` |
| P3.5 A/B variant generation | ✅ Implementado | `video_service.create_ab_variant()`, `task_service.py`, frontend badge A/B |

## NUEVAS FEATURES AÑADIDAS POR ROSA (sesión 2026-03-28)

| Feature | Estado | Archivos |
|---------|--------|---------|
| Elite AI Service (multimodal) | 🔧 Skeleton | `services/elite_ai_service.py` — orquestación Kimi/Qwen/Gemini |
| VFX Hub (Seedance 2.0 style) | 🔧 Skeleton | `services/vfx_service.py` — style transfer, zoom, overlays |
| Viral Thumbnail Generator | ✅ Funcional | `services/thumbnail_service.py` — bold text sobre frame 1/3 |
| Social Distribution (TikTok/IG) | 🔧 Skeleton | `services/social_distribution_service.py` + `api/routes/social.py` |
| Multi-Angle Sync | ✅ Funcional | `services/multi_angle_service.py` + `utils/audio_analysis.py` (cross-correlation) |
| Image Generation (DALL-E 3 / SDXL) | ✅ Funcional | `services/image_gen_service.py` — genera B-roll por prompt |
| Campaign Manager | 🔧 Skeleton | `services/campaign_service.py` + `repositories/campaign_repository.py` |
| Audio Library (BGM por nicho) | ✅ Funcional | `services/audio_library_service.py` — mapeo nicho→música |
| Upload Batch endpoint | ✅ Funcional | `main.py POST /api/upload-batch` — hasta 20 vídeos |

### Bugs encontrados y reparados (sesión 2026-03-28)
- `video_service.py` — 30,197 null bytes (archivo corrompido). Reparado.
- `ai.py` — 25,607 null bytes (archivo corrompido). Reparado.
- `video_utils.py` — función `insert_broll_into_clip` truncada, faltaba `write_videofile()` + `except/finally`. Completada.
- `main.py` — función `upload_batch` truncada en línea 974. Completada.
- `image_gen_service.py` — `httpx` usado pero no importado. Añadido.
- `social.py` — router creado pero no registrado en `main_refactored.py`. Registrado en `/social`.

## PRÓXIMAS PRIORIDADES

| Prioridad | Feature | Descripción |
|-----------|---------|-------------|
| 🔴 Alta | Conectar thumbnail_service al pipeline | Usar `thumbnail_service.generate_viral_thumbnail()` al exportar clips |
| 🔴 Alta | Completar DB migration para campaign | Añadir tabla `campaigns` al schema |
| 🟡 Media | Completar Elite AI análisis | Conectar `EliteAIService.analyze_video_elite()` con el pipeline de `video_service` |
| 🟡 Media | Audio Library con archivos reales | Añadir BGM tracks royalty-free a `backend/assets/audio/bgm/` |
| 🟢 Baja | Social publish TikTok API real | Integrar TikTok Content Posting API v2 |

---
*Actualizado: 2026-03-28 | Ver también: `ANALISIS-COMPETITIVIDAD.md`*
