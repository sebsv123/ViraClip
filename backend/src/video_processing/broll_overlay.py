"""
Professional B-Roll Overlay System — Phase 2

Cinematic B-roll insertion with:
- FFmpeg overlay with fade in/out
- Discard B-roll audio (preserve original audio)
- Smooth transitions between main video and B-roll
- Automatic aspect ratio fitting
"""

import json
import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Any

logger = logging.getLogger(__name__)


@dataclass
class BRollDecision:
    """Decision for B-roll insertion at a specific timestamp."""
    keyword: str                    # Search keyword / visual theme
    timestamp: float               # When to insert (seconds from clip start)
    duration: float                # How long to show (2-5 seconds)
    context: str                   # What's being discussed
    confidence: float              # AI confidence score (0.0-1.0)
    broll_path: Optional[Path] = None  # Local path to B-roll asset
    fade_in: float = 0.5           # Fade-in duration (seconds)
    fade_out: float = 0.5          # Fade-out duration (seconds)
    
    def __post_init__(self):
        # Clamp duration to valid range
        if self.duration < 2.0:
            self.duration = 2.0
        elif self.duration > 5.0:
            self.duration = 5.0
        # Clamp fade times
        self.fade_in = min(self.fade_in, self.duration * 0.3)
        self.fade_out = min(self.fade_out, self.duration * 0.3)


