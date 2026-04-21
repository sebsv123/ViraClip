#!/usr/bin/env bash
# dev-status.sh — Script de monitoreo completo para ViraClip
# Uso: ./dev-status.sh

set -euo pipefail

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

PROJECT_DIR="${PROJECT_DIR:-$HOME/CascadeProjects/ViraClip}"
cd "$PROJECT_DIR" || exit 1

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  ViraClip Dev Status Monitor${NC}"
echo -e "${BLUE}  $(date)${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# ─────────────────────────────────────────────────────────────────────────────
# 1. ESTADO DE CONTENEDORES
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}📦 CONTENEDORES DOCKER${NC}"
echo -e "─────────────────────────────────────────────────────────────"

if docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Health}}" 2>/dev/null | grep -q viraclip; then
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Health}}" | grep -E "viraclip|NAME" | while read line; do
        if echo "$line" | grep -q "healthy"; then
            echo -e "${GREEN}✓${NC} $line"
        elif echo "$line" | grep -q "unhealthy"; then
            echo -e "${RED}✗${NC} $line"
        elif echo "$line" | grep -q "restarting"; then
            echo -e "${YELLOW}↻${NC} $line"
        else
            echo "  $line"
        fi
    done
else
    echo -e "${RED}✗ No hay contenedores viraclip ejecutándose${NC}"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 2. ESTADO DE ARQ QUEUE (Redis)
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}🔄 ARQ JOB QUEUE STATUS${NC}"
echo -e "─────────────────────────────────────────────────────────────"

# Verificar redis-cli disponible
if docker exec viraclip-redis redis-cli --version &>/dev/null; then
    # Queue depth
    QUEUE_DEPTH=$(docker exec viraclip-redis redis-cli ZCARD arq:queue 2>/dev/null || echo "0")
    echo "  Queue depth (arq:queue): $QUEUE_DEPTH jobs"
    
    # Jobs in-progress
    IN_PROGRESS=$(docker exec viraclip-redis redis-cli KEYS 'arq:in-progress:*' 2>/dev/null | wc -l)
    echo "  Jobs in-progress: $IN_PROGRESS"
    
    # Jobs en retry
    RETRY_COUNT=$(docker exec viraclip-redis redis-cli KEYS 'arq:retry:*' 2>/dev/null | wc -l)
    echo "  Jobs in retry: $RETRY_COUNT"
    
    # Dead letter
    DEAD_COUNT=$(docker exec viraclip-redis redis-cli SCARD tasks:dead_letter 2>/dev/null || echo "0")
    echo "  Dead letter queue: $DEAD_COUNT"
    
    # Jobs esperando (detalle)
    if [ "$QUEUE_DEPTH" -gt 0 ]; then
        echo -e "\n  Pending jobs (primeros 5):"
        docker exec viraclip-redis redis-cli ZRANGE arq:queue 0 4 WITHSCORES 2>/dev/null | while read job_id; do
            read timestamp
            # Intentar obtener el nombre de la función
            job_data=$(docker exec viraclip-redis redis-cli GET "$job_id" 2>/dev/null | head -c 100 || echo "")
            echo "    - $job_id (${timestamp}s)"
        done
    fi
else
    echo -e "${RED}  ✗ Redis no responde${NC}"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 3. ÚLTIMAS 20 LÍNEAS DE LOGS DEL WORKER (filtradas)
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}📋 WORKER LOGS (últimas 20 líneas filtradas)${NC}"
echo -e "─────────────────────────────────────────────────────────────"

if docker ps | grep -q viraclip-worker; then
    docker logs viraclip-worker --tail 100 2>&1 | grep -E "(INFO|WARNING|ERROR|CRITICAL|\[Phase|\[Gate|\[Caption|\[HookVisual|\[BeatSync|\[Creative|\[SmartEditor|\[LUT|\[BRoll|\[arq:job)" | tail -20 || echo "  (sin logs recientes)"
else
    echo -e "${RED}  ✗ Worker no está ejecutándose${NC}"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 4. ÚLTIMOS ERRORES DEL BACKEND (últimos 5 minutos)
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}🚨 BACKEND ERRORES (últimos 5 minutos)${NC}"
echo -e "─────────────────────────────────────────────────────────────"

if docker ps | grep -q viraclip-backend; then
    docker logs viraclip-backend --since 5m 2>&1 | grep -E "(ERROR|CRITICAL|Exception|Traceback)" | tail -10 || echo "  (sin errores recientes)"
else
    echo -e "${RED}  ✗ Backend no está ejecutándose${NC}"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 5. ESTADO DE TASKS EN POSTGRESQL
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}🗄️  TASKS EN POSTGRESQL${NC}"
echo -e "─────────────────────────────────────────────────────────────"

