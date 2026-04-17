#!/usr/bin/env python3
"""
ViraClip Setup Verification — Smoke Tests
==========================================
Verifica que todas las fases implementadas funcionen correctamente.

Usage:
    python scripts/verify_setup.py --all
    python scripts/verify_setup.py --phase 4.1
    python scripts/verify_setup.py --phase 5.3
"""

import os
import sys
import argparse
import logging
import asyncio
from pathlib import Path
from typing import Dict, List, Tuple, Any

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Test results
test_results: List[Tuple[str, bool, str]] = []


def log_test(name: str, passed: bool, message: str = ""):
    """Log test result."""
    status = "✅ PASS" if passed else "❌ FAIL"
    logger.info(f"{status}: {name}")
    if message:
        logger.info(f"  └─ {message}")
    test_results.append((name, passed, message))


async def verify_phase_4_1():
    """Verify Phase 4.1: Multi-platform export presets."""
    logger.info("\n" + "=" * 60)
    logger.info("Testing Phase 4.1: Multi-platform Export")
    logger.info("=" * 60)
    
    try:
        from video_processing.export_profiles import (
            ExportService, Platform, BitrateVariant
        )
        log_test("Phase 4.1: Import export_profiles", True)
        
        # Test service initialization
        service = ExportService()
        log_test("Phase 4.1: ExportService init", True)
        
        # Test profile retrieval
        tiktok_profile = service.get_profile(Platform.TIKTOK)
        has_variants = tiktok_profile.bitrate_variants is not None
        log_test(
            "Phase 4.1: TikTok profile has variants",
            has_variants,
            f"Found {len(tiktok_profile.bitrate_variants) if has_variants else 0} variants"
        )
        
        # Test SRT export function exists
        has_srt_method = hasattr(service, 'export_srt_captions')
        log_test(
            "Phase 4.1: SRT export method exists",
            has_srt_method
        )
        
        # Test export specs
        specs = service.get_export_specs(Platform.TIKTOK)
        log_test(
            "Phase 4.1: Export specs generation",
            'has_variants' in specs,
            f"Platform: {specs.get('platform')}, Variants: {specs.get('has_variants')}"
        )
        
        return True
        
    except Exception as e:
        log_test("Phase 4.1: Overall", False, str(e))
        return False


async def verify_phase_4_3():
    """Verify Phase 4.3: Viral trend integration."""
    logger.info("\n" + "=" * 60)
    logger.info("Testing Phase 4.3: Viral Trends")
    logger.info("=" * 60)
    
    try:
        from services.viral_trend_service import ViralTrendService
        log_test("Phase 4.3: Import viral_trend_service", True)
        
        # Test service initialization
        service = ViralTrendService()
        log_test("Phase 4.3: ViralTrendService init", True)
        
        # Test trend boost (without actual API calls)
        base_score = 75.0
        boosted = service.apply_trend_boost(
            base_score=base_score,
            transcript="test content",
            hashtags=["test"],
            platform="tiktok"
        )
        log_test(
            "Phase 4.3: Trend boost calculation",
            isinstance(boosted, float),
            f"Base: {base_score} → Boosted: {boosted}"
        )
        
        # Test fallback trends
        trending_hashtags = service.get_trending_hashtags("tiktok", limit=5)
        log_test(
            "Phase 4.3: Get trending hashtags",
            len(trending_hashtags) > 0,
            f"Found {len(trending_hashtags)} trending tags"
        )
        
        return True
        
    except Exception as e:
        log_test("Phase 4.3: Overall", False, str(e))
        return False


async def verify_phase_5_1():
    """Verify Phase 5.1: Milvus vector DB."""
    logger.info("\n" + "=" * 60)
    logger.info("Testing Phase 5.1: Milvus Vector DB")
    logger.info("=" * 60)
    
    try:
        from services.milvus_vector_service import MilvusVectorService
        log_test("Phase 5.1: Import milvus_vector_service", True)
        
        # Test service initialization
        service = MilvusVectorService()
        log_test("Phase 5.1: MilvusVectorService init", True)
        
        # Check if Milvus is available
        try:
            from pymilvus import connections
            log_test("Phase 5.1: pymilvus library available", True)
        except ImportError:
            log_test("Phase 5.1: pymilvus library available", False, "Install with: pip install pymilvus")
        
        # Test methods exist
        has_index_method = hasattr(service, 'index_clip')
        has_search_method = hasattr(service, 'search_multimodal')
        
        log_test("Phase 5.1: index_clip method exists", has_index_method)
        log_test("Phase 5.1: search_multimodal method exists", has_search_method)
        
        return True
        
    except Exception as e:
        log_test("Phase 5.1: Overall", False, str(e))
        return False


