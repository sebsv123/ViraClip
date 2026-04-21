---
# ViraClip — Workspace State
Updated: 2026-04-21

## Branch activo
version-basica

## Estado actual
- docker-compose.yml actualizado: volumen `shared_temp` compartido entre 
  backend, worker, worker-2, worker-3, gpu-worker y videorator
- `uploads` preservado solo para comfyui
- Variables de entorno fish: DOCKER_BUILDKIT=1 y COMPOSE_DOCKER_CLI_BUILD=1 
  seteadas con `set -Ux` 
- UNSPLASH_ACCESS_KEY= añadida al .env
- Build en curso al momento de escribir este fichero

## Pendiente
- [ ] Al arrancar cada sesión: leer .agent/AGENTS.md para cargar contexto
- [ ] Test de volumen compartido post-build:
      docker exec viraclip-backend touch /app/temp/SYNC_TEST
      docker exec viraclip-worker ls /app/temp/SYNC_TEST
      docker exec viraclip-backend rm /app/temp/SYNC_TEST
- [ ] Validar que el pipeline procesa vídeos sin docker cp manual

## Decisiones arquitectónicas clave
- Shell del sistema: fish (usar `set -Ux VAR valor`, NO `export VAR=valor`)
- Docker Compose: siempre con DOCKER_BUILDKIT=1
- Volúmenes: shared_temp para /app/temp, uploads solo para comfyui
- Coordinador principal: backend/src/services/coordinator.py
- Render paralelo: asyncio.gather en _parallel_rendering
---
