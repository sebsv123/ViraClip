# SupoClip — Análisis Profesional de Competitividad
### Diagnóstico técnico + Roadmap para superar a OpusClip, Quso AI y similares
*Generado: 2026-03-27 · Versión analizada: estado actual del repositorio*

---

## 1. BUGS CORREGIDOS EN ESTA SESIÓN

Los siguientes bugs críticos han sido corregidos antes de este documento:

| # | Bug | Archivo | Impacto |
|---|-----|---------|---------|
| 1 | `cv2.VideoWriter.fourcc` → `cv2.VideoWriter_fourcc` | `video_polish_service.py:261` | 🔴 TypeError al activar Eye Contact Correction |
| 2 | LLMService sin `try/except` → virality_score = 0 en todos los clips | `video_service.py:676-683` | 🔴 Todos los clips mostraban 0/100 de virality |
| 3 | `faster-whisper` usado en código pero no declarado en `pyproject.toml` | `pyproject.toml` | 🔴 ModuleNotFoundError en transcripción local |
| 4 | `pydantic-ai>=0.4.9` (API v0.x) pero código usa API v1.x | `pyproject.toml` | 🔴 `result.output` no existe en v0.x |
| 5 | `ImageGenService` (DALL-E) sin `try/except` | `video_service.py:786-800` | 🟠 Pipeline entero crashea si falta DALL-E key |
| 6 | Duración mínima 5s pero prompt pide 10-45s; sin máximo | `ai.py:647` | 🟠 Clips de 5s o de 60+ minutos pasaban validación |

---

## 2. BUGS PENDIENTES (no corregidos — requieren más análisis)

### ✅ TODOS LOS BUGS B-1 a B-7 CORREGIDOS EN SESIÓN 2026-03-27

| Bug | Descripción | Archivo(s) | Estado |
|-----|-------------|------------|--------|
| B-1 | worker-1 depende de `backend: healthy` → timeout en arranque frío | `docker-compose.yml` | ✅ Corregido: eliminada dependencia de backend; `start_period` backend → 120s |
| B-2 | `niche` nunca llega al render → emojis siempre "general" | `video_service.py` | ✅ Corregido: `detect_niche()` añadido a `segments_json` (ambas ramas dict/objeto) |
| B-3 | Face detection falla silenciosamente → clips mal encuadrados sin aviso | `video_service.py` | ✅ Corregido: `face_detected: bool` añadido al resultado de clip + warning en log |
| B-4 | Transcript cache por ruta → mismo vídeo re-transcrito si se descarga a path distinto | `video_utils.py` | ✅ Corregido: SHA256 de primer 1MB → `/tmp/supoclip_transcript_cache/{hash}.json` |
| B-5 | Karaoke usa `words_per_group = 3` hardcoded | `video_utils.py` | ✅ Corregido: usa `adaptive_word_groups()` (ya existía, ahora conectada) |
| B-6 | B-roll clips no registrados en ResourceGuard → posible memory leak | `video_utils.py` | ✅ Corregido: `guard` pasado a `apply_broll_to_clip_objects`, clips tracked |
| B-7 | Cleanup borra clips >48h sin verificar tareas activas | `utils/cleanup.py`, `workers/tasks.py` | ✅ Corregido: consulta DB para filenames de tareas queued/processing antes de borrar |

> *Todos los bugs anteriores (B-1 a B-7) han sido corregidos y los archivos verificados con `ast.parse()` sin errores de sintaxis.*

---

## 3. ANÁLISIS DE COMPETITIVIDAD

### ¿Qué hace OpusClip que SupoClip no hace igual de bien?

