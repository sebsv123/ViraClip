"""
Performance benchmark: Rust agent vs Python FFmpeg rendering.

Run inside Docker:
    docker-compose exec backend python /app/scripts/benchmark_ffmpeg.py

Requirements:
    - Backend + Rust agent both running
    - A test video at /app/temp/benchmark_test.mp4
      (creates a synthetic one if missing)
"""

import asyncio
import json
import time
import tempfile
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

async def create_test_video(path: str, duration: int = 60) -> bool:
    """Create a synthetic test video using FFmpeg."""
    import subprocess
    result = subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=blue:size=1920x1080:rate=30:duration={duration}",
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=60",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac",
        "-t", str(duration),
        path
    ], capture_output=True, text=True)
    return result.returncode == 0


async def benchmark_python_ffmpeg(
    input_path: str,
    output_path: str,
    start: str = "0:05",
    end: str = "0:35",
    runs: int = 3
) -> dict:
    """Benchmark direct Python subprocess FFmpeg call."""
    import subprocess

    times = []
    for i in range(runs):
        out = output_path.replace(".mp4", f"_py_{i}.mp4")
        start_ts = time.perf_counter()

        result = subprocess.run([
            "ffmpeg", "-y",
            "-ss", "5",
            "-i", input_path,
            "-t", "30",
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-c:a", "aac",
            out
        ], capture_output=True)

        elapsed = time.perf_counter() - start_ts
        times.append(elapsed)

        # Cleanup
        if os.path.exists(out):
            size_mb = os.path.getsize(out) / 1_048_576
            os.remove(out)
        else:
            size_mb = 0.0

        print(f"  Python run {i+1}/{runs}: {elapsed:.2f}s  ({size_mb:.1f} MB)")

    return {
        "backend": "python_subprocess",
        "runs": runs,
        "times_sec": times,
        "avg_sec": sum(times) / len(times),
        "min_sec": min(times),
        "max_sec": max(times),
    }


async def benchmark_rust_agent(
    input_path: str,
    output_path: str,
    start: str = "0:05",
    end: str = "0:35",
    runs: int = 3
) -> dict:
    """Benchmark via Rust agent HTTP API."""
    import httpx

    agent_url = os.environ.get("RUST_AGENT_URL", "http://rust-agent:8001")

    # Check availability
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{agent_url}/agent/health")
            if resp.status_code != 200:
                return {"backend": "rust_agent", "error": "Health check failed", "runs": 0}
    except Exception as e:
        return {"backend": "rust_agent", "error": str(e), "runs": 0}

    times = []
    for i in range(runs):
        out = output_path.replace(".mp4", f"_rust_{i}.mp4")
        start_ts = time.perf_counter()

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{agent_url}/agent/run",
                json={
                    "task": "render video clip",
                    "context": {
                        "input": input_path,
                        "output": out,
                        "start": start,
                        "end": end,
                        "codec": "libx264",
                        "use_gpu": False,
                    },
                    "max_iterations": 1
                }
            )

        elapsed = time.perf_counter() - start_ts
        data = resp.json()

        if data.get("success"):
            times.append(elapsed)
            if os.path.exists(out):
                size_mb = os.path.getsize(out) / 1_048_576
                os.remove(out)
            else:
                size_mb = 0.0
            print(f"  Rust run {i+1}/{runs}: {elapsed:.2f}s  ({size_mb:.1f} MB)")
        else:
            print(f"  Rust run {i+1}/{runs}: FAILED — {data.get('error', 'unknown')}")

    if not times:
        return {"backend": "rust_agent", "error": "All runs failed", "runs": 0}

    return {
        "backend": "rust_agent",
        "runs": len(times),
        "times_sec": times,
        "avg_sec": sum(times) / len(times),
        "min_sec": min(times),
        "max_sec": max(times),
    }


