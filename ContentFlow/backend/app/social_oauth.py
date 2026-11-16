from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from app import meta_graph

# Only what the product uses, which keeps Meta App Review simpler:
#   pages_show_list, business_management  find the user's Pages (incl. Business Manager Pages)
#   pages_read_engagement, read_insights  read Page posts and Page/post insights
#   pages_manage_posts                    publish to Pages
#   instagram_basic, instagram_content_publish, instagram_manage_insights
#                                         find, publish to and read insights of Instagram accounts
META_SCOPES = (
    "pages_show_list,business_management,pages_read_engagement,read_insights,pages_manage_posts,"
    "instagram_basic,instagram_content_publish,instagram_manage_insights"
)

PROVIDER_SETTINGS: dict[str, dict[str, str]] = {
    "meta": {
        "client_id": "META_APP_ID",
        "client_secret": "META_APP_SECRET",
        "scope": META_SCOPES,
    },
}


def _authorize_url() -> str:
    return f"https://www.facebook.com/{meta_graph.graph_version()}/dialog/oauth"


def _token_url() -> str:
    return meta_graph.graph_url("oauth/access_token")


def graph_error_summary(response: httpx.Response) -> str:
    """Describe a failed Graph API response for logs without echoing the request.

    Meta's OAuth requests carry the app secret and authorization code in the URL,
    and httpx includes the URL in its exception text, so log this instead.
    """
    try:
        error = response.json().get("error")
    except ValueError:
        error = None
    if not isinstance(error, dict):
        return f"HTTP {response.status_code}"
    return (
        f"HTTP {response.status_code}: {error.get('message')} "
        f"(type={error.get('type')}, code={error.get('code')}, subcode={error.get('error_subcode')})"
    )


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
        "auth_type": "rerequest",
        "state": state,
    }
    return f"{_authorize_url()}?{urlencode(params)}"


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
            _token_url(),
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
            _token_url(),
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


async def retrieve_connected_accounts(provider: str, token_data: dict[str, Any]) -> dict[str, Any]:
    """Pages and linked Instagram accounts the signed-in Meta user can manage (see meta_graph)."""
    if provider != "meta":
        raise ValueError("Only Meta account discovery is enabled in this integration phase.")
    return await meta_graph.discover_accounts(token_data["access_token"])
