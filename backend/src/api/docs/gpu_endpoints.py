"""
API Documentation Generator — OpenAPI/Swagger for GPU Endpoints
===============================================================

This module generates comprehensive OpenAPI documentation for all GPU service endpoints.
Integrates with FastAPI's built-in docs at /docs and /redoc.

Usage:
    from api.docs.gpu_endpoints import get_gpu_endpoint_docs
    docs = get_gpu_endpoint_docs()
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def get_gpu_endpoint_schemas() -> Dict[str, Any]:
    """
    Return OpenAPI schemas for all GPU service request/response models.
    These are used by FastAPI to generate the /docs UI.
    """
    return {
        "T2VGenerateRequest": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Text prompt for video generation", "example": "ocean waves crashing at sunset"},
                "duration": {"type": "number", "description": "Video duration in seconds", "default": 4.0, "minimum": 2.0, "maximum": 10.0},
                "resolution": {"type": "string", "enum": ["480p", "720p", "1080p"], "default": "720p"},
                "model": {"type": "string", "enum": ["ltx-video", "wan2.2-1.3b", "wan2.2-14b"], "default": "ltx-video"},
                "task_id": {"type": "string", "nullable": True},
            },
            "required": ["prompt"],
        },
        "TTSSynthesizeRequest": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to synthesize", "example": "Welcome to this viral clip!"},
                "language": {"type": "string", "description": "ISO language code", "default": "en", "example": "en"},
                "speaker_wav": {"type": "string", "nullable": True, "description": "Path to speaker sample for voice cloning"},
                "speed": {"type": "number", "default": 1.0, "minimum": 0.5, "maximum": 2.0},
                "task_id": {"type": "string", "nullable": True},
            },
            "required": ["text"],
        },
        "UpscaleRequest": {
            "type": "object",
            "properties": {
                "input_path": {"type": "string", "description": "Absolute path to source video"},
                "scale_factor": {"type": "integer", "enum": [2, 4], "default": 2},
                "model": {"type": "string", "enum": ["realesrgan", "realesrgan-x2", "anime4k"], "default": "realesrgan"},
                "task_id": {"type": "string", "nullable": True},
            },
            "required": ["input_path"],
        },
        "Upscale8KRequest": {
            "type": "object",
            "properties": {
                "input_path": {"type": "string", "description": "Absolute path to source video"},
                "mode": {"type": "string", "enum": ["direct", "dual", "4k_intermediate"], "default": "dual", "description": "direct=fast, dual=best quality"},
                "denoise": {"type": "boolean", "default": False, "description": "Apply AI denoising before upscaling"},
                "hdr": {"type": "boolean", "default": False, "description": "Enable HDR10 tone mapping"},
                "task_id": {"type": "string", "nullable": True},
            },
            "required": ["input_path"],
        },
        "LoRATrainRequest": {
            "type": "object",
            "properties": {
                "dataset_path": {"type": "string", "description": "Path to training dataset folder"},
                "base_model": {"type": "string", "enum": ["sd1.5", "sdxl", "wan2.2-1.3b"], "default": "sd1.5"},
                "style_name": {"type": "string", "description": "Name for the LoRA style", "example": "viral_tiktok_drama"},
                "num_steps": {"type": "integer", "default": 500, "minimum": 100, "maximum": 2000},
                "network_dim": {"type": "integer", "default": 64, "minimum": 4, "maximum": 256},
                "network_alpha": {"type": "integer", "default": 32},
                "resolution": {"type": "integer", "enum": [512, 768, 1024], "default": 512},
            },
            "required": ["dataset_path", "style_name"],
        },
        "JobStatusResponse": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "status": {"type": "string", "enum": ["queued", "running", "done", "error"]},
                "result": {"type": "object", "nullable": True},
                "error": {"type": "string", "nullable": True},
                "created_at": {"type": "string", "format": "date-time"},
                "updated_at": {"type": "string", "format": "date-time"},
            },
        },
        "GPUStatusResponse": {
            "type": "object",
            "properties": {
                "gpu_available": {"type": "boolean"},
                "device_name": {"type": "string", "nullable": True},
                "vram_total_gb": {"type": "number", "nullable": True},
                "vram_used_gb": {"type": "number", "nullable": True},
                "cuda_version": {"type": "string", "nullable": True},
                "supported_features": {"type": "array", "items": {"type": "string"}},
            },
        },
        "HealthCheckResponse": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["healthy", "degraded", "unhealthy"]},
                "services": {"type": "object"},
                "timestamp": {"type": "string", "format": "date-time"},
            },
        },
    }


def get_gpu_endpoint_tags() -> List[Dict[str, Any]]:
    """Return OpenAPI tags for GPU endpoints grouping."""
    return [
        {
            "name": "GPU Services",
            "description": "GPU-intensive generative AI endpoints (T2V, TTS, upscaling, LoRA training)",
        },
        {
            "name": "8K Upscaling",
            "description": "Hollywood-quality 8K video upscaling (Phase 9.3)",
        },
        {
            "name": "Job Management",
            "description": "Asynchronous job status polling for long-running GPU tasks",
        },
    ]


def get_gpu_endpoint_descriptions() -> Dict[str, str]:
    """Return detailed descriptions for each GPU endpoint."""
    return {
        "POST /gpu/broll/generate": """
Generate AI B-roll video from text prompt using T2V models (LTX-Video/Wan2.2).

