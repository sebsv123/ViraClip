"""WhatsApp Cloud API webhook routes — Meta verification + inbound messages."""

import logging
from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import PlainTextResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wa", tags=["whatsapp"])

# ── Config ────────────────────────────────────────────────────────────────────
VERIFY_TOKEN = "agente_seguros"


@router.get("/inbound")
async def wa_verify(
    hub_mode: str = Query("", alias="hub.mode"),
    hub_verify_token: str = Query("", alias="hub.verify_token"),
    hub_challenge: str = Query("", alias="hub.challenge"),
):
    """
    Meta WhatsApp Cloud API webhook verification (GET).

    Meta sends a GET with:
      ?hub.mode=subscribe&hub.verify_token=TOKEN&hub.challenge=CHALLENGE

    If verify_token matches, respond with the challenge as plain text.
    """
    logger.info(
        "WhatsApp verify request: mode=%s token=%s challenge=%s",
        hub_mode, hub_verify_token, hub_challenge,
    )

    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        logger.info("WhatsApp verification SUCCESS — returning challenge")
        return PlainTextResponse(content=hub_challenge, status_code=200)

    logger.warning("WhatsApp verification FAILED — token mismatch or bad mode")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/inbound")
async def wa_webhook(request: Request):
    """
    Receive inbound WhatsApp messages from Meta Cloud API (POST).

    Meta sends JSON payloads here after verification is complete.
    """
    body = await request.json()
    logger.info("WhatsApp inbound message received: %s", body)

    # TODO: process the message — for now just acknowledge
    return {"status": "received"}
