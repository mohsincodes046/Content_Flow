"""Social account connections: OAuth, account selection, health checks, Meta callbacks."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Optional
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Response, status
from fastapi.responses import RedirectResponse

from app import meta_graph, social_oauth
from app.config import public_api_url, public_frontend_url, publisher_is_enabled
from app.database import DatabaseConnection, Row, connect_database, utc_now
from app.schemas import (
    ConnectionCandidate,
    ConnectionSelection,
    PendingConnection,
    SocialAccountResponse,
    SocialProviderStatus,
)
from app.security import record_audit, require_content_role, require_manager, token_cipher, token_digest

logger = logging.getLogger(__name__)
router = APIRouter()
PENDING_CONNECTION_LIFETIME = timedelta(minutes=30)


def account_response(row: Row) -> SocialAccountResponse:
    details = json.loads(row["details_json"]) if row.get("details_json") else {}
    return SocialAccountResponse(
        id=row["id"],
        platform=row["platform"],
        account_id=row["account_id"],
        account_name=row["account_name"],
        account_type=row["account_type"],
        connected_at=row["connected_at"],
        expires_at=row["expires_at"],
        status=row.get("status") or "active",
        last_error=row.get("last_error"),
        last_checked_at=row.get("last_checked_at"),
        profile_picture_url=row.get("profile_picture_url"),
        parent_account_id=row.get("parent_account_id"),
        can_publish=details.get("can_publish"),
        followers_count=details.get("followers_count"),
        linked_page_name=details.get("linked_page_name"),
    )


def mark_account_status(connection: DatabaseConnection, account_row_id: str, error: Optional[meta_graph.GraphError]) -> None:
    """Record the outcome of using an account's token: healthy, or needing reconnection."""
    if error is not None and error.needs_reconnect:
        connection.execute(
            "UPDATE social_accounts SET status = 'needs_reconnect', last_error = ?, last_checked_at = ? WHERE id = ?",
            (error.message[:500], utc_now(), account_row_id),
        )
    elif error is None:
        connection.execute(
            "UPDATE social_accounts SET status = 'active', last_error = NULL, last_checked_at = ? WHERE id = ?",
            (utc_now(), account_row_id),
        )


