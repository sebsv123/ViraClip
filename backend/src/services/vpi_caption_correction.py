"""OUTPUT-CAPTIONS-47 — Conservative, display-only ASR caption correction.

Fixes a *small, evidence-backed* set of visible ASR transcription errors in the
burned captions WITHOUT touching the editorial transcript (`text`). Corrections are
written to a separate display layer (`caption_display_text`); timestamps are never
changed. Editorial systems (selection, B-roll, phrase targeting, cuts, closure)
keep reading `text`, so a visual fix can never alter scoring or sync.

Design:
  * deterministic, high-precision rules only (no general autocorrect, no spellcheck,
    no remote LLM, no second-pass Whisper inside the normal render);
  * each rule carries required/excluded context and an evidence list;
  * ambiguous cases are flagged for review (`caption_review_required`) and left as-is.

The confirmed rules here were validated offline (FASE 2/3) by a local second-pass
faster-whisper transcription of the exact audio windows — that confirmation produced
the rules; it is NOT executed at render time.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class CaptionCorrection:
    original: str
    replacement: str
    reason: str
    confidence: float
    evidence: List[str] = field(default_factory=list)
    start_s: float = 0.0
    end_s: float = 0.0
    rule_id: str = ""


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


_PUNCT = ".,;:¿?¡!\"'()…«»-"


def _norm(s: str) -> str:
    return _strip_accents(str(s or "")).lower().strip().strip(_PUNCT)


# Spanish infinitive endings — the avoid-construction is "evitan <infinitivo>".
_COMMON_INFINITIVES = {
    "hablar", "decir", "comentar", "mencionar", "tratar", "pensar", "gastar",
    "pagar", "contratar", "asegurar", "asumir", "afrontar", "reconocer",
    "preguntar", "buscar", "tocar", "abordar", "nombrar",
}


def _is_infinitive(token_norm: str) -> bool:
    if not token_norm or len(token_norm) < 4:
        return False
    if token_norm in _COMMON_INFINITIVES:
        return True
    return token_norm.endswith(("ar", "er", "ir"))


# ── Approved, evidence-backed correction rules (FASE 7 — small glossary) ──────
# Each rule: wrong-form, corrected display form, context guards, evidence source.
_CORRECTION_RULES: Tuple[Dict[str, Any], ...] = (
    {
        # "depensar" is not a Spanish word: the ASR fused a spurious "de" into the
        # infinitive "pensar". The Spanish periphrasis is "ir A + infinitivo"
        # ("va a pensar"), so the preceding "a" is the genuine connector and must be
        # kept untouched. We only drop the fused "de": display "depensar" -> "pensar".
        # This conserves token count and each token's interval (a stays "a").
        "rule_id": "depensar_pensar",
        "wrong": "depensar",
        "correct": "pensar",
        "absorb_prev_a": False,
        "nonword": True,
        "requires_next_infinitive": False,
        "excludes": (),
        "confidence": 0.97,
        "evidence": [
            "second_pass_agreement:de pensar",
            "contextual_grammar",
            "phonetic_proximity:a depensar~de pensar",
            "domain_context",
            "non_word_token",
        ],
    },
    {
        # "habitan" (they inhabit) is a real word, so it is only corrected to
        # "evitan" (they avoid) in the avoid-construction: habitan + <infinitive>.
        # Near dwelling words it is left untouched (likely the literal meaning).
        "rule_id": "habitan_evitan",
        "wrong": "habitan",
        "correct": "evitan",
        "nonword": False,
        "requires_next_infinitive": True,
        "excludes": (
            "casa", "casas", "ciudad", "ciudades", "lugar", "lugares", "zona",
            "zonas", "pais", "paises", "mundo", "edificio", "barrio", "region",
            "pueblo", "pueblos", "planeta", "isla", "territorio", "vivienda",
        ),
        "confidence": 0.80,
        "evidence": [
            "second_pass_agreement:evitan",
            "contextual_grammar",
            "phonetic_proximity",
            "domain_context",
            "low_original_confidence",
        ],
    },
)

# Safe domain terms (FASE 7) — used only to *whitelist* (never flag as suspicious),
# NOT to auto-correct anything.
_DOMAIN_SAFE_TERMS = frozenset({
    "poliza", "cobertura", "carencia", "copago", "decesos", "indemnizacion",
    "hospitalizacion", "capital", "extranjeria", "residencia", "visado",
    "asegurado", "asistencia", "prima", "franquicia", "siniestro", "beneficiario",
    "deducible", "reembolso",
})

_SUSPICIOUS_LOW_CONF = 0.40
# preposition + verb-ish merges that are very likely ASR token merges
_PREP_MERGE_RE = re.compile(r"^(de|a|en|que|se|le)(pensar|hablar|decir|gastar|pagar|cubrir|sumir)$")


def _confidence_of(w: Dict[str, Any]) -> float:
    for k in ("confidence", "conf", "probability", "prob"):
        v = w.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return 1.0


def _preserve_shape(original: str, replacement: str) -> str:
    """Carry leading capitalization and trailing punctuation from the ASR token."""
    lead = ""
    body = original
    # trailing punctuation
    trail = ""
    while body and body[-1] in _PUNCT:
        trail = body[-1] + trail
        body = body[:-1]
    out = replacement
    if body[:1].isupper():
        out = out[:1].upper() + out[1:]
    return lead + out + trail


def apply_caption_corrections(
    words: List[Dict[str, Any]],
    *,
    transcript_context: str = "",
) -> Tuple[List[Dict[str, Any]], List[CaptionCorrection]]:
    """Annotate `words` in place with `caption_display_text` for confirmed ASR errors.

    Returns (words, corrections). `text` is never modified. Timestamps are never
    modified. Ambiguous suspicious tokens are flagged (`caption_review_required`)
    but NOT corrected.
    """
    corrections: List[CaptionCorrection] = []
    if not isinstance(words, list):
        return words, corrections

    n = len(words)
    for i, w in enumerate(words):
        if not isinstance(w, dict):
            continue
        raw = str(w.get("text") or w.get("word") or "")
        tok = _norm(raw)
        if not tok:
            continue
        nxt = _norm(str((words[i + 1].get("text") or words[i + 1].get("word") or "")) if i + 1 < n and isinstance(words[i + 1], dict) else "")
        prv = _norm(str((words[i - 1].get("text") or words[i - 1].get("word") or "")) if i > 0 and isinstance(words[i - 1], dict) else "")

        matched_rule = next((r for r in _CORRECTION_RULES if tok == r["wrong"]), None)
        if matched_rule is not None:
            excludes = matched_rule.get("excludes") or ()
            # Excluded context (e.g. "habitan la ciudad") -> likely the valid word.
            if excludes and (nxt in excludes or prv in excludes):
                _flag_suspicious(w, "valid_word_in_excluded_context", review=True)
                continue
            # Required next infinitive (the avoid-construction) — otherwise ambiguous.
            if matched_rule.get("requires_next_infinitive") and not _is_infinitive(nxt):
                _flag_suspicious(w, "ambiguous_no_infinitive_follow", review=True)
                continue
            # Pair correction: "a depensar" -> "de pensar" (a->de, depensar->pensar),
            # preserving token count and each token's interval.
            if matched_rule.get("absorb_prev_a") and prv == "a" and i > 0 and isinstance(words[i - 1], dict):
                prev_w = words[i - 1]
                prev_raw = str(prev_w.get("text") or prev_w.get("word") or "")
                prev_w["caption_display_text"] = _preserve_shape(prev_raw, "de")
                prev_w["caption_correction_applied"] = True
                prev_w["caption_correction_rule_id"] = matched_rule["rule_id"]
                w["caption_display_text"] = _preserve_shape(raw, "pensar")
                w["caption_correction_applied"] = True
                w["caption_correction_rule_id"] = matched_rule["rule_id"]
                corrections.append(
                    CaptionCorrection(
                        original=f"{prev_raw} {raw}",
                        replacement="de pensar",
                        reason=matched_rule["rule_id"],
                        confidence=float(matched_rule.get("confidence") or 0.0),
                        evidence=list(matched_rule.get("evidence") or []),
                        start_s=float(prev_w.get("start") or 0.0),
                        end_s=float(w.get("end") or 0.0),
                        rule_id=matched_rule["rule_id"],
                    )
                )
                continue
            display = _preserve_shape(raw, matched_rule["correct"])
            if display == raw:
                continue
            w["caption_display_text"] = display
            w["caption_correction_applied"] = True
            w["caption_correction_rule_id"] = matched_rule["rule_id"]
            corrections.append(
                CaptionCorrection(
                    original=raw,
                    replacement=display,
                    reason=matched_rule["rule_id"],
                    confidence=float(matched_rule.get("confidence") or 0.0),
                    evidence=list(matched_rule.get("evidence") or []),
                    start_s=float(w.get("start") or 0.0),
                    end_s=float(w.get("end") or 0.0),
                    rule_id=matched_rule["rule_id"],
                )
            )
            continue

        # ── FASE 8: suspicious-token detection (NO auto-correction) ───────────
        if tok in _DOMAIN_SAFE_TERMS:
            continue
        if _PREP_MERGE_RE.match(tok):
            _flag_suspicious(w, "prep_verb_merge", review=True)
            continue
        if _confidence_of(w) < _SUSPICIOUS_LOW_CONF:
            _flag_suspicious(w, "low_confidence", review=False)

    return words, corrections


def _flag_suspicious(w: Dict[str, Any], reason: str, *, review: bool) -> None:
    w["caption_suspicious_token"] = True
    prev = str(w.get("caption_review_reason") or "")
    w["caption_review_reason"] = (prev + "," + reason).strip(",") if prev else reason
    if review:
        w["caption_review_required"] = True
        w["caption_correction_candidate"] = True


def summarize_corrections(
    words: List[Dict[str, Any]],
    corrections: List[CaptionCorrection],
) -> Dict[str, Any]:
    """Build the persistence payload (FASE 10)."""
    suspicious = [
        {
            "text": str(w.get("text") or w.get("word") or ""),
            "start_s": float(w.get("start") or 0.0),
            "reason": str(w.get("caption_review_reason") or ""),
        }
        for w in (words if isinstance(words, list) else [])
        if isinstance(w, dict) and w.get("caption_suspicious_token")
    ]
    review_required = any(
        isinstance(w, dict) and w.get("caption_review_required")
        for w in (words if isinstance(words, list) else [])
    )
    return {
        "caption_corrections": [
            {
                "original": c.original,
                "replacement": c.replacement,
                "start_s": c.start_s,
                "end_s": c.end_s,
                "evidence": c.evidence,
                "confidence": c.confidence,
                "rule_id": c.rule_id,
            }
            for c in corrections
        ],
        "caption_correction_count": len(corrections),
        "caption_review_required": bool(review_required),
        "caption_suspicious_tokens": suspicious,
    }
