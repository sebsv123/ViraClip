# VALIDATION-3VIDEOS-STRESS COMPLETE

Fecha: 2026-06-11 · Branch: version-basica · Sin reinicios de servicios.

## 1. Code changed
- **NO** (solo se crearon ficheros bajo checkpoints/; sin git add/commit/reset)

## 2. Tasks

### task_1
- input: https://youtu.be/DHSigj8uPnE?si=5LHdKHWINJhddzEh
- task_id: 01185d62-3791-437b-9957-f7aba827dac3
- status: completed (completed_with_warnings) — 2 clips
- MP4: outputs/generated/01185d62-3791-437b-9957-f7aba827dac3/clip_01.mp4 (32.8s) + clip_02.mp4 (14.4s)
- verdict: **CASI_PUBLICABLE**
- main issue: retake/titubeo — triple repetición de "La salud no siempre avisa" dentro del clip
- retake/titubeo handling: detecta (plan de disfluencias con 4 CUT: 2 repeticiones, 1 false start, 1 dead air) pero **los cortes no se aplican al render**
- silence handling: pausa de ~2.6s a mitad de la frase final retenida, parcialmente cubierta por BGM; pausas cortas bien preservadas

### task_2
- input: https://youtu.be/DvfjmBa3Kvk?si=yLGSOpbb5C-TnPIe
- task_id: 0dd61e76-4fdb-4c1d-868c-c5f3047b4473
- status: completed (completed_with_warnings) — 2 clips
- MP4: outputs/generated/0dd61e76-4fdb-4c1d-868c-c5f3047b4473/clip_01.mp4 (14.1s) + clip_02.mp4 (10.1s)
- verdict: **CASI_PUBLICABLE**
- main issue: selection — clips muy cortos (14s/10s) frente a metadata que declara 30s; ~1s muerto al arranque del clip 1
- retake/titubeo handling: bien — los segmentos elegidos están limpios; solo repeticiones de palabra menores en plan
- silence handling: bien salvo 1.33s de casi-silencio al inicio del clip 1

### task_3
- input: https://youtu.be/bsw9jy-rYzw?si=jdvjvLK-FeJw-wUb
- task_id: 313ea157-daad-45c8-b223-a919fe1c72a8
- status: completed (completed_with_warnings) — 3 clips
- MP4: outputs/generated/313ea157-daad-45c8-b223-a919fe1c72a8/clip_01.mp4 (17.1s), clip_02.mp4 (11.6s), clip_03.mp4 (27.3s)
- verdict: **NO_PUBLICABLE**
- main issue: selection — clip 1 conserva el retake completo ("…pagar más por reflejo, sino / por eso se trata de pagar más por reflejo, sino de… Por") y termina con la frase truncada; clip 3 es backstage puro ("Ya quedó otro vídeo… ¿No se ve que estoy leyendo, Sasa?")
- retake/titubeo handling: **falla** — la repetición entera queda en el clip y el corte final cae justo antes de la toma buena
- silence handling: **falla** — clip 3 retiene dos huecos de habla de ~7s (cubiertos por música)

## 3. Success rate
- publicable: 0/3
- casi_publicable: 2/3 (task_1, task_2)
- no_publicable: 1/3 (task_3)