@router.get("/api/social/providers", response_model=list[SocialProviderStatus])
def list_social_providers(
    user: Annotated[Row, Depends(require_content_role)],
) -> list[SocialProviderStatus]:
    with connect_database() as connection:
        rows = connection.execute(
            "SELECT * FROM social_accounts WHERE workspace_id = ? ORDER BY platform, account_name",
            (user["workspace_id"],),
        ).fetchall()
    accounts_by_provider: dict[str, list[SocialAccountResponse]] = {}
    for row in rows:
        accounts_by_provider.setdefault(row["provider"], []).append(account_response(row))

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
    user: Annotated[Row, Depends(require_manager)],
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
            "INSERT INTO oauth_states (state_hash, provider, user_id, workspace_id, expires_at) VALUES (?, ?, ?, ?, ?)",
            (token_digest(state), provider, user["id"], user["workspace_id"],
             (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()),
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
    def finish(reason: str, connection_id: Optional[str] = None) -> RedirectResponse:
        suffix = f"&connection={connection_id}" if connection_id else ""
        return RedirectResponse(
            f"{public_frontend_url()}/accounts?social={reason}{suffix}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    if not state:
        return finish("invalid_state")
    with connect_database() as connection:
        state_row = connection.execute(
            "SELECT user_id, workspace_id FROM oauth_states WHERE state_hash = ? AND provider = ? AND expires_at > ?",
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
        discovered = await social_oauth.retrieve_connected_accounts(provider, token_data)
    except httpx.HTTPStatusError as failure:
        # Never log the exception itself: its text includes the request URL, which
        # contains the app secret and authorization code during the token exchange.
        logger.warning("%s OAuth connection failed: %s", provider, social_oauth.graph_error_summary(failure.response))
        return finish("connect_failed")
    except httpx.HTTPError as failure:
        logger.warning("%s OAuth connection failed: network error %s", provider, type(failure).__name__)
        return finish("connect_failed")
    except meta_graph.GraphError as failure:
        logger.warning("%s account discovery failed: %s (code %s)", provider, failure.message, failure.code)
        return finish("missing_permissions" if failure.missing_permission else "connect_failed")
    except (RuntimeError, ValueError, KeyError) as failure:
        logger.warning("%s OAuth connection failed: %s: %s", provider, type(failure).__name__, failure)
        return finish("connect_failed")

    if not discovered["accounts"]:
        return finish("no_accounts")
    connection_id = str(uuid4())
    payload = token_cipher().encrypt(json.dumps(discovered).encode("utf-8")).decode("ascii")
    now = datetime.now(timezone.utc)
    with connect_database() as connection:
        connection.execute("DELETE FROM oauth_connections WHERE expires_at <= ?", (now.isoformat(),))
        connection.execute(
            "INSERT INTO oauth_connections (id, workspace_id, user_id, provider, encrypted_payload, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (connection_id, state_row["workspace_id"], state_row["user_id"], provider, payload, now.isoformat(),
             (now + PENDING_CONNECTION_LIFETIME).isoformat()),
        )
    logger.info("%s OAuth found %d account(s); waiting for selection", provider, len(discovered["accounts"]))
    return finish("select", connection_id)


def _pending(connection: DatabaseConnection, connection_id: str, workspace_id: str) -> tuple[Row, dict[str, Any]]:
    row = connection.execute(
        "SELECT * FROM oauth_connections WHERE id = ? AND workspace_id = ? AND expires_at > ?",
        (connection_id, workspace_id, utc_now()),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="This sign-in has expired. Connect the account again.")
    return row, json.loads(token_cipher().decrypt(row["encrypted_payload"].encode("ascii")))


@router.get("/api/social/connections/{connection_id}", response_model=PendingConnection)
def pending_connection(connection_id: str, user: Annotated[Row, Depends(require_manager)]) -> PendingConnection:
    with connect_database() as connection:
        row, discovered = _pending(connection, connection_id, user["workspace_id"])
        existing = {
            (r["platform"], r["account_id"])
            for r in connection.execute(
                "SELECT platform, account_id FROM social_accounts WHERE workspace_id = ?", (user["workspace_id"],)
            ).fetchall()
        }
    candidates = [
        ConnectionCandidate(
            key=f"{account['platform']}:{account['account_id']}",
            platform=account["platform"],
            account_id=account["account_id"],
            account_name=account["account_name"],
            account_type=account["account_type"],
            profile_picture_url=account.get("profile_picture_url"),
            linked_page_name=(account.get("details") or {}).get("linked_page_name"),
            followers_count=(account.get("details") or {}).get("followers_count"),
            can_publish=bool((account.get("details") or {}).get("can_publish", True)),
            already_connected=(account["platform"], account["account_id"]) in existing,
        )
        for account in discovered["accounts"]
    ]
    return PendingConnection(id=row["id"], provider=row["provider"],
                             signed_in_as=discovered.get("external_user_name"), candidates=candidates)


@router.post("/api/social/connections/{connection_id}/select", response_model=list[SocialAccountResponse])
def select_accounts(
    connection_id: str, payload: ConnectionSelection, user: Annotated[Row, Depends(require_manager)]
) -> list[SocialAccountResponse]:
    cipher = token_cipher()
    with connect_database() as connection:
        connection.lock_for_write()
        row, discovered = _pending(connection, connection_id, user["workspace_id"])
        by_key = {f"{a['platform']}:{a['account_id']}": a for a in discovered["accounts"]}
        unknown = [key for key in payload.keys if key not in by_key]
        if unknown:
            raise HTTPException(status_code=400, detail="Choose accounts from this sign-in only.")
        now = utc_now()
        chosen = [by_key[key] for key in dict.fromkeys(payload.keys)]
        # Pages first, so each Instagram account can point at its Page's row.
        chosen.sort(key=lambda account: account["platform"] != "facebook")
        page_rows: dict[str, str] = {}
        saved_ids = []
        for account in chosen:
            parent_row = page_rows.get(account.get("parent_account_id") or "")
            if parent_row is None and account.get("parent_account_id"):
                existing_page = connection.execute(
                    "SELECT id FROM social_accounts WHERE workspace_id = ? AND platform = 'facebook' AND account_id = ?",
                    (user["workspace_id"], account["parent_account_id"]),
                ).fetchone()
                parent_row = existing_page["id"] if existing_page else None
            connection.execute(
                """
                INSERT INTO social_accounts (
                    id, user_id, workspace_id, provider, platform, account_id, account_name, account_type,
                    encrypted_tokens, expires_at, connected_at, updated_at, status, last_error, last_checked_at,
                    profile_picture_url, parent_account_id, external_user_id, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', NULL, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, platform, account_id) DO UPDATE SET
                    provider = excluded.provider, account_name = excluded.account_name,
                    account_type = excluded.account_type, encrypted_tokens = excluded.encrypted_tokens,
                    expires_at = excluded.expires_at, updated_at = excluded.updated_at, status = 'active',
                    last_error = NULL, last_checked_at = excluded.last_checked_at,
                    profile_picture_url = excluded.profile_picture_url,
                    parent_account_id = excluded.parent_account_id,
                    external_user_id = excluded.external_user_id, details_json = excluded.details_json
                """,
                (
                    str(uuid4()), user["id"], user["workspace_id"], row["provider"], account["platform"],
                    account["account_id"], account["account_name"], account["account_type"],
                    cipher.encrypt(json.dumps(account["tokens"]).encode("utf-8")).decode("ascii"),
                    account["tokens"].get("expires_at"), now, now, now, account.get("profile_picture_url"),
                    parent_row, discovered.get("external_user_id"), json.dumps(account.get("details") or {}),
                ),
            )
            saved = connection.execute(
                "SELECT id FROM social_accounts WHERE workspace_id = ? AND platform = ? AND account_id = ?",
                (user["workspace_id"], account["platform"], account["account_id"]),
            ).fetchone()
            saved_ids.append(saved["id"])
            if account["platform"] == "facebook":
                page_rows[account["account_id"]] = saved["id"]
        connection.execute("DELETE FROM oauth_connections WHERE id = ?", (connection_id,))
        record_audit(connection, user["workspace_id"], user["id"], "social.connected", "social_accounts", None,
                     {"accounts": [f"{a['platform']}:{a['account_name']}" for a in chosen]})
        placeholders = ",".join("?" for _ in saved_ids)
        rows = connection.execute(
            f"SELECT * FROM social_accounts WHERE id IN ({placeholders}) ORDER BY platform, account_name", saved_ids
        ).fetchall()
    return [account_response(r) for r in rows]


@router.delete("/api/social/connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def discard_connection(connection_id: str, user: Annotated[Row, Depends(require_manager)]) -> Response:
    with connect_database() as connection:
        connection.execute(
            "DELETE FROM oauth_connections WHERE id = ? AND workspace_id = ?", (connection_id, user["workspace_id"])
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def account_token(row: Row) -> str:
    tokens = json.loads(token_cipher().decrypt(row["encrypted_tokens"].encode("ascii")))
    token = tokens.get("access_token")
    if not isinstance(token, str) or not token:
        raise meta_graph.GraphError("No access token is stored for this account. Reconnect it.", code=190)
    return token


@router.post("/api/social/accounts/{account_id}/check", response_model=SocialAccountResponse)
async def check_social_account(account_id: str, user: Annotated[Row, Depends(require_content_role)]) -> SocialAccountResponse:
    with connect_database() as connection:
        row = connection.execute(
            "SELECT * FROM social_accounts WHERE id = ? AND workspace_id = ?", (account_id, user["workspace_id"])
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Social account not found.")
    failure: Optional[meta_graph.GraphError] = None
    try:
        await meta_graph.check_account(row["platform"], row["account_id"], account_token(row))
    except meta_graph.GraphError as error:
        failure = error
    with connect_database() as connection:
        mark_account_status(connection, row["id"], failure)
        if failure is not None and not failure.needs_reconnect:
            connection.execute(
                "UPDATE social_accounts SET last_error = ?, last_checked_at = ? WHERE id = ?",
                (failure.message[:500], utc_now(), row["id"]),
            )
        updated = connection.execute("SELECT * FROM social_accounts WHERE id = ?", (row["id"],)).fetchone()
    return account_response(updated)


@router.delete("/api/social/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_social_account(
    account_id: str,
    user: Annotated[Row, Depends(require_manager)],
) -> Response:
    with connect_database() as connection:
        row = connection.execute(
            "SELECT platform, account_name FROM social_accounts WHERE id = ? AND workspace_id = ?",
            (account_id, user["workspace_id"]),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Social account not found.")
        connection.execute("UPDATE social_accounts SET parent_account_id = NULL WHERE parent_account_id = ?", (account_id,))
        connection.execute("DELETE FROM social_accounts WHERE id = ?", (account_id,))
        record_audit(connection, user["workspace_id"], user["id"], "social.disconnected", "social_account", account_id,
                     {"account": f"{row['platform']}:{row['account_name']}"})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Meta platform callbacks (configured in the Meta app dashboard) --------------------------

def parse_signed_request(signed_request: str) -> dict[str, Any]:
    """Verify and decode Meta's `signed_request` (HMAC-SHA256 with the app secret)."""
    secret = os.environ.get("META_APP_SECRET", "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="Meta callbacks are not configured.")
    try:
        encoded_signature, encoded_payload = signed_request.split(".", 1)
        decode = lambda part: base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))  # noqa: E731
        signature = decode(encoded_signature)
        payload = json.loads(decode(encoded_payload))
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=400, detail="Malformed signed request.") from error
    expected = hmac.new(secret.encode("utf-8"), encoded_payload.encode("ascii"), hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected) or str(payload.get("algorithm", "")).upper() != "HMAC-SHA256":
        raise HTTPException(status_code=401, detail="Invalid signed request.")
    if not payload.get("user_id"):
        raise HTTPException(status_code=400, detail="Signed request has no user.")
    return payload


@router.post("/api/social/meta/deauthorize")
def meta_deauthorize(signed_request: Annotated[str, Form()]) -> dict[str, str]:
    """A person removed the app in Facebook settings: their tokens no longer work."""
    meta_user = str(parse_signed_request(signed_request)["user_id"])
    with connect_database() as connection:
        connection.execute(
            "UPDATE social_accounts SET status = 'needs_reconnect', "
            "last_error = 'Access was removed in Facebook settings. Reconnect to keep publishing.', last_checked_at = ? "
            "WHERE provider = 'meta' AND external_user_id = ?",
            (utc_now(), meta_user),
        )
    return {"status": "ok"}


@router.post("/api/social/meta/data-deletion")
def meta_data_deletion(signed_request: Annotated[str, Form()]) -> dict[str, str]:
    """Meta data-deletion callback: delete every stored token and account for that person."""
    meta_user = str(parse_signed_request(signed_request)["user_id"])
    code = secrets.token_urlsafe(12)
    with connect_database() as connection:
        connection.execute(
            "UPDATE social_accounts SET parent_account_id = NULL WHERE parent_account_id IN "
            "(SELECT id FROM social_accounts WHERE provider = 'meta' AND external_user_id = ?)",
            (meta_user,),
        )
        deleted = connection.execute(
            "DELETE FROM social_accounts WHERE provider = 'meta' AND external_user_id = ?", (meta_user,)
        ).rowcount
        connection.execute(
            "INSERT INTO data_deletion_requests (confirmation_code, provider, external_user_id, accounts_deleted, created_at) "
            "VALUES (?, 'meta', ?, ?, ?)",
            (code, meta_user, deleted, utc_now()),
        )
    return {"url": f"{public_api_url()}/api/social/meta/data-deletion/{code}", "confirmation_code": code}


@router.get("/api/social/meta/data-deletion/{code}")
def meta_data_deletion_status(code: str) -> dict[str, Any]:
    with connect_database() as connection:
        row = connection.execute(
            "SELECT accounts_deleted, created_at FROM data_deletion_requests WHERE confirmation_code = ?", (code,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown confirmation code.")
    return {"status": "completed", "accounts_deleted": row["accounts_deleted"], "completed_at": row["created_at"]}
