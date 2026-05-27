# Checkpoint: Beta Clean VPI — End-to-End PASS

**Fecha:** 2026-05-27
**Task ID validada:** `ee35a5df-cbcd-4727-9b61-e4bd1bfe90e7`
**Video:** Rosa Valentín 6 (YouTube, 340s)
**Pipeline:** 88.6s → 2 clips (30s cada uno, score=40)

---

## Flags estables (producción)

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

---

## Resumen PASS/FAIL

| Aspecto | Resultado |
|---|---|
| Captions VPI Clean | ✅ PASS |
| Caption cache lookup | ✅ PASS |
| Caption timestamps reales | ✅ PASS |
| Caption posición fija inferior | ✅ PASS |
| Sin SUBTITLE-FALLBACK | ✅ PASS |
| Sin LEGACY-FALLBACK | ✅ PASS |
| Sin texto superior fantasma | ✅ PASS |
| Sin HookVisualService | ✅ PASS |
| Sin top text overlay | ✅ PASS |
| Sin template text overlay | ✅ PASS |
| Sin title/headline overlay | ✅ PASS |
| B-roll editorial local | ✅ PASS |
| LocalBrollAssetBank (3 candidates) | ✅ PASS |
| mark_used con task_id | ✅ PASS |
| B-roll duration ≥ 2.5s | ✅ PASS |
| PIP disabled | ✅ PASS |
| Overlay aplicado | ✅ PASS |
| Output organizado VPI | ✅ PASS |
| .ass copy a output | ✅ PASS |
| task_summary.json | ✅ PASS |
| task_summary.md | ✅ PASS |
| Sin legacy/premium | ✅ PASS |
| libx264 encoding | ✅ PASS |
| Clip health grade B (80) | ✅ PASS |

---

## Rutas output organizado

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

Ejemplo real:
```
/app/outputs/vpi/2026-05-27/task_ee35a5dfcbcd/
```

---

## Captions status

- **Preset:** `vpi_clean`
- **Fuente:** `cached_words` (86-91 words por clip)
- **Layout:** `absolute_position=true x=540 y=1498 anchor=an5`
- **Alignment:** 2 (bottom-center)
- **MarginV:** 280
- **ASS debug:** `/app/temp/caption_debug/`
- **Sin `\pos` ni `\move`**
- **Máximo 4 palabras por línea**
- **Duración mínima 0.65s, máxima 1.80s**

---

## B-roll local status

- **Asset Bank MVP:** 15 assets en 5 categorías
- **Cue aprobada:** `financial_planning` (start=3.46s, dur=2.80s)
- **Asset usado:** `/app/assets/broll/financial_planning/01.mp4`
- **Fuente:** `local`
- **Efecto:** `ken_burns_in`
- **Duración efectiva:** 2.80s
- **PIP:** disabled

---

## task_summary status

Campos incluidos en `task_summary.json`:
- `task_id`, `source_url`, `source_title`, `status`
- `clips_generated`, `beta_clean`, `enable_editorial_broll`
- `whisper_device`, `created_at`
- Por clip: `clip_index`, `filename`, `start_time`, `end_time`, `duration`
- `virality_score`, `clip_health`, `caption_source`, `transcript_snippet`
- `warnings`

Campos adicionales en logs:
- `[task-summary] broll cue_type=... asset=... source=local`
- `[task-summary] caption_source=cached_words`

---

## No legacy/premium — confirmado

- ❌ No `Groq scored`
- ❌ No `Loading SentenceTransformer`
- ❌ No `Phi-3` / `Ollama`
- ❌ No `BRAIN` / `ClipIntel`
- ❌ No `cut_zoom`
- ❌ No `ComfyUI` / `LTX` / `T2V`
- ❌ No `h264_nvenc`
- ❌ No `cloud transcription`

---

## Asset Bank status

- **Categorías:** 7 (5 priorizadas en MVP)
- **Assets MVP:** 15 (3 por categoría)
- **LocalBrollAssetBank v2:** Rotación anti-repetición funcional
- **mark_used:** task_id propagado correctamente
- **Auditor:** Disponible en worker via `scripts/` mount

---

## Defaults restaurados

```
VIRACLIP_BETA_CLEAN=true
VIRACLIP_ENABLE_EDITORIAL_BROLL=false
```

---

## Próximos pasos recomendados

1. **Poblar Asset Bank completo** (70 assets en 7 categorías)
2. **Mejorar calidad de assets** (reemplazar 3 assets flojos identificados)
3. **Validar con más vídeos** (diferentes nichos, duraciones, idiomas)
4. **Probar con B-roll editorial activado** (`VIRACLIP_ENABLE_EDITORIAL_BROLL=true`)
5. **Automatizar ingestión de assets** desde Pexels/Coverr
6. **Mejorar sincronía de subtítulos** (cached word timestamps ya funcional)
7. **Agregar tests automatizados** para el flujo VPI
