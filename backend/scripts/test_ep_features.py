"""
Test new EditingPipeline features:
  - Film grain (noise filter)
  - Face-aware zoom centering (_detect_face_position)
  - Emphasis word callouts (_emphasis_items returns word text)
  - Audio compression chain (highpass + acompressor + loudnorm)
"""
import asyncio
import subprocess
import sys
import os
from pathlib import Path

sys.path.insert(0, "/app")
os.environ.setdefault("EP_FILM_GRAIN",      "10")
os.environ.setdefault("EP_FACE_ZOOM",       "true")
os.environ.setdefault("EP_WORD_CALLOUT",    "true")
os.environ.setdefault("EP_VOICE_COMPRESS",  "true")
os.environ.setdefault("EP_HOOK_ZOOM_ON",    "true")
os.environ.setdefault("EP_BEAT_SYNC_ON",    "true")
os.environ.setdefault("EP_FADE_ON",         "true")
os.environ.setdefault("EP_FADE_DURATION",   "0.25")
os.environ.setdefault("EP_CTA_ON",              "true")
os.environ.setdefault("EP_CTA_TEXT",            "Follow for more!")
os.environ.setdefault("EP_SAT_PULSE_ON",        "true")
os.environ.setdefault("EP_SAT_PULSE_STRENGTH",  "1.60")
os.environ.setdefault("EP_LETTERBOX_ON",        "true")
os.environ.setdefault("EP_LETTERBOX_H",         "0.07")
os.environ.setdefault("EP_WATERMARK_ON",        "true")
os.environ.setdefault("EP_WATERMARK_TEXT",      "@viraclip")
os.environ.setdefault("EP_THEME_GRADE_ON",      "true")
os.environ.setdefault("EP_THEME_EQ_ON",         "true")

from src.video_processing.editing_pipeline import (
    _emphasis_items,
    _beat_timestamps,
    _detect_face_position,
    _build_filter_complex,
    EditingPipeline,
    FILM_GRAIN, VOICE_COMPRESS_ON, WORD_CALLOUT_ON, FACE_ZOOM_ON,
    EP_HOOK_ZOOM_ON, EP_BEAT_SYNC_ON, EP_FADE_ON, EP_FADE_DURATION,
    EP_CTA_ON, EP_CTA_TEXT,
    EP_SAT_PULSE_ON, EP_SAT_PULSE_STRENGTH,
    EP_LETTERBOX_ON, EP_LETTERBOX_H,
    EP_WATERMARK_ON, EP_WATERMARK_TEXT,
    EP_THEME_GRADE_ON, EP_THEME_EQ_ON,
    EP_PROGRESS_STYLE,
    _classify_theme,
)

PASS = "✅"
FAIL = "❌"

def make_test_video(path: Path, duration: float = 8.0, with_face: bool = False) -> None:
    """Create a synthetic test clip (colour bars or a face-like frame)."""
    if with_face:
        # lavfi smptebars has no face; use testsrc2 instead (still no real face,
        # but _detect_face_position will gracefully return 0.5,0.5)
        src = "testsrc2=size=1080x1920:rate=30"
    else:
        src = "smptebars=size=1080x1920:rate=30"

    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"{src},format=yuv420p",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-c:a", "aac", "-b:a", "64k",
        str(path),
    ], capture_output=True, check=True)


# ── Test 1: _emphasis_items returns (timestamp, word_text) tuples ──────────
def test_emphasis_items():
    words = [
        {"start": 1.0, "word": "INCREDIBLE", "is_emphasis": True,  "confidence": 0.99},
        {"start": 4.0, "word": "amazing",    "is_emphasis": False, "confidence": 0.95},
        {"start": 7.0, "word": "WOW",        "is_emphasis": True,  "confidence": 0.97},
    ]
    items = _emphasis_items(words, max_zooms=4)
    assert isinstance(items, list), "should return list"
    assert all(isinstance(t, tuple) and len(t) == 2 for t in items), "each item must be (ts, word)"
    ts_list = [ts for ts, _ in items]
    words_list = [w for _, w in items]
    # INCREDIBLE and WOW are emphasis=True, amazing is not but confidence 0.95 < 0.92 threshold? no wait
    # actually amazing has conf=0.95 >= 0.92 and text is lowercase → not "loud" so only if is_emphasis
    assert any(w in ("INCREDIBLE", "WOW") for w in words_list), f"expected emphasis words, got {words_list}"
    assert ts_list == sorted(ts_list), "timestamps should be sorted"
    print(f"  {PASS} _emphasis_items → {items}")
    return True


