"""Persistent B-roll asset usage memory for Beta Clean editorial freshness."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_DEFAULT_ASSET_DIR = "/app/assets/broll"
_MEMORY_FILENAME = ".asset_usage_memory.json"
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".avif"}


@dataclass
class AssetUsageRecord:
    asset_id: str
    source: str
    asset_path_or_url: str
    category: str
    visual_fingerprint: str
    task_id: str
    clip_index: int
    intent_type: str
    central_topic: str
    selected_at: str
    score: float
    user_quality_flag: Optional[str]
    rejection_count: int
    last_used_at: str


@dataclass
class AssetFreshness:
    asset_id: str
    visual_fingerprint: str
    freshness_score: int
    penalty: float
    reasons: list[str]
    last_used_at: Optional[str]
    user_quality_flag: Optional[str]
    rejection_count: int
    quarantined: bool = False


def _asset_root() -> Path:
    return Path(os.environ.get("LOCAL_BROLL_ASSET_DIR", _DEFAULT_ASSET_DIR))


def default_memory_path() -> Path:
    return Path(os.environ.get("BROLL_ASSET_MEMORY_PATH", str(_asset_root() / _MEMORY_FILENAME)))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return None


def asset_id_for(source: str, asset_path_or_url: str, provider_asset_id: Optional[str] = None) -> str:
    source = (source or "unknown").lower()
    if provider_asset_id:
        return f"{source}:{provider_asset_id}"
    raw = str(asset_path_or_url or "")
    if source == "local":
        for marker in ("/app/assets/broll/", "assets/broll/"):
            if marker in raw:
                return raw.split(marker, 1)[1].lstrip("/")
    if "/uploads/broll/" in raw:
        return f"{source}:{Path(raw).name}"
    digest = hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"{source}:{digest}"


def visual_texture_for(category: str, asset_path_or_url: str) -> str:
    text = f"{category} {asset_path_or_url}".lower()
    if category == "documents_admin" or any(term in text for term in ("document", "paperwork", "contract", "policy", "signing")):
        return "documents_closeup"
    if category in {"family_protection", "emotional_reassurance", "home_responsibility"} or any(term in text for term in ("family", "parents", "home", "child")):
        return "family_home"
    if category == "advisor_consultation" or "advisor" in text or "consultation" in text:
        return "advisor_consultation"
    if category == "financial_planning" or any(term in text for term in ("financial", "budget", "mortgage", "planning")):
        return "financial_planning"
    if any(term in text for term in ("office", "handshake", "business")):
        return "generic_office"
    if any(term in text for term in ("tea", "coffee", "meditation", "yoga", "wellness")):
        return "wellness"
    return "unknown"


def visual_fingerprint_for(source: str, asset_path_or_url: str, category: str) -> str:
    texture = visual_texture_for(category, asset_path_or_url)
    stem = Path(str(asset_path_or_url)).stem.lower()
    if source in {"pexels", "stock", "pixabay", "coverr"} and stem:
        return f"{source}:{category}:{texture}:{stem}"
    return f"{category}:{texture}:{stem}"


class AssetUsageMemory:
    def __init__(self, path: Optional[Path] = None):
        self.path = path or default_memory_path()
        self.data = self._load()

    def _empty(self) -> Dict[str, Any]:
        return {"version": 1, "records": {}, "fingerprints": {}, "quality_flags": {}, "recent": []}

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            logger.info("[asset-memory] loaded records=0 path=%s", self.path)
            return self._empty()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("memory root is not an object")
            data.setdefault("records", {})
            data.setdefault("fingerprints", {})
            data.setdefault("quality_flags", {})
            data.setdefault("recent", [])
            logger.info("[asset-memory] loaded records=%d path=%s", len(data.get("records", {})), self.path)
            return data
        except Exception as exc:
            backup = self.path.with_suffix(self.path.suffix + ".corrupt")
            try:
                self.path.rename(backup)
            except Exception:
                pass
            logger.warning("[asset-memory] corrupt memory reset path=%s error=%s", self.path, exc)
            return self._empty()

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(f".{self.path.name}.tmp")
            tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        except Exception as exc:
            logger.warning("[asset-memory] save failed path=%s error=%s", self.path, exc)

    def freshness(
        self,
        source: str,
        asset_path_or_url: str,
        category: str,
        task_id: Optional[str] = None,
        provider_asset_id: Optional[str] = None,
    ) -> AssetFreshness:
        asset_id = asset_id_for(source, asset_path_or_url, provider_asset_id)
        fingerprint = visual_fingerprint_for(source, asset_path_or_url, category)
        quality = self.data.get("quality_flags", {}).get(asset_id, {})
        flag = quality.get("flag") if isinstance(quality, dict) else None
        rejection_count = int(quality.get("rejection_count", 0) if isinstance(quality, dict) else 0)
        reasons: list[str] = []
        penalty = 0.0
        freshness_score = 100

        cooldown_until = quality.get("cooldown_until") if isinstance(quality, dict) else None
        cooldown_dt = _parse_dt(cooldown_until)
        if cooldown_dt and cooldown_dt > datetime.now(timezone.utc):
            penalty -= 80
            freshness_score = 10
            reasons.append("quality_cooldown_active:-80")
            logger.info(
                "[broll-memory] quality_flag=%s cooldown_until=%s",
                flag or "temporarily_suppressed",
                cooldown_until,
            )
        elif cooldown_dt and cooldown_dt <= datetime.now(timezone.utc):
            reasons.append("quality_cooldown_expired:0")

        if flag in {"bad", "irrelevant", "forbidden_visual", "irrelevant_visual"} or rejection_count >= 3:
            logger.info("[asset-memory] reject asset=%s reason=user_quality_flag_bad flag=%s rejection_count=%d", asset_id, flag, rejection_count)
            return AssetFreshness(asset_id, fingerprint, 0, -200.0, ["quality_reject:-200"], None, flag, rejection_count, True)
        if flag in {"overused", "overused_recent", "temporarily_suppressed"}:
            if not cooldown_dt or cooldown_dt <= datetime.now(timezone.utc):
                penalty -= 35
                reasons.append(f"quality_{flag}:-35")
        elif flag == "weak":
            penalty -= 40
            reasons.append("quality_weak:-40")

        record = self.data.get("records", {}).get(asset_id)
        last_used = record.get("last_used_at") if isinstance(record, dict) else None
        last_dt = _parse_dt(last_used)
        now = datetime.now(timezone.utc)
        if isinstance(record, dict) and task_id and record.get("task_id") == task_id:
            penalty -= 100
            freshness_score = 0
            reasons.append("same_task_exact_asset:-100")
        elif last_dt:
            age_hours = (now - last_dt).total_seconds() / 3600.0
            if age_hours < 24:
                penalty -= 80
                freshness_score = 10
                reasons.append("asset_used_24h:-80")
                logger.info("[asset-memory] recent_use asset=%s penalty=-80 window=24h", asset_id)
            elif age_hours < 72:
                penalty -= 60
                freshness_score = 40
                reasons.append("asset_used_3d:-60")
            elif age_hours < 168:
                penalty -= 35
                freshness_score = 70
                reasons.append("asset_used_7d:-35")

        fp_record = self.data.get("fingerprints", {}).get(fingerprint)
        if isinstance(fp_record, dict):
            if task_id and fp_record.get("task_id") == task_id:
                penalty -= 60
                reasons.append("same_task_visual_fingerprint:-60")
            elif _parse_dt(fp_record.get("last_used_at")):
                fp_age_hours = (now - _parse_dt(fp_record.get("last_used_at"))).total_seconds() / 3600.0  # type: ignore[union-attr]
                if fp_age_hours < 24:
                    penalty -= 25
                    reasons.append("visual_fingerprint_24h:-25")

        return AssetFreshness(asset_id, fingerprint, freshness_score, penalty, reasons, last_used, flag, rejection_count)

    def record_use(
        self,
        *,
        source: str,
        asset_path_or_url: str,
        category: str,
        task_id: str,
        clip_index: int,
        intent_type: str,
        central_topic: str,
        score: float,
        provider_asset_id: Optional[str] = None,
    ) -> AssetUsageRecord:
        asset_id = asset_id_for(source, asset_path_or_url, provider_asset_id)
        fingerprint = visual_fingerprint_for(source, asset_path_or_url, category)
        quality = self.data.get("quality_flags", {}).get(asset_id, {})
        now = _now_iso()
        record = AssetUsageRecord(
            asset_id=asset_id,
            source=source,
            asset_path_or_url=asset_path_or_url,
            category=category,
            visual_fingerprint=fingerprint,
            task_id=task_id,
            clip_index=clip_index,
            intent_type=intent_type,
            central_topic=central_topic,
            selected_at=now,
            score=float(score),
            user_quality_flag=quality.get("flag") if isinstance(quality, dict) else None,
            rejection_count=int(quality.get("rejection_count", 0) if isinstance(quality, dict) else 0),
            last_used_at=now,
        )
        self.data.setdefault("records", {})[asset_id] = asdict(record)
        self.data.setdefault("fingerprints", {})[fingerprint] = {"asset_id": asset_id, "task_id": task_id, "clip_index": clip_index, "last_used_at": now}
        recent = self.data.setdefault("recent", [])
        recent[:] = [item for item in recent if item != asset_id]
        recent.insert(0, asset_id)
        del recent[100:]
        self.save()
        logger.info("[asset-memory] recorded asset=%s fingerprint=%s task=%s clip=%d", asset_id, fingerprint, task_id, clip_index)
        return record

    def mark_asset_quality(self, asset_id: str, flag: str, reason: str, cooldown_hours: Optional[float] = None) -> None:
        flags = self.data.setdefault("quality_flags", {})
        entry = flags.setdefault(asset_id, {})
        entry["flag"] = flag
        entry["reason"] = reason
        entry["updated_at"] = _now_iso()
        if cooldown_hours and cooldown_hours > 0:
            entry["cooldown_until"] = (datetime.now(timezone.utc) + timedelta(hours=float(cooldown_hours))).isoformat()
        elif flag not in {"overused_recent", "temporarily_suppressed", "repeated_in_task"}:
            entry.pop("cooldown_until", None)
        if flag in {"bad", "irrelevant", "forbidden_visual", "irrelevant_visual"}:
            entry["rejection_count"] = int(entry.get("rejection_count", 0)) + 1
        self.save()
        logger.info(
            "[asset-memory] quarantine asset=%s reason=%s flag=%s cooldown_until=%s",
            asset_id,
            reason,
            flag,
            entry.get("cooldown_until"),
        )
        logger.info("[broll-memory] quality_flag=%s cooldown_until=%s", flag, entry.get("cooldown_until"))


def mark_asset_quality(asset_id: str, flag: str, reason: str, cooldown_hours: Optional[float] = None) -> None:
    AssetUsageMemory().mark_asset_quality(asset_id, flag, reason, cooldown_hours=cooldown_hours)
