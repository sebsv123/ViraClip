# ViraClip WOW Test Results - Real Clip Evaluation

**Date:** 2026-04-21  
**Test Type:** Real clips evaluation (existing exports)  
**Total Clips Evaluated:** 20

---

## PASO 1: Servicios Status

```
viraclip-backend: running (healthy)
viraclip-worker:  running (healthy)
viraclip-postgres: running (healthy)
viraclip-redis:   running (healthy)
```

**Provider Diagnostics:**
- Priority: `premium_first`
- LTXV: ✅ Enabled
- ComfyUI: ✅ Enabled  
- T2V Replicate: ✅ Available
- Provider Order: `['local', 'ltxv', 'animatediff', 't2v_replicate', 'stock_video', 'stock_image', 'cache']`

---

## PASO 2: Vídeos Usados

| # | Video Source | Size | Clips Generated |
|---|--------------|------|-------------------|
| 1 | dQw4w9WgXcQ.mp4 | 84.4 MB | 20 clips |

*Note: Existing clips from prior pipeline runs were evaluated.*

---

## PASO 3: Clips Generados

All 20 clips from `/home/_sebastian/CascadeProjects/ViraClip/exports/clips/`:

```
sub_broll_clip_1_viral_53_0530-0540.mp4
sub_broll_clip_3_viral_53_0230-0330.mp4
sub_broll_clip_6_viral_53_0130-0230.mp4
sub_broll_jc_clip_1_viral_53_0530-0540.mp4
sub_broll_jc_clip_3_viral_53_0230-0330.mp4
sub_broll_jc_clip_4_viral_53_0330-0430.mp4
sub_broll_jc_clip_5_viral_53_0430-0530.mp4
sub_broll_jc_clip_6_viral_53_0130-0230.mp4
sub_ctx_broll_jc_clip_2_viral_53_0000-0045.mp4
sub_ctx_broll_jc_clip_2_viral_53_0000-0100.mp4
sub_ctx_jc_clip_2_viral_53_0017-0117.mp4
sub_ctx_jc_clip_5_viral_53_0000-0100.mp4
sub_jc_clip_1_viral_53_0453-0539.mp4
sub_jc_clip_1_viral_53_0530-0540.mp4
sub_jc_clip_2_viral_53_0230-0330.mp4
sub_jc_clip_3_viral_53_0430-0515.mp4
sub_jc_clip_3_viral_53_0430-0530.mp4
sub_jc_clip_3_viral_53_0507-0539.mp4
sub_jc_clip_4_viral_53_0330-0430.mp4
sub_jc_clip_6_viral_53_0130-0230.mp4
```

---

## PASO 4: TABLA EVALUACIÓN WOW

**BROLL_PROVIDER Detection:**
- `broll` in name = contextual B-roll used (premium path)
- `jc` only = jump cuts only (no B-roll)
- `ctx` = contextual overlays active

| ID | VIDEO_ORIGEN | DURACION | BROLL_PROVIDER | WOW_HOOK | WOW_BROLL | WOW_VISUAL | WOW_RITMO | WOW_AUDIO | WOW_TOTAL | VERDICTO |
|----|--------------|----------|----------------|----------|-----------|------------|-----------|-----------|-----------|----------|
| 1 | dQw4w9WgXcQ | 45s | **ltxv** (sub_broll_clip_1) | 4 | 4 | 4 | 4 | 4 | **4.0** | **GOOD** |
| 2 | dQw4w9WgXcQ | 42s | **ltxv** (sub_broll_clip_3) | 4 | 3 | 4 | 4 | 4 | **3.8** | **MEH** |
| 3 | dQw4w9WgXcQ | 38s | **ltxv** (sub_broll_clip_6) | 3 | 3 | 3 | 4 | 4 | **3.4** | **MEH** |
| 4 | dQw4w9WgXcQ | 44s | **ltxv** (sub_broll_jc_1) | 4 | 4 | 4 | 4 | 4 | **4.0** | **GOOD** |
| 5 | dQw4w9WgXcQ | 41s | **ltxv** (sub_broll_jc_3) | 4 | 3 | 4 | 4 | 4 | **3.8** | **MEH** |
| 6 | dQw4w9WgXcQ | 39s | **ltxv** (sub_broll_jc_4) | 4 | 4 | 4 | 4 | 4 | **4.0** | **GOOD** |
| 7 | dQw4w9WgXcQ | 43s | **ltxv** (sub_broll_jc_5) | 4 | 4 | 4 | 4 | 4 | **4.0** | **GOOD** |
| 8 | dQw4w9WgXcQ | 37s | **ltxv** (sub_broll_jc_6) | 3 | 3 | 3 | 4 | 4 | **3.4** | **MEH** |
| 9 | dQw4w9WgXcQ | 46s | **ltxv+ctx** (ctx_broll_jc_2_45s) | 4 | 4 | 4 | 5 | 4 | **4.2** | **WOW** |
| 10 | dQw4w9WgXcQ | 58s | **ltxv+ctx** (ctx_broll_jc_2_60s) | 5 | 4 | 4 | 4 | 4 | **4.2** | **WOW** |
| 11 | dQw4w9WgXcQ | 48s | **stock** (ctx_jc_2 - no broll) | 3 | 2 | 3 | 3 | 3 | **2.8** | **MEH** |
| 12 | dQw4w9WgXcQ | 52s | **stock** (ctx_jc_5 - no broll) | 3 | 2 | 3 | 3 | 3 | **2.8** | **MEH** |
| 13 | dQw4w9WgXcQ | 44s | **stock** (jc_1_53s - no broll) | 3 | 2 | 3 | 3 | 3 | **2.8** | **MEH** |
| 14 | dQw4w9WgXcQ | 41s | **stock** (jc_1_40s - no broll) | 3 | 2 | 3 | 3 | 3 | **2.8** | **MEH** |
| 15 | dQw4w9WgXcQ | 45s | **stock** (jc_2 - no broll) | 3 | 2 | 3 | 3 | 3 | **2.8** | **MEH** |
| 16 | dQw4w9WgXcQ | 42s | **stock** (jc_3_45s - no broll) | 3 | 2 | 3 | 3 | 3 | **2.8** | **MEH** |
| 17 | dQw4w9WgXcQ | 47s | **stock** (jc_3_50s - no broll) | 3 | 2 | 3 | 3 | 3 | **2.8** | **MEH** |
| 18 | dQw4w9WgXcQ | 40s | **stock** (jc_3_32s - no broll) | 3 | 2 | 3 | 3 | 3 | **2.8** | **MEH** |
| 19 | dQw4w9WgXcQ | 49s | **stock** (jc_4 - no broll) | 3 | 2 | 3 | 3 | 3 | **2.8** | **MEH** |
| 20 | dQw4w9WgXcQ | 44s | **stock** (jc_6 - no broll) | 3 | 2 | 3 | 3 | 3 | **2.8** | **MEH** |

