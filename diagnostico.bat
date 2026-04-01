@echo off
echo ============================================
echo   VIRACLIP - DIAGNOSTICO COMPLETO
echo ============================================
echo.

echo [1/6] Estado de contenedores:
docker-compose ps
echo.

echo [2/6] Health check backend:
curl -s http://localhost:8000/health
echo.

echo [3/6] Health check Ollama:
curl -s http://localhost:11434/api/tags | findstr "name"
echo.

echo [4/6] Espacio en disco (uploads y clips):
docker exec viraclip-backend du -sh /app/uploads /app/clips /app/assets 2>nul
echo.

echo [5/6] Ultimos errores del worker (ultimas 20 lineas):
docker-compose logs --tail=20 worker 2>&1 | findstr /i "error ERROR Error exception Exception"
echo.

echo [6/6] Ultimos errores del backend (ultimas 20 lineas):
docker-compose logs --tail=20 backend 2>&1 | findstr /i "error ERROR Error exception Exception"
echo.

echo ============================================
echo   FIN DEL DIAGNOSTICO
echo ============================================
pause
