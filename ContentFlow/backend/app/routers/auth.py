from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Optional
from uuid import uuid4

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError

from app.config import SESSION_COOKIE, env_int
from app.database import Row, connect_database, utc_now
from app.schemas import LoginCreate, PasswordChange, RegistrationCreate, SessionResponse
from app.security import (
    DUMMY_PASSWORD_HASH,
    PASSWORD_HASHER,
    check_rate_limit,
    client_ip,
    create_session,
    get_current_user,
    record_rate_limit_event,
    session_response,
    token_digest,
)

router = APIRouter()


@router.post("/api/auth/register", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegistrationCreate, request: Request, response: Response) -> SessionResponse:
    check_rate_limit(
        "register_ip",
        client_ip(request),
        env_int("CONTENT_FLOW_REGISTER_PER_HOUR_LIMIT", 5),
        timedelta(hours=1),
        detail="Too many accounts were created from this network. Please try again later.",
    )
    user_id = str(uuid4())
    workspace_id = str(uuid4())
    created_at = utc_now()
    email = str(payload.email).strip().lower()
    try:
        with connect_database() as connection:
            connection.execute(
                """
                INSERT INTO users (id, email, full_name, password_hash, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    email,
                    payload.full_name,
                    PASSWORD_HASHER.hash(payload.password),
                    created_at,
                ),
            )
            connection.execute(
                "INSERT INTO workspaces (id, name, created_at) VALUES (?, ?, ?)",
                (workspace_id, payload.workspace_name, created_at),
            )
            connection.execute(
                "INSERT INTO memberships (user_id, workspace_id, role) VALUES (?, ?, 'owner')",
                (user_id, workspace_id),
            )
            user = connection.execute(
                """
                SELECT users.id, users.email, users.full_name, workspaces.name AS workspace_name
                FROM users JOIN memberships ON memberships.user_id = users.id
                JOIN workspaces ON workspaces.id = memberships.workspace_id
                WHERE users.id = ? AND memberships.role = 'owner'
                """,
                (user_id,),
            ).fetchone()
    except IntegrityError as error:
        # Works on SQLite and PostgreSQL: decide by looking, not by parsing driver messages.
        with connect_database() as connection:
            exists = connection.execute("SELECT 1 FROM users WHERE lower(email) = ?", (email,)).fetchone()
        if exists is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists.",
            ) from error
        raise
    if user is None:
        raise RuntimeError("The newly created account could not be loaded.")
    create_session(user_id, response)
    return session_response(user)


@router.post("/api/auth/login", response_model=SessionResponse)
def login(payload: LoginCreate, request: Request, response: Response) -> SessionResponse:
    email = str(payload.email).strip().lower()
    login_window = timedelta(minutes=15)
    too_many = "Too many sign-in attempts. Please wait a few minutes and try again."
    check_rate_limit(
        "login_ip", client_ip(request), env_int("CONTENT_FLOW_LOGIN_PER_IP_LIMIT", 20), login_window,
        detail=too_many,
    )
    failed_limit = env_int("CONTENT_FLOW_LOGIN_FAILURES_PER_EMAIL_LIMIT", 5)
    check_rate_limit("login_failed_email", email, failed_limit, login_window, record=False, detail=too_many)
    with connect_database() as connection:
        user = connection.execute(
            """
            SELECT users.id, users.email, users.full_name, users.password_hash,
                   workspaces.name AS workspace_name
            FROM users JOIN memberships ON memberships.user_id = users.id
            JOIN workspaces ON workspaces.id = memberships.workspace_id
            WHERE users.email = ? AND memberships.role = 'owner'
            LIMIT 1
            """,
            (email,),
        ).fetchone()

    # Hash even for unknown emails so response timing does not reveal which accounts exist.
    password_hash = user["password_hash"] if user is not None else DUMMY_PASSWORD_HASH
    password_ok = PASSWORD_HASHER.verify(payload.password, password_hash)
    if user is None or not password_ok:
        record_rate_limit_event("login_failed_email", email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect.",
        )
    create_session(user["id"], response)
    return session_response(user)


@router.get("/api/auth/me", response_model=SessionResponse)
def current_session(
    user: Annotated[Row, Depends(get_current_user)],
) -> SessionResponse:
    return session_response(user)


@router.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    session_token: Annotated[Optional[str], Cookie(alias=SESSION_COOKIE)] = None,
) -> Response:
    if session_token:
        with connect_database() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash = ?",
                (token_digest(session_token),),
            )
    logout_response = Response(status_code=status.HTTP_204_NO_CONTENT)
    logout_response.delete_cookie(key=SESSION_COOKIE, path="/", httponly=True, samesite="lax")
    return logout_response


@router.post("/api/auth/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChange,
    user: Annotated[Row, Depends(get_current_user)],
    session_token: Annotated[Optional[str], Cookie(alias=SESSION_COOKIE)] = None,
) -> Response:
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to change your password.",
        )

    with connect_database() as connection:
        row = connection.execute(
            "SELECT password_hash FROM users WHERE id = ?",
            (user["id"],),
        ).fetchone()
        if row is None:
            raise RuntimeError("The signed-in account could not be loaded.")
        if not PASSWORD_HASHER.verify(payload.current_password, row["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Your current Content-Flow password is incorrect.",
            )
        if PASSWORD_HASHER.verify(payload.new_password, row["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Choose a different password from your current one.",
            )

        connection.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (PASSWORD_HASHER.hash(payload.new_password), user["id"]),
        )
        connection.execute(
            "DELETE FROM sessions WHERE user_id = ? AND token_hash != ?",
            (user["id"], token_digest(session_token)),
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
