# Informe de Test End-to-End — ViraClip
**Fecha:** 2026-03-29
**Video probado:** "But what is a neural network?" — 3Blue1Brown (19 min)
**URL:** https://www.youtube.com/watch?v=aircAruvnKk
**Tarea:** `d2650c65-24a6-4de5-8672-288d24d4858f`

---

## ✅ Resultado Global

El pipeline completó con éxito tras corregir **11 bugs** en dos sesiones. Se generaron **4 clips únicos** (23–34s cada uno) en ~14 minutos de render. La selección de momentos del video es buena para contenido educativo. Sin embargo, hay múltiples puntos débiles graves que detallar.

---

## 🎬 Clips Generados

| # | Timestamp | Duración | Texto (preview) |
|---|-----------|----------|-----------------|
| 1 | 15:39–16:02 | 23s | "The entire network is just a function, one that takes in 784 numbers..." |
| 2 | 00:14–00:43 | 29s | "I want you to take a moment to appreciate how crazy it is that brains can do this..." |
| 3 | 05:49–06:23 | 34s | "When you or I recognize digits, we piece together various components. A 9 has..." |
| 4 | 02:52–03:24 | 32s | "Right now, when I say neuron, all I want you to think about is a thing that holds..." |

**Valoración de los momentos seleccionados:** Bastante buena. Los 4 clips capturan los conceptos más explicativos del video (la esencia de la red neuronal, el problema de reconocimiento de dígitos, la analogía del neurón). Para contenido educativo de divulgación son selecciones lógicas y potencialmente virales en YouTube Shorts o LinkedIn.

**Comparado con OpusClip/Quso:** Los competidores con 3B1B suelen capturar también los momentos de animación impactante (e.g. la visualización de la red 784→16→16→10). ViraClip no tiene visión real del video (el módulo multimodal está desconectado), así que elige solo por transcripción. Es una desventaja real.

---

## 🐛 Bugs Corregidos Durante el Test

### Sesión anterior
1. `process_video_complete()` no aceptaba `target_platform` ni `url_secondary` → **FixedTypeError al iniciar cualquier tarea**
2. `resume_task()`, `cancel_task()`, `export_clip()`, `list_dead_letter_tasks()` usaban `config` sin definirlo → **NameError en 4 endpoints**
3. pydantic-ai renombró `.data` → `.output` → **AttributeError bloqueaba el análisis AI en `ai.py` y `elite_ai_service.py`**
4. `generate_creative_plan()` no recibía `video_path` → **TypeError en paso EliteAI**
5. `create_single_clip()` no aceptaba `camera_plan`, `sync_offset`, `secondary_video_path` → **TypeError al renderizar clips**
6. `librosa.load()` cargaba el audio completo de 19 min (~100 MB) → **Bloqueo de 5+ min del worker**

### Esta sesión
7. `_extract_key_frames()` extraía 3 frames como base64 que nunca se pasaban al agente → **Trabajo desperdiciado (CPU + RAM)**
8. Transcript pasado completo al prompt de EliteAI sin límite → **Añadido truncado a 8000 chars como safety net**
9. Si EliteAI falla la validación Pydantic, crasheaba la tarea entera → **Añadido fallback con EliteCreativePlan vacío**
10. Sin caché de transcript en disco → **Cada retry re-transcribía el video completo con faster-whisper**

---

## ⚠️ Bugs Activos (No Corregidos Aún)

### 🔴 Crítico: Virality Scores = 0 en todos los clips

**Causa:** El servicio Ollama (`llama3.1:8b`) está offline o no accesible. El `LLMService` cae al fallback, que devuelve solo `virality_score: 50` pero NO devuelve `hook_score`, `engagement_score`, `value_score`, `shareability_score`. Estos 4 campos nunca se setean en el dict del segmento.

**Impacto:** La UI muestra todos los scores en 0. El sistema de ranking de clips no funciona. No hay `hook_type`, `social_title`, ni `suggested_hashtags`.

**Fix recomendado:**
```python
# En LLMService._get_fallback_analysis(), distribuir virality_score en 4 componentes:
"hook_score": 12,        # ~50/4
"engagement_score": 12,
"value_score": 13,
"shareability_score": 13,
```
Y en `video_service.py`, mapear también estos campos desde `v_info`:
```python
"hook_score": v_info.get("hook_score", 0),
"engagement_score": v_info.get("engagement_score", 0),
"value_score": v_info.get("value_score", 0),
"shareability_score": v_info.get("shareability_score", 0),
```

### 🔴 Crítico: Clips duplicados (8 = 4×2) por retry sin limpieza

**Causa:** `process_task()` no borra los clips existentes al empezar. Si ARQ reintenta la tarea (por crash o restart del worker), se crean clips nuevos encima de los antiguos.

**Fix:**
```python
# Al inicio de process_task(), antes de crear clips:
await self.clip_repo.delete_clips_by_task(self.db, task_id)
```

### 🟡 Importante: face_detected siempre null

