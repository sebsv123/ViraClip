# OUTPUT-NARRATIVE-9 COMPLETE

## 1. Files changed
- backend/src/services/vpi_disfluency_editor.py:
  - Refrain protection (FASE 2): _oc_cluster_group_indices (instancia partida por
    pausa = UNA aparición), _oc_is_rhetorical_refrain (2-3 instancias separadas
    por contenido útil + idea temática + sin marcadores de error), consumo de
    repetition groups por clusters manteniendo la instancia más completa.
  - FASE 4: _oc_validate_simulated_ending + simulación del transcript final
    post-cuts con retry (descarta hasta 2 cortes de cola si truncan el cierre)
    y needs_review_reason.
  - Snap padding 0.05→0.12s tras palabra conservada (la cola audible de
    "pensadas" no se recorta).
- backend/src/services/task_service.py:
  - FASE 3: _apply_narrative_closure_planner + constantes (_NARRATIVE_META_PHRASES,
    _NARRATIVE_CONTRAST_SETUPS, _NARRATIVE_PAYOFF_STARTS); call site tras
    _apply_speech_closure_guard y ANTES de _build_post_trim_caption_contract
    (el contrato se rebuild con el nuevo end → captions nunca stale).
- vpi_editorial_scorer.py y transcription.py NO tocados.
- Tests: checkpoints/output_narrative_9_closure_planner/test_narrative_9.py

## 2. Root cause — por qué seguían cortándose ideas narrativas
a) El consumo de repetition groups cortaba TODO menos la última instancia, sin
   noción de motivo retórico; y la instancia final de "La salud no siempre avisa"
   estaba PARTIDA ("La salud" + dead air + "no siempre avisa.") → el corte de la
   cabeza dejaba un cierre truncado.
b) El snap pass cortaba a +0.05s del end de whisper (sistemáticamente corto) →
   cola audible de la última palabra ("pensadas") recortada.
c) _apply_speech_closure_guard solo entiende cierres GRAMATICALES: "susto." con
   puntuación y pausa = already_closed; no ve que "No me gusta explicarlo desde
   el susto." abre un contraste cuyo payoff ("Pero prefiero…") está a +2.4s.

## 3. Refrain protection
- implemented: **yes**
- protected examples: "La salud no siempre avisa." (4 índices = 3 clusters,
  reason=separated_thematic_refrain) — smoke real: REFRAIN_DETECTED/PROTECTED/
  REPETITION_CUT_BLOCKED count=3; las 3 apariciones están en el ASS final.
- blocked false repetition cuts: 3 en el smoke (metadata
  repetition_cut_blocked_count=3, protected_refrain_text en applied_cut_plan).

## 4. Narrative closure planner
- implemented: **yes**
- function: `_apply_narrative_closure_planner` (task_service)
- applied after cuts: **yes con matiz honesto** — corre tras S4/S5/S6 y antes del
  contrato; los cortes físicos ocurren en render, por lo que la validación
  post-cuts la cubre la simulación FASE 4 dentro de build_output_cut_plan
  (la combinación da las mismas garantías; el orden literal de la spec exigiría
  mover el cut-plan a selección, fuera de alcance mínimo).
- applied before caption contract: **yes** (el contrato se reconstruye después)

## 5. Salud smoke
- task_id: 6064b4d6-7989-4532-acf0-36d38f22dec8 (clip_01, 28.61s)
- verdict: **PUBLICABLE** (pendiente QC humano)
- "No todos los seguros…" preserved: yes (0.41s)
- "¿Qué necesitas?" preserved: yes
- "La salud no siempre avisa" handled naturally: yes — 3 apariciones conservadas
  como motivo; dead airs internos recortados (SILENCE_TRIM_APPLIED ×3, 4.56s)
- ending complete: yes — "…tenerlas pensadas. La salud no siempre avisa."
- remaining issue: ninguno relevante (output-cuts dedupe correcto: 2 candidatos
  solapaban cortes del clasificador → 0 dobles cortes)

## 6. Decesos smoke
- task_id: 6064b4d6-7989-4532-acf0-36d38f22dec8 (clip_02, 22.94s) — mismo vídeo
  fuente DHSigj8uPnE (DvfjmBa3Kvk es el de viajes; verificado en checkpoints)
- verdict: **PUBLICABLE** (pendiente QC humano)
- "desde el susto" abrupt ending fixed: yes
- closure extended: yes — 194.42→196.80 (+2.38s) reason=contrast_payoff_completed,
  payoff "Pero prefiero explicarlo desde el cuidado."; el backstage posterior
  ("A menú la última parte… cuando digas…") quedó fuera
- remaining issue: overrun leve de última caption (~0.6s, cosmético, pre-existente)

## 7. Quality preserved
- captions sync: yes (retimados, continuos, sin stale)
- music: yes (bgm=verified ambos clips)
- typewriter absent: yes (sfx=skipped_no_event)
- hook/B-roll: hook yes (quemado ambos); B-roll sin cambios (no renderizado, fuera de scope)
- frontend: yes (HTTP 200)

## 8. Technical regressions
- Ninguna detectada. Tests de regresión: OUTPUT-CUTS-8 17/17, 8B 8/8, NARRATIVE-9 9/9.
- Nota: los logs FINAL_TRANSCRIPT_* solo se emiten cuando hay cortes aceptados
  (con 0 cortes la frontera ya viene validada por S6+planner) — esperado.

## 9. Remaining blockers
- Ninguno. Pendientes de calidad fuera de scope: B-roll nunca renderizado,
  overrun ~0.6s de última caption, arranques a mitad de frase en otros vídeos
  (task 3 del stress), log AUDIO_SYNC_VERIFIED midiendo el MP4 intermedio.

## 10. Next smallest action
Re-smoke de los vídeos 2 (DvfjmBa3Kvk) y 3 (bsw9jy-rYzw) con la capa narrativa
activa para confirmar que el planner no sobre-extiende en vídeos con más ruido
(especialmente task 3: cierre "sino de… Por", donde el planner debería extender
o marcar needs_review=narrative_closure_weak), y luego congelar baseline 9.

## Rutas para revisión humana
- http://localhost:3000/tasks/6064b4d6-7989-4532-acf0-36d38f22dec8
- outputs/generated/6064b4d6-7989-4532-acf0-36d38f22dec8/clip_01.mp4 (salud, 28.6s)
- outputs/generated/6064b4d6-7989-4532-acf0-36d38f22dec8/clip_02.mp4 (decesos, 22.9s)
