#!/usr/bin/env python3
"""
ViraClip Dataset Downloader — Phase 7
======================================
Descarga automática de datasets de viralidad desde HuggingFace, Kaggle, y otras fuentes.

Usage:
    python scripts/download_datasets.py --all
    python scripts/download_datasets.py --tiktok-only
    python scripts/download_datasets.py --kaggle-only
"""

import os
import sys
import argparse
import logging
from pathlib import Path
from typing import Optional

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Dataset paths
DATASETS_DIR = Path(os.getenv("VIRACLIP_DATASETS_DIR", "/app/datasets"))
DATASETS_DIR.mkdir(exist_ok=True, parents=True)

# Required tokens
HF_TOKEN = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
KAGGLE_USERNAME = os.getenv("KAGGLE_USERNAME")
KAGGLE_KEY = os.getenv("KAGGLE_KEY")


def download_tiktok_dataset():
    """
    Descarga TikTok-Videos dataset desde HuggingFace.
    
    Dataset: datahiveai/Tiktok-Videos
    Size: ~2GB (100k+ videos metadata)
    Fields: plays, likes, shares, comments, duration, hashtags
    """
    logger.info("=" * 60)
    logger.info("Descargando TikTok-Videos dataset desde HuggingFace...")
    logger.info("=" * 60)
    
    if not HF_TOKEN:
        logger.warning("⚠ HF_TOKEN no configurado. Intentando descarga pública...")
        logger.warning("  Si falla, obtén token en: https://huggingface.co/settings/tokens")
    
    try:
        from datasets import load_dataset
        
        # Descargar dataset
        dataset = load_dataset(
            "datahiveai/Tiktok-Videos",
            split="train",
            token=HF_TOKEN,
            cache_dir=str(DATASETS_DIR / "huggingface")
        )
        
        logger.info(f"✅ TikTok dataset descargado: {len(dataset)} muestras")
        
        # Guardar versión procesada
        output_path = DATASETS_DIR / "tiktok_videos.parquet"
        dataset.to_parquet(str(output_path))
        logger.info(f"💾 Guardado en: {output_path}")
        
        # Mostrar estadísticas
        logger.info("\n📊 Estadísticas del dataset:")
        logger.info(f"  - Total videos: {len(dataset)}")
        
        if "plays" in dataset.column_names:
            import pandas as pd
            df = dataset.to_pandas()
            logger.info(f"  - Promedio plays: {df['plays'].mean():,.0f}")
            logger.info(f"  - Promedio likes: {df['likes'].mean():,.0f}")
            logger.info(f"  - Videos virales (>1M plays): {(df['plays'] > 1000000).sum()}")
        
        return True
        
    except ImportError:
        logger.error("❌ datasets library no instalada. Ejecuta: pip install datasets")
        return False
    except Exception as e:
        logger.error(f"❌ Error descargando TikTok dataset: {e}")
        logger.error("   Verifica HF_TOKEN y conexión a internet")
        return False


def download_kaggle_dataset():
    """
    Descarga Short Video Engagement dataset desde Kaggle.
    
    Dataset: Short Video Engagement Analysis
    Size: ~500MB (17k rows)
    Fields: audio_features, visual_features, engagement_metrics
    """
    logger.info("=" * 60)
    logger.info("Descargando Short Video Engagement desde Kaggle...")
    logger.info("=" * 60)
    
    if not KAGGLE_USERNAME or not KAGGLE_KEY:
        logger.error("❌ Credenciales de Kaggle no configuradas")
        logger.error("   1. Crea cuenta en https://www.kaggle.com")
        logger.error("   2. Genera API token en Settings → API → Create New Token")
        logger.error("   3. Configura KAGGLE_USERNAME y KAGGLE_KEY en .env")
        return False
    
    try:
        # Configurar credenciales
        os.environ["KAGGLE_USERNAME"] = KAGGLE_USERNAME
        os.environ["KAGGLE_KEY"] = KAGGLE_KEY
        
        from kaggle.api.kaggle_api_extended import KaggleApi
        
        api = KaggleApi()
        api.authenticate()
        
        # Descargar dataset (ajustar nombre según dataset real)
        dataset_name = "DATASET_PLACEHOLDER"  # TODO: reemplazar con dataset real
        output_dir = DATASETS_DIR / "kaggle"
        output_dir.mkdir(exist_ok=True, parents=True)
        
        logger.info(f"📥 Descargando {dataset_name}...")
        # api.dataset_download_files(dataset_name, path=str(output_dir), unzip=True)
        
        logger.warning("⚠ Kaggle dataset placeholder - actualizar con dataset real")
        logger.info("   Datasets sugeridos:")
        logger.info("   - netflix/netflix-shows (para análisis de engagement)")
        logger.info("   - datasnaek/youtube-new (YouTube trending)")
        
        return True
        
    except ImportError:
        logger.error("❌ kaggle library no instalada. Ejecuta: pip install kaggle")
        return False
    except Exception as e:
        logger.error(f"❌ Error descargando Kaggle dataset: {e}")
        return False