def print_comparison(py_result: dict, rust_result: dict):
    """Print side-by-side comparison table."""
    print()
    print("=" * 60)
    print("📊  FFmpeg Rendering Benchmark Results")
    print("=" * 60)
    print(f"{'Metric':<22} {'Python':>12} {'Rust Agent':>12}  {'Winner':>8}")
    print("-" * 60)

    def row(label, py_val, rust_val, lower_is_better=True):
        if isinstance(py_val, float) and isinstance(rust_val, float):
            if lower_is_better:
                winner = "🦀 Rust" if rust_val < py_val else "🐍 Python"
                pct = ((py_val - rust_val) / py_val * 100) if py_val else 0
                note = f"({abs(pct):.0f}% faster)" if pct != 0 else ""
            else:
                winner = "🦀 Rust" if rust_val > py_val else "🐍 Python"
                note = ""
            print(f"  {label:<20} {py_val:>10.2f}s {rust_val:>10.2f}s  {winner} {note}")
        else:
            print(f"  {label:<20} {str(py_val):>12} {str(rust_val):>12}")

    if "error" not in py_result and "error" not in rust_result:
        row("Avg render time", py_result["avg_sec"], rust_result["avg_sec"])
        row("Best time", py_result["min_sec"], rust_result["min_sec"])
        row("Worst time", py_result["max_sec"], rust_result["max_sec"])
        row("Runs completed",
            float(py_result["runs"]), float(rust_result["runs"]), lower_is_better=False)

        print()
        speedup = py_result["avg_sec"] / rust_result["avg_sec"] if rust_result["avg_sec"] > 0 else 0
        if speedup > 1:
            print(f"  🚀 Rust is {speedup:.2f}x faster than Python on average")
        elif speedup < 1:
            print(f"  🐍 Python is {1/speedup:.2f}x faster than Rust on average")
        else:
            print("  ⚖️  Both backends have identical performance")
    else:
        if "error" in py_result:
            print(f"  Python: ERROR — {py_result['error']}")
        else:
            print(f"  Python avg: {py_result['avg_sec']:.2f}s")
        if "error" in rust_result:
            print(f"  Rust: ERROR — {rust_result['error']}")
        else:
            print(f"  Rust avg: {rust_result['avg_sec']:.2f}s")

    print("=" * 60)


async def main():
    RUNS = int(os.environ.get("BENCHMARK_RUNS", "3"))
    VIDEO_PATH = "/app/temp/benchmark_test.mp4"
    OUT_DIR = "/app/temp"

    print("=" * 60)
    print("🏁  ViraClip FFmpeg Benchmark")
    print(f"    Runs per backend: {RUNS}")
    print(f"    Input: {VIDEO_PATH}")
    print("=" * 60)

    # Create test video if needed
    if not os.path.exists(VIDEO_PATH):
        print("\n📹 Creating synthetic test video (60s)...")
        ok = await create_test_video(VIDEO_PATH, duration=60)
        if not ok:
            print("❌ Failed to create test video — is ffmpeg installed?")
            sys.exit(1)
        print(f"   ✅ Created {VIDEO_PATH}")

    print(f"\n🐍 Benchmarking Python FFmpeg ({RUNS} runs)...")
    py_result = await benchmark_python_ffmpeg(VIDEO_PATH, f"{OUT_DIR}/bench_out.mp4", runs=RUNS)

    print(f"\n🦀 Benchmarking Rust Agent ({RUNS} runs)...")
    rust_result = await benchmark_rust_agent(VIDEO_PATH, f"{OUT_DIR}/bench_out.mp4", runs=RUNS)

    print_comparison(py_result, rust_result)

    # Save JSON report
    report_path = f"{OUT_DIR}/benchmark_report.json"
    with open(report_path, "w") as f:
        json.dump({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "runs_per_backend": RUNS,
            "python": py_result,
            "rust": rust_result,
        }, f, indent=2)

    print(f"\n💾 Report saved: {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
