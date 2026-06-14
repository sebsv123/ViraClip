"""VPI_EDITORIAL_SFX — small, controlled editorial SFX route (local assets only).

Distinct from the legacy creative_pipeline/smart_audio route (which injected
hundreds of clicks/typewriter and stays disabled). This service applies at most a
couple of well-placed, voice-subordinate SFX at clear editorial moments and mixes
them BEFORE the final loudness master. No click/glitch/typewriter, ever.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import unicodedata
import hashlib
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# Tokens that must NEVER be used as editorial SFX.
FORBIDDEN_TOKENS = {"click", "glitch", "typing", "typewriter", "tick", "keyboard", "pop", "key_"}

# family -> ordered local candidate assets (repo-relative).
SFX_LIBRARY: Dict[str, Tuple[str, ...]] = {
    "soft_whoosh": (
        "assets/sounds/whoosh_fast.mp3",
    ),
    "magic_whoosh": (
        "assets/sounds/sfx/magic_whoosh/magic_whoosh_pixabay_001.mp3",
        "assets/sounds/sfx/magic_whoosh/magic_whoosh_pixabay_002.mp3",
        "assets/sounds/sfx/magic_whoosh/magic_whoosh_pixabay_003.wav",
        "assets/sounds/sfx/magic_whoosh/magic_whoosh_pixabay_004.mp3",
    ),
    "dark_riser": (
        "assets/sounds/sfx/dark_riser/dark_riser_pixabay_001.wav",
        "assets/sounds/sfx/dark_riser/dark_riser_pixabay_002.mp3",
        "assets/sounds/sfx/dark_riser/dark_riser_pixabay_003.mp3",
    ),
    "high_riser": (
        "assets/sounds/sfx/tension_riser/dragon-studio-riser-swoosh-reverb-390311.mp3",
        "assets/sounds/tension_riser_short.mp3",
    ),
    "deep_boom": (
        "assets/sounds/sfx/deep_boom/deep_boom_mixkit_001.mp3",
        "assets/sounds/sfx/deep_boom/deep_boom_mixkit_002.mp3",
        "assets/sounds/sfx/deep_boom/deep_boom_mixkit_003.mp3",
        "assets/sounds/sfx/deep_boom/deep_boom_mixkit_004.wav",
    ),
    "soft_impact": (
        "assets/sounds/punch_impact.mp3",
    ),
    "soft_chime": (
        "assets/sounds/sfx/soft_chime/soft_chime_pixabay_001.mp3",
        "assets/sounds/sfx/soft_chime/soft_chime_pixabay_002.mp3",
        "assets/sounds/sfx/soft_chime/soft_chime_pixabay_003.wav",
        "assets/sounds/sfx/soft_chime/soft_chime_pixabay_004.wav",
        "assets/sounds/ding_chime_soft.mp3",
    ),
}

# editorial event type -> ordered preferred families.
EVENT_TYPE_FAMILIES: Dict[str, Tuple[str, ...]] = {
    "visual_transition": ("soft_whoosh", "magic_whoosh"),
    "risk_revelation": ("dark_riser", "soft_impact"),
    "payoff_emphasis": ("soft_chime", "magic_whoosh", "soft_impact"),
    "silence_punctuation": ("soft_impact", "soft_chime", "deep_boom"),
}

# headroom (dB) the SFX peak sits BELOW the clip audio peak -> voice stays dominant.
EVENT_HEADROOM_DB: Dict[str, float] = {
    "visual_transition": 9.0,
    "payoff_emphasis": 10.0,
    "risk_revelation": 12.0,
    "silence_punctuation": 18.0,
}
EVENT_DURATION_S: Dict[str, float] = {
    "visual_transition": 0.6,
    "payoff_emphasis": 0.7,
    "risk_revelation": 0.8,
    "silence_punctuation": 0.45,
}

MIN_EVENT_SEPARATION_S = 8.0
END_GUARD_S = 0.8
GAIN_FLOOR_DB = -40.0
GAIN_CEIL_DB = 6.0
DEFAULT_FALLBACK_GAIN_DB = -16.0
SILENCE_PUNCTUATION_GAIN_CEIL_DB = -18.0
_TASK_USED_SFX_ASSETS: Dict[str, set] = {}
_TASK_USED_SFX_LOCK = threading.Lock()


@dataclass
class EditorialSfxPlan:
    planned: bool = False
    rendered: bool = False
    event_type: str = ""
    asset_path: str = ""
    start_s: float = 0.0
    duration_s: float = 0.0
    gain: float = 0.0
    trigger_reason: str = ""
    confidence: float = 0.0
    skip_reason: str = ""
    family: str = ""
    signal_type: str = ""
    signal_text: str = ""
    signal_confidence: float = 0.0
    signal_source: str = ""
    priority: int = 0
    collision_reason: str = ""
    events: List[Dict[str, Any]] = field(default_factory=list)
    silence_punctuation_candidates: List[Dict[str, Any]] = field(default_factory=list)
    silence_punctuation_result: str = ""

    def as_dict(self) -> Dict[str, Any]:
        first_event = (self.events or [{}])[0] if self.events else {}
        pause_event = next((e for e in self.events if e.get("event_type") == "silence_punctuation"), first_event)
        return {
            "editorial_sfx_planned": bool(self.planned),
            "editorial_sfx_rendered": bool(self.rendered),
            "editorial_sfx_count": len(self.events),
            "editorial_sfx_events": list(self.events),
            "editorial_sfx_asset": self.asset_path,
            "editorial_sfx_type": self.event_type,
            "editorial_sfx_family": self.family,
            "editorial_sfx_start_s": round(self.start_s, 2),
            "editorial_sfx_gain": round(self.gain, 2),
            "editorial_sfx_trigger_reason": self.trigger_reason,
            "editorial_sfx_confidence": round(self.confidence, 3),
            "editorial_sfx_skip_reason": self.skip_reason,
            "editorial_sfx_signal_type": self.signal_type,
            "editorial_sfx_signal_text": self.signal_text,
            "editorial_sfx_signal_confidence": round(self.signal_confidence, 3),
            "editorial_sfx_signal_source": self.signal_source,
            "editorial_sfx_priority": int(self.priority),
            "editorial_sfx_collision_reason": self.collision_reason,
            "editorial_sfx_legacy_route_disabled": True,
            "editorial_sfx_asset_candidates": list(first_event.get("asset_candidates") or []),
            "editorial_sfx_asset_selected": str(first_event.get("asset_selected") or self.asset_path or ""),
            "editorial_sfx_asset_family": str(first_event.get("asset_family") or self.family or ""),
            "editorial_sfx_asset_selection_index": int(first_event.get("asset_selection_index") or 0),
            "editorial_sfx_asset_selection_seed": str(first_event.get("asset_selection_seed") or ""),
            "editorial_sfx_asset_recently_avoided": list(first_event.get("asset_recently_avoided") or []),
            "editorial_sfx_asset_single_family_fallback": bool(first_event.get("asset_single_family_fallback")),
            "editorial_sfx_asset_measured_gain": float(first_event.get("measured_gain") or self.gain or 0.0),
            "editorial_sfx_pause_class": str(pause_event.get("pause_class") or ""),
            "editorial_sfx_pause_duration_s": float(pause_event.get("pause_duration_s") or 0.0),
            "editorial_sfx_pause_before_text": str(pause_event.get("pause_before_text") or ""),
            "editorial_sfx_pause_after_text": str(pause_event.get("pause_after_text") or ""),
            "editorial_sfx_silence_preferred": bool(pause_event.get("silence_preferred") or self.silence_punctuation_result == "silence_preferred"),
            "silence_punctuation_candidates": list(self.silence_punctuation_candidates or pause_event.get("silence_punctuation_candidates") or []),
            "silence_punctuation_class": str(pause_event.get("silence_punctuation_class") or pause_event.get("pause_class") or ""),
            "silence_punctuation_pause_start_s": float(pause_event.get("pause_start_s") or 0.0),
            "silence_punctuation_pause_end_s": float(pause_event.get("pause_end_s") or 0.0),
            "silence_punctuation_duration_s": float(pause_event.get("pause_duration_s") or 0.0),
            "silence_punctuation_trigger_before": str(pause_event.get("pause_before_text") or ""),
            "silence_punctuation_trigger_after": str(pause_event.get("pause_after_text") or ""),
            "silence_punctuation_confidence": float(pause_event.get("pause_confidence") or 0.0),
            "silence_punctuation_result": str(pause_event.get("silence_punctuation_result") or self.silence_punctuation_result or ""),
        }


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "assets" / "sounds").exists() and (parent / "backend").exists():
            return parent
        if (parent / "assets" / "sounds").exists() and (parent / "src").exists():
            return parent
    return here.parents[2]


def _abs_asset(rel: str) -> str:
    if not rel:
        return ""
    p = Path(rel)
    if p.is_absolute():
        return str(p) if p.exists() else ""
    cand = _repo_root() / rel
    return str(cand) if cand.exists() else ""


def _is_forbidden(path: str) -> bool:
    low = str(path or "").lower()
    return any(tok in low for tok in FORBIDDEN_TOKENS)


def _is_asset_readable(path: str) -> bool:
    abs_path = _abs_asset(path)
    if not abs_path:
        return False
    try:
        return Path(abs_path).stat().st_size > 0
    except Exception:
        return False


def discover_sfx_assets() -> Dict[str, List[str]]:
    """Return existing, non-forbidden assets per family."""
    out: Dict[str, List[str]] = {}
    for family, cands in SFX_LIBRARY.items():
        found = [c for c in cands if _abs_asset(c) and not _is_forbidden(c)]
        if found:
            out[family] = found
    return out


def _recent_editorial_sfx_assets(limit: int = 5) -> List[str]:
    """Best-effort recent manifest scan. Safe to fail; no DB/locks."""
    roots = [Path("outputs/tasks"), Path("/app/outputs/tasks")]
    rows: List[Tuple[float, str]] = []
    for root in roots:
        if not root.exists():
            continue
        try:
            manifests = sorted(root.glob("*/manifests/vpi_output_manifest.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
        except Exception:
            manifests = []
        for manifest in manifests:
            try:
                text = manifest.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for match in re.finditer(r'"asset_path"\s*:\s*"([^"]+)"', text):
                asset = match.group(1)
                if "sounds" in asset and not _is_forbidden(asset):
                    rows.append((manifest.stat().st_mtime, asset))
            for match in re.finditer(r'"editorial_sfx_asset_selected"\s*:\s*"([^"]+)"', text):
                asset = match.group(1)
                if asset and not _is_forbidden(asset):
                    rows.append((manifest.stat().st_mtime, asset))
    out: List[str] = []
    for _mtime, asset in sorted(rows, key=lambda item: item[0], reverse=True):
        if asset not in out:
            out.append(asset)
        if len(out) >= limit:
            break
    return out


def _candidate_pool_for_event(event_type: str, *, sensitive: bool = False, exclude_families: Optional[set] = None) -> List[Dict[str, Any]]:
    exclude = exclude_families or set()
    families = SENSITIVE_RISK_FAMILIES if event_type == "risk_revelation" and sensitive else EVENT_TYPE_FAMILIES.get(event_type, ())
    pool: List[Dict[str, Any]] = []
    for family in families:
        if family in exclude:
            continue
        if event_type == "visual_transition" and family in {"soft_impact", "deep_boom", "dark_riser", "high_riser"}:
            continue
        if event_type == "payoff_emphasis" and family in {"dark_riser", "deep_boom", "high_riser"}:
            continue
        if event_type == "risk_revelation" and sensitive and family in {"dark_riser", "deep_boom", "high_riser"}:
            continue
        if event_type == "risk_revelation" and family == "deep_boom":
            continue
        if event_type == "silence_punctuation" and family in {"soft_whoosh", "magic_whoosh", "dark_riser", "high_riser"}:
            continue
        if event_type == "silence_punctuation" and sensitive and family == "deep_boom":
            continue
        for index, cand in enumerate(SFX_LIBRARY.get(family, ())):
            if _is_forbidden(cand):
                continue
            if _is_asset_readable(cand):
                pool.append({"family": family, "asset": cand, "family_index": index})
    return pool


def select_editorial_sfx_asset(
    *,
    family: str = "",
    event_type: str,
    task_id: str = "",
    clip_order: int = 0,
    trigger_text: str = "",
    used_assets: Optional[set] = None,
    used_families: Optional[set] = None,
    recent_assets: Optional[Sequence[str]] = None,
    sensitive: bool = False,
) -> Dict[str, Any]:
    """Select a compatible local SFX asset with deterministic variation."""
    used_assets = set(used_assets or set())
    used_families = used_families or set()
    recent_assets = list(recent_assets or [])
    if family:
        pool = [
            {"family": family, "asset": cand, "family_index": idx}
            for idx, cand in enumerate(SFX_LIBRARY.get(family, ()))
            if family not in used_families and not _is_forbidden(cand) and _is_asset_readable(cand)
        ]
    else:
        pool = _candidate_pool_for_event(event_type, sensitive=sensitive, exclude_families=used_families)

    original_pool = list(pool)
    logger.info(
        "VPI_EDITORIAL_SFX_VARIANTS_FOUND event=%s family=%s candidates=%d",
        event_type, family or "event_policy", len(original_pool),
    )
    if not pool:
        return {
            "family": "",
            "asset": "",
            "candidates": [],
            "selection_index": -1,
            "selection_seed": "",
            "recently_avoided": [],
            "single_family_fallback": False,
            "skip_reason": "no_compatible_asset",
        }

    pool_without_used = [item for item in pool if item["asset"] not in used_assets]
    if pool_without_used:
        pool = pool_without_used
    single_family_fallback = len(pool) == 1
    recent_set = set(recent_assets)
    recent_avoided: List[str] = []
    pool_without_recent = [item for item in pool if item["asset"] not in recent_set]
    if pool_without_recent:
        recent_avoided = [item["asset"] for item in pool if item["asset"] in recent_set]
        if recent_avoided:
            logger.info(
                "VPI_EDITORIAL_SFX_ASSET_REPEAT_AVOIDED event=%s avoided=%s",
                event_type, ",".join(recent_avoided),
            )
        pool = pool_without_recent
    if len(pool) == 1 and len(original_pool) == 1:
        logger.info("VPI_EDITORIAL_SFX_ASSET_SINGLE_FALLBACK event=%s asset=%s", event_type, pool[0]["asset"])
        single_family_fallback = True

    seed = "|".join([str(task_id or ""), str(int(clip_order or 0)), event_type, _normalize_text(trigger_text)])
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    selection_index = int(digest[:8], 16) % len(pool)
    selected = pool[selection_index]
    logger.info(
        "VPI_EDITORIAL_SFX_ASSET_SELECTED event=%s family=%s asset=%s index=%d seed=%s",
        event_type, selected["family"], selected["asset"], selection_index, digest[:12],
    )
    return {
        "family": selected["family"],
        "asset": selected["asset"],
        "candidates": [item["asset"] for item in original_pool],
        "selection_index": selection_index,
        "selection_seed": digest[:12],
        "recently_avoided": recent_avoided,
        "single_family_fallback": bool(single_family_fallback),
        "skip_reason": "",
    }


def resolve_event_asset(event_type: str, exclude_families: Optional[set] = None) -> Tuple[str, str]:
    """Compatibility wrapper for older tests/callers."""
    selected = select_editorial_sfx_asset(event_type=event_type, used_families=exclude_families or set())
    return str(selected.get("family") or ""), str(selected.get("asset") or "")


# OUTPUT-SFX-19 — strong, conservative textual triggers (normalized, accent-insensitive).
RISK_PATTERNS: Tuple[Tuple[str, float], ...] = (
    ("la salud no siempre avisa", 0.85),
    ("no siempre avisa", 0.74),
    ("esto mucha gente no lo sabe", 0.82),
    ("mucha gente no lo sabe", 0.76),
    ("lo que nadie te explica", 0.82),
    ("cuando ya es tarde", 0.78),
    ("el problema es que", 0.72),
    ("no todos los seguros", 0.74),
    ("por si acaso", 0.66),
    ("puede pasar", 0.62),
    ("imprevisto", 0.60),
)
PAYOFF_PATTERNS: Tuple[Tuple[str, float], ...] = (
    ("sino de comparar con contexto", 0.86),
    ("comparar con contexto", 0.80),
    ("prefiero explicarlo desde el cuidado", 0.86),
    ("desde el cuidado", 0.72),
    ("no es pagar mas es elegir mejor", 0.84),
    ("elegir mejor", 0.72),
    ("antes de contratar", 0.74),
    ("por eso conviene", 0.74),
    ("la clave esta en", 0.76),
    ("eso es lo importante", 0.74),
    ("decide mejor", 0.72),
    ("vive mas tranquila", 0.72),
    ("vivir mas tranquilo", 0.72),
)

EVENT_PRIORITY: Dict[str, int] = {
    "visual_transition": 1,
    "payoff_emphasis": 2,
    "risk_revelation": 3,
    "silence_punctuation": 4,
}
# On sensitive topics (decesos/illness/death) risk uses ONLY soft_impact (no boom/riser drama).
SENSITIVE_RISK_FAMILIES: Tuple[str, ...] = ("soft_impact",)
SIGNAL_CONFIDENCE_THRESHOLD = 0.70
VISUAL_COLLISION_WINDOW_S = 4.0


def _normalize_text(s: Any) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _resolve_from_families(families: Tuple[str, ...], exclude: Optional[set] = None) -> Tuple[str, str]:
    exclude = exclude or set()
    for family in families:
        if family in exclude:
            continue
        selected = select_editorial_sfx_asset(family=family, event_type="risk_revelation", used_families=exclude)
        if selected.get("family") and selected.get("asset"):
            return str(selected["family"]), str(selected["asset"])
    return "", ""


def detect_editorial_signal(
    words: Optional[List[Dict[str, Any]]] = None,
    editorial_type: str = "",
    matched_patterns: Optional[List[str]] = None,
    travel_context: bool = False,
) -> List[Dict[str, Any]]:
    """Find strong risk/payoff phrases in the POST-CUT word timeline (non-stale)."""
    words = words or []
    toks: List[Tuple[str, float]] = []
    for w in words:
        nt = _normalize_text(w.get("word") if isinstance(w, dict) else w)
        if nt:
            for piece in nt.split():
                toks.append((piece, float((w or {}).get("start") or 0.0)))
    if not toks:
        return []
    norm_words = [t[0] for t in toks]
    et = _normalize_text(editorial_type)
    mp = " ".join(_normalize_text(p) for p in (matched_patterns or []))
    risk_boost = 0.15 if any(k in et for k in ("risk", "revelation", "myth", "objection")) or any(k in mp for k in ("risk", "myth", "revelation")) else 0.0
    payoff_boost = 0.15 if any(k in et for k in ("advice", "coverage", "revelation", "payoff", "closure")) or any(k in mp for k in ("payoff", "advice", "closure")) else 0.0

    def find_phrase(phrase: str) -> Optional[float]:
        ptoks = phrase.split()
        n = len(ptoks)
        for i in range(0, len(norm_words) - n + 1):
            if norm_words[i:i + n] == ptoks:
                return toks[i][1]
        return None

    out: List[Dict[str, Any]] = []
    for phrase, base in RISK_PATTERNS:
        if phrase == "por si acaso" and travel_context:
            continue
        st = find_phrase(phrase)
        if st is None:
            continue
        out.append({
            "event_type": "risk_revelation", "start_s": st, "trigger_text": phrase,
            "confidence": round(min(0.99, base + risk_boost), 3),
            "source": "text_pattern+editorial_type",
        })
    for phrase, base in PAYOFF_PATTERNS:
        st = find_phrase(phrase)
        if st is None:
            continue
        out.append({
            "event_type": "payoff_emphasis", "start_s": st, "trigger_text": phrase,
            "confidence": round(min(0.99, base + payoff_boost), 3),
            "source": "text_pattern+editorial_type",
        })
    return out


_BACKSTAGE_TERMS = {
    "esta raro", "quedo raro", "otra vez", "vamos de nuevo", "espera", "esperate",
    "a ver", "corta", "grabando", "repite", "ahora si", "me trabe", "me equivoque",
}
_TRUNCATED_END_TERMS = {"de", "que", "para", "por", "con", "sin", "y", "o", "pero", "porque", "si"}
_SENSITIVE_TERMS = {"decesos", "duelo", "fallec", "enfermedad", "luto", "muerte"}


def _word_text(w: Dict[str, Any]) -> str:
    return str(w.get("word") or w.get("text") or "").strip()


def _final_pause_candidates_from_words(words: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    clean: List[Dict[str, Any]] = []
    for item in words or []:
        try:
            st = float((item or {}).get("start") or 0.0)
            en = float((item or {}).get("end") or st)
        except Exception:
            continue
        txt = _word_text(item)
        if txt and en >= st:
            clean.append({"word": txt, "start": st, "end": en})
    out: List[Dict[str, Any]] = []
    for idx in range(1, len(clean)):
        prev = clean[idx - 1]
        nxt = clean[idx]
        start = float(prev["end"])
        end = float(nxt["start"])
        dur = round(end - start, 3)
        if dur < 0.25:
            continue
        before_words = [_word_text(w) for w in clean[max(0, idx - 12):idx]]
        after_words = [_word_text(w) for w in clean[idx:min(len(clean), idx + 12)]]
        out.append({
            "pause_start_s": round(start, 3),
            "pause_end_s": round(end, 3),
            "pause_duration_s": dur,
            "before_text": " ".join(before_words).strip(),
            "after_text": " ".join(after_words).strip(),
            "prev_word": _normalize_text(prev.get("word")),
            "next_word": _normalize_text(nxt.get("word")),
        })
    return out


def _pause_editorial_pattern(before: str, after: str) -> Tuple[str, float, str]:
    b = _normalize_text(before)
    a = _normalize_text(after)
    joined = f"{b} {a}".strip()
    if "?" in before or any(k in b for k in ("que necesitas", "cual es la clave", "sabes que necesitas")):
        if len(a.split()) >= 3:
            return "question_to_answer", 0.84, "pregunta_respuesta"
    if any(k in b for k in ("la salud no siempre avisa", "esto mucha gente no lo sabe", "no siempre avisa")):
        if len(a.split()) >= 3:
            return "risk_to_explanation", 0.86, "riesgo_explicacion"
    if any(k in b for k in ("no se trata de pagar mas", "no me gusta explicarlo desde el susto", "no es pagar mas")):
        if any(k in a for k in ("se trata", "sino", "prefiero", "comparar", "elegir")):
            return "contrast_to_payoff", 0.88, "contraste_payoff"
    if any(k in b for k in ("la clave esta en", "por eso conviene", "antes de contratar")):
        if len(a.split()) >= 3:
            return "thesis_to_conclusion", 0.82, "tesis_conclusion"
    if any(k in joined for k in ("sino de comparar con contexto", "comparar con contexto")):
        return "contrast_to_payoff", 0.82, "comparar_contexto"
    return "", 0.0, ""


def _classify_final_pause(
    pause: Dict[str, Any],
    *,
    sensitive: bool = False,
    flagged: bool = False,
) -> Dict[str, Any]:
    dur = float(pause.get("pause_duration_s") or 0.0)
    before = str(pause.get("before_text") or "")
    after = str(pause.get("after_text") or "")
    norm = _normalize_text(f"{before} {after}")
    result = dict(pause)
    result.update({
        "classification": "NATURAL_SILENCE",
        "confidence": 0.55,
        "result": "silence_preferred",
        "reason": "natural_pause",
        "punctuate": False,
    })
    logger.info(
        "VPI_SILENCE_PUNCTUATION_PAUSE_FOUND start=%.2f end=%.2f dur=%.2f",
        float(pause.get("pause_start_s") or 0.0),
        float(pause.get("pause_end_s") or 0.0),
        dur,
    )
    if flagged:
        result.update({"classification": "NATURAL_SILENCE", "confidence": 0.0, "result": "rejected", "reason": "flagged_clip"})
    elif any(term in norm for term in _BACKSTAGE_TERMS):
        result.update({"classification": "NATURAL_SILENCE", "confidence": 0.0, "result": "rejected", "reason": "backstage_or_retake"})
    elif str(pause.get("prev_word") or "") in _TRUNCATED_END_TERMS:
        result.update({"classification": "NATURAL_SILENCE", "confidence": 0.0, "result": "rejected", "reason": "truncated_before_pause"})
    elif dur >= 1.2:
        result.update({"classification": "DEAD_AIR_REMOVE", "confidence": 0.86, "result": "remove_or_compress", "reason": "dead_air_no_sfx"})
    elif 0.8 <= dur <= 1.5:
        result.update({"classification": "COMPRESSED_BREATH", "confidence": 0.72, "result": "compress_or_short_silence", "reason": "breath_or_thinking_pause"})
    elif sensitive and any(term in norm for term in _SENSITIVE_TERMS):
        result.update({"classification": "NATURAL_SILENCE", "confidence": 0.76, "result": "silence_preferred", "reason": "sensitive_silence"})
    elif 0.25 <= dur <= 0.90:
        pattern, confidence, reason = _pause_editorial_pattern(before, after)
        if pattern:
            result.update({
                "classification": "KEEP_EDITORIAL_PAUSE",
                "confidence": confidence,
                "result": "preserve",
                "reason": reason,
                "editorial_pattern": pattern,
            })
            if 0.30 <= dur <= 0.75 and confidence >= 0.82:
                result.update({
                    "classification": "PUNCTUATE_EDITORIAL_PAUSE",
                    "result": "punctuate_if_budget_allows",
                    "punctuate": True,
                })
        else:
            result.update({
                "classification": "KEEP_EDITORIAL_PAUSE" if dur <= 0.90 else "NATURAL_SILENCE",
                "confidence": 0.62,
                "result": "silence_preferred",
                "reason": "no_strong_punctuation_pattern",
            })
    logger.info(
        "VPI_SILENCE_PUNCTUATION_CLASSIFIED class=%s result=%s reason=%s conf=%.2f",
        result["classification"], result["result"], result["reason"], float(result.get("confidence") or 0.0),
    )
    if result["result"] in {"preserve", "silence_preferred"}:
        logger.info("VPI_SILENCE_PUNCTUATION_PRESERVED class=%s", result["classification"])
    if result["result"] == "silence_preferred":
        logger.info("VPI_SILENCE_PUNCTUATION_SILENCE_PREFERRED reason=%s", result["reason"])
    if result["result"] == "rejected":
        logger.info("VPI_SILENCE_PUNCTUATION_REJECTED reason=%s", result["reason"])
    return result


def detect_editorial_pause_signal(
    *,
    final_words: Optional[List[Dict[str, Any]]] = None,
    final_transcript: str = "",
    pause_candidates: Optional[Sequence[Dict[str, Any]]] = None,
    existing_events: Optional[Sequence[Dict[str, Any]]] = None,
    editorial_type: str = "",
    matched_patterns: Optional[List[str]] = None,
    flagged: bool = False,
    sensitive: bool = False,
) -> Dict[str, Any]:
    """Classify final post-cut pauses and return at most one punctuation signal."""
    del final_transcript, matched_patterns  # reserved for future richer signals
    source = list(pause_candidates or []) or _final_pause_candidates_from_words(final_words or [])
    existing = list(existing_events or [])
    classified = [_classify_final_pause(p, sensitive=sensitive, flagged=flagged) for p in source]
    summary = {
        "candidates": classified[:8],
        "selected": None,
        "skip_reason": "no_final_pause_candidates" if not classified else "silence_preferred",
    }
    if flagged:
        summary["skip_reason"] = "flagged_clip"
        return summary
    if any(not e.get("is_visual") for e in existing):
        summary["skip_reason"] = "nonvisual_sfx_already_present"
        return summary
    norm_et = _normalize_text(editorial_type)
    sensitive_pause = sensitive or any(term in norm_et for term in _SENSITIVE_TERMS)
    for item in classified:
        if not bool(item.get("punctuate")):
            continue
        if sensitive_pause and item.get("classification") == "PUNCTUATE_EDITORIAL_PAUSE":
            item = dict(item)
            item["result"] = "silence_preferred"
            item["reason"] = "sensitive_topic_prefers_silence"
            logger.info("VPI_SILENCE_PUNCTUATION_SILENCE_PREFERRED reason=sensitive_topic_prefers_silence")
            continue
        start = max(0.3, float(item.get("pause_start_s") or 0.0) - 0.05)
        if any(abs(start - float(e.get("start_s") or 0.0)) < MIN_EVENT_SEPARATION_S for e in existing):
            logger.info("VPI_SILENCE_PUNCTUATION_REJECTED reason=min_separation")
            summary["skip_reason"] = "min_separation"
            continue
        logger.info(
            "VPI_SILENCE_PUNCTUATION_SFX_SELECTED start=%.2f class=%s reason=%s",
            start, item.get("classification"), item.get("reason"),
        )
        selected = dict(item)
        selected["event_start_s"] = round(start, 2)
        summary["selected"] = selected
        summary["skip_reason"] = ""
        return summary
    return summary


def build_editorial_sfx_plan(
    *,
    clip_duration_s: float,
    segment: Optional[Dict[str, Any]] = None,
    editing_plan: Optional[Dict[str, Any]] = None,
    existing_sfx_applied: bool = False,
    transcript_text: str = "",
    words: Optional[List[Dict[str, Any]]] = None,
    editorial_type: str = "",
    matched_patterns: Optional[List[str]] = None,
    sensitive: bool = False,
    task_id: str = "",
    clip_order: int = 0,
    used_assets: Optional[set] = None,
    recent_assets: Optional[Sequence[str]] = None,
    silence_plan: Optional[Dict[str, Any]] = None,
) -> EditorialSfxPlan:
    """Decide at most 1-2 voice-subordinate editorial SFX (visual + payoff/risk)."""
    segment = segment if isinstance(segment, dict) else {}
    plan = editing_plan if isinstance(editing_plan, dict) else {}
    dur = float(clip_duration_s or 0.0)

    if existing_sfx_applied:
        return EditorialSfxPlan(skip_reason="existing_sfx_present")
    if bool(segment.get("opening_context_weak")) or bool(segment.get("narrative_closure_weak")):
        return EditorialSfxPlan(skip_reason="flagged_clip")
    if dur < 6.0:
        return EditorialSfxPlan(skip_reason="clip_too_short")

    max_events = 2 if dur >= 25.0 else 1

    cands: List[Dict[str, Any]] = []
    vf_start = float(plan.get("visual_fallback_start_s") or 0.0)
    if bool(plan.get("visual_fallback_rendered")) and vf_start > 0.0:
        cands.append({"start_s": vf_start, "event_type": "visual_transition",
                      "trigger_reason": "visual_card_entry", "confidence": 0.85,
                      "signal_text": "", "signal_source": "visual_card", "is_visual": True})
    broll_start = float(segment.get("broll_local_start_s") or plan.get("broll_start_time") or 0.0)
    broll_on = bool(segment.get("broll_rendered") or plan.get("broll_rendered") or segment.get("broll_local_planned"))
    if broll_on and broll_start > 0.0:
        cands.append({"start_s": broll_start, "event_type": "visual_transition",
                      "trigger_reason": "broll_entry", "confidence": 0.85,
                      "signal_text": "", "signal_source": "broll", "is_visual": True})

    et = str(editorial_type or segment.get("editorial_type") or "")
    travel_ctx = ("viaje" in _normalize_text(et) or "travel" in _normalize_text(et)
                  or "travel" in _normalize_text(" ".join(matched_patterns or [])))
    for sig in detect_editorial_signal(words=words, editorial_type=et, matched_patterns=matched_patterns, travel_context=travel_ctx):
        if sig["confidence"] < SIGNAL_CONFIDENCE_THRESHOLD:
            logger.info("VPI_EDITORIAL_SFX_SIGNAL_REJECTED type=%s text=%s reason=low_confidence conf=%.2f",
                        sig["event_type"], sig["trigger_text"], sig["confidence"])
            continue
        place = max(0.3, float(sig["start_s"]) - 0.2)
        logger.info("VPI_EDITORIAL_SFX_SIGNAL_FOUND type=%s text=%s start=%.2f conf=%.2f",
                    sig["event_type"], sig["trigger_text"], place, sig["confidence"])
        cands.append({"start_s": place, "event_type": sig["event_type"],
                      "trigger_reason": sig["event_type"], "confidence": sig["confidence"],
                      "signal_text": sig["trigger_text"], "signal_source": sig["source"], "is_visual": False})

    flagged_clip = bool(segment.get("opening_context_weak")) or bool(segment.get("narrative_closure_weak"))
    pause_signal = detect_editorial_pause_signal(
        final_words=words or [],
        final_transcript=transcript_text,
        pause_candidates=None,
        existing_events=cands,
        editorial_type=et,
        matched_patterns=matched_patterns,
        flagged=flagged_clip,
        sensitive=sensitive,
    )
    pause_candidates_summary = list(pause_signal.get("candidates") or [])
    pause_selected = pause_signal.get("selected") if isinstance(pause_signal.get("selected"), dict) else None
    if pause_selected:
        cands.append({
            "start_s": float(pause_selected.get("event_start_s") or pause_selected.get("pause_start_s") or 0.0),
            "event_type": "silence_punctuation",
            "trigger_reason": "silence_punctuation",
            "confidence": float(pause_selected.get("confidence") or 0.0),
            "signal_text": str(pause_selected.get("reason") or ""),
            "signal_source": "final_post_cut_pause",
            "is_visual": False,
            "pause_metadata": pause_selected,
        })
    elif pause_candidates_summary:
        logger.info(
            "VPI_SILENCE_PUNCTUATION_REJECTED reason=%s",
            str(pause_signal.get("skip_reason") or "silence_preferred"),
        )

    if not cands:
        return EditorialSfxPlan(
            skip_reason="no_clear_editorial_moment",
            silence_punctuation_candidates=pause_candidates_summary,
            silence_punctuation_result=str(pause_signal.get("skip_reason") or ""),
        )

    cands.sort(key=lambda c: (EVENT_PRIORITY.get(c["event_type"], 9), -c["confidence"], c["start_s"]))
    events: List[Dict[str, Any]] = []
    used_families: set = set()
    used_asset_paths: set = set(used_assets or set())
    if task_id:
        with _TASK_USED_SFX_LOCK:
            used_asset_paths.update(_TASK_USED_SFX_ASSETS.get(str(task_id), set()))
    recent_asset_paths: List[str] = list(recent_assets or _recent_editorial_sfx_assets(limit=5))
    nonvisual_count = 0
    collision_reason = ""
    for c in cands:
        if len(events) >= max_events:
            if not c["is_visual"]:
                collision_reason = "budget_full_visual_priority"
                logger.info("VPI_EDITORIAL_SFX_COLLISION_AVOIDED type=%s reason=budget_full", c["event_type"])
            break
        start_s = float(c["start_s"])
        if start_s < 0.3 or start_s > (dur - END_GUARD_S):
            continue
        if (not c["is_visual"]) and c["event_type"] == "risk_revelation" and start_s < 3.2:
            continue
        if (not c["is_visual"]) and nonvisual_count >= 1:
            if c["event_type"] == "silence_punctuation":
                collision_reason = "nonvisual_budget_full"
                logger.info("VPI_SILENCE_PUNCTUATION_REJECTED reason=nonvisual_budget_full")
            continue
        if any(abs(start_s - e["start_s"]) < MIN_EVENT_SEPARATION_S for e in events):
            if not c["is_visual"]:
                collision_reason = "min_separation"
                logger.info("VPI_EDITORIAL_SFX_COLLISION_AVOIDED type=%s reason=min_separation_8s", c["event_type"])
                if c["event_type"] == "silence_punctuation":
                    logger.info("VPI_SILENCE_PUNCTUATION_REJECTED reason=min_separation")
            continue
        if (not c["is_visual"]) and any(e.get("is_visual") and abs(start_s - e["start_s"]) < VISUAL_COLLISION_WINDOW_S for e in events):
            collision_reason = "near_visual_sfx"
            logger.info("VPI_EDITORIAL_SFX_COLLISION_AVOIDED type=%s reason=near_visual_sfx", c["event_type"])
            if c["event_type"] == "silence_punctuation":
                logger.info("VPI_SILENCE_PUNCTUATION_REJECTED reason=near_visual_sfx")
            continue
        if c["event_type"] in {"risk_revelation", "silence_punctuation"} and sensitive:
            selected_asset = select_editorial_sfx_asset(
                event_type=c["event_type"],
                task_id=task_id,
                clip_order=clip_order,
                trigger_text=str(c.get("signal_text") or c.get("trigger_reason") or ""),
                used_assets=used_asset_paths,
                used_families=used_families,
                recent_assets=recent_asset_paths,
                sensitive=True,
            )
        else:
            selected_asset = select_editorial_sfx_asset(
                event_type=c["event_type"],
                task_id=task_id,
                clip_order=clip_order,
                trigger_text=str(c.get("signal_text") or c.get("trigger_reason") or ""),
                used_assets=used_asset_paths,
                used_families=used_families,
                recent_assets=recent_asset_paths,
                sensitive=False,
            )
        family = str(selected_asset.get("family") or "")
        asset = str(selected_asset.get("asset") or "")
        if not family or not asset or family in used_families:
            continue
        if family in ("dark_riser", "high_riser") and "deep_boom" in used_families:
            continue
        if c["event_type"] in ("risk_revelation", "payoff_emphasis"):
            logger.info("VPI_EDITORIAL_SFX_%s_SELECTED text=%s family=%s start=%.2f conf=%.2f",
                        "RISK" if c["event_type"] == "risk_revelation" else "PAYOFF",
                        c.get("signal_text") or "", family, start_s, c["confidence"])
        events.append({
            "event_type": c["event_type"], "family": family, "asset_path": asset,
            "start_s": round(start_s, 2), "duration_s": EVENT_DURATION_S.get(c["event_type"], 0.6),
            "headroom_db": EVENT_HEADROOM_DB.get(c["event_type"], 10.0),
            "trigger_reason": c["trigger_reason"], "signal_text": c.get("signal_text") or "",
            "signal_source": c.get("signal_source") or "", "confidence": c["confidence"],
            "priority": EVENT_PRIORITY.get(c["event_type"], 9), "is_visual": bool(c["is_visual"]),
            "asset_candidates": list(selected_asset.get("candidates") or []),
            "asset_selected": asset,
            "asset_family": family,
            "asset_selection_index": int(selected_asset.get("selection_index") or 0),
            "asset_selection_seed": str(selected_asset.get("selection_seed") or ""),
            "asset_recently_avoided": list(selected_asset.get("recently_avoided") or []),
            "asset_single_family_fallback": bool(selected_asset.get("single_family_fallback")),
            "pause_class": str((c.get("pause_metadata") or {}).get("classification") or ""),
            "pause_start_s": float((c.get("pause_metadata") or {}).get("pause_start_s") or 0.0),
            "pause_end_s": float((c.get("pause_metadata") or {}).get("pause_end_s") or 0.0),
            "pause_duration_s": float((c.get("pause_metadata") or {}).get("pause_duration_s") or 0.0),
            "pause_before_text": str((c.get("pause_metadata") or {}).get("before_text") or ""),
            "pause_after_text": str((c.get("pause_metadata") or {}).get("after_text") or ""),
            "pause_confidence": float((c.get("pause_metadata") or {}).get("confidence") or 0.0),
            "silence_preferred": False,
            "silence_punctuation_result": (
                "sfx_selected"
                if c["event_type"] == "silence_punctuation"
                else str(pause_signal.get("skip_reason") or "")
            ),
            "silence_punctuation_class": str((c.get("pause_metadata") or {}).get("classification") or ""),
            "silence_punctuation_candidates": pause_candidates_summary[:8],
        })
        if c["event_type"] == "silence_punctuation":
            logger.info("VPI_SILENCE_PUNCTUATION_SFX_SELECTED asset=%s family=%s start=%.2f", asset, family, start_s)
        used_families.add(family)
        used_asset_paths.add(asset)
        if task_id and asset:
            with _TASK_USED_SFX_LOCK:
                _TASK_USED_SFX_ASSETS.setdefault(str(task_id), set()).add(asset)
        if not c["is_visual"]:
            nonvisual_count += 1

    if not events:
        return EditorialSfxPlan(
            skip_reason=collision_reason or "no_compatible_asset",
            collision_reason=collision_reason,
            silence_punctuation_candidates=pause_candidates_summary,
            silence_punctuation_result=str(pause_signal.get("skip_reason") or collision_reason or ""),
        )

    events.sort(key=lambda e: e["start_s"])
    logger.info("VPI_EDITORIAL_SFX_BUDGET_APPLIED events=%d max=%d", len(events), max_events)
    first = events[0]
    _sig_ev = next((e for e in events if e["event_type"] in ("risk_revelation", "payoff_emphasis")), None)
    return EditorialSfxPlan(
        planned=True,
        event_type=first["event_type"],
        asset_path=first["asset_path"],
        family=first["family"],
        start_s=first["start_s"],
        duration_s=first["duration_s"],
        trigger_reason=first["trigger_reason"],
        confidence=float(first.get("confidence") or 0.8),
        signal_type=(_sig_ev["event_type"] if _sig_ev else ""),
        signal_text=(_sig_ev.get("signal_text") if _sig_ev else ""),
        signal_confidence=(float(_sig_ev.get("confidence") or 0.0) if _sig_ev else 0.0),
        signal_source=(_sig_ev.get("signal_source") if _sig_ev else ""),
        priority=int(first.get("priority") or EVENT_PRIORITY.get(first["event_type"], 1)),
        collision_reason=collision_reason,
        events=events,
        silence_punctuation_candidates=pause_candidates_summary,
        silence_punctuation_result=(
            "sfx_selected"
            if any(e.get("event_type") == "silence_punctuation" for e in events)
            else str(pause_signal.get("skip_reason") or "silence_preferred")
        ),
    )


def _measure_max_volume(path: str, ffmpeg_bin: str) -> Optional[float]:
    try:
        r = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-i", path, "-map", "0:a?", "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, timeout=30,
        )
    except Exception:
        return None
    m = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", r.stderr or "")
    return float(m.group(1)) if m else None


def render_editorial_sfx(
    *,
    input_video: str | Path,
    output_video: str | Path,
    plan: EditorialSfxPlan | Dict[str, Any],
) -> Dict[str, Any]:
    """Mix the planned editorial SFX into the clip audio, voice-subordinate, no drift."""
    input_path = Path(input_video)
    output_path = Path(output_video)
    plan_obj = plan if isinstance(plan, EditorialSfxPlan) else None
    events = (plan_obj.events if plan_obj else (plan or {}).get("editorial_sfx_events")) or []
    if not events:
        return {"rendered": False, "output_path": str(input_path), "reason": "not_planned"}
    if not input_path.exists():
        return {"rendered": False, "output_path": str(input_path), "reason": "input_missing"}

    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    clip_peak = _measure_max_volume(str(input_path), ffmpeg_bin)

    inputs: List[str] = ["-i", str(input_path)]
    filt_parts: List[str] = []
    mix_labels: List[str] = ["[0:a]"]
    applied_events: List[Dict[str, Any]] = []
    idx = 1
    for ev in events:
        asset_abs = _abs_asset(str(ev.get("asset_path") or ""))
        if not asset_abs or _is_forbidden(asset_abs):
            continue
        logger.info("VPI_EDITORIAL_SFX_ASSET_VALIDATED asset=%s family=%s", ev.get("asset_path"), ev.get("family"))
        ev_dur = float(ev.get("duration_s") or 0.6)
        start_ms = int(round(float(ev.get("start_s") or 0.0) * 1000))
        headroom = float(ev.get("headroom_db") or 10.0)
        sfx_peak = _measure_max_volume(asset_abs, ffmpeg_bin)
        if clip_peak is not None and sfx_peak is not None:
            gain_db = (clip_peak - headroom) - sfx_peak
        else:
            gain_db = DEFAULT_FALLBACK_GAIN_DB
        gain_db = max(GAIN_FLOOR_DB, min(GAIN_CEIL_DB, gain_db))
        if str(ev.get("event_type") or "") == "silence_punctuation":
            gain_db = min(gain_db, SILENCE_PUNCTUATION_GAIN_CEIL_DB)
        ev["gain"] = round(gain_db, 2)
        ev["measured_gain"] = round(gain_db, 2)
        ev["clip_peak_db"] = clip_peak
        ev["sfx_peak_db"] = sfx_peak
        logger.info(
            "VPI_EDITORIAL_SFX_ASSET_GAIN_CALIBRATED family=%s asset=%s gain=%.2f clip_peak=%s sfx_peak=%s",
            ev.get("family"), ev.get("asset_path"), gain_db, clip_peak, sfx_peak,
        )
        fade_out_st = max(0.0, ev_dur - 0.12)
        inputs += ["-i", asset_abs]
        lbl = f"[s{idx}]"
        filt_parts.append(
            f"[{idx}:a]atrim=0:{ev_dur:.3f},afade=t=in:st=0:d=0.06,"
            f"afade=t=out:st={fade_out_st:.3f}:d=0.12,volume={gain_db:.2f}dB,"
            f"adelay={start_ms}|{start_ms}{lbl}"
        )
        mix_labels.append(lbl)
        applied_events.append(ev)
        idx += 1

    if not applied_events:
        return {"rendered": False, "output_path": str(input_path), "reason": "no_valid_asset"}

    n = len(mix_labels)
    filt = ";".join(filt_parts)
    filt += f";{''.join(mix_labels)}amix=inputs={n}:duration=first:normalize=0[mx];[mx]alimiter=limit=0.97[aout]"

    cmd = [
        ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error",
        *inputs,
        "-filter_complex", filt,
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        str(output_path),
    ]
    logger.info(
        "VPI_EDITORIAL_SFX_MIX_STARTED events=%d asset=%s start=%.2f",
        len(applied_events), applied_events[0].get("asset_path"), float(applied_events[0].get("start_s") or 0.0),
    )
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        if r.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            return {
                "rendered": True,
                "output_path": str(output_path),
                "method": "ffmpeg_amix_editorial_sfx",
                "events": applied_events,
                "count": len(applied_events),
                "filtergraph": filt,
                "clip_peak_db": clip_peak,
            }
        return {
            "rendered": False, "output_path": str(input_path),
            "reason": (r.stderr or "ffmpeg_failed")[-300:], "filtergraph": filt,
        }
    except Exception as exc:
        return {"rendered": False, "output_path": str(input_path), "reason": str(exc), "filtergraph": filt}
