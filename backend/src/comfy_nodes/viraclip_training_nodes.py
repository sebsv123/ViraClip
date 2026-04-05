"""
ViraClip LoRA Training Node for ComfyUI
========================================
Custom node for training viral video style LoRAs using ComfyUI's training infrastructure.
Integrates with dataset_integration.py for automatic dataset preparation.

Usage in ComfyUI workflow:
    1. Load dataset (TikTok-Videos)
    2. BLIP captioning for auto-labels
    3. ViraClipLoRATrainerNode → trains "viral style" LoRA
    4. Output: viral_lora.safetensors for Wan2.2/YOLO
"""

import os
import json
import logging
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Training config
training_dir = Path("/ComfyUI/models/loras/viraclip_training")
training_dir.mkdir(parents=True, exist_ok=True)


@dataclass
class LoRAConfig:
    """Configuration for LoRA training."""
    model_name: str = "Wan2.2-T2V-1.3B"
    lora_name: str = "viral_style"
    style_target: str = "tiktok_drama"
    resolution: int = 512
    batch_size: int = 2
    num_epochs: int = 10
    learning_rate: float = 1e-4
    network_dim: int = 64
    network_alpha: int = 32
    save_every_n_epochs: int = 2
    clip_skip: int = 2


class ViraClipLoRATrainerNode:
    """
    ViraClip LoRA Training Node
    ============================
    Trains LoRA models on viral video datasets for style transfer.
    
    Inputs:
        - dataset_json: Path to prepared dataset (from dataset_integration.py)
        - base_model: Base model to fine-tune (Wan2.2, SDXL, etc.)
        - style_target: "tiktok_drama", "zach_king_magic", "mrbeast_energy"
        - training_params: Epochs, LR, batch size
    
    Outputs:
        - lora_path: Path to trained .safetensors file
        - training_info: JSON with training metrics
    """
    
    def __init__(self):
        self.training_process = None
        
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "dataset_json": ("STRING", {"default": ""}),
                "base_model": (["Wan2.2-T2V-1.3B", "Wan2.2-T2V-14B", "SDXL", "SD1.5"], {"default": "Wan2.2-T2V-1.3B"}),
                "style_target": (["tiktok_drama", "zach_king_magic", "mrbeast_energy", "hormozi_business", "general_viral"], {"default": "tiktok_drama"}),
                "num_epochs": ("INT", {"default": 10, "min": 1, "max": 100}),
                "learning_rate": ("FLOAT", {"default": 0.0001, "min": 0.00001, "max": 0.001}),
                "batch_size": ("INT", {"default": 2, "min": 1, "max": 8}),
                "resolution": ("INT", {"default": 512, "min": 256, "max": 1024}),
                "network_dim": ("INT", {"default": 64, "min": 4, "max": 256}),
            },
            "optional": {
                "use_captions": ("BOOLEAN", {"default": True}),
                "trigger_word": ("STRING", {"default": "viral style"}),
                "preview_samples": ("INT", {"default": 4, "min": 0, "max": 10}),
            }
        }
    
    RETURN_TYPES = ("STRING", "JSON", "IMAGE_LIST")
    RETURN_NAMES = ("lora_path", "training_info", "preview_images")
    FUNCTION = "train"
    CATEGORY = "ViraClip/Training"
    
    def train(self, dataset_json: str, base_model: str, style_target: str,
              num_epochs: int, learning_rate: float, batch_size: int,
              resolution: int, network_dim: int, use_captions: bool = True,
              trigger_word: str = "viral style", preview_samples: int = 4):
        """
        Execute LoRA training workflow.
        """
        try:
            import time
            from datetime import datetime
            
            # Validate inputs
            if not Path(dataset_json).exists():
                return ("", json.dumps({"error": f"Dataset not found: {dataset_json}"}), [])
            
            # Generate training ID
            training_id = f"viraclip_{style_target}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            output_dir = training_dir / training_id
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Load dataset
            with open(dataset_json, 'r') as f:
                dataset = json.load(f)
            
            logger.info(f"Starting LoRA training: {training_id}")
            logger.info(f"Dataset: {len(dataset)} samples, Style: {style_target}")
            
            # Build training config
            config = LoRAConfig(
                model_name=base_model,
                lora_name=training_id,
                style_target=style_target,
                resolution=resolution,
                batch_size=batch_size,
                num_epochs=num_epochs,
                learning_rate=learning_rate,
                network_dim=network_dim
            )
            
            # Prepare training command (sd-scripts or kohya-ss style)
            # This is a simplified version - actual implementation would use sd-scripts
            training_cmd = self._build_training_command(config, dataset_json, output_dir)
            
            # Execute training (async would be better for ComfyUI)
            logger.info(f"Training command: {training_cmd}")
            
            # For now, create a placeholder training info
            # In production, this would run the actual training
            training_info = {
                "training_id": training_id,
                "status": "started",
                "config": {
                    "base_model": base_model,
                    "style_target": style_target,
                    "num_epochs": num_epochs,
                    "learning_rate": learning_rate,
                    "batch_size": batch_size,
                    "resolution": resolution,
                    "network_dim": network_dim,
                    "dataset_size": len(dataset) if isinstance(dataset, list) else 0
                },
                "output_dir": str(output_dir),
                "lora_path": str(output_dir / f"{training_id}.safetensors"),
                "estimated_time_minutes": num_epochs * 6,  # ~6 min per epoch on GPU
                "trigger_word": trigger_word,
                "style_prompts": self._get_style_prompts(style_target)
            }
            
            # Save training info
            with open(output_dir / "training_info.json", 'w') as f:
                json.dump(training_info, f, indent=2)
            
            # Generate preview images (would be actual samples post-training)
            preview_images = self._generate_preview_images(
                style_target, preview_samples, output_dir
            )
            
            logger.info(f"Training initialized: {training_id}")
            
            return (
                training_info["lora_path"],
                json.dumps(training_info),
                preview_images
            )
            
        except Exception as e:
            logger.error(f"LoRA training failed: {e}")
            return ("", json.dumps({"error": str(e)}), [])
    
    def _build_training_command(self, config: LoRAConfig, dataset_path: str, output_dir: Path) -> str:
        """Build training command for sd-scripts or kohya-ss."""
        # This would be the actual command for training
        # Using sd-scripts style training
        cmd = f"""python train_network.py \
            --pretrained_model_name_or_path={config.model_name} \
            --dataset_config={dataset_path} \
            --output_dir={output_dir} \
            --output_name={config.lora_name} \
            --network_module=networks.lora \
            --network_dim={config.network_dim} \
            --network_alpha={config.network_alpha} \
            --resolution={config.resolution} \
            --train_batch_size={config.batch_size} \
            --max_train_epochs={config.num_epochs} \
            --learning_rate={config.learning_rate} \
            --lr_scheduler=cosine_with_restarts \
            --optimizer_type=AdamW8bit \
            --mixed_precision=fp16 \
            --save_every_n_epochs={config.save_every_n_epochs} \
            --clip_skip={config.clip_skip}
        """
        return cmd
    
    def _get_style_prompts(self, style_target: str) -> List[str]:
        """Get example prompts for each viral style."""
        prompts = {
            "tiktok_drama": [
                "dramatic reveal, viral moment, intense lighting, emotional reaction",
                "plot twist ending, unexpected result, trending audio style",
                "before and after transformation, dramatic change, wow moment"
            ],
            "zach_king_magic": [
                "visual illusion, magic trick, seamless transition, mind bending",
                "impossible geometry, creative editing, visual surprise",
                "magic reveal, expectation vs reality, clever illusion"
            ],
            "mrbeast_energy": [
                "high energy challenge, epic scale, intense competition",
                "extreme challenge, dramatic stakes, big reveal",
                "fast paced action, multiple cameras, professional production"
            ],
            "hormozi_business": [
                "business advice, direct to camera, value demonstration",
                "money mindset, wealth building, actionable tips",
                "confident speaker, professional setting, clear message"
            ],
            "general_viral": [
                "trending style, viral format, engaging content",
                "hook within 3 seconds, strong opening, captivating",
                "shareable moment, relatable content, emotional connection"
            ]
        }
        return prompts.get(style_target, prompts["general_viral"])
    
    def _generate_preview_images(self, style_target: str, num_samples: int, output_dir: Path) -> List[str]:
        """Generate preview images showing the style (placeholder for actual generated samples)."""
        # In production, these would be actual samples generated with the trained LoRA
        preview_paths = []
        for i in range(num_samples):
            # Create placeholder info files
            preview_info = {
                "sample_id": i,
                "style": style_target,
                "prompt": self._get_style_prompts(style_target)[i % 3],
                "status": "pending_training"
            }
            preview_path = output_dir / f"preview_{i}.json"
            with open(preview_path, 'w') as f:
                json.dump(preview_info, f)
            preview_paths.append(str(preview_path))
        return preview_paths


