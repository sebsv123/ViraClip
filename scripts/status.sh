#!/bin/bash
# ViraClip — Estado del sistema en un comando

echo "=== CONTAINERS ==="
docker ps --format "table {{.Names}}\t{{.Status}}" | grep viraclip || echo "No viraclip containers running"

echo ""
echo "=== REDIS QUEUE ==="
docker exec viraclip-redis redis-cli KEYS "arq:*" 2>/dev/null | sort || echo "Redis not available"

echo ""
echo "=== ÚLTIMAS 30 LÍNEAS DE LOG ==="
docker exec viraclip-worker tail -30 /app/logs/backend.log 2>/dev/null | python3 -c "
import sys, json
for line in sys.stdin:
    try:
        d = json.loads(line)
        ts = d.get('timestamp', '')[11:19] if 'timestamp' in d else '???:???:???'
        level = d.get('level', 'INFO')
        logger = d.get('logger', '').split('.')[-1] if 'logger' in d else 'unknown'
        msg = d.get('message', '')[:120]
        print(f'{ts} [{level}] {logger}: {msg}')
    except:
        print(line.rstrip())
" || echo "Worker log not available"

echo ""
echo "=== EXPORTS RECIENTES ==="
ls -lt exports/clips/*.mp4 2>/dev/null | head -5 || echo "No exports found"
