#!/bin/bash
# ViraClip Health Check — Verificación Rápida de Servicios
# =========================================================
# Verifica que todos los servicios estén corriendo y respondan correctamente

set -e

echo ""
echo "=========================================="
echo "  ViraClip Health Check"
echo "=========================================="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ERRORS=0

# Function to check service
check_service() {
    local name=$1
    local url=$2
    local expected=$3
    
    echo -n "Checking $name... "
    
    if curl -sf "$url" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ OK${NC}"
    else
        echo -e "${RED}❌ FAIL${NC}"
        ERRORS=$((ERRORS + 1))
    fi
}

# Check Docker services are running
echo "Checking Docker services..."
if ! docker-compose ps | grep -q "running"; then
    echo -e "${RED}❌ No services running. Run: docker-compose up -d${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Docker Compose running${NC}"
echo ""

# Backend health
echo "Backend Services:"
check_service "Backend API" "http://localhost:8000/health"
check_service "OpenAPI docs" "http://localhost:8000/docs"

# Frontend
echo ""
echo "Frontend:"
check_service "Next.js frontend" "http://localhost:3000"

# ComfyUI
echo ""
echo "ComfyUI:"
check_service "ComfyUI interface" "http://localhost:8188"
check_service "ComfyUI system stats" "http://localhost:8188/system_stats"

# Database
echo ""
echo "Database:"
if docker-compose exec -T postgres pg_isready -U viraclip -d viraclip > /dev/null 2>&1; then
    echo -e "Postgres... ${GREEN}✅ OK${NC}"
else
    echo -e "Postgres... ${RED}❌ FAIL${NC}"
    ERRORS=$((ERRORS + 1))
fi

# Redis
if docker-compose exec -T redis redis-cli ping | grep -q "PONG"; then
    echo -e "Redis... ${GREEN}✅ OK${NC}"
else
    echo -e "Redis... ${RED}❌ FAIL${NC}"
    ERRORS=$((ERRORS + 1))
fi

# Ollama (if enabled)
echo ""
echo "AI Services:"
if curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo -e "Ollama... ${GREEN}✅ OK${NC}"
else
    echo -e "Ollama... ${YELLOW}⚠ Not running (optional)${NC}"
fi

# Check workers
echo ""
echo "Workers:"
WORKER_COUNT=$(docker-compose ps worker | grep -c "running" || echo "0")
echo "ARQ workers running: $WORKER_COUNT"
if [ "$WORKER_COUNT" -gt 0 ]; then
    echo -e "${GREEN}✅ Workers active${NC}"
else
    echo -e "${RED}❌ No workers running${NC}"
    ERRORS=$((ERRORS + 1))
fi

# Summary
echo ""
echo "=========================================="
if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}✅ All services healthy${NC}"
    echo "=========================================="
    exit 0
else
    echo -e "${RED}❌ $ERRORS service(s) failed${NC}"
    echo "=========================================="
    echo ""
    echo "Troubleshooting:"
    echo "  - View logs: docker-compose logs -f [service]"
    echo "  - Restart: docker-compose restart [service]"
    echo "  - Rebuild: docker-compose build --no-cache [service]"
    exit 1
fi
