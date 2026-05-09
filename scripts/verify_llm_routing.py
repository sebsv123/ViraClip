#!/usr/bin/env python3
"""
Verifica que el routing LLM funciona correctamente en runtime.
Usage: python scripts/verify_llm_routing.py
"""
import asyncio
import os
import sys

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


async def main():
    print("=== LLM Routing Verification ===\n")

    from src.domains.ai.llm_router import (
        LLMRouter,
        _cb_record_failure,
        _cb_record_success,
    )

    router = LLMRouter()

    # Test 1: Con DEEPSEEK_API_KEY configurada
    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
    backend = await router.select_backend(dataset_size=0)
    print(f"Con DEEPSEEK_API_KEY: → {backend.value}")
    esperado = "deepseek" if deepseek_key else "groq"
    status = "✓" if esperado in backend.value else "✗"
    print(f"{status} Esperado: {esperado}")

    # Test 2: Sin DEEPSEEK_API_KEY (simula fallback)
    original = os.environ.pop("DEEPSEEK_API_KEY", None)
    backend = await router.select_backend(dataset_size=0)
    print(f"\nSin DEEPSEEK_API_KEY: → {backend.value}")
    print(f"{'✓' if 'groq' in backend.value else '✗'} Esperado: groq (fallback)")
    if original:
        os.environ["DEEPSEEK_API_KEY"] = original

    # Test 3: Con circuit breaker activo
    for _ in range(3):
        await _cb_record_failure(redis=None)
    backend = await router.select_backend(dataset_size=0)
    print(f"\nCon circuit breaker activo: → {backend.value}")
    print(f"{'✓' if 'groq' in backend.value else '✗'} Esperado: groq (bypass)")
    await _cb_record_success(redis=None)  # reset

    print("\n=== Fin verificación ===")


if __name__ == "__main__":
    asyncio.run(main())