if docker ps | grep -q viraclip-postgres; then
    # Contar tasks por estado
    docker exec viraclip-postgres psql -U viraclip -d viraclip -c "
        SELECT status, COUNT(*) as count 
        FROM tasks 
        WHERE created_at > NOW() - INTERVAL '24 hours'
        GROUP BY status 
        ORDER BY count DESC;
    " 2>/dev/null | grep -E "(pending|processing|completed|error|queued)" || echo "  (no hay tasks en las últimas 24h)"
    
    # Mostrar últimos 3 tasks
    echo -e "\n  Últimos 3 tasks (24h):"
    docker exec viraclip-postgres psql -U viraclip -d viraclip -c "
        SELECT id, status, progress, current_stage, created_at 
        FROM tasks 
        WHERE created_at > NOW() - INTERVAL '24 hours'
        ORDER BY created_at DESC 
        LIMIT 3;
    " 2>/dev/null | tail -4 || echo "  (sin tasks recientes)"
else
    echo -e "${RED}  ✗ PostgreSQL no está ejecutándose${NC}"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 6. USO DE GPU
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}🎮 GPU STATUS${NC}"
echo -e "─────────────────────────────────────────────────────────────"

if command -v nvidia-smi &>/dev/null; then
    nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total --format=csv,noheader 2>/dev/null | while IFS=',' read name temp util mem_used mem_total; do
        echo "  GPU: $name"
        echo "    Temperatura: ${temp}°C"
        echo "    Utilización: ${util}"
        echo "    Memoria: ${mem_used} / ${mem_total}"
    done
elif docker exec viraclip-backend nvidia-smi --version &>/dev/null 2>&1; then
    docker exec viraclip-backend nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total --format=csv,noheader 2>/dev/null | while IFS=',' read name temp util mem_used mem_total; do
        echo "  GPU: $name"
        echo "    Temperatura: ${temp}°C"
        echo "    Utilización: ${util}"
        echo "    Memoria: ${mem_used} / ${mem_total}"
    done
else
    echo "  ℹ️  nvidia-smi no disponible (GPU puede estar en modo CPU fallback)"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 7. ESPACIO EN DISCO (exports y temp)
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${YELLOW}💾 ESPACIO EN DISCO${NC}"
echo -e "─────────────────────────────────────────────────────────────"

# Verificar directorios de clips
if docker exec viraclip-worker test -d /app/exports/clips 2>/dev/null; then
    CLIPS_SIZE=$(docker exec viraclip-worker du -sh /app/exports/clips 2>/dev/null | cut -f1)
    CLIPS_COUNT=$(docker exec viraclip-worker ls /app/exports/clips/*.mp4 2>/dev/null | wc -l || echo "0")
    echo "  /app/exports/clips: ${CLIPS_SIZE} (${CLIPS_COUNT} archivos .mp4)"
else
    echo "  /app/exports/clips: no existe"
fi

# Temp uploads
if docker exec viraclip-worker test -d /app/temp/uploads 2>/dev/null; then
    TEMP_SIZE=$(docker exec viraclip-worker du -sh /app/temp/uploads 2>/dev/null | cut -f1 || echo "0")
    echo "  /app/temp/uploads: ${TEMP_SIZE}"
else
    echo "  /app/temp/uploads: no existe"
fi

# ─────────────────────────────────────────────────────────────────────────────
# RESUMEN EJECUTIVO
# ─────────────────────────────────────────────────────────────────────────────
echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  RESUMEN EJECUTIVO${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Determinar estado general
OVERALL_STATUS="${GREEN}✓ HEALTHY${NC}"
if [ -n "${QUEUE_DEPTH:-}" ] && [ "$QUEUE_DEPTH" -gt 5 ]; then
    OVERALL_STATUS="${YELLOW}⚠ BACKLOG${NC}"
fi
if [ -n "${RETRY_COUNT:-}" ] && [ "$RETRY_COUNT" -gt 3 ]; then
    OVERALL_STATUS="${YELLOW}⚠ RETRIES${NC}"
fi
if [ -n "${DEAD_COUNT:-}" ] && [ "$DEAD_COUNT" -gt 0 ]; then
    OVERALL_STATUS="${RED}✗ FAILURES${NC}"
fi
if docker ps | grep -qE "viraclip-(backend|worker|redis|postgres).*unhealthy"; then
    OVERALL_STATUS="${RED}✗ UNHEALTHY${NC}"
fi

echo -e "  Estado general: $OVERALL_STATUS"
echo -e "  Queue depth: ${QUEUE_DEPTH:-0}"
echo -e "  Jobs in-progress: ${IN_PROGRESS:-0}"
echo -e "  Jobs retrying: ${RETRY_COUNT:-0}"
echo -e "  Dead letter: ${DEAD_COUNT:-0}"
echo ""
