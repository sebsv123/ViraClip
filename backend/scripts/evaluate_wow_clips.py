#!/usr/bin/env python3
"""
ViraClip WOW Clip Evaluation - Manual Review Collector

This script:
1. Finds all generated clips in /app/exports/clips/
2. Displays them with metadata for manual evaluation
3. Collects WOW rubric scores (1-5)
4. Generates final report with verdict

EXECUTION:
    docker-compose exec worker python3 /app/scripts/evaluate_wow_clips.py --interactive
    
    OR for automated evaluation of existing clips:
    docker-compose exec worker python3 /app/scripts/evaluate_wow_clips.py --auto

OUTPUT:
    - CSV with clip metrics and WOW scores
    - Top/bottom 5 clips identified
    - Final verdict report
"""
import os
import sys
import csv
import json
import subprocess
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional
from datetime import datetime

sys.path.insert(0, '/app/src')

@dataclass
class WowEvaluation:
    """WOW rubric evaluation for a single clip."""
    clip_id: str
    clip_path: str
    source_video: str
    duration_sec: float
    file_size_mb: float
    
    # Provider tracking
    broll_provider: str = "unknown"
    provider_order: List[str] = None
    premium_used: bool = False
    stock_fallback: bool = False
    quality_rejections: int = 0
    
    # WOW Rubric (1-5 scale)
    hook_visual: float = 0.0          # Hook visual inicial
    broll_relevance: float = 0.0    # Relevancia del B-roll respecto a lo dicho
    visual_quality: float = 0.0     # Calidad visual/cinemática
    rhythm_pacing: float = 0.0      # Ritmo y pacing
    subtitles_legibility: float = 0.0  # Subtítulos y legibilidad
    audio_mix: float = 0.0          # Audio mix / ducking / claridad
    publishable_feeling: float = 0.0 # Sensación de "esto se podría publicar"
    
    # Notes
    what_works: str = ""
    what_fails: str = ""
    broll_helped: str = ""  # "yes", "no", "neutral"
    looks_premium: str = ""  # "yes", "no", "stock"
    
    @property
    def wow_score_total(self) -> float:
        scores = [
            self.hook_visual, self.broll_relevance, self.visual_quality,
            self.rhythm_pacing, self.subtitles_legibility, self.audio_mix,
            self.publishable_feeling
        ]
        valid = [s for s in scores if s > 0]
        return sum(valid) / len(valid) if valid else 0.0
    
    @property
    def classification(self) -> str:
        score = self.wow_score_total
        if score >= 4.2:
            return "WOW"
        elif score >= 3.5:
            return "GOOD"
        elif score >= 2.5:
            return "MEH"
        else:
            return "BAD"


