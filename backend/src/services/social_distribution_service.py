"""
Social Distribution Service — STUB mínimo.

Este módulo fue referenciado por `video_service.py` y otros pero nunca se
incluyó en el repo. Este stub permite que los imports funcionen y que el
pipeline local (descarga → transcripción → LLM → render ComfyUI) se ejecute
sin depender de distribución a TikTok/Instagram/YouTube.

Si más adelante se implementa la distribución real, basta con reemplazar
este archivo por la versión funcional.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import logging

logger = logging.getLogger(__name__)


class SocialDistributionService:
    """Stub de distribución social. Todos los métodos son no-ops seguros."""

    @staticmethod
    async def publish_clip(
        video_path: Path,
        platform: str,
        caption: str = "",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        No-op: no publica realmente. Devuelve un dict marcando skip.
        """
        logger.info(
            "SocialDistributionService.publish_clip (stub): "
            "platform=%s, video=%s — skipped",
            platform,
            video_path,
        )
        return {
            "success": False,
            "skipped": True,
            "reason": "SocialDistributionService not implemented (stub)",
            "platform": platform,
            "video_path": str(video_path),
        }

    @staticmethod
    def get_oauth_url(platform: str) -> str:
        """
        No-op: devuelve string vacío para evitar crashes en rutas auth.
        """
        logger.info(
            "SocialDistributionService.get_oauth_url (stub): platform=%s", platform
        )
        return ""

    @staticmethod
    async def get_viral_hashtags(
        transcript: str,
        platform: str = "tiktok",
        **kwargs: Any,
    ) -> List[str]:
        """
        No-op: devuelve lista vacía. El pipeline continúa sin hashtags.
        """
        logger.debug(
            "SocialDistributionService.get_viral_hashtags (stub): "
            "platform=%s, transcript_len=%d — returning []",
            platform,
            len(transcript or ""),
        )
        return []


__all__ = ["SocialDistributionService"]