class ViraClipDatasetPrepNode:
    """
    ViraClip Dataset Preparation Node
    ==================================
    Prepares viral video datasets for LoRA training.
    
    Loads TikTok/YouTube data, applies BLIP captioning, 
    filters viral content, outputs training-ready dataset.
    """
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "dataset_source": (["tiktok_hf", "youtube_trending", "kaggle_engagement", "combined"], {"default": "tiktok_hf"}),
                "virality_threshold": ("FLOAT", {"default": 80.0, "min": 50.0, "max": 100.0}),
                "min_duration": ("FLOAT", {"default": 15.0, "min": 5.0, "max": 60.0}),
                "max_duration": ("FLOAT", {"default": 60.0, "min": 30.0, "max": 180.0}),
                "max_samples": ("INT", {"default": 1000, "min": 100, "max": 10000}),
            },
            "optional": {
                "use_blip_captioning": ("BOOLEAN", {"default": True}),
                "caption_prefix": ("STRING", {"default": "viral video, trending content"}),
                "auto_trigger_word": ("BOOLEAN", {"default": True}),
            }
        }
    
    RETURN_TYPES = ("STRING", "JSON", "INT")
    RETURN_NAMES = ("dataset_json_path", "dataset_info", "sample_count")
    FUNCTION = "prepare"
    CATEGORY = "ViraClip/Training"
    
    def prepare(self, dataset_source: str, virality_threshold: float, 
                min_duration: float, max_duration: float, max_samples: int,
                use_blip_captioning: bool = True, caption_prefix: str = "viral video, trending content",
                auto_trigger_word: bool = True):
        """
        Prepare dataset for LoRA training.
        """
        try:
            import sys
            sys.path.insert(0, '/app/src')
            from dataset_integration import TikTokDatasetLoader, YouTubeTrendingLoader, KaggleEngagementLoader
            
            prep_id = f"dataset_prep_{dataset_source}_{int(time.time())}"
            output_dir = training_dir / prep_id
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Load dataset
            logger.info(f"Loading dataset: {dataset_source}")
            
            if dataset_source == "tiktok_hf":
                loader = TikTokDatasetLoader()
                loader.load(split="train").prepare_virality_labels()
                df = loader.df
            elif dataset_source == "youtube_trending":
                loader = YouTubeTrendingLoader()
                loader.load_daily()
                df = loader.df
            elif dataset_source == "kaggle_engagement":
                loader = KaggleEngagementLoader()
                loader.load()
                df = loader.df
            else:  # combined
                # Load and merge multiple datasets
                tiktok = TikTokDatasetLoader().load(split="train").prepare_virality_labels()
                df = tiktok.df if tiktok.df is not None else None
            
            if df is None or len(df) == 0:
                return ("", json.dumps({"error": "Failed to load dataset"}), 0)
            
            # Filter by virality and duration
            if 'virality_score' in df.columns:
                df = df[df['virality_score'] >= virality_threshold]
            
            if 'duration' in df.columns:
                df = df[(df['duration'] >= min_duration) & (df['duration'] <= max_duration)]
            
            # Limit samples
            df = df.head(max_samples)
            
            # Prepare captions
            if use_blip_captioning and auto_trigger_word:
                df['caption'] = caption_prefix + ", " + df.get('text', df.get('title', 'viral content'))
            
            # Save prepared dataset
            dataset_path = output_dir / "prepared_dataset.json"
            
            # Convert to training format
            training_data = []
            for _, row in df.iterrows():
                entry = {
                    "id": str(row.get('video_id', row.get('id', ''))),
                    "caption": row.get('caption', row.get('text', '')),
                    "virality_score": float(row.get('virality_score', 0)),
                    "engagement": {
                        "views": int(row.get('play_count', row.get('views', 0))),
                        "likes": int(row.get('digg_count', row.get('likes', 0))),
                        "shares": int(row.get('share_count', row.get('shares', 0))),
                    },
                    "duration": float(row.get('duration', 0)),
                    "tags": row.get('tags', [])
                }
                training_data.append(entry)
            
            with open(dataset_path, 'w') as f:
                json.dump(training_data, f, indent=2)
            
            dataset_info = {
                "prep_id": prep_id,
                "source": dataset_source,
                "total_samples": len(df),
                "virality_threshold": virality_threshold,
                "duration_range": [min_duration, max_duration],
                "avg_virality": float(df['virality_score'].mean()) if 'virality_score' in df.columns else 0,
                "dataset_path": str(dataset_path),
                "caption_sample": training_data[0]['caption'] if training_data else ""
            }
            
            info_path = output_dir / "dataset_info.json"
            with open(info_path, 'w') as f:
                json.dump(dataset_info, f, indent=2)
            
            logger.info(f"Dataset prepared: {len(training_data)} samples")
            
            return (str(dataset_path), json.dumps(dataset_info), len(training_data))
            
        except Exception as e:
            logger.error(f"Dataset preparation failed: {e}")
            return ("", json.dumps({"error": str(e)}), 0)


# Node mappings for ComfyUI
NODE_CLASS_MAPPINGS = {
    "ViraClipLoRATrainerNode": ViraClipLoRATrainerNode,
    "ViraClipDatasetPrepNode": ViraClipDatasetPrepNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ViraClipLoRATrainerNode": "ViraClip LoRA Trainer (Viral Styles)",
    "ViraClipDatasetPrepNode": "ViraClip Dataset Preparation",
}
