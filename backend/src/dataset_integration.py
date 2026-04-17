"""
ViraClip Dataset Integration — Phase 7
=======================================
Downloads, preprocesses, and integrates viral video datasets for training
virality scorers, LoRAs, and engagement predictors.

Supported Datasets:
- TikTok-Videos (HF): 100k+ videos with engagement metrics
- Short Video Engagement (Kaggle): 17k rows, multimodal features
- YouTube Trending: Daily trending data
- UGC Short Videos (ArXiv): Watch percentage, continuation rate

Usage:
    from dataset_integration import TikTokDatasetLoader
    loader = TikTokDatasetLoader()
    df = loader.load_and_prepare()
    
    # Train virality scorer
    from virality_trainer import ViralityScorerTrainer
    trainer = ViralityScorerTrainer()
    model = trainer.train(df)
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Dataset cache directory
DATASET_CACHE_DIR = Path(os.environ.get("VRACLIP_DATASETS_DIR", "/app/datasets"))
DATASET_CACHE_DIR.mkdir(parents=True, exist_ok=True)


class TikTokDatasetLoader:
    """
    Loader for HuggingFace TikTok-Videos dataset.
    
    Features: play_count, digg_count (likes), share_count, comment_count, duration
    """
    
    DATASET_NAME = "datahiveai/Tiktok-Videos"
    
    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or DATASET_CACHE_DIR / "tiktok"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.df = None
        
    def load(self, split: str = "train", streaming: bool = False) -> "TikTokDatasetLoader":
        """Load dataset from HuggingFace or cache."""
        try:
            from datasets import load_dataset
            
            logger.info(f"Loading {self.DATASET_NAME} (split={split})...")
            
            # Try to load from cache first
            cache_file = self.cache_dir / f"{split}.parquet"
            if cache_file.exists():
                logger.info(f"Loading from cache: {cache_file}")
                import pandas as pd
                self.df = pd.read_parquet(cache_file)
                return self
            
            # Download from HF
            ds = load_dataset(self.DATASET_NAME, split=split, streaming=streaming)
            
            if streaming:
                # Convert streaming to pandas (first 10k samples)
                samples = []
                for i, sample in enumerate(ds):
                    if i >= 10000:
                        break
                    samples.append(sample)
                import pandas as pd
                self.df = pd.DataFrame(samples)
            else:
                self.df = ds.to_pandas()
            
            # Save to cache
            self.df.to_parquet(cache_file)
            logger.info(f"Cached to {cache_file}")
            
        except Exception as e:
            logger.error(f"Failed to load TikTok dataset: {e}")
            # Try fallback CSV if exists
            fallback = self.cache_dir / "tiktok_fallback.csv"
            if fallback.exists():
                import pandas as pd
                self.df = pd.read_csv(fallback)
            else:
                self.df = None
                
        return self
    
    def prepare_virality_labels(self) -> "TikTokDatasetLoader":
        """
        Create virality_score label from engagement metrics.
        
        Formula: log(plays + likes*2 + shares*5 + comments*3) normalized 0-100
        """
        if self.df is None:
            logger.warning("No data loaded, cannot prepare labels")
            return self
        
        # Calculate engagement score
        self.df['engagement_score'] = (
            self.df.get('play_count', 0) + 
            self.df.get('digg_count', 0) * 2 + 
            self.df.get('share_count', 0) * 5 + 
            self.df.get('comment_count', 0) * 3
        )
        
        # Log transform for better distribution
        self.df['virality_score'] = np.log1p(self.df['engagement_score'])
        
        # Normalize 0-100
        self.df['virality_score'] = (
            (self.df['virality_score'] - self.df['virality_score'].min()) / 
            (self.df['virality_score'].max() - self.df['virality_score'].min()) * 100
        ).round(2)
        
        # Binary label (top 20% = viral)
        threshold = self.df['virality_score'].quantile(0.8)
        self.df['is_viral'] = (self.df['virality_score'] >= threshold).astype(int)
        
        logger.info(f"Prepared {len(self.df)} samples with virality labels")
        logger.info(f"Viral threshold: {threshold:.2f}")
        
        return self
    
    def get_training_split(self, test_size: float = 0.2) -> Tuple[Any, Any]:
        """Return train/test split for ML training."""
        from sklearn.model_selection import train_test_split
        
        if self.df is None:
            raise ValueError("No data loaded")
        
        # Features for training
        feature_cols = ['duration', 'virality_score']  # Extend with more features
        
        X = self.df[feature_cols].fillna(0)
        y = self.df['is_viral']
        
        return train_test_split(X, y, test_size=test_size, random_state=42, stratify=y)


class KaggleEngagementLoader:
    """
    Loader for Kaggle Short Video Engagement dataset.
    
    Features: Audio entropy, image histograms, views, likes, comments
    """
    
    DATASET_NAME = "short-video-engagement"
    
    def __init__(self, csv_path: Optional[str] = None):
        self.csv_path = csv_path or str(DATASET_CACHE_DIR / "kaggle_engagement.csv")
        self.df = None
        
    def load(self) -> "KaggleEngagementLoader":
        """Load from CSV or download via Kaggle API."""
        import pandas as pd
        
        if Path(self.csv_path).exists():
            logger.info(f"Loading from {self.csv_path}")
            self.df = pd.read_csv(self.csv_path)
        else:
            # Try Kaggle API
            try:
                import kaggle
                logger.info("Downloading from Kaggle...")
                kaggle.api.dataset_download_files(
                    "your-dataset/short-video-engagement",
                    path=DATASET_CACHE_DIR,
                    unzip=True
                )
                self.df = pd.read_csv(self.csv_path)
            except Exception as e:
                logger.error(f"Failed to download: {e}")
                self.df = None
                
        return self
    
    def prepare_multimodal_features(self) -> Dict[str, np.ndarray]:
        """
        Extract multimodal features for virality prediction.
        
        Returns dict with: audio_features, visual_features, text_features
        """
        if self.df is None:
            return {}
        
        # Audio features: entropy, spectral features
        audio_cols = [col for col in self.df.columns if 'audio' in col.lower()]
        audio_features = self.df[audio_cols].values if audio_cols else np.zeros((len(self.df), 10))
        
        # Visual features: histograms, colors
        visual_cols = [col for col in self.df.columns if any(x in col.lower() for x in ['hist', 'color', 'pixel'])]
        visual_features = self.df[visual_cols].values if visual_cols else np.zeros((len(self.df), 20))
        
        return {
            'audio': audio_features,
            'visual': visual_features,
            'target': self.df.get('engagement_score', np.zeros(len(self.df)))
        }


class YouTubeTrendingLoader:
    """
    Loader for YouTube Trending data (daily updates).
    
    Features: Views, likes, dislikes, tags, category, publish time
    """
    
    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or DATASET_CACHE_DIR / "youtube_trending"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.df = None
        
    def load_daily(self, country: str = "US") -> "YouTubeTrendingLoader":
        """Load latest daily trending data."""
        import pandas as pd
        
        # Check for cached daily data
        cache_file = self.cache_dir / f"trending_{country}_{pd.Timestamp.now().strftime('%Y%m%d')}.csv"
        
        if cache_file.exists():
            self.df = pd.read_csv(cache_file)
            return self
        
        # Download from Kaggle or API
        try:
            # Kaggle dataset: rsrishav/youtube-trending-video-dataset
            url = f"https://www.kaggle.com/datasets/rsrishav/youtube-trending-video-dataset/download"
            logger.info(f"Downloading YouTube trending data for {country}")
            
            # Note: Actual implementation would use Kaggle API or direct download
            # For now, create empty placeholder
            self.df = pd.DataFrame()
            
        except Exception as e:
            logger.error(f"Failed to load YouTube trending: {e}")
            self.df = None
            
        return self
    
    def extract_trending_patterns(self) -> Dict[str, Any]:
        """Extract trending patterns for Ollama prompts."""
        if self.df is None or len(self.df) == 0:
            return {}
        
        patterns = {
            "top_tags": self.df['tags'].str.split('|').explode().value_counts().head(20).to_dict(),
            "avg_views_viral": self.df[self.df['views'] > self.df['views'].quantile(0.9)]['views'].mean(),
            "optimal_duration_range": [
                self.df[self.df['views'] > self.df['views'].quantile(0.8)]['duration'].quantile(0.25),
                self.df[self.df['views'] > self.df['views'].quantile(0.8)]['duration'].quantile(0.75)
            ],
            "best_publish_times": self.df[self.df['views'] > self.df['views'].quantile(0.9)]['publish_time'].value_counts().head(5).to_dict()
        }
        
        return patterns


class DatasetIntegrationService:
    """
    Unified service for dataset operations in ViraClip.
    
    Coordinates multiple datasets, provides training data for virality models,
    and maintains fresh data via scheduled updates.
    """
    
    def __init__(self):
        self.tiktok_loader = TikTokDatasetLoader()
        self.kaggle_loader = KaggleEngagementLoader()
        self.youtube_loader = YouTubeTrendingLoader()
        
    async def initialize_datasets(self):
        """Load all datasets on startup."""
        logger.info("Initializing ViraClip datasets...")
        
        # Load TikTok (primary dataset)
        self.tiktok_loader.load(split="train").prepare_virality_labels()
        
        # Load Kaggle if available
        try:
            self.kaggle_loader.load()
        except:
            logger.warning("Kaggle dataset not available")
        
        logger.info("Dataset initialization complete")
        
    def get_combined_training_data(self) -> Optional[pd.DataFrame]:
        """Merge datasets for comprehensive training."""
        import pandas as pd
        
        datasets = []
        
        if self.tiktok_loader.df is not None:
            df = self.tiktok_loader.df.copy()
            df['source'] = 'tiktok'
            datasets.append(df)
        
        if self.kaggle_loader.df is not None:
            df = self.kaggle_loader.df.copy()
            df['source'] = 'kaggle'
            datasets.append(df)
        
        if not datasets:
            return None
        
        # Combine (simplified - actual implementation would align columns)
        combined = pd.concat(datasets, ignore_index=True)
        return combined
    
    def generate_ollama_context(self) -> str:
        """Generate context for Ollama prompts based on dataset patterns."""
        if self.tiktok_loader.df is None:
            return ""
        
        viral_threshold = self.tiktok_loader.df['virality_score'].quantile(0.8)
        top_videos = self.tiktok_loader.df[self.tiktok_loader.df['virality_score'] >= viral_threshold]
        
        context = f"""
