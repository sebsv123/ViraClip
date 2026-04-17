@echo off
echo 🔨 Building con caché...
docker-compose build backend worker
docker-compose up -d
echo ✅ Build completo
