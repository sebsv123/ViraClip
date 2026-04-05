"""Test different zoompan expression escaping strategies in a subprocess context."""
import subprocess, sys

IN = "/tmp/ep_test_input.mp4"

def try_vf(label, vf_expr):
    cmd = ["ffmpeg", "-y", "-i", IN,
           "-vf", vf_expr,
           "-frames:v", "1", "-f", "null", "/dev/null"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    ok = r.returncode == 0
    snippet = (r.stderr.strip().split("\n")[-1])[:100] if not ok else "OK"
    print(f"  {'✅' if ok else '❌'} {label}: {snippet}")
    return ok

print("=== zoompan comma-escaping strategies ===\n")

# Strategy A: plain commas inside single quotes
try_vf("plain commas + single quotes",
       "zoompan=z='1+0.1*gte(n,10)*lte(n,20)':x=0:y=0:d=1:s=540x960:fps=30")

# Strategy B: backslash-escaped commas, no outer quotes
try_vf("backslash commas, no quotes",
       r"zoompan=z='1+0.1*gte(n\,10)*lte(n\,20)':x=0:y=0:d=1:s=540x960:fps=30")

# Strategy C: fully escaped commas, outer double quotes
try_vf("escaped commas + double quotes",
       r'zoompan=z="1+0.1*gte(n\,10)*lte(n\,20)":x=0:y=0:d=1:s=540x960:fps=30')

# Strategy D: no function calls at all — simple piecewise with arithmetic
# between(n,a,b) = clip(n-a+1,0,1) * clip(b-n+1,0,1)
# Use: step(n-a) - step(n-b-1) = gte(n,a) - gte(n,b+1)
# Actually: use multiplication + clip to avoid commas entirely
# z = 1 + 0.1 * (gte(n-10) - gte(n-21))   → no commas!
try_vf("no commas: gte subtraction",
       "zoompan=z='1+0.1*(gte(n-10)-gte(n-21))':x=0:y=0:d=1:s=540x960:fps=30")

# Strategy E: use gt/lt with no commas
try_vf("gt+lt no commas",
       "zoompan=z='1+0.1*gt(n-10)*lt(20-n)':x=0:y=0:d=1:s=540x960:fps=30")
