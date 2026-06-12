# Baseline v0.3.0-vpi-narrative — Capacidades congeladas

- **anti-backstage**: clasificador BTS en selección + hard-ban de rescate
  (bts_override eliminado; diversity_fill y dialogue/generic fallbacks vetan
  candidatos marcados bts_contamination_too_high/backstage_pure) + frases meta
  en el planner narrativo para no extender hacia backstage.
- **word-level retake cleaner**: build_output_cut_plan (vpi_disfluency_editor)
  corta retakes de frase (grupos de repetición por clusters, conservando la
  instancia más completa), false starts confirmados, stutters consecutivos y
  líneas de corrección explícita ("Perdón.", "me equivoqué, repito").
- **post-trim caption contract**: contrato 5B reconstruido tras cada cambio de
  boundary (S6 + planner narrativo) — captions nunca stale.
- **speech closure guard** (S6): nunca corta a mitad de palabra/frase; extiende
  ≤7s a cierre con puntuación+pausa o recorta al cierre previo, con screening BTS.
- **physical cut application** (OUTPUT-CUTS-8): los CUT del plan se aplican al MP4
  vía ffmpeg trim/atrim+concat (apply_silence_edit_plan), con remap de words/
  eventos/hook y duración; dead air >1.2s comprimido a ~0.35s aunque haya
  keywords de énfasis alrededor (classify_pause prioridad corregida).
- **false-positive guard** (8B): "No…" retórico, preguntas cortas completas y
  primera línea del clip protegidos; false starts exigen evidencia temporal
  (pausa ≥0.6s / near-repeat / corrección explícita con word-boundary match).
- **narrative closure planner** (9): _apply_narrative_closure_planner detecta
  finales retóricamente abiertos (conectores y contraste setup→payoff) y
  extiende 2-8s al primer cierre fuerte, capado en backstage/meta; si no hay
  cierre → needs_review reason=narrative_closure_weak.
- **refrain protection** (9): frases repetidas 2-3 veces separadas por contenido
  útil con idea temática = motivo retórico protegido (instancias partidas por
  pausa cuentan como una); simulación de transcript final post-cuts con retry.
- **synced captions**: ASS retimado a la timeline post-corte, sin texto de tramos
  eliminados, primera caption ≤0.5s, 0 overlaps.
- **background music**: bgm=verified + mastering loudnorm+compressor+limiter.
- **typewriter removed**: sfx=skipped_no_event en toda la cadena.
- **hook/B-roll baseline preserved**: hook quemado <1.5s con texto contextual;
  B-roll planificado (no renderizado — igual que la baseline previa).
- **frontend task pages working**: HTTP 200 con cards y reasons.
