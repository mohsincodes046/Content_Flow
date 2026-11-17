from __future__ import annotations

import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi import Cookie, Depends, HTTPException, Request, Response, status
from pwdlib import PasswordHash

from app.config import SESSION_COOKIE, SESSION_LIFETIME, env_int
from app.database import DatabaseConnection, Row, connect_database, utc_now
from app.schemas import SessionResponse

PASSWORD_HASHER = PasswordHash.recommended()
DUMMY_PASSWORD_HASH = PASSWORD_HASHER.hash(secrets.token_urlsafe(16))

def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_cipher() -> Fernet:
    key = os.environ.get("CONTENT_FLOW_TOKEN_ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError("Configure CONTENT_FLOW_TOKEN_ENCRYPTION_KEY on the backend.")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as error:
        raise RuntimeError("CONTENT_FLOW_TOKEN_ENCRYPTION_KEY must be a valid Fernet key.") from error



RATE_LIMIT_RETENTION = timedelta(days=2)



def client_ip(request: Request) -> str:
    """Best-effort client address.

    Each trusted proxy in front of the API appends the address it received the
    request from to X-Forwarded-For, so with N trusted proxies the client is the
    N-th entry from the right; entries further left are client-controlled.
    CONTENT_FLOW_TRUSTED_PROXY_HOPS sets N (Render: 1; Vercel rewrite -> Koyeb: 2).
    Defaults to 1 on Render, otherwise 0 (use the TCP peer address).
    """
    raw = os.environ.get("CONTENT_FLOW_TRUSTED_PROXY_HOPS", "").strip()
    hops = int(raw) if raw.isdigit() else (1 if os.environ.get("RENDER") else 0)
    if hops:
        forwarded = request.headers.get("x-forwarded-for", "")
        candidates = [part.strip() for part in forwarded.split(",") if part.strip()]
        if candidates:
            return candidates[-hops] if len(candidates) >= hops else candidates[0]
    return request.client.host if request.client else "unknown"


def count_recent_events(
    connection: DatabaseConnection, bucket: str, subject: str, window: timedelta, now: datetime
) -> tuple[int, Optional[str]]:
    row = connection.execute(
        """
        SELECT COUNT(*) AS total, MIN(created_at) AS oldest FROM rate_limit_events
        WHERE bucket = ? AND subject = ? AND created_at > ?
        """,
        (bucket, subject, (now - window).isoformat()),
    ).fetchone()
    return row["total"], row["oldest"]


def rate_limited(retry_after: datetime, now: datetime, detail: str) -> HTTPException:
    seconds = max(1, int((retry_after - now).total_seconds()) + 1)
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=detail,
        headers={"Retry-After": str(seconds)},
    )


def check_rate_limit(
    bucket: str,
    subject: str,
    limit: int,
    window: timedelta,
    *,
    record: bool = True,
    detail: str = "Too many requests. Please wait and try again.",
) -> None:
    """Raise 429 when `subject` already has `limit` events in `window`; otherwise
    optionally record one more event. Runs in one write transaction so
    concurrent requests cannot both pass the final slot."""
    now = datetime.now(timezone.utc)
    with connect_database() as connection:
        connection.lock_for_write()
        connection.execute(
            "DELETE FROM rate_limit_events WHERE created_at < ?",
            ((now - RATE_LIMIT_RETENTION).isoformat(),),
        )
        total, oldest = count_recent_events(connection, bucket, subject, window, now)
        if total >= limit and oldest is not None:
            raise rate_limited(datetime.fromisoformat(oldest) + window, now, detail)
        if record:
            connection.execute(
                "INSERT INTO rate_limit_events (bucket, subject, created_at) VALUES (?, ?, ?)",
                (bucket, subject, now.isoformat()),
            )


def record_rate_limit_event(bucket: str, subject: str) -> None:
    with connect_database() as connection:
        connection.execute(
            "INSERT INTO rate_limit_events (bucket, subject, created_at) VALUES (?, ?, ?)",
            (bucket, subject, utc_now()),
        )


def ai_limits() -> tuple[int, int]:
    return (
        env_int("CONTENT_FLOW_AI_PER_MINUTE_LIMIT", 10),
        env_int("CONTENT_FLOW_AI_DAILY_LIMIT", 50),
    )


