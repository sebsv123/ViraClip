# Baseline v0.3.0-vpi-narrative — Limitaciones conocidas

- Algunos clips aún pueden EMPEZAR a mitad de frase ("del pasaje, para que…",
  "mejor y vive más tranquila.") — el boundary de inicio no tiene equivalente
  del planner narrativo de cierre. Es el issue dominante restante.
- Algunos clips quedan CASI_PUBLICABLE y requieren QC humano; los marcados
  needs_review reason=narrative_closure_weak (p.ej. final en "Que" colgado al
  borde de una pausa larga de la fuente) se señalizan pero se renderizan.
- Fragmentos parciales de titubeo pueden sobrevivir al corte de grupo
  (p.ej. "Por eso se trata /" ~2s antes de la toma buena en vídeo 3 clip 1).
- B-roll/SFX/iconos locales todavía no se explotan de forma avanzada: B-roll
  planificado pero no renderizado (daily_mode bloquea proveedores externos y el
  banco local de assets/broll no está conectado al render); SFX siempre
  skipped_no_event; iconos dropped por presupuesto de capas.
- dedupe/backfill aún puede limitar el número de clips únicos por vídeo
  (tasks de 3 clips a veces entregan 2).
- Placeholders pueden requerir mejor reason UX en frontend.
- Cosmético: VPI_OUTPUT_CUTS_AUDIO_SYNC_VERIFIED probea el MP4 intermedio de la
  etapa silence (drift falso en logs); overrun leve (~0.5s) de la última caption
  en algunos clips; metadata "duration" del API puede no coincidir con el MP4 final.
