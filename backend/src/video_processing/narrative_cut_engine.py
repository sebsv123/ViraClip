"""
Narrative Cut Engine - Intelligent cut point detection
Detects natural break points for seamless editing
"""
import logging
import re
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional

import threading

import numpy as np

logger = logging.getLogger(__name__)

# ── Module-level LangGraph singleton (thread-safe) ──────────────────────────
# Building the graph compiles it via LangGraph's VariableBuilder, which
# registers built-in functions. If multiple threads compile simultaneously,
# the same built-in gets registered twice → "Duplicate dispatch rule".
# Using a threading.Lock ensures exactly one compilation per process.

_graph_instance = None
_graph_lock = threading.Lock()


def _get_or_build_graph():
    """Return the compiled LangGraph, building it exactly once (thread-safe).
    
    Uses double-checked locking. On any error, logs WARNING and returns None.
    The caller should handle None gracefully (skip narrative cuts for that clip).
    """
    global _graph_instance
    if _graph_instance is not None:
        logger.debug("[NarrativeCut] Reusing compiled graph singleton")
        return _graph_instance
    with _graph_lock:
        if _graph_instance is not None:
            logger.debug("[NarrativeCut] Reusing compiled graph singleton")
            return _graph_instance
        if NarrativeCutEngine._graph_compiled:
            logger.debug("[NarrativeCut] Graph already compiled (class flag)")
            return _graph_instance
        try:
            from langgraph.graph import StateGraph, START
            graph = StateGraph(dict)
            graph.add_node("entry", lambda state: state)
            graph.add_edge(START, "entry")
            _graph_instance = graph.compile()
            NarrativeCutEngine._graph_compiled = True
            logger.info("[NarrativeCut] Building graph singleton")
        except Exception as exc:
            logger.warning("[NarrativeCut] Failed to build graph: %s", exc)
            _graph_instance = None
    return _graph_instance

# Module-level singleton for SentenceTransformer (CPU-only to preserve VRAM for Whisper)
_SENTENCE_MODEL = None
_SENTENCE_UTIL = None

def get_sentence_model():
    global _SENTENCE_MODEL, _SENTENCE_UTIL
    if _SENTENCE_MODEL is None:
        from sentence_transformers import SentenceTransformer, util
        _SENTENCE_MODEL = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        _SENTENCE_MODEL = _SENTENCE_MODEL.to("cpu")  # free VRAM for Whisper
        _SENTENCE_UTIL = util
        logger.info("[SentenceTransformer] Loaded once on CPU (VRAM reserved for Whisper)")
    return _SENTENCE_MODEL, _SENTENCE_UTIL

# Hesitation markers that indicate natural cut points
HESITATION_MARKERS = [
    "um", "uh", "eh", "ah", "well", "so", "like", "you know",
    "i mean", "basically", "literally", "actually", "honestly"
]


@dataclass
class CutPoint:
    """A detected point where cutting makes narrative sense"""
    timestamp: float
    confidence: float
    reason: str  # "silence", "topic_change", "hesitation", "energy_drop"
    suggested_transition: str  # "jump_cut", "broll", "fade"


@dataclass
class NarrativeSegment:
    """Segment with intelligent cut points inside"""
    start: float
    end: float
    text: str
    internal_cuts: List[CutPoint]
    best_exit_point: float  # Where to cut if this segment ends
    best_entry_point: float  # Where to start if this is a continuation


