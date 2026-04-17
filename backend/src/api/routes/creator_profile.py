"""Creator Profile API — GET / POST / PUT / DELETE per-user personalization."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/creator-profile", tags=["Creator Profile"])


class ProfileUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    niche: Optional[str] = None
    tone: Optional[str] = None
    target_demo: Optional[str] = None
    preferred_music_genre: Optional[str] = None
    caption_style: Optional[str] = None
    cta_text: Optional[str] = None
    language: Optional[str] = None
    watermark_text: Optional[str] = None
    watermark_image_path: Optional[str] = None
    watermark_position: Optional[str] = None
    hook_strategy: Optional[str] = None
    hashtag_territory: Optional[str] = None


@router.get("/{user_id}")
def get_profile(user_id: str):
    from src.services.creator_profile_service import get_profile as _get
    return _get(user_id).to_dict()


@router.post("/{user_id}")
def create_profile(user_id: str, body: ProfileUpdateRequest):
    from src.services.creator_profile_service import (
        get_profile as _get, update_profile,
    )
    _get(user_id)   # ensure defaults exist
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    return update_profile(user_id, updates).to_dict()


@router.put("/{user_id}")
def update_profile_endpoint(user_id: str, body: ProfileUpdateRequest):
    from src.services.creator_profile_service import update_profile
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    return update_profile(user_id, updates).to_dict()


@router.delete("/{user_id}")
def delete_profile(user_id: str):
    from src.services.creator_profile_service import delete_profile as _del
    deleted = _del(user_id)
    return {"deleted": deleted, "user_id": user_id}


@router.get("/{user_id}/music-genres")
def get_music_genres(user_id: str):
    from src.services.creator_profile_service import get_profile as _get
    profile = _get(user_id)
    return {"user_id": user_id, "genres": profile.music_genres()}


@router.get("/{user_id}/locale-hints")
def get_locale_hints(user_id: str):
    from src.services.creator_profile_service import get_profile as _get
    profile = _get(user_id)
    return {"user_id": user_id, "hints": profile.locale_prompt_hints()}


@router.get("/")
def list_profiles():
    from src.services.creator_profile_service import list_profiles as _list
    return {"profiles": [p.to_dict() for p in _list()]}