class BRollOverlayEngine:
    """
    Professional B-roll overlay using FFmpeg.
    
    Features:
    - Preserves original audio (B-roll video is muted)
    - Smooth fade transitions
    - Automatic scale/aspect ratio correction
    - Support for video and image B-roll
    """
    
    def __init__(
        self,
        broll_library_path: Optional[Path] = None,
        output_resolution: Tuple[int, int] = (1080, 1920),  # 9:16 vertical
    ):
        self.resolution = output_resolution
        self.broll_library = broll_library_path or Path("/backend/music/broll")
        
    def compose_overlay(
        self,
        main_video: Path,
        broll_video: Path,
        output_path: Path,
        start_time: float,
        duration: float,
        fade_in: float = 0.5,
        fade_out: float = 0.5,
    ) -> bool:
        """
        Insert B-roll over main video using FFmpeg with smooth fades.
        
        The B-roll video replaces the visual content during the insertion period,
        but the original audio from the main video is preserved.
        
        Args:
            main_video: Path to main video clip
            broll_video: Path to B-roll asset (video or image)
            output_path: Where to save result
            start_time: When to start overlay (seconds)
            duration: How long to show B-roll (seconds)
            fade_in: Fade-in duration (seconds)
            fade_out: Fade-out duration (seconds)
        
        Returns:
            True on success, False on failure
        """
        try:
            # Build FFmpeg filter complex for overlay with fades
            filter_complex = self._build_overlay_filter(
                start_time, duration, fade_in, fade_out
            )
            
            cmd = [
                "ffmpeg", "-y",
                # Main video input
                "-i", str(main_video),
                # B-roll input (loop if needed)
                "-stream_loop", "-1", "-i", str(broll_video),
                # Filter complex
                "-filter_complex", filter_complex,
                # Map video output
                "-map", "[vout]",
                # Map original audio from main video (B-roll is muted)
                "-map", "0:a",
                # Encode settings
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "192k",
                "-movflags", "+faststart",
                str(output_path)
            ]
            
            logger.info(f"[B-Roll] Composing overlay: {broll_video.name} at t={start_time:.2f}s, dur={duration:.2f}s")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minutes timeout
            )
            
            if result.returncode != 0:
                logger.error(f"[B-Roll] FFmpeg overlay failed: {result.stderr[-400:]}")
                return False
            
            # Verify output
            if not output_path.exists() or output_path.stat().st_size == 0:
                logger.error("[B-Roll] Output file is empty or missing")
                return False
            
            logger.info(f"✅ [B-Roll] Overlay complete: {output_path.name}")
            return True
            
        except subprocess.TimeoutExpired:
            logger.error("[B-Roll] FFmpeg timeout (300s)")
            return False
        except Exception as e:
            logger.error(f"[B-Roll] Overlay error: {e}")
            return False
    
    def _build_overlay_filter(
        self,
        start_time: float,
        duration: float,
        fade_in: float,
        fade_out: float,
    ) -> str:
        """
        Build FFmpeg filter complex for smooth B-roll overlay.
        
        Timeline:
        0           start_time              start+dur           video_end
        |               |                       |                   |
        [main only] [crossfade begin] [B-roll full] [crossfade end] [main only]
        
        The filter uses fade and overlay to smoothly transition.
        """
        end_time = start_time + duration
        
        # Resolution
        width, height = self.resolution
        
        # Scale B-roll to match output resolution (cover mode)
        # This ensures B-roll fills the frame regardless of source aspect ratio
        filter_chain = (
            # Scale main video to target resolution
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1[main];"
            
            # Scale B-roll to target resolution (zoom/crop to fill)
            f"[1:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,format=yuv420p,"
            
            # Apply fade in/out to B-roll
            f"fade=t=in:st=0:d={fade_in}:alpha=1,"
            f"fade=t=out:st={duration-fade_out}:d={fade_out}:alpha=1[broll];"
            
            # Trim B-roll to exact duration needed
            f"[broll]trim=duration={duration},setpts=PTS-STARTPTS[broll_trim];"
            
            # Build the overlay using timeline:
            # Before start_time: show only main
            # During B-roll: overlay B-roll on main with transparency
            # After end: show only main
            f"[main][broll_trim]overlay=0:0:enable='between(t,{start_time},{end_time})':format=auto[vout]"
        )
        
        return filter_chain
    
    def find_broll_asset(
        self,
        keyword: str,
        preferred_duration: float = 3.0,
    ) -> Optional[Path]:
        """
        Find B-roll asset in local library.
        
        Lookup order:
        1. Exact keyword match in broll_library/{keyword}/
        2. Category match (keyword mapped to category)
        3. Generic fallback
        
        Args:
            keyword: Search keyword (e.g., "office", "nature", "city")
            preferred_duration: Minimum duration needed
        
        Returns:
            Path to B-roll asset or None if not found
        """
        if not self.broll_library.exists():
            logger.debug(f"[B-Roll] Library not found: {self.broll_library}")
            return None
        
        # 1. Exact keyword folder
        keyword_dir = self.broll_library / keyword.lower().replace(" ", "_")
        if keyword_dir.exists():
            asset = self._pick_asset_from_dir(keyword_dir, preferred_duration)
            if asset:
                return asset
        
        # 2. Category mapping
        category = self._keyword_to_category(keyword)
        if category:
            cat_dir = self.broll_library / category
            if cat_dir.exists():
                asset = self._pick_asset_from_dir(cat_dir, preferred_duration)
                if asset:
                    return asset
        
        # 3. Generic fallback
        generic_dir = self.broll_library / "generic"
        if generic_dir.exists():
            asset = self._pick_asset_from_dir(generic_dir, preferred_duration)
            if asset:
                return asset
        
        logger.debug(f"[B-Roll] No local asset for '{keyword}'")
        return None
    
    def _keyword_to_category(self, keyword: str) -> Optional[str]:
        """Map keyword to category folder name."""
        keyword_lower = keyword.lower()
        
        category_map = {
            # Business
            "office": "business", "meeting": "business", "startup": "business",
            "entrepreneur": "business", "business": "business", "work": "business",
            # Tech
            "computer": "tech", "laptop": "tech", "phone": "tech",
            "code": "tech", "software": "tech", "data": "tech", "tech": "tech",
            # Finance
            "money": "finance", "stock": "finance", "crypto": "finance",
            "bitcoin": "finance", "invest": "finance", "finance": "finance",
            # Nature
            "nature": "nature", "forest": "nature", "ocean": "nature",
            "mountain": "nature", "sky": "nature", "sunset": "nature",
            # City
            "city": "city", "urban": "city", "street": "city", "building": "city",
            # People
            "person": "people", "people": "people", "crowd": "people", "audience": "people",
            # Health
            "health": "health", "fitness": "health", "wellness": "health",
            # Sport
            "workout": "sport", "gym": "sport", "sport": "sport", "athlete": "sport",
            # Travel
            "travel": "travel", "flight": "travel", "airport": "travel", "hotel": "travel",
            # Food
            "food": "food", "cook": "food", "restaurant": "food", "coffee": "food",
            # Abstract/Motivation
            "abstract": "abstract", "motivat": "motivation", "success": "motivation",
            "inspire": "motivation",
        }
        
        for key, cat in category_map.items():
            if key in keyword_lower:
                return cat
        
        return None
    
    def _pick_asset_from_dir(
        self,
        directory: Path,
        min_duration: float,
    ) -> Optional[Path]:
        """Pick a suitable asset from directory."""
        import random
        
        # Supported formats
        video_exts = {".mp4", ".mov", ".webm", ".mkv"}
        image_exts = {".jpg", ".jpeg", ".png", ".webp"}
        
        # Get all assets
        assets = []
        for ext in video_exts | image_exts:
            assets.extend(directory.glob(f"*{ext}"))
        
        if not assets:
            return None
        
        # For videos, check duration
        valid_assets = []
        for asset in assets:
            if asset.suffix.lower() in video_exts:
                duration = self._probe_duration(asset)
                if duration and duration >= min_duration:
                    valid_assets.append(asset)
            else:
                # Images are always valid (will be shown as still)
                valid_assets.append(asset)
        
        if valid_assets:
            return random.choice(valid_assets)
        
        return None
    
    def _probe_duration(self, video_path: Path) -> Optional[float]:
        """Probe video duration using ffprobe."""
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return float(result.stdout.strip())
        except Exception:
            pass
        return None


