@echo off
echo 🧹 Limpiando contenedores y volúmenes...
docker-compose down -v
if exist backend\temp rmdir /s /q backend\temp
mkdir backend\temp
echo ✅ Limpieza completa
