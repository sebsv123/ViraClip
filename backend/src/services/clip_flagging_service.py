"""
Clip Moderation/Flagging Service — Phase 27

User-driven report submission + auto-moderation rules engine.
Key schema:
  clip_reports:{clip_id}          → LIST of report records
  user_reports:{user_id}          → SET of clips reported by user
  clip_flag_meta:{clip_id}        → HASH: flags_count, auto_action, reviewed
  moderation_actions:{clip_id}    → LIST: actions taken (hide, strike, notify)

Auto-moderation triggers:
  - flags_count >= 3  → auto-hide clip (set auto_action="hidden")
  - flags_count >= 5  → auto-strike creator + hide clip
  - Content keywords detected in report → escalate to human review
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_KEY_REPORTS = "clip_reports"
_KEY_USER_REPORTS = "user_reports"
_KEY_FLAG_META = "clip_flag_meta"
_KEY_ACTIONS = "moderation_actions"

_AUTO_HIDE_THRESHOLD = 3
_AUTO_STRIKE_THRESHOLD = 5

_ESCALATION_KEYWORDS = {
    "csam", "child", "minor", "illegal", "violence", "death",
    "kill", "murder", "weapon", "gun", "terrorism", "extremist",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rkey(clip_id: str) -> str:
    return f"{_KEY_REPORTS}:{clip_id}"


def _ukey(user_id: str) -> str:
    return f"{_KEY_USER_REPORTS}:{user_id}"


def _fkey(clip_id: str) -> str:
    return f"{_KEY_FLAG_META}:{clip_id}"


def _akey(clip_id: str) -> str:
    return f"{_KEY_ACTIONS}:{clip_id}"


async def _redis():
    from src.workers.job_queue import JobQueue
    return await JobQueue.get_pool()


async def submit_report(
    clip_id: str,
    reporter_id: str,
    reason: str,
    details: str = "",
) -> Dict:
    """Submit a user report against a clip. Returns the report record."""
    r = await _redis()

    already_reported = await r.sismember(_ukey(reporter_id), clip_id)
    if already_reported:
        raise ValueError(f"User {reporter_id} already reported clip {clip_id}")

    report = {
        "report_id": f"rpt-{reporter_id[:6]}-{int(datetime.now().timestamp())}",
        "clip_id": clip_id,
        "reporter_id": reporter_id,
        "reason": reason,
        "details": details,
        "created_at": _now(),
    }
    await r.lpush(_rkey(clip_id), json.dumps(report))
    await r.sadd(_ukey(reporter_id), clip_id)

    new_count = await r.llen(_rkey(clip_id))
    await r.hset(_fkey(clip_id), mapping={
        "flags_count": new_count,
        "updated_at": _now(),
    })

    action_taken = await _evaluate_auto_action(clip_id, new_count, reason, details)
    return {**report, "flags_count": new_count, "action_taken": action_taken}


async def _evaluate_auto_action(
    clip_id: str, flags_count: int, reason: str, details: str
) -> Optional[str]:
    """Evaluate and apply auto-moderation rules. Returns action taken or None."""
    r = await _redis()
    combined_text = (reason + " " + details).lower()
    escalate = any(kw in combined_text for kw in _ESCALATION_KEYWORDS)

    action = None
    if escalate:
        action = "escalated"
        await r.hset(_fkey(clip_id), "auto_action", action)
        await r.hset(_fkey(clip_id), "escalated_at", _now())
    elif flags_count >= _AUTO_STRIKE_THRESHOLD:
        action = "strike_and_hide"
        await r.hset(_fkey(clip_id), "auto_action", action)
        await r.lpush(_akey(clip_id), json.dumps({
            "action": "hide_clip", "timestamp": _now(), "trigger": "auto_flag_threshold"
        }))
        await r.lpush(_akey(clip_id), json.dumps({
            "action": "creator_strike", "timestamp": _now(), "trigger": "auto_flag_threshold"
        }))
    elif flags_count >= _AUTO_HIDE_THRESHOLD:
        action = "hidden"
        await r.hset(_fkey(clip_id), "auto_action", action)
        await r.lpush(_akey(clip_id), json.dumps({
            "action": "hide_clip", "timestamp": _now(), "trigger": "auto_flag_threshold"
        }))

    if action:
        await r.hset(_fkey(clip_id), "last_action_at", _now())
    return action


async def get_clip_reports(clip_id: str, limit: int = 50) -> List[Dict]:
    """Return all reports against a clip."""
    try:
        r = await _redis()
        raw = await r.lrange(_rkey(clip_id), 0, limit - 1)
        return [
            json.loads(item.decode() if isinstance(item, bytes) else item)
            for item in raw
        ]
    except Exception as exc:
        logger.warning("[moderation] get_reports failed clip=%s: %s", clip_id, exc)
        return []


async def get_clip_flag_meta(clip_id: str) -> Optional[Dict]:
    """Return flag metadata for a clip."""
    try:
        r = await _redis()
        raw = await r.hgetall(_fkey(clip_id))
        if not raw:
            return None
        return {
            (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
            for k, v in raw.items()
        }
    except Exception as exc:
        logger.warning("[moderation] get_meta failed clip=%s: %s", clip_id, exc)
        return None


async def resolve_reports(clip_id: str, moderator_id: str, resolution: str) -> Dict:
    """Human moderator resolves all pending reports for a clip."""
    r = await _redis()
    await r.hset(_fkey(clip_id), mapping={
        "reviewed": "true",
        "reviewed_at": _now(),
        "moderator_id": moderator_id,
        "resolution": resolution,
    })
    await r.lpush(_akey(clip_id), json.dumps({
        "action": "human_review",
        "resolution": resolution,
        "moderator_id": moderator_id,
        "timestamp": _now(),
    }))
    return {"clip_id": clip_id, "resolved": True, "resolution": resolution}


async def has_user_reported(user_id: str, clip_id: str) -> bool:
    """Check if a user has already reported a specific clip."""
    try:
        r = await _redis()
        return bool(await r.sismember(_ukey(user_id), clip_id))
    except Exception:
        return False
