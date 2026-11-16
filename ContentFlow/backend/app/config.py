from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv


def load_backend_environment(env_file: Path | None = None) -> None:
    load_dotenv(
        dotenv_path=env_file or Path(__file__).resolve().parent.parent / ".env",
        override=False,
    )


load_backend_environment()

Platform = Literal["instagram", "facebook", "linkedin", "youtube", "tiktok"]
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 1024 * 1024
SESSION_LIFETIME = timedelta(days=7)
SESSION_COOKIE = "content_flow_session"
ALLOWED_MEDIA_TYPES = ("image/", "video/")

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

def public_api_url() -> str:
    return os.environ.get("CONTENT_FLOW_API_PUBLIC_URL", os.environ.get("RENDER_EXTERNAL_URL", "http://127.0.0.1:8000")).rstrip("/")


def public_frontend_url() -> str:
    return os.environ.get("CONTENT_FLOW_FRONTEND_URL", "http://localhost:3000").rstrip("/")



def env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer.") from error
    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}.")
    return value



def publisher_is_enabled() -> bool:
    value = os.environ.get("CONTENT_FLOW_PUBLISHER_ENABLED", "false").strip().lower()
    if value not in {"true", "false", "1", "0", "yes", "no", "on", "off"}:
        raise RuntimeError("CONTENT_FLOW_PUBLISHER_ENABLED must be a boolean value.")
    return value in {"true", "1", "yes", "on"}


def publisher_interval_seconds() -> int:
    try:
        interval = int(os.environ.get("CONTENT_FLOW_PUBLISHER_INTERVAL_SECONDS", "60"))
    except ValueError as error:
        raise RuntimeError("CONTENT_FLOW_PUBLISHER_INTERVAL_SECONDS must be an integer.") from error
    if interval < 5:
        raise RuntimeError("CONTENT_FLOW_PUBLISHER_INTERVAL_SECONDS must be at least 5.")
    return interval
