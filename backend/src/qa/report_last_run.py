"""
QA Report — read latest sanity check results and generate a human-readable report.

Usage
-----
    python -m src.qa.report_last_run
    python -m src.qa.report_last_run --format=markdown
    python -m src.qa.report_last_run --path=output/qa_clips/2026-05-16/qa_results_20260516_120000.json

Output
------
- JSON report written to ``output/qa_clips/report_{run_id}.json``
- Markdown report written to ``output/qa_clips/report_{run_id}.md``
- Both also copied to ``output/qa_clips/latest_report.json`` / ``.md``
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

QA_OUTPUT_ROOT = Path("output") / "qa_clips"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _find_latest_results(results_root: Path) -> Optional[Path]:
    """Find the most recent QA results JSON file."""
    # First try latest.json symlink
    latest = results_root / "latest.json"
    if latest.exists():
        return latest

    # Fallback: scan date directories for newest qa_results_*.json
    if not results_root.exists():
        return None

    candidates: List[Path] = []
    for date_dir in sorted(results_root.iterdir()):
        if date_dir.is_dir():
            for f in date_dir.iterdir():
                if f.name.startswith("qa_results_") and f.suffix == ".json":
                    candidates.append(f)

    if not candidates:
        return None

    # Sort by modification time, newest first
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def _load_results(path: Path) -> Optional[Dict[str, Any]]:
    """Load QA results from a JSON file."""
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to load results from %s: %s", path, exc)
        return None


def _icon(passed: bool) -> str:
    return "✅" if passed else "❌"


def _status_badge(passed: bool) -> str:
    return "PASS" if passed else "FAIL"


# ── Report generation ──────────────────────────────────────────────────────────

def generate_json_report(results: Dict[str, Any]) -> Dict[str, Any]:
    """
    Transform raw QA results into a structured JSON report.

    Adds per-clip summaries and aggregate statistics.
    """
    summary = results.get("summary", {})
    clips = results.get("clips", [])

    clip_summaries: List[Dict[str, Any]] = []
    for clip in clips:
        sanity = clip.get("sanity_report")
        if sanity is None:
            clip_summaries.append({
                "source_name": clip.get("source_name", "unknown"),
                "category": clip.get("category", "unknown"),
                "generated": clip.get("generated", False),
                "clip_path": clip.get("clip_path"),
                "overall_pass": False,
                "checks": [],
                "failed_checks": ["Pipeline failed to generate clip"],
            })
            continue

        checks = sanity.get("checks", [])
        failed = [c["name"] for c in checks if not c["passed"]]

        clip_summaries.append({
            "source_name": clip.get("source_name", "unknown"),
            "category": clip.get("category", "unknown"),
            "generated": clip.get("generated", True),
            "clip_path": sanity.get("clip_path"),
            "overall_pass": sanity.get("overall_pass", False),
            "checks": checks,
            "failed_checks": failed,
        })

    total = len(clip_summaries)
    passed = sum(1 for c in clip_summaries if c["overall_pass"])
    failed = total - passed

    report = {
        "report_id": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "generated_at": datetime.now().isoformat(),
        "run_id": results.get("run_id", "unknown"),
        "preset": results.get("preset", "unknown"),
        "total_sources": results.get("total_sources", 0),
        "clips_generated": results.get("clips_generated", 0),
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "overall": "pass" if failed == 0 else "fail",
        },
        "clips": clip_summaries,
    }

    return report


def generate_markdown_report(report: Dict[str, Any]) -> str:
    """Generate a human-readable Markdown report from the JSON report."""
    lines: List[str] = []
    summary = report["summary"]

    lines.append("# ViraClip QA Sanity Report\n")
    lines.append(f"**Run ID:** {report['run_id']}")
    lines.append(f"**Generated:** {report['generated_at']}")
    lines.append(f"**Preset:** {report['preset']}")
    lines.append(f"**Sources:** {report['total_sources']} total, {report['clips_generated']} generated\n")

    # ── Summary bar ───────────────────────────────────────────────────────
    total = summary["total"]
    passed = summary["passed"]
    failed = summary["failed"]
    pass_pct = (passed / total * 100) if total > 0 else 0.0

    lines.append("## Summary\n")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total clips | {total} |")
    lines.append(f"| ✅ Passed | {passed} |")
    lines.append(f"| ❌ Failed | {failed} |")
    lines.append(f"| Pass rate | {pass_pct:.0f}% |")
    lines.append(f"| **Overall** | **{summary['overall'].upper()}** |")
    lines.append("")

    # ── Per-clip details ──────────────────────────────────────────────────
    lines.append("## Per-Clip Results\n")

    for clip in report["clips"]:
        source = clip["source_name"]
        category = clip["category"]
        status_icon = _icon(clip["overall_pass"])
        status_text = _status_badge(clip["overall_pass"])

        lines.append(f"### {status_icon} {source} ({category}) — **{status_text}**\n")

        if not clip["generated"]:
            lines.append("⚠️ *Pipeline failed — clip was not generated.*\n")
            continue

        lines.append(f"- **Path:** `{clip['clip_path']}`")

        if clip["failed_checks"]:
            lines.append(f"- **Failed checks:** {', '.join(clip['failed_checks'])}")

        lines.append("")
        lines.append("| Check | Status | Details |")
        lines.append("|-------|--------|---------|")

        for check in clip.get("checks", []):
            c_icon = _icon(check["passed"])
            c_status = _status_badge(check["passed"])
            details = check.get("details", "").replace("\n", " ")[:120]
            lines.append(f"| {check['name']} | {c_icon} {c_status} | {details} |")

        lines.append("")

    # ── Recommendations ───────────────────────────────────────────────────
    lines.append("## Recommendations\n")

    all_failed_checks: List[str] = []
    for clip in report["clips"]:
        all_failed_checks.extend(clip.get("failed_checks", []))

    if not all_failed_checks:
        lines.append("🎉 All checks passed! No recommendations.")
    else:
        from collections import Counter
        check_counts = Counter(all_failed_checks)
        for check_name, count in check_counts.most_common():
            lines.append(f"- **{check_name}** — failed on {count} clip(s)")

        lines.append("")
        lines.append("### Suggested Actions\n")

        if "Triple Subtitles" in check_counts:
            lines.append("- **Triple Subtitles:** Check subtitle generation config. Ensure only one embedded subtitle stream is added. Disable burned-in subtitles if embedded streams are present.")
        if "B-Roll Diversity" in check_counts:
            lines.append("- **B-Roll Diversity:** Increase B-roll source variety. Add more unique clips from Pexels or AI generation.")
        if "Stable Framing" in check_counts:
            lines.append("- **Stable Framing:** Apply stabilization filter or reduce camera movement. Check if impact zoom is too aggressive.")
        if "Audio Sync & Loudness" in check_counts:
            lines.append("- **Audio Sync & Loudness:** Verify loudnorm is applied (target -14 LUFS). Check audio-video sync in the rendering pipeline.")

    lines.append("")
    lines.append("---")
    lines.append(f"*Report generated by ViraClip QA at {report['generated_at']}*")

    return "\n".join(lines)


# ── Save helpers ───────────────────────────────────────────────────────────────

def save_report(
    json_report: Dict[str, Any],
    markdown_report: str,
    output_root: Path,
) -> None:
    """Save both JSON and Markdown reports to disk."""
    report_id = json_report["report_id"]
    output_root.mkdir(parents=True, exist_ok=True)

    # JSON
    json_path = output_root / f"report_{report_id}.json"
    with open(json_path, "w") as f:
        json.dump(json_report, f, indent=2, default=str)
    logger.info("JSON report saved to %s", json_path)

    # Markdown
    md_path = output_root / f"report_{report_id}.md"
    with open(md_path, "w") as f:
        f.write(markdown_report)
    logger.info("Markdown report saved to %s", md_path)

    # Latest copies
    try:
        latest_json = output_root / "latest_report.json"
        with open(latest_json, "w") as f:
            json.dump(json_report, f, indent=2, default=str)
    except OSError as exc:
        logger.warning("Could not write latest_report.json: %s", exc)

    try:
        latest_md = output_root / "latest_report.md"
        with open(latest_md, "w") as f:
            f.write(markdown_report)
    except OSError as exc:
        logger.warning("Could not write latest_report.md: %s", exc)


# ── Main entry point ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a QA sanity report from the latest run results.",
    )
    parser.add_argument(
        "--path",
        type=str,
        default=None,
        help="Path to a specific QA results JSON file (default: auto-detect latest)",
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["json", "markdown", "both"],
        default="both",
        help="Output format (default: both)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Custom output directory (default: output/qa_clips/)",
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

    output_root = Path(args.output) if args.output else QA_OUTPUT_ROOT

    # ── Locate results ────────────────────────────────────────────────────
    if args.path:
        results_path = Path(args.path)
        if not results_path.exists():
            logger.error("Specified results file not found: %s", results_path)
            sys.exit(1)
    else:
        found = _find_latest_results(output_root)
        if found is None:
            logger.error(
                "No QA results found in %s. "
                "Run `python -m src.qa.generate_test_clips` first.",
                output_root,
            )
            sys.exit(1)
        results_path = found

    logger.info("Loading results from %s", results_path)

    # ── Load and generate report ──────────────────────────────────────────
    results = _load_results(results_path)
    if results is None:
        logger.error("Failed to load results.")
        sys.exit(1)

    json_report = generate_json_report(results)
    markdown_report = generate_markdown_report(json_report)

    # ── Output ────────────────────────────────────────────────────────────
    if args.format in ("json", "both"):
        save_report(json_report, markdown_report, output_root)

    if args.format in ("markdown", "both"):
        print(markdown_report)
    elif args.format == "json":
        print(json.dumps(json_report, indent=2, default=str))

    # ── Exit code ─────────────────────────────────────────────────────────
    overall = json_report["summary"]["overall"]
    sys.exit(0 if overall == "pass" else 1)


if __name__ == "__main__":
    main()