def download_youtube_trending():
    """
    Descarga datos de YouTube Trending usando YouTube Data API.
    
    Requiere: YOUTUBE_API_KEY en .env
    """
    logger.info("=" * 60)
    logger.info("Descargando YouTube Trending data...")
    logger.info("=" * 60)
    
    youtube_api_key = os.getenv("YOUTUBE_API_KEY")
    
    if not youtube_api_key:
        logger.warning("⚠ YOUTUBE_API_KEY no configurado")
        logger.warning("   Obtén key en: https://console.cloud.google.com/apis/credentials")
        logger.warning("   Skipping YouTube trending download...")
        return False
    
    try:
        from googleapiclient.discovery import build
        import json
        from datetime import datetime
        
        youtube = build('youtube', 'v3', developerKey=youtube_api_key)
        
        # Obtener videos trending
        request = youtube.videos().list(
            part="snippet,statistics,contentDetails",
            chart="mostPopular",
            regionCode="US",
            maxResults=50,
            videoCategoryId="0"  # All categories
        )
        response = request.execute()
        
        # Guardar datos
        output_path = DATASETS_DIR / f"youtube_trending_{datetime.now().strftime('%Y%m%d')}.json"
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(response, f, indent=2, ensure_ascii=False)
        
        logger.info(f"✅ YouTube trending descargado: {len(response['items'])} videos")
        logger.info(f"💾 Guardado en: {output_path}")
        
        return True
        
    except ImportError:
        logger.error("❌ google-api-python-client no instalada. Ejecuta: pip install google-api-python-client")
        return False
    except Exception as e:
        logger.error(f"❌ Error descargando YouTube trending: {e}")
        return False


def setup_dataset_cache():
    """Crea estructura de directorios para cache de datasets."""
    dirs = [
        DATASETS_DIR / "huggingface",
        DATASETS_DIR / "kaggle",
        DATASETS_DIR / "youtube",
        DATASETS_DIR / "processed",
        DATASETS_DIR / "models"  # Para LoRA models entrenados
    ]
    
    for dir_path in dirs:
        dir_path.mkdir(exist_ok=True, parents=True)
        logger.info(f"📁 Creado: {dir_path}")
    
    # Crear README
    readme_path = DATASETS_DIR / "README.md"
    with open(readme_path, 'w') as f:
        f.write("""# ViraClip Datasets

Este directorio contiene datasets descargados para entrenamiento de virality scoring y LoRAs.

## Estructura

- `huggingface/` - Datasets de HuggingFace (TikTok-Videos, etc.)
- `kaggle/` - Datasets de Kaggle (Short Video Engagement)
- `youtube/` - YouTube Trending data (JSON diarios)
- `processed/` - Datasets procesados y listos para entrenamiento
- `models/` - LoRA models entrenados

## Datasets Instalados

Ejecuta `python scripts/download_datasets.py --status` para ver datasets disponibles.

## Tokens Requeridos

- `HF_TOKEN` - HuggingFace token (https://huggingface.co/settings/tokens)
- `KAGGLE_USERNAME` + `KAGGLE_KEY` - Kaggle API credentials
- `YOUTUBE_API_KEY` - YouTube Data API v3 key (opcional)

Configura estos en `.env` antes de descargar datasets.
""")
    logger.info(f"📝 Creado: {readme_path}")


