# Próximos pasos recomendados (sobre baseline congelada)

1. **Commit + tag de esta baseline** (comandos sugeridos abajo, ejecutar el usuario).
2. **Selección de arranque** (issue dominante): planner de apertura simétrico al
   de cierre — no empezar a mitad de frase si hay un inicio de oración limpio
   ≤2-3s antes/después (mismo patrón: word-level + screening BTS).
3. **B-roll local**: conectar assets/broll (51 ficheros) como banco al render
   (hoy planned→no_broll_rendered) — el mayor salto visual disponible.
4. **SFX pack sobrio**: usar assets/sounds (~25 SFX) en los momentos ya
   calculados (transition_sfx_sync) — máx 1-2 por clip según ADDENDUM de 8.
5. Limpieza del titubeo parcial residual (fragmento pre-toma-buena) ampliando el
   cluster de repetición hacia fragmentos colgantes adyacentes.
6. Cosméticos: sync-check sobre el MP4 final, recorte del overrun de última caption.

Comandos sugeridos (NO ejecutados):
  git add backend/src/services/vpi_silence_editor.py \
          backend/src/services/vpi_disfluency_editor.py \
          backend/src/services/video_service.py \
          backend/src/services/task_service.py \
          backend/src/services/vpi_retention_editing_service.py \
          backend/src/services/vpi_editorial_scorer.py \
          checkpoints/
  # Nota: el working tree arrastra además trabajo previo sin commitear (~80 ficheros
  # de bloques anteriores). Si se quiere congelar TODO el estado funcional:
  #   git add -A
  git commit -m "v0.3.0-vpi-narrative-baseline"
  git tag v0.3.0-vpi-narrative-baseline
