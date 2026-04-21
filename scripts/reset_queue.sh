#!/bin/bash
# ViraClip — Limpia locks fantasma de Redis

echo "Limpiando locks fantasma..."

# Limpiar arq:in-progress keys
IN_PROGRESS=$(docker exec viraclip-redis redis-cli KEYS "arq:in-progress:*" 2>/dev/null)
if [ -n "$IN_PROGRESS" ]; then
    echo "$IN_PROGRESS" | xargs -r docker exec -i viraclip-redis redis-cli DEL
    echo "✓ Cleared in-progress locks"
else
    echo "✓ No in-progress locks found"
fi

# Limpiar arq:retry keys
RETRY=$(docker exec viraclip-redis redis-cli KEYS "arq:retry:*" 2>/dev/null)
if [ -n "$RETRY" ]; then
    echo "$RETRY" | xargs -r docker exec -i viraclip-redis redis-cli DEL
    echo "✓ Cleared retry keys"
else
    echo "✓ No retry keys found"
fi

# Mostrar estado final
echo ""
echo "=== Estado actual de Redis ==="
docker exec viraclip-redis redis-cli KEYS "arq:*" 2>/dev/null | sort || echo "Redis not available"

echo ""
echo "Queue limpia. Listo para procesar."
