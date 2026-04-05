"""Find valid zoompan expressions for FFmpeg 4.4 (uses 'in' not 'n', no multi-arg funcs)."""
import subprocess

IN = "/tmp/ep_test_input.mp4"

def try_fc(label, fc_expr):
    cmd = ["ffmpeg", "-y", "-i", IN,
           "-filter_complex", fc_expr,
           "-map", "[v]", "-frames:v", "5", "-f", "null", "/dev/null"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    ok = r.returncode == 0
    if not ok:
        lines = [l for l in r.stderr.split("\n") if "Eval" in l or "Error" in l]
        snippet = (lines[0] if lines else r.stderr.strip().split("\n")[-1])[:100]
    else:
        snippet = "OK"
    print(f"  {'✅' if ok else '❌'} {label}: {snippet}")
    return ok

print("=== zoompan: 'in' variable + single-arg functions ===\n")

# Gaussian bell curve: exp(-k * (in-f0)*(in-f0))  — no commas!
try_fc("Gaussian at frame 60 (t=2s)",
       "[0:v]zoompan=z='1+0.12*exp(-0.05*(in-60)*(in-60))':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d=1:s=540x960:fps=30[v]")

# Two Gaussian peaks (sum)
try_fc("Two Gaussian peaks at 2s and 7s",
       "[0:v]zoompan=z='1+0.12*exp(-0.05*(in-60)*(in-60))+0.12*exp(-0.05*(in-210)*(in-210))':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d=1:s=540x960:fps=30[v]")

# Ken Burns: linear with 'in'
try_fc("Ken Burns linear in",
       "[0:v]zoompan=z='1+0.00004*in':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d=1:s=540x960:fps=30[v]")

# gte with 'in' (single arg — means gte(in-10, 0))
try_fc("gte(in-10) single arg",
       "[0:v]zoompan=z='1+0.05*gte(in-10)':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d=1:s=540x960:fps=30[v]")

# sqrt() single arg
try_fc("sqrt single arg",
       "[0:v]zoompan=z='1+0.001*sqrt(in)':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d=1:s=540x960:fps=30[v]")

# Combination: Ken Burns + Gaussian pulse
try_fc("KenBurns + Gaussian pulse",
       "[0:v]zoompan=z='1+0.00003*in+0.10*exp(-0.05*(in-60)*(in-60))':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d=1:s=540x960:fps=30[v]")
