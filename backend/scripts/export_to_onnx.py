"""
export_to_onnx.py — Phase 8.4
================================
CLI to export ViraClip ML models to ONNX format for mobile/edge deployment.

Exports:
  1. viral_scorer MLP (sklearn) → viral_scorer.onnx   (~2MB)
  2. engagement_predictor (PyTorch LSTM/CNN) → engagement_predictor.onnx (~5MB)

Usage (inside Docker container):
    python /app/scripts/export_to_onnx.py
    python /app/scripts/export_to_onnx.py --model viral_scorer
    python /app/scripts/export_to_onnx.py --model engagement
    python /app/scripts/export_to_onnx.py --model all --verify
    python /app/scripts/export_to_onnx.py --status

Requirements:
    pip install skl2onnx onnxruntime         (for viral_scorer)
    pip install torch onnxruntime            (for engagement_predictor)

Deployment:
  - Copy *.onnx to mobile app assets
  - iOS:   Use CoreML converter (coremltools) on the .onnx files
  - Android: Use ONNX Runtime Android AAR
  - Edge:  Use onnxruntime (CPU only, ~5MB) on any Python environment
"""

import argparse
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

ONNX_DIR = Path(os.getenv("ONNX_MODEL_DIR", "/app/models/onnx"))


def export_viral_scorer(verify: bool = False) -> bool:
    from services.onnx_inference_service import export_viral_scorer_to_onnx, VIRAL_SCORER_ONNX

    print("\n📦 Exporting viral_scorer.onnx...")
    ok = export_viral_scorer_to_onnx(onnx_output_path=VIRAL_SCORER_ONNX)
    if not ok:
        print("  ❌ Export failed (model not trained yet? Run train_viral_scorer.py first)")
        return False

    print(f"  ✅ Exported → {VIRAL_SCORER_ONNX} ({VIRAL_SCORER_ONNX.stat().st_size // 1024}KB)")

    if verify:
        print("  🔍 Verifying ONNX Runtime inference...")
        try:
            import onnxruntime as ort
            import numpy as np
            sess = ort.InferenceSession(str(VIRAL_SCORER_ONNX), providers=["CPUExecutionProvider"])
            dummy = np.zeros((1, 26), dtype=np.float32)
            out = sess.run(None, {"float_input": dummy})
            score = float(out[0][0])
            print(f"  ✅ Inference OK — dummy score: {score:.2f}")
        except Exception as e:
            print(f"  ⚠ Verification failed: {e}")

    return True


def export_engagement(verify: bool = False, seq_len: int = 60) -> bool:
    from services.onnx_inference_service import export_engagement_predictor_to_onnx, ENGAGEMENT_ONNX

    print("\n📦 Exporting engagement_predictor.onnx...")
    ok = export_engagement_predictor_to_onnx(
        onnx_output_path=ENGAGEMENT_ONNX,
        sequence_length=seq_len,
    )
    if not ok:
        print("  ❌ Export failed (model not trained? Run train_engagement_predictor.py first)")
        return False

    print(f"  ✅ Exported → {ENGAGEMENT_ONNX} ({ENGAGEMENT_ONNX.stat().st_size // 1024}KB)")

    if verify:
        print("  🔍 Verifying ONNX Runtime inference...")
        try:
            import onnxruntime as ort
            import numpy as np
            sess = ort.InferenceSession(str(ENGAGEMENT_ONNX), providers=["CPUExecutionProvider"])
            dummy = np.zeros((1, seq_len, 10), dtype=np.float32)
            out = sess.run(None, {"features": dummy})
            print(f"  ✅ Inference OK — output shape: {out[0].shape}")
        except Exception as e:
            print(f"  ⚠ Verification failed: {e}")

    return True


def print_status():
    print("\n📊 ONNX Model Status")
    print(f"   Directory: {ONNX_DIR}")

    models = [
        ("viral_scorer.onnx",          ONNX_DIR / "viral_scorer.onnx"),
        ("engagement_predictor.onnx",  ONNX_DIR / "engagement_predictor.onnx"),
    ]
    for name, path in models:
        if path.exists():
            size_kb = path.stat().st_size // 1024
            print(f"   ✅ {name}: {size_kb}KB")
        else:
            print(f"   ❌ {name}: not found")

    try:
        import onnxruntime as ort
        print(f"\n   ONNX Runtime: v{ort.__version__}")
        print(f"   Providers: {ort.get_available_providers()}")
    except ImportError:
        print("\n   ⚠ onnxruntime not installed: pip install onnxruntime")


def main():
    parser = argparse.ArgumentParser(
        description="Export ViraClip models to ONNX (Phase 8.4)"
    )
    parser.add_argument(
        "--model",
        choices=["viral_scorer", "engagement", "all"],
        default="all",
        help="Which model to export (default: all)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify ONNX Runtime inference after export",
    )
    parser.add_argument(
        "--seq-len",
        type=int,
        default=60,
        help="Fixed sequence length for engagement model export (default: 60)",
    )
    parser.add_argument("--status", action="store_true", help="Show model status and exit")
    args = parser.parse_args()

    if args.status:
        print_status()
        return

    results = []
    if args.model in ("viral_scorer", "all"):
        results.append(("viral_scorer", export_viral_scorer(verify=args.verify)))
    if args.model in ("engagement", "all"):
        results.append(("engagement", export_engagement(verify=args.verify, seq_len=args.seq_len)))

    print("\n" + "─" * 40)
    all_ok = all(ok for _, ok in results)
    for name, ok in results:
        status = "✅" if ok else "❌"
        print(f"  {status} {name}")
    print("─" * 40)

    if all_ok:
        print("\n🚀 ONNX export complete. Models ready for mobile/edge deployment.")
        print(f"   📁 Output dir: {ONNX_DIR}")
    else:
        print("\n⚠ Some exports failed — check that models are trained first.")
        sys.exit(1)


if __name__ == "__main__":
    main()
