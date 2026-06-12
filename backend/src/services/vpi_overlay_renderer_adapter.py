"""
vpi_overlay_renderer_adapter.py — Overlay renderer adapter skeleton.

Provides adapter classes that consume ViraClipTimelinePlan / ASSCaptionPlan
and produce renderer-specific commands or data structures.

Three adapters:
1. FFmpegASSAdapter — available by default; produces FFmpeg drawtext/ASS filter args.
2. RemotionAdapter — available only when VIRACLIP_REMOTION_OVERLAYS=true AND
   remotion project files exist AND command path is configured.
3. MotionCanvasAdapter — available only when VPI_MOTION_CANVAS_ENABLED=true.

Design
------
- Adapter pattern: each adapter has a consistent interface (render_plan, to_command).
- Pure data transformation: no actual rendering happens here.
- Compatible with ViraClipTimelinePlan and ASSCaptionPlan.

Integration
-----------
- editing_pipeline.py: consumes adapter output → runs FFmpeg/Remotion/MotionCanvas
- overlay_renderer.py: consumes FFmpegASSAdapter → builds filter graph
- caption_service.py: consumes FFmpegASSAdapter → builds .ass file
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ── Environment flags ───────────────────────────────────────────────────────────

VPI_REMOTION_ENABLED = os.environ.get("VPI_REMOTION_ENABLED", "false").lower() == "true"
VPI_MOTION_CANVAS_ENABLED = os.environ.get("VPI_MOTION_CANVAS_ENABLED", "false").lower() == "true"

# New env var for Remotion overlay path (default: remotion/ in project root)
VIRACLIP_REMOTION_OVERLAYS = os.environ.get("VIRACLIP_REMOTION_OVERLAYS", "false").lower() == "true"
VIRACLIP_REMOTION_PROJECT_DIR = os.environ.get(
    "VIRACLIP_REMOTION_PROJECT_DIR",
    "",
)
VIRACLIP_REMOTION_COMMAND = os.environ.get("VIRACLIP_REMOTION_COMMAND", "").strip()

# Sidecar render mode env vars
VIRACLIP_REMOTION_RENDER_MODE = os.environ.get("VIRACLIP_REMOTION_RENDER_MODE", "local_command").strip().lower()
VIRACLIP_REMOTION_SIDECAR_TIMEOUT = int(os.environ.get("VIRACLIP_REMOTION_SIDECAR_TIMEOUT", "180"))
VIRACLIP_REMOTION_SIDECAR_POLL_INTERVAL = float(os.environ.get("VIRACLIP_REMOTION_SIDECAR_POLL_INTERVAL", "2.0"))
# Shared temp base directory for sidecar file handoff
VIRACLIP_REMOTION_SIDECAR_BASE_DIR = os.environ.get(
    "VIRACLIP_REMOTION_SIDECAR_BASE_DIR",
    "/app/temp/remotion",
).rstrip("/")


# ── Overlay render mode ─────────────────────────────────────────────────────────


class OverlayRenderMode(Enum):
    """Supported overlay render backends."""
    FFMPEG_ASS = auto()           # Stable FFmpeg + ASS subtitle path
    REMOTION_OVERLAY = auto()     # Optional Remotion React-based renderer
    MOTION_CANVAS_FUTURE = auto() # Future Motion Canvas support


# ── Overlay render result ───────────────────────────────────────────────────────


@dataclass
class OverlayRenderResult:
    """Result of an overlay render attempt.

    Status values:
    - "rendered"                  — Successfully rendered
    - "skipped"                   — Skipped (not enabled, not available)
    - "failed"                    — Render failed
    - "planned"                   — Scene plan built, not yet rendered
    - "planned_sidecar"           — Render request written for sidecar consumption
    - "sidecar_not_running"       — Sidecar container not detected
    - "sidecar_timeout"           — Sidecar did not produce result in time
    - "sidecar_failed"            — Sidecar reported failure
    - "render_disabled"           — Render explicitly disabled via env var
    - "skipped_remotion_unavailable" — Remotion runtime not ready
    """
    status: str
    output_path: str = ""
    scene_plan_path: str = ""
    reason: str = ""
    backend: str = "ffmpeg_ass"      # Which adapter produced this result
    metadata: Dict[str, Any] = field(default_factory=dict)



# ── Renderer command ────────────────────────────────────────────────────────────


@dataclass
class RendererCommand:
    """A renderer command produced by an adapter."""
    renderer: str                          # "ffmpeg", "remotion", "motion_canvas"
    command: List[str]                     # CLI command parts
    input_files: List[str] = field(default_factory=list)
    output_file: str = ""
    env: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── Base adapter ────────────────────────────────────────────────────────────────


class BaseOverlayAdapter:
    """Base class for overlay renderer adapters."""

    def __init__(self, name: str, enabled: bool = True) -> None:
        self.name = name
        self.enabled = enabled

    def is_available(self) -> bool:
        return self.enabled

    def render_plan(self, plan: Any, **kwargs: Any) -> RendererCommand:
        """Convert a plan to a renderer command.

        Subclasses must override this.
        """
        raise NotImplementedError

    def to_command(self, plan: Any, **kwargs: Any) -> List[str]:
        """Convert a plan to a CLI command list.

        Subclasses must override this.
        """
        raise NotImplementedError


# ── FFmpeg ASS adapter (default) ────────────────────────────────────────────────


class FFmpegASSAdapter(BaseOverlayAdapter):
    """FFmpeg ASS adapter — produces FFmpeg filter graph arguments.

    Available by default.  Consumes ASSCaptionPlan and produces
    FFmpeg drawtext / ass filter arguments.
    """

    def __init__(self) -> None:
        super().__init__("ffmpeg_ass", enabled=True)

    def render_plan(
        self,
        plan: Any,  # ASSCaptionPlan
        output_ass_path: str = "/tmp/captions.ass",
        **kwargs: Any,
    ) -> RendererCommand:
        """Convert an ASSCaptionPlan to an FFmpeg ASS render command.

        Produces a command that writes the .ass file and returns the
        FFmpeg filter arguments needed to burn it into video.
        """
        # Generate ASS script content
        ass_script = plan.to_ass_script() if hasattr(plan, "to_ass_script") else ""

        # Build FFmpeg filter arguments
        vf_parts: List[str] = []

        # ASS subtitle burn
        vf_parts.append(f"ass={output_ass_path}")

        # Additional drawtext filters for dynamic overlays
        if hasattr(plan, "hook_event") and plan.hook_event:
            hook = plan.hook_event
            vf_parts.append(
                f"drawtext=text='{hook.text}':"
                f"x={hook.margin_l}:y={hook.margin_v}:"
                f"fontsize=36:fontcolor=white:"
                f"enable='between(t,{hook.start},{hook.end})'"
            )

        filter_complex = ",".join(vf_parts) if vf_parts else ""

        return RendererCommand(
            renderer="ffmpeg",
            command=[
                "ffmpeg",
                "-i", kwargs.get("input_video", "input.mp4"),
                "-vf", filter_complex,
                "-c:a", "copy",
                kwargs.get("output_video", "output.mp4"),
            ],
            input_files=[kwargs.get("input_video", "input.mp4")],
            output_file=kwargs.get("output_video", "output.mp4"),
            metadata={
                "ass_script": ass_script,
                "ass_path": output_ass_path,
                "filter_complex": filter_complex,
            },
        )

    def to_command(
        self,
        plan: Any,
        output_ass_path: str = "/tmp/captions.ass",
        **kwargs: Any,
    ) -> List[str]:
        cmd = self.render_plan(plan, output_ass_path, **kwargs)
        return cmd.command


# ── Remotion adapter (opt-in) ───────────────────────────────────────────────────


def _check_remotion_available() -> bool:
    """Check if Remotion is actually available on this system.

    Returns True only when ALL of:
    1. VIRACLIP_REMOTION_OVERLAYS env var is true
    2. remotion project directory exists
    3. npx remotion is available on PATH
    """
    if not _is_truthy_env("VIRACLIP_REMOTION_OVERLAYS", default=False):
        logger.debug("[remotion-adapter] VIRACLIP_REMOTION_OVERLAYS not enabled")
        return False
    status = detect_remotion_runtime_status()
    if not bool(status.get("runtime_ready")):
        logger.debug("[remotion-adapter] Remotion runtime not ready reasons=%s", ",".join(status.get("reasons") or []))
        return False
    logger.info("[remotion-adapter] Remotion is available at %s", str(status.get("project_dir") or "-"))
    return True


def _is_truthy_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "true" if default else "false")
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _resolve_remotion_project_dir(project_dir: Optional[Path] = None) -> Path:
    if project_dir is not None and str(project_dir).strip():
        return Path(str(project_dir))
    if VIRACLIP_REMOTION_PROJECT_DIR:
        return Path(VIRACLIP_REMOTION_PROJECT_DIR)
    here = Path(__file__).resolve()
    repo_root = None
    for ancestor in here.parents:
        if (ancestor / "docker-compose.yml").exists():
            repo_root = ancestor
            break
        if (ancestor / "src").exists() and (ancestor / "scripts").exists():
            repo_root = ancestor
            break
    if repo_root is None:
        repo_root = here.parents[2]
    candidates = [
        Path("/app/remotion"),
        repo_root / "remotion",
        here.parents[2] / "remotion",  # backend/remotion (legacy fallback)
        Path.cwd() / "remotion",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[1]


def _detect_remotion_scaffold(project_dir: Path) -> Dict[str, Any]:
    remotion_dir = _resolve_remotion_project_dir(project_dir)
    root = remotion_dir.parent if remotion_dir.name == "remotion" else Path(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    root_pkg = root / "package.json"
    remotion_pkg = remotion_dir / "package.json"
    root_pkg_json = _load_json(root_pkg) if root_pkg.exists() else {}
    remotion_pkg_json = _load_json(remotion_pkg) if remotion_pkg.exists() else {}
    root_deps = {
        **(root_pkg_json.get("dependencies") or {}),
        **(root_pkg_json.get("devDependencies") or {}),
    }
    remotion_deps = {
        **(remotion_pkg_json.get("dependencies") or {}),
        **(remotion_pkg_json.get("devDependencies") or {}),
    }
    dep_keys = {str(k).lower() for k in list(root_deps.keys()) + list(remotion_deps.keys())}
    remotion_declared = any(k == "remotion" or k.startswith("@remotion/") for k in dep_keys)
    node_modules_candidates = [
        root / "node_modules" / "remotion",
        root / "node_modules" / "@remotion",
        remotion_dir / "node_modules" / "remotion",
        remotion_dir / "node_modules" / "@remotion",
    ]
    remotion_installed = any(path.exists() for path in node_modules_candidates)
    scaffold_required = [
        remotion_dir / "Root.tsx",
        remotion_dir / "ViraClipOverlayComposition.tsx",
        remotion_dir / "loadScenePlan.ts",
        remotion_dir / "types.ts",
        remotion_dir / "styleTokens.ts",
    ]
    component_required = [
        remotion_dir / "components" / "HookCard.tsx",
        remotion_dir / "components" / "CaptionEmphasis.tsx",
        remotion_dir / "components" / "SemanticObject.tsx",
        remotion_dir / "components" / "DocumentReveal.tsx",
        remotion_dir / "components" / "ChecklistReveal.tsx",
        remotion_dir / "components" / "WarningBadge.tsx",
        remotion_dir / "components" / "LowerThird.tsx",
    ]
    scaffold_present = remotion_dir.exists() and all(p.exists() for p in scaffold_required + component_required)
    return {
        "project_dir": str(remotion_dir),
        "scaffold_present": bool(scaffold_present),
        "dependencies_declared": bool(remotion_declared),
        "dependencies_installed": bool(remotion_installed),
        "root_package_json": str(root_pkg) if root_pkg.exists() else "",
        "remotion_package_json": str(remotion_pkg) if remotion_pkg.exists() else "",
    }


def _resolve_remotion_command(project_dir: Path) -> List[str]:
    custom = VIRACLIP_REMOTION_COMMAND
    if custom:
        try:
            parts = [p for p in shlex.split(custom) if p]
        except Exception:
            parts = [p for p in custom.split(" ") if p]
        if parts:
            return parts
    return ["npx", "remotion", "render"]


def detect_remotion_runtime_status(project_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Detect Remotion runtime readiness without rendering.

    runtime_ready is true only when:
    - scaffold_present
    - dependencies_installed
    - command_available
    """
    pdir = _resolve_remotion_project_dir(project_dir)
    scaffold_status = _detect_remotion_scaffold(pdir)
    command_parts = _resolve_remotion_command(pdir)
    command_bin = command_parts[0] if command_parts else ""
    node_available = bool(shutil.which("node"))
    npx_available = bool(shutil.which("npx"))
    command_available = False
    if command_bin:
        as_path = Path(command_bin)
        if as_path.exists() and os.access(str(as_path), os.X_OK):
            command_available = True
        else:
            command_available = bool(shutil.which(command_bin))

    reasons: List[str] = []
    if not bool(scaffold_status.get("scaffold_present")):
        reasons.append("remotion_scaffold_missing")
    if not bool(scaffold_status.get("dependencies_declared")):
        reasons.append("remotion_dependencies_not_declared")
    if not bool(scaffold_status.get("dependencies_installed")):
        reasons.append("remotion_dependencies_missing")
    if not node_available:
        reasons.append("remotion_node_missing")
    if not npx_available and not VIRACLIP_REMOTION_COMMAND:
        reasons.append("remotion_npx_missing")
    if not command_available:
        reasons.append("remotion_command_unavailable")

    runtime_ready = bool(
        scaffold_status.get("scaffold_present")
        and scaffold_status.get("dependencies_installed")
        and command_available
    )

    return {
        "scaffold_present": bool(scaffold_status.get("scaffold_present")),
        "dependencies_declared": bool(scaffold_status.get("dependencies_declared")),
        "dependencies_installed": bool(scaffold_status.get("dependencies_installed")),
        "node_available": node_available,
        "npx_available": npx_available,
        "command_available": command_available,
        "runtime_ready": runtime_ready,
        "reasons": reasons,
        "project_dir": str(pdir),
        "command": " ".join(command_parts) if command_parts else "",
    }