class BRollDecisionEngine:
    """
    AI-driven B-roll decision engine.
    
    Analyzes segment content and decides where and when to insert B-roll
    based on contextual relevance and cinematic timing.
    """
    
    # Strict rules for B-roll decisions
    STRICT_RULES = {
        "min_segment_duration": 10.0,      # Don't B-roll very short segments
        "max_broll_per_segment": 2,        # Max 2 B-roll insertions per clip
        "min_gap_between_broll": 4.0,      # Minimum 4 seconds between B-rolls
        "fade_duration": 0.5,              # Standard fade in/out
        "broll_duration_range": (2.0, 4.0),  # B-roll duration min/max
    }
    
    def __init__(self):
        self.decisions: List[BRollDecision] = []
    
    def analyze_segment(
        self,
        segment_text: str,
        segment_start: float,
        segment_duration: float,
        keywords: List[str],
        confidence_threshold: float = 0.6,
    ) -> List[BRollDecision]:
        """
        Analyze a video segment and generate B-roll decisions.
        
        Args:
            segment_text: Transcript text of the segment
            segment_start: Start time in full video (seconds)
            segment_duration: Duration of segment (seconds)
            keywords: Extracted visual keywords from the segment
            confidence_threshold: Minimum confidence for a decision
        
        Returns:
            List of BRollDecision objects
        """
        decisions = []
        
        # Rule: Skip very short segments
        if segment_duration < self.STRICT_RULES["min_segment_duration"]:
            logger.debug(f"[B-Roll] Segment too short ({segment_duration:.1f}s) — skipping")
            return decisions
        
        # Rule: Max 2 B-roll per segment
        max_broll = min(len(keywords), self.STRICT_RULES["max_broll_per_segment"])
        
        # Calculate insertion points
        # Strategy: First keyword early in segment, second keyword later
        min_gap = self.STRICT_RULES["min_gap_between_broll"]
        
        for i, keyword in enumerate(keywords[:max_broll]):
            # Determine insertion timing
            if i == 0:
                # First B-roll: around 1/3 into segment (after hook)
                relative_time = segment_duration * 0.33
            else:
                # Second B-roll: around 2/3 into segment
                relative_time = segment_duration * 0.67
            
            # Check gap from previous decision
            absolute_time = segment_start + relative_time
            if decisions:
                last_end = decisions[-1].timestamp + decisions[-1].duration
                if absolute_time - last_end < min_gap:
                    # Too close to previous B-roll, skip
                    continue
            
            # Duration: random between 2-4 seconds
            import random
            duration = random.uniform(
                self.STRICT_RULES["broll_duration_range"][0],
                self.STRICT_RULES["broll_duration_range"][1]
            )
            
            # Check B-roll doesn't extend past segment end
            if relative_time + duration > segment_duration:
                duration = segment_duration - relative_time - 0.5
                if duration < 2.0:
                    continue  # Too short, skip
            
            # Create decision
            decision = BRollDecision(
                keyword=keyword,
                timestamp=absolute_time,
                duration=duration,
                context=segment_text[:100],  # First 100 chars as context
                confidence=0.75,  # Default confidence
                fade_in=self.STRICT_RULES["fade_duration"],
                fade_out=self.STRICT_RULES["fade_duration"],
            )
            
            decisions.append(decision)
            logger.info(f"[B-Roll] Decision: '{keyword}' at t={absolute_time:.2f}s, dur={duration:.1f}s")
        
        return decisions
    
    def fetch_assets_for_decisions(
        self,
        decisions: List[BRollDecision],
        overlay_engine: BRollOverlayEngine,
        fallback_to_api: bool = True,
    ) -> List[BRollDecision]:
        """
        Fetch B-roll assets for all decisions.
        
        Updates decisions in-place with broll_path when found.
        
        Args:
            decisions: List of BRollDecision objects
            overlay_engine: BRollOverlayEngine instance
            fallback_to_api: If True, fetch from Pexels API if local not found
        
        Returns:
            List of decisions with broll_path populated (may be filtered)
        """
        from ..broll import search_broll_videos, get_best_broll_video
        
        valid_decisions = []
        
        for decision in decisions:
            # Try local library first
            local_asset = overlay_engine.find_broll_asset(
                decision.keyword,
                decision.duration
            )
            
            if local_asset:
                decision.broll_path = local_asset
                valid_decisions.append(decision)
                logger.info(f"[B-Roll] Local asset: {local_asset.name}")
                continue
            
            # Fallback to API if enabled
            if fallback_to_api:
                try:
                    import asyncio
                    videos = asyncio.run(search_broll_videos(decision.keyword, per_page=3))
                    if videos:
                        best = get_best_broll_video(decision.keyword, decision.duration)
                        if best:
                            # Download would happen here - for now just log
                            logger.info(f"[B-Roll] API candidate for '{decision.keyword}'")
                            # In production, download and set path
                            # decision.broll_path = downloaded_path
                            # valid_decisions.append(decision)
                except Exception as e:
                    logger.debug(f"[B-Roll] API fetch failed: {e}")
            
            if not decision.broll_path:
                logger.warning(f"[B-Roll] No asset found for '{decision.keyword}'")
        
        return valid_decisions


