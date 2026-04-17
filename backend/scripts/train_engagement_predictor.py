"""
train_engagement_predictor.py — Phase 8.3
==========================================
CLI to train the LSTM/CNN engagement predictor using feedback data.

Training data sources:
  1. Feedback DB — clips with actual_engagement_score and retention_curve
  2. Synthetic — generated from heuristic + noise (bootstrap)

Usage (inside Docker container):
    python /app/scripts/train_engagement_predictor.py
    python /app/scripts/train_engagement_predictor.py --source synthetic --epochs 100
    python /app/scripts/train_engagement_predictor.py --status
"""

import argparse
import asyncio
import json
import logging
import os
import random
import sys
from pathlib import Path
from typing import List, Dict, Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

MODEL_PATH = Path(os.getenv("ENGAGEMENT_MODEL", "/app/models/engagement_predictor.pkl"))


# ─────────────────────────────────────────────────────────────────────────────
#  Data sources
# ─────────────────────────────────────────────────────────────────────────────

async def load_feedback_samples() -> List[Dict[str, Any]]:
    """Load samples from feedback DB — clips with words + retention curves."""
    samples = []
    try:
        import asyncpg
        db_url = os.getenv("DATABASE_URL", "").replace("postgres://", "postgresql://")
        if not db_url:
            logger.warning("DATABASE_URL not set — skipping DB samples")
            return []

        conn = await asyncpg.connect(db_url)
        try:
            rows = await conn.fetch(
                """
                SELECT
                    cf.transcript,
                    cf.duration,
                    cf.audio_features,
                    cf.actual_engagement_score,
                    cf.retention_curve
                FROM clip_feedback cf
                WHERE cf.transcript IS NOT NULL
                  AND LENGTH(cf.transcript) > 20
                  AND cf.actual_engagement_score IS NOT NULL
                ORDER BY cf.created_at DESC
                LIMIT 5000
                """
            )
        finally:
            await conn.close()

        for row in rows:
            try:
                words = [{"text": w, "start": i * 500, "end": (i + 1) * 500, "confidence": 0.9}
                         for i, w in enumerate(str(row["transcript"]).split())]
                af = json.loads(row["audio_features"] or "{}")
                curve_raw = row["retention_curve"]
                if curve_raw:
                    curve = json.loads(curve_raw) if isinstance(curve_raw, str) else list(curve_raw)
                else:
                    # Build synthetic curve from engagement score
                    score = float(row["actual_engagement_score"])
                    T = max(1, int(float(row["duration"] or 30)))
                    curve = [max(5.0, score - i * (score / T * 0.8)) for i in range(T)]

                samples.append({
                    "words": words,
                    "audio_features": af,
                    "duration": float(row["duration"] or 30.0),
                    "retention_curve": curve,
                })
            except Exception as e:
                logger.debug(f"Bad DB sample: {e}")

        logger.info(f"Loaded {len(samples)} samples from feedback DB")
    except ImportError:
        logger.warning("asyncpg not installed — skipping DB")
    except Exception as e:
        logger.warning(f"DB load failed: {e}")
    return samples


