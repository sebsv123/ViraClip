#!/usr/bin/env python3
"""
ComfyUI Workflow Initializer — Phase 6
=======================================
Copia workflows de ViraClip a ComfyUI y verifica custom nodes.

Usage:
    python scripts/init_comfyui_workflows.py
"""

import os
import sys
import json
import shutil
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
WORKFLOWS_SRC = PROJECT_ROOT / "workflows"
COMFYUI_WORKFLOWS_DEST = Path("/ComfyUI/workflows") if Path("/ComfyUI").exists() else PROJECT_ROOT / "comfyui_workflows"
CUSTOM_NODES_SRC = PROJECT_ROOT / "backend" / "src" / "comfy_nodes"
COMFYUI_CUSTOM_NODES = Path("/ComfyUI/custom_nodes/viraclip_nodes") if Path("/ComfyUI").exists() else None


def copy_workflows():
    """Copia workflows JSON a directorio de ComfyUI."""
    logger.info("=" * 60)
    logger.info("Copiando workflows a ComfyUI...")
    logger.info("=" * 60)
    
    COMFYUI_WORKFLOWS_DEST.mkdir(exist_ok=True, parents=True)
    
    workflows = [
        "viral_clip_basic.json",
        "viral_clip_with_broll.json",
        "viral_clip_generative.json",
        "viral_clip_quantum_inspired.json",
        "viral_clip_swarm_evolution.json"
    ]
    
    copied = 0
    for workflow_file in workflows:
        src = WORKFLOWS_SRC / workflow_file
        dest = COMFYUI_WORKFLOWS_DEST / workflow_file
        
        if not src.exists():
            logger.warning(f"⚠ No encontrado: {src}")
            continue
        
        try:
            shutil.copy2(src, dest)
            
            # Verificar JSON válido
            with open(dest, 'r') as f:
                data = json.load(f)
            
            logger.info(f"✅ {workflow_file:<40} → {dest}")
            copied += 1
            
        except Exception as e:
            logger.error(f"❌ Error copiando {workflow_file}: {e}")
    
    logger.info(f"\n📊 Workflows copiados: {copied}/{len(workflows)}")
    return copied


def verify_custom_nodes():
    """Verifica que custom nodes estén disponibles."""
    logger.info("\n" + "=" * 60)
    logger.info("Verificando custom nodes de ViraClip...")
    logger.info("=" * 60)
    
    required_files = [
        "__init__.py",
        "viraclip_nodes.py",
        "viraclip_training_nodes.py",
        "viraclip_advanced_ml.py"
    ]
    
    all_exist = True
    
    for file_name in required_files:
        src_path = CUSTOM_NODES_SRC / file_name
        exists = src_path.exists()
        
        status = "✅" if exists else "❌"
        logger.info(f"{status} {file_name:<35} ({src_path})")
        
        if not exists:
            all_exist = False
    
    if all_exist:
        logger.info("\n✅ Todos los custom nodes están presentes")
        logger.info(f"   Montados en: {COMFYUI_CUSTOM_NODES or 'docker volume'}")
    else:
        logger.error("\n❌ Faltan algunos custom nodes")
        logger.error("   Verifica que backend/src/comfy_nodes/ esté completo")
    
    return all_exist


