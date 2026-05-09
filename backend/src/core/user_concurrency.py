"""
Per-user concurrency limiter for task processing.
Uses Redis INCR with TTL failsafe.
"""
import os

USER_MAX_CONCURRENT = int(os.getenv("USER_MAX_CONCURRENT_TASKS", "2"))


async def acquire_user_slot(user_id: str, redis) -> tuple[bool, int]:
    """
    Adquiere un slot de concurrencia para el usuario.
    Retorna (acquired: bool, active_count: int).
    TTL de 30 min por si la task no libera el slot (failsafe).
    """
    try:
        env = os.getenv("APP_ENV", "production")
        key = f"{env}:concurrency:{user_id}"
        current = await redis.incr(key)
        if current == 1:
            await redis.expire(key, 1800)
        if current > USER_MAX_CONCURRENT:
            await redis.decr(key)
            return False, current - 1
        return True, current
    except Exception:
        return True, 1


async def release_user_slot(user_id: str, redis) -> None:
    """Libera un slot de concurrencia al terminar la task."""
    try:
        env = os.getenv("APP_ENV", "production")
        key = f"{env}:concurrency:{user_id}"
        current = await redis.decr(key)
        if current < 0:
            await redis.set(key, 0)
    except Exception:
        pass
