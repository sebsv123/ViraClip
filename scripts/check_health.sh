#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# ViraClip Health Check — ejecutar después de cualquier deploy
# Uso: bash scripts/check_health.sh
# ─────────────────────────────────────────────────────────
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()   { echo -e "${GREEN}  ✅ $1${NC}"; }
fail() { echo -e "${RED}  ❌ $1${NC}"; FAILED=$((FAILED+1)); }
warn() { echo -e "${YELLOW}  ⚠️  $1${NC}"; }
FAILED=0

echo ""
echo "═══════════════════════════════════════════"
echo "  ViraClip Health Check"
echo "═══════════════════════════════════════════"

# ── 1. Contenedores corriendo ────────────────
echo ""
echo "▶ Contenedores"
for svc in viraclip-backend viraclip-worker viraclip-redis viraclip-postgres; do
  STATUS=$(docker inspect --format='{{.State.Status}}' "$svc" 2>/dev/null || echo "missing")
  if [ "$STATUS" = "running" ]; then ok "$svc running"
  else fail "$svc → $STATUS"; fi
done

# ── 2. Backend API ───────────────────────────
echo ""
echo "▶ Backend API"
HTTP=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health || echo "000")
if [ "$HTTP" = "200" ]; then ok "GET /health → 200"
else fail "GET /health → $HTTP"; fi

DB=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health/db || echo "000")
if [ "$DB" = "200" ]; then ok "GET /health/db → 200"
else fail "GET /health/db → $DB"; fi

# ── 3. Redis ─────────────────────────────────
echo ""
echo "▶ Redis"
PING=$(docker exec viraclip-redis redis-cli PING 2>/dev/null || echo "FAIL")
if [ "$PING" = "PONG" ]; then ok "Redis PING → PONG"
else fail "Redis no responde: $PING"; fi

QNAME=$(docker exec viraclip-worker /app/.venv/bin/python3 -c \
  "from src.workers.tasks import WorkerSettings; print(getattr(WorkerSettings,'queue_name','default'))" \
  2>/dev/null | tail -1)
ok "Worker queue_name = ${QNAME:-default}"

QLEN=$(docker exec viraclip-redis redis-cli ZCARD arq:queue 2>/dev/null || echo "?")
if [ "$QLEN" = "0" ]; then ok "arq:queue vacía (sin jobs pendientes)"
else warn "arq:queue tiene $QLEN job(s) pendientes sin procesar"; fi

# ── 4. Worker polling ────────────────────────
echo ""
echo "▶ Worker polling"
READY=$(docker logs viraclip-worker --since 2m 2>&1 | grep -c "Worker ready\|polling starts" || true)
if [ "$READY" -gt 0 ]; then ok "Worker arrancó y está en polling"
else
  STARTUP=$(docker logs viraclip-worker --since 2m 2>&1 | grep -c "Worker starting up" || true)
  if [ "$STARTUP" -gt 0 ]; then warn "Worker arrancó pero no confirmó polling (revisar logs)"
  else fail "Worker sin actividad en los últimos 2 minutos"; fi
fi

# ── 5. Test end-to-end (opcional) ────────────
echo ""
echo "▶ Test end-to-end"
TASK=$(curl -s -X POST http://localhost:8000/tasks/ \
  -H "Content-Type: application/json" \
  -H "x-viraclip-user-id: healthcheck" \
  -d '{"source":{"url":"https://youtu.be/3wgwaxIfUJQ"},"force_fresh":true,"num_clips":1}' \
  2>/dev/null || echo "{}")
JOB_ID=$(echo "$TASK" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('job_id','FAIL'))" 2>/dev/null || echo "FAIL")
if [ "$JOB_ID" != "FAIL" ] && [ -n "$JOB_ID" ]; then
  ok "Task encolada → job_id=$JOB_ID"
  sleep 5
  NEWQ=$(docker exec viraclip-redis redis-cli ZCARD arq:queue 2>/dev/null || echo "?")
  PROCESSING=$(docker logs viraclip-worker --since 10s 2>&1 | grep -c "process_video\|job:start\|Phase" || true)
  if [ "$PROCESSING" -gt 0 ]; then ok "Worker cogió el job y está procesando ✨"
  else warn "Job encolado pero worker no logueó actividad en 5s (puede ser normal si está ocupado)"; fi
else
  fail "No se pudo crear task de prueba"
fi

# ── Resumen ───────────────────────────────────
echo ""
echo "═══════════════════════════════════════════"
if [ "$FAILED" -eq 0 ]; then
  echo -e "${GREEN}  ✅ Todo OK — ViraClip operativo${NC}"
else
  echo -e "${RED}  ❌ $FAILED problema(s) detectado(s)${NC}"
  echo ""
  echo "  Diagnóstico rápido:"
  echo "    docker logs viraclip-worker --since 5m 2>&1 | tail -30"
  echo "    docker logs viraclip-backend --since 5m 2>&1 | grep ERROR"
fi
echo "═══════════════════════════════════════════"
echo ""
exit $FAILED
