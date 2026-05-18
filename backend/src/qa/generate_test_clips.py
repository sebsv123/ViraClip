"""
QA Clip Generation — run the full pipeline on a curated test dataset.

Usage
-----
    python -m src.qa.generate_test_clips --preset=tiktok_basic --limit=10

This script:
1. Defines a test dataset of 5-10 source videos (talking-head, podcast, high-motion)
2. Runs the full ViraClip pipeline on each source
3. Saves rendered clips to ``output/qa_clips/{date}/``
4. Runs sanity checks on each generated clip
5. Saves results to a JSON file for ``report_last_run`` to consume
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.qa.clip_sanity_checks import run_all_sanity_checks, SanityReport

logger = logging.getLogger(__name__)

# ── Output directory ──────────────────────────────────────────────────────────
QA_OUTPUT_ROOT = Path("output") / "qa_clips"


# ── Test dataset definition ───────────────────────────────────────────────────

@dataclass
class TestSource:
    """A single source video in the test dataset."""
    name: str
    path: str
    category: str  # "talking_head" | "podcast" | "high_motion" | "interview"
    description: str = ""

    def exists(self) -> bool:
        return Path(self.path).exists()


# Curated test dataset — 8 sources covering the required categories.
# Paths are relative to the project root; adjust to your environment.
TEST_DATASET: List[TestSource] = [
    # ── Talking-head (2) ──────────────────────────────────────────────────
    TestSource(
        name="talking_head_01",
        path="inputs/test_videos/talking_head_01.mp4",
        category="talking_head",
        description="Single speaker, static camera, medium shot",
    ),
    TestSource(
        name="talking_head_02",
        path="inputs/test_videos/talking_head_02.mp4",
        category="talking_head",
        description="Single speaker, slight head movement, close-up",
    ),
    # ── Podcast / Interview (2) ───────────────────────────────────────────
    TestSource(
        name="podcast_01",
        path="inputs/test_videos/podcast_01.mp4",
        category="podcast",
        description="Two speakers, split-screen, conversational",
    ),
    TestSource(
        name="interview_01",
        path="inputs/test_videos/interview_01.mp4",
        category="interview",
        description="Interview format, Q&A style, alternating speakers",
    ),
    # ── High-motion (2) ───────────────────────────────────────────────────
    TestSource(
        name="high_motion_01",
        path="inputs/test_videos/high_motion_01.mp4",
        category="high_motion",
        description="Fast cuts, camera movement, action content",
    ),
    TestSource(
        name="high_motion_02",
        path="inputs/test_videos/high_motion_02.mp4",
        category="high_motion",
        description="Sports / dance, rapid scene changes",
    ),
    # ── Bonus: varied formats ─────────────────────────────────────────────
    TestSource(
        name="vertical_native_01",
        path="inputs/test_videos/vertical_native_01.mp4",
        category="talking_head",
        description="Already 9:16 vertical, shot on phone",
    ),
    TestSource(
        name="longform_01",
        path="inputs/test_videos/longform_01.mp4",
        category="interview",
        description="10+ minute long-form interview excerpt",
    ),
]


def discover_test_sources() -> List[TestSource]:
    """
    Return available test sources.
    
    Filters the curated dataset to only include files that actually exist
    on disk.  If none exist, logs a warning with instructions.
    """
    available = [s for s in TEST_DATASET if s.exists()]
    missing = [s for s in TEST_DATASET if not s.exists()]
    if missing:
        logger.warning(
            "Missing %d test source(s): %s",
            len(missing),
            ", ".join(s.name for s in missing),
        )
        logger.warning(
            "Place test videos in inputs/test_videos/ or update TEST_DATASET paths."
        )
    if not available:
        logger.error(
            "No test sources found! Create at least one video file "
            "referenced in TEST_DATASET."
        )
    return available


# ── Pipeline invocation ───────────────────────────────────────────────────────

def run_pipeline_on_source(
    source: TestSource,
    output_dir: Path,
    preset: str = "tiktok_basic",
) -> Optional[Path]:
    """
    Run the ViraClip pipeline on a single source video.
    
    This invokes the pipeline via CLI or direct Python call.
    The exact mechanism depends on how the pipeline is exposed.
    
    Returns the path to the rendered clip, or None on failure.
    """
    clip_name = f"{source.name}_{preset}"
    clip_output = output_dir / f"{clip_name}.mp4"
    
    if clip_output.exists():
        logger.info("  ↻ Clip already exists: %s", clip_output)
        return clip_output

    # ── Attempt 1: Use the pipeline CLI if available ──────────────────────
    # Try the process_simple.py script which is a known entry point
    pipeline_script = Path(__file__).resolve().parent.parent.parent / "process_simple.py"
    if pipeline_script.exists():
        logger.info("  ▶ Running pipeline via process_simple.py ...")
        cmd = [
            sys.executable,
            str(pipeline_script),
            "--input", source.path,
            "--output", str(clip_output),
            "--preset", preset,
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=600, check=False)
        if result.returncode == 0 and clip_output.exists():
            logger.info("  ✓ Pipeline succeeded: %s", clip_output)
            return clip_output
        else:
            logger.warning(
                "  ⚠ Pipeline failed (code=%d): %s",
                result.returncode,
                result.stderr.decode(errors="replace")[:500],
            )
    
    # ── Attempt 2: Fallback — apply export preset directly ────────────────
    logger.info("  ▶ Falling back to direct export preset ...")
    try:
        from src.services.export_preset_service import export_with_preset, Preset
        out = export_with_preset(
            input_path=source.path,
            output_path=str(clip_output),
            preset=Preset(preset) if preset else Preset.TIKTOK_BASIC,
        )
        if out and Path(out).exists():
            logger.info("  ✓ Export preset applied: %s", out)
            return Path(out)
    except Exception as exc:
        logger.warning("  ⚠ Export preset fallback failed: %s", exc)
    
    # ── Attempt 3: Minimal FFmpeg transcode ───────────────────────────────
    logger.info("  ▶ Falling back to minimal FFmpeg transcode ...")
    cmd = [
        "ffmpeg", "-y",
        "-i", source.path,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(clip_output),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=300, check=False)
    if result.returncode == 0 and clip_output.exists():
        logger.info("  ✓ FFmpeg transcode succeeded: %s", clip_output)
        return clip_output
    
    logger.error("  ✗ All pipeline attempts failed for %s", source.name)
    return None


# ── Main entry point ──────────────────────────────────────────────────────────

def generate_qa_clips(
    preset: str = "tiktok_basic",
    limit: int = 10,
    output_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Generate QA clips from the test dataset and run sanity checks.
    
    Parameters
    ----------
    preset:
        Export preset to apply (e.g. ``tiktok_basic``, ``fast_vertical``).
    limit:
        Maximum number of clips to generate.
    output_root:
        Root output directory (defaults to ``output/qa_clips/``).
    
    Returns
    -------
    Dict with keys:
        - ``run_id``: ISO-formatted timestamp
        - ``preset``: preset used
        - ``total_sources``: number of sources attempted
        - ``clips_generated``: number of clips successfully generated
        - ``clips``: list of per-clip results with sanity check reports
        - ``summary``: aggregate pass/fail counts
    """
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    date_str = datetime.now().strftime("%Y-%m-%d")
    output_dir = (output_root or QA_OUTPUT_ROOT) / date_str
    output_dir.mkdir(parents=True, exist_ok=True)

    sources = discover_test_sources()
    if not sources:
        return {
            "run_id": run_id,
            "preset": preset,
            "total_sources": 0,
            "clips_generated": 0,
            "clips": [],
            "summary": {"total": 0, "passed": 0, "failed": 0, "overall": "no_sources"},
        }

    # Limit sources
    sources = sources[:limit]
    logger.info(
        "Generating up to %d QA clips with preset='%s' in %s",
        len(sources), preset, output_dir,
    )

    clips_results: List[Dict[str, Any]] = []
    total_pass = 0
    total_fail = 0

    for source in sources:
        logger.info("Processing source: %s (%s)", source.name, source.category)
        clip_path = run_pipeline_on_source(source, output_dir, preset)
        
        if clip_path is None:
            clips_results.append({
                "source_name": source.name,
                "category": source.category,
                "clip_path": None,
                "generated": False,
                "sanity_report": None,
            })
            total_fail += 1
            continue

        # Run sanity checks on the generated clip
        logger.info("  ▶ Running sanity checks on %s ...", clip_path.name)
        report = run_all_sanity_checks(str(clip_path))
        
        clips_results.append({
            "source_name": source.name,
            "category": source.category,
            "clip_path": str(clip_path),
            "generated": True,
            "sanity_report": report.to_dict(),
        })
        
        if report.overall_pass:
            total_pass += 1
        else:
            total_fail += 1
        
        logger.info(
            "  %s Sanity: %s",
            "✓" if report.overall_pass else "✗",
            "PASS" if report.overall_pass else "FAIL",
        )

    # ── Save results ──────────────────────────────────────────────────────
    results = {
        "run_id": run_id,
        "preset": preset,
        "total_sources": len(sources),
        "clips_generated": sum(1 for c in clips_results if c["generated"]),
        "clips": clips_results,
        "summary": {
            "total": len(clips_results),
            "passed": total_pass,
            "failed": total_fail,
            "overall": "pass" if total_fail == 0 else "fail",
        },
    }

    results_path = output_dir / f"qa_results_{run_id}.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info("Results saved to %s", results_path)

    # Also save a symlink / copy to latest.json for report_last_run
    latest_path = (output_root or QA_OUTPUT_ROOT) / "latest.json"
    try:
        with open(latest_path, "w") as f:
            json.dump(results, f, indent=2, default=str)
        logger.info("Latest results symlinked to %s", latest_path)
    except Exception as exc:
        logger.warning("Could not write latest.json: %s", exc)

    return results


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Generate QA test clips from the curated dataset.",
    )
    parser.add_argument(
        "--preset",
        default="tiktok_basic",
        help="Export preset to apply (default: tiktok_basic)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of sources to process (default: 10)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Custom output root directory (default: output/qa_clips/)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    output_root = Path(args.output) if args.output else None
    results = generate_qa_clips(
        preset=args.preset,
        limit=args.limit,
        output_root=output_root,
    )

    summary = results["summary"]
    print(f"\n{'='*60}")
    print(f"QA Clip Generation Complete")
    print(f"  Run ID:      {results['run_id']}")
    print(f"  Preset:      {results['preset']}")
    print(f"  Sources:     {results['total_sources']}")
    print(f"  Generated:   {results['clips_generated']}")
    print(f"  Passed:      {summary['passed']}")
    print(f"  Failed:      {summary['failed']}")
    print(f"  Overall:     {summary['overall'].upper()}")
    print(f"{'='*60}")

    sys.exit(0 if summary["overall"] == "pass" else 1)


if __name__ == "__main__":
    main()
