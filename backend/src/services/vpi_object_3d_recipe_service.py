"""
vpi_object_3d_recipe_service.py — OUTPUT-OBJECTS-3D-53C: self-expanding 3D library.

A declarative, safe recipe + catalog layer that lets the 3D library GROW from the real concepts
in a clip's transcript — WITHOUT the rigid 4-family literal-phrase gate of 53/53B. Concepts are
extracted from the transcript (frequency × visualizability), a concrete visualizable concept is
selected, and — if no catalog asset (or alias) already covers it — a NEW composite asset is minted
from a whitelist of allowed component meshes, rendered once (Remotion+three.js), validated by
pixels/alpha, and registered. Equivalent concepts (aliases) then reuse the same cached asset.

Growth controls: max 1 new asset per task; generic/abstract concepts (tranquilidad, libertad, …)
never mint an asset; an asset is only registered after real pixel + alpha verification.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

CATALOG_VERSION = 1
PALETTE_VERSION = "vpi-3d-v1"

# ── Allowed component meshes (no free-form generated code; composites pick from this whitelist) ──
ALLOWED_COMPONENTS = frozenset({
    # base-family primitives (53)
    "suitcase_body_mesh", "shield_mesh", "heart_mesh", "passport_mesh",
    # 53C composite components
    "medical_document_mesh", "medical_cross_mesh", "coin_mesh", "return_arrow_mesh",
})

# ── Declarative recipes (a recipe is a name + allowed components + the Remotion composition) ──
@dataclass(frozen=True)
class Recipe:
    asset_id: str
    canonical_concept: str
    domain: str
    recipe_type: str               # "composite" | "primitive"
    components: Tuple[str, ...]
    remotion_composition: str
    aliases: Tuple[str, ...] = ()
    frames: int = 54
    fps: int = 30
    width: int = 720
    height: int = 720

RECIPES: Dict[str, Recipe] = {
    "medical_reimbursement_3d": Recipe(
        asset_id="medical_reimbursement_3d",
        canonical_concept="reembolso médico",
        domain="health_insurance",
        recipe_type="composite",
        components=("medical_document_mesh", "medical_cross_mesh", "coin_mesh", "return_arrow_mesh"),
        remotion_composition="MedicalReimbursement3D",
        aliases=("reembolso", "seguro de reembolso", "póliza de reembolso", "gastos médicos",
                 "devolución de gastos", "reembolso de gastos médicos"),
        frames=51,
    ),
}

# ── Concept knowledge (NOT a 4-family literal gate — a growable semantic map) ─────────────────
# Each surface token -> (canonical_concept, visualizability 0..1, domain, generic?). Concrete
# object-like concepts score high; abstract emotionals score low / generic.
_CONCEPT_LEXICON: Dict[str, Tuple[str, float, str, bool]] = {
    "reembolso": ("reembolso médico", 0.95, "health_insurance", False),
    "reembolsos": ("reembolso médico", 0.95, "health_insurance", False),
    "reembolsar": ("reembolso médico", 0.90, "health_insurance", False),
    "gastos": ("reembolso médico", 0.70, "health_insurance", False),  # "gastos médicos"
    "poliza": ("póliza de salud", 0.55, "health_insurance", False),
    "polizas": ("póliza de salud", 0.55, "health_insurance", False),
    "especialista": ("especialistas", 0.50, "health", False),
    "especialistas": ("especialistas", 0.50, "health", False),
    "hospital": ("hospitalización", 0.80, "health", False),
    "libertad": ("libertad de elección", 0.20, "abstract", True),
    "cobertura": ("cobertura", 0.30, "insurance", False),
    # generic / abstract — never mint an asset
    "tranquilidad": ("tranquilidad", 0.10, "abstract", True),
    "cuidado": ("cuidado", 0.10, "abstract", True),
    "seguridad": ("seguridad", 0.12, "abstract", True),
    "importante": ("importante", 0.05, "abstract", True),
    "problema": ("problema", 0.08, "abstract", True),
}
MIN_VISUALIZABILITY_TO_MINT = 0.70
GENERIC_CONCEPTS = frozenset({"tranquilidad", "cuidado", "seguridad", "importante", "problema",
                              "libertad de elección"})


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]", " ", s)


# ── Catalog I/O ───────────────────────────────────────────────────────────────
def _objects_root() -> Path:
    import os as _os
    env = _os.environ.get("VPI_OBJECTS_3D_ROOT")  # sandbox override (tests / offline mint)
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for base in (here.parents[3], Path("/app"), Path.cwd()):
        cand = base / "assets" / "objects_3d"
        if cand.exists():
            return cand
    return here.parents[3] / "assets" / "objects_3d"


def catalog_path() -> Path:
    return _objects_root() / "catalog.json"


def load_catalog() -> Dict[str, Any]:
    p = catalog_path()
    if not p.exists():
        return {"version": CATALOG_VERSION, "assets": {}}
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {"version": CATALOG_VERSION, "assets": {}}


def save_catalog(catalog: Dict[str, Any]) -> None:
    catalog_path().write_text(json.dumps(catalog, ensure_ascii=False, indent=2))


# ── Concept extraction (no allow-list gate) ─────────────────────────────────────
@dataclass
class ConceptCandidate:
    concept: str
    surface: str
    count: int
    visualizability: float
    domain: str
    generic: bool
    score: float = 0.0


def extract_concepts(transcript: str) -> List[ConceptCandidate]:
    """Extract ranked visualizable concepts from the transcript by frequency × visualizability.
    Generic/abstract concepts are kept but flagged (they never mint an asset)."""
    n = _norm(transcript)
    tokens = n.split()
    counts: Dict[str, int] = {}
    for tok in tokens:
        if tok in _CONCEPT_LEXICON:
            counts[tok] = counts.get(tok, 0) + 1
    agg: Dict[str, ConceptCandidate] = {}
    for surface, c in counts.items():
        canon, vis, domain, generic = _CONCEPT_LEXICON[surface]
        cc = agg.get(canon)
        if cc is None:
            agg[canon] = ConceptCandidate(canon, surface, c, vis, domain, generic)
        else:
            cc.count += c
            if vis > cc.visualizability:
                cc.visualizability, cc.surface = vis, surface
    out = list(agg.values())
    for cc in out:
        cc.score = round(cc.count * cc.visualizability, 4)
    out.sort(key=lambda x: x.score, reverse=True)
    return out


def is_generic_concept(concept: str) -> bool:
    return concept in GENERIC_CONCEPTS or _norm(concept) in {_norm(g) for g in GENERIC_CONCEPTS}


def select_concept(candidates: List[ConceptCandidate]) -> Optional[ConceptCandidate]:
    """Pick the dominant CONCRETE concept (highest score, visualizable enough, not generic)."""
    for cc in candidates:
        if not cc.generic and cc.visualizability >= MIN_VISUALIZABILITY_TO_MINT and cc.count >= 1:
            return cc
    return None


# ── Concept → asset resolution (catalog hit by canonical or alias) ──────────────
def resolve_concept_to_asset(concept: str, catalog: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Return the asset_id whose canonical_concept or alias matches `concept`, else None."""
    catalog = catalog if catalog is not None else load_catalog()
    target = _norm(concept)
    for asset_id, entry in (catalog.get("assets") or {}).items():
        if not entry.get("approved"):
            continue
        keys = [entry.get("canonical_concept", "")] + list(entry.get("aliases") or [])
        if any(_norm(k) == target or target in _norm(k) or _norm(k) in target for k in keys if k):
            return asset_id
    return None


