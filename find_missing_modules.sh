#!/bin/bash
# Encontrar TODOS los módulos faltantes del backend

PYTHON_BIN="$HOME/CascadeProjects/ViraClip/backend/.venv/bin/python3"
BACKEND="$HOME/CascadeProjects/ViraClip/backend"

cd "$BACKEND"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PASO 1 — Imports de video_service.py (líneas 1-70)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
head -70 src/services/video_service.py
echo ""

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PASO 2 — Escaneo exhaustivo de imports faltantes"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

"$PYTHON_BIN" << 'PYEOF' 2>&1
import ast
import sys
import os
from pathlib import Path

backend_dir = Path(os.path.expanduser('~/CascadeProjects/ViraClip/backend'))
src_dir = backend_dir / 'src'
os.chdir(backend_dir)

# Añadir rutas para que las importaciones relativas funcionen
sys.path.insert(0, str(backend_dir))
sys.path.insert(0, str(src_dir))

# Recoger todos los archivos .py del src/
py_files = sorted(src_dir.rglob('*.py'))
print(f"Archivos Python analizados: {len(py_files)}")
print()

missing_by_target = {}   # {módulo_faltante: [archivos que lo importan]}

for pyfile in py_files:
    try:
        tree = ast.parse(pyfile.read_text(encoding='utf-8'))
    except Exception as e:
        continue

    # Calcular el paquete de este archivo para resolver imports relativos
    rel = pyfile.relative_to(backend_dir)
    pkg_parts = rel.parts[:-1]  # todas menos el nombre del archivo
    pkg = '.'.join(pkg_parts)   # ej. 'src.services'

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue

        # Resolver el nombre completo del módulo importado
        if isinstance(node, ast.ImportFrom):
            module = node.module or ''
            level = node.level or 0
            if level > 0:
                # Import relativo: .foo, ..bar, etc.
                base_parts = list(pkg_parts[:-level+1]) if level > 1 else list(pkg_parts)
                # Mejor: ir hacia arriba 'level' niveles
                base_parts = list(pkg_parts[:len(pkg_parts) - (level - 1)])
                if module:
                    full_mod = '.'.join(base_parts + [module])
                else:
                    full_mod = '.'.join(base_parts)
            else:
                full_mod = module

            # Solo nos interesan imports internos del proyecto
            if not (full_mod.startswith('src.') or full_mod.startswith('src')):
                # Imports absolutos que no empiecen con src, pero que puedan ser del proyecto
                first_part = full_mod.split('.')[0]
                if first_part not in {'services', 'models', 'repositories',
                                       'utils', 'api', 'config', 'core',
                                       'workers', 'clip_editor', 'schemas',
                                       'db', 'auth', 'comfy_nodes', 'exceptions'}:
                    continue

            # Intentar importar
            try:
                __import__(full_mod)
            except ModuleNotFoundError as e:
                # Mensaje típico: "No module named 'xyz'"
                err_str = str(e)
                missing_by_target.setdefault(err_str, []).append(str(pyfile.relative_to(backend_dir)))
            except Exception:
                # Otros errores (SyntaxError, etc.) los ignoramos por ahora
                pass

# Imprimir por módulo faltante
if not missing_by_target:
    print("✅ No se encontraron imports faltantes")
else:
    print(f"Total errores únicos de import: {len(missing_by_target)}")
    print()
    # Ordenar por número de archivos afectados (los más críticos primero)
    sorted_missing = sorted(
        missing_by_target.items(),
        key=lambda kv: (-len(kv[1]), kv[0])
    )
    for err, files in sorted_missing:
        print(f"❌ {err}")
        for f in sorted(set(files))[:5]:
            print(f"     └─ {f}")
        if len(set(files)) > 5:
            print(f"     ... ({len(set(files)) - 5} archivo(s) más)")
        print()
PYEOF

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PASO 3 — Archivos .py que SÍ existen en services/"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
ls "$BACKEND/src/services/"*.py 2>/dev/null | xargs -I{} basename {} | sort
echo ""
echo "Subdirectorios de services/:"
find "$BACKEND/src/services/" -maxdepth 2 -type d | tail -n +2
echo ""

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PASO 4 — Usos de SocialDistribution en video_service.py"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
grep -n "social_distribution\|SocialDistribution" "$BACKEND/src/services/video_service.py"
echo ""

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "PASO 5 — Verificación: ¿ya compila video_service.py?"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
cd "$BACKEND"
"$PYTHON_BIN" -c "
import sys
sys.path.insert(0, 'src')
sys.path.insert(0, '.')
try:
    from src.services import video_service
    print('✅ video_service.py importa sin errores')
except ModuleNotFoundError as e:
    print(f'❌ Siguiente módulo faltante: {e}')
except Exception as e:
    print(f'⚠️  Otro error: {type(e).__name__}: {e}')
" 2>&1
