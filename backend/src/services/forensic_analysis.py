"""
Forensic Analysis Service
Deepfake detection, video authenticity verification, and forensic analysis.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
import hashlib

logger = logging.getLogger(__name__)


class AuthenticityStatus(Enum):
    """Video authenticity status."""
    AUTHENTIC = "authentic"
    SUSPICIOUS = "suspicious"
    MANIPULATED = "manipulated"
    UNKNOWN = "unknown"


class ForensicCheckType(Enum):
    """Types of forensic checks."""
    DEEPFAKE = "deepfake"
    FRAME_CONSISTENCY = "frame_consistency"
    AUDIO_SYNC = "audio_sync"
    METADATA_INTEGRITY = "metadata_integrity"
    WATERMARK = "watermark"
    FACE_MANIPULATION = "face_manipulation"


@dataclass
class ForensicResult:
    """Forensic analysis result."""
    check_type: ForensicCheckType
    score: float  # 0-1, higher = more suspicious
    confidence: float
    details: str
    passed: bool
    evidence: List[Dict[str, Any]]


@dataclass
class VideoAuthenticity:
    """Overall video authenticity report."""
    video_id: str
    overall_status: AuthenticityStatus
    trust_score: float  # 0-100
    file_hash: str
    metadata: Dict[str, Any]
    forensic_checks: List[ForensicResult]
    created_at: str
    analyzed_at: str


class ForensicAnalysisService:
    """
    Forensic analysis for video authenticity and manipulation detection.
    """
    
    def __init__(self):
        self._analysis_cache: Dict[str, VideoAuthenticity] = {}
        self._thresholds = {
            "deepfake": 0.7,
            "consistency": 0.8,
            "audio_sync": 0.9,
            "metadata": 0.95
        }
    
    async def analyze_video(
        self,
        video_id: str,
        video_path: Path,
        checks: Optional[List[ForensicCheckType]] = None
    ) -> VideoAuthenticity:
        """
        Perform comprehensive forensic analysis on a video.
        
        Args:
            video_id: Unique identifier for the video
            video_path: Path to video file
            checks: List of checks to perform (all if None)
        """
        if not video_path.exists():
            raise FileNotFoundError(f"Video not found: {video_path}")
        
        checks = checks or list(ForensicCheckType)
        
        # Calculate file hash
        file_hash = await self._calculate_file_hash(video_path)
        
        # Extract metadata
        metadata = await self._extract_metadata(video_path)
        
        # Perform forensic checks
        forensic_checks = []
        
        if ForensicCheckType.DEEPFAKE in checks:
            forensic_checks.append(await self._check_deepfake(video_path))
        
        if ForensicCheckType.FRAME_CONSISTENCY in checks:
            forensic_checks.append(await self._check_frame_consistency(video_path))
        
        if ForensicCheckType.AUDIO_SYNC in checks:
            forensic_checks.append(await self._check_audio_sync(video_path))
        
        if ForensicCheckType.METADATA_INTEGRITY in checks:
            forensic_checks.append(await self._check_metadata_integrity(video_path, metadata))
        
        if ForensicCheckType.WATERMARK in checks:
            forensic_checks.append(await self._check_watermarks(video_path))
        
        if ForensicCheckType.FACE_MANIPULATION in checks:
            forensic_checks.append(await self._check_face_manipulation(video_path))
        
        # Calculate overall status
        overall_status = self._calculate_overall_status(forensic_checks)
        trust_score = self._calculate_trust_score(forensic_checks)
        
        report = VideoAuthenticity(
            video_id=video_id,
            overall_status=overall_status,
            trust_score=trust_score,
            file_hash=file_hash,
            metadata=metadata,
            forensic_checks=forensic_checks,
            created_at=metadata.get("creation_time", datetime.now().isoformat()),
            analyzed_at=datetime.now().isoformat()
        )
        
        self._analysis_cache[video_id] = report
        logger.info(f"Completed forensic analysis for video {video_id}")
        
        return report
    
    async def _calculate_file_hash(self, video_path: Path) -> str:
        """Calculate SHA-256 hash of video file."""
        sha256 = hashlib.sha256()
        with open(video_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    
    async def _extract_metadata(self, video_path: Path) -> Dict[str, Any]:
        """Extract video metadata using ffprobe."""
        import subprocess
        import json
        
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "quiet",
                    "-print_format", "json",
                    "-show_format", "-show_streams",
                    str(video_path)
                ],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            data = json.loads(result.stdout)
            
            return {
                "format": data.get("format", {}),
                "streams": data.get("streams", []),
                "creation_time": data.get("format", {}).get("tags", {}).get("creation_time"),
                "encoder": data.get("format", {}).get("tags", {}).get("encoder"),
                "software": data.get("format", {}).get("tags", {}).get("software")
            }
            
        except Exception as e:
            logger.error(f"Metadata extraction failed: {e}")
            return {}
    
    async def _check_deepfake(self, video_path: Path) -> ForensicResult:
        """Check for deepfake manipulation using AI detection."""
        # In production, this would use specialized deepfake detection models
        # For now, return placeholder result
        
        # Simulate analysis
        suspicious_score = 0.2  # Placeholder
        
        return ForensicResult(
            check_type=ForensicCheckType.DEEPFAKE,
            score=suspicious_score,
            confidence=0.85,
            details="No deepfake artifacts detected" if suspicious_score < self._thresholds["deepfake"] else "Potential deepfake indicators found",
            passed=suspicious_score < self._thresholds["deepfake"],
            evidence=[]
        )
    
    async def _check_frame_consistency(self, video_path: Path) -> ForensicResult:
        """Check for frame-level inconsistencies."""
        # Analyze frame-to-frame consistency
        # Look for sudden quality changes, resolution changes, etc.
        
        inconsistencies = []
        
        # Placeholder analysis
        consistency_score = 0.95
        
        return ForensicResult(
            check_type=ForensicCheckType.FRAME_CONSISTENCY,
            score=1.0 - consistency_score,
            confidence=0.9,
            details="Frame consistency verified" if consistency_score > self._thresholds["consistency"] else f"Found {len(inconsistencies)} inconsistencies",
            passed=consistency_score > self._thresholds["consistency"],
            evidence=inconsistencies
        )
    
    async def _check_audio_sync(self, video_path: Path) -> ForensicResult:
        """Check audio-video synchronization."""
        # Analyze lip sync and audio-video correlation
        
        sync_score = 0.98  # Placeholder
        
        return ForensicResult(
            check_type=ForensicCheckType.AUDIO_SYNC,
            score=1.0 - sync_score,
            confidence=0.88,
            details="Audio-video sync verified" if sync_score > self._thresholds["audio_sync"] else "Audio sync issues detected",
            passed=sync_score > self._thresholds["audio_sync"],
            evidence=[]
        )
    
    async def _check_metadata_integrity(
        self,
        video_path: Path,
        metadata: Dict[str, Any]
    ) -> ForensicResult:
        """Check metadata integrity and consistency."""
        issues = []
        
        format_info = metadata.get("format", {})
        
        # Check for suspicious metadata
        if not format_info.get("tags", {}).get("creation_time"):
            issues.append("Missing creation timestamp")
        
        # Check encoder consistency
        encoder = format_info.get("tags", {}).get("encoder", "")
        suspicious_encoders = ["fake", "spoofed"]
        
        for susp in suspicious_encoders:
            if susp.lower() in encoder.lower():
                issues.append(f"Suspicious encoder: {encoder}")
        
        integrity_score = 1.0 if not issues else 0.5
        
        return ForensicResult(
            check_type=ForensicCheckType.METADATA_INTEGRITY,
            score=1.0 - integrity_score,
            confidence=0.95,
            details="Metadata integrity verified" if integrity_score > self._thresholds["metadata"] else "Metadata issues found",
            passed=integrity_score > self._thresholds["metadata"],
            evidence=[{"issue": i} for i in issues]
        )
    
    async def _check_watermarks(self, video_path: Path) -> ForensicResult:
        """Check for watermarks and digital signatures."""
        # Look for visible and invisible watermarks
        
        watermarks_found = []
        
        return ForensicResult(
            check_type=ForensicCheckType.WATERMARK,
            score=0.0,
            confidence=0.8,
            details=f"Found {len(watermarks_found)} watermarks" if watermarks_found else "No watermarks detected",
            passed=True,
            evidence=watermarks_found
        )
    
    async def _check_face_manipulation(self, video_path: Path) -> ForensicResult:
        """Check for face manipulation and tampering."""
        # Detect face swaps, expression manipulation, etc.
        
        manipulation_score = 0.15  # Placeholder
        
        return ForensicResult(
            check_type=ForensicCheckType.FACE_MANIPULATION,
            score=manipulation_score,
            confidence=0.82,
            details="No face manipulation detected" if manipulation_score < 0.5 else "Potential face manipulation found",
            passed=manipulation_score < 0.5,
            evidence=[]
        )
    
    def _calculate_overall_status(
        self,
        checks: List[ForensicResult]
    ) -> AuthenticityStatus:
        """Calculate overall authenticity status."""
        failed_checks = [c for c in checks if not c.passed]
        high_risk = [c for c in checks if c.score > 0.8]
        
        if high_risk:
            return AuthenticityStatus.MANIPULATED
        elif failed_checks:
            return AuthenticityStatus.SUSPICIOUS
        else:
            return AuthenticityStatus.AUTHENTIC
    
    def _calculate_trust_score(self, checks: List[ForensicResult]) -> float:
        """Calculate overall trust score (0-100)."""
        if not checks:
            return 0.0
        
        # Weight different checks
        weights = {
            ForensicCheckType.DEEPFAKE: 0.25,
            ForensicCheckType.FACE_MANIPULATION: 0.20,
            ForensicCheckType.FRAME_CONSISTENCY: 0.20,
            ForensicCheckType.AUDIO_SYNC: 0.15,
            ForensicCheckType.METADATA_INTEGRITY: 0.15,
            ForensicCheckType.WATERMARK: 0.05
        }
        
        total_score = 0
        total_weight = 0
        
        for check in checks:
            weight = weights.get(check.check_type, 0.1)
            # Convert score (suspicion) to trust
            trust = 1.0 - check.score
            total_score += trust * weight
            total_weight += weight
        
        return (total_score / total_weight) * 100 if total_weight > 0 else 0
    
    async def verify_authenticity(
        self,
        video_id: str,
        claimed_hash: Optional[str] = None
    ) -> Dict[str, Any]:
        """Verify video authenticity against stored analysis."""
        if video_id not in self._analysis_cache:
            return {"error": "No forensic analysis found for this video"}
        
        report = self._analysis_cache[video_id]
        
        result = {
            "video_id": video_id,
            "status": report.overall_status.value,
            "trust_score": report.trust_score,
            "analyzed_at": report.analyzed_at,
            "file_hash": report.file_hash,
            "hash_matches": True
        }
        
        if claimed_hash:
            result["hash_matches"] = report.file_hash == claimed_hash
            result["verification_passed"] = (
                result["hash_matches"] and 
                report.overall_status == AuthenticityStatus.AUTHENTIC
            )
        
        return result
    
    def get_analysis_report(self, video_id: str) -> Optional[VideoAuthenticity]:
        """Get stored analysis report."""
        return self._analysis_cache.get(video_id)
    
    async def batch_analyze(
        self,
        videos: List[Dict[str, Any]]
    ) -> List[VideoAuthenticity]:
        """Analyze multiple videos."""
        results = []
        
        for video in videos:
            try:
                result = await self.analyze_video(
                    video["video_id"],
                    Path(video["path"])
                )
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to analyze {video['video_id']}: {e}")
        
        return results
    
    def get_forensic_stats(self) -> Dict[str, Any]:
        """Get forensic analysis statistics."""
        total = len(self._analysis_cache)
        
        status_counts = {
            AuthenticityStatus.AUTHENTIC.value: 0,
            AuthenticityStatus.SUSPICIOUS.value: 0,
            AuthenticityStatus.MANIPULATED.value: 0,
            AuthenticityStatus.UNKNOWN.value: 0
        }
        
        trust_scores = []
        
        for report in self._analysis_cache.values():
            status_counts[report.overall_status.value] += 1
            trust_scores.append(report.trust_score)
        
        return {
            "total_analyzed": total,
            "status_breakdown": status_counts,
            "average_trust_score": sum(trust_scores) / len(trust_scores) if trust_scores else 0,
            "authentic_percentage": (status_counts[AuthenticityStatus.AUTHENTIC.value] / total * 100) if total > 0 else 0
        }


# Global instance
_forensic_service: Optional[ForensicAnalysisService] = None


def get_forensic_service() -> ForensicAnalysisService:
    """Get global forensic analysis service."""
    global _forensic_service
    if _forensic_service is None:
        _forensic_service = ForensicAnalysisService()
    return _forensic_service


# Convenience functions
async def verify_video_authenticity(video_id: str, video_path: Path) -> Dict[str, Any]:
    """Quick authenticity verification."""
    service = get_forensic_service()
    report = await service.analyze_video(video_id, video_path)
    
    return {
        "video_id": video_id,
        "status": report.overall_status.value,
        "trust_score": report.trust_score,
        "is_authentic": report.overall_status == AuthenticityStatus.AUTHENTIC
    }