def insert_broll_into_clip(
    clip_path: Path,
    decisions: List[BRollDecision],
    output_path: Path,
    resolution: Tuple[int, int] = (1080, 1920),
) -> bool:
    """
    High-level function to insert multiple B-rolls into a clip.
    
    Args:
        clip_path: Source video clip
        decisions: List of BRollDecision with broll_path populated
        output_path: Where to save result
        resolution: Output resolution (width, height)
    
    Returns:
        True on success, False on failure
    """
    if not decisions:
        logger.info("[B-Roll] No decisions — copying clip without changes")
        import shutil
        shutil.copy(clip_path, output_path)
        return True
    
    # Filter decisions that have assets
    valid_decisions = [d for d in decisions if d.broll_path]
    
    if not valid_decisions:
        logger.warning("[B-Roll] No valid assets — copying clip without changes")
        import shutil
        shutil.copy(clip_path, output_path)
        return True
    
    # For now, process sequentially (each B-roll overlay becomes the new base)
    # In production, this could be optimized to single FFmpeg command with complex timeline
    current_video = clip_path
    
    for i, decision in enumerate(valid_decisions):
        if i == len(valid_decisions) - 1:
            # Last iteration: output to final destination
            temp_output = output_path
        else:
            # Intermediate: use temp file
            temp_output = Path(tempfile.mktemp(suffix=".mp4"))
        
        engine = BRollOverlayEngine(output_resolution=resolution)
        success = engine.compose_overlay(
            main_video=current_video,
            broll_video=decision.broll_path,
            output_path=temp_output,
            start_time=decision.timestamp,
            duration=decision.duration,
            fade_in=decision.fade_in,
            fade_out=decision.fade_out,
        )
        
        if not success:
            logger.error(f"[B-Roll] Failed to insert '{decision.keyword}'")
            if i > 0 and current_video != clip_path:
                # Clean up temp file
                try:
                    current_video.unlink()
                except:
                    pass
            return False
        
        # Update current video for next iteration
        if i > 0 and current_video != clip_path:
            try:
                current_video.unlink()
            except:
                pass
        current_video = temp_output
    
    logger.info(f"✅ [B-Roll] All {len(valid_decisions)} B-rolls inserted into {output_path.name}")
    return True
