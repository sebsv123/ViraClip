"""
Auto-Pilot Service — fully automated end-to-end content pipeline.

One call: source URL (or local path) → ingest → denoise → process
→ jump-cut → publish → track performance.

Returns a workflow ID that can be polled for status.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_WORKFLOW_STORE = Path(
    os.environ.get("AUTOPILOT_STORE_PATH", "/app/data/autopilot_workflows.json")
)


class WorkflowStatus(str, Enum):
    QUEUED = "queued"
    INGESTING = "ingesting"
    PROCESSING = "processing"
    PUBLISHING = "publishing"
    TRACKING = "tracking"
    DONE = "done"
    FAILED = "failed"


@dataclass
class AutopilotConfig:
    """Full configuration for one auto-pilot run."""
    # Source
    source_url: Optional[str] = None
    source_local_path: Optional[str] = None

    # Processing
    niche: str = "auto"
    target_platform: str = "tiktok"
    max_clips: int = 5
    add_subtitles: bool = True
    caption_template: str = "default"

    # Enhancement
    denoise_audio: bool = True
    jump_cut: bool = True
    jump_cut_fillers: bool = True

    # Voiceover (optional)
    add_voiceover: bool = False
    voiceover_text: Optional[str] = None
    voiceover_provider: str = "auto"

    # Publishing
    auto_publish: bool = False
    publish_platforms: List[str] = field(default_factory=lambda: ["tiktok"])
    caption_text: Optional[str] = None
    hashtags: List[str] = field(default_factory=list)
    schedule_iso: Optional[str] = None

    # User
    user_id: Optional[str] = None


@dataclass
class WorkflowStep:
    name: str
    status: str = "pending"    # pending | running | done | skipped | failed
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    output: Optional[Any] = None
    error: Optional[str] = None


@dataclass
class AutopilotWorkflow:
    workflow_id: str
    config: AutopilotConfig
    status: WorkflowStatus = WorkflowStatus.QUEUED
    steps: List[WorkflowStep] = field(default_factory=list)
    task_id: Optional[str] = None
    clips: List[Dict[str, Any]] = field(default_factory=list)
    publish_results: List[Dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "status": self.status,
            "task_id": self.task_id,
            "clips_produced": len(self.clips),
            "publish_results": self.publish_results,
            "steps": [
                {
                    "name": s.name,
                    "status": s.status,
                    "started_at": s.started_at,
                    "finished_at": s.finished_at,
                    "error": s.error,
                }
                for s in self.steps
            ],
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }


# ── In-memory + disk store ────────────────────────────────────────────────────

_active_workflows: Dict[str, AutopilotWorkflow] = {}


def _save_workflow(wf: AutopilotWorkflow) -> None:
    store = {}
    if _WORKFLOW_STORE.exists():
        try:
            store = json.loads(_WORKFLOW_STORE.read_text())
        except Exception:
            pass
    store[wf.workflow_id] = wf.to_dict()
    _WORKFLOW_STORE.parent.mkdir(parents=True, exist_ok=True)
    _WORKFLOW_STORE.write_text(json.dumps(store, indent=2))


def get_workflow(workflow_id: str) -> Optional[Dict[str, Any]]:
    """Return workflow status dict (checks memory first, then disk)."""
    if workflow_id in _active_workflows:
        return _active_workflows[workflow_id].to_dict()
    if _WORKFLOW_STORE.exists():
        try:
            store = json.loads(_WORKFLOW_STORE.read_text())
            return store.get(workflow_id)
        except Exception:
            pass
    return None


def list_workflows(limit: int = 20) -> List[Dict[str, Any]]:
    """List recent workflows from disk store."""
    if not _WORKFLOW_STORE.exists():
        return []
    try:
        store = json.loads(_WORKFLOW_STORE.read_text())
        items = sorted(store.values(), key=lambda x: x.get("created_at", 0), reverse=True)
        return items[:limit]
    except Exception:
        return []


# ── Workflow runner ───────────────────────────────────────────────────────────

def _step(wf: AutopilotWorkflow, name: str) -> WorkflowStep:
    s = WorkflowStep(name=name)
    wf.steps.append(s)
    return s


async def _run_workflow(wf: AutopilotWorkflow) -> None:
    """Execute all pipeline stages for a workflow."""
    try:
        # ── Stage 1: Ingest ──────────────────────────────────────────────────
        local_path: Optional[str] = wf.config.source_local_path
        if wf.config.source_url and not local_path:
            s = _step(wf, "ingest")
            s.status = "running"; s.started_at = time.time()
            wf.status = WorkflowStatus.INGESTING
            _save_workflow(wf)
            try:
                from .video_ingestion_service import ingest_url
                result = await ingest_url(wf.config.source_url)
                if not result.success:
                    raise RuntimeError(f"Ingest failed: {result.error}")
                local_path = result.local_path
                s.status = "done"; s.output = {"local_path": local_path}
            except Exception as exc:
                s.status = "failed"; s.error = str(exc)
                wf.status = WorkflowStatus.FAILED; wf.error = str(exc)
                _save_workflow(wf); return
            finally:
                s.finished_at = time.time()

        if not local_path or not Path(local_path).exists():
            wf.status = WorkflowStatus.FAILED
            wf.error = "No valid source video"
            _save_workflow(wf)
            return

        # ── Stage 2: Create processing task ──────────────────────────────────
        wf.status = WorkflowStatus.PROCESSING
        s = _step(wf, "create_task")
        s.status = "running"; s.started_at = time.time()
        _save_workflow(wf)
        try:
            from ..workers.job_queue import JobQueue
            job_queue = JobQueue()
            task_config = {
                "output_dir": str(Path(local_path).parent / "clips"),
                "target_platform": wf.config.target_platform,
                "add_subtitles": wf.config.add_subtitles,
                "caption_template": wf.config.caption_template,
                "denoise_audio": wf.config.denoise_audio,
                "jump_cut": wf.config.jump_cut,
                "jump_cut_fillers": wf.config.jump_cut_fillers,
                "max_clips": wf.config.max_clips,
                "user_id": wf.config.user_id or "",
                "autopilot_workflow_id": wf.workflow_id,
            }
            task_id = await job_queue.enqueue(
                video_path=local_path,
                config=task_config,
            )
            wf.task_id = task_id
            s.status = "done"; s.output = {"task_id": task_id}
        except Exception as exc:
            s.status = "failed"; s.error = str(exc)
            wf.status = WorkflowStatus.FAILED; wf.error = str(exc)
            _save_workflow(wf); return
        finally:
            s.finished_at = time.time()

        # ── Stage 3: Wait for task completion (poll) ──────────────────────────
        s = _step(wf, "wait_for_clips")
        s.status = "running"; s.started_at = time.time()
        _save_workflow(wf)
        try:
            from ..workers.job_queue import JobQueue
            jq = JobQueue()
            for _ in range(720):   # 720 × 5s = 60 min max
                await asyncio.sleep(5)
                status = await jq.get_status(wf.task_id)
                if status and status.get("status") in ("done", "complete", "completed"):
                    wf.clips = status.get("clips", [])
                    break
                if status and status.get("status") == "error":
                    raise RuntimeError(f"Task failed: {status.get('error')}")
            s.status = "done"; s.output = {"clips_count": len(wf.clips)}
        except Exception as exc:
            s.status = "failed"; s.error = str(exc)
            # Non-fatal: continue to try publishing any clips we have
            logger.warning("[autopilot] Wait failed: %s", exc)
        finally:
            s.finished_at = time.time()

        # ── Stage 4: Optional voiceover ───────────────────────────────────────
        if wf.config.add_voiceover and wf.config.voiceover_text:
            s = _step(wf, "voiceover")
            s.status = "running"; s.started_at = time.time()
            _save_workflow(wf)
            try:
                from .voiceover_service import add_voiceover_to_clip
                for clip in wf.clips:
                    clip_path = clip.get("path", "")
                    if not Path(clip_path).exists():
                        continue
                    out = str(Path(clip_path).with_name(f"vo_{Path(clip_path).name}"))
                    vo_result = await add_voiceover_to_clip(
                        clip_path, wf.config.voiceover_text, out,
                        provider=wf.config.voiceover_provider,
                    )
                    if vo_result.mixed_video_path:
                        clip["path"] = vo_result.mixed_video_path
                        clip["voiceover_added"] = True
                s.status = "done"
            except Exception as exc:
                s.status = "skipped"; s.error = str(exc)
            finally:
                s.finished_at = time.time()

        # ── Stage 5: Auto-publish ─────────────────────────────────────────────
        if wf.config.auto_publish and wf.clips:
            wf.status = WorkflowStatus.PUBLISHING
            s = _step(wf, "publish")
            s.status = "running"; s.started_at = time.time()
            _save_workflow(wf)
            try:
                from .social_publisher import publish_to_all
                for clip in wf.clips[:3]:   # publish top 3 clips
                    clip_path = clip.get("path", "")
                    if not Path(clip_path).exists():
                        continue
                    caption = wf.config.caption_text or clip.get("suggested_caption", "")
                    results = await publish_to_all(
                        video_path=clip_path,
                        caption=caption,
                        hashtags=wf.config.hashtags,
                        platforms=wf.config.publish_platforms,
                        schedule_iso=wf.config.schedule_iso,
                    )
                    for r in results:
                        wf.publish_results.append({
                            "clip_path": clip_path,
                            "platform": r.platform,
                            "status": r.status,
                            "post_id": r.post_id,
                            "post_url": r.post_url,
                            "error": r.error,
                        })
                s.status = "done"
            except Exception as exc:
                s.status = "failed"; s.error = str(exc)
                logger.warning("[autopilot] Publish failed: %s", exc)
            finally:
                s.finished_at = time.time()

        # ── Stage 6: Register for performance tracking ────────────────────────
        wf.status = WorkflowStatus.TRACKING
        s = _step(wf, "register_tracking")
        s.status = "running"; s.started_at = time.time()
        _save_workflow(wf)
        try:
            # Record skeleton performance events (views=0) for tracking
            from .performance_webhook_service import PerformanceEvent, record_performance_event
            for pub in wf.publish_results:
                if pub.get("post_id"):
                    event = PerformanceEvent(
                        clip_id=pub["post_id"],
                        platform=pub["platform"],
                    )
                    record_performance_event(
                        event,
                        caption_template=wf.config.caption_template,
                    )
            s.status = "done"
        except Exception as exc:
            s.status = "skipped"; s.error = str(exc)
        finally:
            s.finished_at = time.time()

        wf.status = WorkflowStatus.DONE
        wf.finished_at = time.time()
        logger.info("[autopilot] Workflow %s DONE — %d clips, %d published",
                    wf.workflow_id, len(wf.clips), len(wf.publish_results))

    except Exception as exc:
        wf.status = WorkflowStatus.FAILED
        wf.error = str(exc)
        logger.exception("[autopilot] Workflow %s FAILED", wf.workflow_id)
    finally:
        _save_workflow(wf)


async def start_autopilot(config: AutopilotConfig) -> AutopilotWorkflow:
    """
    Create and start an auto-pilot workflow.

    The workflow runs asynchronously — call get_workflow(workflow_id) to poll.
    """
    wf = AutopilotWorkflow(
        workflow_id=str(uuid.uuid4()),
        config=config,
    )
    _active_workflows[wf.workflow_id] = wf
    _save_workflow(wf)
    # Fire and forget — caller can poll get_workflow()
    asyncio.create_task(_run_workflow(wf))
    logger.info("[autopilot] Started workflow %s", wf.workflow_id)
    return wf
