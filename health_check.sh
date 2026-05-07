#!/bin/bash
echo "=== DOCKER CONTAINERS ==="
docker ps --format "table {{.Names}}\t{{.Status}}"

echo ""
echo "=== HEALTH ENDPOINTS ==="
curl -s http://localhost:8000/health 2>&1
echo ""
curl -s http://localhost:8000/health/db 2>&1
echo ""

echo "=== GPU STATUS ==="
nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu --format=csv,noheader 2>&1

echo ""
echo "=== DISK USAGE ==="
df -h / 2>&1 | tail -3

echo ""
echo "=== DOCKER DISK ==="
docker system df 2>&1

echo ""
echo "=== COMPOSE STATUS ==="
docker compose ps --format "table {{.Name}}\t{{.Status}}" 2>&1
