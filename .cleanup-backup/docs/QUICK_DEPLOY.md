# 🚀 ViraClip - Guía de Despliegue Rápido

**Tiempo estimado:** 15-20 minutos  
**Última actualización:** 12 Abril 2026

---

## ✅ Pre-requisitos

- Windows 10/11 o Linux/macOS
- Docker Desktop instalado
- 50GB+ espacio libre en disco
- 8GB+ RAM (16GB recomendado)

---

## 📋 Paso 1: Configuración Inicial (5 min)

### 1.1 Clonar Repositorio
```powershell
# Si aún no tienes el repositorio
git clone https://github.com/sebsv123/ViraClip.git
cd ViraClip
```

### 1.2 Copiar y Configurar .env
```powershell
# Copiar plantilla
Copy-Item .env.example .env

# Editar .env con tu editor favorito
notepad .env  # Windows
# nano .env   # Linux/macOS
```

### 1.3 Generar Secrets Seguros
```powershell
# PowerShell (Windows)
$bytes = New-Object byte[] 32
(New-Object Security.Cryptography.RNGCryptoServiceProvider).GetBytes($bytes)
$secret1 = [Convert]::ToBase64String($bytes)
$bytes = New-Object byte[] 32
(New-Object Security.Cryptography.RNGCryptoServiceProvider).GetBytes($bytes)
$secret2 = [Convert]::ToBase64String($bytes)
$bytes = New-Object byte[] 32
(New-Object Security.Cryptography.RNGCryptoServiceProvider).GetBytes($bytes)
$secret3 = [Convert]::ToBase64String($bytes)
$bytes = New-Object byte[] 16
(New-Object Security.Cryptography.RNGCryptoServiceProvider).GetBytes($bytes)
$dbpass = [Convert]::ToBase64String($bytes)

Write-Host "BETTER_AUTH_SECRET=$secret1"
Write-Host "BACKEND_AUTH_SECRET=$secret2"
Write-Host "ADMIN_SECRET=$secret3"
Write-Host "POSTGRES_PASSWORD=$dbpass"

# Bash (Linux/macOS)
# openssl rand -base64 32  # BETTER_AUTH_SECRET
# openssl rand -base64 32  # BACKEND_AUTH_SECRET
# openssl rand -base64 32  # ADMIN_SECRET
# openssl rand -base64 16  # POSTGRES_PASSWORD
```

### 1.4 Configurar .env (CRÍTICO)

Edita `C:\Users\Sebitas\ViraClip\.env` y cambia:

```bash
# ═══ SEGURIDAD (CAMBIAR TODOS) ═══
BETTER_AUTH_SECRET=<pegar secret1 aquí>
BACKEND_AUTH_SECRET=<pegar secret2 aquí>
ADMIN_SECRET=<pegar secret3 aquí>
POSTGRES_PASSWORD=<pegar dbpass aquí>
REDIS_PASSWORD=<generar otro secret>

# ═══ APIS PRINCIPALES ═══
GROQ_API_KEY=gsk_...                    # Obligatorio para LLM
ASSEMBLY_AI_API_KEY=...                 # Opcional (Whisper local funciona)
PEXELS_API_KEY=...                      # Recomendado para B-roll

# ═══ URLS PRODUCCIÓN ═══
NEXT_PUBLIC_API_URL=http://localhost:8000     # Cambiar en prod
NEXT_PUBLIC_APP_URL=http://localhost:3000     # Cambiar en prod
CORS_ORIGINS=http://localhost:3000            # Añadir dominios prod
```

**APIs gratuitas recomendadas:**
- Groq: https://console.groq.com (Llama 3.3 70B gratis)
- Pexels: https://www.pexels.com/api/ (200 req/hora gratis)

---

## 🛠️ Paso 2: Build y Deploy (10 min)

### 2.1 Validar Configuración
```powershell
# Ejecutar validación automática
.\scripts\validate-production.ps1

# Si hay errores, corregir y volver a validar
```

### 2.2 Build de Imágenes
```powershell
# Primera vez (15-20 min) - descarga dependencias
docker compose build --no-cache

# Posteriores builds (~2-3 min)
docker compose build
```

### 2.3 Iniciar Servicios
```powershell
# Iniciar todo (recomendado)
docker compose up -d

# O iniciar por fases (más control):
docker compose up -d postgres redis
timeout /t 30  # Esperar healthchecks
docker compose up -d backend worker worker-2 worker-3 ollama
timeout /t 60  # Esperar backend ready
docker compose up -d frontend
```

