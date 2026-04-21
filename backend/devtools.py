#!/usr/bin/env python3
"""
ViraClip DevTools — ejecutar con:
  docker exec viraclip-worker /app/.venv/bin/python3 /app/devtools.py <comando>

Comandos:
  queue-status     → estado completo de arq en Redis
  job-result <id>  → decodifica el resultado de un job
  flush-queue      → limpia arq:queue (con confirmación)
  test-task <url>  → crea y monitorea un task de prueba
  arq-version      → versión de arq y configuración de WorkerSettings
"""
import sys, os
sys.path.insert(0, '/app')

def queue_status():
    import redis as redis_lib
    r = redis_lib.Redis(host=os.getenv('REDIS_HOST','viraclip-redis'), port=6379, decode_responses=True)
    print("=== ARQ QUEUE STATUS ===")
    print(f"arq:queue depth     : {r.zcard('arq:queue')}")
    print(f"in-progress         : {len(r.keys('arq:in-progress:*'))}")
    print(f"retry               : {len(r.keys('arq:retry:*'))}")
    print(f"results stored      : {len(r.keys('arq:result:*'))}")
    print(f"all arq keys        :")
    for k in sorted(r.keys('arq:*')): print(f"  {k}")

def job_result(job_id):
    import redis as redis_lib, msgpack
    r = redis_lib.Redis(host=os.getenv('REDIS_HOST','viraclip-redis'), port=6379)
    raw = r.get(f'arq:result:{job_id}')
    if not raw:
        print(f"No result found for job {job_id}")
        return
    try:
        unpacker = msgpack.Unpacker(raw=False, strict_map_key=False)
        unpacker.feed(raw)
        parts = list(unpacker)
        labels = ['function','args','kwargs','job_try','enqueue_time','score','success','result','start_time','finish_time','queue_name']
        for i, val in enumerate(parts):
            label = labels[i] if i < len(labels) else f'field_{i}'
            print(f"  {label:15}: {val}")
    except Exception as e:
        print(f"Raw bytes: {raw[:200]}")
        print(f"Error: {e}")

def flush_queue():
    import redis as redis_lib
    r = redis_lib.Redis(host=os.getenv('REDIS_HOST','viraclip-redis'), port=6379, decode_responses=True)
    depth = r.zcard('arq:queue')
    if depth == 0:
        print("Queue already empty (depth=0)")
        return
    print(f"WARNING: This will delete {depth} pending jobs from arq:queue")
    confirm = input("Type 'yes' to confirm: ")
    if confirm == 'yes':
        r.delete('arq:queue')
        # Also clean up any named queues
        for key in r.keys('arq:queue:*'):
            r.delete(key)
        print("Queue flushed.")
    else:
        print("Cancelled.")

def arq_version():
    import arq, importlib.metadata
    print(f"arq version: {importlib.metadata.version('arq')}")
    from src.workers.tasks import WorkerSettings
    ws = WorkerSettings
    print(f"queue_name : {getattr(ws, 'queue_name', 'DEFAULT (arq:queue)')}")
    print(f"max_jobs   : {getattr(ws, 'max_jobs', 'default')}")
    print(f"job_timeout: {getattr(ws, 'job_timeout', 'default')}")
    print(f"max_tries  : {getattr(ws, 'max_tries', 'default')}")
    print(f"functions  : {[f.__name__ if callable(f) else f for f in ws.functions]}")

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'queue-status'
    if cmd == 'queue-status': queue_status()
    elif cmd == 'job-result' and len(sys.argv) > 2: job_result(sys.argv[2])
    elif cmd == 'flush-queue': flush_queue()
    elif cmd == 'arq-version': arq_version()
    else: print(__doc__)
