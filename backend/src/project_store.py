"""
Persistent project state management with input/working/output structure.
Inspired by schibsted/videofy_minimal - solves ViraClip's render restart issue.

Each task has:
  projects/<task_id>/
    input/          ← original downloaded video
    working/
      transcript.json    ← Whisper output
      segments.json      ← ai.py output (viral analysis)
      timeline.json      ← ClipTimeline (schemas_v2)
      analysis/
        frames/           ← extracted frames
        descriptions.json ← Vision AI descriptions
        placements.json   ← frame → segment mapping
    output/
      clip_01.mp4
      clip_02.mp4
"""

import json
from pathlib import Path
from datetime import datetime, timezone

class ProjectStore:
    """Manages persistent state for each ViraClip job."""
    
    def __init__(self, base_dir: str = "/app/projects"):
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)

    def project_path(self, task_id: str) -> Path:
        """Get root path for a task project."""
        return self.base / task_id

    def input_path(self, task_id: str) -> Path:
        """Get input directory (original video)."""
        p = self.project_path(task_id) / "input"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def working_path(self, task_id: str) -> Path:
        """Get working directory (intermediate files)."""
        p = self.project_path(task_id) / "working"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def output_path(self, task_id: str) -> Path:
        """Get output directory (final clips)."""
        p = self.project_path(task_id) / "output"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def analysis_path(self, task_id: str) -> Path:
        """Get analysis directory (frames, descriptions, placements)."""
        p = self.working_path(task_id) / "analysis"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def frames_path(self, task_id: str) -> Path:
        """Get frames directory."""
        p = self.analysis_path(task_id) / "frames"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def save_json(
        self,
        task_id: str,
        filename: str,
        data: dict | list,
        folder: str = "working"
    ) -> None:
        """Save JSON data to project folder."""
        if folder == "analysis":
            target = self.analysis_path(task_id) / filename
        else:
            target = self.project_path(task_id) / folder / filename
        
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8"
        )

    def load_json(
        self,
        task_id: str,
        filename: str,
        folder: str = "working"
    ) -> dict | list | None:
        """Load JSON data from project folder."""
        if folder == "analysis":
            target = self.analysis_path(task_id) / filename
        else:
            target = self.project_path(task_id) / folder / filename
        
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            return None

    def is_step_done(self, task_id: str, step: str) -> bool:
        """
        Check if a pipeline step is already complete.
        Allows skipping completed steps on restart.
        
        step: "transcript" | "segments" | "analysis" | "timeline" | "render"
        """
        markers = {
            "transcript": "working/transcript.json",
            "segments":   "working/segments.json",
            "analysis":   "working/analysis/placements.json",
            "timeline":   "working/timeline.json",
            "render":     "output/clip_01.mp4",
        }
        path = self.project_path(task_id) / markers.get(step, "")
        return path.exists() and path.stat().st_size > 0

    def get_step_timestamp(self, task_id: str, step: str) -> datetime | None:
        """Get when a step was last completed."""
        markers = {
            "transcript": "working/transcript.json",
            "segments":   "working/segments.json",
            "analysis":   "working/analysis/placements.json",
            "timeline":   "working/timeline.json",
            "render":     "output/clip_01.mp4",
        }
        path = self.project_path(task_id) / markers.get(step, "")
        if path.exists():
            return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return None

    def cleanup_working(self, task_id: str) -> None:
        """Clean up working directory (keep input and output)."""
        import shutil
        working = self.working_path(task_id)
        if working.exists():
            shutil.rmtree(working, ignore_errors=True)

    def cleanup_project(self, task_id: str) -> None:
        """Delete entire project directory."""
        import shutil
        project = self.project_path(task_id)
        if project.exists():
            shutil.rmtree(project, ignore_errors=True)
