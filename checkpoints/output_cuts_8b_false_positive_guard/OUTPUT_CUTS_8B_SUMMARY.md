# OUTPUT-CUTS-8B COMPLETE

## 1. Files changed
- backend/src/services/vpi_disfluency_editor.py (único archivo tocado):
  - Constantes y helpers del guard: _OC_WEAK_CORRECTION_MARKERS,
    _OC_EXPLICIT_CORRECTION_PHRASES (match por límites de palabra),
    _oc_is_complete_short_question, _oc_near_repeat_after, _oc_false_start_evidence.
  - build_output_cut_plan: los false starts del detector ahora requieren evidencia
    antes de convertirse en HARD_CUT; nuevo scan de líneas de corrección explícita
    (≤6 palabras) como HARD_CUT "explicit_correction_line"; metadata
    protected_cut_candidates_count / protected_cut_reasons / false_start_guard_version.
- vpi_silence_editor.py NO tocado (el falso positivo no venía de ahí).
- Tests: checkpoints/output_cuts_8b_false_positive_guard/test_false_positive_guard.py

## 2. Root cause — por qué se cortaban arranques retóricos válidos
`_AUTO_CORRECTION_MARKERS` de vpi_editorial_fluency_service incluye "no" (y "bueno",
"digo", "o sea"): cualquier línea que EMPIEZA por "No …" se etiqueta
starts_with_auto_correction_no. Y la regla short_abandoned_start marca toda línea
≤5 palabras seguida de una ≥2x más larga con ≥1 palabra compartida — lo que mata
preguntas retóricas como "¿Qué necesitas?". OUTPUT-CUTS-8 confiaba ciegamente en
esas etiquetas al construir los HARD_CUT. El detector compartido NO se modificó
(lo usan otros consumidores); el guard se aplica en el consumo físico.

## 3. False-positive guards
- rhetorical_no protected: **yes** (marcadores débiles solo confirman con "no no",
  corrección explícita, pausa ≥0.6s tras fragmento ≤3 palabras, o near-repeat)
- first_line protected: **yes** (primera línea solo cae con corrección explícita,
  near-repeat posterior o pausa larga + fragmento muy corto)
- short_question protected: **yes** (pregunta completa ≤6 palabras terminada en "?")
- temporal evidence required: **yes** (pausa ≥0.6s, near-repeat con overlap ≥0.6,
  o marcador de corrección explícito; si no, VPI_OUTPUT_CUTS_FALSE_START_PROTECTED)

## 4. Tests
- passed: 8/8 nuevos (guard) + 17/17 regresión OUTPUT-CUTS-8 re-ejecutados
- failed: 0

## 5. Smoke Task 1
- task_id: 421c7e2b-7753-486c-8dd4-8c7333c6c9b4
- cuts_detected: 5 (clip 1) + 0 (clip 2)
- cuts_applied: 3 (clip 1) — las 2 repeticiones del retake + "La salud" colgado
- total_cut_seconds: 4.58
- "No todos los seguros…" preserved: **yes** (abre el clip a 0.41s; log
  VPI_OUTPUT_CUTS_RETHORICAL_NO_PROTECTED)
- "¿Qué necesitas?" preserved: **yes** (tríada retórica completa; log
  VPI_OUTPUT_CUTS_SHORT_QUESTION_PROTECTED)
- triple repetition reduced: **yes** (queda una sola instancia de cierre
  "pensadas. no siempre avisa.")
- dead air reduced: **yes** (0 silencios ≥0.9s en el MP4 final)

## 6. Quality preserved
- subtitles sync: yes (retimados, 0 overlaps, sin stale, sin overrun: 23.92 vs 24.02s)
- music present: yes (bgm=verified)
- typewriter absent: yes (sfx=skipped_no_event)
- hook/B-roll preserved: hook yes (quemado 0.25–3.05s); B-roll sin cambios vs
  baseline (no renderizado, fuera de scope)
- frontend loads: yes (HTTP 200)

## 7. Technical regressions
- Ninguna detectada en este smoke. El guard de clip 2 protegió además
  "y menos peso encima." (short_abandoned_start) — correcto, era continuación legítima.
- Persisten (pre-existentes, no de 8B): log AUDIO_SYNC_VERIFIED mide contra MP4
  intermedio (drift falso en logs); B-roll planificado nunca renderizado.

## 8. Remaining blockers
- Ninguno. Pendientes de calidad fuera de este bloque: cierre hacia atrás cuando
  la toma buena queda fuera de ventana (task 3: "sino de… Por"), arranques de
  selección a mitad de frase, render de B-roll.

## 9. Next smallest action
Re-smoke de tasks 2 y 3 con el guard activo para confirmar que los cortes reales
(retake de task 2, "Perdón." de task 3) siguen aplicándose — esperado sí, porque
ambos son correcciones/duplicados explícitos que el guard confirma. Después,
backward speech-closure para el cierre "sino de… Por" (task_service, bloque aparte).

## Rutas para revisión humana
- http://localhost:3000/tasks/421c7e2b-7753-486c-8dd4-8c7333c6c9b4
- outputs/generated/421c7e2b-7753-486c-8dd4-8c7333c6c9b4/clip_01.mp4 (24.0s)
- outputs/generated/421c7e2b-7753-486c-8dd4-8c7333c6c9b4/clip_02.mp4 (20.6s)
