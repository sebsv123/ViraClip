---
# Decisiones Arquitectónicas — ViraClip

## 2026-04-21 — Volúmenes Docker
- DECISIÓN: shared_temp:/app/temp compartido entre todos los workers
- MOTIVO: evitar docker cp manual entre backend y worker
- ALTERNATIVA RECHAZADA: volumen uploads montado en subdirectorio (causaba 
  desincronización)

## 2026-04-21 — Shell del sistema
- DECISIÓN: fish shell, NO bash
- IMPACTO: variables de entorno con `set -Ux`, no `export` 
- IMPACTO: scripts .sh pueden fallar si usan sintaxis bash, usar fish o sh explícito
---
