"""
CLI: python -m viraclip.metrics.summary [--last-days=7]

Prints an aggregated metrics summary for the given time window.
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ViraClip Metrics Summary — integration usage telemetry"
    )
    parser.add_argument(
        "--last-days",
        type=int,
        default=7,
        help="Number of days to look back (default: 7)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of formatted text",
    )
    args = parser.parse_args()

    try:
        from src.services.metrics_aggregator import get_summary, format_summary_text

        summary = get_summary(last_days=args.last_days)

        if args.json:
            import json
            print(json.dumps(summary, indent=2, default=str))
        else:
            print(format_summary_text(summary))

    except ImportError as e:
        print(f"[ERROR] Could not load metrics module: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] Failed to generate summary: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
