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

# Module-level singleton for SentenceTransformer (CPU-only to preserve VRAM for Whisper)
_SENTENCE_MODEL = None
_SENTENCE_UTIL = None

# Redis B-roll blacklist key (shared with broll_service.py)
_BROLL_BLACKLIST_KEY = "broll:used_urls"


async def _redis_url_is_used(url: str) -> bool:
    """Return True if *url* is already in the global Redis B-roll blacklist."""
    try:
        from src.utils.redis_pool import get_redis_client
        r = await get_redis_client()
        _score = await r.zscore(_BROLL_BLACKLIST_KEY, url)
        return _score is not None
    except Exception as _e:
        logger.debug("[SemanticBroll] Redis blacklist check failed: %s", _e)
        return False

def get_sentence_model():
    global _SENTENCE_MODEL, _SENTENCE_UTIL
    if _SENTENCE_MODEL is None:
        from sentence_transformers import SentenceTransformer, util
        _SENTENCE_MODEL = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        _SENTENCE_MODEL = _SENTENCE_MODEL.to("cpu")  # free VRAM for Whisper
        _SENTENCE_UTIL = util
        logger.info("[SentenceTransformer] Loaded once on CPU (VRAM reserved for Whisper)")
    return _SENTENCE_MODEL, _SENTENCE_UTIL


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
        """Lazy load sentence-transformers model (~80MB) via singleton"""
        if self.embedding_model is None:
            self.embedding_model, self.sentence_transformers = get_sentence_model()
            logger.info(f"Using singleton embedding model: {self.embedding_model_name}")
    
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
        
        # Guard: skip API call if query is empty (prevents 400 Bad Request)
        if not query or not query.strip():
            logger.debug("[SemanticBroll] Empty query — skipping Pexels search")
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
        min_semantic_score: float = 0.5,
        used_urls: Optional[set] = None
    ) -> Optional[Dict]:
        """
        Complete pipeline: search + semantic match for B-roll
        
        Args:
            transcript_segment: Text to find matching footage for
            segment_duration: Target duration in seconds
            min_semantic_score: Minimum similarity threshold
            used_urls: Set of URLs already used in this task (for anti-repetition)
            
        Returns:
            B-roll metadata dict or None
        """
        if used_urls is None:
            used_urls = set()
        
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
            video_url = best_video.best_quality_url
            # FIX 4: Skip if URL already used in this task
            if video_url in used_urls:
                logger.info(f"[SemanticBroll] Skipping duplicate URL: {video_url[:60]}...")
                return None
            # Redis blacklist check: skip if used in any previous task
            if await _redis_url_is_used(video_url):
                logger.info(f"[SemanticBroll] Skipping Redis-blacklisted URL: {video_url[:60]}...")
                return None
            used_urls.add(video_url)
            return {
                "video_url": video_url,
                "pexels_id": best_video.id,
                "duration": min(segment_duration, best_video.duration),
                "semantic_score": score,
                "search_query": search_query,
                "matched_text": transcript_segment[:100],
                "source": "pexels_semantic"
            }
        
        return None
    
    def _extract_keywords(self, text: str) -> str:
        """Extract insurance-native + emotional search queries for Pexels.

        Priority order:
        1. INSURANCE CONCEPT MAP — if any insurance keyword is found,
           return the mapped insurance-native query.
        2. EMOTION MAP — if any emotional word is found, return the
           mapped emotional query.
        3. FALLBACK — take the 2 most concrete nouns from the transcript,
           append "insurance Spain". Never return generic terms.
        """
        text_lower = text.lower()

        # ── INSURANCE CONCEPT MAP ──────────────────────────────────────
        _INSURANCE_MAP: Dict[str, str] = {
            "póliza": "insurance policy document signing",
            "poliza": "insurance policy document signing",
            "policy": "insurance policy document signing",
            "contrato": "insurance policy document signing",
            "cobertura": "family protection insurance advisor",
            "coverage": "family protection insurance advisor",
            "protección": "family protection insurance advisor",
            "proteccion": "family protection insurance advisor",
            "prima": "insurance payment calculator family",
            "premium": "insurance payment calculator family",
            "pago": "insurance payment calculator family",
            "siniestro": "insurance claim document office",
            "reclamación": "insurance claim document office",
            "reclamacion": "insurance claim document office",
            "claim": "insurance claim document office",
            "ahorro": "family savings financial planning",
            "savings": "family savings financial planning",
            "futuro": "family savings financial planning",
            "riesgo": "risk protection family home",
            "risk": "risk protection family home",
            "seguro de vida": "life insurance family protection",
            "life insurance": "life insurance family protection",
            "seguro de coche": "car insurance document signing",
            "car insurance": "car insurance document signing",
            "auto": "car insurance document signing",
            "seguro del hogar": "home protection family house",
            "home insurance": "home protection family house",
            "hogar": "home protection family house",
        }

        # Check multi-word insurance phrases first
        _multi_word = ["seguro de vida", "seguro de coche", "seguro del hogar",
                       "life insurance", "car insurance", "home insurance"]
        for phrase in _multi_word:
            if phrase in text_lower:
                result = _INSURANCE_MAP.get(phrase)
                if result:
                    logger.info("[SemanticBroll] Insurance concept match: '%s' → '%s'", phrase, result)
                    return result

        # Check single-word insurance keywords
        for word in text_lower.split():
            word_clean = word.strip(".,!?;:'\"")
            if word_clean in _INSURANCE_MAP:
                result = _INSURANCE_MAP[word_clean]
                logger.info("[SemanticBroll] Insurance keyword match: '%s' → '%s'", word_clean, result)
                return result

        # ── EMOTION MAP ────────────────────────────────────────────────
        _EMOTION_MAP: Dict[str, str] = {
            "calma": "calm peaceful family home",
            "calm": "calm peaceful family home",
            "tranquilidad": "calm peaceful family home",
            "tranquilo": "calm peaceful family home",
            "paz": "calm peaceful family home",
            "peace": "calm peaceful family home",
            "relax": "calm peaceful family home",
            "seguridad": "family safe protected home",
            "safe": "family safe protected home",
            "preocupación": "worried family financial stress",
            "preocupacion": "worried family financial stress",
            "worry": "worried family financial stress",
            "miedo": "worried family financial stress",
            "fear": "worried family financial stress",
            "confianza": "confident advisor handshake client",
            "trust": "confident advisor handshake client",
            "felicidad": "happy family home protected",
            "alegría": "happy family home protected",
            "alegria": "happy family home protected",
            "happy": "happy family home protected",
            "responsabilidad": "responsible parent family future",
            "responsibility": "responsible parent family future",
        }

        for word in text_lower.split():
            word_clean = word.strip(".,!?;:'\"")
            if word_clean in _EMOTION_MAP:
                result = _EMOTION_MAP[word_clean]
                logger.info("[SemanticBroll] Emotion match: '%s' → '%s'", word_clean, result)
                return result

        # ── FALLBACK: concrete nouns + "insurance Spain" ───────────────
        # Take the 2 most concrete nouns from the transcript.
        # Never return generic terms like "business", "office", "technology", "people".
        _GENERIC_TERMS = {"business", "office", "technology", "people", "person",
                          "thing", "stuff", "way", "thing", "something", "everything",
                          "nothing", "anything", "work", "life", "time", "day", "year",
                          "world", "company", "service", "product", "system", "process"}

        words = text_lower.split()
        # Filter: keep words > 3 chars, not in stop words, not generic
        _STOP_WORDS = {
            "the", "a", "an", "is", "are", "was", "were",
            "be", "been", "being", "have", "has", "had",
            "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "must", "shall",
            "can", "need", "dare", "ought", "used", "to",
            "and", "but", "or", "yet", "so", "for", "nor",
            "at", "by", "from", "in", "into", "of", "off",
            "on", "onto", "out", "over", "to", "up", "with",
            "que", "de", "la", "el", "en", "un", "una", "por",
            "con", "las", "los", "del", "se", "no", "es", "lo",
            "más", "mas", "pero", "como", "para", "su", "al",
        }

        concrete = []
        for w in words:
            w_clean = w.strip(".,!?;:'\"")
            if (len(w_clean) > 3
                    and w_clean not in _STOP_WORDS
                    and w_clean not in _GENERIC_TERMS):
                concrete.append(w_clean)

        if concrete:
            result = " ".join(concrete[:2]) + " insurance Spain"
            logger.info("[SemanticBroll] Fallback: '%s' → '%s'", text[:40], result)
            return result

        # Absolute last resort — return a safe insurance query
        logger.warning("[SemanticBroll] Fallback exhausted — returning safe default")
        return "insurance family protection Spain"
    
    async def batch_find_broll(
        self,
        segments: List[Dict[str, Any]],
        min_semantic_score: float = 0.3,
        used_urls: Optional[set] = None
    ) -> List[Optional[Dict]]:
        """Find B-roll for multiple segments in parallel.

        Args:
            segments: List of segment dicts with 'text' and 'duration' keys.
            min_semantic_score: Minimum similarity threshold (0.0–1.0).
            used_urls: Shared set of URLs already used in this task.
                       If None, a new set is created (per-task singleton).
                       The same set is passed to every find_broll_for_segment()
                       call so no URL repeats across segments.
        """
        import asyncio
        
        if used_urls is None:
            used_urls = set()
        
        tasks = [
            self.find_broll_for_segment(
                seg.get("text", ""),
                seg.get("duration", 15.0),
                min_semantic_score,
                used_urls=used_urls
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
