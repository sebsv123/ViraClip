"""
BRoll Service - AI-powered B-roll injection for viral video enhancement.

Provider priority (configurable via BROLL_PROVIDER_PRIORITY):
  premium_first (default):
    1. LTXV / ComfyUI local generation  (best quality, zero API cost)
    2. T2V Replicate                    (cloud generative, paid)
    3. Pexels / Pixabay / Coverr stock  (free, lower relevance)
  stock_first:
    1. Pexels / Pixabay / Coverr stock
    2. LTXV / ComfyUI
    3. T2V Replicate

Pipeline:
  1. Keyword extraction   — Groq llama-3.1-8b-instant extracts 2-3 visual search terms
  2. Asset fetch           — ordered by provider priority with quality gating
  3. Silence detection     — librosa finds gaps > 1.5 s in segment audio
  4. FFmpeg overlay        — inserts B-roll with fade-in/out at timestamps
"""
import asyncio
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import httpx

from ..config import Config, get_config
from ..comfyui_bridge import ComfyUIBridge, COMFYUI_ENABLED, LTXV_ENABLED
from .broll_compositor import compose_overlay, probe_duration
from .broll_asset_memory import AssetUsageMemory, asset_id_for, visual_fingerprint_for
from .editorial_broll_planner import BrollCueDecision, EditorialBrollPlanner
from .vpi_broll_intent import (
    ClipTheme,
    IMAGE_EXTS as VPI_IMAGE_EXTS,
    assess_broll_relevance,
    build_stock_queries,
    detect_clip_theme,
    detect_intent,
    is_broll_asset_forbidden,
    score_broll_phrase_fit,
    score_broll_candidate,
    normalize_text as _vpi_normalize_text,
)
from .broll_provider_strategy import (
    BROLL_PROVIDER_PRIORITY,
    BROLL_ENABLE_STOCK,
    BROLL_MIN_CLIP_DURATION_SEC,
    ProviderType,
    get_provider_order,
    diagnose_providers,
    passes_quality_gate,
)
from .vpi_production_safe_edit import (
    production_safe_mode_active,
    production_safe_route_allowed,
)

logger = logging.getLogger(__name__)


def _production_safe_blocked(route_name: str) -> bool:
    return bool(production_safe_mode_active() and not production_safe_route_allowed(route_name))

# ── B-roll tuning ─────────────────────────────────────────────────────────────
_BROLL_DOWNLOAD_TIMEOUT = int(os.environ.get("BROLL_DOWNLOAD_TIMEOUT", "30"))
_MIN_SILENCE_SEC = float(os.environ.get("BROLL_MIN_SILENCE_SEC", "1.5"))
_BROLL_DURATION = float(os.environ.get("BROLL_DURATION", "2.5"))
_FADE_DURATION = float(os.environ.get("BROLL_FADE_DURATION", "0.6"))
_CACHE_TTL_DAYS = int(os.environ.get("BROLL_CACHE_TTL_DAYS", "7"))
_BROLL_MAX_OVERLAYS = int(os.environ.get("BROLL_MAX_OVERLAYS", "8"))
_BETA_CLEAN_BROLL_MIN_VISIBLE_S = 1.4
_BETA_CLEAN_BROLL_TARGET_S = 2.0
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".avif"}
_GENERIC_BAD_TERMS = {
    "tea", "coffee", "meditation", "yoga", "wellness", "spa", "zen",
    "stock market", "trading", "luxury", "cash", "funeral", "hospital",
}
_EDITORIAL_BROLL_STOPWORD_STEMS = {
    "de", "la", "el", "los", "las", "que", "sea", "o", "y", "les", "me", "te",
    "un", "una", "es", "en", "por", "para", "con", "como", "esto", "este",
    "esta", "momento", "pues", "hola",
}

_PRODUCTION_SAFE_BROLL_TERMS = {
    "proteccion familiar",
    "protección familiar",
    "tranquilidad",
    "salud",
    "médico",
    "medico",
    "hospitalizacion",
    "hospitalización",
    "accidente",
    "riesgo",
    "ahorro",
    "dinero",
    "imprevisto",
    "familia",
    "proteger",
}


def _is_high_relevance_broll_cue(
    *,
    cue: BrollCueDecision,
    segment_text: str,
    theme: ClipTheme,
) -> Tuple[bool, str]:
    cue_text = " ".join([
        str(cue.visual_query or ""),
        str(cue.trigger_text or ""),
        str(cue.reason or ""),
        segment_text or "",
        theme.central_topic or "",
        theme.domain or "",
    ])
    normalized = _vpi_normalize_text(cue_text)
    if cue.confidence < 0.75:
        return False, "confidence_below_threshold"
    if not any(term in normalized for term in _PRODUCTION_SAFE_BROLL_TERMS):
        return False, "no_explicit_semantic_match"
    return True, "high_confidence_explicit_match"

# ── Semantic keyword classification for generative B-roll ────────────────────
_MOTION_KEYWORDS = {
    "run", "race", "crowd", "explosion", "fast", "chase", "build",
    "construct", "drive", "fly", "jump", "fight", "sport", "traffic",
    "running", "speed", "motion", "action", "dynamic", "movement"
}
_ABSTRACT_KEYWORDS = {
    "money", "fear", "love", "future", "success", "death", "dream",
    "freedom", "power", "danger", "opportunity", "wealth", "family",
    "insurance", "protection", "planning", "financial", "security",
    "hope", "trust", "growth", "innovation", "challenge", "goal"
}

def _select_broll_workflow(keyword: str) -> str:
    """Select appropriate workflow based on keyword semantics."""
    kw_tokens = set(keyword.lower().split())
    if kw_tokens & _MOTION_KEYWORDS:
        return "generate_broll"  # LTXV — better for motion
    elif kw_tokens & _ABSTRACT_KEYWORDS:
        return "generate_broll_flux"  # FLUX — better for abstract/emotional
    else:
        return "generate_broll"  # default LTXV

def _extract_mood(text: str) -> str:
    """Extract emotional mood from transcript context."""
    text_lower = text.lower()
    if any(w in text_lower for w in ["miedo", "fear", "peligro", "riesgo", "danger", "scary"]):
        return "tense dramatic dark shadows"
    elif any(w in text_lower for w in ["éxito", "success", "logro", "victoria", "win", "achieve"]):
        return "uplifting bright energetic golden"
    elif any(w in text_lower for w in ["familia", "family", "amor", "love", "care", "together"]):
        return "warm soft intimate cozy"
    elif any(w in text_lower for w in ["money", "wealth", "financial", "rich", "profit"]):
        return "luxurious sleek modern professional"
    else:
        return "neutral professional cinematic"

def build_broll_prompt(keyword: str, transcript_context: str = "") -> str:
    """
    Build cinematic prompt for ComfyUI from keyword and transcript context.
    Creates rich, non-literal descriptions that evoke the concept.
    """
    base = (
        f"cinematic vertical video 9:16, {keyword}, "
        "professional camera movement, shallow depth of field, "
        "golden hour lighting, high contrast, film grain, "
        "dynamic composition, no text, no watermark, "
        "broadcast quality, 4K, masterpiece"
    )
    if transcript_context:
        mood = _extract_mood(transcript_context)
        base += f", {mood} atmosphere"
    return base


