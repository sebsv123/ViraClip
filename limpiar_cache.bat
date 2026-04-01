@echo off
REM Script para limpiar caché de análisis AI
REM Útil cuando necesitas forzar re-análisis sin esperar 24h TTL

echo ============================================
echo   LIMPIAR CACHE DE ANALISIS AI
echo ============================================
echo.

echo Limpiando tabla processing_cache en PostgreSQL...
docker exec viraclip-postgres psql -U viraclip -d viraclip -c "DELETE FROM processing_cache;"

echo.
echo Cache limpiado exitosamente.
echo Proximos procesamientos re-analizaran desde cero.
echo.

pause
