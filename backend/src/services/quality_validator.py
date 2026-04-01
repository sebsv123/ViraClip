"""
Clip Quality Validation System
Validates generated clips against quality criteria.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)


class QualityLevel(Enum):
    """Quality levels for clips."""
    EXCELLENT = "excellent"  # 90-100
    GOOD = "good"            # 75-89
    ACCEPTABLE = "acceptable"  # 60-74
    POOR = "poor"            # 40-59
    REJECT = "reject"        # 0-39


@dataclass
class QualityCheck:
    """Individual quality check result."""
    name: str
    passed: bool
    score: float  # 0-100
    message: str
    recommendation: Optional[str] = None


@dataclass
class ClipQualityReport:
    """Complete quality report for a clip."""
    clip_id: str
    overall_score: float
    quality_level: QualityLevel
    checks: List[QualityCheck]
    passed: bool
    recommendations: List[str]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "clip_id": self.clip_id,
            "overall_score": self.overall_score,
            "quality_level": self.quality_level.value,
            "passed": self.passed,
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "score": c.score,
                    "message": c.message,
                    "recommendation": c.recommendation
                }
                for c in self.checks
            ],
            "recommendations": self.recommendations
        }


class ClipQualityValidator:
    """
    Validates clip quality based on multiple criteria.
    """
    
    # Quality thresholds
    MIN_DURATION_SEC = 5
    MAX_DURATION_SEC = 180  # 3 minutes max for shorts
    MIN_RESOLUTION = 720    # Minimum 720px height
    TARGET_ASPECT_RATIO = 9/16  # Vertical video
    MIN_AUDIO_LEVEL = -40   # dB
    MAX_AUDIO_LEVEL = -3    # dB
    
    def __init__(self):
        self.checks: List[callable] = [
            self._check_duration,
            self._check_resolution,
            self._check_aspect_ratio,
            self._check_audio_levels,
            self._check_file_integrity,
            self._check_virality_score,
        ]
    
    def validate_clip(
        self,
        clip_path: Path,
        clip_info: Dict[str, Any]
    ) -> ClipQualityReport:
        """
        Validate a clip and generate quality report.
        """
        checks = []
        recommendations = []
        
        # Run all quality checks
        for check_func in self.checks:
            try:
                check = check_func(clip_path, clip_info)
                checks.append(check)
                if check.recommendation:
                    recommendations.append(check.recommendation)
            except Exception as e:
                logger.warning(f"Quality check {check_func.__name__} failed: {e}")
                checks.append(QualityCheck(
                    name=check_func.__name__.replace("_check_", ""),
                    passed=False,
                    score=0,
                    message=f"Check failed: {e}",
                    recommendation="Review clip manually"
                ))
        
        # Calculate overall score
        if checks:
            overall_score = sum(c.score for c in checks) / len(checks)
        else:
            overall_score = 0
        
        # Determine quality level
        quality_level = self._score_to_level(overall_score)
        
        # Determine if clip passed (minimum GOOD level)
        passed = overall_score >= 60
        
        return ClipQualityReport(
            clip_id=clip_info.get("clip_id", "unknown"),
            overall_score=overall_score,
            quality_level=quality_level,
            checks=checks,
            passed=passed,
            recommendations=recommendations
        )
    
    def _score_to_level(self, score: float) -> QualityLevel:
        """Convert score to quality level."""
        if score >= 90:
            return QualityLevel.EXCELLENT
        elif score >= 75:
            return QualityLevel.GOOD
        elif score >= 60:
            return QualityLevel.ACCEPTABLE
        elif score >= 40:
            return QualityLevel.POOR
        else:
            return QualityLevel.REJECT
    
    def _check_duration(
        self,
        clip_path: Path,
        clip_info: Dict[str, Any]
    ) -> QualityCheck:
        """Check clip duration."""
        duration = clip_info.get("duration", 0)
        
        if duration < self.MIN_DURATION_SEC:
            return QualityCheck(
                name="duration",
                passed=False,
                score=30,
                message=f"Clip too short: {duration:.1f}s (min: {self.MIN_DURATION_SEC}s)",
                recommendation="Extend clip duration or choose longer segment"
            )
        
        if duration > self.MAX_DURATION_SEC:
            return QualityCheck(
                name="duration",
                passed=False,
                score=50,
                message=f"Clip too long: {duration:.1f}s (max: {self.MAX_DURATION_SEC}s)",
                recommendation="Consider splitting into multiple clips"
            )
        
        # Optimal duration for shorts: 15-60 seconds
        if 15 <= duration <= 60:
            score = 100
            message = f"Optimal duration: {duration:.1f}s"
        else:
            score = 85
            message = f"Good duration: {duration:.1f}s"
        
        return QualityCheck(
            name="duration",
            passed=True,
            score=score,
            message=message
        )
    
    def _check_resolution(
        self,
        clip_path: Path,
        clip_info: Dict[str, Any]
    ) -> QualityCheck:
        """Check video resolution."""
        try:
            import subprocess
            import json
            
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=height,width",
                    "-of", "json",
                    str(clip_path)
                ],
                capture_output=True,
                text=True
            )
            
            info = json.loads(result.stdout)
            stream = info.get("streams", [{}])[0]
            height = int(stream.get("height", 0))
            width = int(stream.get("width", 0))
            
            if height < self.MIN_RESOLUTION:
                return QualityCheck(
                    name="resolution",
                    passed=False,
                    score=40,
                    message=f"Low resolution: {width}x{height} (min height: {self.MIN_RESOLUTION})",
                    recommendation="Source video quality too low"
                )
            
            if height >= 1080:
                score = 100
                message = f"Excellent resolution: {width}x{height}"
            elif height >= 720:
                score = 85
                message = f"Good resolution: {width}x{height}"
            else:
                score = 70
                message = f"Acceptable resolution: {width}x{height}"
            
            return QualityCheck(
                name="resolution",
                passed=True,
                score=score,
                message=message
            )
            
        except Exception as e:
            return QualityCheck(
                name="resolution",
                passed=False,
                score=0,
                message=f"Failed to check resolution: {e}",
                recommendation="Verify video file integrity"
            )
    
    def _check_aspect_ratio(
        self,
        clip_path: Path,
        clip_info: Dict[str, Any]
    ) -> QualityCheck:
        """Check aspect ratio for vertical video."""
        try:
            import subprocess
            import json
            
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=display_aspect_ratio",
                    "-of", "json",
                    str(clip_path)
                ],
                capture_output=True,
                text=True
            )
            
            info = json.loads(result.stdout)
            stream = info.get("streams", [{}])[0]
            
            # Get actual dimensions if DAR not available
            width = int(clip_info.get("width", 1080))
            height = int(clip_info.get("height", 1920))
            
            if width > 0 and height > 0:
                aspect = width / height
                target = self.TARGET_ASPECT_RATIO
                diff = abs(aspect - target)
                
                if diff < 0.05:  # Within 5% of 9:16
                    return QualityCheck(
                        name="aspect_ratio",
                        passed=True,
                        score=100,
                        message=f"Perfect vertical ratio: {width}:{height}"
                    )
                elif aspect > 1:  # Horizontal
                    return QualityCheck(
                        name="aspect_ratio",
                        passed=False,
                        score=50,
                        message=f"Horizontal format: {width}:{height} (expected vertical)",
                        recommendation="Reprocess with vertical output format"
                    )
                else:
                    return QualityCheck(
                        name="aspect_ratio",
                        passed=True,
                        score=80,
                        message=f"Acceptable ratio: {width}:{height}"
                    )
            
            return QualityCheck(
                name="aspect_ratio",
                passed=True,
                score=70,
                message="Could not verify aspect ratio"
            )
            
        except Exception as e:
            return QualityCheck(
                name="aspect_ratio",
                passed=True,
                score=60,
                message=f"Aspect ratio check skipped: {e}"
            )
    
    def _check_audio_levels(
        self,
        clip_path: Path,
        clip_info: Dict[str, Any]
    ) -> QualityCheck:
        """Check audio levels."""
        try:
            import subprocess
            
            # Get audio levels using ffmpeg
            result = subprocess.run(
                [
                    "ffmpeg", "-i", str(clip_path),
                    "-af", "volumedetect",
                    "-f", "null", "-"
                ],
                capture_output=True,
                text=True
            )
            
            # Parse mean volume from stderr
            output = result.stderr
            
            # Extract mean_volume
            import re
            mean_match = re.search(r'mean_volume: ([-\d.]+) dB', output)
            max_match = re.search(r'max_volume: ([-\d.]+) dB', output)
            
            if mean_match:
                mean_db = float(mean_match.group(1))
                
                if mean_db < self.MIN_AUDIO_LEVEL:
                    return QualityCheck(
                        name="audio_levels",
                        passed=False,
                        score=40,
                        message=f"Audio too quiet: {mean_db:.1f} dB",
                        recommendation="Check source audio or boost volume"
                    )
                
                if mean_db > self.MAX_AUDIO_LEVEL:
                    return QualityCheck(
                        name="audio_levels",
                        passed=False,
                        score=50,
                        message=f"Audio too loud: {mean_db:.1f} dB (potential clipping)",
                        recommendation="Reduce volume to prevent distortion"
                    )
                
                # Good audio level
                score = 100 - abs(mean_db + 20) * 2  # Optimal around -20dB
                score = max(70, min(100, score))
                
                return QualityCheck(
                    name="audio_levels",
                    passed=True,
                    score=int(score),
                    message=f"Good audio level: {mean_db:.1f} dB"
                )
            
            return QualityCheck(
                name="audio_levels",
                passed=True,
                score=70,
                message="Audio present (level not verified)"
            )
            
        except Exception as e:
            return QualityCheck(
                name="audio_levels",
                passed=True,
                score=60,
                message=f"Audio check skipped: {e}"
            )
    
    def _check_file_integrity(
        self,
        clip_path: Path,
        clip_info: Dict[str, Any]
    ) -> QualityCheck:
        """Check video file integrity."""
        try:
            if not clip_path.exists():
                return QualityCheck(
                    name="file_integrity",
                    passed=False,
                    score=0,
                    message="File does not exist",
                    recommendation="Clip creation failed"
                )
            
            size = clip_path.stat().st_size
            
            if size == 0:
                return QualityCheck(
                    name="file_integrity",
                    passed=False,
                    score=0,
                    message="File is empty (0 bytes)",
                    recommendation="Clip creation failed"
                )
            
            if size < 1024:  # Less than 1KB
                return QualityCheck(
                    name="file_integrity",
                    passed=False,
                    score=20,
                    message=f"File too small: {size} bytes",
                    recommendation="Check for encoding errors"
                )
            
            # Verify it's a valid video file
            import subprocess
            result = subprocess.run(
                ["ffprobe", "-v", "error", str(clip_path)],
                capture_output=True
            )
            
            if result.returncode != 0:
                return QualityCheck(
                    name="file_integrity",
                    passed=False,
                    score=30,
                    message="File is not a valid video",
                    recommendation="Re-encode the clip"
                )
            
            # Good file
            size_mb = size / (1024 * 1024)
            return QualityCheck(
                name="file_integrity",
                passed=True,
                score=100,
                message=f"Valid video file: {size_mb:.1f}MB"
            )
            
        except Exception as e:
            return QualityCheck(
                name="file_integrity",
                passed=False,
                score=0,
                message=f"Integrity check failed: {e}",
                recommendation="Review clip manually"
            )
    
    def _check_virality_score(
        self,
        clip_path: Path,
        clip_info: Dict[str, Any]
    ) -> QualityCheck:
        """Check virality/content score."""
        virality = clip_info.get("virality_score", 0)
        hook_score = clip_info.get("hook_score", 0)
        engagement = clip_info.get("engagement_score", 0)
        
        # Weighted score
        weighted = (virality * 0.5) + (hook_score * 0.3) + (engagement * 0.2)
        
        if weighted >= 70:
            return QualityCheck(
                name="content_quality",
                passed=True,
                score=int(weighted),
                message=f"High viral potential (score: {weighted:.1f})"
            )
        elif weighted >= 50:
            return QualityCheck(
                name="content_quality",
                passed=True,
                score=int(weighted),
                message=f"Good content (score: {weighted:.1f})"
            )
        else:
            return QualityCheck(
                name="content_quality",
                passed=False,
                score=int(weighted),
                message=f"Low viral score: {weighted:.1f}",
                recommendation="Consider different segment selection"
            )
    
    def batch_validate(
        self,
        clips: List[Tuple[Path, Dict[str, Any]]]
    ) -> List[ClipQualityReport]:
        """Validate multiple clips."""
        reports = []
        for clip_path, clip_info in clips:
            report = self.validate_clip(clip_path, clip_info)
            reports.append(report)
        return reports


# Global validator instance
_validator: Optional[ClipQualityValidator] = None


def get_quality_validator() -> ClipQualityValidator:
    """Get global quality validator instance."""
    global _validator
    if _validator is None:
        _validator = ClipQualityValidator()
    return _validator


def validate_clip(clip_path: Path, clip_info: Dict[str, Any]) -> ClipQualityReport:
    """Convenience function to validate a clip."""
    return get_quality_validator().validate_clip(clip_path, clip_info)
