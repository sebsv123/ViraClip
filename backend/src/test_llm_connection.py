#!/usr/bin/env python3
"""
ViraClip LLM Connection Test — Groq edition
Mounted at /app/src/ inside the worker container.

Run:
  docker-compose exec worker python src/test_llm_connection.py
"""

import os
import sys
import asyncio
import traceback
from pathlib import Path

# /app/src → parent is /app, which is PYTHONPATH so 'from src.X import' works
sys.path.insert(0, str(Path(__file__).parent.parent))

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):   print(f"{GREEN}✅ {msg}{RESET}")
def fail(msg): print(f"{RED}❌ {msg}{RESET}")
def warn(msg): print(f"{YELLOW}⚠️  {msg}{RESET}")
def info(msg): print(f"   {msg}")


TEST_TRANSCRIPT = """[00:00 - 00:08] Hey everyone, welcome back to the channel.
[00:08 - 00:20] Today I'm going to show you the number one mistake that 90% of developers make when building APIs.
[00:20 - 00:35] This single mistake can cause your application to lose thousands of users overnight without you even realising it.
[00:35 - 00:50] I discovered this the hard way when our startup lost 40% of our revenue in a single week.
[00:50 - 01:10] The problem is called N+1 query — and it's lurking in almost every ORM-based app you've ever written.
[01:10 - 01:28] Here's exactly how it works. Every time you load a list of 100 users and then fetch their profile for each one, you're making 101 database queries instead of 1.
[01:28 - 01:45] The fix is dead simple: eager loading. Two lines of code and your query count drops from 101 to 1.
[01:45 - 02:00] If you're using Django, just add select_related or prefetch_related. In Rails it's includes. In Laravel it's with.
[02:00 - 02:18] We fixed this bug on a Friday afternoon and by Monday our server costs had dropped by 60 percent. That's not a typo.
[02:18 - 02:30] If this saved you time, smash that like button and subscribe — I post one of these every week."""


def _ts_to_seconds(ts: str) -> int:
    parts = ts.strip().split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    return int(parts[0])