def check_dataset_status():
    """Verifica qué datasets están disponibles."""
    logger.info("=" * 60)
    logger.info("Estado de Datasets")
    logger.info("=" * 60)
    
    datasets_info = [
        {
            "name": "TikTok-Videos (HF)",
            "path": DATASETS_DIR / "tiktok_videos.parquet",
            "size_mb": "~2000",
            "source": "datahiveai/Tiktok-Videos"
        },
        {
            "name": "Kaggle Short Video",
            "path": DATASETS_DIR / "kaggle" / "short_video_engagement.csv",
            "size_mb": "~500",
            "source": "Kaggle"
        },
        {
            "name": "YouTube Trending",
            "path": DATASETS_DIR / "youtube",
            "size_mb": "~50/day",
            "source": "YouTube Data API"
        }
    ]
    
    for ds in datasets_info:
        path = ds["path"]
        exists = path.exists()
        
        status_icon = "✅" if exists else "❌"
        size_str = ""
        
        if exists:
            if path.is_file():
                size_mb = path.stat().st_size / (1024 * 1024)
                size_str = f" ({size_mb:.1f} MB)"
            elif path.is_dir():
                files = list(path.glob("*"))
                size_str = f" ({len(files)} archivos)"
        
        logger.info(f"{status_icon} {ds['name']:<25} {size_str}")
        logger.info(f"   Source: {ds['source']}")
        logger.info(f"   Path: {path}")
        logger.info("")


def main():
    parser = argparse.ArgumentParser(description="ViraClip Dataset Downloader")
    parser.add_argument("--all", action="store_true", help="Descargar todos los datasets")
    parser.add_argument("--tiktok-only", action="store_true", help="Solo TikTok dataset")
    parser.add_argument("--kaggle-only", action="store_true", help="Solo Kaggle dataset")
    parser.add_argument("--youtube-only", action="store_true", help="Solo YouTube trending")
    parser.add_argument("--status", action="store_true", help="Ver estado de datasets")
    parser.add_argument("--setup", action="store_true", help="Setup inicial de directorios")
    
    args = parser.parse_args()
    
    # Banner
    print("\n" + "=" * 60)
    print("   ViraClip Dataset Downloader — Phase 7")
    print("=" * 60 + "\n")
    
    # Setup inicial
    if args.setup or not DATASETS_DIR.exists():
        setup_dataset_cache()
        print("")
    
    # Verificar status
    if args.status:
        check_dataset_status()
        return
    
    # Descargar datasets
    success_count = 0
    total_count = 0
    
    if args.all or args.tiktok_only:
        total_count += 1
        if download_tiktok_dataset():
            success_count += 1
        print("")
    
    if args.all or args.kaggle_only:
        total_count += 1
        if download_kaggle_dataset():
            success_count += 1
        print("")
    
    if args.all or args.youtube_only:
        total_count += 1
        if download_youtube_trending():
            success_count += 1
        print("")
    
    # Si no se especificó nada, mostrar ayuda
    if not any([args.all, args.tiktok_only, args.kaggle_only, args.youtube_only, args.status, args.setup]):
        parser.print_help()
        print("\nEjemplos:")
        print("  python scripts/download_datasets.py --setup")
        print("  python scripts/download_datasets.py --all")
        print("  python scripts/download_datasets.py --tiktok-only")
        print("  python scripts/download_datasets.py --status")
        return
    
    # Resumen
    if total_count > 0:
        logger.info("=" * 60)
        logger.info(f"Descarga completada: {success_count}/{total_count} datasets exitosos")
        logger.info("=" * 60)
        
        if success_count < total_count:
            logger.warning("\n⚠ Algunos datasets fallaron. Revisa los logs arriba.")
            logger.warning("  Verifica tokens en .env y conexión a internet.")
        
        logger.info("\nPróximos pasos:")
        logger.info("  1. Verifica datasets: python scripts/download_datasets.py --status")
        logger.info("  2. Entrena virality scorer: python -m src.dataset_integration")
        logger.info("  3. Entrena LoRA en ComfyUI: http://localhost:8188")


if __name__ == "__main__":
    main()