class RemotionAdapter(BaseOverlayAdapter):
    """Remotion adapter — produces Remotion composition data.

    Available only when VIRACLIP_REMOTION_OVERLAYS=true AND remotion project
    files exist AND npx is on PATH.
    Consumes ViraClipTimelinePlan and produces Remotion-compatible JSON.
    """

    def __init__(self) -> None:
        self.project_dir = _resolve_remotion_project_dir()
        self.scaffold_status = _detect_remotion_scaffold(self.project_dir)
        self.runtime_status = detect_remotion_runtime_status(self.project_dir)
        available = _check_remotion_available()
        super().__init__("remotion", enabled=available)

    def build_scene_plan(
        self,
        timeline_plan: Any,  # ViraClipTimelinePlan
        output_dir: str = "/tmp/remotion_scenes",
        visual_style: Optional[str] = None,
    ) -> OverlayRenderResult:
        """Build a Remotion scene plan from a ViraClipTimelinePlan.

        This is a pure data transformation — no rendering happens here.
        Returns an OverlayRenderResult with status='planned' and the
        scene plan path.
        """
        if not self.is_available():
            logger.info("[remotion-adapter] Remotion not available; returning skipped")
            return OverlayRenderResult(
                status="skipped",
                reason="Remotion adapter not available",
                backend="remotion",
            )

        # Build the scene plan
        scene_plan = self._build_scene_plan_data(timeline_plan, visual_style)

        # Write to output directory
        os.makedirs(output_dir, exist_ok=True)
        clip_id = getattr(timeline_plan, "clip_id", "unknown")
        scene_path = os.path.join(output_dir, f"{clip_id}_scene_plan.json")

        with open(scene_path, "w") as f:
            json.dump(scene_plan, f, indent=2, default=str)

        logger.info(
            "[remotion-adapter] Scene plan written to %s (status=planned)",
            scene_path,
        )

        return OverlayRenderResult(
            status="planned",
            output_path="",
            scene_plan_path=scene_path,
            reason="Scene plan built; rendering requires explicit enable",
            backend="remotion",
            metadata={"scene_plan": scene_plan},
        )

    def render_scene(
        self,
        scene_plan_path: str,
        output_path: str = "/tmp/remotion_output.mp4",
    ) -> OverlayRenderResult:
        """Render a Remotion scene plan to video.

        Returns 'skipped' unless explicitly enabled via env var.
        This prevents accidental Remotion rendering when the user
        hasn't explicitly opted in.
        """
        if not self.is_available():
            return OverlayRenderResult(
                status="skipped",
                reason="Remotion adapter not available",
                backend="remotion",
            )

        # Check if rendering is explicitly enabled
        render_enabled = os.environ.get("VIRACLIP_REMOTION_RENDER", "false").lower() == "true"
        if not render_enabled:
            logger.info(
                "[remotion-adapter] Remotion render skipped (VIRACLIP_REMOTION_RENDER != true)"
            )
            return OverlayRenderResult(
                status="skipped",
                scene_plan_path=scene_plan_path,
                reason="Remotion rendering not explicitly enabled; set VIRACLIP_REMOTION_RENDER=true",
                backend="remotion",
            )

        # Read the scene plan
        try:
            with open(scene_plan_path) as f:
                scene_plan = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error("[remotion-adapter] Failed to read scene plan: %s", e)
            return OverlayRenderResult(
                status="failed",
                scene_plan_path=scene_plan_path,
                reason=f"Failed to read scene plan: {e}",
                backend="remotion",
            )

        # Build render command
        composition_id = scene_plan.get("composition", {}).get("id", "unknown")
        cmd = RendererCommand(
            renderer="remotion",
            command=[
                "npx", "remotion", "render",
                "--composition-id", composition_id,
                str(self.project_dir / "Root.tsx"),
                output_path,
            ],
            output_file=output_path,
            env={
                "REMOTION_COMPOSITION_JSON": json.dumps(scene_plan),
                "REMOTION_PROJECT_DIR": str(self.project_dir),
            },
            metadata={"scene_plan": scene_plan},
        )

        logger.info(
            "[remotion-adapter] Render command prepared: %s",
            " ".join(cmd.command),
        )

        return OverlayRenderResult(
            status="planned",
            output_path=output_path,
            scene_plan_path=scene_plan_path,
            reason="Render command prepared; execute via editing_pipeline",
            backend="remotion",
            metadata={"command": cmd.command, "env": cmd.env},
        )

    def render_remotion_overlay(
        self,
        scene_plan_path: str,
        output_path: str,
    ) -> OverlayRenderResult:
        scene = Path(str(scene_plan_path or ""))
        output = Path(str(output_path or ""))
        logger.info(
            "REMOTION_OVERLAY_RENDER_REQUESTED scene=%s output=%s",
            str(scene),
            str(output),
        )

        # ── Dispatch to sidecar filesystem mode if configured ──────────────
        if VIRACLIP_REMOTION_RENDER_MODE == "sidecar_filesystem":
            logger.info(
                "[remotion-adapter] Dispatching to sidecar filesystem mode "
                "(VIRACLIP_REMOTION_RENDER_MODE=sidecar_filesystem)"
            )
            return self.render_remotion_overlay_sidecar(scene_plan_path, output_path)

        render_enabled = _is_truthy_env("VIRACLIP_REMOTION_OVERLAYS", default=False)
        runtime_status = detect_remotion_runtime_status(self.project_dir)
        if not render_enabled:
            reason = "render_disabled"
            logger.info("REMOTION_OVERLAY_RENDER_SKIPPED reason=%s", reason)
            return OverlayRenderResult(
                status="render_disabled",
                output_path="",
                scene_plan_path=str(scene),
                reason=reason,
                backend="remotion",
                metadata={"render_enabled": False, **self.scaffold_status, **runtime_status},
            )
        if not scene.exists():
            reason = "scene_plan_missing"
            logger.info("REMOTION_OVERLAY_RENDER_SKIPPED reason=%s", reason)
            return OverlayRenderResult(
                status="failed",
                output_path="",
                scene_plan_path=str(scene),
                reason=reason,
                backend="remotion",
                metadata={**self.scaffold_status, **runtime_status},
            )

        cmd_parts = _resolve_remotion_command(self.project_dir)

        if not bool(runtime_status.get("runtime_ready")):
            reason = "skipped_remotion_unavailable:" + ",".join(runtime_status.get("reasons") or [])
            logger.info("REMOTION_OVERLAY_RENDER_SKIPPED reason=%s", reason)
            return OverlayRenderResult(
                status="skipped_remotion_unavailable",
                output_path="",
                scene_plan_path=str(scene),
                reason=reason,
                backend="remotion",
                metadata={**self.scaffold_status, **runtime_status, "render_enabled": True},
            )

        output.parent.mkdir(parents=True, exist_ok=True)
        composition_id = "ViraClipOverlay"
        render_cmd = [
            *cmd_parts,
            str(self.project_dir / "Root.tsx"),
            composition_id,
            str(output),
            "--props",
            json.dumps({"scenePlanPath": str(scene)}, ensure_ascii=False),
        ]
        env = os.environ.copy()
        env["VIRACLIP_REMOTION_SCENE_PLAN"] = str(scene)
        env["VIRACLIP_REMOTION_RENDER"] = "true"
        try:
            result = subprocess.run(
                render_cmd,
                cwd=str(self.project_dir.parent),
                env=env,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if result.returncode == 0 and output.exists():
                logger.info("REMOTION_OVERLAY_RENDERED output=%s", str(output))
                return OverlayRenderResult(
                    status="rendered",
                    output_path=str(output),
                    scene_plan_path=str(scene),
                    reason="rendered",
                    backend="remotion",
                    metadata={
                        **self.scaffold_status,
                        **runtime_status,
                        "render_enabled": True,
                        "render_command_used": " ".join(render_cmd),
                    },
                )
            reason = f"render_command_failed:{(result.stderr or result.stdout or 'unknown')[-240:]}"
            logger.warning("REMOTION_OVERLAY_FAILED reason=%s", reason)
            logger.warning("REMOTION_OVERLAY_FALLBACK backend=ffmpeg_ass reason=%s", reason)
            return OverlayRenderResult(
                status="failed",
                output_path="",
                scene_plan_path=str(scene),
                reason=reason,
                backend="remotion",
                metadata={
                    **self.scaffold_status,
                    **runtime_status,
                    "render_enabled": True,
                    "render_command_used": " ".join(render_cmd),
                },
            )
        except Exception as exc:
            reason = f"render_exception:{exc}"
            logger.warning("REMOTION_OVERLAY_FAILED reason=%s", reason)
            logger.warning("REMOTION_OVERLAY_FALLBACK backend=ffmpeg_ass reason=%s", reason)
            return OverlayRenderResult(
                status="failed",
                output_path="",
                scene_plan_path=str(scene),
                reason=reason,
                backend="remotion",
                metadata={
                    **self.scaffold_status,
                    **runtime_status,
                    "render_enabled": True,
                    "render_command_used": " ".join(render_cmd),
                },
            )

    # ── Sidecar filesystem mode helpers ──────────────────────────────────────

    def _sidecar_requests_dir(self) -> Path:
        """Return the directory where render request files are written."""
        return Path(VIRACLIP_REMOTION_SIDECAR_BASE_DIR) / "requests"

    def _sidecar_results_dir(self) -> Path:
        """Return the directory where render result files are written."""
        return Path(VIRACLIP_REMOTION_SIDECAR_BASE_DIR) / "results"

    def _sidecar_scenes_dir(self) -> Path:
        """Return the directory where scene plan files are written."""
        return Path(VIRACLIP_REMOTION_SIDECAR_BASE_DIR) / "scenes"

    def _detect_sidecar_running(self) -> bool:
        """Detect if the sidecar container is running via heartbeat file.

        The sidecar watchdog writes a heartbeat file at
        VIRACLIP_REMOTION_SIDECAR_BASE_DIR/.sidecar_heartbeat on each poll
        cycle.  If the file exists and was modified within the last 30
        seconds, we consider the sidecar running.
        """
        heartbeat = Path(VIRACLIP_REMOTION_SIDECAR_BASE_DIR) / ".sidecar_heartbeat"
        if not heartbeat.exists():
            logger.debug("[remotion-adapter] Sidecar heartbeat file not found at %s", heartbeat)
            return False
        try:
            age = (Path().stat() if False else None)  # placeholder
            mtime = heartbeat.stat().st_mtime
            import time
            if (time.time() - mtime) > 30.0:
                logger.debug("[remotion-adapter] Sidecar heartbeat stale (>30s old)")
                return False
            logger.debug("[remotion-adapter] Sidecar heartbeat detected (age=%.1fs)", time.time() - mtime)
            return True
        except OSError:
            return False

    def _write_sidecar_request(
        self,
        clip_id: str,
        scene_plan_path: str,
        output_path: str,
    ) -> Path:
        """Write a render request JSON for the sidecar watchdog to consume.

        The request file is written to:
          VIRACLIP_REMOTION_SIDECAR_BASE_DIR/requests/<clip_id>_render_request.json

        Returns the path to the written request file.
        """
        req_dir = self._sidecar_requests_dir()
        req_dir.mkdir(parents=True, exist_ok=True)

        request = {
            "clip_id": clip_id,
            "scene_plan_path": scene_plan_path,
            "output_path": output_path,
            "composition_id": "ViraClipOverlay",
            "render_mode": "sidecar_filesystem",
            "requested_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        }
        req_path = req_dir / f"{clip_id}_render_request.json"
        req_path.write_text(json.dumps(request, indent=2, default=str), encoding="utf-8")
        logger.info(
            "[remotion-adapter] Sidecar render request written to %s",
            str(req_path),
        )
        return req_path

    def _poll_sidecar_result(
        self,
        clip_id: str,
        timeout: Optional[float] = None,
        poll_interval: Optional[float] = None,
    ) -> OverlayRenderResult:
        """Poll for a sidecar render result file.

        Waits up to *timeout* seconds (default VIRACLIP_REMOTION_SIDECAR_TIMEOUT),
        checking every *poll_interval* seconds (default
        VIRACLIP_REMOTION_SIDECAR_POLL_INTERVAL).

        Returns an OverlayRenderResult with status:
        - "rendered" if the result file reports success
        - "sidecar_failed" if the result file reports failure
        - "sidecar_timeout" if the timeout expires
        """
        timeout = timeout if timeout is not None else float(VIRACLIP_REMOTION_SIDECAR_TIMEOUT)
        poll_interval = poll_interval if poll_interval is not None else float(VIRACLIP_REMOTION_SIDECAR_POLL_INTERVAL)

        result_dir = self._sidecar_results_dir()
        result_path = result_dir / f"{clip_id}_render_result.json"

        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            if result_path.exists():
                try:
                    data = json.loads(result_path.read_text(encoding="utf-8"))
                    status = str(data.get("status", "unknown"))
                    output_path = str(data.get("output_path", ""))
                    reason = str(data.get("reason", ""))
                    file_size = data.get("file_size_bytes", 0)

                    # Clean up the result file after reading
                    try:
                        result_path.unlink(missing_ok=True)
                    except Exception:
                        pass

                    if status == "rendered":
                        logger.info(
                            "[remotion-adapter] Sidecar render succeeded output=%s",
                            output_path,
                        )
                        return OverlayRenderResult(
                            status="rendered",
                            output_path=output_path,
                            scene_plan_path="",
                            reason=reason or "sidecar_rendered",
                            backend="remotion",
                            metadata={"sidecar_mode": True, "file_size_bytes": file_size},
                        )
                    else:
                        logger.warning(
                            "[remotion-adapter] Sidecar render failed status=%s reason=%s",
                            status,
                            reason,
                        )
                        return OverlayRenderResult(
                            status="sidecar_failed",
                            output_path=output_path,
                            scene_plan_path="",
                            reason=reason or f"sidecar_status:{status}",
                            backend="remotion",
                            metadata={"sidecar_mode": True, "sidecar_status": status},
                        )
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning(
                        "[remotion-adapter] Error reading sidecar result: %s",
                        exc,
                    )
                    # If the file is corrupt, remove it and keep polling
                    try:
                        result_path.unlink(missing_ok=True)
                    except Exception:
                        pass

            time.sleep(poll_interval)

        logger.warning(
            "[remotion-adapter] Sidecar render timed out after %.1fs clip=%s",
            timeout,
            clip_id,
        )
        return OverlayRenderResult(
            status="sidecar_timeout",
            output_path="",
            scene_plan_path="",
            reason=f"sidecar_timeout_after_{int(timeout)}s",
            backend="remotion",
            metadata={"sidecar_mode": True, "timeout_seconds": timeout},
        )

    def render_remotion_overlay_sidecar(
        self,
        scene_plan_path: str,
        output_path: str,
    ) -> OverlayRenderResult:
        """Render a Remotion overlay via the sidecar filesystem handoff.

        This method:
        1. Checks if the sidecar container is running (heartbeat).
        2. Copies the scene plan to the shared scenes directory.
        3. Writes a render_request.json to the shared requests directory.
        4. Polls for a render_result.json in the shared results directory.
        5. Returns the result.

        If the sidecar is not running, returns status "sidecar_not_running"
        so the caller can fall back to FFmpeg/ASS.
        """
        scene = Path(str(scene_plan_path or ""))
        output = Path(str(output_path or ""))
        clip_id = scene.stem.replace("_scene_plan", "") if scene.exists() else "unknown"

        logger.info(
            "REMOTION_SIDECAR_REQUESTED scene=%s output=%s clip=%s",
            str(scene),
            str(output),
            clip_id,
        )

        # 1. Check if sidecar is running
        if not self._detect_sidecar_running():
            logger.info(
                "[remotion-adapter] Sidecar not running; returning sidecar_not_running"
            )
            return OverlayRenderResult(
                status="sidecar_not_running",
                output_path="",
                scene_plan_path=str(scene),
                reason="sidecar_container_not_detected",
                backend="remotion",
                metadata={"sidecar_mode": True, "render_mode": VIRACLIP_REMOTION_RENDER_MODE},
            )

        # 2. Copy scene plan to shared scenes directory
        scenes_dir = self._sidecar_scenes_dir()
        scenes_dir.mkdir(parents=True, exist_ok=True)
        shared_scene_path = scenes_dir / scene.name

        if scene.exists():
            try:
                shared_scene_path.write_text(scene.read_text(encoding="utf-8"), encoding="utf-8")
                logger.debug(
                    "[remotion-adapter] Scene plan copied to %s",
                    str(shared_scene_path),
                )
            except OSError as exc:
                logger.warning(
                    "[remotion-adapter] Failed to copy scene plan: %s",
                    exc,
                )
                return OverlayRenderResult(
                    status="sidecar_failed",
                    output_path="",
                    scene_plan_path=str(scene),
                    reason=f"scene_plan_copy_failed:{exc}",
                    backend="remotion",
                    metadata={"sidecar_mode": True},
                )
        else:
            logger.warning(
                "[remotion-adapter] Scene plan not found at %s",
                str(scene),
            )
            return OverlayRenderResult(
                status="failed",
                output_path="",
                scene_plan_path=str(scene),
                reason="scene_plan_missing",
                backend="remotion",
                metadata={"sidecar_mode": True},
            )

        # 3. Write render request
        output.parent.mkdir(parents=True, exist_ok=True)
        self._write_sidecar_request(clip_id, str(shared_scene_path), str(output))

        # 4. Poll for result
        result = self._poll_sidecar_result(clip_id)

        # If the result is a timeout, log a fallback warning
        if result.status == "sidecar_timeout":
            logger.warning(
                "REMOTION_SIDECAR_TIMEOUT clip=%s timeout=%ds FALLBACK backend=ffmpeg_ass",
                clip_id,
                VIRACLIP_REMOTION_SIDECAR_TIMEOUT,
            )

        return result

    def _build_scene_plan_data(
        self,
        plan: Any,
        visual_style: Optional[str] = None,
    ) -> Dict[str, Any]:

        """Build the internal scene plan data structure."""
        composition: Dict[str, Any] = {
            "id": getattr(plan, "clip_id", "unknown"),
            "durationInFrames": int(getattr(plan, "duration", 10.0) * getattr(plan, "fps", 30)),
            "fps": getattr(plan, "fps", 30),
            "width": getattr(plan, "resolution", (1080, 1920))[0],
            "height": getattr(plan, "resolution", (1080, 1920))[1],
            "tracks": [],
        }

        # Convert tracks to Remotion sequences
        for track in getattr(plan, "tracks", []):
            track_data = {
                "kind": track.kind.name if hasattr(track.kind, "name") else str(track.kind),
                "enabled": track.enabled,
                "zIndex": track.z_index,
                "items": [],
            }
            for item in getattr(track, "items", []):
                track_data["items"].append({
                    "id": item.item_id,
                    "start": item.time.start,
                    "end": item.time.end,
                    "opacity": item.opacity,
                    "position": list(item.position),
                    "scale": list(item.scale),
                    "metadata": item.metadata,
                })
            composition["tracks"].append(track_data)

        scene_plan: Dict[str, Any] = {
            "schema_version": "1.0",
            "composition": composition,
            "events": [],
            "style_tokens": {
                "visual_style": visual_style or "clear_explanation",
                "font_family": "Inter, sans-serif",
                "primary_color": "#FFFFFF",
                "accent_color": "#FFD700",
                "background_color": "#1A1A2E",
            },
            "quality_warnings": [],
        }

        # Extract events from tracks for the events array
        for track in getattr(plan, "tracks", []):
            for item in getattr(track, "items", []):
                event_type = self._map_track_kind_to_event_type(track.kind)
                if event_type:
                    scene_plan["events"].append({
                        "event_id": item.item_id,
                        "event_type": event_type,
                        "start": item.time.start,
                        "end": item.time.end,
                        "zone": self._infer_zone_from_position(item.position),
                        "metadata": item.metadata,
                    })

        return scene_plan

    def _map_track_kind_to_event_type(self, track_kind: Any) -> Optional[str]:
        """Map a TrackKind to a Remotion event type."""
        kind_name = track_kind.name if hasattr(track_kind, "name") else str(track_kind)
        mapping = {
            "OVERLAY_TEXT": "hook_card",
            "CAPTION_TEXT": "caption_emphasis",
            "SEMANTIC_OBJECT": "semantic_object",
            "BRANDING": "lower_third",
            "BROLL": "broll",
            "TRANSITION": "transition",
        }
        return mapping.get(kind_name)

    def _infer_zone_from_position(
        self,
        position: Tuple[float, float],
    ) -> str:
        """Infer a face-safe zone name from normalised position."""
        x, y = position
        if y < 0.4:
            return "face_zone"
        elif y > 0.7:
            return "caption_zone"
        elif x < 0.4:
            return "object_left_zone"
        elif x > 0.6:
            return "object_right_zone"
        else:
            return "hook_card_zone"

    def render_plan(
        self,
        plan: Any,  # ViraClipTimelinePlan
        **kwargs: Any,
    ) -> RendererCommand:
        """Convert a ViraClipTimelinePlan to a Remotion render command.

        Produces a Remotion composition JSON that can be consumed by
        Remotion's still() or renderMedia() API.
        """
        scene_plan = self._build_scene_plan_data(
            plan,
            visual_style=kwargs.get("visual_style"),
        )

        return RendererCommand(
            renderer="remotion",
            command=[
                "npx", "remotion", "render",
                "--composition-id", scene_plan["composition"]["id"],
                kwargs.get("remotion_entry", str(self.project_dir / "Root.tsx")),
                kwargs.get("output_file", "out/output.mp4"),
            ],
            output_file=kwargs.get("output_file", "out/output.mp4"),
            env={"REMOTION_COMPOSITION_JSON": json.dumps(scene_plan)},
            metadata={"composition": scene_plan["composition"], "scene_plan": scene_plan},
        )

    def to_command(
        self,
        plan: Any,
        **kwargs: Any,
    ) -> List[str]:
        cmd = self.render_plan(plan, **kwargs)
        return cmd.command


# ── Motion Canvas adapter (opt-in) ──────────────────────────────────────────────


class MotionCanvasAdapter(BaseOverlayAdapter):
    """Motion Canvas adapter — produces Motion Canvas scene data.

    Available only when VPI_MOTION_CANVAS_ENABLED=true.
    Consumes ViraClipTimelinePlan and produces Motion Canvas-compatible
    scene descriptors.
    """

    def __init__(self) -> None:
        super().__init__("motion_canvas", enabled=VPI_MOTION_CANVAS_ENABLED)

    def render_plan(
        self,
        plan: Any,  # ViraClipTimelinePlan
        **kwargs: Any,
    ) -> RendererCommand:
        """Convert a ViraClipTimelinePlan to a Motion Canvas render command.

        Produces a Motion Canvas scene descriptor JSON that can be
        consumed by @motion-canvas/2d's Scene component.
        """
        # Build Motion Canvas scene data
        scene: Dict[str, Any] = {
            "id": getattr(plan, "clip_id", "unknown"),
            "duration": getattr(plan, "duration", 10.0),
            "fps": getattr(plan, "fps", 30),
            "resolution": list(getattr(plan, "resolution", (1080, 1920))),
            "nodes": [],
        }

        for track in getattr(plan, "tracks", []):
            for item in getattr(track, "items", []):
                node = {
                    "type": "rect" if track.kind.name in ("CAPTION_BG",) else "text",
                    "position": list(item.position),
                    "scale": list(item.scale),
                    "opacity": item.opacity,
                    "start": item.time.start,
                    "end": item.time.end,
                    "metadata": item.metadata,
                }
                scene["nodes"].append(node)

        return RendererCommand(
            renderer="motion_canvas",
            command=[
                "npx", "motion-canvas", "render",
                "--scene", scene["id"],
                kwargs.get("project_file", "src/project.ts"),
                kwargs.get("output_file", "out/output.mp4"),
            ],
            output_file=kwargs.get("output_file", "out/output.mp4"),
            env={"MOTION_CANVAS_SCENE_JSON": str(scene)},
            metadata={"scene": scene},
        )

    def to_command(
        self,
        plan: Any,
        **kwargs: Any,
    ) -> List[str]:
        cmd = self.render_plan(plan, **kwargs)
        return cmd.command


# ── Adapter registry ────────────────────────────────────────────────────────────


def get_available_adapters() -> Dict[str, BaseOverlayAdapter]:
    """Get all available overlay renderer adapters."""
    adapters: Dict[str, BaseOverlayAdapter] = {
        "ffmpeg_ass": FFmpegASSAdapter(),
    }

    remotion = RemotionAdapter()
    if remotion.is_available():
        adapters["remotion"] = remotion

    motion_canvas = MotionCanvasAdapter()
    if motion_canvas.is_available():
        adapters["motion_canvas"] = motion_canvas

    return adapters


def select_adapter(
    preferred: str = "ffmpeg_ass",
) -> Optional[BaseOverlayAdapter]:
    """Select an adapter by name, falling back to ffmpeg_ass if available."""
    adapters = get_available_adapters()

    if preferred in adapters:
        return adapters[preferred]

    # Fallback to ffmpeg_ass
    if "ffmpeg_ass" in adapters:
        logger.warning(
            "[overlay-adapter] Preferred adapter '%s' not available; "
            "falling back to ffmpeg_ass",
            preferred,
        )
        return adapters["ffmpeg_ass"]

    return None
