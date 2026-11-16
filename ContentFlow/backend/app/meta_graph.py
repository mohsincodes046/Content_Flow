"""Meta Graph API client: account discovery, connection checks, publishing.

Errors never include request URLs, because Graph requests carry access tokens
(and, during OAuth, the app secret) as query parameters.
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx

DEFAULT_GRAPH_VERSION = "v26.0"
TOKEN_ERROR_CODES = {190, 102}   # expired, revoked or invalid authorization
PERMISSION_ERROR_CODES = {10, 200, 3}
RATE_LIMIT_CODES = {4, 17, 32, 613, 80001, 80002, 80005}
TRANSIENT_CODES = {1, 2} | RATE_LIMIT_CODES

# Patched in tests so container polling does not wait in real time.
sleep = asyncio.sleep


def graph_version() -> str:
    return os.environ.get("META_GRAPH_VERSION", DEFAULT_GRAPH_VERSION).strip() or DEFAULT_GRAPH_VERSION


def graph_url(path: str, video: bool = False) -> str:
    host = "graph-video.facebook.com" if video else "graph.facebook.com"
    return f"https://{host}/{graph_version()}/{path.lstrip('/')}"


@dataclass
class GraphError(Exception):
    """A failed Graph request. `message` is Meta's text and safe to show users."""

    message: str
    status: int = 0
    code: Optional[int] = None
    subcode: Optional[int] = None
    transient: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message

    @property
    def needs_reconnect(self) -> bool:
        return self.code in TOKEN_ERROR_CODES

    @property
    def missing_permission(self) -> bool:
        return self.code in PERMISSION_ERROR_CODES

    @property
    def retryable(self) -> bool:
        return self.transient or self.code in TRANSIENT_CODES or self.status >= 500


def _error_from(response: httpx.Response) -> GraphError:
    try:
        error = response.json().get("error")
    except ValueError:
        error = None
    if not isinstance(error, dict):
        return GraphError(f"Meta returned HTTP {response.status_code}.", status=response.status_code,
                          transient=response.status_code >= 500)
    code = error.get("code") if isinstance(error.get("code"), int) else None
    subcode = error.get("error_subcode") if isinstance(error.get("error_subcode"), int) else None
    message = str(error.get("error_user_msg") or error.get("message") or "Unknown Meta error").strip()
    if code in TOKEN_ERROR_CODES:
        message = f"The connection to Meta has expired or was revoked. Reconnect the account. ({message})"
    elif code in PERMISSION_ERROR_CODES:
        message = f"Meta denied permission for this action. ({message})"
    return GraphError(message, status=response.status_code, code=code, subcode=subcode,
                      transient=bool(error.get("is_transient")))


async def request(method: str, path: str, *, token: str, params: Optional[dict[str, Any]] = None,
                  data: Optional[dict[str, Any]] = None, files: Any = None, video: bool = False,
                  timeout: float = 60) -> dict[str, Any]:
    query = {**(params or {}), "access_token": token}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "GET":
                response = await client.get(graph_url(path, video), params=query)
            else:
                response = await client.post(graph_url(path, video), params={"access_token": token},
                                             data=data or {}, files=files)
    except httpx.TimeoutException:
        raise GraphError("Meta did not respond in time.", transient=True) from None
    except httpx.HTTPError as error:
        raise GraphError(f"Could not reach Meta ({type(error).__name__}).", transient=True) from None
    if response.is_error:
        raise _error_from(response)
    try:
        payload = response.json()
    except ValueError:
        raise GraphError("Meta returned an unreadable response.", status=response.status_code) from None
    return payload if isinstance(payload, dict) else {"data": payload}


async def get_all(path: str, *, token: str, params: dict[str, Any], max_pages: int = 20) -> list[dict[str, Any]]:
    """Follow cursor pagination (`paging.cursors.after`) up to `max_pages` pages."""
    items: list[dict[str, Any]] = []
    query = dict(params)
    for _ in range(max_pages):
        payload = await request("GET", path, token=token, params=query)
        items.extend(item for item in payload.get("data", []) if isinstance(item, dict))
        after = (payload.get("paging") or {}).get("cursors", {}).get("after")
        if not after or not (payload.get("paging") or {}).get("next"):
            break
        query["after"] = after
    return items


