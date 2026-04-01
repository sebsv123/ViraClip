"""
Semantic B-Roll Matching Service
Pexels API (free, 200 req/hour) + sentence-transformers (MIT license)
Contextual B-roll matching based on semantic meaning, not just keywords
"""
import httpx
import os
import logging
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass
import numpy as np

logger = logging.getLogger(__name__)

# Lazy import for sentence-transformers
def _import_sentence_transformers():
    try:
        from sentence_transformers import SentenceTransformer, util
        return SentenceTransformer, util
    except ImportError:
        logger.error("sentence-transformers not installed. Run: pip install sentence-transformers")
        raise


@dataclass
class PexelsVideo:
    """Pexels video result with metadata"""
    id: int
    url: str
    video_files: List[Dict]
    description: str
    duration: int
    semantic_score: float = 0.0
    
    @property
    def best_quality_url(self) -> str:
        """Get best quality video URL"""
        if not self.video_files:
            return ""
        # Sort by quality (height), prefer 1080p or 720p
        sorted_files = sorted(
            self.video_files, 
            key=lambda x: x.get("height", 0), 
            reverse=True
        )
        for vf in sorted_files:
            if vf.get("height", 0) <= 1080:  # Prefer 1080p max
                return vf.get("link", "")
        return sorted_files[0].get("link", "") if sorted_files else ""


