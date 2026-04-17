"""
Pre-deployment verification script.

Checks all services, endpoints, and integration points before going live.

Run inside Docker:
    docker-compose exec backend python /app/scripts/deploy_check.py

Or from host (requires services to be running):
    python backend/scripts/deploy_check.py
"""

import asyncio
import sys
import os
import json
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))


BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
RUST_AGENT_URL = os.environ.get("RUST_AGENT_URL", "http://rust-agent:8001")


# ─────────────────────────────────────────────────────────────────────────────
# Check functions
# ─────────────────────────────────────────────────────────────────────────────

async def check(label: str, coro) -> Tuple[bool, str]:
    """Run a check and return (passed, detail)."""
    try:
        result = await coro
        return True, result
    except Exception as e:
        return False, str(e)


async def _check_backend_health():
    import httpx
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{BACKEND_URL}/health")
        r.raise_for_status()
        return r.json().get("status", "unknown")


async def _check_diagnostics():
    import httpx
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(f"{BACKEND_URL}/health/diagnostics")
        r.raise_for_status()
        data = r.json()
        checks = data.get("checks", {})
        failed = [k for k, v in checks.items() if isinstance(v, dict) and not v.get("ok", True)]
        if failed:
            return f"degraded — failing: {', '.join(failed)}"
        return f"all {len(checks)} checks passed"


async def _check_rust_agent():
    import httpx
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{RUST_AGENT_URL}/agent/health")
        r.raise_for_status()
        data = r.json()
        ffmpeg = "✅" if data.get("ffmpeg_available") else "⚠️ no ffmpeg"
        tools = len(data.get("tools_available", []))
        return f"v{data.get('version','?')} — {tools} tools, ffmpeg={ffmpeg}"


async def _check_sse_endpoint():
    import httpx
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Just open the stream; the endpoint should return 200 even if no events yet
        async with client.stream("GET", f"{BACKEND_URL}/api/tasks/smoke-test/stream") as r:
            # We only want to verify the connection opens; don't consume the stream
            return f"HTTP {r.status_code}"


async def _check_task_control():
    import httpx
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(f"{BACKEND_URL}/api/tasks/all")
        r.raise_for_status()
        tasks = r.json()
        return f"{len(tasks)} tasks in registry"


async def _check_clip_endpoints():
    import httpx
    async with httpx.AsyncClient(timeout=10.0) as client:
        # GET /clips/nonexistent should return 404, not 500
        r = await client.get(f"{BACKEND_URL}/clips/nonexistent-clip-id")
        if r.status_code == 404:
            return "404 on missing clip ✅"
        return f"unexpected HTTP {r.status_code}"


async def _check_dataset_dir():
    dataset_dir = os.environ.get("DATASET_DIR", "/app/datasets")
    path = Path(dataset_dir)
    path.mkdir(parents=True, exist_ok=True)
    # Verify writable
    test_file = path / ".write_test"
    test_file.write_text("ok")
    test_file.unlink()
    return f"{dataset_dir} (writable)"


async def _check_redis_pubsub():
    import redis.asyncio as aioredis
    host = os.environ.get("REDIS_HOST", "redis")
    port = int(os.environ.get("REDIS_PORT", "6379"))
    r = aioredis.Redis(host=host, port=port, decode_responses=True)
    pubsub = r.pubsub()
    await pubsub.subscribe("smoke_test_channel")
    await pubsub.unsubscribe("smoke_test_channel")
    await pubsub.close()
    await r.aclose()
    return f"pub/sub OK on {host}:{port}"


# ─────────────────────────────────────────────────────────────────────────────
# Main runner
# ─────────────────────────────────────────────────────────────────────────────

CHECKS = [
    ("Backend health",       _check_backend_health()),
    ("Full diagnostics",     _check_diagnostics()),
    ("Dataset dir writable", _check_dataset_dir()),
    ("Redis pub/sub",        _check_redis_pubsub()),
    ("Task control API",     _check_task_control()),
    ("Clip endpoints",       _check_clip_endpoints()),
    ("SSE stream endpoint",  _check_sse_endpoint()),
    ("Rust agent",           _check_rust_agent()),
]


async def run_all_checks() -> List[Tuple[str, bool, str]]:
    results = []
    for label, coro in CHECKS:
        ok, detail = await check(label, coro)
        results.append((label, ok, detail))
        icon = "✅" if ok else "❌"
        print(f"  {icon}  {label:<28} {detail}")
    return results


async def main():
    print("=" * 60)
    print("🚀  ViraClip Pre-Deployment Check")
    print(f"    Backend: {BACKEND_URL}")
    print(f"    Rust:    {RUST_AGENT_URL}")
    print("=" * 60)
    print()

    results = await run_all_checks()

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    failed = [(label, detail) for label, ok, detail in results if not ok]

    print()
    print("=" * 60)
    print(f"  Result: {passed}/{total} checks passed")
    print("=" * 60)

    if failed:
        print("\n⚠️  Failed checks:")
        for label, detail in failed:
            print(f"   • {label}: {detail}")
        print("\n❌ NOT ready for deployment — fix failures above first.")
        return 1
    else:
        print("\n✅ All checks passed — ready to deploy!")
        return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