async def run_test() -> bool:
    from src.config import Config
    from src.ai import get_transcript_agent, build_transcript_analysis_prompt

    cfg = Config()

    print(f"\n{BOLD}{'=' * 62}{RESET}")
    print(f"{BOLD}  ViraClip — LLM Connection & Segment Quality Test{RESET}")
    print(f"{BOLD}{'=' * 62}{RESET}\n")

    # 1. Configuration
    print(f"{BOLD}[1/4] Configuration{RESET}")
    info(f"LLM model   : {cfg.llm}")
    provider = cfg.llm.split(":", 1)[0].strip().lower()
    info(f"Provider    : {provider}")

    key_map = {
        "groq":       ("GROQ_API_KEY",      cfg.groq_api_key),
        "openai":     ("OPENAI_API_KEY",     cfg.openai_api_key),
        "anthropic":  ("ANTHROPIC_API_KEY",  cfg.anthropic_api_key),
        "google":     ("GOOGLE_API_KEY",     cfg.google_api_key),
        "google-gla": ("GOOGLE_API_KEY",     cfg.google_api_key),
        "ollama":     (None,                 True),
    }
    key_name, key_value = key_map.get(provider, (f"{provider.upper()}_API_KEY", None))

    if key_name is None:
        ok("Ollama — no API key required")
    elif key_value:
        preview = str(key_value)[:12] + "..." if len(str(key_value)) > 12 else str(key_value)
        ok(f"{key_name} is set  ({preview})")
    else:
        fail(f"{key_name} is NOT set in .env")
        info(f"Add  {key_name}=<your_key>  to your .env and restart workers.")
        return False

    # 2. Agent init
    print(f"\n{BOLD}[2/4] Initialise pydantic-ai agent{RESET}")
    try:
        agent = get_transcript_agent()
        ok("Agent created successfully")
    except Exception as exc:
        fail(f"Agent creation failed: {exc}")
        _print_hint(str(exc), cfg.llm)
        traceback.print_exc()
        return False

    # 3. LLM call
    print(f"\n{BOLD}[3/4] Sending test transcript to {cfg.llm}{RESET}")
    info(f"Transcript  : {len(TEST_TRANSCRIPT)} chars, ~2 min video")
    prompt = build_transcript_analysis_prompt(
        transcript=TEST_TRANSCRIPT,
        include_broll=False,
        video_duration=150.0,
    )
    info(f"Prompt size : {len(prompt)} chars")
    try:
        result = await agent.run(prompt)
        ok("LLM responded without error")
    except Exception as exc:
        fail(f"LLM call raised: {type(exc).__name__}: {exc}")
        _print_hint(str(exc), cfg.llm)
        traceback.print_exc()
        return False

    # 4. Segment quality
    print(f"\n{BOLD}[4/4] Segment quality analysis{RESET}")
    segments = result.output.most_relevant_segments
    info(f"Raw segments returned: {len(segments)}")

    if not segments:
        fail("LLM returned 0 segments — clips will NOT be generated.")
        info("Possible causes:")
        info("  • Model ignoring the mandatory 3-7 segment requirement")
        info("  • Transcript too short / no viral content detected")
        info(f"  Try: LLM=groq:llama-3.1-8b-instant  or  LLM=groq:mixtral-8x7b-32768")
        return False

    all_good = True
    for i, seg in enumerate(segments):
        start_s = _ts_to_seconds(seg.start_time)
        end_s   = _ts_to_seconds(seg.end_time)
        dur     = end_s - start_s
        v_score = seg.virality.total_score if seg.virality else "N/A"
        dur_ok  = dur >= 10
        flag = f"{GREEN}✅{RESET}" if dur_ok else f"{RED}❌{RESET}"
        print(f"  {flag} Segment {i+1}: {seg.start_time}→{seg.end_time} ({dur}s)  virality={v_score}")
        if not dur_ok:
            warn(f"     {dur}s < 10s — auto-extend will fix this at runtime.")
            all_good = False
        if len(seg.text) < 10:
            warn(f"     Segment {i+1} text very short: '{seg.text}'")
            all_good = False

    print()
    if all_good:
        ok(f"All {len(segments)} segments pass quality checks (>= 10s each)")
    else:
        warn("Some segments are short — auto-extend code will handle them at runtime.")

    print(f"\n{BOLD}{'=' * 62}{RESET}")
    ok(f"LLM reachable — {len(segments)} segment(s) returned. Ready to process videos.")
    print(f"{BOLD}{'=' * 62}{RESET}\n")
    return True


def _print_hint(error_str: str, model: str):
    e = error_str.lower()
    if "authentication" in e or "api key" in e or "401" in e or "invalid_api_key" in e:
        print(f"\n{YELLOW}💡 API key error:{RESET}")
        info("  1. GROQ_API_KEY is set correctly in .env")
        info("  2. Key is active at https://console.groq.com/keys")
        info("  3. Restart workers after changing .env:")
        info("       docker-compose restart worker worker-2 worker-3")
    elif "rate" in e or "429" in e:
        print(f"\n{YELLOW}💡 Rate limit:{RESET}")
        info("  Free Groq tier: 30 req/min. Wait 60s and retry.")
    elif "model" in e or "not found" in e or "404" in e:
        print(f"\n{YELLOW}💡 Model not found — valid Groq models:{RESET}")
        info("  LLM=groq:llama-3.3-70b-versatile   ← recommended")
        info("  LLM=groq:llama-3.1-8b-instant       ← fastest")
        info("  LLM=groq:mixtral-8x7b-32768          ← long transcripts")
        info(f"  Current: {model}")
    elif "timeout" in e or "connection" in e:
        print(f"\n{YELLOW}💡 Connection issue:{RESET}")
        info("  docker-compose exec worker curl -s https://api.groq.com")


if __name__ == "__main__":
    try:
        success = asyncio.run(run_test())
    except KeyboardInterrupt:
        print("\nTest interrupted.")
        success = False
    sys.exit(0 if success else 1)