class BrollService:
    """AI-powered B-roll injection service."""
    _task_seen_asset_ids_by_task: Dict[str, set[str]] = {}
    _task_seen_visual_fingerprints_by_task: Dict[str, set[str]] = {}
    _task_seen_filename_stems_by_task: Dict[str, set[str]] = {}

    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()
        self.broll_dir = Path(self.config.temp_dir) / "uploads/broll"
        self.broll_dir.mkdir(parents=True, exist_ok=True)
        self.last_editorial_broll: List[Dict[str, Any]] = []
        self.asset_memory = AssetUsageMemory()
        self._pending_provider_asset_ids: Dict[str, str] = {}
        self._downloaded_provider_asset_ids: Dict[str, str] = {}
        self._task_seen_asset_ids: set[str] = set()
        self._task_seen_provider_video_ids: set[str] = set()
        self._task_seen_visual_fingerprints: set[str] = set()
        self._task_seen_filename_stems: set[str] = set()
        self._broll_hard_guard_rejections: List[Dict[str, Any]] = []
        self._last_broll_selection_stats: Dict[str, Any] = {}

    @staticmethod
    def _normalize_editorial_asset_selection(
        result: Any,
    ) -> Tuple[Optional[Path], str, float, List[str], Optional[str]]:
        """Normalize selector output into a safe 5-tuple."""
        if result is None:
            return (None, "none", 0.0, ["no_contextual_match"], None)
        if isinstance(result, (tuple, list)) and len(result) == 5:
            asset, source, score, reasons, category = result
            if isinstance(asset, str) and asset:
                asset = Path(asset)
            if asset is not None and not isinstance(asset, Path):
                asset = None
            return (
                asset,
                str(source or "none"),
                float(score or 0.0),
                [str(r) for r in (reasons or [])],
                str(category) if category else None,
            )
        logger.warning("[editorial-broll] malformed selection result type=%s", type(result).__name__)
        return (None, "none", 0.0, ["malformed_selection_result"], None)

    @classmethod
    def _shared_task_sets(cls, task_id: Optional[str]) -> Tuple[set[str], set[str], set[str]]:
        if not task_id:
            return set(), set(), set()
        return (
            cls._task_seen_asset_ids_by_task.setdefault(task_id, set()),
            cls._task_seen_visual_fingerprints_by_task.setdefault(task_id, set()),
            cls._task_seen_filename_stems_by_task.setdefault(task_id, set()),
        )

    # ──────────────────────────────────────────────────────────────────────────
    # 1. KEYWORD EXTRACTION
    # ──────────────────────────────────────────────────────────────────────────

    async def extract_keywords(
        self,
        text: str,
        video_path: Optional[Path] = None,
        clip_duration: float = 0.0,
    ) -> List[str]:
        """
        Extract 2-3 visual B-roll keywords from *text*.

        If *video_path* is provided, YOLOv10 visual grounding filters out
        keywords whose subject is already visible in the clip — no B-roll
        needed for what the viewer can already see.
        """
        groq_key = os.getenv("GROQ_API_KEY", "")
        if not groq_key:
            logger.warning("[BRoll] GROQ_API_KEY not set — falling back to first 3 nouns")
            keywords = self._simple_keyword_fallback(text)
            return await self._apply_yolo_filter(keywords, video_path, clip_duration)

        prompt = (
            "You are a cinematic B-roll director for a viral video. "
            "Analyze this transcript and extract 2-3 VISUAL CONCEPTS that would make the video WOW.\n\n"
            "CONTEXT RULES:\n"
            "1. Keywords must EXACTLY match what the speaker is saying IN THIS MOMENT\n"
            "2. Choose CINEMATIC, MOVIE-QUALITY visuals (not generic stock footage)\n"
            "3. Prefer: dynamic motion, dramatic lighting, professional cinematography\n"
            "4. AVOID: generic motivational concepts, abstract ideas, obvious stock tropes\n"
            "5. FOCUS ON: specific actions, detailed environments, emotional moments\n\n"
            "QUALITY CHECK:\n"
            "- Would this look like a Netflix documentary? → YES = good keyword\n"
            "- Could this be a movie scene? → YES = good keyword\n"
            "- Does it have motion and depth? → YES = good keyword\n\n"
            "EXAMPLES:\n"
            '- Talking about hard work → ["sweat droplets on forehead close-up", "hands typing furiously on keyboard", "clock hands moving rapidly"]\n'
            '- Talking about money → ["gold coins falling in slow motion", "luxury car headlights at night", "stack of cash being counted"]\n'
            '- Talking about nature → ["drone shot of forest canopy", "waves crashing dramatic rocks", "time-lapse blooming flower"]\n\n'
            "Reply with ONLY a JSON array of cinematic search terms.\n\n"
            f"TRANSCRIPT: {text[:600]}"
        )
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {groq_key}"},
                    json={
                        "model": "llama-3.1-8b-instant",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 60,
                        "temperature": 0.2,
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"].strip()
                # Parse the JSON array
                keywords = json.loads(content)
                if isinstance(keywords, list):
                    result = [str(k).strip() for k in keywords[:3] if k]
                    logger.info(f"[BRoll] Keywords extracted: {result}")
                    return await self._apply_yolo_filter(result, video_path, clip_duration)
        except Exception as e:
            logger.warning(f"[BRoll] Keyword extraction failed: {e}")
        fallback = self._simple_keyword_fallback(text)
        return await self._apply_yolo_filter(fallback, video_path, clip_duration)

    async def _apply_yolo_filter(
        self,
        keywords: List[str],
        video_path: Optional[Path],
        clip_duration: float,
    ) -> List[str]:
        """Filter *keywords* using YOLOv10 visual grounding on *video_path*."""
        if not video_path or clip_duration <= 0:
            return keywords
        try:
            from .yolo_detector import get_visual_context, filter_keywords_with_yolo
            ctx = await get_visual_context(video_path, clip_duration)
            filtered = filter_keywords_with_yolo(keywords, ctx["detected_labels"])
            if filtered != keywords:
                logger.info(
                    "[BRoll] YOLO filtered %d → %d keywords: %s → %s",
                    len(keywords), len(filtered), keywords, filtered,
                )
            return filtered
        except Exception as exc:
            logger.debug("[BRoll] YOLO filter skipped: %s", exc)
            return keywords

    @staticmethod
    def _simple_keyword_fallback(text: str) -> List[str]:
        """Return insurance/finance-first Spanish stock-video keywords as fallback."""
        # Beta: insurance/finance domain in Spanish — always return domain-relevant terms
        # that work well with Pexels/Coverr stock libraries
        text_lower = text.lower()
        # Detect insurance/finance context
        if any(w in text_lower for w in ["seguro", "seguros", "póliza", "cobertura", "prima",
                                          "indemnización", "siniestro", "reclamo", "aseguradora",
                                          "financial", "financiero", "inversión", "ahorro",
                                          "banco", "bank", "cuenta", "crédito", "hipoteca"]):
            return ["oficina ejecutivos reunión", "familia protección hogar",
                    "dinero calculadora ahorro", "documentos firma contrato",
                    "edificio corporativo moderno"]
        # Detect health/medical context
        if any(w in text_lower for w in ["salud", "hospital", "médico", "doctor", "clínica",
                                          "paciente", "enfermedad", "seguro salud"]):
            return ["hospital pasillo doctor", "manos doctor paciente",
                    "familia salud bienestar", "medicina laboratorio análisis"]
        # Generic Spanish fallback
        return ["oficina moderna profesional", "personas caminando ciudad",
                "tecnología computadora oficina", "naturaleza paisaje tranquilo"]

    # ──────────────────────────────────────────────────────────────────────────
    # 2. PROVIDER DIAGNOSTICS
    # ──────────────────────────────────────────────────────────────────────────

    def log_provider_status(self) -> dict:
        """Log and return availability of all B-roll providers.

        Delegates to the centralised broll_provider_strategy module.
        """
        status = diagnose_providers()
        return status.as_dict()

    # ──────────────────────────────────────────────────────────────────────────
    # 3. QUALITY GATING
    # ──────────────────────────────────────────────────────────────────────────

    def _is_cache_fresh(self, path: Path) -> bool:
        """Return True if *path* exists and was modified within _CACHE_TTL_DAYS."""
        import time as _time
        if not path.exists() or path.stat().st_size < 1_000:
            return False
        age_days = (_time.time() - path.stat().st_mtime) / 86400
        return age_days <= _CACHE_TTL_DAYS

    @staticmethod
    def _passes_quality_gate(path: Path, provider: str) -> bool:
        """Unified quality gate — delegates to broll_provider_strategy."""
        return passes_quality_gate(path, provider)

    # ──────────────────────────────────────────────────────────────────────────
    # 4. ASSET FETCH — strategy-driven dispatch (single source of truth)
    # ──────────────────────────────────────────────────────────────────────────

    async def fetch_broll_asset(self, keyword: str) -> Optional[Path]:
        """Fetch the best B-roll asset for *keyword* using provider order
        from broll_provider_strategy.get_provider_order().

        This is the ONLY method that routes to individual providers.
        No other file should duplicate this routing logic.
        """
        safe = "".join(c if c.isalnum() else "_" for c in keyword).lower()
        provider_order = get_provider_order()  # single source of truth

        for provider_type in provider_order:
            result = await self._try_provider(provider_type, keyword, safe)
            if result:
                return result

        logger.warning("[BRoll] ALL PROVIDERS EXHAUSTED for keyword='%s' "
                       "(priority=%s, order=%s)",
                       keyword, BROLL_PROVIDER_PRIORITY,
                       [p.value for p in provider_order])
        return None

    async def fetch_editorial_broll_asset(self, keyword: str) -> Optional[Path]:
        """Fetch B-roll for editorial v1 without premium/generative providers."""
        safe = "".join(c if c.isalnum() else "_" for c in keyword).lower()
        for provider_type in (
            ProviderType.LOCAL,
            ProviderType.STOCK_VIDEO,
            ProviderType.STOCK_IMAGE,
            ProviderType.CACHE,
        ):
            result = await self._try_provider(provider_type, keyword, safe)
            if result:
                return result
        logger.info("[editorial-broll] no stock/local asset for query=%s", keyword)
        return None

    @staticmethod
    def _score_broll_candidate(
        asset: Path,
        cue: BrollCueDecision,
        source: str,
        theme: Optional[ClipTheme] = None,
        category: Optional[str] = None,
        query: Optional[str] = None,
        task_seen: Optional[set[str]] = None,
        category_seen: Optional[Dict[str, int]] = None,
        memory: Optional[AssetUsageMemory] = None,
        task_id: Optional[str] = None,
        provider_asset_id: Optional[str] = None,
    ) -> Tuple[float, List[str]]:
        category = category or cue.cue_type or ""
        query_text = (query or cue.visual_query or "").lower()
        task_seen = task_seen or set()
        category_seen = category_seen or {}
        intent = detect_intent(
            " ".join([cue.trigger_text or "", cue.reason or "", query_text]),
            suggested_broll_cue_type=cue.cue_type,
            matched_patterns=[cue.trigger_text] if cue.trigger_text else [],
        )
        if cue.intent_type and cue.intent_type != intent.intent_type:
            intent.intent_type = cue.intent_type
        if cue.preferred_categories:
            intent.preferred_categories = list(cue.preferred_categories)
        if cue.preferred_queries:
            intent.pexels_queries = list(cue.preferred_queries)
        if cue.avoid_terms:
            intent.avoid_terms = list(cue.avoid_terms)
        intent.min_candidate_score = float(cue.min_score or intent.min_candidate_score)

        score, reasons = score_broll_candidate(
            {
                "source": "pexels" if source in {"stock", "pexels"} else source,
                "path": asset,
                "category": category,
                "query": query_text,
                "is_image": asset.suffix.lower() in VPI_IMAGE_EXTS,
                "is_video": asset.suffix.lower() not in VPI_IMAGE_EXTS,
                "used_in_task": str(asset) in task_seen,
                "category_repeated": category_seen.get(category, 0) > 0,
                "orientation": "portrait",
            },
            intent,
            theme,
            {
                "task_seen_assets": task_seen,
                "category_seen": category_seen,
                "selected_categories": list((category_seen or {}).keys()),
                "selected_visual_types": [
                    self_type for self_type, count in (
                        ("documents_paper_closeup", category_seen.get("documents_admin", 0)),
                        ("human_family_home", category_seen.get("family_protection", 0) + category_seen.get("emotional_reassurance", 0)),
                        ("advisor_planning", category_seen.get("advisor_consultation", 0) + category_seen.get("financial_planning", 0)),
                    )
                    if count > 0
                ],
                "suggested_broll_cue_type": cue.cue_type,
            },
        )
        if memory is not None:
            freshness = memory.freshness(
                "pexels" if source in {"stock", "pexels"} else source,
                str(asset),
                category,
                task_id=task_id,
                provider_asset_id=provider_asset_id,
            )
            score += freshness.penalty
            reasons.extend(freshness.reasons)
            reasons.append(f"freshness_score:{freshness.freshness_score}")
            if freshness.last_used_at:
                reasons.append(f"last_used_at:{freshness.last_used_at}")
            reasons.append(f"visual_fingerprint:{freshness.visual_fingerprint}")
            if freshness.quarantined:
                score = min(score, -200.0)
        return score, reasons

    def _hard_guard_context(
        self,
        *,
        asset: Path,
        cue: BrollCueDecision,
        source: str,
        category: str,
        theme: ClipTheme,
        task_seen_assets: set[str],
        task_seen_categories: Dict[str, int],
        task_id: Optional[str] = None,
        query: Optional[str] = None,
        provider_asset_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        source_key = "pexels" if source in {"stock", "pexels"} else source
        asset_id = asset_id_for(source_key, str(asset), provider_asset_id)
        fingerprint = visual_fingerprint_for(source_key, str(asset), category)
        shared_asset_ids, shared_fingerprints, shared_stems = self._shared_task_sets(task_id)
        return {
            "asset_id": asset_id,
            "task_id": task_id,
            "provider_video_id": provider_asset_id,
            "visual_fingerprint": fingerprint,
            "query": query or cue.visual_query or "",
            "category": category,
            "cue_type": cue.cue_type,
            "intent_type": cue.intent_type,
            "central_topic": theme.central_topic,
            "theme_topic": theme.central_topic,
            "documents_already_used": task_seen_categories.get("documents_admin", 0) > 0,
            "task_seen_assets": task_seen_assets,
            "task_seen_asset_ids": self._task_seen_asset_ids | shared_asset_ids,
            "task_seen_provider_video_ids": self._task_seen_provider_video_ids,
            "task_seen_visual_fingerprints": self._task_seen_visual_fingerprints | shared_fingerprints,
            "task_seen_filename_stems": self._task_seen_filename_stems | shared_stems,
            "strict_fingerprint_repeat": True,
        }

    def _reject_for_hard_guard(
        self,
        *,
        asset: Path,
        cue: BrollCueDecision,
        source: str,
        category: str,
        theme: ClipTheme,
        task_seen_assets: set[str],
        task_seen_categories: Dict[str, int],
        task_id: Optional[str] = None,
        query: Optional[str] = None,
        provider_asset_id: Optional[str] = None,
    ) -> Optional[List[str]]:
        stem = asset.stem.lower().strip()
        if stem in _EDITORIAL_BROLL_STOPWORD_STEMS:
            logger.info("[broll-hard-guard] reject asset=%s reasons=stopword_asset_filename", asset)
            return ["stopword_asset_filename"]

        context = self._hard_guard_context(
            asset=asset,
            cue=cue,
            source=source,
            category=category,
            theme=theme,
            task_seen_assets=task_seen_assets,
            task_seen_categories=task_seen_categories,
            task_id=task_id,
            query=query,
            provider_asset_id=provider_asset_id,
        )
        forbidden, reasons = is_broll_asset_forbidden(
            {
                "path": str(asset),
                "query": query or cue.visual_query or "",
                "category": category,
                "provider_video_id": provider_asset_id,
                "visual_fingerprint": context.get("visual_fingerprint"),
            },
            context,
        )
        freshness = self.asset_memory.freshness(
            "pexels" if source in {"stock", "pexels"} else source,
            str(asset),
            category,
            task_id=None,
            provider_asset_id=provider_asset_id,
        )
        task_freshness = self.asset_memory.freshness(
            "pexels" if source in {"stock", "pexels"} else source,
            str(asset),
            category,
            task_id=context.get("task_id"),
            provider_asset_id=provider_asset_id,
        ) if context.get("task_id") else freshness
        for freshness_reason in task_freshness.reasons:
            if freshness_reason.startswith("same_task_exact_asset:"):
                reasons.append("exact_asset_repeat")
            elif freshness_reason.startswith("same_task_visual_fingerprint:"):
                reasons.append("visual_fingerprint_repeat")
            elif freshness_reason.startswith("asset_used_24h:"):
                reasons.append("recent_exact_asset_24h")
        if task_freshness.quarantined or task_freshness.user_quality_flag in {"bad", "irrelevant", "forbidden_visual", "irrelevant_visual"}:
            reasons.append(f"asset_quality_flag:{task_freshness.user_quality_flag or 'quarantined'}")
        if any(reason.startswith("quality_cooldown_active:") for reason in task_freshness.reasons):
            reasons.append("cooldown_active")
        reasons = list(dict.fromkeys(reasons))
        forbidden = forbidden or bool(reasons)
        if not forbidden:
            logger.info("[broll-hard-guard] accept asset=%s category=%s score=pending", asset, category)
            return None

        asset_id = str(context.get("asset_id") or "")
        reason_text = ",".join(reasons)
        logger.info("[broll-hard-guard] reject asset=%s reasons=%s", asset, reason_text)
        if asset_id:
            if any("wellness" in reason or "tea" in reason or "known_tea" in reason for reason in reasons):
                flag = "forbidden_visual"
                cooldown_hours = None
                quarantine_reason = "tea_or_wellness"
            elif any(reason in {"exact_asset_repeat", "provider_video_repeat", "filename_stem_repeat"} for reason in reasons):
                flag = "repeated_in_task"
                cooldown_hours = 24.0
                quarantine_reason = reason_text
            elif any("recent_exact" in reason or "cooldown" in reason or "overused" in reason for reason in reasons):
                flag = "overused_recent"
                cooldown_hours = 24.0
                quarantine_reason = reason_text
            elif any(reason.startswith("asset_quality_flag:") for reason in reasons):
                flag = "irrelevant_visual"
                cooldown_hours = None
                quarantine_reason = reason_text
            else:
                flag = "irrelevant_visual"
                cooldown_hours = None
                quarantine_reason = reason_text
            self.asset_memory.mark_asset_quality(asset_id, flag, quarantine_reason, cooldown_hours=cooldown_hours)
            logger.info("[broll-quarantine] asset=%s flag=%s reason=%s", asset_id, flag, quarantine_reason)
        if any(reason == "exact_asset_repeat" for reason in reasons):
            logger.info("[broll-repeat-guard] reject exact_repeat asset=%s", asset)
            logger.info("[broll-task-diversity] reject asset=%s reason=used_in_task", asset)
        if any(reason == "provider_video_repeat" for reason in reasons):
            logger.info("[broll-repeat-guard] reject provider_repeat id=%s", provider_asset_id or "")
        if any(reason == "filename_stem_repeat" for reason in reasons):
            logger.info("[broll-repeat-guard] reject filename_repeat asset=%s", asset)
            logger.info("[broll-task-diversity] reject asset=%s reason=filename_used_in_task", asset)
        if any(reason == "visual_fingerprint_repeat" for reason in reasons):
            logger.info("[broll-repeat-guard] penalize fingerprint_repeat fp=%s", context.get("visual_fingerprint") or "")
            logger.info("[broll-task-diversity] reject fp=%s reason=fingerprint_used_in_task", context.get("visual_fingerprint") or "")
        self._broll_hard_guard_rejections.append(
            {
                "asset": str(asset),
                "asset_id": asset_id,
                "provider_video_id": provider_asset_id,
                "visual_fingerprint": context.get("visual_fingerprint"),
                "category": category,
                "source": source,
                "reasons": reasons,
            }
        )
        return reasons

    @staticmethod
    def _guard_rejection_bucket(reasons: List[str]) -> str:
        if any(
            "tea" in reason
            or "wellness" in reason
            or "known_tea" in reason
            or reason.startswith(("severe_risk_cliche", "finance_cliche", "generic_office", "life_insurance_forbidden"))
            for reason in reasons
        ):
            return "forbidden"
        if any("cooldown" in reason or "recent_exact" in reason or "overused" in reason for reason in reasons):
            return "cooldown"
        if any("repeat" in reason for reason in reasons):
            return "repeat"
        return "relevance"

    @staticmethod
    def _only_cooldown_reasons(reasons: List[str]) -> bool:
        if not reasons:
            return False
        hard_terms = ("tea", "wellness", "known_tea", "forbidden", "severe_risk_cliche", "finance_cliche", "generic_office")
        if any(any(term in reason for term in hard_terms) for reason in reasons):
            return False
        return any("cooldown" in reason or "recent_exact" in reason or "overused" in reason for reason in reasons)

    def _mark_selected_for_repeat_guard(
        self,
        *,
        asset: Path,
        source: str,
        category: str,
        provider_asset_id: Optional[str] = None,
    ) -> None:
        source_key = "pexels" if source in {"stock", "pexels"} else source
        self._task_seen_asset_ids.add(asset_id_for(source_key, str(asset), provider_asset_id))
        if provider_asset_id:
            self._task_seen_provider_video_ids.add(str(provider_asset_id))
        self._task_seen_visual_fingerprints.add(visual_fingerprint_for(source_key, str(asset), category))
        stem = asset.stem.lower()
        if stem:
            self._task_seen_filename_stems.add(stem)

    def _mark_selected_for_task_diversity(
        self,
        *,
        task_id: Optional[str],
        asset: Path,
        source: str,
        category: str,
        provider_asset_id: Optional[str] = None,
    ) -> None:
        if not task_id:
            return
        source_key = "pexels" if source in {"stock", "pexels"} else source
        shared_asset_ids, shared_fingerprints, shared_stems = self._shared_task_sets(task_id)
        shared_asset_ids.add(asset_id_for(source_key, str(asset), provider_asset_id))
        shared_fingerprints.add(visual_fingerprint_for(source_key, str(asset), category))
        if asset.stem:
            shared_stems.add(asset.stem.lower())

    @staticmethod
    def _choose_diverse_candidate(
        candidates: List[Tuple[float, Path, str, List[str], str]],
        min_score: float,
        theme: ClipTheme,
        task_seen_categories: Dict[str, int],
    ) -> Optional[Tuple[float, Path, str, List[str], str]]:
        passing = [item for item in candidates if item[0] >= min_score]
        if not passing:
            return None
        passing.sort(key=lambda item: item[0], reverse=True)
        best = passing[0]
        repeated = task_seen_categories.get(best[4], 0) > 0
        document_repeat = best[4] == "documents_admin" and task_seen_categories.get("documents_admin", 0) > 0
        if repeated or document_repeat:
            alternatives = [item for item in passing[1:] if item[4] != best[4] and item[0] >= 50.0]
            if alternatives:
                alternative = alternatives[0]
                if document_repeat or best[0] - alternative[0] <= 35.0:
                    logger.info(
                        "[diversity-rerank] replaced asset=%s with=%s reason=%s best_score=%.1f alt_score=%.1f",
                        best[1],
                        alternative[1],
                        "documents_repeat" if document_repeat else "category_repeat",
                        best[0],
                        alternative[0],
                    )
                    return alternative
        if (
            theme.central_topic == "life_insurance_family_protection"
            and best[4] == "documents_admin"
            and task_seen_categories.get("documents_admin", 0) > 0
        ):
            logger.info("[diversity-rerank] kept repeated documents only because no alternative passed threshold asset=%s", best[1])
        return best

    @staticmethod
    def _diversity_queries_for(cue: BrollCueDecision, theme: ClipTheme) -> List[Tuple[str, str]]:
        if theme.central_topic != "life_insurance_family_protection":
            return []
        if cue.intent_type in {"myth_debunk_age", "client_objection"} or cue.cue_type in {"documents_admin", "explain_coverage"}:
            return [
                ("advisor_consultation", "financial advisor explaining contract to young couple"),
                ("advisor_consultation", "young couple financial planning consultation"),
            ]
        if cue.intent_type == "family_responsibility" or cue.cue_type == "family_protection":
            return [
                ("financial_planning", "family financial planning at home"),
                ("advisor_consultation", "financial advisor family documents"),
            ]
        return []

    @staticmethod
    def _broll_relevance_for_candidate(
        cue: BrollCueDecision,
        category: str,
        theme: ClipTheme,
        query: Optional[str] = None,
    ) -> Tuple[bool, float, str]:
        phrase = " ".join(
            str(item or "")
            for item in [
                cue.trigger_text,
                cue.visual_query,
                cue.reason,
                query,
            ]
        )
        return assess_broll_relevance(
            phrase=phrase,
            category=category or cue.cue_type,
            intent_type=cue.intent_type or "",
            central_topic=getattr(theme, "central_topic", "") or "",
        )

    @staticmethod
    def _asset_motion_type(asset: Path) -> Tuple[str, float, bool]:
        is_image = asset.suffix.lower() in _IMAGE_EXTS
        if is_image:
            return "static_image", -60.0, True
        try:
            duration = probe_duration(asset)
            if duration and duration >= 1.0:
                return "video_motion", 40.0, False
        except Exception:
            pass
        return "unknown", 0.0, False

    @staticmethod
    def _phrase_context_for_candidate(cue: BrollCueDecision, query: Optional[str] = None) -> str:
        return " ".join(
            str(item or "")
            for item in [
                cue.trigger_text,
                cue.visual_query,
                cue.reason,
                query,
            ]
        )

    def _score_phrase_fit_for_candidate(
        self,
        *,
        asset: Path,
        cue: BrollCueDecision,
        category: str,
        theme: ClipTheme,
        query: Optional[str] = None,
    ) -> Dict[str, Any]:
        fit = score_broll_phrase_fit(
            {
                "path": str(asset),
                "category": category,
                "cue_type": cue.cue_type,
                "query": query or cue.visual_query or "",
                "is_image": asset.suffix.lower() in _IMAGE_EXTS,
            },
            self._phrase_context_for_candidate(cue, query),
            theme,
            cue.intent_type or "",
        )
        logger.info(
            '[broll-phrase-fit] asset=%s phrase="%s" score=%.1f label=%s primary=%s reason=%s',
            asset,
            (cue.trigger_text or cue.visual_query or query or "")[:120],
            float(fit.get("phrase_fit_score") or 0.0),
            fit.get("phrase_fit_label"),
            str(bool(fit.get("allowed_as_primary"))).lower(),
            fit.get("phrase_fit_reason"),
        )
        return fit

    async def _select_editorial_asset_for_cue(
        self,
        cue: BrollCueDecision,
        task_id: Optional[str],
        task_seen_assets: set[str],
        task_seen_categories: Dict[str, int],
        local_bank_enabled: bool,
        theme: ClipTheme,
        clip_index: int = 0,
    ) -> Tuple[Optional[Path], str, float, List[str], Optional[str]]:
        min_score = float(cue.min_score or 55.0)
        candidates: List[Tuple[float, Path, str, List[str], str]] = []
        cooldown_recovery_candidates: List[Tuple[float, Path, str, List[str], str]] = []
        attempted_stock_queries: set[str] = set()
        stats: Dict[str, Any] = {
            "broll_candidates_total": 0,
            "broll_candidates_rejected_forbidden": 0,
            "broll_candidates_rejected_cooldown": 0,
            "broll_candidates_rejected_relevance": 0,
            "broll_candidates_usable": 0,
            "broll_no_broll_reason": None,
        }

        # ── VPI local-only mode: use VPI asset library, bypass external APIs ──
        _vpi_local_only = os.environ.get("VPI_BROLL_LOCAL_ONLY", "").lower() in ("1", "true", "yes")

        if local_bank_enabled or _vpi_local_only:
            try:
                from .local_broll_asset_bank import list_assets as _list_local_assets
                from .local_broll_asset_bank import mark_used as _mark_asset_used
                for category in (cue.preferred_categories or [cue.cue_type]):
                    if not category:
                        continue
                    local_assets = _list_local_assets(category)
                    if not local_assets:
                        continue
                    for asset in local_assets:
                        stats["broll_candidates_total"] += 1
                        guard_reasons = self._reject_for_hard_guard(
                            asset=asset,
                            cue=cue,
                            source="local",
                            category=category,
                            theme=theme,
                            task_seen_assets=task_seen_assets,
                            task_seen_categories=task_seen_categories,
                            task_id=task_id,
                        )
                        if guard_reasons:
                            bucket = self._guard_rejection_bucket(guard_reasons)
                            if bucket == "forbidden":
                                stats["broll_candidates_rejected_forbidden"] += 1
                            elif bucket in {"cooldown", "repeat"}:
                                stats["broll_candidates_rejected_cooldown"] += 1
                            else:
                                stats["broll_candidates_rejected_relevance"] += 1
                            if self._only_cooldown_reasons(guard_reasons):
                                relevance_ok, relevance_score, relevance_reason = self._broll_relevance_for_candidate(
                                    cue=cue,
                                    category=category,
                                    theme=theme,
                                )
                                if relevance_ok:
                                    phrase_fit = self._score_phrase_fit_for_candidate(
                                        asset=asset,
                                        cue=cue,
                                        category=category,
                                        theme=theme,
                                    )
                                    motion_type, motion_bonus, is_image = self._asset_motion_type(asset)
                                    logger.info("[broll-motion] asset=%s type=%s penalty=%.1f", asset, motion_type, motion_bonus)
                                    if float(phrase_fit.get("phrase_fit_score") or 0.0) < 60.0:
                                        logger.info("[broll-safe-recovery] rejected asset=%s reason=low_phrase_fit", asset)
                                        continue
                                    if motion_type != "video_motion" and not (is_image and phrase_fit.get("allowed_as_support")):
                                        logger.info("[broll-safe-recovery] rejected asset=%s reason=weak_motion_type", asset)
                                        continue
                                    recovery_score, recovery_reasons = self._score_broll_candidate(
                                        asset,
                                        cue,
                                        "local",
                                        theme=theme,
                                        category=category,
                                        task_seen=task_seen_assets,
                                        category_seen=task_seen_categories,
                                        memory=None,
                                        task_id=task_id,
                                    )
                                    recovery_reasons.extend([
                                        f"broll_relevance_score:{relevance_score:.1f}",
                                        f"broll_relevance_reason:{relevance_reason}",
                                        "broll_used_with_cooldown_exception:true",
                                        "cooldown_exception_reason:safe_asset_better_than_no_broll",
                                        f"broll_phrase_fit_score:{phrase_fit['phrase_fit_score']}",
                                        f"broll_phrase_fit_label:{phrase_fit['phrase_fit_label']}",
                                        f"broll_phrase_fit_reason:{phrase_fit['phrase_fit_reason']}",
                                        f"broll_allowed_as_primary:{str(bool(phrase_fit['allowed_as_primary'])).lower()}",
                                        f"broll_allowed_as_support:{str(bool(phrase_fit['allowed_as_support'])).lower()}",
                                        f"broll_motion_type:{motion_type}",
                                        f"broll_static_penalty:{motion_bonus if is_image else 0.0}",
                                        f"broll_is_image:{str(is_image).lower()}",
                                        f"broll_ken_burns_applied:{str(is_image).lower()}",
                                    ])
                                    recovery_score += motion_bonus
                                    cooldown_recovery_candidates.append((recovery_score, asset, "local", recovery_reasons, category))
                            continue
                        relevance_ok, relevance_score, relevance_reason = self._broll_relevance_for_candidate(
                            cue=cue,
                            category=category,
                            theme=theme,
                        )
                        if not relevance_ok:
                            logger.info(
                                "[broll-relevance] reject asset=%s reason=%s",
                                asset,
                                relevance_reason,
                            )
                            stats["broll_candidates_rejected_relevance"] += 1
                            continue
                        phrase_fit = self._score_phrase_fit_for_candidate(
                            asset=asset,
                            cue=cue,
                            category=category,
                            theme=theme,
                        )
                        motion_type, motion_bonus, is_image = self._asset_motion_type(asset)
                        logger.info("[broll-motion] asset=%s type=%s penalty=%.1f", asset, motion_type, motion_bonus)
                        if not phrase_fit.get("allowed_as_primary"):
                            stats["broll_candidates_rejected_relevance"] += 1
                            logger.info("[broll-phrase-fit] reject asset=%s reason=weak_phrase_fit", asset)
                            continue
                        if is_image:
                            stats["broll_candidates_rejected_relevance"] += 1
                            logger.info("[broll-motion] reject static_image reason=primary_requires_video")
                            continue
                        score, reasons = self._score_broll_candidate(
                            asset,
                            cue,
                            "local",
                            theme=theme,
                            category=category,
                            task_seen=task_seen_assets,
                            category_seen=task_seen_categories,
                            memory=self.asset_memory,
                            task_id=task_id,
                        )
                        reasons.extend([
                            f"broll_relevance_score:{relevance_score:.1f}",
                            f"broll_relevance_reason:{relevance_reason}",
                            f"broll_phrase_fit_score:{phrase_fit['phrase_fit_score']}",
                            f"broll_phrase_fit_label:{phrase_fit['phrase_fit_label']}",
                            f"broll_phrase_fit_reason:{phrase_fit['phrase_fit_reason']}",
                            f"broll_allowed_as_primary:{str(bool(phrase_fit['allowed_as_primary'])).lower()}",
                            f"broll_allowed_as_support:{str(bool(phrase_fit['allowed_as_support'])).lower()}",
                            f"broll_motion_type:{motion_type}",
                            f"broll_static_penalty:{motion_bonus if is_image else 0.0}",
                            f"broll_is_image:{str(is_image).lower()}",
                            f"broll_ken_burns_applied:{str(is_image).lower()}",
                        ])
                        score += motion_bonus
                        logger.info(
                            "[broll-relevance] accept cue=%s phrase=%s reason=%s",
                            category,
                            cue.trigger_text or cue.visual_query or "",
                            relevance_reason,
                        )
                        logger.info("[broll-hard-guard] accept asset=%s category=%s score=%.1f", asset, category, score)
                        logger.info(
                            "[broll-candidate] source=local cue=%s asset=%s score=%.1f reasons=%s",
                            category,
                            asset,
                            score,
                            ",".join(reasons),
                        )
                        stats["broll_candidates_usable"] += 1
                        candidates.append((score, asset, "local", reasons, category))
            except Exception as _local_e:
                logger.debug("[editorial-broll] local asset bank error: %s", _local_e)

        # ── VPI asset library as additional local B-roll source ──
        if _vpi_local_only or local_bank_enabled:
            try:
                from .vpi_asset_library_service import discover_asset_library as _vpi_discover
                from .vpi_asset_library_service import _classify_broll_by_filename as _vpi_classify_broll
                _vpi_lib = _vpi_discover()
                _vpi_broll_paths = _vpi_lib.get("broll", [])
                if _vpi_broll_paths:
                    logger.info("[vpi-broll] discovered %d VPI broll assets", len(_vpi_broll_paths))
                    for _vpi_asset in _vpi_broll_paths:
                        _vpi_path_str = _vpi_asset.get("path") if isinstance(_vpi_asset, dict) else str(_vpi_asset)
                        if not _vpi_path_str:
                            continue
                        _vpi_path = Path(_vpi_path_str)
                        if not _vpi_path.exists():
                            continue
                        _vpi_intent, _vpi_tags = _vpi_classify_broll(_vpi_path_str)
                        # Match against cue categories
                        _vpi_categories = cue.preferred_categories or [cue.cue_type]
                        _vpi_matched = False
                        for _vpi_cat in _vpi_categories:
                            if not _vpi_cat:
                                continue
                            _vpi_cat_lower = _vpi_cat.lower()
                            if _vpi_intent and _vpi_intent in _vpi_cat_lower:
                                _vpi_matched = True
                                break
                            if any(tag in _vpi_cat_lower for tag in _vpi_tags):
                                _vpi_matched = True
                                break
                            # Also match if any tag is in the intent name
                            if _vpi_intent and any(tag in _vpi_intent for tag in _vpi_cat_lower.split("_")):
                                _vpi_matched = True
                                break
                        if not _vpi_matched:
                            logger.info("[vpi-broll] skip asset=%s intent=%s no_match_for_categories=%s",
                                        _vpi_path_str, _vpi_intent, _vpi_categories)
                            continue
                        stats["broll_candidates_total"] += 1
                        guard_reasons = self._reject_for_hard_guard(
                            asset=_vpi_path,
                            cue=cue,
                            source="vpi_local",
                            category=_vpi_intent or "generic",
                            theme=theme,
                            task_seen_assets=task_seen_assets,
                            task_seen_categories=task_seen_categories,
                            task_id=task_id,
                        )
                        if guard_reasons:
                            bucket = self._guard_rejection_bucket(guard_reasons)
                            if bucket == "forbidden":
                                stats["broll_candidates_rejected_forbidden"] += 1
                            elif bucket in {"cooldown", "repeat"}:
                                stats["broll_candidates_rejected_cooldown"] += 1
                            else:
                                stats["broll_candidates_rejected_relevance"] += 1
                            logger.info("[vpi-broll] reject asset=%s reason=%s", _vpi_path_str, guard_reasons)
                            continue
                        relevance_ok, relevance_score, relevance_reason = self._broll_relevance_for_candidate(
                            cue=cue,
                            category=_vpi_intent or "generic",
                            theme=theme,
                        )
                        if not relevance_ok:
                            stats["broll_candidates_rejected_relevance"] += 1
                            logger.info("[vpi-broll] relevance reject asset=%s reason=%s", _vpi_path_str, relevance_reason)
                            continue
                        phrase_fit = self._score_phrase_fit_for_candidate(
                            asset=_vpi_path,
                            cue=cue,
                            category=_vpi_intent or "generic",
                            theme=theme,
                        )
                        motion_type, motion_bonus, is_image = self._asset_motion_type(_vpi_path)
                        logger.info("[vpi-broll] asset=%s intent=%s motion=%s bonus=%.1f",
                                    _vpi_path_str, _vpi_intent, motion_type, motion_bonus)
                        score, reasons = self._score_broll_candidate(
                            _vpi_path,
                            cue,
                            "vpi_local",
                            theme=theme,
                            category=_vpi_intent or "generic",
                            task_seen=task_seen_assets,
                            category_seen=task_seen_categories,
                            memory=self.asset_memory,
                            task_id=task_id,
                        )
                        reasons.extend([
                            f"broll_relevance_score:{relevance_score:.1f}",
                            f"broll_relevance_reason:{relevance_reason}",
                            f"broll_phrase_fit_score:{phrase_fit['phrase_fit_score']}",
                            f"broll_phrase_fit_label:{phrase_fit['phrase_fit_label']}",
                            f"broll_phrase_fit_reason:{phrase_fit['phrase_fit_reason']}",
                            f"broll_allowed_as_primary:{str(bool(phrase_fit['allowed_as_primary'])).lower()}",
                            f"broll_allowed_as_support:{str(bool(phrase_fit['allowed_as_support'])).lower()}",
                            f"broll_motion_type:{motion_type}",
                            f"broll_static_penalty:{motion_bonus if is_image else 0.0}",
                            f"broll_is_image:{str(is_image).lower()}",
                            f"broll_ken_burns_applied:{str(is_image).lower()}",
                            f"broll_vpi_intent:{_vpi_intent}",
                            f"broll_vpi_tags:{','.join(_vpi_tags)}",
                            f"broll_source:vpi_local",
                        ])
                        score += motion_bonus
                        logger.info("[vpi-broll] accept asset=%s intent=%s score=%.1f", _vpi_path_str, _vpi_intent, score)
                        stats["broll_candidates_usable"] += 1
                        candidates.append((score, _vpi_path, "vpi_local", reasons, _vpi_intent or "generic"))
            except Exception as _vpi_e:
                logger.debug("[vpi-broll] VPI asset library error: %s", _vpi_e)

        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            score, asset, source, reasons, category = candidates[0]
            stats["broll_no_broll_reason"] = None
            self._last_broll_selection_stats = stats
            if task_id:
                self._record_selected_asset(
                    asset=asset,
                    source=source,
                    category=category,
                    task_id=task_id,
                    clip_index=clip_index,
                    cue=cue,
                    theme=theme,
                    score=score,
                )
            return (asset, source, score, reasons, category)

        if cooldown_recovery_candidates:
            cooldown_recovery_candidates.sort(key=lambda item: item[0], reverse=True)
            score, asset, source, reasons, category = cooldown_recovery_candidates[0]
            stats["broll_no_broll_reason"] = "cooldown_exception_selected"
            self._last_broll_selection_stats = stats
            if task_id:
                self._record_selected_asset(
                    asset=asset,
                    source=source,
                    category=category,
                    task_id=task_id,
                    clip_index=clip_index,
                    cue=cue,
                    theme=theme,
                    score=score,
                )
            return (asset, source, score, reasons, category)

        stats["broll_no_broll_reason"] = "no_contextual_match"
        self._last_broll_selection_stats = stats
        return (None, "none", 0.0, ["no_contextual_match"], None)

    @staticmethod
    def _clip_index_from_path(video_path: str) -> int:
        name = Path(video_path).name
        parts = name.split("_")
        for idx, part in enumerate(parts):
            if part == "clip" and idx + 3 < len(parts):
                try:
                    return int(parts[idx + 3])
                except ValueError:
                    continue
        return 0

    def _record_selected_asset(
        self,
        *,
        asset: Path,
        source: str,
        category: str,
        task_id: Optional[str],
        clip_index: int,
        cue: BrollCueDecision,
        theme: ClipTheme,
        score: float,
    ) -> None:
        if not task_id:
            return
        provider_asset_id = self._downloaded_provider_asset_ids.get(str(asset))
        self.asset_memory.record_use(
            source="pexels" if source == "stock" else source,
            asset_path_or_url=str(asset),
            category=category,
            task_id=task_id,
            clip_index=clip_index,
            intent_type=cue.intent_type or "",
            central_topic=theme.central_topic,
            score=score,
            provider_asset_id=provider_asset_id,
        )

    async def _try_provider(
        self, provider_type: ProviderType, keyword: str, safe: str
    ) -> Optional[Path]:
        """Dispatch to a single provider. Returns Path on success, None on failure."""
        if provider_type == ProviderType.LOCAL:
            return self._try_local_cache(keyword, safe)
        if provider_type == ProviderType.LTXV:
            return await self._try_ltxv(keyword, safe)
        if provider_type == ProviderType.ANIMATEDIFF:
            return await self._try_animatediff(keyword, safe)
        if provider_type == ProviderType.T2V_REPLICATE:
            return await self._try_t2v(keyword, safe)
        if provider_type == ProviderType.STOCK_VIDEO:
            return await self._try_stock_video(keyword, safe)
        if provider_type == ProviderType.STOCK_IMAGE:
            return await self._try_stock_image(keyword, safe)
        if provider_type == ProviderType.CACHE:
            return self._try_disk_cache(keyword, safe)
        return None

    # ──────────────────────────────────────────────────────────────────────────
    # 5. INDIVIDUAL PROVIDER METHODS
    # ──────────────────────────────────────────────────────────────────────────

    def _try_local_cache(self, keyword: str, safe: str) -> Optional[Path]:
        """Check local disk cache for a fresh asset."""
        cached_video = self.broll_dir / f"{safe}.mp4"
        cached_photo = self.broll_dir / f"{safe}.jpg"
        if self._is_cache_fresh(cached_video):
            logger.info("[BRoll] ✓ PROVIDER=local keyword='%s' → %s", keyword, cached_video.name)
            return cached_video
        if self._is_cache_fresh(cached_photo):
            logger.info("[BRoll] ✓ PROVIDER=local keyword='%s' → %s", keyword, cached_photo.name)
            return cached_photo
        return None

    async def _try_ltxv(
        self, keyword: str, safe: str, transcript_context: str = ""
    ) -> Optional[Path]:
        """Try LTXV/FLUX generative B-roll based on keyword semantics."""
        if _production_safe_blocked("comfyui"):
            logger.info("PRODUCTION_SAFE_ROUTE_BLOCKED route=comfyui reason=premium_local_stability")
            return None
        if not LTXV_ENABLED:
            logger.debug("[BRoll] LTXV disabled (LTXV_ENABLED=false)")
            return None

        out_path = self.broll_dir / f"gen_{safe}.mp4"

        try:
            bridge = ComfyUIBridge()
            available = await bridge.is_available()
            if not available:
                logger.info("[BRoll] ✗ PROVIDER=ltxv SKIP — ComfyUI not reachable")
                return None

            # Select workflow based on keyword semantics
            workflow = _select_broll_workflow(keyword)
            prompt = build_broll_prompt(keyword, transcript_context)

            logger.info(f"[BRoll] Using workflow={workflow} for keyword='{keyword}'")

            if workflow == "generate_broll_flux":
                result = await bridge.generate_flux_broll(prompt, out_path)
            else:
                result = await bridge.generate_ltxv_broll(prompt, out_path, duration=_BROLL_DURATION)

            await bridge.close()

            if result and self._passes_quality_gate(out_path, workflow):
                logger.info("[BRoll] ✓ PROVIDER=%s keyword='%s' → %s", workflow, keyword, out_path.name)
                return out_path
            logger.info("[BRoll] ✗ PROVIDER=%s keyword='%s' → failed or quality reject", workflow, keyword)
        except Exception as exc:
            logger.warning("[BRoll] ✗ PROVIDER=ltxv keyword='%s' error: %s", keyword, exc)

        return None

    async def _try_animatediff(self, keyword: str, safe: str) -> Optional[Path]:
        """Try ComfyUI AnimateDiff. Returns Path or None."""
        if _production_safe_blocked("comfyui"):
            logger.info("PRODUCTION_SAFE_ROUTE_BLOCKED route=comfyui reason=premium_local_stability")
            return None
        if not COMFYUI_ENABLED:
            logger.debug("[BRoll] ComfyUI AnimateDiff disabled (COMFYUI_ENABLED=false)")
            return None

        out_path = self.broll_dir / f"gen_{safe}.mp4"

        try:
            bridge = ComfyUIBridge()
            available = await bridge.is_available()
            if available:
                prompt = f"Cinematic vertical footage of {keyword}, smooth, professional"
                result = await bridge.generate_broll(prompt, out_path, duration=_BROLL_DURATION)
                await bridge.close()
                if result and self._passes_quality_gate(out_path, "animatediff"):
                    logger.info("[BRoll] ✓ PROVIDER=animatediff keyword='%s' → %s", keyword, out_path.name)
                    return out_path
                logger.info("[BRoll] ✗ PROVIDER=animatediff keyword='%s' → failed", keyword)
            else:
                logger.info("[BRoll] ✗ PROVIDER=animatediff SKIP — ComfyUI not reachable")
        except Exception as exc:
            logger.warning("[BRoll] ✗ PROVIDER=animatediff keyword='%s' error: %s", keyword, exc)

        return None

    async def _try_t2v(self, keyword: str, safe: str) -> Optional[Path]:
        """Try T2V Replicate. Returns Path or None."""
        if _production_safe_blocked("t2v"):
            logger.info("PRODUCTION_SAFE_ROUTE_BLOCKED route=t2v reason=premium_local_stability")
            return None
        try:
            from .t2v_broll_service import T2VBrollService
            if T2VBrollService.is_available():
                t2v = T2VBrollService()
                t2v_prompt = f"Cinematic 4K vertical footage of {keyword}, smooth camera, no text"
                t2v_out = self.broll_dir / f"t2v_{safe}.mp4"
                res = await t2v.generate(prompt=t2v_prompt, duration=_BROLL_DURATION, output_path=str(t2v_out))
                if res and t2v_out.exists() and self._passes_quality_gate(t2v_out, "t2v_replicate"):
                    logger.info("[BRoll] ✓ PROVIDER=t2v_replicate keyword='%s' → %s", keyword, t2v_out.name)
                    return t2v_out
                logger.info("[BRoll] ✗ PROVIDER=t2v_replicate keyword='%s' → failed", keyword)
        except Exception as exc:
            logger.debug("[BRoll] ✗ PROVIDER=t2v_replicate keyword='%s' error: %s", keyword, exc)

        return None

    async def _try_stock_video(self, keyword: str, safe: str) -> Optional[Path]:
        """Try Pexels → Pixabay → Coverr. Returns Path or None."""
        if _production_safe_blocked("external_pexels"):
            logger.info("PRODUCTION_SAFE_ROUTE_BLOCKED route=external_pexels reason=premium_local_stability")
            return None
        if not BROLL_ENABLE_STOCK:
            logger.debug("[BRoll] Stock providers disabled (BROLL_ENABLE_STOCK=false)")
            return None

        cached_video = self.broll_dir / f"{safe}.mp4"

        # ── Parallel stock video search ───────────────────────────────────────
        pexels_task  = asyncio.create_task(self._search_pexels(keyword))
        pixabay_task = asyncio.create_task(self._search_pixabay(keyword))
        coverr_task  = asyncio.create_task(self._search_coverr(keyword))

        results = await asyncio.gather(pexels_task, pixabay_task, coverr_task,
                                       return_exceptions=True)
        providers = ["pexels_video", "pixabay_video", "coverr_video"]
        video_urls = [(r, p) for r, p in zip(results, providers) if isinstance(r, str) and r]

        for url, provider in video_urls:
            result = await self._download(url, cached_video)
            if result and self._passes_quality_gate(cached_video, provider):
                provider_asset_id = self._pending_provider_asset_ids.get(url)
                if provider_asset_id:
                    self._downloaded_provider_asset_ids[str(cached_video)] = provider_asset_id
                logger.info("[BRoll] ✓ PROVIDER=%s keyword='%s' → %s", provider, keyword, result.name)
                return result
            elif result:
                logger.info("[BRoll] ✗ PROVIDER=%s keyword='%s' → quality reject", provider, keyword)

        return None

    async def _try_stock_image(self, keyword: str, safe: str) -> Optional[Path]:
        """Try Pexels Photos. Returns Path or None."""
        if _production_safe_blocked("pexels_overlay"):
            logger.info("PRODUCTION_SAFE_ROUTE_BLOCKED route=pexels_overlay reason=premium_local_stability")
            return None
        if not BROLL_ENABLE_STOCK:
            logger.debug("[BRoll] Stock providers disabled (BROLL_ENABLE_STOCK=false)")
            return None

        cached_photo = self.broll_dir / f"{safe}.jpg"

        photo = await self._search_pexels_photos_and_download(keyword, safe)
        if photo and self._passes_quality_gate(photo, "pexels_photo"):
            logger.info("[BRoll] ✓ PROVIDER=pexels_photo keyword='%s' → %s", keyword, photo.name)
            return photo

        return None

    def _try_disk_cache(self, keyword: str, safe: str) -> Optional[Path]:
        """Alias for _try_local_cache (disk cache = local cache)."""
        return self._try_local_cache(keyword, safe)

    # ──────────────────────────────────────────────────────────────────────────
    # 6. API SEARCH HELPERS
    # ──────────────────────────────────────────────────────────────────────────

    async def _search_pexels_photos_and_download(self, keyword: str, safe_name: str) -> Optional[Path]:
        """Search Pexels Photos API and download a portrait image for *keyword*."""
        if _production_safe_blocked("external_pexels"):
            logger.info("PRODUCTION_SAFE_ROUTE_BLOCKED route=external_pexels reason=premium_local_stability")
            return None
        key = self.config.pexels_api_key or os.getenv("PEXELS_API_KEY", "")
        if not key:
            return None
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.pexels.com/v1/search",
                    headers={"Authorization": key},
                    params={"query": keyword, "per_page": 3, "orientation": "portrait"},
                )
                resp.raise_for_status()
                photos = resp.json().get("photos", [])
                if not photos:
                    return None
                src = photos[0].get("src", {})
                photo_url = src.get("portrait") or src.get("large2x") or src.get("large")
                if not photo_url:
                    return None
                dest = self.broll_dir / f"{safe_name}.jpg"
                img_resp = await client.get(photo_url, follow_redirects=True, timeout=_BROLL_DOWNLOAD_TIMEOUT)
                img_resp.raise_for_status()
                dest.write_bytes(img_resp.content)
                logger.info(f"[BRoll] Pexels photo: '{keyword}' → {dest} ({dest.stat().st_size // 1024} KB)")
                return dest
        except Exception as e:
            logger.warning(f"[BRoll] Pexels Photos search error for '{keyword}': {e}")
            return None

    async def _search_pexels(self, query: str) -> Optional[str]:
        if _production_safe_blocked("external_pexels"):
            logger.info("PRODUCTION_SAFE_ROUTE_BLOCKED route=external_pexels reason=premium_local_stability")
            return None
        key = self.config.pexels_api_key or os.getenv("PEXELS_API_KEY", "")
        if not key:
            return None
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.pexels.com/videos/search",
                    headers={"Authorization": key},
                    params={"query": query, "per_page": 5, "orientation": "portrait"},
                )
                resp.raise_for_status()
                videos = resp.json().get("videos", [])
                if not videos:
                    return None
                for video in videos[:5]:
                    video_id = str(video.get("id") or "")
                    provider_asset_id = video_id
                    freshness = self.asset_memory.freshness("pexels", provider_asset_id or query, "stock", provider_asset_id=provider_asset_id or None)
                    logger.info(
                        "[pexels-candidate] video_id=%s used_recently=%s score=%s",
                        video_id or "unknown",
                        freshness.freshness_score < 70 or freshness.quarantined,
                        freshness.freshness_score,
                    )
                    if freshness.quarantined or freshness.freshness_score < 70:
                        logger.info("[pexels-select] skipped video_id=%s reason=recently_used", video_id or "unknown")
                        continue
                    files = video.get("video_files", [])
                    for vf in files:
                        w, h = vf.get("width", 0), vf.get("height", 0)
                        if h > w and vf.get("file_type") == "video/mp4":
                            url = vf["link"]
                            self._pending_provider_asset_ids[url] = provider_asset_id
                            logger.info("[pexels-select] selected video_id=%s", video_id or "unknown")
                            logger.info(f"[BRoll] Pexels hit for '{query}': {url[:60]}...")
                            return url
                    if files:
                        url = files[0]["link"]
                        self._pending_provider_asset_ids[url] = provider_asset_id
                        logger.info("[pexels-select] selected video_id=%s", video_id or "unknown")
                        return url
        except Exception as e:
            logger.warning(f"[BRoll] Pexels search error: {e}")
            return None

    async def _search_coverr(self, query: str) -> Optional[str]:
        """Search Coverr CC0 video library."""
        if not self.config.coverr_enabled:
            logger.debug("[BRoll] Coverr disabled (no API key)")
            return None
        key = self.config.coverr_api_key
        if not key:
            return None
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.coverr.co/videos",
                    params={"keywords": query, "token": key, "per_page": 5},
                )
                resp.raise_for_status()
                data = resp.json()
                for item in data.get("hits", []):
                    # Prefer clips with portrait dimensions and duration 3-10s
                    dur = item.get("duration", 0)
                    w   = item.get("width", 0)
                    h   = item.get("height", 0)
                    url = item.get("urls", {}).get("mp4_download") or item.get("url")
                    if url and 3 <= dur <= 12 and h >= 720:
                        logger.info(f"[BRoll] Coverr hit for '{query}': {url[:60]}...")
                        return url
                # Any clip if none match portrait preference
                for item in data.get("hits", []):
                    url = item.get("urls", {}).get("mp4_download") or item.get("url")
                    if url:
                        return url
        except Exception as e:
            logger.debug(f"[BRoll] Coverr search error: {e}")
        return None

    async def _search_pixabay(self, query: str) -> Optional[str]:
        key = self.config.pixabay_api_key or os.getenv("PIXABAY_API_KEY", "")
        if not key:
            return None
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://pixabay.com/api/videos/",
                    params={
                        "key": key,
                        "q": query,
                        "video_type": "film",
                        "orientation": "vertical",
                        "per_page": 3,
                    },
                )
                resp.raise_for_status()
                hits = resp.json().get("hits", [])
                if not hits:
                    return None
                videos = hits[0].get("videos", {})
                for size in ("medium", "small", "large"):
                    url = videos.get(size, {}).get("url")
                    if url:
                        logger.info(f"[BRoll] Pixabay hit for '{query}': {url[:60]}...")
                        return url
        except Exception as e:
            logger.warning(f"[BRoll] Pixabay search error: {e}")
        return None

    async def _download(self, url: str, dest: Path) -> Optional[Path]:
        try:
            async with httpx.AsyncClient(timeout=_BROLL_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    with open(dest, "wb") as f:
                        async for chunk in resp.aiter_bytes(8192):
                            f.write(chunk)
            logger.info(f"[BRoll] Downloaded: {dest} ({dest.stat().st_size // 1024} KB)")
            return dest
        except Exception as e:
            logger.error(f"[BRoll] Download failed {url[:60]}: {e}")
            dest.unlink(missing_ok=True)
            return None

    # ──────────────────────────────────────────────────────────────────────────
    # 3. SILENCE DETECTION
    # ──────────────────────────────────────────────────────────────────────────

    def detect_silences(
        self,
        audio_path: str,
        min_duration: float = _MIN_SILENCE_SEC,
    ) -> List[Tuple[float, float]]:
        """Return list of (start, end) silence gaps >= *min_duration* seconds."""
        try:
            import librosa
            import numpy as np

            y, sr = librosa.load(audio_path, sr=16000, mono=True)
            rms = librosa.feature.rms(y=y, frame_length=512, hop_length=256)[0]
            times = librosa.frames_to_time(range(len(rms)), sr=sr, hop_length=256)

            threshold = float(np.percentile(rms, 15))  # bottom 15% = silence
            silences: List[Tuple[float, float]] = []
            in_silence = False
            silence_start = 0.0

            for i, (t, energy) in enumerate(zip(times, rms)):
                if energy < threshold and not in_silence:
                    in_silence = True
                    silence_start = float(t)
                elif energy >= threshold and in_silence:
                    in_silence = False
                    duration = float(t) - silence_start
                    if duration >= min_duration:
                        silences.append((silence_start, float(t)))

            logger.info(f"[BRoll] Detected {len(silences)} silence gaps >= {min_duration}s")
            return silences
        except Exception as e:
            logger.warning(f"[BRoll] Silence detection failed: {e}")
            return []

    # ──────────────────────────────────────────────────────────────────────────
    # 4. FFMPEG OVERLAY INSERTION
    # ──────────────────────────────────────────────────────────────────────────

    async def insert_broll(
        self,
        video_path: str,
        output_path: str,
        broll_path: str,
        timestamp: float,
        overlay_duration: float = _BROLL_DURATION,
        fade: float = _FADE_DURATION,
    ) -> bool:
        """
        Overlay *broll_path* on *video_path* at *timestamp* for *overlay_duration* seconds.
        Delegates to broll_compositor.compose_overlay for format-adaptive scaling.
        Returns True on success.
        """
        try:
            ok = compose_overlay(
                main_path=video_path,
                broll_path=broll_path,
                output_path=output_path,
                timestamp=timestamp,
                duration=overlay_duration,
                fade=fade,
            )
            if ok:
                logger.info(f"[BRoll] ✓ Overlay inserted at t={timestamp:.1f}s → {output_path}")
            else:
                logger.error(f"[BRoll] compose_overlay returned False for {video_path}")
            return ok
        except Exception as e:
            logger.error(f"[BRoll] insert_broll exception: {e}")
            return False

    # ──────────────────────────────────────────────────────────────────────────
    # PUBLIC ENTRY POINT
    # ──────────────────────────────────────────────────────────────────────────

    async def process_clip(
        self,
        video_path: str,
        output_path: str,
        segment_text: str,
        audio_path: Optional[str] = None,
        clip_duration: float = 0.0,
        max_overlays: int = 3,
        overlay_duration_s: float = _BROLL_DURATION,
        words_with_timestamps: Optional[List[Dict]] = None,
        precomputed_keywords: Optional[List[str]] = None,
        broll_fade_s: float = 0.25,
        task_id: Optional[str] = None,
        suggested_broll_cue_type: Optional[str] = None,
        editorial_type: Optional[str] = None,
        vpi_score: Optional[float] = None,
        hook_broll_delay_until_s: float = 0.0,
    ) -> str:
        """
        Full B-roll pipeline for a single clip.

        1. Plan editorial cues locally from the Spanish transcript
        2. Fetch stock/local assets for approved cue visual queries
        3. Insert B-roll overlays at the planner's approved timestamps

        Returns *output_path* on success, *video_path* (original) on failure.
        """
        try:
            self.last_editorial_broll = []
            # ── Duration guard: skip B-roll for very short clips ──────────────
            if clip_duration > 0 and clip_duration < BROLL_MIN_CLIP_DURATION_SEC:
                logger.info("[BRoll] SKIP — clip duration %.1fs < BROLL_MIN_CLIP_DURATION_SEC=%.1fs",
                            clip_duration, BROLL_MIN_CLIP_DURATION_SEC)
                return video_path

            planner = EditorialBrollPlanner()
            clip_theme = detect_clip_theme(
                segment_text,
                editorial_type=editorial_type,
                suggested_broll_cue_type=suggested_broll_cue_type,
                vpi_score=vpi_score,
            )
            clip_index = self._clip_index_from_path(video_path)
            segment_intent = detect_intent(
                segment_text,
                editorial_type=editorial_type,
                suggested_broll_cue_type=suggested_broll_cue_type,
                vpi_score=vpi_score,
                segment_duration=clip_duration,
            )
            logger.info(
                "[theme-context] domain=%s topic=%s visual_mix=%s avoid_overuse=%s",
                clip_theme.domain,
                clip_theme.central_topic,
                "|".join(clip_theme.preferred_visual_mix),
                "|".join(clip_theme.avoid_visual_overuse),
            )
            if segment_intent.intent_type == "weak_intro" and segment_intent.max_overlays == 0:
                logger.info(
                    "[context-no-broll] hard_stop reason=weak_intro_no_broll task=%s clip=%s",
                    task_id or "",
                    Path(video_path).stem,
                )
                return video_path
            cue_decisions = planner.plan(
                transcript_segments=segment_text,
                clip_duration=clip_duration or probe_duration(video_path),
                word_timestamps=words_with_timestamps,
                max_cues=max_overlays,
                suggested_broll_cue_type=suggested_broll_cue_type,
            )
            approved_cues: List[BrollCueDecision] = [
                cue for cue in cue_decisions
                if cue.decision == "approve" and cue.visual_query and cue.start_s is not None
            ]
            safe_approved_cues: List[BrollCueDecision] = []
            for cue in approved_cues:
                explicit_ok, explicit_reason = _is_high_relevance_broll_cue(
                    cue=cue,
                    segment_text=segment_text,
                    theme=clip_theme,
                )
                if not explicit_ok:
                    logger.info(
                        "BROLL_REJECTED_LOW_RELEVANCE task_id=%s clip_order=%s cue=%s reason=%s confidence=%.2f",
                        task_id or "",
                        clip_index,
                        cue.trigger_text or cue.visual_query or cue.cue_type,
                        explicit_reason,
                        float(cue.confidence or 0.0),
                    )
                    continue
                safe_approved_cues.append(cue)
            approved_cues = safe_approved_cues
            if hook_broll_delay_until_s and hook_broll_delay_until_s > 0:
                for cue in approved_cues:
                    old_start = float(cue.start_s or 0.0)
                    if old_start < hook_broll_delay_until_s:
                        cue.start_s = round(float(hook_broll_delay_until_s), 2)
                        logger.info(
                            "[broll-timing-polish] adjusted start due_to_hook_power old=%.2f new=%.2f",
                            old_start,
                            cue.start_s,
                        )
            rejected_cues = [cue for cue in cue_decisions if cue.decision == "reject"]
            for cue in cue_decisions:
                if cue.intent_type:
                    logger.info(
                        "[visual-intent] task=%s clip=%s type=%s confidence=%.2f categories=%s queries=%s avoid=%s",
                        task_id or "",
                        Path(video_path).stem,
                        cue.intent_type,
                        cue.confidence,
                        "|".join(cue.preferred_categories or []),
                        "|".join((cue.preferred_queries or [])[:5]),
                        "|".join((cue.avoid_terms or [])[:8]),
                    )
            logger.info(
                "[editorial-broll] planned cues approved=%d rejected=%d",
                len(approved_cues),
                len(rejected_cues),
            )
            for cue in approved_cues:
                logger.info(
                    "[editorial-broll] approve type=%s start=%.2f dur=%.2f query=%s reason=%s",
                    cue.cue_type,
                    cue.start_s or 0.0,
                    cue.duration_s,
                    cue.visual_query,
                    cue.reason,
                )
            for cue in rejected_cues:
                logger.info(
                    "[editorial-broll] reject type=%s reason=%s",
                    cue.cue_type,
                    cue.reason,
                )

            if not approved_cues:
                logger.info("[broll-select] skipped reason=no_approved_editorial_cues task=%s clip=%s", task_id or "", Path(video_path).stem)
                return video_path

            # Step 2 — try LocalBrollAssetBank first, then stock fetch.
            from ..config import get_config as _get_cfg_asset
            _cfg_asset = _get_cfg_asset()
            _local_bank_enabled = (
                _cfg_asset.enable_local_broll_bank
                if hasattr(_cfg_asset, "enable_local_broll_bank")
                else True
            )

            broll_assets: List[Path] = []
            asset_cues: List[BrollCueDecision] = []
            asset_sources: List[str] = []
            asset_categories: List[str] = []
            asset_scores: List[float] = []
            asset_score_reasons: List[List[str]] = []
            task_seen_assets: set[str] = set()
            task_seen_categories: Dict[str, int] = {}
            for cue in approved_cues:
                if len(broll_assets) >= max_overlays:
                    break

                selection = await self._select_editorial_asset_for_cue(
                    cue=cue,
                    task_id=task_id,
                    task_seen_assets=task_seen_assets,
                    task_seen_categories=task_seen_categories,
                    local_bank_enabled=_local_bank_enabled,
                    theme=clip_theme,
                    clip_index=clip_index,
                )
                asset, asset_source, asset_score, score_reasons, selected_category = self._normalize_editorial_asset_selection(selection)

                if asset:
                    broll_assets.append(asset)
                    asset_cues.append(cue)
                    asset_sources.append(asset_source)
                    asset_categories.append(selected_category or cue.cue_type)
                    asset_scores.append(asset_score)
                    asset_score_reasons.append(score_reasons)
                    task_seen_assets.add(str(asset))
                    if selected_category:
                        task_seen_categories[selected_category] = task_seen_categories.get(selected_category, 0) + 1
                    logger.info(
                        "[editorial-broll] asset query=%s path=%s score=%.1f reasons=%s",
                        cue.visual_query,
                        asset,
                        asset_score,
                        ",".join(score_reasons),
                    )
                    logger.info(
                        "EDITORIAL_BROLL_SELECTED task_id=%s clip_order=%s category=%s asset=%s cue=%s manifest_validated=true",
                        task_id or "",
                        clip_index,
                        selected_category or cue.cue_type,
                        str(asset),
                        cue.trigger_text or cue.visual_query or cue.cue_type,
                    )
                else:
                    logger.info(
                        "LOCAL_BROLL_SKIPPED task_id=%s clip_order=%s reason=no_contextual_match",
                        task_id or "",
                        clip_index,
                    )
                    logger.info(
                        "EDITORIAL_BROLL_SKIPPED task_id=%s clip_order=%s reason=no_editorial_broll_match cue=%s",
                        task_id or "",
                        clip_index,
                        cue.trigger_text or cue.visual_query or cue.cue_type,
                    )
                    logger.info(
                        "EDITORIAL_BROLL_SKIPPED task_id=%s clip_order=%s reason=asset_taxonomy_mismatch cue=%s",
                        task_id or "",
                        clip_index,
                        cue.trigger_text or cue.visual_query or cue.cue_type,
                    )
                    logger.info(
                        "EDITORIAL_BROLL_SKIPPED task_id=%s clip_order=%s reason=asset_brand_fit_false cue=%s",
                        task_id or "",
                        clip_index,
                        cue.trigger_text or cue.visual_query or cue.cue_type,
                    )
                    logger.info(
                        "EDITORIAL_BROLL_SKIPPED task_id=%s clip_order=%s reason=avoid_context_match cue=%s",
                        task_id or "",
                        clip_index,
                        cue.trigger_text or cue.visual_query or cue.cue_type,
                    )
                    logger.info(
                        "[broll-select] skipped reason=no_asset_passed_scoring task=%s clip=%s cue=%s",
                        task_id or "",
                        Path(video_path).stem,
                        cue.cue_type,
                    )

            if not broll_assets:
                logger.info("[broll-select] skipped reason=approved_cues_had_no_usable_assets task=%s clip=%s", task_id or "", Path(video_path).stem)
                return video_path

            insert_timestamps: List[float] = [float(cue.start_s or 0.0) for cue in asset_cues]

            # Step 4 — build (timestamp, asset, duration) pairs and apply in one pass
            broll_pairs: List[Tuple[float, str, float]] = []
            broll_metadata: List[Dict[str, Any]] = []
            for ts, asset, cue, asset_source, selected_category, asset_score, score_reasons in zip(
                insert_timestamps, broll_assets, asset_cues, asset_sources, asset_categories, asset_scores, asset_score_reasons
            ):
                remaining = max(0.0, (clip_duration or cue.duration_s + ts + 1.0) - ts - 0.5)
                requested = float(cue.duration_s or _BETA_CLEAN_BROLL_TARGET_S)
                effective = min(requested, remaining) if remaining > 0 else requested
                is_image = asset.suffix.lower() in _IMAGE_EXTS
                if is_image:
                    effective = min(effective, 1.5)
                asset_duration = _BETA_CLEAN_BROLL_TARGET_S if is_image else probe_duration(asset)
                logger.info(
                    "[broll-duration] requested=%.2f asset_duration=%.2f effective=%.2f",
                    requested,
                    asset_duration,
                    effective,
                )
                if effective < _BETA_CLEAN_BROLL_MIN_VISIBLE_S:
                    logger.info("[broll-duration] skipped too short after clamp")
                    continue
                if not is_image and asset_duration < effective:
                    logger.info("[broll-duration] extended/looped to effective=%.2f", effective)
                source_key = "pexels" if asset_source == "stock" else asset_source
                provider_asset_id = self._downloaded_provider_asset_ids.get(str(asset))
                selected_asset_id = asset_id_for(source_key, str(asset), provider_asset_id)
                selected_fingerprint = visual_fingerprint_for(source_key, str(asset), selected_category)
                broll_pairs.append((ts, str(asset), effective))
                broll_metadata.append({
                    "cue_type": cue.cue_type,
                    "selected_category": selected_category,
                    "trigger_text": cue.trigger_text,
                    "visual_query": cue.visual_query,
                    "asset_path": str(asset),
                    "asset_id": selected_asset_id,
                    "provider_video_id": provider_asset_id,
                    "asset_source": asset_source,
                    "asset_score": asset_score,
                    "asset_score_reasons": score_reasons,
                    "broll_relevance_score": next((reason.split(":", 1)[1] for reason in score_reasons if reason.startswith("broll_relevance_score:")), None),
                    "broll_relevance_reason": next((reason.split(":", 1)[1] for reason in score_reasons if reason.startswith("broll_relevance_reason:")), None),
                    "broll_phrase_fit_score": next((reason.split(":", 1)[1] for reason in score_reasons if reason.startswith("broll_phrase_fit_score:")), None),
                    "broll_phrase_fit_label": next((reason.split(":", 1)[1] for reason in score_reasons if reason.startswith("broll_phrase_fit_label:")), None),
                    "broll_phrase_fit_reason": next((reason.split(":", 1)[1] for reason in score_reasons if reason.startswith("broll_phrase_fit_reason:")), None),
                    "broll_allowed_as_primary": next((reason.split(":", 1)[1] for reason in score_reasons if reason.startswith("broll_allowed_as_primary:")), None),
                    "broll_allowed_as_support": next((reason.split(":", 1)[1] for reason in score_reasons if reason.startswith("broll_allowed_as_support:")), None),
                    "broll_motion_type": next((reason.split(":", 1)[1] for reason in score_reasons if reason.startswith("broll_motion_type:")), "static_image" if is_image else "unknown"),
                    "broll_static_penalty": next((reason.split(":", 1)[1] for reason in score_reasons if reason.startswith("broll_static_penalty:")), None),
                    "broll_is_image": is_image,
                    "broll_ken_burns_applied": is_image,
                    "broll_transition_applied": editorial_fade_s > 0.0,
                    "broll_transition_type": "alpha_fade" if editorial_fade_s > 0.0 else "cut",
                    "broll_transition_duration_s": editorial_fade_s,
                    "no_broll_reason": None,
                    "broll_no_broll_reason": None,
                    "broll_used_with_cooldown_exception": any(reason == "broll_used_with_cooldown_exception:true" for reason in score_reasons),
                    "broll_cooldown_exception_reason": next((reason.split(":", 1)[1] for reason in score_reasons if reason.startswith("cooldown_exception_reason:")), None),
                    "broll_candidates_total": next((reason.split(":", 1)[1] for reason in score_reasons if reason.startswith("broll_candidates_total:")), None),
                    "broll_candidates_rejected_forbidden": next((reason.split(":", 1)[1] for reason in score_reasons if reason.startswith("broll_candidates_rejected_forbidden:")), None),
                    "broll_candidates_rejected_cooldown": next((reason.split(":", 1)[1] for reason in score_reasons if reason.startswith("broll_candidates_rejected_cooldown:")), None),
                    "broll_candidates_rejected_relevance": next((reason.split(":", 1)[1] for reason in score_reasons if reason.startswith("broll_candidates_rejected_relevance:")), None),
                    "broll_candidates_usable": next((reason.split(":", 1)[1] for reason in score_reasons if reason.startswith("broll_candidates_usable:")), None),
                    "asset_freshness_score": next((reason.split(":", 1)[1] for reason in score_reasons if reason.startswith("freshness_score:")), None),
                    "last_used_at": next((reason.split(":", 1)[1] for reason in score_reasons if reason.startswith("last_used_at:")), None),
                    "recent_use_penalty": sum(
                        float(reason.rsplit(":", 1)[1])
                        for reason in score_reasons
                        if reason.startswith(("same_task_exact_asset:", "asset_used_24h:", "asset_used_3d:", "asset_used_7d:", "same_task_visual_fingerprint:", "visual_fingerprint_24h:"))
                    ),
                    "visual_fingerprint": next((reason.split(":", 1)[1] for reason in score_reasons if reason.startswith("visual_fingerprint:")), None),
                    "broll_hard_guard_rejections": list(self._broll_hard_guard_rejections),
                    "broll_forbidden_reason": None,
                    "broll_repetition_guard": {
                        "asset_id": selected_asset_id,
                        "provider_video_id": provider_asset_id,
                        "visual_fingerprint": selected_fingerprint,
                        "repeated_broll_rejected": bool(self._broll_hard_guard_rejections),
                        "visual_fingerprint_repeats": [
                            item for item in self._broll_hard_guard_rejections
                            if "visual_fingerprint_repeat" in item.get("reasons", [])
                        ],
                    },
                    "broll_task_duplicate_rejected": any(
                        any(reason in {"exact_asset_repeat", "provider_video_repeat", "filename_stem_repeat", "visual_fingerprint_repeat"} for reason in item.get("reasons", []))
                        for item in self._broll_hard_guard_rejections
                    ),
                    "broll_task_diversity_reason": "unique_asset_selected",
                    "broll_reused_in_task": False,
                    "intent_type": cue.intent_type,
                    "preferred_queries": cue.preferred_queries or [],
                    "avoid_terms": cue.avoid_terms or [],
                    "theme_domain": clip_theme.domain,
                    "theme_topic": clip_theme.central_topic,
                    "theme_visual_mix": clip_theme.preferred_visual_mix,
                    "start_s": ts,
                    "requested_duration": requested,
                    "asset_duration": asset_duration,
                    "effective_duration": effective,
                    "transition": cue.transition,
                    "reason": cue.reason,
                })

            if not broll_pairs:
                logger.info("[broll-select] skipped reason=no_suitable_duration_after_clamp task=%s clip=%s", task_id or "", Path(video_path).stem)
                return video_path
            coverage = sum(duration for _, _, duration in broll_pairs) / max(1.0, float(clip_duration or probe_duration(video_path) or 1.0))
            logger.info(
                "[broll-select] coverage=%.3f overlays=%d task=%s clip=%s",
                coverage,
                len(broll_pairs),
                task_id or "",
                Path(video_path).stem,
            )

            editorial_fade_s = max(0.16, min(0.20, broll_fade_s))
            if len(broll_pairs) == 1:
                ts, asset_path, dur = broll_pairs[0]
                ok = await self.insert_broll(
                    video_path=video_path,
                    fade=editorial_fade_s,
                    output_path=output_path,
                    broll_path=asset_path,
                    timestamp=ts,
                    overlay_duration=dur,
                )
            else:
                from .broll_compositor import compose_overlay_multi
                ok = await compose_overlay_multi(
                    fade=editorial_fade_s,
                    main_path=video_path,
                    broll_pairs=broll_pairs,
                    output_path=output_path,
                )

            if ok:
                self.last_editorial_broll = broll_metadata
                logger.info("[broll-select] final_count=%d task=%s clip=%s", len(broll_pairs), task_id or "", Path(video_path).stem)
                logger.info(f"[BRoll] ✓ {len(broll_pairs)} overlays applied: {[f't={t:.1f}s' for t,_,_ in broll_pairs]}")
            return output_path if ok else video_path

        except Exception as e:
            logger.error(f"[BRoll] process_clip failed: {e}", exc_info=True)
            return video_path


# ──────────────────────────────────────────────────────────────────────────────
# B-ROLL TRANSITIONS — Entry and exit effects for cinematic feel
# ──────────────────────────────────────────────────────────────────────────────

def apply_broll_transitions(
    broll_path: str,
    output_path: str,
    duration: float,
    transition_duration: float = 0.25
) -> Optional[str]:
    """
    Apply zoom-punch entry and fade-out exit to B-roll clip.
    Entry: smooth zoom from 1.0 to 1.08 in first transition_duration seconds
    Exit: fade-out with slight motion blur in last transition_duration seconds
    """
    try:
        fade_out_start = max(0, duration - transition_duration)
        total_frames = int(duration * 30)
        zoom_frames = int(transition_duration * 30)

        # Build filter_complex with scale/crop, zoom-in entry and fade-out exit
        filter_complex = (
            f"[0:v]"
            f"scale=576:1024:force_original_aspect_ratio=increase,"
            f"crop=576:1024,"
            f"fade=t=in:st=0:d={transition_duration}:alpha=1,"
            f"zoompan=z='if(lte(in,{zoom_frames}),1.0+0.08*in/{zoom_frames},1.08)':"
            f"d={total_frames}:s=576x1024:fps=30,"
            f"fade=t=out:st={fade_out_start}:d={transition_duration}"
            f"[vout];"
            f"[0:a]"
            f"afade=t=in:st=0:d={transition_duration},"
            f"afade=t=out:st={fade_out_start}:d={transition_duration}"
            f"[aout]"
        )

        cmd = [
            "ffmpeg", "-y", "-i", broll_path,
            "-filter_complex", filter_complex,
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "h264_nvenc", "-rc", "constqp", "-qp", "18",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            # Fallback to software encoding if NVENC fails
            logger.warning("[BRoll] NVENC failed, retrying with libx264")
            cmd[cmd.index("h264_nvenc")] = "libx264"
            cmd[cmd.index("-rc")] = "-crf"
            cmd[cmd.index("-qp")] = "18"
            cmd.insert(cmd.index("-crf") + 2, "-preset")
            cmd.insert(cmd.index("-preset") + 1, "fast")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode == 0 and Path(output_path).exists():
            logger.info(f"[BRoll] ✓ Transitions applied: {Path(output_path).name}")
            return output_path
        else:
            logger.warning(f"[BRoll] Transition filter failed: {result.stderr[:200]}")
            return None
    except Exception as e:
        logger.warning(f"[BRoll] apply_broll_transitions error: {e}")
        return None