## 4. Common failures
- selection: clips que arrancan a mitad de frase ("exclusiones…", "Pero…"); en el vídeo más difícil el ranking deja pasar una ventana backstage como clip 3 pese a que el clasificador BTS rechazó muchos candidatos (bts_contamination_too_high) — el fill de diversidad termina rescatando material malo cuando hay pocos candidatos limpios
- retake/titubeo: patrón consistente — el disfluency planner DETECTA repeticiones/false starts/dead air y genera action=CUT, pero el render no aplica esos cortes (evidencia: ASS conserva los huecos, audio conserva la pausa, traza "DISFLUENCY_PLAN events=0" en la fase de render); resultado: frases repetidas en pantalla en tasks 1 y 3
- silence handling: pausas largas (2.6s y 2×~7s) retenidas y enmascaradas con BGM en vez de cortadas; silence editor solo clasifica pausas cortas (breath) y termina con cuts=0
- speech closure: el guard funcionó en tasks 1-2 (cierres en palabra final + buffer) pero falló en task 3 clip 1, que termina en "sino de… Por" (palabra suelta tras puntos suspensivos)
- captions: sin fallos de sincronización ni texto stale en ninguno de los 7 clips; los subtítulos reflejan fielmente el audio (incluido el material de ensayo no cortado)
- visual editing: B-roll planificado pero nunca renderizado (no_broll_rendered; daily_mode bloquea proveedores externos y no hay banco local conectado al render); transiciones planificadas no renderizadas; push-in sí aplicado

## 5. Common strengths
- Pipeline estable: 3/3 tasks completadas sin fallo, 7 MP4 válidos 1080x1920 h264+aac
- Hook quemado y visible <1.5s en todos los clips, con texto contextual distinto por clip
- Música presente y verificada (bgm=verified) + mastering (loudnorm+compressor+limiter, ~-16 LUFS) en todos
- Typewriter ausente, sin debug overlays, sfx=skipped_no_event
- Subtítulos sincronizados, sin stale, con fades y tamaño consistente
- Frontend HTTP 200 con cards y reasons en las 3 tasks
- Cierre de speech correcto en 4 de 5 clips "de contenido"

## 6. Recommendation
- freeze baseline: **yes** — la base (captions/música/hook/frontend/estabilidad) aguanta el estrés; los fallos están concentrados en selección/retakes
- next block should be: **A. retake/titubeo cleaner** (prioritario: hacer que los CUT del disfluency plan se APLIQUEN al render, y penalizar más fuerte ventanas con retake en el ranking), seguido de **B. silence handling** (mismo mecanismo de aplicación) y endurecer el gate BTS para que diversity_fill nunca rescate backstage

## 7. Local assets inventory
(checkpoints/validation_3videos_stress/local_assets_inventory_future_sfx_icons_broll.txt — 297 entradas)
- SFX found: **yes** (~20-25 ficheros en assets/sounds: whoosh, impact, riser, etc.)
- icons/objects found: **yes** (41 en assets/icons + 116 menciones icon/svg/object, incl. vpi_3d_object_registry.json y overlays/overlays_staging con 179 ficheros)
- broll found: **yes** (51 ficheros bajo assets/broll)
- recommended future use: conectar assets/broll como banco local al render (hoy el B-roll se planifica pero daily_mode bloquea proveedores externos y no se renderiza nada); usar SFX locales para los momentos de transición ya seleccionados (transition_sfx_sync ya se calcula); iconos/overlays para visual_reinforcement (hoy dropped por presupuesto de capas)

## 8. Human review needed
Frontend:
- http://localhost:3000/tasks/01185d62-3791-437b-9957-f7aba827dac3
- http://localhost:3000/tasks/0dd61e76-4fdb-4c1d-868c-c5f3047b4473
- http://localhost:3000/tasks/313ea157-daad-45c8-b223-a919fe1c72a8

MP4 directos:
- outputs/generated/01185d62-3791-437b-9957-f7aba827dac3/clip_01.mp4
- outputs/generated/01185d62-3791-437b-9957-f7aba827dac3/clip_02.mp4
- outputs/generated/0dd61e76-4fdb-4c1d-868c-c5f3047b4473/clip_01.mp4
- outputs/generated/0dd61e76-4fdb-4c1d-868c-c5f3047b4473/clip_02.mp4
- outputs/generated/313ea157-daad-45c8-b223-a919fe1c72a8/clip_01.mp4
- outputs/generated/313ea157-daad-45c8-b223-a919fe1c72a8/clip_02.mp4
- outputs/generated/313ea157-daad-45c8-b223-a919fe1c72a8/clip_03.mp4
