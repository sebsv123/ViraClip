---
# Lecciones Aprendidas — ViraClip

## L001 — fish shell en este sistema
- REGLA: Este sistema usa fish shell. Nunca usar `export VAR=value` ni 
  añadir nada a .bashrc. Usar siempre `set -Ux VAR valor`.
- EVIDENCIA: error al hacer source ~/.bashrc — "Uso no soportado de '='"

## L002 — BuildKit requerido
- REGLA: Siempre verificar que DOCKER_BUILDKIT=1 antes de docker compose build.
  Los Dockerfiles usan --mount=type=cache que requiere BuildKit.
- EVIDENCIA: error "the --mount option requires BuildKit"

## L003 — Volumen compartido backend↔worker
- REGLA: backend y workers comparten /app/temp via volumen `shared_temp`.
  No usar docker cp para mover vídeos entre contenedores.
- EVIDENCIA: fix aplicado en docker-compose.yml commit 2026-04-21
---
