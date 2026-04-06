"""
Usage Analytics Service — Phase 20

Tracks per-user API call counts in Redis using daily-bucketed counters.

Key schema:
  usage:{user_id}:{YYYY-MM-DD}:{endpoint}  →  integer count
  usage_total:{user_id}:{endpoint}          →  lifetime integer count

Retention: daily keys expire after 90 days.
"""

import logging
from datetime import date, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_DAILY_TTL = 60 * 60 * 24 * 90   # 90 days


async def _redis():
    from src.workers.job_queue import JobQueue
    return await JobQueue.get_pool()


# ── Recording ─────────────────────────────────────────────────────────────────

async def record_usage(user_id: str, endpoint: str, count: int = 1) -> None:
    """Increment the usage counter for a user+endpoint pair (today's bucket)."""
    try:
        r = await _redis()
        today = date.today().isoformat()
        daily_key = f"usage:{user_id}:{today}:{endpoint}"
        total_key = f"usage_total:{user_id}:{endpoint}"
        pipe = r.pipeline()
        pipe.incr(daily_key)
        pipe.expire(daily_key, _DAILY_TTL)
        pipe.incr(total_key)
        await pipe.execute()
    except Exception as exc:
        logger.warning("[usage] record_usage failed user=%s endpoint=%s: %s",
                       user_id, endpoint, exc)


# ── Reading ────────────────────────────────────────────────────────────────────

async def get_daily_usage(
    user_id: str,
    endpoint: Optional[str] = None,
    days: int = 7,
) -> List[Dict]:
    """
    Return per-day call counts for the last `days` days.
    If `endpoint` is None, sums across all endpoints for each day.
    """
    try:
        r = await _redis()
        today = date.today()
        results = []
        for i in range(days - 1, -1, -1):
            day = (today - timedelta(days=i)).isoformat()
            if endpoint:
                key = f"usage:{user_id}:{day}:{endpoint}"
                val = await r.get(key)
                results.append({"date": day, "endpoint": endpoint,
                                 "count": int(val) if val else 0})
            else:
                pattern = f"usage:{user_id}:{day}:*"
                keys = await r.keys(pattern)
                total = 0
                by_endpoint: Dict[str, int] = {}
                for k in keys:
                    k_str = k.decode() if isinstance(k, bytes) else k
                    ep = k_str.split(":")[-1]
                    val = await r.get(k)
                    n = int(val) if val else 0
                    total += n
                    by_endpoint[ep] = n
                results.append({"date": day, "total": total, "by_endpoint": by_endpoint})
        return results
    except Exception as exc:
        logger.warning("[usage] get_daily_usage failed: %s", exc)
        return []


async def get_total_usage(user_id: str) -> Dict[str, int]:
    """Return lifetime total call counts per endpoint for a user."""
    try:
        r = await _redis()
        pattern = f"usage_total:{user_id}:*"
        keys = await r.keys(pattern)
        totals: Dict[str, int] = {}
        for k in keys:
            k_str = k.decode() if isinstance(k, bytes) else k
            endpoint = k_str.split(":")[-1]
            val = await r.get(k)
            totals[endpoint] = int(val) if val else 0
        return totals
    except Exception as exc:
        logger.warning("[usage] get_total_usage failed: %s", exc)
        return {}


async def get_usage_summary(user_id: str, days: int = 7) -> Dict:
    """Return a combined summary: daily breakdown + totals."""
    daily = await get_daily_usage(user_id, days=days)
    totals = await get_total_usage(user_id)
    grand_total = sum(totals.values())
    return {
        "user_id": user_id,
        "period_days": days,
        "grand_total": grand_total,
        "totals_by_endpoint": totals,
        "daily": daily,
    }