# --- Discovery -------------------------------------------------------------------------------

async def discover_accounts(user_token: str) -> dict[str, Any]:
    """Every Facebook Page the user can manage and each Page's linked Instagram professional account.

    Returns {"external_user_id", "external_user_name", "accounts": [...]} where each account has
    platform, account_id, account_name, account_type, profile_picture_url, parent_account_id
    (the Page's id for Instagram accounts), details and tokens.
    """
    me = await request("GET", "me", token=user_token, params={"fields": "id,name"})
    pages = await get_all("me/accounts", token=user_token, params={
        "fields": "id,name,access_token,category,tasks,picture{url}", "limit": 100,
    })
    accounts: list[dict[str, Any]] = []
    for page in pages:
        page_token = page.get("access_token")
        if not isinstance(page_token, str) or not page_token:
            continue  # no Page token means no permission to act for this Page
        tasks = page.get("tasks") if isinstance(page.get("tasks"), list) else []
        can_publish = "CREATE_CONTENT" in tasks or "MANAGE" in tasks
        tokens = {"access_token": page_token, "refresh_token": None, "expires_at": None}
        accounts.append({
            "platform": "facebook",
            "account_id": str(page["id"]),
            "account_name": page.get("name") or "Facebook Page",
            "account_type": "page",
            "profile_picture_url": ((page.get("picture") or {}).get("data") or {}).get("url"),
            "parent_account_id": None,
            "details": {"category": page.get("category"), "can_publish": can_publish, "tasks": tasks},
            "tokens": tokens,
        })
        linked = await request("GET", str(page["id"]), token=page_token, params={
            "fields": "instagram_business_account{id,username,name,profile_picture_url,followers_count}",
        })
        instagram = linked.get("instagram_business_account")
        if isinstance(instagram, dict) and instagram.get("id"):
            accounts.append({
                "platform": "instagram",
                "account_id": str(instagram["id"]),
                "account_name": instagram.get("username") or instagram.get("name") or "Instagram account",
                "account_type": "professional",
                "profile_picture_url": instagram.get("profile_picture_url"),
                "parent_account_id": str(page["id"]),
                "details": {"followers_count": instagram.get("followers_count"), "can_publish": can_publish,
                            "linked_page_name": page.get("name")},
                "tokens": tokens,
            })
    return {"external_user_id": str(me.get("id") or ""), "external_user_name": me.get("name"), "accounts": accounts}


async def check_account(platform: str, account_id: str, token: str) -> dict[str, Any]:
    """Confirm the stored token still works for this account; raises GraphError if not."""
    fields = "id,name" if platform == "facebook" else "id,username"
    return await request("GET", account_id, token=token, params={"fields": fields})


# --- Facebook Page publishing ----------------------------------------------------------------

@dataclass
class MediaFile:
    path: Path
    filename: str
    media_type: str

    @property
    def is_video(self) -> bool:
        return self.media_type.startswith("video/")


@dataclass
class PublishResult:
    external_id: str
    url: Optional[str] = None


async def publish_facebook(page_id: str, token: str, message: str, media: list[MediaFile],
                           link: Optional[str] = None) -> PublishResult:
    if not media:
        payload = await request("POST", f"{page_id}/feed", token=token,
                                data={"message": message, **({"link": link} if link else {})})
        return PublishResult(payload["id"], f"https://www.facebook.com/{payload['id']}")
    if len(media) == 1 and media[0].is_video:
        with media[0].path.open("rb") as handle:
            payload = await request("POST", f"{page_id}/videos", token=token, video=True, timeout=600,
                                    data={"description": message},
                                    files={"source": (media[0].filename, handle, media[0].media_type)})
        return PublishResult(payload["id"], f"https://www.facebook.com/{page_id}/videos/{payload['id']}")
    if any(item.is_video for item in media):
        raise GraphError("Facebook posts can have several photos or one video, not a mix.")
    if len(media) == 1:
        with media[0].path.open("rb") as handle:
            payload = await request("POST", f"{page_id}/photos", token=token, timeout=180,
                                    data={"caption": message},
                                    files={"source": (media[0].filename, handle, media[0].media_type)})
        post_id = payload.get("post_id") or payload["id"]
        return PublishResult(post_id, f"https://www.facebook.com/{post_id}")
    # Several photos: upload each unpublished, then publish one post that attaches them all.
    photo_ids = []
    for item in media:
        with item.path.open("rb") as handle:
            uploaded = await request("POST", f"{page_id}/photos", token=token, timeout=180,
                                     data={"published": "false"},
                                     files={"source": (item.filename, handle, item.media_type)})
        photo_ids.append(uploaded["id"])
    data = {"message": message}
    for index, photo_id in enumerate(photo_ids):
        data[f"attached_media[{index}]"] = json.dumps({"media_fbid": photo_id})
    payload = await request("POST", f"{page_id}/feed", token=token, data=data)
    return PublishResult(payload["id"], f"https://www.facebook.com/{payload['id']}")


