"""
Phase 7.5 — Auto-Update Data Pipeline
======================================
ARQ cron tasks for automated dataset refresh and model retraining:

  Daily  (03:00 UTC)  — fetch_trending_data()      YouTube Trending daily pull + cache update
  Weekly (Sun 02:30)  — retrain_lora_weekly()       LoRA viral-style fine-tune with fresh clips
  Monthly (1st 04:00) — retrain_scorer_monthly()    Full virality scorer retrain on accumulated data

These are registered as arq cron jobs in WorkerSettings (tasks.py) and
GpuWorkerSettings (gpu_tasks.py) respectively.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, Any

try:
    from ..database import AsyncSessionLocal
except Exception:
    AsyncSessionLocal = None  # type: ignore

try:
    from ..domains.feedback.lora_training_service import LoRATrainingService
except Exception:
    LoRATrainingService = None  # type: ignore

try:
    from ..dataset_integration import TikTokDatasetLoader, YouTubeTrendingLoader, ViralityScorerTrainer
except Exception:
    TikTokDatasetLoader = None  # type: ignore
    YouTubeTrendingLoader = None  # type: ignore
    ViralityScorerTrainer = None  # type: ignore

try:
    from ..config import get_config
except Exception:
    get_config = None  # type: ignore

logger = logging.getLogger(__name__)

DATASET_CACHE_DIR = Path(os.environ.get("VIRACLIP_DATASETS_DIR", "/app/datasets"))
LORA_OUTPUT_DIR   = Path(os.environ.get("LORA_OUTPUT_DIR",  "/app/models/lora"))
MODELS_DIR        = Path(os.environ.get("MODELS_DIR",        "/app/models"))


# ─────────────────────────────────────────────────────────────────────────────
# Daily cron: fetch trending data (CPU worker)
# ─────────────────────────────────────────────────────────────────────────────

async def fetch_trending_data(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Phase 7.5 — Daily cron (03:00 UTC).
    Fetches latest YouTube Trending snapshots and caches patterns in Redis
    so the virality scorer can reference fresh trend boosts immediately.
    """
    logger.info("[cron:daily] Starting daily trending-data fetch …")
    results: Dict[str, Any] = {"status": "ok", "fetched": {}}

    # ── 1. YouTube Trending ───────────────────────────────────────────────────
    try:
        from ..dataset_integration import YouTubeTrendingLoader
        loader = YouTubeTrendingLoader()
        patterns = loader.extract_trend_patterns()
        if patterns:
            results["fetched"]["youtube_trending"] = {
                "top_tags":          patterns.get("top_tags", [])[:10],
                "viral_duration_s":  patterns.get("viral_duration_range", []),
                "optimal_publish":   patterns.get("optimal_publish_hours", []),
            }
            # Cache in Redis for viral_trend_service real-time use
            try:
                from ..config import get_config
                import redis.asyncio as aioredis, json
                cfg = get_config()
                r = aioredis.Redis(
                    host=cfg.redis_host, port=cfg.redis_port,
                    password=cfg.redis_password, decode_responses=True,
                )
                await r.setex(
                    "viraclip:trending:youtube",
                    86400,  # 24 h TTL
                    json.dumps(patterns),
                )
                await r.close()
                logger.info("[cron:daily] YouTube trending patterns cached in Redis (TTL=24h)")
            except Exception as _re:
                logger.debug(f"[cron:daily] Redis cache skipped: {_re}")

            logger.info(
                f"[cron:daily] YouTube Trending: {len(patterns.get('top_tags', []))} tags fetched"
            )
    except Exception as exc:
        logger.warning(f"[cron:daily] YouTube Trending fetch failed: {exc}")
        results["fetched"]["youtube_trending"] = {"error": str(exc)}

    # ── 2. Viral Trend Service refresh ───────────────────────────────────────
    try:
        from ..domains.virality.viral_trend_service import ViralTrendService
        vts = ViralTrendService()
        await vts.refresh_all()
        results["fetched"]["viral_trends"] = "refreshed"
        logger.info("[cron:daily] ViralTrendService cache refreshed")
    except Exception as exc:
        logger.debug(f"[cron:daily] ViralTrendService refresh skipped: {exc}")

    logger.info(f"[cron:daily] Completed. fetched={list(results['fetched'].keys())}")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Weekly cron: LoRA retrain (GPU worker)
# ─────────────────────────────────────────────────────────────────────────────

