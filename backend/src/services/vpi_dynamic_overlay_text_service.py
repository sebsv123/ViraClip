from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


_REPO_ROOT = Path(__file__).resolve().parents[3]


def _norm(text: str) -> str:
    return str(text or "").strip().lower()


def _has_any(text: str, needles: List[str]) -> bool:
    return any(needle in text for needle in needles)


def _trim(text: str, max_chars: int) -> str:
    out = str(text or "").strip()
    if len(out) <= max_chars:
        return out
    return out[: max(0, max_chars - 1)].rstrip() + "…"


def _weak_segment(text: str) -> bool:
    t = _norm(text)
    if len(t) < 24:
        return True
    weak_tokens = ("ok", "vale", "mmm", "eh", "a ver", "bueno", "pues")
    return _has_any(t, list(weak_tokens)) and len(t.split()) < 8


def _claim_risk(text: str) -> bool:
    t = _norm(text)
    risk_tokens = ("100%", "garantizado", "aprobado", "gratis", "descuento")
    return _has_any(t, list(risk_tokens))


def build_dynamic_overlay_text_plan(
    segment_text: str,
    topics: List[str] | None = None,
    overlay_concept: str | None = None,
    editorial_signal: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    text = _norm(segment_text)
    topic_blob = " ".join(str(t or "").lower() for t in (topics or []))
    concept = _norm(overlay_concept or "")
    signal = editorial_signal or {}

    claim_verified = bool(signal.get("claim_verified", False))
    caption_visible = bool(signal.get("caption_already_strong", False))
    delicate = _has_any(topic_blob + " " + text, ["decesos", "emotional_closure", "emocional", "duelo", "fallecimiento"])

    base: Dict[str, Any] = {
        "dynamic_text_needed": False,
        "overlay_text": "",
        "overlay_subtext": "",
        "text_role": "",
        "font_family": "Manrope",
        "font_weight": "SemiBold",
        "max_chars": 32,
        "safe_to_render": False,
        "needs_claim_review": False,
        "reason": "no_dynamic_text_gain",
    }

    if not concept or _weak_segment(text):
        base["reason"] = "weak_or_missing_context"
        return base

    if delicate and concept not in {"shield", "heart", "location_popup"}:
        base["reason"] = "sensitive_segment_skip"
        return base

    plan = dict(base)
    plan["dynamic_text_needed"] = True
    plan["safe_to_render"] = True

    if concept == "notification_card":
        if _has_any(text, ["whatsapp", "escríbenos", "escribenos", "llámanos", "llamanos", "hablamos", "consulta", "duda"]):
            plan.update({"overlay_text": "Nuevo mensaje", "overlay_subtext": "Te lo explicamos claro", "text_role": "cta", "font_weight": "Bold", "reason": "notification_cta"})
        elif _has_any(text, ["ojo", "importante", "no todos"]):
            plan.update({"overlay_text": "Aviso importante", "overlay_subtext": "Revisa esto", "text_role": "warning", "reason": "notification_warning"})
        elif _has_any(text, ["vence", "plazo", "renovación", "renovacion"]):
            plan.update({"overlay_text": "Recordatorio", "overlay_subtext": "Revisa tu seguro", "text_role": "warning", "reason": "notification_reminder"})
        else:
            plan["dynamic_text_needed"] = False
            plan["safe_to_render"] = False
            plan["reason"] = "notification_no_clear_phrase"

    elif concept == "toggle_card":
        if _has_any(text, ["sin copago", "sin copagos", "copago", "copagos"]):
            plan.update({"overlay_text": "Copagos", "overlay_subtext": "OFF", "text_role": "coverage", "font_weight": "Bold", "reason": "toggle_copagos"})
        elif _has_any(text, ["sin deducible", "sin deducibles", "deducible", "deducibles"]):
            plan.update({"overlay_text": "Deducibles", "overlay_subtext": "OFF", "text_role": "coverage", "font_weight": "Bold", "reason": "toggle_deducibles"})
        elif _has_any(text, ["protección", "proteccion", "tranquilidad"]):
            plan.update({"overlay_text": "Protección", "overlay_subtext": "ON", "text_role": "hook", "font_weight": "Bold", "reason": "toggle_proteccion"})
        else:
            plan["dynamic_text_needed"] = False
            plan["safe_to_render"] = False
            plan["reason"] = "toggle_no_clear_phrase"

    elif concept == "stat_card":
        if _has_any(text, ["reseña", "reseñas", "google", "cinco estrellas", "5 estrellas", "clientes", "recomendado", "confianza"]):
            plan.update({"overlay_text": "Confianza", "overlay_subtext": "Reseñas verificadas", "text_role": "claim", "needs_claim_review": True, "reason": "stat_reviews"})
        elif _has_any(text, ["porcentaje", "100%", "casos", "aprobado"]):
            plan.update({"overlay_text": "Dato importante", "overlay_subtext": "Revisar claim", "text_role": "claim", "needs_claim_review": True, "reason": "stat_claim"})
            if not claim_verified:
                plan["safe_to_render"] = False
        else:
            plan["dynamic_text_needed"] = False
            plan["safe_to_render"] = False
            plan["reason"] = "stat_no_clear_phrase"

    elif concept in {"price_badge", "promo_badge", "euro"}:
        if _has_any(text, ["descuento", "gratis", "oferta", "promoción", "promocion", "prima", "ahorro", "precio", "meses gratis"]):
            plan.update({"overlay_text": "Oferta", "overlay_subtext": "Revisar condiciones", "text_role": "claim", "needs_claim_review": True, "reason": "promo_claim"})
            if not claim_verified and _claim_risk(text):
                plan["safe_to_render"] = False
        else:
            plan["dynamic_text_needed"] = False
            plan["safe_to_render"] = False
            plan["reason"] = "promo_no_clear_phrase"

    elif concept == "timeline_card":
        plan["max_chars"] = 40
        if _has_any(text, ["trámite", "tramite", "extranjería", "extranjeria", "documentación", "documentacion"]):
            plan.update({"overlay_text": "3 pasos", "overlay_subtext": "Seguro · Póliza · Trámite", "text_role": "process", "reason": "timeline_tramite"})
        elif _has_any(text, ["salud", "comparamos", "contratas"]):
            plan.update({"overlay_text": "Proceso claro", "overlay_subtext": "Caso · Opciones · Contratación", "text_role": "process", "reason": "timeline_salud"})
        else:
            plan["dynamic_text_needed"] = False
            plan["safe_to_render"] = False
            plan["reason"] = "timeline_no_clear_phrase"

    elif concept == "folder_gallery":
        if _has_any(text, ["documentos", "póliza", "poliza", "trámite", "tramite"]):
            plan.update({"overlay_text": "Documentación", "overlay_subtext": "Todo en orden", "text_role": "coverage", "reason": "folder_docs"})
        else:
            plan["dynamic_text_needed"] = False
            plan["safe_to_render"] = False
            plan["reason"] = "folder_no_clear_phrase"

    elif concept == "location_popup":
        if _has_any(text, ["boadilla"]):
            plan.update({"overlay_text": "Boadilla", "overlay_subtext": "Atención local", "text_role": "local", "font_weight": "Medium", "reason": "location_boadilla"})
        elif _has_any(text, ["madrid"]):
            plan.update({"overlay_text": "Madrid", "overlay_subtext": "Online y presencial", "text_role": "local", "font_weight": "Medium", "reason": "location_madrid"})
        else:
            plan["dynamic_text_needed"] = False
            plan["safe_to_render"] = False
            plan["reason"] = "location_no_clear_phrase"

    elif concept == "keyword_spin":
        category = ""
        if _has_any(text + " " + topic_blob, ["salud"]):
            category = "SALUD"
        elif _has_any(text + " " + topic_blob, ["vida"]):
            category = "VIDA"
        elif _has_any(text + " " + topic_blob, ["decesos"]):
            category = "DECESOS"
        elif _has_any(text + " " + topic_blob, ["autónomos", "autonomos"]):
            category = "AUTÓNOMOS"
        elif _has_any(text + " " + topic_blob, ["extranjería", "extranjeria"]):
            category = "EXTRANJERÍA"
        if category:
            plan.update({"overlay_text": category, "overlay_subtext": "", "text_role": "hook", "font_weight": "Bold", "reason": "keyword_category"})
        else:
            plan["dynamic_text_needed"] = False
            plan["safe_to_render"] = False
            plan["reason"] = "keyword_no_category"
    else:
        plan["dynamic_text_needed"] = False
        plan["safe_to_render"] = False
        plan["reason"] = "concept_not_supported_for_dynamic_text"

    plan["overlay_text"] = _trim(plan.get("overlay_text", ""), int(plan.get("max_chars") or 32))
    plan["overlay_subtext"] = _trim(plan.get("overlay_subtext", ""), 48)

    if caption_visible and plan["overlay_text"] and plan["overlay_text"].lower() in text:
        plan["dynamic_text_needed"] = False
        plan["safe_to_render"] = False
        plan["reason"] = "duplicate_caption_phrase"

    if _claim_risk(text):
        plan["needs_claim_review"] = True
        if not claim_verified:
            plan["safe_to_render"] = False

    if not plan.get("overlay_text"):
        plan["dynamic_text_needed"] = False
        plan["safe_to_render"] = False

    return plan


def _safe_output_dir(output_dir: str | Path | None) -> Path:
    base = (_REPO_ROOT / "exports" / "dynamic_overlay_text").resolve()
    if output_dir is None:
        base.mkdir(parents=True, exist_ok=True)
        return base
    candidate = Path(output_dir)
    candidate = candidate if candidate.is_absolute() else (_REPO_ROOT / candidate)
    resolved = candidate.resolve()
    try:
        resolved.relative_to(_REPO_ROOT)
    except ValueError:
        base.mkdir(parents=True, exist_ok=True)
        return base
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _resolve_font_paths(asset_index: Optional[Dict[str, Any]]) -> Dict[str, str]:
    idx = asset_index or {}
    fonts = list((idx.get("verified") or {}).get("fonts") or [])
    ranked: List[Tuple[int, str]] = []
    for entry in fonts:
        path = str(entry.get("path") or "")
        p = Path(path)
        if not (path and p.exists() and p.is_file()):
            continue
        name = p.name.lower()
        score = 0
        if "manrope" in name:
            score += 10
        if "inter" in name:
            score += 7
        if "semibold" in name:
            score += 4
        if "bold" in name:
            score += 3
        if p.suffix.lower() in {".ttf", ".otf"}:
            score += 2
        ranked.append((score, str(p)))
    ranked.sort(key=lambda item: item[0], reverse=True)
    best = ranked[0][1] if ranked else ""
    return {
        "best": best,
        "fallback_family": "Manrope" if best and "manrope" in Path(best).name.lower() else ("Inter" if best else "PIL_DEFAULT"),
    }


def render_dynamic_overlay_text_asset(
    plan: dict,
    output_dir: str | Path | None = None,
    asset_index: dict | None = None,
    width: int = 1080,
    height: int = 320,
) -> dict:
    out = {
        "dynamic_overlay_text_rendered": False,
        "dynamic_overlay_text_asset_path": "",
        "dynamic_overlay_text_asset_exists": False,
        "font_path": "",
        "font_family": str((plan or {}).get("font_family") or "Manrope"),
        "render_width": int(width),
        "render_height": int(height),
        "error": None,
        "reason": "not_requested",
    }
    p = dict(plan or {})
    if not bool(p.get("dynamic_text_needed")):
        out["reason"] = "dynamic_text_not_needed"
        return out
    if not bool(p.get("safe_to_render")):
        out["reason"] = "unsafe_to_render"
        return out
    if bool(p.get("needs_claim_review")) and not bool(p.get("claim_verified")):
        out["reason"] = "claim_review_required"
        return out

    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
    except Exception:
        out["error"] = "pillow_missing"
        out["reason"] = "pillow_missing"
        return out

    safe_dir = _safe_output_dir(output_dir)
    role = re.sub(r"[^a-z0-9_]+", "_", str(p.get("text_role") or "generic").lower()).strip("_") or "generic"
    digest = hashlib.sha1(
        f"{p.get('overlay_text','')}|{p.get('overlay_subtext','')}|{role}|{width}|{height}".encode("utf-8")
    ).hexdigest()[:12]
    filename = f"dynamic_overlay_text_{role}_{digest}.png"
    out_path = (safe_dir / filename).resolve()

    font_info = _resolve_font_paths(asset_index)
    font_path = font_info.get("best") or ""
    out["font_path"] = font_path
    if font_info.get("fallback_family") == "PIL_DEFAULT":
        out["font_family"] = "PIL_DEFAULT"

    text_main = str(p.get("overlay_text") or "").strip()
    text_sub = str(p.get("overlay_subtext") or "").strip()
    if not text_main:
        out["reason"] = "empty_overlay_text"
        return out

    try:
        image = Image.new("RGBA", (int(width), int(height)), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        main_size = 84
        sub_size = 44
        stroke_w = 3

        def _load_font(size: int):
            if font_path:
                try:
                    return ImageFont.truetype(font_path, size=size)
                except Exception:
                    return ImageFont.load_default()
            return ImageFont.load_default()

        font_main = _load_font(main_size)
        font_sub = _load_font(sub_size)

        max_w = int(width * 0.92)
        while main_size > 30:
            bbox = draw.textbbox((0, 0), text_main, font=font_main, stroke_width=stroke_w)
            w = int(bbox[2] - bbox[0])
            if w <= max_w:
                break
            main_size -= 4
            font_main = _load_font(main_size)

        while text_sub and sub_size > 18:
            bbox_sub = draw.textbbox((0, 0), text_sub, font=font_sub, stroke_width=max(1, stroke_w - 1))
            if int(bbox_sub[2] - bbox_sub[0]) <= max_w:
                break
            sub_size -= 2
            font_sub = _load_font(sub_size)

        bbox_main = draw.textbbox((0, 0), text_main, font=font_main, stroke_width=stroke_w)
        main_w = int(bbox_main[2] - bbox_main[0])
        main_h = int(bbox_main[3] - bbox_main[1])

        sub_h = 0
        sub_w = 0
        if text_sub:
            bbox_sub = draw.textbbox((0, 0), text_sub, font=font_sub, stroke_width=max(1, stroke_w - 1))
            sub_w = int(bbox_sub[2] - bbox_sub[0])
            sub_h = int(bbox_sub[3] - bbox_sub[1])

        gap = 14 if text_sub else 0
        total_h = main_h + gap + sub_h
        y = max(10, (height - total_h) // 2)
        x_main = max(10, (width - main_w) // 2)
        x_sub = max(10, (width - sub_w) // 2) if text_sub else 0

        # Main text (white + dark stroke)
        draw.text(
            (x_main, y),
            text_main,
            font=font_main,
            fill=(245, 245, 245, 255),
            stroke_width=stroke_w,
            stroke_fill=(12, 12, 12, 220),
        )
        if text_sub:
            draw.text(
                (x_sub, y + main_h + gap),
                text_sub,
                font=font_sub,
                fill=(220, 220, 220, 245),
                stroke_width=max(1, stroke_w - 1),
                stroke_fill=(12, 12, 12, 180),
            )

        image.save(str(out_path), format="PNG")
        out["dynamic_overlay_text_rendered"] = True
        out["dynamic_overlay_text_asset_path"] = str(out_path)
        out["dynamic_overlay_text_asset_exists"] = out_path.exists() and out_path.is_file()
        out["reason"] = "rendered"
        return out
    except Exception as exc:
        out["error"] = str(exc)
        out["reason"] = "render_failed"
        return out