def generate_synthetic_samples(n: int = 300) -> List[Dict[str, Any]]:
    """Generate synthetic training samples with realistic engagement curves."""
    rng = random.Random(42)
    samples = []

    # High-engagement template: fast speech, viral keywords, low filler
    for _ in range(n // 2):
        duration = rng.uniform(15, 45)
        T = int(duration)
        wpm = rng.uniform(140, 200)
        words = []
        t = 0.0
        word_pool = [
            "shocking", "secret", "never", "amazing", "revealed",
            "you", "this", "watch", "listen", "see", "wait",
            "top", "best", "why", "how", "what",
        ]
        while t < duration:
            w = rng.choice(word_pool)
            dur = 60.0 / wpm
            words.append({
                "text": w, "start": int(t * 1000),
                "end": int((t + dur) * 1000), "confidence": rng.uniform(0.8, 1.0)
            })
            t += dur + rng.uniform(0, 0.1)

        # Curve: starts ~85%, gradual decay, energy boosts
        curve = []
        val = rng.uniform(80, 95)
        for i in range(T):
            val -= rng.uniform(0.3, 1.2)
            if rng.random() < 0.15:
                val += rng.uniform(2, 6)
            curve.append(max(5.0, min(100.0, val)))

        samples.append({
            "words": words,
            "audio_features": {
                "tempo_bpm": rng.uniform(120, 160),
                "rms_energy": rng.uniform(0.06, 0.15),
                "energy_peaks_timestamps": [rng.uniform(0, duration) for _ in range(rng.randint(2, 6))],
            },
            "duration": duration,
            "retention_curve": curve,
        })

    # Low-engagement template: slow speech, filler words, silences
    for _ in range(n // 2):
        duration = rng.uniform(30, 90)
        T = int(duration)
        wpm = rng.uniform(80, 120)
        words = []
        t = 0.0
        filler_pool = ["um", "uh", "like", "you know", "basically", "so", "and"]
        while t < duration:
            w = rng.choice(filler_pool)
            dur = 60.0 / wpm
            words.append({
                "text": w, "start": int(t * 1000),
                "end": int((t + dur) * 1000), "confidence": rng.uniform(0.5, 0.7)
            })
            t += dur + rng.uniform(0, 0.8)

        curve = []
        val = rng.uniform(50, 65)
        for i in range(T):
            val -= rng.uniform(0.8, 2.0)
            curve.append(max(5.0, min(100.0, val)))

        samples.append({
            "words": words,
            "audio_features": {
                "tempo_bpm": rng.uniform(80, 110),
                "rms_energy": rng.uniform(0.02, 0.06),
                "energy_peaks_timestamps": [],
            },
            "duration": duration,
            "retention_curve": curve,
        })

    rng.shuffle(samples)
    return samples


# ─────────────────────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────────────────────

async def train(source: str = "both", epochs: int = 50, synthetic_n: int = 300) -> dict:
    from services.engagement_prediction_service import EngagementPredictionService

    samples = []
    if source in ("feedback", "both"):
        samples.extend(await load_feedback_samples())
    if source in ("synthetic", "both") or len(samples) < 10:
        n_synth = max(synthetic_n, 10 - len(samples))
        samples.extend(generate_synthetic_samples(n=n_synth))

    logger.info(f"Total training samples: {len(samples)}")
    svc = EngagementPredictionService(model_path=MODEL_PATH)
    return svc.train(samples, epochs=epochs)


def print_status():
    if not MODEL_PATH.exists():
        print(f"\n❌ No trained model at {MODEL_PATH}")
        return
    import pickle
    with open(MODEL_PATH, "rb") as f:
        data = pickle.load(f)
    size_kb = MODEL_PATH.stat().st_size // 1024
    print(f"\n✅ Engagement Predictor")
    print(f"   Path:  {MODEL_PATH}")
    print(f"   Size:  {size_kb} KB")
    print(f"   Model: {type(data.get('model', '')).__name__}")


def main():
    parser = argparse.ArgumentParser(description="Train ViraClip engagement predictor (Phase 8.3)")
    parser.add_argument("--source", choices=["feedback", "synthetic", "both"], default="both")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--synthetic-n", type=int, default=300)
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    if args.status:
        print_status()
        return

    result = asyncio.run(train(args.source, args.epochs, args.synthetic_n))

    if result.get("status") == "trained":
        print(f"\n✅ Training complete!")
        print(f"   Samples:    {result['n_samples']}")
        print(f"   Val loss:   {result.get('best_val_loss', 'N/A'):.4f}")
        print(f"   Epochs:     {result['epochs']}")
        print(f"   Model:      {MODEL_PATH}")
    else:
        print(f"\n⚠ {result.get('status')}: {result.get('reason', '')}")


if __name__ == "__main__":
    main()
