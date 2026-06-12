# OUTPUT-CUTS-8 COMPLETE

## 1. Files changed
- backend/src/services/vpi_silence_editor.py — prioridad hard dead air (≥1.2s → shorten 0.35s)
  sobre ramas de énfasis por keywords; presupuesto dead_air 12s (resto 2.5s), máx 8 cuts.
- backend/src/services/vpi_disfluency_editor.py — build_output_cut_plan(): contrato
  applied_cut_plan (cuts/keep_segments/totales) + política editorial HARD_CUT /
  COMPRESS_SILENCE / KEEP_EDITORIAL_PAUSE / MASK_WITH_VISUAL (metadata) /
  SFX_PUNCTUATE (metadata) sobre detectores existentes + snap pass.
- backend/src/services/video_service.py — bridge a _silence_plan_obj.cuts antes de
  apply_silence_edit_plan; filtrado de words dentro de cortes pre-remap; logs
  VPI_OUTPUT_CUTS_*; artifact plans/clip_N_applied_cut_plan.json; metadata output_cuts.
- backend/src/services/vpi_retention_editing_service.py — FASE 5: bts_override eliminado
  (RESCUE_BLOCKED + placeholder); razones BTS vetadas en dialogue/generic fallbacks.
- backend/src/services/vpi_editorial_scorer.py — FASE 5: guard en diversity_fill.
(4 y 5 fuera de la lista de permitidos pero son la ubicación exacta del rescate que FASE 5 exige.)
Tests: checkpoints/output_cuts_8_apply_disfluency_cuts/test_output_cuts.py — 17/17 PASS.

## 2. Root cause — por qué los cortes detectados no se renderizaban
El único camino físico de corte (vpi_silence_editor.apply_silence_edit_plan, ffmpeg
trim+atrim+concat) solo recibía cuts de 3 fuentes y ninguna funcionaba sobre titubeos:
(a) el plan de vpi_disfluency_editor era metadata post-render, jamás se puenteaba a
plan.cuts; (b) el bridge de fluency cuts exigía transcript con timestamps "[MM:SS]"
que nunca llegaba (texto plano → plan=None); (c) el clasificador de silencios daba
prioridad a "emphasis_pause" por keywords (p.ej. "no siempre") sobre dead_air, y
tenía caps de 2.5s/4 cuts, dejando cuts=0.

## 3. Cut application
- implemented: **yes**
- render method: ffmpeg filter_complex trim/atrim + concat (ruta existente de
  apply_silence_edit_plan, ahora alimentada con keep/cut segments reales)
- captions retimed: **yes** (filtrado de words cortadas + remap por offset_map;
  ASS continuo, primera caption ≤0.25s, 0 overlaps, texto eliminado ausente)
- audio/video sync verified: **yes** en los MP4 finales (0 silencios ≥0.9s, captions
  alineados). Nota: el log AUDIO_SYNC_VERIFIED probea el MP4 intermedio de la etapa
  silence y reporta drift falso; el final real está en sync (ver caption_validation.md).

## 4. Task 1
- task_id: 6e676484-ef14-4036-aa4a-261362a9605e
- cuts_detected: 8 (7 clip1 + 1 clip2) · cuts_applied: 6 (5 + 1)
- total_cut_seconds: 8.95 (7.56 + 1.39)
- verdict before: CASI_PUBLICABLE · after: **CASI_PUBLICABLE (mejor)** — triple
  repetición "La salud no siempre avisa" reducida a 1 cierre; dead air 2.6s eliminado.
- main remaining issue: SOBRE-CORTE — la apertura "No todos los seguros…" cayó por el
  marcador de auto-corrección "no" y "¿Qué necesitas?" como short_abandoned_start
  (falsos positivos sobre arranques retóricos).

