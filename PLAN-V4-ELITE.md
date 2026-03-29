# ViraClip V4 — Plan Elite de Evolución
### Análisis técnico real + Roadmap por fases
*Creado: 2026-03-28 | Actualizado: 2026-03-28 — Estrategia 100% local, sin APIs de pago*

---

## EVALUACIÓN DE VIABILIDAD TÉCNICA REAL

Antes de planificar, analizamos cada tecnología propuesta con criterio de producción local (Windows + Docker + FastAPI).

> ⚡ **Decisión de arquitectura:** Máxima potencia local. Sin APIs de pago para el pipeline de IA visual.
> La visión multimodal usa **Qwen3-VL-8B via Ollama** — gratis, local, GPU-accelerated.

| Tecnología | Viabilidad | Bloqueador | Veredicto |
|-----------|-----------|-----------|---------|
| **Kimi-K2.5 API** | ❌ Descartado | API de pago | **NO — usar Qwen3-VL local** |
| **Kimi-K2.5 local (GGUF)** | ❌ Imposible | ~621GB VRAM Q4_K_M | **NO viable** — 1T params MoE |
| **Qwen3-VL-8B local** | ✅ Alta | ~6-8GB VRAM Q4_K_M | **✅ IMPLEMENTADO — Ollama** |
| **SpaceTimeDB 2.0** | 🟡 Media | Python SDK deprecated | **SOLO frontend WebSocket** (ver abajo) |
| **ACE Studio Video Composer** | ❌ Baja | Sin API, solo desktop | **DESCARTAR** → usar ACE-Step 1.5 |
| **Seedance 2.0 (Dreamina)** | ❌ Baja | Propietario, sin API | **DESCARTAR** → aproximar con ComfyUI |
| **Kolors Virtual Try-On** | 🟡 Media | +24GB VRAM, solo imágenes | **OPCIONAL** — nicho muy específico |
| **Unsloth + Google Colab** | 🟡 Media | No apto para producción | **SOLO fine-tuning offline** |
| **PySceneDetect (open-source)** | ✅ Alta | Ninguno | **INTEGRAR ahora** |
| **ACE-Step 1.5 (open-source)** | ✅ Alta | ~8GB VRAM | **INTEGRAR — generación musical** |

---

## ANÁLISIS TÉCNICO DE CADA TECNOLOGÍA

### 1. Qwen3-VL-8B via Ollama — ✅ IMPLEMENTADO (visión local)

**Por qué Qwen3-VL-8B y no Kimi-K2.5:**
- Kimi-K2.5 tiene 1.04T parámetros totales (MoE). En Q4_K_M necesitaría ~621GB VRAM — imposible en consumer hardware.
- Qwen3-VL-8B cuantizado a Q4_K_M = **6-8GB VRAM** — funciona en RTX 3080, 4070, 4080.
- Qwen3-VL-8B es **completamente gratis**, sin API key, sin límite de llamadas.
- Soporte nativo en Ollama: `ollama pull qwen3-vl:8b`

**Arquitectura implementada:**
```
Clip renderizado
    → extract_representative_frames() [ffmpeg, 8 frames]
    → Ollama /api/generate [Qwen3-VL-8B multimodal]
    → VisionScore { visual_hook, facial_energy, subtitle_readability,
                    visual_virality, edit_rhythm, recommendations }
    → blend_with_text_score() [70% texto + 30% visual]
    → final_virality_score
```

**Ficheros implementados:**
- `backend/src/services/vision_service.py` — servicio completo con fallback graceful
- `backend/src/utils/scene_analysis.py` — PySceneDetect para ritmo y loop detection
- `docker-compose.yml` — servicio `ollama` con GPU passthrough y volumen persistente
- Config: `OLLAMA_VISION_MODEL=qwen3-vl:8b`, `VISION_ANALYSIS_ENABLED=true`

**Para activarlo (primera vez):**
```bash
# El servicio Ollama arranca automáticamente con docker-compose up
# El backend/worker descarga el modelo en segundo plano al iniciar:
docker-compose logs -f ollama    # monitorear descarga (~5GB, primera vez)
# O descargar manualmente:
docker exec viraclip-ollama ollama pull qwen3-vl:8b
```

**Opciones según VRAM disponible:**
| Modelo | VRAM | Calidad | Uso |
|--------|------|---------|-----|
| `qwen3-vl:8b` | ~8GB | ⭐⭐⭐⭐⭐ | **Recomendado (RTX 3080+)** |
| `qwen3-vl:4b` | ~5GB | ⭐⭐⭐⭐ | RTX 3060, 4060 |
| `moondream:v2` | ~2GB | ⭐⭐⭐ | CPU fallback |