async def retrain_lora_weekly(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Phase 7.5 — Weekly cron (Sunday 02:30 UTC, GPU worker).
    Re-trains the viral-style LoRA on new highly-rated clips collected
    since the last weekly run.
    """
    logger.info("[cron:weekly-lora] Starting weekly LoRA retrain …")

    gpu_available = ctx.get("gpu_available", False)
    if not gpu_available:
        logger.warning("[cron:weekly-lora] No GPU detected — skipping LoRA retrain")
        return {"status": "skipped", "reason": "no_gpu"}

    try:
        viral_clips: list = []
        try:
            async with AsyncSessionLocal() as session:
                from sqlalchemy import text
                rows = await session.execute(text("""
                    SELECT gc.file_path, gc.virality_score, gc.metadata
                    FROM generated_clips gc
                    WHERE gc.user_rating >= 4
                      AND gc.created_at >= NOW() - INTERVAL '7 days'
                    ORDER BY gc.virality_score DESC
                    LIMIT 200
                """))
                raw = rows.fetchall()
                viral_clips = [
                    dict(r._mapping) if hasattr(r, '_mapping') else (r if isinstance(r, dict) else dict(r))
                    for r in raw
                ]
        except Exception as _dbe:
            logger.warning(f"[cron:weekly-lora] DB query failed: {_dbe}")

        if len(viral_clips) < 10:
            logger.info(
                f"[cron:weekly-lora] Only {len(viral_clips)} rated clips this week "
                "— skipping (need ≥10)"
            )
            return {"status": "skipped", "reason": "insufficient_data", "count": len(viral_clips)}

        # Write captions dataset
        dataset_dir = DATASET_CACHE_DIR / "lora_weekly"
        dataset_dir.mkdir(parents=True, exist_ok=True)
        for i, clip in enumerate(viral_clips):
            meta = clip.get("metadata") or {}
            caption = (
                meta.get("seo_title")
                or meta.get("suggested_hashtags", ["viral", "trending"])[0]
                or "viral short clip"
            )
            (dataset_dir / f"clip_{i:04d}.txt").write_text(caption)

        # Train LoRA
        svc = LoRATrainingService()
        output_path = LORA_OUTPUT_DIR / "viral_style_weekly.safetensors"
        result = await svc.train(
            dataset_path=str(dataset_dir),
            base_model=os.environ.get("T2V_MODEL", "sd1.5"),
            style_name="viral_weekly",
            num_steps=int(os.environ.get("LORA_WEEKLY_STEPS", "500")),
            output_path=str(output_path),
        )
        logger.info(
            f"[cron:weekly-lora] LoRA retrain done — "
            f"loss={result.get('loss', '?'):.4f}, steps={result.get('steps')}"
        )
        return {"status": "ok", **result}

    except Exception as exc:
        logger.error(f"[cron:weekly-lora] LoRA retrain failed: {exc}")
        return {"status": "error", "error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# Monthly cron: full virality scorer retrain (CPU worker)
# ─────────────────────────────────────────────────────────────────────────────

async def retrain_scorer_monthly(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Phase 7.5 — Monthly cron (1st of month, 04:00 UTC, CPU worker).
    Full virality scorer retrain using accumulated TikTok + YouTube + user feedback data.
    """
    logger.info("[cron:monthly-scorer] Starting monthly full virality scorer retrain …")

    try:
        # Run the existing training script logic programmatically
        import pandas as pd

        dfs = []

        # TikTok dataset
        try:
            tiktok = TikTokDatasetLoader()
            df_tt = tiktok.load().prepare()
            if df_tt is not None and len(df_tt) > 0:
                dfs.append(df_tt)
                logger.info(f"[cron:monthly-scorer] TikTok dataset: {len(df_tt)} rows")
        except Exception as _tte:
            logger.warning(f"[cron:monthly-scorer] TikTok load failed: {_tte}")

        # YouTube Trending patterns
        try:
            yt = YouTubeTrendingLoader()
            df_yt = yt.to_dataframe()
            if df_yt is not None and len(df_yt) > 0:
                dfs.append(df_yt)
                logger.info(f"[cron:monthly-scorer] YouTube dataset: {len(df_yt)} rows")
        except Exception as _yte:
            logger.debug(f"[cron:monthly-scorer] YouTube load failed: {_yte}")

        if not dfs:
            logger.warning("[cron:monthly-scorer] No dataset available — aborting")
            return {"status": "skipped", "reason": "no_datasets"}

        combined = pd.concat(dfs, ignore_index=True)

        # Re-train XGBoost virality scorer
        trainer = ViralityScorerTrainer()
        model, metrics = trainer.train(combined)

        # Save model
        model_path = MODELS_DIR / "viral_scorer.pkl"
        trainer.save(model_path)

        # Hot-reload signal via Redis
        try:
            import redis.asyncio as aioredis
            cfg = get_config()
            r = aioredis.Redis(
                host=cfg.redis_host, port=cfg.redis_port,
                password=cfg.redis_password, decode_responses=True,
            )
            await r.publish("viraclip:model_reload", "viral_scorer")
            await r.close()
        except Exception:
            pass  # hot-reload is best-effort

        logger.info(
            f"[cron:monthly-scorer] Scorer retrained — "
            f"r2={metrics.get('r2', '?'):.3f}, mae={metrics.get('mae', '?'):.2f}, "
            f"rows={len(combined)}"
        )
        return {"status": "ok", "metrics": metrics, "rows": len(combined)}

    except Exception as exc:
        logger.error(f"[cron:monthly-scorer] Retrain failed: {exc}")
        return {"status": "error", "error": str(exc)}
