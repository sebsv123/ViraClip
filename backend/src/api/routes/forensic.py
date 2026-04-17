"""
Forensic Analysis API — ViraClip

Endpoints for deepfake detection, video authenticity verification,
frame consistency checks, and forensic batch analysis.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.forensic_analysis import (
    AuthenticityStatus,
    ForensicCheckType,
    ForensicAnalysisService,
    get_forensic_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/forensic", tags=["forensic"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class AnalyzeVideoRequest(BaseModel):
    video_id: str
    video_path: str
    checks: Optional[List[str]] = None     # subset of ForensicCheckType values


class VerifyRequest(BaseModel):
    video_id: str
    claimed_hash: Optional[str] = None


class BatchAnalyzeRequest(BaseModel):
    videos: List[Dict[str, str]]    # [{video_id, path}]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_checks(values: Optional[List[str]]) -> Optional[List[ForensicCheckType]]:
    if not values:
        return None
    valid = {c.value: c for c in ForensicCheckType}
    result = []
    for v in values:
        if v not in valid:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown check '{v}'. Valid: {list(valid.keys())}",
            )
        result.append(valid[v])
    return result


def _fmt_report(report) -> Dict[str, Any]:
    return {
        "video_id": report.video_id,
        "overall_status": report.overall_status.value,
        "trust_score": round(report.trust_score, 1),
        "file_hash": report.file_hash,
        "metadata": report.metadata,
        "forensic_checks": [
            {
                "check_type": c.check_type.value,
                "score": round(c.score, 3),
                "confidence": round(c.confidence, 3),
                "passed": c.passed,
                "details": c.details,
                "evidence": c.evidence,
            }
            for c in report.forensic_checks
        ],
        "created_at": report.created_at,
        "analyzed_at": report.analyzed_at,
    }


# ------------------------------------------------------------------
# Single-video analysis
# ------------------------------------------------------------------

@router.post("/analyze")
async def analyze_video(body: AnalyzeVideoRequest):
    """
    Perform a comprehensive forensic analysis on a video file.

    Runs up to 6 checks:
    - `deepfake` — AI-based deepfake detection
    - `frame_consistency` — frame-level quality / resolution changes
    - `audio_sync` — lip-sync / audio-video correlation
    - `metadata_integrity` — encoder and timestamp metadata
    - `watermark` — visible and steganographic watermarks
    - `face_manipulation` — face-swap / expression tampering

    Pass `checks` to run a subset; omit for all.
    """
    checks = _parse_checks(body.checks)
    video_path = Path(body.video_path)

    svc = get_forensic_service()
    try:
        report = await svc.analyze_video(body.video_id, video_path, checks)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "analyzed", "report": _fmt_report(report)}


@router.get("/{video_id}")
def get_report(video_id: str):
    """Retrieve a previously computed forensic report from the in-memory cache."""
    svc = get_forensic_service()
    report = svc.get_analysis_report(video_id)
    if report is None:
        raise HTTPException(
            status_code=404,
            detail=f"No forensic report found for video '{video_id}'. Run POST /forensic/analyze first.",
        )
    return {"status": "success", "report": _fmt_report(report)}


@router.post("/verify")
async def verify_authenticity(body: VerifyRequest):
    """
    Verify a video's authenticity against its stored forensic report.
    Optionally supply `claimed_hash` (SHA-256) to confirm file integrity.
    """
    svc = get_forensic_service()
    result = await svc.verify_authenticity(body.video_id, body.claimed_hash)

    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return {"status": "success", "verification": result}


# ------------------------------------------------------------------
# Batch analysis
# ------------------------------------------------------------------

@router.post("/batch")
async def batch_analyze(body: BatchAnalyzeRequest):
    """
    Analyze multiple videos in a single call.
    Each item must contain `video_id` and `path`.
    Videos that fail (e.g. file not found) are skipped and logged.
    """
    if not body.videos:
        raise HTTPException(status_code=400, detail="videos must not be empty")

    svc = get_forensic_service()
    try:
        reports = await svc.batch_analyze(body.videos)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "analyzed",
        "count": len(reports),
        "reports": [_fmt_report(r) for r in reports],
    }


# ------------------------------------------------------------------
# Stats & metadata
# ------------------------------------------------------------------

@router.get("/stats/overview")
def get_stats():
    """Platform-wide forensic stats: total analyzed, status breakdown, avg trust score."""
    svc = get_forensic_service()
    return {"status": "success", "stats": svc.get_forensic_stats()}


@router.get("/checks/list")
def list_checks():
    """List all available forensic check types."""
    return {
        "checks": [c.value for c in ForensicCheckType],
        "statuses": [s.value for s in AuthenticityStatus],
    }
