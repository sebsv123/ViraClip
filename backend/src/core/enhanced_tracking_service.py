"""
Enhanced Object Tracking Service

Multi-subject tracking with dynamic reframing (ReframeAnything-style).
Extends SAM2 face tracking to support:
- Multiple subjects
- Object tracking beyond faces
- Smooth camera movement simulation
- Dynamic subject switching
"""

import asyncio
import logging
import os
from pathlib import Path
from typing import List, Tuple, Optional, Dict
from enum import Enum

logger = logging.getLogger(__name__)


class TrackingMode(str, Enum):
    """Tracking modes."""
    FACE = "face"
    PERSON = "person"
    OBJECT = "object"
    AUTO = "auto"


class EnhancedTrackingService:
    """
    Enhanced tracking with multi-subject support.
    Builds on SAM2 foundation from face_tracking_service.py
    """
    
    def __init__(self):
        self.sam2_enabled = os.environ.get("SAM2_ENABLED", "false").lower() == "true"
        self.tracking_mode = os.environ.get("TRACKING_MODE", "auto")
    
    async def track_subject(
        self,
        video_path: Path,
        start_time: float,
        end_time: float,
        mode: TrackingMode = TrackingMode.AUTO,
        subject_id: Optional[int] = None
    ) -> List[Tuple[float, int, int]]:
        """
        Track subject(s) in video segment.
        
        Args:
            video_path: Video file
            start_time: Segment start
            end_time: Segment end
            mode: Tracking mode (face/person/object/auto)
            subject_id: Specific subject to track (None = primary subject)
            
        Returns:
            List of (time, cx, cy) trajectory points
        """
        if not self.sam2_enabled:
            logger.debug("SAM2 tracking disabled, using static centering")
            return []
        
        try:
            if mode == TrackingMode.FACE or mode == TrackingMode.AUTO:
                # Use existing SAM2 face tracking
                from ..domains.detection.face_tracking_service import track_person_sam2
                return track_person_sam2(video_path, start_time, end_time)
            
            elif mode == TrackingMode.PERSON:
                # Track full person (wider tracking area)
                return await self._track_person_full(video_path, start_time, end_time)
            
            elif mode == TrackingMode.OBJECT:
                # Track arbitrary object
                return await self._track_object(video_path, start_time, end_time, subject_id)
            
            else:
                return []
        
        except Exception as e:
            logger.warning(f"Enhanced tracking failed: {e}")
            return []
    
    async def _track_person_full(
        self,
        video_path: Path,
        start_time: float,
        end_time: float
    ) -> List[Tuple[float, int, int]]:
        """Track full person body (not just face)."""
        try:
            from sam2.build_sam import build_sam2_video_predictor
            import cv2
            import numpy as np
            
            # Use MediaPipe pose detection for initial point
            initial_point = await self._detect_person_center(video_path, start_time)
            
            if initial_point is None:
                return []
            
            # Track using SAM2
            predictor = build_sam2_video_predictor(
                "sam2_hiera_tiny.yaml",
                "/app/models/sam2/sam2.1_hiera_tiny.pt"
            )
            
            cap = cv2.VideoCapture(str(video_path))
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            start_frame = int(start_time * fps)
            end_frame = int(end_time * fps)
            
            trajectory = []
            
            with predictor.init_state(video_path=str(video_path)) as inference_state:
                predictor.add_new_points_or_box(
                    inference_state,
                    frame_idx=start_frame,
                    obj_id=1,
                    points=np.array([initial_point], dtype=np.float32),
                    labels=np.array([1], dtype=np.int32),
                )
                
                for frame_idx, object_ids, masks in predictor.propagate_in_video(
                    inference_state,
                    start_frame_idx=start_frame,
                    max_frame_num_to_track=(end_frame - start_frame),
                ):
                    t = frame_idx / fps
                    if masks and len(masks) > 0:
                        mask = masks[0].squeeze()
                        ys, xs = np.where(mask > 0.5)
                        if len(xs) > 0:
                            cx = int(xs.mean())
                            cy = int(ys.mean())
                            trajectory.append((t, cx, cy))
            
            cap.release()
            return trajectory
        
        except Exception as e:
            logger.debug(f"Person tracking failed: {e}")
            return []
    
    async def _track_object(
        self,
        video_path: Path,
        start_time: float,
        end_time: float,
        object_id: Optional[int] = None
    ) -> List[Tuple[float, int, int]]:
        """Track arbitrary object (for product demos, text on screen, etc.)."""
        # Placeholder for object tracking
        # Would use object detection (YOLO) + SAM2 tracking
        logger.debug("Object tracking not yet implemented, using face tracking fallback")
        from ..domains.detection.face_tracking_service import track_person_sam2
        return track_person_sam2(video_path, start_time, end_time)
    
    async def _detect_person_center(
        self,
        video_path: Path,
        time: float
    ) -> Optional[Tuple[int, int]]:
        """Detect person center using MediaPipe Pose."""
        try:
            import cv2
            import mediapipe as mp
            
            cap = cv2.VideoCapture(str(video_path))
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            frame_num = int(time * fps)
            
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()
            cap.release()
            
            if not ret:
                return None
            
            h, w = frame.shape[:2]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Use MediaPipe Pose for body center
            with mp.solutions.pose.Pose(
                static_image_mode=True,
                model_complexity=1
            ) as pose:
                results = pose.process(rgb)
                
                if results.pose_landmarks:
                    # Use torso center (average of shoulders and hips)
                    landmarks = results.pose_landmarks.landmark
                    
                    # Shoulders: 11 (left), 12 (right)
                    # Hips: 23 (left), 24 (right)
                    shoulder_x = (landmarks[11].x + landmarks[12].x) / 2
                    shoulder_y = (landmarks[11].y + landmarks[12].y) / 2
                    hip_x = (landmarks[23].x + landmarks[24].x) / 2
                    hip_y = (landmarks[23].y + landmarks[24].y) / 2
                    
                    cx = int((shoulder_x + hip_x) / 2 * w)
                    cy = int((shoulder_y + hip_y) / 2 * h)
                    
                    return (cx, cy)
            
            return None
        
        except Exception as e:
            logger.debug(f"Person detection failed: {e}")
            return None
    
    def smooth_trajectory(
        self,
        trajectory: List[Tuple[float, int, int]],
        smoothing_window: int = 5
    ) -> List[Tuple[float, int, int]]:
        """
        Smooth tracking trajectory to reduce jitter.
        Uses moving average filter.
        
        Args:
            trajectory: Raw trajectory points
            smoothing_window: Window size for moving average
            
        Returns:
            Smoothed trajectory
        """
        if len(trajectory) < smoothing_window:
            return trajectory
        
        smoothed = []
        
        for i in range(len(trajectory)):
            window_start = max(0, i - smoothing_window // 2)
            window_end = min(len(trajectory), i + smoothing_window // 2 + 1)
            
            window = trajectory[window_start:window_end]
            
            avg_cx = sum(p[1] for p in window) / len(window)
            avg_cy = sum(p[2] for p in window) / len(window)
            
            smoothed.append((trajectory[i][0], int(avg_cx), int(avg_cy)))
        
        return smoothed


# Singleton
_enhanced_tracking_instance: Optional[EnhancedTrackingService] = None


def get_enhanced_tracking_service() -> EnhancedTrackingService:
    """Get or create singleton enhanced tracking service."""
    global _enhanced_tracking_instance
    if _enhanced_tracking_instance is None:
        _enhanced_tracking_instance = EnhancedTrackingService()
    return _enhanced_tracking_instance
