#!/usr/bin/env python3
"""
ViraClip WOW Test - Automated Execution
Generates clips and produces evaluation report automatically.
"""
import os
import sys
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, '/app/src')

OUTPUT_DIR = Path("/app/exports/clips")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

print("="*70)
print("🔥 ViraClip REAL WOW Test - Automated Execution")
print("="*70)
print(f"Time: {datetime.now().isoformat()}")
print(f"Output: {OUTPUT_DIR}")
print()

# 1. Check available videos
print("📁 Step 1: Finding test videos...")
temp_videos = list(Path("/app/temp").glob("*.mp4")) if Path("/app/temp").exists() else []
print(f"   Found {len(temp_videos)} videos in /app/temp")
for v in temp_videos:
    print(f"   - {v.name} ({v.stat().st_size / 1024 / 1024:.1f} MB)")

# 2. Check existing clips
print("\n🎬 Step 2: Checking existing clips...")
existing_clips = list(OUTPUT_DIR.glob("*.mp4"))
print(f"   Found {len(existing_clips)} existing clips")

# 3. Get provider diagnostics
print("\n🔧 Step 3: Provider diagnostics...")
try:
    from services.broll_provider_strategy import diagnose_providers, get_provider_order_labels
    status = diagnose_providers()
    print(f"   Priority: {status.priority}")
    print(f"   LTXV: {status.ltxv_enabled}")
    print(f"   ComfyUI: {status.comfyui_enabled}")
    print(f"   T2V: {status.t2v_available}")
    print(f"   Provider order: {get_provider_order_labels()}")
except Exception as e:
    print(f"   ⚠️ Error: {e}")

# 4. If no clips exist, we need to generate them
if len(existing_clips) < 15 and temp_videos:
    print(f"\n⚠️  Only {len(existing_clips)} clips found, need 15-20 for valid test")
    print("   Videos available but pipeline execution requires:")
    print("   1. Backend API running (docker-compose up backend)")
    print("   2. Worker running (docker-compose up worker)")
    print("   3. Database and Redis connected")
    print()
    print("   To generate clips, run from host:")
    print("   docker-compose up -d backend worker")
    print("   Then POST to localhost:8000/tasks/ with video URLs")

# 5. Evaluate existing clips
print(f"\n📊 Step 4: Evaluating {len(existing_clips)} clips...")

results = []
for i, clip in enumerate(existing_clips[:20], 1):
    # Get video info
    try:
        duration = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(clip)],
            capture_output=True, text=True, timeout=5
        )
        dur = float(duration.stdout.strip()) if duration.returncode == 0 else 0
    except:
        dur = 0
    
    stat = clip.stat()
    size_mb = stat.st_size / 1024 / 1024
    
    # Detect if contextual broll was used
    name = clip.name.lower()
    has_broll = "broll" in name or "ctx" in name
    is_jumpcut = "jc" in name and not has_broll
    
    # Heuristic WOW scoring
    # Duration score: 15-60s is ideal
    duration_score = 4.0 if 15 <= dur <= 60 else 3.0 if 10 <= dur <= 90 else 2.0
    
    # Quality score based on file size (proxy for bitrate/quality)
    quality_score = min(5.0, max(2.0, size_mb / 3))
    
    # B-roll bonus
    broll_score = 4.0 if has_broll else 2.5
    
    # Overall WOW score (simplified)
    wow_score = (duration_score + quality_score + broll_score) / 3
    
    classification = "WOW" if wow_score >= 4.2 else "GOOD" if wow_score >= 3.5 else "MEH" if wow_score >= 2.5 else "BAD"
    
    results.append({
        "clip_id": f"clip_{i:03d}",
        "name": clip.name,
        "duration": dur,
        "size_mb": size_mb,
        "has_broll": has_broll,
        "is_jumpcut": is_jumpcut,
        "duration_score": duration_score,
        "quality_score": quality_score,
        "broll_score": broll_score,
        "wow_score": wow_score,
        "classification": classification
    })
    
    print(f"   {i}. {clip.name[:40]:40} | {dur:5.1f}s | {size_mb:5.1f}MB | Score: {wow_score:.2f} ({classification})")

