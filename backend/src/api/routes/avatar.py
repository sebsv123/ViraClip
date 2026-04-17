"""
NeRF Avatar API endpoints — ViraClip

Implements avatar lifecycle: create → render → composite onto clip.
Supports all 4 modes: ERNeRF, TEXT2AVATAR, VIDEO2AVATAR, UV_VOLUMES.
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request
from pydantic import BaseModel

from ...services.nerf_avatar_service import (
    get_nerf_avatar_service,
    AvatarMode,
    SMPLPose,
    NeRFAvatarService,
)
from ...services.avatar_compositor import (
    get_avatar_compositor,
    CompositeOptions,
    CompositeMode,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/avatars", tags=["avatars"])


# ------------------------------------------------------------------
# Request / Response models
# ------------------------------------------------------------------

class CreateAvatarRequest(BaseModel):
    mode: str  # ernerf | text2avatar | video2avatar | uv_volumes
    text_prompt: Optional[str] = None
    style_prompt: Optional[str] = None


class RenderAvatarRequest(BaseModel):
    audio_path: Optional[str] = None
    duration_seconds: float = 5.0
    output_path: Optional[str] = None
    # SMPL pose (TEXT2AVATAR / VIDEO2AVATAR / UV_VOLUMES)
    body_pose: Optional[list] = None     # 72-element list
    shape: Optional[list] = None         # 10-element list
    translation: Optional[list] = None  # 3-element list


class CompositeRequest(BaseModel):
    clip_path: str
    avatar_video_path: str
    output_path: Optional[str] = None
    mode: str = "pip"       # pip | face_replace | side_by_side | full_replace | lower_third
    pip_position: str = "bottom_right"
    pip_scale: float = 0.28
    chroma_key_color: Optional[str] = None   # e.g. "0x00FF00"
    face_blend_alpha: float = 0.85


# ------------------------------------------------------------------
# Avatar lifecycle endpoints
# ------------------------------------------------------------------

@router.post("")
async def create_avatar(body: CreateAvatarRequest):
    """
    Create a new NeRF avatar.

    Mode: ernerf | text2avatar | video2avatar | uv_volumes

    - **ernerf**: Provide source_image_path after upload (audio-driven talking head)
    - **text2avatar**: Provide text_prompt to generate from description
    - **video2avatar**: Provide source_video_path after upload (animatable from video)
    - **uv_volumes**: Provide source_video_path for editable UV rendering
    """
    try:
        mode = AvatarMode(body.mode)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode '{body.mode}'. Choose: ernerf, text2avatar, video2avatar, uv_volumes",
        )

    if mode == AvatarMode.TEXT2AVATAR and not body.text_prompt:
        raise HTTPException(status_code=400, detail="text2avatar mode requires text_prompt")

    svc = get_nerf_avatar_service()
    avatar = await svc.create_avatar(
        mode=mode,
        text_prompt=body.text_prompt,
        style_prompt=body.style_prompt,
    )

    return {
        "status": "success",
        "avatar": avatar.to_dict(),
        "message": f"Avatar created with mode={body.mode}. Use /avatars/{avatar.avatar_id}/render to generate video.",
    }


@router.post("/upload")
async def create_avatar_from_upload(
    mode: str = Form(...),
    style_prompt: Optional[str] = Form(None),
    text_prompt: Optional[str] = Form(None),
    file: UploadFile = File(...),
):
    """
    Create a NeRF avatar from an uploaded image or video file.

    - **ernerf**: Upload a face photo (JPG/PNG)
    - **video2avatar**: Upload a video (MP4) of the person
    - **uv_volumes**: Upload a video (MP4) of the person
    """
    import shutil

    try:
        avatar_mode = AvatarMode(mode)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {mode}")

    # Save uploaded file
    upload_dir = NeRFAvatarService.AVATARS_DIR / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    save_path = upload_dir / file.filename

    with save_path.open("wb") as buf:
        shutil.copyfileobj(file.file, buf)

    # Determine source type
    is_video = file.filename.lower().endswith((".mp4", ".mov", ".avi", ".webm"))
    svc = get_nerf_avatar_service()

    avatar = await svc.create_avatar(
        mode=avatar_mode,
        source_image_path=str(save_path) if not is_video else None,
        source_video_path=str(save_path) if is_video else None,
        text_prompt=text_prompt,
        style_prompt=style_prompt,
    )

    return {
        "status": "success",
        "avatar": avatar.to_dict(),
        "uploaded_file": str(save_path),
    }


@router.get("")
async def list_avatars():
    """List all available avatars."""
    svc = get_nerf_avatar_service()
    avatars = svc.list_avatars()

    return {
        "status": "success",
        "count": len(avatars),
        "avatars": [a.to_dict() for a in avatars],
    }


@router.get("/{avatar_id}")
async def get_avatar(avatar_id: str):
    """Get details of a specific avatar."""
    svc = get_nerf_avatar_service()
    avatar = svc.get_avatar(avatar_id)

    if not avatar:
        raise HTTPException(status_code=404, detail=f"Avatar {avatar_id} not found")

    return {"status": "success", "avatar": avatar.to_dict()}


@router.delete("/{avatar_id}")
async def delete_avatar(avatar_id: str):
    """Delete an avatar and all its files."""
    svc = get_nerf_avatar_service()
    deleted = svc.delete_avatar(avatar_id)

    if not deleted:
        raise HTTPException(status_code=404, detail=f"Avatar {avatar_id} not found")

    return {"status": "deleted", "avatar_id": avatar_id}


@router.post("/{avatar_id}/render")
async def render_avatar(avatar_id: str, body: RenderAvatarRequest):
    """
    Render a video from the avatar.

    - **ernerf**: Optionally provide audio_path to drive lip sync
    - **text2avatar / video2avatar / uv_volumes**: Optionally provide SMPL pose params
    """
    svc = get_nerf_avatar_service()
    avatar = svc.get_avatar(avatar_id)

    if not avatar:
        raise HTTPException(status_code=404, detail=f"Avatar {avatar_id} not found")

    pose = None
    if body.body_pose or body.shape or body.translation:
        pose = SMPLPose(
            body_pose=body.body_pose or [0.0] * 72,
            shape=body.shape or [0.0] * 10,
            translation=body.translation or [0.0, 0.0, 0.0],
        )

    result = await svc.render_avatar_video(
        avatar_id=avatar_id,
        audio_path=body.audio_path,
        target_pose=pose,
        duration_seconds=body.duration_seconds,
        output_path=body.output_path,
    )

    if not result:
        raise HTTPException(status_code=500, detail="Avatar rendering failed")

    return {
        "status": "success",
        "avatar_id": avatar_id,
        "rendered_video_path": result,
        "duration_seconds": body.duration_seconds,
    }


@router.post("/{avatar_id}/composite")
async def composite_avatar_onto_clip(avatar_id: str, body: CompositeRequest):
    """
    Composite a rendered avatar video onto a clip.

    Modes:
    - **pip**: Picture-in-picture overlay (default)
    - **face_replace**: Replace face in clip with avatar (ERNeRF-style)
    - **side_by_side**: Split screen, clip left + avatar right
    - **full_replace**: Avatar replaces clip entirely
    - **lower_third**: Avatar as animated lower-third presenter
    """
    try:
        comp_mode = CompositeMode(body.mode)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid composite mode '{body.mode}'. Choose: pip, face_replace, side_by_side, full_replace, lower_third",
        )

    compositor = get_avatar_compositor()
    options = CompositeOptions(
        mode=comp_mode,
        pip_position=body.pip_position,
        pip_scale=body.pip_scale,
        face_blend_alpha=body.face_blend_alpha,
        chroma_key_color=body.chroma_key_color,
    )

    output_path = body.output_path or body.clip_path.replace(".mp4", f"_avatar_{body.mode}.mp4")

    try:
        result = await compositor.composite(
            clip_path=body.clip_path,
            avatar_video_path=body.avatar_video_path,
            output_path=output_path,
            options=options,
        )
    except Exception as e:
        logger.error(f"[Avatar] Composite failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "success",
        "output_path": result,
        "mode": body.mode,
    }


@router.post("/{avatar_id}/render-and-composite")
async def render_and_composite(
    avatar_id: str,
    clip_path: str,
    audio_path: Optional[str] = None,
    duration_seconds: float = 5.0,
    composite_mode: str = "pip",
    pip_position: str = "bottom_right",
    output_path: Optional[str] = None,
):
    """
    One-shot: render avatar video then composite onto clip.
    Combines /render + /composite in a single request.
    """
    svc = get_nerf_avatar_service()
    avatar = svc.get_avatar(avatar_id)

    if not avatar:
        raise HTTPException(status_code=404, detail=f"Avatar {avatar_id} not found")

    # Step 1: Render avatar
    render_out = str(svc.AVATARS_DIR / avatar_id / "render_temp.mp4")
    rendered = await svc.render_avatar_video(
        avatar_id=avatar_id,
        audio_path=audio_path,
        duration_seconds=duration_seconds,
        output_path=render_out,
    )

    if not rendered:
        raise HTTPException(status_code=500, detail="Avatar rendering failed")

    # Step 2: Composite onto clip
    final_out = output_path or clip_path.replace(".mp4", f"_with_avatar.mp4")

    try:
        comp_mode = CompositeMode(composite_mode)
    except ValueError:
        comp_mode = CompositeMode.PICTURE_IN_PICTURE

    compositor = get_avatar_compositor()
    result = await compositor.composite(
        clip_path=clip_path,
        avatar_video_path=rendered,
        output_path=final_out,
        options=CompositeOptions(mode=comp_mode, pip_position=pip_position),
    )

    return {
        "status": "success",
        "avatar_id": avatar_id,
        "clip_path": clip_path,
        "output_path": result,
        "avatar_video_path": rendered,
        "composite_mode": composite_mode,
    }


@router.get("/modes/info")
async def get_avatar_modes():
    """List all avatar modes with descriptions and requirements."""
    return {
        "modes": [
            {
                "mode": "ernerf",
                "name": "ERNeRF Audio-Driven Talking Head",
                "description": "Creates a talking head avatar driven by audio. Upload a face photo.",
                "paper": "https://arxiv.org/abs/2307.09323",
                "requires": ["source_image (face photo)"],
                "optional": ["audio_path for lip sync"],
                "gpu_required": False,
                "gpu_recommended": True,
                "training_time": "15 min (GPU) / instant (CPU fallback)",
            },
            {
                "mode": "text2avatar",
                "name": "AvatarCraft Text-to-Avatar",
                "description": "Create a 3D avatar from a text description using diffusion guidance.",
                "paper": "https://arxiv.org/abs/2303.17606",
                "requires": ["text_prompt"],
                "optional": ["style_prompt"],
                "gpu_required": False,
                "gpu_recommended": True,
                "training_time": "30 min (GPU) / DALL-E API (CPU fallback)",
            },
            {
                "mode": "video2avatar",
                "name": "Animatable NeRF",
                "description": "Create an animatable avatar from a monocular video. Novel pose synthesis.",
                "paper": "https://arxiv.org/abs/2110.13915",
                "requires": ["source_video (person video)"],
                "optional": ["SMPL pose params for rendering"],
                "gpu_required": True,
                "gpu_recommended": True,
                "training_time": "2-4 hours (GPU)",
            },
            {
                "mode": "uv_volumes",
                "name": "UV-Volumes Editable Rendering",
                "description": "Real-time editable avatar using UV appearance maps. Change appearance without retraining.",
                "paper": "https://arxiv.org/abs/2304.01012",
                "requires": ["source_video (person video)"],
                "optional": ["SMPL pose params for animation"],
                "gpu_required": False,
                "gpu_recommended": True,
                "training_time": "1-2 hours (GPU) / instant (CPU fallback)",
            },
        ],
        "composite_modes": [
            {"mode": "pip", "description": "Picture-in-picture overlay in a corner"},
            {"mode": "face_replace", "description": "Replace face in clip with avatar (ERNeRF-style)"},
            {"mode": "side_by_side", "description": "Split screen: clip left, avatar right"},
            {"mode": "full_replace", "description": "Avatar replaces clip entirely"},
            {"mode": "lower_third", "description": "Avatar as animated lower-third presenter"},
        ],
    }
