#!/usr/bin/env python3
"""Repair poisoned VPI B-roll asset memory flags.

This script only edits assets/broll/.asset_usage_memory.json when --apply is
passed. It always writes a report and creates a timestamped backup on apply.
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
MEMORY_PATH = ROOT / "assets/broll/.asset_usage_memory.json"
REPORT_JSON = ROOT / "reports/broll_memory_repair_report.json"
REPORT_MD = ROOT / "reports/broll_memory_repair_report.md"

TEMPORARY_TERMS = (
    "recent_exact_asset_24h",
    "overused",
    "cooldown",
    "repeated",
    "exact_repeat",
    "filename_repeat",
    "visual_fingerprint_repeat",
    "same_task",
)
FORBIDDEN_TERMS = (
    "tea",
    "té",
    "wellness",
    "meditation",
    "meditación",
    "yoga",
    "taza",
    "cup",
    "coffee",
    "café",
    "cafe",
    "spa",
    "emotional_reassurance/02.mp4",
    "forbidden",
    "hospital",
    "funeral",
)
REASONABLE_PREFIXES = (
    "family_protection/",
    "financial_planning/",
    "advisor_consultation/",
    "home_responsibility/",
    "documents_admin/",
)
NEVER_REHABILITATE = (
    "emotional_reassurance/02.mp4",
    "tea",
    "wellness",
    "meditation",
    "yoga",
    "spa",
    "coffee",
    "cup",
    "taza",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(value: Any) -> str:
    return str(value or "").replace("\\", "/").lower()


def _load_memory(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"version": 1, "records": {}, "fingerprints": {}, "quality_flags": {}, "recent": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _classify(asset_id: str, entry: Dict[str, Any], records: Dict[str, Any]) -> tuple[str, str]:
    reason = _norm(entry.get("reason"))
    flag = _norm(entry.get("flag"))
    record = records.get(asset_id, {}) if isinstance(records, dict) else {}
    path = _norm(record.get("asset_path_or_url") or asset_id)
    haystack = " ".join([asset_id.lower(), path, reason, flag])

    if any(term in haystack for term in NEVER_REHABILITATE):
        return "keep_forbidden", "never_rehabilitate"
    if any(term in haystack for term in FORBIDDEN_TERMS):
        return "keep_forbidden", "forbidden_visual"
    if any(term in haystack for term in TEMPORARY_TERMS):
        return "convert_cooldown", "temporary_usage_flag"
    if any(asset_id.startswith(prefix) for prefix in REASONABLE_PREFIXES):
        return "rehabilitate", "reasonable_local_asset"
    return "keep", "no_rule_matched"


def repair_memory(memory: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    repaired = json.loads(json.dumps(memory))
    flags = repaired.setdefault("quality_flags", {})
    records = repaired.get("records", {})
    report: Dict[str, Any] = {
        "memory_path": str(MEMORY_PATH),
        "generated_at": _now_iso(),
        "total_flags_before": len(flags),
        "rehabilitated": [],
        "kept_forbidden": [],
        "converted_to_cooldown": [],
        "kept": [],
    }

    cooldown_until = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    for asset_id, entry in list(flags.items()):
        if not isinstance(entry, dict):
            entry = {"flag": str(entry)}
        action, why = _classify(asset_id, entry, records)
        item = {
            "asset_id": asset_id,
            "old_flag": entry.get("flag"),
            "old_reason": entry.get("reason"),
            "action": action,
            "why": why,
        }
        if action == "rehabilitate":
            flags.pop(asset_id, None)
            report["rehabilitated"].append(item)
        elif action == "convert_cooldown":
            new_entry = dict(entry)
            new_entry["flag"] = "overused_recent"
            new_entry["reason"] = why
            new_entry["updated_at"] = _now_iso()
            new_entry["cooldown_until"] = cooldown_until
            new_entry["rejection_count"] = 0
            flags[asset_id] = new_entry
            item["new_flag"] = "overused_recent"
            item["cooldown_until"] = cooldown_until
            report["converted_to_cooldown"].append(item)
        elif action == "keep_forbidden":
            new_entry = dict(entry)
            new_entry["flag"] = "forbidden_visual" if why == "forbidden_visual" else "irrelevant_visual"
            new_entry["reason"] = why
            new_entry["updated_at"] = _now_iso()
            flags[asset_id] = new_entry
            item["new_flag"] = new_entry["flag"]
            report["kept_forbidden"].append(item)
        else:
            report["kept"].append(item)

    report["total_flags_after"] = len(flags)
    report["rehabilitated_count"] = len(report["rehabilitated"])
    report["kept_forbidden_count"] = len(report["kept_forbidden"])
    report["converted_to_cooldown_count"] = len(report["converted_to_cooldown"])
    return repaired, report


def write_reports(report: Dict[str, Any]) -> None:
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [
        "# B-roll Memory Repair Report",
        "",
        f"- memory_path: `{report.get('memory_path')}`",
        f"- backup_path: `{report.get('backup_path')}`",
        f"- dry_run: `{report.get('dry_run')}`",
        f"- total_flags_before: `{report.get('total_flags_before')}`",
        f"- total_flags_after: `{report.get('total_flags_after')}`",
        f"- rehabilitated: `{report.get('rehabilitated_count')}`",
        f"- kept_forbidden: `{report.get('kept_forbidden_count')}`",
        f"- converted_to_cooldown: `{report.get('converted_to_cooldown_count')}`",
        "",
        "## Rehabilitated",
    ]
    for item in report.get("rehabilitated", []):
        lines.append(f"- `{item['asset_id']}` old=`{item.get('old_flag')}` why=`{item.get('why')}`")
    lines.append("")
    lines.append("## Converted To Cooldown")
    for item in report.get("converted_to_cooldown", []):
        lines.append(f"- `{item['asset_id']}` old=`{item.get('old_flag')}` until=`{item.get('cooldown_until')}`")
    lines.append("")
    lines.append("## Kept Forbidden")
    for item in report.get("kept_forbidden", []):
        lines.append(f"- `{item['asset_id']}` new=`{item.get('new_flag')}` why=`{item.get('why')}`")
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Preview repair without writing memory")
    parser.add_argument("--apply", action="store_true", help="Apply repair to memory file")
    args = parser.parse_args()
    if not args.dry_run and not args.apply:
        parser.error("Use --dry-run or --apply")

    memory = _load_memory(MEMORY_PATH)
    repaired, report = repair_memory(memory)
    report["dry_run"] = bool(args.dry_run)
    backup_path = None
    if args.apply:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = MEMORY_PATH.with_name(f"{MEMORY_PATH.name}.bak.{timestamp}")
        if MEMORY_PATH.exists():
            shutil.copy2(MEMORY_PATH, backup_path)
        MEMORY_PATH.write_text(json.dumps(repaired, indent=2, ensure_ascii=False), encoding="utf-8")
    report["backup_path"] = str(backup_path) if backup_path else None
    write_reports(report)

    print(f"[broll-memory-repair] backup={report['backup_path']}")
    print(f"[broll-memory-repair] rehabilitated={report['rehabilitated_count']}")
    print(f"[broll-memory-repair] kept_forbidden={report['kept_forbidden_count']}")
    print(f"[broll-memory-repair] converted_to_cooldown={report['converted_to_cooldown_count']}")
    print(f"[broll-memory-repair] report_json={REPORT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