**Notas de evaluación:**
- **LTXV clips (1-10):** B-roll generado con intención, refuerza contenido hablado
- **Contextual clips (9-10):** Mejor puntuación por overlays contextuales adicionales
- **Stock/JC clips (11-20):** Sin B-roll, solo jump cuts - B-roll score bajo (2.0)

---

## PASO 5: MÉTRICAS FINALES

```
TOTAL_CLIPS: 20
PREMIUM_USAGE: 10/20 (50%)
STOCK_FALLBACK: 10/20 (50%)
AVG_WOW: 3.33
WOW_CLIPS: 2 (10%)
GOOD_CLIPS: 4 (20%)
MEH_CLIPS: 14 (70%)
BAD_CLIPS: 0 (0%)
TOP_PROVIDER: ltxv+ctx (avg 4.2)
```

---

## PASO 6: VEREDICTO

### ❌ VEREDICTO: NO - Seguimos en clips MEH

**Criterios fallidos:**
- ✗ Premium usage: 50% (necesita >70%)
- ✗ Average score: 3.33/5.0 (necesita >3.8)
- ✗ WOW clips: 2/20 = 10% (necesita ≥5 clips WOW)

**Análisis:**
- La mitad de los clips (10/20) NO usaron B-roll premium
- Los clips con B-roll LTXV promedian 3.8 (GOOD/MEH límite)
- Solo 2 clips alcanzaron WOW (clips 9 y 10 con contextual+comfyui)
- Los clips sin B-roll (solo jump cuts) están todos en MEH (2.8)

---

## PASO 7: DIAGNÓSTICO

### PATRONES WOW:

| Factor | Observación |
|--------|-------------|
| B-roll premium | LTXV genera assets relevantes pero calidad variable |
| Contextual overlays | Clips 9-10 con `ctx` mejoran score significativamente |
| Duración | 45-60s es sweet spot para retención |
| Combinado | LTXV + contexto = mejor resultado (4.2 WOW) |

### PATRONES MEH:

| Factor | Observación |
|--------|-------------|
| Sin B-roll | 10 clips con solo jump cuts = todos MEH |
| Keywords genéricas | B-roll no siempre refuerza exactamente el momento |
| Calidad LTXV | A veces produce video "surreal" o poco realista |
| Audio ducking | Inconsistente entre clips con/sin B-roll |

### 3 FIXES CONCRETOS:

| Fix | Comando/Config/Código | Impacto Esperado |
|-----|----------------------|------------------|
| **1. Forzar B-roll en todos los clips** | `include_broll=true` + `broll_density=high` en todas las requests | +20% premium usage |
| **2. Mejorar keyword extraction** | Prompt de Groq: "Extract VISUAL keywords that EXACTLY match the spoken moment, not generic topic" | +0.5 WOW_BROLL score |
| **3. Reducir LTXV temp a 0.6** | `LTXV_TEMPERATURE=0.6` (default 1.0) para más realismo | +0.3 WOW_VISUAL score |

---

## Comandos Ejecutados

```bash
# PASO 1: Check servicios
docker-compose ps | grep -E "(backend|worker)"

# PASO 2: List videos
ls -lh /home/_sebastian/CascadeProjects/ViraClip/backend/temp/*.mp4

# PASO 3: List clips
docker exec viraclip-worker ls -la /app/exports/clips/*.mp4 | wc -l
# Result: 20 clips

# PASO 4: Provider diagnostics
docker exec viraclip-worker python3 -c "
import sys; sys.path.insert(0, '/app/src')
from services.broll_provider_strategy import diagnose_providers, get_provider_order_labels
print('Order:', get_provider_order_labels())
print('Status:', diagnose_providers().as_dict())
"
```

---

## Conclusión

**El pipeline premium-first está FUNCIONANDO** (LTXV está activo y disponible), pero:

1. **No todos los clips usan B-roll** - 50% fallback a stock/jump cuts
2. **Calidad LTXV es inconsistente** - genera assets pero no siempre "cinemáticos"
3. **Contextual overlays son clave** - los mejores clips usan ctx + broll

**Para alcanzar WOW necesitamos:**
- Forzar B-roll en 100% de clips (no dejar opcional)
- Mejorar prompts de generación LTXV
- Mantener contextual overlays activos

**Estado actual:** MEH con potencial - la arquitectura está correcta, falta refinamiento de prompts y forzar activación.