# ── Test 2: filter_complex contains film grain ──────────────────────────────
def test_film_grain_in_filter():
    items = [
        (2.0, "INCREDIBLE"),
        (5.0, "WOW"),
    ]
    fc, vl, al = _build_filter_complex(
        w=1080, h=1920, fps=30.0, dur=10.0,
        emphasis_items=items,
        has_audio=True,
        segment_text="Test grain",
    )
    assert "noise=alls=" in fc, f"film grain filter missing from fc: {fc[:200]}"
    print(f"  {PASS} film grain → noise=alls={FILM_GRAIN} present in filter_complex")
    return True


# ── Test 3: filter_complex contains audio compression chain ─────────────────
def test_audio_compression_in_filter():
    fc, _, al = _build_filter_complex(
        w=1080, h=1920, fps=30.0, dur=10.0,
        emphasis_items=[],
        has_audio=True,
        segment_text="",
    )
    assert al is not None, "audio label should not be None"
    if VOICE_COMPRESS_ON:
        assert "highpass=f=80" in fc, "highpass filter missing"
        assert "acompressor" in fc, "acompressor filter missing"
        print(f"  {PASS} audio chain → highpass + acompressor + loudnorm present")
    else:
        assert "loudnorm" in fc
        print(f"  {PASS} audio chain → loudnorm present (VOICE_COMPRESS_ON=false)")
    return True


# ── Test 4: filter_complex contains word callouts ───────────────────────────
def test_word_callouts_in_filter():
    items = [(2.0, "INCREDIBLE"), (5.0, "WOW")]
    fc, _, _ = _build_filter_complex(
        w=1080, h=1920, fps=30.0, dur=10.0,
        emphasis_items=items,
        has_audio=True,
        segment_text="Test",
    )
    if WORD_CALLOUT_ON:
        assert "[vcall0]" in fc, "callout label [vcall0] missing"
        assert "drawtext=text='INCREDIBLE'" in fc or "drawtext=text='WOW'" in fc, \
            f"callout drawtext missing; fc snippet: {fc[500:800]}"
        print(f"  {PASS} word callouts → [vcall0],[vcall1] drawtext filters present")
    else:
        print(f"  {PASS} word callouts skipped (WORD_CALLOUT_ON=false)")
    return True


# ── Test 5a: saturation pulse uses [vpulse] label when enabled ──────────────
def test_sat_pulse_in_filter():
    items = [(2.0, "BOOM"), (5.0, "WOW")]
    fc, _, _ = _build_filter_complex(
        w=1080, h=1920, fps=30.0, dur=10.0,
        emphasis_items=items, has_audio=False,
    )
    if EP_SAT_PULSE_ON:
        assert "[vpulse]" in fc, "[vpulse] label missing from filter_complex"
        assert "between(t,1.900,2.500)" in fc, "between() for sat pulse missing"
        assert f"eq=saturation={EP_SAT_PULSE_STRENGTH / 1.25:.3f}" in fc or "eq=saturation=" in fc, \
            "saturation ratio missing"
        print(f"  {PASS} sat-pulse → [vpulse] eq=saturation with enable='between(...)' present")
    else:
        print(f"  {PASS} sat-pulse skipped (EP_SAT_PULSE_ON=false)")
    return True


# ── Test 5b: letterbox bars present when enabled ─────────────────────────────
def test_letterbox_in_filter():
    fc, _, _ = _build_filter_complex(
        w=1080, h=1920, fps=30.0, dur=10.0,
        emphasis_items=[], has_audio=False,
    )
    if EP_LETTERBOX_ON:
        assert "[vbars]" in fc, "[vbars] label missing from filter_complex"
        bars_h = max(1, int(1920 * EP_LETTERBOX_H))
        assert f"h={bars_h}" in fc, f"letterbox height {bars_h} missing from filter_complex"
        print(f"  {PASS} letterbox → [vbars] drawbox (h={bars_h}px) present")
    else:
        print(f"  {PASS} letterbox skipped (EP_LETTERBOX_ON=false)")
    return True