---

### 2. SpaceTimeDB — SOLO para WebSocket Frontend

**El problema real:** El SDK de Python de SpaceTimeDB está en modo mantenimiento. No hay soporte oficial para módulos Python. Necesitarías escribir los módulos en Rust o C#.

**Lo que SÍ puedes aprovechar:** El protocolo WebSocket v2 para sincronizar estado entre pestañas del frontend sin polling.

**Arquitectura propuesta (Rust Proxy opcional):**
```
Backend Python (FastAPI)
    → Redis pub/sub (ya existe)
    → [Rust WebSocket Bridge] → SpaceTimeDB
    → Frontend TypeScript SDK → multi-tab sync
```

**Alternativa MÁS SIMPLE que logra lo mismo:**
```
FastAPI WebSocket nativo (/ws/tasks/{id}/progress)
    → Reemplaza SSE existente
    → Multi-tab sync vía BroadcastChannel API del navegador
    → CERO infraestructura extra, CERO Rust
```

**Veredicto:** Implementar primero WebSocket nativo de FastAPI. SpaceTimeDB como fase futura experimental.

---

### 3. ACE-Step 1.5 — SÍ, en lugar de ACE Studio

ACE Studio Video Composer es solo desktop, sin API. **ACE-Step 1.5** es open-source y puede generar música por:
- Prompt de texto (describe el mood)
- Tags estructurados (genre, tempo, instruments)
- Referencia de audio (estilo de otra canción)

**Cómo integrarlo con escenas:**
```
Video → PySceneDetect → escenas + duración + intensidad de movimiento
     → Audio Library Service (selección por nicho)
     → ACE-Step 1.5 (generación si no hay track disponible)
     → ffmpeg mix (ducking durante speech)
```

**Instalación:**
```bash
pip install ace-step  # ~8GB VRAM, T4 de Colab funciona
```

---

### 4. Qwen3-VL — ✅ IMPLEMENTADO como motor visual principal

Qwen3-VL-8B a Q4_K_M (6-8GB VRAM) ya está completamente integrado. Ver sección 1 para detalles completos.

**Variables de entorno disponibles:**
```bash
OLLAMA_BASE_URL=http://ollama:11434    # automático en Docker
OLLAMA_VISION_MODEL=qwen3-vl:8b       # modelo por defecto
VISION_ANALYSIS_ENABLED=true          # activar/desactivar scoring visual
```

La ventaja sobre cualquier API: **gratis, sin latencia de red, sin límite de tokens por día, privado (los frames no salen del servidor)**.

---

### 5. Seedance 2.0 — DESCARTAR, aproximar con open-source

Seedance 2.0 es propietario de ByteDance, sin API pública. Lo que podemos **aprender** de él e implementar:

| Concepto de Seedance | Implementación open-source |
|--------------------|---------------------------|
| Style guiding multi-referencia | ComfyUI + ControlNet (IP-Adapter) |
| Consistencia de movimiento entre clips | RAFT optical flow (ya integrado via cv2) |
| Audio-visual sync | librosa beat_track() + ffmpeg concat |
| Loop detection para TikTok | PySceneDetect AdaptiveDetector |

---

### 6. Kolors Virtual Try-On — OPCIONAL, nicho específico

Útil principalmente para contenido de moda/lifestyle. Requiere 24GB+ VRAM. **Posponer** hasta que haya demanda específica.

---

### 7. Unsloth + Colab — SOLO fine-tuning offline

**Caso de uso válido:** Usar Colab (T4 gratis) para fine-tunear el modelo de scoring de viralidad con datos reales de ViraClip. El notebook `scripts/fine_tune_virality.py` ya existe.

**Flujo:**
```
ViraClip genera clips → usuario califica viralidad (1-5 estrellas)
→ Dataset exportado → Fine-tuning en Colab con Unsloth
→ Modelo GGUF descargado → Ollama local sirve nuevo modelo
```

**No usar Colab para inferencia en producción** — latencia variable, cuotas de GPU, sesiones que expiran.

---

## PLAN DE IMPLEMENTACIÓN POR FASES

### FASE 0 — Foundation (Esta semana) ⚡
*Conectar las piezas ya construidas pero desconectadas*