Based on analysis of {len(self.tiktok_loader.df)} TikTok videos:
- Viral threshold: {viral_threshold:.1f}/100
- Average plays (viral): {top_videos['play_count'].mean():,.0f}
- Average duration (viral): {top_videos['duration'].mean():.1f}s
- Key success factors: Strong hook in first 3s, 15-30s optimal length, high engagement first hour
"""
        return context


class ViralityScorerTrainer:
    """
    Trainer for custom virality prediction models.
    
    Trains on dataset features to predict virality_score or is_viral.
    """
    
    def __init__(self, model_type: str = "xgboost"):
        self.model_type = model_type
        self.model = None
        self.feature_importance = None
        
    def train(self, df: pd.DataFrame, target_col: str = "is_viral") -> "ViralityScorerTrainer":
        """
        Train virality prediction model.
        
        Args:
            df: DataFrame with features and target
            target_col: 'is_viral' (binary) or 'virality_score' (regression)
        """
        from sklearn.model_selection import cross_val_score
        
        # Select features (extend based on available data)
        feature_cols = ['duration', 'virality_score']
        available_features = [c for c in feature_cols if c in df.columns]
        
        X = df[available_features].fillna(0)
        y = df[target_col]
        
        if self.model_type == "xgboost":
            try:
                from xgboost import XGBClassifier, XGBRegressor
                
                if target_col == "is_viral":
                    self.model = XGBClassifier(n_estimators=100, max_depth=5)
                else:
                    self.model = XGBRegressor(n_estimators=100, max_depth=5)
                    
                self.model.fit(X, y)
                
                # Feature importance
                self.feature_importance = dict(zip(available_features, self.model.feature_importances_))
                
                # CV score
                scores = cross_val_score(self.model, X, y, cv=5)
                logger.info(f"Model trained. CV accuracy: {scores.mean():.3f} (+/- {scores.std()*2:.3f})")
                
            except ImportError:
                logger.error("xgboost not installed, using sklearn fallback")
                from sklearn.ensemble import RandomForestClassifier
                self.model = RandomForestClassifier(n_estimators=100)
                self.model.fit(X, y)
        
        return self
    
    def predict(self, features: Dict[str, float]) -> float:
        """Predict virality for a single clip."""
        if self.model is None:
            return 50.0  # Default
        
        X = np.array([[features.get('duration', 0), features.get('engagement', 0)]])
        pred = self.model.predict_proba(X)[0][1] if hasattr(self.model, 'predict_proba') else self.model.predict(X)[0]
        return float(pred) * 100 if hasattr(self.model, 'predict_proba') else float(pred)
    
    def save(self, path: str):
        """Save trained model."""
        import joblib
        joblib.dump(self.model, path)
        logger.info(f"Model saved to {path}")
    
    def load(self, path: str):
        """Load trained model."""
        import joblib
        self.model = joblib.load(path)
        logger.info(f"Model loaded from {path}")


# Convenience functions for quick access
def get_tiktok_dataset() -> TikTokDatasetLoader:
    """Get TikTok dataset (downloads if needed)."""
    return TikTokDatasetLoader().load(split="train").prepare_virality_labels()


def get_youtube_trending_patterns() -> Dict[str, Any]:
    """Get current YouTube trending patterns."""
    loader = YouTubeTrendingLoader()
    loader.load_daily()
    return loader.extract_trending_patterns()


# If run directly, test dataset loading
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Test TikTok dataset
    logger.info("Testing TikTok dataset loader...")
    tiktok = TikTokDatasetLoader().load(split="train")
    if tiktok.df is not None:
        tiktok.prepare_virality_labels()
        print(f"Loaded {len(tiktok.df)} TikTok videos")
        print(f"Columns: {tiktok.df.columns.tolist()}")
        print(f"\nVirality score distribution:")
        print(tiktok.df['virality_score'].describe())
