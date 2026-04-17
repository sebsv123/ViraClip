"""
ComfyUIOrchestrator - Integración ViraClip con ComfyUI
Optimizado para RTX 5070 8GB VRAM
"""

import aiohttp
import asyncio
import random
from pathlib import Path
from typing import Optional, Dict, Any


class ComfyUIOrchestrator:
    """Orquesta workflows de ComfyUI para ViraClip"""
    
    def __init__(self, base_url: str = "http://localhost:8188"):
        self.url = base_url.rstrip("/")
    
    async def subtitles(self, video_path: str, task_id: str) -> str:
        """Generar subtítulos con Whisper"""
        workflow = {
            "1": {
                "inputs": {
                    "video": f"/comfyui/input/{task_id}.mp4",
                    "force_rate": 30,
                    "frame_load_cap": 0
                },
                "class_type": "VHS_LoadVideo"
            },
            "2": {
                "inputs": {
                    "audio": ["1", 1],
                    "model": "base",
                    "language": "auto",
                    "transcription_format": "srt"
                },
                "class_type": "WhisperTranscribe"
            },
            "3": {
                "inputs": {
                    "transcription": ["2", 0],
                    "file_path": f"/comfyui/output/{task_id}.srt"
                },
                "class_type": "WhisperSaveTranscription"
            }
        }
        return await self._execute(workflow, task_id, "srt")
    
    async def reframe_9_16(self, video_path: str, task_id: str, 
                           chunk_size: int = 300) -> str:
        """Reencuadre 9:16 con chunking para videos largos"""
        workflow = {
            "1": {
                "inputs": {
                    "video": f"/comfyui/input/{task_id}.mp4",
                    "force_rate": 30,
                    "frame_load_cap": chunk_size
                },
                "class_type": "VHS_LoadVideo"
            },
            "2": {
                "inputs": {
                    "video": ["1", 0],
                    "width": 1080,
                    "height": 1920,
                    "interpolation": "bilinear"
                },
                "class_type": "VHS_ResizeVideo"
            },
            "3": {
                "inputs": {
                    "images": ["2", 0],
                    "frame_rate": 30,
                    "format": "video/h264-mp4",
                    "crf": 23
                },
                "class_type": "VHS_VideoCombine"
            },
            "4": {
                "inputs": {
                    "video": ["3", 0],
                    "filename_prefix": f"{task_id}_9_16"
                },
                "class_type": "VHS_SaveVideo"
            }
        }
        return await self._execute(workflow, task_id, "mp4")
    
    async def thumbnail(self, keyframe_path: str, task_id: str, 
                        prompt: str = "cinematic viral thumbnail") -> str:
        """Generar thumbnail con SDXL-Turbo GGUF"""
        workflow = {
            "1": {
                "inputs": {
                    "text": f"{prompt}, bold colors, trending, best quality",
                    "clip": ["4", 1]
                },
                "class_type": "CLIPTextEncode"
            },
            "2": {
                "inputs": {
                    "text": "blurry, low quality, watermark",
                    "clip": ["4", 1]
                },
                "class_type": "CLIPTextEncode"
            },
            "3": {
                "inputs": {
                    "width": 1920,
                    "height": 1080,
                    "batch_size": 1
                },
                "class_type": "EmptyLatentImage"
            },
            "4": {
                "inputs": {
                    "unet_name": "turbo-xl-Q4_0.gguf",
                    "weight_dtype": "default"
                },
                "class_type": "UnetLoaderGGUF"
            },
            "5": {
                "inputs": {
                    "seed": random.randint(1, 1000000),
                    "steps": 4,
                    "cfg": 1.0,
                    "sampler_name": "dpmpp_2m",
                    "scheduler": "karras",
                    "denoise": 0.9,
                    "model": ["4", 0],
                    "positive": ["1", 0],
                    "negative": ["2", 0],
                    "latent_image": ["3", 0]
                },
                "class_type": "KSampler"
            },
            "6": {
                "inputs": {
                    "samples": ["5", 0],
                    "vae": ["4", 2]
                },
                "class_type": "VAEDecode"
            },
            "7": {
                "inputs": {
                    "filename_prefix": f"thumb_{task_id}",
                    "images": ["6", 0]
                },
                "class_type": "SaveImage"
            }
        }
        return await self._execute(workflow, task_id, "png")
    
    async def add_broll_transition(self, main_clip: str, broll_clip: str, 
                                   task_id: str, transition_type: str = "fade",
                                   duration: float = 1.0) -> str:
        """Añadir B-roll con transición"""
        frames = int(duration * 30)
        workflow = {
            "1": {
                "inputs": {
                    "video": f"/comfyui/input/{task_id}_main.mp4",
                    "force_rate": 30,
                    "frame_load_cap": 0
                },
                "class_type": "VHS_LoadVideo"
            },
            "2": {
                "inputs": {
                    "video": f"/comfyui/input/{task_id}_broll.mp4",
                    "force_rate": 30,
                    "frame_load_cap": 0
                },
                "class_type": "VHS_LoadVideo"
            },
            "3": {
                "inputs": {
                    "video1": ["1", 0],
                    "video2": ["2", 0],
                    "transition_frames": frames,
                    "transition_type": transition_type
                },
                "class_type": "VHS_VideoConcatenate"
            },
            "4": {
                "inputs": {
                    "images": ["3", 0],
                    "frame_rate": 30,
                    "format": "video/h264-mp4",
                    "crf": 23
                },
                "class_type": "VHS_VideoCombine"
            },
            "5": {
                "inputs": {
                    "video": ["4", 0],
                    "filename_prefix": f"{task_id}_transition"
                },
                "class_type": "VHS_SaveVideo"
            }
        }
        return await self._execute(workflow, task_id, "mp4")
    
    async def _execute(self, workflow: Dict[str, Any], task_id: str, 
                       ext: str) -> str:
        """Ejecutar workflow y esperar resultado"""
        
        # 1. Enviar workflow a ComfyUI
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.url}/prompt",
                json={"prompt": workflow}
            ) as resp:
                if resp.status != 200:
                    raise Exception(f"Error enviando workflow: {await resp.text()}")
                result = await resp.json()
                prompt_id = result.get("prompt_id")
                if not prompt_id:
                    raise Exception("No se recibió prompt_id")
        
        # 2. Polling hasta que termine (max 10 min)
        for attempt in range(300):  # 300 x 2s = 10 min
            await asyncio.sleep(2)
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.url}/history/{prompt_id}"
                ) as resp:
                    if resp.status != 200:
                        continue
                    history = await resp.json()
                    
                    if prompt_id in history:
                        outputs = history[prompt_id].get("outputs", {})
                        if outputs:
                            # Extraer ruta del output
                            for node_id, node_output in outputs.items():
                                if "images" in node_output:
                                    return f"/comfyui/output/{task_id}.{ext}"
                                if "video" in node_output or "gifs" in node_output:
                                    return f"/comfyui/output/{task_id}.{ext}"
                                if "srt" in str(node_output).lower():
                                    return f"/comfyui/output/{task_id}.{ext}"
        
        raise TimeoutError(f"Timeout esperando resultado para {task_id}")
    
    async def health_check(self) -> Dict[str, Any]:
        """Verificar estado de ComfyUI"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.url}/system_stats",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status == 200:
                        return {"status": "ok", "data": await resp.json()}
                    return {"status": "error", "code": resp.status}
        except Exception as e:
            return {"status": "error", "message": str(e)}


# Instancia global
comfyui_orchestrator = ComfyUIOrchestrator()


async def test_comfyui_connection():
    """Test rápido de conexión"""
    orch = ComfyUIOrchestrator()
    health = await orch.health_check()
    print(f"Health Check: {health}")
    return health.get("status") == "ok"


if __name__ == "__main__":
    # Test de conexión
    asyncio.run(test_comfyui_connection())
