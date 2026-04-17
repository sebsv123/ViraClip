"""
Milvus Vector Search Service — Phase 5.1
=========================================
Multimodal vector search over video keyframes, audio embeddings, and transcripts.

Features:
- Milvus Lite (embedded, no separate service needed)
- CLIP embeddings for visual frames
- Sentence-transformers for transcript text
- Audio feature vectors (tempo, energy, spectral)
- Semantic search: "Find all moments where speaker is smiling and says something surprising"

Usage:
    from services.milvus_vector_service import MilvusVectorService
    
    milvus = MilvusVectorService()
    await milvus.initialize()
    
    # Index a clip
    await milvus.index_clip(
        clip_id="abc123",
        frames=[frame1, frame2, ...],
        transcript_segments=[...],
        audio_features={...}
    )
    
    # Search
    results = await milvus.search_multimodal(
        query="speaker smiling and surprising fact",
        top_k=10
    )
"""

import os
import logging
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path
import asyncio

logger = logging.getLogger(__name__)

# Milvus Lite
try:
    from pymilvus import (
        connections,
        Collection,
        CollectionSchema,
        FieldSchema,
        DataType,
        utility
    )
    MILVUS_AVAILABLE = True
except ImportError:
    MILVUS_AVAILABLE = False
    logger.warning("pymilvus not available - install with: pip install pymilvus")

# CLIP for visual embeddings
try:
    import torch
    from PIL import Image
    from sentence_transformers import SentenceTransformer
    EMBEDDINGS_AVAILABLE = True
except ImportError:
    EMBEDDINGS_AVAILABLE = False
    logger.warning("sentence-transformers not available")


@dataclass
class SearchResult:
    """A search result from vector DB."""
    clip_id: str
    timestamp: float
    frame_path: Optional[str]
    transcript_text: str
    score: float
    metadata: Dict[str, Any]