| Feature | OpusClip | Quso AI | SupoClip actual | Gap |
|---------|----------|---------|-----------------|-----|
| Selección de clips IA | ✅ Excelente | ✅ Bueno | ✅ Bueno (Gemini/GPT) | Pequeño |
| Calidad de subtítulos | ✅ Karaoke word-by-word | ✅ Karaoke | ✅ Implementado | Pequeño |
| Face tracking / reencuadre | ✅ Muy preciso | ✅ Bueno | 🟡 Funciona pero a veces shakycam | Medio |
| B-roll automático | ✅ Excelente | ✅ Bueno | 🟡 Pexels pero sin control fino | Medio |
| Eye contact correction | ✅ IA real | ❌ No | 🟡 MediaPipe implementado (nuevo) | Medio |
| Emojis animados en captions | ✅ Sí | ✅ Sí | 🟡 Overlays, no en texto | Medio |
| Música de fondo | ✅ Librería integrada | ✅ Sí | 🟡 Carpeta manual /music/ | Medio |
| Velocidad de render | ✅ ~2-5 min | ✅ ~3-7 min | 🟡 5-20 min (sin GPU) | **Grande** |
| Templates de caption | ✅ 10+ | ✅ 8+ | ✅ 8 templates | Pequeño |
| Scoring por plataforma | ✅ TikTok/IG/YT | ✅ Sí | ✅ Implementado (nuevo) | Cerrado |
| Auto-capítulos navegables | ✅ Sí | ✅ Sí | 🟡 Filtro básico (nuevo) | Medio |
| Exportación directa a RRSS | ✅ Sí | ✅ Sí | ❌ No | **Grande** |
| Panel analytics de clips | ✅ CTR, retención | ✅ Sí | ❌ No | **Grande** |
| Reencuadre multi-speaker | ✅ Sí | ✅ Sí | ❌ No (solo 1 cara) | **Grande** |
| Traducción + doblaje | ✅ 30+ idiomas | ✅ Sí | 🟡 Código existe, no funcional | **Grande** |
| Clip refinement por IA | ✅ Chat con IA | ✅ Sí | ❌ No | **Grande** |
| Virality score calibrado | ✅ 95%+ precisión | ✅ Sí | 🟡 Sin calibración real | Grande |
| Precio | $19-149/mes | $29-99/mes | 🟢 Gratis/local | **Ventaja** |
| Privacidad datos | ❌ Cloud obligatorio | ❌ Cloud | 🟢 100% local | **Ventaja** |
| Personalización técnica | ❌ Cerrado | ❌ Cerrado | 🟢 Open source | **Ventaja** |

---

## 4. CAUSAS REALES DE CLIPS DEFECTUOSOS

Basado en el análisis del código, estos son los problemas más frecuentes que producen clips de mala calidad:

### 4.1 Face Centering — Principal causa de clips mal encuadrados

**El problema en profundidad:**
```
MediaPipe → detecta cara OK
↓
EMA smoothing (α=0.12) → suaviza shakycam ✓
↓
create_dynamic_crop_clip → usa VideoClip(frame_function=...)
↓
PERO: Si hay múltiples caras o cara sale del frame → crop se desplaza
```

La función `detect_face_trajectory()` en `video_utils.py` solo devuelve puntos donde se detecta cara. Si hay frames sin cara (pausa, giro), la interpolación numpy crea movimientos bruscos entre el último punto conocido y el siguiente.

**Síntoma visual**: La cámara "salta" cuando el speaker se mueve o gira.

### 4.2 Subtítulos — Timing incorrecto con faster-whisper

El código mezcla dos fuentes de transcripción:
- **AssemblyAI**: devuelve timestamps en milisegundos → correctos
- **faster-whisper local**: devuelve timestamps en segundos → correctos

PERO: cuando se usa faster-whisper, los words se guardan como objetos `Word` de faster-whisper, no como dicts. El código en `cache_transcript_data()` intenta convertirlos pero puede fallar silenciosamente, resultando en subtítulos sin timing o desincronizados.

### 4.3 Virality Score = 0 (corregido)

