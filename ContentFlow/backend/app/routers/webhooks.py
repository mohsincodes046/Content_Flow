from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os

from fastapi import APIRouter, HTTPException, Request, Response

logger = logging.getLogger(__name__)

router = APIRouter()


MAX_WEBHOOK_BYTES = 1024 * 1024


def webhook_verify_token() -> str:
    token = os.environ.get("META_WEBHOOK_VERIFY_TOKEN", "").strip()
    if not token:
        raise HTTPException(status_code=503, detail="Meta webhooks are not configured.")
    return token


@router.get("/api/social/webhook")
def verify_webhook(request: Request) -> Response:
    expected_token = webhook_verify_token()
    hub_mode = request.query_params.get("hub.mode")
    hub_challenge = request.query_params.get("hub.challenge") or ""
    hub_verify_token = request.query_params.get("hub.verify_token") or ""
    if hub_mode == "subscribe" and hmac.compare_digest(
        hub_verify_token.encode("utf-8"), expected_token.encode("utf-8")
    ):
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed.")


@router.post("/api/social/webhook")
async def receive_webhook(request: Request) -> dict[str, str]:
    webhook_verify_token()
    app_secret = os.environ.get("META_APP_SECRET", "").strip()
    if not app_secret:
        raise HTTPException(status_code=503, detail="Meta webhooks are not configured.")
    body = await request.body()
    if len(body) > MAX_WEBHOOK_BYTES:
        raise HTTPException(status_code=413, detail="Webhook payload is too large.")
    signature = request.headers.get("x-hub-signature-256", "")
    expected = "sha256=" + hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")
    try:
        payload = json.loads(body)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Webhook payload must be JSON.") from error
    logger.info(
        "Received Meta webhook for object %r with %d entries.",
        payload.get("object") if isinstance(payload, dict) else None,
        len(payload.get("entry", [])) if isinstance(payload, dict) else 0,
    )
    return {"status": "received"}