class SemanticBrollService:
    """
    Semantic B-roll matching using Pexels API + sentence-transformers
    Free alternative to expensive stock footage APIs
    """
    
    def __init__(
        self, 
        pexels_api_key: Optional[str] = None,
        embedding_model: str = "all-MiniLM-L6-v2"
    ):
        self.api_key = pexels_api_key or os.environ.get("PEXELS_API_KEY")
        if not self.api_key:
            logger.warning("Pexels API key not provided. B-roll service will not function.")
        
        self.base_url = "https://api.pexels.com/videos"
        self.embedding_model_name = embedding_model
        self.embedding_model = None
        self.sentence_transformers = None
        
        logger.info(f"Semantic B-roll Service initialized (model: {embedding_model})")
    
    def _load_embedding_model(self):
        """Lazy load sentence-transformers model (~80MB)"""
        if self.embedding_model is None:
            SentenceTransformer, util = _import_sentence_transformers()
            logger.info(f"Loading embedding model: {self.embedding_model_name}")
            self.embedding_model = SentenceTransformer(self.embedding_model_name)
            self.sentence_transformers = util
    
    async def search_videos(
        self, 
        query: str, 
        per_page: int = 10,
        orientation: str = "portrait"  # 9:16 for Shorts/Reels
    ) -> List[PexelsVideo]:
        """
        Search videos on Pexels API
        
        Args:
            query: Search query
            per_page: Results per page (max 80)
            orientation: "landscape", "portrait", or "square"
            
        Returns:
            List of PexelsVideo objects
        """
        if not self.api_key:
            logger.error("Pexels API key required")
            return []
        
        headers = {"Authorization": self.api_key}
        params = {
            "query": query,
            "per_page": min(per_page, 80),
            "orientation": orientation
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.base_url}/search",
                    headers=headers,
                    params=params
                )
                response.raise_for_status()
                data = response.json()
                
                videos = []
                for v in data.get("videos", []):
                    videos.append(PexelsVideo(
                        id=v["id"],
                        url=v["url"],
                        video_files=v.get("video_files", []),
                        description=v.get("user", {}).get("name", "") + " " + query,
                        duration=v.get("duration", 0)
                    ))
                
                logger.info(f"Found {len(videos)} videos for query: {query}")
                return videos
                
        except Exception as e:
            logger.error(f"Pexels search failed: {e}")
            return []
    
    async def semantic_match(
        self,
        transcript_segment: str,
        pexels_videos: List[PexelsVideo]
    ) -> Tuple[Optional[PexelsVideo], float]:
        """
        Find best semantic match using embeddings
        
        Args:
            transcript_segment: The transcript text to match
            pexels_videos: List of videos from Pexels
            
        Returns:
            (best_match, confidence_score) or (None, 0.0)
        """
        if not pexels_videos:
            return None, 0.0
        
        self._load_embedding_model()
        util = self.sentence_transformers
        
        # Encode transcript segment
        segment_embedding = self.embedding_model.encode(transcript_segment)
        
        # Encode each video description
        best_match = None
        best_score = 0.0
        
        for video in pexels_videos:
            # Create rich description from metadata
            description = f"{video.description} video footage"
            
            # Encode and compare
            video_embedding = self.embedding_model.encode(description)
            similarity = util.cos_sim(segment_embedding, video_embedding).item()
            
            video.semantic_score = similarity
            
            if similarity > best_score:
                best_score = similarity
                best_match = video
        
        # Log results
        if best_match:
            logger.info(f"Best semantic match: {best_score:.3f} for '{transcript_segment[:50]}...'")
        
        return best_match, best_score
    
    async def find_broll_for_segment(
        self,
        transcript_segment: str,
        segment_duration: float = 15.0,
        min_semantic_score: float = 0.3
    ) -> Optional[Dict]:
        """
        Complete pipeline: search + semantic match for B-roll
        
        Args:
            transcript_segment: Text to find matching footage for
            segment_duration: Target duration in seconds
            min_semantic_score: Minimum similarity threshold
            
        Returns:
            B-roll metadata dict or None
        """
        # Extract keywords from transcript for initial search
        search_query = self._extract_keywords(transcript_segment)
        
        # Search Pexels
        videos = await self.search_videos(search_query, per_page=15)
        
        if not videos:
            # Fallback: search with full text (truncated)
            videos = await self.search_videos(
                transcript_segment[:50], 
                per_page=10
            )
        
        if not videos:
            return None
        
        # Semantic matching
        best_video, score = await self.semantic_match(transcript_segment, videos)
        
        if best_video and score >= min_semantic_score:
            return {
                "video_url": best_video.best_quality_url,
                "pexels_id": best_video.id,
                "duration": min(segment_duration, best_video.duration),
                "semantic_score": score,
                "search_query": search_query,
                "matched_text": transcript_segment[:100],
                "source": "pexels_semantic"
            }
        
        return None
    
    def _extract_keywords(self, text: str) -> str:
        """Extract key nouns and verbs for search query"""
        # Simple keyword extraction (could use NLP for better results)
        words = text.lower().split()
        
        # Remove common stop words
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", 
            "be", "been", "being", "have", "has", "had",
            "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "must", "shall",
            "can", "need", "dare", "ought", "used", "to",
            "and", "but", "or", "yet", "so", "for", "nor",
            "at", "by", "from", "in", "into", "of", "off",
            "on", "onto", "out", "over", "to", "up", "with"
        }
        
        keywords = [w for w in words if w not in stop_words and len(w) > 3]
        
        # Return first 3-5 keywords
        return " ".join(keywords[:5])
    
    async def batch_find_broll(
        self,
        segments: List[Dict[str, Any]],
        min_semantic_score: float = 0.3
    ) -> List[Optional[Dict]]:
        """Find B-roll for multiple segments in parallel"""
        import asyncio
        
        tasks = [
            self.find_broll_for_segment(
                seg.get("text", ""),
                seg.get("duration", 15.0),
                min_semantic_score
            )
            for seg in segments
        ]
        
        return await asyncio.gather(*tasks)


def create_semantic_broll_service() -> SemanticBrollService:
    """Factory function with environment variables"""
    return SemanticBrollService(
        pexels_api_key=os.environ.get("PEXELS_API_KEY"),
        embedding_model=os.environ.get("BROLL_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    )


# Setup instructions
SETUP_INSTRUCTIONS = """
Setup for Semantic B-roll Service:

1. Get free Pexels API key: https://www.pexels.com/api/
2. Set environment variable:
   export PEXELS_API_KEY="your_api_key_here"
   
3. Install dependencies:
   pip install sentence-transformers httpx
   
4. The service uses:
   - Pexels API (200 requests/hour, FREE)
   - all-MiniLM-L6-v2 model (80MB, Apache 2.0 license)
   - Semantic matching vs keyword matching (key differentiator)

Free tier limits:
- 200 API requests/hour from Pexels
- Unlimited local embedding generation
- Model runs on CPU (4GB RAM) or GPU
"""