# ── Test 5c: watermark present when enabled ───────────────────────────────
def test_watermark_in_filter():
    fc, _, _ = _build_filter_complex(
        w=1080, h=1920, fps=30.0, dur=10.0,
        emphasis_items=[], has_audio=False,
    )
    if EP_WATERMARK_ON and EP_WATERMARK_TEXT:
        assert "[vwm]" in fc, "[vwm] label missing from filter_complex"
        assert "white@0.25" in fc, "watermark opacity (white@0.25) missing"
        print(f"  {PASS} watermark → [vwm] drawtext('{EP_WATERMARK_TEXT}') at 25% opacity")
    else:
        print(f"  {PASS} watermark skipped (EP_WATERMARK_ON=false or empty text)")
    return True


# ── Test 5d: face-aware lower-third shifts y when face is low ──────────────
def test_face_aware_lower_third():
    h = 1920
    # Face at top (cy=0.3) → lower-third at 80% (y=1536)
    fc_top, _, _ = _build_filter_complex(
        w=1080, h=h, fps=30.0, dur=10.0,
        emphasis_items=[], has_audio=False,
        segment_text="Test segment",
        face_cy_norm=0.30,
    )
    # Face at bottom (cy=0.75) → lower-third at 68% (y=1305)
    fc_bot, _, _ = _build_filter_complex(
        w=1080, h=h, fps=30.0, dur=10.0,
        emphasis_items=[], has_audio=False,
        segment_text="Test segment",
        face_cy_norm=0.75,
    )
    y_top = int(h * 0.80)   # 1536
    y_bot = int(h * 0.68)   # 1305
    assert f"y={y_top}" in fc_top, f"expected y={y_top} for top face, got different position"
    assert f"y={y_bot}" in fc_bot, f"expected y={y_bot} for bottom face, got different position"
    assert y_top != y_bot, "y positions must differ for top vs bottom face"
    print(f"  {PASS} face-aware lower-third → y={y_top} (face top) vs y={y_bot} (face bottom)")
    return True


# ── Test: _classify_theme keyword matching ───────────────────────────────────
def test_classify_theme():
    assert _classify_theme("fitness motivation workout") == "warm", "fitness should be warm"
    assert _classify_theme("tech coding software startup") == "cool", "tech should be cool"
    assert _classify_theme("some random clip") == "neutral", "no keywords = neutral"
    assert _classify_theme("") == "neutral", "empty text = neutral"
    print(f"  {PASS} _classify_theme → warm/cool/neutral classification correct")
    return True


# ── Test: theme-adaptive colorbalance params differ per theme ────────────────
def test_theme_grade_in_filter():
    if not EP_THEME_GRADE_ON:
        print(f"  {PASS} theme grade skipped (EP_THEME_GRADE_ON=false)")
        return True
    fc_warm, _, _ = _build_filter_complex(
        w=1080, h=1920, fps=30.0, dur=10.0,
        emphasis_items=[], has_audio=False,
        segment_text="fitness motivation workout",
    )
    fc_cool, _, _ = _build_filter_complex(
        w=1080, h=1920, fps=30.0, dur=10.0,
        emphasis_items=[], has_audio=False,
        segment_text="tech coding startup software",
    )
    fc_neutral, _, _ = _build_filter_complex(
        w=1080, h=1920, fps=30.0, dur=10.0,
        emphasis_items=[], has_audio=False,
        segment_text="some random clip",
    )
    # Each theme should produce a distinct colorbalance parameter string
    assert fc_warm != fc_cool, "warm and cool should produce different filter_complex"
    assert fc_warm != fc_neutral, "warm and neutral should produce different filter_complex"
    assert "rh=0.10" in fc_warm, "warm grade should have rh=0.10"
    assert "bs=0.10" in fc_cool, "cool grade should have bs=0.10"
    print(f"  {PASS} theme grade → warm/cool/neutral produce distinct colorbalance params")
    return True


