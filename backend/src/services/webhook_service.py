"""
Webhook delivery service with HMAC signing and retry.
"""
import asyncio
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
WEBHOOK_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
WEBHOOK_MAX_ATTEMPTS = 3


def _sign_payload(payload: dict) -> str:
    """HMAC-SHA256 signature for webhook authenticity verification."""
    if not WEBHOOK_SECRET:
        return ""
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    sig = hmac.new(
        WEBHOOK_SECRET.encode(),
        body.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={sig}"


async def deliver_webhook(
    webhook_url: str,
    task_id: str,
    status: str,
    payload: dict,
    attempt: int = 1,
) -> bool:
    """Deliver webhook with HMAC signature. Returns True on success."""
    full_payload = {
        "event": f"task.{status}",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "task_id": task_id,
        "attempt": attempt,
        **payload,
    }

    signature = _sign_payload(full_payload)
    headers = {
        "Content-Type": "application/json",
        "X-ViraClip-Event": f"task.{status}",
        "X-ViraClip-Task-ID": task_id,
        "X-ViraClip-Attempt": str(attempt),
    }
    if signature:
        headers["X-ViraClip-Signature"] = signature

    try:
        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT) as client:
            response = await client.post(webhook_url, json=full_payload, headers=headers)
            if 200 <= response.status_code < 300:
                logger.info(
                    "[Webhook] Delivered task.%s (HTTP %d, attempt %d)",
                    status, response.status_code, attempt,
                )
                return True
            logger.warning(
                "[Webhook] HTTP %d for task %s attempt %d",
                response.status_code, task_id, attempt,
            )
            return False
    except Exception as exc:
        logger.warning(
            "[Webhook] Failed (attempt %d/%d): %s",
            attempt, WEBHOOK_MAX_ATTEMPTS, type(exc).__name__,
        )
        return False


async def deliver_webhook_with_retry(
    webhook_url: str,
    task_id: str,
    status: str,
    payload: dict,
    db,
) -> None:
    """Deliver with up to 3 attempts, exponential backoff."""
    for attempt in range(1, WEBHOOK_MAX_ATTEMPTS + 1):
        success = await deliver_webhook(webhook_url, task_id, status, payload, attempt)
        if success:
            await db.update_task(task_id, {
                "webhook_delivered": True,
                "webhook_attempts": attempt,
            })
            return
        if attempt < WEBHOOK_MAX_ATTEMPTS:
            await asyncio.sleep(2 ** attempt)

    await db.update_task(task_id, {
        "webhook_delivered": False,
        "webhook_attempts": WEBHOOK_MAX_ATTEMPTS,
    })
    logger.error(
        "[Webhook] All %d attempts failed for task %s",
        WEBHOOK_MAX_ATTEMPTS, task_id,
    )