def verify_node_mappings():
    """Verifica que NODE_CLASS_MAPPINGS esté correctamente definido."""
    logger.info("\n" + "=" * 60)
    logger.info("Verificando NODE_CLASS_MAPPINGS...")
    logger.info("=" * 60)
    
    init_file = CUSTOM_NODES_SRC / "__init__.py"
    
    if not init_file.exists():
        logger.error(f"❌ No encontrado: {init_file}")
        return False
    
    try:
        with open(init_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verificar imports
        required_imports = [
            "viraclip_nodes",
            "viraclip_training_nodes",
            "viraclip_advanced_ml"
        ]
        
        for module in required_imports:
            if module in content:
                logger.info(f"✅ Import encontrado: {module}")
            else:
                logger.warning(f"⚠ Import faltante: {module}")
        
        # Verificar NODE_CLASS_MAPPINGS
        if "NODE_CLASS_MAPPINGS" in content:
            logger.info("✅ NODE_CLASS_MAPPINGS definido")
        else:
            logger.error("❌ NODE_CLASS_MAPPINGS no definido")
            return False
        
        # Contar nodos
        node_count = content.count("Node\":")
        logger.info(f"📊 Nodos registrados: ~{node_count}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Error leyendo __init__.py: {e}")
        return False


def create_comfyui_readme():
    """Crea README para usuarios de ComfyUI."""
    readme_content = """# ViraClip Custom Nodes for ComfyUI

## Nodes Disponibles

### Core Pipeline Nodes
- **ViraClipWhisperNode** - Transcripción con Whisper + virality scoring
- **ViraClipYOLONode** - Detección de objetos para B-roll keywords
- **ViraClipSilenceRemovalNode** - Jump cuts automáticos
- **ViraClipThumbnailNode** - Selección inteligente de thumbnail
- **ViraClipMetadataNode** - Generación de títulos SEO + hashtags

### Training Nodes (GPU Required)
- **ViraClipLoRATrainerNode** - Entrenamiento de LoRAs de estilo viral
- **ViraClipDatasetPrepNode** - Preparación de datasets para training

### Advanced ML Nodes (Phase 8)
- **QuantumInspiredViralityNode** - Simulador de viralidad cuántico-inspirado
- **SwarmEvolutionViralityNode** - Optimización evolutiva con algoritmos genéticos

## Workflows Incluidos

1. **viral_clip_basic.json**
   - Pipeline básico: Whisper → Silence removal → Metadata → Thumbnail
   - CPU-only, no requiere GPU

2. **viral_clip_with_broll.json**
   - Pipeline + YOLO object detection para B-roll
   - CPU-only

3. **viral_clip_generative.json**
   - Pipeline + Wan2.2 generative B-roll
   - **Requiere GPU 8GB+**

4. **viral_clip_quantum_inspired.json**
   - Simulación de 100+ variantes virales en latent space
   - Retorna top-3 variantes por probabilidad
   - CPU/GPU opcional

5. **viral_clip_swarm_evolution.json**
   - Evolución de 50 genomas de clips durante 10 generaciones
   - Optimización por content type (educational, entertainment, general)
   - CPU-only

## Instalación

Los custom nodes se montan automáticamente via Docker:

```yaml
# docker-compose.yml
volumes:
  - ./backend/src/comfy_nodes:/ComfyUI/custom_nodes/viraclip_nodes
```

Después de `docker-compose up`, los nodos aparecen en categoría "ViraClip".

## Uso Vía API

```python
import httpx

# Ejecutar workflow
response = httpx.post(
    "http://localhost:8000/api/comfyui/execute/viral_clip_basic",
    json={
        "video_path": "/path/to/video.mp4",
        "platform": "tiktok"
    }
)

prompt_id = response.json()["prompt_id"]

# Verificar status
status = httpx.get(f"http://localhost:8000/api/comfyui/status/{prompt_id}")
```

## Troubleshooting

### Nodos no aparecen en ComfyUI
1. Verifica que el volumen esté montado: `docker-compose ps`
2. Reinicia ComfyUI: `docker-compose restart comfyui`
3. Revisa logs: `docker-compose logs comfyui | grep -i viraclip`

### Error "Module not found"
Instala dependencias en ComfyUI container:
```bash
docker-compose exec comfyui pip install deap matplotlib pymilvus aioredis
```

### GPU out of memory
Reduce resolución o usa `--lowvram` en CLI_ARGS:
```yaml
environment:
  - CLI_ARGS=--listen 0.0.0.0 --port 8188 --lowvram
```

## Soporte

Ver documentación completa en:
- `ROADMAP.md` - Fases 6, 7, 8
- `DEPLOY_GUIDE.md` - Guía de deployment
- `IMPLEMENTATION_SUMMARY.md` - Detalles de implementación
"""
    
    readme_path = COMFYUI_WORKFLOWS_DEST / "README_VIRACLIP.md"
    
    with open(readme_path, 'w', encoding='utf-8') as f:
        f.write(readme_content)
    
    logger.info(f"\n📝 README creado: {readme_path}")


def main():
    print("\n" + "=" * 60)
    print("   ComfyUI Workflow Initializer — Phase 6")
    print("=" * 60 + "\n")
    
    # Verificar estructura
    if not WORKFLOWS_SRC.exists():
        logger.error(f"❌ Directorio workflows no encontrado: {WORKFLOWS_SRC}")
        logger.error("   Ejecuta desde la raíz del proyecto ViraClip")
        return 1
    
    if not CUSTOM_NODES_SRC.exists():
        logger.error(f"❌ Custom nodes no encontrados: {CUSTOM_NODES_SRC}")
        return 1
    
    # Copiar workflows
    copied = copy_workflows()
    
    # Verificar custom nodes
    nodes_ok = verify_custom_nodes()
    mappings_ok = verify_node_mappings()
    
    # Crear README
    create_comfyui_readme()
    
    # Resumen
    print("\n" + "=" * 60)
    print("Resumen de Inicialización")
    print("=" * 60)
    print(f"{'✅' if copied > 0 else '❌'} Workflows copiados: {copied}")
    print(f"{'✅' if nodes_ok else '❌'} Custom nodes verificados")
    print(f"{'✅' if mappings_ok else '❌'} NODE_CLASS_MAPPINGS válido")
    print("")
    
    if copied > 0 and nodes_ok and mappings_ok:
        print("✅ Inicialización completada exitosamente")
        print("")
        print("Próximos pasos:")
        print("  1. Inicia ComfyUI: docker-compose up -d comfyui")
        print("  2. Accede a: http://localhost:8188")
        print("  3. Carga workflow: viral_clip_basic.json")
        print("  4. Verifica nodos en categoría 'ViraClip'")
        return 0
    else:
        print("⚠ Inicialización completada con advertencias")
        print("   Revisa los errores arriba")
        return 1


if __name__ == "__main__":
    sys.exit(main())
