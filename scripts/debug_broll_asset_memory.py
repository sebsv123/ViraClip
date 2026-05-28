#!/usr/bin/env python3
"""Inspect and update B-roll asset usage memory."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from src.services.broll_asset_memory import AssetUsageMemory  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", default="")
    parser.add_argument("--last-days", type=int, default=7)
    parser.add_argument("--mark-bad", default="")
    parser.add_argument("--flag", default="irrelevant", choices=["good", "okay", "weak", "bad", "irrelevant", "overused"])
    parser.add_argument("--reason", default="manual_debug_mark")
    args = parser.parse_args()

    memory = AssetUsageMemory()
    if args.mark_bad:
        memory.mark_asset_quality(args.mark_bad, args.flag, args.reason)

    records = memory.data.get("records", {})
    flags = memory.data.get("quality_flags", {})
    print(f"memory_path={memory.path}")
    print(f"records={len(records)} quality_flags={len(flags)}")

    repeated: dict[str, list[str]] = {}
    for asset_id, record in records.items():
        if args.task_id and record.get("task_id") != args.task_id:
            continue
        fp = record.get("visual_fingerprint") or "unknown"
        repeated.setdefault(fp, []).append(asset_id)
        print(
            "record",
            json.dumps(
                {
                    "asset_id": asset_id,
                    "source": record.get("source"),
                    "category": record.get("category"),
                    "task_id": record.get("task_id"),
                    "clip_index": record.get("clip_index"),
                    "last_used_at": record.get("last_used_at"),
                    "fingerprint": fp,
                    "score": record.get("score"),
                    "flag": flags.get(asset_id, {}).get("flag") if isinstance(flags.get(asset_id), dict) else None,
                },
                ensure_ascii=False,
            ),
        )

    print("repeated_fingerprints")
    for fp, asset_ids in sorted(repeated.items()):
        if len(asset_ids) > 1:
            print(json.dumps({"fingerprint": fp, "asset_ids": asset_ids}, ensure_ascii=False))

    print("quarantine")
    for asset_id, flag in sorted(flags.items()):
        print(json.dumps({"asset_id": asset_id, **flag}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