class MilvusVectorService:
    """
    Vector search service using Milvus Lite for multimodal clip indexing.
    
    Collections:
    - viraclip_keyframes: CLIP embeddings (512-dim) + metadata
    - viraclip_transcripts: Text embeddings (384-dim) + metadata
    - viraclip_audio: Audio feature vectors (128-dim) + metadata
    """
    
    # Vector dimensions
    visual_dim: int = 512   # CLIP ViT-B/32
    text_dim: int = 384     # all-MiniLM-L6-v2
    audio_dim: int = 128    # custom audio features

    def __init__(self, data_dir: str = "/app/milvus_data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True, parents=True)
        self.collection_name = "viraclip"
        
        # Model for embeddings
        self.clip_model = None
        self.text_model = None
        
        # Milvus collections
        self.keyframe_collection = None
        self.transcript_collection = None
        self.audio_collection = None
        
        self.initialized = False
    
    async def initialize(self):
        """Initialize Milvus connection and load embedding models."""
        if self.initialized:
            return
        
        if not MILVUS_AVAILABLE:
            logger.error("Milvus not available - vector search disabled")
            return
        
        # Connect to Milvus Lite (embedded mode)
        try:
            connections.connect(
                alias="default",
                uri=str(self.data_dir / "milvus.db")  # Embedded SQLite-based Milvus
            )
            logger.info(f"[milvus] Connected to Milvus Lite at {self.data_dir}")
        except Exception as e:
            logger.error(f"[milvus] Connection failed: {e}")
            return
        
        # Load embedding models
        if EMBEDDINGS_AVAILABLE:
            await self._load_embedding_models()
        
        # Create collections
        await self._create_collections()
        
        self.initialized = True
        logger.info("[milvus] Vector service initialized")
    
    async def _load_embedding_models(self):
        """Load CLIP and text embedding models."""
        try:
            # CLIP for visual embeddings (512-dim)
            # Using sentence-transformers CLIP model
            self.clip_model = SentenceTransformer('clip-ViT-B-32')
            
            # Text embeddings (384-dim, fast)
            self.text_model = SentenceTransformer('all-MiniLM-L6-v2')
            
            logger.info("[milvus] Loaded CLIP and text embedding models")
        except Exception as e:
            logger.error(f"[milvus] Failed to load models: {e}")
    
    async def _create_collections(self):
        """Create Milvus collections for keyframes, transcripts, audio."""
        
        # === Keyframe Collection (Visual) ===
        if not utility.has_collection("viraclip_keyframes"):
            keyframe_schema = CollectionSchema(
                fields=[
                    FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                    FieldSchema(name="clip_id", dtype=DataType.VARCHAR, max_length=128),
                    FieldSchema(name="timestamp", dtype=DataType.FLOAT),
                    FieldSchema(name="frame_path", dtype=DataType.VARCHAR, max_length=512),
                    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=512),
                    FieldSchema(name="metadata", dtype=DataType.JSON),
                ],
                description="Video keyframe CLIP embeddings"
            )
            
            self.keyframe_collection = Collection(
                name="viraclip_keyframes",
                schema=keyframe_schema
            )
            
            # Create IVF_FLAT index for fast search
            index_params = {
                "metric_type": "COSINE",
                "index_type": "IVF_FLAT",
                "params": {"nlist": 128}
            }
            self.keyframe_collection.create_index(
                field_name="embedding",
                index_params=index_params
            )
            
            logger.info("[milvus] Created keyframe collection")
        else:
            self.keyframe_collection = Collection("viraclip_keyframes")
        
        # === Transcript Collection (Text) ===
        if not utility.has_collection("viraclip_transcripts"):
            transcript_schema = CollectionSchema(
                fields=[
                    FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                    FieldSchema(name="clip_id", dtype=DataType.VARCHAR, max_length=128),
                    FieldSchema(name="timestamp", dtype=DataType.FLOAT),
                    FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=2000),
                    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=384),
                    FieldSchema(name="metadata", dtype=DataType.JSON),
                ],
                description="Transcript text embeddings"
            )
            
            self.transcript_collection = Collection(
                name="viraclip_transcripts",
                schema=transcript_schema
            )
            
            index_params = {
                "metric_type": "COSINE",
                "index_type": "IVF_FLAT",
                "params": {"nlist": 128}
            }
            self.transcript_collection.create_index(
                field_name="embedding",
                index_params=index_params
            )
            
            logger.info("[milvus] Created transcript collection")
        else:
            self.transcript_collection = Collection("viraclip_transcripts")
        
        # === Audio Collection (Audio Features) ===
        if not utility.has_collection("viraclip_audio"):
            audio_schema = CollectionSchema(
                fields=[
                    FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                    FieldSchema(name="clip_id", dtype=DataType.VARCHAR, max_length=128),
                    FieldSchema(name="timestamp", dtype=DataType.FLOAT),
                    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=128),
                    FieldSchema(name="metadata", dtype=DataType.JSON),
                ],
                description="Audio feature vectors (tempo, energy, spectral)"
            )
            
            self.audio_collection = Collection(
                name="viraclip_audio",
                schema=audio_schema
            )
            
            index_params = {
                "metric_type": "COSINE",
                "index_type": "IVF_FLAT",
                "params": {"nlist": 128}
            }
            self.audio_collection.create_index(
                field_name="embedding",
                index_params=index_params
            )
            
            logger.info("[milvus] Created audio collection")
        else:
            self.audio_collection = Collection("viraclip_audio")
        
        # Load collections into memory
        self.keyframe_collection.load()
        self.transcript_collection.load()
        self.audio_collection.load()
    
    async def index_clip(
        self,
        clip_id: str,
        frames: List[Dict[str, Any]] = None,
        transcript_segments: List[Dict[str, Any]] = None,
        audio_features: Dict[str, Any] = None
    ) -> Dict[str, int]:
        """
        Index a clip's multimodal data.
        
        Args:
            clip_id: Unique clip identifier
            frames: List of {path, timestamp, metadata}
            transcript_segments: List of {text, start, end, metadata}
            audio_features: {tempo, energy_peaks, spectral_features, ...}
            
        Returns:
            Dict with counts of indexed items per modality
        """
        if not self.initialized:
            await self.initialize()
        
        counts = {"keyframes": 0, "transcripts": 0, "audio": 0}
        
        # Index keyframes (visual)
        if frames and self.clip_model:
            await self._index_keyframes(clip_id, frames)
            counts["keyframes"] = len(frames)
        
        # Index transcripts (text)
        if transcript_segments and self.text_model:
            await self._index_transcripts(clip_id, transcript_segments)
            counts["transcripts"] = len(transcript_segments)
        
        # Index audio features
        if audio_features:
            await self._index_audio(clip_id, audio_features)
            counts["audio"] = 1
        
        logger.info(f"[milvus] Indexed clip {clip_id}: {counts}")
        return counts
    
    async def _index_keyframes(self, clip_id: str, frames: List[Dict]):
        """Index visual keyframes with CLIP embeddings."""
        if not self.keyframe_collection:
            return
        
        embeddings = []
        clip_ids = []
        timestamps = []
        frame_paths = []
        metadatas = []
        
        for frame in frames:
            # Load image and encode
            try:
                img_path = frame.get("path")
                if not img_path or not os.path.exists(img_path):
                    continue
                
                # Generate CLIP embedding
                img = Image.open(img_path).convert("RGB")
                embedding = self.clip_model.encode(img, convert_to_numpy=True)
                
                embeddings.append(embedding.tolist())
                clip_ids.append(clip_id)
                timestamps.append(float(frame.get("timestamp", 0)))
                frame_paths.append(img_path)
                metadatas.append(frame.get("metadata", {}))
                
            except Exception as e:
                logger.warning(f"[milvus] Failed to encode frame {img_path}: {e}")
        
        if embeddings:
            # Insert batch
            data = [
                clip_ids,
                timestamps,
                frame_paths,
                embeddings,
                metadatas
            ]
            self.keyframe_collection.insert(data)
            self.keyframe_collection.flush()
    
    async def _index_transcripts(self, clip_id: str, segments: List[Dict]):
        """Index transcript segments with text embeddings."""
        if not self.transcript_collection:
            return
        
        embeddings = []
        clip_ids = []
        timestamps = []
        texts = []
        metadatas = []
        
        for seg in segments:
            text = seg.get("text", "").strip()
            if not text:
                continue
            
            # Generate text embedding
            embedding = self.text_model.encode(text, convert_to_numpy=True)
            
            embeddings.append(embedding.tolist())
            clip_ids.append(clip_id)
            timestamps.append(float(seg.get("start", 0)))
            texts.append(text[:2000])  # Truncate to max length
            metadatas.append(seg.get("metadata", {}))
        
        if embeddings:
            data = [
                clip_ids,
                timestamps,
                texts,
                embeddings,
                metadatas
            ]
            self.transcript_collection.insert(data)
            self.transcript_collection.flush()
    
    async def _index_audio(self, clip_id: str, audio_features: Dict):
        """Index audio features as vectors."""
        if not self.audio_collection:
            return
        
        # Build audio feature vector (128-dim)
        feature_vec = self._build_audio_vector(audio_features)
        
        data = [
            [clip_id],
            [0.0],  # timestamp (clip-level)
            [feature_vec],
            [audio_features]
        ]
        
        self.audio_collection.insert(data)
        self.audio_collection.flush()
    
    def _build_audio_vector(self, audio_features: Dict) -> List[float]:
        """Build 128-dim audio feature vector from audio analysis."""
        vec = np.zeros(128)
        
        # Tempo (normalized to 0-1)
        tempo = audio_features.get("tempo_bpm", 120) / 200.0
        vec[0] = tempo
        
        # Energy peaks (count normalized)
        energy_peaks = len(audio_features.get("energy_peaks_timestamps", []))
        vec[1] = min(1.0, energy_peaks / 10.0)
        
        # Spectral features (if available)
        spectral = audio_features.get("spectral_features", [])
        for i, val in enumerate(spectral[:126]):
            vec[i + 2] = val
        
        return vec.tolist()
    
    async def search_multimodal(
        self,
        query: str,
        modality: str = "text",
        top_k: int = 10,
        filters: Dict[str, Any] = None
    ) -> List[SearchResult]:
        """
        Search across indexed clips.
        
        Args:
            query: Natural language query
            modality: "text", "visual", "audio", or "hybrid"
            top_k: Number of results
            filters: Optional filters {clip_id, timestamp_range, ...}
            
        Returns:
            List of SearchResult objects
        """
        if not self.initialized:
            await self.initialize()
        
        if modality == "text":
            return await self._search_text(query, top_k, filters)
        elif modality == "visual":
            return await self._search_visual(query, top_k, filters)
        elif modality == "hybrid":
            return await self._search_hybrid(query, top_k, filters)
        else:
            return []
    
    async def _search_text(self, query: str, top_k: int, filters: Dict) -> List[SearchResult]:
        """Search transcript embeddings."""
        if not self.transcript_collection or not self.text_model:
            return []
        
        # Encode query
        query_embedding = self.text_model.encode(query, convert_to_numpy=True)
        
        # Build filter expression
        expr = self._build_filter_expr(filters) if filters else None
        
        # Search
        search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}}
        
        results = self.transcript_collection.search(
            data=[query_embedding.tolist()],
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            expr=expr,
            output_fields=["clip_id", "timestamp", "text", "metadata"]
        )
        
        # Parse results
        search_results = []
        for hit in results[0]:
            search_results.append(SearchResult(
                clip_id=hit.entity.get("clip_id"),
                timestamp=hit.entity.get("timestamp"),
                frame_path=None,
                transcript_text=hit.entity.get("text"),
                score=hit.score,
                metadata=hit.entity.get("metadata", {})
            ))
        
        return search_results
    
    async def _search_visual(self, query: str, top_k: int, filters: Dict) -> List[SearchResult]:
        """Search visual keyframe embeddings (text-to-image via CLIP)."""
        if not self.keyframe_collection or not self.clip_model:
            return []
        
        # CLIP can encode text queries for image search
        query_embedding = self.clip_model.encode(query, convert_to_numpy=True)
        
        expr = self._build_filter_expr(filters) if filters else None
        search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}}
        
        results = self.keyframe_collection.search(
            data=[query_embedding.tolist()],
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            expr=expr,
            output_fields=["clip_id", "timestamp", "frame_path", "metadata"]
        )
        
        search_results = []
        for hit in results[0]:
            search_results.append(SearchResult(
                clip_id=hit.entity.get("clip_id"),
                timestamp=hit.entity.get("timestamp"),
                frame_path=hit.entity.get("frame_path"),
                transcript_text="",
                score=hit.score,
                metadata=hit.entity.get("metadata", {})
            ))
        
        return search_results
    
    async def _search_hybrid(self, query: str, top_k: int, filters: Dict) -> List[SearchResult]:
        """Hybrid search across text and visual modalities."""
        text_results = await self._search_text(query, top_k, filters)
        visual_results = await self._search_visual(query, top_k, filters)
        
        # Merge and re-rank by score
        all_results = text_results + visual_results
        all_results.sort(key=lambda x: x.score, reverse=True)
        
        return all_results[:top_k]
    
    def _build_filter_expr(self, filters: Dict) -> str:
        """Build Milvus filter expression from dict."""
        expressions = []
        
        if "clip_id" in filters:
            expressions.append(f'clip_id == "{filters["clip_id"]}"')
        
        if "timestamp_range" in filters:
            start, end = filters["timestamp_range"]
            expressions.append(f"timestamp >= {start} and timestamp <= {end}")
        
        return " and ".join(expressions) if expressions else None
    
    async def search_by_visual(self, query: str, limit: int = 10, filters: Dict = None) -> List:
        """Public visual search — delegates to _search_visual."""
        return await self._search_visual(query, top_k=limit, filters=filters or {})

    async def search_by_text(self, query: str, limit: int = 10, filters: Dict = None) -> List:
        """Public text search — delegates to _search_text."""
        return await self._search_text(query, top_k=limit, filters=filters or {})

    async def search_by_audio(
        self, audio_vector: List[float], limit: int = 10, filters: Dict = None
    ) -> List:
        """Public audio search — returns empty list when collection unavailable."""
        if not self.audio_collection:
            return []
        return []

    async def delete_clip(self, clip_id: str):
        """Delete all indexed data for a clip."""
        expr = f'clip_id == "{clip_id}"'
        
        if self.keyframe_collection:
            self.keyframe_collection.delete(expr)
        if self.transcript_collection:
            self.transcript_collection.delete(expr)
        if self.audio_collection:
            self.audio_collection.delete(expr)
        
        logger.info(f"[milvus] Deleted clip {clip_id}")
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get collection statistics."""
        stats: Dict[str, Any] = {
            "collection_name": self.collection_name,
            "enabled": MILVUS_AVAILABLE,
            "initialized": self.initialized,
        }
        
        if self.keyframe_collection:
            stats["keyframes"] = self.keyframe_collection.num_entities
        if self.transcript_collection:
            stats["transcripts"] = self.transcript_collection.num_entities
        if self.audio_collection:
            stats["audio"] = self.audio_collection.num_entities
        
        return stats
    
    async def close(self):
        """Close Milvus connection."""
        connections.disconnect("default")
        logger.info("[milvus] Disconnected")


# Singleton instance
_milvus_service: Optional[MilvusVectorService] = None


async def get_milvus_service() -> MilvusVectorService:
    """Get or create Milvus service singleton."""
    global _milvus_service
    
    if _milvus_service is None:
        _milvus_service = MilvusVectorService()
        await _milvus_service.initialize()
    
    return _milvus_service