### 2.4 Verificar Estado
```powershell
# Ver todos los servicios
docker compose ps

# Deberías ver:
# ✅ viraclip-backend     (healthy)
# ✅ viraclip-frontend    (healthy)
# ✅ viraclip-postgres    (healthy)
# ✅ viraclip-redis       (healthy)
# ✅ viraclip-worker      (healthy)
# ✅ viraclip-worker-2    (healthy)
# ✅ viraclip-worker-3    (healthy)
# ✅ viraclip-ollama      (healthy)
# ⚠️ viraclip-nginx       (puede estar unhealthy inicialmente)
```

---

## 🧪 Paso 3: Verificación (3 min)

### 3.1 Healthchecks
```powershell
# Backend
curl http://localhost:8000/health/db
# Esperado: {"status":"healthy","database":"connected"}

# Frontend
curl http://localhost:3000/
# Esperado: HTML página principal
```

### 3.2 Logs (Buscar Errores)
```powershell
# Ver logs en tiempo real
docker compose logs -f backend

# Buscar errores recientes
docker compose logs backend | Select-String -Pattern "ERROR"
docker compose logs worker | Select-String -Pattern "ERROR"
```

### 3.3 Test Funcional
1. Abrir navegador: http://localhost:3000
2. Crear cuenta de prueba
3. Subir video corto (30-60s)
4. Verificar generación de clips
5. Revisar logs de worker: `docker compose logs worker -f`

---

## 🎯 Configuración Opcional

### GPU Support (NVIDIA)
```powershell
# Activar workers GPU
docker compose --profile gpu up -d gpu_worker comfyui

# Verificar
nvidia-smi  # Debe mostrar GPU
```

### Escalado de Workers
```powershell
# Añadir más workers (si tienes CPU potente)
docker compose up -d --scale worker=5
```

### Monitoring
```bash
# Ver uso de recursos
docker stats

# Ver logs combinados
docker compose logs -f --tail=100
```

---

## 🔧 Troubleshooting Común

### Problema: Workers no procesan tareas
```powershell
# Verificar Redis
docker exec viraclip-redis redis-cli ping
# Esperado: PONG

# Reiniciar workers
docker compose restart worker worker-2 worker-3
```

### Problema: Frontend no carga
```powershell
# Ver logs
docker compose logs frontend

# Rebuild si es necesario
docker compose up -d --build frontend
```

### Problema: PostgreSQL no inicia
```powershell
# Verificar permisos volumen
docker volume inspect viraclip_postgres_data

# Recrear si es necesario
docker compose down
docker volume rm viraclip_postgres_data
docker compose up -d postgres
```

### Problema: Falta espacio en disco
```powershell
# Limpiar imágenes antiguas
docker system prune -a --volumes

# Ver uso
docker system df
```

---

## 📊 Comandos Útiles

```powershell
# Ver todos los servicios
docker compose ps

# Reiniciar todo
docker compose restart

# Detener todo
docker compose down

# Detener y eliminar volúmenes (CUIDADO: borra datos)
docker compose down -v

# Ver logs de un servicio
docker compose logs -f backend

# Ejecutar comando en contenedor
docker exec -it viraclip-backend bash

# Ver uso de recursos
docker stats

# Backup PostgreSQL
docker exec viraclip-postgres pg_dump -U viraclip viraclip > backup.sql

# Restaurar PostgreSQL
cat backup.sql | docker exec -i viraclip-postgres psql -U viraclip viraclip
```

---

## 🔒 Seguridad Post-Deploy

### Checklist Mínimo
- [ ] Passwords cambiados de default
- [ ] Redis con password configurado
- [ ] Secrets únicos generados
- [ ] `.env` no commiteado a Git
- [ ] Firewall configurado (solo puertos necesarios)
- [ ] Backup automático configurado

### Producción Pública
- [ ] SSL/TLS configurado (Let's Encrypt)
- [ ] Reverse proxy (nginx/Traefik)
- [ ] Rate limiting activado
- [ ] Monitoring configurado
- [ ] Alertas configuradas

---

## 📚 Recursos Adicionales

- **Evaluación completa:** `EVALUATION_PRODUCCION_2026-04-12.md`
- **Checklist producción:** `PRODUCTION_CHECKLIST.md`
- **Guía detallada:** `DEPLOY_GUIDE.md`
- **Roadmap features:** `ROADMAP.md`
- **Testing:** `TESTING_GUIDE.md`

---

## 🆘 Soporte

**Si algo falla:**
1. Ejecutar: `.\scripts\validate-production.ps1`
2. Revisar logs: `docker compose logs`
3. Consultar: `TROUBLESHOOTING.md`
4. GitHub Issues: https://github.com/sebsv123/ViraClip/issues

---

**¡Listo para crear clips virales! 🎬✨**
