"""
train_all_models.py — Batch Model Training
===========================================
Entrena todos los modelos ML de ViraClip en un solo comando.
Útil para setup inicial o retraining periódico.

Usage (PowerShell):
    # Dentro del container
    docker-compose exec backend python /app/scripts/train_all_models.py

    # Solo sintético (bootstrap sin DB)
    docker-compose exec backend python /app/scripts/train_all_models.py --synthetic-only

    # Especificar epochs
    docker-compose exec backend python /app/scripts/train_all_models.py --epochs 100

    # Exportar a ONNX después de entrenar
    docker-compose exec backend python /app/scripts/train_all_models.py --export-onnx

Output:
    - /app/models/viral_scorer.pkl
    - /app/models/engagement_predictor.pkl
    - /app/models/onnx/viral_scorer.onnx (si --export-onnx)
    - /app/models/onnx/engagement_predictor.onnx (si --export-onnx)
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


async def train_viral_scorer(source: str, epochs: int) -> dict:
    """Train viral scorer MLP."""
    logger.info("\n" + "="*60)
    logger.info("🎯 Training Viral Scorer (Phase 2.2)")
    logger.info("="*60)
    
    try:
        from services.viral_scorer_service import ViralScorerService
        from pathlib import Path
        import os
        
        model_path = Path(os.getenv("VIRAL_SCORER_MODEL", "/app/models/viral_scorer.pkl"))
        svc = ViralScorerService(model_path=model_path)
        
        # Cargar samples
        samples = []
        
        if source in ("feedback", "both"):
            logger.info("Loading samples from feedback DB...")
            try:
                import asyncpg
                db_url = os.getenv("DATABASE_URL", "").replace("postgres://", "postgresql://")
                if db_url:
                    conn = await asyncpg.connect(db_url)
                    try:
                        rows = await conn.fetch(
                            """
                            SELECT transcript, duration, virality_score
                            FROM clip_feedback
                            WHERE transcript IS NOT NULL
                              AND LENGTH(transcript) > 20
                              AND virality_score IS NOT NULL
                            ORDER BY created_at DESC
                            LIMIT 2000
                            """
                        )
                        for row in rows:
                            samples.append({
                                "transcript": str(row["transcript"]),
                                "duration": float(row["duration"] or 15.0),
                                "virality_score": float(row["virality_score"]),
                            })
                    finally:
                        await conn.close()
                    logger.info(f"  ✓ Loaded {len(samples)} samples from DB")
            except Exception as e:
                logger.warning(f"  ⚠ DB load failed: {e}")
        
        if source in ("synthetic", "both") or len(samples) < 20:
            logger.info("Generating synthetic samples...")
            n_synth = max(200, 50 - len(samples))
            import random
            rng = random.Random(42)
            viral_keywords = ["shocking", "secret", "revealed", "never", "amazing", "you won't believe"]
            boring_keywords = ["um", "uh", "so", "like", "basically"]
            
            for i in range(n_synth):
                if i % 2 == 0:
                    # High virality
                    transcript = " ".join(rng.choices(viral_keywords, k=rng.randint(15, 30)))
                    score = rng.uniform(75, 95)
                else:
                    # Low virality
                    transcript = " ".join(rng.choices(boring_keywords, k=rng.randint(10, 20)))
                    score = rng.uniform(20, 45)
                
                samples.append({
                    "transcript": transcript,
                    "duration": rng.uniform(10, 45),
                    "virality_score": score,
                })
            logger.info(f"  ✓ Generated {n_synth} synthetic samples")
        
        logger.info(f"\nTotal samples: {len(samples)}")
        result = svc.train(samples)
        
        if result["status"] == "trained":
            logger.info(f"✅ Viral scorer trained successfully")
            logger.info(f"   Samples:  {result['n_samples']}")
            r2 = result.get('r2', result.get('r2_score', 'N/A'))
            r2_str = f"{r2:.3f}" if isinstance(r2, (int, float)) else str(r2)
            logger.info(f"   R² score: {r2_str}")
            logger.info(f"   Model:    {model_path}")
            return {"model": "viral_scorer", **result, "status": "success"}
        else:
            logger.error(f"❌ Training failed: {result.get('reason', 'unknown')}")
            return {"status": "failed", "model": "viral_scorer", **result}
            
    except Exception as e:
        logger.error(f"❌ Exception during viral scorer training: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "model": "viral_scorer", "error": str(e)}


async def train_engagement_predictor(source: str, epochs: int) -> dict:
    """Train engagement LSTM/CNN predictor."""
    logger.info("\n" + "="*60)
    logger.info("📉 Training Engagement Predictor (Phase 8.3)")
    logger.info("="*60)
    
    try:
        from services.engagement_prediction_service import EngagementPredictionService
        from pathlib import Path
        import os
        
        model_path = Path(os.getenv("ENGAGEMENT_MODEL", "/app/models/engagement_predictor.pkl"))
        svc = EngagementPredictionService(model_path=model_path)
        
        # Cargar samples
        samples = []
        
        if source in ("feedback", "both"):
            logger.info("Loading samples from feedback DB...")
            try:
                import asyncpg
                db_url = os.getenv("DATABASE_URL", "").replace("postgres://", "postgresql://")
                if db_url:
                    conn = await asyncpg.connect(db_url)
                    try:
                        rows = await conn.fetch(
                            """
                            SELECT
                                transcript,
                                duration,
                                audio_features,
                                retention_curve
                            FROM clip_feedback
                            WHERE transcript IS NOT NULL
                              AND LENGTH(transcript) > 20
                              AND retention_curve IS NOT NULL
                            ORDER BY created_at DESC
                            LIMIT 1000
                            """
                        )
                        for row in rows:
                            import json
                            words = [{"text": w, "start": i*500, "end": (i+1)*500, "confidence": 0.9}
                                     for i, w in enumerate(str(row["transcript"]).split())]
                            af = json.loads(row["audio_features"] or "{}")
                            curve_raw = row["retention_curve"]
                            curve = json.loads(curve_raw) if isinstance(curve_raw, str) else list(curve_raw)
                            
                            samples.append({
                                "words": words,
                                "audio_features": af,
                                "duration": float(row["duration"] or 30.0),
                                "retention_curve": curve,
                            })
                    finally:
                        await conn.close()
                    logger.info(f"  ✓ Loaded {len(samples)} samples from DB")
            except Exception as e:
                logger.warning(f"  ⚠ DB load failed: {e}")
        
        if source in ("synthetic", "both") or len(samples) < 10:
            logger.info("Generating synthetic samples...")
            # Usar generador sintético del training script
            sys.path.insert(0, str(Path(__file__).parent))
            from train_engagement_predictor import generate_synthetic_samples
            n_synth = max(100, 20 - len(samples))
            synth_samples = generate_synthetic_samples(n=n_synth)
            samples.extend(synth_samples)
            logger.info(f"  ✓ Generated {len(synth_samples)} synthetic samples")
        
        logger.info(f"\nTotal samples: {len(samples)}")
        result = svc.train(samples, epochs=epochs)
        
        if result["status"] == "trained":
            logger.info(f"✅ Engagement predictor trained successfully")
            logger.info(f"   Samples:      {result['n_samples']}")
            logger.info(f"   Val loss:     {result.get('best_val_loss', 'N/A'):.4f}")
            logger.info(f"   Epochs:       {result['epochs']}")
            logger.info(f"   Model:        {model_path}")
            return {"model": "engagement_predictor", **result, "status": "success"}
        else:
            logger.error(f"❌ Training failed: {result.get('reason', 'unknown')}")
            return {"status": "failed", "model": "engagement_predictor", **result}
            
    except Exception as e:
        logger.error(f"❌ Exception during engagement training: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "model": "engagement_predictor", "error": str(e)}


def export_to_onnx() -> dict:
    """Export trained models to ONNX."""
    logger.info("\n" + "="*60)
    logger.info("📦 Exporting Models to ONNX (Phase 8.4)")
    logger.info("="*60)
    
    results = {"viral_scorer": False, "engagement_predictor": False}
    
    try:
        from services.onnx_inference_service import (
            export_viral_scorer_to_onnx,
            export_engagement_predictor_to_onnx,
        )
        
        # Viral scorer
        logger.info("\n1. Exporting viral_scorer.onnx...")
        ok1 = export_viral_scorer_to_onnx()
        results["viral_scorer"] = ok1
        if ok1:
            logger.info("   ✅ viral_scorer.onnx exported")
        else:
            logger.warning("   ⚠ Export skipped (model not trained or skl2onnx missing)")
        
        # Engagement predictor
        logger.info("\n2. Exporting engagement_predictor.onnx...")
        ok2 = export_engagement_predictor_to_onnx()
        results["engagement_predictor"] = ok2
        if ok2:
            logger.info("   ✅ engagement_predictor.onnx exported")
        else:
            logger.warning("   ⚠ Export skipped (model not trained or PyTorch missing)")
        
        return results
        
    except Exception as e:
        logger.error(f"❌ ONNX export failed: {e}")
        import traceback
        traceback.print_exc()
        return results


async def main():
    parser = argparse.ArgumentParser(description="Train all ViraClip ML models")
    parser.add_argument(
        "--source",
        choices=["feedback", "synthetic", "both"],
        default="both",
        help="Training data source (default: both)",
    )
    parser.add_argument(
        "--synthetic-only",
        action="store_true",
        help="Use only synthetic data (no DB)",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=50,
        help="Training epochs (default: 50)",
    )
    parser.add_argument(
        "--export-onnx",
        action="store_true",
        help="Export to ONNX after training",
    )
    parser.add_argument(
        "--skip-viral",
        action="store_true",
        help="Skip viral scorer training",
    )
    parser.add_argument(
        "--skip-engagement",
        action="store_true",
        help="Skip engagement predictor training",
    )
    args = parser.parse_args()
    
    source = "synthetic" if args.synthetic_only else args.source
    
    print("\n" + "="*60)
    print("🤖 ViraClip Model Training Pipeline")
    print("="*60)
    print(f"Source:       {source}")
    print(f"Epochs:       {args.epochs}")
    print(f"Export ONNX:  {args.export_onnx}")
    print("="*60 + "\n")
    
    results = []
    
    # Train viral scorer
    if not args.skip_viral:
        result = await train_viral_scorer(source, args.epochs)
        results.append(result)
    
    # Train engagement predictor
    if not args.skip_engagement:
        result = await train_engagement_predictor(source, args.epochs)
        results.append(result)
    
    # Export to ONNX
    onnx_results = None
    if args.export_onnx:
        onnx_results = export_to_onnx()
    
    # Summary
    print("\n" + "="*60)
    print("📊 Training Summary")
    print("="*60)
    
    success_count = sum(1 for r in results if r["status"] == "success")
    print(f"\nModels trained: {success_count}/{len(results)}")
    
    for r in results:
        status_icon = "✅" if r["status"] == "success" else "❌"
        print(f"  {status_icon} {r['model']}: {r['status']}")
    
    if onnx_results:
        print(f"\nONNX exports:")
        for model, ok in onnx_results.items():
            icon = "✅" if ok else "⚠"
            print(f"  {icon} {model}.onnx")
    
    print("="*60 + "\n")
    
    # Exit code
    if success_count == len(results):
        print("🚀 All models trained successfully!\n")
        return 0
    else:
        print("⚠ Some models failed to train. Check logs above.\n")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