El `LLMService.get_virality_analysis()` llama a un modelo Llama local que la mayoría de usuarios no tiene configurado. Cuando falla (lo cual es siempre en instalaciones estándar), **todos los clips quedaban con virality_score: 0** porque el código usaba `v_info.get("virality_score", 0)` en vez de los scores de la IA principal. **YA CORREGIDO**.

### 4.4 Clips sin audio (caso centered_)

Cuando se activa `auto_center_face`, el proceso usa `cv2.VideoWriter` que no soporta audio. El audio se pierde si no se re-mezcla con ffmpeg correctamente. La función `auto_center_face()` en `video_polish_service.py` tiene lógica para re-mezclar pero solo funciona si el archivo original tiene audio y ffmpeg está en el PATH del contenedor.

---

## 5. ROADMAP REALISTA PARA IGUALAR/SUPERAR A LA COMPETENCIA

### FASE 1 — Estabilización de calidad (1-2 semanas)
*Objetivo: Que cada clip generado sea de calidad profesional consistente*

**P1.1: Face tracking mejorado** *(2-3 días)*
- Mejorar `detect_face_trajectory()`: cuando no hay cara detectada, mantener el último crop conocido en lugar de interpolar
- Añadir padding dinámico: si la cara está en el 20% superior, bajar el crop para incluir hombros
- Resultado esperado: eliminación de 80% de los saltos de cámara

**P1.2: Faster-whisper pipeline limpio** *(1 día)*
- Verificar que `cache_transcript_data()` convierte correctamente los Word objects de faster-whisper a dicts con claves `{text, start, end, confidence}`
- Añadir test de integración que procese 30s de audio y verifique el formato del cache

**P1.3: Subtítulos posicionados correctamente** *(1 día)*
- El 75% vertical funciona bien en 9:16, pero con `split_screen` los subtítulos se superponen al contenido de abajo
- Ajustar `position_y` dinámicamente según `split_screen` y `hook_title` activos

**P1.4: Niche propagado al render** *(2 horas)*
- Añadir `"niche": detect_niche(segment.get("text",""))` en `segments_json` en `video_service.py`
- Ahora los emojis de overlay usarán el nicho correcto en lugar de "general"

---

### FASE 2 — Features diferenciadoras (2-4 semanas)
*Objetivo: Tener features que la competencia no tiene o hace peor*

**P2.1: Render multi-proceso real** *(3-4 días)*
El cuello de botella actual es que los 3 workers renderizan secuencialmente. Con 3 workers en paralelo:
```python
# En task_service.py: renderizar clips en paralelo entre workers
# Actualmente: loop secuencial
# Solución: usar asyncio.gather() con semaphore por worker
```
Esto podría reducir el tiempo de 15 min → 5 min para un video de 30 min.

**P2.2: Biblioteca de música royalty-free integrada** *(2 días)*
- Integrar con Pixabay API (gratuita) o Free Music Archive
- Categorizar música por mood: energética, emotional, motivational
- Auto-seleccionar mood según `niche` del clip
- Añadir UI para previsualizar y cambiar track

**P2.3: Template de caption animado — "Word Pop"** *(2-3 días)*
El más viral actualmente en TikTok (2025): cada palabra aparece con un micro-bounce y color dinámico por énfasis. Es diferente al karaoke (que destaca la palabra actual) — aquí CADA palabra tiene su propia animación de entrada.

**P2.4: Multi-speaker detection** *(3-5 días)*
- Usar PyAnnote Audio para diarización de hablantes
- Cuando hay 2+ hablantes, alternar el crop entre sus posiciones
- Esto cubre podcasts, entrevistas — el caso de uso más común para clips virales

**P2.5: Hook Score calibrado por datos reales** *(5-7 días)*
Crear un dataset de 100 clips virales conocidos (>1M views) y 100 clips normales, extraer sus scores de la IA, y calibrar los umbrales de virality para que coincidan con el rendimiento real. Actualmente el scoring es teórico, no empírico.

