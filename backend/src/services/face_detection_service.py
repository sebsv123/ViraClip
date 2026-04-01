"""
Face Detection Service - Crop 9:16 dinámico con MediaPipe
Sigue la cara del speaker para mantenerla centrada en el reencuadre vertical
"""
import logging
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from pathlib import Path
import subprocess
import json

logger = logging.getLogger(__name__)

# Intentar importar MediaPipe
try:
    import mediapipe as mp
    MEDIAPIPE_AVAILABLE = True
    
    # Intentar importar solutions de diferentes formas según la versión
    try:
        mp_face_detection = mp.solutions.face_detection
        mp_drawing = mp.solutions.drawing_utils
    except AttributeError:
        # Versión nueva de MediaPipe
        try:
            from mediapipe.tasks.python.vision import FaceDetector
            mp_face_detection = None  # Usar FaceDetector en lugar de solutions
            mp_drawing = None
        except ImportError:
            mp_face_detection = None
            mp_drawing = None
except ImportError:
    MEDIAPIPE_AVAILABLE = False
    mp_face_detection = None
    mp_drawing = None
    logger.warning("MediaPipe not available. Face detection disabled.")


try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    cv2 = None


@dataclass
class FaceBox:
    """Bounding box de una cara detectada"""
    x: float  # Normalizado 0-1
    y: float
    width: float
    height: float
    confidence: float
    
    def center(self) -> Tuple[float, float]:
        """Devuelve centro de la caja (x, y) normalizado"""
        return (self.x + self.width / 2, self.y + self.height / 2)


@dataclass
class CropRegion:
    """Región de recorte para 9:16"""
    x: int  # Píxeles
    y: int
    width: int
    height: int
    target_aspect_ratio: float = 9 / 16