**Models:**
- `ltx-video` (5GB VRAM): Fast 720p generation, best for most use cases
- `wan2.2-1.3b` (8GB VRAM): Balanced quality/speed
- `wan2.2-14b` (16GB VRAM): Best quality, requires RTX 4090

**Rate Limiting:** 10 requests/minute per user (GPU-intensive)

**Returns:** Job ID for polling via GET /gpu/broll/{job_id}
""",
        "POST /gpu/tts/synthesize": """
Synthesize speech using Coqui XTTS v2 (17 languages, voice cloning).

**Features:**
- 3-second voice cloning from speaker sample
- 17 languages supported
- Adjustable speed (0.5x - 2.0x)

**Rate Limiting:** 20 requests/minute per user

**Returns:** Job ID for polling via GET /gpu/tts/{job_id}
""",
        "POST /gpu/upscale": """
Upscale video to 2x or 4x using Real-ESRGAN.

**Models:**
- `realesrgan`: 4x photorealistic upscaling
- `realesrgan-x2`: 2x upscaling (faster)
- `anime4k`: Optimized for anime/cartoon content

**Rate Limiting:** 5 requests/minute per user (GPU-intensive)

**Returns:** Job ID for polling via GET /gpu/upscale/{job_id}
""",
        "POST /gpu/upscale/8k": """
Hollywood-quality 8K upscaling (7680×4320) with multiple quality modes.

**Modes:**
- `direct`: Single 4× pass (~20s per 60s clip)
- `dual`: Two 2× passes for best quality (~40s)
- `4k_intermediate`: ProRes 4K then 2× to 8K (~30s)

**Requirements:** 8GB+ VRAM (12GB recommended for dual mode)

**Rate Limiting:** 3 requests/minute per user (very GPU-intensive)
""",
        "POST /gpu/lora/train": """
Train a custom LoRA for viral style generation.

**Training Time:** 30min - 1h for 100-500 clips

**Rate Limiting:** 1 request/hour per user (extremely GPU-intensive)

**Style Examples:**
- `viral_tiktok_drama` — High-energy drama clips
- `zach_king_magic` — Magic trick reveal style
- `mrbeast_energy` — Charity/challenge energy
- `hormozi_business` — Business advice format
""",
    }


def get_gpu_openapi_extension() -> Dict[str, Any]:
    """
    Return complete OpenAPI extension for GPU endpoints.
    This can be merged with the main FastAPI OpenAPI schema.
    """
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "ViraClip GPU Services API",
            "version": "1.0.0",
            "description": "GPU-intensive generative AI services for viral video creation",
        },
        "components": {
            "schemas": get_gpu_endpoint_schemas(),
        },
        "tags": get_gpu_endpoint_tags(),
        "paths": {
            "/gpu/status": {
                "get": {
                    "tags": ["GPU Services"],
                    "summary": "Get GPU status and capabilities",
                    "responses": {
                        "200": {
                            "description": "GPU status information",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/GPUStatusResponse"}
                                }
                            }
                        }
                    }
                }
            },
            "/gpu/broll/generate": {
                "post": {
                    "tags": ["GPU Services"],
                    "summary": "Generate T2V B-roll from text prompt",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/T2VGenerateRequest"}
                            }
                        }
                    },
                    "responses": {
                        "202": {"description": "Job accepted", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/JobStatusResponse"}}}},
                        "429": {"description": "Rate limit exceeded"},
                        "503": {"description": "GPU unavailable"},
                    }
                }
            },
            "/gpu/tts/synthesize": {
                "post": {
                    "tags": ["GPU Services"],
                    "summary": "Synthesize speech with XTTS v2",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/TTSSynthesizeRequest"}
                            }
                        }
                    },
                    "responses": {
                        "202": {"description": "Job accepted", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/JobStatusResponse"}}}},
                        "429": {"description": "Rate limit exceeded"},
                    }
                }
            },
            "/gpu/upscale": {
                "post": {
                    "tags": ["GPU Services"],
                    "summary": "Upscale video with Real-ESRGAN",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/UpscaleRequest"}
                            }
                        }
                    },
                    "responses": {
                        "202": {"description": "Job accepted", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/JobStatusResponse"}}}},
                        "429": {"description": "Rate limit exceeded"},
                    }
                }
            },
            "/gpu/upscale/8k": {
                "post": {
                    "tags": ["8K Upscaling"],
                    "summary": "Hollywood-quality 8K upscaling",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Upscale8KRequest"}
                            }
                        }
                    },
                    "responses": {
                        "202": {"description": "Job accepted", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/JobStatusResponse"}}}},
                        "429": {"description": "Rate limit exceeded"},
                        "503": {"description": "Insufficient VRAM for 8K"},
                    }
                }
            },
            "/gpu/lora/train": {
                "post": {
                    "tags": ["GPU Services"],
                    "summary": "Train custom LoRA for viral style",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/LoRATrainRequest"}
                            }
                        }
                    },
                    "responses": {
                        "202": {"description": "Job accepted", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/JobStatusResponse"}}}},
                        "429": {"description": "Rate limit exceeded"},
                        "503": {"description": "GPU unavailable"},
                    }
                }
            },
        },
    }


# Export main function for use in FastAPI app
__all__ = [
    "get_gpu_endpoint_schemas",
    "get_gpu_endpoint_tags",
    "get_gpu_endpoint_descriptions",
    "get_gpu_openapi_extension",
]