**0.1 — Conectar thumbnail_service al pipeline de exportación**
```python
# En video_service.py create_single_clip(), después del render:
from .thumbnail_service import generate_viral_thumbnail

thumbnail_path = output_path.parent / f"{output_path.stem}_thumb.jpg"
generate_viral_thumbnail(
    video_path=str(output_path),
    output_path=str(thumbnail_path),
    text=segment.get("hook_type", "WATCH THIS").upper()
)
```

**0.2 — Migración DB campaigns**
```sql
-- backend/src/migrations/sql/20260328_0001_campaigns.sql
CREATE TABLE IF NOT EXISTS campaigns (
    id              VARCHAR(36) PRIMARY KEY,
    user_id         VARCHAR(36) NOT NULL,
    name            VARCHAR(200) NOT NULL,
    description     TEXT,
    platform        VARCHAR(50) DEFAULT 'all',
    status          VARCHAR(50) DEFAULT 'active',
    task_ids        TEXT[],
    ab_test_config  JSONB,
    performance     JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_campaigns_user_id ON campaigns (user_id);
```

**0.3 — PySceneDetect para loop detection y score de ritmo visual**
```python
# backend/src/utils/scene_analysis.py
from scenedetect import detect, ContentDetector, AdaptiveDetector

def analyze_clip_rhythm(video_path: Path) -> dict:
    """
    Detecta ritmo visual: nº de escenas, duración media, variación.
    Clips con 3-8 cortes en 30s son más virales (ritmo óptimo).
    """
    scenes = detect(str(video_path), AdaptiveDetector())
    num_scenes = len(scenes)
    durations = [(end - start).get_seconds() for start, end in scenes]

    avg_duration = sum(durations) / len(durations) if durations else 0
    rhythm_score = min(100, max(0,
        100 - abs(avg_duration - 3.0) * 15  # óptimo: 3s por escena
    ))

    return {
        "scene_count": num_scenes,
        "avg_scene_duration": round(avg_duration, 2),
        "rhythm_score": int(rhythm_score),
        "edit_pace": "fast" if avg_duration < 2 else "medium" if avg_duration < 5 else "slow"
    }
```

**Añadir a pyproject.toml:**
```toml
"scenedetect>=0.6.5",
"httpx>=0.27.0",
```

---

### FASE 1 — Vision Pipeline Local ✅ COMPLETADO
*Análisis visual real de clips via Qwen3-VL-8B, 100% local, sin APIs de pago*

**Estado:** Implementado en esta sesión. Todos los ficheros creados y conectados.

**Lo que hace:**
- `vision_service.py` — Qwen3-VL-8B via Ollama analiza 8 frames por clip
- `scene_analysis.py` — PySceneDetect detecta ritmo de edición y loop potential
- `video_service.py` — blend 70% texto + 30% visual en `create_single_clip()`
- `docker-compose.yml` — servicio `ollama` con GPU passthrough y volumen persistente
- `main_refactored.py` — descarga del modelo en background al iniciar (no bloquea)

**Para activar (primera vez):**
```bash
docker-compose up -d --build    # rebuild con nuevas dependencias
docker-compose logs -f ollama   # monitorear descarga de qwen3-vl:8b (~5GB)
```

**Fallback graceful:** Si Ollama no está disponible, el pipeline continúa con score textual únicamente.

---

### FASE 2 — Audio Intelligence (2-3 semanas) 🎵
*BGM generativo + sincronización musical*

**2.0 — Prerequisito ya cumplido:**
- ✅ Ollama + Qwen3-VL funcionando
- ✅ PySceneDetect integrado para tiempos de corte

**2.1 — ACE-Step 1.5 para BGM generativo**
- (antes era "Añadir Qwen3-VL como backend" — ya completado)

**2.2 — ACE-Step 1.5 para música generativa**
```python
# backend/src/services/music_gen_service.py
from ace_step import ACEStepPipeline

class MusicGenService:
    """Genera música de fondo adaptada al mood del clip usando ACE-Step 1.5"""

    def __init__(self):
        self.pipeline = None  # lazy load

    async def generate_for_clip(
        self,
        mood: str,          # "hype", "suspense", "inspiring", "lo-fi"
        duration: float,    # duración del clip en segundos
        bpm_hint: int = 120 # BPM deseado
    ) -> Path:
        """Genera audio BGM de duración exacta para el clip."""
        if self.pipeline is None:
            from ace_step import ACEStepPipeline
            self.pipeline = ACEStepPipeline.from_pretrained("ACE-Step/ACE-Step-v1-3.5B")

        prompt = f"{mood} background music, {bpm_hint} bpm, no vocals, loop-ready, {duration:.0f} seconds"
        audio = self.pipeline(prompt=prompt, duration=duration)

        output = Path(f"/tmp/bgm_{hash(prompt)}.wav")
        audio.save(str(output))
        return output
```

