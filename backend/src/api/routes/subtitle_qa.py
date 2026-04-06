"""Subtitle QA API — validate and auto-fix subtitle files."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import os

router = APIRouter(prefix="/subtitle-qa", tags=["Subtitle QA"])


class SubtitleQARequest(BaseModel):
    content: str                      # Raw ASS/SRT subtitle string
    apply_fixes: bool = True
    censor_profanity: bool = True
    add_emojis: bool = True


class SubtitleFileQARequest(BaseModel):
    file_path: str
    apply_fixes: bool = True
    censor_profanity: bool = True
    add_emojis: bool = True
    overwrite: bool = False


@router.post("/check")
def check_subtitle_content(req: SubtitleQARequest):
    """Run QA checks on raw subtitle string content."""
    from src.video_processing.subtitle_qa import run_subtitle_qa
    report = run_subtitle_qa(
        req.content,
        apply_fixes=req.apply_fixes,
        censor_profanity=req.censor_profanity,
        add_emojis=req.add_emojis,
    )
    return {
        "passed": report.passed,
        "summary": report.summary(),
        "total_segments": report.total_segments,
        "reading_speed_violations": report.reading_speed_violations,
        "profanity_found": report.profanity_found,
        "emojis_injected": report.emojis_injected,
        "issues": [
            {"index": i.index, "kind": i.kind,
             "severity": i.severity, "message": i.message}
            for i in report.issues
        ],
        "fixed_content": report.fixed_content if req.apply_fixes else None,
    }


@router.post("/check-file")
def check_subtitle_file(req: SubtitleFileQARequest):
    """Run QA checks on a subtitle file by path."""
    if not os.path.exists(req.file_path):
        raise HTTPException(status_code=404, detail="Subtitle file not found")
    from src.video_processing.subtitle_qa import run_subtitle_qa_on_file
    report = run_subtitle_qa_on_file(
        req.file_path,
        apply_fixes=req.apply_fixes,
        censor_profanity=req.censor_profanity,
        add_emojis=req.add_emojis,
        overwrite=req.overwrite,
    )
    return {
        "passed": report.passed,
        "summary": report.summary(),
        "file_path": req.file_path,
        "overwritten": req.overwrite and req.apply_fixes,
        "total_segments": report.total_segments,
        "reading_speed_violations": report.reading_speed_violations,
        "profanity_found": report.profanity_found,
        "emojis_injected": report.emojis_injected,
        "issues": [
            {"index": i.index, "kind": i.kind,
             "severity": i.severity, "message": i.message}
            for i in report.issues
        ],
    }