async def verify_phase_5_3():
    """Verify Phase 5.3: Feedback loop."""
    logger.info("\n" + "=" * 60)
    logger.info("Testing Phase 5.3: Feedback Loop")
    logger.info("=" * 60)
    
    try:
        from services.feedback_loop_service import FeedbackLoopService
        log_test("Phase 5.3: Import feedback_loop_service", True)
        
        # Test service initialization
        service = FeedbackLoopService()
        log_test("Phase 5.3: FeedbackLoopService init", True)
        
        # Check training libraries
        try:
            import pandas as pd
            import xgboost as xgb
            from sklearn.model_selection import train_test_split
            log_test("Phase 5.3: ML libraries available", True)
            
            # Test synthetic data generation
            df = await service.collect_feedback_batch(days_back=7)
            log_test(
                "Phase 5.3: Collect feedback batch",
                len(df) > 0,
                f"Generated {len(df)} synthetic samples"
            )
            
            # Test feature extraction
            X, y = service.extract_features(df)
            log_test(
                "Phase 5.3: Extract features",
                len(X) == len(y),
                f"X: {X.shape}, y: {len(y)}"
            )
            
            # Test prediction method exists
            has_predict = hasattr(service, 'predict')
            log_test("Phase 5.3: predict method exists", has_predict)
            
        except ImportError as ie:
            log_test("Phase 5.3: ML libraries available", False, str(ie))
        
        return True
        
    except Exception as e:
        log_test("Phase 5.3: Overall", False, str(e))
        return False


async def verify_datasets():
    """Verify dataset download scripts."""
    logger.info("\n" + "=" * 60)
    logger.info("Testing Dataset Integration")
    logger.info("=" * 60)
    
    try:
        # Check download script exists
        download_script = Path(__file__).parent / "download_datasets.py"
        script_exists = download_script.exists()
        log_test(
            "Datasets: download_datasets.py exists",
            script_exists,
            str(download_script)
        )
        
        # Check HuggingFace library
        try:
            from datasets import load_dataset
            log_test("Datasets: HuggingFace datasets library", True)
        except ImportError:
            log_test("Datasets: HuggingFace datasets library", False, "Install with: pip install datasets")
        
        # Check Kaggle library
        try:
            from kaggle.api.kaggle_api_extended import KaggleApi
            log_test("Datasets: Kaggle API library", True)
        except ImportError:
            log_test("Datasets: Kaggle API library", False, "Install with: pip install kaggle")
        
        # Check YouTube API
        try:
            from googleapiclient.discovery import build
            log_test("Datasets: Google API client", True)
        except ImportError:
            log_test("Datasets: Google API client", False, "Install with: pip install google-api-python-client")
        
        return True
        
    except Exception as e:
        log_test("Datasets: Overall", False, str(e))
        return False


async def verify_comfyui_setup():
    """Verify ComfyUI workflows and nodes."""
    logger.info("\n" + "=" * 60)
    logger.info("Testing ComfyUI Setup")
    logger.info("=" * 60)
    
    try:
        # Check workflows exist
        workflows_dir = Path(__file__).parent.parent.parent / "workflows"
        workflows_exist = workflows_dir.exists()
        log_test(
            "ComfyUI: Workflows directory exists",
            workflows_exist,
            str(workflows_dir)
        )
        
        if workflows_exist:
            workflow_files = list(workflows_dir.glob("*.json"))
            log_test(
                "ComfyUI: Workflow JSON files",
                len(workflow_files) > 0,
                f"Found {len(workflow_files)} workflows"
            )
        
        # Check custom nodes
        nodes_dir = Path(__file__).parent.parent / "comfy_nodes"
        nodes_exist = nodes_dir.exists()
        log_test(
            "ComfyUI: Custom nodes directory exists",
            nodes_exist,
            str(nodes_dir)
        )
        
        if nodes_exist:
            init_file = nodes_dir / "__init__.py"
            log_test(
                "ComfyUI: __init__.py exists",
                init_file.exists()
            )
            
            # Check for key node files
            key_files = [
                "viraclip_nodes.py",
                "viraclip_training_nodes.py",
                "viraclip_advanced_ml.py"
            ]
            
            for file_name in key_files:
                file_path = nodes_dir / file_name
                log_test(
                    f"ComfyUI: {file_name} exists",
                    file_path.exists()
                )
        
        return True
        
    except Exception as e:
        log_test("ComfyUI: Overall", False, str(e))
        return False


