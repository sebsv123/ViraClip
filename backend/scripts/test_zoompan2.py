"""Minimal zoompan tests to find what the FFmpeg version supports."""
import subprocess

IN = "/tmp/ep_test_input.mp4"

def try_fc(label, fc_expr):
    cmd = ["ffmpeg", "-y", "-i", IN,
           "-filter_complex", fc_expr,
           "-map", "[v]", "-frames:v", "1", "-f", "null", "/dev/null"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    ok = r.returncode == 0
    if not ok:
        lines = [l for l in r.stderr.split("\n") if "Eval" in l or "undefined" in l.lower() or "conversion" in l.lower()]
        snippet = (lines[-1] if lines else r.stderr.strip().split("\n")[-1])[:120]
    else:
        snippet = "OK"
    print(f"  {'✅' if ok else '❌'} {label}: {snippet}")
    return ok

print("=== zoompan via filter_complex ===\n")

# 1. Constant zoom
try_fc("constant zoom 1.05",
       "[0:v]zoompan=z=1.05:x=0:y=0:d=1:s=540x960:fps=30[v]")

# 2. Linear zoom growth (no functions)
try_fc("linear z=1+0.001*n",
       "[0:v]zoompan=z='1+0.001*n':x=0:y=0:d=1:s=540x960:fps=30[v]")

# 3. Use 'in' (frame counter variable)
try_fc("z=1+0.001*in",
       "[0:v]zoompan=z='1+0.001*in':x=0:y=0:d=1:s=540x960:fps=30[v]")

# 4. Min function (one arg, no comma)
try_fc("z=min(1.05/1) no comma",
       "[0:v]zoompan=z='min(1.05)':x=0:y=0:d=1:s=540x960:fps=30[v]")

# 5. gte with single arg (no comma)
try_fc("gte single arg",
       "[0:v]zoompan=z='1+0.1*gte(n-10)':x=0:y=0:d=1:s=540x960:fps=30[v]")

# 6. if with single condition (no comma) — invalid but test
try_fc("mod no comma",
       "[0:v]zoompan=z='1+0.05*mod(n/15)':x=0:y=0:d=1:s=540x960:fps=30[v]")

# 7. Backslash-comma in filter_complex (not quoted)
try_fc("backslash-comma in fc, unquoted",
       r"[0:v]zoompan=z=1+0.1*gte(n\,10)*lte(n\,20):x=0:y=0:d=1:s=540x960:fps=30[v]")

# 8. Backslash-comma in filter_complex + single-quoted  
try_fc("backslash-comma + single quoted",
       r"[0:v]zoompan=z='1+0.1*gte(n\,10)*lte(n\,20)':x=0:y=0:d=1:s=540x960:fps=30[v]")

# Check FFmpeg version
r = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
print(f"\nFFmpeg: {r.stdout.split(chr(10))[0]}")