---

### FASE 3 — Paridad con competidores top (1-2 meses)
*Objetivo: Usuario elige SupoClip porque es objetivamente mejor en algo*

**P3.1: Chat de refinamiento con IA**
"Este clip empieza muy tarde, recórtalo" → IA ajusta timestamps y re-renderiza

**P3.2: Exportación directa a plataformas**
- TikTok API (content posting API)
- Instagram Graph API
- YouTube Data API
- Buffer/Hootsuite para programación

**P3.3: Analytics de rendimiento**
- Integración con TikTok/IG Analytics API
- Mostrar qué clips funcionaron mejor
- Feedback loop para mejorar el scoring de virality

**P3.4: Traducción + doblaje funcional**
El código de `translation_service.py` existe pero usa modelos que crashean. Opciones:
- ElevenLabs para doblaje de voz (API disponible, 10k chars gratis/mes)
- Whisper + NLLB-200 para traducción
- Burn subtítulos en el idioma target como mínimo viable

**P3.5: Modo "Clip Masivo"**
- Procesar 10 vídeos en una sola tarea (batch processing)
- Cola con prioridad por virality score esperado
- Notificación (email/webhook) cuando terminan

---

## 6. VENTAJAS COMPETITIVAS QUE DEBES EXPLOTAR

SupoClip tiene ventajas reales que los competidores **no pueden replicar**:

### 6.1 Privacidad total
OpusClip y Quso procesan tus vídeos en sus servidores. SupoClip corre 100% local. Para creadores de contenido B2B, conferencias corporativas, contenido sensible — esto es un diferenciador enorme.

### 6.2 Sin límite de procesamiento
La competencia cobra por minuto de vídeo procesado. SupoClip: procesa 10 horas de contenido al día si quieres, sin coste adicional.

### 6.3 Personalización técnica total
Puedes añadir tu propio prompt de IA, tus propias fuentes de B-roll, tus propios templates de caption. La competencia es una caja negra.

### 6.4 Integración con modelos propios
Si entrenas un modelo fine-tuned para tu nicho específico (finanzas, fitness, gaming), puedes integrarlo directamente. La competencia usa modelos genéricos.

---

## 7. ACCIONES INMEDIATAS (esta semana)

En orden de impacto/esfuerzo:

1. **Reiniciar workers** para cargar los 5 bugs corregidos en esta sesión:
   ```bash
   docker-compose restart worker worker-2 worker-3
   ```

2. **Actualizar dependencias** para incluir faster-whisper y pydantic-ai correctos:
   ```bash
   cd backend && uv sync
   # En Docker:
   docker-compose up -d --build
   ```

3. **Probar un clip end-to-end** y revisar los logs del worker:
   ```bash
   docker-compose logs -f worker | grep -E "ERROR|WARNING|✅|❌|virality"
   ```

4. **Añadir música royalty-free** a `backend/music/` — cualquier .mp3 libre de derechos. Se mezcla automáticamente al 12% de volumen.

5. **Configurar la carpeta de B-roll**: si tienes vídeos satisfying/motivational locales, ponlos en la carpeta que usa `BrollService` o confía en Pexels con `PEXELS_API_KEY`.

---

## 8. MÉTRICAS DE CALIDAD A MONITORIZAR

Para saber si estás mejorando objetivamente, mide estas métricas con cada cambio:

| Métrica | Medición | Objetivo |
|---------|----------|---------|
| Clips exitosos / total | Logs del worker | >95% |
| Tiempo medio de render | Logs per-clip timing | <3 min por clip |
| Face detected % | Log `face_detected` | >85% de clips |
| Virality score medio | BD `generated_clips` | >60/100 |
| Subtítulos sincronizados | Test manual 5 clips | 100% |
| Clips con audio correcto | Test manual | 100% |

---

*Este documento debe actualizarse cada vez que se resuelva un bug o se añada una feature importante.*
