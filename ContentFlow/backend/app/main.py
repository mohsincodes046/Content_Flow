from __future__ import annotations

import json
import os
import hashlib
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal, Optional
from uuid import uuid4

from fastapi import Cookie, Depends, FastAPI, File, HTTPException, Query, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pwdlib import PasswordHash
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


Platform = Literal["instagram", "facebook", "linkedin", "youtube", "tiktok"]
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
SESSION_LIFETIME = timedelta(days=7)
SESSION_COOKIE = "content_flow_session"
ALLOWED_MEDIA_TYPES = ("image/", "video/")
PASSWORD_HASHER = PasswordHash.recommended()
DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR = Path(os.environ.get("CONTENT_FLOW_DATA_DIR", str(DEFAULT_DATA_DIR))).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
DATABASE_PATH = DATA_DIR / "content_flow.sqlite3"
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "CONTENT_FLOW_ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if origin.strip()
]


class SubmissionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign: str = Field(default="", max_length=100)
    audience: str = Field(min_length=1, max_length=160)
    instructions: str = Field(min_length=1, max_length=2000)
    language: str = Field(min_length=1, max_length=60)
    platforms: list[Platform] = Field(min_length=1, max_length=5)
    asset_ids: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("campaign", "audience", "instructions", "language", mode="before")
    @classmethod
    def strip_text_fields(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("Text fields must be strings.")
        return value.strip()

    @field_validator("platforms")
    @classmethod
    def reject_duplicate_platforms(cls, value: list[Platform]) -> list[Platform]:
        if len(value) != len(set(value)):
            raise ValueError("Each platform can only be selected once.")
        return value

    @field_validator("asset_ids")
    @classmethod
    def reject_duplicate_assets(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Each uploaded asset can only be attached once.")
        return value


class RegistrationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str = Field(min_length=1, max_length=100)
    workspace_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("full_name", "workspace_name", mode="before")
    @classmethod
    def strip_required_text(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("This field must be text.")
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank.")
        return value


class LoginCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class ScheduledPostCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_name: str = Field(min_length=1, max_length=255)
    date: date
    time: time
    platforms: list[Platform] = Field(min_length=1, max_length=5)
    caption: str = Field(default="", max_length=5000)

    @field_validator("media_name", mode="before")
    @classmethod
    def strip_media_name(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("Media name must be text.")
        value = value.strip()
        if not value:
            raise ValueError("Media name cannot be blank.")
        return value

    @field_validator("time")
    @classmethod
    def require_local_minute_precision(cls, value: time) -> time:
        if value.second or value.microsecond or value.tzinfo is not None:
            raise ValueError("Scheduled times must use local hours and minutes.")
        return value

    @field_validator("platforms")
    @classmethod
    def reject_duplicate_scheduled_platforms(
        cls,
        value: list[Platform],
    ) -> list[Platform]:
        if len(value) != len(set(value)):
            raise ValueError("Each platform can only be selected once.")
        return value


class ScheduledPostBatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    posts: list[ScheduledPostCreate] = Field(min_length=1, max_length=366)


class ScheduledPostDateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: date


class ScheduledPostResponse(BaseModel):
    id: str
    media_name: str
    date: str
    time: str
    platforms: list[Platform]
    caption: str


class AssetResponse(BaseModel):
    id: str
    filename: str
    media_type: str
    size: int


class SubmissionResponse(BaseModel):
    id: str
    campaign: str
    audience: str
    instructions: str
    language: str
    platforms: list[Platform]
    assets: list[AssetResponse]
    status: Literal["submitted"]
    created_at: str


class SessionResponse(BaseModel):
    id: str
    email: str
    full_name: str
    workspace_name: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect_database() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with connect_database() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                full_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS workspaces (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memberships (
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('owner', 'member')),
                PRIMARY KEY (user_id, workspace_id)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS submissions (
                id TEXT PRIMARY KEY,
                campaign TEXT NOT NULL,
                audience TEXT NOT NULL,
                instructions TEXT NOT NULL,
                language TEXT NOT NULL,
                platforms_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('submitted')),
                created_at TEXT NOT NULL,
                user_id TEXT REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS assets (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                media_type TEXT NOT NULL,
                size INTEGER NOT NULL CHECK(size > 0),
                storage_name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                submission_id TEXT REFERENCES submissions(id),
                user_id TEXT REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id TEXT PRIMARY KEY,
                media_name TEXT NOT NULL,
                scheduled_date TEXT NOT NULL,
                scheduled_time TEXT NOT NULL,
                platforms_json TEXT NOT NULL,
                caption TEXT NOT NULL,
                created_at TEXT NOT NULL,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS scheduled_posts_user_date_idx
                ON scheduled_posts(user_id, scheduled_date, scheduled_time);
            """
        )
        submission_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(submissions)")
        }
        if "user_id" not in submission_columns:
            connection.execute(
                "ALTER TABLE submissions ADD COLUMN user_id TEXT REFERENCES users(id) ON DELETE CASCADE"
            )
        asset_columns = {row["name"] for row in connection.execute("PRAGMA table_info(assets)")}
        if "user_id" not in asset_columns:
            connection.execute(
                "ALTER TABLE assets ADD COLUMN user_id TEXT REFERENCES users(id) ON DELETE CASCADE"
            )


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_storage()
    yield


app = FastAPI(
    title="Content-Flow API",
    description="Content intake API for the Content-Flow frontend.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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


@app.post("/api/auth/register", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegistrationCreate, response: Response) -> SessionResponse:
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
    except sqlite3.IntegrityError as error:
        if "users.email" in str(error).lower() or "unique constraint failed: users.email" in str(error).lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists.",
            ) from error
        raise
    if user is None:
        raise RuntimeError("The newly created account could not be loaded.")
    create_session(user_id, response)
    return session_response(user)


@app.post("/api/auth/login", response_model=SessionResponse)
def login(payload: LoginCreate, response: Response) -> SessionResponse:
    email = str(payload.email).strip().lower()
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

    if user is None or not PASSWORD_HASHER.verify(payload.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect.",
        )
    create_session(user["id"], response)
    return session_response(user)


@app.get("/api/auth/me", response_model=SessionResponse)
def current_session(
    user: Annotated[sqlite3.Row, Depends(get_current_user)],
) -> SessionResponse:
    return session_response(user)


@app.post("/api/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
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


@app.post("/api/auth/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChange,
    user: Annotated[sqlite3.Row, Depends(get_current_user)],
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


def get_assets(asset_ids: list[str], user_id: str) -> list[AssetResponse]:
    if not asset_ids:
        return []

    placeholders = ",".join("?" for _ in asset_ids)
    with connect_database() as connection:
        rows = connection.execute(
            f"""
            SELECT id, filename, media_type, size, submission_id
            FROM assets
            WHERE id IN ({placeholders}) AND user_id = ?
            """,
            [*asset_ids, user_id],
        ).fetchall()

    by_id = {row["id"]: row for row in rows}
    if len(by_id) != len(asset_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more uploaded assets could not be found.",
        )

    attached_assets = [by_id[asset_id] for asset_id in asset_ids]
    if any(row["submission_id"] is not None for row in attached_assets):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An uploaded asset is already attached to a submission.",
        )

    return [
        AssetResponse(
            id=row["id"],
            filename=row["filename"],
            media_type=row["media_type"],
            size=row["size"],
        )
        for row in attached_assets
    ]


def submission_from_row(
    row: sqlite3.Row,
    assets: list[AssetResponse],
) -> SubmissionResponse:
    return SubmissionResponse(
        id=row["id"],
        campaign=row["campaign"],
        audience=row["audience"],
        instructions=row["instructions"],
        language=row["language"],
        platforms=json.loads(row["platforms_json"]),
        assets=assets,
        status=row["status"],
        created_at=row["created_at"],
    )


def scheduled_post_from_row(row: sqlite3.Row) -> ScheduledPostResponse:
    return ScheduledPostResponse(
        id=row["id"],
        media_name=row["media_name"],
        date=row["scheduled_date"],
        time=row["scheduled_time"],
        platforms=json.loads(row["platforms_json"]),
        caption=row["caption"],
    )


def scheduled_post_conflicts(
    platforms: list[Platform],
    scheduled_date: str,
    scheduled_time: str,
    existing_rows: list[sqlite3.Row],
    *,
    exclude_id: Optional[str] = None,
) -> bool:
    for row in existing_rows:
        if row["id"] == exclude_id:
            continue
        if row["scheduled_date"] != scheduled_date or row["scheduled_time"] != scheduled_time:
            continue
        existing_platforms = set(json.loads(row["platforms_json"]))
        if existing_platforms.intersection(platforms):
            return True
    return False


@app.get("/api/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/scheduled-posts", response_model=list[ScheduledPostResponse])
def list_scheduled_posts(
    user: Annotated[sqlite3.Row, Depends(get_current_user)],
) -> list[ScheduledPostResponse]:
    with connect_database() as connection:
        rows = connection.execute(
            """
            SELECT * FROM scheduled_posts
            WHERE user_id = ?
            ORDER BY scheduled_date, scheduled_time, created_at
            """,
            (user["id"],),
        ).fetchall()
    return [scheduled_post_from_row(row) for row in rows]


@app.post(
    "/api/scheduled-posts",
    response_model=list[ScheduledPostResponse],
    status_code=status.HTTP_201_CREATED,
)
def create_scheduled_posts(
    payload: ScheduledPostBatchCreate,
    user: Annotated[sqlite3.Row, Depends(get_current_user)],
) -> list[ScheduledPostResponse]:
    incoming = payload.posts
    for index, post in enumerate(incoming):
        for other in incoming[index + 1 :]:
            if (
                post.date == other.date
                and post.time == other.time
                and set(post.platforms).intersection(other.platforms)
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Two posts cannot use the same channel at the same time.",
                )

    with connect_database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing_rows = connection.execute(
            "SELECT * FROM scheduled_posts WHERE user_id = ?",
            (user["id"],),
        ).fetchall()
        response_rows: list[sqlite3.Row] = []

        for post in incoming:
            scheduled_date = post.date.isoformat()
            scheduled_time = post.time.strftime("%H:%M")
            same_slot = [
                row
                for row in existing_rows
                if row["scheduled_date"] == scheduled_date
                and row["scheduled_time"] == scheduled_time
                and set(json.loads(row["platforms_json"])).intersection(post.platforms)
            ]
            if same_slot:
                identical = next(
                    (
                        row
                        for row in same_slot
                        if row["media_name"] == post.media_name
                        and row["platforms_json"] == json.dumps(post.platforms)
                        and row["caption"] == post.caption
                    ),
                    None,
                )
                if identical is not None and len(same_slot) == 1:
                    response_rows.append(identical)
                    continue
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A post is already scheduled for one of these channels at that time.",
                )

            post_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO scheduled_posts (
                    id, media_name, scheduled_date, scheduled_time,
                    platforms_json, caption, created_at, user_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    post_id,
                    post.media_name,
                    scheduled_date,
                    scheduled_time,
                    json.dumps(post.platforms),
                    post.caption,
                    utc_now(),
                    user["id"],
                ),
            )
            row = connection.execute(
                "SELECT * FROM scheduled_posts WHERE id = ?",
                (post_id,),
            ).fetchone()
            if row is None:
                raise RuntimeError("The scheduled post could not be read back.")
            response_rows.append(row)
            existing_rows.append(row)

    return [scheduled_post_from_row(row) for row in response_rows]


@app.patch("/api/scheduled-posts/{post_id}", response_model=ScheduledPostResponse)
def reschedule_post(
    post_id: str,
    payload: ScheduledPostDateUpdate,
    user: Annotated[sqlite3.Row, Depends(get_current_user)],
) -> ScheduledPostResponse:
    with connect_database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT * FROM scheduled_posts WHERE id = ? AND user_id = ?",
            (post_id, user["id"]),
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Scheduled post not found.",
            )

        scheduled_date = payload.date.isoformat()
        existing_rows = connection.execute(
            "SELECT * FROM scheduled_posts WHERE user_id = ?",
            (user["id"],),
        ).fetchall()
        if scheduled_post_conflicts(
            json.loads(row["platforms_json"]),
            scheduled_date,
            row["scheduled_time"],
            existing_rows,
            exclude_id=post_id,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A post is already scheduled for one of these channels at that time.",
            )

        connection.execute(
            "UPDATE scheduled_posts SET scheduled_date = ? WHERE id = ? AND user_id = ?",
            (scheduled_date, post_id, user["id"]),
        )
        updated = connection.execute(
            "SELECT * FROM scheduled_posts WHERE id = ?",
            (post_id,),
        ).fetchone()
        if updated is None:
            raise RuntimeError("The rescheduled post could not be read back.")

    return scheduled_post_from_row(updated)


@app.delete("/api/scheduled-posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scheduled_post(
    post_id: str,
    user: Annotated[sqlite3.Row, Depends(get_current_user)],
) -> Response:
    with connect_database() as connection:
        cursor = connection.execute(
            "DELETE FROM scheduled_posts WHERE id = ? AND user_id = ?",
            (post_id, user["id"]),
        )
        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Scheduled post not found.",
            )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post(
    "/api/assets",
    response_model=AssetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_asset(
    file: Annotated[UploadFile, File()],
    user: Annotated[sqlite3.Row, Depends(get_current_user)],
) -> AssetResponse:
    media_type = file.content_type or ""
    if not media_type.startswith(ALLOWED_MEDIA_TYPES):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only image and video files are accepted.",
        )

    asset_id = str(uuid4())
    storage_name = f"{asset_id}.upload"
    destination = UPLOAD_DIR / storage_name
    total_bytes = 0

    try:
        with destination.open("wb") as output:
            while chunk := await file.read(UPLOAD_CHUNK_BYTES):
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="Each uploaded file must be 50 MB or smaller.",
                    )
                output.write(chunk)

        if total_bytes == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The uploaded file is empty.",
            )

        filename = Path(file.filename or "upload").name
        created_at = utc_now()
        with connect_database() as connection:
            connection.execute(
                """
                INSERT INTO assets (id, filename, media_type, size, storage_name, created_at, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (asset_id, filename, media_type, total_bytes, storage_name, created_at, user["id"]),
            )
        return AssetResponse(
            id=asset_id,
            filename=filename,
            media_type=media_type,
            size=total_bytes,
        )
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@app.post(
    "/api/submissions",
    response_model=SubmissionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_submission(
    payload: SubmissionCreate,
    user: Annotated[sqlite3.Row, Depends(get_current_user)],
) -> SubmissionResponse:
    assets = get_assets(payload.asset_ids, user["id"])
    submission_id = str(uuid4())
    created_at = utc_now()

    with connect_database() as connection:
        connection.execute(
            """
            INSERT INTO submissions (
                id, campaign, audience, instructions, language,
                platforms_json, status, created_at, user_id
            )
            VALUES (?, ?, ?, ?, ?, ?, 'submitted', ?, ?)
            """,
            (
                submission_id,
                payload.campaign,
                payload.audience,
                payload.instructions,
                payload.language,
                json.dumps(payload.platforms),
                created_at,
                user["id"],
            ),
        )
        if payload.asset_ids:
            placeholders = ",".join("?" for _ in payload.asset_ids)
            cursor = connection.execute(
                f"""
                UPDATE assets SET submission_id = ?
                WHERE id IN ({placeholders}) AND submission_id IS NULL
                """,
                [submission_id, *payload.asset_ids],
            )
            if cursor.rowcount != len(payload.asset_ids):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="An uploaded asset was attached by another submission.",
                )

        row = connection.execute(
            "SELECT * FROM submissions WHERE id = ?",
            (submission_id,),
        ).fetchone()

    if row is None:
        raise RuntimeError("The saved submission could not be read back.")
    return submission_from_row(row, assets)


@app.get("/api/submissions", response_model=list[SubmissionResponse])
def list_submissions(
    user: Annotated[sqlite3.Row, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[SubmissionResponse]:
    with connect_database() as connection:
        rows = connection.execute(
            "SELECT * FROM submissions WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user["id"], limit),
        ).fetchall()

        result: list[SubmissionResponse] = []
        for row in rows:
            asset_rows = connection.execute(
                """
                SELECT id, filename, media_type, size
                FROM assets
                WHERE submission_id = ?
                ORDER BY created_at, id
                """,
                (row["id"],),
            ).fetchall()
            assets = [
                AssetResponse(
                    id=asset["id"],
                    filename=asset["filename"],
                    media_type=asset["media_type"],
                    size=asset["size"],
                )
                for asset in asset_rows
            ]
            result.append(submission_from_row(row, assets))

    return result


@app.get("/api/submissions/{submission_id}", response_model=SubmissionResponse)
def read_submission(
    submission_id: str,
    user: Annotated[sqlite3.Row, Depends(get_current_user)],
) -> SubmissionResponse:
    with connect_database() as connection:
        row = connection.execute(
            "SELECT * FROM submissions WHERE id = ? AND user_id = ?",
            (submission_id, user["id"]),
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Submission not found.",
            )

        asset_rows = connection.execute(
            """
            SELECT id, filename, media_type, size
            FROM assets
            WHERE submission_id = ?
            ORDER BY created_at, id
            """,
            (submission_id,),
        ).fetchall()

    assets = [
        AssetResponse(
            id=asset["id"],
            filename=asset["filename"],
            media_type=asset["media_type"],
            size=asset["size"],
        )
        for asset in asset_rows
    ]
    return submission_from_row(row, assets)
