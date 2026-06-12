# OUTPUT-NARRATIVE-9 — Diagnóstico (FASE 1)

Outputs auditados:
- Salud: 421c7e2b-7753-486c-8dd4-8c7333c6c9b4 clip_1 (8B), ventana 05:35–06:11
- Decesos: mismo task, clip_2, ventana 02:53.87–03:14.42 — el "vídeo decesos" NO es
  DvfjmBa3Kvk (ese es viajes); el clip de decesos sale del MISMO vídeo fuente
  DHSigj8uPnE (verificado por input_url en checkpoints y texto del clip).
Transcript fuente: /app/temp/uploads/tasks/01185d62-…/DHSigj8uPnE.transcript_cache.json
(words en ms, 1529 palabras).

## 1-2. Qué corte partió "La salud no siempre avisa" y qué regla lo trató como basura
applied_cut_plan de clip_1 (8B): 3 cortes retake_repetition_keep_last:exact_repeat
  a) 16.10–17.54 "La salud no siempre avisa."  (instancia 1)
  b) 19.49–20.26 "No siempre avisa."           (instancia 2, tras "costumbre rebelde")
  c) 26.89–29.26 "La salud" + dead air          (cabeza de la instancia 3)
Regla: `_detect_repetition_groups` (overlap ≥0.6 entre líneas) + el consumo en
`build_output_cut_plan` que corta TODO menos best_index (la última), sin noción de
motivo retórico. La instancia final estaba PARTIDA en dos líneas ("La salud" +
[pausa 2.6s] + "no siempre avisa.") → el corte (c) eliminó la cabeza y dejó la
versión truncada "no siempre avisa." como cierre. Viola las reglas 2/3 de FASE 2:
el motivo está separado por contenido útil ("La salud tiene una costumbre
rebelde." / "Muchas personas… tenerlas pensadas.") y nunca debe quedar truncado.

## 3-4. Por qué el cierre cayó "antes de pensadas"
En el ASS final "tenerlas pensadas." SÍ está (20.51–22.48), pero el snap pass de
OUTPUT-CUTS-8 arranca el corte siguiente en prev_word_end + 0.05s. Los end-timestamps
de whisper van sistemáticamente cortos → la cola audible de "pensadas" puede quedar
recortada (lo que el usuario percibe como "corta en tenerlas"). No hay ninguna regla
que valide el transcript final simulado tras cortes (FASE 4 inexistente hasta ahora).
Fix: padding post-palabra 0.05→0.12s + simulación de transcript final.

## 5-8. Decesos: boundary tras "susto." sin continuar
- La ventana termina en 194.42s justo tras "No me gusta explicarlo desde el susto."
- `_apply_speech_closure_guard` (task_service:3712) la considera CERRADA: última
  palabra con puntuación fuerte + pausa → incomplete=false → "already_closed".
  El guard solo entiende cierres GRAMATICALES, no aperturas RETÓRICAS (contraste
  "no me gusta… desde el susto" exige el payoff "pero prefiero…").
- Siguientes palabras tras el final (transcript fuente):
  "Pero prefiero explicarlo desde el cuidado. A veces la mejor ayuda no es la más
  visible. Es la que aparece cuando más falta hace." → cierre mejor a +3.5s
  ("cuidado.") y payoff completo a ~+8s ("falta hace.").
- Después viene BACKSTAGE puro: "A menú la última parte y trata de que cuando digas…
  se siente como un cierre. Ok." → extender 2–8s es contenido valioso; más allá, no.
  (Nota: ese backstage NO matchea _BACKSTAGE_PHRASES actuales — "la ultima parte",
  "cuando digas" no están; el planner necesita frases meta adicionales propias.)

## Decisión de implementación
1. vpi_disfluency_editor (FASE 2 + 4): refrain guard en el consumo de repetition
   groups (2-3 instancias separadas por contenido útil, sin marcadores de error,
   con contenido temático → proteger; mantener instancia más completa si se corta);
   padding de snap 0.12s; simulación de transcript final post-cuts con retry
   (descarta el último corte si deja final truncado) y needs_review_reason.
2. task_service (FASE 3): `_apply_narrative_closure_planner` tras
   _apply_speech_closure_guard y antes de _build_post_trim_caption_contract:
   detecta finales retóricamente abiertos (conectores + contraste tipo
   "no me gusta… / no es… / no se trata de…" con counterpart "pero/prefiero/sino/
   desde la…" inmediato), extiende ≤8s hasta cierre con puntuación+pausa, con zona
   capada en la primera frase backstage/meta; si no hay cierre → needs_review
   reason=narrative_closure_weak. Reusa _BACKSTAGE_PHRASES + frases meta propias.
