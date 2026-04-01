@echo off
setlocal enabledelayedexpansion
echo Que quieres hacer?
echo [1] Levantar todo
echo [2] Parar todo  
echo [3] Reiniciar backend + workers (cambios en .py - 15 seg)
echo [4] Ver logs worker (tiempo real)
echo [5] Ver logs backend (tiempo real)
echo [6] Diagnostico completo
echo [7] Reconstruir backend (requirements.txt o Dockerfile - 20 min)
echo [8] Limpiar clips antiguos
echo.
set /p opcion=Opcion: 

if "%opcion%"=="1" docker-compose up -d
if "%opcion%"=="2" docker-compose down

if "%opcion%"=="3" (
    echo Reiniciando backend y workers (sin rebuild - solo codigo Python)...
    docker-compose restart backend worker worker-2 worker-3
    echo Listo en ~15 segundos
)

if "%opcion%"=="4" docker-compose logs -f worker
if "%opcion%"=="5" docker-compose logs -f backend
if "%opcion%"=="6" call diagnostico.bat

if "%opcion%"=="7" (
    echo Para que necesitas rebuild?
    echo [1] Cambie requirements.txt o Dockerfile (rebuild completo - 20 min^)
    echo [2] Solo cambie codigo .py (restart rapido - 15 seg^)
    set /p motivo=Opcion: 
    if "!motivo!"=="1" docker-compose up -d --build backend worker worker-2 worker-3
    if "!motivo!"=="2" docker-compose restart backend worker worker-2 worker-3
)

if "%opcion%"=="8" docker exec viraclip-backend find /app/clips -name "*.mp4" -mtime +7 -delete && echo Clips de mas de 7 dias eliminados
pause
