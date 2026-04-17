@echo off
echo 🔨 Rebuilding desde cero...
docker-compose down
docker-compose build --no-cache backend worker
docker-compose up -d
echo ✅ Rebuild completo
