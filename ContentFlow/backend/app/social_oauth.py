from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx


META_GRAPH_VERSION = "v25.0"

PROVIDER_SETTINGS: dict[str, dict[str, str]] = {
    "meta": {
        "client_id": "META_APP_ID",
        "client_secret": "META_APP_SECRET",
        "authorize_url": f"https://www.facebook.com/{META_GRAPH_VERSION}/dialog/oauth",
        "token_url": f"https://graph.facebook.com/{META_GRAPH_VERSION}/oauth/access_token",
        "scope": (
            "pages_show_list,pages_read_engagement,pages_manage_posts,"
            "pages_manage_engagement,instagram_basic,instagram_content_publish,"
            "instagram_manage_comments,instagram_manage_insights"
        ),
    },
}


def get_provider_settings(provider: str) -> dict[str, str]:
    settings = PROVIDER_SETTINGS.get(provider)
    if settings is None:
        raise ValueError("Unsupported social account provider.")
    client_id = os.environ.get(settings["client_id"], "").strip()
    client_secret = os.environ.get(settings["client_secret"], "").strip()
    if not client_id or not client_secret:
        raise RuntimeError(f"Configure {settings['client_id']} and {settings['client_secret']} on the backend.")
    return {**settings, "client_id_value": client_id, "client_secret_value": client_secret}


def build_authorization_url(provider: str, settings: dict[str, str], redirect_uri: str, state: str) -> str:
    if provider != "meta":
        raise ValueError("Only Meta OAuth is enabled in this integration phase.")
    params = {
        "client_id": settings["client_id_value"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": settings["scope"],
        "state": state,
    }
    return f"{settings['authorize_url']}?{urlencode(params)}"


def _expires_at(payload: dict[str, Any]) -> str | None:
    expires_in = payload.get("expires_in")
    if not isinstance(expires_in, (int, float)):
        return None
    return (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()


async def exchange_authorization_code(
    provider: str,
    settings: dict[str, str],
    code: str,
    redirect_uri: str,
) -> dict[str, Any]:
    if provider != "meta":
        raise ValueError("Only Meta OAuth is enabled in this integration phase.")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            settings["token_url"],
            params={
                "client_id": settings["client_id_value"],
                "client_secret": settings["client_secret_value"],
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
        response.raise_for_status()
        payload = response.json()
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise ValueError("The provider did not return an access token.")
    async with httpx.AsyncClient(timeout=30) as client:
        long_lived_response = await client.get(
            settings["token_url"],
            params={
                "grant_type": "fb_exchange_token",
                "client_id": settings["client_id_value"],
                "client_secret": settings["client_secret_value"],
                "fb_exchange_token": access_token,
            },
        )
        long_lived_response.raise_for_status()
        long_lived_payload = long_lived_response.json()
    long_lived_token = long_lived_payload.get("access_token")
    if not isinstance(long_lived_token, str) or not long_lived_token:
        raise ValueError("Meta did not return a long-lived access token.")
    long_lived_payload["expires_at"] = _expires_at(long_lived_payload)
    return long_lived_payload


async def retrieve_connected_accounts(provider: str, token_data: dict[str, Any]) -> list[dict[str, Any]]:
    if provider != "meta":
        raise ValueError("Only Meta account discovery is enabled in this integration phase.")
    access_token = token_data["access_token"]
    token_fields = {
        "access_token": access_token,
        "refresh_token": token_data.get("refresh_token"),
        "expires_at": token_data.get("expires_at"),
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"https://graph.facebook.com/{META_GRAPH_VERSION}/me/accounts",
            params={
                "fields": "id,name,access_token,instagram_business_account{id,username}",
                "access_token": access_token,
            },
        )
        response.raise_for_status()
        pages = response.json().get("data", [])
        accounts: list[dict[str, Any]] = []
        for page in pages:
            page_token = page.get("access_token") or access_token
            page_tokens = {**token_fields, "access_token": page_token, "expires_at": None}
            accounts.append({
                "platform": "facebook",
                "account_id": str(page["id"]),
                "account_name": page.get("name") or "Facebook Page",
                "account_type": "page",
                "tokens": page_tokens,
            })
            instagram = page.get("instagram_business_account")
            if isinstance(instagram, dict) and instagram.get("id"):
                accounts.append({
                    "platform": "instagram",
                    "account_id": str(instagram["id"]),
                    "account_name": instagram.get("username") or "Instagram professional account",
                    "account_type": "professional",
                    "tokens": page_tokens,
                })
        return accounts
