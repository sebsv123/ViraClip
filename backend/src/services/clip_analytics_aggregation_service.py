"""
Clip Analytics Aggregation Service — Phase 27

Daily and weekly rollup of clip metrics stored in Redis hashes.
Key schema:
  clip_daily:{clip_id}:{date}   → HASH: views, unique_viewers, avg_watch_time, completions
  clip_weekly:{clip_id}:{week}  → HASH: aggregated metrics for ISO week
  analytics_index:{clip_id}     → SET of dates/weeks with data

Provides efficient time-series queries without heavy DB load.
"""

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_KEY_DAILY = "clip_daily"
_KEY_WEEKLY = "clip_weekly"
_KEY_INDEX = "analytics_index"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dkey(clip_id: str, day: str) -> str:
    return f"{_KEY_DAILY}:{clip_id}:{day}"


def _wkey(clip_id: str, week: str) -> str:
    return f"{_KEY_WEEKLY}:{clip_id}:{week}"


def _ikey(clip_id: str) -> str:
    return f"{_KEY_INDEX}:{clip_id}"


def _today() -> str:
    return date.today().isoformat()


def _this_week() -> str:
    return datetime.now().strftime("%G-W%V")


def _parse_week(week_str: str) -> Tuple[int, int]:
    """Parse '2026-W12' format to (year, week)."""
    year, wk = week_str.split("-W")
    return int(year), int(wk)


async def _redis():
    from src.workers.job_queue import JobQueue
    return await JobQueue.get_pool()


async def record_view(
    clip_id: str,
    viewer_id: str,
    watch_seconds: float,
    completed: bool = False,
) -> Dict:
    """Record a single view event, updating daily and weekly rollups."""
    r = await _redis()
    today = _today()
    week = _this_week()

    day_key = _dkey(clip_id, today)
    week_key = _wkey(clip_id, week)

    pipe = r.pipeline()
    pipe.hincrby(day_key, "views", 1)
    pipe.hincrby(day_key, "watch_seconds_total", int(watch_seconds))
    pipe.sadd(f"{day_key}:viewers", viewer_id)
    if completed:
        pipe.hincrby(day_key, "completions", 1)
    pipe.expire(day_key, 60 * 60 * 24 * 90)  # 90 days

    pipe.hincrby(week_key, "views", 1)
    pipe.hincrby(week_key, "watch_seconds_total", int(watch_seconds))
    pipe.sadd(f"{week_key}:viewers", viewer_id)
    if completed:
        pipe.hincrby(week_key, "completions", 1)
    pipe.expire(week_key, 60 * 60 * 24 * 365)  # 1 year

    pipe.sadd(_ikey(clip_id), today)
    pipe.sadd(_ikey(clip_id), week)

    await pipe.execute()

    return {
        "clip_id": clip_id,
        "date": today,
        "week": week,
        "watch_seconds": watch_seconds,
        "completed": completed,
    }


async def get_daily_stats(clip_id: str, day: Optional[str] = None) -> Dict:
    """Return daily stats for a clip. Defaults to today."""
    if day is None:
        day = _today()
    try:
        r = await _redis()
        raw = await r.hgetall(_dkey(clip_id, day))
        viewers = await r.scard(f"{_dkey(clip_id, day)}:viewers")
        if not raw and viewers == 0:
            return {"clip_id": clip_id, "date": day, "views": 0, "unique_viewers": 0}

        data = {
            (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
            for k, v in raw.items()
        }
        views = int(data.get("views", 0))
        watch_total = int(data.get("watch_seconds_total", 0))
        avg_watch = round(watch_total / views, 2) if views > 0 else 0.0

        return {
            "clip_id": clip_id,
            "date": day,
            "views": views,
            "unique_viewers": viewers,
            "avg_watch_seconds": avg_watch,
            "completions": int(data.get("completions", 0)),
            "watch_seconds_total": watch_total,
        }
    except Exception as exc:
        logger.warning("[analytics] daily stats failed: %s", exc)
        return {"clip_id": clip_id, "date": day, "views": 0, "unique_viewers": 0}


async def get_weekly_stats(clip_id: str, week: Optional[str] = None) -> Dict:
    """Return weekly stats for a clip. Defaults to current week."""
    if week is None:
        week = _this_week()
    try:
        r = await _redis()
        raw = await r.hgetall(_wkey(clip_id, week))
        viewers = await r.scard(f"{_wkey(clip_id, week)}:viewers")
        if not raw and viewers == 0:
            return {"clip_id": clip_id, "week": week, "views": 0, "unique_viewers": 0}

        data = {
            (k.decode() if isinstance(k, bytes) else k): (v.decode() if isinstance(v, bytes) else v)
            for k, v in raw.items()
        }
        views = int(data.get("views", 0))
        watch_total = int(data.get("watch_seconds_total", 0))
        avg_watch = round(watch_total / views, 2) if views > 0 else 0.0

        return {
            "clip_id": clip_id,
            "week": week,
            "views": views,
            "unique_viewers": viewers,
            "avg_watch_seconds": avg_watch,
            "completions": int(data.get("completions", 0)),
            "watch_seconds_total": watch_total,
        }
    except Exception as exc:
        logger.warning("[analytics] weekly stats failed: %s", exc)
        return {"clip_id": clip_id, "week": week, "views": 0, "unique_viewers": 0}


async def get_analytics_range(
    clip_id: str,
    start_date: str,
    end_date: str,
) -> List[Dict]:
    """Return daily stats for a date range (inclusive)."""
    results = []
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        current = start
        while current <= end:
            day_stats = await get_daily_stats(clip_id, current.isoformat())
            results.append(day_stats)
            current += timedelta(days=1)
    except Exception as exc:
        logger.warning("[analytics] range query failed: %s", exc)
    return results


async def get_available_periods(clip_id: str) -> Dict:
    """Return all dates and weeks that have analytics data."""
    try:
        r = await _redis()
        raw = await r.smembers(_ikey(clip_id))
        periods = [p.decode() if isinstance(p, bytes) else p for p in raw]
        dates = [p for p in periods if "-W" not in p]
        weeks = [p for p in periods if "-W" in p]
        return {"clip_id": clip_id, "dates": sorted(dates), "weeks": sorted(weeks)}
    except Exception as exc:
        logger.warning("[analytics] periods query failed: %s", exc)
        return {"clip_id": clip_id, "dates": [], "weeks": []}