# --- Instagram publishing --------------------------------------------------------------------

CONTAINER_POLL_SECONDS = 10
CONTAINER_POLL_ATTEMPTS = 30  # Meta recommends polling for no more than ~5 minutes


async def _wait_for_container(container_id: str, token: str) -> None:
    for _ in range(CONTAINER_POLL_ATTEMPTS):
        status = await request("GET", container_id, token=token, params={"fields": "status_code,status"})
        code = status.get("status_code")
        if code in ("FINISHED", "PUBLISHED"):
            return
        if code in ("ERROR", "EXPIRED"):
            raise GraphError(f"Instagram could not process the media ({status.get('status') or code}).")
        await sleep(CONTAINER_POLL_SECONDS)
    raise GraphError("Instagram is still processing the media; try again shortly.", transient=True)


async def _container(ig_id: str, token: str, item: tuple[str, str], *, caption: Optional[str],
                     carousel_item: bool) -> str:
    media_type, url = item
    data: dict[str, Any] = {}
    if media_type.startswith("video/"):
        data["video_url"] = url
        data["media_type"] = "VIDEO" if carousel_item else "REELS"
    else:
        data["image_url"] = url
    if carousel_item:
        data["is_carousel_item"] = "true"
    elif caption:
        data["caption"] = caption
    payload = await request("POST", f"{ig_id}/media", token=token, data=data)
    return payload["id"]


async def publishing_quota(ig_id: str, token: str) -> Optional[dict[str, Any]]:
    payload = await request("GET", f"{ig_id}/content_publishing_limit", token=token,
                            params={"fields": "config,quota_usage"})
    data = payload.get("data")
    return data[0] if isinstance(data, list) and data else None


async def publish_instagram(ig_id: str, token: str, caption: str, media: list[tuple[str, str]]) -> PublishResult:
    """`media` is a list of (media_type, public_url). Images must be JPEG (Meta requirement)."""
    if not media:
        raise GraphError("Instagram posts need at least one photo or video.")
    if len(media) > 10:
        raise GraphError("Instagram carousels can have at most 10 items.")
    quota = await publishing_quota(ig_id, token)
    if quota:
        total = (quota.get("config") or {}).get("quota_total")
        used = quota.get("quota_usage")
        if isinstance(total, int) and isinstance(used, int) and used >= total:
            raise GraphError(f"Instagram's daily publishing limit ({total} posts in 24 hours) is reached.",
                             transient=True)
    if len(media) == 1:
        container = await _container(ig_id, token, media[0], caption=caption, carousel_item=False)
    else:
        children = [await _container(ig_id, token, item, caption=None, carousel_item=True) for item in media]
        for child in children:
            await _wait_for_container(child, token)
        payload = await request("POST", f"{ig_id}/media", token=token,
                                data={"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption})
        container = payload["id"]
    await _wait_for_container(container, token)
    published = await request("POST", f"{ig_id}/media_publish", token=token, data={"creation_id": container})
    media_id = published["id"]
    permalink = None
    try:
        permalink = (await request("GET", media_id, token=token, params={"fields": "permalink"})).get("permalink")
    except GraphError:
        pass  # the post is live; a missing permalink is not a failure
    return PublishResult(media_id, permalink)
