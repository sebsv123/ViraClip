"""
Subtitle Quality Guard — validate and auto-fix ASS/SRT subtitle files.

Checks:
  1. Reading speed  — flag segments > 3 words/sec (TikTok retention killer)
  2. Natural line breaks — re-wrap at clause boundaries (comma/conjunction)
  3. Profanity filter  — optional censorship pass for TikTok compliance
  4. Emoji insertion   — inject relevant emojis at emotion keywords

Returns a SubtitleQAReport with issues + an optionally auto-fixed subtitle string.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ── Profanity list (common TikTok strike-words) ───────────────────────────────
# Extend via env var PROFANITY_LIST (comma-separated)
import os
_DEFAULT_PROFANITY = {
    "fuck", "shit", "bitch", "asshole", "cunt", "nigger", "nigga", "faggot",
    "retard", "whore", "slut",
}
_extra = os.getenv("PROFANITY_LIST", "")
PROFANITY_WORDS = _DEFAULT_PROFANITY | {w.strip().lower() for w in _extra.split(",") if w.strip()}

# ── Emoji keyword map ─────────────────────────────────────────────────────────
EMOJI_MAP: dict[str, str] = {
    "fire": "🔥", "amazing": "🔥", "incredible": "🔥",
    "money": "💰", "rich": "💰", "income": "💰", "profit": "💰",
    "love": "❤️", "heart": "❤️",
    "win": "🏆", "winner": "🏆", "champion": "🏆",
    "fast": "⚡", "speed": "⚡", "quick": "⚡",
    "think": "🤔", "question": "❓", "why": "❓",
    "secret": "🤫", "hack": "💡", "tip": "💡",
    "laugh": "😂", "funny": "😂",
    "sad": "😢", "cry": "😭",
    "shocked": "😱", "surprise": "😲", "crazy": "😱",
    "grow": "📈", "growth": "📈", "success": "📈",
    "workout": "💪", "fitness": "💪", "strong": "💪",
}

MAX_WPS = 3.0          # words per second — TikTok safe threshold
MAX_CHARS_PER_LINE = 42


@dataclass
class SubtitleIssue:
    index: int          # segment index (0-based)
    kind: str           # reading_speed | line_length | profanity | suggestion
    message: str
    severity: str = "warning"   # warning | error | info


@dataclass
class SubtitleQAReport:
    total_segments: int = 0
    issues: list[SubtitleIssue] = field(default_factory=list)
    fixed_content: str = ""
    reading_speed_violations: int = 0
    profanity_found: int = 0
    emojis_injected: int = 0

    @property
    def passed(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    def summary(self) -> str:
        counts = {}
        for i in self.issues:
            counts[i.kind] = counts.get(i.kind, 0) + 1
        parts = [f"Segments: {self.total_segments}"]
        for k, v in counts.items():
            parts.append(f"{k}: {v}")
        return " | ".join(parts)


# ── ASS parsing helpers ───────────────────────────────────────────────────────

_ASS_TIME = re.compile(r"(\d+):(\d{2}):(\d{2})\.(\d{2})")
_ASS_LINE = re.compile(
    r"^(Dialogue:\s*\d+,)"
    r"(\d+:\d{2}:\d{2}\.\d{2}),"
    r"(\d+:\d{2}:\d{2}\.\d{2}),"
    r"([^,]*),([^,]*),([^,]*),([^,]*),([^,]*),([^,]*),"
    r"(.*)$"
)


def _ass_time_to_seconds(t: str) -> float:
    m = _ASS_TIME.match(t)
    if not m:
        return 0.0
    h, mn, s, cs = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    return h * 3600 + mn * 60 + s + cs / 100


def _strip_ass_tags(text: str) -> str:
    return re.sub(r"\{[^}]*\}", "", text).strip()


def _count_words(text: str) -> int:
    return len(text.split())


# ── Core QA functions ─────────────────────────────────────────────────────────

def check_reading_speed(
    text: str, start: float, end: float, idx: int
) -> Optional[SubtitleIssue]:
    duration = max(end - start, 0.1)
    wps = _count_words(text) / duration
    if wps > MAX_WPS:
        return SubtitleIssue(
            index=idx,
            kind="reading_speed",
            message=f"Too fast: {wps:.1f} wps (limit {MAX_WPS}). Duration {duration:.1f}s, {_count_words(text)} words.",
            severity="warning",
        )
    return None


def fix_line_breaks(text: str) -> str:
    """Re-wrap text at natural clause boundaries for readability."""
    clean = _strip_ass_tags(text)
    if len(clean) <= MAX_CHARS_PER_LINE:
        return text

    # Try breaking at conjunction / comma near the middle
    mid = len(clean) // 2
    best_break = -1
    for sep in [", ", " but ", " and ", " or ", " so ", " because ", " that ", " - "]:
        pos = clean.find(sep, mid - 15)
        if mid - 15 <= pos <= mid + 20:
            best_break = pos + len(sep) - 1
            break

    if best_break > 0:
        fixed = clean[:best_break] + "\\N" + clean[best_break:]
        return re.sub(r"\\N+", "\\N", fixed)
    return text


def apply_profanity_filter(text: str, censor_char: str = "*") -> tuple[str, int]:
    """Replace profanity words with censored version. Returns (new_text, count)."""
    clean = _strip_ass_tags(text)
    count = 0
    words = clean.split()
    for i, word in enumerate(words):
        base = re.sub(r"[^a-z]", "", word.lower())
        if base in PROFANITY_WORDS:
            words[i] = censor_char * len(word)
            count += 1
    return " ".join(words), count


def inject_emojis(text: str) -> tuple[str, int]:
    """Append relevant emojis at the end of the subtitle line."""
    clean = _strip_ass_tags(text).lower()
    injected = set()
    for kw, emoji in EMOJI_MAP.items():
        if kw in clean and emoji not in injected:
            injected.add(emoji)
            if len(injected) >= 2:
                break
    if injected:
        return text.rstrip() + " " + " ".join(sorted(injected)), len(injected)
    return text, 0


# ── Main entry ────────────────────────────────────────────────────────────────

def run_subtitle_qa(
    subtitle_content: str,
    apply_fixes: bool = True,
    censor_profanity: bool = True,
    add_emojis: bool = True,
) -> SubtitleQAReport:
    """
    Run full QA pipeline on an ASS subtitle string.
    Returns SubtitleQAReport with optional fixed_content.
    """
    report = SubtitleQAReport()
    lines = subtitle_content.splitlines()
    fixed_lines = []
    idx = 0

    for line in lines:
        m = _ASS_LINE.match(line)
        if not m:
            fixed_lines.append(line)
            continue

        prefix = m.group(1)
        t_start = m.group(2)
        t_end = m.group(3)
        style_etc = ",".join([m.group(i) for i in range(4, 10)])
        raw_text = m.group(10)

        start_s = _ass_time_to_seconds(t_start)
        end_s = _ass_time_to_seconds(t_end)
        display_text = _strip_ass_tags(raw_text)
        report.total_segments += 1

        working_text = raw_text

        # 1. Reading speed
        issue = check_reading_speed(display_text, start_s, end_s, idx)
        if issue:
            report.issues.append(issue)
            report.reading_speed_violations += 1

        # 2. Line breaks
        if apply_fixes and len(display_text) > MAX_CHARS_PER_LINE:
            working_text = fix_line_breaks(working_text)

        # 3. Profanity
        if censor_profanity:
            censored, cnt = apply_profanity_filter(working_text)
            if cnt:
                report.profanity_found += cnt
                report.issues.append(SubtitleIssue(
                    index=idx, kind="profanity",
                    message=f"{cnt} word(s) censored for platform compliance.",
                    severity="info",
                ))
                if apply_fixes:
                    working_text = censored

        # 4. Emojis
        if add_emojis:
            emo_text, cnt = inject_emojis(working_text)
            if cnt:
                report.emojis_injected += cnt
                if apply_fixes:
                    working_text = emo_text

        fixed_line = f"{prefix}{t_start},{t_end},{style_etc},{working_text}"
        fixed_lines.append(fixed_line)
        idx += 1

    report.fixed_content = "\n".join(fixed_lines)
    return report


def run_subtitle_qa_on_file(
    path: str,
    apply_fixes: bool = True,
    censor_profanity: bool = True,
    add_emojis: bool = True,
    overwrite: bool = False,
) -> SubtitleQAReport:
    """Run QA on a subtitle file. If overwrite=True, writes fixed version back."""
    import pathlib
    p = pathlib.Path(path)
    content = p.read_text(encoding="utf-8", errors="replace")
    report = run_subtitle_qa(content, apply_fixes, censor_profanity, add_emojis)
    if apply_fixes and overwrite and report.fixed_content:
        p.write_text(report.fixed_content, encoding="utf-8")
    return report
