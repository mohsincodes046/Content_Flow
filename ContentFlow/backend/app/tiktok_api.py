"""TikTok Login Kit (OAuth v2) and Content Posting API (direct post of videos).

Official limits that matter here:
  * Posting needs the `video.publish` scope and app approval of the Content
    Posting API. Until TikTok audits the app, every post is private
    (SELF_ONLY); public posting is refused by TikTok.
  * Access tokens last 24 hours; refresh tokens about a year. Tokens are
    refreshed before publishing.
  * A post is reported published only when TikTok's status is PUBLISH_COMPLETE.
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from app.meta_graph import GraphError, PublishResult

AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
API = "https://open.tiktokapis.com/v2"
SCOPES = "user.info.basic,video.publish"
STATUS_POLL_SECONDS = 5
STATUS_POLL_ATTEMPTS = 24
sleep = asyncio.sleep  # patched in tests


def _error(response: httpx.Response) -> GraphError:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    code = str(error.get("code") or payload.get("error") or response.status_code)
    message = str(error.get("message") or payload.get("error_description") or f"TikTok returned HTTP {response.status_code}.")
    if code in {"access_token_invalid", "scope_not_authorized", "invalid_grant", "token_expired"}:
        return GraphError(f"The TikTok connection has expired or lacks permission. Reconnect it. ({message})",
                          status=response.status_code, code=190)
    if code == "unaudited_client_can_only_post_to_private_accounts":
        return GraphError("TikTok only allows private posts until the app passes TikTok's review "
                          "(the account must be private, or the app audited).", status=response.status_code)
    return GraphError(f"TikTok: {message} ({code})", status=response.status_code,
                      transient=response.status_code >= 500 or code == "rate_limit_exceeded")


async def _call(method: str, url: str, *, token: Optional[str] = None, timeout: float = 60, **kwargs: Any) -> httpx.Response:
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method, url, headers=headers, **kwargs)
    except httpx.HTTPError as error:
        raise GraphError(f"Could not reach TikTok ({type(error).__name__}).", transient=True) from None
    if response.is_error:
        raise _error(response)
    return response


def _json_ok(response: httpx.Response) -> dict[str, Any]:
    payload = response.json()
    error = payload.get("error")
    if isinstance(error, dict) and error.get("code") not in (None, "ok"):
        raise _error(response)
    return payload.get("data") or {}


def authorization_url(client_key: str, redirect_uri: str, state: str) -> str:
    return f"{AUTHORIZE_URL}?{urlencode({'client_key': client_key, 'scope': SCOPES, 'response_type': 'code', 'redirect_uri': redirect_uri, 'state': state})}"


def _tokens(payload: dict[str, Any]) -> dict[str, Any]:
    if not payload.get("access_token"):
        raise GraphError(f"TikTok did not return an access token ({payload.get('error_description') or payload.get('error')}).")
    now = datetime.now(timezone.utc)
    return {
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token"),
        "expires_at": (now + timedelta(seconds=int(payload.get("expires_in") or 0))).isoformat(),
        "refresh_expires_at": (now + timedelta(seconds=int(payload.get("refresh_expires_in") or 0))).isoformat(),
        "open_id": payload.get("open_id"),
    }


async def exchange_code(client_key: str, client_secret: str, code: str, redirect_uri: str) -> dict[str, Any]:
    response = await _call("POST", f"{API}/oauth/token/", data={
        "client_key": client_key, "client_secret": client_secret, "code": code,
        "grant_type": "authorization_code", "redirect_uri": redirect_uri,
    }, headers={"Content-Type": "application/x-www-form-urlencoded"})
    return _tokens(response.json())


async def refresh(tokens: dict[str, Any]) -> dict[str, Any]:
    client_key = os.environ.get("TIKTOK_CLIENT_KEY", "").strip()
    client_secret = os.environ.get("TIKTOK_CLIENT_SECRET", "").strip()
    if not tokens.get("refresh_token") or not client_key:
        raise GraphError("The TikTok connection has expired. Reconnect it.", code=190)
    response = await _call("POST", f"{API}/oauth/token/", data={
        "client_key": client_key, "client_secret": client_secret,
        "grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
    }, headers={"Content-Type": "application/x-www-form-urlencoded"})
    return {**tokens, **_tokens(response.json())}


def needs_refresh(tokens: dict[str, Any]) -> bool:
    expires = tokens.get("expires_at")
    return not expires or datetime.fromisoformat(expires) <= datetime.now(timezone.utc) + timedelta(minutes=5)


async def discover(tokens: dict[str, Any]) -> dict[str, Any]:
    response = await _call("GET", f"{API}/user/info/", token=tokens["access_token"],
                           params={"fields": "open_id,avatar_url,display_name"})
    user = _json_ok(response).get("user") or {}
    open_id = user.get("open_id") or tokens.get("open_id")
    return {"external_user_id": open_id, "external_user_name": user.get("display_name"), "accounts": [{
        "platform": "tiktok", "account_id": open_id, "account_name": user.get("display_name") or "TikTok account",
        "account_type": "creator", "profile_picture_url": user.get("avatar_url"), "parent_account_id": None,
        "details": {"can_publish": True}, "tokens": tokens,
    }]}


async def publish_video(token: str, caption: str, video: Path, media_type: str) -> PublishResult:
    creator = _json_ok(await _call("POST", f"{API}/post/publish/creator_info/query/", token=token,
                                   headers={"Content-Type": "application/json; charset=UTF-8"}))
    options = creator.get("privacy_level_options") or ["SELF_ONLY"]
    privacy = "PUBLIC_TO_EVERYONE" if "PUBLIC_TO_EVERYONE" in options else options[0]
    size = video.stat().st_size
    init = _json_ok(await _call("POST", f"{API}/post/publish/video/init/", token=token, json={
        "post_info": {"title": caption[:2200], "privacy_level": privacy, "disable_comment": False,
                      "disable_duet": False, "disable_stitch": False},
        "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1},
    }, headers={"Content-Type": "application/json; charset=UTF-8"}))
    publish_id, upload_url = init.get("publish_id"), init.get("upload_url")
    if not publish_id or not upload_url:
        raise GraphError("TikTok did not return an upload address.")
    await _call("PUT", upload_url, timeout=600, content=video.read_bytes(), headers={
        "Content-Type": media_type, "Content-Range": f"bytes 0-{size - 1}/{size}", "Content-Length": str(size)})
    for _ in range(STATUS_POLL_ATTEMPTS):
        status = _json_ok(await _call("POST", f"{API}/post/publish/status/fetch/", token=token,
                                      json={"publish_id": publish_id},
                                      headers={"Content-Type": "application/json; charset=UTF-8"}))
        state = status.get("status")
        if state == "PUBLISH_COMPLETE":
            post_ids = status.get("publicaly_available_post_id") or status.get("publicly_available_post_id") or []
            return PublishResult(str(post_ids[0]) if post_ids else publish_id, None)
        if state == "FAILED":
            raise GraphError(f"TikTok could not publish the video ({status.get('fail_reason') or 'unknown reason'}).")
        await sleep(STATUS_POLL_SECONDS)
    raise GraphError(f"TikTok accepted the video (publish id {publish_id}) but is still processing it. "
                     "Check TikTok before retrying to avoid a duplicate.")
