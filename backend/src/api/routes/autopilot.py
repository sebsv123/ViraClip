"""Auto-Pilot API routes — end-to-end content automation."""
from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...api.middleware.rate_limit import autopilot_rate_limit_dependency

router = APIRouter(prefix="/autopilot", tags=["autopilot"])


class AutopilotRequest(BaseModel):
    # Source (one of url or local_path required)
    source_url: Optional[str] = None
    source_local_path: Optional[str] = None

    # Processing
    niche: str = "auto"
    target_platform: str = "tiktok"
    max_clips: int = 5
    add_subtitles: bool = True
    caption_template: str = "default"

    # Enhancement
    denoise_audio: bool = True
    jump_cut: bool = True
    jump_cut_fillers: bool = True

    # Voiceover
    add_voiceover: bool = False
    voiceover_text: Optional[str] = None
    voiceover_provider: str = "auto"

    # Publishing
    auto_publish: bool = False
    publish_platforms: List[str] = ["tiktok"]
    caption_text: Optional[str] = None
    hashtags: List[str] = []
    schedule_iso: Optional[str] = None

    # User
    user_id: Optional[str] = None


class AutopilotResponse(BaseModel):
    workflow_id: str
    status: str
    message: str


@router.post("/run", response_model=AutopilotResponse)
async def run_autopilot(body: AutopilotRequest, _rl=Depends(autopilot_rate_limit_dependency)):
    """
    Start a fully automated pipeline: ingest → denoise → process
    → jump-cut → (optional voiceover) → (optional publish) → track.

    Returns immediately with a workflow_id. Poll /autopilot/status/{id} for progress.
    """
    if not body.source_url and not body.source_local_path:
        raise HTTPException(
            status_code=400,
            detail="Provide either source_url or source_local_path"
        )

    from ...services.autopilot_service import AutopilotConfig, start_autopilot

    config = AutopilotConfig(
        source_url=body.source_url,
        source_local_path=body.source_local_path,
        niche=body.niche,
        target_platform=body.target_platform,
        max_clips=body.max_clips,
        add_subtitles=body.add_subtitles,
        caption_template=body.caption_template,
        denoise_audio=body.denoise_audio,
        jump_cut=body.jump_cut,
        jump_cut_fillers=body.jump_cut_fillers,
        add_voiceover=body.add_voiceover,
        voiceover_text=body.voiceover_text,
        voiceover_provider=body.voiceover_provider,
        auto_publish=body.auto_publish,
        publish_platforms=body.publish_platforms,
        caption_text=body.caption_text,
        hashtags=body.hashtags,
        schedule_iso=body.schedule_iso,
        user_id=body.user_id,
    )

    wf = await start_autopilot(config)
    return AutopilotResponse(
        workflow_id=wf.workflow_id,
        status=wf.status,
        message=f"Autopilot workflow started. Poll /autopilot/status/{wf.workflow_id}",
    )


@router.get("/status/{workflow_id}")
def get_status(workflow_id: str):
    """Poll the status of a running or completed autopilot workflow."""
    from ...services.autopilot_service import get_workflow
    wf = get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail=f"Workflow {workflow_id} not found")
    return wf


@router.get("/workflows")
def list_workflows(limit: int = 20):
    """List recent autopilot workflows."""
    from ...services.autopilot_service import list_workflows
    return {"workflows": list_workflows(limit)}


@router.post("/ab-winner")
def trigger_ab_winner(user_id: str, min_viral_posts: int = 5):
    """
    Manually trigger A/B winner selection for a user.
    If a template has ≥ min_viral_posts viral clips, it becomes the user's default.
    """
    from ...domains.publishing.performance_webhook_service import auto_update_creator_template
    winner = auto_update_creator_template(user_id, min_viral_posts)
    if winner:
        return {"updated": True, "new_template": winner, "user_id": user_id}
    return {"updated": False, "message": "No qualifying winner yet", "user_id": user_id}