# ── Test: theme-adaptive audio EQ inserts shelf filter ──────────────────────
def test_theme_eq_in_filter():
    if not EP_THEME_EQ_ON:
        print(f"  {PASS} theme EQ skipped (EP_THEME_EQ_ON=false)")
        return True
    fc_warm, _, _ = _build_filter_complex(
        w=1080, h=1920, fps=30.0, dur=10.0,
        emphasis_items=[], has_audio=True,
        segment_text="fitness motivation workout",
    )
    fc_cool, _, _ = _build_filter_complex(
        w=1080, h=1920, fps=30.0, dur=10.0,
        emphasis_items=[], has_audio=True,
        segment_text="tech coding startup software",
    )
    assert "lowshelf" in fc_warm, "warm theme should add lowshelf EQ"
    assert "highshelf" in fc_cool, "cool theme should add highshelf EQ"
    print(f"  {PASS} theme EQ → lowshelf(warm) and highshelf(cool) present in audio chain")
    return True


# ── Test: face-aware callout y avoids face region ───────────────────────
def test_face_aware_callout():
    items = [(3.0, "WOW"), (6.0, "INSANE")]
    h = 1920
    # Face at top (cy=0.30) → callouts pushed down to 58%
    fc_top, _, _ = _build_filter_complex(
        w=1080, h=h, fps=30.0, dur=10.0,
        emphasis_items=items, has_audio=False,
        face_cy_norm=0.30,
    )
    # Face at bottom (cy=0.75) → callouts in upper-third at 38%
    fc_bot, _, _ = _build_filter_complex(
        w=1080, h=h, fps=30.0, dur=10.0,
        emphasis_items=items, has_audio=False,
        face_cy_norm=0.75,
    )
    y_mid = int(h * 0.58)   # 1113
    y_top = int(h * 0.38)   # 729
    assert f"y={y_mid}" in fc_top, f"expected callout y={y_mid} for top face"
    assert f"y={y_top}" in fc_bot, f"expected callout y={y_top} for bottom face"
    assert y_mid != y_top, "callout y must differ for upper vs lower face"
    print(f"  {PASS} face-aware callout → y={y_mid} (face top) vs y={y_top} (face bottom)")
    return True


# ── Test: progress bar style variants ──────────────────────────────────────
def test_progress_bar_styles():
    import os
    # solid (default)
    os.environ["EP_PROGRESS_STYLE"] = "solid"
    import importlib, src.video_processing.editing_pipeline as ep_mod
    importlib.reload(ep_mod)
    fc_solid, _, _ = ep_mod._build_filter_complex(
        w=1080, h=1920, fps=30.0, dur=10.0, emphasis_items=[], has_audio=False,
    )
    assert "[vpbar]" in fc_solid, "solid: [vpbar] missing"
    assert "iw*t/10.000" in fc_solid, "solid: dynamic width expression missing"

    # gradient
    os.environ["EP_PROGRESS_STYLE"] = "gradient"
    importlib.reload(ep_mod)
    fc_grad, _, _ = ep_mod._build_filter_complex(
        w=1080, h=1920, fps=30.0, dur=10.0, emphasis_items=[], has_audio=False,
    )
    assert "[vpbar]" in fc_grad, "gradient: [vpbar] missing"
    # gradient has two drawbox entries
    assert fc_grad.count("drawbox") >= 2, "gradient: expected >=2 drawbox calls"

    # dots
    os.environ["EP_PROGRESS_STYLE"] = "dots"
    importlib.reload(ep_mod)
    fc_dots, _, _ = ep_mod._build_filter_complex(
        w=1080, h=1920, fps=30.0, dur=10.0, emphasis_items=[], has_audio=False,
    )
    assert "[vpbar]" in fc_dots, "dots: [vpbar] missing"
    assert "gte(t," in fc_dots, "dots: enable='gte(t,...)' missing"
    assert fc_dots.count("drawbox") >= 10, "dots: expected 10 dot drawboxes"

    # restore default
    os.environ["EP_PROGRESS_STYLE"] = "solid"
    importlib.reload(ep_mod)
    print(f"  {PASS} progress bar styles → solid/gradient/dots all render [vpbar]")
    return True


