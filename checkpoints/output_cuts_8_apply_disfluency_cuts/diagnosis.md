# OUTPUT-CUTS-8 — Diagnóstico exacto (FASE 1)

## 1. Dónde se genera el disfluency plan
- `backend/src/services/vpi_disfluency_editor.py` → `build_disfluency_edit_plan(words, clip_duration, visual_style)`.
  Detectores word-level: `detect_fillers`, `detect_repetitions`, `detect_false_starts`, `detect_awkward_pauses`
  (DEAD_AIR = gap ≥1.0s, rango 0.5–3.0s). Es "pure data: no FFmpeg, no rendering" (docstring, línea 24).
- Se invoca SOLO desde `video_service._build_premium_timeline_plan` (línea ~1702), que corre DESPUÉS del render
  ("without changing render behavior", línea 1558) y se persiste como `plans/clip_N_disfluency_plan.json`
  vía `_write_plan_artifact` (línea 13459).

## 2. Dónde se guardan las acciones action=CUT
- En el artifact `plans/clip_N_disfluency_plan.json` (post-render, metadata).
- En el timeline plan como items MOTION_EFFECT role=disfluency_edit (líneas 1711-1730) — nadie los consume para cortar.

## 3. Formato
`DisfluencySegment`: disfluency_type, start_s, end_s (relativos al clip), original_text, confidence (0.7–0.9),
action (CUT/COMPRESS/...), reason, padding_before/after (0.05), speed_factor.

## 4. Por qué esos CUT no llegan al render
El único camino físico de corte es `vpi_silence_editor.apply_silence_edit_plan` (ffmpeg filter_complex
trim+atrim+concat), invocado en `video_service` línea ~6484 sobre `_silence_plan_obj.cuts`. A `plan.cuts` solo entran:
  a) cortes del propio clasificador de silencios (`_build_safe_cuts`);
  b) `_fluency_media_cuts` desde `_fluency_edit_plan` (línea 6295-6341);
  c) microcuts de shot-rhythm.
El plan de vpi_disfluency_editor NUNCA se puentea a `plan.cuts`. Además:
  - (b) está muerto: `_fluency_edit_plan` se construye con `_parse_transcript_lines(segment["text"])` (línea 4592),
    que exige formato "[MM:SS - MM:SS] texto"; el texto del segmento es plano → `no_timestamp_lines` → plan=None.
  - (a) clasifica mal los dead air largos: en `classify_pause` la rama `after_strong and (affects_hook or duration>=0.2)`
    (emphasis_pause, preserve_and_emphasize) tiene prioridad sobre la rama `duration >= dead_air_threshold` (0.85s).
    El dead air de 2.66s de task 1 ("…tenerlas pensadas. [2.66s] no siempre avisa") matchea "no siempre"
    (after_keywords) → preserve_and_emphasize → no corta. Las pausas de ~7s de task 3 idem o exceden los caps.
  - `_build_safe_cuts` además limita total_removed ≤2.5s y ≤4 cuts.

## 5. Silence editor con cuts=0
Sí: `[silence-plan] segments=N cuts=0` + `[silence-apply] skipped reason=no_safe_cuts`.
Modo SÍ es safe_trim (beta_clean=true, línea 6283); el problema es la clasificación/priorización, no el modo.

## 6. ¿El render solo extrae ventana continua?
Sí: el clip base se extrae como ventana continua start/end; después `apply_silence_edit_plan` PUEDE recortar
con keep-intervals + concat (infra existente y probada), pero llega sin cuts.

## 7. Dónde aplicar la timeline keep/cut
En el punto existente: poblar `_silence_plan_obj.cuts` ANTES de `_apply_silence_edit_plan` (video_service ~6295-6484).
No hace falta nueva ruta de render: `_keep_intervals` + filter_complex concat ya hacen extracción+concat+sync A/V.

## 8. Cómo se generan captions después del render
Tras el apply exitoso, `remap_word_timestamps/remap_events/remap_hook_plan` con `offset_map` reescriben
`words_with_confidence` y eventos a la timeline post-corte (líneas 6540-6553) y `duration` se actualiza.
El ASS se construye DESPUÉS desde esas words remapeadas → el retiming de captions viene gratis si el corte
entra por esta ruta. Texto de tramos cortados: las words dentro del corte colapsan al mismo instante
(start==end) → hay que filtrarlas/verificarlas (validación FASE 4).

## 9. Post-trim caption contract y speech closure
El contrato 5B y el speech-closure guard operan aguas arriba (task_service) sobre la ventana del segmento;
el corte físico ocurre después con remap coherente de words → el contrato sigue siendo válido siempre que
no cortemos la última frase (regla: nunca cortar el tramo final de cierre) y el offset_map sea exacto.

## FASE 5 — backstage rescue
El rescate ocurre en dos sitios:
  - `vpi_retention_editing_service.filter_content_quality_candidates` líneas 966-985: `bts_override_used`
    rescata candidatos marcados `bts_contamination_too_high` si son "strong VPI insurance".
  - `vpi_editorial_scorer` (~línea 2224): `diversity_fill` rellena slots sin mirar `content_quality_label`.
Nota honesta: el clip backstage de task 3 (02:48→03:18, "Ya quedó otro vídeo… Sasa") NO estaba marcado BTS
([clean-take] bts_lines=0): los términos BTS no matchean ese texto. El hard-ban pedido (solo candidatos YA
marcados) no lo habría bloqueado; se implementa igualmente para los marcados + guard en diversity_fill para
content_quality_label=reject con razón BTS.

## Decisión de implementación (mínima)
1. `vpi_silence_editor.classify_pause`: rama temprana hard dead air (≥1.2s → shorten a ~0.35s) con prioridad
   sobre las ramas de énfasis por keywords (ADDENDUM: COMPRESS_SILENCE 0.25–0.55s).
2. `vpi_disfluency_editor.build_output_cut_plan(...)` (nuevo, en el planner permitido): política editorial
   HARD_CUT/COMPRESS_SILENCE/KEEP_EDITORIAL_PAUSE/MASK_WITH_VISUAL(metadata)/SFX_PUNCTUATE(metadata) sobre
   detecciones EXISTENTES (word gaps + detectores de frase de vpi_editorial_fluency_service alimentados con
   líneas sintetizadas desde word timestamps) → contrato applied_cut_plan + media cuts.
3. `video_service`: bridge → merge en `_silence_plan_obj.cuts`, rebuild offset_map, logs VPI_OUTPUT_CUTS_*,
   metadata y artifact `clip_N_applied_cut_plan.json`.
4. Hard-ban backstage en los 2 puntos de rescate (FASE 5 manda sobre la lista de archivos; cambio mínimo).