**Causa:** `create_single_clip()` no devuelve `face_detected` en el dict de retorno. La detección de cara (MediaPipe/OpenCV) se usa internamente para el crop vertical, pero el resultado nunca se expone.

**Fix:** Añadir `"face_detected": <bool>` al dict retornado en `create_single_clip()`.

### 🟡 Importante: social_title / suggested_hashtags siempre null

**Causa:** `create_single_clip()` no mapea `suggested_title` del segmento a `social_title` en el dict de retorno. El LLM (cuando funciona) sí devuelve `suggested_title`, pero se pierde antes de llegar a la DB.

**Fix:** En el return dict de `create_single_clip()`:
```python
"social_title": segment.get("suggested_title"),
"suggested_hashtags": segment.get("hashtags"),
```

### 🟡 Importante: A/B variants son exact duplicates cuando Ollama offline

**Causa:** El A/B variant (`generate_ab_variants=True`) usa `create_ab_variant()` que cambia el caption template. Si el fallback de virality scoring no detecta diferencias de score, ambas versiones son idénticas.

### 🟠 Performance: 4 renders en paralelo congela el sistema

**Causa:** `asyncio.gather()` lanza 4 threads de MoviePy en paralelo. En un CPU de consumo sin GPU, esto satura el 100% de CPU durante 10–20 minutos, congelando el navegador y haciendo inutilizable el equipo.

**Fix recomendado:** Limitar concurrencia con semáforo:
```python
_render_sem = asyncio.Semaphore(2)  # máx 2 en paralelo, no 4
```
Ya existe `_render_sem` en el código pero revisar su valor actual.

### 🟠 Performance: Render de 19 min → 14 min de CPU

**Total time breakdown (estimado):**
- Download: ~2 min
- Transcripción (faster-whisper local): ~3 min
- AI analysis (Gemini): ~1 min
- EliteAI (Gemini): ~1 min
- Virality scoring (Ollama): ~0s (fallback instantáneo)
- Render 4 clips: **~14 min** ← dominante

Para un video de 19 min, el competidor OpusClip tarda ~3-5 min total (con GPU cloud). ViraClip en CPU local tarda ~21 min. Con GPU (RTX 3070+), el render debería bajar a ~2-4 min.

---

## 📊 Comparativa con Competidores

| Feature | ViraClip | OpusClip | SupoClip (original) | Quso AI |
|---------|----------|----------|---------------------|---------|
| Selección de clips | ✅ Buena (texto) | ✅ Excelente (vision+texto) | ✅ Buena | ✅ Buena |
| Virality scoring | ❌ Roto (0s) | ✅ Funcional | ✅ Funcional | ✅ Funcional |
| Subtítulos animados | ✅ Sí | ✅ Sí | ✅ Sí | ✅ Sí |
| Face detection / crop | ✅ Sí (activo en render) | ✅ Sí | ✅ Sí | ✅ Sí |
| Social copy (título/hashtags) | ❌ Null (bug) | ✅ Funcional | ❌ Básico | ✅ Funcional |
| Velocidad (CPU) | ❌ ~21 min | ✅ ~3-5 min (cloud GPU) | ❌ Lento | ✅ Cloud |
| Visual analysis (multimodal) | ❌ Desconectado | ✅ Sí | ❌ No | ✅ Limitado |
| A/B testing | ⚠️ Implementado pero roto | ❌ No | ❌ No | ❌ No |
| Local/privado | ✅ 100% local | ❌ Cloud | ❌ Cloud | ❌ Cloud |
| Coste por clip | ✅ €0 (local) | ❌ $$/créditos | ❌ $$/créditos | ❌ $$/créditos |
| Control total del código | ✅ AGPL | ❌ SaaS cerrado | ✅ Open source | ❌ SaaS |

---

## 🏗️ Próximos Pasos Prioritarios

1. **[CRÍTICO]** Fix virality scores: mapear hook/engagement/value/shareability en el pipeline
2. **[CRÍTICO]** Fix duplicados: limpiar clips existentes al inicio de `process_task()`
3. **[IMPORTANTE]** Fix social_title: mapear `suggested_title` al return dict de `create_single_clip()`
4. **[IMPORTANTE]** Verificar semáforo de renders paralelos (limitar a max 2 en CPU)
5. **[IMPORTANTE]** Activar/verificar Ollama: sin `llama3.1:8b` todo el scoring es fallback genérico
6. **[FUTURO]** Reconectar análisis visual multimodal (pasar frames al director_agent con pydantic-ai UserContent)
7. **[FUTURO]** Caché de análisis AI: si el mismo video se reprocesa, reutilizar los segments del primer run
8. **[FUTURO]** GPU rendering: con CUDA habilitado en Docker el render de 14 min → <3 min

---

## 📁 Dónde Ver los Clips

Los clips generados están en: `C:\Users\Sebitas\ViraClip-Exports\`
También accesibles desde la UI en `http://localhost:3000`
