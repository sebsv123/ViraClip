"""
ErrorDiagnostician — analyzes any error and returns a structured diagnosis.

Uses Redis knowledge base to cache known fixes and avoid re-analysis.
"""
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("diagnostician")

REDIS_URL = os.getenv("REDIS_URL", f"redis://{os.getenv('REDIS_HOST', 'redis')}:{os.getenv('REDIS_PORT', '6379')}")


@dataclass
class ErrorDiagnosis:
    error_type: str          # LLM_JSON_WRAPPER | ATTRIBUTE_ERROR | TIMEOUT | PYDANTIC_RETRIES | UNKNOWN
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    fix_description: str = ""
    fix_code: Optional[str] = None   # old_code → new_code
    is_known: bool = False
    can_fix_in_runtime: bool = False


class ErrorDiagnostician:
    """Analyzes errors and returns structured diagnoses."""

    @staticmethod
    def _error_hash(error: str) -> str:
        return hashlib.md5(error.encode()).hexdigest()[:12]

    @staticmethod
    async def _get_redis():
        import redis.asyncio as aioredis
        return await aioredis.from_url(REDIS_URL, decode_responses=True)

    @classmethod
    async def diagnose(cls, error: str, traceback: str) -> ErrorDiagnosis:
        """Analyze error + traceback and return a structured diagnosis."""
        combined = f"{error} {traceback}"

        # Check knowledge base first
        known = await cls._check_knowledge_base(error)
        if known:
            return known

        # Rule 1: LLM JSON wrapper
        if "function=final_result" in combined:
            return cls._diagnose_llm_wrapper(traceback)

        # Rule 2: _SegmentsWrapper attribute error
        if "_SegmentsWrapper" in combined and "has no attribute" in combined:
            return cls._diagnose_attribute_error(traceback)

        # Rule 3: pydantic retries
        if "Exceeded maximum retries" in combined or "output validation" in combined:
            return cls._diagnose_pydantic_retries()

        # Rule 4: timeout
        if "QUEUED_TIMEOUT" in combined or ("queued" in combined.lower() and "timeout" in combined.lower()):
            return ErrorDiagnosis(
                error_type="TIMEOUT",
                fix_description="Task timed out in queue — re-enqueue",
                can_fix_in_runtime=True,
            )

        return ErrorDiagnosis(error_type="UNKNOWN", fix_description="Unknown error — re-enqueue", can_fix_in_runtime=True)

    @classmethod
    def _diagnose_llm_wrapper(cls, traceback: str) -> ErrorDiagnosis:
        file_path, line = cls._extract_file_line(traceback)
        fix_code = (
            "# BEFORE:\n"
            "result = await agent.run(user_prompt)\n"
            "analysis = getattr(result, 'output', None) or getattr(result, 'data', None)\n\n"
            "# AFTER:\n"
            "result = await agent.run(user_prompt)\n"
            "import re as _re\n"
            "_raw = getattr(result, 'output', None) or getattr(result, 'data', None)\n"
            "if isinstance(_raw, str):\n"
            "    _m = _re.search(r'<function[^>]*>(.*?)</function>', _raw, _re.DOTALL)\n"
            "    if _m:\n"
            "        _raw = _m.group(1).strip()\n"
            "    _m = _re.search(r'```(?:json)?\\s*(.*?)\\s*```', _raw, _re.DOTALL)\n"
            "    if _m:\n"
            "        _raw = _m.group(1).strip()\n"
            "analysis = _raw"
        )
        return ErrorDiagnosis(
            error_type="LLM_JSON_WRAPPER",
            file_path=file_path or "src/ai.py",
            line_number=line,
            fix_description="LLM returned XML/JSON wrapper — add strip_function_wrapper before pydantic-ai validation",
            fix_code=fix_code,
            can_fix_in_runtime=False,
        )

    @classmethod
    def _diagnose_attribute_error(cls, traceback: str) -> ErrorDiagnosis:
        file_path, line = cls._extract_file_line(traceback)
        m = re.search(r"has no attribute '(\w+)'", traceback)
        attr = m.group(1) if m else "?"
        fix_code = (
            f"# BEFORE:\n"
            f"obj.{attr}\n\n"
            f"# AFTER:\n"
            f"getattr(obj, '{attr}', None)"
        )
        return ErrorDiagnosis(
            error_type="ATTRIBUTE_ERROR",
            file_path=file_path,
            line_number=line,
            fix_description=f"Replace .{attr} with getattr() fallback",
            fix_code=fix_code,
            can_fix_in_runtime=False,
        )

    @classmethod
    def _diagnose_pydantic_retries(cls) -> ErrorDiagnosis:
        return ErrorDiagnosis(
            error_type="PYDANTIC_RETRIES",
            file_path="src/ai.py",
            fix_description="Increase max_result_retries from 1 to 3",
            fix_code="# BEFORE:\nmax_result_retries = 1\n\n# AFTER:\nmax_result_retries = 3",
            can_fix_in_runtime=False,
        )

    @staticmethod
    def _extract_file_line(traceback: str) -> tuple[Optional[str], Optional[int]]:
        for m in re.finditer(r'File "([^"]+)", line (\d+)', traceback):
            fp = m.group(1)
            if fp.startswith("/app/src/"):
                return fp, int(m.group(2))
        return None, None

    @classmethod
    async def _check_knowledge_base(cls, error: str) -> Optional[ErrorDiagnosis]:
        """Check if a known fix exists for this error."""
        try:
            r = await cls._get_redis()
            key = f"diagnosis:{cls._error_hash(error)}"
            raw = await r.get(key)
            await r.aclose()
            if raw:
                data = json.loads(raw)
                if data.get("success_count", 0) > data.get("fail_count", 0):
                    return ErrorDiagnosis(
                        error_type=data["error_type"],
                        file_path=data.get("file_path"),
                        line_number=data.get("line_number"),
                        fix_description=data.get("fix_description", ""),
                        fix_code=data.get("fix_code"),
                        is_known=True,
                        can_fix_in_runtime=data.get("can_fix_in_runtime", False),
                    )
        except Exception:
            pass
        return None

    @classmethod
    async def save_to_knowledge_base(cls, diagnosis: ErrorDiagnosis, success: bool) -> None:
        """Save diagnosis result to Redis knowledge base."""
        try:
            r = await cls._get_redis()
            key = f"diagnosis:{cls._error_hash(diagnosis.fix_description)}"
            existing = await r.get(key)
            data = json.loads(existing) if existing else {"success_count": 0, "fail_count": 0}
            if success:
                data["success_count"] += 1
            else:
                data["fail_count"] += 1
            data.update({
                "error_type": diagnosis.error_type,
                "file_path": diagnosis.file_path,
                "line_number": diagnosis.line_number,
                "fix_description": diagnosis.fix_description,
                "fix_code": diagnosis.fix_code,
                "can_fix_in_runtime": diagnosis.can_fix_in_runtime,
                "last_seen": datetime.now(timezone.utc).isoformat(),
            })
            await r.setex(key, 86400 * 7, json.dumps(data))
            await r.aclose()
        except Exception as exc:
            logger.debug("Knowledge base save failed: %s", exc)