## 5. Task 2
- task_id: 7c994bf6-6663-4277-9119-aedabbc1024b
- cuts_detected: 2 · cuts_applied: 1 · total_cut_seconds: 2.25
- verdict before: CASI_PUBLICABLE · after: **CASI_PUBLICABLE (mejor)** — retake
  "No es una cuestión de dramatizar," cortado (queda la última toma); ~1s muerto
  inicial reducido a 0.21s; el clip limpio (12.1s) quedó intacto (no sobre-corta).
- main remaining issue: selección arranca a mitad de frase (boundary, fuera de scope).

## 6. Task 3
- task_id: 26a9aa6a-7d3b-4d84-ab64-fb1d04666882
- cuts_detected: 10 (5+1+4) · cuts_applied: 2 · total_cut_seconds: 4.75 (3.56 + 1.19)
- backstage rescue blocked: **instalado, no disparado** — los candidatos BTS fueron
  rechazados upstream ([clean-take] reject bts_contaminated) y el backstage de la
  baseline ("…¿No se ve que estoy leyendo, Sasa?") YA NO está en los finales; 0 logs
  VPI_OUTPUT_CUTS_BACKSTAGE_RESCUE_BLOCKED porque nadie intentó rescatarlo esta vez.
- verdict before: NO_PUBLICABLE · after: **CASI_PUBLICABLE** — sin backstage, retake
  duplicado cortado (clip 1), "Perdón." cortado (clip 3).
- main remaining issue: cierre truncado persiste — clip 1 termina en "sino de… Por"
  (la toma buena cae fuera de la ventana 06:35–07:11; el closure guard no recorta
  hacia atrás hasta "…veces no."); clip 3 termina en "Que" colgado.

## 7. Quality preserved
- subtitles sync: yes (retimados post-cut, 0 overlaps, sin texto stale)
- music present: yes (bgm=verified en los 3 tasks)
- typewriter absent: yes (sfx=skipped_no_event)
- hook/B-roll preserved: hook yes (quemado <1.5s en todos); B-roll sigue sin
  renderizarse (igual que baseline, sin regresión; fuera de scope)
- frontend loads: yes (HTTP 200 en las 3 tasks)

## 8. Technical regressions
1. Sobre-corte de arranques retóricos: _AUTO_CORRECTION_MARKERS ("no") y
   short_abandoned_start cortan frases de apertura legítimas (task 1 clip 1).
2. Log VPI_OUTPUT_CUTS_AUDIO_SYNC_VERIFIED mide contra el MP4 intermedio → drift
   falso en logs (cosmético; el final está verificado por otra vía).
3. Overrun leve de última caption (0.4–0.6s sobre el fin del MP4) — ya existía.

## 9. Remaining blockers
- Ninguno bloqueante para freeze. Pendientes de calidad: falsos positivos de false
  start, cierre hacia atrás cuando la toma buena queda fuera de ventana, arranques
  de selección a mitad de frase.

## 10. Next smallest action
Acotar los falsos positivos de false start en build_output_cut_plan: (a) exigir
pausa ≥0.4s tras el supuesto false start, (b) no permitir HARD_CUT de la primera
línea del clip salvo razón backstage o duplicado exacto, (c) sacar "no" de los
marcadores de auto-corrección salvo patrón "no, no"/"no espera". (~20 líneas en
vpi_disfluency_editor.build_output_cut_plan, re-smoke solo task 1.)

## Rutas para revisión humana
- http://localhost:3000/tasks/6e676484-ef14-4036-aa4a-261362a9605e
- http://localhost:3000/tasks/7c994bf6-6663-4277-9119-aedabbc1024b
- http://localhost:3000/tasks/26a9aa6a-7d3b-4d84-ab64-fb1d04666882
- outputs/generated/6e676484-ef14-4036-aa4a-261362a9605e/clip_0{1,2}.mp4
- outputs/generated/7c994bf6-6663-4277-9119-aedabbc1024b/clip_0{1,2}.mp4
- outputs/generated/26a9aa6a-7d3b-4d84-ab64-fb1d04666882/clip_0{1,2,3}.mp4