class WowEvaluator:
    """Evaluates generated clips with WOW rubric."""
    
    def __init__(self, clips_dir: str = "/app/exports/clips"):
        self.clips_dir = Path(clips_dir)
        self.evaluations: List[WowEvaluation] = []
        
    def find_clips(self) -> List[Path]:
        """Find all MP4 clips in output directory."""
        if not self.clips_dir.exists():
            print(f"❌ Clips directory not found: {self.clips_dir}")
            return []
        
        clips = list(self.clips_dir.glob("*.mp4"))
        # Sort by creation time, newest first
        clips.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return clips
    
    def get_video_info(self, clip_path: Path) -> Dict:
        """Extract video metadata using ffprobe."""
        try:
            # Duration
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", str(clip_path)],
                capture_output=True, text=True, timeout=10
            )
            duration = float(result.stdout.strip()) if result.returncode == 0 else 0.0
            
            # Resolution
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0",
                 str(clip_path)],
                capture_output=True, text=True, timeout=10
            )
            resolution = result.stdout.strip() if result.returncode == 0 else "unknown"
            
            stat = clip_path.stat()
            
            return {
                "duration": duration,
                "resolution": resolution,
                "file_size_mb": stat.st_size / 1024 / 1024,
                "created": datetime.fromtimestamp(stat.st_mtime).isoformat()
            }
        except Exception as e:
            print(f"   ⚠️ ffprobe error: {e}")
            return {"duration": 0, "resolution": "unknown", "file_size_mb": 0, "created": ""}
    
    def detect_provider_from_logs(self, clip_path: Path) -> Dict:
        """Try to detect which provider was used from log analysis."""
        # In a real implementation, this would query the database or parse logs
        # For now, return placeholder based on clip name patterns
        name = clip_path.name.lower()
        
        if "broll" in name or "ctx" in name:
            return {
                "provider": "contextual_broll",
                "premium": True,
                "stock_fallback": "jc" in name  # jc = jump cut only, no broll
            }
        return {"provider": "unknown", "premium": False, "stock_fallback": False}
    
    def interactive_evaluate(self):
        """Interactive evaluation of each clip."""
        clips = self.find_clips()
        
        if not clips:
            print("\n❌ No clips found to evaluate!")
            print(f"   Looked in: {self.clips_dir}")
            return
        
        print(f"\n🎬 Found {len(clips)} clips to evaluate\n")
        print("=" * 70)
        print("WOW RUBRIC - Rate each clip 1-5 (or press Enter to skip)")
        print("=" * 70)
        print("""
1 = Muy malo / Very bad
2 = Malo / Bad  
3 = Regular / Mediocre (MEH)
4 = Bueno / Good
5 = Excelente / WOW
        """)
        
        for i, clip_path in enumerate(clips[:20], 1):  # Max 20 clips
            info = self.get_video_info(clip_path)
            provider_info = self.detect_provider_from_logs(clip_path)
            
            print(f"\n{'='*70}")
            print(f"CLIP {i}/{min(len(clips), 20)}: {clip_path.name}")
            print(f"   Duration: {info['duration']:.1f}s | Size: {info['file_size_mb']:.1f}MB")
            print(f"   Resolution: {info['resolution']}")
            print(f"   Provider: {provider_info['provider']}")
            print(f"   Path: {clip_path}")
            print("="*70)
            
            # Collect scores
            scores = {}
            dimensions = [
                ("hook_visual", "Hook visual inicial (1-5)"),
                ("broll_relevance", "Relevancia B-roll respecto a lo dicho (1-5)"),
                ("visual_quality", "Calidad visual/cinemática (1-5)"),
                ("rhythm_pacing", "Ritmo y pacing (1-5)"),
                ("subtitles_legibility", "Subtítulos y legibilidad (1-5)"),
                ("audio_mix", "Audio mix / ducking / claridad (1-5)"),
                ("publishable_feeling", "Sensación de 'publicable' (1-5)")
            ]
            
            for key, prompt in dimensions:
                while True:
                    val = input(f"   {prompt}: ").strip()
                    if val == "":
                        scores[key] = 0.0
                        break
                    try:
                        score = float(val)
                        if 1 <= score <= 5:
                            scores[key] = score
                            break
                        else:
                            print("      Must be 1-5")
                    except ValueError:
                        print("      Enter a number or press Enter to skip")
            
            # Collect notes
            print("\n   Notas:")
            what_works = input("   - ¿Qué funciona bien? ")
            what_fails = input("   - ¿Qué falla? ")
            broll_helped = input("   - ¿El B-roll ayudó? (yes/no/neutral) [neutral]: ").strip() or "neutral"
            looks_premium = input("   - ¿Parece premium o stock? (premium/stock) [stock]: ").strip() or "stock"
            
            # Create evaluation
            eval = WowEvaluation(
                clip_id=f"clip_{i:03d}",
                clip_path=str(clip_path),
                source_video="unknown",  # Would get from task metadata
                duration_sec=info['duration'],
                file_size_mb=info['file_size_mb'],
                broll_provider=provider_info['provider'],
                premium_used=provider_info['premium'],
                stock_fallback=provider_info['stock_fallback'],
                **scores,
                what_works=what_works,
                what_fails=what_fails,
                broll_helped=broll_helped,
                looks_premium=looks_premium
            )
            
            self.evaluations.append(eval)
            print(f"\n   ✓ Saved! WOW Score: {eval.wow_score_total:.2f} | Classification: {eval.classification}")
        
        self._generate_report()
    
    def auto_evaluate(self):
        """Automated evaluation based on heuristics (for testing)."""
        clips = self.find_clips()
        
        print(f"\n🎬 Auto-evaluating {len(clips)} clips...")
        
        for i, clip_path in enumerate(clips, 1):
            info = self.get_video_info(clip_path)
            provider_info = self.detect_provider_from_logs(clip_path)
            
            # Heuristic scoring based on clip characteristics
            # In reality, this would be manual human evaluation
            duration_score = 4.0 if 15 <= info['duration'] <= 60 else 3.0
            size_score = 4.0 if info['file_size_mb'] > 5 else 3.0
            
            eval = WowEvaluation(
                clip_id=f"clip_{i:03d}",
                clip_path=str(clip_path),
                source_video=clip_path.stem,
                duration_sec=info['duration'],
                file_size_mb=info['file_size_mb'],
                broll_provider=provider_info['provider'],
                premium_used=provider_info['premium'],
                stock_fallback=provider_info['stock_fallback'],
                hook_visual=duration_score,
                broll_relevance=3.5 if provider_info['premium'] else 2.5,
                visual_quality=size_score,
                rhythm_pacing=3.5,
                subtitles_legibility=4.0,
                audio_mix=3.5,
                publishable_feeling=3.5 if provider_info['premium'] else 2.5,
                what_works="Auto-generated evaluation",
                what_fails="N/A",
                broll_helped="yes" if provider_info['premium'] else "neutral",
                looks_premium="premium" if provider_info['premium'] else "stock"
            )
            
            self.evaluations.append(eval)
        
        self._generate_report()
    
    def _generate_report(self):
        """Generate final CSV and console report."""
        if not self.evaluations:
            print("\n❌ No evaluations to report!")
            return
        
        # CSV export
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = self.clips_dir / f"wow_evaluation_report_{timestamp}.csv"
        
        with open(report_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'clip_id', 'clip_name', 'duration_sec', 'file_size_mb',
                'broll_provider', 'premium_used', 'stock_fallback',
                'hook_visual', 'broll_relevance', 'visual_quality',
                'rhythm_pacing', 'subtitles_legibility', 'audio_mix',
                'publishable_feeling', 'wow_score_total', 'classification',
                'broll_helped', 'looks_premium', 'what_works', 'what_fails'
            ])
            
            for eval in self.evaluations:
                writer.writerow([
                    eval.clip_id, Path(eval.clip_path).name, eval.duration_sec,
                    eval.file_size_mb, eval.broll_provider, eval.premium_used,
                    eval.stock_fallback, eval.hook_visual, eval.broll_relevance,
                    eval.visual_quality, eval.rhythm_pacing, eval.subtitles_legibility,
                    eval.audio_mix, eval.publishable_feeling, eval.wow_score_total,
                    eval.classification, eval.broll_helped, eval.looks_premium,
                    eval.what_works, eval.what_fails
                ])
        
        # Console report
        print(f"\n{'='*70}")
        print("📊 WOW EVALUATION REPORT")
        print("=" * 70)
        
        total = len(self.evaluations)
        wow_count = sum(1 for e in self.evaluations if e.classification == "WOW")
        good_count = sum(1 for e in self.evaluations if e.classification == "GOOD")
        meh_count = sum(1 for e in self.evaluations if e.classification == "MEH")
        bad_count = sum(1 for e in self.evaluations if e.classification == "BAD")
        
        premium_count = sum(1 for e in self.evaluations if e.premium_used)
        stock_count = sum(1 for e in self.evaluations if e.stock_fallback)
        
        avg_score = sum(e.wow_score_total for e in self.evaluations) / total
        
        print(f"\n📈 Summary Statistics:")
        print(f"   Total clips evaluated: {total}")
        print(f"   Average WOW Score: {avg_score:.2f}/5.0")
        print(f"")
        print(f"   Classification breakdown:")
        print(f"   - WOW (≥4.2):    {wow_count} ({wow_count/total*100:.1f}%)")
        print(f"   - GOOD (3.5-4.19): {good_count} ({good_count/total*100:.1f}%)")
        print(f"   - MEH (2.5-3.49):  {meh_count} ({meh_count/total*100:.1f}%)")
        print(f"   - BAD (<2.5):      {bad_count} ({bad_count/total*100:.1f}%)")
        print(f"")
        print(f"   Provider usage:")
        print(f"   - Premium B-roll: {premium_count} ({premium_count/total*100:.1f}%)")
        print(f"   - Stock fallback: {stock_count} ({stock_count/total*100:.1f}%)")
        
        # Top 5
        sorted_evals = sorted(self.evaluations, key=lambda e: e.wow_score_total, reverse=True)
        print(f"\n🏆 Top 5 Clips:")
        for i, eval in enumerate(sorted_evals[:5], 1):
            print(f"   {i}. {eval.clip_id} - Score: {eval.wow_score_total:.2f} ({eval.classification})")
            print(f"      Provider: {eval.broll_provider} | Premium: {eval.premium_used}")
        
        # Bottom 5
        print(f"\n💩 Bottom 5 Clips:")
        for i, eval in enumerate(sorted_evals[-5:], 1):
            print(f"   {i}. {eval.clip_id} - Score: {eval.wow_score_total:.2f} ({eval.classification})")
            print(f"      Provider: {eval.broll_provider} | Premium: {eval.premium_used}")
        
        # Verdict
        print(f"\n{'='*70}")
        print("🎯 FINAL VERDICT")
        print("=" * 70)
        
        criteria_met = (
            premium_count / total >= 0.70 and  # >70% premium
            avg_score >= 3.8 and               # Avg >3.8
            wow_count >= 5                      # At least 5 WOW clips
        )
        
        if criteria_met:
            print("\n✅ VERDICT: SÍ - Estamos generando clips WOW")
            print(f"   El sistema está produciendo clips de calidad publicable.")
            print(f"   Premium usage: {premium_count/total*100:.1f}% (>70% ✓)")
            print(f"   Average score: {avg_score:.2f}/5.0 (>3.8 ✓)")
            print(f"   WOW clips: {wow_count} (≥5 ✓)")
        else:
            print("\n❌ VERDICT: NO - Seguimos en clips MEH")
            print(f"   El sistema aún no alcanza el estándar WOW.")
            if premium_count / total < 0.70:
                print(f"   ✗ Premium usage: {premium_count/total*100:.1f}% (necesita >70%)")
            if avg_score < 3.8:
                print(f"   ✗ Average score: {avg_score:.2f}/5.0 (necesita >3.8)")
            if wow_count < 5:
                print(f"   ✗ WOW clips: {wow_count} (necesita ≥5)")
        
        print(f"\n📝 Full report saved: {report_file}")
        
        # Recommendations
        print(f"\n💡 Recommendations:")
        if avg_score < 3.8:
            print(f"   - Improve B-roll relevance matching")
            print(f"   - Enhance subtitle readability")
            print(f"   - Better audio ducking/mixing")
        if stock_count / total > 0.20:
            print(f"   - Reduce stock fallback rate (currently {stock_count/total*100:.1f}%)")
            print(f"   - Check why premium providers are failing")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="WOW Clip Evaluation")
    parser.add_argument("--interactive", "-i", action="store_true", 
                       help="Interactive manual evaluation")
    parser.add_argument("--auto", "-a", action="store_true",
                       help="Automated heuristic evaluation")
    args = parser.parse_args()
    
    evaluator = WowEvaluator()
    
    if args.interactive:
        evaluator.interactive_evaluate()
    elif args.auto:
        evaluator.auto_evaluate()
    else:
        # Default: just show available clips
        clips = evaluator.find_clips()
        print(f"\n🎬 Found {len(clips)} clips in {evaluator.clips_dir}")
        print("\nRun with:")
        print("   --interactive  for manual evaluation")
        print("   --auto         for automated heuristics")
        
        for clip in clips[:10]:
            info = evaluator.get_video_info(clip)
            print(f"   - {clip.name} ({info['duration']:.1f}s, {info['file_size_mb']:.1f}MB)")


if __name__ == "__main__":
    main()
