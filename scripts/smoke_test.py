#!/usr/bin/env python3
"""
Smoke test — validates core infrastructure after cleanup operations.
Usage: python scripts/smoke_test.py
Exit code: 0 = all OK, 1 = any check failed
"""
import asyncio
import sys


async def check_postgres() -> bool:
    """Check PostgreSQL connectivity."""
    try:
        import asyncpg
        from src.config import get_config
        cfg = get_config()
        db_url = cfg.database_url.replace("postgresql+asyncpg://", "postgresql://")
        conn = await asyncpg.connect(db_url)
        val = await conn.fetchval("SELECT 1")
        await conn.close()
        return val == 1
    except Exception as e:
        print(f"  ✗ PostgreSQL — FAILED: {e}")
        return False


async def check_redis() -> bool:
    """Check Redis connectivity."""
    try:
        import redis.asyncio as aioredis
        from src.config import get_config
        cfg = get_config()
        r = aioredis.Redis(host=cfg.redis_host, port=cfg.redis_port, password=cfg.redis_password or None, decode_responses=True)
        pong = await r.ping()
        await r.aclose()
        return bool(pong)
    except Exception as e:
        print(f"  ✗ Redis — FAILED: {e}")
        return False


async def check_worker_health() -> bool:
    """Check ARQ worker health via Redis."""
    try:
        import redis.asyncio as aioredis
        from src.config import get_config
        cfg = get_config()
        r = aioredis.Redis(host=cfg.redis_host, port=cfg.redis_port, password=cfg.redis_password or None, decode_responses=True)
        health = await r.hgetall("arq:health:viraclip_cpu_tasks")
        await r.aclose()
        workers = int(health.get("workers", 0)) if health else 0
        print(f"  ✓ Worker ARQ — {workers} workers active")
        return True
    except Exception as e:
        print(f"  ✗ Worker ARQ — FAILED: {e}")
        return False


def check_imports() -> bool:
    """Check critical imports work without error."""
    ok = True
    checks = [
        ("src.domains.ai.llm_router", "LLMRouter"),
        ("src.domains.broll.broll_service", "BrollService"),
        ("src.workers.tasks", "cleanup_stale_tasks"),
        ("src.domains.longform.longform_coordinator", "create_longform_video"),
        ("src.domains.sfx.sfx_orchestrator", "SFXOrchestrator"),
        ("src.domains.detection.visual_keyword_detector", "VisualKeywordDetector"),
    ]
    for module_path, symbol in checks:
        try:
            mod = __import__(module_path, fromlist=[symbol])
            getattr(mod, symbol)
            print(f"  ✓ {module_path}.{symbol} — OK")
        except Exception as e:
            print(f"  ✗ {module_path}.{symbol} — FAILED: {e}")
            ok = False
    return ok


async def main():
    print("=" * 50)
    print("  ViraClip Smoke Test")
    print("=" * 50)
    print()

    results = []

    print("[1/5] PostgreSQL connectivity...")
    results.append(("PostgreSQL", await check_postgres()))

    print("[2/5] Redis connectivity...")
    results.append(("Redis", await check_redis()))

    print("[3/5] Worker ARQ health...")
    results.append(("Worker ARQ", await check_worker_health()))

    print("[4/5] Critical imports...")
    results.append(("Imports", check_imports()))

    print()
    print("=" * 50)
    print("  RESULTS")
    print("=" * 50)
    all_ok = True
    for name, ok in results:
        status = "✓ OK" if ok else "✗ FAILED"
        print(f"  {status} — {name}")
        if not ok:
            all_ok = False

    print()
    if all_ok:
        print("  ✅ ALL CHECKS PASSED")
    else:
        print("  ❌ SOME CHECKS FAILED")
    print()

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