class FaceDetectionService:
    """
    Servicio de detección de caras para crop 9:16 dinámico
    Usa MediaPipe para seguir al speaker y mantenerlo centrado
    """
    
    def __init__(self, detection_confidence: float = 0.5):
        self.confidence = detection_confidence
        self.available = MEDIAPIPE_AVAILABLE and CV2_AVAILABLE
        
        if self.available:
            self.face_detection = mp_face_detection.FaceDetection(
                min_detection_confidence=detection_confidence
            )
            logger.info("✓ Face Detection Service initialized (MediaPipe)")
        else:
            logger.warning("⚠ Face Detection Service unavailable")
    
    def detect_faces_in_frame(self, frame) -> List[FaceBox]:
        """
        Detecta caras en un frame
        
        Args:
            frame: Frame de OpenCV (numpy array)
            
        Returns:
            Lista de FaceBox detectadas
        """
        if not self.available or frame is None:
            return []
        
        # Convertir BGR a RGB
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        # Procesar
        results = self.face_detection.process(rgb_frame)
        
        faces = []
        if results.detections:
            h, w = frame.shape[:2]
            
            for detection in results.detections:
                confidence = detection.score[0] if detection.score else 0.0
                
                if confidence < self.confidence:
                    continue
                
                bbox = detection.location_data.relative_bounding_box
                
                # Convertir a coordenadas normalizadas
                face = FaceBox(
                    x=bbox.xmin,
                    y=bbox.ymin,
                    width=bbox.width,
                    height=bbox.height,
                    confidence=confidence
                )
                faces.append(face)
        
        return faces
    
    def detect_faces_in_video(
        self,
        video_path: str,
        sample_rate: int = 5  # Analizar 1 de cada N frames
    ) -> List[Dict]:
        """
        Detecta caras en múltiples frames del video
        
        Args:
            video_path: Ruta al video
            sample_rate: Muestrear 1 de cada N frames
            
        Returns:
            Lista de detecciones con timestamp
        """
        if not self.available:
            return []
        
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.error(f"Cannot open video: {video_path}")
            return []
        
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        detections = []
        frame_count = 0
        
        logger.info(f"Analyzing {total_frames} frames for face detection...")
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            # Muestrear
            if frame_count % sample_rate == 0:
                faces = self.detect_faces_in_frame(frame)
                timestamp = frame_count / fps
                
                if faces:
                    # Usar la cara más grande (probablemente el speaker principal)
                    main_face = max(faces, key=lambda f: f.width * f.height)
                    
                    detections.append({
                        "timestamp": timestamp,
                        "frame": frame_count,
                        "face": main_face,
                        "num_faces": len(faces)
                    })
            
            frame_count += 1
        
        cap.release()
        
        logger.info(f"Found faces in {len(detections)} frames")
        return detections
    
    def calculate_optimal_crop_region(
        self,
        video_width: int,
        video_height: int,
        target_aspect: float = 9 / 16,
        face_tracks: List[Dict] = None
    ) -> CropRegion:
        """
        Calcula región de crop 9:16 manteniendo la cara centrada
        
        Args:
            video_width: Ancho del video original
            video_height: Alto del video original
            target_aspect: Ratio objetivo (9/16 para vertical)
            face_tracks: Tracks de caras detectadas
            
        Returns:
            CropRegion con coordenadas
        """
        # Calcular dimensiones del crop
        target_height = video_height
        target_width = int(target_height * target_aspect)
        
        # Si no hay caras, centrar en el video
        if not face_tracks:
            x = (video_width - target_width) // 2
            y = 0
            return CropRegion(
                x=max(0, x),
                y=0,
                width=min(target_width, video_width),
                height=video_height
            )
        
        # Calcular posición promedio de la cara
        centers_x = [t["face"].center()[0] for t in face_tracks]
        avg_center_x = sum(centers_x) / len(centers_x)
        
        # Convertir a píxeles
        center_x_px = int(avg_center_x * video_width)
        
        # Centrar el crop en la cara
        crop_x = center_x_px - (target_width // 2)
        
        # Asegurar que no salimos del video
        crop_x = max(0, min(crop_x, video_width - target_width))
        
        return CropRegion(
            x=crop_x,
            y=0,
            width=target_width,
            height=video_height
        )
    
    def generate_ffmpeg_crop_filter(
        self,
        video_path: str,
        target_aspect: float = 9 / 16
    ) -> str:
        """
        Genera filtro FFmpeg para crop dinámico basado en face detection
        
        Args:
            video_path: Video a analizar
            target_aspect: Ratio objetivo
            
        Returns:
            String del filtro FFmpeg (ej: "crop=608:1080:336:0")
        """
        if not self.available:
            # Fallback: crop al centro
            return "crop=iw*9/16:ih:(iw-ow)/2:0"
        
        # Detectar caras en el video
        face_tracks = self.detect_faces_in_video(video_path, sample_rate=10)
        
        # Obtener dimensiones del video
        cap = cv2.VideoCapture(video_path)
        video_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        video_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        
        # Calcular región óptima
        crop = self.calculate_optimal_crop_region(
            video_width, video_height, target_aspect, face_tracks
        )
        
        # Asegurar valores pares (requerido por algunos codecs)
        crop.width = crop.width // 2 * 2
        crop.height = crop.height // 2 * 2
        crop.x = crop.x // 2 * 2
        crop.y = crop.y // 2 * 2
        
        logger.info(f"Crop region: {crop.width}x{crop.height} @ ({crop.x}, {crop.y})")
        
        return f"crop={crop.width}:{crop.height}:{crop.x}:{crop.y}"
    
    def create_dynamic_crop_video(
        self,
        input_path: str,
        output_path: str,
        target_resolution: str = "1080x1920"
    ) -> bool:
        """
        Crea video con crop 9:16 dinámico siguiendo la cara
        
        Args:
            input_path: Video de entrada (16:9)
            output_path: Video de salida (9:16)
            target_resolution: Resolución objetivo
            
        Returns:
            True si éxito
        """
        try:
            # Obtener filtro de crop
            crop_filter = self.generate_ffmpeg_crop_filter(input_path)
            
            # Escalar a resolución objetivo
            width, height = target_resolution.split("x")
            scale_filter = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
            
            # Combinar filtros
            full_filter = f"{crop_filter},{scale_filter}"
            
            cmd = [
                "ffmpeg", "-y",
                "-i", input_path,
                "-vf", full_filter,
                "-c:v", "libx264",
                "-crf", "23",
                "-preset", "fast",
                "-c:a", "copy",
                "-movflags", "+faststart",
                output_path
            ]
            
            subprocess.run(cmd, capture_output=True, check=True)
            logger.info(f"✓ Dynamic crop video created: {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create dynamic crop: {e}")
            return False


class SimpleFaceTracker:
    """
    Tracker simple de cara para transiciones suaves
    Mantiene historial de posiciones para evitar saltos bruscos
    """
    
    def __init__(self, smooth_factor: float = 0.3):
        self.smooth_factor = smooth_factor
        self.last_center: Optional[Tuple[float, float]] = None
    
    def smooth_center(
        self,
        new_center: Tuple[float, float]
    ) -> Tuple[float, float]:
        """
        Suaviza la transición entre posiciones de cara
        """
        if self.last_center is None:
            self.last_center = new_center
            return new_center
        
        # Interpolación lineal
        smoothed_x = (
            self.last_center[0] * (1 - self.smooth_factor) +
            new_center[0] * self.smooth_factor
        )
        smoothed_y = (
            self.last_center[1] * (1 - self.smooth_factor) +
            new_center[1] * self.smooth_factor
        )
        
        self.last_center = (smoothed_x, smoothed_y)
        return self.last_center


# Funciones de conveniencia
def get_face_centered_crop_filter(video_path: str) -> str:
    """
    Función simple para obtener filtro de crop centrado en cara
    
    Example:
        filter_str = get_face_centered_crop_filter("input.mp4")
        # Usar en FFmpeg: ffmpeg -i input.mp4 -vf "{filter_str}" output.mp4
    """
    service = FaceDetectionService()
    return service.generate_ffmpeg_crop_filter(video_path)


def crop_to_vertical_with_face_tracking(
    input_path: str,
    output_path: str
) -> bool:
    """
    Función de conveniencia para crop 9:16 con face tracking
    
    Example:
        success = crop_to_vertical_with_face_tracking("wide.mp4", "vertical.mp4")
    """
    service = FaceDetectionService()
    return service.create_dynamic_crop_video(input_path, output_path)
