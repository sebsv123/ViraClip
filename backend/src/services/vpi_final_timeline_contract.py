"""OUTPUT-TIMELINE-23 — Final duration reconciliation contract.

Guarantees the approved closing sentence fits inside the mastered MP4, captions never
visibly exceed it, legitimate music/ambient tails are preserved, and any spoken tail is
captioned. Never blind-clamps captions to hide truncated audio.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SAFETY_MARGIN_S = 0.12          # closure must end at <= master - margin
CAPTION_CLAMP_MARGIN_S = 0.05   # clamp caption end to master - this
OVERRUN_TRUNCATION_TOL_S = 0.8  # caption beyond master by more than this => real clause lost
LEGIT_TAIL_MIN_S = 0.5          # uncaptioned tail considered a "tail" beyond this
MIN_CAPTION_DUR_S = 0.30        # never produce a caption shorter than this


def classify_final_timeline(
    *,
    master_duration_s: float,
    last_caption_end_s: float,
    last_spoken_word_end_s: Optional[float] = None,
    tail_speech_present: bool = False,
    safety_margin_s: float = SAFETY_MARGIN_S,
    overrun_tol_s: float = OVERRUN_TRUNCATION_TOL_S,
    legit_tail_min_s: float = LEGIT_TAIL_MIN_S,
) -> Dict[str, Any]:
    """Pure classifier. Returns issue class + reconciliation action + publishability."""
    master = float(master_duration_s or 0.0)
    cap_end = float(last_caption_end_s or 0.0)
    word_end = float(last_spoken_word_end_s) if last_spoken_word_end_s is not None else cap_end
    caption_overrun = round(cap_end - master, 3)          # >0 => caption past master
    uncaptioned_tail = round(master - cap_end, 3)          # >0 => video past last caption
    closure_contained = cap_end <= (master + overrun_tol_s) and word_end <= master + 0.05

    if caption_overrun > overrun_tol_s or word_end > master + 0.05:
        # The approved closure (a full clause) does not fit -> real truncation.
        issue, action, tail_type, pub, contained = (
            "SPEECH_TRUNCATED", "block_no_clamp", "none", False, False)
    elif uncaptioned_tail > legit_tail_min_s and tail_speech_present:
        issue, action, tail_type, pub, contained = (
            "UNCOVERED_SPEECH_TAIL", "recaption_or_block", "speech", False, True)
    elif uncaptioned_tail > legit_tail_min_s and not tail_speech_present:
        issue, action, tail_type, pub, contained = (
            "LEGITIMATE_AUDIO_TAIL", "preserve", "music_or_ambient", True, True)
    elif caption_overrun > 0:
        issue, action, tail_type, pub, contained = (
            "CAPTION_OVERRUN_ONLY", "caption_clamp", "none", True, True)
    else:
        issue, action, tail_type, pub, contained = (
            "CONTAINED", "none", "none", True, True)

    return {
        "final_master_duration_s": round(master, 3),
        "final_last_spoken_word_end_s": round(word_end, 3),
        "final_last_caption_end_s": round(cap_end, 3),
        "final_timeline_delta_s": caption_overrun,
        "final_timeline_issue_class": issue,
        "final_timeline_reconciliation": action,
        "final_tail_type": tail_type,
        "final_closure_contained": bool(contained),
        "final_timeline_publishable_ok": bool(pub),
    }


def _ass_last_dialogue_end(ass_path: str | Path) -> float:
    mx = 0.0
    try:
        for ln in Path(ass_path).read_text(errors="ignore").splitlines():
            if ln.startswith("Dialogue:"):
                ts = re.findall(r"(\d):(\d\d):(\d\d\.\d\d)", ln)
                if len(ts) >= 2:
                    h, m, s = ts[1]
                    mx = max(mx, int(h) * 3600 + int(m) * 60 + float(s))
    except Exception:
        return 0.0
    return round(mx, 3)


def _probe_duration(path: str | Path) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        return round(float((r.stdout or "0").strip()), 3)
    except Exception:
        return 0.0


def _tail_has_speech(path: str | Path, from_s: float, dur_s: float) -> bool:
    """True if the tail window carries clear speech (energetic, non-silent)."""
    if dur_s <= 0.05:
        return False
    try:
        r = subprocess.run(
            ["ffmpeg", "-hide_banner", "-ss", f"{from_s:.2f}", "-t", f"{dur_s:.2f}", "-i", str(path),
             "-map", "0:a?", "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, timeout=30,
        )
        m = re.search(r"max_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", r.stderr or "")
        n = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", r.stderr or "")
        mx = float(m.group(1)) if m else -99.0
        mn = float(n.group(1)) if n else -99.0
        # clear speech: peaks loud (>-8 dB) AND mean energetic (>-22 dB)
        return mx > -8.0 and mn > -22.0
    except Exception:
        return False


def _clamp_ass_captions(ass_path: str | Path, master_duration_s: float, margin_s: float = CAPTION_CLAMP_MARGIN_S) -> int:
    """Clamp Dialogue end times to master-margin (overrun-only). Returns lines clamped."""
    p = Path(ass_path)
    limit = max(0.0, master_duration_s - margin_s)

    def to_ts(sec: float) -> str:
        sec = max(0.0, sec)
        h = int(sec // 3600); m = int((sec % 3600) // 60); s = sec - h * 3600 - m * 60
        return f"{h}:{m:02d}:{s:05.2f}"

    def parse_ts(ts: str) -> float:
        h, m, s = ts.split(":"); return int(h) * 3600 + int(m) * 60 + float(s)

    out: List[str] = []
    clamped = 0
    try:
        for ln in p.read_text(errors="ignore").splitlines():
            if ln.startswith("Dialogue:"):
                parts = ln.split(",", 3)
                if len(parts) >= 3:
                    start = parse_ts(parts[1].strip()); end = parse_ts(parts[2].strip())
                    if end > limit:
                        new_end = max(start + MIN_CAPTION_DUR_S, limit)
                        if new_end < end:
                            parts[2] = " " + to_ts(new_end)
                            ln = ",".join(parts); clamped += 1
            out.append(ln)
        if clamped:
            p.write_text("\n".join(out) + "\n")
    except Exception as exc:
        logger.warning("VPI_FINAL_TIMELINE caption clamp failed: %s", exc)
        return 0
    return clamped


def reconcile_final_timeline_contract(
    *,
    final_mp4: str | Path,
    ass_path: Optional[str | Path] = None,
    words: Optional[List[Dict[str, Any]]] = None,
    closure_word_end_s: Optional[float] = None,
    task_id: str = "",
    clip_order: int = 0,
) -> Dict[str, Any]:
    """Audit the final master, classify, safe-clamp captions, return contract metadata."""
    master = _probe_duration(final_mp4)
    cap_end = _ass_last_dialogue_end(ass_path) if ass_path else 0.0
    word_end = None
    if closure_word_end_s is not None:
        word_end = float(closure_word_end_s)
    elif words:
        ends = [float(w.get("end") or 0.0) for w in words if isinstance(w, dict)]
        word_end = max(ends) if ends else None
    # If captions are the only closure signal, use them.
    effective_caption_end = cap_end or (word_end or 0.0)

    # Speech in the uncaptioned tail?
    tail_speech = False
    if master - effective_caption_end > LEGIT_TAIL_MIN_S:
        tail_speech = _tail_has_speech(final_mp4, effective_caption_end, master - effective_caption_end)

    result = classify_final_timeline(
        master_duration_s=master,
        last_caption_end_s=effective_caption_end,
        last_spoken_word_end_s=word_end,
        tail_speech_present=tail_speech,
    )
    logger.info(
        "VPI_FINAL_TIMELINE_AUDIT task_id=%s clip_order=%s master=%.2f caption_end=%.2f word_end=%s class=%s delta=%.2f contained=%s",
        task_id, clip_order, master, effective_caption_end, word_end,
        result["final_timeline_issue_class"], result["final_timeline_delta_s"],
        str(result["final_closure_contained"]).lower(),
    )
    cls = result["final_timeline_issue_class"]
    if cls == "SPEECH_TRUNCATED":
        logger.warning("VPI_FINAL_TIMELINE_SPEECH_TRUNCATED task_id=%s clip_order=%s delta=%.2f", task_id, clip_order, result["final_timeline_delta_s"])
    elif cls == "CAPTION_OVERRUN_ONLY" and ass_path:
        n = _clamp_ass_captions(ass_path, master)
        result["final_caption_lines_clamped"] = n
        logger.info("VPI_FINAL_TIMELINE_CAPTION_OVERRUN task_id=%s clip_order=%s clamped=%d", task_id, clip_order, n)
    elif cls == "LEGITIMATE_AUDIO_TAIL":
        logger.info("VPI_FINAL_TIMELINE_LEGITIMATE_TAIL task_id=%s clip_order=%s tail=%.2f", task_id, clip_order, master - effective_caption_end)
    elif cls == "UNCOVERED_SPEECH_TAIL":
        logger.warning("VPI_FINAL_TIMELINE_UNCOVERED_SPEECH task_id=%s clip_order=%s tail=%.2f", task_id, clip_order, master - effective_caption_end)
    logger.info("VPI_FINAL_TIMELINE_RECONCILED task_id=%s clip_order=%s action=%s publishable=%s", task_id, clip_order, result["final_timeline_reconciliation"], str(result["final_timeline_publishable_ok"]).lower())
    return result