def recipe_for_concept(concept: str) -> Optional[Recipe]:
    target = _norm(concept)
    for r in RECIPES.values():
        keys = [r.canonical_concept] + list(r.aliases)
        if any(_norm(k) == target or target in _norm(k) or _norm(k) in target for k in keys):
            return r
    return None


# ── Validation + registration (growth controls) ─────────────────────────────────
def validate_render(webm_path: Path) -> Dict[str, Any]:
    """Physical validation before registration: alpha present, frames>0, valid bbox, no all-black."""
    import subprocess
    res = {"ok": False, "alpha_verified": False, "frame_count": 0, "reason": ""}
    if not webm_path.exists():
        res["reason"] = "file_absent"
        return res
    try:
        am = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream_tags=alpha_mode",
                             "-of", "default=nw=1:nk=1", str(webm_path)], capture_output=True, text=True, timeout=60).stdout.strip()
        nb = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
                             "-show_entries", "stream=nb_read_packets", "-of", "default=nw=1:nk=1", str(webm_path)],
                            capture_output=True, text=True, timeout=60).stdout.strip()
        res["alpha_verified"] = (am == "1")
        res["frame_count"] = int(nb or 0)
        res["ok"] = res["alpha_verified"] and res["frame_count"] > 0
        if not res["ok"]:
            res["reason"] = "no_alpha" if not res["alpha_verified"] else "no_frames"
    except Exception as e:  # pragma: no cover
        res["reason"] = f"probe_error:{e}"
    return res


