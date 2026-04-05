#!/bin/bash
set -e

# ViraClip Complete Setup Script — Phase 6-7-8
# =============================================
# Descarga datasets, inicializa ComfyUI, y verifica toda la configuración

echo ""
echo "=========================================="
echo "  ViraClip Complete Setup — Phase 6-7-8"
echo "=========================================="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Verificar que estamos en la raíz del proyecto
if [ ! -f "docker-compose.yml" ]; then
    echo -e "${RED}❌ Error: Ejecuta este script desde la raíz del proyecto ViraClip${NC}"
    exit 1
fi

# Verificar .env existe
if [ ! -f "backend/.env" ]; then
    echo -e "${YELLOW}⚠ .env no encontrado, copiando desde .env.example...${NC}"
    cp backend/.env.example backend/.env
    echo -e "${GREEN}✅ Creado backend/.env${NC}"
    echo -e "${YELLOW}⚠ IMPORTANTE: Configura tus API keys en backend/.env antes de continuar${NC}"
    echo ""
    echo "Tokens necesarios:"
    echo "  - HF_TOKEN (HuggingFace) - https://huggingface.co/settings/tokens"
    echo "  - KAGGLE_USERNAME + KAGGLE_KEY (opcional)"
    echo "  - OPENAI_API_KEY o GOOGLE_API_KEY (para LLM)"
    echo ""
    read -p "Presiona Enter cuando hayas configurado los tokens..."
fi

echo ""
echo "=========================================="
echo "Paso 1: Verificando Dependencias"
echo "=========================================="

# Verificar Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker no instalado${NC}"
    echo "   Instala Docker desde: https://docs.docker.com/get-docker/"
    exit 1
fi
echo -e "${GREEN}✅ Docker instalado${NC}"

# Verificar Docker Compose
if ! command -v docker-compose &> /dev/null; then
    echo -e "${RED}❌ Docker Compose no instalado${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Docker Compose instalado${NC}"

echo ""
echo "=========================================="
echo "Paso 2: Construyendo Containers"
echo "=========================================="

echo "Construyendo imágenes (esto puede tomar 10-15 min)..."
docker-compose build --no-cache backend worker

echo -e "${GREEN}✅ Containers construidos${NC}"

echo ""
echo "=========================================="
echo "Paso 3: Iniciando Servicios Base"
echo "=========================================="

# Iniciar servicios base primero
docker-compose up -d postgres redis ollama

echo "Esperando a que Postgres esté listo..."
sleep 10

# Verificar Postgres
if docker-compose exec -T postgres pg_isready -U viraclip > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Postgres listo${NC}"
else
    echo -e "${YELLOW}⚠ Postgres aún iniciando, esperando...${NC}"
    sleep 10
fi

echo ""
echo "=========================================="
echo "Paso 4: Descargando Datasets (Fase 7)"
echo "=========================================="

# Verificar si HF_TOKEN está configurado
HF_TOKEN=$(grep "^HF_TOKEN=" backend/.env | cut -d '=' -f2)

if [ -z "$HF_TOKEN" ]; then
    echo -e "${YELLOW}⚠ HF_TOKEN no configurado en .env${NC}"
    echo "   Skipping dataset download. Para descargar datasets:"
    echo "   1. Obtén token en https://huggingface.co/settings/tokens"
    echo "   2. Añádelo a backend/.env: HF_TOKEN=hf_..."
    echo "   3. Ejecuta: docker-compose run --rm backend python scripts/download_datasets.py --all"
else
    echo "Descargando TikTok-Videos dataset desde HuggingFace..."
    docker-compose run --rm backend python scripts/download_datasets.py --tiktok-only || {
        echo -e "${YELLOW}⚠ Dataset download falló (puede requerir login HF)${NC}"
        echo "   Continúa sin datasets - puedes descargar después"
    }
fi

echo ""
echo "=========================================="
echo "Paso 5: Inicializando ComfyUI (Fase 6)"
echo "=========================================="

# Copiar workflows a ComfyUI
echo "Copiando workflows de ViraClip a ComfyUI..."
docker-compose run --rm backend python scripts/init_comfyui_workflows.py || {
    echo -e "${YELLOW}⚠ Workflow init falló - ejecuta manualmente después${NC}"
}

echo ""
echo "=========================================="
echo "Paso 6: Iniciando Todos los Servicios"
echo "=========================================="

docker-compose up -d

echo "Esperando a que servicios estén listos..."
sleep 15

echo ""
echo "=========================================="
echo "Paso 7: Verificando Health Checks"
echo "=========================================="

# Backend health
if curl -s http://localhost:8000/health | grep -q "ok"; then
    echo -e "${GREEN}✅ Backend healthy (http://localhost:8000)${NC}"
else
    echo -e "${YELLOW}⚠ Backend aún iniciando...${NC}"
fi

# Frontend
if curl -s http://localhost:3000 > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Frontend running (http://localhost:3000)${NC}"
else
    echo -e "${YELLOW}⚠ Frontend aún iniciando...${NC}"
fi

# ComfyUI
if curl -s http://localhost:8188/system_stats > /dev/null 2>&1; then
    echo -e "${GREEN}✅ ComfyUI running (http://localhost:8188)${NC}"
else
    echo -e "${YELLOW}⚠ ComfyUI aún iniciando (puede tomar 2-3 min)...${NC}"
fi

echo ""
echo "=========================================="
echo "Paso 8: Verificando Custom Nodes ComfyUI"
echo "=========================================="

# Esperar a ComfyUI
sleep 5

# Verificar custom nodes
if curl -s http://localhost:8188/object_info 2>/dev/null | grep -q "ViraClip"; then
    echo -e "${GREEN}✅ Custom nodes ViraClip registrados en ComfyUI${NC}"
else
    echo -e "${YELLOW}⚠ Custom nodes no detectados - verifica logs${NC}"
    echo "   Ejecuta: docker-compose logs comfyui | grep -i viraclip"
fi

echo ""
echo "=========================================="
echo "✅ Setup Completado"
echo "=========================================="
echo ""
echo "Servicios disponibles:"
echo "  • Frontend:  http://localhost:3000"
echo "  • Backend:   http://localhost:8000"
echo "  • ComfyUI:   http://localhost:8188"
echo "  • Swagger:   http://localhost:8000/docs"
echo ""
echo "Próximos pasos:"
echo "  1. Abre ComfyUI: http://localhost:8188"
echo "  2. Carga workflow: viral_clip_basic.json"
echo "  3. Verifica nodos en categoría 'ViraClip'"
echo "  4. Crea tu primer clip desde: http://localhost:3000"
echo ""
echo "Verificar status:"
echo "  docker-compose ps"
echo "  docker-compose logs -f backend"
echo ""
echo "Descargar datasets (si saltaste):"
echo "  docker-compose run --rm backend python scripts/download_datasets.py --all"
echo ""
echo "Troubleshooting:"
echo "  Ver logs: docker-compose logs -f [service]"
echo "  Reiniciar: docker-compose restart [service]"
echo "  Rebuild: docker-compose build --no-cache [service]"
echo ""
echo "Documentación completa: DEPLOY_GUIDE.md"
echo ""
