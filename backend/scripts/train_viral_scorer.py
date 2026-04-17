"""
train_viral_scorer.py — Phase 2.2
===================================
CLI to train the ViralScorerService MLP model using:
  1. Feedback loop data from the DB (clips with real engagement scores)
  2. (Optional) TikTok-Videos HuggingFace dataset for bootstrap training

Usage (inside Docker container):
    python /app/scripts/train_viral_scorer.py
    python /app/scripts/train_viral_scorer.py --source feedback --min-samples 50
    python /app/scripts/train_viral_scorer.py --source huggingface --dataset-limit 5000
    python /app/scripts/train_viral_scorer.py --source both --min-samples 100
    python /app/scripts/train_viral_scorer.py --status

Env vars used:
    DATABASE_URL       — Postgres connection string
    VIRAL_SCORER_MODEL — Override model save path (default: /app/models/viral_scorer.pkl)
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import List, Dict, Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

MODEL_PATH = Path(os.getenv("VIRAL_SCORER_MODEL", "/app/models/viral_scorer.pkl"))


# ─────────────────────────────────────────────────────────────────────────────
#  Data sources
# ─────────────────────────────────────────────────────────────────────────────

async def load_feedback_samples(min_score_variance: float = 5.0) -> List[Dict[str, Any]]:
    """Load training samples from the feedback loop DB (ClipFeedback table)."""
    samples = []
    try:
        import asyncpg

        db_url = os.getenv("DATABASE_URL", "")
        if not db_url:
            logger.warning("DATABASE_URL not set — skipping feedback DB samples")
            return []

        # asyncpg uses postgresql:// not postgres://
        db_url = db_url.replace("postgres://", "postgresql://")

        conn = await asyncpg.connect(db_url)
        try:
            rows = await conn.fetch(
                """
                SELECT
                    cf.transcript,
                    cf.duration,
                    cf.virality_score,
                    cf.actual_engagement_score,
                    cf.audio_features
                FROM clip_feedback cf
                WHERE cf.virality_score IS NOT NULL
                  AND cf.transcript IS NOT NULL
                  AND LENGTH(cf.transcript) > 20
                ORDER BY cf.created_at DESC
                LIMIT 10000
                """
            )
        finally:
            await conn.close()

        import json as _json

        for row in rows:
            # Use actual engagement score if available, otherwise virality_score
            target = row["actual_engagement_score"] or row["virality_score"]
            if target is None:
                continue
            af = {}
            if row["audio_features"]:
                try:
                    af = _json.loads(row["audio_features"])
                except Exception:
                    pass
            samples.append({
                "transcript": row["transcript"] or "",
                "duration": float(row["duration"] or 15.0),
                "audio_features": af,
                "virality_score": float(target),
            })

        logger.info(f"Loaded {len(samples)} samples from feedback DB")

    except ImportError:
        logger.warning("asyncpg not installed — skipping DB samples")
    except Exception as e:
        logger.warning(f"Failed to load feedback samples: {e}")

    return samples


def load_huggingface_samples(limit: int = 5000) -> List[Dict[str, Any]]:
    """
    Load synthetic training data from TikTok-Videos HuggingFace dataset.
    Uses views/likes as weak supervision for virality score.
    """
    samples = []
    try:
        from datasets import load_dataset

        logger.info(f"Loading HuggingFace dataset (limit={limit})...")
        # Use the subset we can load in streaming mode to avoid full 500GB download
        ds = load_dataset(
            "RicoEric/tiktok-videos",
            split="train",
            streaming=True,
            trust_remote_code=True,
        )

        for i, row in enumerate(ds):
            if i >= limit:
                break
            try:
                # Derive virality score from engagement ratio
                views = int(row.get("play_count", 0) or 0)
                likes = int(row.get("digg_count", 0) or 0)
                shares = int(row.get("share_count", 0) or 0)
                comments = int(row.get("comment_count", 0) or 0)

                if views < 100:
                    continue

                engagement_rate = (likes + shares * 3 + comments * 2) / max(views, 1)
                virality = min(100, int(engagement_rate * 500))  # scale to 0-100

                desc = str(row.get("desc", "") or "")
                if len(desc) < 10:
                    continue

                duration = float(row.get("video_duration", 15) or 15)
                samples.append({
                    "transcript": desc,
                    "duration": duration,
                    "audio_features": {},
                    "virality_score": virality,
                })

            except Exception:
                continue

        logger.info(f"Loaded {len(samples)} samples from HuggingFace dataset")

    except ImportError:
        logger.warning("datasets package not installed — skipping HuggingFace samples")
    except Exception as e:
        logger.warning(f"Failed to load HuggingFace samples: {e}")

    return samples


def generate_synthetic_samples(n: int = 200) -> List[Dict[str, Any]]:
    """
    Generate minimal synthetic samples for bootstrap training when no real data exists.
    Based on known viral content patterns.
    """
    import random
    random.seed(42)

    high_viral_texts = [
        "This secret nobody tells you will change your life forever",
        "The shocking truth about why you're always tired revealed",
        "3 mistakes everyone makes that kill their productivity",
        "Wait until you see what happens at the end - you won't believe it",
        "Why successful people never do this one thing in the morning",
        "The viral hack that saved me 2 hours every single day",
        "I tested this crazy trick for 30 days and here are the results",
        "Nobody is talking about this but you need to hear it right now",
    ]
    low_viral_texts = [
        "Hello everyone welcome to my channel today we will be talking about things",
        "So basically what I wanted to say is that in my opinion things are kind of ok",
        "Let me just explain this very long process step by step slowly",
        "Today I want to discuss some general concepts in a somewhat boring way",
        "This is just a regular video about nothing particularly interesting",
    ]

    samples = []
    for text in high_viral_texts:
        score = random.randint(70, 95)
        samples.append({
            "transcript": text,
            "duration": random.uniform(15, 30),
            "audio_features": {
                "tempo_bpm": random.uniform(120, 160),
                "speech_rate_words_per_min": random.uniform(150, 200),
            },
            "virality_score": score,
        })

    for text in low_viral_texts:
        score = random.randint(20, 45)
        samples.append({
            "transcript": text,
            "duration": random.uniform(30, 90),
            "audio_features": {
                "tempo_bpm": random.uniform(80, 110),
                "speech_rate_words_per_min": random.uniform(80, 120),
            },
            "virality_score": score,
        })

    # Add more random samples
    for _ in range(n - len(samples)):
        score = random.randint(0, 100)
        samples.append({
            "transcript": f"Sample transcript with some random content score {score}",
            "duration": random.uniform(10, 90),
            "audio_features": {
                "tempo_bpm": random.uniform(80, 180),
            },
            "virality_score": score,
        })

    return samples


# ─────────────────────────────────────────────────────────────────────────────
#  Main training logic
# ─────────────────────────────────────────────────────────────────────────────

async def train(
    source: str = "both",
    min_samples: int = 20,
    dataset_limit: int = 5000,
    use_synthetic_fallback: bool = True,
) -> dict:
    """Run training pipeline and return summary."""
    from services.viral_scorer_service import ViralScorerService

    all_samples = []

    if source in ("feedback", "both"):
        db_samples = await load_feedback_samples()
        all_samples.extend(db_samples)

    if source in ("huggingface", "both"):
        hf_samples = load_huggingface_samples(limit=dataset_limit)
        all_samples.extend(hf_samples)

    if len(all_samples) < min_samples and use_synthetic_fallback:
        need = max(200, min_samples - len(all_samples))
        logger.info(
            f"Not enough real samples ({len(all_samples)}) — "
            f"adding {need} synthetic samples for bootstrap"
        )
        all_samples.extend(generate_synthetic_samples(n=need))

    if not all_samples:
        logger.error("No training samples available. Cannot train.")
        return {"status": "failed", "reason": "no samples"}

    logger.info(f"\nTotal training samples: {len(all_samples)}")
    logger.info(f"Score range: [{min(s['virality_score'] for s in all_samples):.0f}, "
                f"{max(s['virality_score'] for s in all_samples):.0f}]")

    scorer = ViralScorerService(model_path=MODEL_PATH)
    result = scorer.train(all_samples)
    return result


def print_status():
    """Show current model status."""
    if not MODEL_PATH.exists():
        print(f"\n❌ No trained model found at {MODEL_PATH}")
        print("   Run: python /app/scripts/train_viral_scorer.py")
        return

    import pickle
    with open(MODEL_PATH, "rb") as f:
        data = pickle.load(f)

    model = data.get("model")
    n = data.get("n_training_samples", "?")
    size_kb = MODEL_PATH.stat().st_size // 1024

    print(f"\n✅ Viral Scorer Model")
    print(f"   Path:            {MODEL_PATH}")
    print(f"   Size:            {size_kb} KB")
    print(f"   Training samples: {n}")
    if model:
        try:
            mlp = model.named_steps.get("mlp")
            if mlp:
                print(f"   Architecture:    MLP {mlp.hidden_layer_sizes}")
                print(f"   Best val loss:   {mlp.best_loss_:.4f}" if hasattr(mlp, "best_loss_") else "")
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(
        description="Train ViraClip MLP virality scorer (Phase 2.2)"
    )
    parser.add_argument(
        "--source",
        choices=["feedback", "huggingface", "both", "synthetic"],
        default="both",
        help="Training data source (default: both)",
    )
    parser.add_argument("--min-samples", type=int, default=20,
                        help="Minimum samples required before training")
    parser.add_argument("--dataset-limit", type=int, default=5000,
                        help="Max samples from HuggingFace dataset")
    parser.add_argument("--no-synthetic", action="store_true",
                        help="Disable synthetic sample fallback")
    parser.add_argument("--status", action="store_true",
                        help="Show current model status and exit")
    args = parser.parse_args()

    if args.status:
        print_status()
        return

    src = "both" if args.source == "synthetic" else args.source
    synthetic = not args.no_synthetic or args.source == "synthetic"

    result = asyncio.run(
        train(
            source=src,
            min_samples=args.min_samples,
            dataset_limit=args.dataset_limit,
            use_synthetic_fallback=synthetic,
        )
    )

    if result.get("status") == "trained":
        print(f"\n✅ Training complete!")
        print(f"   Samples:  {result['n_samples']} train / {result['n_val']} val")
        print(f"   MAE:      {result['mae']:.2f} points")
        print(f"   R²:       {result['r2']:.3f}")
        print(f"   Model:    {MODEL_PATH}")
    else:
        print(f"\n⚠ {result.get('status')}: {result.get('reason', '')}")


if __name__ == "__main__":
    main()