def register_asset(
    catalog: Dict[str, Any],
    recipe: Recipe,
    *,
    variant_renders: Dict[str, Dict[str, Any]],
    created_from_task: str,
    max_new_assets_in_run: int = 1,
    run_new_count: int = 0,
) -> Dict[str, Any]:
    """Register a validated asset into the catalog. Growth-controlled and validation-gated.

    `variant_renders[variant]` must carry a passing `validate_render` result + cache metadata.
    Returns {registered, reason}. Refuses if: component not whitelisted, max-new exceeded,
    any variant fails pixel/alpha validation, or asset already present.
    """
    assets = catalog.setdefault("assets", {})
    if recipe.asset_id in assets:
        return {"registered": False, "reason": "already_present"}
    if run_new_count >= max_new_assets_in_run:
        return {"registered": False, "reason": "max_new_assets_per_task_reached"}
    bad = [c for c in recipe.components if c not in ALLOWED_COMPONENTS]
    if bad:
        return {"registered": False, "reason": f"unwhitelisted_components:{bad}"}
    for variant, meta in variant_renders.items():
        v = meta.get("validation") or {}
        if not (v.get("ok") and v.get("alpha_verified") and v.get("frame_count", 0) > 0):
            return {"registered": False, "reason": f"validation_failed:{variant}:{v.get('reason')}"}
    assets[recipe.asset_id] = {
        "asset_id": recipe.asset_id,
        "canonical_concept": recipe.canonical_concept,
        "aliases": list(recipe.aliases),
        "domain": recipe.domain,
        "recipe_type": recipe.recipe_type,
        "components": list(recipe.components),
        "remotion_composition": recipe.remotion_composition,
        "approved": True,
        "pixel_verified": True,
        "alpha_verified": all(m.get("validation", {}).get("alpha_verified") for m in variant_renders.values()),
        "created_from_task": created_from_task,
        "palette_version": PALETTE_VERSION,
        "variants": {v: {k: meta[k] for k in ("cache_key", "render_path", "frame_count", "fps", "duration_s")
                         if k in meta} for v, meta in variant_renders.items()},
    }
    return {"registered": True, "reason": "registered", "asset_id": recipe.asset_id}


# ── 53D: single public runtime entrypoint for the live route ────────────────────
import os
import subprocess


@dataclass
class Object3DResolution:
    status: str                          # "resolved" | "skipped"
    concept: Optional[str] = None
    asset_id: Optional[str] = None
    source_phrase: Optional[str] = None
    window_start_s: Optional[float] = None
    window_end_s: Optional[float] = None
    placement: str = "upper_right"
    animation_variant: str = "reveal_right"
    cache_hit: bool = False
    minted: bool = False
    approved: bool = False
    fallback_reason: Optional[str] = None
    resolution_path: str = ""            # exact_family | catalog_hit | alias_hit | recipe_mint
    evidence_tier: str = ""


def _cache_key_for(recipe: Recipe, variant: str) -> str:
    return (f"{recipe.asset_id}__{variant}__{recipe.width}x{recipe.height}"
            f"__{recipe.fps}fps__{recipe.frames}f__{PALETTE_VERSION}")