# 6. Generate Report
if results:
    print(f"\n{'='*70}")
    print("📊 WOW TEST RESULTS")
    print("="*70)
    
    total = len(results)
    wow_count = sum(1 for r in results if r["classification"] == "WOW")
    good_count = sum(1 for r in results if r["classification"] == "GOOD")
    meh_count = sum(1 for r in results if r["classification"] == "MEH")
    bad_count = sum(1 for r in results if r["classification"] == "BAD")
    
    broll_count = sum(1 for r in results if r["has_broll"])
    avg_score = sum(r["wow_score"] for r in results) / total
    
    print(f"\n📈 Summary:")
    print(f"   Total clips: {total}")
    print(f"   Average WOW Score: {avg_score:.2f}/5.0")
    print(f"")
    print(f"   Classification:")
    print(f"   - WOW:   {wow_count} ({wow_count/total*100:.1f}%)")
    print(f"   - GOOD:  {good_count} ({good_count/total*100:.1f}%)")
    print(f"   - MEH:   {meh_count} ({meh_count/total*100:.1f}%)")
    print(f"   - BAD:   {bad_count} ({bad_count/total*100:.1f}%)")
    print(f"")
    print(f"   B-roll usage: {broll_count}/{total} ({broll_count/total*100:.1f}%)")
    
    # Top 5
    sorted_results = sorted(results, key=lambda x: x["wow_score"], reverse=True)
    print(f"\n🏆 Top 5 Clips:")
    for i, r in enumerate(sorted_results[:5], 1):
        print(f"   {i}. {r['name'][:45]:45} | {r['wow_score']:.2f} | {r['classification']}")
    
    # Bottom 5
    print(f"\n💩 Bottom 5 Clips:")
    for i, r in enumerate(sorted_results[-5:], 1):
        print(f"   {i}. {r['name'][:45]:45} | {r['wow_score']:.2f} | {r['classification']}")
    
    # Verdict
    print(f"\n{'='*70}")
    print("🎯 FINAL VERDICT")
    print("="*70)
    
    # Criteria
    premium_rate = broll_count / total  # Approximation
    stock_rate = 1 - premium_rate
    
    meets_criteria = (
        premium_rate >= 0.70 and
        avg_score >= 3.8 and
        wow_count >= 5
    )
    
    if meets_criteria:
        print("\n✅ VERDICT: SÍ - Estamos generando clips WOW")
        print(f"   Premium usage: {premium_rate*100:.1f}% (>70% ✓)")
        print(f"   Average score: {avg_score:.2f}/5.0 (>3.8 ✓)")
        print(f"   WOW clips: {wow_count} (≥5 ✓)")
    else:
        print("\n❌ VERDICT: NO - Seguimos en clips MEH")
        if premium_rate < 0.70:
            print(f"   ✗ Premium usage: {premium_rate*100:.1f}% (necesita >70%)")
        if avg_score < 3.8:
            print(f"   ✗ Average score: {avg_score:.2f}/5.0 (necesita >3.8)")
        if wow_count < 5:
            print(f"   ✗ WOW clips: {wow_count} (necesita ≥5)")
    
    # Save report
    report_file = OUTPUT_DIR / f"wow_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_file, 'w') as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "total_clips": total,
            "avg_wow_score": avg_score,
            "classification_counts": {
                "WOW": wow_count,
                "GOOD": good_count,
                "MEH": meh_count,
                "BAD": bad_count
            },
            "premium_usage_pct": premium_rate * 100,
            "clips": results
        }, f, indent=2)
    
    print(f"\n📝 Report saved: {report_file}")
else:
    print("\n❌ No clips to evaluate!")
    print("   Generate clips first with: docker-compose up -d backend worker")

print(f"\n{'='*70}")
print("Test complete")
print("="*70)
