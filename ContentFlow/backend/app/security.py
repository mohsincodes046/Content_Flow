from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi import Cookie, HTTPException, Request, Response, status
from pwdlib import PasswordHash

from app.config import SESSION_COOKIE, SESSION_LIFETIME, env_int
from app.database import connect_database, utc_now
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

    On Render, requests arrive through Render's proxy, which appends the real
    client address as the last X-Forwarded-For entry; earlier entries are
    client-controlled and must not be trusted.
    """
    if os.environ.get("RENDER"):
        forwarded = request.headers.get("x-forwarded-for", "")
        candidates = [part.strip() for part in forwarded.split(",") if part.strip()]
        if candidates:
            return candidates[-1]
    return request.client.host if request.client else "unknown"


def count_recent_events(
    connection: sqlite3.Connection, bucket: str, subject: str, window: timedelta, now: datetime
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
        connection.execute("BEGIN IMMEDIATE")
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


def create_session(user_id: str, response: Response) -> None:
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
            INSERT INTO sessions (id, user_id, token_hash, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (str(uuid4()), user_id, token_digest(raw_token), expires_at.isoformat(), now.isoformat()),
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


def get_current_user(
    session_token: Annotated[Optional[str], Cookie(alias=SESSION_COOKIE)] = None,
) -> sqlite3.Row:
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to access this resource.",
        )
    now = utc_now()
    with connect_database() as connection:
        row = connection.execute(
            """
            SELECT users.id, users.email, users.full_name, workspaces.name AS workspace_name
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            JOIN memberships ON memberships.user_id = users.id AND memberships.role = 'owner'
            JOIN workspaces ON workspaces.id = memberships.workspace_id
            WHERE sessions.token_hash = ? AND sessions.expires_at > ?
            LIMIT 1
            """,
            (token_digest(session_token), now),
        ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your session has expired. Sign in again.",
        )
    return row


def session_response(user: sqlite3.Row) -> SessionResponse:
    return SessionResponse(
        id=user["id"],
        email=user["email"],
        full_name=user["full_name"],
        workspace_name=user["workspace_name"],
    )
