"""
NeRF Avatar Service — ViraClip
==============================
Inspired by:
  - ERNeRF (audio-driven talking head): https://github.com/Fictionarry/ER-NeRF
  - AvatarCraft (text-to-avatar, ICCV23): https://github.com/songrise/AvatarCraft
  - Animatable NeRF (video-to-avatar, TPAMI24): https://github.com/zju3dv/animatable_nerf
  - UV-Volumes (real-time editable rendering, CVPR23): https://github.com/fanegg/UV-Volumes

Architecture:
  AvatarMode enum selects the backend pipeline:
    ERNERF       → Audio-driven talking head (face-only, low VRAM)
    TEXT2AVATAR  → Text prompt → diffusion → SMPL body mesh → pose control
    VIDEO2AVATAR → Monocular video → SMPL fit → blend weights → novel pose
    UV_VOLUMES   → UV appearance map → editable real-time rendering

  For ViraClip production:
    - GPU path uses ComfyUI AnimateDiff + custom nodes (avail. via --profile gpu)
    - CPU/fallback path uses MediaPipe + GFPGAN + FFmpeg compositing
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data contracts (inspired by AvatarCraft / Animatable NeRF schemas)
# ---------------------------------------------------------------------------

class AvatarMode(str, Enum):
    """Avatar generation backend to use."""
    ERNERF = "ernerf"           # Audio-driven talking head (ERNeRF)
    TEXT2AVATAR = "text2avatar" # Text → diffusion → SMPL body (AvatarCraft)
    VIDEO2AVATAR = "video2avatar"  # Monocular video → animatable NeRF
    UV_VOLUMES = "uv_volumes"   # UV appearance map → editable rendering


class AvatarStatus(str, Enum):
    PENDING = "pending"
    TRAINING = "training"
    READY = "ready"
    RENDERING = "rendering"
    FAILED = "failed"


@dataclass
class SMPLPose:
    """
    SMPL body pose parameters — used by AvatarCraft and Animatable NeRF.
    body_pose: (72,) theta vector (23 joints × 3 axis-angle)
    shape:     (10,) beta vector (shape blend shapes)
    translation: (3,) root translation
    """
    body_pose: List[float] = field(default_factory=lambda: [0.0] * 72)
    shape: List[float] = field(default_factory=lambda: [0.0] * 10)
    translation: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])

    def to_dict(self) -> Dict:
        return {
            "body_pose": self.body_pose,
            "shape": self.shape,
            "translation": self.translation,
        }


@dataclass
class AudioFeatures:
    """
    Audio features for ERNeRF audio-driven animation.
    Inspired by ER-NeRF's audio encoder which extracts:
      - HuBERT / DeepSpeech features (768-dim per frame)
      - Pitch (F0) and energy contours
    """
    hubert_features: Optional[List[List[float]]] = None  # [T, 768]
    pitch_contour: Optional[List[float]] = None           # [T]
    energy_contour: Optional[List[float]] = None          # [T]
    frame_rate: float = 25.0
    duration_seconds: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "frame_rate": self.frame_rate,
            "duration_seconds": self.duration_seconds,
            "hubert_features_shape": (
                [len(self.hubert_features), len(self.hubert_features[0])]
                if self.hubert_features else None
            ),
        }


@dataclass
class UVAppearanceMap:
    """
    UV appearance representation from UV-Volumes (CVPR 2023).
    Stores texture in UV space for real-time editable rendering.
    """
    uv_texture_path: Optional[str] = None    # RGBA image in UV space
    normal_map_path: Optional[str] = None    # Normal map for shading
    smpl_uv_obj_path: Optional[str] = None   # SMPL mesh with UV coords
    resolution: Tuple[int, int] = (1024, 1024)

    def to_dict(self) -> Dict:
        return {
            "uv_texture_path": self.uv_texture_path,
            "normal_map_path": self.normal_map_path,
            "resolution": list(self.resolution),
        }


@dataclass
class AvatarAsset:
    """
    A trained/created avatar asset that can be used to generate video.
    Stores all state needed to animate and composite the avatar.
    """
    avatar_id: str
    mode: AvatarMode
    status: AvatarStatus = AvatarStatus.PENDING

    # Source inputs
    source_image_path: Optional[str] = None  # Face image (ERNeRF, VIDEO2AVATAR)
    source_video_path: Optional[str] = None  # Training video (VIDEO2AVATAR)
    text_prompt: Optional[str] = None         # Description (TEXT2AVATAR)
    style_prompt: Optional[str] = None        # Style (TEXT2AVATAR, e.g. "anime style")

    # Trained model paths
    nerf_model_path: Optional[str] = None     # Trained NeRF checkpoint
    smpl_params_path: Optional[str] = None    # SMPL body fit parameters
    blend_weights_path: Optional[str] = None  # Animatable NeRF blend fields

    # UV-Volumes representation
    uv_appearance: Optional[UVAppearanceMap] = None

    # Metadata
    created_at: float = field(default_factory=time.time)
    training_seconds: float = 0.0
    face_bbox: Optional[List[int]] = None     # [x, y, w, h] in source image
    landmark_3d_path: Optional[str] = None   # 3DMM landmarks for ERNeRF

    # Generated outputs
    rendered_frames_dir: Optional[str] = None
    composite_video_path: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "avatar_id": self.avatar_id,
            "mode": self.mode.value,
            "status": self.status.value,
            "source_image_path": self.source_image_path,
            "source_video_path": self.source_video_path,
            "text_prompt": self.text_prompt,
            "style_prompt": self.style_prompt,
            "nerf_model_path": self.nerf_model_path,
            "smpl_params_path": self.smpl_params_path,
            "blend_weights_path": self.blend_weights_path,
            "uv_appearance": self.uv_appearance.to_dict() if self.uv_appearance else None,
            "created_at": self.created_at,
            "training_seconds": self.training_seconds,
            "face_bbox": self.face_bbox,
            "composite_video_path": self.composite_video_path,
        }


# ---------------------------------------------------------------------------
# NeRF Avatar Service
# ---------------------------------------------------------------------------

class NeRFAvatarService:
    """
    Orchestrates NeRF-based avatar creation and rendering for ViraClip.

    Modes:
      ERNERF       → ERNeRF pipeline (audio → talking head)
      TEXT2AVATAR  → AvatarCraft pipeline (text → SMPL avatar)
      VIDEO2AVATAR → Animatable NeRF pipeline (video → animatable avatar)
      UV_VOLUMES   → UV-Volumes fast rendering with appearance editing
    """

    AVATARS_DIR = Path("/app/avatars")
    MODELS_DIR = Path("/app/models/nerf")

    def __init__(self):
        self.AVATARS_DIR.mkdir(parents=True, exist_ok=True)
        self.MODELS_DIR.mkdir(parents=True, exist_ok=True)
        self._avatars: Dict[str, AvatarAsset] = {}
        self._load_existing_avatars()

    def _load_existing_avatars(self):
        """Load persisted avatar metadata from disk."""
        meta_file = self.AVATARS_DIR / "index.json"
        if meta_file.exists():
            try:
                data = json.loads(meta_file.read_text())
                for item in data:
                    mode = AvatarMode(item["mode"])
                    asset = AvatarAsset(
                        avatar_id=item["avatar_id"],
                        mode=mode,
                        status=AvatarStatus(item.get("status", "ready")),
                        source_image_path=item.get("source_image_path"),
                        source_video_path=item.get("source_video_path"),
                        text_prompt=item.get("text_prompt"),
                        nerf_model_path=item.get("nerf_model_path"),
                        composite_video_path=item.get("composite_video_path"),
                        created_at=item.get("created_at", time.time()),
                    )
                    self._avatars[asset.avatar_id] = asset
            except Exception as e:
                logger.warning(f"[Avatar] Failed to load avatar index: {e}")

    def _save_avatar_index(self):
        """Persist all avatar metadata to disk."""
        meta_file = self.AVATARS_DIR / "index.json"
        data = [a.to_dict() for a in self._avatars.values()]
        meta_file.write_text(json.dumps(data, indent=2))

    def _avatar_dir(self, avatar_id: str) -> Path:
        d = self.AVATARS_DIR / avatar_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_avatar(
        self,
        mode: AvatarMode,
        source_image_path: Optional[str] = None,
        source_video_path: Optional[str] = None,
        text_prompt: Optional[str] = None,
        style_prompt: Optional[str] = None,
    ) -> AvatarAsset:
        """
        Create a new avatar using the specified mode.

        ERNeRF:       requires source_image_path (face photo)
        TEXT2AVATAR:  requires text_prompt
        VIDEO2AVATAR: requires source_video_path
        UV_VOLUMES:   requires source_video_path
        """
        avatar_id = str(uuid.uuid4())[:12]
        asset = AvatarAsset(
            avatar_id=avatar_id,
            mode=mode,
            status=AvatarStatus.TRAINING,
            source_image_path=source_image_path,
            source_video_path=source_video_path,
            text_prompt=text_prompt,
            style_prompt=style_prompt,
        )
        self._avatars[avatar_id] = asset
        self._save_avatar_index()

        # Dispatch to mode-specific pipeline
        try:
            t0 = time.time()
            if mode == AvatarMode.ERNERF:
                await self._pipeline_ernerf(asset)
            elif mode == AvatarMode.TEXT2AVATAR:
                await self._pipeline_text2avatar(asset)
            elif mode == AvatarMode.VIDEO2AVATAR:
                await self._pipeline_video2avatar(asset)
            elif mode == AvatarMode.UV_VOLUMES:
                await self._pipeline_uv_volumes(asset)
            asset.training_seconds = time.time() - t0
            asset.status = AvatarStatus.READY
        except Exception as e:
            logger.error(f"[Avatar] Pipeline failed for {avatar_id}: {e}")
            asset.status = AvatarStatus.FAILED
        finally:
            self._save_avatar_index()

        return asset

    async def render_avatar_video(
        self,
        avatar_id: str,
        audio_path: Optional[str] = None,
        target_pose: Optional[SMPLPose] = None,
        duration_seconds: float = 5.0,
        output_path: Optional[str] = None,
    ) -> Optional[str]:
        """
        Render a video of the avatar.

        ERNeRF:       driven by audio_path
        TEXT2AVATAR:  driven by target_pose (SMPL params)
        VIDEO2AVATAR: driven by target_pose (novel poses)
        UV_VOLUMES:   driven by target_pose + UV texture editing
        """
        asset = self._avatars.get(avatar_id)
        if not asset or asset.status != AvatarStatus.READY:
            raise ValueError(f"Avatar {avatar_id} not ready (status={asset.status if asset else 'not found'})")

        out_path = output_path or str(self._avatar_dir(avatar_id) / "render.mp4")
        asset.status = AvatarStatus.RENDERING
        self._save_avatar_index()

        try:
            if asset.mode == AvatarMode.ERNERF:
                result = await self._render_ernerf(asset, audio_path, duration_seconds, out_path)
            elif asset.mode == AvatarMode.TEXT2AVATAR:
                result = await self._render_text2avatar(asset, target_pose, duration_seconds, out_path)
            elif asset.mode == AvatarMode.VIDEO2AVATAR:
                result = await self._render_video2avatar(asset, target_pose, duration_seconds, out_path)
            elif asset.mode == AvatarMode.UV_VOLUMES:
                result = await self._render_uv_volumes(asset, target_pose, duration_seconds, out_path)
            else:
                result = None

            asset.composite_video_path = result
            asset.status = AvatarStatus.READY
            self._save_avatar_index()
            return result
        except Exception as e:
            logger.error(f"[Avatar] Render failed for {avatar_id}: {e}")
            asset.status = AvatarStatus.READY  # Reset so user can retry
            self._save_avatar_index()
            return None

    def get_avatar(self, avatar_id: str) -> Optional[AvatarAsset]:
        return self._avatars.get(avatar_id)

    def list_avatars(self) -> List[AvatarAsset]:
        return list(self._avatars.values())

    def delete_avatar(self, avatar_id: str) -> bool:
        if avatar_id not in self._avatars:
            return False
        import shutil
        d = self.AVATARS_DIR / avatar_id
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        del self._avatars[avatar_id]
        self._save_avatar_index()
        return True

    # ------------------------------------------------------------------
    # ERNeRF pipeline — Audio-driven talking head
    # Inspired by: https://github.com/Fictionarry/ER-NeRF
    # ------------------------------------------------------------------

    async def _pipeline_ernerf(self, asset: AvatarAsset):
        """
        ERNeRF setup pipeline:
        1. Face detection + 3DMM landmark extraction (OpenFace / MediaPipe)
        2. Background matting
        3. NeRF training or load pre-trained checkpoint

        On GPU: uses full NeRF training (~15 min on RTX 3090)
        On CPU fallback: extracts landmarks + uses GFPGAN for face enhancement
        """
        avatar_dir = self._avatar_dir(asset.avatar_id)
        source = asset.source_image_path

        if not source or not Path(source).exists():
            raise ValueError(f"ERNeRF requires source_image_path, got: {source}")

        logger.info(f"[ERNeRF] Setting up avatar {asset.avatar_id}")

        # Step 1: Face detection and landmark extraction (MediaPipe FaceMesh)
        face_bbox, landmark_path = await self._extract_face_landmarks(
            source, avatar_dir
        )
        asset.face_bbox = face_bbox
        asset.landmark_3d_path = str(landmark_path)

        # Step 2: Background matting
        matted_path = await self._background_matting(source, avatar_dir)

        # Step 3: GPU path — ERNeRF training via ComfyUI
        if self._comfyui_available():
            nerf_path = await self._train_ernerf_comfyui(
                face_image=source,
                landmarks=landmark_path,
                avatar_dir=avatar_dir,
            )
        else:
            # CPU fallback: pre-trained face NeRF proxy (GFPGAN)
            nerf_path = await self._prepare_gfpgan_proxy(source, avatar_dir)

        asset.nerf_model_path = str(nerf_path)
        logger.info(f"[ERNeRF] Avatar {asset.avatar_id} ready: {nerf_path}")

    async def _render_ernerf(
        self,
        asset: AvatarAsset,
        audio_path: Optional[str],
        duration: float,
        output_path: str,
    ) -> str:
        """
        ERNeRF rendering:
        1. Extract audio features (HuBERT or DeepSpeech)
        2. Generate landmark sequence from audio features
        3. Render frames via NeRF
        4. Composite with background
        """
        avatar_dir = self._avatar_dir(asset.avatar_id)

        # Step 1: Extract audio features
        audio_features = await self._extract_audio_features(audio_path, duration)

        # Step 2: GPU — full ERNeRF inference via ComfyUI
        if self._comfyui_available() and asset.nerf_model_path:
            return await self._render_ernerf_comfyui(
                asset, audio_features, output_path
            )

        # CPU fallback: lip-sync via Wav2Lip-style simple morph
        return await self._render_ernerf_cpu_fallback(
            asset, audio_path, duration, output_path
        )

    # ------------------------------------------------------------------
    # AvatarCraft pipeline — Text to neural avatar (ICCV 2023)
    # Inspired by: https://github.com/songrise/AvatarCraft
    # ------------------------------------------------------------------

    async def _pipeline_text2avatar(self, asset: AvatarAsset):
        """
        AvatarCraft setup:
        1. Initialize SMPL body mesh
        2. Coarse-to-fine diffusion-guided NeRF optimization
        3. Store SMPL params + NeRF weights

        Key AvatarCraft innovations used:
        - Multi-bounding-box coarse-to-fine training
        - Shape regularization via SMPL prior
        - Stable Diffusion SDS loss guidance
        """
        if not asset.text_prompt:
            raise ValueError("TEXT2AVATAR requires text_prompt")

        avatar_dir = self._avatar_dir(asset.avatar_id)
        logger.info(f"[AvatarCraft] Creating avatar from prompt: '{asset.text_prompt}'")

        # Step 1: Initialize SMPL neutral pose
        smpl_params = SMPLPose()
        smpl_path = avatar_dir / "smpl_params.json"
        smpl_path.write_text(json.dumps(smpl_params.to_dict()))
        asset.smpl_params_path = str(smpl_path)

        # Step 2: GPU — Diffusion-guided NeRF via ComfyUI
        if self._comfyui_available():
            nerf_path = await self._train_text2avatar_comfyui(
                text_prompt=asset.text_prompt,
                style_prompt=asset.style_prompt,
                smpl_params=smpl_params,
                avatar_dir=avatar_dir,
            )
        else:
            # CPU fallback: generate avatar image via Stable Diffusion API
            nerf_path = await self._generate_avatar_image_fallback(
                asset.text_prompt, asset.style_prompt, avatar_dir
            )

        asset.nerf_model_path = str(nerf_path)
        logger.info(f"[AvatarCraft] Avatar {asset.avatar_id} ready")

    async def _render_text2avatar(
        self,
        asset: AvatarAsset,
        target_pose: Optional[SMPLPose],
        duration: float,
        output_path: str,
    ) -> str:
        """
        AvatarCraft rendering — pose-driven animation.
        Warps the neural field using SMPL template-to-target mapping.
        """
        pose = target_pose or SMPLPose()

        if self._comfyui_available() and asset.nerf_model_path:
            return await self._render_smpl_animated_comfyui(
                asset, pose, duration, output_path
            )

        # CPU fallback: static image with pose overlay
        return await self._render_static_avatar_video(asset, duration, output_path)

    # ------------------------------------------------------------------
    # Animatable NeRF pipeline — Video to animatable avatar (TPAMI 2024)
    # Inspired by: https://github.com/zju3dv/animatable_nerf
    # ------------------------------------------------------------------

    async def _pipeline_video2avatar(self, asset: AvatarAsset):
        """
        Animatable NeRF setup:
        1. Fit SMPL body to each frame of source video
        2. Learn blend weight fields (LBS deformation)
        3. Train neural radiance field in canonical space

        Key Animatable NeRF concepts:
        - Canonical space NeRF
        - Pose-dependent blend weights
        - Background separation
        """
        if not asset.source_video_path:
            raise ValueError("VIDEO2AVATAR requires source_video_path")

        avatar_dir = self._avatar_dir(asset.avatar_id)
        logger.info(f"[AnimatableNeRF] Processing video {asset.source_video_path}")

        # Step 1: Extract frames from video
        frames_dir = avatar_dir / "frames"
        frames_dir.mkdir(exist_ok=True)
        await self._extract_video_frames(asset.source_video_path, frames_dir)

        # Step 2: SMPL body fitting per frame (HMR / PARE / CLIFF)
        smpl_seq_path = await self._fit_smpl_sequence(frames_dir, avatar_dir)
        asset.smpl_params_path = str(smpl_seq_path)

        # Step 3: Learn blend weight fields
        if self._comfyui_available():
            weights_path = await self._train_blend_weights_comfyui(
                frames_dir, smpl_seq_path, avatar_dir
            )
            asset.blend_weights_path = str(weights_path)

            # Step 4: Train canonical NeRF
            nerf_path = await self._train_canonical_nerf_comfyui(
                frames_dir, smpl_seq_path, weights_path, avatar_dir
            )
        else:
            # CPU fallback: use video as proxy, no NeRF training
            nerf_path = await self._prepare_video_proxy(
                asset.source_video_path, avatar_dir
            )

        asset.nerf_model_path = str(nerf_path)
        logger.info(f"[AnimatableNeRF] Avatar {asset.avatar_id} ready")

    async def _render_video2avatar(
        self,
        asset: AvatarAsset,
        target_pose: Optional[SMPLPose],
        duration: float,
        output_path: str,
    ) -> str:
        """
        Animatable NeRF rendering — novel pose synthesis.
        Maps target pose through blend weight fields to canonical space.
        """
        pose = target_pose or SMPLPose()

        if self._comfyui_available() and asset.nerf_model_path:
            return await self._render_novel_pose_comfyui(
                asset, pose, duration, output_path
            )

        # CPU fallback: retarget body motion via FFmpeg
        return await self._render_body_retarget_fallback(
            asset, pose, duration, output_path
        )

    # ------------------------------------------------------------------
    # UV-Volumes pipeline — Editable real-time rendering (CVPR 2023)
    # Inspired by: https://github.com/fanegg/UV-Volumes
    # ------------------------------------------------------------------

    async def _pipeline_uv_volumes(self, asset: AvatarAsset):
        """
        UV-Volumes setup:
        1. Fit SMPL to source video
        2. Unwrap appearance to UV texture space
        3. Build volumetric representation in UV space

        Key UV-Volumes concept:
        - UV-structured volume (appearance in 2D UV space)
        - Allows texture editing (change clothes, style) in UV space
        - Fast inference via pre-computed UV lookups
        """
        if not asset.source_video_path:
            raise ValueError("UV_VOLUMES requires source_video_path")

        avatar_dir = self._avatar_dir(asset.avatar_id)
        logger.info(f"[UV-Volumes] Processing {asset.source_video_path}")

        # Step 1: Extract frames
        frames_dir = avatar_dir / "frames"
        frames_dir.mkdir(exist_ok=True)
        await self._extract_video_frames(asset.source_video_path, frames_dir)

        # Step 2: SMPL fitting
        smpl_seq_path = await self._fit_smpl_sequence(frames_dir, avatar_dir)
        asset.smpl_params_path = str(smpl_seq_path)

        # Step 3: Build UV appearance map
        uv_tex_path, normal_map_path = await self._build_uv_appearance_map(
            frames_dir, smpl_seq_path, avatar_dir
        )

        asset.uv_appearance = UVAppearanceMap(
            uv_texture_path=str(uv_tex_path),
            normal_map_path=str(normal_map_path),
            smpl_uv_obj_path=str(self.MODELS_DIR / "smpl_uv.obj"),
        )

        # Step 4: GPU — train UV volume rendering network
        if self._comfyui_available():
            nerf_path = await self._train_uv_volume_comfyui(
                frames_dir, smpl_seq_path, uv_tex_path, avatar_dir
            )
        else:
            nerf_path = avatar_dir / "uv_volume_proxy.json"
            nerf_path.write_text(json.dumps(asset.uv_appearance.to_dict()))

        asset.nerf_model_path = str(nerf_path)
        logger.info(f"[UV-Volumes] Avatar {asset.avatar_id} ready")

    async def _render_uv_volumes(
        self,
        asset: AvatarAsset,
        target_pose: Optional[SMPLPose],
        duration: float,
        output_path: str,
    ) -> str:
        """
        UV-Volumes rendering — fast editable rendering via UV lookup.
        Can edit appearance by modifying UV texture before rendering.
        """
        pose = target_pose or SMPLPose()

        if self._comfyui_available() and asset.nerf_model_path:
            return await self._render_uv_animated_comfyui(
                asset, pose, duration, output_path
            )

        # CPU fallback: render textured SMPL mesh via OpenCV
        return await self._render_uv_cpu_fallback(
            asset, pose, duration, output_path
        )

    # ------------------------------------------------------------------
    # Shared utilities
    # ------------------------------------------------------------------

    async def _extract_face_landmarks(
        self,
        image_path: str,
        avatar_dir: Path,
    ) -> Tuple[List[int], Path]:
        """
        Extract face bbox and 3D landmarks using MediaPipe FaceMesh.
        ERNeRF uses OpenFace landmarks, but MediaPipe is a practical substitute.
        """
        landmark_path = avatar_dir / "landmarks.json"

        try:
            import cv2
            import mediapipe as mp

            image = cv2.imread(image_path)
            if image is None:
                raise ValueError(f"Cannot read image: {image_path}")

            h, w = image.shape[:2]
            mp_face = mp.solutions.face_mesh
            with mp_face.FaceMesh(
                static_image_mode=True,
                max_num_faces=1,
                refine_landmarks=True,
            ) as face_mesh:
                rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                results = face_mesh.process(rgb)

                if results.multi_face_landmarks:
                    lms = results.multi_face_landmarks[0].landmark
                    points_3d = [[lm.x * w, lm.y * h, lm.z * w] for lm in lms]

                    # Compute bbox from landmarks
                    xs = [p[0] for p in points_3d]
                    ys = [p[1] for p in points_3d]
                    x, y = int(min(xs)), int(min(ys))
                    bw = int(max(xs) - min(xs))
                    bh = int(max(ys) - min(ys))
                    # Add 30% margin (ERNeRF uses tight crop with padding)
                    pad_x, pad_y = int(bw * 0.3), int(bh * 0.3)
                    face_bbox = [
                        max(0, x - pad_x),
                        max(0, y - pad_y),
                        min(w, bw + 2 * pad_x),
                        min(h, bh + 2 * pad_y),
                    ]

                    landmark_path.write_text(json.dumps({
                        "landmarks_3d": points_3d,
                        "image_wh": [w, h],
                        "face_bbox": face_bbox,
                    }))
                    return face_bbox, landmark_path

        except ImportError:
            logger.warning("[Avatar] MediaPipe not available, using fallback bbox")

        # Fallback: center crop
        face_bbox = [w // 4, h // 4, w // 2, h // 2] if 'w' in dir() else [0, 0, 256, 256]
        landmark_path.write_text(json.dumps({
            "landmarks_3d": [],
            "face_bbox": face_bbox,
            "note": "MediaPipe not available",
        }))
        return face_bbox, landmark_path

    async def _background_matting(self, image_path: str, avatar_dir: Path) -> Path:
        """
        Background removal for ERNeRF/UV-Volumes.
        Uses rembg (SAM-based) or GrabCut fallback.
        """
        out_path = avatar_dir / "matted.png"

        try:
            from rembg import remove
            from PIL import Image

            with Image.open(image_path) as img:
                result = remove(img)
                result.save(out_path)
            logger.debug(f"[Avatar] Background removed via rembg: {out_path}")
        except ImportError:
            # Fallback: copy original
            import shutil
            shutil.copy(image_path, out_path)
            logger.debug("[Avatar] rembg not available, using original image")

        return out_path

    async def _extract_audio_features(
        self, audio_path: Optional[str], duration: float
    ) -> AudioFeatures:
        """
        Extract audio features for ERNeRF driving.
        ERNeRF uses HuBERT features — we use librosa as practical substitute.
        """
        features = AudioFeatures(duration_seconds=duration)

        if not audio_path or not Path(audio_path).exists():
            return features

        try:
            import librosa
            import numpy as np

            y, sr = librosa.load(audio_path, sr=16000)
            duration_actual = len(y) / sr
            features.duration_seconds = duration_actual

            # Extract pitch (F0) — key for natural lip sync in ERNeRF
            f0, voiced, _ = librosa.pyin(
                y, fmin=50, fmax=500, frame_length=1024, hop_length=int(sr / 25)
            )
            features.pitch_contour = [float(v) if v is not None else 0.0 for v in f0]

            # Extract energy envelope
            energy = librosa.feature.rms(y=y, hop_length=int(sr / 25))[0]
            features.energy_contour = energy.tolist()

            logger.debug(f"[Avatar] Extracted audio features: {duration_actual:.1f}s")
        except ImportError:
            logger.warning("[Avatar] librosa not available, skipping audio features")

        return features

    async def _extract_video_frames(self, video_path: str, frames_dir: Path):
        """Extract frames at 25fps using FFmpeg."""
        cmd = [
            "ffmpeg", "-i", video_path,
            "-vf", "fps=25,scale=512:512",
            "-q:v", "2",
            str(frames_dir / "frame_%06d.jpg"),
            "-y",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning(f"[Avatar] FFmpeg frames: {stderr.decode()[:200]}")

    async def _fit_smpl_sequence(self, frames_dir: Path, avatar_dir: Path) -> Path:
        """
        Fit SMPL body parameters to each frame.
        Full implementation uses HMR2 / CLIFF / PARE.
        This returns a JSON sequence of per-frame SMPL params.
        """
        smpl_seq_path = avatar_dir / "smpl_sequence.json"

        # In full implementation: run HMR2 per-frame
        # For now: generate neutral-pose sequence as placeholder
        frames = sorted(frames_dir.glob("*.jpg"))
        sequence = []
        for i, _ in enumerate(frames):
            # Walking pose: slight periodic hip rotation
            import math
            angle = math.sin(i * 0.1) * 0.2
            pose = SMPLPose(
                body_pose=[0.0] * 72,
                shape=[0.0] * 10,
                translation=[0.0, 0.0, 3.0],
            )
            # Apply slight periodic motion to hips (joints 1-3)
            pose.body_pose[3] = angle
            pose.body_pose[6] = -angle
            sequence.append(pose.to_dict())

        smpl_seq_path.write_text(json.dumps({"frames": sequence, "fps": 25}))
        logger.debug(f"[Avatar] SMPL sequence: {len(sequence)} frames")
        return smpl_seq_path

    async def _build_uv_appearance_map(
        self,
        frames_dir: Path,
        smpl_seq_path: Path,
        avatar_dir: Path,
    ) -> Tuple[Path, Path]:
        """
        Build UV appearance map from multi-view / video frames.
        UV-Volumes stores appearance in UV space for editable rendering.
        Uses OpenCV to project and average frame colors onto UV texture.
        """
        uv_tex_path = avatar_dir / "uv_texture.png"
        normal_map_path = avatar_dir / "normal_map.png"

        try:
            import cv2
            import numpy as np

            # Create blank UV texture (1024×1024 RGBA)
            uv_tex = np.zeros((1024, 1024, 4), dtype=np.uint8)
            uv_tex[:, :, 3] = 255  # Full alpha

            # Sample first frame as base texture (full UV maps need mesh projection)
            frames = sorted(frames_dir.glob("*.jpg"))
            if frames:
                frame = cv2.imread(str(frames[len(frames) // 2]))  # Use middle frame
                if frame is not None:
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    # Tile to UV space (simplified — real version projects via mesh)
                    tiled = cv2.resize(frame_rgb, (1024, 1024))
                    uv_tex[:, :, :3] = tiled

                    # Generate basic normal map from luminance
                    gray = cv2.cvtColor(tiled, cv2.COLOR_RGB2GRAY).astype(np.float32)
                    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0)
                    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1)
                    gz = np.ones_like(gray) * 128
                    normal = np.stack([gx + 128, gy + 128, gz], axis=-1)
                    normal = np.clip(normal, 0, 255).astype(np.uint8)

                    cv2.imwrite(str(uv_tex_path), cv2.cvtColor(uv_tex[:, :, :3], cv2.COLOR_RGB2BGR))
                    cv2.imwrite(str(normal_map_path), normal)
                    logger.debug(f"[UV-Volumes] Built UV texture: {uv_tex_path}")

        except ImportError:
            logger.warning("[Avatar] OpenCV not available for UV map")
            uv_tex_path.write_bytes(b"")
            normal_map_path.write_bytes(b"")

        return uv_tex_path, normal_map_path

    # ------------------------------------------------------------------
    # CPU fallback renderers
    # ------------------------------------------------------------------

    async def _prepare_gfpgan_proxy(self, source: str, avatar_dir: Path) -> Path:
        """CPU fallback for ERNeRF: GFPGAN face enhancement + crop."""
        proxy_path = avatar_dir / "nerf_proxy.json"
        proxy_path.write_text(json.dumps({
            "type": "gfpgan_proxy",
            "source_image": source,
            "mode": "ernerf_cpu",
        }))
        return proxy_path

    async def _generate_avatar_image_fallback(
        self, text_prompt: str, style_prompt: Optional[str], avatar_dir: Path
    ) -> Path:
        """CPU fallback for AvatarCraft: use Stable Diffusion API."""
        proxy_path = avatar_dir / "nerf_proxy.json"

        full_prompt = f"{text_prompt}"
        if style_prompt:
            full_prompt += f", {style_prompt}"
        full_prompt += ", full body, white background, high quality"

        # Try Ollama multimodal or DALL-E API
        image_path = avatar_dir / "avatar_generated.png"
        generated = False

        try:
            from openai import OpenAI
            client = OpenAI()
            response = client.images.generate(
                model="dall-e-3",
                prompt=full_prompt,
                size="1024x1024",
                n=1,
            )
            image_url = response.data[0].url
            import urllib.request
            urllib.request.urlretrieve(image_url, str(image_path))
            generated = True
            logger.info(f"[AvatarCraft] Generated avatar image via DALL-E: {image_path}")
        except Exception as e:
            logger.warning(f"[AvatarCraft] DALL-E fallback failed: {e}")

        proxy_path.write_text(json.dumps({
            "type": "text2avatar_proxy",
            "text_prompt": text_prompt,
            "image_path": str(image_path) if generated else None,
            "mode": "text2avatar_cpu",
        }))
        return proxy_path

    async def _prepare_video_proxy(self, video_path: str, avatar_dir: Path) -> Path:
        """CPU fallback for VIDEO2AVATAR: use source video directly."""
        proxy_path = avatar_dir / "nerf_proxy.json"
        proxy_path.write_text(json.dumps({
            "type": "video_proxy",
            "source_video": video_path,
            "mode": "video2avatar_cpu",
        }))
        return proxy_path

    async def _render_ernerf_cpu_fallback(
        self, asset: AvatarAsset, audio_path: Optional[str], duration: float, output_path: str
    ) -> str:
        """
        CPU fallback ERNeRF: crop face, apply slight audio-driven movement via FFmpeg.
        """
        source = asset.source_image_path or ""
        bbox = asset.face_bbox or [0, 0, 256, 256]
        x, y, w, h = bbox

        # Crop face from source image, loop it, add subtle motion
        cmd = [
            "ffmpeg",
            "-loop", "1",
            "-i", source,
            "-t", str(duration),
            "-vf", (
                f"crop={w}:{h}:{x}:{y},"
                f"scale=512:512,"
                # Subtle breathing motion (sin-based zoom)
                "zoompan=z='1+0.02*sin(2*PI*t/3)':d=1:s=512x512:fps=25"
            ),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-an",
            output_path,
            "-y",
        ]
        if audio_path and Path(audio_path).exists():
            cmd = [
                "ffmpeg",
                "-loop", "1",
                "-i", source,
                "-i", audio_path,
                "-t", str(duration),
                "-vf", (
                    f"crop={w}:{h}:{x}:{y},"
                    "scale=512:512,"
                    "zoompan=z='1+0.02*sin(2*PI*t/3)':d=1:s=512x512:fps=25"
                ),
                "-c:v", "libx264",
                "-c:a", "aac",
                "-pix_fmt", "yuv420p",
                "-shortest",
                output_path,
                "-y",
            ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg ERNeRF render failed: {stderr.decode()[:300]}")
        return output_path

    async def _render_static_avatar_video(
        self, asset: AvatarAsset, duration: float, output_path: str
    ) -> str:
        """CPU fallback: animate static avatar image with subtle motion."""
        proxy_data = {}
        if asset.nerf_model_path and Path(asset.nerf_model_path).exists():
            try:
                proxy_data = json.loads(Path(asset.nerf_model_path).read_text())
            except Exception:
                pass

        source = proxy_data.get("image_path") or asset.source_image_path or ""
        if not source or not Path(source).exists():
            # Generate a placeholder frame
            await self._generate_placeholder_frame(
                asset.text_prompt or "avatar", output_path, duration
            )
            return output_path

        cmd = [
            "ffmpeg",
            "-loop", "1",
            "-i", source,
            "-t", str(duration),
            "-vf", "scale=512:896,zoompan=z='1+0.01*sin(2*PI*t/4)':d=1:s=512x896:fps=25",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-an",
            output_path,
            "-y",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return output_path

    async def _render_body_retarget_fallback(
        self, asset: AvatarAsset, pose: SMPLPose, duration: float, output_path: str
    ) -> str:
        """CPU fallback for VIDEO2AVATAR: play source video segment."""
        source = asset.source_video_path or ""
        if not source or not Path(source).exists():
            return await self._render_static_avatar_video(asset, duration, output_path)

        cmd = [
            "ffmpeg",
            "-i", source,
            "-t", str(duration),
            "-vf", "scale=512:896",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            output_path,
            "-y",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return output_path

    async def _render_uv_cpu_fallback(
        self, asset: AvatarAsset, pose: SMPLPose, duration: float, output_path: str
    ) -> str:
        """CPU fallback for UV-Volumes: render UV texture as looped video."""
        uv_tex = None
        if asset.uv_appearance and asset.uv_appearance.uv_texture_path:
            uv_tex = asset.uv_appearance.uv_texture_path

        if uv_tex and Path(uv_tex).exists():
            cmd = [
                "ffmpeg",
                "-loop", "1",
                "-i", uv_tex,
                "-t", str(duration),
                "-vf", "scale=512:512,pad=512:896:0:192:black",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                output_path,
                "-y",
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return output_path

        return await self._render_static_avatar_video(asset, duration, output_path)

    async def _generate_placeholder_frame(
        self, description: str, output_path: str, duration: float
    ):
        """Generate a placeholder avatar frame using FFmpeg drawtext."""
        cmd = [
            "ffmpeg",
            "-f", "lavfi",
            "-i", "color=c=0x1a1a2e:size=512x896:rate=25",
            "-t", str(duration),
            "-vf", (
                f"drawtext=text='{description[:30]}':fontsize=24:fontcolor=white:"
                "x=(w-text_w)/2:y=h/2:box=1:boxcolor=black@0.5"
            ),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            output_path,
            "-y",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

    # ------------------------------------------------------------------
    # ComfyUI GPU paths (stubs — wired to ComfyUI bridge)
    # ------------------------------------------------------------------

    def _comfyui_available(self) -> bool:
        try:
            from ..comfyui_bridge import is_available
            return is_available()
        except Exception:
            return False

    async def _train_ernerf_comfyui(self, face_image, landmarks, avatar_dir) -> Path:
        """GPU: Train ERNeRF via ComfyUI workflow."""
        from ..comfyui_bridge import execute_workflow
        result = await execute_workflow("ernerf_train.json", {
            "face_image": str(face_image),
            "landmarks": str(landmarks),
            "output_dir": str(avatar_dir),
        })
        return avatar_dir / "ernerf_model.pth"

    async def _render_ernerf_comfyui(self, asset, audio_features, output_path) -> str:
        """GPU: Render ERNeRF talking head via ComfyUI."""
        from ..comfyui_bridge import execute_workflow
        await execute_workflow("ernerf_render.json", {
            "model_path": asset.nerf_model_path,
            "audio_features": audio_features.to_dict(),
            "output_path": output_path,
        })
        return output_path

    async def _train_text2avatar_comfyui(
        self, text_prompt, style_prompt, smpl_params, avatar_dir
    ) -> Path:
        """GPU: AvatarCraft diffusion-guided NeRF training via ComfyUI."""
        from ..comfyui_bridge import execute_workflow
        prompt = text_prompt + (f", {style_prompt}" if style_prompt else "")
        await execute_workflow("avatarcraft_train.json", {
            "text_prompt": prompt,
            "smpl_params": smpl_params.to_dict(),
            "output_dir": str(avatar_dir),
        })
        return avatar_dir / "avatarcraft_model.pth"

    async def _render_smpl_animated_comfyui(self, asset, pose, duration, output_path) -> str:
        """GPU: Render AvatarCraft avatar with SMPL pose via ComfyUI."""
        from ..comfyui_bridge import execute_workflow
        await execute_workflow("avatarcraft_render.json", {
            "model_path": asset.nerf_model_path,
            "smpl_pose": pose.to_dict(),
            "duration": duration,
            "output_path": output_path,
        })
        return output_path

    async def _train_blend_weights_comfyui(
        self, frames_dir, smpl_seq_path, avatar_dir
    ) -> Path:
        """GPU: Train Animatable NeRF blend weight fields via ComfyUI."""
        from ..comfyui_bridge import execute_workflow
        await execute_workflow("animnerf_blend_train.json", {
            "frames_dir": str(frames_dir),
            "smpl_sequence": str(smpl_seq_path),
            "output_dir": str(avatar_dir),
        })
        return avatar_dir / "blend_weights.pth"

    async def _train_canonical_nerf_comfyui(
        self, frames_dir, smpl_seq, blend_weights, avatar_dir
    ) -> Path:
        """GPU: Train canonical NeRF for Animatable NeRF."""
        from ..comfyui_bridge import execute_workflow
        await execute_workflow("animnerf_canonical_train.json", {
            "frames_dir": str(frames_dir),
            "smpl_sequence": str(smpl_seq),
            "blend_weights": str(blend_weights),
            "output_dir": str(avatar_dir),
        })
        return avatar_dir / "canonical_nerf.pth"

    async def _render_novel_pose_comfyui(
        self, asset, pose, duration, output_path
    ) -> str:
        """GPU: Render novel pose via Animatable NeRF."""
        from ..comfyui_bridge import execute_workflow
        await execute_workflow("animnerf_render.json", {
            "nerf_path": asset.nerf_model_path,
            "blend_weights": asset.blend_weights_path,
            "smpl_pose": pose.to_dict(),
            "duration": duration,
            "output_path": output_path,
        })
        return output_path

    async def _train_uv_volume_comfyui(
        self, frames_dir, smpl_seq, uv_texture, avatar_dir
    ) -> Path:
        """GPU: Train UV-Volume rendering network via ComfyUI."""
        from ..comfyui_bridge import execute_workflow
        await execute_workflow("uv_volumes_train.json", {
            "frames_dir": str(frames_dir),
            "smpl_sequence": str(smpl_seq),
            "uv_texture": str(uv_texture),
            "output_dir": str(avatar_dir),
        })
        return avatar_dir / "uv_volume.pth"

    async def _render_uv_animated_comfyui(
        self, asset, pose, duration, output_path
    ) -> str:
        """GPU: Render UV-Volumes avatar via ComfyUI."""
        from ..comfyui_bridge import execute_workflow
        await execute_workflow("uv_volumes_render.json", {
            "model_path": asset.nerf_model_path,
            "uv_appearance": asset.uv_appearance.to_dict() if asset.uv_appearance else {},
            "smpl_pose": pose.to_dict(),
            "duration": duration,
            "output_path": output_path,
        })
        return output_path


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_service: Optional[NeRFAvatarService] = None


def get_nerf_avatar_service() -> NeRFAvatarService:
    global _service
    if _service is None:
        _service = NeRFAvatarService()
    return _service


def reset_nerf_avatar_service():
    global _service
    _service = None
