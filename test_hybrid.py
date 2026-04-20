#!/usr/bin/env python3
"""ViraClip hybrid B-roll test runner - writes output to file."""
import subprocess, json, time, sys, os

OUT = "/home/_sebastian/CascadeProjects/ViraClip/test_output.txt"

def run(cmd, timeout=15):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return f"ERROR: {e}"

lines = []
def log(msg):
    lines.append(msg)
    print(msg)

log("=" * 60)
log("STEP 1: Container status")
log(run("docker ps --format '{{.Names}} | {{.Status}}'"))

log("\nSTEP 2: ComfyUI logs (RealESRGAN + VideoUpscale)")
log(run("docker logs --tail 50 viraclip-comfyui 2>&1 | grep -iE 'RealESRGAN|VideoUpscale|Downloading|error|listen|ready|custom' | head -15"))

log("\nSTEP 3: ComfyUI /system_stats")
log(run("curl -s --max-time 5 http://localhost:8188/system_stats 2>&1 | head -5"))

log("\nSTEP 4: Backend /health")
log(run("curl -s --max-time 5 http://localhost:8000/health 2>&1"))

log("\nSTEP 5: Create test task (Test A)")
resp = run("""curl -s --max-time 10 -X POST http://localhost:8000/tasks/ \
  -H 'user_id: test_user' \
  -H 'Content-Type: application/json' \
  -d '{"source":{"url":"https://youtu.be/3wgwaxIfUJQ"},"options":{"num_clips":1,"min_duration":15,"max_duration":30}}'""")
log(resp)

log("\nWaiting 10s for pipeline to start...")
time.sleep(10)
log("\nSTEP 6: Worker logs (B-roll routing)")
log(run("docker logs --tail 80 viraclip-worker 2>&1 | grep -E 'B-roll slot|BRoll|enhance_pexels|ltxv|broll_source|Step 5|Step 4' | tail -25"))

log("\n" + "=" * 60)
log("DONE")

with open(OUT, "w") as f:
    f.write("\n".join(lines))
log(f"Output written to {OUT}")