def create_session(user_id: str, response: Response, workspace_id: Optional[str] = None) -> str:
    """Start a session (cookie set on `response`); returns the raw session token."""
    raw_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = now + SESSION_LIFETIME
    with connect_database() as connection:
        connection.execute(
            "DELETE FROM sessions WHERE expires_at <= ?",
            (now.isoformat(),),
        )
        connection.execute(
            """
            INSERT INTO sessions (id, user_id, token_hash, expires_at, created_at, active_workspace_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (str(uuid4()), user_id, token_digest(raw_token), expires_at.isoformat(), now.isoformat(), workspace_id),
        )
    response.set_cookie(
        key=SESSION_COOKIE,
        value=raw_token,
        max_age=int(SESSION_LIFETIME.total_seconds()),
        httponly=True,
        secure=os.environ.get("CONTENT_FLOW_COOKIE_SECURE", "false").lower() == "true",
        samesite="lax",
        path="/",
    )
    return raw_token


def load_session_user(raw_token: str) -> Row:
    return get_current_user(session_token=raw_token)


ROLES = ("owner", "admin", "editor", "client")
MANAGERS = ("owner", "admin")             # members, settings, social accounts
CONTENT_ROLES = ("owner", "admin", "editor")  # create, edit and schedule content
REVIEWERS = ("owner", "admin", "client")  # approve, reject, request changes


def user_workspaces(connection: DatabaseConnection, user_id: str) -> list[Row]:
    return connection.execute(
        """
        SELECT workspaces.id, workspaces.name, memberships.role
        FROM memberships JOIN workspaces ON workspaces.id = memberships.workspace_id
        WHERE memberships.user_id = ?
        ORDER BY CASE memberships.role WHEN 'owner' THEN 0 ELSE 1 END, memberships.created_at, workspaces.name
        """,
        (user_id,),
    ).fetchall()


def get_current_user(
    session_token: Annotated[Optional[str], Cookie(alias=SESSION_COOKIE)] = None,
) -> Row:
    """The signed-in user and their active workspace.

    Keys: id, email, full_name, session_id, workspace_id, workspace_name, role.
    The workspace keys are None when the user belongs to no workspace. The
    membership is re-checked on every request, so a removed member loses access
    immediately; if the remembered workspace is gone, the next one is used.
    """
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to access this resource.",
        )
    now = utc_now()
    with connect_database() as connection:
        session = connection.execute(
            """
            SELECT users.id, users.email, users.full_name, sessions.id AS session_id,
                   sessions.active_workspace_id
            FROM sessions JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = ? AND sessions.expires_at > ?
            """,
            (token_digest(session_token), now),
        ).fetchone()
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Your session has expired. Sign in again.",
            )
        workspaces = user_workspaces(connection, session["id"])
        active = next((w for w in workspaces if w["id"] == session["active_workspace_id"]), None)
        if active is None and workspaces:
            active = workspaces[0]
        if (active["id"] if active else None) != session["active_workspace_id"]:
            connection.execute(
                "UPDATE sessions SET active_workspace_id = ? WHERE id = ?",
                (active["id"] if active else None, session["session_id"]),
            )
    return {
        "id": session["id"],
        "email": session["email"],
        "full_name": session["full_name"],
        "session_id": session["session_id"],
        "workspace_id": active["id"] if active else None,
        "workspace_name": active["name"] if active else None,
        "role": active["role"] if active else None,
    }


def require_roles(*roles: str):  # type: ignore[no-untyped-def]
    """Dependency: a signed-in user whose role in the active workspace is one of `roles`."""
    allowed = set(roles)

    def dependency(user: Annotated[Row, Depends(get_current_user)]) -> Row:
        if user["workspace_id"] is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Create or join a workspace first.")
        if user["role"] not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your role in this workspace does not allow this action.",
            )
        return user

    dependency.__name__ = f"require_{'_'.join(sorted(allowed))}"
    return dependency


require_member = require_roles(*ROLES)
require_manager = require_roles(*MANAGERS)
require_content_role = require_roles(*CONTENT_ROLES)
require_reviewer = require_roles(*REVIEWERS)


def record_audit(
    connection: DatabaseConnection,
    workspace_id: str,
    actor_user_id: Optional[str],
    action: str,
    target_type: str,
    target_id: Optional[str] = None,
    details: Optional[dict] = None,
) -> None:
    connection.execute(
        """
        INSERT INTO audit_log (id, workspace_id, actor_user_id, action, target_type, target_id, created_at, details_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (str(uuid4()), workspace_id, actor_user_id, action, target_type, target_id, utc_now(),
         json.dumps(details) if details else None),
    )


def session_response(user: Row) -> SessionResponse:
    with connect_database() as connection:
        workspaces = user_workspaces(connection, user["id"])
    return SessionResponse(
        id=user["id"],
        email=user["email"],
        full_name=user["full_name"],
        workspace_id=user.get("workspace_id"),
        workspace_name=user.get("workspace_name"),
        role=user.get("role"),
        workspaces=[{"id": w["id"], "name": w["name"], "role": w["role"]} for w in workspaces],
    )