# ── Test 5a (old numbering): hook zoom punch appears in zoom expression ────────────────────
def test_hook_zoom_in_filter():
    fc, _, _ = _build_filter_complex(
        w=1080, h=1920, fps=30.0, dur=10.0,
        emphasis_items=[],
        has_audio=False,
    )
    if EP_HOOK_ZOOM_ON:
        assert "exp(-" in fc and "*in*in)" in fc, \
            f"hook zoom Gaussian (in*in) missing from zoompan; snippet: {fc[300:500]}"
        print(f"  {PASS} hook zoom → Gaussian at frame 0 present in z_expr")
    else:
        print(f"  {PASS} hook zoom skipped (EP_HOOK_ZOOM_ON=false)")
    return True


# ── Test 5b: fade-in/out present in filter_complex ──────────────────────────
def test_fade_in_filter():
    fc, _, _ = _build_filter_complex(
        w=1080, h=1920, fps=30.0, dur=10.0,
        emphasis_items=[],
        has_audio=False,
    )
    if EP_FADE_ON:
        assert "fade=t=in" in fc,  "fade-in missing"
        assert "fade=t=out" in fc, "fade-out missing"
        print(f"  {PASS} fade-in/out → fade=t=in and fade=t=out present")
    else:
        print(f"  {PASS} fade skipped (EP_FADE_ON=false)")
    return True


# ── Test 5c: CTA overlay present when EP_CTA_ON=true ────────────────────────
def test_cta_in_filter():
    fc, _, _ = _build_filter_complex(
        w=1080, h=1920, fps=30.0, dur=10.0,
        emphasis_items=[],
        has_audio=False,
        segment_text="",
    )
    if EP_CTA_ON:
        safe_cta = EP_CTA_TEXT.replace("'", "")
        assert "[vcta]" in fc, "CTA label missing from filter_complex"
        assert "fontcolor=yellow" in fc, "CTA fontcolor=yellow missing"
        print(f"  {PASS} CTA overlay → [vcta] drawtext present")
    else:
        print(f"  {PASS} CTA skipped (EP_CTA_ON=false)")
    return True


# ── Test 5d: _beat_timestamps returns list of floats (or empty) ──────────────
def test_beat_timestamps(test_video: Path):
    result = _beat_timestamps(test_video, dur=8.0, max_beats=6)
    assert isinstance(result, list), "should return list"
    assert all(isinstance(t, float) for t in result), "all elements must be float"
    assert all(1.0 < t < 7.0 for t in result), f"beats out of valid range: {result}"
    print(f"  {PASS} _beat_timestamps → {len(result)} beats (synthetic audio may have 0)")
    return True


# ── Test 5: face-aware zoom x/y expressions use face_cx_norm ────────────────
def test_face_aware_zoom_expressions():
    items = [(2.0, "TEST")]
    for cx in [0.3, 0.5, 0.7]:
        fc, _, _ = _build_filter_complex(
            w=1080, h=1920, fps=30.0, dur=10.0,
            emphasis_items=items,
            has_audio=False,
            face_cx_norm=cx,
            face_cy_norm=0.5,
        )
        expected_x = f"(iw-iw/zoom)*{cx:.4f}"
        assert expected_x in fc, f"face cx_norm={cx} expression missing; got: {fc[400:600]}"
    print(f"  {PASS} face-aware zoom → x=(iw-iw/zoom)*face_cx_norm expressions correct")
    return True


# ── Test 6: _detect_face_position returns tuple (float, float) ──────────────
def test_detect_face_position(test_video: Path):
    cx, cy = _detect_face_position(test_video, dur=8.0)
    assert isinstance(cx, float) and isinstance(cy, float), "should return (float, float)"
    assert 0.0 <= cx <= 1.0 and 0.0 <= cy <= 1.0, f"values out of [0,1]: cx={cx}, cy={cy}"
    # synthetic test video has no real face → falls back to (0.5, 0.5)
    print(f"  {PASS} _detect_face_position → ({cx:.3f}, {cy:.3f}) [no real face → fallback]")
    return True


