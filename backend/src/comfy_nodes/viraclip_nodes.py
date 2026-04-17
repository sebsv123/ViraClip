"""
ViraClip Custom Nodes for ComfyUI
=================================
Integrates ViraClip's viral video pipeline into ComfyUI's nodal workflow system.

Nodes:
- ViraClipWhisperNode: Transcription + virality scoring
- ViraClipYOLONode: Object detection for B-roll keywords  
- ViraClipSilenceRemovalNode: Jump cuts via FFmpeg
- ViraClipThumbnailNode: Smart frame selection
- ViraClipMetadataNode: LLM-generated hashtags/SEO
"""

import os
import sys
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add ViraClip backend to path
VRACLIP_BACKEND = "/app/src"
if VRACLIP_BACKEND not in sys.path:
    sys.path.insert(0, VRACLIP_BACKEND)


class ViraClipWhisperNode:
    """
    ViraClip Whisper Node: Transcribes video audio and scores virality per segment.
    
    Returns: (transcription_text, virality_scores, segments_json)
    """
    
    def __init__(self):
        self.model = None
        self.model_size = "large-v3"
        
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_path": ("STRING", {"default": ""}),
                "model_size": (["tiny", "base", "small", "medium", "large-v3"], {"default": "large-v3"}),
                "device": (["cpu", "cuda"], {"default": "cpu"}),
                "compute_type": (["int8", "float16", "float32"], {"default": "int8"}),
            },
            "optional": {
                "language": ("STRING", {"default": "auto"}),
                "chunk_length": ("INT", {"default": 30, "min": 10, "max": 60}),
            }
        }
    
    RETURN_TYPES = ("STRING", "FLOAT_LIST", "JSON")
    RETURN_NAMES = ("transcription", "virality_scores", "segments")
    FUNCTION = "process"
    CATEGORY = "ViraClip"
    
    def process(self, video_path: str, model_size: str, device: str, 
                compute_type: str, language: str = "auto", chunk_length: int = 30):
        try:
            from faster_whisper import WhisperModel
            import torch
            
            # Lazy load model
            if self.model is None or self.model_size != model_size:
                logger.info(f"Loading Whisper model: {model_size} on {device}")
                self.model_size = model_size
                self.model = WhisperModel(
                    model_size,
                    device=device if torch.cuda.is_available() else "cpu",
                    compute_type=compute_type
                )
            
            # Transcribe
            if not Path(video_path).exists():
                logger.error(f"Video not found: {video_path}")
                return ("", [], json.dumps({"error": "Video not found"}))
            
            segments, info = self.model.transcribe(
                video_path,
                language=None if language == "auto" else language,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
                chunk_length=chunk_length
            )
            
            # Collect segments and score virality
            segment_list = []
            virality_scores = []
            full_text = []
            
            for seg in segments:
                text = seg.text.strip()
                full_text.append(text)
                
                # Simple virality heuristics (matches ViraClip's logic)
                score = self._score_segment_virality(text, seg.words)
                virality_scores.append(score)
                
                segment_list.append({
                    "start": seg.start,
                    "end": seg.end,
                    "text": text,
                    "virality_score": score,
                    "words": [{"word": w.word, "start": w.start, "end": w.end} for w in (seg.words or [])]
                })
            
            result_json = json.dumps({
                "segments": segment_list,
                "language": info.language,
                "language_probability": info.language_probability,
                "duration": sum(s["end"] - s["start"] for s in segment_list)
            }, ensure_ascii=False)
            
            return (" ".join(full_text), virality_scores, result_json)
            
        except Exception as e:
            logger.error(f"ViraClipWhisperNode error: {e}")
            # Fallback: return empty but don't crash workflow
            return ("", [], json.dumps({"error": str(e)}))
    
    def _score_segment_virality(self, text: str, words) -> float:
        """Score virality 0-100 based on text features."""
        score = 50.0  # baseline
        
        # Length factor (optimal: 15-30 words)
        word_count = len(text.split())
        if 15 <= word_count <= 30:
            score += 15
        elif word_count < 10:
            score -= 10
        
        # Hook words bonus
        hook_words = ["secret", "hack", "trick", "revealed", "exposed", "shocking", 
                      "surprising", "unexpected", "finally", "truth", "myth"]
        text_lower = text.lower()
        for word in hook_words:
            if word in text_lower:
                score += 8
        
        # Numbers bonus ("3 ways", "5 tips")
        import re
        if re.search(r'\b\d+\s+(ways?|tips?|secrets?|reasons?|hacks?)', text_lower):
            score += 10
        
        # Question bonus
        if "?" in text:
            score += 5
        
        # Energy words
        energy_words = ["amazing", "incredible", "insane", "mind-blowing", "game-changer",
                        "must-see", "viral", "trending", "breaking"]
        for word in energy_words:
            if word in text_lower:
                score += 7
        
        return min(100.0, max(0.0, score))