**2.3 — PySceneDetect → sincronización musical**
```
Clip → detect scene cuts → extraer tiempos de corte
     → librosa.beat.beat_track(music) → extraer tiempos de beat
     → Ajustar cortes para coincidir con beats del BGM (±100ms)
     → ffmpeg concat con timing ajustado
```

---

### FASE 3 — WebSocket Real-Time (3-4 semanas) ⚡
*Reemplazar SSE con WebSockets nativos de FastAPI*

**Por qué WebSocket > SpaceTimeDB ahora:**
- FastAPI tiene soporte WebSocket nativo sin dependencias extra
- Multi-tab sync con `BroadcastChannel` API del navegador (nativo)
- SpaceTimeDB se mantiene como "bonus experimental" para el futuro
- Cero infraestructura nueva

**3.1 — Endpoint WebSocket de progreso**
```python
# backend/src/api/routes/tasks.py — añadir:
from fastapi import WebSocket, WebSocketDisconnect

@router.websocket("/{task_id}/ws")
async def task_progress_websocket(
    task_id: str,
    websocket: WebSocket,
    db: AsyncSession = Depends(get_db)
):
    """WebSocket alternativo a SSE para progreso en tiempo real."""
    await websocket.accept()

    redis_client = await get_redis()
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(f"task_progress:{task_id}")

    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"])
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe()
```

**3.2 — Frontend: BroadcastChannel para multi-tab**
```typescript
// frontend/src/lib/task-progress.ts
export class TaskProgressManager {
    private ws: WebSocket | null = null;
    private channel: BroadcastChannel;

    constructor(taskId: string) {
        this.channel = new BroadcastChannel(`task-${taskId}`);
        this.connect(taskId);
    }

    private connect(taskId: string) {
        const wsUrl = `ws://localhost:8000/tasks/${taskId}/ws`;
        this.ws = new WebSocket(wsUrl);

        this.ws.onmessage = (event) => {
            const progress = JSON.parse(event.data);
            // Broadcast a TODAS las pestañas del mismo task
            this.channel.postMessage(progress);
        };
    }
}
```

**3.3 — SpaceTimeDB (experimental futuro)**
Si en el futuro quieres SpaceTimeDB: el Rust proxy sería un proceso separado que:
- Escucha Redis pub/sub
- Republica eventos a SpaceTimeDB via su SDK de Rust
- El frontend TypeScript usa el SDK de SpaceTimeDB
- Esto agrega latencia mínima pero habilita sync de estado muy sofisticado

---

### FASE 4 — Elite AI Mode (1-2 meses) 👑
*EliteAIService conectado al pipeline real*

**4.1 — Modo de análisis: Standard vs Elite**
```python
# En config.py:
ANALYSIS_MODE: Literal["standard", "elite"] = "standard"
# "elite" activa: Qwen3-VL local + ACE-Step + scene analysis + fine-tuned scoring
```

**4.2 — Pipeline Elite completo por clip:**
```
Transcripción AssemblyAI
    ↓
PySceneDetect → ritmo visual + edit pace score     ← ✅ ya integrado
    ↓
Qwen3-VL-8B (Ollama local) → análisis visual       ← ✅ ya integrado
    ↓
EliteAIService.plan_clip() → VFXInstruction + AudioInstruction
    ↓
audio_library_service / MusicGenService → BGM generado o seleccionado
    ↓
video_service.create_single_clip() → render con todo aplicado
    ↓
thumbnail_service.generate_viral_thumbnail() → thumbnail automático
    ↓
social_distribution_service.get_viral_hashtags() → hashtags trending
```

**4.3 — CommunityManagerAgent (respuestas a comentarios)**
Usa EliteAIService con contexto del clip para generar respuestas consistentes con el "brand DNA". El endpoint ya existe (`POST /social/reply`), solo falta implementar la lógica del agente.

---

### FASE 5 — Fine-Tuning & Viral Intelligence (2-3 meses) 🎓
*Feedback loop real: tus clips mejoran con el tiempo*

**5.1 — Rating system en frontend**
- Añadir ⭐ rating (1-5) en cada clip card del task
- Guardar en DB: `generated_clips.user_rating`
- Exportar dataset: `scripts/collect_dataset.py` (ya existe)

**5.2 — Fine-tuning en Colab con Unsloth**
```python
# scripts/fine_tune_virality.py (ya existe, completar):
from unsloth import FastLanguageModel

