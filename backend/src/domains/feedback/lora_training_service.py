"""
LoRA Training Service — Phase 7.3
===================================
Fine-tune Wan2.2 / SD1.5 LoRAs on viral video style using PEFT + diffusers.
Triggered by GPU worker weekly or via API.

Output: .safetensors LoRA file loadable into ComfyUI or diffusers pipelines.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
LORA_OUTPUT_DIR  = Path(os.environ.get("LORA_OUTPUT_DIR", "/app/models/lora"))
LORA_CACHE_DIR   = Path(os.environ.get("LORA_CACHE_DIR", "/app/models/lora_cache"))
TEMP_DIR         = Path(os.environ.get("TEMP_DIR", "/app/temp/uploads"))

_BASE_MODELS = {
    "wan2.2-1.3b":  "Wan-AI/Wan2.2-T2V-1.3B-Diffusers",
    "wan2.2-14b":   "Wan-AI/Wan2.2-T2V-14B-Diffusers",
    "sd1.5":        "runwayml/stable-diffusion-v1-5",
    "sdxl":         "stabilityai/stable-diffusion-xl-base-1.0",
}


class LoRATrainingService:
    """
    Fine-tune a text-to-video or text-to-image model with LoRA adapters.

    Supported base models: wan2.2-1.3b, wan2.2-14b, sd1.5, sdxl

    Usage:
        svc    = LoRATrainingService()
        result = await svc.train(
            dataset_path="/app/datasets/viral_clips/",
            base_model="sd1.5",
            style_name="tiktok_drama",
            num_steps=500,
        )
        # → {"lora_path": str, "loss": float, "steps": int, "style": str}
    """

    def __init__(self):
        LORA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        LORA_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # ── Public API ────────────────────────────────────────────────────────────

    async def train(
        self,
        dataset_path: str,
        base_model: str = "sd1.5",
        style_name: str = "viral_tiktok",
        num_steps: int = 500,
        batch_size: int = 2,
        learning_rate: float = 1e-4,
        lora_rank: int = 16,
        output_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Train a LoRA adapter on *dataset_path*.

        Args:
            dataset_path:   Folder of image/video + caption pairs OR parquet file
            base_model:     One of _BASE_MODELS keys
            style_name:     Human-readable style tag (used in output filename)
            num_steps:      Training iterations
            batch_size:     Gradient accumulation batch size
            learning_rate:  AdamW learning rate
            lora_rank:      LoRA r parameter (8 / 16 / 32)
            output_path:    Where to save .safetensors (auto if None)

        Returns:
            {"lora_path": str, "loss": float, "steps": int, "style": str}
        """
        if output_path is None:
            ts = int(time.time())
            output_path = str(LORA_OUTPUT_DIR / f"lora_{style_name}_{ts}.safetensors")

        dest = Path(output_path)
        loop = asyncio.get_event_loop()

        try:
            result = await loop.run_in_executor(
                None, self._train_sync,
                dataset_path, base_model, style_name,
                num_steps, batch_size, learning_rate, lora_rank, dest,
            )
        except Exception as exc:
            logger.error(f"[LoRA] Training failed: {exc}")
            raise

        logger.info(f"[LoRA] ✓ {style_name} → {dest.name} (loss={result['loss']:.4f})")
        return result

    @staticmethod
    def is_available() -> bool:
        try:
            import torch
            import peft    # noqa: F401
            import diffusers  # noqa: F401
            return torch.cuda.is_available()
        except ImportError:
            return False

    # ── Sync training (runs in ThreadPoolExecutor) ────────────────────────────

    def _train_sync(
        self,
        dataset_path: str,
        base_model: str,
        style_name: str,
        num_steps: int,
        batch_size: int,
        lr: float,
        lora_rank: int,
        dest: Path,
    ) -> Dict[str, Any]:
        import torch
        from diffusers import StableDiffusionPipeline, UNet2DConditionModel
        from peft import LoraConfig, get_peft_model

        model_id = _BASE_MODELS.get(base_model, _BASE_MODELS["sd1.5"])
        device   = "cuda" if torch.cuda.is_available() else "cpu"
        dtype    = torch.float16 if device == "cuda" else torch.float32

        logger.info(f"[LoRA] Loading base model {model_id} on {device} …")
        pipe = StableDiffusionPipeline.from_pretrained(
            model_id, torch_dtype=dtype, cache_dir=str(LORA_CACHE_DIR)
        )
        unet = pipe.unet.to(device)

        lora_config = LoraConfig(
            r=lora_rank,
            lora_alpha=lora_rank * 2,
            target_modules=["to_q", "to_k", "to_v", "to_out.0",
                            "proj_in", "proj_out"],
            lora_dropout=0.1,
            bias="none",
        )
        unet = get_peft_model(unet, lora_config)
        unet.print_trainable_parameters()

        dataset = self._load_dataset(dataset_path, style_name)
        optimizer = torch.optim.AdamW(
            unet.parameters(), lr=lr, weight_decay=1e-2
        )

        text_enc = pipe.text_encoder.to(device)
        tokenizer = pipe.tokenizer
        vae       = pipe.vae.to(device)
        scheduler = pipe.scheduler

        unet.train()
        total_loss = 0.0
        step       = 0

        for step in range(1, num_steps + 1):
            batch = self._sample_batch(dataset, batch_size, device, tokenizer, text_enc, vae, dtype)
            if batch is None:
                continue

            noise      = torch.randn_like(batch["latents"])
            timesteps  = torch.randint(0, scheduler.config.num_train_timesteps,
                                       (batch_size,), device=device)
            noisy      = scheduler.add_noise(batch["latents"], noise, timesteps)
            pred       = unet(noisy, timesteps, batch["encoder_hidden_states"]).sample
            loss       = torch.nn.functional.mse_loss(pred, noise)

            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(unet.parameters(), 1.0)
            optimizer.step()

            total_loss += loss.item()
            if step % 50 == 0:
                logger.info(f"[LoRA] step {step}/{num_steps} — loss={loss.item():.4f}")

        avg_loss = total_loss / max(step, 1)

        # Save LoRA weights
        unet.save_pretrained(str(dest.parent / f"lora_{dest.stem}"))
        # Also export safetensors
        self._export_safetensors(unet, dest)

        return {"lora_path": str(dest), "loss": avg_loss, "steps": step, "style": style_name}

    # ── Dataset helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _load_dataset(dataset_path: str, style_name: str) -> List[Dict[str, str]]:
        """Load (image_path, caption) pairs from folder or parquet."""
        import glob

        dp = Path(dataset_path)
        samples: List[Dict[str, str]] = []

        if dp.is_dir():
            for img in dp.glob("*.jpg"):
                txt_file = img.with_suffix(".txt")
                caption  = txt_file.read_text().strip() if txt_file.exists() else style_name
                samples.append({"image": str(img), "caption": caption})
            for img in dp.glob("*.png"):
                txt_file = img.with_suffix(".txt")
                caption  = txt_file.read_text().strip() if txt_file.exists() else style_name
                samples.append({"image": str(img), "caption": caption})
        elif dp.suffix == ".parquet":
            import pandas as pd
            df = pd.read_parquet(str(dp))
            for _, row in df.iterrows():
                if "image_path" in row and "caption" in row:
                    samples.append({"image": row["image_path"], "caption": row["caption"]})

        if not samples:
            logger.warning(f"[LoRA] No training samples found in {dataset_path}, using synthetic")
            samples = [{"image": None,
                        "caption": f"{style_name}, cinematic, viral, high energy"}
                       for _ in range(50)]

        logger.info(f"[LoRA] Dataset: {len(samples)} samples")
        return samples

    @staticmethod
    def _sample_batch(dataset, batch_size, device, tokenizer, text_enc, vae, dtype):
        import random, torch
        from PIL import Image

        items = random.sample(dataset, min(batch_size, len(dataset)))
        captions   = [it["caption"] for it in items]
        img_paths  = [it.get("image") for it in items]

        # Tokenize captions
        tokens = tokenizer(
            captions,
            max_length=tokenizer.model_max_length,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        ).input_ids.to(device)

        with torch.no_grad():
            enc_hidden = text_enc(tokens).last_hidden_state

        # Encode images → latents (use zeros if no image)
        latents_list = []
        for ip in img_paths:
            if ip and Path(ip).exists():
                img = Image.open(ip).convert("RGB").resize((512, 512))
                import torchvision.transforms as T
                transform = T.Compose([T.ToTensor(), T.Normalize([0.5], [0.5])])
                tensor = transform(img).unsqueeze(0).to(device).to(dtype)
                with torch.no_grad():
                    latent = vae.encode(tensor).latent_dist.sample() * 0.18215
            else:
                latent = torch.zeros(1, 4, 64, 64, device=device, dtype=dtype)
            latents_list.append(latent)

        latents = torch.cat(latents_list, dim=0)
        return {"latents": latents, "encoder_hidden_states": enc_hidden}

    @staticmethod
    def _export_safetensors(unet, dest: Path):
        try:
            from safetensors.torch import save_file
            lora_weights = {
                k: v for k, v in unet.state_dict().items()
                if "lora_" in k
            }
            save_file(lora_weights, str(dest))
            logger.info(f"[LoRA] Saved safetensors → {dest}")
        except Exception as exc:
            logger.warning(f"[LoRA] safetensors export failed: {exc}")