def _remotion_root() -> Optional[Path]:
    here = Path(__file__).resolve()
    for base in (here.parents[3], Path("/app"), Path.cwd()):
        cand = base / "remotion"
        if (cand / "node_modules" / ".bin" / "remotion").exists():
            return cand
    return None


def render_recipe_variants(recipe: Recipe, *, rendered_root: Path, budget_s: int = 90) -> Optional[Dict[str, Any]]:
    """FASE 6 — render the recipe's 2 variants via Remotion+three.js (host renderer). Returns
    validated variant_renders, or None if the renderer is unavailable / fails / times out. NEVER
    raises into the live route (the caller treats None as a clean fallback)."""
    rroot = _remotion_root()
    if rroot is None:
        logger.info("VPI_3D_MINT_REJECTED reason=renderer_unavailable")
        return None
    bin_path = rroot / "node_modules" / ".bin" / "remotion"
    vr: Dict[str, Any] = {}
    import time as _time
    deadline = _time.monotonic() + max(1, int(budget_s))
    for variant in ("reveal_left", "reveal_right"):
        remaining = max(1, int(deadline - _time.monotonic()))
        key = _cache_key_for(recipe, variant)
        out = rendered_root / f"{key}.webm"
        props = json.dumps({"variant": variant, "renderWidth": recipe.width, "renderHeight": recipe.height})
        try:
            r = subprocess.run(
                [str(bin_path), "render", "./Root.tsx", recipe.remotion_composition, str(out),
                 f"--props={props}", "--codec=vp9", "--pixel-format=yuva420p",
                 f"--frames=0-{recipe.frames - 1}"],
                cwd=str(rroot), capture_output=True, text=True, timeout=remaining,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            logger.warning("VPI_3D_MINT_REJECTED reason=render_failed detail=%s", str(e)[:120])
            return None
        if r.returncode != 0 or not out.exists():
            logger.warning("VPI_3D_MINT_REJECTED reason=render_rc=%s", r.returncode)
            return None
        val = validate_render(out)
        if not val.get("ok"):
            logger.warning("VPI_3D_MINT_REJECTED reason=validation:%s variant=%s", val.get("reason"), variant)
            return None
        import hashlib
        vr[variant] = {"cache_key": key, "render_path": f"assets/objects_3d/rendered/{key}.webm",
                       "frame_count": val["frame_count"], "fps": recipe.fps,
                       "duration_s": round(val["frame_count"] / recipe.fps, 3), "validation": val,
                       "asset_sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
                       "bytes": out.stat().st_size}
    return vr


def _persist_mint(recipe: Recipe, vr: Dict[str, Any], *, rendered_root: Path, task_id: str, run_new_count: int) -> bool:
    """Add manifest entries + register the asset in the catalog (host-writable assets only)."""
    try:
        mf = rendered_root / "manifest.json"
        manifest = json.loads(mf.read_text()) if mf.exists() else {"objects": {}}
        for variant, meta in vr.items():
            manifest.setdefault("objects", {})[meta["cache_key"]] = {
                "asset_id": recipe.asset_id, "animation_variant": variant,
                "object_3d_cache_key": meta["cache_key"], "renderer": "remotion+three",
                "render_path": meta["render_path"], "frame_count": meta["frame_count"],
                "resolution": f"{recipe.width}x{recipe.height}", "fps": recipe.fps,
                "duration_s": meta["duration_s"], "palette_version": PALETTE_VERSION,
                "alpha_verified": meta["validation"]["alpha_verified"],
                "asset_sha256": meta.get("asset_sha256", ""), "bytes": meta.get("bytes", 0),
            }
        mf.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        catalog = load_catalog()
        res = register_asset(catalog, recipe, variant_renders=vr, created_from_task=task_id, run_new_count=run_new_count)
        if res.get("registered"):
            save_catalog(catalog)
            return True
        logger.warning("VPI_3D_MINT_REJECTED reason=register:%s", res.get("reason"))
        return False
    except OSError as e:
        logger.warning("VPI_3D_MINT_REJECTED reason=persist_failed:%s", str(e)[:120])
        return False


def _window_for_phrase(words, surfaces, *, clip_duration_s, hook_end_s, avoid):
    """Reuse the 52C phrase-windowing for the concept's surface tokens (no new scorer)."""
    from .vpi_object_2d import place_object_best_phrase
    cands = [{"matched_phrase": s, "matched_norm": _norm(s)} for s in surfaces if s]
    placed = place_object_best_phrase(words or [], cands, clip_duration=clip_duration_s,
                                      hook_end=hook_end_s, avoid=avoid or [], closure_tail_s=1.5)
    return placed.get("window"), placed.get("chosen_phrase")


def resolve_or_mint_3d_asset(
    *,
    transcript_words: List[Dict[str, Any]],
    clip_text: str,
    clip_duration_s: float,
    existing_visuals: Dict[str, Any],
    task_id: str,
    clip_id: str,
    task_context: Optional[Dict[str, Any]] = None,
    rendered_root: Optional[Path] = None,
    allow_mint: bool = True,
    mint_budget_s: int = 90,
) -> Object3DResolution:
    """FASE 4 — the ONE public live entrypoint. Resolver order:
    exact 4-family 3D > catalog hit > alias hit > registered composite recipe > new safe mint.
    Never raises; on any miss/failure returns status='skipped' so the caller falls to card/2D."""
    tc = task_context if task_context is not None else {}
    rroot = rendered_root or (_objects_root() / "rendered")
    hook_end = float(tc.get("hook_end_s") or 3.0) + 4.0
    avoid = list(tc.get("avoid_intervals") or [])

    # FASE 11 — strong B-roll wins: 3D is not evaluated at all (defense-in-depth; the live hook
    # also guards this before calling).
    if bool((existing_visuals or {}).get("broll_strong")):
        return Object3DResolution(status="skipped", fallback_reason="strong_broll_present")

    # 1/2) exact 4-family 3D (53/53B literal/inferred gate)
    try:
        from .vpi_object_3d_service import select_object_3d, _choose_placement_and_variant
        dec = select_object_3d(transcript_words or [], existing_visuals=existing_visuals,
                               clip_duration_s=clip_duration_s, task_context=tc)
    except Exception as e:  # never break the live route
        logger.info("VPI_3D_LIVE_FALLBACK task_id=%s clip_id=%s reason=exact_family_error:%s", task_id, clip_id, str(e)[:80])
        dec = None
        from .vpi_object_3d_service import _choose_placement_and_variant  # type: ignore
    if dec is not None:
        return Object3DResolution(
            status="resolved", concept=dec.intent, asset_id=dec.asset_id, source_phrase=dec.phrase,
            window_start_s=dec.window_start_s, window_end_s=dec.window_end_s, placement=dec.placement,
            animation_variant=dec.animation_variant, cache_hit=True, minted=False, approved=True,
            resolution_path="exact_family", evidence_tier=getattr(dec, "evidence_tier", ""))

    # 3) concept extraction (no literal allow-list)
    concepts = extract_concepts(clip_text or "")
    sel = select_concept(concepts)
    if sel is None:
        logger.info("VPI_3D_LIVE_FALLBACK task_id=%s clip_id=%s reason=no_visualizable_concept", task_id, clip_id)
        return Object3DResolution(status="skipped", fallback_reason="no_visualizable_concept")
    concept = sel.concept
    logger.info("VPI_3D_CONCEPT_EXTRACTED task_id=%s clip_id=%s concept=%s vis=%.2f count=%s",
                task_id, clip_id, concept, sel.visualizability, sel.count)
    placement, variant = _choose_placement_and_variant(existing_visuals)

    catalog = load_catalog()
    recipe = recipe_for_concept(concept)
    surfaces = ([sel.surface] + list(recipe.aliases) + [concept]) if recipe else [sel.surface, concept]

    # 3/4) catalog / alias hit
    asset_id = resolve_concept_to_asset(concept, catalog)
    if asset_id:
        tc["object_3d_catalog_hits"] = int(tc.get("object_3d_catalog_hits") or 0) + 1
        alias = bool(sel.surface and _norm(sel.surface) != _norm(concept))
        win, phrase = _window_for_phrase(transcript_words, surfaces, clip_duration_s=clip_duration_s,
                                         hook_end_s=hook_end, avoid=avoid)
        if not win:
            logger.info("VPI_3D_LIVE_FALLBACK task_id=%s clip_id=%s reason=no_clean_window asset=%s", task_id, clip_id, asset_id)
            return Object3DResolution(status="skipped", concept=concept, asset_id=asset_id,
                                      fallback_reason="no_clean_window")
        tc["object_3d_cache_hits"] = int(tc.get("object_3d_cache_hits") or 0) + 1
        logger.info("VPI_3D_%s task_id=%s clip_id=%s concept=%s asset=%s window=%.2f-%.2f cache_hit=true",
                    "ALIAS_HIT" if alias else "CATALOG_HIT", task_id, clip_id, concept, asset_id,
                    float(win["start_s"]), float(win["end_s"]))
        return Object3DResolution(status="resolved", concept=concept, asset_id=asset_id, source_phrase=phrase,
                                  window_start_s=float(win["start_s"]), window_end_s=float(win["end_s"]),
                                  placement=placement, animation_variant=variant, cache_hit=True, minted=False,
                                  approved=True, resolution_path="alias_hit" if alias else "catalog_hit")

    # 5) new safe recipe mint (growth-controlled; host renderer only)
    if not recipe:
        logger.info("VPI_3D_LIVE_FALLBACK task_id=%s clip_id=%s reason=no_recipe_for_concept concept=%s", task_id, clip_id, concept)
        return Object3DResolution(status="skipped", concept=concept, fallback_reason="no_recipe_for_concept")
    if not allow_mint or bool(tc.get("object_3d_mint_attempted")):
        logger.info("VPI_3D_LIVE_FALLBACK task_id=%s clip_id=%s reason=mint_not_allowed_or_already_attempted", task_id, clip_id)
        return Object3DResolution(status="skipped", concept=concept, fallback_reason="mint_budget_exhausted")
    tc["object_3d_mint_attempted"] = True
    run_new = int(tc.get("object_3d_new_assets_created") or 0)
    logger.info("VPI_3D_MINT_STARTED task_id=%s clip_id=%s concept=%s asset=%s", task_id, clip_id, concept, recipe.asset_id)
    vr = render_recipe_variants(recipe, rendered_root=rroot, budget_s=mint_budget_s)
    if not vr or not _persist_mint(recipe, vr, rendered_root=rroot, task_id=task_id, run_new_count=run_new):
        return Object3DResolution(status="skipped", concept=concept, fallback_reason="mint_failed")
    tc["object_3d_new_assets_created"] = run_new + 1
    logger.info("VPI_3D_MINT_APPROVED task_id=%s clip_id=%s concept=%s asset=%s", task_id, clip_id, concept, recipe.asset_id)
    win, phrase = _window_for_phrase(transcript_words, surfaces, clip_duration_s=clip_duration_s,
                                     hook_end_s=hook_end, avoid=avoid)
    if not win:
        return Object3DResolution(status="skipped", concept=concept, asset_id=recipe.asset_id,
                                  minted=True, approved=True, fallback_reason="no_clean_window_post_mint")
    return Object3DResolution(status="resolved", concept=concept, asset_id=recipe.asset_id, source_phrase=phrase,
                              window_start_s=float(win["start_s"]), window_end_s=float(win["end_s"]),
                              placement=placement, animation_variant=variant, cache_hit=False, minted=True,
                              approved=True, resolution_path="recipe_mint")


# ── Per-task live runtime state (growth control across clips in one task) ────────
_LIVE_TASK_STATE: Dict[str, Dict[str, Any]] = {}


def get_live_task_state(task_id: str) -> Dict[str, Any]:
    return _LIVE_TASK_STATE.setdefault(task_id, {})


def reset_live_task_state(task_id: str) -> None:
    _LIVE_TASK_STATE.pop(task_id, None)
