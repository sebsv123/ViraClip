"""
Central registry of all LLM prompt versions.
Zero dependencies — safe to import anywhere.
"""
import logging

PROMPT_VERSIONS = {
    "viral_scorer":           "v1.0",
    "script_writer":          "v1.0",
    "yt_metadata":            "v1.0",
    "transcript_analysis":    "v1.0",
    "creative_director":      "v1.0",
    "hook_rewriter":          "v1.0",
    "edit_decision":          "v1.0",
    "broll_director":         "v1.0",
    "quality_judge":          "v1.0",
    "audio_mix":              "v1.0",
    "subagent_pipeline":      "v1.0",
    "elite_trend_researcher": "v1.0",
    "elite_community_mgr":    "v1.0",
}


def get_prompt_version(name: str) -> str:
    return PROMPT_VERSIONS.get(name, "unknown")


def log_prompt_usage(name: str, logger: logging.Logger) -> None:
    version = get_prompt_version(name)
    logger.debug("[Prompt] %s @ %s", name, version)