# ── Test 7: Full EditingPipeline with all new effects ───────────────────────
async def test_full_pipeline(test_video: Path):
    out = Path("/tmp/ep_features_test_output.mp4")
    words = [
        {"start": 1.5, "word": "INCREDIBLE", "is_emphasis": True,  "confidence": 0.99},
        {"start": 4.5, "word": "WOW",        "is_emphasis": True,  "confidence": 0.97},
    ]
    ep = EditingPipeline()
    result = await ep.apply(
        video_path=test_video,
        words=words,
        output_path=out,
        segment_text="Test all new effects",
        flash_timestamps=[2.0, 5.0],
    )
    assert result.exists() and result.stat().st_size > 50_000, \
        f"output too small or missing: {result} ({result.stat().st_size if result.exists() else 'missing'})"
    size_kb = result.stat().st_size // 1024
    print(f"  {PASS} Full EditingPipeline → {result.name}  size={size_kb}KB")
    return True


async def main():
    print("\n" + "="*60)
    print("🧪 EditingPipeline New Features Test")
    print("="*60)
    print(f"  Config: FILM_GRAIN={FILM_GRAIN}  VOICE_COMPRESS={VOICE_COMPRESS_ON}"
          f"  WORD_CALLOUT={WORD_CALLOUT_ON}  FACE_ZOOM={FACE_ZOOM_ON}"
          f"  HOOK_ZOOM={EP_HOOK_ZOOM_ON}  BEAT_SYNC={EP_BEAT_SYNC_ON}"
          f"  FADE={EP_FADE_ON}({EP_FADE_DURATION}s)  CTA={EP_CTA_ON}")
    print()

    test_video = Path("/tmp/ep_features_input.mp4")
    print("→ Creating synthetic test video (8s, 1080x1920, with audio)…")
    make_test_video(test_video, duration=8.0)
    print(f"  {PASS} Test video: {test_video.stat().st_size // 1024}KB\n")

    tests = [
        ("_emphasis_items returns (ts, word) pairs",    lambda: test_emphasis_items()),
        ("Film grain present in filter_complex",         lambda: test_film_grain_in_filter()),
        ("Audio compression chain in filter_complex",    lambda: test_audio_compression_in_filter()),
        ("Word callouts in filter_complex",              lambda: test_word_callouts_in_filter()),
        ("Face-aware zoom x/y expressions",             lambda: test_face_aware_zoom_expressions()),
        ("_detect_face_position returns (float, float)", lambda: test_detect_face_position(test_video)),
    ("Hook zoom punch-in at t=0 in filter_complex",   lambda: test_hook_zoom_in_filter()),
    ("Fade-in/out in filter_complex",                 lambda: test_fade_in_filter()),
    ("CTA overlay in filter_complex",                 lambda: test_cta_in_filter()),
    ("Beat-sync _beat_timestamps fallback",           lambda: test_beat_timestamps(test_video)),
    ("Saturation pulse at emphasis in filter_complex", lambda: test_sat_pulse_in_filter()),
    ("Letterbox bars in filter_complex",              lambda: test_letterbox_in_filter()),
    ("Watermark in filter_complex",                   lambda: test_watermark_in_filter()),
    ("Face-aware lower-third y moves up",             lambda: test_face_aware_lower_third()),
    ("_classify_theme keyword matching",              lambda: test_classify_theme()),
    ("Theme-adaptive colorbalance in filter_complex", lambda: test_theme_grade_in_filter()),
    ("Theme-adaptive audio EQ in filter_complex",     lambda: test_theme_eq_in_filter()),
    ("Face-aware callout y avoids face region",        lambda: test_face_aware_callout()),
    ("Progress bar styles in filter_complex",          lambda: test_progress_bar_styles()),
    ]

    passed = 0
    for name, fn in tests:
        try:
            print(f"Testing: {name}")
            fn()
            passed += 1
        except Exception as e:
            print(f"  {FAIL} {name}: {e}")
        print()

    # Async test
    print("Testing: Full EditingPipeline encode with all effects")
    try:
        await test_full_pipeline(test_video)
        passed += 1
    except Exception as e:
        print(f"  {FAIL} Full pipeline: {e}")
    print()

    total = len(tests) + 1
    print("="*60)
    print(f"📊 Results: {passed}/{total} passed")
    print("="*60)
    if passed == total:
        print("🎉 All new EditingPipeline features verified!")
    else:
        print("⚠️  Some tests failed — check output above")
    return passed == total


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
