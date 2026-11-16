from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse

from app import social_oauth
from app.config import public_api_url, public_frontend_url, publisher_is_enabled
from app.database import Row, connect_database, utc_now
from app.schemas import SocialAccountResponse, SocialProviderStatus
from app.security import get_current_user, token_cipher, token_digest

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/social/providers", response_model=list[SocialProviderStatus])
def list_social_providers(
    user: Annotated[Row, Depends(get_current_user)],
) -> list[SocialProviderStatus]:
    with connect_database() as connection:
        rows = connection.execute(
            "SELECT * FROM social_accounts WHERE user_id = ? ORDER BY platform, account_name",
            (user["id"],),
        ).fetchall()
    account_responses = [
        SocialAccountResponse(
            id=row["id"],
            platform=row["platform"],
            account_id=row["account_id"],
            account_name=row["account_name"],
            account_type=row["account_type"],
            connected_at=row["connected_at"],
            expires_at=row["expires_at"],
        )
        for row in rows
    ]
    accounts_by_provider: dict[str, list[SocialAccountResponse]] = {}
    for account, row in zip(account_responses, rows):
        accounts_by_provider.setdefault(row["provider"], []).append(account)

    results: list[SocialProviderStatus] = []
    for provider in social_oauth.PROVIDER_SETTINGS:
        try:
            social_oauth.get_provider_settings(provider)
            token_cipher()
            configured = True
        except (RuntimeError, ValueError):
            configured = False
        results.append(SocialProviderStatus(
            provider=provider,
            configured=configured,
            accounts=accounts_by_provider.get(provider, []),
            publisher_enabled=publisher_is_enabled(),
        ))
    return results


@router.get("/api/social/oauth/{provider}/start")
def start_social_oauth(
    provider: str,
    user: Annotated[Row, Depends(get_current_user)],
) -> RedirectResponse:
    try:
        settings = social_oauth.get_provider_settings(provider)
        token_cipher()
    except ValueError as error:
        raise HTTPException(status_code=404, detail="Unsupported social account provider.") from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    api_url = public_api_url()
    if urlsplit(api_url).scheme != "https":
        raise HTTPException(
            status_code=503,
            detail=(
                "Meta OAuth requires an HTTPS API callback. Set "
                "CONTENT_FLOW_API_PUBLIC_URL to your HTTPS tunnel or deployment URL."
            ),
        )

    state = secrets.token_urlsafe(32)
    redirect_uri = f"{api_url}/api/social/oauth/{provider}/callback"
    with connect_database() as connection:
        connection.execute("DELETE FROM oauth_states WHERE expires_at <= ?", (utc_now(),))
        connection.execute(
            "INSERT INTO oauth_states (state_hash, provider, user_id, expires_at) VALUES (?, ?, ?, ?)",
            (token_digest(state), provider, user["id"], (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()),
        )
    return RedirectResponse(
        social_oauth.build_authorization_url(provider, settings, redirect_uri, state),
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/api/social/oauth/{provider}/callback")
async def finish_social_oauth(
    provider: str,
    state: Optional[str] = None,
    code: Optional[str] = None,
    error: Optional[str] = None,
) -> RedirectResponse:
    def finish(reason: str) -> RedirectResponse:
        return RedirectResponse(
            f"{public_frontend_url()}/accounts?social={reason}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not state:
        return finish("invalid_state")
    with connect_database() as connection:
        state_row = connection.execute(
            "SELECT user_id FROM oauth_states WHERE state_hash = ? AND provider = ? AND expires_at > ?",
            (token_digest(state), provider, utc_now()),
        ).fetchone()
        connection.execute("DELETE FROM oauth_states WHERE state_hash = ?", (token_digest(state),))
    if state_row is None:
        return finish("invalid_state")
    if error or not code:
        return finish("cancelled")

    redirect_uri = f"{public_api_url()}/api/social/oauth/{provider}/callback"
    try:
        settings = social_oauth.get_provider_settings(provider)
        token_data = await social_oauth.exchange_authorization_code(provider, settings, code, redirect_uri)
        accounts = await social_oauth.retrieve_connected_accounts(provider, token_data)
        if not accounts:
            return finish("no_accounts")
        cipher = token_cipher()
        now = utc_now()
        with connect_database() as connection:
            for account in accounts:
                encrypted_tokens = cipher.encrypt(json.dumps(account["tokens"]).encode("utf-8")).decode("ascii")
                connection.execute(
                    """
                    INSERT INTO social_accounts (
                        id, user_id, provider, platform, account_id, account_name,
                        account_type, encrypted_tokens, expires_at, connected_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, platform, account_id) DO UPDATE SET
                        provider = excluded.provider,
                        account_name = excluded.account_name,
                        account_type = excluded.account_type,
                        encrypted_tokens = excluded.encrypted_tokens,
                        expires_at = excluded.expires_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        str(uuid4()), state_row["user_id"], provider, account["platform"],
                        account["account_id"], account["account_name"], account["account_type"],
                        encrypted_tokens, account["tokens"].get("expires_at"), now, now,
                    ),
                )
    except httpx.HTTPStatusError as failure:
        # Never log the exception itself: its text includes the request URL, which
        # contains the app secret and authorization code during the token exchange.
        logger.warning(
            "%s OAuth connection failed: %s", provider, social_oauth.graph_error_summary(failure.response)
        )
        return finish("connect_failed")
    except httpx.HTTPError as failure:
        logger.warning("%s OAuth connection failed: network error %s", provider, type(failure).__name__)
        return finish("connect_failed")
    except (RuntimeError, ValueError, KeyError) as failure:
        logger.warning("%s OAuth connection failed: %s: %s", provider, type(failure).__name__, failure)
        return finish("connect_failed")
    logger.info("%s OAuth connected %d account(s) for user %s", provider, len(accounts), state_row["user_id"])
    return finish("connected")


@router.delete("/api/social/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_social_account(
    account_id: str,
    user: Annotated[Row, Depends(get_current_user)],
) -> Response:
    with connect_database() as connection:
        result = connection.execute(
            "DELETE FROM social_accounts WHERE id = ? AND user_id = ?",
            (account_id, user["id"]),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Social account not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
