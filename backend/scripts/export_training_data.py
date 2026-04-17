"""
B.6: Export rated clips as training data.

Usage:
    python -m scripts.export_training_data [--min-rating 4] [--output ratings.json]

Outputs a JSON file with all clips that have a user_rating, sorted by rating desc.
Each record includes: id, task_id, text, virality_score, hook_type, duration,
reasoning, user_rating, and the clip file path.
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text as sa_text


async def fetch_rated_clips(db_url: str, min_rating: int) -> list[dict]:
    engine = create_async_engine(db_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        result = await session.execute(
            sa_text(
                """
                SELECT id, task_id, filename, file_path, text,
                       virality_score, hook_type, duration, reasoning,
                       hook_score, engagement_score, value_score, shareability_score,
                       user_rating, created_at
                FROM generated_clips
                WHERE user_rating IS NOT NULL
                  AND user_rating >= :min_rating
                ORDER BY user_rating DESC, virality_score DESC
                """
            ),
            {"min_rating": min_rating},
        )
        rows = result.fetchall()

    await engine.dispose()
    return [dict(r._mapping) for r in rows]


def serialize(obj):
    """JSON serializer for objects not serializable by default."""
    import datetime
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def main():
    parser = argparse.ArgumentParser(description="Export rated clips as training data")
    parser.add_argument(
        "--min-rating", type=int, default=1, metavar="N",
        help="Minimum user_rating to include (1-5, default: 1)"
    )
    parser.add_argument(
        "--output", type=str, default="rated_clips.json", metavar="FILE",
        help="Output JSON file path (default: rated_clips.json)"
    )
    args = parser.parse_args()

    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://viraclip:viraclip_password@localhost:5432/viraclip",
    )

    print(f"Connecting to database…")
    clips = asyncio.run(fetch_rated_clips(db_url, args.min_rating))

    if not clips:
        print("No rated clips found.")
        return

    out_path = Path(args.output)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(clips, f, indent=2, default=serialize, ensure_ascii=False)

    print(f"Exported {len(clips)} clip(s) to {out_path.resolve()}")
    stars = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for c in clips:
        stars[c["user_rating"]] = stars.get(c["user_rating"], 0) + 1
    for rating, count in sorted(stars.items(), reverse=True):
        if count:
            print(f"  {'★' * rating}{'☆' * (5 - rating)}  {count} clip(s)")


if __name__ == "__main__":
    main()
