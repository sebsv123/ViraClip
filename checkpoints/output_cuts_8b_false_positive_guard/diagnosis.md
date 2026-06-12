# OUTPUT-CUTS-8B — Diagnóstico (FASE 1)

## 1. Dónde se clasificó "No todos los seguros…" como false_start
`vpi_editorial_fluency_service._detect_false_starts` (línea ~840): marca cualquier
línea cuyo normalizado EMPIECE por un marcador de `_AUTO_CORRECTION_MARKERS`
(línea 676). Ese set incluye `"no"` (también "bueno", "digo", "o sea") → cualquier
frase española que empiece por "No …" se etiqueta `starts_with_auto_correction_no`.
El consumo físico ocurre en `vpi_disfluency_editor.build_output_cut_plan` (bucle
sobre `_detect_false_starts(lines)`), que en 8 confiaba ciegamente en el detector.

## 2. Dónde se clasificó "¿Qué necesitas?" como short_abandoned_start
Mismo `_detect_false_starts`, segunda regla (líneas ~849-862): línea con ≤5 palabras
seguida de línea ≥2x más larga que comparte ≥1 palabra → `short_abandoned_start`.
"¿Qué necesitas?" (2 palabras) seguida de "¿Y qué tranquilidad estás buscando? …"
comparte "qué" → falso positivo sobre una tríada retórica.

## 3. Reglas exactas que dispararon
- Task 1 clip 1 cut[0]: reason=`false_start:starts_with_auto_correction_no`,
  text="No todos los seguros de salud son iguales." (apertura editorial)
- Task 1 clip 1 cut[1]: reason=`false_start:short_abandoned_start_words=2_vs_5`,
  text="¿Qué necesitas?" (pregunta retórica completa)

## 4. Cortes reales que SÍ deben mantenerse (no relajar)
- Repeticiones claras de frase (retake_repetition_keep_last) — p.ej. la triple
  "La salud no siempre avisa" (task 1) y "No es una cuestión de dramatizar," (task 2).
- False starts con corrección explícita — p.ej. "Perdón." (task 3 clip 3,
  starts_with_auto_correction_perdon) o "me equivoqué", "espera", "otra vez".
- Dead air > 1.2s (COMPRESS_SILENCE) y leading silence.
- Backstage lines.
- Word stutter consecutivo ("por por").

## Decisión (FASE 2)
Guard en `vpi_disfluency_editor.build_output_cut_plan` (archivo permitido), en el
bucle de false starts — NO se toca el detector compartido de
vpi_editorial_fluency_service (lo usan otros consumidores como scoring):
1. "no" retórico: el marcador "no" solo confirma si hay "no no" repetido, un
   marcador de corrección explícito, o pausa ≥0.6s tras la línea con frase corta.
2. Pregunta corta completa (termina en "?", ≤6 palabras) → protegida.
3. Primera línea del clip → solo se corta con evidencia fuerte (corrección
   explícita, near-repeat posterior, o pausa larga + frase muy corta).
4. Evidencia temporal para todo false start: pausa posterior ≥0.6s, near-repeat
   posterior (overlap ≥0.6), o marcador de corrección explícito.
Logs y metadata según spec (false_start_guard_version="8b").
