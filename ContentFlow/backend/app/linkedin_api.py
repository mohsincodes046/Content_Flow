"""LinkedIn OAuth (OpenID Connect) and the Posts API for personal profiles.

Official limits that matter here:
  * Posting as a member uses the self-serve "Share on LinkedIn" product
    (`w_member_social`). Posting as a company Page needs `w_organization_social`
    from the Community Management API, which LinkedIn must approve.
  * Access tokens last about 60 days and most apps get no refresh token, so an
    expired token means reconnecting.
  * Every call sends `LinkedIn-Version` (YYYYMM) and `X-Restli-Protocol-Version: 2.0.0`.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlencode

import httpx

from app.meta_graph import GraphError, PublishResult

AUTHORIZE_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
API = "https://api.linkedin.com"
SCOPES = "openid profile w_member_social"
DEFAULT_VERSION = "202610"


def api_version() -> str:
    return os.environ.get("LINKEDIN_API_VERSION", DEFAULT_VERSION).strip() or DEFAULT_VERSION


def _error(response: httpx.Response) -> GraphError:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    message = str(payload.get("message") or payload.get("error_description") or f"LinkedIn returned HTTP {response.status_code}.")
    if response.status_code == 401:
        return GraphError(f"The LinkedIn connection has expired. Reconnect it. ({message})", status=401, code=190)
    if response.status_code == 403:
        return GraphError(f"LinkedIn denied permission for this action. ({message})", status=403, code=200)
    return GraphError(f"LinkedIn: {message}", status=response.status_code,
                      transient=response.status_code in (409, 429) or response.status_code >= 500)


async def _call(method: str, url: str, *, token: Optional[str] = None, rest: bool = True, timeout: float = 60,
                **kwargs: Any) -> httpx.Response:
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if rest:
        headers.update({"LinkedIn-Version": api_version(), "X-Restli-Protocol-Version": "2.0.0"})
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method, url, headers=headers, **kwargs)
    except httpx.HTTPError as error:
        raise GraphError(f"Could not reach LinkedIn ({type(error).__name__}).", transient=True) from None
    if response.is_error:
        raise _error(response)
    return response


def authorization_url(client_id: str, redirect_uri: str, state: str) -> str:
    return f"{AUTHORIZE_URL}?{urlencode({'response_type': 'code', 'client_id': client_id, 'redirect_uri': redirect_uri, 'state': state, 'scope': SCOPES})}"


async def exchange_code(client_id: str, client_secret: str, code: str, redirect_uri: str) -> dict[str, Any]:
    response = await _call("POST", TOKEN_URL, rest=False, data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
        "client_id": client_id, "client_secret": client_secret,
    })
    payload = response.json()
    if not payload.get("access_token"):
        raise GraphError("LinkedIn did not return an access token.")
    return {
        "access_token": payload["access_token"], "refresh_token": payload.get("refresh_token"),
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=int(payload.get("expires_in") or 0))).isoformat(),
    }


def expired(tokens: dict[str, Any]) -> bool:
    expires = tokens.get("expires_at")
    return bool(expires) and datetime.fromisoformat(expires) <= datetime.now(timezone.utc)


async def discover(tokens: dict[str, Any]) -> dict[str, Any]:
    user = (await _call("GET", f"{API}/v2/userinfo", token=tokens["access_token"], rest=False)).json()
    person = user.get("sub")
    if not person:
        raise GraphError("LinkedIn did not return the member's id.")
    return {"external_user_id": person, "external_user_name": user.get("name"), "accounts": [{
        "platform": "linkedin", "account_id": person, "account_name": user.get("name") or "LinkedIn member",
        "account_type": "member", "profile_picture_url": user.get("picture"), "parent_account_id": None,
        "details": {"can_publish": True}, "tokens": tokens,
    }]}


async def _upload_image(token: str, author: str, image: Path, media_type: str) -> str:
    init = (await _call("POST", f"{API}/rest/images?action=initializeUpload", token=token,
                        json={"initializeUploadRequest": {"owner": author}})).json()
    value = init.get("value") or {}
    if not value.get("uploadUrl") or not value.get("image"):
        raise GraphError("LinkedIn did not return an image upload address.")
    await _call("PUT", value["uploadUrl"], token=token, rest=False, timeout=300, content=image.read_bytes(),
                headers={"Content-Type": media_type})
    return value["image"]


async def publish(person_id: str, token: str, text: str, images: list[tuple[Path, str]]) -> PublishResult:
    author = f"urn:li:person:{person_id}"
    body: dict[str, Any] = {
        "author": author, "commentary": text, "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
        "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False,
    }
    if images:
        path, media_type = images[0]
        body["content"] = {"media": {"id": await _upload_image(token, author, path, media_type)}}
    response = await _call("POST", f"{API}/rest/posts", token=token, json=body)
    post_urn = response.headers.get("x-restli-id")
    if not post_urn:
        raise GraphError("LinkedIn did not return the post id.")
    return PublishResult(post_urn, f"https://www.linkedin.com/feed/update/{quote(post_urn, safe=':')}/")