async def verify_docker_config():
    """Verify docker-compose.yml configuration."""
    logger.info("\n" + "=" * 60)
    logger.info("Testing Docker Configuration")
    logger.info("=" * 60)
    
    try:
        compose_file = Path(__file__).parent.parent.parent / "docker-compose.yml"
        compose_exists = compose_file.exists()
        log_test(
            "Docker: docker-compose.yml exists",
            compose_exists,
            str(compose_file)
        )
        
        if compose_exists:
            with open(compose_file, 'r') as f:
                content = f.read()
            
            # Check for key services
            services = [
                "backend",
                "frontend",
                "worker",
                "postgres",
                "redis",
                "ollama",
                "comfyui"
            ]
            
            for service in services:
                has_service = f"{service}:" in content
                log_test(
                    f"Docker: {service} service configured",
                    has_service
                )
            
            # Check for volumes
            volumes = [
                "comfyui_models",
                "comfyui_workflows",
                "whisper_models"
            ]
            
            for volume in volumes:
                has_volume = volume in content
                log_test(
                    f"Docker: {volume} volume configured",
                    has_volume
                )
        
        return True
        
    except Exception as e:
        log_test("Docker: Overall", False, str(e))
        return False


def print_summary():
    """Print test summary."""
    logger.info("\n" + "=" * 60)
    logger.info("Test Summary")
    logger.info("=" * 60)
    
    total = len(test_results)
    passed = sum(1 for _, p, _ in test_results if p)
    failed = total - passed
    
    logger.info(f"\nTotal tests: {total}")
    logger.info(f"Passed: {passed} ✅")
    logger.info(f"Failed: {failed} ❌")
    logger.info(f"Success rate: {(passed/total*100):.1f}%")
    
    if failed > 0:
        logger.info("\nFailed tests:")
        for name, passed, msg in test_results:
            if not passed:
                logger.info(f"  ❌ {name}")
                if msg:
                    logger.info(f"     └─ {msg}")
    
    return failed == 0


async def main():
    parser = argparse.ArgumentParser(description="ViraClip Setup Verification")
    parser.add_argument("--all", action="store_true", help="Run all tests")
    parser.add_argument("--phase", type=str, help="Test specific phase (e.g., 4.1, 5.3)")
    parser.add_argument("--datasets", action="store_true", help="Test dataset integration")
    parser.add_argument("--comfyui", action="store_true", help="Test ComfyUI setup")
    parser.add_argument("--docker", action="store_true", help="Test Docker config")
    
    args = parser.parse_args()
    
    # Banner
    print("\n" + "=" * 60)
    print("   ViraClip Setup Verification — Smoke Tests")
    print("=" * 60 + "\n")
    
    # Run tests
    if args.all:
        await verify_phase_4_1()
        await verify_phase_4_3()
        await verify_phase_5_1()
        await verify_phase_5_3()
        await verify_datasets()
        await verify_comfyui_setup()
        await verify_docker_config()
    
    elif args.phase == "4.1":
        await verify_phase_4_1()
    elif args.phase == "4.3":
        await verify_phase_4_3()
    elif args.phase == "5.1":
        await verify_phase_5_1()
    elif args.phase == "5.3":
        await verify_phase_5_3()
    
    elif args.datasets:
        await verify_datasets()
    elif args.comfyui:
        await verify_comfyui_setup()
    elif args.docker:
        await verify_docker_config()
    
    else:
        parser.print_help()
        print("\nExamples:")
        print("  python scripts/verify_setup.py --all")
        print("  python scripts/verify_setup.py --phase 5.3")
        print("  python scripts/verify_setup.py --datasets")
        return 1
    
    # Print summary
    all_passed = print_summary()
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