class ViraClipYOLONode:
    """
    ViraClip YOLO Node: Detects objects in video frames for B-roll keyword extraction.
    
    Returns: (detected_objects_list, keywords_json)
    """
    
    def __init__(self):
        self.model = None
        
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_path": ("STRING", {"default": ""}),
                "model_size": (["yolov10n", "yolov10s", "yolov10m"], {"default": "yolov10n"}),
                "max_frames": ("INT", {"default": 6, "min": 1, "max": 20}),
                "conf_threshold": ("FLOAT", {"default": 0.35, "min": 0.1, "max": 0.9}),
            }
        }
    
    RETURN_TYPES = ("STRING_LIST", "JSON")
    RETURN_NAMES = ("objects", "detection_data")
    FUNCTION = "process"
    CATEGORY = "ViraClip"
    
    def process(self, video_path: str, model_size: str, max_frames: int, conf_threshold: float):
        try:
            import cv2
            from ultralytics import YOLO
            
            # Lazy load YOLO
            if self.model is None:
                logger.info(f"Loading YOLO model: {model_size}")
                self.model = YOLO(f"{model_size}.pt")
            
            if not Path(video_path).exists():
                return ([], json.dumps({"error": "Video not found"}))
            
            cap = cv2.VideoCapture(video_path)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            step = max(1, total_frames // max_frames)
            
            all_objects = set()
            frame_results = []
            
            for i in range(max_frames):
                frame_idx = i * step
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ret, frame = cap.read()
                if not ret:
                    break
                
                results = self.model(frame, verbose=False)
                frame_objects = []
                
                for r in results:
                    for box in r.boxes:
                        conf = float(box.conf)
                        if conf >= conf_threshold:
                            cls_id = int(box.cls)
                            name = self.model.names[cls_id]
                            all_objects.add(name)
                            frame_objects.append({
                                "class": name,
                                "confidence": conf,
                                "frame": frame_idx
                            })
                
                frame_results.append({"frame": frame_idx, "objects": frame_objects})
            
            cap.release()
            
            # Map to B-roll keywords
            keyword_map = {
                "laptop": "computer work", "cell phone": "smartphone social media",
                "book": "reading study", "cup": "coffee morning", "car": "driving",
                "dog": "dog pet", "cat": "cat pet", "bicycle": "cycling",
                "airplane": "travel airplane", "boat": "ocean boat",
                "chair": "office workspace", "desk": "desk work",
                "keyboard": "typing computer", "mouse": "computer mouse",
                "tv": "television screen", "microwave": "kitchen cooking",
                "refrigerator": "kitchen", "sink": "kitchen sink",
                "person": "person walking", "people": "crowd"
            }
            
            keywords = []
            for obj in all_objects:
                if obj in keyword_map:
                    keywords.append(keyword_map[obj])
                else:
                    keywords.append(obj.replace("_", " "))
            
            result_json = json.dumps({
                "detected_objects": list(all_objects),
                "broll_keywords": keywords,
                "frame_detections": frame_results,
                "total_unique_objects": len(all_objects)
            }, ensure_ascii=False)
            
            return (list(all_objects), result_json)
            
        except Exception as e:
            logger.error(f"ViraClipYOLONode error: {e}")
            return ([], json.dumps({"error": str(e)}))


class ViraClipSilenceRemovalNode:
    """
    ViraClip Silence Removal Node: Removes pauses and filler words via FFmpeg.
    
    Returns: (output_video_path, removed_segments_json)
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_path": ("STRING", {"default": ""}),
                "segments_json": ("JSON", {"default": "{}"}),
                "silence_threshold": ("FLOAT", {"default": 0.4, "min": 0.1, "max": 2.0}),
                "filler_words": ("STRING", {"default": "um,uh,er,like,basically,literally"}),
            },
            "optional": {
                "output_suffix": ("STRING", {"default": "_jumpcut"}),
            }
        }
    
    RETURN_TYPES = ("STRING", "JSON")
    RETURN_NAMES = ("output_video", "removed_segments")
    FUNCTION = "process"
    CATEGORY = "ViraClip"
    
    def process(self, video_path: str, segments_json: str, silence_threshold: float,
                filler_words: str, output_suffix: str = "_jumpcut"):
        try:
            import subprocess
            import json as json_mod
            
            if not Path(video_path).exists():
                return ("", json_mod.dumps({"error": "Video not found"}))
            
            # Parse segments
            try:
                data = json_mod.loads(segments_json) if isinstance(segments_json, str) else segments_json
                segments = data.get("segments", [])
            except:
                segments = []
            
            if not segments:
                return (video_path, json_mod.dumps({"message": "No segments provided, skipping"}))
            
            # Build keep intervals (non-silent parts)
            filler_set = set(filler_words.lower().split(","))
            keep_intervals = []
            removed = []
            
            for seg in segments:
                words = seg.get("words", [])
                seg_start = seg.get("start", 0)
                seg_end = seg.get("end", 0)
                
                # Filter out filler words
                valid_words = [w for w in words if w.get("word", "").lower().strip() not in filler_set]
                
                if valid_words:
                    # Create keep interval
                    keep_start = valid_words[0].get("start", seg_start)
                    keep_end = valid_words[-1].get("end", seg_end)
                    keep_intervals.append((keep_start, keep_end))
                else:
                    removed.append({"start": seg_start, "end": seg_end, "reason": "filler_only"})
            
            # Merge close intervals
            if len(keep_intervals) > 1:
                merged = [keep_intervals[0]]
                for start, end in keep_intervals[1:]:
                    if start - merged[-1][1] <= silence_threshold:
                        merged[-1] = (merged[-1][0], end)
                    else:
                        removed.append({"start": merged[-1][1], "end": start, "reason": "silence"})
                        merged.append((start, end))
                keep_intervals = merged
            
            # Generate output path
            input_path = Path(video_path)
            output_path = input_path.parent / f"{input_path.stem}{output_suffix}{input_path.suffix}"
            
            # Build FFmpeg select filter
            select_parts = [f"between(t,{s:.3f},{e:.3f})" for s, e in keep_intervals]
            select_expr = "+".join(select_parts) if len(select_parts) > 1 else select_parts[0]
            
            cmd = [
                "ffmpeg", "-y", "-i", video_path,
                "-vf", f"select='{select_expr}',setpts=N/FRAME_RATE/TB",
                "-af", f"aselect='{select_expr}',asetpts=N/SR/TB",
                "-c:v", "libx264", "-preset", "fast", "-crf", "22",
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                str(output_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0 or not output_path.exists():
                logger.error(f"FFmpeg failed: {result.stderr}")
                return (video_path, json_mod.dumps({"error": "FFmpeg failed", "stderr": result.stderr}))
            
            removed_json = json_mod.dumps({
                "removed_segments": removed,
                "kept_intervals": keep_intervals,
                "original_duration": sum(seg.get("end", 0) - seg.get("start", 0) for seg in segments),
                "output_path": str(output_path)
            })
            
            return (str(output_path), removed_json)
            
        except Exception as e:
            logger.error(f"ViraClipSilenceRemovalNode error: {e}")
            return (video_path, json.dumps({"error": str(e)}))


class ViraClipThumbnailNode:
    """
    ViraClip Thumbnail Node: Selects best frame using sharpness + face detection.
    
    Returns: (thumbnail_path, score_data_json)
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_path": ("STRING", {"default": ""}),
                "n_candidates": ("INT", {"default": 8, "min": 3, "max": 20}),
                "face_bonus": ("FLOAT", {"default": 50.0, "min": 0, "max": 100}),
            },
            "optional": {
                "output_name": ("STRING", {"default": "thumbnail.jpg"}),
            }
        }
    
    RETURN_TYPES = ("STRING", "JSON")
    RETURN_NAMES = ("thumbnail_path", "frame_scores")
    FUNCTION = "process"
    CATEGORY = "ViraClip"
    
    def process(self, video_path: str, n_candidates: int, face_bonus: float, output_name: str = "thumbnail.jpg"):
        try:
            import cv2
            import numpy as np
            
            if not Path(video_path).exists():
                return ("", json.dumps({"error": "Video not found"}))
            
            cap = cv2.VideoCapture(video_path)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            
            # Skip first/last 5%
            skip_start = int(total_frames * 0.05)
            skip_end = int(total_frames * 0.95)
            usable = max(1, skip_end - skip_start)
            step = max(1, usable // n_candidates)
            
            best_frame = None
            best_score = -1
            frame_scores = []
            
            # Try to import mediapipe for face detection
            try:
                import mediapipe as mp
                mp_face = mp.solutions.face_detection
                face_detector = mp_face.FaceDetection(model_selection=0, min_detection_confidence=0.4)
            except:
                face_detector = None
            
            for i in range(n_candidates):
                idx = skip_start + i * step
                cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ret, frame = cap.read()
                if not ret:
                    continue
                
                # Score: Laplacian variance (sharpness)
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
                
                score = laplacian_var
                has_face = False
                
                # Face bonus
                if face_detector:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    results = face_detector.process(rgb)
                    if results.detections:
                        score += face_bonus
                        has_face = True
                
                # Brightness penalty
                mean_lum = gray.mean()
                if mean_lum < 40 or mean_lum > 220:
                    score -= 20
                
                frame_scores.append({
                    "frame_idx": idx,
                    "timestamp": idx / fps,
                    "sharpness": laplacian_var,
                    "face_detected": has_face,
                    "final_score": score
                })
                
                if score > best_score:
                    best_score = score
                    best_frame = frame
            
            cap.release()
            
            if best_frame is None:
                return ("", json.dumps({"error": "Could not extract frames"}))
            
            # Save thumbnail
            input_path = Path(video_path)
            output_path = input_path.parent / output_name
            cv2.imwrite(str(output_path), best_frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            
            result_json = json.dumps({
                "selected_frame": next((f for f in frame_scores if f["final_score"] == best_score), {}),
                "all_scores": frame_scores,
                "total_frames": total_frames,
                "thumbnail_path": str(output_path)
            })
            
            return (str(output_path), result_json)
            
        except Exception as e:
            logger.error(f"ViraClipThumbnailNode error: {e}")
            return ("", json.dumps({"error": str(e)}))


class ViraClipMetadataNode:
    """
    ViraClip Metadata Node: Generates SEO title, description, and hashtags using LLM.
    
    Returns: (title, description, hashtags_list, metadata_json)
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "transcription": ("STRING", {"default": "", "multiline": True}),
                "platform": (["tiktok", "reels", "shorts", "universal"], {"default": "tiktok"}),
                "llm_provider": (["ollama", "openai", "groq"], {"default": "ollama"}),
            },
            "optional": {
                "custom_prompt": ("STRING", {"default": "", "multiline": True}),
            }
        }
    
    RETURN_TYPES = ("STRING", "STRING", "STRING_LIST", "JSON")
    RETURN_NAMES = ("title", "description", "hashtags", "metadata_json")
    FUNCTION = "process"
    CATEGORY = "ViraClip"
    
    def process(self, transcription: str, platform: str, llm_provider: str, custom_prompt: str = ""):
        try:
            import requests
            import json as json_mod
            
            # Platform-specific hashtag counts
            hashtag_limits = {"tiktok": 30, "reels": 20, "shorts": 15, "universal": 20}
            max_hashtags = hashtag_limits.get(platform, 20)
            
            # Build prompt
            if custom_prompt:
                prompt = custom_prompt
            else:
                prompt = f"""Generate viral metadata for a {platform} video.

Transcript: {transcription[:500]}

Create:
1. A punchy SEO title (max 60 chars, no hashtags)
2. A hook description (1-2 sentences, max 150 chars)  
3. Exactly {max_hashtags} relevant hashtags (without # prefix)

Respond ONLY with valid JSON:
{{"title": "...", "description": "...", "hashtags": ["tag1", "tag2", ...]}}"""
            
            # Call LLM based on provider
            response_text = ""
            
            if llm_provider == "ollama":
                try:
                    resp = requests.post(
                        "http://ollama:11434/api/generate",
                        json={
                            "model": "llama3.2",
                            "prompt": prompt,
                            "stream": False,
                            "options": {"temperature": 0.4, "num_predict": 300}
                        },
                        timeout=30
                    )
                    if resp.status_code == 200:
                        response_text = resp.json().get("response", "")
                except Exception as e:
                    logger.warning(f"Ollama call failed: {e}")
            
            # Parse response
            try:
                # Extract JSON from response
                text = response_text.strip()
                if "```json" in text:
                    text = text.split("```json")[1].split("```")[0]
                elif "```" in text:
                    text = text.split("```")[1].split("```")[0]
                
                data = json_mod.loads(text.strip())
                title = str(data.get("title", "Viral Clip"))[:60]
                description = str(data.get("description", transcription[:150]))[:150]
                hashtags = [str(h).lstrip("#") for h in data.get("hashtags", [])][:max_hashtags]
                
            except:
                # Fallback: generate from transcript
                title = " ".join(transcription.split()[:6])[:60] or "Viral Clip"
                description = transcription[:150]
                words = [w.lower() for w in transcription.split() if len(w) > 3][:max_hashtags]
                platform_tags = {"tiktok": ["tiktok", "viral", "fyp"], "reels": ["reels", "viral"], 
                               "shorts": ["shorts", "viral"], "universal": ["viral"]}
                hashtags = list(dict.fromkeys(words + platform_tags.get(platform, ["viral"])))[:max_hashtags]
            
            metadata_json = json_mod.dumps({
                "title": title,
                "description": description,
                "hashtags": hashtags,
                "platform": platform,
                "llm_provider": llm_provider,
                "hashtag_count": len(hashtags)
            }, ensure_ascii=False)
            
            return (title, description, hashtags, metadata_json)
            
        except Exception as e:
            logger.error(f"ViraClipMetadataNode error: {e}")
            fallback_title = transcription[:50] or "Viral Clip"
            return (fallback_title, transcription[:150], ["viral"], json.dumps({"error": str(e)}))


class ViraClipQuantumNode:
    """
    ComfyUI Node: Quantum-Inspired Virality Simulator (Phase 8.1)
    
    Simulates 100+ parallel viral universes with different hook configurations
    to find optimal virality patterns.
    """
    
    def __init__(self):
        self.simulator = None
        
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "transcription": ("STRING", {"multiline": True}),
                "duration": ("FLOAT", {"default": 60.0, "min": 15.0, "max": 300.0}),
                "platform": (["tiktok", "reels", "shorts", "universal"], {"default": "tiktok"}),
            },
            "optional": {
                "num_universes": ("INT", {"default": 100, "min": 20, "max": 500}),
            }
        }
    
    RETURN_TYPES = ("JSON", "FLOAT", "STRING")
    RETURN_NAMES = ("top_variants", "diversity_score", "best_recommendations")
    FUNCTION = "simulate_quantum"
    CATEGORY = "ViraClip/Advanced ML"
    
    def simulate_quantum(self, transcription, duration=60.0, platform="tiktok", num_universes=100):
        """Run quantum-inspired virality simulation."""
        try:
            import asyncio
            from src.services.quantum_virality_simulator import QuantumViralitySimulator
            
            if self.simulator is None:
                self.simulator = QuantumViralitySimulator()
            
            clip_features = {
                "text": transcription,
                "duration": duration,
            }
            
            result = asyncio.run(self.simulator.simulate_parallel_universes(
                clip_features,
                num_universes=num_universes,
            ))
            
            top_variants = result.get("top_variants", [])
            diversity = result.get("diversity_score", 0.0)
            
            # Build recommendations string
            if top_variants:
                best = top_variants[0]
                recs = " | ".join(best.get("recommendations", []))
            else:
                recs = "No recommendations available"
            
            return (json.dumps(top_variants), diversity, recs)
            
        except Exception as e:
            logger.error(f"ViraClipQuantumNode error: {e}")
            return (json.dumps({"error": str(e)}), 0.0, "Simulation failed")


class ViraClipEvolutionNode:
    """
    ComfyUI Node: Swarm Evolution Viral Engine (Phase 8.2)
    
    Uses genetic algorithms to evolve clip variants through selection,
    crossover, and mutation over multiple generations.
    """
    
    def __init__(self):
        self.engine = None
        
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "transcription": ("STRING", {"multiline": True}),
                "content_type": (["educational", "entertainment", "promotional"], {"default": "entertainment"}),
            },
            "optional": {
                "population_size": ("INT", {"default": 50, "min": 20, "max": 100}),
                "generations": ("INT", {"default": 10, "min": 5, "max": 20}),
            }
        }
    
    RETURN_TYPES = ("JSON", "JSON", "STRING")
    RETURN_NAMES = ("top_survivors", "fitness_progression", "implementation_guide")
    FUNCTION = "evolve_genome"
    CATEGORY = "ViraClip/Advanced ML"
    
    def evolve_genome(self, transcription, content_type="entertainment", population_size=50, generations=10):
        """Run swarm evolution on clip genome."""
        try:
            import asyncio
            from src.services.swarm_evolution_engine import SwarmEvolutionEngine
            
            if self.engine is None:
                self.engine = SwarmEvolutionEngine()
            
            clip_features = {
                "text": transcription,
                "duration": 60.0,
            }
            
            result = asyncio.run(self.engine.evolve_viral_clip(
                clip_features,
                population_size=population_size,
                generations=generations,
                content_type=content_type,
            ))
            
            top_survivors = result.get("top_survivors", [])
            progression = result.get("fitness_progression", {})
            
            # Build implementation guide
            if top_survivors:
                best = top_survivors[0]
                guide = "\n".join(best.get("implementation_guide", []))
            else:
                guide = "No guide available"
            
            return (json.dumps(top_survivors), json.dumps(progression), guide)
            
        except Exception as e:
            logger.error(f"ViraClipEvolutionNode error: {e}")
            return (json.dumps({"error": str(e)}), json.dumps({}), "Evolution failed")


# Node class mappings for ComfyUI
NODE_CLASS_MAPPINGS = {
    "ViraClipWhisperNode": ViraClipWhisperNode,
    "ViraClipYOLONode": ViraClipYOLONode,
    "ViraClipSilenceRemovalNode": ViraClipSilenceRemovalNode,
    "ViraClipThumbnailNode": ViraClipThumbnailNode,
    "ViraClipMetadataNode": ViraClipMetadataNode,
    "ViraClipQuantumNode": ViraClipQuantumNode,
    "ViraClipEvolutionNode": ViraClipEvolutionNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ViraClipWhisperNode": "ViraClip Whisper + Virality Score",
    "ViraClipYOLONode": "ViraClip YOLO Object Detection",
    "ViraClipSilenceRemovalNode": "ViraClip Jump Cut / Silence Removal",
    "ViraClipThumbnailNode": "ViraClip Smart Thumbnail",
    "ViraClipMetadataNode": "ViraClip Viral Metadata (SEO + Hashtags)",
    "ViraClipQuantumNode": "ViraClip Quantum Virality Sim",
    "ViraClipEvolutionNode": "ViraClip Swarm Evolution",
}

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']