# Dataset: clips con rating + virality_score real
# Fine-tune: ajustar pesos de scoring de viralidad
# Output: modelo GGUF → descargar → Ollama local
```

**5.3 — A/B Performance Analytics**
- `campaign_service.py` ya tiene la estructura
- Añadir tabla `clip_performance` con: views, likes, shares (simulados o reales vía API)
- Feed de vuelta al scoring: si un clip con virality=72 consiguió 500K views, subir su peso

---

## DESCARTES Y REEMPLAZOS DEFINITIVOS

| Descartado | Por qué | Reemplazado por |
|-----------|---------|-----------------|
| **ACE Studio Video Composer** | Sin API pública, solo desktop | ACE-Step 1.5 (open-source, pip install) |
| **Seedance 2.0 directo** | Propietario ByteDance, sin API | ComfyUI + IP-Adapter + ControlNet para style |
| **Kolors Virtual Try-On (ahora)** | 24GB+ VRAM, nicho muy específico | Posponer hasta versión mobile/lite |
| **Google Colab para producción** | Latencia variable, sesiones expiran | Solo para fine-tuning offline |
| **SpaceTimeDB Python módulos** | SDK deprecated | WebSocket nativo FastAPI + BroadcastChannel |

---

## ARQUITECTURA V4 FINAL

```
┌─────────────────────────────────────────────────────────────┐
│                    ViraClip V4 Stack                        │
├─────────────────────────────────────────────────────────────┤
│ FRONTEND (Next.js 15)                                       │
│   WebSocket ← BroadcastChannel (multi-tab sync nativo)      │
│   AI Refine Panel | Batch URLs | A/B Badge | Social Copy    │
├─────────────────────────────────────────────────────────────┤
│ BACKEND (FastAPI)                                           │
│   Standard Mode: AssemblyAI + Gemini/Claude/OpenAI          │
│   Elite Mode:   + Qwen3-VL-8B local (Ollama) ✅             │
│                 + PySceneDetect ✅ + ACE-Step BGM (fase 2)  │
├─────────────────────────────────────────────────────────────┤
│ WORKERS (ARQ × 3)                                           │
│   Render paralelo | Silence trim | Multi-speaker detect     │
│   A/B variant | Thumbnail generation | Social hashtags      │
├─────────────────────────────────────────────────────────────┤
│ INFRAESTRUCTURA                                             │
│   PostgreSQL | Redis pub/sub | Ollama (Qwen3-VL local)      │
│   SpaceTimeDB [futuro] como WebSocket state layer opcional  │
├─────────────────────────────────────────────────────────────┤
│ FINE-TUNING (offline)                                       │
│   Google Colab + Unsloth → GGUF → Ollama local              │
│   Dataset: clips rating → virality model mejorado           │
└─────────────────────────────────────────────────────────────┘
```

---

## PRÓXIMOS PASOS CONCRETOS (esta semana)

1. **`docker-compose up -d --build`** → rebuild con Ollama + scenedetect (nuevas deps)
2. **`docker-compose logs -f ollama`** → esperar que descargue `qwen3-vl:8b` (~5GB, primera vez)
3. **Verificar pipeline visual** → procesar un video y confirmar `visual_virality` en los clips
4. **FASE 2** → integrar ACE-Step 1.5 para BGM generativo
5. **Rating system** → añadir ⭐ en el frontend para feedback loop de fine-tuning

---

## RECURSOS Y LINKS

- [Qwen3-VL-8B HuggingFace](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct) — modelo base (ya disponible en Ollama)
- [Ollama Library — qwen3-vl](https://ollama.com/library/qwen3-vl) — `ollama pull qwen3-vl:8b`
- [ACE-Step GitHub](https://github.com/ace-step/ACE-Step-1.5) — música generativa
- [PySceneDetect](https://www.scenedetect.com/) — pip install scenedetect
- [SpaceTimeDB Docs](https://spacetimedb.com/docs) — para la fase WebSocket futura
- [Unsloth Studio](https://unsloth.ai/docs/new/studio) — fine-tuning en Colab

---

*Actualizado: 2026-03-28 | Status: Fase 0 + Fase 1 completadas — estrategia 100% local sin APIs de pago*