class NarrativeCutEngine:
    """
    Detects intelligent cut points using:
    - Audio silences (>0.5s)
    - Topic changes (sentence-transformers)
    - Hesitation markers ("um", "eh")
    - Energy drops in audio

    The compiled LangGraph is built once at module level with a threading.Lock
    to prevent "Duplicate dispatch rule for <built-in function intern>" when
    multiple threads create NarrativeCutEngine instances simultaneously.
    """

    _graph_compiled = False

    def __init__(self, min_silence_duration: float = 0.5):
        self.min_silence_duration = min_silence_duration
        self.sentence_transformers = None
        # Reference the module-level singleton graph (built once, thread-safe)
        self._graph = _get_or_build_graph()
    
    def _load_embeddings(self):
        """Lazy load sentence-transformers for topic detection via singleton"""
        if self.sentence_transformers is None:
            try:
                model, util = get_sentence_model()
                self.sentence_transformers = {'model': model, 'util': util}
            except ImportError:
                logger.warning("sentence-transformers not available, topic detection disabled")
    
    def find_narrative_cuts(
        self,
        transcript: str,
        words_with_timestamps: List[Dict],
        audio_silences: List[Tuple[float, float]],
        audio_energy: Optional[List[float]] = None
    ) -> List[CutPoint]:
        """
        Find all narrative-appropriate cut points
        
        Args:
            transcript: Full text
            words_with_timestamps: [{word, start, end, probability}]
            audio_silences: [(start, end), ...] silent periods
            audio_energy: RMS energy values per time window
            
        Returns:
            List of CutPoint sorted by confidence
        """
        cuts = []
        
        # 1. Detect silences > 0.5s as natural pause points
        for silence_start, silence_end in audio_silences:
            duration = silence_end - silence_start
            if duration >= self.min_silence_duration:
                confidence = min(0.95, 0.7 + duration * 0.1)  # Longer = more confident
                cuts.append(CutPoint(
                    timestamp=silence_start,
                    confidence=confidence,
                    reason="dramatic_pause",
                    suggested_transition="jump_cut" if duration < 1.0 else "fade"
                ))
        
        # 2. Detect hesitation markers
        for word_info in words_with_timestamps:
            word_lower = word_info.get("word", "").lower().strip()
            if word_lower in HESITATION_MARKERS:
                cuts.append(CutPoint(
                    timestamp=word_info.get("end", 0),
                    confidence=0.75,
                    reason="hesitation_marker",
                    suggested_transition="broll"  # Cover the "um" with B-roll
                ))
        
        # 3. Detect topic changes using embeddings
        topic_cuts = self._detect_topic_changes(words_with_timestamps)
        cuts.extend(topic_cuts)
        
        # 4. Detect energy drops
        if audio_energy:
            energy_cuts = self._detect_energy_drops(audio_energy, words_with_timestamps)
            cuts.extend(energy_cuts)
        
        # Sort by confidence and remove duplicates (within 1s)
        cuts.sort(key=lambda x: x.confidence, reverse=True)
        filtered_cuts = self._remove_duplicate_cuts(cuts, min_distance=1.0)
        
        return sorted(filtered_cuts, key=lambda x: x.timestamp)
    
    def _detect_topic_changes(self, words: List[Dict]) -> List[CutPoint]:
        """Detect where topic shifts using sentence embeddings"""
        self._load_embeddings()
        if not self.sentence_transformers or len(words) < 10:
            return []
        
        cuts = []
        model = self.sentence_transformers['model']
        util = self.sentence_transformers['util']
        
        # Group words into sentence windows (5-word windows, step 3)
        window_size = 5
        step = 3
        
        for i in range(0, len(words) - window_size, step):
            # Get two consecutive windows
            window1_words = words[i:i+window_size]
            window2_words = words[i+step:i+step+window_size]
            
            text1 = " ".join([w.get("word", "") for w in window1_words])
            text2 = " ".join([w.get("word", "") for w in window2_words])
            
            # Compare semantic similarity
            emb1 = model.encode(text1)
            emb2 = model.encode(text2)
            similarity = util.cos_sim(emb1, emb2).item()
            
            # Low similarity = topic change
            if similarity < 0.6:
                cut_time = window1_words[-1].get("end", 0)
                cuts.append(CutPoint(
                    timestamp=cut_time,
                    confidence=0.8 - similarity,  # Lower similarity = higher confidence
                    reason="topic_change",
                    suggested_transition="broll"
                ))
        
        return cuts
    
    def _detect_energy_drops(
        self,
        energy: List[float],
        words: List[Dict]
    ) -> List[CutPoint]:
        """Detect energy drops as natural cut points"""
        cuts = []
        
        # Find drops below 30th percentile
        threshold = np.percentile(energy, 30)
        
        for i, e in enumerate(energy):
            if e < threshold:
                # Map to timestamp
                time_idx = int(i * len(words) / len(energy))
                if time_idx < len(words):
                    timestamp = words[time_idx].get("start", 0)
                    cuts.append(CutPoint(
                        timestamp=timestamp,
                        confidence=0.6,
                        reason="energy_drop",
                        suggested_transition="fade"
                    ))
        
        return cuts
    
    def _remove_duplicate_cuts(
        self,
        cuts: List[CutPoint],
        min_distance: float = 1.0
    ) -> List[CutPoint]:
        """Remove cut points that are too close to each other"""
        if not cuts:
            return []
        
        # Sort by timestamp
        sorted_cuts = sorted(cuts, key=lambda x: x.timestamp)
        
        filtered = [sorted_cuts[0]]
        for cut in sorted_cuts[1:]:
            if cut.timestamp - filtered[-1].timestamp >= min_distance:
                filtered.append(cut)
        
        return filtered
    
    def find_best_continuation(
        self,
        current_segment_end: float,
        available_segments: List[Dict],
        max_gap: float = 30.0
    ) -> Optional[Dict]:
        """
        Find the best segment to continue the narrative after a cut
        
        Args:
            current_segment_end: Timestamp where we cut
            available_segments: Other viral segments to choose from
            max_gap: Maximum time gap to consider
            
        Returns:
            Best continuation segment or None
        """
        candidates = []
        
        for seg in available_segments:
            seg_start = seg.get("start", 0)
            gap = seg_start - current_segment_end
            
            # Skip segments before current or too far ahead
            if gap < 0 or gap > max_gap:
                continue
            
            # Score based on:
            # - Small gap (seamless continuation)
            # - High virality score
            # - Topic coherence (would need embeddings)
            
            gap_score = max(0, 1.0 - gap / max_gap)  # Closer = higher
            virality_score = seg.get("virality_score", 50) / 100
            
            total_score = gap_score * 0.4 + virality_score * 0.6
            
            candidates.append((seg, total_score))
        
        if not candidates:
            return None
        
        # Return best match
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]
    
    def create_narrative_segments(
        self,
        raw_segments: List[Dict],
        cut_points: List[CutPoint]
    ) -> List[NarrativeSegment]:
        """
        Transform raw segments into narrative-aware segments with internal cuts
        """
        narrative_segments = []
        
        for seg in raw_segments:
            seg_start = seg.get("start", 0)
            seg_end = seg.get("end", 0)
            
            # Find cuts within this segment
            internal_cuts = [
                cut for cut in cut_points
                if seg_start <= cut.timestamp <= seg_end
            ]
            
            # Determine best exit point
            if internal_cuts:
                # Use last high-confidence cut
                best_exit = max(
                    [cut.timestamp for cut in internal_cuts if cut.confidence > 0.75],
                    default=seg_end
                )
            else:
                best_exit = seg_end
            
            narrative_segments.append(NarrativeSegment(
                start=seg_start,
                end=seg_end,
                text=seg.get("text", ""),
                internal_cuts=internal_cuts,
                best_exit_point=best_exit,
                best_entry_point=seg_start
            ))
        
        return narrative_segments


def detect_hesitations(text: str) -> List[Tuple[int, str]]:
    """Find hesitation markers in text with positions"""
    text_lower = text.lower()
    found = []
    
    for marker in HESITATION_MARKERS:
        idx = text_lower.find(marker)
        while idx != -1:
            found.append((idx, marker))
            idx = text_lower.find(marker, idx + 1)
    
    return sorted(found, key=lambda x: x[0])
